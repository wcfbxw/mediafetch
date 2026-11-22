import logging
import re
from collections.abc import Mapping
from typing import Any
from urllib.parse import parse_qs, urlencode, urlsplit

import httpx
from yt_dlp.extractor.common import InfoExtractor
from yt_dlp.utils import ExtractorError

from app.core.config import get_settings
from app.services.formats import clean_watermark_url

logger = logging.getLogger(__name__)

PIPIXIA_MOBILE_UA = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Mobile/15E148 Safari/604.1"
)


def _positive_int(value: Any) -> int | None:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


class MediaFetchPipixiaIE(InfoExtractor):
    """Dedicated Pipixia extractor that selects origin_video_download (no watermark)."""

    IE_NAME = "mediafetch:pipixia"
    _VALID_URL = r"https?://(?:h5\.|www\.)?pipixia\.com/(?:item|s)/(?P<id>[A-Za-z0-9_-]+)"

    def _real_extract(self, url: str) -> dict[str, Any]:
        raw_id = self._match_id(url)
        item_id = raw_id if raw_id.isdigit() else None
        if not item_id:
            parsed = urlsplit(url)
            match = re.search(r"/item/(\d+)", parsed.path)
            if match:
                item_id = match.group(1)
        if not item_id:
            raise ExtractorError("Pipixia item ID was not found", expected=True)

        api_url = "https://h5.pipixia.com/bds/webapi/item/detail/?" + urlencode(
            {"item_id": item_id, "source": "share"}
        )
        payload = self._download_json(
            api_url,
            item_id,
            headers={
                "User-Agent": PIPIXIA_MOBILE_UA,
                "Referer": f"https://h5.pipixia.com/item/{item_id}",
            },
        )
        item = (
            payload.get("data", {}).get("item")
            if isinstance(payload, Mapping) and isinstance(payload.get("data"), Mapping)
            else None
        )
        if not isinstance(item, Mapping):
            raise ExtractorError("Pipixia item payload unavailable", expected=True)

        # Read origin_video_download (clean upload) instead of watermarked video_download.
        origin_video = item.get("origin_video_download")
        if not isinstance(origin_video, Mapping):
            video_node = item.get("video")
            if isinstance(video_node, Mapping):
                origin_video = video_node.get("video_high") or video_node.get(
                    "origin_video_download"
                )

        headers = {
            "User-Agent": PIPIXIA_MOBILE_UA,
            "Referer": "https://h5.pipixia.com/",
        }
        formats: list[dict[str, Any]] = []
        if isinstance(origin_video, Mapping):
            url_list = origin_video.get("url_list")
            clean_url = next(
                (
                    entry.get("url")
                    for entry in (url_list or [])
                    if isinstance(entry, Mapping)
                    and isinstance(entry.get("url"), str)
                    and entry["url"].startswith(("http://", "https://"))
                ),
                None,
            )
            if clean_url:
                formats.append(
                    {
                        "format_id": "ppx-origin-clean",
                        "format_note": "Pipixia original clean video",
                        "url": clean_url,
                        "protocol": "https",
                        "ext": "mp4",
                        "width": _positive_int(origin_video.get("width")),
                        "height": _positive_int(origin_video.get("height")),
                        "vcodec": "h264",
                        "acodec": "aac",
                        "watermark_free": True,
                        "source_preference": 500,
                        "http_headers": headers,
                    }
                )

        gallery: list[dict[str, Any]] = []
        note = item.get("note")
        if isinstance(note, Mapping) and isinstance(note.get("multi_image"), list):
            for img in note["multi_image"]:
                if not isinstance(img, Mapping):
                    continue
                img_urls = img.get("url_list")
                img_url = next(
                    (
                        u.get("url")
                        for u in (img_urls or [])
                        if isinstance(u, Mapping)
                        and isinstance(u.get("url"), str)
                        and u["url"].startswith(("http://", "https://"))
                    ),
                    None,
                )
                if img_url:
                    gallery.append(
                        {
                            "url": img_url,
                            "extension": "webp" if ".webp" in img_url.lower() else "jpg",
                            "width": _positive_int(img.get("width")),
                            "height": _positive_int(img.get("height")),
                            "live_video_url": None,
                            "http_headers": headers,
                        }
                    )

        if not formats and not gallery:
            raise ExtractorError("Pipixia clean media unavailable", expected=True)

        author = item.get("author")
        uploader = (
            str(author.get("name") or "").strip()[:200]
            if isinstance(author, Mapping)
            else None
        )
        title = str(item.get("content") or f"Pipixia {item_id}").strip()[:300]
        cover_node = item.get("cover")
        cover_url = None
        if isinstance(cover_node, Mapping) and isinstance(cover_node.get("url_list"), list):
            for u in cover_node["url_list"]:
                if isinstance(u, Mapping) and isinstance(u.get("url"), str):
                    cover_url = u["url"]
                    break

        duration_val = (
            _positive_int(origin_video.get("duration"))
            if isinstance(origin_video, Mapping)
            else None
        )
        return {
            "id": item_id,
            "title": title,
            "uploader": uploader or None,
            "duration": duration_val,
            "thumbnail": cover_url or (gallery[0]["url"] if gallery else None),
            "webpage_url": url,
            "formats": formats,
            "_mediafetch_gallery": gallery,
            "_mediafetch_engine": "pipixia-clean",
        }


