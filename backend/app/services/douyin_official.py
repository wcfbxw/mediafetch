import json
import re
from collections.abc import Mapping
from typing import Any
from urllib.parse import parse_qs, urlencode, urlsplit

from app.services.formats import clean_watermark_url

OFFICIAL_DOUYIN_FORMAT_ID = "mediafetch-douyin-official-1080p"
DOUYIN_MOBILE_USER_AGENT = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.0 "
    "Mobile/15E148 Safari/604.1"
)
_ITEM_ID_PATH = re.compile(
    r"/(?:video|note|share/video|share/note|share/slides)/(\d+)(?:[/?#]|$)",
    re.IGNORECASE,
)
_ROUTER_DATA_MARKER = re.compile(r"window\._ROUTER_DATA\s*=", re.IGNORECASE)


class DouyinOfficialPlaybackUnavailable(Exception):
    """The official share page did not contain a usable playback URI."""


def is_official_share_url(source_url: str) -> bool:
    parsed = urlsplit(source_url)
    hostname = (parsed.hostname or "").lower().rstrip(".")
    return hostname in {"iesdouyin.com", "www.iesdouyin.com"} and bool(
        _ITEM_ID_PATH.search(parsed.path)
    )


def _video_id(source_url: str, info: Mapping[str, Any]) -> str:
    for candidate_url in (source_url, info.get("webpage_url")):
        if not isinstance(candidate_url, str):
            continue
        parsed = urlsplit(candidate_url)
        match = _ITEM_ID_PATH.search(parsed.path)
        if match:
            return match.group(1)
        modal_ids = parse_qs(parsed.query).get("modal_id") or []
        if modal_ids and modal_ids[0].isdigit():
            return modal_ids[0]
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


def _item_detail(router_data: Mapping[str, Any], expected_id: str) -> Mapping[str, Any]:
    stack: list[tuple[Any, int]] = [(router_data, 0)]
    fallback: Mapping[str, Any] | None = None
    visited = 0
    while stack:
        value, depth = stack.pop()
        visited += 1
        if visited > 50_000 or depth > 64:
            continue
        if isinstance(value, Mapping):
            has_images = isinstance(value.get("images"), list) and len(value["images"]) > 0
            video = value.get("video")
            has_play_uri = (
                isinstance(video, Mapping)
                and isinstance(video.get("play_addr"), Mapping)
                and bool(video["play_addr"].get("uri"))
            )
            if has_play_uri or has_images:
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


def _first_public_url(value: Any, *, clean_only: bool = False) -> str | None:
    if not isinstance(value, Mapping):
        return None
    urls = value.get("url_list")
    if not isinstance(urls, list):
        return None
    candidates = [
        clean_watermark_url(url)
        for url in urls
        if isinstance(url, str) and url.startswith("https://")
    ]
    if clean_only:
        non_wm = [url for url in candidates if "watermark" not in url.lower()]
        if non_wm:
            return non_wm[0]
    return candidates[0] if candidates else None


def _image_ext_from_url(url: str) -> str:
    path = urlsplit(url).path.lower()
    for ext in ("png", "webp", "jpeg", "jpg"):
        if path.endswith(f".{ext}"):
            return "jpg" if ext == "jpeg" else ext
    return "jpg"


def _extract_douyin_gallery(detail: Mapping[str, Any]) -> list[dict[str, Any]]:
    images = detail.get("images")
    if not isinstance(images, list) or not images:
        return []
    headers = {
        "Referer": "https://www.douyin.com/",
        "User-Agent": DOUYIN_MOBILE_USER_AGENT,
    }
    gallery: list[dict[str, Any]] = []
    for item in images:
        if not isinstance(item, Mapping):
            continue
        image_url = _first_public_url(item, clean_only=True)
        if not image_url:
            continue
        live_video_url: str | None = None
        clip_video = item.get("video")
        if isinstance(clip_video, Mapping):
            play_addr = clip_video.get("play_addr")
            if isinstance(play_addr, Mapping):
                uri = str(play_addr.get("uri") or "").strip()
                if uri and len(uri) <= 512 and not any(ord(c) < 32 for c in uri):
                    live_video_url = "https://www.iesdouyin.com/aweme/v1/play/?" + urlencode(
                        {"video_id": uri, "ratio": "1080p", "line": "0"}
                    )
                else:
                    live_video_url = _first_public_url(play_addr, clean_only=True)
        gallery.append(
            {
                "url": image_url,
                "extension": _image_ext_from_url(image_url),
                "width": _positive_int(item.get("width")),
                "height": _positive_int(item.get("height")),
                "live_video_url": live_video_url,
                "http_headers": headers,
            }
        )
    return gallery


