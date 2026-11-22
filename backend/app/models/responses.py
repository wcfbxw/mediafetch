from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

DeliveryMode = Literal["stream", "async_merge"]
MediaType = Literal["video", "gallery", "audio"]


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
    watermark_free: bool = True
    delivery_mode: DeliveryMode = "async_merge"
    stream_url: str | None = None


class GalleryItem(BaseModel):
    model_config = ConfigDict(extra="ignore")

    index: int
    extension: str = "jpg"
    width: int | None = None
    height: int | None = None
    preview_url: str
    download_url: str
    live_video_url: str | None = None


class InspectResponse(BaseModel):
    inspect_id: str
    title: str
    thumbnail: str | None = None
    duration: int | None = None
    uploader: str | None = None
    platform: str
    engine: str | None = None
    media_type: MediaType = "video"
    watermark_free: bool = True
    parser_hook: str | None = None
    formats: list[MediaFormat]
    audio_formats: list[MediaFormat]
    gallery: list[GalleryItem] = Field(default_factory=list)
    gallery_zip_url: str | None = None


class ParseResponse(BaseModel):
    code: Literal[200] = 200
    inspect_id: str
    title: str
    cover_url: str | None = None
    duration: int | None = None
    uploader: str | None = None
    platform: str
    engine: str | None = None
    media_type: MediaType = "video"
    watermark_free: bool = True
    parser_hook: str | None = None
    formats: list[MediaFormat]
    audio_formats: list[MediaFormat]
    gallery: list[GalleryItem] = Field(default_factory=list)
    gallery_zip_url: str | None = None


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


class AuthRequirementResponse(BaseModel):
    access_token_required: bool = False


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
