import httpcore
import httpx
import pytest

from app.core import security
from app.core.errors import AppError
from app.services import link_resolver
from app.services.link_resolver import (
    LinkResolver,
    PinnedAsyncNetworkBackend,
    SSRFSafeAsyncHTTPTransport,
)


@pytest.mark.asyncio
async def test_link_resolver_follows_relative_redirects(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(security, "_resolved_addresses", lambda _host, _port: {"8.8.8.8"})

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/short":
            return httpx.Response(302, headers={"Location": "/final"})
        return httpx.Response(200)

    resolver = LinkResolver(
        max_redirects=3,
        transport=httpx.MockTransport(handler),
    )
    assert await resolver.resolve("https://public.example/short") == (
        "https://public.example/final"
    )


@pytest.mark.asyncio
async def test_link_resolver_falls_back_to_bounded_get(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(security, "_resolved_addresses", lambda _host, _port: {"8.8.8.8"})
    methods: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        methods.append(request.method)
        if request.url.path == "/short" and request.method == "HEAD":
            return httpx.Response(405)
        if request.url.path == "/short":
            assert request.headers["range"] == "bytes=0-0"
            return httpx.Response(301, headers={"Location": "https://target.example/video"})
        return httpx.Response(200)

    resolver = LinkResolver(
        max_redirects=3,
        transport=httpx.MockTransport(handler),
    )
    assert await resolver.resolve("https://public.example/short") == (
        "https://target.example/video"
    )
    assert methods == ["HEAD", "GET", "HEAD"]


@pytest.mark.asyncio
async def test_link_resolver_blocks_private_redirect(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(security, "_resolved_addresses", lambda _host, _port: {"8.8.8.8"})

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(302, headers={"Location": "http://127.0.0.1/admin"})

    resolver = LinkResolver(
        max_redirects=3,
        transport=httpx.MockTransport(handler),
    )
    with pytest.raises(AppError) as caught:
        await resolver.resolve("https://public.example/short")
    assert caught.value.code == "BLOCKED_ADDRESS"


@pytest.mark.asyncio
async def test_link_resolver_enforces_redirect_limit(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(security, "_resolved_addresses", lambda _host, _port: {"8.8.8.8"})

    def handler(request: httpx.Request) -> httpx.Response:
        index = int(request.url.path.rsplit("/", 1)[-1])
        return httpx.Response(302, headers={"Location": f"/redirect/{index + 1}"})

    resolver = LinkResolver(
        max_redirects=2,
        transport=httpx.MockTransport(handler),
    )
    with pytest.raises(AppError) as caught:
        await resolver.resolve("https://public.example/redirect/0")
    assert caught.value.code == "INVALID_URL"


@pytest.mark.asyncio
async def test_pinned_backend_rejects_mixed_public_private_dns(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr(
        link_resolver,
        "_resolved_addresses",
        lambda _host, _port: {"8.8.8.8", "192.168.1.2"},
    )
    backend = PinnedAsyncNetworkBackend()
    with pytest.raises(AppError) as caught:
        await backend.connect_tcp("rebind.example", 443)
    assert caught.value.code == "BLOCKED_ADDRESS"


@pytest.mark.parametrize("proxy", [None, "http://172.16.0.1:7890"])
@pytest.mark.parametrize(
    ("host", "port"),
    [("172.16.0.1", 7890), ("172.16.0.1", 80), ("172.16.0.2", 7890)],
)
async def test_pinned_backend_only_allows_exact_private_proxy(
    monkeypatch: pytest.MonkeyPatch, proxy, host, port
):
    backend = PinnedAsyncNetworkBackend(proxy=proxy)
    connections = []
    stream = object()

    async def connect(address, port, **_kwargs):
        connections.append((address, port))
        return stream

    monkeypatch.setattr(backend._backend, "connect_tcp", connect)
    if proxy and host == "172.16.0.1" and port == 7890:
        assert await backend.connect_tcp(host, port) is stream
        assert connections == [(host, port)]
    else:
        with pytest.raises(AppError) as caught:
            await backend.connect_tcp(host, port)
        assert caught.value.code == "BLOCKED_ADDRESS"
        assert not connections


async def test_pinned_backend_allows_private_dns_only_for_proxy_hostname(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr(link_resolver, "_resolved_addresses", lambda _h, _p: {"172.16.0.1"})
    backend = PinnedAsyncNetworkBackend(proxy="http://bridge.example:7890")
    connections = []
    stream = object()

    async def connect(address, port, **_kwargs):
        connections.append((address, port))
        return stream

    monkeypatch.setattr(backend._backend, "connect_tcp", connect)
    assert await backend.connect_tcp("bridge.example", 7890) is stream
    assert connections == [("172.16.0.1", 7890)]
    with pytest.raises(AppError) as caught:
        await backend.connect_tcp("other.example", 7890)
    assert caught.value.code == "BLOCKED_ADDRESS"


@pytest.mark.parametrize("scheme", ["http", "https"])
async def test_link_resolver_actually_uses_private_proxy_with_fake_target_dns(
    monkeypatch: pytest.MonkeyPatch, test_settings, scheme: str
):
    test_settings.ytdlp_proxy = "http://172.16.0.1:7890"
    monkeypatch.setattr(security, "_resolved_addresses", lambda _h, _p: {"2001::1"})
    monkeypatch.setenv("NO_PROXY", "*")
    transport = SSRFSafeAsyncHTTPTransport()
    assert isinstance(transport._pool, httpcore.AsyncHTTPProxy)
    connections = []
    writes: list[bytes] = []
    tls_hosts = []

    class ProxyStream:
        def __init__(self):
            self.request = b""

        async def read(self, max_bytes, timeout=None):
            if self.request.startswith(b"CONNECT "):
                self.request = b""
                return b"HTTP/1.1 200 Connection established\r\n\r\n"
            if b"/short " in self.request:
                return b"HTTP/1.1 302 Found\r\nLocation: /final\r\nContent-Length: 0\r\n\r\n"
            return b"HTTP/1.1 200 OK\r\nContent-Length: 0\r\n\r\n"

        async def write(self, buffer, timeout=None):
            writes.append(buffer)
            if buffer.startswith((b"CONNECT ", b"HEAD ")):
                self.request = buffer

        async def aclose(self):
            pass

        async def start_tls(self, ssl_context, server_hostname=None, timeout=None):
            tls_hosts.append(server_hostname)
            return self

        def get_extra_info(self, _name):
            return None

    async def connect(host, port, **_kwargs):
        connections.append((host, port))
        return ProxyStream()

    monkeypatch.setattr(transport._pool._network_backend._backend, "connect_tcp", connect)
    resolver = LinkResolver(max_redirects=3, transport=transport)
    assert await resolver.resolve(f"{scheme}://www.youtube.com/short") == (
        f"{scheme}://www.youtube.com/final"
    )
    assert connections and set(connections) == {("172.16.0.1", 7890)}
    if scheme == "https":
        assert writes[0].startswith(b"CONNECT www.youtube.com:443 HTTP/1.1\r\n")
        assert tls_hosts and set(tls_hosts) == {"www.youtube.com"}
    else:
        assert writes[0].startswith(b"HEAD http://www.youtube.com/short HTTP/1.1\r\n")


@pytest.mark.parametrize("private_target", ["172.16.0.1:7890", "172.16.0.2", "169.254.169.254"])
async def test_proxy_does_not_allow_private_redirects(
    monkeypatch: pytest.MonkeyPatch, test_settings, private_target: str
):
    test_settings.ytdlp_proxy = "http://172.16.0.1:7890"
    monkeypatch.setattr(security, "_resolved_addresses", lambda _h, _p: {"2001::1"})
    requests = []

    def handler(request):
        requests.append(request.url)
        return httpx.Response(302, headers={"Location": f"http://{private_target}/admin"})

    resolver = LinkResolver(max_redirects=3, transport=httpx.MockTransport(handler))
    with pytest.raises(AppError) as caught:
        await resolver.resolve("https://public.example/short")
    assert caught.value.code == "BLOCKED_ADDRESS"
    assert len(requests) == 1


async def test_transport_cannot_use_proxy_exception_to_fetch_proxy_as_target(test_settings):
    test_settings.ytdlp_proxy = "http://172.16.0.1:7890"
    async with SSRFSafeAsyncHTTPTransport() as transport:
        with pytest.raises(AppError) as caught:
            await transport.handle_async_request(httpx.Request("GET", "http://172.16.0.1:7890/"))
    assert caught.value.code == "BLOCKED_ADDRESS"
