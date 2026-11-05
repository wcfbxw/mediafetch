import io
import json
from pathlib import Path

from yt_dlp.networking.common import Response

from app.core import security
from app.services import downloader, extractor
from app.services.extractor import SafeUrllibRH
from app.services.jobs import default_job_state, save_new_job
from app.services.platform_credentials import platform_cookie_file, save_platform_cookie_file


def test_xiaohongshu_parse_and_download_use_imported_session_with_existing_extractor(
    monkeypatch, redis_client, tmp_path
):
    note_id = "64b7f1234567890123456789"
    source_url = f"https://www.xiaohongshu.com/explore/{note_id}"
    media_url = "https://sns-video-bd.xhscdn.com/test-original.mp4"
    payload = b"synthetic-media-payload"
    note = {
        "title": "Synthetic Xiaohongshu note",
        "user": {"userId": "test-user"},
        "video": {
            "consumer": {"originVideoKey": "test-original.mp4"},
            "media": {
                "stream": {
                    "h264": [
                        {
                            "masterUrl": "https://sns-video-hw.xhscdn.com/test-rendition.mp4",
                            "width": 720,
                            "height": 1280,
                            "videoCodec": "h264",
                            "audioCodec": "aac",
                            "qualityType": "HD",
                            "duration": 1000,
                        }
                    ],
                },
            },
        },
    }
    state = {"note": {"noteDetailMap": {note_id: {"note": note}}}}
    page = (
        "<html><script>window.__INITIAL_STATE__=" + json.dumps(state) + ";</script></html>"
    ).encode()
    save_platform_cookie_file(
        "xiaohongshu",
        b"# Netscape HTTP Cookie File\n"
        b".xiaohongshu.com\tTRUE\t/\tTRUE\t4102444800\tweb_session\ttest-only\n",
    )
    managed = platform_cookie_file("xiaohongshu")
    original = managed.read_bytes()
    requests: list[tuple[str, set[str]]] = []
    snapshots: set[Path] = set()

    def send(handler, request):
        jar = handler._get_cookiejar(request)
        snapshot = Path(jar.filename)
        assert snapshot != managed and snapshot.is_file()
        snapshots.add(snapshot)
        names = {cookie.name for cookie in jar.get_cookies_for_url(request.url)}
        requests.append((request.url, names))
        if request.url == source_url:
            assert names == {"web_session"}
            body, content_type = page, "text/html; charset=utf-8"
        else:
            assert request.url == media_url
            assert not names
            body, content_type = payload, "video/mp4"
        return Response(
            io.BytesIO(body),
            request.url,
            {"Content-Type": content_type, "Content-Length": str(len(body))},
        )

    monkeypatch.setattr(security, "_resolved_addresses", lambda _host, _port: {"8.8.8.8"})
    monkeypatch.setattr(SafeUrllibRH, "_send", send)

    info = extractor._extract_sync(source_url)

    assert info["extractor_key"] == "XiaoHongShu"
    assert info["title"] == note["title"]
    assert info["formats"][-1]["format_id"] == "direct"
    assert info["formats"][-1]["width"] == 720
    assert snapshots and all(not snapshot.exists() for snapshot in snapshots)
    requests.clear()
    save_new_job(redis_client, default_job_state("xiaohongshu-test"))
    context = downloader.DownloadContext(redis_client, "xiaohongshu-test", {})

    output = downloader._download_track(
        context,
        url=source_url,
        format_id="direct",
        temp_dir=tmp_path,
        prefix="video",
        status="downloading_video",
        progress_start=1,
        progress_span=90,
        message="downloading",
    )

    assert output.read_bytes() == payload
    assert (source_url, {"web_session"}) in requests
    assert (media_url, set()) in requests
    assert len(snapshots) == 2
    assert all(not snapshot.exists() for snapshot in snapshots)
    assert managed.read_bytes() == original
