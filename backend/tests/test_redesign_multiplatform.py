import io
import json
import zipfile

import fakeredis
import httpx
import pytest
from fastapi.testclient import TestClient

from app.core import security
from app.core.config import Settings, get_settings, is_domestic_url
from app.core.errors import AppError
from app.services import stream_tokens
from app.services.clean_extractors import (
    MediaFetchPipixiaIE,
    select_playlist_or_multipart_entry,
)
from app.services.douyin_official import extract_official_douyin_info
from app.services.formats import (
    clean_watermark_url,
    is_watermarked_format,
    normalize_formats,
)
from app.services.kuaishou import extract_kuaishou_state
from app.services.platform_credentials import (
    configure_ytdlp_credentials,
    save_platform_cookie_file,
)
from app.services.xiaohongshu import extract_xiaohongshu_note_from_html


def test_watermark_filter_strips_watermarked_streams_and_keeps_clean():
    raw = [
        {
            "format_id": "download_addr-0",
            "format_note": "watermarked",
            "url": "https://v16.tiktokcdn.com/video/tos/watermarked.mp4",
            "protocol": "https",
            "ext": "mp4",
            "width": 1080,
            "height": 1920,
            "vcodec": "h264",
            "acodec": "aac",
            "tbr": 4500,
        },
        {
            "format_id": "play_addr-0",
            "format_note": "Direct video (no watermark)",
            "url": "https://v16.tiktokcdn.com/video/tos/clean.mp4",
            "protocol": "https",
            "ext": "mp4",
            "width": 1080,
            "height": 1920,
            "vcodec": "h264",
            "acodec": "aac",
            "tbr": 2800,
        },
    ]
    video, _ = normalize_formats(raw, 20)
    assert [item["id"] for item in video] == ["play_addr-0"]
    assert video[0]["watermark_free"] is True
    assert video[0]["delivery_mode"] == "stream"


def test_watermark_only_formats_are_rejected():
    raw = [
        {
            "format_id": "wm-only",
            "format_note": "watermarked preview",
            "url": "https://cdn.example/video.mp4?watermark=1",
            "protocol": "https",
            "ext": "mp4",
            "width": 720,
            "height": 1280,
            "vcodec": "h264",
            "acodec": "aac",
        }
    ]
    with pytest.raises(AppError) as caught:
        normalize_formats(raw, 15)
    assert caught.value.code == "WATERMARKED_ONLY"


def test_douyin_playwm_url_is_rewritten_to_clean_play():
    dirty = "https://www.iesdouyin.com/aweme/v1/playwm/?video_id=v0200fg1&ratio=1080p"
    cleaned = clean_watermark_url(dirty)
    assert "/playwm/" not in cleaned
    assert "/play/" in cleaned
    assert not is_watermarked_format({"format_id": "clean", "url": cleaned})


def test_dual_proxy_routing_separates_cn_and_global_platforms():
    settings = Settings(
        token_secret="x" * 36,
        cn_proxy_url="http://127.0.0.1:7890",
        global_proxy_url="http://127.0.0.1:7891",
        ytdlp_proxy="http://127.0.0.1:9999",
    )
    assert is_domestic_url("https://www.douyin.com/video/123")
    assert is_domestic_url("https://www.xiaohongshu.com/explore/64b7f1234567890123456789")
    assert not is_domestic_url("https://www.youtube.com/watch?v=dQw4w9WgXcQ")
    assert not is_domestic_url("https://www.tiktok.com/@user/video/123")

    assert settings.proxy_for_url("https://www.douyin.com/video/123") == "http://127.0.0.1:7890"
    assert settings.proxy_for_url("https://x.com/user/status/123") == "http://127.0.0.1:7891"


