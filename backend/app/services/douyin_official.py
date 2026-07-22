import json
import re
from collections.abc import Mapping
from typing import Any
from urllib.parse import urlencode, urlsplit

OFFICIAL_DOUYIN_FORMAT_ID = "mediafetch-douyin-official-1080p"
DOUYIN_MOBILE_USER_AGENT = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.0 "
    "Mobile/15E148 Safari/604.1"
)
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


def build_official_playback(
    source_url: str,
    info: Mapping[str, Any],
    share_page: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    video_id = _video_id(source_url, info)
    detail = _playback_detail(parse_router_data(share_page), video_id)
    video = detail["video"]
    play_addr = video["play_addr"]
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


def _first_public_url(value: Any) -> str | None:
    if not isinstance(value, Mapping):
        return None
    urls = value.get("url_list")
    if not isinstance(urls, list):
        return None
    return next((url for url in urls if isinstance(url, str) and url.startswith("https://")), None)


def _fetch_share_page(ydl: Any, video_id: str) -> str:
    share_url = f"https://www.iesdouyin.com/share/video/{video_id}"
    response = ydl.urlopen(share_url)
    try:
        return response.read(10_000_001).decode("utf-8", "replace")
    finally:
        response.close()


def extract_official_douyin_info(ydl: Any, source_url: str) -> dict[str, Any]:
    """Build a complete fallback result from Douyin's official share-page data."""

    video_id = _video_id(source_url, {})
    share_page = _fetch_share_page(ydl, video_id)
    router_data = parse_router_data(share_page)
    detail = _playback_detail(router_data, video_id)
    raw_format, internal_source = build_official_playback(source_url, {}, share_page)
    video_value = detail.get("video")
    author_value = detail.get("author")
    video: Mapping[str, Any] = video_value if isinstance(video_value, Mapping) else {}
    author: Mapping[str, Any] = author_value if isinstance(author_value, Mapping) else {}
    duration_ms = _positive_int(video.get("duration"))
    title = str(detail.get("desc") or "Douyin video").strip()[:300] or "Douyin video"
    return {
        "id": video_id,
        "title": title,
        "description": title,
        "uploader": str(author.get("nickname") or "").strip()[:200] or None,
        "duration": duration_ms / 1000 if duration_ms else None,
        "thumbnail": _first_public_url(video.get("cover")),
        "webpage_url": f"https://www.iesdouyin.com/share/video/{video_id}",
        "extractor": "mediafetch:douyin:official",
        "extractor_key": "MediaFetchDouyinOfficial",
        "formats": [raw_format],
        "_mediafetch_direct_formats": {OFFICIAL_DOUYIN_FORMAT_ID: internal_source},
    }


def add_official_playback_format(ydl: Any, source_url: str, info: dict[str, Any]) -> bool:
    """Append one server-generated official playback candidate to a yt-dlp result."""

    video_id = _video_id(source_url, info)
    page = _fetch_share_page(ydl, video_id)
    raw_format, internal_source = build_official_playback(source_url, info, page)

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
