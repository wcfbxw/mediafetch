import json
import re
from collections.abc import Mapping
from typing import Any
from urllib.parse import urlsplit

XIAOHONGSHU_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/143.0.0.0 Safari/537.36"
)
_NOTE_ID_RE = re.compile(
    r"/(?:explore|discovery/item|items)/([0-9a-fA-F]{24})(?:[/?#]|$)"
)
_INITIAL_STATE_RE = re.compile(r"window\.__INITIAL_STATE__\s*=\s*", re.IGNORECASE)
_UNDEFINED_RE = re.compile(r'(?<=[:\[,])\s*undefined\s*(?=[,\]}])')


class XiaohongshuExtractUnavailable(Exception):
    """Official Xiaohongshu initial state could not be parsed."""


def is_xiaohongshu_url(url: str) -> bool:
    host = (urlsplit(url).hostname or "").lower().rstrip(".")
    return host == "xiaohongshu.com" or host.endswith(".xiaohongshu.com") or host == "xhslink.com"


def _balanced_json(page: str, start: int) -> str:
    opening = page.find("{", start)
    if opening < 0:
        raise XiaohongshuExtractUnavailable("missing initial state object")
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
    raise XiaohongshuExtractUnavailable("unterminated initial state")


def parse_xhs_initial_state(page: str) -> dict[str, Any]:
    if not isinstance(page, str) or not page:
        raise XiaohongshuExtractUnavailable("empty page")
    match = _INITIAL_STATE_RE.search(page)
    if not match:
        raise XiaohongshuExtractUnavailable("missing __INITIAL_STATE__")
    raw_json = _balanced_json(page, match.end())
    sanitized = _UNDEFINED_RE.sub("null", raw_json)
    try:
        parsed = json.loads(sanitized)
    except (TypeError, ValueError) as exc:
        raise XiaohongshuExtractUnavailable("invalid __INITIAL_STATE__ JSON") from exc
    if not isinstance(parsed, dict):
        raise XiaohongshuExtractUnavailable("unexpected __INITIAL_STATE__ root")
    return parsed


def _find_note(state: Mapping[str, Any], note_id: str | None) -> Mapping[str, Any]:
    note_root = state.get("note")
    if isinstance(note_root, Mapping):
        detail_map = note_root.get("noteDetailMap")
        if isinstance(detail_map, Mapping):
            if note_id and isinstance(detail_map.get(note_id), Mapping):
                candidate = detail_map[note_id].get("note")
                if isinstance(candidate, Mapping):
                    return candidate
            for entry in detail_map.values():
                if isinstance(entry, Mapping) and isinstance(entry.get("note"), Mapping):
                    return entry["note"]
        direct_note = note_root.get("note")
        if isinstance(direct_note, Mapping) and direct_note:
            return direct_note
    raise XiaohongshuExtractUnavailable("note detail not found in state")


def _clean_xhs_image_url(image: Mapping[str, Any]) -> str | None:
    trace_id = str(image.get("traceId") or image.get("fileId") or "").strip()
    if trace_id and "/" not in trace_id and len(trace_id) >= 16:
        return f"https://sns-img-bd.xhscdn.com/{trace_id}?imageView2/2/w/format/png"

    for key in ("urlDefault", "urlPre", "url"):
        raw = image.get(key)
        if isinstance(raw, str) and raw.startswith(("http://", "https://")):
            https_url = "https://" + raw.removeprefix("http://").removeprefix("https://")
            # Strip watermarked !nd_... style suffixes when present on xhscdn.
            parsed = urlsplit(https_url)
            if (parsed.hostname or "").endswith("xhscdn.com") and "!" in parsed.path:
                clean_path = parsed.path.split("!", 1)[0]
                return f"https://{parsed.hostname}{clean_path}?imageView2/2/w/format/png"
            return https_url
    info_list = image.get("infoList")
    if isinstance(info_list, list):
        for entry in reversed(info_list):
            if isinstance(entry, Mapping):
                url = entry.get("url")
                if isinstance(url, str) and url.startswith(("http://", "https://")):
                    return "https://" + url.removeprefix("http://").removeprefix("https://")
    return None


def _live_photo_video_url(image: Mapping[str, Any]) -> str | None:
    stream = image.get("stream")
    if not isinstance(stream, Mapping):
        return None
    for codec_key in ("h264", "h265", "av1"):
        tracks = stream.get(codec_key)
        if isinstance(tracks, list):
            for track in tracks:
                if isinstance(track, Mapping):
                    master = track.get("masterUrl")
                    if isinstance(master, str) and master.startswith(("http://", "https://")):
                        return "https://" + master.removeprefix("http://").removeprefix("https://")
    return None


def _positive_int(value: Any) -> int | None:
    try:
        num = int(value)
    except (TypeError, ValueError):
        return None
    return num if num > 0 else None


