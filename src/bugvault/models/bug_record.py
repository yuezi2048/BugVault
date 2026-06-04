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

    def to_chunks(self) -> list[dict]:
        """Split this bug record into searchable chunks (small-to-big RAG).

        Returns a list of dicts ready for ``bugvault_chunks`` table::

            [
                {"chunk_id": "<md5>_err", "parent_id": "<record_id>",
                 "chunk_type": "error", "search_text": "...",
                 "tech_stack": "...", "project_name": "..."},
                {"chunk_id": "<md5>_sol", "parent_id": "<record_id>",
                 "chunk_type": "solution", "search_text": "...",
                 "tech_stack": "...", "project_name": "..."},
            ]
        """
        import hashlib
        rid = self.record_id or hashlib.md5(self.bug_title.encode()).hexdigest()

        chunks: list[dict] = [
            {
                "chunk_id": f"{rid}_err",
                "parent_id": rid,
                "chunk_type": "error",
                "search_text": f"{self.bug_title}\n{self.error_log_snippet}",
                "tech_stack": self.tech_stack or "",
                "project_name": self.project_name or "",
            },
            {
                "chunk_id": f"{rid}_sol",
                "parent_id": rid,
                "chunk_type": "solution",
                "search_text": (
                    f"{self.bug_title}\n{self.tried_methods}\n{self.final_solution}"
                    + (f"\n{self.root_cause}" if self.root_cause else "")
                ),
                "tech_stack": self.tech_stack or "",
                "project_name": self.project_name or "",
            },
        ]
        return chunks

    def to_search_text(self) -> str:
        """Concatenate key fields into a single blob for embedding."""
        parts = [self.bug_title, self.error_log_snippet, self.tried_methods, self.final_solution]
        if self.root_cause:
            parts.append(self.root_cause)
        return "\n".join(parts)

    def to_chunks(self) -> list[dict]:
        """Generate two focused text chunks for parent-child vector retrieval.

        Chunk A (``error_log`` type):
            ``bug_title + "\\n" + error_log_snippet``
            → for exact-error matching.

        Chunk B (``semantic`` type):
            ``bug_title + "\\n" + tried_methods + "\\n" + final_solution``
            → for semantic-similarity matching (same-class problems).

        Returns a list of dicts, each with:
            chunk_id, parent_id (self.record_id), chunk_type, search_text.
        """
        import hashlib

        chunks: list[dict] = []

        # ── Chunk A: error_log ──────────────────────────────────────
        error_text = f"{self.bug_title}\n{self.error_log_snippet}"
        error_chunk_id = hashlib.md5(
            f"{self.record_id}_error_log".encode()
        ).hexdigest()
        chunks.append({
            "chunk_id": error_chunk_id,
            "parent_id": self.record_id or "",
            "chunk_type": "error_log",
            "search_text": error_text,
        })

        # ── Chunk B: semantic ───────────────────────────────────────
        semantic_text = f"{self.bug_title}\n{self.tried_methods}\n{self.final_solution}"
        semantic_chunk_id = hashlib.md5(
            f"{self.record_id}_semantic".encode()
        ).hexdigest()
        chunks.append({
            "chunk_id": semantic_chunk_id,
            "parent_id": self.record_id or "",
            "chunk_type": "semantic",
            "search_text": semantic_text,
        })

        return chunks
