import json
import logging
import math
import re
import shutil
import threading
import time
from concurrent.futures import Future, ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from redis import Redis
from yt_dlp.networking import Request

from app.core.config import Settings, get_settings
from app.core.errors import AppError
from app.core.security import validate_public_url_sync
from app.services.extractor import QuietLogger, SafeYoutubeDL
from app.services.jobs import update_job
from app.services.platform_credentials import configure_ytdlp_credentials, is_bilibili_url

logger = logging.getLogger(__name__)

_CONTENT_RANGE = re.compile(r"^bytes\s+(\d+)-(\d+)/(\d+)$", re.IGNORECASE)
_PLAYINFO = re.compile(r"window\.__playinfo__\s*=\s*({.+?})</script>", re.DOTALL)
_BILIBILI_FORMAT_ID = re.compile(r"-(\d+)\.m4s$")
_SAFE_EXTENSION = re.compile(r"^[a-z0-9]{2,8}$")
_MAX_PLAYINFO_PAGE_BYTES = 4 * 1024 * 1024
_ALLOWED_MEDIA_HEADERS = {
    "accept",
    "accept-language",
    "origin",
    "referer",
    "user-agent",
}


class ParallelDownloadUnavailable(Exception):
    """The media endpoint cannot be downloaded safely with HTTP ranges."""


class ParallelDownloadFailed(Exception):
    def __init__(self, reason: str = "unknown") -> None:
        self.reason = reason
        super().__init__(reason)


class _RetryableRangeError(Exception):
    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


class _ProgressStopped(Exception):
    def __init__(self, cause: Exception):
        super().__init__(type(cause).__name__)
        self.cause = cause


class _Context(Protocol):
    redis: Redis
    job_id: str
    settings: Settings
    completed_bytes: int

    def check_limits(self, current_bytes: int = 0) -> None: ...


@dataclass(frozen=True)
class DirectFormat:
    url: str
    extension: str
    headers: dict[str, str]
    backup_urls: tuple[str, ...] = ()

    @property
    def candidate_urls(self) -> tuple[str, ...]:
        return (self.url, *self.backup_urls)


def segment_ranges(total_bytes: int, connections: int) -> list[tuple[int, int]]:
    if total_bytes <= 0:
        raise ValueError("total_bytes must be positive")
    count = max(1, min(connections, total_bytes))
    size = math.ceil(total_bytes / count)
    return [
        (start, min(total_bytes - 1, start + size - 1)) for start in range(0, total_bytes, size)
    ]


