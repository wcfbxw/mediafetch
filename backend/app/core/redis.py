from functools import lru_cache

import redis
import redis.asyncio as async_redis

from app.core.config import get_settings


@lru_cache
def get_redis() -> redis.Redis:
    return redis.Redis.from_url(
        get_settings().redis_url,
        decode_responses=True,
        health_check_interval=30,
        socket_connect_timeout=5,
        socket_timeout=10,
    )


@lru_cache
def get_rq_redis() -> redis.Redis:
    # RQ stores pickled binary payloads and must not use decode_responses.
    return redis.Redis.from_url(
        get_settings().redis_url,
        decode_responses=False,
        health_check_interval=30,
        socket_connect_timeout=5,
        socket_timeout=10,
    )


@lru_cache
def get_async_redis() -> async_redis.Redis:
    return async_redis.Redis.from_url(
        get_settings().redis_url,
        decode_responses=True,
        health_check_interval=30,
        socket_connect_timeout=5,
        socket_timeout=10,
    )


async def close_redis_clients() -> None:
    await get_async_redis().aclose()
    get_redis().close()
    get_rq_redis().close()