def _extract_bitrate_formats(
    video: Mapping[str, Any],
    duration_s: float | None,
) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]]]:
    bit_rates = video.get("bit_rate")
    if not isinstance(bit_rates, list):
        return [], {}
    headers = {
        "Referer": "https://www.douyin.com/",
        "User-Agent": DOUYIN_MOBILE_USER_AGENT,
    }
    formats: list[dict[str, Any]] = []
    direct_map: dict[str, dict[str, Any]] = {}
    for index, entry in enumerate(bit_rates):
        if not isinstance(entry, Mapping):
            continue
        play_addr = entry.get("play_addr")
        url = _first_public_url(play_addr, clean_only=True)
        if not url:
            continue
        gear_name = str(entry.get("gear_name") or f"gear-{index}").strip()[:48]
        is_bytevc1 = str(entry.get("is_bytevc1") or entry.get("is_h265") or "0") in {"1", "true"}
        codec = "hevc" if is_bytevc1 else "h264"
        fmt_id = f"douyin-clean-{gear_name}-{codec}-{index}"
        addr_map = play_addr if isinstance(play_addr, Mapping) else {}
        width = _positive_int(addr_map.get("width")) or _positive_int(video.get("width"))
        height = _positive_int(addr_map.get("height")) or _positive_int(video.get("height"))
        size = _positive_int(addr_map.get("data_size"))
        bps = _positive_int(entry.get("bit_rate"))
        fps = _positive_int(entry.get("FPS"))
        raw: dict[str, Any] = {
            "format_id": fmt_id,
            "format_note": f"Douyin clean {gear_name}",
            "url": url,
            "protocol": "https",
            "ext": "mp4",
            "width": width,
            "height": height,
            "fps": fps,
            "tbr": round(bps / 1000, 1) if bps else None,
            "filesize": size,
            "vcodec": codec,
            "acodec": "aac",
            "watermark_free": True,
            "source_preference": 200 - index,
            "http_headers": headers,
        }
        if duration_s:
            raw["duration"] = duration_s
        formats.append(raw)
        direct_map[fmt_id] = {"url": url, "http_headers": headers}
    return formats, direct_map


def build_official_playback(
    source_url: str,
    info: Mapping[str, Any],
    share_page: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    video_id = _video_id(source_url, info)
    detail = _item_detail(parse_router_data(share_page), video_id)
    video = detail.get("video")
    if not isinstance(video, Mapping) or not isinstance(video.get("play_addr"), Mapping):
        raise DouyinOfficialPlaybackUnavailable("missing official playback uri")
    play_addr = video["play_addr"]
    playback_uri = str(play_addr.get("uri") or "").strip()
    if (
        not playback_uri
        or playback_uri.startswith(("http://", "https://"))
        or len(playback_uri) > 512
        or any(ord(char) < 32 for char in playback_uri)
    ):
        raise DouyinOfficialPlaybackUnavailable("invalid official playback uri")

    playback_url = "https://www.iesdouyin.com/aweme/v1/play/?" + urlencode(
        {"video_id": playback_uri, "ratio": "1080p", "line": "0"}
    )
    width = _positive_int(video.get("width"))
    height = _positive_int(video.get("height"))
    duration_ms = _positive_int(video.get("duration"))
    headers = {
        "Referer": "https://www.douyin.com/",
        "User-Agent": DOUYIN_MOBILE_USER_AGENT,
    }
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
        "watermark_free": True,
        "source_preference": 150,
        "http_headers": headers,
    }
    if duration_ms and duration_ms >= 1000:
        raw_format["duration"] = duration_ms / 1000
    internal_source = {
        "url": playback_url,
        "http_headers": headers,
    }
    return raw_format, internal_source


