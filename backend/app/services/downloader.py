import json
import logging
import queue
import shutil
import subprocess
import tempfile
import threading
import time
from pathlib import Path
from typing import Any, cast

from redis import Redis
from yt_dlp.utils import DownloadError

from app.core.config import get_settings
from app.core.errors import AppError, error
from app.core.logging import redact_url
from app.services.extractor import QuietLogger, SafeYoutubeDL, map_ytdlp_error
from app.services.file_tokens import create_file_token, sanitize_filename
from app.services.jobs import (
    JobCancelled,
    cancellation_requested,
    release_client_slot,
    update_job,
)
from app.services.parallel_downloader import (
    ParallelDownloadFailed,
    ParallelDownloadUnavailable,
    parallel_download_track,
)
from app.services.platform_credentials import configure_ytdlp_credentials, is_bilibili_url
from app.services.postprocess import (
    VideoPostprocessPlan,
    build_video_postprocess_plan,
    postprocess_preset_from_payload,
)

logger = logging.getLogger(__name__)


class DownloadLimitExceeded(Exception):
    pass


class DownloadContext:
    def __init__(self, redis_client: Redis, job_id: str, payload: dict[str, Any]):
        self.redis = redis_client
        self.job_id = job_id
        self.payload = payload
        self.settings = get_settings()
        self.started_at = time.monotonic()
        self.completed_bytes = 0

    def check_limits(self, current_bytes: int = 0) -> None:
        if cancellation_requested(self.redis, self.job_id):
            raise JobCancelled()
        if time.monotonic() - self.started_at > self.settings.download_timeout_seconds:
            raise error("DOWNLOAD_FAILED", message="下载任务超时")
        if self.completed_bytes + current_bytes > self.settings.max_file_size_bytes:
            raise DownloadLimitExceeded()

    def progress_hook(self, status: str, start: float, span: float, message: str):
        def hook(data: dict[str, Any]) -> None:
            downloaded = int(data.get("downloaded_bytes") or 0)
            self.check_limits(downloaded)
            total = int(data.get("total_bytes") or data.get("total_bytes_estimate") or 0) or None
            fraction = (downloaded / total) if total else 0
            progress = start + min(max(fraction, 0), 1) * span
            update_job(
                self.redis,
                self.job_id,
                status=status,
                progress=progress,
                speed=int(data.get("speed") or 0) or None,
                downloaded_bytes=self.completed_bytes + downloaded,
                total_bytes=(self.completed_bytes + total) if total else None,
                eta=int(data.get("eta") or 0) or None,
                message=message,
            )

        return hook


