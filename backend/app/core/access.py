import hmac

from fastapi import APIRouter, Request

from app.core.config import get_settings
from app.core.errors import error
from app.models.responses import AuthRequirementResponse

router = APIRouter(tags=["auth"])


@router.get("/auth/config", response_model=AuthRequirementResponse)
async def auth_config() -> AuthRequirementResponse:
    return AuthRequirementResponse(
        access_token_required=bool(get_settings().access_token),
    )


def require_access_token(request: Request) -> None:
    expected = get_settings().access_token
    if not expected:
        return
    provided = (request.headers.get("x-access-token") or "").strip()
    if not provided or not hmac.compare_digest(provided.encode("utf-8"), expected.encode("utf-8")):
        raise error("ACCESS_UNAUTHORIZED")
