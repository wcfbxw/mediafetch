import json
import threading
from pathlib import Path

import pytest

from app.core.errors import AppError
from app.services import downloader, parallel_downloader
from app.services.downloader import DownloadContext
from app.services.jobs import default_job_state, load_job, save_new_job
from app.services.parallel_downloader import (
    DirectFormat,
    ParallelDownloadFailed,
    ParallelDownloadUnavailable,
    connection_attempts,
    parallel_download_track,
    segment_ranges,
)


def test_segment_ranges_cover_file_without_gaps_or_overlap():
    ranges = segment_ranges(10, 3)

    assert ranges == [(0, 3), (4, 7), (8, 9)]
    assert sum(end - start + 1 for start, end in ranges) == 10


@pytest.mark.parametrize(
    ("connections", "expected"),
    [
        (1, []),
        (3, [3]),
        (4, [4]),
        (6, [6, 4]),
        (8, [8, 4]),
        (16, [16, 8, 4]),
    ],
)
def test_connection_attempts_degrade_to_four(connections, expected):
    assert connection_attempts(connections) == expected


def test_bilibili_backup_urls_are_selected_by_format_id():
    primary = "https://primary.example/path/video-30080.m4s?token=one"
    backup = "https://backup.example/path/video-30080.m4s?token=two"
    other = "https://backup.example/path/video-30112.m4s?token=three"
    play_info = {
        "data": {
            "dash": {
                "video": [
                    {"baseUrl": primary, "backupUrl": [backup]},
                    {"baseUrl": other, "backupUrl": []},
                ],
                "audio": [],
            }
        }
    }
    html = ("<script>window.__playinfo__=" + json.dumps(play_info) + "</script>").encode()
    ydl = _FakePageYdl(html)

    assert parallel_downloader._extract_bilibili_backup_urls(
        ydl,
        "https://www.bilibili.com/video/BV1test",
        "30080",
    ) == [backup]


def test_media_range_options_do_not_open_shared_cookie_file(monkeypatch):
    credential_calls = []
    monkeypatch.setattr(
        parallel_downloader,
        "configure_ytdlp_credentials",
        lambda *_args: credential_calls.append(True),
    )

    options = parallel_downloader._network_options(
        "https://www.bilibili.com/video/BV1test",
        {},
        include_credentials=False,
    )

    assert credential_calls == []
    assert "cookiefile" not in options


def test_parallel_download_combines_segments_and_reports_progress(
    redis_client,
    test_settings,
    monkeypatch,
    tmp_path: Path,
):
    payload = (b"mediafetch-parallel-range-test" * 120_000)[: 3 * 1024 * 1024 + 7]
    test_settings.parallel_download_enabled = True
    test_settings.parallel_download_connections = 3
    test_settings.parallel_download_min_split_size_mb = 1
    save_new_job(redis_client, default_job_state("parallel-job"))
    context = DownloadContext(redis_client, "parallel-job", {})
    direct = DirectFormat(
        url="https://cdn.example/video",
        extension="mp4",
        headers={},
    )

    monkeypatch.setattr(parallel_downloader, "_extract_direct_format", lambda *_args: direct)
    monkeypatch.setattr(
        parallel_downloader,
        "_probe_total_bytes",
        lambda *_args: len(payload),
    )

    def fake_segment(**kwargs):
        start = kwargs["start"]
        end = kwargs["end"]
        data = payload[start : end + 1]
        kwargs["output"].write_bytes(data)
        kwargs["progress"].advance(len(data))

    monkeypatch.setattr(parallel_downloader, "_download_segment", fake_segment)
    output = parallel_download_track(
        context,
        source_url="https://www.bilibili.com/video/BV1test",
        format_id="video-format",
        temp_dir=tmp_path,
        prefix="video",
        status="downloading_video",
        progress_start=1,
        progress_span=90,
        message="downloading",
    )

    assert output.read_bytes() == payload
    assert not list(tmp_path.glob("*.part"))
    state = load_job(redis_client, "parallel-job")
    assert state["status"] == "downloading_video"
    assert state["downloaded_bytes"] == len(payload)
    assert state["progress"] == 91


def test_parallel_download_retries_invalid_range_response(
    redis_client,
    monkeypatch,
    tmp_path: Path,
):
    payload = b"test"
    save_new_job(redis_client, default_job_state("range-retry-job"))
    context = DownloadContext(redis_client, "range-retry-job", {})
    progress = parallel_downloader._Progress(
        context,
        total_bytes=len(payload),
        status="downloading_video",
        progress_start=1,
        progress_span=90,
        message="downloading",
    )
    responses = [
        _FakeResponse(200, "", b""),
        _FakeResponse(206, "bytes 0-3/4", payload),
    ]

    def fake_open_range(*_args, **_kwargs):
        return _FakeYdl(), responses.pop(0)

    monkeypatch.setattr(parallel_downloader, "_open_range", fake_open_range)
    monkeypatch.setattr(parallel_downloader.time, "sleep", lambda _seconds: None)
    output = tmp_path / "segment.part"
    parallel_downloader._download_segment(
        direct=DirectFormat("https://cdn.example/video", "mp4", {}),
        source_url="https://www.bilibili.com/video/BV1test",
        start=0,
        end=3,
        output=output,
        progress=progress,
        stop=threading.Event(),
        chunk_size=4,
    )

    assert output.read_bytes() == payload
    assert not responses


