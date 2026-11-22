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
from urllib.parse import urljoin, urlsplit

from redis import Redis
from yt_dlp import YoutubeDL
from yt_dlp.networking._urllib import HTTPHandler, RedirectHandler, UrllibRH
from yt_dlp.networking.impersonate import ImpersonateTarget
from yt_dlp.utils import DownloadError

from app.core.config import get_settings
from app.core.errors import AppError, error
from app.core.logging import redact_url
from app.core.security import (
    _resolved_addresses,
    validate_public_url_sync,
    validate_resolved_addresses,
)
from app.models.responses import InspectResponse
from app.parsers import DEFAULT_VIDEO_PARSER_HOOKS, VideoParserHook
from app.services.clean_extractors import (
    MediaFetchPipixiaIE,
    fetch_hybrid_clean_media,
    select_playlist_or_multipart_entry,
)
from app.services.douyin_official import (
    DouyinOfficialPlaybackUnavailable,
    add_official_playback_format,
    extract_official_douyin_info,
    is_official_share_url,
)
from app.services.file_tokens import sanitize_filename
from app.services.formats import normalize_formats
from app.services.kuaishou import MediaFetchKuaishouIE
from app.services.link_resolver import LinkResolver
from app.services.official_platforms import prefer_official_original_formats
from app.services.platform_credentials import (
    configure_ytdlp_credentials,
    is_managed_cookie_file,
)
from app.services.stream_tokens import create_gallery_zip_token, create_stream_token
from app.services.xiaohongshu import (
    XiaohongshuExtractUnavailable,
    extract_xiaohongshu_info,
    is_xiaohongshu_url,
)

logger = logging.getLogger(__name__)

IMPERSONATE_DOMAINS: tuple[str, ...] = (
    "tiktok.com",
    "x.com",
    "twitter.com",
    "instagram.com",
    "facebook.com",
    "fb.watch",
    "reddit.com",
    "redd.it",
    "vimeo.com",
    "twitch.tv",
    "threads.net",
    "pinterest.com",
    "dailymotion.com",
)


def _should_impersonate(url: str) -> bool:
    host = (urlsplit(url).hostname or "").lower().rstrip(".")
    return any(host == domain or host.endswith(f".{domain}") for domain in IMPERSONATE_DOMAINS)


def _curl_cffi_available() -> bool:
    try:
        import yt_dlp.networking._curlcffi  # noqa: F401
    except ImportError:
        return False
    return True


def _wrap_safe_curl_session(session: Any) -> Any:
    original_request = session.request

    def safe_request(*, method: str, url: str, max_redirects: int = 5, **kwargs: Any) -> Any:
        current_url = validate_public_url_sync(url)
        limit = min(int(max_redirects or 5), get_settings().max_redirects)
        current_method = method
        for hop in range(limit + 1):
            resp = original_request(
                method=current_method,
                url=current_url,
                allow_redirects=False,
                **kwargs,
            )
            location = resp.headers.get("location")
            if resp.status_code not in {301, 302, 303, 307, 308} or not location:
                return resp
            resp.close()
            if hop >= limit:
                raise error("INVALID_URL", message="链接重定向次数过多")
            current_url = validate_public_url_sync(urljoin(current_url, location))
            if resp.status_code == 303 and current_method.upper() not in {"GET", "HEAD"}:
                current_method = "GET"
                kwargs["data"] = None
        raise error("INVALID_URL", message="链接重定向次数过多")

    session.request = safe_request
    return session