def _track_file(temp_dir: Path, prefix: str) -> Path:
    candidates = sorted(
        (
            path
            for path in temp_dir.glob(f"{prefix}.*")
            if path.is_file() and not path.name.endswith((".part", ".ytdl", ".temp"))
        ),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    if not candidates:
        raise error("DOWNLOAD_FAILED")
    return candidates[0]


def _download_track(
    context: DownloadContext,
    *,
    url: str,
    format_id: str,
    temp_dir: Path,
    prefix: str,
    status: str,
    progress_start: float,
    progress_span: float,
    message: str,
    expected_size: int | None = None,
) -> Path:
    context.check_limits()
    if is_bilibili_url(url):
        try:
            downloaded = parallel_download_track(
                context,
                source_url=url,
                format_id=format_id,
                temp_dir=temp_dir,
                prefix=prefix,
                status=status,
                progress_start=progress_start,
                progress_span=progress_span,
                message=message,
            )
        except ParallelDownloadUnavailable:
            logger.info("Parallel ranges unavailable for %s; using yt-dlp", redact_url(url))
        except (JobCancelled, DownloadLimitExceeded, AppError):
            raise
        except DownloadError as exc:
            raise map_ytdlp_error(exc) from exc
        except ParallelDownloadFailed as exc:
            logger.error("Parallel media download failed for %s", redact_url(url))
            raise error("DOWNLOAD_FAILED") from exc
        except Exception as exc:
            logger.error(
                "Parallel media download failed for %s error_type=%s",
                redact_url(url),
                type(exc).__name__,
            )
            raise error("DOWNLOAD_FAILED") from exc
        else:
            _validate_track_size(downloaded, expected_size, url)
            context.completed_bytes += downloaded.stat().st_size
            context.check_limits()
            return downloaded

    options: dict[str, Any] = {
        "format": format_id,
        "outtmpl": str(temp_dir / f"{prefix}.%(ext)s"),
        "noplaylist": True,
        "continuedl": True,
        "overwrites": True,
        "nopart": False,
        "quiet": True,
        "no_warnings": True,
        "cachedir": False,
        "socket_timeout": 30,
        "retries": 5,
        "fragment_retries": 5,
        "file_access_retries": 3,
        "http_chunk_size": context.settings.parallel_download_chunk_size_mb * 1024 * 1024,
        "progress_hooks": [context.progress_hook(status, progress_start, progress_span, message)],
        "logger": QuietLogger(),
    }
    if context.settings.ytdlp_proxy:
        options["proxy"] = context.settings.ytdlp_proxy
    configure_ytdlp_credentials(options, url)
    try:
        with SafeYoutubeDL(options) as ydl:
            ydl.download([url])
    except (JobCancelled, DownloadLimitExceeded, AppError):
        raise
    except DownloadError as exc:
        if cancellation_requested(context.redis, context.job_id):
            raise JobCancelled() from exc
        raise map_ytdlp_error(exc) from exc
    except Exception as exc:
        logger.error(
            "Track download failed for %s error_type=%s",
            redact_url(url),
            type(exc).__name__,
        )
        raise error("DOWNLOAD_FAILED") from exc
    downloaded = _track_file(temp_dir, prefix)
    _validate_track_size(downloaded, expected_size, url)
    context.completed_bytes += downloaded.stat().st_size
    context.check_limits()
    return downloaded


def _validate_track_size(path: Path, expected_size: int | None, source_url: str) -> None:
    if not is_bilibili_url(source_url) or not expected_size or expected_size <= 0:
        return
    actual_size = path.stat().st_size
    if actual_size >= expected_size * 0.9:
        return
    logger.error(
        "Downloaded track is incomplete actual_bytes=%s expected_bytes=%s",
        actual_size,
        expected_size,
    )
    path.unlink(missing_ok=True)
    raise error("DOWNLOAD_FAILED")


def _probe_stream_duration(path: Path, stream_selector: str) -> float | None:
    try:
        result = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-select_streams",
                stream_selector,
                "-show_entries",
                "stream=duration:format=duration",
                "-of",
                "json",
                str(path),
            ],
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        logger.error("FFprobe validation failed error_type=%s", type(exc).__name__)
        return None
    if result.returncode:
        logger.error("FFprobe validation returned code=%s", result.returncode)
        return None
    try:
        probe = json.loads(result.stdout)
    except (TypeError, ValueError):
        return None
    for stream in probe.get("streams") or []:
        try:
            return float(stream["duration"])
        except (KeyError, TypeError, ValueError):
            continue
    try:
        return float(probe["format"]["duration"])
    except (KeyError, TypeError, ValueError):
        return None


def _validate_output_duration(path: Path, expected_duration: int, *, has_video: bool) -> None:
    if expected_duration <= 0:
        return
    actual_duration = _probe_stream_duration(path, "v:0" if has_video else "a:0")
    minimum_duration = expected_duration - max(5.0, expected_duration * 0.05)
    if actual_duration is not None and actual_duration >= minimum_duration:
        return
    logger.error(
        "Output duration validation failed actual_seconds=%s expected_seconds=%s",
        actual_duration,
        expected_duration,
    )
    path.unlink(missing_ok=True)
    raise error("DOWNLOAD_FAILED")


def _run_ffmpeg(
    context: DownloadContext,
    args: list[str],
    *,
    output: Path,
    failure_code: str,
    progress_duration: int | None = None,
    progress_message: str = "正在转换格式",
) -> None:
    context.check_limits()
    settings = context.settings
    started = time.monotonic()
    command = args
    report_progress = bool(progress_duration and progress_duration > 0)
    if report_progress:
        command = args[:-1] + ["-progress", "pipe:1", "-nostats", args[-1]]
    progress_lines: queue.SimpleQueue[str] = queue.SimpleQueue()
    with tempfile.TemporaryFile(mode="w+b") as stderr:
        process = subprocess.Popen(
            command,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE if report_progress else subprocess.DEVNULL,
            stderr=stderr,
            close_fds=True,
        )
        reader_thread: threading.Thread | None = None
        if report_progress and process.stdout is not None:
            progress_stream = process.stdout

            def read_progress() -> None:
                for raw_line in iter(progress_stream.readline, b""):
                    progress_lines.put(raw_line.decode("utf-8", "replace").strip())

            reader_thread = threading.Thread(
                target=read_progress,
                name="ffmpeg-progress",
                daemon=True,
            )
            reader_thread.start()

        def publish_progress() -> None:
            if not progress_duration:
                return
            latest_seconds: float | None = None
            while True:
                try:
                    line = progress_lines.get_nowait()
                except queue.Empty:
                    break
                key, separator, value = line.partition("=")
                if separator and key in {"out_time_us", "out_time_ms"}:
                    try:
                        latest_seconds = int(value) / 1_000_000
                    except ValueError:
                        continue
            if latest_seconds is None:
                return
            fraction = min(max(latest_seconds / progress_duration, 0), 1)
            elapsed = max(time.monotonic() - started, 0.001)
            media_rate = latest_seconds / elapsed
            remaining = max(0.0, progress_duration - latest_seconds)
            update_job(
                context.redis,
                context.job_id,
                status="processing",
                progress=92 + fraction * 7,
                speed=None,
                eta=int(remaining / media_rate) if media_rate > 0 else None,
                message=progress_message,
            )

        try:
            while process.poll() is None:
                publish_progress()
                if cancellation_requested(context.redis, context.job_id):
                    process.terminate()
                    try:
                        process.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        process.kill()
                    raise JobCancelled()
                if time.monotonic() - started > settings.ffmpeg_timeout_seconds:
                    process.kill()
                    raise error(failure_code, message="媒体处理超时")
                if output.exists() and output.stat().st_size > settings.max_file_size_bytes:
                    process.kill()
                    raise DownloadLimitExceeded()
                time.sleep(0.25)
            publish_progress()
            if process.returncode:
                stderr.seek(0)
                detail = stderr.read(16_384).decode("utf-8", "replace")
                logger.error("FFmpeg failed: %s", detail)
                raise error(failure_code)
        finally:
            if process.poll() is None:
                process.kill()
                process.wait()
            process_stdout = getattr(process, "stdout", None)
            if process_stdout is not None:
                process_stdout.close()
            if reader_thread is not None:
                reader_thread.join(timeout=1)


