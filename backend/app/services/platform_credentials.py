import copy
import os
import tempfile
import time
from http.cookiejar import Cookie, CookieJar, MozillaCookieJar
from pathlib import Path
from typing import Any, Literal, cast
from urllib.parse import urlsplit

from app.core.config import get_settings
from app.core.errors import error
from app.services.kuaishou import KUAISHOU_MOBILE_USER_AGENT

PlatformCookieName = Literal["douyin", "instagram", "youtube"]

BILIBILI_DOMAINS = ("bilibili.com", "b23.tv")
PLATFORM_DOMAINS: dict[str, tuple[str, ...]] = {
    "bilibili": BILIBILI_DOMAINS,
    "douyin": ("douyin.com", "iesdouyin.com"),
    "instagram": ("instagram.com",),
    "youtube": ("youtube.com", "youtu.be", "google.com"),
    "kuaishou": ("kuaishou.com", "chenzhongtech.com"),
}
COOKIE_PLATFORMS = frozenset({"bilibili", "douyin", "instagram", "youtube"})
IMPORTABLE_COOKIE_PLATFORMS = frozenset({"douyin", "instagram", "youtube"})
MAX_COOKIE_FILE_BYTES = 128 * 1024

DESKTOP_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/143.0.0.0 Safari/537.36"
)


def _host_matches(hostname: str, domains: tuple[str, ...]) -> bool:
    return any(hostname == domain or hostname.endswith(f".{domain}") for domain in domains)


def _platform_for_url(url: str) -> str | None:
    hostname = (urlsplit(url).hostname or "").lower().rstrip(".")
    return next(
        (name for name, domains in PLATFORM_DOMAINS.items() if _host_matches(hostname, domains)),
        None,
    )


def is_bilibili_url(url: str) -> bool:
    return _platform_for_url(url) == "bilibili"


def platform_cookie_file(platform: str) -> Path:
    if platform not in COOKIE_PLATFORMS:
        raise error("INTERNAL_ERROR")
    settings = get_settings()
    root = settings.credentials_root.resolve()
    target = (root / f"{platform}-cookies.txt").resolve()
    if target.parent != root:
        raise error("INTERNAL_ERROR")
    return target


def _safe_cookie_path() -> Path:
    return platform_cookie_file("bilibili")


def is_managed_cookie_file(value: str | Path) -> bool:
    try:
        candidate = Path(value).resolve()
    except (OSError, ValueError):
        return False
    return any(candidate == platform_cookie_file(name) for name in COOKIE_PLATFORMS)


def _atomic_save_cookie_jar(target: Path, cookies: list[Cookie]) -> int:
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(prefix=f".{target.stem}-", dir=target.parent)
    os.close(fd)
    temporary = Path(temporary_name)
    try:
        destination = MozillaCookieJar(str(temporary))
        for cookie in cookies:
            destination.set_cookie(cookie)
        destination.save(ignore_discard=True, ignore_expires=True)
        os.chmod(temporary, 0o600)
        os.replace(temporary, target)
        os.chmod(target, 0o600)
    finally:
        temporary.unlink(missing_ok=True)
    return int(target.stat().st_mtime)


def save_bilibili_cookies(source: CookieJar) -> int:
    target = _safe_cookie_path()
    selected = [
        copy.copy(cookie)
        for cookie in source
        if _host_matches(cookie.domain.lstrip(".").lower(), ("bilibili.com",))
    ]
    if not any(cookie.name == "SESSDATA" and cookie.value for cookie in selected):
        raise error("PLATFORM_LOGIN_FAILED")
    return _atomic_save_cookie_jar(target, selected)


def _load_cookie_jar(target: Path) -> MozillaCookieJar | None:
    if not target.is_file():
        return None
    jar = MozillaCookieJar(str(target))
    try:
        jar.load(ignore_discard=True, ignore_expires=True)
    except (OSError, ValueError, TypeError):
        return None
    return jar


def platform_session_status(platform: str) -> dict[str, int | bool | None]:
    target = platform_cookie_file(platform)
    jar = _load_cookie_jar(target)
    if jar is None:
        return {
            "configured": False,
            "updated_at": int(target.stat().st_mtime) if target.exists() else None,
            "expires_at": None,
        }
    now = int(time.time())
    active = [
        cookie
        for cookie in jar
        if cookie.value and (not cookie.expires or cookie.expires > now)
    ]
    if platform == "bilibili":
        active = [cookie for cookie in active if cookie.name == "SESSDATA"]
    expirations = [cookie.expires for cookie in active if cookie.expires]
    return {
        "configured": bool(active),
        "updated_at": int(target.stat().st_mtime),
        "expires_at": min(expirations) if expirations else None,
    }


