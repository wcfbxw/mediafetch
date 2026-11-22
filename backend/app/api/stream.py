import asyncio
import io
import logging
import zipfile
from collections.abc import AsyncIterator
from typing import Any
from urllib.parse import urljoin

import httpx
from fastapi import APIRouter, Query, Request, Response
from fastapi.responses import StreamingResponse

from app.core.config import get_settings
from app.core.errors import AppError, error
from app.core.redis import get_redis
from app.core.security import REDIRECT_STATUSES, validate_public_url
from app.services.file_tokens import content_disposition, sanitize_filename
from app.services.link_resolver import SSRFSafeAsyncHTTPTransport
from app.services.platform_credentials import cookie_header_for_url
from app.services.stream_tokens import validate_gallery_zip_token, validate_stream_token

logger = logging.getLogger(__name__)
router = APIRouter(tags=["stream"])

STREAM_CHUNK_BYTES = 64 * 1024


def _build_client(url: str, timeout_seconds: float = 60.0) -> httpx.AsyncClient:
    settings = get_settings()
    proxy = settings.proxy_for_url(url)
    timeout = httpx.Timeout(timeout_seconds, connect=12.0)
    if proxy:
        return httpx.AsyncClient(
            proxy=proxy,
            timeout=timeout,
            follow_redirects=False,
            trust_env=False,
        )
    return httpx.AsyncClient(
        transport=SSRFSafeAsyncHTTPTransport(),
        timeout=timeout,
        follow_redirects=False,
        trust_env=False,
    )


def _upstream_headers(
    payload: dict[str, Any],
    *,
    current_url: str,
    range_header: str | None = None,
) -> dict[str, str]:
    headers = dict(payload.get("http_headers") or {})
    cookie_val = cookie_header_for_url(current_url) or cookie_header_for_url(
        str(payload.get("source_url") or "")
    )
    if cookie_val:
        headers["Cookie"] = cookie_val
    if range_header and range_header.startswith("bytes="):
        headers["Range"] = range_header[:128]
    return headers


@router.get("/stream/{token}")
async def stream_media(
    token: str,
    request: Request,
    inline: bool = Query(default=False),
) -> Response:
    payload = await asyncio.to_thread(validate_stream_token, get_redis(), token)
    settings = get_settings()
    current_url = await validate_public_url(str(payload["url"]))
    range_header = request.headers.get("range")

    client = _build_client(current_url, timeout_seconds=float(settings.download_timeout_seconds))
    upstream_response: httpx.Response | None = None
    try:
        for hop in range(settings.max_redirects + 1):
            headers = _upstream_headers(
                payload,
                current_url=current_url,
                range_header=range_header,
            )
            req = client.build_request("GET", current_url, headers=headers)
            resp = await client.send(req, stream=True)
            if resp.status_code in REDIRECT_STATUSES and resp.headers.get("location"):
                location = resp.headers["location"]
                await resp.aclose()
                if hop >= settings.max_redirects:
                    await client.aclose()
                    raise error("DOWNLOAD_FAILED", message="媒体源重定向次数过多")
                current_url = await validate_public_url(urljoin(current_url, location))
                continue
            upstream_response = resp
            break
    except AppError:
        await client.aclose()
        raise
    except Exception as exc:
        await client.aclose()
        logger.warning("Upstream stream connect failed error_type=%s", type(exc).__name__)
        raise error("DOWNLOAD_FAILED", message="无法连接上游无水印媒体源") from exc

    if upstream_response is None or upstream_response.status_code >= 400:
        if upstream_response is not None:
            await upstream_response.aclose()
        await client.aclose()
        raise error("DOWNLOAD_FAILED", message="上游媒体源拒绝访问或链接已失效")

    content_length = upstream_response.headers.get("content-length")
    if content_length and content_length.isdigit():
        if int(content_length) > settings.max_file_size_bytes:
            await upstream_response.aclose()
            await client.aclose()
            raise error("FILE_TOO_LARGE")

    filename = str(payload.get("filename") or "media.mp4")
    disposition = (
        f'inline; filename="{sanitize_filename(filename)}"'
        if inline
        else content_disposition(filename)
    )
    media_type = (
        str(payload.get("media_type") or "")
        or upstream_response.headers.get("content-type")
        or "application/octet-stream"
    )
    response_headers: dict[str, str] = {
        "Content-Disposition": disposition,
        "Cache-Control": "private, no-store",
        "Accept-Ranges": "bytes",
        "X-Accel-Buffering": "no",
    }
    if content_length and content_length.isdigit():
        response_headers["Content-Length"] = content_length
    content_range = upstream_response.headers.get("content-range")
    if content_range:
        response_headers["Content-Range"] = content_range

    status_code = 206 if upstream_response.status_code == 206 else 200
    max_bytes = settings.max_file_size_bytes

    async def body_iterator() -> AsyncIterator[bytes]:
        transferred = 0
        try:
            async for chunk in upstream_response.aiter_bytes(chunk_size=STREAM_CHUNK_BYTES):
                transferred += len(chunk)
                if transferred > max_bytes:
                    break
                yield chunk
        finally:
            await upstream_response.aclose()
            await client.aclose()

    return StreamingResponse(
        body_iterator(),
        status_code=status_code,
        media_type=media_type,
        headers=response_headers,
    )