def _ffmpeg_base() -> list[str]:
    settings = get_settings()
    return [
        "ffmpeg",
        "-nostdin",
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-threads",
        str(settings.ffmpeg_threads),
    ]


def _create_video_output(
    context: DownloadContext,
    *,
    video_path: Path,
    audio_path: Path | None,
    output_path: Path,
    plan: VideoPostprocessPlan,
) -> None:
    inputs = ["-i", str(video_path)]
    if audio_path:
        inputs.extend(["-i", str(audio_path)])
    maps = ["-map", "0:v:0"]
    if audio_path:
        maps.extend(["-map", "1:a:0"])
    else:
        maps.extend(["-map", "0:a?"])

    if plan.transcode:
        update_job(
            context.redis,
            context.job_id,
            status="processing",
            progress=92,
            speed=None,
            eta=None,
            message="正在转换为兼容格式",
        )
        codec_args = [
            "-c:v",
            "libx264",
            "-preset",
            context.settings.ffmpeg_x264_preset,
            "-crf",
            "23",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-b:a",
            "192k",
            "-movflags",
            "+faststart",
        ]
        failure_code = "TRANSCODE_FAILED"
    else:
        update_job(
            context.redis,
            context.job_id,
            status="merging",
            progress=92,
            speed=None,
            eta=None,
            message="正在无损合并音视频",
        )
        codec_args = ["-c", "copy"]
        if output_path.suffix == ".mp4":
            codec_args.extend(["-movflags", "+faststart"])
        failure_code = "MERGE_FAILED"
    _run_ffmpeg(
        context,
        _ffmpeg_base() + inputs + maps + codec_args + [str(output_path)],
        output=output_path,
        failure_code=failure_code,
        progress_duration=(
            int(context.payload.get("duration") or 0) if plan.transcode else None
        ),
        progress_message="正在转换为兼容格式",
    )


def _create_audio_output(
    context: DownloadContext,
    *,
    source: Path,
    output: Path,
    container: str,
    audio_codec: str | None,
) -> None:
    if container == "original":
        shutil.copy2(source, output)
        return
    update_job(
        context.redis,
        context.job_id,
        status="processing",
        progress=92,
        speed=None,
        eta=None,
        message="正在处理音频格式",
    )
    if container == "mp3":
        codec_args = [
            "-vn",
            "-c:a",
            "libmp3lame",
            "-q:a",
            str(context.settings.audio_mp3_quality),
        ]
    elif audio_codec and any(marker in audio_codec.lower() for marker in ("aac", "mp4a")):
        codec_args = ["-vn", "-c:a", "copy", "-movflags", "+faststart"]
    else:
        codec_args = ["-vn", "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart"]
    _run_ffmpeg(
        context,
        _ffmpeg_base() + ["-i", str(source)] + codec_args + [str(output)],
        output=output,
        failure_code="TRANSCODE_FAILED",
    )