def _fetch_share_page(ydl: Any, video_id: str) -> str:
    share_url = f"https://www.iesdouyin.com/share/video/{video_id}"
    response = ydl.urlopen(share_url)
    try:
        return response.read(10_000_001).decode("utf-8", "replace")
    finally:
        response.close()


def extract_official_douyin_info(ydl: Any, source_url: str) -> dict[str, Any]:
    """Build a complete clean result from Douyin's official share-page data."""

    video_id = _video_id(source_url, {})
    share_page = _fetch_share_page(ydl, video_id)
    router_data = parse_router_data(share_page)
    detail = _item_detail(router_data, video_id)
    gallery = _extract_douyin_gallery(detail)

    video_value = detail.get("video")
    author_value = detail.get("author")
    video: Mapping[str, Any] = video_value if isinstance(video_value, Mapping) else {}
    author: Mapping[str, Any] = author_value if isinstance(author_value, Mapping) else {}
    duration_ms = _positive_int(video.get("duration"))
    duration_s = duration_ms / 1000 if duration_ms else None

    formats: list[dict[str, Any]] = []
    direct_formats: dict[str, dict[str, Any]] = {}
    try:
        raw_format, internal_source = build_official_playback(source_url, {}, share_page)
        formats.append(raw_format)
        direct_formats[OFFICIAL_DOUYIN_FORMAT_ID] = internal_source
    except DouyinOfficialPlaybackUnavailable:
        if not gallery:
            raise

    extra_formats, extra_direct = _extract_bitrate_formats(video, duration_s)
    formats.extend(extra_formats)
    direct_formats.update(extra_direct)

    # Extract background music audio for image notes if available.
    if gallery:
        music_url = _first_public_url(video.get("play_addr"), clean_only=True)
        if music_url and music_url.startswith("https://") and not formats:
            formats.append(
                {
                    "format_id": "douyin-bgm-audio",
                    "format_note": "Douyin note BGM",
                    "url": music_url,
                    "protocol": "https",
                    "ext": "m4a",
                    "vcodec": "none",
                    "acodec": "mp3",
                    "watermark_free": True,
                    "http_headers": {
                        "Referer": "https://www.douyin.com/",
                        "User-Agent": DOUYIN_MOBILE_USER_AGENT,
                    },
                }
            )

    title = str(detail.get("desc") or "Douyin media").strip()[:300] or "Douyin media"
    cover = _first_public_url(video.get("cover")) or (
        gallery[0]["url"] if gallery else None
    )
    return {
        "id": video_id,
        "title": title,
        "description": title,
        "uploader": str(author.get("nickname") or "").strip()[:200] or None,
        "duration": duration_s if not gallery else None,
        "thumbnail": cover,
        "webpage_url": f"https://www.iesdouyin.com/share/video/{video_id}",
        "extractor": "mediafetch:douyin:official",
        "extractor_key": "MediaFetchDouyinOfficial",
        "formats": formats,
        "_mediafetch_direct_formats": direct_formats,
        "_mediafetch_gallery": gallery,
        "_mediafetch_engine": "douyin-clean",
    }


def add_official_playback_format(ydl: Any, source_url: str, info: dict[str, Any]) -> bool:
    """Append clean official playback candidates and gallery items to a yt-dlp result."""

    video_id = _video_id(source_url, info)
    page = _fetch_share_page(ydl, video_id)
    router_data = parse_router_data(page)
    detail = _item_detail(router_data, video_id)
    gallery = _extract_douyin_gallery(detail)
    if gallery:
        info["_mediafetch_gallery"] = gallery

    raw_format, internal_source = build_official_playback(source_url, info, page)
    video_value = detail.get("video")
    video: Mapping[str, Any] = video_value if isinstance(video_value, Mapping) else {}
    duration_ms = _positive_int(video.get("duration"))
    extra_formats, extra_direct = _extract_bitrate_formats(
        video, duration_ms / 1000 if duration_ms else None
    )

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
    formats.extend(extra_formats)
    direct_store = info.setdefault("_mediafetch_direct_formats", {})
    direct_store[OFFICIAL_DOUYIN_FORMAT_ID] = internal_source
    direct_store.update(extra_direct)
    return True
