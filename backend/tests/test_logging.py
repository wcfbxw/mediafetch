import logging

from app.core.logging import RedactingFilter


def test_redacting_filter_preserves_positional_argument_types() -> None:
    record = logging.LogRecord(
        "test",
        logging.INFO,
        __file__,
        1,
        "pid=%d duration=%0.2f url=%s",
        (8, 1.25, "https://example.com/video?token=secret"),
        None,
    )

    assert RedactingFilter().filter(record)
    assert record.getMessage() == "pid=8 duration=1.25 url=https://example.com/video"


def test_redacting_filter_preserves_mapping_arguments() -> None:
    record = logging.LogRecord(
        "test",
        logging.INFO,
        __file__,
        1,
        "cleanup=%s",
        ({"temp": 0, "url": "https://example.com/video?sig=secret"},),
        None,
    )

    assert RedactingFilter().filter(record)
    assert record.getMessage() == ("cleanup={'temp': 0, 'url': 'https://example.com/video'}")
