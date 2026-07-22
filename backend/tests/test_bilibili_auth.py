from http.cookiejar import CookieJar, MozillaCookieJar
from typing import Any

import fakeredis.aioredis
import httpx
import pytest

from app.core.config import get_settings
from app.services import bilibili_auth
from tests.test_platform_credentials import make_cookie


class FakeResponse:
    def __init__(self, body: dict[str, Any], cookies: CookieJar | None = None):
        self._body = body
        self.cookies = type("Cookies", (), {"jar": cookies or CookieJar()})()

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict[str, Any]:
        return self._body


class FakeClient:
    responses: list[FakeResponse] = []

    def __init__(self, **_kwargs: Any):
        self.cookies = httpx.Cookies(_kwargs.get("cookies"))

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args: Any) -> None:
        return None

    async def get(self, *_args: Any, **_kwargs: Any) -> FakeResponse:
        return self.responses.pop(0)


@pytest.mark.asyncio
async def test_qr_login_hides_upstream_key_and_saves_success_cookie(monkeypatch):
    redis_client = fakeredis.aioredis.FakeRedis(decode_responses=True)
    cookie_jar = CookieJar()
    cookie_jar.set_cookie(make_cookie("SESSDATA", "server-session"))
    FakeClient.responses = [
        FakeResponse(
            {
                "code": 0,
                "data": {
                    "url": "https://account.bilibili.com/h5/account-h5/auth/scan-web?x=1",
                    "qrcode_key": "upstream-secret-key",
                },
            }
        ),
        FakeResponse({"code": 0, "data": {"code": 0}}, cookie_jar),
        FakeResponse(
            {
                "code": 0,
                "data": {"b_3": "device-three", "b_4": "device-four"},
            }
        ),
    ]
    monkeypatch.setattr(bilibili_auth.httpx, "AsyncClient", FakeClient)

    started = await bilibili_auth.begin_bilibili_login(redis_client)
    assert "upstream-secret-key" not in str(started)
    assert started["qr_image"].startswith("data:image/svg+xml;base64,")

    completed = await bilibili_auth.poll_bilibili_login(redis_client, started["login_id"])
    assert completed["status"] == "ready"
    assert await redis_client.get(f"platform-login:bilibili:{started['login_id']}") is None

    saved = MozillaCookieJar(str(get_settings().bilibili_cookie_file))
    saved.load(ignore_discard=True, ignore_expires=True)
    assert {cookie.name for cookie in saved} >= {"SESSDATA", "buvid3", "buvid4", "b_nut"}
