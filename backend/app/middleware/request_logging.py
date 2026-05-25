"""HTTP access logging — one line per API request on stdout (Render/Docker friendly)."""

import logging
import sys
import time
from typing import Callable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from app.config import settings

access_logger = logging.getLogger("trustbond.access")

# Paths that platforms poll constantly; skip to keep logs readable.
_QUIET_PATHS = frozenset({"/health", "/api/v1/health"})


def configure_app_logging() -> None:
    """Ensure app + uvicorn loggers stream to stdout with timestamps."""
    level = logging.DEBUG if settings.debug else logging.INFO
    root = logging.getLogger()
    if not root.handlers:
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(
            logging.Formatter(
                "%(asctime)s %(levelname)s [%(name)s] %(message)s",
                datefmt="%Y-%m-%d %H:%M:%S",
            )
        )
        root.addHandler(handler)
    root.setLevel(level)

    for name in ("uvicorn", "uvicorn.error", "uvicorn.access", "trustbond.access"):
        logging.getLogger(name).setLevel(level)


class RequestLogMiddleware(BaseHTTPMiddleware):
    """Log method, path, status, and duration for every HTTP request."""

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        if not getattr(settings, "request_access_log", True):
            return await call_next(request)

        path = request.url.path
        method = request.method
        quiet = path in _QUIET_PATHS and method in ("GET", "HEAD", "OPTIONS")
        start = time.perf_counter()

        try:
            response = await call_next(request)
        except Exception:
            elapsed_ms = (time.perf_counter() - start) * 1000
            if not quiet:
                access_logger.exception(
                    "%s %s -> ERROR (%.0fms)",
                    method,
                    path,
                    elapsed_ms,
                )
            raise

        elapsed_ms = (time.perf_counter() - start) * 1000
        if not quiet:
            client = request.client.host if request.client else "-"
            access_logger.info(
                '%s %s -> %s (%.0fms) client=%s',
                method,
                path,
                response.status_code,
                elapsed_ms,
                client,
            )
        return response
