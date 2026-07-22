import httpx
import pytest

from app.core import security
from app.core.errors import AppError
from app.services import link_resolver
from app.services.link_resolver import LinkResolver, PinnedAsyncNetworkBackend


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
