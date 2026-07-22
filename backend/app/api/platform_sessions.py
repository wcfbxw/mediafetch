from typing import Literal

from fastapi import APIRouter, Depends, File, UploadFile

from app.core.admin import require_admin
from app.core.errors import error
from app.models.responses import PlatformSessionStatus
from app.services.platform_credentials import (
    MAX_COOKIE_FILE_BYTES,
    PlatformCookieName,
    clear_platform_session,
    platform_session_status,
    save_platform_cookie_file,
)

router = APIRouter(
    prefix="/admin/platforms",
    tags=["admin"],
    dependencies=[Depends(require_admin)],
)


@router.get("/{platform}/status", response_model=PlatformSessionStatus)
async def session_status(
    platform: Literal["douyin", "instagram", "youtube"],
) -> PlatformSessionStatus:
    return PlatformSessionStatus.model_validate(platform_session_status(platform))


@router.put("/{platform}/cookies", response_model=PlatformSessionStatus)
async def upload_cookies(
    platform: PlatformCookieName,
    file: UploadFile = File(...),
) -> PlatformSessionStatus:
    try:
        content = await file.read(MAX_COOKIE_FILE_BYTES + 1)
    finally:
        await file.close()
    if len(content) > MAX_COOKIE_FILE_BYTES:
        raise error("INVALID_COOKIE_FILE")
    result = save_platform_cookie_file(platform, content)
    return PlatformSessionStatus.model_validate(result)


@router.delete("/{platform}/session", response_model=PlatformSessionStatus)
async def delete_session(
    platform: Literal["douyin", "instagram", "youtube"],
) -> PlatformSessionStatus:
    clear_platform_session(platform)
    return PlatformSessionStatus(configured=False)
