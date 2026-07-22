import json

import pytest
from pydantic import ValidationError

from app.api.downloads import _create_download
from app.core.errors import AppError
from app.models.requests import DownloadRequest
from app.services.jobs import (
    can_transition,
    default_job_state,
    request_cancellation,
    save_new_job,
)


def test_task_state_transitions():
    assert can_transition("queued", "downloading_video")
    assert can_transition("downloading_video", "downloading_audio")
    assert can_transition("downloading_audio", "merging")
    assert can_transition("merging", "ready")
    assert not can_transition("ready", "downloading")
    assert can_transition("ready", "expired")


def test_download_request_rejects_unsafe_postprocess_preset():
    with pytest.raises(ValidationError):
        DownloadRequest(
            inspect_id="abcdefghijklmnopqrstuvwxyz",
            video_format_id="v1",
            output_container="mp4",
            postprocess_preset="delogo",  # type: ignore[arg-type]
        )


def test_task_cancellation(redis_client):
    state = default_job_state("job-one")
    save_new_job(redis_client, state)
    cancelled = request_cancellation(redis_client, "job-one")
    assert cancelled["status"] == "cancelled"
    assert redis_client.get("cancel:job-one") == "1"


def test_expired_inspect_id(redis_client):
    payload = DownloadRequest(
        inspect_id="abcdefghijklmnopqrstuvwxyz",
        video_format_id="v1",
        output_container="mp4",
    )
    with pytest.raises(AppError) as caught:
        _create_download(redis_client, payload, "203.0.113.5")
    assert caught.value.code == "FORMAT_EXPIRED"


def test_illegal_format_id_from_valid_inspection(redis_client):
    inspection = {
        "inspect_id": "abcdefghijklmnopqrstuvwxyz",
        "title": "Fixture",
        "_source_url": "https://example.com/video",
        "duration": 30,
        "formats": [
            {
                "id": "known",
                "has_video": True,
                "has_audio": True,
                "estimated_size": 100,
            }
        ],
        "audio_formats": [],
    }
    redis_client.set("inspect:abcdefghijklmnopqrstuvwxyz", json.dumps(inspection))
    payload = DownloadRequest(
        inspect_id="abcdefghijklmnopqrstuvwxyz",
        video_format_id="unknown",
        output_container="mp4",
    )
    with pytest.raises(AppError) as caught:
        _create_download(redis_client, payload, "203.0.113.5")
    assert caught.value.code == "FORMAT_NOT_FOUND"


def test_estimated_file_size_limit(redis_client, test_settings):
    inspection = {
        "inspect_id": "abcdefghijklmnopqrstuvwxyz",
        "title": "Large fixture",
        "_source_url": "https://example.com/video",
        "duration": 30,
        "formats": [
            {
                "id": "large",
                "has_video": True,
                "has_audio": True,
                "estimated_size": test_settings.max_file_size_bytes + 1,
            }
        ],
        "audio_formats": [],
    }
    redis_client.set("inspect:abcdefghijklmnopqrstuvwxyz", json.dumps(inspection))
    payload = DownloadRequest(
        inspect_id="abcdefghijklmnopqrstuvwxyz",
        video_format_id="large",
        output_container="mp4",
    )
    with pytest.raises(AppError) as caught:
        _create_download(redis_client, payload, "203.0.113.5")
    assert caught.value.code == "FILE_TOO_LARGE"
