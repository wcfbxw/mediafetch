from fastapi import APIRouter, Request

from app.core.config import get_settings
from app.core.redis import get_async_redis, get_redis
from app.core.security import enforce_rate_limit, get_client_ip
from app.models.requests import InspectRequest
from app.models.responses import InspectResponse
from app.services.extractor import inspect_media

router = APIRouter(tags=["inspect"])


@router.post("/inspect", response_model=InspectResponse)
async def inspect_url(payload: InspectRequest, request: Request) -> InspectResponse:
    settings = get_settings()
    await enforce_rate_limit(
        get_async_redis(),
        client_ip=get_client_ip(request),
        scope="inspect",
        limit=settings.rate_limit_inspect_per_minute,
    )
    # Extraction is blocking and runs in its own thread; the sync Redis client
    # is intentionally used only from that workflow.
    return await inspect_media(payload.url, get_redis())
