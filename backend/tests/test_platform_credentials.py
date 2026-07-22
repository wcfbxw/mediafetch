import os
from http.cookiejar import Cookie, CookieJar
from pathlib import Path

from app.services.extractor import SafeYoutubeDL
from app.services.platform_credentials import (
    bilibili_session_status,
    clear_bilibili_session,
    configure_ytdlp_credentials,
    platform_cookie_file,
    platform_session_status,
    save_bilibili_cookies,
    save_platform_cookie_file,
)


def make_cookie(name: str, value: str, domain: str = ".bilibili.com") -> Cookie:
    return Cookie(
        version=0,
        name=name,
        value=value,
        port=None,
        port_specified=False,
        domain=domain,
        domain_specified=True,
        domain_initial_dot=domain.startswith("."),
        path="/",
        path_specified=True,
        secure=True,
        expires=4_102_444_800,
        discard=False,
        comment=None,
        comment_url=None,
        rest={},
    )


def test_bilibili_cookie_is_saved_and_only_injected_for_bilibili(test_settings):
    jar = CookieJar()
    jar.set_cookie(make_cookie("SESSDATA", "session-value"))
    jar.set_cookie(make_cookie("ignored", "secret", ".example.com"))
    save_bilibili_cookies(jar)

    status = bilibili_session_status()
    assert status["configured"] is True
    if os.name != "nt":
        assert test_settings.bilibili_cookie_file.stat().st_mode & 0o777 == 0o600

    bili_options = {}
    configure_ytdlp_credentials(bili_options, "https://www.bilibili.com/video/BV1abc")
    assert bili_options["cookiefile"] == str(test_settings.bilibili_cookie_file.resolve())
    assert "User-Agent" in bili_options["http_headers"]

    other_options = {}
    configure_ytdlp_credentials(other_options, "https://example.com/video")
    assert other_options == {}


def test_clearing_bilibili_session(test_settings):
    jar = CookieJar()
    jar.set_cookie(make_cookie("SESSDATA", "session-value"))
    save_bilibili_cookies(jar)
    clear_bilibili_session()
    assert bilibili_session_status()["configured"] is False
    assert not test_settings.bilibili_cookie_file.exists()


def test_admin_platform_cookie_file_is_domain_scoped_and_injected():
    content = (
        b"# Netscape HTTP Cookie File\n"
        b".instagram.com\tTRUE\t/\tTRUE\t4102444800\tsessionid\tsecret-value\n"
    )
    result = save_platform_cookie_file("instagram", content)

    assert result["configured"] is True
    assert platform_session_status("instagram")["configured"] is True
    options = {}
    configure_ytdlp_credentials(options, "https://www.instagram.com/reel/example/")
    assert options["cookiefile"] == str(platform_cookie_file("instagram"))
    assert options["http_headers"]["Referer"] == "https://www.instagram.com/"


def test_admin_platform_cookie_file_rejects_unrelated_domains():
    content = (
        b"# Netscape HTTP Cookie File\n"
        b".example.com\tTRUE\t/\tTRUE\t4102444800\tsessionid\tsecret-value\n"
    )

    try:
        save_platform_cookie_file("instagram", content)
    except Exception as exc:
        assert getattr(exc, "code", None) == "INVALID_COOKIE_FILE"
    else:
        raise AssertionError("unrelated cookie domain was accepted")


def test_managed_cookie_is_copied_to_a_private_per_operation_snapshot():
    content = (
        b"# Netscape HTTP Cookie File\n"
        b".youtube.com\tTRUE\t/\tTRUE\t4102444800\tSID\tsecret-value\n"
    )
    save_platform_cookie_file("youtube", content)
    managed = platform_cookie_file("youtube")
    original = managed.read_bytes()
    options = {}
    configure_ytdlp_credentials(options, "https://www.youtube.com/watch?v=example")

    ydl = SafeYoutubeDL({**options, "quiet": True})
    snapshot = Path(ydl.params["cookiefile"])
    assert snapshot != managed
    assert snapshot.read_bytes() == original
    ydl.close()

    assert not snapshot.exists()
    assert managed.read_bytes() == original
