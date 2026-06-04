#!/usr/bin/env python3
"""Bulk import bug records from external datasets (Stack Overflow, GitHub Issues, CSV, Parquet).

Usage
-----
    # Stack Overflow Parquet (from ClickHouse dataset)
    uv run python scripts/import_external.py \
        --format parquet \
        --input stackoverflow_posts.parquet \
        --map-title Title \
        --map-error Body \
        --map-solution AcceptedAnswerBody \
        --map-tags Tags \
        --map-time CreationDate \
        --tech-stack-prefix "python" \
        --limit 100000

    # GitHub Issues JSON (from gh CLI)
    uv run python scripts/import_external.py \
        --format json \
        --input cpython_bugs.json \
        --map-title title \
        --map-error body \
        --map-solution comments \
        --map-tags labels \
        --map-project repository \
        --limit 50000

    # CSV with custom columns
    uv run python scripts/import_external.py \
        --format csv \
        --input my_bugs.csv \
        --map-title bug_title \
        --map-error error_log \
        --map-solution fix \
        --map-methods tried \
        --limit 10000

Environment
-----------
All ``BUGVAULT_*`` env vars are honoured (data_root, embedding model, etc.).
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

from bugvault.utils.stdout_guard import _MCPStdoutProxy  # noqa: F401

from bugvault.config import settings
from bugvault.database.lancedb_client import LanceDBClient
from bugvault.models.bug_record import BugRecord
from bugvault.services.embedding_svc import EmbeddingService
from bugvault.utils.logger import logger


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Bulk import bug records from external datasets into BugVault",
    )
    parser.add_argument("--format", required=True, choices=["parquet", "json", "csv"],
                        help="Input file format")
    parser.add_argument("--input", required=True,
                        help="Path to input file")
    parser.add_argument("--limit", type=int, default=0,
                        help="Max records to import (0 = all)")

    # Column mapping
    parser.add_argument("--map-title", required=True,
                        help="Column/field name for bug_title")
    parser.add_argument("--map-error", required=True,
                        help="Column/field name for error_log_snippet")
    parser.add_argument("--map-solution", required=True,
                        help="Column/field name for final_solution")
    parser.add_argument("--map-methods", default="",
                        help="Column/field name for tried_methods (optional)")
    parser.add_argument("--map-tags", default="",
                        help="Column/field name for tech_stack (optional)")
    parser.add_argument("--map-project", default="",
                        help="Column/field name for project_name (optional)")
    parser.add_argument("--map-time", default="",
                        help="Column/field name for create_time (optional)")
    parser.add_argument("--map-root-cause", default="",
                        help="Column/field name for root_cause (optional)")

    # Filters
    parser.add_argument("--tech-stack-prefix", default="",
                        help="Only import records where tech_stack contains this (case-insensitive)")
    parser.add_argument("--min-score", type=float, default=0,
                        help="Minimum score threshold (for datasets with a Score column)")

    args = parser.parse_args()

    # ── Init ───────────────────────────────────────────────────────
    print("=" * 60)
    print("  BugVault — External Dataset Import")
    print("=" * 60)
    print(f"  File:   {args.input}")
    print(f"  Format: {args.format}")
    print(f"  Limit:  {'all' if args.limit == 0 else args.limit}")
    print()

    t_start = time.perf_counter()

    print("  ⏳ Initialising LanceDB client …")
    client = LanceDBClient()
    client.initialize()

    print("  ⏳ Loading embedding model …")
    embedding_svc = EmbeddingService()

    # ── Read data ─────────────────────────────────────────────────
    print(f"  📖 Reading {args.format} file …")
    rows = _read_file(args.format, args.input, args.limit)
    print(f"     Found {len(rows)} records")

    # ── Apply filters ─────────────────────────────────────────────
    if args.tech_stack_prefix:
        _filter_by_tech_stack(rows, args.tech_stack_prefix, args.map_tags)
        print(f"     After tech_stack filter: {len(rows)} records")

    # ── Parse & embed ─────────────────────────────────────────────
    print("  🧠 Generating embeddings …")
    t_embed = time.perf_counter()

    batch_data: list[dict] = []
    failed = 0
    for i, row in enumerate(rows):
        record = _row_to_record(row, args)
        if record is None:
            failed += 1
            continue

        search_text = record.to_search_text()
        try:
            embedding = embedding_svc.generate_embedding(search_text)
        except Exception:
            logger.exception("Embedding failed for record %d", i)
            failed += 1
            continue

        batch_data.append({
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
        })

        if (i + 1) % 1000 == 0:
            print(f"     Progress: {i + 1}/{len(rows)} ({batch_data[-1]['bug_title'][:40]})")

    print(f"     Embedded {len(batch_data)} records ({time.perf_counter() - t_embed:.1f}s)")

    # ── Batch upsert ──────────────────────────────────────────────
    if batch_data:
        print(f"  💾 Inserting {len(batch_data)} records into LanceDB …")
        client._table.merge_insert("record_id") \
            .when_matched_update_all() \
            .when_not_matched_insert_all() \
            .execute(batch_data)  # type: ignore[arg-type]

        # Rebuild FTS index
        client.create_fts_index(replace=True)

    # ── Summary ───────────────────────────────────────────────────
    t_elapsed = time.perf_counter() - t_start
    print()
    print(f"  {'─' * 56}")
    print(f"  ✅ Import complete")
    print(f"     Total input:  {len(rows)}")
    print(f"     Imported:     {len(batch_data)}")
    print(f"     Failed:       {failed}")
    print(f"     Time:         {t_elapsed:.1f}s")
    print(f"  {'─' * 56}")

    if failed > 0:
        sys.exit(1)


# ═══════════════════════════════════════════════════════════════════
#  Readers
# ═══════════════════════════════════════════════════════════════════


def _read_file(fmt: str, path: str, limit: int) -> list[dict]:
    """Read and parse the input file into a list of dicts."""
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"Input file not found: {path}")

    if fmt == "parquet":
        return _read_parquet(p, limit)
    elif fmt == "json":
        return _read_json(p, limit)
    elif fmt == "csv":
        return _read_csv(p, limit)
    else:
        raise ValueError(f"Unsupported format: {fmt}")


def _read_parquet(path: Path, limit: int) -> list[dict]:
    try:
        import pyarrow.parquet as pq
    except ImportError:
        raise ImportError("pyarrow required for Parquet: pip install pyarrow")

    table = pq.read_table(str(path))
    if limit > 0:
        table = table.slice(0, limit)
    return table.to_pylist()


def _read_json(path: Path, limit: int) -> list[dict]:
    import json
    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, list):
        return data[:limit] if limit > 0 else data
    # Nested structure: try common keys
    for key in ("items", "records", "data", "results"):
        if isinstance(data, dict) and key in data:
            items = data[key]
            return items[:limit] if limit > 0 else items
    raise ValueError("JSON root must be a list or contain 'items'/'records'/'data' key")


def _read_csv(path: Path, limit: int) -> list[dict]:
    import csv
    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        rows = []
        for i, row in enumerate(reader):
            if limit > 0 and i >= limit:
                break
            rows.append(row)
    return rows


# ═══════════════════════════════════════════════════════════════════
#  Filters
# ═══════════════════════════════════════════════════════════════════


def _filter_by_tech_stack(rows: list[dict], prefix: str, tags_col: str) -> None:
    """Filter rows in-place, keeping only those where tags_col contains prefix."""
    prefix_lower = prefix.lower()
    i = 0
    while i < len(rows):
        tags = rows[i].get(tags_col, "")
        if isinstance(tags, str):
            keep = prefix_lower in tags.lower()
        elif isinstance(tags, list):
            keep = any(prefix_lower in str(t).lower() for t in tags)
        else:
            keep = False
        if not keep:
            rows[i] = rows[-1]
            rows.pop()
        else:
            i += 1


# ═══════════════════════════════════════════════════════════════════
#  Row → BugRecord
# ═══════════════════════════════════════════════════════════════════


def _row_to_record(row: dict, args: argparse.Namespace) -> BugRecord | None:
    """Map a data row to a BugRecord using the column mapping."""
    try:
        bug_title = str(row.get(args.map_title, "") or "")
        error_snippet = str(row.get(args.map_error, "") or "")
        solution = str(row.get(args.map_solution, "") or "")

        if not bug_title or not error_snippet or not solution:
            return None

        # Cap lengths
        bug_title = bug_title[:256]
        error_snippet = error_snippet[:32768]
        solution = solution[:16384]

        tried = ""
        if args.map_methods:
            tried = str(row.get(args.map_methods, "") or "")
        if not tried:
            tried = "(not recorded)"
        tried = tried[:8192]

        tech_stack = ""
        if args.map_tags:
            raw_tags = row.get(args.map_tags, "")
            if isinstance(raw_tags, list):
                # GitHub labels: extract name field
                tags = []
                for t in raw_tags:
                    if isinstance(t, dict):
                        tags.append(str(t.get("name", t.get("id", ""))))
                    else:
                        tags.append(str(t))
                tech_stack = ", ".join(tags)
            else:
                # SO tags: "<python><flask>" format
                tech_stack = str(raw_tags).replace("><", ", ").replace("<", "").replace(">", "")
        tech_stack = tech_stack[:256]

        project_name = ""
        if args.map_project:
            project_name = str(row.get(args.map_project, "") or "")[:128]

        root_cause = ""
        if args.map_root_cause:
            root_cause = str(row.get(args.map_root_cause, "") or "")[:4096]

        create_time = ""
        if args.map_time:
            create_time = str(row.get(args.map_time, "") or "")

        return BugRecord(
            bug_title=bug_title or "(untitled)",
            error_log_snippet=error_snippet or "(no error log)",
            tried_methods=tried,
            final_solution=solution,
            project_name=project_name or None,
            tech_stack=tech_stack or None,
            root_cause=root_cause or None,
            create_time=create_time,
        )
    except Exception:
        logger.exception("Failed to parse row")
        return None


if __name__ == "__main__":
    main()
