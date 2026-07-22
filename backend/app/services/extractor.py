import asyncio
import functools
import hashlib
import http.client
import json
import logging
import os
import secrets
import shutil
import socket
import tempfile
import urllib.request
from pathlib import Path
from typing import Any, cast
from urllib.parse import urljoin

from redis import Redis
from yt_dlp import YoutubeDL
from yt_dlp.networking._urllib import HTTPHandler, RedirectHandler, UrllibRH
from yt_dlp.utils import DownloadError

from app.core.config import get_settings
from app.core.errors import AppError, error
from app.core.logging import redact_url
from app.core.security import (
    _resolved_addresses,
    validate_public_url_sync,
    validate_redirect_chain,
    validate_resolved_addresses,
)
from app.models.responses import InspectResponse
from app.services.formats import normalize_formats
from app.services.kuaishou import MediaFetchKuaishouIE
from app.services.platform_credentials import (
    configure_ytdlp_credentials,
    is_managed_cookie_file,
)

logger = logging.getLogger(__name__)


class QuietLogger:
    def debug(self, message: str) -> None:
        return None

    def warning(self, message: str) -> None:
        logger.warning("yt-dlp warning: %s", redact_url(message))

    def error(self, message: str) -> None:
        logger.error("yt-dlp error: %s", redact_url(message))


class ValidatingRedirectHandler(RedirectHandler):
    def __init__(self) -> None:
        super().__init__()
        self.max_redirections = get_settings().max_redirects

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        checked_url = validate_public_url_sync(urljoin(req.full_url, newurl))
        return super().redirect_request(req, fp, code, msg, headers, checked_url)


def _create_pinned_connection(http_class, source_address, *args, **kwargs):
    connection = http_class(*args, **kwargs)
    hostname = connection.host
    port = connection.port
    addresses = validate_resolved_addresses(_resolved_addresses(hostname, port))

    def connect(
        _target,
        timeout=None,
        source_address_override=None,
    ):
        chosen_source = source_address_override
        if chosen_source is None and source_address is not None:
            chosen_source = (source_address, 0)
        last_error: OSError | None = None
        for address in sorted(addresses):
            try:
                return socket.create_connection(
                    (address, port),
                    timeout=timeout,
                    source_address=chosen_source,
                )
            except OSError as exc:
                last_error = exc
        if last_error:
            raise last_error
        raise OSError("No validated addresses available")

    connection._create_connection = connect
    if source_address is not None:
        connection.source_address = (source_address, 0)
    return connection


class PinnedHTTPHandler(HTTPHandler):
    def http_open(self, req):
        connection_class = self._make_conn_class(http.client.HTTPConnection, req)
        return self.do_open(
            functools.partial(
                _create_pinned_connection,
                connection_class,
                self._source_address,
            ),
            req,
        )

    def https_open(self, req):
        connection_class = self._make_conn_class(http.client.HTTPSConnection, req)
        return self.do_open(
            functools.partial(
                _create_pinned_connection,
                connection_class,
                self._source_address,
            ),
            req,
            context=self._context,
        )


class SafeUrllibRH(UrllibRH):
    # Preserve the key expected by YoutubeDL._setup_opener while replacing the
    # implementation with a redirect-validating subclass.
    RH_KEY = "Urllib"
    RH_NAME = "safe-urllib"

    def _create_instance(self, proxies, cookiejar, legacy_ssl_support=None):
        default_opener = super()._create_instance(proxies, cookiejar, legacy_ssl_support)
        opener = urllib.request.OpenerDirector()
        for handler in default_opener.handlers:
            if isinstance(handler, HTTPHandler | RedirectHandler):
                continue
            opener.add_handler(handler)
        opener.add_handler(
            PinnedHTTPHandler(
                debuglevel=int(bool(self.verbose)),
                context=self._make_sslcontext(legacy_ssl_support=legacy_ssl_support),
                source_address=self.source_address,
            )
        )
        opener.add_handler(ValidatingRedirectHandler())
        opener.addheaders = []
        return opener


class SafeYoutubeDL(YoutubeDL):
    """Revalidate DNS for every extractor, redirect and manifest request."""

    def __init__(self, params=None, auto_init=True):
        safe_params = dict(params or {})
        self._credential_snapshot: Path | None = None
        cookiefile = safe_params.get("cookiefile")
        if isinstance(cookiefile, str) and is_managed_cookie_file(cookiefile):
            fd, snapshot_name = tempfile.mkstemp(prefix=".mediafetch-cookie-", suffix=".txt")
            os.close(fd)
            snapshot = Path(snapshot_name)
            try:
                shutil.copyfile(cookiefile, snapshot)
                os.chmod(snapshot, 0o600)
            except Exception:
                snapshot.unlink(missing_ok=True)
                raise
            safe_params["cookiefile"] = str(snapshot)
            self._credential_snapshot = snapshot
        try:
            super().__init__(safe_params, auto_init=auto_init)
        except Exception:
            if self._credential_snapshot:
                self._credential_snapshot.unlink(missing_ok=True)
            raise

    def add_default_info_extractors(self):
        # yt-dlp has no built-in Kuaishou extractor. Register our narrow public-page
        # extractor before GenericIE so parsing and downloading use the same format IDs.
        self.add_info_extractor(MediaFetchKuaishouIE(self))
        super().add_default_info_extractors()

    def close(self):
        try:
            super().close()
        finally:
            if self._credential_snapshot:
                self._credential_snapshot.unlink(missing_ok=True)
                self._credential_snapshot = None

    def build_request_director(self, _handlers, preferences=None):
        # Restrict HTTP(S) to the hardened urllib transport. This prevents an
        # optional requests/curl-cffi backend from following redirects inside
        # its own session without invoking our validator.
        return super().build_request_director([SafeUrllibRH], preferences)

    def urlopen(self, req):
        request_url = getattr(req, "url", None) or str(req)
        validate_public_url_sync(request_url)
        return super().urlopen(req)


