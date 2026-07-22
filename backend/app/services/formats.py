from collections.abc import Iterable
from typing import Any

from app.core.errors import error

VALID_PROTOCOL_PREFIXES = ("http", "https", "m3u8", "dash")
INVALID_EXTENSIONS = {"mhtml", "html", "jpg", "jpeg", "png", "webp", "gif"}
H264_MARKERS = ("avc", "h264")
AAC_MARKERS = ("aac", "mp4a")


def _codec(value: object) -> str | None:
    if not value or str(value).lower() in {"none", "unknown", "null"}:
        return None
    return str(value)


def _number(value: object, cast):
    try:
        return cast(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def quality_label(width: int | None, height: int | None, has_video: bool) -> str:
    if not has_video:
        return "仅音频"
    resolution = min(width, height) if width and height else height or width
    if resolution is None:
        return "未知画质"
    for target in (2160, 1440, 1080, 720, 480, 360):
        if resolution >= target:
            return f"{target}P"
    return f"{resolution}P"


def estimate_size(item: dict[str, Any], duration: int | None) -> int | None:
    explicit = _number(item.get("filesize") or item.get("filesize_approx"), int)
    if explicit and explicit > 0:
        return explicit
    bitrate = _number(item.get("tbr") or item.get("abr") or item.get("vbr"), float)
    if bitrate and duration and duration > 0:
        return int(bitrate * 1000 * duration / 8)
    return None


def normalize_format(item: dict[str, Any], duration: int | None) -> dict[str, Any] | None:
    format_id = str(item.get("format_id") or "").strip()
    ext = str(item.get("ext") or "").lower().strip()
    protocol = str(item.get("protocol") or "").lower()
    url = item.get("url")
    format_note = str(item.get("format_note") or "").lower()
    if not format_id or not url:
        return None
    if item.get("has_drm") or "storyboard" in format_note or ext in INVALID_EXTENSIONS:
        return None
    if protocol and not protocol.startswith(VALID_PROTOCOL_PREFIXES):
        return None

    vcodec = _codec(item.get("vcodec"))
    acodec = _codec(item.get("acodec"))
    width = _number(item.get("width"), int)
    height = _number(item.get("height"), int)
    has_video = vcodec is not None or bool(width or height)
    has_audio = acodec is not None
    if not has_video and not has_audio:
        return None

    fps = _number(item.get("fps"), float)
    bitrate = _number(item.get("tbr") or item.get("vbr") or item.get("abr"), float)
    return {
        "id": format_id,
        "label": quality_label(width, height, has_video),
        "width": width,
        "height": height,
        "fps": fps,
        "extension": ext or "bin",
        "video_codec": vcodec,
        "audio_codec": acodec,
        "bitrate": bitrate,
        "estimated_size": estimate_size(item, duration),
        "has_video": has_video,
        "has_audio": has_audio,
        "requires_merge": has_video and not has_audio,
        "preferred": False,
    }


def _is_h264(codec: str | None) -> bool:
    return bool(codec and any(marker in codec.lower() for marker in H264_MARKERS))


def _is_aac(codec: str | None) -> bool:
    return bool(codec and any(marker in codec.lower() for marker in AAC_MARKERS))


def is_mp4_compatible(video_codec: str | None, audio_codec: str | None) -> bool:
    return _is_h264(video_codec) and (not audio_codec or _is_aac(audio_codec))


def _video_sort_key(item: dict[str, Any]) -> tuple:
    return (
        -(item.get("height") or -1),
        -int(item["has_video"] and item["has_audio"]),
        -int(item["extension"] in {"mp4", "m4v"}),
        -int(_is_h264(item.get("video_codec"))),
        -(item.get("fps") or 0),
        -(item.get("bitrate") or 0),
        -int(item.get("estimated_size") is not None),
        item["id"],
    )


def _audio_sort_key(item: dict[str, Any]) -> tuple:
    return (
        -int(item["extension"] in {"m4a", "mp4"}),
        -int(_is_aac(item.get("audio_codec"))),
        -(item.get("bitrate") or 0),
        -int(item.get("estimated_size") is not None),
        item["id"],
    )


def normalize_formats(
    raw_formats: Iterable[dict[str, Any]],
    duration: int | None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    seen: set[str] = set()
    video: list[dict[str, Any]] = []
    audio: list[dict[str, Any]] = []
    for raw in raw_formats:
        normalized = normalize_format(raw, duration)
        if not normalized or normalized["id"] in seen:
            continue
        seen.add(normalized["id"])
        if normalized["has_video"]:
            video.append(normalized)
        else:
            audio.append(normalized)
    video.sort(key=_video_sort_key)
    audio.sort(key=_audio_sort_key)

    preferred_labels: set[str] = set()
    for item in video:
        if item["label"] not in preferred_labels:
            item["preferred"] = True
            preferred_labels.add(item["label"])
    if audio:
        audio[0]["preferred"] = True
    return video, audio


def find_format(
    formats: Iterable[dict[str, Any]],
    format_id: str,
) -> dict[str, Any]:
    for item in formats:
        if item.get("id") == format_id:
            return item
    raise error("FORMAT_NOT_FOUND")


def choose_audio_format(
    audio_formats: list[dict[str, Any]],
    video_format: dict[str, Any],
) -> dict[str, Any] | None:
    if video_format.get("has_audio"):
        return None
    if not audio_formats:
        raise error("NO_FORMATS", message="该画质没有可用的音频轨")

    video_ext = video_format.get("extension")
    video_codec = (video_format.get("video_codec") or "").lower()

    def score(audio: dict[str, Any]) -> tuple:
        audio_codec = (audio.get("audio_codec") or "").lower()
        compatible_mp4 = video_ext in {"mp4", "m4v"} and _is_aac(audio_codec)
        compatible_webm = video_ext == "webm" and any(
            marker in audio_codec for marker in ("opus", "vorbis")
        )
        codec_family = 2 if compatible_mp4 or compatible_webm else 0
        if "av01" in video_codec and _is_aac(audio_codec):
            codec_family = max(codec_family, 1)
        return (
            codec_family,
            int(audio.get("preferred", False)),
            audio.get("bitrate") or 0,
        )

    return max(audio_formats, key=score)


def select_output_container(
    requested: str,
    *,
    video_codec: str | None,
    audio_codec: str | None,
    compatibility_mode: bool,
) -> str:
    if compatibility_mode:
        return "mp4"
    video = (video_codec or "").lower()
    audio = (audio_codec or "").lower()
    mp4_ok = is_mp4_compatible(video, audio)
    webm_ok = any(codec in video for codec in ("vp9", "vp09", "av01")) and (
        not audio or any(codec in audio for codec in ("opus", "vorbis"))
    )
    if requested == "mp4" and not mp4_ok:
        return "webm" if webm_ok else "mkv"
    if requested == "webm" and not webm_ok:
        return "mp4" if mp4_ok else "mkv"
    if requested in {"mp4", "webm", "mkv"}:
        return requested
    return "mp4" if mp4_ok else ("webm" if webm_ok else "mkv")
