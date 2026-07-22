import asyncio
import http.client
import ipaddress
import socket
import ssl
from collections.abc import Iterable
from typing import cast
from urllib.parse import urljoin, urlsplit, urlunsplit

from fastapi import Request

from app.core.config import get_settings
from app.core.errors import AppError, error

ALLOWED_SCHEMES = {"http", "https"}
BLOCKED_HOSTNAMES = {
    "localhost",
    "localhost.localdomain",
    "metadata",
    "metadata.google.internal",
}
REDIRECT_STATUSES = {301, 302, 303, 307, 308}


def canonicalize_url(value: str) -> str:
    value = value.strip()
    if not value or len(value) > 2048:
        raise error("INVALID_URL")
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError as exc:
        raise error("INVALID_URL") from exc
    if parsed.scheme.lower() not in ALLOWED_SCHEMES or not parsed.hostname:
        raise error("INVALID_URL")
    if parsed.username or parsed.password:
        raise error("INVALID_URL")
    hostname = parsed.hostname.rstrip(".").lower()
    if hostname in BLOCKED_HOSTNAMES or hostname.endswith(".localhost"):
        raise error("BLOCKED_ADDRESS")
    if port is not None and not 1 <= port <= 65535:
        raise error("INVALID_URL")
    netloc = hostname
    if ":" in hostname:
        netloc = f"[{hostname}]"
    if port is not None:
        netloc = f"{netloc}:{port}"
    return urlunsplit((parsed.scheme.lower(), netloc, parsed.path or "/", parsed.query, ""))


def is_blocked_ip(address: str) -> bool:
    try:
        ip = ipaddress.ip_address(address.split("%", 1)[0])
    except ValueError:
        return True
    # is_global also rejects loopback, private, link-local, multicast,
    # unspecified, documentation, benchmarking and reserved ranges.
    return not ip.is_global


def _resolved_addresses(hostname: str, port: int) -> set[str]:
    try:
        records = socket.getaddrinfo(
            hostname,
            port,
            family=socket.AF_UNSPEC,
            type=socket.SOCK_STREAM,
        )
    except socket.gaierror as exc:
        raise error("INVALID_URL", message="无法解析该链接的域名") from exc
    return {cast(str, record[4][0]) for record in records}


def validate_resolved_addresses(addresses: Iterable[str]) -> set[str]:
    resolved = set(addresses)
    if not resolved:
        raise error("INVALID_URL", message="无法解析该链接的域名")
    if any(is_blocked_ip(address) for address in resolved):
        raise error("BLOCKED_ADDRESS")
    return resolved


def validate_public_url_sync(value: str) -> str:
    url = canonicalize_url(value)
    parsed = urlsplit(url)
    hostname = parsed.hostname or ""
    try:
        literal = ipaddress.ip_address(hostname.split("%", 1)[0])
    except ValueError:
        validate_resolved_addresses(
            _resolved_addresses(hostname, parsed.port or (443 if parsed.scheme == "https" else 80))
        )
    else:
        if not literal.is_global:
            raise error("BLOCKED_ADDRESS")
    return url


async def validate_public_url(value: str) -> str:
    return await asyncio.to_thread(validate_public_url_sync, value)


def _probe_redirect(value: str) -> str | None:
    """Issue a HEAD request while connecting to a previously validated IP."""

    url = canonicalize_url(value)
    parsed = urlsplit(url)
    hostname = parsed.hostname or ""
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    try:
        literal = ipaddress.ip_address(hostname.split("%", 1)[0])
    except ValueError:
        addresses = validate_resolved_addresses(_resolved_addresses(hostname, port))
    else:
        if not literal.is_global:
            raise error("BLOCKED_ADDRESS")
        addresses = {str(literal)}

    request_target = urlunsplit(("", "", parsed.path or "/", parsed.query, ""))
    last_error: OSError | http.client.HTTPException | None = None
    for address in sorted(addresses):
        if parsed.scheme == "https":
            connection: http.client.HTTPConnection = http.client.HTTPSConnection(
                hostname,
                port,
                timeout=8,
                context=ssl.create_default_context(),
            )
        else:
            connection = http.client.HTTPConnection(hostname, port, timeout=8)

        def connect_pinned(
            _target,
            timeout=None,
            source_address=None,
            *,
            pinned_address=address,
        ):
            return socket.create_connection(
                (pinned_address, port),
                timeout=timeout,
                source_address=source_address,
            )

        connection._create_connection = connect_pinned  # type: ignore[attr-defined]
        try:
            connection.request(
                "HEAD",
                request_target,
                headers={"User-Agent": "MediaFetch/1.0 URL safety preflight"},
            )
            response = connection.getresponse()
            if response.status not in REDIRECT_STATUSES:
                return None
            return response.getheader("location")
        except (OSError, http.client.HTTPException) as exc:
            last_error = exc
        finally:
            connection.close()
    if last_error:
        return None
    return None


async def validate_redirect_chain(value: str) -> str:
    """Validate every redirect target before the extractor follows it.

    yt-dlp additionally uses ``SafeYoutubeDL`` which repeats the DNS check for
    every request, including redirects and media manifests.
    """

    settings = get_settings()
    current = await validate_public_url(value)
    for _ in range(settings.max_redirects + 1):
        location = await asyncio.to_thread(_probe_redirect, current)
        if not location:
            return current
        current = await validate_public_url(urljoin(current, location))
    raise error("INVALID_URL", message="链接重定向次数过多")


def get_client_ip(request: Request) -> str:
    # The API is only exposed through the Compose Nginx service; it replaces
    # X-Real-IP instead of trusting a value sent by the public client.
    candidate = request.headers.get("x-real-ip")
    if candidate:
        try:
            return str(ipaddress.ip_address(candidate.strip()))
        except ValueError:
            pass
    return request.client.host if request.client else "unknown"


async def enforce_rate_limit(
    redis_client,
    *,
    client_ip: str,
    scope: str,
    limit: int,
    window_seconds: int = 60,
) -> None:
    key = f"ratelimit:{scope}:{client_ip}"
    try:
        count = await redis_client.incr(key)
        if count == 1:
            await redis_client.expire(key, window_seconds)
    except Exception as exc:
        # Rate limiting must fail closed only for excessive requests, while a
        # Redis outage is handled by the normal API availability checks.
        raise error("INTERNAL_ERROR") from exc
    if count > limit:
        ttl = await redis_client.ttl(key)
        raise AppError(
            "RATE_LIMITED",
            "请求过于频繁，请稍后再试",
            429,
            {"retry_after": max(ttl, 1)},
        )
