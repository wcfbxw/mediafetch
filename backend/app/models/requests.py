import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class InspectRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    url: str = Field(min_length=8, max_length=2048)

    @field_validator("url", mode="before")
    @classmethod
    def extract_url_from_share_text(cls, value: object) -> str:
        if not isinstance(value, str) or len(value) > 8192:
            raise ValueError("invalid URL input")
        match = re.search(r"https?://[^\s<>\"']+", value, flags=re.IGNORECASE)
        if not match:
            raise ValueError("no HTTP URL found")
        candidate = match.group(0)
        trailing = frozenset(".,;:!?])}>,，。；：！？）】》」』")
        while candidate and candidate[-1] in trailing:
            candidate = candidate[:-1]
        return candidate


class DownloadRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    inspect_id: str = Field(min_length=20, max_length=128, pattern=r"^[A-Za-z0-9_-]+$")
    video_format_id: str = Field(min_length=1, max_length=256)
    audio_format_id: str | None = Field(default=None, max_length=256)
    output_container: Literal["mp4", "webm", "mkv", "original", "m4a", "mp3"] = "mp4"
    compatibility_mode: bool = False

    @field_validator("video_format_id", "audio_format_id")
    @classmethod
    def reject_control_characters(cls, value: str | None) -> str | None:
        if value is not None and any(ord(char) < 32 for char in value):
            raise ValueError("format id contains control characters")
        return value
