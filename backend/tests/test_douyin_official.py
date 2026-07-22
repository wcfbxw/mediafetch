import json

import pytest

from app.services.douyin_official import (
    DOUYIN_MOBILE_USER_AGENT,
    OFFICIAL_DOUYIN_FORMAT_ID,
    DouyinOfficialPlaybackUnavailable,
    add_official_playback_format,
    build_official_playback,
    extract_official_douyin_info,
    is_official_share_url,
    parse_router_data,
)


def router_page(video_id: str = "7480123456789012345", uri: str = "v0200-test-playback") -> str:
    payload = {
        "loaderData": {
            f"video_{video_id}/page": {
                "videoInfoRes": {
                    "item_list": [
                        {
                            "aweme_id": video_id,
                            "desc": "fixture",
                            "video": {
                                "width": 1080,
                                "height": 1920,
                                "duration": 25_400,
                                "play_addr": {"uri": uri},
                            },
                        }
                    ]
                }
            }
        }
    }
    return (
        "<html><script>window._ROUTER_DATA = "
        + json.dumps(payload, ensure_ascii=False)
        + ";</script></html>"
    )


def test_router_data_parser_handles_braces_inside_json_strings():
    page = router_page().replace('"fixture"', '"fixture } text"')

    parsed = parse_router_data(page)

    assert "loaderData" in parsed


def test_only_fixed_iesdouyin_share_page_is_treated_as_direct_official_source():
    assert is_official_share_url("https://www.iesdouyin.com/share/video/7480123456789012345")
    assert not is_official_share_url("https://www.douyin.com/video/7480123456789012345")
    assert not is_official_share_url(
        "https://www.iesdouyin.com.evil.example/share/video/7480123456789012345"
    )


def test_builds_fixed_host_official_playback_candidate():
    video_id = "7480123456789012345"

    raw_format, internal = build_official_playback(
        f"https://www.douyin.com/video/{video_id}",
        {"id": video_id},
        router_page(video_id, "video uri/with+characters"),
    )

    assert raw_format["format_id"] == OFFICIAL_DOUYIN_FORMAT_ID
    assert raw_format["width"] == 1080
    assert raw_format["height"] == 1920
    assert raw_format["url"].startswith("https://www.iesdouyin.com/aweme/v1/play/?")
    assert "video_id=video+uri%2Fwith%2Bcharacters" in raw_format["url"]
    assert "/playwm/" not in raw_format["url"]
    assert internal["http_headers"]["User-Agent"] == DOUYIN_MOBILE_USER_AGENT


def test_rejects_page_without_official_playback_uri():
    page = '<script>window._ROUTER_DATA={"loaderData": {}};</script>'

    with pytest.raises(DouyinOfficialPlaybackUnavailable):
        build_official_playback(
            "https://www.douyin.com/video/7480123456789012345",
            {},
            page,
        )


def test_appends_candidate_and_keeps_media_url_internal():
    video_id = "7480123456789012345"

    class Response:
        def read(self, limit):
            assert limit == 10_000_001
            return router_page(video_id).encode()

        def close(self):
            return None

    class YDL:
        def urlopen(self, url):
            assert url == f"https://www.iesdouyin.com/share/video/{video_id}"
            return Response()

    info = {
        "id": video_id,
        "webpage_url": f"https://www.douyin.com/video/{video_id}",
        "formats": [{"format_id": "existing", "url": "https://cdn.example/video.mp4"}],
    }

    assert add_official_playback_format(YDL(), info["webpage_url"], info) is True
    assert [item["format_id"] for item in info["formats"]] == [
        "existing",
        OFFICIAL_DOUYIN_FORMAT_ID,
    ]
    assert info["_mediafetch_direct_formats"][OFFICIAL_DOUYIN_FORMAT_ID]["url"].startswith(
        "https://www.iesdouyin.com/aweme/v1/play/"
    )


def test_builds_complete_fallback_result_when_ytdlp_does_not_support_share_page():
    video_id = "7480123456789012345"

    class Response:
        def read(self, limit):
            return router_page(video_id).encode()

        def close(self):
            return None

    class YDL:
        def urlopen(self, url):
            return Response()

    info = extract_official_douyin_info(
        YDL(),
        f"https://www.iesdouyin.com/share/video/{video_id}?tracking=removed",
    )

    assert info["id"] == video_id
    assert info["title"] == "fixture"
    assert info["duration"] == 25.4
    assert info["extractor_key"] == "MediaFetchDouyinOfficial"
    assert info["webpage_url"] == f"https://www.iesdouyin.com/share/video/{video_id}"
    assert info["formats"][0]["format_id"] == OFFICIAL_DOUYIN_FORMAT_ID
