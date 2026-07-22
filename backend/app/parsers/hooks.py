from abc import ABC
from collections.abc import Mapping, Sequence
from copy import deepcopy
from dataclasses import dataclass
from typing import Any, ClassVar, final
from urllib.parse import urlsplit

from app.core.errors import error
from app.core.security import canonicalize_url
from app.services.douyin_official import DOUYIN_MOBILE_USER_AGENT


def _host_matches(hostname: str, domains: Sequence[str]) -> bool:
    host = hostname.lower().rstrip(".")
    return any(host == domain or host.endswith(f".{domain}") for domain in domains)


@dataclass(frozen=True)
class ParserRequestProfile:
    """The only request settings a parser hook may add to yt-dlp."""

    referer: str | None = None
    user_agent: str | None = None


class VideoParserHook(ABC):
    """Server-owned extension point around the normal yt-dlp extractor.

    Hooks are selected exclusively by an allowlisted source hostname. They may
    provide a fixed request profile and validate the extractor result, but the
    interface deliberately has no method that can return or rewrite a media
    URL, format selector, yt-dlp argument, FFmpeg argument, or output path.
    """

    name: ClassVar[str]
    allowed_source_domains: ClassVar[tuple[str, ...]]
    request_profile: ClassVar[ParserRequestProfile] = ParserRequestProfile()

    @final
    def matches(self, source_url: str) -> bool:
        try:
            checked = canonicalize_url(source_url)
        except Exception:
            return False
        hostname = urlsplit(checked).hostname or ""
        return _host_matches(hostname, self.allowed_source_domains)

    @final
    def apply_request_profile(
        self,
        source_url: str,
        options: Mapping[str, Any],
    ) -> dict[str, Any]:
        self.validate_source(source_url)
        updated = dict(options)
        existing_headers = updated.get("http_headers")
        headers = dict(existing_headers) if isinstance(existing_headers, dict) else {}
        if self.request_profile.referer:
            headers["Referer"] = self.request_profile.referer
        if self.request_profile.user_agent:
            headers["User-Agent"] = self.request_profile.user_agent
        if headers:
            updated["http_headers"] = headers
        return updated

    @final
    def validate_source(self, source_url: str) -> None:
        checked = canonicalize_url(source_url)
        hostname = urlsplit(checked).hostname or ""
        if not _host_matches(hostname, self.allowed_source_domains):
            raise error("UNSUPPORTED_URL")

    @final
    def validate_extracted_info(
        self,
        source_url: str,
        info: Mapping[str, Any],
    ) -> None:
        self.validate_source(source_url)
        webpage_url = info.get("webpage_url")
        if isinstance(webpage_url, str) and not self.matches(webpage_url):
            raise error("UNSUPPORTED_URL")
        # Platform-specific validation receives a detached copy, so even a
        # defective code-owned hook cannot rewrite the extractor result.
        self.validate_platform_result(deepcopy(dict(info)))

    def validate_platform_result(self, info: Mapping[str, Any]) -> None:
        """Optionally reject metadata that does not belong to the hook's platform."""
        del info


class DouyinOfficialFormatHook(VideoParserHook):
    name = "douyin-official-formats"
    allowed_source_domains = ("douyin.com", "iesdouyin.com")
    request_profile = ParserRequestProfile(
        referer="https://www.douyin.com/",
        user_agent=DOUYIN_MOBILE_USER_AGENT,
    )

    def validate_platform_result(self, info: Mapping[str, Any]) -> None:
        extractor = str(info.get("extractor_key") or info.get("extractor") or "").lower()
        if extractor and "douyin" not in extractor:
            raise error("UNSUPPORTED_URL")


class VideoParserHookRegistry:
    def __init__(self, hooks: Sequence[VideoParserHook]) -> None:
        names: set[str] = set()
        validated: list[VideoParserHook] = []
        for hook in hooks:
            if not hook.name or hook.name in names or not hook.allowed_source_domains:
                raise ValueError("parser hook names and source-domain allowlists must be unique")
            if any(
                not domain
                or domain != domain.lower().rstrip(".")
                or ":" in domain
                or "/" in domain
                for domain in hook.allowed_source_domains
            ):
                raise ValueError("parser hook source domains must be normalized hostnames")
            names.add(hook.name)
            validated.append(hook)
        self._hooks = tuple(validated)

    @property
    def hooks(self) -> tuple[VideoParserHook, ...]:
        return self._hooks

    def select(self, source_url: str) -> VideoParserHook | None:
        matches = [hook for hook in self._hooks if hook.matches(source_url)]
        if len(matches) > 1:
            raise error("INTERNAL_ERROR")
        return matches[0] if matches else None


DEFAULT_VIDEO_PARSER_HOOKS = VideoParserHookRegistry((DouyinOfficialFormatHook(),))
