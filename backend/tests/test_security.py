import pytest

from app.core import security
from app.core.errors import AppError
from app.services.extractor import ValidatingRedirectHandler


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
