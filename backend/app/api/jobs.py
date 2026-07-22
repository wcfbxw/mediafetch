import asyncio
import json
import time
from typing import cast

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse
from rq.job import Job

from app.core.errors import error
from app.core.redis import get_async_redis, get_redis, get_rq_redis
from app.models.responses import JobResponse
from app.services.jobs import load_job, release_client_slot, request_cancellation

router = APIRouter(tags=["jobs"])


def _public_job(state: dict) -> JobResponse:
    if state.get("status") == "expired":
        raise error("JOB_EXPIRED")
    return JobResponse.model_validate(state)


@router.get("/jobs/{job_id}", response_model=JobResponse)
async def get_job(job_id: str) -> JobResponse:
    state = await asyncio.to_thread(load_job, get_redis(), job_id)
    return _public_job(state)


@router.delete("/jobs/{job_id}", response_model=JobResponse)
async def cancel_job(job_id: str) -> JobResponse:
    state = await asyncio.to_thread(request_cancellation, get_redis(), job_id)
    cancelled_while_queued = False
    try:
        rq_job = await asyncio.to_thread(
            Job.fetch,
            job_id,
            connection=get_rq_redis(),
        )
        if rq_job.get_status() in {"queued", "deferred", "scheduled"}:
            await asyncio.to_thread(rq_job.cancel)
            cancelled_while_queued = True
    except Exception:
        # The cancellation flag is authoritative for an already-running task.
        pass
    if cancelled_while_queued:
        redis_client = get_redis()
        client_ip = cast(str | None, redis_client.get(f"job-owner:{job_id}"))
        if client_ip:
            await asyncio.to_thread(
                release_client_slot,
                redis_client,
                client_ip,
                job_id,
            )
        redis_client.delete(
            f"job-payload:{job_id}",
            f"job-owner:{job_id}",
        )
    return _public_job(state)


@router.get("/jobs/{job_id}/events")
async def job_events(job_id: str, request: Request) -> StreamingResponse:
    redis_client = get_async_redis()
    initial = await redis_client.get(f"job:{job_id}")
    if not initial:
        raise error("JOB_NOT_FOUND")

    async def events():
        pubsub = redis_client.pubsub()
        await pubsub.subscribe(f"job:{job_id}:events")
        last_heartbeat = time.monotonic()
        try:
            # Subscribe before the second read so a state change cannot be lost
            # between the initial existence check and event consumption.
            latest = await redis_client.get(f"job:{job_id}") or initial
            initial_state = json.loads(latest)
            event_name = "completed" if initial_state.get("status") == "ready" else "progress"
            yield f"event: {event_name}\ndata: {latest}\n\n"
            if initial_state.get("status") in {"ready", "failed", "cancelled", "expired"}:
                return
            while not await request.is_disconnected():
                message = await pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0)
                if message and message.get("type") == "message":
                    data = str(message["data"])
                    state = json.loads(data)
                    event_name = "completed" if state.get("status") == "ready" else "progress"
                    yield f"event: {event_name}\ndata: {data}\n\n"
                    last_heartbeat = time.monotonic()
                    if state.get("status") in {"ready", "failed", "cancelled", "expired"}:
                        return
                elif time.monotonic() - last_heartbeat >= 15:
                    yield ": heartbeat\n\n"
                    last_heartbeat = time.monotonic()
        finally:
            await pubsub.unsubscribe(f"job:{job_id}:events")
            await pubsub.aclose()

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
