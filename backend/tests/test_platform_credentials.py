import os
from http.cookiejar import Cookie, CookieJar, MozillaCookieJar
from pathlib import Path

import pytest

from app.core.errors import AppError
from app.services.extractor import SafeYoutubeDL
from app.services.platform_credentials import (
    MAX_COOKIE_FILE_BYTES,
    bilibili_session_status,
    clear_bilibili_session,
    configure_ytdlp_credentials,
    platform_cookie_file,
    platform_session_status,
    save_bilibili_cookies,
    save_platform_cookie_file,
)


def cookie_export(*rows: str) -> bytes:
    return ("# Netscape HTTP Cookie File\n" + "\n".join(rows) + "\n").encode("utf-8")


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


def test_douyin_import_filters_mixed_browser_export_and_keeps_live_platform_rows():
    content = cookie_export(
        ".bytedance.com\tTRUE\t/\tTRUE\t4102444800\ttracking\ttest-only",
        "#HttpOnly_.douyin.com\tTRUE\t/\tTRUE\t4102444800\tsessionid\ttest-only",
        "v.douyin.com\tFALSE\t/\tFALSE\t0\tsession\ttest-only",
        ".iesdouyin.com\tTRUE\t/\tTRUE\t4102444800\tshare\ttest-only",
        ".douyin.com\tTRUE\t/\tTRUE\t1\texpired\ttest-only",
        ".youtube.com\tTRUE\t/\tTRUE\t4102444800\tunrelated\ttest-only",
        ".douyin.com.evil.example\tTRUE\t/\tTRUE\t4102444800\tspoofed\ttest-only",
    )

    result = save_platform_cookie_file("douyin", b"\xef\xbb\xbf" + content.replace(b"\n", b"\r\n"))

    assert result["configured"] is True
    assert result["cookie_count"] == 3
    saved = MozillaCookieJar(str(platform_cookie_file("douyin")))
    saved.load(ignore_discard=True, ignore_expires=True)
    assert {(cookie.domain, cookie.name) for cookie in saved} == {
        (".douyin.com", "sessionid"),
        ("v.douyin.com", "session"),
        (".iesdouyin.com", "share"),
    }
    session_cookie = next(cookie for cookie in saved if cookie.name == "session")
    assert session_cookie.expires is None
    http_only_cookie = next(cookie for cookie in saved if cookie.name == "sessionid")
    assert http_only_cookie.has_nonstandard_attr("HTTPOnly")


@pytest.mark.parametrize(
    "domain", [".xiaohongshu.com", "www.xiaohongshu.com", ".edith.xiaohongshu.com"]
)
def test_xiaohongshu_import_accepts_extractor_page_domains_and_injects_credentials(domain):
    include_subdomains = "TRUE" if domain.startswith(".") else "FALSE"
    result = save_platform_cookie_file(
        "xiaohongshu",
        cookie_export(
            f"{domain}\t{include_subdomains}\t/\tTRUE\t4102444800\tweb_session\ttest-only"
        ),
    )

    assert result["configured"] is True
    assert result["cookie_count"] == 1
    options = {}
    configure_ytdlp_credentials(
        options, "https://www.xiaohongshu.com/explore/64b7f1234567890123456789"
    )
    assert options["cookiefile"] == str(platform_cookie_file("xiaohongshu"))
    assert options["http_headers"]["Referer"] == "https://www.xiaohongshu.com/"

    for url in (
        "https://www.youtube.com/watch?v=example",
        "https://www.xiaohongshu.com.evil.example/video",
        "https://xhslink.com/example",
        "https://sns-video-bd.xhscdn.com/video.mp4",
    ):
        other_options = {}
        configure_ytdlp_credentials(other_options, url)
        assert "cookiefile" not in other_options


@pytest.mark.parametrize(
    ("platform", "domain"),
    [
        ("douyin", ".douyin.com.evil.example"),
        ("douyin", ".notdouyin.com"),
        ("douyin", ".bytedance.com"),
        ("xiaohongshu", ".xiaohongshu.com.evil.example"),
        ("xiaohongshu", ".notxiaohongshu.com"),
        ("xiaohongshu", ".douyin.com"),
        ("xiaohongshu", ".xhslink.com"),
        ("xiaohongshu", ".xhscdn.com"),
    ],
)
def test_import_requires_at_least_one_allowed_domain(platform, domain):
    with pytest.raises(AppError) as caught:
        save_platform_cookie_file(
            platform,
            cookie_export(f"{domain}\tTRUE\t/\tTRUE\t4102444800\tsession\ttest-only"),
        )

    assert caught.value.code == "INVALID_COOKIE_FILE"
    assert not platform_cookie_file(platform).exists()


