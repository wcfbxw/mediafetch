import re

from fastapi import APIRouter, Depends

from app.core.admin import require_admin
from app.core.errors import error
from app.core.redis import get_async_redis
from app.models.responses import (
    BilibiliLoginPoll,
    BilibiliLoginStart,
    PlatformSessionStatus,
)
from app.services.bilibili_auth import begin_bilibili_login, poll_bilibili_login
from app.services.platform_credentials import (
    bilibili_session_status,
    clear_bilibili_session,
)

router = APIRouter(
    prefix="/admin/bilibili",
    tags=["admin"],
    dependencies=[Depends(require_admin)],
)
LOGIN_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{20,64}$")


@router.get("/status", response_model=PlatformSessionStatus)
async def session_status() -> PlatformSessionStatus:
    return PlatformSessionStatus.model_validate(bilibili_session_status())


@router.post("/login", response_model=BilibiliLoginStart)
async def start_login() -> BilibiliLoginStart:
    result = await begin_bilibili_login(get_async_redis())
    return BilibiliLoginStart.model_validate(result)


@router.get("/login/{login_id}", response_model=BilibiliLoginPoll)
async def poll_login(login_id: str) -> BilibiliLoginPoll:
    if not LOGIN_ID_PATTERN.fullmatch(login_id):
        raise error("PLATFORM_LOGIN_EXPIRED")
    result = await poll_bilibili_login(get_async_redis(), login_id)
    return BilibiliLoginPoll.model_validate(result)


@router.delete("/session", response_model=PlatformSessionStatus)
async def delete_session() -> PlatformSessionStatus:
    clear_bilibili_session()
    return PlatformSessionStatus(configured=False)