async def _fetch_bounded_bytes(
    url: str,
    *,
    source_url: str,
    http_headers: dict[str, str],
    max_bytes: int,
) -> bytes:
    settings = get_settings()
    current = await validate_public_url(url)
    async with _build_client(current, timeout_seconds=45.0) as client:
        for hop in range(settings.max_redirects + 1):
            headers = _upstream_headers(
                {"http_headers": http_headers, "source_url": source_url},
                current_url=current,
            )
            async with client.stream("GET", current, headers=headers) as resp:
                if resp.status_code in REDIRECT_STATUSES and resp.headers.get("location"):
                    if hop >= settings.max_redirects:
                        raise error("DOWNLOAD_FAILED")
                    current = await validate_public_url(urljoin(current, resp.headers["location"]))
                    continue
                if resp.status_code >= 400:
                    raise error("DOWNLOAD_FAILED", message="图集原图读取失败")
                buf = bytearray()
                async for chunk in resp.aiter_bytes(chunk_size=STREAM_CHUNK_BYTES):
                    buf.extend(chunk)
                    if len(buf) > max_bytes:
                        raise error("FILE_TOO_LARGE")
                return bytes(buf)
    raise error("DOWNLOAD_FAILED")


@router.get("/gallery/{token}")
async def download_gallery_zip(token: str) -> Response:
    payload = await asyncio.to_thread(validate_gallery_zip_token, get_redis(), token)
    settings = get_settings()
    items = payload.get("items") or []
    if not isinstance(items, list) or not items:
        raise error("NO_FORMATS", message="图集中没有可下载的无水印图片")

    source_url = str(payload.get("source_url") or "")
    title = sanitize_filename(str(payload.get("title") or "gallery"), max_length=90)
    archive_buffer = io.BytesIO()
    total_bytes = 0
    per_item_limit = min(settings.max_file_size_bytes, 80 * 1024 * 1024)

    with zipfile.ZipFile(archive_buffer, mode="w", compression=zipfile.ZIP_STORED) as zf:
        for idx, item in enumerate(items, start=1):
            if not isinstance(item, dict) or not isinstance(item.get("url"), str):
                continue
            headers = dict(item.get("http_headers") or {})
            ext = str(item.get("extension") or "jpg").lstrip(".")[:8] or "jpg"
            img_bytes = await _fetch_bounded_bytes(
                item["url"],
                source_url=source_url,
                http_headers=headers,
                max_bytes=per_item_limit,
            )
            total_bytes += len(img_bytes)
            if total_bytes > settings.max_file_size_bytes:
                raise error("FILE_TOO_LARGE")
            zf.writestr(f"{title}_{idx:02d}.{ext}", img_bytes)

            live_url = item.get("live_video_url")
            if isinstance(live_url, str) and live_url.startswith(("http://", "https://")):
                try:
                    live_bytes = await _fetch_bounded_bytes(
                        live_url,
                        source_url=source_url,
                        http_headers=headers,
                        max_bytes=per_item_limit,
                    )
                    total_bytes += len(live_bytes)
                    if total_bytes <= settings.max_file_size_bytes:
                        zf.writestr(f"{title}_{idx:02d}_live.mp4", live_bytes)
                except AppError:
                    logger.info("Skipping unavailable live-photo clip index=%d", idx)

    zip_bytes = archive_buffer.getvalue()
    zip_filename = f"{title}_无水印图集.zip"
    return Response(
        content=zip_bytes,
        media_type="application/zip",
        headers={
            "Content-Disposition": content_disposition(zip_filename),
            "Content-Length": str(len(zip_bytes)),
            "Cache-Control": "private, no-store",
        },
    )
