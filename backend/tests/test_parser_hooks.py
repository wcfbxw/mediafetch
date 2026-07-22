import pytest

from app.core.errors import AppError
from app.parsers.hooks import (
    DouyinOfficialFormatHook,
    ParserRequestProfile,
    VideoParserHook,
    VideoParserHookRegistry,
)


class ExampleHook(VideoParserHook):
    name = "example-official-formats"
    allowed_source_domains = ("video.example",)
    request_profile = ParserRequestProfile(
        referer="https://video.example/",
        user_agent="MediaFetch-Test-Agent",
    )


def test_registry_selects_only_exact_or_subdomain_matches():
    registry = VideoParserHookRegistry((DouyinOfficialFormatHook(),))

    assert registry.select("https://www.douyin.com/video/123") is not None
    assert registry.select("https://douyin.com/video/123") is not None
    assert registry.select("https://douyin.com.evil.example/video/123") is None
    assert registry.select("https://example.com/?next=https://douyin.com") is None


def test_hook_can_only_apply_its_fixed_request_profile():
    hook = ExampleHook()
    original = {"skip_download": True, "http_headers": {"Accept": "video/mp4"}}

    updated = hook.apply_request_profile("https://video.example/watch/1", original)

    assert original == {"skip_download": True, "http_headers": {"Accept": "video/mp4"}}
    assert updated["skip_download"] is True
    assert updated["http_headers"] == {
        "Accept": "video/mp4",
        "Referer": "https://video.example/",
        "User-Agent": "MediaFetch-Test-Agent",
    }


def test_hook_validation_does_not_rewrite_official_format_urls():
    class DefectiveHook(ExampleHook):
        name = "defective-test-hook"

        def validate_platform_result(self, info):
            info["formats"][0]["url"] = "https://attacker.example/rewritten"

    hook = DefectiveHook()
    media_url = "https://cdn.video.example/media/file.mp4?signature=unchanged"
    info = {
        "webpage_url": "https://video.example/watch/1",
        "formats": [{"format_id": "official", "url": media_url}],
    }

    hook.validate_extracted_info("https://video.example/watch/1", info)

    assert info["formats"][0]["url"] == media_url


def test_hook_rejects_extractor_result_from_another_source_domain():
    hook = ExampleHook()

    with pytest.raises(AppError) as caught:
        hook.validate_extracted_info(
            "https://video.example/watch/1",
            {"webpage_url": "https://attacker.example/watch/1"},
        )

    assert caught.value.code == "UNSUPPORTED_URL"


def test_registry_rejects_duplicate_names_and_malformed_allowlists():
    with pytest.raises(ValueError):
        VideoParserHookRegistry((ExampleHook(), ExampleHook()))

    class MalformedHook(VideoParserHook):
        name = "malformed"
        allowed_source_domains = ("https://video.example",)

    with pytest.raises(ValueError):
        VideoParserHookRegistry((MalformedHook(),))
