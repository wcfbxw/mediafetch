import logging
import secrets
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import ORJSONResponse

from app.api import admin, convenience, downloads, health, inspect, jobs, platform_sessions
from app.core.config import get_settings
from app.core.errors import AppError, error
from app.core.logging import RequestIdAdapter, configure_logging, redact_path
from app.core.redis import close_redis_clients

settings = get_settings()
configure_logging(settings.log_level)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    settings.ensure_storage()
    yield
    await close_redis_clients()


app = FastAPI(
    title="MediaFetch API",
    version="1.2.0",
    docs_url="/api/docs" if settings.app_env != "production" else None,
    redoc_url=None,
    default_response_class=ORJSONResponse,
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_credentials=False,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Accept", "Content-Type", "X-Request-ID", "X-Admin-Token"],
    expose_headers=["Content-Disposition", "X-Request-ID"],
)


@app.middleware("http")
async def request_context(request: Request, call_next):
    request_id = request.headers.get("x-request-id") or secrets.token_hex(12)
    request_id = "".join(char for char in request_id if char.isalnum() or char in "-_")[:64]
    request.state.request_id = request_id
    started = time.monotonic()
    adapter = RequestIdAdapter(logger, {"request_id": request_id})
    try:
        response = await call_next(request)
    except Exception:
        adapter.exception("Unhandled request error path=%s", request.url.path)
        app_error = error("INTERNAL_ERROR")
        response = ORJSONResponse(
            status_code=app_error.status_code,
            content={
                "error": {
                    "code": app_error.code,
                    "message": app_error.message,
                    "request_id": request_id,
                }
            },
        )
    response.headers["X-Request-ID"] = request_id
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "no-referrer"
    adapter.info(
        "request method=%s path=%s status=%s duration_ms=%d",
        request.method,
        redact_path(request.url.path),
        response.status_code,
        (time.monotonic() - started) * 1000,
    )
    return response


@app.exception_handler(AppError)
async def app_error_handler(request: Request, exc: AppError) -> ORJSONResponse:
    request_id = getattr(request.state, "request_id", secrets.token_hex(12))
    headers = {}
    if exc.code == "RATE_LIMITED" and exc.details:
        headers["Retry-After"] = str(exc.details.get("retry_after", 60))
    return ORJSONResponse(
        status_code=exc.status_code,
        headers=headers,
        content={
            "error": {
                "code": exc.code,
                "message": exc.message,
                "request_id": request_id,
            }
        },
    )


@app.exception_handler(RequestValidationError)
async def validation_error_handler(
    request: Request, _exc: RequestValidationError
) -> ORJSONResponse:
    request_id = getattr(request.state, "request_id", secrets.token_hex(12))
    return ORJSONResponse(
        status_code=400,
        content={
            "error": {
                "code": "INVALID_URL",
                "message": "请求参数无效",
                "request_id": request_id,
            }
        },
    )


for router in (
    health.router,
    inspect.router,
    convenience.router,
    downloads.router,
    jobs.router,
    admin.router,
    platform_sessions.router,
):
    app.include_router(router, prefix=settings.api_prefix)