def test_xiaohongshu_clean_video_and_gallery_extraction():
    video_html = (
        "<script>window.__INITIAL_STATE__="
        '{"note":{"noteDetailMap":{"64b7f1234567890123456789":{"note":{'
        '"noteId":"64b7f1234567890123456789","type":"video","title":"小红书无水印视频",'
        '"user":{"nickname":"测试作者"},'
        '"imageList":[{"traceId":"1040g00831abcde123456789"}],'
        '"video":{"capa":{"duration":18},"consumer":{"originVideoKey":"spectrum/clean_master_key"},'
        '"media":{"stream":{"h264":[{"masterUrl":"http://sns-video-hw.xhscdn.com/stream_hd.mp4",'
        '"width":1080,"height":1920,"fps":30,"videoBitrate":3200000}],"h265":undefined}}}'
        "}}}}}</script>"
    )
    video_info = extract_xiaohongshu_note_from_html(
        video_html,
        "https://www.xiaohongshu.com/explore/64b7f1234567890123456789",
    )
    assert video_info["title"] == "小红书无水印视频"
    assert video_info["_mediafetch_gallery"] == []
    normalized, _ = normalize_formats(video_info["formats"], 18)
    assert normalized[0]["id"] == "xhs-origin-master"
    assert normalized[0]["watermark_free"] is True
    assert normalized[0]["delivery_mode"] == "stream"

    gallery_html = (
        "<script>window.__INITIAL_STATE__="
        '{"note":{"noteDetailMap":{"64b7f1234567890123456780":{"note":{'
        '"noteId":"64b7f1234567890123456780","type":"normal","title":"小红书实况图集",'
        '"user":{"nickname":"摄影师"},'
        '"imageList":['
        '{"traceId":"1040g00831cleanimg000001","width":1440,"height":1920,'
        '"stream":{"h264":[{"masterUrl":"https://sns-video-bd.xhscdn.com/live_clip.mp4"}]}},'
        '{"urlDefault":"http://sns-webpic-qc.xhscdn.com/2026/abc/img2!nd_dft_wlteh_webp_3","width":1080,"height":1440}'
        "]}}}}}</script>"
    )
    gallery_info = extract_xiaohongshu_note_from_html(
        gallery_html,
        "https://www.xiaohongshu.com/explore/64b7f1234567890123456780",
    )
    assert gallery_info["formats"] == []
    gallery = gallery_info["_mediafetch_gallery"]
    assert len(gallery) == 2
    assert gallery[0]["url"] == (
        "https://sns-img-bd.xhscdn.com/1040g00831cleanimg000001?imageView2/2/w/format/png"
    )
    assert gallery[0]["live_video_url"] == "https://sns-video-bd.xhscdn.com/live_clip.mp4"
    assert "!" not in gallery[1]["url"]


def test_douyin_gallery_note_and_kuaishou_atlas_extraction():
    douyin_id = "7480999999999999999"
    douyin_payload = {
        "loaderData": {
            f"note_{douyin_id}/page": {
                "videoInfoRes": {
                    "item_list": [
                        {
                            "aweme_id": douyin_id,
                            "desc": "抖音无水印图文",
                            "author": {"nickname": "图文作者"},
                            "images": [
                                {
                                    "width": 1080,
                                    "height": 1440,
                                    "url_list": [
                                        "https://p3-sign.douyinpic.com/img1~watermark.webp",
                                        "https://p3-sign.douyinpic.com/tos-cn-i/clean_img1.jpeg",
                                    ],
                                }
                            ],
                        }
                    ]
                }
            }
        }
    }
    page = f"<script>window._ROUTER_DATA = {json.dumps(douyin_payload)};</script>"

    class DummyResp:
        def read(self, _limit):
            return page.encode("utf-8")

        def close(self):
            return None

    class DummyYDL:
        def urlopen(self, _url):
            return DummyResp()

    info = extract_official_douyin_info(
        DummyYDL(),
        f"https://www.iesdouyin.com/share/note/{douyin_id}",
    )
    assert len(info["_mediafetch_gallery"]) == 1
    assert info["_mediafetch_gallery"][0]["url"].endswith("clean_img1.jpeg")

    ks_state = {
        "tusjoh": {
            "photo": {
                "photoId": "ks-atlas-1",
                "caption": "快手无水印图集",
                "userName": "快手创作者",
                "ext_params": {
                    "atlas": {
                        "cdn": ["tx2.a.kwimgs.com"],
                        "list": ["/ufile/atlas/img_01.webp", "/ufile/atlas/img_02.webp"],
                    }
                },
            }
        }
    }
    ks_res = extract_kuaishou_state(ks_state, "https://v.kuaishou.com/abc")
    assert len(ks_res["_mediafetch_gallery"]) == 2
    assert ks_res["_mediafetch_gallery"][0]["url"] == "https://tx2.a.kwimgs.com/ufile/atlas/img_01.webp"


