"""ConventionRecord — the project-convention memory model for BugVault v2.

"Convention" = any rule the AI should follow when working on this project:
architecture conventions, business rules, test conventions, style guides,
or AI behavior constraints.

Shares the **same DB table** as BugRecord via ``record_type='convention'``
discriminator, reusing the same retrieval pipeline (chunk-level dual recall,
RRF fusion, Cross-Encoder reranking, RAG evaluation).
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Annotated

from pydantic import BaseModel, Field, model_validator


class ConventionRecord(BaseModel):
    """A structured record of a project convention the AI must follow.

    Only 4 fields are mandatory — these are the minimum required to
    make a convention useful for future retrieval:

        convention_name      — Short human-readable rule name.
        trigger_context      — When / where this convention applies.
        incorrect_behavior   — What the AI should NOT do (violation).
        correct_behavior     — What the AI SHOULD do (the rule).

    All other fields are optional and can be enriched asynchronously
    via multi-turn probing with the user.
    """

    # ── Mandatory fields ────────────────────────────────────────────
    convention_name: Annotated[
        str,
        Field(min_length=1, max_length=256, description="Short descriptive rule name"),
    ]
    trigger_context: Annotated[
        str,
        Field(
            min_length=1, max_length=32768,
            description="When / where this convention applies",
        ),
    ]
    incorrect_behavior: Annotated[
        str,
        Field(
            min_length=1, max_length=8192,
            description="What the AI should NOT do (violation example)",
        ),
    ]
    correct_behavior: Annotated[
        str,
        Field(
            min_length=1, max_length=16384,
            description="What the AI SHOULD do (the rule)",
        ),
    ]

    # ── Optional / async-enriched fields ────────────────────────────
    scope: Annotated[
        str | None,
        Field(
            max_length=256,
            description="Scope of applicability — e.g. 'src/repository/', 'tests/', 'Python'",
        ),
    ] = None
    tags: Annotated[
        str | None,
        Field(
            max_length=256,
            description="Categorisation tags — e.g. 'architecture, Java, DDD'",
        ),
    ] = None

    # ── System-managed metadata ─────────────────────────────────────
    record_id: Annotated[
        str | None,
        Field(
            default=None,
            description=(
                "MD5(convention_name + trigger_context) — "
                "globally unique dedup key"
            ),
        ),
    ]
    create_time: Annotated[
        str,
        Field(default_factory=lambda: datetime.now(timezone.utc).isoformat()),
    ]
    record_type: Annotated[
        str,
        Field(
            default="convention",
            description="Discriminator — always 'convention' for this model",
        ),
    ] = "convention"

    # ── Model validators ────────────────────────────────────────────

    @model_validator(mode="after")
    def _compute_record_id(self) -> "ConventionRecord":
        """Compute MD5(convention_name + trigger_context) as dedup key."""
        import hashlib

        raw = (self.convention_name + self.trigger_context).encode("utf-8")
        self.record_id = hashlib.md5(raw).hexdigest()
        return self

    # ── Public API ──────────────────────────────────────────────────

    def missing_required_fields(self) -> list[str]:
        """Return names of mandatory fields that are empty."""
        missing: list[str] = []
        for field in ("incorrect_behavior", "correct_behavior"):
            if not getattr(self, field, "").strip():
                missing.append(field)
        return missing

    def to_search_text(self) -> str:
        """Concatenate key fields into a single blob for embedding."""
        parts = [
            self.convention_name,
            self.trigger_context,
            self.incorrect_behavior,
            self.correct_behavior,
        ]
        return "\n".join(parts)

    def to_table_row(self) -> dict:
        """Map convention fields to the shared ``bug_records`` table columns.

        Field mapping (Convention → bug_records):
            convention_name   → bug_title
            trigger_context   → error_log_snippet
            incorrect_behavior → tried_methods
            correct_behavior  → final_solution
            scope             → project_name
            tags              → tech_stack
            root_cause        → "" (not applicable)

        Plus system fields: record_id, create_time, record_type='convention'.
        """
        return {
            "record_id": self.record_id or "",
            "bug_title": self.convention_name,
            "error_log_snippet": self.trigger_context,
            "tried_methods": self.incorrect_behavior,
            "final_solution": self.correct_behavior,
            "project_name": self.scope or "",
            "tech_stack": self.tags or "",
            "root_cause": "",
            "create_time": self.create_time,
            "search_text": self.to_search_text(),
            "record_type": "convention",
        }

    @classmethod
    def from_table_row(cls, row: dict) -> "ConventionRecord":
        """Build a ConventionRecord from a ``bug_records`` table row dict.

        The inverse of ``to_table_row()``: maps bug_records columns back
        to convention semantics when ``record_type='convention'``.
        """
        return cls(
            convention_name=row.get("bug_title", ""),
            trigger_context=row.get("error_log_snippet", ""),
            incorrect_behavior=row.get("tried_methods", ""),
            correct_behavior=row.get("final_solution", ""),
            scope=row.get("project_name") or None,
            tags=row.get("tech_stack") or None,
            record_id=row.get("record_id", ""),
            create_time=row.get("create_time", ""),
        )

    CHUNK_MAX_SIZE: int = 800  # max chars per chunk before recursive split

    def to_chunks(self, max_size: int | None = None) -> list[dict]:
        """Split this convention record into searchable chunks.

        - Chunk A (``context``): ``convention_name + trigger_context``
        - Chunk(s) B (``correct_behavior``): ``convention_name + incorrect + correct``
          → auto-split at paragraph boundary if exceeds ``max_size`` chars.

        Every chunk carries ``record_type='convention'`` for filtered retrieval.
        """
        import hashlib

        max_size = max_size or self.CHUNK_MAX_SIZE
        preamble = self.convention_name

        chunks: list[dict] = []

        def _add(ctype: str, text: str, idx: int = 0) -> None:
            raw = f"{preamble}\n{text}"
            cid = hashlib.md5(
                f"{self.record_id}_{ctype}_{idx}".encode(),
            ).hexdigest()
            chunks.append({
                "chunk_id": cid,
                "parent_id": self.record_id or "",
                "chunk_type": ctype,
                "search_text": raw,
                "tech_stack": self.tags or "",
                "project_name": self.scope or "",
                "record_type": "convention",
            })

        # ── Chunk A: context (always 1 chunk) ──────────────────
        _add("context", self.trigger_context)

        # ── Chunk(s) B: correct_behavior (recursive split) ────
        body = f"{self.incorrect_behavior}\n{self.correct_behavior}"

        if len(body) <= max_size:
            _add("correct_behavior", body)
        else:
            segments = _split_at_boundary(body, max_size)
            for idx, seg in enumerate(segments):
                _add("correct_behavior", seg, idx)

        return chunks


def _split_at_boundary(text: str, max_size: int) -> list[str]:
    """Split *text* into chunks ≤ *max_size* at paragraph (\\n\\n) boundaries.

    Falls back to line break (\\n) then character boundary if needed.
    """
    if len(text) <= max_size:
        return [text]

    # Try paragraph break first
    para_break = text.rfind("\n\n", 0, max_size)
    if para_break > max_size * 0.3:
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