def _build_safe_impersonate_handlers(handlers: list[Any]) -> list[Any]:
    try:
        from yt_dlp.networking._curlcffi import CurlCFFIRH
    except ImportError:
        return [SafeUrllibRH]

    class SafeCurlCFFIRH(CurlCFFIRH):
        RH_KEY = "CurlCFFI"
        RH_NAME = "safe-curl_cffi"

        def _create_instance(self, cookiejar: Any = None) -> Any:
            return _wrap_safe_curl_session(super()._create_instance(cookiejar=cookiejar))

    return [
        SafeUrllibRH
        if h is UrllibRH
        else (SafeCurlCFFIRH if h is CurlCFFIRH else h)
        for h in handlers
        if h in {UrllibRH, CurlCFFIRH}
    ]


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
    RH_KEY = "Urllib"
    RH_NAME = "safe-urllib"

    def _create_instance(self, proxies, cookiejar, legacy_ssl_support=None):
        default_opener = super()._create_instance(proxies, cookiejar, legacy_ssl_support)
        opener = urllib.request.OpenerDirector()
        has_proxy = bool(proxies)
        for handler in default_opener.handlers:
            if isinstance(handler, RedirectHandler):
                continue
            if not has_proxy and isinstance(handler, HTTPHandler):
                continue
            opener.add_handler(handler)
        if not has_proxy:
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
        self.add_info_extractor(MediaFetchKuaishouIE(self))
        self.add_info_extractor(MediaFetchPipixiaIE(self))
        super().add_default_info_extractors()

    def close(self):
        try:
            super().close()
        finally:
            if self._credential_snapshot:
                self._credential_snapshot.unlink(missing_ok=True)
                self._credential_snapshot = None

    def build_request_director(self, handlers, preferences=None):
        if self.params.get("impersonate"):
            safe_handlers = _build_safe_impersonate_handlers(list(handlers))
            return super().build_request_director(safe_handlers, preferences)
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
    login_markers = ("login required", "sign in", "cookies", "fresh cookies")
    if any(marker in message for marker in login_markers):
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


def _extract_sync(url: str, parser_hook: VideoParserHook | None = None) -> dict[str, Any]:
    settings = get_settings()

    # Optional Tier-0 Hybrid Engine (Douyin_TikTok_Download_API container) when configured.
    hybrid_result = fetch_hybrid_clean_media(url)
    if hybrid_result is not None:
        return hybrid_result

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
    proxy = settings.proxy_for_url(url)
    if proxy:
        options["proxy"] = proxy
    if settings.ytdlp_impersonate and _should_impersonate(url) and _curl_cffi_available():
        try:
            options["impersonate"] = ImpersonateTarget.from_str(settings.ytdlp_impersonate)
        except ValueError:
            logger.warning("Ignoring invalid YTDLP_IMPERSONATE=%s", settings.ytdlp_impersonate)

    configure_ytdlp_credentials(options, url)
    if parser_hook is not None:
        options = parser_hook.apply_request_profile(url, options)

    is_xhs = is_xiaohongshu_url(url)
    try:
        with SafeYoutubeDL(options) as ydl:
            ytdlp_error: DownloadError | None = None
            is_douyin = parser_hook is not None and parser_hook.name == "douyin-official-formats"
            official_only = is_douyin and is_official_share_url(url)
            if official_only:
                result = extract_official_douyin_info(ydl, url)
            elif is_xhs:
                # Prefer clean __INITIAL_STATE__ extractor (originVideoKey & galleries),
                # falling back to yt-dlp's XiaoHongShu extractor when needed.
                try:
                    result = extract_xiaohongshu_info(ydl, url)
                except XiaohongshuExtractUnavailable:
                    result = ydl.extract_info(url, download=False)
            else:
                try:
                    result = ydl.extract_info(url, download=False)
                except DownloadError as exc:
                    ytdlp_error = exc
                    result = None
            if result is None and is_douyin:
                try:
                    result = extract_official_douyin_info(ydl, url)
                except DouyinOfficialPlaybackUnavailable as exc:
                    if ytdlp_error is not None:
                        raise ytdlp_error from exc
                    raise
            elif isinstance(result, dict) and is_douyin and not official_only:
                try:
                    add_official_playback_format(ydl, url, result)
                except DouyinOfficialPlaybackUnavailable:
                    logger.info(
                        "Douyin official playback format was unavailable for %s",
                        redact_url(url),
                    )
                except Exception as exc:
                    logger.warning(
                        "Douyin official playback lookup failed for %s error_type=%s",
                        redact_url(url),
                        type(exc).__name__,
                    )
            elif result is None and ytdlp_error is not None:
                raise ytdlp_error
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
        selected_entry = select_playlist_or_multipart_entry(result, url)
        if selected_entry is None:
            raise error("UNSUPPORTED_URL", message="暂不支持空的播放列表页面")
        result = selected_entry
    if parser_hook is not None:
        parser_hook.validate_extracted_info(url, result)
    prefer_official_original_formats(result)
    return result


def _cache_key_for_url(url: str) -> str:
    return hashlib.sha256(url.encode("utf-8")).hexdigest()


