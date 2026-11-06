import http.client
import io
import socket
import ssl

import pytest
from yt_dlp.networking import Request as YtdlpRequest

from app.core import security
from app.core.errors import AppError
from app.services import extractor
from app.services.extractor import (
    SafeYoutubeDL,
    ValidatingRedirectHandler,
    _create_pinned_connection,
)


def test_public_url_validation(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(security, "_resolved_addresses", lambda _host, _port: {"8.8.8.8"})
    assert security.validate_public_url_sync("https://video.example/watch?v=1") == (
        "https://video.example/watch?v=1"
    )


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1/video",
        "http://10.1.2.3/video",
        "http://172.16.2.3/video",
        "http://192.168.1.2/video",
        "http://169.254.169.254/latest/meta-data",
        "http://localhost/video",
        "file:///etc/passwd",
        "ftp://example.com/file",
        "data:text/plain,hello",
        "C:\\Windows\\system.ini",
    ],
)
def test_private_and_non_http_addresses_are_blocked(url: str):
    with pytest.raises(AppError) as caught:
        security.validate_public_url_sync(url)
    assert caught.value.code in {"BLOCKED_ADDRESS", "INVALID_URL"}


@pytest.mark.parametrize(
    "url",
    [
        "http://[::1]/",
        "http://[fc00::1]/",
        "http://[fe80::1]/",
        "http://[::]/",
    ],
)
def test_private_ipv6_is_blocked(url: str):
    with pytest.raises(AppError) as caught:
        security.validate_public_url_sync(url)
    assert caught.value.code == "BLOCKED_ADDRESS"


