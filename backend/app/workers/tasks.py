import json
import logging
from typing import cast

from app.core.redis import get_redis
from app.services.downloader import execute_download
from app.services.jobs import JobCancelled, release_client_slot, update_job

logger = logging.getLogger(__name__)


def run_download_job(job_id: str) -> None:
    redis_client = get_redis()
    encoded = cast(str | None, redis_client.get(f"job-payload:{job_id}"))
    if not encoded:
        client_ip = cast(str | None, redis_client.get(f"job-owner:{job_id}"))
        try:
            update_job(
                redis_client,
                job_id,
                status="failed",
                message="任务数据已过期",
                error={"code": "JOB_EXPIRED", "message": "任务数据已过期"},
            )
        except JobCancelled:
            pass
        except Exception:
            logger.exception("Could not mark missing payload for job_id=%s", job_id)
        release_client_slot(redis_client, client_ip or "", job_id)
        redis_client.delete(f"job-owner:{job_id}")
        return
    execute_download(redis_client, job_id, json.loads(encoded))
