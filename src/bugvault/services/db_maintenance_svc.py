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
from bugvault.models.convention_record import ConventionRecord
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
    include_conventions: bool = True,
) -> dict:
    """Concurrently parse all ``.md`` files, embed, and batch-upsert.

    Automatically detects bug vs convention record type from YAML
    frontmatter ``type`` field.

    Args:
        client: Initialised LanceDBClient.
        embedding_svc: Shared EmbeddingService instance.
        archive_path: Directory containing ``.md`` files.
        max_workers: Thread count for concurrent parsing + embedding.
        include_conventions: When True, also scans ``{archive_path}/conventions/``.

    Returns:
        {total, succeeded, failed, elapsed_sec}
    """
    archive_dir = Path(archive_path).expanduser().resolve()
    if not archive_dir.is_dir():
        raise NotADirectoryError(f"Archive path not found: {archive_dir}")

    md_files = sorted(archive_dir.glob("*.md"))
    # ── Also scan conventions subdirectory ───────────────────────
    if include_conventions:
        conv_dir = archive_dir / "conventions"
        if conv_dir.is_dir():
            md_files += sorted(conv_dir.glob("*.md"))
            logger.info("Including %d files from conventions subdirectory", len(md_files))
    total = len(md_files)
    logger.info("Found %d markdown files in %s", total, archive_dir)

    if total == 0:
        return {"total": 0, "succeeded": 0, "failed": 0, "elapsed_sec": 0.0}

    import time
    t0 = time.perf_counter()

    # ── Step A: Concurrent parse + embed ─────────────────────────
    batch_data: list[dict] = []
    batch_chunks: list[dict] = []
    failed: int = 0

    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {
            pool.submit(_parse_and_embed, path, embedding_svc): path
            for path in md_files
        }
        for future in concurrent.futures.as_completed(futures):
            path = futures[future]
            try:
                result = future.result()
                if result is not None:
                    parent_dict, chunk_rows = result
                    batch_data.append(parent_dict)
                    batch_chunks.extend(chunk_rows)
                else:
                    failed += 1
            except Exception:
                logger.exception("Unexpected error processing %s", path)
                failed += 1

    # ── Step B: Batch upsert (parent records) ───────────────────
    if not batch_data:
        logger.warning("No valid records parsed — nothing to import")
        return {
            "total": total, "succeeded": 0,
            "failed": failed, "elapsed_sec": time.perf_counter() - t0,
        }

    logger.info(
        "Inserting %d parent records into LanceDB …",
        len(batch_data),
    )
    # ── Dedup by record_id before batch insert ─────────────────
    # merge_insert fails if multiple source rows match the same target
    seen_rid: set[str] = set()
    deduped_batch: list[dict] = []
    for row in batch_data:
        rid = row.get("record_id", "")
        if rid in seen_rid:
            continue
        seen_rid.add(rid)
        deduped_batch.append(row)

    client._table.merge_insert("record_id") \
        .when_matched_update_all() \
        .when_not_matched_insert_all() \
        .execute(deduped_batch)  # type: ignore[arg-type]

    # ── Step C: Batch upsert (chunks) ─────────────────────────────
    if batch_chunks:
        logger.info(
            "Inserting %d chunks into bugvault_chunks …",
            len(batch_chunks),
        )
        # Dedup by chunk_id
        seen_cid: set[str] = set()
        deduped_chunks: list[dict] = []
        for row in batch_chunks:
            cid = row.get("chunk_id", "")
            if cid in seen_cid:
                continue
            seen_cid.add(cid)
            deduped_chunks.append(row)

        client._chunks_table.merge_insert("chunk_id") \
            .when_matched_update_all() \
            .when_not_matched_insert_all() \
            .execute(deduped_chunks)  # type: ignore[arg-type]

    # ── Rebuild FTS indices after bulk load ──────────────────────
    client.create_fts_index(replace=True)
    client.create_chunks_fts_index(replace=True)

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


def _detect_record_type(path: Path) -> str:
    """Read the YAML frontmatter ``type`` field to determine bug vs convention."""
    try:
        text = path.read_text(encoding="utf-8")
        fm_match = _FRONTMATTER_RE.search(text)
        if fm_match:
            import yaml
            fm = yaml.safe_load(fm_match.group(1)) or {}
            return fm.get("type", "bug")
    except Exception:
        pass
    return "bug"


