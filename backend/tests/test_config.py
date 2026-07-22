from app.core.config import Settings


def test_comma_separated_allowed_origins(monkeypatch):
    monkeypatch.setenv(
        "ALLOWED_ORIGINS",
        "https://media.example,https://admin.example",
    )
    settings = Settings()
    assert settings.allowed_origins == [
        "https://media.example",
        "https://admin.example",
    ]
