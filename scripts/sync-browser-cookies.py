#!/usr/bin/env python3
"""Synchronize only allowlisted platform cookies from a local Chromium profile."""

import argparse
import os
import sqlite3
import sys
import tempfile
import time
from collections import defaultdict
from http.cookiejar import Cookie
from pathlib import Path
from typing import Any

import httpx
from yt_dlp.cookies import (
    _find_files,
    _get_chromium_based_browser_settings,
    _get_column_names,
    _newest,
    _open_database_copy,
    _process_chrome_cookie,
    get_cookie_decryptor,
)

PLATFORM_DOMAINS: dict[str, tuple[str, ...]] = {
    "douyin": ("douyin.com", "iesdouyin.com"),
    "instagram": ("instagram.com",),
    "youtube": ("youtube.com", "google.com"),
}
MAX_COOKIE_FILE_BYTES = 128 * 1024


class QuietLogger:
    """Prevent profile paths and cookie internals from reaching terminal logs."""

    def debug(self, _message: str) -> None:
        return None

    def info(self, _message: str) -> None:
        return None

    def warning(self, _message: str) -> None:
        return None

    def error(self, _message: str) -> None:
        return None


def _matches_domain(hostname: str, domains: tuple[str, ...]) -> bool:
    host = hostname.lstrip(".").lower().rstrip(".")
    return any(host == domain or host.endswith(f".{domain}") for domain in domains)


def _cookie_database(browser_name: str, profile: str | None) -> tuple[dict[str, Any], Path]:
    config = _get_chromium_based_browser_settings(browser_name)
    if profile:
        candidate = Path(profile).expanduser()
        if candidate.exists():
            search_root = str(candidate)
            config["browser_dir"] = str(candidate.parent)
        elif config["supports_profiles"]:
            search_root = str(Path(config["browser_dir"]) / profile)
        else:
            raise RuntimeError("This browser does not support named profiles")
    else:
        search_root = config["browser_dir"]
    database = _newest(_find_files(search_root, "Cookies", QuietLogger()))
    if database is None:
        raise RuntimeError("No Chromium cookie database was found")
    return config, Path(database)


def _targeted_query() -> tuple[str, list[str]]:
    domains = sorted({domain for values in PLATFORM_DOMAINS.values() for domain in values})
    clauses: list[str] = []
    parameters: list[str] = []
    for domain in domains:
        clauses.append("(host_key = ? OR host_key = ? OR host_key LIKE ?)")
        parameters.extend((domain, f".{domain}", f"%.{domain}"))
    return " OR ".join(clauses), parameters


def extract_target_cookies(
    browser_name: str,
    profile: str | None = None,
) -> dict[str, list[Cookie]]:
    config, database = _cookie_database(browser_name, profile)
    selected: dict[str, list[Cookie]] = defaultdict(list)
    with tempfile.TemporaryDirectory(prefix="mediafetch-cookie-sync-") as temporary:
        cursor: sqlite3.Cursor | None = None
        try:
            cursor = _open_database_copy(str(database), temporary)
            metadata = cursor.execute('SELECT value FROM meta WHERE key = "version"').fetchone()
            meta_version = int(metadata[0]) if metadata else 0
            decryptor = get_cookie_decryptor(
                config["browser_dir"],
                config["keyring_name"],
                QuietLogger(),
                meta_version=meta_version,
            )
            cursor.connection.text_factory = bytes
            columns = _get_column_names(cursor, "cookies")
            secure_column = "is_secure" if "is_secure" in columns else "secure"
            where, parameters = _targeted_query()
            cursor.execute(
                "SELECT host_key, name, value, encrypted_value, path, expires_utc, "
                f"{secure_column} FROM cookies WHERE {where}",
                parameters,
            )
            now = int(time.time())
            for row in cursor.fetchall():
                _encrypted, cookie = _process_chrome_cookie(decryptor, *row)
                if not cookie or not cookie.value:
                    continue
                if cookie.expires is not None and cookie.expires <= now:
                    continue
                for platform, domains in PLATFORM_DOMAINS.items():
                    if _matches_domain(cookie.domain, domains):
                        selected[platform].append(cookie)
                        break
        finally:
            if cursor is not None:
                cursor.connection.close()
    return {platform: selected.get(platform, []) for platform in PLATFORM_DOMAINS}


def netscape_cookie_bytes(cookies: list[Cookie]) -> bytes:
    lines = ["# Netscape HTTP Cookie File", "# Generated locally for MediaFetch"]
    for cookie in cookies:
        fields = (cookie.domain, cookie.path, cookie.name, cookie.value)
        if any("\t" in field or "\r" in field or "\n" in field for field in fields):
            raise RuntimeError("A selected cookie contains invalid control characters")
        domain = cookie.domain
        rest = {str(key).lower() for key in getattr(cookie, "_rest", {})}
        if "httponly" in rest:
            domain = f"#HttpOnly_{domain}"
        lines.append(
            "\t".join(
                (
                    domain,
                    "TRUE" if cookie.domain_initial_dot or cookie.domain.startswith(".") else "FALSE",
                    cookie.path or "/",
                    "TRUE" if cookie.secure else "FALSE",
                    str(int(cookie.expires or 0)),
                    cookie.name,
                    cookie.value,
                )
            )
        )
    content = ("\n".join(lines) + "\n").encode("utf-8")
    if len(content) > MAX_COOKIE_FILE_BYTES:
        raise RuntimeError("Selected platform cookies exceed the server's 128 KiB limit")
    return content


def upload_cookies(base_url: str, admin_token: str, platform: str, content: bytes) -> bool:
    url = f"{base_url.rstrip('/')}/api/v1/admin/platforms/{platform}/cookies"
    with httpx.Client(timeout=30, follow_redirects=False) as client:
        response = client.put(
            url,
            headers={"X-Admin-Token": admin_token},
            files={"file": (f"{platform}-cookies.txt", content, "text/plain")},
        )
    if response.status_code != 200:
        raise RuntimeError(f"Server rejected {platform} cookies with HTTP {response.status_code}")
    body = response.json()
    return bool(body.get("configured"))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--browser", default="chrome", choices=("chrome", "edge", "chromium", "brave"))
    parser.add_argument("--profile", help="Optional Chromium profile name or absolute profile directory")
    parser.add_argument(
        "--base-url",
        default="https://mnzo.de",
        help="MediaFetch public origin",
    )
    parser.add_argument("--dry-run", action="store_true", help="Only report selected cookie counts")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        selected = extract_target_cookies(args.browser, args.profile)
    except Exception as exc:
        print(f"Chrome Cookie 提取失败：{type(exc).__name__}", file=sys.stderr)
        return 1

    for platform, cookies in selected.items():
        print(f"{platform}: {len(cookies)} 个目标域名 Cookie")
    if args.dry_run:
        return 0

    token = os.environ.get("MEDIAFETCH_ADMIN_TOKEN", "").strip()
    if len(token) < 32:
        print("缺少 MEDIAFETCH_ADMIN_TOKEN", file=sys.stderr)
        return 2
    uploaded = 0
    for platform, cookies in selected.items():
        if not cookies:
            print(f"{platform}: 跳过（本机没有登录会话）")
            continue
        try:
            configured = upload_cookies(
                args.base_url,
                token,
                platform,
                netscape_cookie_bytes(cookies),
            )
        except Exception as exc:
            print(f"{platform}: 上传失败（{exc}）", file=sys.stderr)
            continue
        print(f"{platform}: {'同步成功' if configured else '服务器未接受会话'}")
        uploaded += int(configured)
    return 0 if uploaded else 3


if __name__ == "__main__":
    raise SystemExit(main())
