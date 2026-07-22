import io
from pathlib import Path

import pytest
from yt_dlp.cookies import YoutubeDLCookieJar
from yt_dlp.networking._urllib import HTTPHandler, RedirectHandler
from yt_dlp.utils import DownloadError

from app.core.errors import AppError
from app.services import downloader
from app.services.downloader import DownloadContext, _run_ffmpeg
from app.services.extractor import (
    PinnedHTTPHandler,
    QuietLogger,
    SafeUrllibRH,
    ValidatingRedirectHandler,
    map_ytdlp_error,
)
from app.services.jobs import default_job_state, load_job, save_new_job


@pytest.mark.parametrize(
    ("message", "code"),
    [
        ("Unsupported URL: test", "UNSUPPORTED_URL"),
        ("This video is unavailable", "VIDEO_UNAVAILABLE"),
        ("Private video", "PRIVATE_VIDEO"),
        ("Sign in to confirm your age", "LOGIN_REQUIRED"),
        ("This format is DRM protected", "DRM_PROTECTED"),
    ],
)
def test_ytdlp_error_mapping(message: str, code: str):
    assert map_ytdlp_error(DownloadError(message)).code == code


def test_safe_urllib_opener_replaces_network_handlers():
    request_handler = SafeUrllibRH(logger=QuietLogger())

    opener = request_handler._create_instance({}, YoutubeDLCookieJar())

    assert any(isinstance(item, PinnedHTTPHandler) for item in opener.handlers)
    assert any(isinstance(item, ValidatingRedirectHandler) for item in opener.handlers)
    assert not any(
        isinstance(item, HTTPHandler) and not isinstance(item, PinnedHTTPHandler)
        for item in opener.handlers
    )
    assert not any(
        isinstance(item, RedirectHandler) and not isinstance(item, ValidatingRedirectHandler)
        for item in opener.handlers
    )


def test_ffmpeg_error_mapping(
    redis_client,
    test_settings,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
):
    class FailedProcess:
        returncode = 1

        def poll(self):
            return 1

        def kill(self):
            return None

        def wait(self):
            return 1

    monkeypatch.setattr(downloader.subprocess, "Popen", lambda *_args, **_kwargs: FailedProcess())
    context = DownloadContext(redis_client, "job", {})
    output = tmp_path / "output.mp4"
    with pytest.raises(AppError) as caught:
        _run_ffmpeg(context, ["ffmpeg", "-version"], output=output, failure_code="MERGE_FAILED")
    assert caught.value.code == "MERGE_FAILED"


def test_ffmpeg_transcode_reports_processing_progress(
    redis_client,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
):
    commands: list[list[str]] = []

    class ProgressProcess:
        returncode = 0
        stdout = io.BytesIO(b"out_time_us=5000000\nprogress=continue\n")

        def __init__(self):
            self.poll_count = 0

        def poll(self):
            self.poll_count += 1
            return None if self.poll_count == 1 else 0

        def kill(self):
            return None

        def wait(self):
            return 0

    def fake_popen(args, **_kwargs):
        commands.append(args)
        return ProgressProcess()

    monkeypatch.setattr(downloader.subprocess, "Popen", fake_popen)
    initial = default_job_state("progress-job")
    initial["status"] = "downloading_video"
    save_new_job(redis_client, initial)
    context = DownloadContext(redis_client, "progress-job", {"duration": 10})
    _run_ffmpeg(
        context,
        ["ffmpeg", "-i", "input", str(tmp_path / "output.mp4")],
        output=tmp_path / "output.mp4",
        failure_code="TRANSCODE_FAILED",
        progress_duration=10,
    )

    state = load_job(redis_client, "progress-job")
    assert state["status"] == "processing"
    assert state["progress"] == pytest.approx(95.5)
    assert "-progress" in commands[0]