def test_all_dns_answers_are_checked(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(
        security,
        "_resolved_addresses",
        lambda _host, _port: {"8.8.8.8", "192.168.1.50"},
    )
    with pytest.raises(AppError) as caught:
        security.validate_public_url_sync("https://rebind.example/video")
    assert caught.value.code == "BLOCKED_ADDRESS"


@pytest.mark.asyncio
async def test_redirect_to_private_ip_is_blocked(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(security, "_resolved_addresses", lambda _host, _port: {"8.8.8.8"})
    monkeypatch.setattr(
        security,
        "_probe_redirect",
        lambda _url: "http://127.0.0.1/admin",
    )
    with pytest.raises(AppError) as caught:
        await security.validate_redirect_chain("https://public.example/video")
    assert caught.value.code == "BLOCKED_ADDRESS"


def test_ytdlp_transport_rechecks_redirect_target():
    class Request:
        full_url = "https://public.example/video"

    with pytest.raises(AppError) as caught:
        ValidatingRedirectHandler().redirect_request(
            Request(),
            None,
            302,
            "Found",
            {},
            "http://127.0.0.1/private",
        )
    assert caught.value.code == "BLOCKED_ADDRESS"


@pytest.mark.parametrize("proxy", ["", "http://172.16.0.1:7890"])
@pytest.mark.parametrize("address", ["2001::1", "198.18.0.1", "172.16.2.3"])
def test_only_proxied_public_hostnames_skip_local_dns(
    monkeypatch: pytest.MonkeyPatch, test_settings, proxy: str, address: str
):
    test_settings.ytdlp_proxy = proxy
    lookups: list[str] = []

    def resolve(host, _port):
        lookups.append(host)
        return {address}

    monkeypatch.setattr(security, "_resolved_addresses", resolve)
    url = "https://www.youtube.com/watch?v=test"
    if proxy:
        assert security.validate_public_url_sync(url) == url
        assert not lookups
    else:
        with pytest.raises(AppError) as caught:
            security.validate_public_url_sync(url)
        assert caught.value.code == "BLOCKED_ADDRESS"
        assert lookups == ["www.youtube.com"]


@pytest.mark.parametrize(
    "target",
    [
        "127.0.0.1", "10.0.0.1", "172.16.0.1:7890", "172.16.2.3:7890",
        "169.254.169.254", "[::1]", "[fe80::1]", "[2001::1]",
        "localhost", "metadata.google.internal", "router.local", "service.internal",
        "2130706433", "127.1", "0x7f000001", "0177.0.0.1",
    ],
)
def test_proxy_does_not_authorize_private_targets(test_settings, target: str):
    test_settings.ytdlp_proxy = "http://172.16.0.1:7890"
    with pytest.raises(AppError) as caught:
        security.validate_public_url_sync(f"http://{target}/private")
    assert caught.value.code == "BLOCKED_ADDRESS"


@pytest.mark.parametrize(
    ("proxy", "host", "port", "allowed"),
    [
        (None, "172.16.0.1", 7890, False),
        ("http://172.16.0.1:7890", "172.16.0.1", 7890, True),
        ("http://172.16.0.1:7890", "172.16.0.2", 7890, False),
        ("http://172.16.0.1:7890", "172.16.0.1", 80, False),
        ("http://bridge.example:7890", "bridge.example", 7890, True),
    ],
)
def test_safe_urllib_pins_only_the_configured_private_proxy(
    monkeypatch: pytest.MonkeyPatch, test_settings, proxy, host, port, allowed
):
    test_settings.ytdlp_proxy = proxy
    monkeypatch.setattr(extractor, "_resolved_addresses", lambda _h, _p: {"172.16.0.1"})
    connections: list[tuple[str, int]] = []
    sock = object()

    def connect(address, **_kwargs):
        connections.append(address)
        return sock

    monkeypatch.setattr(socket, "create_connection", connect)
    if not allowed:
        with pytest.raises(AppError) as caught:
            _create_pinned_connection(http.client.HTTPConnection, None, host, port)
        assert caught.value.code == "BLOCKED_ADDRESS"
        assert not connections
        return
    connection = _create_pinned_connection(http.client.HTTPConnection, None, host, port)
    assert connection._create_connection((host, port)) is sock
    assert connections == [("172.16.0.1", port)]


@pytest.mark.parametrize("scheme", ["http", "https"])
@pytest.mark.parametrize("preflight", [False, True])
def test_safe_ytdlp_uses_private_proxy_without_resolving_target(
    monkeypatch: pytest.MonkeyPatch, test_settings, scheme: str, preflight: bool
):
    test_settings.ytdlp_proxy = "http://172.16.0.1:7890"
    monkeypatch.setattr(security, "_resolved_addresses", lambda _h, _p: {"2001::1"})
    lookups: list[tuple[str, int]] = []
    connections: list[tuple[str, int]] = []
    requests: list[bytes] = []
    tls_hosts = []

    def resolve(host, port):
        lookups.append((host, port))
        assert (host, port) == ("172.16.0.1", 7890)
        return {"172.16.0.1"}

    class ProxySocket:
        def __init__(self):
            self.tunnel_pending = scheme == "https"

        def setsockopt(self, *_args):
            pass

        def sendall(self, data):
            requests.append(data)

        def makefile(self, *_args):
            if self.tunnel_pending:
                self.tunnel_pending = False
                return io.BytesIO(b"HTTP/1.1 200 Connection established\r\n\r\n")
            return io.BytesIO(b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\n\r\nok")

        def close(self):
            pass

    def connect(address, **_kwargs):
        connections.append(address)
        return ProxySocket()

    monkeypatch.setattr(extractor, "_resolved_addresses", resolve)
    monkeypatch.setattr(socket, "create_connection", connect)

    def wrap_socket(_context, sock, *, server_hostname, **_kwargs):
        tls_hosts.append(server_hostname)
        return sock

    monkeypatch.setattr(ssl.SSLContext, "wrap_socket", wrap_socket)
    # Even a system-wide bypass must not route a DNS-unchecked target directly.
    monkeypatch.setattr("urllib.request.proxy_bypass", lambda _host: True)
    url = f"{scheme}://www.youtube.com/watch?v=test"
    if preflight:
        assert security._probe_redirect(url) is None
    else:
        with SafeYoutubeDL({"quiet": True}) as ydl:
            response = ydl.urlopen(YtdlpRequest(url, proxies={"all": None}))
            try:
                assert response.read() == b"ok"
            finally:
                response.close()
    assert lookups == connections == [("172.16.0.1", 7890)]
    method = b"HEAD" if preflight else b"GET"
    if scheme == "https":
        assert requests[0].startswith(b"CONNECT www.youtube.com:443 HTTP/1.")
        assert requests[1].startswith(method + b" /watch?v=test HTTP/1.1\r\n")
        assert tls_hosts == ["www.youtube.com"]
    else:
        assert requests[0].startswith(method + b" http://www.youtube.com/watch?v=test HTTP/1.1\r\n")


def test_safe_ytdlp_disables_ambient_proxies_without_ytdlp_proxy(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setenv("HTTP_PROXY", "http://172.16.0.2:7890")
    monkeypatch.setenv("HTTPS_PROXY", "http://172.16.0.2:7890")
    with SafeYoutubeDL({"quiet": True}) as ydl:
        assert ydl.proxies == {"all": "__noproxy__"}


def test_proxy_redirect_validator_still_blocks_private_targets(test_settings):
    test_settings.ytdlp_proxy = "http://172.16.0.1:7890"
    request = type("Request", (), {"full_url": "https://public.example/video"})()
    with pytest.raises(AppError) as caught:
        ValidatingRedirectHandler().redirect_request(
            request, None, 302, "Found", {}, "http://172.16.0.1:7890/admin"
        )
    assert caught.value.code == "BLOCKED_ADDRESS"


def test_proxy_hostname_is_not_allowed_as_a_user_target(test_settings):
    test_settings.ytdlp_proxy = "http://bridge.example:7890"
    with pytest.raises(AppError) as caught:
        security.validate_public_url_sync("http://bridge.example:7890/admin")
    assert caught.value.code == "BLOCKED_ADDRESS"
