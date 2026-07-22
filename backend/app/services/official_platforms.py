from collections.abc import Mapping
from typing import Any

SUPPORTED_PLATFORM_EXTRACTORS: dict[str, tuple[str, ...]] = {
    "douyin": ("Douyin", "MediaFetchDouyinOfficial"),
    "kuaishou": ("MediaFetchKuaishou",),
    "xiaohongshu": ("XiaoHongShu",),
    "bilibili": ("BiliBili",),
    "weibo": ("Weibo", "WeiboVideo"),
    "xigua": ("Ixigua",),
    "youtube": ("Youtube",),
}


def _is_media_reference(item: Mapping[str, Any]) -> bool:
    return bool(
        item.get("width")
        or item.get("height")
        or str(item.get("vcodec") or "").lower() not in {"", "none", "unknown"}
    )


def _reference_score(item: Mapping[str, Any]) -> tuple[float, float, float]:
    def number(value: Any) -> float:
        try:
            return float(value or 0)
        except (TypeError, ValueError):
            return 0

    return (
        number(item.get("width")) * number(item.get("height")),
        number(item.get("tbr") or item.get("vbr")),
        number(item.get("fps")),
    )


def prefer_official_original_formats(info: dict[str, Any]) -> None:
    """Preserve official originals whose endpoint omits codec metadata.

    yt-dlp's Xiaohongshu extractor obtains ``originVideoKey`` from the official
    page and probes the matching xhscdn URL. That direct response intentionally
    has little metadata, so copy only descriptive stream properties from the
    best official rendition. The media URL itself is never changed.
    """

    extractor = str(info.get("extractor_key") or "")
    if extractor != "XiaoHongShu":
        return
    formats = info.get("formats")
    if not isinstance(formats, list):
        return
    original = next(
        (
            item
            for item in formats
            if isinstance(item, dict) and item.get("format_id") == "direct" and item.get("url")
        ),
        None,
    )
    if original is None:
        return
    references = [
        item
        for item in formats
        if isinstance(item, Mapping) and item is not original and _is_media_reference(item)
    ]
    if not references:
        return
    reference = max(references, key=_reference_score)
    for field in ("width", "height", "fps", "vcodec", "acodec"):
        if not original.get(field) and reference.get(field) is not None:
            original[field] = reference[field]
    original["format_note"] = "Xiaohongshu official original"
    original["source_preference"] = 1000