def test_xiaohongshu_import_drops_short_link_cdn_and_unrelated_cookie_rows():
    content = cookie_export(
        ".xiaohongshu.com\tTRUE\t/\tTRUE\t4102444800\tweb_session\ttest-only",
        ".xhslink.com\tTRUE\t/\tTRUE\t4102444800\tshort_link\ttest-only",
        ".xhscdn.com\tTRUE\t/\tTRUE\t4102444800\tcdn\ttest-only",
        ".instagram.com\tTRUE\t/\tTRUE\t4102444800\tunrelated\ttest-only",
    )

    result = save_platform_cookie_file("xiaohongshu", content)

    assert result["cookie_count"] == 1
    saved = MozillaCookieJar(str(platform_cookie_file("xiaohongshu")))
    saved.load()
    assert {cookie.domain for cookie in saved} == {".xiaohongshu.com"}


def test_import_skips_empty_name_rows_without_rejecting_the_file():
    content = cookie_export(
        ".douyin.com\tTRUE\t/\tTRUE\t4102444800\tsessionid\ttest-only",
        ".douyin.com\tTRUE\t/\tTRUE\t4102444800\t\ttest-only",
        ".douyin.com\tTRUE\t/\tTRUE\t4102444800\tttwid\ttest-only",
    )

    result = save_platform_cookie_file("douyin", content)

    assert result["cookie_count"] == 2
    saved = MozillaCookieJar(str(platform_cookie_file("douyin")))
    saved.load()
    assert {(cookie.domain, cookie.name) for cookie in saved} == {
        (".douyin.com", "sessionid"),
        (".douyin.com", "ttwid"),
    }


def test_import_rejects_file_with_only_empty_name_rows():
    with pytest.raises(AppError) as caught:
        save_platform_cookie_file(
            "douyin",
            cookie_export(".douyin.com\tTRUE\t/\tTRUE\t4102444800\t\ttest-only"),
        )

    assert caught.value.code == "INVALID_COOKIE_FILE"
    assert not platform_cookie_file("douyin").exists()


@pytest.mark.parametrize(
    "platform, domain", [("douyin", ".douyin.com"), ("xiaohongshu", ".xiaohongshu.com")]
)
def test_import_rejects_all_expired_platform_rows_even_with_live_unrelated_rows(platform, domain):
    with pytest.raises(AppError) as caught:
        save_platform_cookie_file(
            platform,
            cookie_export(
                f"{domain}\tTRUE\t/\tTRUE\t1\tsession\ttest-only",
                ".example.com\tTRUE\t/\tTRUE\t4102444800\tunrelated\ttest-only",
            ),
        )

    assert caught.value.code == "INVALID_COOKIE_FILE"
    assert not platform_cookie_file(platform).exists()


@pytest.mark.parametrize(
    "content",
    [
        b"",
        b"# Netscape HTTP Cookie File\n",
        b"\xff",
        b"\x00",
        b"#" * (MAX_COOKIE_FILE_BYTES + 1),
        cookie_export(".douyin.com\tTRUE\t/\tTRUE\t4102444800\tsession"),
        cookie_export(".douyin.com\tINVALID\t/\tTRUE\t4102444800\tsession\ttest-only"),
        cookie_export(".douyin.com\tTRUE\t/\tINVALID\t4102444800\tsession\ttest-only"),
        cookie_export(".douyin.com\tTRUE\tnot-a-path\tTRUE\t4102444800\tsession\ttest-only"),
        cookie_export(".douyin.com\tTRUE\t/\tTRUE\tinvalid\tsession\ttest-only"),
        cookie_export(".douyin.com\tTRUE\t/\tTRUE\t4102444800\tsession\ttest\x01only"),
    ],
    ids=[
        "empty",
        "comments-only",
        "encoding",
        "nul",
        "oversize",
        "columns",
        "subdomains-flag",
        "secure-flag",
        "path",
        "expiry",
        "control-character",
    ],
)
def test_invalid_import_does_not_replace_existing_session(content):
    save_platform_cookie_file(
        "douyin",
        cookie_export(".douyin.com\tTRUE\t/\tTRUE\t4102444800\tsession\ttest-only"),
    )
    target = platform_cookie_file("douyin")
    original = target.read_bytes()

    with pytest.raises(AppError) as caught:
        save_platform_cookie_file("douyin", content)

    assert caught.value.code == "INVALID_COOKIE_FILE"
    assert target.read_bytes() == original


def test_managed_cookie_is_copied_to_a_private_per_operation_snapshot():
    content = (
        b"# Netscape HTTP Cookie File\n.youtube.com\tTRUE\t/\tTRUE\t4102444800\tSID\tsecret-value\n"
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