def is_douyin_or_tiktok_url(url: str) -> bool:
    host = (urlsplit(url).hostname or "").lower().rstrip(".")
    return any(
        host == domain or host.endswith(f".{domain}")
        for domain in ("douyin.com", "iesdouyin.com", "tiktok.com")
    )


def fetch_hybrid_clean_media(source_url: str) -> dict[str, Any] | None:
    """Query optional internal Douyin_TikTok_Download_API container when configured."""

    settings = get_settings()
    base = settings.douyin_api_base_url
    if not base or not is_douyin_or_tiktok_url(source_url):
        return None

    endpoint = f"{base.rstrip('/')}/api/hybrid/video_data"
    try:
        with httpx.Client(timeout=15.0, follow_redirects=False, trust_env=False) as client:
            response = client.get(endpoint, params={"url": source_url, "minimal": "false"})
            if response.status_code != 200:
                return None
            body = response.json()
    except Exception as exc:
        logger.info("Hybrid API fallback triggered error_type=%s", type(exc).__name__)
        return None

    data = body.get("data") if isinstance(body, Mapping) else None
    if not isinstance(data, Mapping):
        return None

    is_tiktok = "tiktok.com" in (urlsplit(source_url).hostname or "").lower()
    referer = "https://www.tiktok.com/" if is_tiktok else "https://www.douyin.com/"
    headers = {
        "Referer": referer,
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/143.0.0.0 Safari/537.36"
        ),
    }

    formats: list[dict[str, Any]] = []
    direct_formats: dict[str, dict[str, Any]] = {}
    video_data = data.get("video_data")
    video_node = data.get("video")
    width = _positive_int(video_node.get("width")) if isinstance(video_node, Mapping) else None
    height = _positive_int(video_node.get("height")) if isinstance(video_node, Mapping) else None

    if isinstance(video_data, Mapping):
        for key, label, pref in (
            ("nwm_video_url_HQ", "Hybrid HQ clean", 900),
            ("nwm_video_url", "Hybrid clean", 800),
        ):
            candidate = video_data.get(key)
            if isinstance(candidate, str) and candidate.startswith(("http://", "https://")):
                cleaned = clean_watermark_url(candidate)
                fmt_id = f"hybrid-{key.lower()}"
                formats.append(
                    {
                        "format_id": fmt_id,
                        "format_note": label,
                        "url": cleaned,
                        "protocol": "https",
                        "ext": "mp4",
                        "width": width,
                        "height": height,
                        "vcodec": "h264",
                        "acodec": "aac",
                        "watermark_free": True,
                        "source_preference": pref,
                        "http_headers": headers,
                    }
                )
                direct_formats[fmt_id] = {"url": cleaned, "http_headers": headers}

    gallery: list[dict[str, Any]] = []
    image_data = data.get("image_data")
    if isinstance(image_data, Mapping):
        clean_images = image_data.get("no_watermark_image_list")
        if isinstance(clean_images, list):
            for img_url in clean_images:
                if isinstance(img_url, str) and img_url.startswith(("http://", "https://")):
                    gallery.append(
                        {
                            "url": img_url,
                            "extension": "webp" if ".webp" in img_url.lower() else "jpg",
                            "width": None,
                            "height": None,
                            "live_video_url": None,
                            "http_headers": headers,
                        }
                    )

    if not formats and not gallery:
        return None

    author = data.get("author")
    uploader = (
        str(author.get("nickname") or "").strip()[:200]
        if isinstance(author, Mapping)
        else None
    )
    duration_ms = (
        _positive_int(video_node.get("duration"))
        if isinstance(video_node, Mapping)
        else None
    )
    duration_s = (
        duration_ms / 1000
        if duration_ms and duration_ms > 500
        else (float(duration_ms) if duration_ms else None)
    )
    cover_data = data.get("cover_data")
    cover_url = None
    if isinstance(cover_data, Mapping):
        origin_cover = cover_data.get("origin_cover") or cover_data.get("dynamic_cover")
        if isinstance(origin_cover, Mapping) and isinstance(origin_cover.get("url_list"), list):
            cover_url = next(
                (u for u in origin_cover["url_list"] if isinstance(u, str) and u.startswith("https://")),
                None,
            )

    return {
        "id": str(data.get("aweme_id") or "media"),
        "title": str(data.get("desc") or "Media").strip()[:300] or "Media",
        "uploader": uploader or None,
        "duration": duration_s if not gallery else None,
        "thumbnail": cover_url or (gallery[0]["url"] if gallery else None),
        "webpage_url": source_url,
        "extractor": "mediafetch:hybrid",
        "extractor_key": "TikTok" if is_tiktok else "Douyin",
        "formats": formats,
        "_mediafetch_direct_formats": direct_formats,
        "_mediafetch_gallery": gallery,
        "_mediafetch_engine": "hybrid-api",
    }


