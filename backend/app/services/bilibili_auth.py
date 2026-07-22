import base64
import io
import json
import logging
import secrets
import time
from http.cookiejar import CookieJar
from typing import Any, Literal, cast
from urllib.parse import urlsplit

import httpx
import redis.asyncio as async_redis
import segno

from app.core.config import get_settings
from app.core.errors import error
from app.services.platform_credentials import save_bilibili_cookies

GENERATE_URL = "https://passport.bilibili.com/x/passport-login/web/qrcode/generate"
POLL_URL = "https://passport.bilibili.com/x/passport-login/web/qrcode/poll"
DEVICE_URL = "https://api.bilibili.com/x/frontend/finger/spi"
LOGIN_TTL_SECONDS = 180
QR_HOSTS = {"passport.bilibili.com", "account.bilibili.com"}
logger = logging.getLogger(__name__)


def _headers() -> dict[str, str]:
    return {
        "User-Agent": get_settings().bilibili_user_agent,
        "Referer": "https://www.bilibili.com/",
        "Accept": "application/json, text/plain, */*",
    }


def _qr_image(value: str) -> str:
    stream = io.BytesIO()
    segno.make(value, error="m").save(
        stream,
        kind="svg",
        scale=5,
        border=2,
        xmldecl=False,
    )
    encoded = base64.b64encode(stream.getvalue()).decode("ascii")
    return f"data:image/svg+xml;base64,{encoded}"


async def _add_device_cookies(source: CookieJar) -> CookieJar:
    """Add Bilibili's official device identifiers to the account session."""
    try:
        async with httpx.AsyncClient(
            timeout=12,
            follow_redirects=False,
            cookies=httpx.Cookies(source),
        ) as client:
            response = await client.get(DEVICE_URL, headers=_headers())
            response.raise_for_status()
            body = response.json()
            data = body.get("data") if isinstance(body, dict) else None
            if not isinstance(data, dict) or not data.get("b_3") or not data.get("b_4"):
                raise ValueError("device identifiers missing")
            client.cookies.set("buvid3", str(data["b_3"]), domain=".bilibili.com", path="/")
            client.cookies.set("buvid4", str(data["b_4"]), domain=".bilibili.com", path="/")
            client.cookies.set(
                "b_nut",
                str(int(time.time())),
                domain=".bilibili.com",
                path="/",
            )
            return client.cookies.jar
    except (httpx.HTTPError, TypeError, ValueError):
        logger.warning("Could not obtain Bilibili device cookies after QR login")
        return source


async def begin_bilibili_login(redis_client: async_redis.Redis) -> dict[str, Any]:
    try:
        async with httpx.AsyncClient(timeout=12, follow_redirects=False) as client:
            response = await client.get(GENERATE_URL, headers=_headers())
            response.raise_for_status()
            body = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise error("PLATFORM_LOGIN_FAILED") from exc
    data = body.get("data") if isinstance(body, dict) else None
    if not isinstance(body, dict) or body.get("code") != 0 or not isinstance(data, dict):
        raise error("PLATFORM_LOGIN_FAILED")
    qr_url = data.get("url")
    qr_key = data.get("qrcode_key")
    if not isinstance(qr_url, str) or not isinstance(qr_key, str):
        raise error("PLATFORM_LOGIN_FAILED")
    qr_target = urlsplit(qr_url)
    if qr_target.scheme != "https" or qr_target.hostname not in QR_HOSTS:
        raise error("PLATFORM_LOGIN_FAILED")

    login_id = secrets.token_urlsafe(24)
    await redis_client.setex(
        f"platform-login:bilibili:{login_id}",
        LOGIN_TTL_SECONDS,
        json.dumps({"qrcode_key": qr_key}, separators=(",", ":")),
    )
    return {
        "login_id": login_id,
        "qr_image": _qr_image(qr_url),
        "expires_in": LOGIN_TTL_SECONDS,
    }


async def poll_bilibili_login(
    redis_client: async_redis.Redis,
    login_id: str,
) -> dict[str, Any]:
    key = f"platform-login:bilibili:{login_id}"
    encoded = cast(str | None, await redis_client.get(key))
    if not encoded:
        raise error("PLATFORM_LOGIN_EXPIRED")
    try:
        qr_key = json.loads(encoded)["qrcode_key"]
        if not isinstance(qr_key, str):
            raise ValueError
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        await redis_client.delete(key)
        raise error("PLATFORM_LOGIN_FAILED") from exc

    try:
        async with httpx.AsyncClient(timeout=12, follow_redirects=False) as client:
            response = await client.get(
                POLL_URL,
                params={"qrcode_key": qr_key},
                headers=_headers(),
            )
            response.raise_for_status()
            body = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise error("PLATFORM_LOGIN_FAILED") from exc
    data = body.get("data") if isinstance(body, dict) else None
    if not isinstance(body, dict) or body.get("code") != 0 or not isinstance(data, dict):
        raise error("PLATFORM_LOGIN_FAILED")

    code = data.get("code")
    status: Literal["waiting_scan", "waiting_confirm", "ready", "expired"]
    messages = {
        "waiting_scan": "请使用哔哩哔哩 App 扫码",
        "waiting_confirm": "已扫码，请在 App 中确认登录",
        "ready": "平台会话已安全保存",
        "expired": "二维码已过期，请重新生成",
    }
    if code == 86101:
        status = "waiting_scan"
    elif code == 86090:
        status = "waiting_confirm"
    elif code == 86038:
        status = "expired"
        await redis_client.delete(key)
    elif code == 0:
        cookies = await _add_device_cookies(response.cookies.jar)
        save_bilibili_cookies(cookies)
        status = "ready"
        await redis_client.delete(key)
    else:
        raise error("PLATFORM_LOGIN_FAILED")
    ttl = (
        max(cast(int, await redis_client.ttl(key)), 0) if status not in {"ready", "expired"} else 0
    )
    return {"status": status, "message": messages[status], "expires_in": ttl}
