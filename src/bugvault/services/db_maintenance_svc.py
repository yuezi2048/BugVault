"""Database maintenance — clear + batch rebuild from Markdown archive.

Provides two internal utility methods:

- ``clear_database(client)`` — drop & recreate the LanceDB table.
- ``import_from_archive(client, embedding_svc, archive_path)`` —
  concurrently parse all ``.md`` files in *archive_path*, generate
  embeddings, and batch-upsert into LanceDB.

These are **not** MCP tools — they are intended for one-shot
maintenance scripts (see ``scripts/rebuild_index.py``).
"""

from __future__ import annotations

import concurrent.futures
import re
from pathlib import Path

import yaml

from bugvault.database.lancedb_client import LanceDBClient
from bugvault.models.bug_record import BugRecord
from bugvault.services.embedding_svc import EmbeddingService
from bugvault.utils.logger import logger


# ═══════════════════════════════════════════════════════════════════
#  Public API
# ═══════════════════════════════════════════════════════════════════


def clear_database(client: LanceDBClient) -> None:
    """Drop the existing table and re-create an empty one."""
    client.drop_table()
    logger.info("Database cleared — fresh empty table ready")


def import_from_archive(
    client: LanceDBClient,
    embedding_svc: EmbeddingService,
    archive_path: str | Path,
    max_workers: int = 8,
) -> dict:
    """Concurrently parse all ``.md`` files, embed, and batch-upsert.

    Args:
        client: Initialised LanceDBClient.
        embedding_svc: Shared EmbeddingService instance.
        archive_path: Directory containing ``.md`` files.
        max_workers: Thread count for concurrent parsing + embedding.

    Returns:
        {total, succeeded, failed, elapsed_sec}
    """
    archive_dir = Path(archive_path).expanduser().resolve()
    if not archive_dir.is_dir():
        raise NotADirectoryError(f"Archive path not found: {archive_dir}")

    md_files = sorted(archive_dir.glob("*.md"))
    total = len(md_files)
    logger.info("Found %d markdown files in %s", total, archive_dir)

    if total == 0:
        return {"total": 0, "succeeded": 0, "failed": 0, "elapsed_sec": 0.0}

    import time
    t0 = time.perf_counter()

    # ── Step A: Concurrent parse + embed ─────────────────────────
    batch_data: list[dict] = []
    failed: int = 0

    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {
            pool.submit(_parse_and_embed, path, embedding_svc): path
            for path in md_files
        }
        for future in concurrent.futures.as_completed(futures):
            path = futures[future]
            try:
                data_dict = future.result()
                if data_dict is not None:
                    batch_data.append(data_dict)
                else:
                    failed += 1
            except Exception:
                logger.exception("Unexpected error processing %s", path)
                failed += 1

    # ── Step B: Batch upsert ─────────────────────────────────────
    if not batch_data:
        logger.warning("No valid records parsed — nothing to import")
        return {
            "total": total, "succeeded": 0,
            "failed": failed, "elapsed_sec": time.perf_counter() - t0,
        }

    logger.info(
        "Inserting %d records into LanceDB in a single batch …",
        len(batch_data),
    )
    client._table.merge_insert("record_id") \
        .when_matched_update_all() \
        .when_not_matched_insert_all() \
        .execute(batch_data)  # type: ignore[arg-type]

    elapsed = time.perf_counter() - t0
    logger.info(
        "Rebuild complete: %d succeeded, %d failed, %.1f sec",
        len(batch_data), failed, elapsed,
    )
    return {
        "total": total,
        "succeeded": len(batch_data),
        "failed": failed,
        "elapsed_sec": round(elapsed, 2),
    }


# ═══════════════════════════════════════════════════════════════════
#  Internal: parse + embed single file (runs in executor thread)
# ═══════════════════════════════════════════════════════════════════


