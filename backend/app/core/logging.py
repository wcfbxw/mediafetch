import logging
import re
from collections.abc import Mapping, MutableMapping
from typing import Any
from urllib.parse import urlsplit, urlunsplit

SENSITIVE_PATTERN = re.compile(
    r"(?i)(cookie|authorization|token|signature|sig|key|password)=([^&\s]+)"
)
URL_PATTERN = re.compile(r"https?://[^\s\"'<>]+", re.IGNORECASE)
FILE_TOKEN_PATH = re.compile(r"(/api/v1/files/)[^/?\s]+")


def _redact_single_url(value: str) -> str:
    try:
        parts = urlsplit(value)
        if parts.scheme and parts.netloc:
            netloc = parts.hostname or ""
            if ":" in netloc:
                netloc = f"[{netloc}]"
            if parts.port:
                netloc = f"{netloc}:{parts.port}"
            return urlunsplit((parts.scheme, netloc, parts.path, "", ""))
    except ValueError:
        pass
    return value


def redact_url(value: str) -> str:
    redacted = URL_PATTERN.sub(lambda match: _redact_single_url(match.group(0)), value)
    return SENSITIVE_PATTERN.sub(r"\1=[REDACTED]", redacted)


def redact_path(value: str) -> str:
    return FILE_TOKEN_PATH.sub(r"\1[REDACTED]", value)


class RedactingFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        if not hasattr(record, "request_id"):
            record.request_id = "-"
        if isinstance(record.msg, str):
            record.msg = redact_url(record.msg)
        if isinstance(record.args, Mapping):
            record.args = {
                key: redact_url(value) if isinstance(value, str) else value
                for key, value in record.args.items()
            }
        elif record.args:
            record.args = tuple(
                redact_url(arg) if isinstance(arg, str) else arg for arg in record.args
            )
        return True


class RedactingFormatter(logging.Formatter):
    def formatException(self, exc_info) -> str:
        return redact_url(super().formatException(exc_info))


def configure_logging(level: str) -> None:
    handler = logging.StreamHandler()
    handler.addFilter(RedactingFilter())
    handler.setFormatter(
        RedactingFormatter(
            "%(asctime)s %(levelname)s %(name)s request_id=%(request_id)s %(message)s"
        )
    )
    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level.upper())


class RequestIdAdapter(logging.LoggerAdapter):
    def process(
        self, msg: object, kwargs: MutableMapping[str, Any]
    ) -> tuple[object, MutableMapping[str, Any]]:
        adapter_extra = self.extra or {}
        kwargs.setdefault("extra", {}).setdefault(
            "request_id", adapter_extra.get("request_id", "-")
        )
        return msg, kwargs
