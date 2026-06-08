"""BugRecord — the core data model for the entire BugVault system.

This Pydantic model serves as the single source of truth / contract
across all layers: MCP tools, services, and LanceDB persistence.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Annotated

from pydantic import BaseModel, Field, field_validator, model_validator


class BugRecord(BaseModel):
    """A structured record of a bug-troubleshooting experience.

    Only 4 fields are mandatory — these are the minimum required to
    make a record useful for future retrieval:

        bug_title          — Short human-readable label.
        error_log_snippet  — Key error message / stack trace excerpt.
        tried_methods      — What was attempted (even if it failed).
        final_solution     — What actually fixed the problem.

    All other fields are optional and can be enriched asynchronously
    via multi-turn probing with the user.
    """

    # ── Mandatory fields ────────────────────────────────────────────
    bug_title: Annotated[
        str,
        Field(min_length=1, max_length=256, description="Short descriptive title"),
    ]
    error_log_snippet: Annotated[
        str,
        Field(min_length=1, max_length=32768, description="Error message or stack trace"),
    ]
    tried_methods: Annotated[
        str,
        Field(min_length=1, max_length=8192, description="Methods already attempted"),
    ]
    final_solution: Annotated[
        str,
        Field(min_length=1, max_length=16384, description="The working fix"),
    ]

    # ── Optional / async-enriched fields ────────────────────────────
    project_name: Annotated[
        str | None,
        Field(max_length=128, description="Affected project or service"),
    ] = None
    tech_stack: Annotated[
        str | None,
        Field(max_length=256, description="Relevant technology tags"),
    ] = None
    root_cause: Annotated[
        str | None,
        Field(max_length=4096, description="Root cause analysis"),
    ] = None

    # ── System-managed metadata ─────────────────────────────────────
    record_id: Annotated[
        str | None,
        Field(
            default=None,
            description="MD5(bug_title + error_log_snippet) — globally unique dedup key",
        ),
    ]
    create_time: Annotated[
        str,
        Field(default_factory=lambda: datetime.now(timezone.utc).isoformat()),
    ]

    # ── Internal: probe round tracking ──────────────────────────────
    _probe_rounds: int = 0
    MAX_PROBE_ROUNDS: int = 3

    # ── Validators ──────────────────────────────────────────────────

    @field_validator("error_log_snippet")
    @classmethod
    def _sanitise_snippet(cls, v: str) -> str:
        # Strip ANSI escape codes that may be present in terminal output
        import re as _re
        cleaned = _re.sub(r"\x1b\[[0-9;]*[a-zA-Z]", "", v)
        return cleaned.strip()

    # ── Model validators ────────────────────────────────────────────

    @model_validator(mode="after")
    def _compute_record_id(self) -> "BugRecord":
        """Compute MD5(bug_title + error_log_snippet) as the global dedup key."""
        import hashlib

        raw = (self.bug_title + self.error_log_snippet).encode("utf-8")
        self.record_id = hashlib.md5(raw).hexdigest()
        return self

    # ── Public API ──────────────────────────────────────────────────

    def probe_round_exhausted(self) -> bool:
        return self._probe_rounds >= self.MAX_PROBE_ROUNDS

    def increment_probe(self) -> None:
        self._probe_rounds += 1

    def missing_required_fields(self) -> list[str]:
        """Return names of mandatory fields that are empty."""
        missing: list[str] = []
        for field in ("tried_methods", "final_solution"):
            if not getattr(self, field, "").strip():
                missing.append(field)
        return missing

    def to_search_text(self) -> str:
        """Concatenate key fields into a single blob for embedding."""
        parts = [self.bug_title, self.error_log_snippet, self.tried_methods, self.final_solution]
        if self.root_cause:
            parts.append(self.root_cause)
        return "\n".join(parts)

    CHUNK_MAX_SIZE: int = 800  # max chars per chunk before recursive split

    def to_chunks(self, max_size: int | None = None) -> list[dict]:
        """Split this bug record into searchable chunks (small-to-big RAG).

        - Chunk A (``error_log``): ``bug_title + error_log_snippet``
        - Chunk(s) B (``semantic``): ``bug_title + tried + solution``
          → auto-split at paragraph boundary if exceeds ``max_size`` chars.

        Every chunk carries full ``bug_title`` header for context.
        """
        import hashlib

        max_size = max_size or self.CHUNK_MAX_SIZE
        preamble = self.bug_title

        chunks: list[dict] = []

        def _add(ctype: str, text: str, idx: int = 0) -> None:
            raw = f"{preamble}\n{text}"
            cid = hashlib.md5(f"{self.record_id}_{ctype}_{idx}".encode()).hexdigest()
            chunks.append({
                "chunk_id": cid,
                "parent_id": self.record_id or "",
                "chunk_type": ctype,
                "search_text": raw,
                "tech_stack": self.tech_stack or "",
                "project_name": self.project_name or "",
            })

        # ── Chunk A: error_log (always 1 chunk) ─────────────────
        _add("error_log", self.error_log_snippet)

        # ── Chunk(s) B: semantic (recursive split if too long) ──
        body = f"{self.tried_methods}\n{self.final_solution}"
        if self.root_cause:
            body += f"\n{self.root_cause}"

        if len(body) <= max_size:
            _add("semantic", body)
        else:
            # Recursive split at paragraph boundary (\n\n)
            segments = _split_at_boundary(body, max_size)
            for idx, seg in enumerate(segments):
                _add("semantic", seg, idx)

        return chunks


def _split_at_boundary(text: str, max_size: int) -> list[str]:
    """Split *text* into chunks ≤ *max_size* at paragraph (\\n\\n) boundaries.

    Falls back to sentence boundary (\\n) then character boundary if needed.
    """
    if len(text) <= max_size:
        return [text]

    # Try paragraph break first
    para_break = text.rfind("\n\n", 0, max_size)
    if para_break > max_size * 0.3:  # meaningful split point
        head = text[:para_break]
        tail = text[para_break + 2:]
        return [head] + _split_at_boundary(tail, max_size)

    # Fallback: line break
    line_break = text.rfind("\n", 0, max_size)
    if line_break > max_size * 0.3:
        head = text[:line_break]
        tail = text[line_break + 1:]
        return [head] + _split_at_boundary(tail, max_size)

    # Last resort: hard character split
    return [text[:max_size]] + _split_at_boundary(text[max_size:], max_size)
