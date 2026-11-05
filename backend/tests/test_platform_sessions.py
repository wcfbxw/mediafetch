import secrets
from http.cookiejar import MozillaCookieJar

import pytest
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

from app.api.platform_sessions import router
from app.core.errors import AppError
from app.services.platform_credentials import MAX_COOKIE_FILE_BYTES, platform_cookie_file


@pytest.fixture
def admin_client(test_settings):
    test_settings.admin_token = secrets.token_urlsafe(48)
    app = FastAPI()
    app.include_router(router, prefix="/api/v1")

    @app.exception_handler(AppError)
    async def handle_error(_request: Request, exc: AppError):
        return JSONResponse(status_code=exc.status_code, content={"error": {"code": exc.code}})

    with TestClient(app, headers={"X-Admin-Token": test_settings.admin_token}) as client:
        yield client


@pytest.mark.parametrize(
    "platform, domain", [("douyin", ".douyin.com"), ("xiaohongshu", ".xiaohongshu.com")]
)
def test_admin_import_filters_mixed_export_and_supports_status_and_delete(
    admin_client, platform, domain
):
    base = f"/api/v1/admin/platforms/{platform}"
    assert admin_client.get(f"{base}/status").json()["configured"] is False
    content = (
        "# Netscape HTTP Cookie File\n"
        f"{domain}\tTRUE\t/\tTRUE\t4102444800\tsession\ttest-only\n"
        ".example.com\tTRUE\t/\tTRUE\t4102444800\tunrelated\ttest-only\n"
    ).encode()

    response = admin_client.put(
        f"{base}/cookies", files={"file": ("cookies.txt", content, "text/plain")}
    )

    assert response.status_code == 200
    assert response.json()["configured"] is True
    assert set(response.json()) == {"configured", "updated_at", "expires_at"}
    saved = MozillaCookieJar(str(platform_cookie_file(platform)))
    saved.load()
    assert {cookie.domain for cookie in saved} == {domain}
    assert admin_client.get(f"{base}/status").json()["configured"] is True
    assert admin_client.delete(f"{base}/session").json()["configured"] is False
    assert not platform_cookie_file(platform).exists()


def test_admin_import_keeps_upload_size_limit(admin_client):
    response = admin_client.put(
        "/api/v1/admin/platforms/douyin/cookies",
        files={"file": ("cookies.txt", b"#" * (MAX_COOKIE_FILE_BYTES + 1), "text/plain")},
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "INVALID_COOKIE_FILE"
    assert not platform_cookie_file("douyin").exists()


@pytest.mark.parametrize(
    "method, suffix", [("get", "status"), ("put", "cookies"), ("delete", "session")]
)
def test_xiaohongshu_session_endpoints_require_admin(admin_client, method, suffix):
    response = getattr(admin_client, method)(
        f"/api/v1/admin/platforms/xiaohongshu/{suffix}", headers={"X-Admin-Token": ""}
    )

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "ADMIN_UNAUTHORIZED"
