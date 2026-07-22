import json
import time
from typing import Any, cast

from redis import Redis
from redis.exceptions import WatchError

from app.core.config import get_settings
from app.core.errors import error

TERMINAL_STATUSES = {"ready", "failed", "cancelled", "expired"}
ALLOWED_TRANSITIONS: dict[str, set[str]] = {
    "queued": {"downloading", "downloading_video", "downloading_audio", "cancelled", "failed"},
    "inspecting": {"queued", "failed", "cancelled"},
    "downloading": {
        "downloading_video",
        "downloading_audio",
        "merging",
        "processing",
        "ready",
        "failed",
        "cancelled",
    },
    "downloading_video": {
        "downloading_audio",
        "merging",
        "processing",
        "ready",
        "failed",
        "cancelled",
    },
    "downloading_audio": {"merging", "processing", "ready", "failed", "cancelled"},
    "merging": {"processing", "ready", "failed", "cancelled"},
    "processing": {"ready", "failed", "cancelled"},
    "ready": {"expired"},
    "failed": {"expired"},
    "cancelled": {"expired"},
    "expired": set(),
}


class JobCancelled(Exception):
    pass


def default_job_state(job_id: str) -> dict[str, Any]:
    return {
        "job_id": job_id,
        "status": "queued",
        "progress": 0.0,
        "speed": None,
        "downloaded_bytes": 0,
        "total_bytes": None,
        "eta": None,
        "message": "任务已进入队列",
        "download_url": None,
        "error": None,
        "created_at": int(time.time()),
        "updated_at": int(time.time()),
    }


def can_transition(current: str, target: str) -> bool:
    return current == target or target in ALLOWED_TRANSITIONS.get(current, set())


def load_job(redis_client: Redis, job_id: str) -> dict[str, Any]:
    encoded = cast(str | None, redis_client.get(f"job:{job_id}"))
    if not encoded:
        raise error("JOB_NOT_FOUND")
    return json.loads(encoded)


def save_new_job(redis_client: Redis, state: dict[str, Any]) -> None:
    settings = get_settings()
    encoded = json.dumps(state, ensure_ascii=False, separators=(",", ":"))
    created = redis_client.set(
        f"job:{state['job_id']}", encoded, ex=settings.job_ttl_seconds, nx=True
    )
    if not created:
        raise error("INTERNAL_ERROR")
    redis_client.publish(f"job:{state['job_id']}:events", encoded)


def update_job(redis_client: Redis, job_id: str, **updates: Any) -> dict[str, Any]:
    settings = get_settings()
    key = f"job:{job_id}"
    while True:
        try:
            with redis_client.pipeline() as pipeline:
                pipeline.watch(key)
                encoded = cast(str | None, pipeline.get(key))
                if not encoded:
                    raise error("JOB_EXPIRED")
                state = json.loads(encoded)
                target = updates.get("status", state["status"])
                if not can_transition(state["status"], target):
                    if state["status"] == "cancelled":
                        raise JobCancelled()
                    raise RuntimeError(f"Invalid job transition {state['status']} -> {target}")
                state.update(updates)
                state["updated_at"] = int(time.time())
                state["progress"] = min(100.0, max(0.0, float(state.get("progress") or 0)))
                encoded = json.dumps(state, ensure_ascii=False, separators=(",", ":"))
                pipeline.multi()
                pipeline.setex(key, settings.job_ttl_seconds, encoded)
                pipeline.execute()
                break
        except WatchError:
            continue
    redis_client.publish(f"job:{job_id}:events", encoded)
    return state


def cancellation_requested(redis_client: Redis, job_id: str) -> bool:
    return bool(redis_client.get(f"cancel:{job_id}"))


def request_cancellation(redis_client: Redis, job_id: str) -> dict[str, Any]:
    settings = get_settings()
    state = load_job(redis_client, job_id)
    if state["status"] in TERMINAL_STATUSES:
        return state
    redis_client.setex(f"cancel:{job_id}", settings.download_timeout_seconds + 600, "1")
    return update_job(
        redis_client,
        job_id,
        status="cancelled",
        message="任务已取消",
        speed=None,
        eta=None,
    )


def release_client_slot(redis_client: Redis, client_ip: str, job_id: str) -> None:
    if client_ip:
        redis_client.srem(f"active-jobs:{client_ip}", job_id)


def reserve_client_slot(redis_client: Redis, client_ip: str, job_id: str) -> None:
    settings = get_settings()
    key = f"active-jobs:{client_ip}"
    while True:
        try:
            with redis_client.pipeline() as pipeline:
                pipeline.watch(key)
                existing = cast(set[str], pipeline.smembers(key))
                stale: list[str] = []
                for existing_id in existing:
                    try:
                        state = load_job(redis_client, existing_id)
                    except Exception:
                        stale.append(existing_id)
                        continue
                    if state.get("status") in TERMINAL_STATUSES:
                        stale.append(existing_id)
                active_count = len(existing) - len(stale)
                if active_count >= settings.max_concurrent_jobs_per_ip:
                    raise error(
                        "RATE_LIMITED",
                        message="当前 IP 的并发下载任务已达上限",
                    )
                pipeline.multi()
                if stale:
                    pipeline.srem(key, *stale)
                pipeline.sadd(key, job_id)
                pipeline.expire(key, settings.job_ttl_seconds)
                pipeline.execute()
                return
        except WatchError:
            continue
