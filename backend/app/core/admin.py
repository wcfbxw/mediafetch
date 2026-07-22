import secrets
from typing import Annotated

from fastapi import Header

from app.core.config import get_settings
from app.core.errors import error


async def require_admin(
    x_admin_token: Annotated[str | None, Header()] = None,
) -> None:
    expected = get_settings().admin_token
    if not expected or not x_admin_token or not secrets.compare_digest(expected, x_admin_token):
        raise error("ADMIN_UNAUTHORIZED")