def _public_payload(data: dict[str, Any]) -> dict[str, Any]:
    cleaned: dict[str, Any] = {}
    for key, value in data.items():
        if key.startswith("_"):
            continue
        if key in {"formats", "audio_formats"} and isinstance(value, list):
            cleaned[key] = [
                {k: v for k, v in item.items() if not str(k).startswith("_")}
                if isinstance(item, dict)
                else item
                for item in value
            ]
        else:
            cleaned[key] = value
    return cleaned


def _mime_for_ext(ext: str, *, is_audio: bool = False) -> str:
    ext_lower = ext.lower().lstrip(".")
    if is_audio:
        return {
            "m4a": "audio/mp4",
            "mp3": "audio/mpeg",
            "webm": "audio/webm",
            "opus": "audio/ogg",
        }.get(ext_lower, "application/octet-stream")
    return {
        "mp4": "video/mp4",
        "webm": "video/webm",
        "mkv": "video/x-matroska",
        "mov": "video/quicktime",
        "jpg": "image/jpeg",
        "jpeg": "image/jpeg",
        "png": "image/png",
        "webp": "image/webp",
    }.get(ext_lower, "application/octet-stream")


def _attach_stream_and_gallery_tokens(
    redis_client: Redis,
    *,
    title: str,
    source_url: str,
    formats: list[dict[str, Any]],
    audio_formats: list[dict[str, Any]],
    raw_gallery: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], str | None]:
    settings = get_settings()
    safe_stem = sanitize_filename(title, default="video", max_length=100)

    for fmt in formats:
        source = fmt.get("_direct_media") or fmt.get("_stream_source")
        is_stream = (
            fmt.get("delivery_mode") == "stream"
            and isinstance(source, dict)
            and isinstance(source.get("url"), str)
        )
        if is_stream and isinstance(source, dict):
            ext = str(fmt.get("extension") or "mp4")
            label = str(fmt.get("label") or "")
            filename = f"{safe_stem}_{label}.{ext}" if label else f"{safe_stem}.{ext}"
            token = create_stream_token(
                redis_client,
                url=source["url"],
                filename=filename,
                media_type=_mime_for_ext(ext, is_audio=False),
                source_url=source_url,
                http_headers=source.get("http_headers"),
            )
            fmt["stream_url"] = f"{settings.api_prefix}/stream/{token}"

    for afmt in audio_formats:
        source = afmt.get("_stream_source")
        is_audio_stream = (
            afmt.get("delivery_mode") == "stream"
            and isinstance(source, dict)
            and isinstance(source.get("url"), str)
        )
        if is_audio_stream and isinstance(source, dict):
            ext = str(afmt.get("extension") or "m4a")
            filename = f"{safe_stem}_audio.{ext}"
            token = create_stream_token(
                redis_client,
                url=source["url"],
                filename=filename,
                media_type=_mime_for_ext(ext, is_audio=True),
                source_url=source_url,
                http_headers=source.get("http_headers"),
            )
            afmt["stream_url"] = f"{settings.api_prefix}/stream/{token}"

    public_gallery: list[dict[str, Any]] = []
    valid_zip_items: list[dict[str, Any]] = []
    for index, item in enumerate(raw_gallery, start=1):
        if not isinstance(item, dict) or not isinstance(item.get("url"), str):
            continue
        try:
            checked_img_url = validate_public_url_sync(item["url"])
        except AppError:
            continue
        ext = str(item.get("extension") or "jpg").lower().lstrip(".")
        headers = dict(item.get("http_headers") or {})
        img_token = create_stream_token(
            redis_client,
            url=checked_img_url,
            filename=f"{safe_stem}_{index:02d}.{ext}",
            media_type=_mime_for_ext(ext),
            source_url=source_url,
            http_headers=headers,
        )
        live_stream_url: str | None = None
        raw_live = item.get("live_video_url")
        checked_live: str | None = None
        if isinstance(raw_live, str) and raw_live.startswith(("http://", "https://")):
            try:
                checked_live = validate_public_url_sync(raw_live)
            except AppError:
                checked_live = None
            if checked_live:
                live_token = create_stream_token(
                    redis_client,
                    url=checked_live,
                    filename=f"{safe_stem}_{index:02d}_live.mp4",
                    media_type="video/mp4",
                    source_url=source_url,
                    http_headers=headers,
                )
                live_stream_url = f"{settings.api_prefix}/stream/{live_token}"

        public_gallery.append(
            {
                "index": index,
                "extension": ext,
                "width": item.get("width"),
                "height": item.get("height"),
                "preview_url": f"{settings.api_prefix}/stream/{img_token}?inline=true",
                "download_url": f"{settings.api_prefix}/stream/{img_token}",
                "live_video_url": live_stream_url,
            }
        )
        valid_zip_items.append(
            {
                "url": checked_img_url,
                "extension": ext,
                "live_video_url": checked_live,
                "http_headers": headers,
            }
        )

    gallery_zip_url: str | None = None
    if valid_zip_items:
        zip_token = create_gallery_zip_token(
            redis_client,
            title=safe_stem,
            source_url=source_url,
            items=valid_zip_items,
        )
        gallery_zip_url = f"{settings.api_prefix}/gallery/{zip_token}"

    return public_gallery, gallery_zip_url


