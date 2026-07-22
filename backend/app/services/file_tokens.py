import hashlib
import hmac
import json
import re
import secrets
import time
import unicodedata
from pathlib import Path
from typing import cast
from urllib.parse import quote

from redis import Redis

from app.core.config import get_settings
from app.core.errors import AppError, error

INVALID_FILENAME = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
WHITESPACE = re.compile(r"\s+")
WINDOWS_RESERVED = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10)),
}


def sanitize_filename(value: str, *, default: str = "media", max_length: int = 160) -> str:
    normalized = unicodedata.normalize("NFKC", value)
    normalized = INVALID_FILENAME.sub("_", normalized)
    normalized = WHITESPACE.sub(" ", normalized).strip(" .")
    if not normalized or normalized in {".", ".."}:
        normalized = default
    stem = normalized.rsplit(".", 1)[0].upper()
    if stem in WINDOWS_RESERVED:
        normalized = f"_{normalized}"
    if len(normalized) > max_length:
        suffix = Path(normalized).suffix[:16]
        normalized = normalized[: max_length - len(suffix)].rstrip(" .") + suffix
    return normalized or default


def ensure_within(base: Path, candidate: Path) -> Path:
    base_resolved = base.resolve()
    resolved = candidate.resolve()
    try:
        resolved.relative_to(base_resolved)
    except ValueError as exc:
        raise error("INTERNAL_ERROR") from exc
    return resolved


def _token_key(token: str) -> str:
    digest = hashlib.sha256(token.encode("utf-8")).hexdigest()
    return f"file-token:{digest}"


def _signature(expires_at: int, nonce: str) -> str:
    secret = get_settings().token_secret.encode("utf-8")
    message = f"{expires_at}.{nonce}".encode()
    return hmac.new(secret, message, hashlib.sha256).hexdigest()


def create_file_token(redis_client: Redis, job_id: str, file_path: Path) -> tuple[str, int]:
    settings = get_settings()
    resolved = ensure_within(settings.downloads_dir, file_path)
    if not resolved.is_file():
        raise error("INTERNAL_ERROR")
    relative = resolved.relative_to(settings.downloads_dir.resolve())
    if len(relative.parts) != 2 or relative.parts[0] != job_id:
        raise error("INTERNAL_ERROR")

    expires_at = int(time.time()) + settings.file_ttl_seconds
    nonce = secrets.token_urlsafe(24)
    token = f"{expires_at}.{nonce}.{_signature(expires_at, nonce)}"
    payload = {
        "job_id": job_id,
        "relative_path": relative.as_posix(),
        "filename": sanitize_filename(resolved.name),
        "expires_at": expires_at,
        "size": resolved.stat().st_size,
    }
    redis_client.setex(
        _token_key(token),
        settings.file_ttl_seconds,
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
    )
    return token, expires_at


def validate_file_token(redis_client: Redis, token: str) -> dict:
    if len(token) > 300:
        raise AppError("JOB_NOT_FOUND", "下载令牌无效", 404)
    try:
        expires_text, nonce, provided = token.split(".", 2)
        expires_at = int(expires_text)
    except (TypeError, ValueError):
        raise AppError("JOB_NOT_FOUND", "下载令牌无效", 404) from None
    expected = _signature(expires_at, nonce)
    if not hmac.compare_digest(expected, provided):
        raise AppError("JOB_NOT_FOUND", "下载令牌无效", 404)
    if expires_at <= int(time.time()):
        raise AppError("JOB_EXPIRED", "下载链接已过期", 410)
    encoded = cast(str | None, redis_client.get(_token_key(token)))
    if not encoded:
        raise AppError("JOB_EXPIRED", "下载链接已过期", 410)
    payload = json.loads(encoded)
    settings = get_settings()
    candidate = ensure_within(
        settings.downloads_dir, settings.downloads_dir / payload["relative_path"]
    )
    if not candidate.is_file():
        redis_client.delete(_token_key(token))
        raise AppError("JOB_EXPIRED", "下载文件已过期", 410)
    payload["path"] = candidate
    return payload


def internal_download_uri(relative_path: str) -> str:
    clean_parts = [quote(part, safe="") for part in Path(relative_path).parts]
    return "/protected/" + "/".join(clean_parts)


def content_disposition(filename: str) -> str:
    safe = sanitize_filename(filename)
    ascii_fallback = (
        unicodedata.normalize("NFKD", safe).encode("ascii", "ignore").decode("ascii") or "download"
    )
    ascii_fallback = INVALID_FILENAME.sub("_", ascii_fallback).replace('"', "_")
    encoded = quote(safe, safe="")
    return f"attachment; filename=\"{ascii_fallback}\"; filename*=UTF-8''{encoded}"