def test_pipixia_suitable_and_multipart_selection():
    assert MediaFetchPipixiaIE.suitable("https://h5.pipixia.com/item/7391234567890123456")
    assert MediaFetchPipixiaIE.suitable("https://h5.pipixia.com/s/iABC123/")

    bili_playlist = {
        "_type": "multi_video",
        "title": "合集总标题",
        "entries": [
            {"id": "p1", "title": "第一集", "formats": [{"format_id": "1"}]},
            {"id": "p2", "title": "第二集", "formats": [{"format_id": "2"}]},
        ],
    }
    chosen = select_playlist_or_multipart_entry(
        bili_playlist,
        "https://www.bilibili.com/video/BV1xx411c7mD?p=2",
    )
    assert chosen is not None
    assert chosen["id"] == "p2"


def test_expanded_operator_cookies_and_youtube_po_token(test_settings, monkeypatch):
    monkeypatch.setattr(test_settings, "youtube_po_token", "web+test_po_token_value")
    yt_opts: dict = {}
    configure_ytdlp_credentials(yt_opts, "https://www.youtube.com/watch?v=dQw4w9WgXcQ")
    assert yt_opts["extractor_args"]["youtube"]["po_token"] == ["web+test_po_token_value"]

    tiktok_cookie = (
        b"# Netscape HTTP Cookie File\n"
        b".tiktok.com\tTRUE\t/\tTRUE\t4102444800\tsessionid\ttiktok-secret\n"
    )
    status = save_platform_cookie_file("tiktok", tiktok_cookie)
    assert status["configured"] is True
    tk_opts: dict = {}
    configure_ytdlp_credentials(tk_opts, "https://www.tiktok.com/@creator/video/12345")
    assert "tiktok-cookies.txt" in tk_opts["cookiefile"]


