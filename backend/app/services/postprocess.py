from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from app.core.errors import error
from app.services.formats import is_mp4_compatible, select_output_container


class PostprocessPreset(StrEnum):
    REMUX = "remux"
    TRANSCODE = "transcode"


@dataclass(frozen=True)
class VideoPostprocessPlan:
    preset: PostprocessPreset
    output_container: str
    transcode: bool


def resolve_postprocess_preset(
    preset: PostprocessPreset | str,
    *,
    legacy_compatibility_mode: bool = False,
) -> PostprocessPreset:
    if legacy_compatibility_mode:
        return PostprocessPreset.TRANSCODE
    try:
        return PostprocessPreset(preset)
    except ValueError as exc:
        raise error("FORMAT_NOT_FOUND", message="不支持这个后处理预设") from exc


def postprocess_preset_from_payload(payload: dict[str, Any]) -> PostprocessPreset:
    raw = payload.get("postprocess_preset")
    if raw is None:
        return (
            PostprocessPreset.TRANSCODE
            if bool(payload.get("compatibility_mode"))
            else PostprocessPreset.REMUX
        )
    try:
        return PostprocessPreset(str(raw))
    except ValueError as exc:
        raise error("DOWNLOAD_FAILED") from exc


def build_video_postprocess_plan(
    *,
    preset: PostprocessPreset,
    requested_container: str,
    video_codec: str | None,
    audio_codec: str | None,
) -> VideoPostprocessPlan:
    if preset is PostprocessPreset.TRANSCODE:
        return VideoPostprocessPlan(
            preset=preset,
            output_container="mp4",
            transcode=not is_mp4_compatible(video_codec, audio_codec),
        )
    return VideoPostprocessPlan(
        preset=preset,
        output_container=select_output_container(
            requested_container,
            video_codec=video_codec,
            audio_codec=audio_codec,
            compatibility_mode=False,
        ),
        transcode=False,
    )