async def inspect_media(url: str, redis_client: Redis) -> InspectResponse:
    settings = get_settings()
    checked_url = await LinkResolver(max_redirects=settings.max_redirects).resolve(url)
    parser_hook = DEFAULT_VIDEO_PARSER_HOOKS.select(checked_url)
    url_hash = _cache_key_for_url(checked_url)
    cached_id = cast(str | None, redis_client.get(f"inspect-url:{url_hash}"))
    if cached_id:
        cached = cast(str | None, redis_client.get(f"inspect:{cached_id}"))
        if cached:
            return InspectResponse.model_validate(_public_payload(json.loads(cached)))

    try:
        info = await asyncio.wait_for(
            asyncio.to_thread(_extract_sync, checked_url, parser_hook),
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

    raw_gallery = info.get("_mediafetch_gallery")
    gallery_list = raw_gallery if isinstance(raw_gallery, list) else []

    raw_formats = info.get("formats") or []
    if raw_formats:
        formats, audio_formats = normalize_formats(raw_formats, duration)
    else:
        formats, audio_formats = [], []

    direct_formats = info.get("_mediafetch_direct_formats")
    if isinstance(direct_formats, dict):
        for item in formats:
            direct_source = direct_formats.get(item["id"])
            if isinstance(direct_source, dict):
                item["_direct_media"] = direct_source
                item["delivery_mode"] = "stream"

    title = str(info.get("title") or "未命名媒体").strip()[:300]
    public_gallery, gallery_zip_url = await asyncio.to_thread(
        _attach_stream_and_gallery_tokens,
        redis_client,
        title=title,
        source_url=checked_url,
        formats=formats,
        audio_formats=audio_formats,
        raw_gallery=gallery_list,
    )

    if not formats and not audio_formats and not public_gallery:
        raise error("NO_FORMATS")

    media_type = (
        "gallery"
        if public_gallery and not formats
        else ("audio" if audio_formats and not formats else "video")
    )
    inspect_id = secrets.token_urlsafe(24)
    uploader = str(info.get("uploader") or info.get("channel") or "").strip()[:200] or None
    platform = str(info.get("extractor_key") or info.get("extractor") or "Unknown")[:80]
    engine = str(info.get("_mediafetch_engine") or "yt-dlp")[:40]
    thumbnail = _safe_thumbnail(info) or (
        public_gallery[0]["preview_url"] if public_gallery else None
    )

    payload: dict[str, Any] = {
        "inspect_id": inspect_id,
        "title": title,
        "thumbnail": thumbnail,
        "duration": duration,
        "uploader": uploader,
        "platform": platform,
        "engine": engine,
        "media_type": media_type,
        "watermark_free": True,
        "parser_hook": parser_hook.name if parser_hook else None,
        "formats": formats,
        "audio_formats": audio_formats,
        "gallery": public_gallery,
        "gallery_zip_url": gallery_zip_url,
        "_source_url": checked_url,
        "_webpage_url": redact_url(str(info.get("webpage_url") or checked_url)),
    }
    cache_ttl = min(settings.inspect_cache_ttl_seconds, settings.stream_token_ttl_seconds)
    encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    pipeline = redis_client.pipeline()
    pipeline.setex(f"inspect:{inspect_id}", cache_ttl, encoded)
    pipeline.setex(
        f"inspect-url:{url_hash}",
        cache_ttl,
        inspect_id,
    )
    pipeline.execute()
    return InspectResponse.model_validate(_public_payload(payload))