def map_ytdlp_error(exc: Exception) -> AppError:
    message = str(exc).lower()
    if "drm" in message:
        return error("DRM_PROTECTED")
    if "private video" in message or "private" in message and "video" in message:
        return error("PRIVATE_VIDEO")
    if any(marker in message for marker in ("login required", "sign in", "cookies")):
        return error("LOGIN_REQUIRED")
    if any(marker in message for marker in ("unavailable", "removed", "not available")):
        return error("VIDEO_UNAVAILABLE")
    if any(marker in message for marker in ("unsupported url", "no suitable extractor")):
        return error("UNSUPPORTED_URL")
    return error("UNSUPPORTED_URL")


def _safe_thumbnail(info: dict[str, Any]) -> str | None:
    thumbnail = info.get("thumbnail")
    if not isinstance(thumbnail, str):
        return None
    try:
        return redact_url(validate_public_url_sync(thumbnail))
    except AppError:
        return None


def _extract_sync(url: str) -> dict[str, Any]:
    settings = get_settings()
    options: dict[str, Any] = {
        "skip_download": True,
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "cachedir": False,
        "socket_timeout": min(settings.inspect_timeout_seconds, 30),
        "extractor_retries": 2,
        "fragment_retries": 2,
        "logger": QuietLogger(),
    }
    if settings.ytdlp_proxy:
        options["proxy"] = settings.ytdlp_proxy
    configure_ytdlp_credentials(options, url)
    try:
        with SafeYoutubeDL(options) as ydl:
            result = ydl.extract_info(url, download=False)
    except AppError:
        raise
    except DownloadError as exc:
        raise map_ytdlp_error(exc) from exc
    except Exception as exc:
        logger.error(
            "Unexpected extractor failure for %s error_type=%s",
            redact_url(url),
            type(exc).__name__,
        )
        raise map_ytdlp_error(exc) from exc
    if not isinstance(result, dict):
        raise error("UNSUPPORTED_URL")
    if result.get("_type") in {"playlist", "multi_video"}:
        entries = [entry for entry in result.get("entries") or [] if isinstance(entry, dict)]
        if len(entries) != 1:
            raise error("UNSUPPORTED_URL", message="暂不支持播放列表或多视频页面")
        result = entries[0]
    return result


def _cache_key_for_url(url: str) -> str:
    return hashlib.sha256(url.encode("utf-8")).hexdigest()


def _public_payload(data: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in data.items() if not key.startswith("_")}


async def inspect_media(url: str, redis_client: Redis) -> InspectResponse:
    settings = get_settings()
    checked_url = await validate_redirect_chain(url)
    url_hash = _cache_key_for_url(checked_url)
    cached_id = cast(str | None, redis_client.get(f"inspect-url:{url_hash}"))
    if cached_id:
        cached = cast(str | None, redis_client.get(f"inspect:{cached_id}"))
        if cached:
            return InspectResponse.model_validate(_public_payload(json.loads(cached)))

    try:
        info = await asyncio.wait_for(
            asyncio.to_thread(_extract_sync, checked_url),
            timeout=settings.inspect_timeout_seconds,
        )
    except TimeoutError as exc:
        raise error("UNSUPPORTED_URL", message="解析超时，请稍后重试") from exc

    if info.get("has_drm") or any(
        item.get("has_drm") for item in info.get("formats") or [] if isinstance(item, dict)
    ):
        raise error("DRM_PROTECTED")

    duration_value = info.get("duration")
    duration = int(duration_value) if isinstance(duration_value, int | float) else None
    if duration and duration > settings.max_duration_seconds:
        raise error("VIDEO_TOO_LONG")

    formats, audio_formats = normalize_formats(info.get("formats") or [], duration)
    if not formats and not audio_formats:
        raise error("NO_FORMATS")

    inspect_id = secrets.token_urlsafe(24)
    title = str(info.get("title") or "未命名视频").strip()[:300]
    uploader = str(info.get("uploader") or info.get("channel") or "").strip()[:200] or None
    platform = str(info.get("extractor_key") or info.get("extractor") or "Unknown")[:80]
    payload: dict[str, Any] = {
        "inspect_id": inspect_id,
        "title": title,
        "thumbnail": _safe_thumbnail(info),
        "duration": duration,
        "uploader": uploader,
        "platform": platform,
        "formats": formats,
        "audio_formats": audio_formats,
        "_source_url": checked_url,
        "_webpage_url": redact_url(str(info.get("webpage_url") or checked_url)),
    }
    encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    pipeline = redis_client.pipeline()
    pipeline.setex(f"inspect:{inspect_id}", settings.inspect_cache_ttl_seconds, encoded)
    pipeline.setex(
        f"inspect-url:{url_hash}",
        settings.inspect_cache_ttl_seconds,
        inspect_id,
    )
    pipeline.execute()
    return InspectResponse.model_validate(_public_payload(payload))
