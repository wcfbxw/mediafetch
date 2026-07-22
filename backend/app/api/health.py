import shutil

from fastapi import APIRouter
from yt_dlp.version import __version__ as ytdlp_version

from app.core.redis import get_async_redis
from app.models.responses import HealthResponse

router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    redis_ok = False
    try:
        redis_ok = bool(await get_async_redis().ping())
    except Exception:
        redis_ok = False
    ffmpeg_ok = shutil.which("ffmpeg") is not None
    ytdlp_ok = bool(ytdlp_version)
    status = "ok" if redis_ok and ffmpeg_ok and ytdlp_ok else "degraded"
    return HealthResponse(status=status, redis=redis_ok, ffmpeg=ffmpeg_ok, ytdlp=ytdlp_ok)
