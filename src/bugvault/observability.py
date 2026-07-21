"""Structured AI operation logging for observability and audit.

Implements guardrail #6 (AI 调用日志):
Records every AI operation with event_type, tool_name, duration, status, error_code.

Implements guardrail #12 (token 成本记录):
Estimates monetary cost from token usage using known model pricing.

Output is written as JSONL to ``{data_root}/log/ai_call.jsonl`` — one
line per AI operation (tool entry OR tool exit).
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from bugvault.config import settings
from bugvault.models.error_code import ErrorCode
from bugvault.utils.logger import logger, get_trace_id

# ═══════════════════════════════════════════════════════════════════
#  Model pricing table (USD per 1M tokens)
#  ── source: current OpenAI / Anthropic / OpenRouter public pricing
# ═══════════════════════════════════════════════════════════════════

_MODEL_PRICING: dict[str, tuple[float, float]] = {
    # OpenAI
    "gpt-4o": (2.50, 10.00),
    "gpt-4o-mini": (0.15, 0.60),
    "gpt-4o-2024-08-06": (2.50, 10.00),
    "gpt-4o-mini-2024-07-18": (0.15, 0.60),
    "gpt-4-turbo": (10.00, 30.00),
    "gpt-3.5-turbo": (0.50, 1.50),
    # Anthropic
    "claude-sonnet-4-20250514": (3.00, 15.00),
    "claude-3-haiku-20240307": (0.25, 1.25),
    "claude-3-sonnet-20240229": (3.00, 15.00),
    "claude-opus-4-20250514": (15.00, 75.00),
    # DeepSeek
    "deepseek-chat": (0.27, 1.10),
    "deepseek-v4-pro": (0.435, 0.87),
    # Qwen
    "qwen3-coder": (0.45, 1.80),
    "qwen3-32b": (0.50, 1.50),
    # Default fallback (conservative estimate)
    "__default__": (2.00, 8.00),
}


def estimate_cost(model: str, prompt_tokens: int, completion_tokens: int) -> float:
    """Estimate USD cost for a single LLM call.

    Args:
        model: Model identifier (e.g. ``"gpt-4o-mini"``).
        prompt_tokens: Number of input tokens.
        completion_tokens: Number of output tokens.

    Returns:
        Estimated cost in USD, rounded to 6 decimal places.
    """
    input_rate, output_rate = _MODEL_PRICING.get(
        model, _MODEL_PRICING["__default__"]
    )
    cost = (prompt_tokens / 1_000_000 * input_rate) + (
        completion_tokens / 1_000_000 * output_rate
    )
    return round(cost, 6)


# ═══════════════════════════════════════════════════════════════════
#  Structured log entry
# ═══════════════════════════════════════════════════════════════════


class AiCallLogEntry:
    """A single structured AI operation log record."""

    __slots__ = (
        "timestamp", "trace_id", "event_type", "tool_name",
        "duration_ms", "status", "error_code", "error_message",
        "model", "prompt_tokens", "completion_tokens", "total_tokens",
        "estimated_cost_usd", "metadata",
    )

    def __init__(  # noqa: PLR0913  (many fields is the point)
        self,
        event_type: str,        # "entry" | "exit"
        tool_name: str,
        status: str = "ok",     # "ok" | "error"
        error_code: str = "",
        error_message: str = "",
        duration_ms: float = 0.0,
        model: str = "",
        prompt_tokens: int = 0,
        completion_tokens: int = 0,
        total_tokens: int = 0,
        estimated_cost_usd: float = 0.0,
        metadata: dict | None = None,
    ) -> None:
        self.timestamp = datetime.now(timezone.utc).isoformat()
        self.trace_id = get_trace_id() or "-"
        self.event_type = event_type
        self.tool_name = tool_name
        self.duration_ms = duration_ms
        self.status = status
        self.error_code = error_code
        self.error_message = error_message
        self.model = model
        self.prompt_tokens = prompt_tokens
        self.completion_tokens = completion_tokens
        self.total_tokens = total_tokens
        self.estimated_cost_usd = estimated_cost_usd
        self.metadata = metadata or {}

    def to_dict(self) -> dict:
        return {s: getattr(self, s) for s in self.__slots__}


# ═══════════════════════════════════════════════════════════════════
#  JSONL persistence
# ═══════════════════════════════════════════════════════════════════


def _get_log_path() -> Path:
    log_dir = Path(settings.data_root) / "log"
    log_dir.mkdir(parents=True, exist_ok=True)
    return log_dir / "ai_call.jsonl"


def append_ai_call_log(entry: AiCallLogEntry) -> None:
    """Append one structured log entry to ``ai_call.jsonl``."""
    try:
        path = _get_log_path()
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry.to_dict(), ensure_ascii=False) + "\n")
    except OSError:
        logger.exception("Failed to write ai_call log to %s", path)


# ═══════════════════════════════════════════════════════════════════
#  Decorator for tool-level entry/exit logging
# ═══════════════════════════════════════════════════════════════════


def log_tool_call(func):
    """Decorator that wraps an async MCP tool handler with structured logging.

    Usage::

        @log_tool_call
        async def handle_retrieve(args, ...):
            ...
    """
    import functools
    import time

    @functools.wraps(func)
    async def wrapper(*args, **kwargs):
        # ── Entry log ─────────────────────────────────────────────
        tool_name = func.__name__
        entry_log = AiCallLogEntry(
            event_type="entry",
            tool_name=tool_name,
        )
        append_ai_call_log(entry_log)
        logger.info("Tool start: %s", tool_name)

        start = time.monotonic()
        try:
            result = await func(*args, **kwargs)
            duration = (time.monotonic() - start) * 1000

            # ── Exit log (success) ────────────────────────────────
            exit_log = AiCallLogEntry(
                event_type="exit",
                tool_name=tool_name,
                status="ok",
                error_code="ok",
                duration_ms=round(duration, 2),
            )
            append_ai_call_log(exit_log)
            logger.info(
                "Tool done: %s (%.0f ms)",
                tool_name, duration,
            )
            return result

        except Exception as exc:
            duration = (time.monotonic() - start) * 1000

            # ── Exit log (error) ──────────────────────────────────
            exit_log = AiCallLogEntry(
                event_type="exit",
                tool_name=tool_name,
                status="error",
                error_code=_classify_error(exc),
                error_message=str(exc)[:500],
                duration_ms=round(duration, 2),
            )
            append_ai_call_log(exit_log)
            logger.exception(
                "Tool error: %s (%.0f ms)",
                tool_name, duration,
            )
            raise

    return wrapper


# ═══════════════════════════════════════════════════════════════════
#  Error classification helper
# ═══════════════════════════════════════════════════════════════════


def _classify_error(exc: Exception) -> str:
    """Map an exception to an ``ErrorCode`` value.

    Uses exception type and message heuristics.
    """
    msg = str(exc).lower()

    if "rate limit" in msg or "too many requests" in msg:
        return ErrorCode.RATE_LIMITED
    if "timeout" in msg or "timed out" in msg:
        return ErrorCode.TIMEOUT
    if "auth" in msg or "unauthorized" in msg or "api key" in msg:
        return ErrorCode.AUTH_FAIL
    if "content" in msg and ("safety" in msg or "flagged" in msg):
        return ErrorCode.CONTENT_SAFETY
    if "parse" in msg or "json" in msg or "decode" in msg:
        return ErrorCode.PARSE_ERROR

    return ErrorCode.INTERNAL
