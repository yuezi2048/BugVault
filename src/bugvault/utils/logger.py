"""Logger with traceId support for end-to-end request tracing.

Implements guardrail #5 (traceId):
Every log line from a single tool invocation shares the same ``trace_id``,
making it possible to correlate log entries across services.

Usage
-----
    from bugvault.utils.logger import logger, get_trace_id, set_trace_id

    # At tool entry:
    trace_id = set_trace_id()          # generates UUID, sets context var
    logger.info("Tool invoked")        # → [2026-07-13 10:30:00] bugvault INFO [a1b2c3d4] Tool invoked

    # In downstream services:
    from bugvault.utils.logger import logger, get_trace_id
    tid = get_trace_id()               # → "a1b2c3d4"  (same trace)
    logger.info("DB query done")       # → same trace_id in log line
"""

from __future__ import annotations

import logging
import sys
import uuid
from contextvars import ContextVar

# ── Context variable for the current request's trace ID ────────────
_trace_id_var: ContextVar[str] = ContextVar("trace_id", default="")


def set_trace_id() -> str:
    """Generate a new short trace ID and set it on the current context.

    Returns the generated trace ID.
    """
    tid = uuid.uuid4().hex[:12]  # 12-char hex, e.g. "a1b2c3d4e5f6"
    _trace_id_var.set(tid)
    return tid


def get_trace_id() -> str:
    """Return the current trace ID, or ``""`` if none is set."""
    return _trace_id_var.get()


# ── Custom log filter that injects trace_id into each record ───────


class TraceIdFilter(logging.Filter):
    """Injects ``trace_id`` into every log record's ``trace_id`` attribute.

    Usage::

        handler.addFilter(TraceIdFilter())
        formatter = logging.Formatter(
            "[%(asctime)s] %(name)s %(levelname)s [%(trace_id)s] %(message)s",
            ...
        )
    """

    def filter(self, record: logging.LogRecord) -> bool:
        record.trace_id = get_trace_id() or "-"
        return True


# ── Logger setup ──────────────────────────────────────────────────


def setup_logger(name: str = "bugvault", level: int = logging.INFO) -> logging.Logger:
    """Return a logger that writes to stderr only — never stdout.

    Includes ``trace_id`` in every log line when a trace context is active.
    """
    logger = logging.getLogger(name)
    logger.setLevel(level)

    if not logger.handlers:
        handler = logging.StreamHandler(stream=sys.stderr)
        handler.setFormatter(logging.Formatter(
            "[%(asctime)s] %(name)s %(levelname)s [%(trace_id)s] %(message)s",
            datefmt="%H:%M:%S",
        ))
        handler.addFilter(TraceIdFilter())
        logger.addHandler(handler)

    # Prevent log propagation to the root logger, which may have
    # handlers attached to stdout by third-party libraries.
    logger.propagate = False

    return logger


logger = setup_logger()
