import pytest
from pydantic import ValidationError

from app.models.requests import InspectRequest


def test_inspect_request_accepts_plain_url():
    assert InspectRequest(url="  https://example.com/video  ").url == "https://example.com/video"


def test_inspect_request_extracts_url_from_platform_share_text():
    request = InspectRequest(
        url="【第1集：外卖小哥穿越修仙世界，变成了一头猪-哔哩哔哩】 https://b23.tv/V6TfblR"
    )
    assert request.url == "https://b23.tv/V6TfblR"


def test_inspect_request_removes_trailing_chinese_punctuation():
    assert InspectRequest(url="视频地址：https://example.com/watch?v=1。").url == (
        "https://example.com/watch?v=1"
    )


@pytest.mark.parametrize("value", ["只有标题", "ftp://example.com/video", "file:///etc/passwd"])
def test_inspect_request_rejects_text_without_http_url(value: str):
    with pytest.raises(ValidationError):
        InspectRequest(url=value)