def _parse_and_embed(
    path: Path,
    embedding_svc: EmbeddingService,
) -> tuple[dict, list[dict]] | None:
    """Parse a single ``.md`` into a parent row dict + list of chunk row dicts.

    Automatically detects bug vs convention format from YAML frontmatter
    and routes to the appropriate parser.

    Returns ``(parent_dict, [chunk_dict, ...])`` on success, or ``None``
    on parse / embedding failure (already logged).
    """
    record_type = _detect_record_type(path)

    if record_type == "convention":
        return _parse_and_embed_convention(path, embedding_svc)

    # ── Bug record path (default) ────────────────────────────────
    record = _parse_markdown_to_record(path)
    if record is None:
        return None

    search_text = record.to_search_text()
    try:
        full_embedding = embedding_svc.generate_embedding(search_text)
    except Exception:
        logger.exception("Full-text embedding failed for %s", path.name)
        return None

    parent_dict = {
        "vector": full_embedding,
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
        "record_type": "bug",
    }

    chunk_defs = record.to_chunks()
    chunk_rows = _embed_chunks(chunk_defs, embedding_svc, path)
    return parent_dict, chunk_rows


def _parse_and_embed_convention(
    path: Path,
    embedding_svc: EmbeddingService,
) -> tuple[dict, list[dict]] | None:
    """Parse a convention ``.md`` file into a parent dict + chunk rows."""
    record = _parse_markdown_to_convention_record(path)
    if record is None:
        return None

    search_text = record.to_search_text()
    try:
        full_embedding = embedding_svc.generate_embedding(search_text)
    except Exception:
        logger.exception("Convention full-text embedding failed for %s", path.name)
        return None

    table_row = record.to_table_row()
    parent_dict = {
        "vector": full_embedding,
        **table_row,
        "search_text": search_text,
    }

    chunk_defs = record.to_chunks()
    chunk_rows = _embed_chunks(chunk_defs, embedding_svc, path)
    return parent_dict, chunk_rows


def _embed_chunks(
    chunk_defs: list[dict],
    embedding_svc: EmbeddingService,
    path: Path,
) -> list[dict]:
    """Generate embeddings for chunk definitions and return chunk rows.

    Each row includes fields from the chunk def (tech_stack, project_name,
    record_type) — the caller is responsible for ensuring these are set.
    """
    chunk_rows: list[dict] = []
    for cd in chunk_defs:
        try:
            chunk_emb = embedding_svc.generate_embedding(cd["search_text"])
        except Exception:
            logger.exception("Chunk embedding failed for %s", path.name)
            continue
        chunk_rows.append({
            "vector": chunk_emb,
            "chunk_id": cd["chunk_id"],
            "parent_id": cd["parent_id"],
            "chunk_type": cd["chunk_type"],
            "search_text": cd["search_text"],
            "tech_stack": cd.get("tech_stack", ""),
            "project_name": cd.get("project_name", ""),
            "record_type": cd.get("record_type", "bug"),
        })
    return chunk_rows


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


def _parse_markdown_to_convention_record(path: Path) -> ConventionRecord | None:
    """Parse a convention markdown archive file into a ConventionRecord.

    Handles the format produced by ``archive_svc.convention_to_markdown()``:

    .. code-block:: yaml
       ---
       date: ...
       type: convention
       scope: src/repository/
       tags:
         - architecture
       ---
       # Rule: ...

       ## 触发场景

       ## 错误行为（不要做）

       ## 正确行为（应该做）
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

    # ── Extract title (``# Rule: Name`` or ``# Name``) ──────────
    title_match = _TITLE_RE.search(body)
    convention_name = ""
    if title_match:
        raw = title_match.group(1).strip()
        # Strip leading "Rule:" prefix
        convention_name = re.sub(r"^Rule:\s*", "", raw, flags=re.IGNORECASE).strip()
    if not convention_name:
        logger.warning("No title found in %s, using filename", path.name)
        convention_name = path.stem.replace("_", " ")

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

    trigger_context = _get_section("触发场景", "Trigger Context")
    incorrect = _get_section("错误行为（不要做）", "错误行为", "Incorrect Behavior")
    correct = _get_section("正确行为（应该做）", "正确行为", "Correct Behavior")

    # ── Build tags from frontmatter ──────────────────────────────
    tags = frontmatter.get("tags", [])
    if isinstance(tags, list):
        tags_str = ", ".join(str(t) for t in tags if t)
    elif isinstance(tags, str):
        tags_str = tags
    else:
        tags_str = ""
    scope = frontmatter.get("scope", "")

    if not incorrect:
        incorrect = "(empty)"
    if not correct:
        correct = "(empty)"

    try:
        record = ConventionRecord(
            convention_name=convention_name or "(untitled)",
            trigger_context=trigger_context or "(no context)",
            incorrect_behavior=incorrect,
            correct_behavior=correct,
            scope=str(scope) or None,
            tags=tags_str or None,
            create_time=str(frontmatter.get("date", "")),
        )
        return record
    except Exception:
        logger.exception("ConventionRecord validation failed for %s", path.name)
        return None