def _parse_and_embed(
    path: Path,
    embedding_svc: EmbeddingService,
) -> dict | None:
    """Parse a single ``.md`` into a LanceDB row dict (with vector).

    Returns ``None`` on parse failure (already logged).
    """
    record = _parse_markdown_to_record(path)
    if record is None:
        return None

    search_text = record.to_search_text()
    try:
        embedding = embedding_svc.generate_embedding(search_text)
    except Exception:
        logger.exception("Embedding failed for %s", path.name)
        return None

    return {
        "vector": embedding,
        "record_id": record.record_id or "",
        "bug_title": record.bug_title,
        "error_log_snippet": record.error_log_snippet,
        "tried_methods": record.tried_methods,
        "final_solution": record.final_solution,
        "project_name": record.project_name or "",
        "tech_stack": record.tech_stack or "",
        "root_cause": record.root_cause or "",
        "create_time": record.create_time,
        "search_text": search_text,
    }


# ═══════════════════════════════════════════════════════════════════
#  Markdown → BugRecord parser
# ═══════════════════════════════════════════════════════════════════


_FRONTMATTER_RE = re.compile(
    r"^---\s*\n(.*?)\n---\s*\n",
    re.DOTALL,
)
_TITLE_RE = re.compile(
    r"^#\s+(.+)$",
    re.MULTILINE,
)
_SECTION_RE = re.compile(
    r"^##\s+(.+?)$\n(.*?)(?=^##|\Z)",
    re.MULTILINE | re.DOTALL,
)


def _parse_markdown_to_record(path: Path) -> BugRecord | None:
    """Parse a BugVault markdown archive file into a BugRecord.

    Handles:
    - ``# [Bug] Title`` or ``# Title``
    - YAML frontmatter with ``date``, ``project``, ``tags``
    - Sections ``## 报错信息``, ``## 尝试过的方法``,
      ``## 最终解决方案``, ``## 根因分析``
    - Missing sections → empty string (never crashes)
    """
    try:
        text = path.read_text(encoding="utf-8")
    except Exception:
        logger.exception("Cannot read %s", path)
        return None

    # ── Extract YAML frontmatter ─────────────────────────────────
    fm_match = _FRONTMATTER_RE.search(text)
    frontmatter: dict = {}
    if fm_match:
        try:
            frontmatter = yaml.safe_load(fm_match.group(1)) or {}
        except Exception:
            logger.warning("YAML parse warning for %s (will use defaults)", path.name)

    body = text[fm_match.end():] if fm_match else text

    # ── Extract title (first ``#`` heading) ──────────────────────
    title_match = _TITLE_RE.search(body)
    bug_title = ""
    if title_match:
        bug_title = title_match.group(1).strip()
    if not bug_title:
        logger.warning("No title found in %s, using filename", path.name)
        bug_title = path.stem.replace("_", " ")

    # ── Extract sections ─────────────────────────────────────────
    sections: dict[str, str] = {}
    for m in _SECTION_RE.finditer(body):
        heading = m.group(1).strip()
        content = m.group(2).strip()
        sections[heading] = content

    def _get_section(*aliases: str) -> str:
        for alias in aliases:
            if alias in sections:
                return sections[alias]
        return ""

    error_snippet = _get_section("报错信息", "Error", "错误信息")
    tried = _get_section("尝试过的方法", "Tried", "尝试的方法")
    solution = _get_section("最终解决方案", "Solution", "解决方案")
    root_cause = _get_section("根因分析", "Root Cause", "根因")

    # ── Strip code fences from error snippet ─────────────────────
    error_snippet = re.sub(r"^```[a-zA-Z]*\n|```$", "", error_snippet.strip())

    # ── Build tech_stack from tags ───────────────────────────────
    tags = frontmatter.get("tags", [])
    if isinstance(tags, list):
        tech_stack = ", ".join(str(t) for t in tags if t)
    elif isinstance(tags, str):
        tech_stack = tags
    else:
        tech_stack = ""

    # ── Add missing fields marker so validate_and_prepare doesn't block ─
    if not tried:
        tried = "(empty)"
    if not solution:
        solution = "(empty)"

    try:
        record = BugRecord(
            bug_title=bug_title or "(untitled)",
            error_log_snippet=error_snippet or "(no error log)",
            tried_methods=tried,
            final_solution=solution,
            project_name=str(frontmatter.get("project", "")) or None,
            tech_stack=tech_stack or None,
            root_cause=root_cause or None,
            create_time=str(frontmatter.get("date", "")),
        )
        return record
    except Exception:
        logger.exception("BugRecord validation failed for %s", path.name)
        return None
