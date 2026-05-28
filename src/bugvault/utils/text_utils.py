"""Text processing utilities: truncation, deduplication, sanitisation."""

from __future__ import annotations

from typing import ClassVar

from pydantic import BaseModel, Field


class StackTraceTruncator(BaseModel):
    """Configurable stack-trace truncation with three severity levels.

    Level 1 (default): Head 10 lines + project-relevant frames + tail 5 lines.
    Level 2 (detailed):  All lines matching known project package prefixes.
    Level 3 (raw):       Full stack trace — no truncation.
    """

    raw: str = Field(default="", max_length=65536, description="Original stack trace text")
    project_prefixes: list[str] = Field(
        default_factory=lambda: [
            "com.mycompany",
            "app.",
            "src.",
            "internal/",
            "pkg/",
        ],
        description="Package/module paths that identify first-party code",
    )

    _MAX_HEAD_LINES: ClassVar[int] = 10
    _MAX_TAIL_LINES: ClassVar[int] = 5
    _CONTEXT_WINDOW: ClassVar[int] = 2

    def truncate(self, level: int = 1) -> str:
        """Return a truncated representation at the requested verbosity level."""
        if not self.raw:
            return ""

        lines = self.raw.splitlines()

        if level >= 3 or len(lines) <= self._MAX_HEAD_LINES + self._MAX_TAIL_LINES + 2:
            return self.raw

        if level == 2:
            return self._truncate_detailed(lines)

        return self._truncate_default(lines)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _truncate_default(self, lines: list[str]) -> str:
        """Level 1: head + project frames + tail — no overlapping segments."""
        project_indices = [
            i for i, ln in enumerate(lines)
            if any(p in ln for p in self.project_prefixes)
        ]

        if not project_indices:
            kept = (
                lines[: self._MAX_HEAD_LINES]
                + ["... [truncated] ..."]
                + lines[-self._MAX_TAIL_LINES :]
            )
            return "\n".join(kept)

        # Project block: [ctx_start, ctx_end) (exclusive end)
        ctx_start = max(0, project_indices[0] - self._CONTEXT_WINDOW)
        ctx_end = min(len(lines), project_indices[-1] + self._CONTEXT_WINDOW + 1)

        # Head: lines before ctx_start, capped at MAX_HEAD_LINES
        head_end = min(ctx_start, self._MAX_HEAD_LINES)
        head = lines[:head_end]

        # Tail: lines after ctx_end, capped at MAX_TAIL_LINES
        tail_start = max(ctx_end, len(lines) - self._MAX_TAIL_LINES)
        tail = lines[tail_start:]

        # Build result — non-overlapping by construction
        kept: list[str] = list(head)
        if ctx_start > head_end:
            kept.append("... [frames omitted before project code] ...")
        kept.extend(lines[ctx_start:ctx_end])
        if tail_start > ctx_end:
            kept.append("... [frames omitted after project code] ...")
        kept.extend(tail)

        return "\n".join(kept)

    def _truncate_detailed(self, lines: list[str]) -> str:
        """Level 2: keep every first-party frame + 2 lines of context."""
        kept: list[str] = []
        in_project_block = False

        for i, ln in enumerate(lines):
            is_project = any(p in ln for p in self.project_prefixes)
            if is_project:
                if not in_project_block and i > 0:
                    kept.append("...")
                for ctx in range(max(0, i - self._CONTEXT_WINDOW), i):
                    kept.append(lines[ctx])
                kept.append(ln)
                for ctx in range(i + 1, min(len(lines), i + self._CONTEXT_WINDOW + 1)):
                    kept.append(lines[ctx])
                in_project_block = True
            elif in_project_block:
                kept.append("...")
                in_project_block = False

        return "\n".join(kept)


def truncate_text(text: str, max_chars: int = 2000) -> str:
    """Naive character-level truncation with an ellipsis marker."""
    if len(text) <= max_chars:
        return text
    return text[:max_chars] + "\n... [truncated] ..."
