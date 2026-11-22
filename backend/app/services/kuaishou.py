import json
import re
from collections.abc import Mapping
from typing import Any

from yt_dlp.extractor.common import InfoExtractor
from yt_dlp.utils import ExtractorError

KUAISHOU_MOBILE_USER_AGENT = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 18_5 like Mac OS X) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148"
)


def _find_photo(value: object) -> dict[str, Any] | None:
    if isinstance(value, dict):
        if isinstance(value.get("manifest"), dict) and value.get("photoType") in {
            "VIDEO",
            "VERTICAL_ATLAS",
            "HORIZONTAL_ATLAS",
            "IMAGE_ATLAS",
            None,
        }:
            return value
        if isinstance(value.get("ext_params"), dict) and isinstance(
            value["ext_params"].get("atlas"), dict
        ):
            return value
        if isinstance(value.get("atlas"), dict) and isinstance(
            value["atlas"].get("list"), list
        ):
            return value
        for nested in value.values():
            found = _find_photo(nested)
            if found:
                return found
    elif isinstance(value, list):
        for nested in value:
            found = _find_photo(nested)
            if found:
                return found
    return None


def _first_url(value: object) -> str | None:
    if not isinstance(value, list):
        return None
    for item in value:
        if isinstance(item, str) and item.startswith(("http://", "https://")):
            return item
        if isinstance(item, dict):
            candidate = item.get("url") or item.get("cdn")
            if isinstance(candidate, str) and candidate.startswith(("http://", "https://")):
                return candidate
    return None


def _codec_name(value: object) -> str:
    codec = str(value or "unknown").lower()
    if codec in {"avc", "avc1"}:
        return "h264"
    if codec in {"h265", "hev1", "hvc1"}:
        return "hevc"
    return codec


def _extract_kuaishou_atlas(photo: Mapping[str, Any], webpage_url: str) -> list[dict[str, Any]]:
    atlas = photo.get("atlas")
    if not isinstance(atlas, Mapping):
        ext_params = photo.get("ext_params")
        if isinstance(ext_params, Mapping):
            atlas = ext_params.get("atlas")
    if not isinstance(atlas, Mapping):
        return []
    paths = atlas.get("list")
    if not isinstance(paths, list) or not paths:
        return []
    cdn_list = atlas.get("cdn") or atlas.get("cdnList") or []
    cdn_host = "tx2.a.kwimgs.com"
    if isinstance(cdn_list, list) and cdn_list:
        first_cdn = cdn_list[0]
        if isinstance(first_cdn, str) and first_cdn:
            cdn_host = first_cdn.strip("/")
        elif isinstance(first_cdn, Mapping) and isinstance(first_cdn.get("cdn"), str):
            cdn_host = first_cdn["cdn"].strip("/")
    headers = {
        "User-Agent": KUAISHOU_MOBILE_USER_AGENT,
        "Referer": webpage_url,
    }
    gallery: list[dict[str, Any]] = []
    for rel in paths:
        if not isinstance(rel, str) or not rel:
            continue
        url = rel if rel.startswith(("http://", "https://")) else f"https://{cdn_host}/{rel.lstrip('/')}"
        ext = "webp" if ".webp" in url.lower() else "jpg"
        gallery.append(
            {
                "url": url,
                "extension": ext,
                "width": None,
                "height": None,
                "live_video_url": None,
                "http_headers": headers,
            }
        )
    return gallery


