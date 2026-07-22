import asyncio
import ipaddress
import re
import ssl
from collections.abc import Iterable
from urllib.parse import urljoin

import certifi
import httpcore
import httpx

from app.core.errors import AppError, error
from app.core.security import (
    REDIRECT_STATUSES,
    _resolved_addresses,
    validate_public_url,
    validate_resolved_addresses,
)

MOBILE_USER_AGENT = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 18_5 like Mac OS X) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.5 "
    "Mobile/15E148 Safari/604.1"
)
URL_PATTERN = re.compile(
    r"https?://[^\s<>\"'，。；：！？）】》」』]+",
    flags=re.IGNORECASE,
)
TRAILING_URL_PUNCTUATION = frozenset(".,;:!?])}>,，。；：！？）】》」』")
HEAD_FALLBACK_STATUSES = frozenset({400, 403, 405, 406, 429, 500, 501})


def extract_http_url(share_text: str) -> str:
    """Extract the first HTTP(S) URL from a bounded platform share message."""

    if not isinstance(share_text, str) or not share_text or len(share_text) > 8192:
        raise error("INVALID_URL")
    match = URL_PATTERN.search(share_text)
    if not match:
        raise error("INVALID_URL")
    candidate = match.group(0)
    while candidate and candidate[-1] in TRAILING_URL_PUNCTUATION:
        candidate = candidate[:-1]
    if not candidate:
        raise error("INVALID_URL")
    return candidate


class PinnedAsyncNetworkBackend(httpcore.AsyncNetworkBackend):
    """Resolve and validate every TCP destination immediately before connecting.

    The HTTP request keeps the original hostname, so TLS SNI and certificate
    verification remain correct, while the TCP connection is pinned to an IP
    that passed the public-address checks. This closes the usual DNS-rebinding
    gap between URL validation and the HTTP client's own DNS lookup.
    """

    def __init__(self) -> None:
        self._backend = httpcore.AnyIOBackend()

    async def connect_tcp(
        self,
        host: str,
        port: int,
        timeout: float | None = None,
        local_address: str | None = None,
        socket_options: Iterable[httpcore.SOCKET_OPTION] | None = None,
    ) -> httpcore.AsyncNetworkStream:
        normalized_host = host.strip("[]").split("%", 1)[0]
        try:
            literal = ipaddress.ip_address(normalized_host)
        except ValueError:
            addresses = validate_resolved_addresses(
                await asyncio.to_thread(_resolved_addresses, normalized_host, port)
            )
        else:
            if not literal.is_global:
                raise error("BLOCKED_ADDRESS")
            addresses = {str(literal)}

        last_error: Exception | None = None
        for address in sorted(addresses):
            try:
                return await self._backend.connect_tcp(
                    address,
                    port,
                    timeout=timeout,
                    local_address=local_address,
                    socket_options=socket_options,
                )
            except Exception as exc:  # httpcore exposes several network exception types
                last_error = exc
        if last_error is not None:
            raise last_error
        raise httpcore.ConnectError("No validated public address is available")

    async def connect_unix_socket(
        self,
        path: str,
        timeout: float | None = None,
        socket_options: Iterable[httpcore.SOCKET_OPTION] | None = None,
    ) -> httpcore.AsyncNetworkStream:
        raise httpcore.ConnectError("Unix sockets are disabled for URL resolution")

    async def sleep(self, seconds: float) -> None:
        await self._backend.sleep(seconds)


class SSRFSafeAsyncHTTPTransport(httpx.AsyncHTTPTransport):
    """HTTPX transport backed by the DNS-validating, IP-pinned connector."""

    def __init__(self) -> None:
        ssl_context = ssl.create_default_context(cafile=certifi.where())
        super().__init__(verify=ssl_context, trust_env=False, retries=0)
        self._pool = httpcore.AsyncConnectionPool(
            ssl_context=ssl_context,
            max_connections=10,
            max_keepalive_connections=5,
            keepalive_expiry=10.0,
            http1=True,
            http2=False,
            retries=0,
            network_backend=PinnedAsyncNetworkBackend(),
        )


class LinkResolver:
    def __init__(
        self,
        *,
        max_redirects: int,
        timeout_seconds: float = 10.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.max_redirects = max_redirects
        self.timeout_seconds = timeout_seconds
        self.transport = transport

    async def resolve_share_text(self, share_text: str) -> str:
        return await self.resolve(extract_http_url(share_text))

    async def resolve(self, url: str) -> str:
        current = await validate_public_url(url)
        transport = self.transport or SSRFSafeAsyncHTTPTransport()
        timeout = httpx.Timeout(self.timeout_seconds)
        headers = {
            "User-Agent": MOBILE_USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,application/json;q=0.9,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.7",
        }
        try:
            async with httpx.AsyncClient(
                transport=transport,
                timeout=timeout,
                follow_redirects=False,
                trust_env=False,
                headers=headers,
            ) as client:
                for redirect_count in range(self.max_redirects + 1):
                    status, location = await self._probe(client, current)
                    if status not in REDIRECT_STATUSES or not location:
                        return current
                    if redirect_count >= self.max_redirects:
                        raise error("INVALID_URL", message="链接重定向次数过多")
                    current = await validate_public_url(urljoin(current, location))
        except AppError:
            raise
        except (httpx.HTTPError, httpcore.NetworkError, httpcore.TimeoutException) as exc:
            raise error("INVALID_URL", message="无法访问或还原该分享链接") from exc
        return current

    @staticmethod
    async def _probe(client: httpx.AsyncClient, url: str) -> tuple[int, str | None]:
        async with client.stream("HEAD", url) as response:
            status = response.status_code
            location = response.headers.get("location")
        if status not in HEAD_FALLBACK_STATUSES:
            return status, location
        async with client.stream(
            "GET",
            url,
            headers={"Range": "bytes=0-0"},
        ) as response:
            return response.status_code, response.headers.get("location")
