import time

import pytest

from app.api import downloads
from app.core.errors import AppError
from app.services import file_tokens
from app.services.file_tokens import (
    create_file_token,
    ensure_within,
    sanitize_filename,
    validate_file_token,
)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("my/video?.mp4", "my_video_.mp4"),
        ("  title   with spaces .mp4  ", "title with spaces .mp4"),
        ("CON", "_CON"),
        ("..", "media"),
    ],
)
def test_filename_sanitization(raw: str, expected: str):
    assert sanitize_filename(raw) == expected


def test_path_traversal_is_rejected(test_settings):
    with pytest.raises(AppError):
        ensure_within(
            test_settings.downloads_dir,
            test_settings.downloads_dir / ".." / "secrets.txt",
        )


def test_file_token_does_not_expose_path_and_expires(
    redis_client,
    test_settings,
    monkeypatch: pytest.MonkeyPatch,
):
    job_id = "safeJobId"
    directory = test_settings.downloads_dir / job_id
    directory.mkdir()
    media = directory / "测试 video.mp4"
    media.write_bytes(b"video")
    now = int(time.time())
    monkeypatch.setattr(file_tokens.time, "time", lambda: now)
    token, expires_at = create_file_token(redis_client, job_id, media)
    assert str(test_settings.downloads_dir) not in token
    assert validate_file_token(redis_client, token)["path"] == media.resolve()
    monkeypatch.setattr(file_tokens.time, "time", lambda: expires_at + 1)
    with pytest.raises(AppError) as caught:
        validate_file_token(redis_client, token)
    assert caught.value.status_code == 410


def test_token_mapping_cannot_escape_download_root(redis_client, test_settings):
    job_id = "job"
    directory = test_settings.downloads_dir / job_id
    directory.mkdir()
    media = directory / "safe.mp4"
    media.write_bytes(b"data")
    token, _ = create_file_token(redis_client, job_id, media)
    key = next(iter(redis_client.scan_iter("file-token:*")))
    redis_client.set(
        key,
        '{"relative_path":"../outside","filename":"x","expires_at":9999999999,"size":1}',
    )
    with pytest.raises(AppError):
        validate_file_token(redis_client, token)


@pytest.mark.asyncio
async def test_x_accel_response_leaves_content_length_to_nginx(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr(downloads, "get_redis", lambda: object())
    monkeypatch.setattr(
        downloads,
        "validate_file_token",
        lambda _redis, _token: {
            "relative_path": "job/file.mp4",
            "filename": "file.mp4",
            "size": 4096,
        },
    )

    response = await downloads.download_file("valid-token")

    assert response.headers["x-accel-redirect"] == "/protected/job/file.mp4"
    assert "content-length" not in response.headers