def extract_kuaishou_state(state: dict[str, Any], webpage_url: str) -> dict[str, Any]:
    photo = _find_photo(state)
    if not photo:
        raise ExtractorError("Kuaishou public video data was not found", expected=True)

    manifest = photo.get("manifest")
    formats: list[dict[str, Any]] = []
    headers = {
        "User-Agent": KUAISHOU_MOBILE_USER_AGENT,
        "Referer": webpage_url,
    }
    if isinstance(manifest, dict):
        for adaptation in manifest.get("adaptationSet") or []:
            if not isinstance(adaptation, dict):
                continue
            for representation in adaptation.get("representation") or []:
                if not isinstance(representation, dict):
                    continue
                media_url = representation.get("url") or _first_url(
                    representation.get("backupUrl")
                )
                if not isinstance(media_url, str) or not media_url.startswith(
                    ("http://", "https://")
                ):
                    continue
                codec = _codec_name(representation.get("videoCodec"))
                representation_id = str(representation.get("id") or len(formats) + 1)
                formats.append(
                    {
                        "format_id": f"ks-{representation_id}-{codec}",
                        "format_note": str(representation.get("qualityLabel") or ""),
                        "url": media_url,
                        "ext": "mp4",
                        "protocol": "https",
                        "width": representation.get("width") or photo.get("width"),
                        "height": representation.get("height") or photo.get("height"),
                        "fps": representation.get("frameRate"),
                        "tbr": representation.get("avgBitrate"),
                        "filesize": representation.get("fileSize"),
                        "vcodec": codec,
                        "acodec": "aac",
                        "http_headers": headers,
                    }
                )
    if not formats:
        main_mv = _first_url(photo.get("mainMvUrls")) or photo.get("photoUrl")
        if isinstance(main_mv, str) and main_mv.startswith(("http://", "https://")):
            formats.append(
                {
                    "format_id": "ks-direct-h264",
                    "format_note": "Kuaishou clean main stream",
                    "url": main_mv,
                    "ext": "mp4",
                    "protocol": "https",
                    "width": photo.get("width"),
                    "height": photo.get("height"),
                    "vcodec": "h264",
                    "acodec": "aac",
                    "watermark_free": True,
                    "http_headers": headers,
                }
            )

    gallery = _extract_kuaishou_atlas(photo, webpage_url)
    if not formats and not gallery:
        raise ExtractorError("Kuaishou public video has no downloadable formats", expected=True)

    raw_duration = photo.get("duration")
    try:
        duration = float(raw_duration) / 1000 if raw_duration is not None else None
    except (TypeError, ValueError):
        duration = None
    caption = str(photo.get("caption") or "").strip()
    uploader = str(photo.get("userName") or "").strip()
    photo_id = str(photo.get("photoId") or photo.get("kwaiId") or "video")
    if not caption or caption == "...":
        caption = f"{uploader or 'Kuaishou'} - {photo_id}"

    result: dict[str, Any] = {
        "id": photo_id,
        "title": caption,
        "uploader": uploader or None,
        "duration": duration,
        "thumbnail": _first_url(photo.get("coverUrls"))
        or _first_url(photo.get("webpCoverUrls"))
        or (gallery[0]["url"] if gallery else None),
        "formats": formats,
        "webpage_url": webpage_url,
    }
    if gallery:
        result["_mediafetch_gallery"] = gallery
    return result


class MediaFetchKuaishouIE(InfoExtractor):
    IE_NAME = "mediafetch:kuaishou"
    _VALID_URL = (
        r"https?://(?:"
        r"(?:(?:v|www|c)\.)?kuaishou\.com/(?:short-video/|f/|fw/photo/)?|"
        r"(?:v\.)?m\.(?:chenzhongtech|gifshow)\.com/fw/photo/"
        r")(?P<id>[A-Za-z0-9_-]+)"
    )
    _INIT_STATE = re.compile(
        r"window\.(?:INIT_STATE|__APOLLO_STATE__)\s*=\s*(?P<json>\{.+?\})\s*;?\s*</script>",
        re.DOTALL,
    )

    def _real_extract(self, url: str) -> dict[str, Any]:
        display_id = self._match_id(url)
        webpage = self._download_webpage(
            url,
            display_id,
            headers={
                "User-Agent": KUAISHOU_MOBILE_USER_AGENT,
                "Referer": "https://v.kuaishou.com/",
            },
        )
        match = self._INIT_STATE.search(webpage)
        if not match:
            raise ExtractorError("Kuaishou public page data was not found", expected=True)
        try:
            state = json.loads(match.group("json"))
        except (TypeError, ValueError) as exc:
            raise ExtractorError("Invalid Kuaishou public page data", expected=True) from exc
        result = extract_kuaishou_state(state, url)
        result["display_id"] = display_id
        return result
