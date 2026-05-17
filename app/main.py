import logging
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy.exc import IntegrityError
from starlette.types import Scope

from app.api.v1.router import api_router
from app.core.config import settings
from app.core.exceptions import AppError

logger = logging.getLogger("nanoboost.api")

# Uploaded files are content-hashed at write time (e.g. services3_d71e05544582.webp),
# so any change produces a new URL. That makes long-lived immutable caching safe.
_UPLOAD_CACHE_CONTROL = "public, max-age=31536000, immutable"


class CachedStaticFiles(StaticFiles):
    """StaticFiles with a long-lived immutable Cache-Control on 200s.

    Only successful responses get the header — 404s stay uncached so a
    fresh upload at the same path isn't masked by negative caching.
    """

    async def get_response(self, path: str, scope: Scope):
        response = await super().get_response(path, scope)
        if response.status_code == 200:
            response.headers["Cache-Control"] = _UPLOAD_CACHE_CONTROL
        return response


app = FastAPI(
    title="Nanoboost Admin API",
    version="1.0.0",
    description="REST API for Nanoboost public site and admin panel.",
    docs_url="/docs",
    redoc_url="/redoc",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


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
    CachedStaticFiles(directory=uploads_dir, check_dir=False),
    name="uploads",
)