def select_playlist_or_multipart_entry(
    result: dict[str, Any],
    source_url: str,
) -> dict[str, Any] | None:
    """Select the target video or collect gallery entries from multi-item posts."""

    entries = [entry for entry in result.get("entries") or [] if isinstance(entry, dict)]
    if not entries:
        return None
    if len(entries) == 1:
        return entries[0]

    parsed = urlsplit(source_url)
    host = (parsed.hostname or "").lower().rstrip(".")

    # Bilibili multi-part (?p=N): choose requested page index (1-based).
    if host.endswith(("bilibili.com", "b23.tv")):
        p_values = parse_qs(parsed.query).get("p") or []
        page_num = _positive_int(p_values[0]) if p_values else 1
        idx = min(max((page_num or 1) - 1, 0), len(entries) - 1)
        chosen = dict(entries[idx])
        if not chosen.get("title") and result.get("title"):
            chosen["title"] = result["title"]
        return chosen

    # Multi-media social posts (X/Twitter, Instagram, Weibo, Reddit, TikTok, Xiaohongshu):
    image_exts = {"jpg", "jpeg", "png", "webp"}
    video_entries = [
        entry
        for entry in entries
        if entry.get("formats")
        or (entry.get("url") and str(entry.get("ext") or "").lower() not in image_exts)
    ]
    image_entries: list[dict[str, Any]] = []
    for entry in entries:
        entry_url = entry.get("url")
        entry_ext = str(entry.get("ext") or "").lower()
        is_valid_img = (
            isinstance(entry_url, str)
            and entry_url.startswith(("http://", "https://"))
            and entry_ext in image_exts
        )
        if is_valid_img:
            assert isinstance(entry_url, str)
            image_entries.append(
                {
                    "url": entry_url,
                    "extension": "jpg" if entry_ext == "jpeg" else entry_ext,
                    "width": _positive_int(entry.get("width")),
                    "height": _positive_int(entry.get("height")),
                    "live_video_url": None,
                    "http_headers": dict(entry.get("http_headers") or {}),
                }
            )

    if video_entries:
        chosen = dict(video_entries[0])
        if not chosen.get("title") and result.get("title"):
            chosen["title"] = result["title"]
        if not chosen.get("uploader") and result.get("uploader"):
            chosen["uploader"] = result["uploader"]
        if image_entries and not chosen.get("_mediafetch_gallery"):
            chosen["_mediafetch_gallery"] = image_entries
        return chosen

    if image_entries:
        return {
            "id": str(result.get("id") or "gallery"),
            "title": str(result.get("title") or "图集作品").strip()[:300],
            "uploader": result.get("uploader"),
            "duration": None,
            "thumbnail": image_entries[0]["url"],
            "webpage_url": str(result.get("webpage_url") or source_url),
            "extractor": result.get("extractor") or "generic",
            "extractor_key": result.get("extractor_key") or "Gallery",
            "formats": [],
            "_mediafetch_gallery": image_entries,
        }

    return None
