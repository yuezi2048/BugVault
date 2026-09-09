"""Archive service — writes bug records as human-readable Markdown files.

Extracted from ``ingestion_svc`` to break the reverse dependency where
``database/lancedb_client.py`` was importing ``record_to_markdown``.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path

from bugvault.config import settings
from bugvault.models.bug_record import BugRecord
from bugvault.models.convention_record import ConventionRecord


def _clean_timestamp(ts: str) -> str:
    """Parse ISO-8601 timestamp and return a **valid ISO 8601** string.

    Strips microsecond precision and normalises the timezone to UTC so
    the output ``"2026-05-29T08:23:32+00:00"`` can be round-tripped
    through ``datetime.fromisoformat()``.

    Falls back to the raw string on parse failure.
    """
    try:
        dt = datetime.fromisoformat(ts)
        if dt.tzinfo is not None:
            dt = dt.astimezone(timezone.utc)
        return dt.strftime("%Y-%m-%dT%H:%M:%S+00:00")
    except (ValueError, TypeError):
        return ts


def _clean_tech_stack(tech_stack: str | None) -> list[str]:
    """Split *tech_stack* by comma (Chinese or English) into trimmed tags.

    Returns ``["bug"]`` when the input is empty / None.
    """
    if not tech_stack or not tech_stack.strip():
        return ["bug"]
    tags = [t.strip() for t in re.split(r"[，,]", tech_stack) if t.strip()]
    return tags if tags else ["bug"]


def _strip_llm_prefix(text: str, field_name: str) -> str:
    """Remove a leading ``field_name:`` prefix that an LLM may hallucinate.

    For example, ``"root_cause: The issue was..."`` becomes
    ``"The issue was..."`` (case-insensitive).
    """
    return re.sub(
        rf"^{re.escape(field_name)}\s*:\s*",
        "",
        text,
        flags=re.IGNORECASE,
    ).strip()


def record_to_markdown(record: BugRecord) -> str:
    """Serialize a bug record as a structured Markdown file with YAML frontmatter.

    The output is designed for Obsidian / Logseq compatibility:

    .. code-block:: markdown

       ---
       date: 2026-05-29T10:27:15+00:00
       project: BugVault
       tags:
         - Python 3.13
         - fastembed
       ---

       # Title
       ...
    """
    # ── Data cleaning ────────────────────────────────────────────────
    date_str = _clean_timestamp(record.create_time)
    project = record.project_name or "unknown"
    tags = _clean_tech_stack(record.tech_stack)
    solution = _strip_llm_prefix(record.final_solution, "final_solution")
    root_cause = _strip_llm_prefix(record.root_cause or "", "root_cause")

    # ── YAML frontmatter ─────────────────────────────────────────────
    frontmatter: list[str] = [
        "---",
        f"date: {date_str}",
        f"project: {project}",
        "tags:",
    ]
    for tag in tags:
        frontmatter.append(f"  - {tag}")
    frontmatter.append("---")

    # ── Markdown body ────────────────────────────────────────────────
    parts: list[str] = [
        "\n".join(frontmatter),
        "",
        f"# {record.bug_title}",
        "",
        "## 报错信息",
        "",
        f"```\n{record.error_log_snippet}\n```",
        "",
        "## 尝试过的方法",
        "",
        record.tried_methods,
        "",
        "## 最终解决方案",
        "",
        solution,
        "",
    ]
    if root_cause:
        parts.extend([
            "## 根因分析",
            "",
            root_cause,
            "",
        ])
    return "\n".join(parts)


def write_markdown_archive(record: BugRecord) -> Path:
    """Write a single bug record as a Markdown file under the archive directory.

    The filename is ``{datetime}-{sanitised-title}.md``.
    Returns the path of the written file.
    """
    archive_dir = Path(settings.markdown_archive_dir)
    archive_dir.mkdir(parents=True, exist_ok=True)

    # Build a safe filename
    safe_title = "".join(c if c.isalnum() or c in ("-", "_", " ") else "_" for c in record.bug_title)
    safe_title = safe_title.strip().replace(" ", "_")[:80]
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    filename = f"{ts}_{safe_title}.md"

    out_path = archive_dir / filename
    content = record_to_markdown(record)
    out_path.write_text(content, encoding="utf-8")
    return out_path


# ===================================================================
#  Convention archive — separate directory, different template
# ===================================================================

CONVENTION_ARCHIVE_SUBDIR = "conventions"


def convention_to_markdown(record: ConventionRecord) -> str:
    """Serialize a convention record as a structured Markdown file.

    Output format:

    .. code-block:: markdown

       ---
       date: 2026-06-08T10:00:00+00:00
       type: convention
       scope: src/repository/
       tags:
         - architecture
         - Java
       ---

       # Rule: DTO 转换规则

       ## 触发场景
       ...
    """
    date_str = _clean_timestamp(record.create_time)
    scope = record.scope or "(global)"
    tags = _clean_tech_stack(record.tags)

    # ── YAML frontmatter ─────────────────────────────────────────────
    frontmatter: list[str] = [
        "---",
        f"date: {date_str}",
        "type: convention",
        f"scope: {scope}",
        "tags:",
    ]
    for tag in tags:
        frontmatter.append(f"  - {tag}")
    frontmatter.append("---")

    # ── Markdown body ────────────────────────────────────────────────
    parts: list[str] = [
        "\n".join(frontmatter),
        "",
        f"# Rule: {record.convention_name}",
        "",
        "## 触发场景",
        "",
        record.trigger_context,
        "",
        "## 错误行为（不要做）",
        "",
        record.incorrect_behavior,
        "",
        "## 正确行为（应该做）",
        "",
        record.correct_behavior,
        "",
    ]

    return "\n".join(parts)


def write_convention_archive(record: ConventionRecord) -> Path:
    """Write a single convention record as a Markdown file.

    Stored under ``{archive_dir}/conventions/`` so bug and convention
    archives live in separate directories.
    """
    archive_dir = Path(settings.markdown_archive_dir) / CONVENTION_ARCHIVE_SUBDIR
    archive_dir.mkdir(parents=True, exist_ok=True)

    safe_name = "".join(c if c.isalnum() or c in ("-", "_", " ") else "_" for c in record.convention_name)
    safe_name = safe_name.strip().replace(" ", "_")[:80]
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    filename = f"{ts}_{safe_name}.md"

    out_path = archive_dir / filename
    content = convention_to_markdown(record)
    out_path.write_text(content, encoding="utf-8")
    return out_path


# ===================================================================
#  Archive reader
# ===================================================================

ArchiveRecord = BugRecord | ConventionRecord

_FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)
_TITLE_RE = re.compile(r"^#\s+(.+)$", re.MULTILINE)
_SECTION_RE = re.compile(r"^##\s+(.+?)$\n(.*?)(?=^##|\Z)", re.MULTILINE | re.DOTALL)


def read_archive_record(path: str | Path) -> ArchiveRecord | None:
    """Read one Archive file into its complete typed domain record.

    Missing ``type`` frontmatter remains a Bug Record for compatibility with
    existing archives.  Invalid files return ``None`` so maintenance can keep
    rebuilding the remaining Index projections.
    """
    archive_path = Path(path)
    try:
        text = archive_path.read_text(encoding="utf-8")
    except Exception:
        from bugvault.utils.logger import logger

        logger.exception("Cannot read %s", archive_path)
        return None

    frontmatter, body = _split_archive_document(text, archive_path)
    record_type = frontmatter.get("type", "bug")
    if record_type == "convention":
        return _read_convention_record(frontmatter, body, archive_path)
    if record_type != "bug":
        from bugvault.utils.logger import logger

        logger.warning("Unsupported archive record type %r in %s", record_type, archive_path.name)
        return None
    return _read_bug_record(frontmatter, body, archive_path)


def _split_archive_document(text: str, path: Path) -> tuple[dict, str]:
    match = _FRONTMATTER_RE.search(text)
    if not match:
        return {}, text
    try:
        return _parse_frontmatter(match.group(1)), text[match.end():]
    except Exception:
        from bugvault.utils.logger import logger

        logger.warning("YAML parse warning for %s (will use defaults)", path.name)
        return {}, text[match.end():]


def _parse_frontmatter(text: str) -> dict:
    """Parse the Archive's small YAML subset without a runtime dependency."""
    frontmatter: dict[str, object] = {}
    current_list: list[str] | None = None
    for line in text.splitlines():
        if line.startswith("  - ") and current_list is not None:
            current_list.append(line[4:].strip())
            continue
        key, separator, value = line.partition(":")
        if not separator:
            continue
        key = key.strip()
        value = value.strip()
        if value:
            frontmatter[key] = value.strip('"')
            current_list = None
        else:
            current_list = []
            frontmatter[key] = current_list
    return frontmatter


