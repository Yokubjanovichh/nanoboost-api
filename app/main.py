import logging
import mimetypes
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy.exc import IntegrityError

from app.api.v1.router import api_router
from app.core.config import settings
from app.core.exceptions import AppError
from app.shared import scheduler as scheduler_module

logger = logging.getLogger("nanoboost.api")


@asynccontextmanager
async def lifespan(_app: FastAPI):
    scheduler_module.start()
    try:
        yield
    finally:
        scheduler_module.shutdown()


# Register image MIME types explicitly. Starlette's FileResponse defers to
# `mimetypes.guess_type`, and on slim Linux containers (Railway uses
# python:slim) `.webp` isn't always registered, so it falls back to
# `text/plain`. Registering up-front guarantees correct Content-Type.
for ext, mime in (
    (".webp", "image/webp"),
    (".jpg", "image/jpeg"),
    (".jpeg", "image/jpeg"),
    (".png", "image/png"),
    (".gif", "image/gif"),
    (".svg", "image/svg+xml"),
):
    mimetypes.add_type(mime, ext)

# Uploaded files are content-hashed at write time (e.g. services3_d71e05544582.webp),
# so any change produces a new URL. That makes long-lived immutable caching safe.
_UPLOAD_CACHE_CONTROL = "public, max-age=31536000, immutable"

# Industry-baseline security headers applied to every response. Values picked
# to match the storefront's Vercel defaults so the API and the public site
# present a uniform posture to scanners.
_SECURITY_HEADERS = {
    "Strict-Transport-Security": "max-age=31536000; includeSubDomains",
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "strict-origin-when-cross-origin",
    "Permissions-Policy": "geolocation=(), microphone=(), camera=(), payment=()",
}


app = FastAPI(
    title="Nanoboost Admin API",
    version="1.0.0",
    description="REST API for Nanoboost public site and admin panel.",
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def uploads_cache_headers(request: Request, call_next):
    """Long-lived immutable Cache-Control for the /uploads/* mount.

    Acts on the outgoing response so headers are set after StaticFiles is
    done — the previous `get_response` override silently lost the header
    in some Starlette paths. Scoped to 200s; 404s stay uncached so a
    fresh upload at the same path isn't masked by negative caching.
    """
    response = await call_next(request)
    if response.status_code == 200 and request.url.path.startswith(
        settings.UPLOADS_URL_PREFIX + "/"
    ):
        response.headers["Cache-Control"] = _UPLOAD_CACHE_CONTROL
    return response


@app.middleware("http")
async def security_headers(request: Request, call_next):
    """Stamp baseline security headers on every outgoing response."""
    response = await call_next(request)
    for name, value in _SECURITY_HEADERS.items():
        response.headers[name] = value
    return response


@app.exception_handler(AppError)
async def app_error_handler(_: Request, exc: AppError) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": exc.detail},
        headers=exc.headers or {},
    )


@app.exception_handler(IntegrityError)
async def integrity_error_handler(_: Request, exc: IntegrityError) -> JSONResponse:
    msg = str(exc.orig) if exc.orig else "Resource is referenced by other records"
    return JSONResponse(
        status_code=409,
        content={"detail": "Database integrity error", "message": msg[:200]},
    )


@app.exception_handler(Exception)
async def unhandled_exception_handler(_: Request, exc: Exception) -> JSONResponse:
    if isinstance(exc, HTTPException):
        return JSONResponse(
            status_code=exc.status_code,
            content={"detail": exc.detail},
            headers=exc.headers or {},
        )
    logger.exception("Unhandled exception", exc_info=exc)
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error"},
    )


@app.get("/health", tags=["health"])
async def health() -> dict[str, str]:
    return {"status": "ok"}


app.include_router(api_router)

uploads_dir = Path(settings.UPLOADS_DIR)
uploads_dir.mkdir(parents=True, exist_ok=True)
app.mount(
    settings.UPLOADS_URL_PREFIX,
    StaticFiles(directory=uploads_dir, check_dir=False),
    name="uploads",
)