def execute_download(redis_client: Redis, job_id: str, payload: dict[str, Any]) -> None:
    settings = get_settings()
    context = DownloadContext(redis_client, job_id, payload)
    client_ip = str(payload.get("client_ip") or "")
    temp_dir = settings.temp_dir / job_id
    final_dir = settings.downloads_dir / job_id
    try:
        context.check_limits()
        temp_dir.mkdir(parents=True, exist_ok=False)
        final_dir.mkdir(parents=True, exist_ok=False)

        selected = payload["video_format"]
        audio = payload.get("audio_format")
        source_url = payload["source_url"]
        has_video = bool(selected["has_video"])
        if has_video:
            video_span = 84.0 if audio else 90.0
            video_path = _download_track(
                context,
                url=source_url,
                format_id=selected["id"],
                temp_dir=temp_dir,
                prefix="video",
                status="downloading_video",
                progress_start=1.0,
                progress_span=video_span,
                message="正在下载视频轨",
                expected_size=selected.get("estimated_size"),
            )
            audio_path = None
            if audio:
                audio_path = _download_track(
                    context,
                    url=source_url,
                    format_id=audio["id"],
                    temp_dir=temp_dir,
                    prefix="audio",
                    status="downloading_audio",
                    progress_start=85.0,
                    progress_span=6.0,
                    message="正在下载音频轨",
                    expected_size=audio.get("estimated_size"),
                )
            audio_codec = (audio or selected).get("audio_codec")
            plan = build_video_postprocess_plan(
                preset=postprocess_preset_from_payload(payload),
                requested_container=payload["output_container"],
                video_codec=selected.get("video_codec"),
                audio_codec=audio_codec,
            )
            container = plan.output_container
            filename = sanitize_filename(f"{payload['title']}.{container}")
            output_path = final_dir / filename
            _create_video_output(
                context,
                video_path=video_path,
                audio_path=audio_path,
                output_path=output_path,
                plan=plan,
            )
        else:
            source_path = _download_track(
                context,
                url=source_url,
                format_id=selected["id"],
                temp_dir=temp_dir,
                prefix="audio",
                status="downloading_audio",
                progress_start=1.0,
                progress_span=90.0,
                message="正在下载音频",
                expected_size=selected.get("estimated_size"),
            )
            container = payload["output_container"]
            extension = source_path.suffix.lstrip(".") if container == "original" else container
            filename = sanitize_filename(f"{payload['title']}.{extension}")
            output_path = final_dir / filename
            _create_audio_output(
                context,
                source=source_path,
                output=output_path,
                container=container,
                audio_codec=selected.get("audio_codec"),
            )

        context.check_limits()
        if not output_path.is_file() or output_path.stat().st_size <= 0:
            raise error("DOWNLOAD_FAILED")
        if output_path.stat().st_size > settings.max_file_size_bytes:
            raise DownloadLimitExceeded()
        _validate_output_duration(
            output_path,
            int(payload.get("duration") or 0),
            has_video=has_video,
        )

        token, _ = create_file_token(redis_client, job_id, output_path)
        update_job(
            redis_client,
            job_id,
            status="ready",
            progress=100,
            speed=None,
            downloaded_bytes=output_path.stat().st_size,
            total_bytes=output_path.stat().st_size,
            eta=0,
            message="文件已准备完成",
            download_url=f"/api/v1/files/{token}",
            error=None,
            filename=filename,
            expires_at=int(time.time()) + settings.file_ttl_seconds,
        )
    except JobCancelled:
        try:
            update_job(
                redis_client,
                job_id,
                status="cancelled",
                message="任务已取消",
                speed=None,
                eta=None,
            )
        except JobCancelled:
            pass
    except DownloadLimitExceeded:
        update_job(
            redis_client,
            job_id,
            status="failed",
            message="文件超过服务器允许的大小",
            speed=None,
            eta=None,
            error={"code": "FILE_TOO_LARGE", "message": "文件超过服务器允许的大小"},
        )
    except AppError as exc:
        code = (
            exc.code
            if exc.code in {"DOWNLOAD_FAILED", "MERGE_FAILED", "TRANSCODE_FAILED"}
            else "DOWNLOAD_FAILED"
        )
        public = error(code)
        update_job(
            redis_client,
            job_id,
            status="failed",
            message=public.message,
            speed=None,
            eta=None,
            error={"code": public.code, "message": public.message},
        )
    except Exception:
        logger.exception("Unhandled download failure job_id=%s", job_id)
        public = error("DOWNLOAD_FAILED")
        update_job(
            redis_client,
            job_id,
            status="failed",
            message=public.message,
            speed=None,
            eta=None,
            error={"code": public.code, "message": public.message},
        )
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)
        try:
            encoded_state = cast(str | None, redis_client.get(f"job:{job_id}"))
            state = json.loads(encoded_state) if encoded_state else {}
            if state.get("status") != "ready":
                shutil.rmtree(final_dir, ignore_errors=True)
        finally:
            release_client_slot(redis_client, client_ip, job_id)
            redis_client.delete(
                f"job-payload:{job_id}",
                f"job-owner:{job_id}",
            )
