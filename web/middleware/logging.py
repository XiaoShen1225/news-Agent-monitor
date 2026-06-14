"""Request-ID middleware and trace context for structured logging.

Usage:
    from web.middleware.logging import trace_ctx, get_request_id, get_trace_id

    # Set trace_id for pipeline operations:
    trace_ctx.set(trace_id="coord_20260610...", request_id=None)

    # In any module:
    rid = get_request_id()  # current HTTP request ID or ""
    tid = get_trace_id()    # current pipeline trace ID or ""
"""

from __future__ import annotations

import contextvars
import logging
import uuid

from starlette.middleware.base import BaseHTTPMiddleware

# ── Context variables ────────────────────────────────────────────────
_request_id: contextvars.ContextVar[str] = contextvars.ContextVar(
    "request_id", default=""
)
_trace_id: contextvars.ContextVar[str] = contextvars.ContextVar("trace_id", default="")


class trace_ctx:
    """Bulk set/get context variables in a single call."""

    @staticmethod
    def set(*, trace_id: str = "", request_id: str = ""):
        if trace_id:
            _trace_id.set(trace_id)
        if request_id:
            _request_id.set(request_id)

    @staticmethod
    def get() -> dict[str, str]:
        rid = _request_id.get()
        tid = _trace_id.get()
        parts = {}
        if rid:
            parts["request_id"] = rid
        if tid:
            parts["trace_id"] = tid
        return parts


def get_request_id() -> str:
    return _request_id.get()


def get_trace_id() -> str:
    return _trace_id.get()


# ── Logging filter ────────────────────────────────────────────────────


class TraceFilter(logging.Filter):
    """Inject request_id / trace_id into every log record."""

    def filter(self, record):
        rid = _request_id.get()
        tid = _trace_id.get()
        if rid:
            record.request_id = rid
        else:
            record.request_id = ""
        if tid:
            record.trace_id = tid
        else:
            record.trace_id = ""
        return True


# ── Middleware ─────────────────────────────────────────────────────────


class RequestIDMiddleware(BaseHTTPMiddleware):
    """Generate and propagate a request ID for every HTTP request."""

    async def dispatch(self, request, call_next):
        rid = request.headers.get("X-Request-ID") or uuid.uuid4().hex[:12]
        _request_id.set(rid)
        response = await call_next(request)
        response.headers["X-Request-ID"] = rid
        return response


def install(app, *, json_format: bool = False):
    """Add RequestIDMiddleware and configure root logger with TraceFilter."""
    app.add_middleware(RequestIDMiddleware)

    root = logging.getLogger()
    # Remove existing handlers' filters to avoid duplicates on re-install
    trace_filter = TraceFilter()

    if json_format:
        # Simple JSON log format — structlog-free, zero deps
        _install_json(root, trace_filter)
    else:
        _install_text(root, trace_filter)


def _install_text(root, trace_filter):
    from logging import StreamHandler, Formatter

    for h in root.handlers:
        if isinstance(h, StreamHandler):
            h.addFilter(trace_filter)
            h.setFormatter(
                Formatter(
                    "[%(levelname)s] %(name)s%(request_id)s%(trace_id)s: %(message)s",
                    datefmt="%H:%M:%S",
                )
            )


def _install_json(root, trace_filter):
    """Minimal JSON log formatter — no extra dependencies."""
    import json as _json
    from logging import StreamHandler, Formatter

    class _JSONFormatter(Formatter):
        def format(self, record):
            obj = {
                "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S"),
                "level": record.levelname,
                "logger": record.name,
                "msg": record.getMessage(),
            }
            rid = getattr(record, "request_id", "") or ""
            tid = getattr(record, "trace_id", "") or ""
            if rid:
                obj["request_id"] = rid
            if tid:
                obj["trace_id"] = tid
            if record.exc_info and record.exc_info[1]:
                obj["error"] = str(record.exc_info[1])
            return _json.dumps(obj, ensure_ascii=False)

    for h in root.handlers:
        if isinstance(h, StreamHandler):
            h.addFilter(trace_filter)
            h.setFormatter(_JSONFormatter())