def _archive_title(body: str, path: Path, prefix: str = "") -> str:
    match = _TITLE_RE.search(body)
    title = match.group(1).strip() if match else ""
    if prefix:
        title = re.sub(rf"^{re.escape(prefix)}\s*", "", title, flags=re.IGNORECASE).strip()
    return title or path.stem.replace("_", " ")


def _archive_sections(body: str) -> dict[str, str]:
    return {
        match.group(1).strip(): match.group(2).strip()
        for match in _SECTION_RE.finditer(body)
    }


def _section(sections: dict[str, str], *aliases: str) -> str:
    return next((sections[alias] for alias in aliases if alias in sections), "")


def _archive_tags(frontmatter: dict) -> str:
    tags = frontmatter.get("tags", [])
    if isinstance(tags, list):
        return ", ".join(str(tag) for tag in tags if tag)
    return tags if isinstance(tags, str) else ""


def _read_bug_record(frontmatter: dict, body: str, path: Path) -> BugRecord | None:
    sections = _archive_sections(body)
    try:
        return BugRecord(
            bug_title=_archive_title(body, path) or "(untitled)",
            error_log_snippet=re.sub(
                r"^```[a-zA-Z]*\n|```$", "",
                _section(sections, "报错信息", "Error", "错误信息").strip(),
            ) or "(no error log)",
            tried_methods=_section(sections, "尝试过的方法", "Tried", "尝试的方法") or "(empty)",
            final_solution=_section(sections, "最终解决方案", "Solution", "解决方案") or "(empty)",
            project_name=str(frontmatter.get("project", "")) or None,
            tech_stack=_archive_tags(frontmatter) or None,
            root_cause=_section(sections, "根因分析", "Root Cause", "根因") or None,
            create_time=str(frontmatter.get("date", "")),
        )
    except Exception:
        from bugvault.utils.logger import logger

        logger.exception("BugRecord validation failed for %s", path.name)
        return None


def _read_convention_record(frontmatter: dict, body: str, path: Path) -> ConventionRecord | None:
    sections = _archive_sections(body)
    try:
        return ConventionRecord(
            convention_name=_archive_title(body, path, "Rule:") or "(untitled)",
            trigger_context=_section(sections, "触发场景", "Trigger Context") or "(no context)",
            incorrect_behavior=_section(
                sections, "错误行为（不要做）", "错误行为", "Incorrect Behavior"
            ) or "(empty)",
            correct_behavior=_section(
                sections, "正确行为（应该做）", "正确行为", "Correct Behavior"
            ) or "(empty)",
            scope=str(frontmatter.get("scope", "")) or None,
            tags=_archive_tags(frontmatter) or None,
            create_time=str(frontmatter.get("date", "")),
        )
    except Exception:
        from bugvault.utils.logger import logger

        logger.exception("ConventionRecord validation failed for %s", path.name)
        return None
