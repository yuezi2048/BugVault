"""Structured error codes for AI operation classification.

Implements guardrail #7 (模型错误码分类):
区分限流、超时、鉴权、内容安全、JSON 失败、内部错误。
"""

from __future__ import annotations

from enum import Enum


class ErrorCode(str, Enum):
    """Machine-readable error code for every AI operation outcome."""

    # ── Success ────────────────────────────────────────────────────
    OK = "ok"

    # ── Client / request errors ───────────────────────────────────
    RATE_LIMITED = "rate_limited"        # 限流 — too many requests
    TIMEOUT = "timeout"                  # 超时 — LLM or DB timeout
    AUTH_FAIL = "auth_fail"              # 鉴权 — API key invalid / expired
    CONTENT_SAFETY = "content_safety"    # 内容安全 — flagged by moderation

    # ── Processing errors ─────────────────────────────────────────
    PARSE_ERROR = "parse_error"          # JSON 解析失败
    VALIDATION_ERROR = "validation_error"  # 输入校验不通过
    INTERNAL = "internal"                # 内部错误 — catch-all

    # ── Resource errors ───────────────────────────────────────────
    NOT_FOUND = "not_found"              # 检索无结果
    QUOTA_EXCEEDED = "quota_exceeded"    # 配额耗尽（claim-level eval）

    def __str__(self) -> str:
        return self.value
