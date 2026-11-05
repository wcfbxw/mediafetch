import json
import re
from collections.abc import Mapping
from typing import Any
from urllib.parse import urlencode, urlsplit

from yt_dlp.networking.common import Request

from app.services.douyin_web_signature import pick_uifid, sign_detail_query

OFFICIAL_DOUYIN_FORMAT_ID = "mediafetch-douyin-official-1080p"
DOUYIN_DESKTOP_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/143.0.0.0 Safari/537.36"
)
DOUYIN_MOBILE_USER_AGENT = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.0 "
    "Mobile/15E148 Safari/604.1"
)
DOUYIN_WEB_DETAIL_URL = "https://www.douyin.com/aweme/v1/web/aweme/detail/"
_VIDEO_ID_PATH = re.compile(r"/(?:video|share/video)/(\d+)(?:[/?#]|$)", re.IGNORECASE)
_ROUTER_DATA_MARKER = re.compile(r"window\._ROUTER_DATA\s*=", re.IGNORECASE)


class DouyinOfficialPlaybackUnavailable(Exception):
    """The official share page did not contain a usable playback URI."""


def is_official_share_url(source_url: str) -> bool:
    parsed = urlsplit(source_url)
    hostname = (parsed.hostname or "").lower().rstrip(".")
    return hostname in {"iesdouyin.com", "www.iesdouyin.com"} and bool(
        _VIDEO_ID_PATH.search(parsed.path)
    )


def _video_id(source_url: str, info: Mapping[str, Any]) -> str:
    for candidate_url in (source_url, info.get("webpage_url")):
        if not isinstance(candidate_url, str):
            continue
        match = _VIDEO_ID_PATH.search(urlsplit(candidate_url).path)
        if match:
            return match.group(1)
    for key in ("id", "aweme_id"):
        candidate = str(info.get(key) or "")
        if candidate.isdigit() and len(candidate) <= 32:
            return candidate
    raise DouyinOfficialPlaybackUnavailable("missing video id")


def _balanced_json_object(page: str, start: int) -> str:
    opening = page.find("{", start)
    if opening < 0:
        raise DouyinOfficialPlaybackUnavailable("missing router data object")
    depth = 0
    in_string = False
    escaped = False
    for index in range(opening, min(len(page), opening + 8_000_000)):
        char = page[index]
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return page[opening : index + 1]
    raise DouyinOfficialPlaybackUnavailable("unterminated router data object")


def parse_router_data(page: str) -> dict[str, Any]:
    if not isinstance(page, str) or not page or len(page) > 10_000_000:
        raise DouyinOfficialPlaybackUnavailable("invalid share page")
    marker = _ROUTER_DATA_MARKER.search(page)
    if marker is None:
        raise DouyinOfficialPlaybackUnavailable("missing router data")
    try:
        value = json.loads(_balanced_json_object(page, marker.end()))
    except (TypeError, ValueError) as exc:
        raise DouyinOfficialPlaybackUnavailable("invalid router data") from exc
    if not isinstance(value, dict):
        raise DouyinOfficialPlaybackUnavailable("invalid router data root")
    return value


def _playback_detail(router_data: Mapping[str, Any], expected_id: str) -> Mapping[str, Any]:
    stack: list[tuple[Any, int]] = [(router_data, 0)]
    fallback: Mapping[str, Any] | None = None
    visited = 0
    while stack:
        value, depth = stack.pop()
        visited += 1
        if visited > 50_000 or depth > 64:
            continue
        if isinstance(value, Mapping):
            video = value.get("video")
            if isinstance(video, Mapping):
                play_addr = video.get("play_addr")
                if isinstance(play_addr, Mapping) and play_addr.get("uri"):
                    identity = str(
                        value.get("aweme_id") or value.get("item_id") or value.get("id") or ""
                    )
                    if identity == expected_id:
                        return value
                    fallback = fallback or value
            stack.extend((child, depth + 1) for child in value.values())
        elif isinstance(value, list):
            stack.extend((child, depth + 1) for child in value)
    if fallback is not None:
        return fallback
    raise DouyinOfficialPlaybackUnavailable("missing official playback uri")