def test_zero_disk_streaming_proxy_and_gallery_zip(test_settings, monkeypatch):
    from app.main import app

    fake_redis = fakeredis.FakeRedis(decode_responses=True)
    monkeypatch.setattr("app.api.stream.get_redis", lambda: fake_redis)
    monkeypatch.setattr(security, "_resolved_addresses", lambda _host, _port: {"8.8.8.8"})

    video_bytes = b"0123456789abcdefCLEAN_MP4_STREAM"

    def mock_handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "iesdouyin.example":
            return httpx.Response(302, headers={"Location": "https://cdn.example/clean.mp4"})
        if request.url.path == "/private-redirect":
            return httpx.Response(302, headers={"Location": "http://127.0.0.1/secret"})
        if request.url.path == "/img1.jpg":
            return httpx.Response(200, content=b"JPEG_ONE", headers={"Content-Type": "image/jpeg"})
        if request.url.path == "/img2.png":
            return httpx.Response(200, content=b"PNG_TWO", headers={"Content-Type": "image/png"})
        range_hdr = request.headers.get("Range")
        if range_hdr == "bytes=0-9":
            return httpx.Response(
                206,
                content=video_bytes[:10],
                headers={
                    "Content-Type": "video/mp4",
                    "Content-Length": "10",
                    "Content-Range": f"bytes 0-9/{len(video_bytes)}",
                },
            )
        return httpx.Response(
            200,
            content=video_bytes,
            headers={
                "Content-Type": "video/mp4",
                "Content-Length": str(len(video_bytes)),
            },
        )

    monkeypatch.setattr(
        "app.api.stream._build_client",
        lambda _url, timeout_seconds=60.0: httpx.AsyncClient(
            transport=httpx.MockTransport(mock_handler),
            timeout=timeout_seconds,
            follow_redirects=False,
        ),
    )

    token = stream_tokens.create_stream_token(
        fake_redis,
        url="https://iesdouyin.example/aweme/v1/play/?video_id=clean",
        filename="无水印测试视频.mp4",
        media_type="video/mp4",
        source_url="https://www.douyin.com/video/123",
        http_headers={"Referer": "https://www.douyin.com/"},
    )

    client = TestClient(app)
    full_resp = client.get(f"/api/v1/stream/{token}")
    assert full_resp.status_code == 200
    assert full_resp.content == video_bytes
    assert "attachment;" in full_resp.headers["content-disposition"]

    range_resp = client.get(f"/api/v1/stream/{token}", headers={"Range": "bytes=0-9"})
    assert range_resp.status_code == 206
    assert range_resp.content == b"0123456789"
    assert range_resp.headers["content-range"] == f"bytes 0-9/{len(video_bytes)}"

    # Verify SSRF protection blocks upstream redirect to 127.0.0.1
    ssrf_token = stream_tokens.create_stream_token(
        fake_redis,
        url="https://public.example/private-redirect",
        filename="bad.mp4",
        media_type="video/mp4",
        source_url="https://public.example/private-redirect",
    )
    blocked_resp = client.get(f"/api/v1/stream/{ssrf_token}")
    assert blocked_resp.status_code == 400
    assert blocked_resp.json()["error"]["code"] == "BLOCKED_ADDRESS"

    # Verify Gallery ZIP packaging
    zip_token = stream_tokens.create_gallery_zip_token(
        fake_redis,
        title="旅行图集",
        source_url="https://www.xiaohongshu.com/explore/123",
        items=[
            {"url": "https://cdn.example/img1.jpg", "extension": "jpg", "http_headers": {}},
            {"url": "https://cdn.example/img2.png", "extension": "png", "http_headers": {}},
        ],
    )
    zip_resp = client.get(f"/api/v1/gallery/{zip_token}")
    assert zip_resp.status_code == 200
    assert zip_resp.headers["content-type"] == "application/zip"
    with zipfile.ZipFile(io.BytesIO(zip_resp.content)) as zf:
        names = zf.namelist()
        assert names == ["旅行图集_01.jpg", "旅行图集_02.png"]
        assert zf.read("旅行图集_01.jpg") == b"JPEG_ONE"
        assert zf.read("旅行图集_02.png") == b"PNG_TWO"


def test_optional_access_token_gate(test_settings, monkeypatch):
    from app.main import app

    settings = get_settings()
    monkeypatch.setattr(settings, "access_token", "my-private-passcode")
    client = TestClient(app)

    cfg = client.get("/api/v1/auth/config")
    assert cfg.status_code == 200
    assert cfg.json() == {"access_token_required": True}

    denied = client.post("/api/v1/inspect", json={"url": "https://example.com/video"})
    assert denied.status_code == 401
    assert denied.json()["error"]["code"] == "ACCESS_UNAUTHORIZED"


def test_curl_cffi_impersonation_is_active_and_blocks_private_redirects(
    test_settings, monkeypatch
):
    from yt_dlp.networking.impersonate import ImpersonateTarget

    from app.services.extractor import (
        SafeYoutubeDL,
        _curl_cffi_available,
        _wrap_safe_curl_session,
    )

    assert _curl_cffi_available() is True
    with SafeYoutubeDL(
        {"quiet": True, "impersonate": ImpersonateTarget.from_str("chrome")}
    ) as ydl:
        handler_names = {h.RH_NAME for h in ydl._request_director.handlers.values()}
        assert handler_names == {"safe-curl_cffi", "safe-urllib"}

    monkeypatch.setattr(security, "_resolved_addresses", lambda _host, _port: {"8.8.8.8"})

    class FakeResp:
        status_code = 302
        headers = {"location": "http://127.0.0.1:8080/internal"}

        def close(self):
            return None

    class FakeSession:
        def request(self, **_kwargs):
            return FakeResp()

    wrapped = _wrap_safe_curl_session(FakeSession())
    with pytest.raises(AppError) as caught:
        wrapped.request(method="GET", url="https://public.example/video")
    assert caught.value.code == "BLOCKED_ADDRESS"
