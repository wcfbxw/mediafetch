import pytest

from app.core.errors import AppError
from app.services.formats import (
    choose_audio_format,
    find_format,
    is_mp4_compatible,
    normalize_formats,
    select_output_container,
)


def raw_format(
    format_id: str,
    *,
    height: int | None = None,
    ext: str = "mp4",
    vcodec: str = "avc1.640028",
    acodec: str = "none",
    fps: int = 30,
    tbr: int = 1000,
):
    return {
        "format_id": format_id,
        "url": f"https://cdn.example/{format_id}",
        "protocol": "https",
        "height": height,
        "width": height and int(height * 16 / 9),
        "ext": ext,
        "vcodec": vcodec,
        "acodec": acodec,
        "fps": fps,
        "tbr": tbr,
    }


def test_format_normalization_filters_invalid_and_separates_audio():
    raw = [
        raw_format("v1080", height=1080),
        raw_format("combined", height=720, acodec="mp4a.40.2"),
        raw_format("audio", height=None, ext="m4a", vcodec="none", acodec="mp4a.40.2"),
        {**raw_format("story", height=90), "format_note": "storyboard"},
        {**raw_format("drm", height=1080), "has_drm": True},
        {**raw_format("image"), "ext": "jpg", "vcodec": "none"},
        {"format_id": "missing-url", "vcodec": "h264", "height": 360},
    ]
    video, audio = normalize_formats(raw, 60)
    assert [item["id"] for item in video] == ["v1080", "combined"]
    assert [item["id"] for item in audio] == ["audio"]
    assert video[0]["label"] == "1080P"
    assert video[0]["requires_merge"] is True
    assert audio[0]["label"] == "仅音频"


def test_duplicate_resolution_sorting_uses_documented_preference():
    raw = [
        raw_format("vp9-60", height=1080, ext="webm", vcodec="vp9", fps=60, tbr=2500),
        raw_format("h264-video", height=1080, ext="mp4", fps=30, tbr=2200),
        raw_format(
            "combined",
            height=1080,
            ext="webm",
            vcodec="vp9",
            acodec="opus",
            fps=30,
            tbr=1800,
        ),
    ]
    video, _ = normalize_formats(raw, 120)
    assert [item["id"] for item in video] == ["combined", "h264-video", "vp9-60"]
    assert video[0]["preferred"] is True
    assert sum(item["preferred"] for item in video) == 1


def test_vertical_video_uses_short_edge_for_quality_label():
    vertical = raw_format("vertical", height=1920)
    vertical["width"] = 1080

    video, _ = normalize_formats([vertical], 15)

    assert video[0]["label"] == "1080P"


def test_invalid_format_id_is_rejected():
    with pytest.raises(AppError) as caught:
        find_format([{"id": "valid"}], "valid/but/not-present")
    assert caught.value.code == "FORMAT_NOT_FOUND"


def test_compatible_audio_is_selected():
    video = {"has_audio": False, "extension": "mp4", "video_codec": "avc1"}
    audio = [
        {"id": "opus", "audio_codec": "opus", "bitrate": 160, "preferred": True},
        {"id": "aac", "audio_codec": "mp4a.40.2", "bitrate": 128, "preferred": False},
    ]
    assert choose_audio_format(audio, video)["id"] == "aac"


def test_container_is_not_blindly_forced():
    assert (
        select_output_container(
            "mp4",
            video_codec="vp9",
            audio_codec="opus",
            compatibility_mode=False,
        )
        == "webm"
    )
    assert (
        select_output_container(
            "webm",
            video_codec="avc1",
            audio_codec="mp4a.40.2",
            compatibility_mode=True,
        )
        == "mp4"
    )


def test_h264_aac_is_already_compatible_without_transcoding():
    assert is_mp4_compatible("avc1.640033", "mp4a.40.2") is True
    assert is_mp4_compatible("hev1.1.6.L150.90", "mp4a.40.2") is False
    assert is_mp4_compatible("avc1.640033", "opus") is False
