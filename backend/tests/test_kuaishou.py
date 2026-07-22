import pytest
from yt_dlp.utils import ExtractorError

from app.services.kuaishou import extract_kuaishou_state


def kuaishou_state() -> dict:
    return {
        "obfuscated-cache-key": {
            "photo": {
                "photoType": "VIDEO",
                "photoId": "photo-123",
                "caption": "A public work",
                "userName": "Creator",
                "duration": 12_345,
                "coverUrls": [{"url": "https://img.example.com/cover.jpg"}],
                "manifest": {
                    "adaptationSet": [
                        {
                            "representation": [
                                {
                                    "id": 3,
                                    "url": "https://media.example.com/video.mp4",
                                    "qualityLabel": "1080p",
                                    "width": 1080,
                                    "height": 1920,
                                    "frameRate": 30,
                                    "avgBitrate": 1050,
                                    "fileSize": 9_519_531,
                                    "videoCodec": "hevc",
                                }
                            ]
                        }
                    ]
                },
            }
        }
    }


def test_kuaishou_public_state_is_normalized_without_exposing_page_state():
    result = extract_kuaishou_state(
        kuaishou_state(),
        "https://www.kuaishou.com/short-video/photo-123",
    )

    assert result["id"] == "photo-123"
    assert result["title"] == "A public work"
    assert result["uploader"] == "Creator"
    assert result["duration"] == pytest.approx(12.345)
    assert result["thumbnail"] == "https://img.example.com/cover.jpg"
    assert result["formats"] == [
        {
            "format_id": "ks-3-hevc",
            "format_note": "1080p",
            "url": "https://media.example.com/video.mp4",
            "ext": "mp4",
            "protocol": "https",
            "width": 1080,
            "height": 1920,
            "fps": 30,
            "tbr": 1050,
            "filesize": 9_519_531,
            "vcodec": "hevc",
            "acodec": "aac",
            "http_headers": result["formats"][0]["http_headers"],
        }
    ]
    assert "User-Agent" in result["formats"][0]["http_headers"]


def test_kuaishou_missing_video_data_is_rejected():
    with pytest.raises(ExtractorError):
        extract_kuaishou_state({"unrelated": True}, "https://www.kuaishou.com/short-video/x")
