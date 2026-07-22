from pathlib import Path

import fakeredis
import pytest

from app.core.config import get_settings


@pytest.fixture(autouse=True)
def test_settings(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("TOKEN_SECRET", "test-secret-that-is-definitely-at-least-32-chars")
    monkeypatch.setenv("STORAGE_ROOT", str(tmp_path / "storage"))
    monkeypatch.setenv("CREDENTIALS_ROOT", str(tmp_path / "credentials"))
    monkeypatch.setenv("MAX_FILE_SIZE_MB", "16")
    get_settings.cache_clear()
    settings = get_settings()
    settings.ensure_storage()
    yield settings
    get_settings.cache_clear()


@pytest.fixture
def redis_client():
    return fakeredis.FakeRedis(decode_responses=True)