def test_parallel_download_switches_to_backup_cdn_after_early_eof(
    redis_client,
    monkeypatch,
    tmp_path: Path,
):
    save_new_job(redis_client, default_job_state("backup-cdn-job"))
    context = DownloadContext(redis_client, "backup-cdn-job", {})
    progress = parallel_downloader._Progress(
        context,
        total_bytes=4,
        status="downloading_video",
        progress_start=1,
        progress_span=90,
        message="downloading",
    )
    primary = "https://primary.example/video"
    backup = "https://backup.example/video"
    requests = []

    def fake_open_range(_direct, _source_url, start, end, *, media_url=None):
        requests.append((media_url, start, end))
        if media_url == primary:
            return _FakeYdl(), _FakeResponse(206, "bytes 0-3/4", b"ab")
        return _FakeYdl(), _FakeResponse(206, "bytes 2-3/4", b"cd")

    monkeypatch.setattr(parallel_downloader, "_open_range", fake_open_range)
    monkeypatch.setattr(parallel_downloader.time, "sleep", lambda _seconds: None)
    output = tmp_path / "backup.segment.part"
    parallel_downloader._download_segment(
        direct=DirectFormat(primary, "mp4", {}, (backup,)),
        source_url="https://www.bilibili.com/video/BV1test",
        start=0,
        end=3,
        output=output,
        progress=progress,
        stop=threading.Event(),
        chunk_size=4,
    )

    assert output.read_bytes() == b"abcd"
    assert requests == [(primary, 0, 3), (backup, 2, 3)]


def test_parallel_download_reconnects_at_bounded_chunk_boundaries(
    redis_client,
    monkeypatch,
    tmp_path: Path,
):
    payload = b"0123456789"
    save_new_job(redis_client, default_job_state("bounded-chunk-job"))
    context = DownloadContext(redis_client, "bounded-chunk-job", {})
    progress = parallel_downloader._Progress(
        context,
        total_bytes=len(payload),
        status="downloading_video",
        progress_start=1,
        progress_span=90,
        message="downloading",
    )
    requested_ranges = []

    def fake_open_range(_direct, _source_url, start, end, **_kwargs):
        requested_ranges.append((start, end))
        return (
            _FakeYdl(),
            _FakeResponse(
                206,
                f"bytes {start}-{end}/{len(payload)}",
                payload[start : end + 1],
            ),
        )

    monkeypatch.setattr(parallel_downloader, "_open_range", fake_open_range)
    output = tmp_path / "bounded.segment.part"
    parallel_downloader._download_segment(
        direct=DirectFormat("https://cdn.example/video", "mp4", {}),
        source_url="https://www.bilibili.com/video/BV1test",
        start=0,
        end=len(payload) - 1,
        output=output,
        progress=progress,
        stop=threading.Event(),
        chunk_size=4,
    )

    assert output.read_bytes() == payload
    assert requested_ranges == [(0, 3), (4, 7), (8, 9)]


def test_parallel_download_degrades_connections(
    redis_client,
    test_settings,
    monkeypatch,
    tmp_path: Path,
):
    test_settings.parallel_download_connections = 8
    test_settings.parallel_download_min_split_size_mb = 1
    save_new_job(redis_client, default_job_state("degrade-job"))
    context = DownloadContext(redis_client, "degrade-job", {})
    direct = DirectFormat("https://cdn.example/video", "mp4", {})
    extractions = []

    def fake_extract(*_args):
        extractions.append(True)
        return direct

    monkeypatch.setattr(parallel_downloader, "_extract_direct_format", fake_extract)
    monkeypatch.setattr(
        parallel_downloader,
        "_probe_total_bytes",
        lambda *_: 16 * 1024 * 1024,
    )
    monkeypatch.setattr(parallel_downloader.time, "sleep", lambda _seconds: None)
    attempts = []

    def fake_once(*_args, **kwargs):
        attempts.append(kwargs["connections"])
        if kwargs["connections"] == 8:
            raise ParallelDownloadFailed("http_status_200")
        output = tmp_path / "video.mp4"
        output.write_bytes(b"complete")
        return output

    monkeypatch.setattr(parallel_downloader, "_parallel_download_once", fake_once)
    output = parallel_download_track(
        context,
        source_url="https://www.bilibili.com/video/BV1test",
        format_id="video-format",
        temp_dir=tmp_path,
        prefix="video",
        status="downloading_video",
        progress_start=1,
        progress_span=90,
        message="downloading",
    )

    assert output.read_bytes() == b"complete"
    assert attempts == [8, 4]
    assert len(extractions) == 2
    assert "4" in load_job(redis_client, "degrade-job")["message"]


