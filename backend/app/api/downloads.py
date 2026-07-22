import asyncio
import json
import logging
import secrets
from typing import cast

from fastapi import APIRouter, Request, Response
from fastapi.responses import FileResponse
from redis import Redis
from rq import Queue

from app.core.config import get_settings
from app.core.errors import AppError, error
from app.core.redis import get_async_redis, get_redis, get_rq_redis
from app.core.security import enforce_rate_limit, get_client_ip
from app.models.requests import DownloadRequest
from app.models.responses import CreateDownloadResponse
from app.services.file_tokens import (
    content_disposition,
    internal_download_uri,
    validate_file_token,
)
from app.services.formats import choose_audio_format, find_format
from app.services.jobs import (
    default_job_state,
    release_client_slot,
    reserve_client_slot,
    save_new_job,
)
from app.services.postprocess import PostprocessPreset, resolve_postprocess_preset
from app.workers.tasks import run_download_job

logger = logging.getLogger(__name__)
router = APIRouter(tags=["downloads"])


def _create_download(
    redis_client: Redis,
    payload: DownloadRequest,
    client_ip: str,
) -> CreateDownloadResponse:
    settings = get_settings()
    encoded = cast(str | None, redis_client.get(f"inspect:{payload.inspect_id}"))
    if not encoded:
        raise error("FORMAT_EXPIRED")
    inspection = json.loads(encoded)
    all_primary = inspection.get("formats", []) + inspection.get("audio_formats", [])
    selected = find_format(all_primary, payload.video_format_id)

    if selected["has_video"] and payload.output_container in {"original", "m4a", "mp3"}:
        raise error("FORMAT_NOT_FOUND", message="视频格式不能输出为所选音频容器")
    if not selected["has_video"] and payload.output_container not in {"original", "m4a", "mp3"}:
        raise error("FORMAT_NOT_FOUND", message="仅音频格式请选择原始音频、M4A 或 MP3")

    audio = None
    if selected["has_video"] and not selected["has_audio"]:
        if payload.audio_format_id:
            audio = find_format(inspection.get("audio_formats", []), payload.audio_format_id)
        else:
            audio = choose_audio_format(inspection.get("audio_formats", []), selected)
    elif payload.audio_format_id:
        raise error("FORMAT_NOT_FOUND", message="当前格式已包含音频，无需额外选择音频轨")

    estimated_size = sum(
        item.get("estimated_size") or 0 for item in (selected, audio) if item is not None
    )
    if estimated_size and estimated_size > settings.max_file_size_bytes:
        raise error("FILE_TOO_LARGE")

    duration = inspection.get("duration")
    if duration and duration > settings.max_duration_seconds:
        raise error("VIDEO_TOO_LONG")

    queue = Queue("mediafetch", connection=get_rq_redis())
    if queue.count >= settings.max_queue_size:
        raise error("QUEUE_FULL")

    job_id = secrets.token_urlsafe(24)
    postprocess_preset = resolve_postprocess_preset(
        payload.postprocess_preset,
        legacy_compatibility_mode=payload.compatibility_mode,
    )
    reserve_client_slot(redis_client, client_ip, job_id)
    state = default_job_state(job_id)
    task_payload = {
        "source_url": inspection["_source_url"],
        "title": inspection["title"],
        "video_format": selected,
        "audio_format": audio,
        "output_container": payload.output_container,
        "postprocess_preset": postprocess_preset.value,
        # Retained for workers that were already running during a rolling upgrade.
        "compatibility_mode": postprocess_preset is PostprocessPreset.TRANSCODE,
        "duration": duration,
        "client_ip": client_ip,
    }
    try:
        save_new_job(redis_client, state)
        redis_client.setex(
            f"job-payload:{job_id}",
            settings.job_ttl_seconds,
            json.dumps(task_payload, ensure_ascii=False, separators=(",", ":")),
        )
        redis_client.setex(
            f"job-owner:{job_id}",
            settings.job_ttl_seconds,
            client_ip,
        )
        queue.enqueue(
            run_download_job,
            job_id,
            job_id=job_id,
            job_timeout=settings.download_timeout_seconds + settings.ffmpeg_timeout_seconds + 300,
            result_ttl=settings.job_ttl_seconds,
            failure_ttl=settings.job_ttl_seconds,
        )
    except AppError:
        release_client_slot(redis_client, client_ip, job_id)
        redis_client.delete(
            f"job:{job_id}",
            f"job-payload:{job_id}",
            f"job-owner:{job_id}",
        )
        raise
    except Exception as exc:
        release_client_slot(redis_client, client_ip, job_id)
        redis_client.delete(
            f"job:{job_id}",
            f"job-payload:{job_id}",
            f"job-owner:{job_id}",
        )
        logger.exception("Failed to enqueue job_id=%s", job_id)
        raise error("QUEUE_FULL") from exc
    return CreateDownloadResponse(job_id=job_id, status="queued")


@router.post("/downloads", response_model=CreateDownloadResponse, status_code=202)
async def create_download(
    payload: DownloadRequest,
    request: Request,
) -> CreateDownloadResponse:
    settings = get_settings()
    client_ip = get_client_ip(request)
    await enforce_rate_limit(
        get_async_redis(),
        client_ip=client_ip,
        scope="download",
        limit=settings.rate_limit_download_per_minute,
    )
    return await asyncio.to_thread(_create_download, get_redis(), payload, client_ip)


@router.get("/files/{token}")
async def download_file(token: str) -> Response:
    payload = await asyncio.to_thread(validate_file_token, get_redis(), token)
    if not get_settings().x_accel_redirect_enabled:
        return FileResponse(
            path=payload["path"],
            filename=payload["filename"],
            media_type="application/octet-stream",
            headers={"Cache-Control": "private, no-store"},
        )
    headers = {
        "X-Accel-Redirect": internal_download_uri(payload["relative_path"]),
        "Content-Disposition": content_disposition(payload["filename"]),
        "Content-Type": "application/octet-stream",
        "Accept-Ranges": "bytes",
        "Cache-Control": "private, no-store",
    }
    response = Response(status_code=200, headers=headers)
    # Nginx calculates the final file length (and Range length) after the
    # internal redirect. Advertising the full file length on this empty
    # upstream response makes ASGI correctly report a short response body.
    del response.headers["content-length"]
    return response