def extract_xiaohongshu_note_from_html(page: str, source_url: str) -> dict[str, Any]:
    match = _NOTE_ID_RE.search(urlsplit(source_url).path)
    note_id = match.group(1) if match else None
    state = parse_xhs_initial_state(page)
    note = _find_note(state, note_id)
    resolved_id = str(note.get("noteId") or note_id or "xhs-note")
    title = (
        str(note.get("title") or note.get("desc") or "小红书作品").strip()[:300]
        or "小红书作品"
    )
    user = note.get("user")
    uploader = (
        str(user.get("nickname") or "").strip()[:200]
        if isinstance(user, Mapping)
        else None
    ) or None

    headers = {
        "Referer": "https://www.xiaohongshu.com/",
        "User-Agent": XIAOHONGSHU_USER_AGENT,
    }

    gallery: list[dict[str, Any]] = []
    image_list = note.get("imageList")
    if isinstance(image_list, list):
        for img in image_list:
            if not isinstance(img, Mapping):
                continue
            clean_img = _clean_xhs_image_url(img)
            if not clean_img:
                continue
            gallery.append(
                {
                    "url": clean_img,
                    "extension": "png" if "format/png" in clean_img else "jpg",
                    "width": _positive_int(img.get("width")),
                    "height": _positive_int(img.get("height")),
                    "live_video_url": _live_photo_video_url(img),
                    "http_headers": headers,
                }
            )

    formats: list[dict[str, Any]] = []
    direct_formats: dict[str, dict[str, Any]] = {}
    duration_s: float | None = None
    video = note.get("video")
    note_type = str(note.get("type") or "").lower()

    has_video_payload = isinstance(video, Mapping) and bool(
        note_type == "video" or video.get("consumer") or video.get("media")
    )
    if has_video_payload and isinstance(video, Mapping):
        capa = video.get("capa")
        if isinstance(capa, Mapping):
            dur = _positive_int(capa.get("duration"))
            if dur:
                duration_s = float(dur)

        consumer = video.get("consumer")
        origin_key = (
            str(consumer.get("originVideoKey") or "").strip()
            if isinstance(consumer, Mapping)
            else ""
        ) or str(video.get("originVideoKey") or "").strip()

        media = video.get("media")
        stream = media.get("stream") if isinstance(media, Mapping) else None
        ref_width: int | None = None
        ref_height: int | None = None
        ref_fps: int | None = None

        if isinstance(stream, Mapping):
            for codec_key, vcodec in (("h264", "h264"), ("h265", "hevc"), ("av1", "av01")):
                tracks = stream.get(codec_key)
                if not isinstance(tracks, list):
                    continue
                for idx, track in enumerate(tracks):
                    if not isinstance(track, Mapping):
                        continue
                    master = track.get("masterUrl")
                    if not isinstance(master, str) or not master.startswith(("http://", "https://")):
                        continue
                    https_master = "https://" + master.removeprefix("http://").removeprefix("https://")
                    w = _positive_int(track.get("width"))
                    h = _positive_int(track.get("height"))
                    fps = _positive_int(track.get("fps"))
                    tbr = _positive_int(track.get("videoBitrate") or track.get("avgBitrate"))
                    size = _positive_int(track.get("size"))
                    ref_width = ref_width or w
                    ref_height = ref_height or h
                    ref_fps = ref_fps or fps
                    fmt_id = f"xhs-{codec_key}-{idx}"
                    formats.append(
                        {
                            "format_id": fmt_id,
                            "format_note": f"Xiaohongshu clean {codec_key}",
                            "url": https_master,
                            "protocol": "https",
                            "ext": "mp4",
                            "width": w,
                            "height": h,
                            "fps": fps,
                            "tbr": round(tbr / 1000, 1) if tbr and tbr > 10_000 else tbr,
                            "filesize": size,
                            "vcodec": vcodec,
                            "acodec": "aac",
                            "watermark_free": True,
                            "source_preference": 300 - idx,
                            "http_headers": headers,
                        }
                    )
                    direct_formats[fmt_id] = {"url": https_master, "http_headers": headers}

        if origin_key and not any(ord(c) < 32 for c in origin_key):
            origin_url = f"https://sns-video-bd.xhscdn.com/{origin_key.lstrip('/')}"
            formats.append(
                {
                    "format_id": "xhs-origin-master",
                    "format_note": "Xiaohongshu official original",
                    "url": origin_url,
                    "protocol": "https",
                    "ext": "mp4",
                    "width": ref_width,
                    "height": ref_height,
                    "fps": ref_fps,
                    "vcodec": "h264",
                    "acodec": "aac",
                    "watermark_free": True,
                    "source_preference": 1000,
                    "http_headers": headers,
                }
            )
            direct_formats["xhs-origin-master"] = {"url": origin_url, "http_headers": headers}
        # Video notes also carry a cover image in imageList; keep gallery empty for videos.
        if formats:
            gallery_for_result: list[dict[str, Any]] = []
        else:
            gallery_for_result = gallery
    else:
        gallery_for_result = gallery

    if not formats and not gallery_for_result:
        raise XiaohongshuExtractUnavailable("no clean video or image gallery found")

    thumbnail = gallery[0]["url"] if gallery else None
    return {
        "id": resolved_id,
        "title": title,
        "uploader": uploader,
        "duration": duration_s,
        "thumbnail": thumbnail,
        "webpage_url": source_url,
        "extractor": "mediafetch:xiaohongshu:clean",
        "extractor_key": "XiaoHongShu",
        "formats": formats,
        "_mediafetch_direct_formats": direct_formats,
        "_mediafetch_gallery": gallery_for_result,
        "_mediafetch_engine": "xiaohongshu-clean",
    }


def extract_xiaohongshu_info(ydl: Any, source_url: str) -> dict[str, Any]:
    response = ydl.urlopen(source_url)
    try:
        html = response.read(10_000_001).decode("utf-8", "replace")
    finally:
        response.close()
    return extract_xiaohongshu_note_from_html(html, source_url)
