"""Reflection service — manages bug-prevention rules written to CLAUDE.md.

This service allows the Agent to persist preventive rules back to the
project's CLAUDE.md file, creating a feedback loop where the Agent
learns from past mistakes and avoids repeating them.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from bugvault.config import settings
from bugvault.utils.logger import logger


class ReflectionService:
    """Read / append prevention rules under ``## Bug Prevention Rules`` in CLAUDE.md.

    The file location is resolved from ``settings`` (defaults to
    ``~/.bugvault/CLAUDE.md``).  Rules are appended with a numbered
    entry, timestamp, category tag, and the reflection text.
    """

    SECTION_HEADER = "## Bug Prevention Rules"

    def __init__(self, claude_md_path: str | Path | None = None) -> None:
        """If *claude_md_path* is ``None``, default to ``~/.bugvault/CLAUDE.md``."""
        if claude_md_path:
            self._path = Path(claude_md_path)
        else:
            self._path = Path.home() / ".bugvault" / "CLAUDE.md"

    @property
    def path(self) -> Path:
        return self._path

    # ── public API ──────────────────────────────────────────────────

    def add_preventive_rule(
        self,
        reflection_text: str,
        error_category: str,
        preventive_rule: str,
    ) -> dict:
        """Append one prevention rule to CLAUDE.md and return metadata.

        Returns
        -------
        dict
            ``{"rule_number": int, "error_category": str,
               "total_rules": int, "created_at": str}``
        """
        # 1. Ensure parent dir and file exist
        self._path.parent.mkdir(parents=True, exist_ok=True)
        if not self._path.exists():
            self._path.write_text(
                "# BugVault\n\nProject-level memory for BugVault MCP server.\n",
                encoding="utf-8",
            )

        # 2. Read current content
        content = self._path.read_text(encoding="utf-8")

        # 3. Count existing rules under section
        existing_count = self._count_rules(content)

        # 4. Build new entry
        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S+00:00")
        new_number = existing_count + 1

        new_entry = (
            f"- **Rule #{new_number}** [{error_category}] ({now})\n"
            f"  - **Analysis**: {reflection_text}\n"
            f"  - **Prevention**: {preventive_rule}\n"
        )

        # 5. Append or create section
        content = self._append_to_section(content, new_entry)

        # 6. Write back
        self._path.write_text(content, encoding="utf-8")

        logger.info(
            "Wrote prevention rule #%s (%s) to %s",
            new_number, error_category, self._path,
        )

        return {
            "rule_number": new_number,
            "error_category": error_category,
            "total_rules": existing_count + 1,
            "created_at": now,
        }

    # ── internal helpers ────────────────────────────────────────────

    @staticmethod
    def _count_rules(content: str) -> int:
        """Count existing ``- **Rule #N**`` entries under the section."""
        in_section = False
        count = 0
        for line in content.splitlines():
            stripped = line.strip()
            if stripped == ReflectionService.SECTION_HEADER:
                in_section = True
                continue
            if in_section:
                if stripped.startswith("## "):
                    break  # next section → stop counting
                if stripped.startswith("- **Rule #"):
                    count += 1
        return count

    @staticmethod
    def _append_to_section(content: str, new_entry: str) -> str:
        """Insert *new_entry* at the end of the section, creating it if needed."""
        header = ReflectionService.SECTION_HEADER
        if header not in content:
            return f"{content}\n\n{header}\n\n{new_entry}"

        lines = content.splitlines()

        # Find section header index
        header_idx: int | None = None
        for i, line in enumerate(lines):
            if line.strip() == header:
                header_idx = i
                break

        if header_idx is None:
            return content  # shouldn't happen

        # Find end of section (next ## or end-of-file)
        section_end = len(lines)
        for i in range(header_idx + 1, len(lines)):
            if lines[i].strip().startswith("## "):
                section_end = i
                break

        # Insert before the blank line that precedes the next section (if any)
        insert_pos = section_end
        # Walk backwards from section_end to find where to insert
        # (skip trailing blank lines within the section so new_entry lands cleanly)
        while insert_pos > header_idx + 1 and not lines[insert_pos - 1].strip():
            insert_pos -= 1

        # Add a blank line before new_entry if we're appending after existing content
        if insert_pos > header_idx + 1 and lines[insert_pos - 1].strip():
            new_entry = "\n" + new_entry

        lines.insert(insert_pos, new_entry)
        return "\n".join(lines)