"""Structured logging configuration.

Production: one JSON line per record (Railway / Datadog / Loki ingest
this directly). Dev: a colored console formatter for local readability.

Stdlib `logging` and `structlog` share the same processor pipeline so
third-party libraries (uvicorn, sqlalchemy, apscheduler) end up in the
same JSON stream rather than printing un-tagged plain text. The
contextvars processor automatically pulls request_id / user_id from
the per-request middleware bindings.
"""

from __future__ import annotations

import logging
import sys

import structlog

from app.core.config import settings


def _resolve_format() -> str:
    """Resolve the LOG_FORMAT="auto" sentinel.

    Production gets JSON because Railway's log viewer + any downstream
    ingest expects it. Dev/test get pretty output because no human
    wants to read JSON in a terminal.
    """
    if settings.LOG_FORMAT != "auto":
        return settings.LOG_FORMAT
    return "json" if settings.ENVIRONMENT == "prod" else "pretty"


def configure_logging() -> None:
    """Idempotent — safe to call from app startup and from tests."""
    use_json = _resolve_format() == "json"

    timestamper = structlog.processors.TimeStamper(fmt="iso", utc=True)

    shared_processors: list = [
        # Surface request_id, user_id, etc. bound in the middleware.
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        timestamper,
        structlog.processors.StackInfoRenderer(),
        # Format `exc_info=True` into a string so the JSON renderer
        # can include it as a single field instead of dropping it.
        structlog.processors.format_exc_info,
    ]

    if use_json:
        # stdlib output → structlog → JSON. A single foreign-pre-chain so
        # logs from libraries like uvicorn / sqlalchemy match the shape
        # of logs we emit ourselves.
        formatter = structlog.stdlib.ProcessorFormatter(
            processors=[
                structlog.stdlib.ProcessorFormatter.remove_processors_meta,
                structlog.processors.JSONRenderer(),
            ],
            foreign_pre_chain=shared_processors,
        )
    else:
        formatter = structlog.stdlib.ProcessorFormatter(
            processors=[
                structlog.stdlib.ProcessorFormatter.remove_processors_meta,
                structlog.dev.ConsoleRenderer(colors=True),
            ],
            foreign_pre_chain=shared_processors,
        )

    # Defer the stream lookup so the handler always writes to the
    # *current* sys.stdout. pytest swaps sys.stdout at test setup; if
    # we capture the reference at configure time we end up writing to a
    # stale stream that pytest's capsys can't see.
    class _LiveStdoutHandler(logging.StreamHandler):
        @property
        def stream(self):
            return sys.stdout

        @stream.setter
        def stream(self, _value):
            pass

    handler = _LiveStdoutHandler()
    handler.setFormatter(formatter)

    root = logging.getLogger()
    # Replace existing handlers so re-config (tests, reload) doesn't
    # accumulate duplicates.
    root.handlers = [handler]
    root.setLevel(settings.LOG_LEVEL)

    # uvicorn ships its own handlers — let our pipeline own them too.
    for noisy in ("uvicorn", "uvicorn.access", "uvicorn.error"):
        logging.getLogger(noisy).handlers = []
        logging.getLogger(noisy).propagate = True

    structlog.configure(
        processors=[
            *shared_processors,
            # Hand off to the stdlib formatter that we just installed.
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        wrapper_class=structlog.stdlib.BoundLogger,
        logger_factory=structlog.stdlib.LoggerFactory(),
        # Caching breaks reconfig-in-tests: a logger built under pretty
        # mode would keep its old processor chain even after we flip to
        # json. The per-call overhead is negligible for our log volume.
        cache_logger_on_first_use=False,
    )


def get_logger(name: str | None = None) -> structlog.stdlib.BoundLogger:
    """Module-level shortcut so call sites don't import structlog directly."""
    return structlog.get_logger(name)
