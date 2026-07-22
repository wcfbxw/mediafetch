import pytest

from app.core.admin import require_admin
from app.core.config import get_settings
from app.core.errors import AppError


@pytest.mark.asyncio
async def test_admin_token_required(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("ADMIN_TOKEN", "a" * 64)
    get_settings.cache_clear()
    with pytest.raises(AppError) as caught:
        await require_admin("wrong")
    assert caught.value.code == "ADMIN_UNAUTHORIZED"
    await require_admin("a" * 64)