def connection_attempts(connections: int) -> list[int]:
    """Return a bounded degradation sequence ending at four connections."""
    if connections <= 1:
        return []
    attempts = [connections]
    while attempts[-1] > 4:
        reduced = max(4, attempts[-1] // 2)
        if reduced == attempts[-1]:
            break
        attempts.append(reduced)
    return attempts


def _safe_media_headers(value: object) -> dict[str, str]:
    if not isinstance(value, dict):
        return {}
    headers: dict[str, str] = {}
    for raw_name, raw_value in value.items():
        name = str(raw_name).strip()
        header_value = str(raw_value).strip()
        if (
            name.lower() in _ALLOWED_MEDIA_HEADERS
            and header_value
            and len(header_value) <= 4096
            and "\r" not in header_value
            and "\n" not in header_value
        ):
            headers[name] = header_value
    return headers


def _network_options(
    source_url: str,
    headers: dict[str, str],
    *,
    include_credentials: bool = True,
) -> dict[str, Any]:
    settings = get_settings()
    options: dict[str, Any] = {
        "quiet": True,
        "no_warnings": True,
        "cachedir": False,
        "socket_timeout": 20,
        "logger": QuietLogger(),
    }
    if settings.ytdlp_proxy:
        options["proxy"] = settings.ytdlp_proxy
    if include_credentials:
        configure_ytdlp_credentials(options, source_url)
    configured_headers = options.get("http_headers")
    options["http_headers"] = {
        **headers,
        **(configured_headers if isinstance(configured_headers, dict) else {}),
    }
    return options


def _bilibili_format_id(media_url: str) -> str | None:
    match = _BILIBILI_FORMAT_ID.search(media_url.split("?", 1)[0])
    return match.group(1) if match else None


def _extract_bilibili_backup_urls(
    ydl: SafeYoutubeDL,
    source_url: str,
    format_id: str,
) -> list[str]:
    response = ydl.urlopen(Request(source_url))
    try:
        body = response.read(_MAX_PLAYINFO_PAGE_BYTES + 1)
    finally:
        response.close()
    if len(body) > _MAX_PLAYINFO_PAGE_BYTES:
        return []
    match = _PLAYINFO.search(body.decode("utf-8", "replace"))
    if not match:
        return []
    try:
        play_info = json.loads(match.group(1))
    except (TypeError, ValueError):
        return []
    dash = play_info.get("data", {}).get("dash", {})
    if not isinstance(dash, dict):
        return []

    candidates: list[str] = []
    for media_type in ("video", "audio"):
        formats = dash.get(media_type, [])
        if not isinstance(formats, list):
            continue
        for item in formats:
            if not isinstance(item, dict):
                continue
            base_url = item.get("baseUrl") or item.get("base_url")
            if not isinstance(base_url, str) or _bilibili_format_id(base_url) != format_id:
                continue
            backup_urls = item.get("backupUrl") or item.get("backup_url") or []
            if isinstance(backup_urls, list):
                candidates.extend(url for url in backup_urls if isinstance(url, str))
    return candidates


def _extract_direct_format(source_url: str, format_id: str) -> DirectFormat:
    options = _network_options(source_url, {})
    options.update(
        {
            "skip_download": True,
            "noplaylist": True,
            "extractor_retries": 2,
        }
    )
    with SafeYoutubeDL(options) as ydl:
        info = ydl.extract_info(source_url, download=False)
        if not isinstance(info, dict):
            raise ParallelDownloadUnavailable()

        formats = info.get("formats")
        if not isinstance(formats, list):
            raise ParallelDownloadUnavailable()
        selected = next(
            (
                item
                for item in formats
                if isinstance(item, dict) and str(item.get("format_id")) == format_id
            ),
            None,
        )
        if not selected:
            raise ParallelDownloadUnavailable()
        backup_urls: list[str] = []
        if is_bilibili_url(source_url):
            try:
                backup_urls = _extract_bilibili_backup_urls(ydl, source_url, format_id)
            except Exception as exc:
                logger.warning(
                    "Bilibili backup CDN discovery failed error_type=%s",
                    type(exc).__name__,
                )
    protocol = str(selected.get("protocol") or "").lower()
    media_url = selected.get("url")
    if protocol not in {"http", "https"} or not isinstance(media_url, str):
        raise ParallelDownloadUnavailable()
    checked_url = validate_public_url_sync(media_url)
    checked_backups: list[str] = []
    for backup_url in backup_urls:
        try:
            checked_backup = validate_public_url_sync(backup_url)
        except AppError:
            continue
        if checked_backup != checked_url and checked_backup not in checked_backups:
            checked_backups.append(checked_backup)
    extension = str(selected.get("ext") or "bin").lower()
    if not _SAFE_EXTENSION.fullmatch(extension):
        extension = "bin"
    return DirectFormat(
        url=checked_url,
        extension=extension,
        headers=_safe_media_headers(selected.get("http_headers")),
        backup_urls=tuple(checked_backups),
    )


def _open_range(
    direct: DirectFormat,
    source_url: str,
    start: int,
    end: int,
    *,
    media_url: str | None = None,
):
    options = _network_options(
        source_url,
        direct.headers,
        include_credentials=False,
    )
    ydl = SafeYoutubeDL(options)
    try:
        response = ydl.urlopen(
            Request(
                media_url or direct.url,
                headers={"Range": f"bytes={start}-{end}"},
            )
        )
    except Exception:
        ydl.close()
        raise
    return ydl, response


def _probe_total_bytes(direct: DirectFormat, source_url: str) -> int:
    ydl = None
    response = None
    try:
        ydl, response = _open_range(direct, source_url, 0, 0)
        if response.status != 206:
            raise ParallelDownloadUnavailable()
        match = _CONTENT_RANGE.fullmatch(response.get_header("Content-Range", "").strip())
        if not match or int(match.group(1)) != 0 or int(match.group(2)) != 0:
            raise ParallelDownloadUnavailable()
        total_bytes = int(match.group(3))
        if total_bytes <= 0:
            raise ParallelDownloadUnavailable()
        response.read(1)
        return total_bytes
    except AppError:
        raise
    except ParallelDownloadUnavailable:
        raise
    except Exception as exc:
        raise ParallelDownloadUnavailable() from exc
    finally:
        if response is not None:
            response.close()
        if ydl is not None:
            ydl.close()


class _Progress:
    def __init__(
        self,
        context: _Context,
        *,
        total_bytes: int,
        status: str,
        progress_start: float,
        progress_span: float,
        message: str,
    ) -> None:
        self.context = context
        self.total_bytes = total_bytes
        self.status = status
        self.progress_start = progress_start
        self.progress_span = progress_span
        self.message = message
        self.started_at = time.monotonic()
        self.downloaded = 0
        self.last_update = 0.0
        self.lock = threading.Lock()

    def advance(self, size: int) -> None:
        with self.lock:
            self.downloaded += size
            try:
                self.context.check_limits(self.downloaded)
                now = time.monotonic()
                if now - self.last_update < 0.25 and self.downloaded < self.total_bytes:
                    return
                elapsed = max(now - self.started_at, 0.001)
                speed = int(self.downloaded / elapsed)
                remaining = max(0, self.total_bytes - self.downloaded)
                update_job(
                    self.context.redis,
                    self.context.job_id,
                    status=self.status,
                    progress=self.progress_start
                    + min(self.downloaded / self.total_bytes, 1.0) * self.progress_span,
                    speed=speed or None,
                    downloaded_bytes=self.context.completed_bytes + self.downloaded,
                    total_bytes=self.context.completed_bytes + self.total_bytes,
                    eta=math.ceil(remaining / speed) if speed else None,
                    message=self.message,
                )
                self.last_update = now
            except Exception as exc:
                raise _ProgressStopped(exc) from exc


def _download_segment(
    *,
    direct: DirectFormat,
    source_url: str,
    start: int,
    end: int,
    output: Path,
    progress: _Progress,
    stop: threading.Event,
    chunk_size: int,
) -> None:
    output.unlink(missing_ok=True)
    written = 0
    candidate_index = 0
    while start + written <= end:
        request_end = min(end, start + written + chunk_size - 1)
        for attempt in range(3):
            if stop.is_set():
                return
            ydl = None
            response = None
            try:
                current_start = start + written
                ydl, response = _open_range(
                    direct,
                    source_url,
                    current_start,
                    request_end,
                    media_url=direct.candidate_urls[candidate_index],
                )
                if response.status != 206:
                    raise _RetryableRangeError(f"http_status_{response.status}")
                match = _CONTENT_RANGE.fullmatch(response.get_header("Content-Range", "").strip())
                if (
                    not match
                    or int(match.group(1)) != current_start
                    or int(match.group(2)) != request_end
                    or int(match.group(3)) != progress.total_bytes
                ):
                    raise _RetryableRangeError("invalid_content_range")
                remaining = request_end - current_start + 1
                with output.open("ab") as destination:
                    while remaining:
                        if stop.is_set():
                            return
                        data = response.read(min(1024 * 1024, remaining))
                        if not data:
                            raise _RetryableRangeError("early_eof")
                        destination.write(data)
                        written += len(data)
                        remaining -= len(data)
                        progress.advance(len(data))
                break
            except _ProgressStopped as exc:
                stop.set()
                raise exc.cause from exc
            except AppError:
                stop.set()
                raise
            except Exception as exc:
                reason = (
                    exc.reason
                    if isinstance(exc, _RetryableRangeError)
                    else f"network_{type(exc).__name__}"
                )
                if attempt == 2:
                    stop.set()
                    raise ParallelDownloadFailed(reason) from exc
                candidate_index = (candidate_index + 1) % len(direct.candidate_urls)
                logger.warning(
                    "Range chunk retry attempt=%s reason=%s candidate=%s/%s",
                    attempt + 1,
                    reason,
                    candidate_index + 1,
                    len(direct.candidate_urls),
                )
                time.sleep(0.2 * (attempt + 1))
            finally:
                if response is not None:
                    response.close()
                if ydl is not None:
                    ydl.close()


def _parallel_download_once(
    context: _Context,
    *,
    direct: DirectFormat,
    source_url: str,
    total_bytes: int,
    connections: int,
    temp_dir: Path,
    prefix: str,
    status: str,
    progress_start: float,
    progress_span: float,
    message: str,
) -> Path:
    ranges = segment_ranges(total_bytes, connections)
    stop = threading.Event()
    progress = _Progress(
        context,
        total_bytes=total_bytes,
        status=status,
        progress_start=progress_start,
        progress_span=progress_span,
        message=message,
    )
    parts = [temp_dir / f".{prefix}.segment-{index:02d}.part" for index in range(len(ranges))]
    futures: list[Future[None]] = []
    first_error: Exception | None = None
    try:
        with ThreadPoolExecutor(max_workers=len(ranges), thread_name_prefix="media-range") as pool:
            for (start, end), part in zip(ranges, parts, strict=True):
                futures.append(
                    pool.submit(
                        _download_segment,
                        direct=direct,
                        source_url=source_url,
                        start=start,
                        end=end,
                        output=part,
                        progress=progress,
                        stop=stop,
                        chunk_size=context.settings.parallel_download_chunk_size_mb * 1024 * 1024,
                    )
                )
            for future in as_completed(futures):
                try:
                    future.result()
                except Exception as exc:
                    if first_error is None:
                        first_error = exc
                    stop.set()
        if first_error is not None:
            raise first_error

        target = temp_dir / f"{prefix}.{direct.extension}"
        with target.open("wb") as destination:
            for part in parts:
                with part.open("rb") as source:
                    shutil.copyfileobj(source, destination, length=1024 * 1024)
                context.check_limits(total_bytes)
        if target.stat().st_size != total_bytes:
            raise ParallelDownloadFailed("assembled_size_mismatch")
        return target
    finally:
        stop.set()
        for future in futures:
            future.cancel()
        for part in parts:
            part.unlink(missing_ok=True)


def parallel_download_track(
    context: _Context,
    *,
    source_url: str,
    format_id: str,
    temp_dir: Path,
    prefix: str,
    status: str,
    progress_start: float,
    progress_span: float,
    message: str,
) -> Path:
    settings = context.settings
    if not settings.parallel_download_enabled or settings.parallel_download_connections <= 1:
        raise ParallelDownloadUnavailable()

    direct = _extract_direct_format(source_url, format_id)
    total_bytes = _probe_total_bytes(direct, source_url)
    context.check_limits(total_bytes)
    min_split_bytes = settings.parallel_download_min_split_size_mb * 1024 * 1024
    connections = min(
        settings.parallel_download_connections,
        max(1, total_bytes // min_split_bytes),
    )
    if connections <= 1:
        raise ParallelDownloadUnavailable()

    attempts = connection_attempts(connections)
    last_error: ParallelDownloadFailed | None = None
    for attempt_index, attempt_connections in enumerate(attempts):
        if attempt_index:
            time.sleep(min(2**attempt_index, 4))
            try:
                refreshed_direct = _extract_direct_format(source_url, format_id)
                refreshed_total = _probe_total_bytes(refreshed_direct, source_url)
            except ParallelDownloadUnavailable:
                logger.warning("Parallel CDN refresh unavailable; using standard downloader")
                break
            if refreshed_total != total_bytes:
                logger.warning("Parallel CDN refresh changed media size; using standard downloader")
                break
            direct = refreshed_direct
        try:
            return _parallel_download_once(
                context,
                direct=direct,
                source_url=source_url,
                total_bytes=total_bytes,
                connections=attempt_connections,
                temp_dir=temp_dir,
                prefix=prefix,
                status=status,
                progress_start=progress_start,
                progress_span=progress_span,
                message=message,
            )
        except ParallelDownloadFailed as exc:
            last_error = exc
            logger.warning(
                "Parallel range attempt failed connections=%s reason=%s",
                attempt_connections,
                exc.reason,
            )
            if attempt_index + 1 < len(attempts):
                next_connections = attempts[attempt_index + 1]
                update_job(
                    context.redis,
                    context.job_id,
                    status=status,
                    progress=progress_start,
                    speed=None,
                    eta=None,
                    message=f"源站连接不稳定，正在使用 {next_connections} 路重试",
                )

    logger.warning(
        "Parallel ranges exhausted attempts=%s final_reason=%s; using standard downloader",
        attempts,
        last_error.reason if last_error else "unknown",
    )
    raise ParallelDownloadUnavailable() from last_error
