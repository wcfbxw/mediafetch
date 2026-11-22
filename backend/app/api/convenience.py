import asyncio

from fastapi import APIRouter, Request

from app.api.downloads import _create_download
from app.core.access import require_access_token
from app.core.config import get_settings
from app.core.errors import error
from app.core.redis import get_async_redis, get_redis
from app.core.security import enforce_rate_limit, get_client_ip
from app.models.requests import DownloadRequest, ParseRequest, QuickDownloadRequest
from app.models.responses import (
    MediaFormat,
    ParseResponse,
    QuickDownloadResponse,
)
from app.services.extractor import inspect_media

router = APIRouter(tags=["convenience"])


def _public_parse_response(inspection) -> ParseResponse:
    return ParseResponse(
        inspect_id=inspection.inspect_id,
        title=inspection.title,
        cover_url=inspection.thumbnail,
        duration=inspection.duration,
        uploader=inspection.uploader,
        platform=inspection.platform,
        engine=inspection.engine,
        media_type=inspection.media_type,
        watermark_free=inspection.watermark_free,
        parser_hook=inspection.parser_hook,
        formats=inspection.formats,
        audio_formats=inspection.audio_formats,
        gallery=inspection.gallery,
        gallery_zip_url=inspection.gallery_zip_url,
    )


def _select_quick_video(formats: list[MediaFormat]) -> MediaFormat:
    video_formats = [item for item in formats if item.has_video]
    if not video_formats:
        raise error("NO_FORMATS")
    preferred = [item for item in video_formats if item.preferred]
    candidates = preferred or video_formats
    return next((item for item in candidates if (item.height or 0) <= 1080), candidates[0])


@router.post("/parse", response_model=ParseResponse)
async def parse_share_text(payload: ParseRequest, request: Request) -> ParseResponse:
    require_access_token(request)
    settings = get_settings()
    await enforce_rate_limit(
        get_async_redis(),
        client_ip=get_client_ip(request),
        scope="inspect",
        limit=settings.rate_limit_inspect_per_minute,
    )
    inspection = await inspect_media(payload.share_text, get_redis())
    return _public_parse_response(inspection)


@router.post(
    "/download",
    response_model=QuickDownloadResponse,
    status_code=202,
)
async def quick_download(
    payload: QuickDownloadRequest,
    request: Request,
) -> QuickDownloadResponse:
    if payload.apply_ffmpeg_crop:
        raise error("WATERMARK_REMOVAL_NOT_SUPPORTED")

    require_access_token(request)
    settings = get_settings()
    client_ip = get_client_ip(request)
    await enforce_rate_limit(
        get_async_redis(),
        client_ip=client_ip,
        scope="download",
        limit=settings.rate_limit_download_per_minute,
    )
    inspection = await inspect_media(payload.share_text, get_redis())
    selected = _select_quick_video(inspection.formats)
    created = await asyncio.to_thread(
        _create_download,
        get_redis(),
        DownloadRequest(
            inspect_id=inspection.inspect_id,
            video_format_id=selected.id,
            audio_format_id=None,
            output_container=payload.output_container,
            postprocess_preset=payload.postprocess_preset,
            compatibility_mode=payload.compatibility_mode,
        ),
        client_ip,
    )
    return QuickDownloadResponse(job_id=created.job_id, status=created.status)