def bilibili_session_status() -> dict[str, int | bool | None]:
    return platform_session_status("bilibili")


def clear_platform_session(platform: str) -> None:
    platform_cookie_file(platform).unlink(missing_ok=True)


def clear_bilibili_session() -> None:
    clear_platform_session("bilibili")


def _parse_netscape_cookie_file(platform: PlatformCookieName, content: bytes) -> list[Cookie]:
    if not content or len(content) > MAX_COOKIE_FILE_BYTES or b"\x00" in content:
        raise error("INVALID_COOKIE_FILE")
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise error("INVALID_COOKIE_FILE") from exc

    allowed_domains = PLATFORM_DOMAINS[platform]
    now = int(time.time())
    cookies: list[Cookie] = []
    for raw_line in text.splitlines():
        line = raw_line.strip("\r\n")
        http_only = line.startswith("#HttpOnly_")
        if not line or line.startswith("#") and not http_only:
            continue
        parts = line.split("\t")
        if len(parts) != 7:
            raise error("INVALID_COOKIE_FILE")
        domain, include_subdomains, path, secure, expires_text, name, value = parts
        if http_only:
            domain = domain.removeprefix("#HttpOnly_")
        normalized_domain = domain.lstrip(".").lower().rstrip(".")
        if not normalized_domain or not _host_matches(normalized_domain, allowed_domains):
            raise error("INVALID_COOKIE_FILE")
        if include_subdomains.upper() not in {"TRUE", "FALSE"}:
            raise error("INVALID_COOKIE_FILE")
        if secure.upper() not in {"TRUE", "FALSE"}:
            raise error("INVALID_COOKIE_FILE")
        if not path.startswith("/") or not name or any(ord(char) < 32 for char in name + value):
            raise error("INVALID_COOKIE_FILE")
        try:
            raw_expires = int(expires_text)
        except ValueError as exc:
            raise error("INVALID_COOKIE_FILE") from exc
        expires = raw_expires if raw_expires > 0 else None
        if expires is not None and expires <= now:
            continue
        cookies.append(
            Cookie(
                version=0,
                name=name,
                value=value,
                port=None,
                port_specified=False,
                domain=domain,
                domain_specified=True,
                domain_initial_dot=domain.startswith("."),
                path=path,
                path_specified=True,
                secure=secure.upper() == "TRUE",
                expires=expires,
                discard=expires is None,
                comment=None,
                comment_url=None,
                rest={"HTTPOnly": ""} if http_only else {},
            )
        )
    if not cookies:
        raise error("INVALID_COOKIE_FILE")
    return cookies


def save_platform_cookie_file(platform: PlatformCookieName, content: bytes) -> dict[str, Any]:
    if platform not in IMPORTABLE_COOKIE_PLATFORMS:
        raise error("INVALID_COOKIE_FILE")
    cookies = _parse_netscape_cookie_file(platform, content)
    _atomic_save_cookie_jar(platform_cookie_file(platform), cookies)
    return {**platform_session_status(platform), "cookie_count": len(cookies)}


def configure_ytdlp_credentials(options: dict[str, Any], url: str) -> None:
    platform = _platform_for_url(url)
    if not platform:
        return
    settings = get_settings()
    headers: dict[str, str]
    if platform == "bilibili":
        headers = {
            "User-Agent": settings.bilibili_user_agent,
            "Referer": "https://www.bilibili.com/",
        }
    elif platform == "kuaishou":
        headers = {
            "User-Agent": KUAISHOU_MOBILE_USER_AGENT,
            "Referer": "https://v.kuaishou.com/",
        }
    else:
        referers = {
            "douyin": "https://www.douyin.com/",
            "instagram": "https://www.instagram.com/",
            "youtube": "https://www.youtube.com/",
        }
        headers = {"User-Agent": DESKTOP_USER_AGENT, "Referer": referers[platform]}
    existing_headers = options.get("http_headers")
    options["http_headers"] = {
        **(cast(dict[str, str], existing_headers) if isinstance(existing_headers, dict) else {}),
        **headers,
    }

    if platform in COOKIE_PLATFORMS:
        target = platform_cookie_file(platform)
        if target.is_file() and platform_session_status(platform)["configured"]:
            options["cookiefile"] = str(target)
