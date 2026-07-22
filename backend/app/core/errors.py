from dataclasses import dataclass
from typing import Any


@dataclass
class AppError(Exception):
    code: str
    message: str
    status_code: int = 400
    details: dict[str, Any] | None = None

    def __str__(self) -> str:
        return self.message


ERROR_MESSAGES: dict[str, tuple[str, int]] = {
    "INVALID_URL": ("链接格式无效，仅支持公开的 HTTP 或 HTTPS 地址", 400),
    "BLOCKED_ADDRESS": ("出于安全原因，无法访问该地址", 400),
    "UNSUPPORTED_URL": ("暂时不支持这个链接", 422),
    "VIDEO_UNAVAILABLE": ("视频不可用或已被删除", 422),
    "PRIVATE_VIDEO": ("无法处理私密内容", 403),
    "LOGIN_REQUIRED": ("该内容需要有效平台会话，请由管理员在 /admin 更新登录会话", 403),
    "DRM_PROTECTED": ("该内容可能受 DRM 保护，无法处理", 422),
    "NO_FORMATS": ("没有找到可下载的媒体格式", 422),
    "FORMAT_EXPIRED": ("解析结果已过期，请重新解析链接", 410),
    "FORMAT_NOT_FOUND": ("所选格式不存在，请重新选择", 400),
    "FILE_TOO_LARGE": ("文件超过服务器允许的大小", 413),
    "VIDEO_TOO_LONG": ("视频时长超过服务器限制", 413),
    "RATE_LIMITED": ("请求过于频繁，请稍后再试", 429),
    "QUEUE_FULL": ("当前任务较多，请稍后再试", 503),
    "DOWNLOAD_FAILED": ("下载失败，请稍后重试", 500),
    "MERGE_FAILED": ("音视频合并失败", 500),
    "TRANSCODE_FAILED": ("格式转换失败", 500),
    "JOB_NOT_FOUND": ("任务不存在", 404),
    "JOB_EXPIRED": ("任务已过期", 410),
    "ADMIN_UNAUTHORIZED": ("管理员凭证无效", 401),
    "PLATFORM_LOGIN_FAILED": ("平台登录失败，请重新生成二维码", 502),
    "PLATFORM_LOGIN_EXPIRED": ("登录二维码已过期", 410),
    "INVALID_COOKIE_FILE": ("Cookie 文件无效、已过期或包含非目标平台域名", 400),
    "INTERNAL_ERROR": ("服务器暂时无法处理请求", 500),
}


def error(code: str, *, message: str | None = None, details: dict | None = None) -> AppError:
    default_message, status = ERROR_MESSAGES.get(code, ERROR_MESSAGES["INTERNAL_ERROR"])
    return AppError(code, message or default_message, status, details)
