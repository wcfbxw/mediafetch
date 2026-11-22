from functools import lru_cache
from pathlib import Path
from typing import Annotated, Literal
from urllib.parse import urlsplit

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

DOMESTIC_PLATFORM_DOMAINS: tuple[str, ...] = (
    "douyin.com",
    "iesdouyin.com",
    "douyinvod.com",
    "byteimg.com",
    "snssdk.com",
    "xiaohongshu.com",
    "xhslink.com",
    "xhscdn.com",
    "kuaishou.com",
    "chenzhongtech.com",
    "gifshow.com",
    "yximgs.com",
    "kwimgs.com",
    "bilibili.com",
    "b23.tv",
    "bilivideo.com",
    "bilivideo.cn",
    "hdslb.com",
    "weibo.com",
    "weibo.cn",
    "weibocdn.com",
    "sinaimg.cn",
    "ixigua.com",
    "toutiao.com",
    "pipixia.com",
    "ppximg.com",
    "acfun.cn",
    "huya.com",
    "douyu.com",
    "zhihu.com",
    "qq.com",
)


def is_domestic_url(url: str) -> bool:
    hostname = (urlsplit(url).hostname or "").lower().rstrip(".")
    if not hostname:
        return False
    return any(
        hostname == domain or hostname.endswith(f".{domain}")
        for domain in DOMESTIC_PLATFORM_DOMAINS
    )


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
    access_token: str | None = None
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
    stream_token_ttl_seconds: int = 1800
    file_ttl_seconds: int = 7200
    job_ttl_seconds: int = 86_400
    cleanup_interval_seconds: int = 300
    max_redirects: int = 5
    rate_limit_inspect_per_minute: int = 20
    rate_limit_download_per_minute: int = 10
    audio_mp3_quality: int = 2

    # Outbound proxy routing: CN_PROXY_URL for domestic platforms,
    # GLOBAL_PROXY_URL for international platforms, YTDLP_PROXY as fallback.
    cn_proxy_url: str | None = None
    global_proxy_url: str | None = None
    ytdlp_proxy: str | None = None

    # Optional multi-engine & anti-bot capabilities.
    douyin_api_base_url: str | None = None
    ytdlp_impersonate: str | None = "chrome"
    youtube_po_token: str | None = None

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

    @field_validator(
        "access_token",
        "cn_proxy_url",
        "global_proxy_url",
        "ytdlp_proxy",
        "douyin_api_base_url",
        "ytdlp_impersonate",
        "youtube_po_token",
    )
    @classmethod
    def normalize_optional_str(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        return cleaned or None

    def proxy_for_url(self, url: str) -> str | None:
        if is_domestic_url(url):
            return self.cn_proxy_url or self.ytdlp_proxy
        return self.global_proxy_url or self.ytdlp_proxy

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