def test_parallel_download_exhaustion_requests_standard_fallback(
    redis_client,
    test_settings,
    monkeypatch,
    tmp_path: Path,
):
    test_settings.parallel_download_connections = 8
    test_settings.parallel_download_min_split_size_mb = 1
    save_new_job(redis_client, default_job_state("fallback-job"))
    context = DownloadContext(redis_client, "fallback-job", {})
    direct = DirectFormat("https://cdn.example/video", "mp4", {})
    monkeypatch.setattr(parallel_downloader, "_extract_direct_format", lambda *_: direct)
    monkeypatch.setattr(
        parallel_downloader,
        "_probe_total_bytes",
        lambda *_: 16 * 1024 * 1024,
    )
    monkeypatch.setattr(parallel_downloader.time, "sleep", lambda _seconds: None)
    attempts = []

    def always_fail(*_args, **kwargs):
        attempts.append(kwargs["connections"])
        raise ParallelDownloadFailed("network_TimeoutError")

    monkeypatch.setattr(parallel_downloader, "_parallel_download_once", always_fail)
    with pytest.raises(ParallelDownloadUnavailable):
        parallel_download_track(
            context,
            source_url="https://www.bilibili.com/video/BV1test",
            format_id="video-format",
            temp_dir=tmp_path,
            prefix="video",
            status="downloading_video",
            progress_start=1,
            progress_span=90,
            message="downloading",
        )

    assert attempts == [8, 4]


def test_track_download_uses_ytdlp_after_parallel_exhaustion(
    redis_client,
    monkeypatch,
    tmp_path: Path,
):
    save_new_job(redis_client, default_job_state("standard-fallback-job"))
    context = DownloadContext(redis_client, "standard-fallback-job", {})
    captured_options = {}

    def parallel_unavailable(*_args, **_kwargs):
        raise ParallelDownloadUnavailable()

    class FakeYoutubeDL:
        def __init__(self, options):
            captured_options.update(options)

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def download(self, _urls):
            output = Path(str(captured_options["outtmpl"]).replace("%(ext)s", "mp4"))
            output.write_bytes(b"standard-downloader")

    monkeypatch.setattr(downloader, "parallel_download_track", parallel_unavailable)
    monkeypatch.setattr(downloader, "SafeYoutubeDL", FakeYoutubeDL)
    output = downloader._download_track(
        context,
        url="https://www.bilibili.com/video/BV1test",
        format_id="video-format",
        temp_dir=tmp_path,
        prefix="video",
        status="downloading_video",
        progress_start=1,
        progress_span=90,
        message="downloading",
    )

    assert output.read_bytes() == b"standard-downloader"
    assert captured_options["continuedl"] is True
    assert captured_options["http_chunk_size"] == 4 * 1024 * 1024
    assert context.completed_bytes == len(b"standard-downloader")


def test_incomplete_bilibili_track_is_rejected(tmp_path: Path):
    output = tmp_path / "truncated.mp4"
    output.write_bytes(b"too-short")

    with pytest.raises(AppError):
        downloader._validate_track_size(
            output,
            expected_size=1_000,
            source_url="https://www.bilibili.com/video/BV1test",
        )

    assert not output.exists()


def test_truncated_video_duration_is_rejected(monkeypatch, tmp_path: Path):
    output = tmp_path / "truncated.mp4"
    output.write_bytes(b"media")
    monkeypatch.setattr(downloader, "_probe_stream_duration", lambda *_args: 80.0)

    with pytest.raises(AppError):
        downloader._validate_output_duration(output, 415, has_video=True)

    assert not output.exists()


@pytest.mark.parametrize(
    ("probe_output", "expected"),
    [
        ({"streams": [{"duration": "80.0"}], "format": {"duration": "415.0"}}, 80.0),
        ({"streams": [{}], "format": {"duration": "14.2"}}, 14.2),
    ],
)
def test_duration_probe_prefers_stream_and_falls_back_to_container(
    monkeypatch,
    tmp_path: Path,
    probe_output,
    expected,
):
    class Result:
        returncode = 0
        stdout = json.dumps(probe_output)

    monkeypatch.setattr(downloader.subprocess, "run", lambda *_args, **_kwargs: Result())

    assert downloader._probe_stream_duration(tmp_path / "video.mkv", "v:0") == expected


class _FakeYdl:
    def close(self):
        return None


class _FakePageYdl:
    def __init__(self, body: bytes):
        self.body = body

    def urlopen(self, _request):
        return _FakeResponse(200, "", self.body)


class _FakeResponse:
    def __init__(self, status: int, content_range: str, body: bytes):
        self.status = status
        self.content_range = content_range
        self.body = body
        self.offset = 0

    def get_header(self, name: str, default: str = "") -> str:
        return self.content_range if name.lower() == "content-range" else default

    def read(self, size: int) -> bytes:
        chunk = self.body[self.offset : self.offset + size]
        self.offset += len(chunk)
        return chunk

    def close(self):
        return None