def _positive_int(value: Any) -> int | None:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def _playback_format_from_video(
    video: Mapping[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    play_addr = video.get("play_addr")
    if not isinstance(play_addr, Mapping):
        raise DouyinOfficialPlaybackUnavailable("missing official playback uri")
    playback_uri = str(play_addr.get("uri") or "").strip()
    if not playback_uri or len(playback_uri) > 512 or any(ord(char) < 32 for char in playback_uri):
        raise DouyinOfficialPlaybackUnavailable("invalid official playback uri")

    playback_url = "https://www.iesdouyin.com/aweme/v1/play/?" + urlencode(
        {"video_id": playback_uri, "ratio": "1080p", "line": "0"}
    )
    width = _positive_int(video.get("width"))
    height = _positive_int(video.get("height"))
    duration_ms = _positive_int(video.get("duration"))
    raw_format: dict[str, Any] = {
        "format_id": OFFICIAL_DOUYIN_FORMAT_ID,
        "format_note": "Douyin official playback",
        "url": playback_url,
        "protocol": "https",
        "ext": "mp4",
        "width": width,
        "height": height,
        "vcodec": "h264",
        "acodec": "aac",
        "source_preference": 100,
    }
    if duration_ms and duration_ms >= 1000:
        raw_format["duration"] = duration_ms / 1000
    internal_source = {
        "url": playback_url,
        "http_headers": {
            "Referer": "https://www.douyin.com/",
            "User-Agent": DOUYIN_MOBILE_USER_AGENT,
        },
    }
    return raw_format, internal_source


def build_official_playback(
    source_url: str,
    info: Mapping[str, Any],
    share_page: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    video_id = _video_id(source_url, info)
    detail = _playback_detail(parse_router_data(share_page), video_id)
    video = detail["video"]
    if not isinstance(video, Mapping):
        raise DouyinOfficialPlaybackUnavailable("missing official video")
    return _playback_format_from_video(video)


def _first_public_url(value: Any) -> str | None:
    if not isinstance(value, Mapping):
        return None
    urls = value.get("url_list")
    if not isinstance(urls, list):
        return None
    return next((url for url in urls if isinstance(url, str) and url.startswith("https://")), None)


def _cookie_map(ydl: Any) -> dict[str, str]:
    jar = getattr(ydl, "cookiejar", None)
    if jar is None:
        return {}
    try:
        getter = getattr(jar, "get_cookies_for_url", None)
        cookies = getter("https://www.douyin.com/") if getter else list(jar)
    except Exception:
        try:
            cookies = list(jar)
        except Exception:
            return {}
    return {
        str(cookie.name): str(cookie.value)
        for cookie in cookies
        if getattr(cookie, "value", None)
    }


def _cookie_int(cookies: Mapping[str, str], name: str, fallback: int) -> int:
    value = _positive_int(cookies.get(name))
    return value if value is not None else fallback


def _cookie_header(cookies: Mapping[str, str]) -> str:
    return "; ".join(
        f"{name}={value}"
        for name, value in cookies.items()
        if not any(ord(char) < 32 for char in name + value)
    )


def _fetch_web_detail(ydl: Any, video_id: str) -> dict[str, Any]:
    cookies = _cookie_map(ydl)
    if pick_uifid(cookies) is None:
        raise DouyinOfficialPlaybackUnavailable(
            "douyin session is missing UIFID_TEMP; re-import browser cookies"
        )
    try:
        query, signature_headers = sign_detail_query(
            video_id=video_id,
            user_agent=DOUYIN_DESKTOP_USER_AGENT,
            cookies=cookies,
            screen_width=_cookie_int(cookies, "dy_swidth", 1920),
            screen_height=_cookie_int(cookies, "dy_sheight", 1080),
        )
        request = Request(
            f"{DOUYIN_WEB_DETAIL_URL}?{query}",
            headers={
                "User-Agent": DOUYIN_DESKTOP_USER_AGENT,
                "Referer": "https://www.douyin.com/",
                "Accept": "application/json, text/plain, */*",
                "Accept-Language": "zh-CN,zh;q=0.9",
                "Cookie": _cookie_header(cookies),
                **signature_headers,
            },
        )
        response = ydl.urlopen(request)
        try:
            raw = response.read(2_000_001)
        finally:
            response.close()
    except DouyinOfficialPlaybackUnavailable:
        raise
    except Exception as exc:
        raise DouyinOfficialPlaybackUnavailable(
            f"douyin web detail request failed ({type(exc).__name__})"
        ) from exc

    if len(raw) > 2_000_000:
        raise DouyinOfficialPlaybackUnavailable("douyin web detail response is too large")
    try:
        payload = json.loads(raw.decode("utf-8", "replace"))
    except (UnicodeDecodeError, TypeError, ValueError) as exc:
        raise DouyinOfficialPlaybackUnavailable("invalid douyin web detail response") from exc
    if not isinstance(payload, Mapping):
        raise DouyinOfficialPlaybackUnavailable("invalid douyin web detail response")
    detail = payload.get("aweme_detail")
    if not isinstance(detail, Mapping):
        status = payload.get("status_code")
        raise DouyinOfficialPlaybackUnavailable(f"douyin web detail unavailable (status {status})")
    detail_id = str(detail.get("aweme_id") or "")
    if detail_id and detail_id != video_id:
        raise DouyinOfficialPlaybackUnavailable("douyin web detail returned another video")
    return dict(detail)


def _fetch_share_page(ydl: Any, video_id: str) -> str:
    share_url = f"https://www.iesdouyin.com/share/video/{video_id}"
    response = ydl.urlopen(
        Request(
            share_url,
            headers={
                "User-Agent": DOUYIN_MOBILE_USER_AGENT,
                "Referer": "https://www.douyin.com/",
            },
        )
    )
    try:
        return response.read(10_000_001).decode("utf-8", "replace")
    finally:
        response.close()


def _info_from_detail(
    source_url: str,
    video_id: str,
    detail: Mapping[str, Any],
) -> dict[str, Any]:
    video_value = detail.get("video")
    author_value = detail.get("author")
    video: Mapping[str, Any] = video_value if isinstance(video_value, Mapping) else {}
    author: Mapping[str, Any] = author_value if isinstance(author_value, Mapping) else {}
    raw_format, internal_source = _playback_format_from_video(video)
    duration_ms = _positive_int(video.get("duration"))
    title = str(detail.get("desc") or "Douyin video").strip()[:300] or "Douyin video"
    webpage_url = (
        f"https://www.iesdouyin.com/share/video/{video_id}"
        if is_official_share_url(source_url)
        else f"https://www.douyin.com/video/{video_id}"
    )
    return {
        "id": video_id,
        "title": title,
        "description": title,
        "uploader": str(author.get("nickname") or "").strip()[:200] or None,
        "duration": duration_ms / 1000 if duration_ms else None,
        "thumbnail": _first_public_url(video.get("cover")),
        "webpage_url": webpage_url,
        "extractor": "mediafetch:douyin:official",
        "extractor_key": "MediaFetchDouyinOfficial",
        "formats": [raw_format],
        "_mediafetch_direct_formats": {OFFICIAL_DOUYIN_FORMAT_ID: internal_source},
    }


def extract_official_douyin_info(ydl: Any, source_url: str) -> dict[str, Any]:
    """Build a complete fallback result from Douyin's official share-page data."""

    video_id = _video_id(source_url, {})
    try:
        detail = _fetch_web_detail(ydl, video_id)
    except DouyinOfficialPlaybackUnavailable as web_error:
        try:
            share_page = _fetch_share_page(ydl, video_id)
            detail = _playback_detail(parse_router_data(share_page), video_id)
        except DouyinOfficialPlaybackUnavailable:
            raise web_error from None
        except Exception:
            raise web_error from None
    return _info_from_detail(source_url, video_id, detail)


def add_official_playback_format(ydl: Any, source_url: str, info: dict[str, Any]) -> bool:
    """Append one server-generated official playback candidate to a yt-dlp result."""

    video_id = _video_id(source_url, info)
    try:
        detail = _fetch_web_detail(ydl, video_id)
    except DouyinOfficialPlaybackUnavailable as web_error:
        try:
            page = _fetch_share_page(ydl, video_id)
            detail = _playback_detail(parse_router_data(page), video_id)
        except DouyinOfficialPlaybackUnavailable:
            raise web_error from None
        except Exception:
            raise web_error from None
    video = detail.get("video")
    if not isinstance(video, Mapping):
        raise DouyinOfficialPlaybackUnavailable("missing official video")
    raw_format, internal_source = _playback_format_from_video(video)

    formats = info.setdefault("formats", [])
    if not isinstance(formats, list):
        raise DouyinOfficialPlaybackUnavailable("invalid extractor formats")
    formats[:] = [
        item
        for item in formats
        if not isinstance(item, Mapping)
        or item.get("format_id") != OFFICIAL_DOUYIN_FORMAT_ID
    ]
    formats.append(raw_format)
    info.setdefault("_mediafetch_direct_formats", {})[OFFICIAL_DOUYIN_FORMAT_ID] = internal_source
    return True
