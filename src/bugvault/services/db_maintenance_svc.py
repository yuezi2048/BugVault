"""Database maintenance — rebuild Index projections from the Archive."""

from __future__ import annotations

import concurrent.futures
import time
from pathlib import Path
from typing import TYPE_CHECKING

from bugvault.models.bug_record import BugRecord
from bugvault.models.convention_record import ConventionRecord
from bugvault.services.archive_svc import read_archive_record
from bugvault.services.embedding_svc import EmbeddingService
from bugvault.services.persistence_svc import RecordPersistence
from bugvault.utils.logger import logger

if TYPE_CHECKING:
    from bugvault.database.lancedb_client import LanceDBClient


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
    """Read Archive records, embed them, and batch-upsert their Index projections."""
    archive_dir = Path(archive_path).expanduser().resolve()
    if not archive_dir.is_dir():
        raise NotADirectoryError(f"Archive path not found: {archive_dir}")

    archive_files = sorted(archive_dir.glob("*.md"))
    if include_conventions:
        convention_dir = archive_dir / "conventions"
        if convention_dir.is_dir():
            archive_files += sorted(convention_dir.glob("*.md"))
    total = len(archive_files)
    logger.info("Found %d markdown files in %s", total, archive_dir)
    if total == 0:
        return {"total": 0, "succeeded": 0, "failed": 0, "elapsed_sec": 0.0}

    started_at = time.perf_counter()
    parent_rows: list[dict] = []
    chunk_rows: list[dict] = []
    failed = 0
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {
            pool.submit(_parse_and_embed, path, embedding_svc): path
            for path in archive_files
        }
        for future in concurrent.futures.as_completed(futures):
            path = futures[future]
            try:
                result = future.result()
                if result is None:
                    failed += 1
                    continue
                parent_row, record_chunks = result
                parent_rows.append(parent_row)
                chunk_rows.extend(record_chunks)
            except Exception:
                logger.exception("Unexpected error processing %s", path)
                failed += 1

    if not parent_rows:
        logger.warning("No valid records parsed — nothing to import")
        return {
            "total": total,
            "succeeded": 0,
            "failed": failed,
            "elapsed_sec": time.perf_counter() - started_at,
        }

    client._table.merge_insert("record_id") \
        .when_matched_update_all() \
        .when_not_matched_insert_all() \
        .execute(_deduplicate(parent_rows, "record_id"))  # type: ignore[arg-type]

    if chunk_rows:
        client._chunks_table.merge_insert("chunk_id") \
            .when_matched_update_all() \
            .when_not_matched_insert_all() \
            .execute(_deduplicate(chunk_rows, "chunk_id"))  # type: ignore[arg-type]

    client.create_fts_index(replace=True)
    client.create_chunks_fts_index(replace=True)
    elapsed = time.perf_counter() - started_at
    logger.info("Rebuild complete: %d succeeded, %d failed, %.1f sec", len(parent_rows), failed, elapsed)
    return {
        "total": total,
        "succeeded": len(parent_rows),
        "failed": failed,
        "elapsed_sec": round(elapsed, 2),
    }


def _deduplicate(rows: list[dict], key: str) -> list[dict]:
    seen: set[str] = set()
    deduplicated: list[dict] = []
    for row in rows:
        value = row.get(key, "")
        if value in seen:
            continue
        seen.add(value)
        deduplicated.append(row)
    return deduplicated


def _parse_and_embed(
    path: Path,
    embedding_svc: EmbeddingService,
) -> tuple[dict, list[dict]] | None:
    """Embed one complete Archive record using the persistence module."""
    record = read_archive_record(path)
    if record is None:
        return None
    try:
        embedded = RecordPersistence(embedding_svc=embedding_svc).embed(record)
    except Exception:
        logger.exception("Record embedding failed for %s", path.name)
        return None
    return embedded.table_row, embedded.chunk_rows


# Compatibility shims for existing maintenance callers. Archive owns parsing.
def _detect_record_type(path: Path) -> str:
    record = read_archive_record(path)
    return "convention" if isinstance(record, ConventionRecord) else "bug"


def _parse_markdown_to_record(path: Path) -> BugRecord | None:
    record = read_archive_record(path)
    return record if isinstance(record, BugRecord) else None


def _parse_markdown_to_convention_record(path: Path) -> ConventionRecord | None:
    record = read_archive_record(path)
    return record if isinstance(record, ConventionRecord) else None
