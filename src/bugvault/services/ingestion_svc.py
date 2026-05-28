"""Ingestion service — handles validation, probing, and persistence of bug records."""

from __future__ import annotations

import json

from bugvault.config import settings
from bugvault.models.bug_record import BugRecord


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
    """Serialize a bug record as a human-readable markdown snippet for archiving."""
    parts = [
        f"# {record.bug_title}",
        "",
        f"- **时间**: {record.create_time}",
        f"- **项目**: {record.project_name or '(未指定)'}",
        f"- **技术栈**: {record.tech_stack or '(未指定)'}",
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
        record.final_solution,
        "",
    ]
    if record.root_cause:
        parts.extend([
            "## 根因分析",
            "",
            record.root_cause,
            "",
        ])
    return "\n".join(parts)
