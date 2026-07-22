from functools import lru_cache
from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    app_name: str = "MediaFetch"
    app_env: Literal["development", "test", "production"] = "production"
    log_level: str = "INFO"
    api_prefix: str = "/api/v1"
    redis_url: str = "redis://localhost:6379/0"
    public_base_url: str = "http://localhost"
    x_accel_redirect_enabled: bool = True
    allowed_origins: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: ["http://localhost"]
    )
    token_secret: str = Field(min_length=32)
    admin_token: str | None = None
    storage_root: Path = Path("./storage")
    credentials_root: Path = Path("./credentials")

    max_concurrent_jobs_per_ip: int = 2
    max_global_workers: int = 2
    max_queue_size: int = 100
    max_file_size_mb: int = 2048
    max_duration_seconds: int = 10_800
    download_timeout_seconds: int = 3600
    ffmpeg_timeout_seconds: int = 1800
    ffmpeg_threads: int = 2
    ffmpeg_x264_preset: Literal[
        "ultrafast",
        "superfast",
        "veryfast",
        "faster",
        "fast",
        "medium",
        "slow",
    ] = "veryfast"
    inspect_timeout_seconds: int = 45
    inspect_cache_ttl_seconds: int = 600
    file_ttl_seconds: int = 7200
    job_ttl_seconds: int = 86_400
    cleanup_interval_seconds: int = 300
    max_redirects: int = 5
    rate_limit_inspect_per_minute: int = 20
    rate_limit_download_per_minute: int = 10
    audio_mp3_quality: int = 2
    ytdlp_proxy: str | None = None
    parallel_download_enabled: bool = True
    parallel_download_connections: int = Field(default=8, ge=1, le=16)
    parallel_download_min_split_size_mb: int = Field(default=4, ge=1, le=64)
    parallel_download_chunk_size_mb: int = Field(default=4, ge=1, le=32)
    bilibili_user_agent: str = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/143.0.0.0 Safari/537.36"
    )

    @field_validator("allowed_origins", mode="before")
    @classmethod
    def parse_origins(cls, value: object) -> object:
        if isinstance(value, str):
            return [item.strip() for item in value.split(",") if item.strip()]
        return value

    @field_validator("token_secret")
    @classmethod
    def validate_secret(cls, value: str) -> str:
        if len(value) < 32:
            raise ValueError("TOKEN_SECRET must contain at least 32 characters")
        return value

    @field_validator("admin_token")
    @classmethod
    def validate_admin_token(cls, value: str | None) -> str | None:
        if value is None or not value.strip():
            return None
        if len(value) < 32:
            raise ValueError("ADMIN_TOKEN must contain at least 32 characters")
        return value

    @property
    def max_file_size_bytes(self) -> int:
        return self.max_file_size_mb * 1024 * 1024

    @property
    def downloads_dir(self) -> Path:
        return self.storage_root / "downloads"

    @property
    def temp_dir(self) -> Path:
        return self.storage_root / "temp"

    @property
    def bilibili_cookie_file(self) -> Path:
        return self.credentials_root / "bilibili-cookies.txt"

    def ensure_storage(self) -> None:
        self.downloads_dir.mkdir(parents=True, exist_ok=True)
        self.temp_dir.mkdir(parents=True, exist_ok=True)
        self.credentials_root.mkdir(parents=True, exist_ok=True)


@lru_cache
def get_settings() -> Settings:
    return Settings()
