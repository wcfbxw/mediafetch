import pytest

from app.services.extractor import SafeYoutubeDL
from app.services.formats import normalize_formats
from app.services.kuaishou import MediaFetchKuaishouIE
from app.services.official_platforms import (
    SUPPORTED_PLATFORM_EXTRACTORS,
    prefer_official_original_formats,
)


@pytest.mark.parametrize(
    ("platform", "extractor_key", "url"),
    [
        ("douyin", "Douyin", "https://www.douyin.com/video/7480123456789012345"),
        ("xiaohongshu", "XiaoHongShu", "https://www.xiaohongshu.com/explore/64b7f1234567890123456789"),
        ("bilibili", "BiliBili", "https://www.bilibili.com/video/BV1xx411c7mD"),
        ("weibo", "WeiboVideo", "https://weibo.com/tv/show/1034:1234567890123456"),
        ("xigua", "Ixigua", "https://www.ixigua.com/1234567890123456"),
        ("youtube", "Youtube", "https://www.youtube.com/watch?v=dQw4w9WgXcQ"),
    ],
)
def test_pinned_ytdlp_has_platform_specific_extractor(platform, extractor_key, url):
    assert extractor_key in SUPPORTED_PLATFORM_EXTRACTORS[platform]
    with SafeYoutubeDL({"quiet": True}) as ydl:
        assert ydl.get_info_extractor(extractor_key).suitable(url)


@pytest.mark.parametrize(
    "url",
    [
        "https://kuaishou.com/abc123",
        "https://v.kuaishou.com/abc123",
        "https://www.kuaishou.com/short-video/abc123",
        "https://v.m.chenzhongtech.com/fw/photo/abc123",
    ],
)
def test_kuaishou_dedicated_extractor_accepts_all_public_landing_hosts(url):
    assert MediaFetchKuaishouIE.suitable(url)


def test_xiaohongshu_official_original_survives_strict_format_normalization():
    original_url = "https://sns-video-bd.xhscdn.com/original-key"
    info = {
        "extractor_key": "XiaoHongShu",
        "formats": [
            {
                "format_id": "h264-hd",
                "url": "https://sns-video-hw.xhscdn.com/rendition.mp4",
                "width": 1080,
                "height": 1920,
                "fps": 30,
                "vcodec": "h264",
                "acodec": "aac",
                "tbr": 2500,
            },
            {
                "format_id": "direct",
                "url": original_url,
                "ext": "mp4",
                "quality": 1,
            },
        ],
    }

    prefer_official_original_formats(info)

    original = info["formats"][1]
    assert original["url"] == original_url
    assert original["width"] == 1080
    assert original["height"] == 1920
    assert original["vcodec"] == "h264"
    assert original["acodec"] == "aac"
    assert original["source_preference"] == 1000
    normalized, _ = normalize_formats(info["formats"], 30)
    assert normalized[0]["id"] == "direct"
    assert normalized[0]["preferred"] is True


def test_non_xiaohongshu_result_is_not_modified():
    info = {
        "extractor_key": "WeiboVideo",
        "formats": [{"format_id": "direct", "url": "https://f.video.weibocdn.com/a.mp4"}],
    }

    prefer_official_original_formats(info)

    assert info["formats"] == [
        {"format_id": "direct", "url": "https://f.video.weibocdn.com/a.mp4"}
    ]
