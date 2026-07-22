from typing import cast

import pytest
from fastapi import Request

from app.api.convenience import _select_quick_video, quick_download
from app.core.errors import AppError
from app.models.requests import ParseRequest, QuickDownloadRequest
from app.models.responses import MediaFormat, ParseResponse


def make_format(identifier: str, height: int, *, preferred: bool) -> MediaFormat:
    return MediaFormat(
        id=identifier,
        label=f"{height}P",
        width=height * 16 // 9,
        height=height,
        extension="mp4",
        video_codec="h264",
        audio_codec="aac",
        has_video=True,
        has_audio=True,
        requires_merge=False,
        preferred=preferred,
    )


def test_parse_request_extracts_url_from_share_text():
    payload = ParseRequest(
        share_text="7.89 abc:/ 复制打开抖音 https://v.douyin.com/example/ 更多文案"
    )
    assert payload.share_text == "https://v.douyin.com/example/"


def test_quick_download_prefers_normalized_1080p_or_lower():
    selected = _select_quick_video(
        [
            make_format("2160", 2160, preferred=True),
            make_format("1080", 1080, preferred=True),
            make_format("720", 720, preferred=True),
        ]
    )
    assert selected.id == "1080"


@pytest.mark.asyncio
async def test_quick_download_rejects_watermark_crop_before_network_access():
    payload = QuickDownloadRequest(
        share_text="https://example.com/video",
        apply_ffmpeg_crop=True,
    )
    with pytest.raises(AppError) as caught:
        await quick_download(payload, cast(Request, None))
    assert caught.value.code == "WATERMARK_REMOVAL_NOT_SUPPORTED"


def test_parse_response_never_exposes_media_url_or_file_path():
    response = ParseResponse(
        inspect_id="inspect-id",
        title="title",
        platform="Example",
        formats=[make_format("720", 720, preferred=True)],
        audio_formats=[],
    )
    payload = response.model_dump()
    assert "video_url" not in payload
    assert "file_path" not in payload


def test_convenience_routes_are_registered():
    from app.main import app

    paths = {route.path for route in app.routes}
    assert "/api/v1/parse" in paths
    assert "/api/v1/download" in paths
