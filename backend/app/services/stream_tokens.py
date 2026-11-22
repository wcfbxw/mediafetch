import hashlib
import hmac
import json
import secrets
import time
from collections.abc import Mapping
from typing import Any, cast

from redis import Redis

from app.core.config import get_settings
from app.core.errors import AppError
from app.services.file_tokens import sanitize_filename


def _sign(prefix: str, expires_at: int, nonce: str) -> str:
    secret = get_settings().token_secret.encode("utf-8")
    message = f"{prefix}.{expires_at}.{nonce}".encode()
    return hmac.new(secret, message, hashlib.sha256).hexdigest()


def _redis_key(prefix: str, token: str) -> str:
    digest = hashlib.sha256(token.encode("utf-8")).hexdigest()
    return f"{prefix}:{digest}"


def create_stream_token(
    redis_client: Redis,
    *,
    url: str,
    filename: str,
    media_type: str,
    source_url: str,
    http_headers: Mapping[str, str] | None = None,
) -> str:
    settings = get_settings()
    ttl = settings.stream_token_ttl_seconds
    expires_at = int(time.time()) + ttl
    nonce = secrets.token_urlsafe(20)
    signature = _sign("stream", expires_at, nonce)
    token = f"{expires_at}.{nonce}.{signature}"
    clean_headers = {
        str(k): str(v)
        for k, v in (http_headers or {}).items()
        if isinstance(k, str) and isinstance(v, str) and k.lower() != "cookie"
    }
    payload = {
        "url": url,
        "filename": sanitize_filename(filename),
        "media_type": media_type,
        "source_url": source_url,
        "http_headers": clean_headers,
        "expires_at": expires_at,
    }
    redis_client.setex(
        _redis_key("stream-token", token),
        ttl,
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
    )
    return token


def validate_stream_token(redis_client: Redis, token: str) -> dict[str, Any]:
    if not token or len(token) > 300:
        raise AppError("JOB_NOT_FOUND", "流媒体下载令牌无效", 404)
    try:
        expires_text, nonce, provided = token.split(".", 2)
        expires_at = int(expires_text)
    except (TypeError, ValueError):
        raise AppError("JOB_NOT_FOUND", "流媒体下载令牌无效", 404) from None
    expected = _sign("stream", expires_at, nonce)
    if not hmac.compare_digest(expected, provided):
        raise AppError("JOB_NOT_FOUND", "流媒体下载令牌无效", 404)
    if expires_at <= int(time.time()):
        raise AppError("JOB_EXPIRED", "直传下载链接已过期，请重新解析", 410)
    encoded = cast(str | None, redis_client.get(_redis_key("stream-token", token)))
    if not encoded:
        raise AppError("JOB_EXPIRED", "直传下载链接已过期，请重新解析", 410)
    return cast(dict[str, Any], json.loads(encoded))


def create_gallery_zip_token(
    redis_client: Redis,
    *,
    title: str,
    source_url: str,
    items: list[dict[str, Any]],
) -> str:
    settings = get_settings()
    ttl = settings.stream_token_ttl_seconds
    expires_at = int(time.time()) + ttl
    nonce = secrets.token_urlsafe(20)
    signature = _sign("gallery", expires_at, nonce)
    token = f"{expires_at}.{nonce}.{signature}"
    payload = {
        "title": sanitize_filename(title, default="gallery", max_length=100),
        "source_url": source_url,
        "items": items,
        "expires_at": expires_at,
    }
    redis_client.setex(
        _redis_key("gallery-token", token),
        ttl,
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
    )
    return token


def validate_gallery_zip_token(redis_client: Redis, token: str) -> dict[str, Any]:
    if not token or len(token) > 300:
        raise AppError("JOB_NOT_FOUND", "图集打包令牌无效", 404)
    try:
        expires_text, nonce, provided = token.split(".", 2)
        expires_at = int(expires_text)
    except (TypeError, ValueError):
        raise AppError("JOB_NOT_FOUND", "图集打包令牌无效", 404) from None
    expected = _sign("gallery", expires_at, nonce)
    if not hmac.compare_digest(expected, provided):
        raise AppError("JOB_NOT_FOUND", "图集打包令牌无效", 404)
    if expires_at <= int(time.time()):
        raise AppError("JOB_EXPIRED", "图集打包链接已过期，请重新解析", 410)
    encoded = cast(str | None, redis_client.get(_redis_key("gallery-token", token)))
    if not encoded:
        raise AppError("JOB_EXPIRED", "图集打包链接已过期，请重新解析", 410)
    return cast(dict[str, Any], json.loads(encoded))
