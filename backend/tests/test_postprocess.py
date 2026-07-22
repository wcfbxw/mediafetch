import pytest

from app.core.errors import AppError
from app.services.postprocess import (
    PostprocessPreset,
    build_video_postprocess_plan,
    postprocess_preset_from_payload,
    resolve_postprocess_preset,
)


def test_remux_uses_a_codec_compatible_container_without_transcoding():
    plan = build_video_postprocess_plan(
        preset=PostprocessPreset.REMUX,
        requested_container="mp4",
        video_codec="vp9",
        audio_codec="opus",
    )

    assert plan.output_container == "webm"
    assert plan.transcode is False


def test_transcode_outputs_mp4_only_when_codecs_need_conversion():
    incompatible = build_video_postprocess_plan(
        preset=PostprocessPreset.TRANSCODE,
        requested_container="webm",
        video_codec="vp9",
        audio_codec="opus",
    )
    compatible = build_video_postprocess_plan(
        preset=PostprocessPreset.TRANSCODE,
        requested_container="webm",
        video_codec="avc1.640028",
        audio_codec="mp4a.40.2",
    )

    assert incompatible.output_container == "mp4"
    assert incompatible.transcode is True
    assert compatible.output_container == "mp4"
    assert compatible.transcode is False


def test_legacy_compatibility_mode_maps_to_transcode_preset():
    assert (
        resolve_postprocess_preset(
            PostprocessPreset.REMUX,
            legacy_compatibility_mode=True,
        )
        is PostprocessPreset.TRANSCODE
    )
    assert (
        postprocess_preset_from_payload({"compatibility_mode": True})
        is PostprocessPreset.TRANSCODE
    )


def test_worker_rejects_an_unknown_postprocess_preset():
    with pytest.raises(AppError) as caught:
        postprocess_preset_from_payload({"postprocess_preset": "crop-or-delogo"})

    assert caught.value.code == "DOWNLOAD_FAILED"
