from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class MediaFormat(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str
    label: str
    width: int | None = None
    height: int | None = None
    fps: float | None = None
    extension: str
    video_codec: str | None = None
    audio_codec: str | None = None
    bitrate: float | None = None
    estimated_size: int | None = None
    has_video: bool
    has_audio: bool
    requires_merge: bool
    preferred: bool = False


class InspectResponse(BaseModel):
    inspect_id: str
    title: str
    thumbnail: str | None = None
    duration: int | None = None
    uploader: str | None = None
    platform: str
    parser_hook: str | None = None
    formats: list[MediaFormat]
    audio_formats: list[MediaFormat]


class ParseResponse(BaseModel):
    code: Literal[200] = 200
    inspect_id: str
    title: str
    cover_url: str | None = None
    duration: int | None = None
    uploader: str | None = None
    platform: str
    parser_hook: str | None = None
    formats: list[MediaFormat]
    audio_formats: list[MediaFormat]


JobStatus = Literal[
    "queued",
    "inspecting",
    "downloading",
    "downloading_video",
    "downloading_audio",
    "merging",
    "processing",
    "ready",
    "failed",
    "cancelled",
    "expired",
]


class CreateDownloadResponse(BaseModel):
    job_id: str
    status: Literal["queued"]


class QuickDownloadResponse(BaseModel):
    code: Literal[202] = 202
    message: Literal["queued"] = "queued"
    job_id: str
    status: Literal["queued"]


class JobResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    job_id: str
    status: JobStatus
    progress: float = Field(ge=0, le=100)
    speed: int | None = None
    downloaded_bytes: int = 0
    total_bytes: int | None = None
    eta: int | None = None
    message: str
    download_url: str | None = None
    error: dict | None = None


class HealthResponse(BaseModel):
    status: Literal["ok", "degraded"]
    redis: bool
    ffmpeg: bool
    ytdlp: bool


class PlatformSessionStatus(BaseModel):
    configured: bool
    updated_at: int | None = None
    expires_at: int | None = None


class BilibiliLoginStart(BaseModel):
    login_id: str
    qr_image: str
    expires_in: int


class BilibiliLoginPoll(BaseModel):
    status: Literal["waiting_scan", "waiting_confirm", "ready", "expired"]
    message: str
    expires_in: int
