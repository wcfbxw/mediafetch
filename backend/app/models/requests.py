from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.core.errors import AppError
from app.services.link_resolver import extract_http_url
from app.services.postprocess import PostprocessPreset


class InspectRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    url: str = Field(min_length=8, max_length=2048)

    @field_validator("url", mode="before")
    @classmethod
    def extract_url_from_share_text(cls, value: object) -> str:
        if not isinstance(value, str):
            raise ValueError("invalid URL input")
        try:
            return extract_http_url(value)
        except AppError as exc:
            raise ValueError("invalid URL input") from exc


class DownloadRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    inspect_id: str = Field(min_length=20, max_length=128, pattern=r"^[A-Za-z0-9_-]+$")
    video_format_id: str = Field(min_length=1, max_length=256)
    audio_format_id: str | None = Field(default=None, max_length=256)
    output_container: Literal["mp4", "webm", "mkv", "original", "m4a", "mp3"] = "mp4"
    postprocess_preset: PostprocessPreset = PostprocessPreset.REMUX
    compatibility_mode: bool = False

    @field_validator("video_format_id", "audio_format_id")
    @classmethod
    def reject_control_characters(cls, value: str | None) -> str | None:
        if value is not None and any(ord(char) < 32 for char in value):
            raise ValueError("format id contains control characters")
        return value


class ParseRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    share_text: str = Field(min_length=8, max_length=8192)

    @field_validator("share_text", mode="before")
    @classmethod
    def extract_url_from_share_text(cls, value: object) -> str:
        if not isinstance(value, str):
            raise ValueError("invalid share text")
        try:
            return extract_http_url(value)
        except AppError as exc:
            raise ValueError("invalid share text") from exc


class QuickDownloadRequest(ParseRequest):
    output_container: Literal["mp4", "webm", "mkv"] = "mp4"
    postprocess_preset: PostprocessPreset = PostprocessPreset.REMUX
    compatibility_mode: bool = False
    apply_ffmpeg_crop: bool = False
