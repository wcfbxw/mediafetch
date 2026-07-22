import argparse
import json
import logging
import shutil
import signal
import sys
import time
from pathlib import Path
from typing import cast

from app.core.config import get_settings
from app.core.logging import configure_logging
from app.core.redis import get_redis
from app.services.jobs import TERMINAL_STATUSES

logger = logging.getLogger(__name__)


def _safe_remove_tree(root: Path, candidate: Path) -> bool:
    try:
        candidate.resolve().relative_to(root.resolve())
        shutil.rmtree(candidate)
        logger.info("Deleted expired directory %s", candidate.name)
        return True
    except FileNotFoundError:
        return True
    except (OSError, ValueError):
        logger.exception("Could not delete directory %s; will retry", candidate.name)
        return False


def cleanup_once(now: float | None = None) -> dict[str, int]:
    settings = get_settings()
    settings.ensure_storage()
    redis_client = get_redis()
    current = now or time.time()
    deleted_temp = 0
    deleted_downloads = 0
    deleted_tokens = 0

    for directory in settings.temp_dir.iterdir():
        if not directory.is_dir():
            continue
        job_id = directory.name
        encoded = cast(str | None, redis_client.get(f"job:{job_id}"))
        stale = current - directory.stat().st_mtime > settings.download_timeout_seconds + 600
        terminal = False
        if encoded:
            try:
                terminal = json.loads(encoded).get("status") in TERMINAL_STATUSES
            except json.JSONDecodeError:
                terminal = True
        if stale or terminal or not encoded:
            deleted_temp += int(_safe_remove_tree(settings.temp_dir, directory))

    for directory in settings.downloads_dir.iterdir():
        if not directory.is_dir():
            continue
        job_id = directory.name
        newest_mtime = max(
            (path.stat().st_mtime for path in directory.rglob("*") if path.is_file()),
            default=directory.stat().st_mtime,
        )
        if current - newest_mtime > settings.file_ttl_seconds:
            if _safe_remove_tree(settings.downloads_dir, directory):
                deleted_downloads += 1
                encoded = cast(str | None, redis_client.get(f"job:{job_id}"))
                if encoded:
                    try:
                        state = json.loads(encoded)
                        state.update(
                            {
                                "status": "expired",
                                "download_url": None,
                                "message": "下载文件已过期",
                                "updated_at": int(current),
                            }
                        )
                        redis_client.setex(
                            f"job:{job_id}",
                            min(settings.job_ttl_seconds, 3600),
                            json.dumps(state, ensure_ascii=False, separators=(",", ":")),
                        )
                        redis_client.publish(
                            f"job:{job_id}:events",
                            json.dumps(state, ensure_ascii=False, separators=(",", ":")),
                        )
                    except json.JSONDecodeError:
                        redis_client.delete(f"job:{job_id}")

    for key in redis_client.scan_iter(match="file-token:*", count=100):
        encoded = cast(str | None, redis_client.get(key))
        if not encoded:
            continue
        try:
            payload = json.loads(encoded)
            candidate = settings.downloads_dir / payload["relative_path"]
            if not candidate.is_file() or payload.get("expires_at", 0) <= current:
                redis_client.delete(key)
                deleted_tokens += 1
        except (json.JSONDecodeError, KeyError, TypeError):
            redis_client.delete(key)
            deleted_tokens += 1

    return {
        "temp": deleted_temp,
        "downloads": deleted_downloads,
        "tokens": deleted_tokens,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Clean expired MediaFetch files")
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()
    settings = get_settings()
    configure_logging(settings.log_level)
    stopping = False

    def stop(_signum, _frame) -> None:
        nonlocal stopping
        stopping = True

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    while not stopping:
        logger.info("Cleanup result: %s", cleanup_once())
        if args.once:
            break
        end = time.monotonic() + settings.cleanup_interval_seconds
        while not stopping and time.monotonic() < end:
            time.sleep(min(1, max(0, end - time.monotonic())))
    return 0


if __name__ == "__main__":
    sys.exit(main())
