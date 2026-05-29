"""Ingestion service — handles validation, probing, and persistence of bug records."""

from __future__ import annotations

import re
from datetime import datetime, timezone

from bugvault.models.bug_record import BugRecord


def _clean_timestamp(ts: str) -> str:
    """Parse ISO-8601 timestamp and return 'YYYY-MM-DD HH:MM:SS UTC'.

    Strips microsecond precision and normalises the timezone to UTC.
    Falls back to the raw string on parse failure.
    """
    try:
        dt = datetime.fromisoformat(ts)
        if dt.tzinfo is not None:
            dt = dt.astimezone(timezone.utc)
        return dt.strftime("%Y-%m-%d %H:%M:%S") + " UTC"
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


def validate_and_prepare(record: BugRecord) -> list[str]:
    """Validate a BugRecord and return a list of missing fields.

    If no fields are missing, the record is ready for embedding + storage.
    """
    return record.missing_required_fields()


def suggest_probe_questions(missing_fields: list[str]) -> str:
    """Return a structured prompt for Claude to probe missing information."""
    probe_map: dict[str, list[str]] = {
        "tried_methods": [
            "针对这个报错，你尝试过哪些解决方法？结果如何？",
            "是否尝试过重启/回滚版本/清除缓存等常规操作？",
        ],
        "final_solution": [
            "最终是怎么解决这个 Bug 的？用了什么具体的代码或配置变更？",
            "修复这个 Bug 的关键步骤是什么？",
        ],
        "root_cause": [
            "你判断这个 Bug 的根本原因是什么？",
            "是代码逻辑问题、配置错误还是外部依赖异常？",
        ],
        "project_name": [
            "这个 Bug 出现在哪个项目或服务中？",
        ],
        "tech_stack": [
            "涉及哪些技术栈（语言、框架、中间件）？",
        ],
    }

    suggestions: list[str] = []
    for field in missing_fields:
        questions = probe_map.get(field, ["请补充更多上下文信息"])
        suggestions.extend(questions)

    return "\n".join(
        f"- {q}" for q in suggestions[:3]  # max 3 questions per turn
    )


def record_to_markdown(record: BugRecord) -> str:
    """Serialize a bug record as a structured Markdown file with YAML frontmatter.

    The output is designed for Obsidian / Logseq compatibility:

    .. code-block:: markdown

       ---
       date: 2026-05-29 10:27:15 UTC
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
