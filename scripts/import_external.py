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

    # Stack Overflow posts Parquet + self-join (recommended, tested with mikex86/stackoverflow-posts)
    uv run python scripts/import_external.py \
        --format parquet \
        --input stackoverflow_posts.parquet \
        --join-solution \
        --col-id Id \
        --col-accepted-answer AcceptedAnswerId \
        --col-post-type PostTypeId \
        --post-type-question 1 \
        --post-type-answer 2 \
        --map-title Title \
        --map-error Body \
        --map-solution Body \
        --map-tags Tags \
        --map-time CreationDate \
        --tech-stack-prefix python \
        --limit 100000

    # HuggingFace streaming dataset (for pre-joined QA datasets like mteb/StackOverflowQA)
    uv run python scripts/import_external.py \
        --format hf \
        --hf-dataset mteb/StackOverflowQA \
        --hf-split train \
        --map-title title \
        --map-error text \
        --map-solution answer \
        --map-tags tags \
        --limit 50000

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
    parser.add_argument("--format", required=True, choices=["parquet", "json", "csv", "hf"],
                        help="Input file format (hf = HuggingFace streaming dataset)")
    parser.add_argument("--input", default="",
                        help="Path to input file (not used for --format hf)")

    # HuggingFace dataset options
    parser.add_argument("--hf-dataset", default="juancopi81/stack_overflow_python_data",
                        help="HuggingFace dataset name (default: juancopi81/stack_overflow_python_data)")
    parser.add_argument("--hf-split", default="train",
                        help="Dataset split (default: train)")
    parser.add_argument("--hf-filter", default="",
                        help="Optional: only import rows where tags contain this string (case-insensitive)")
    parser.add_argument("--limit", type=int, default=0,
                        help="Max records to import (0 = all)")
    parser.add_argument("--workers", type=int, default=1,
                        help="Parallel workers for embedding (default: 1, ONNX CPU)")

    # Self-join mode (for Stack Overflow posts table where answers are same table)
    parser.add_argument("--join-solution", action="store_true",
                        help="Enable self-join mode: questions.AcceptedAnswerId → answers.Id")
    parser.add_argument("--col-id", default="Id",
                        help="Column name for the record ID (default: Id)")
    parser.add_argument("--col-parent", default="ParentId",
                        help="Column name for the answer's parent question ID")
    parser.add_argument("--col-post-type", default="PostTypeId",
                        help="Column name for post type discriminator")
    parser.add_argument("--post-type-question", type=int, default=1,
                        help="Value identifying a question post (default: 1)")
    parser.add_argument("--post-type-answer", type=int, default=2,
                        help="Value identifying an answer post (default: 2)")
    parser.add_argument("--col-accepted-answer", default="AcceptedAnswerId",
                        help="Column name for accepted answer reference")

    # Auto-extract Stack Overflow fields (HF mode only)
    parser.add_argument("--extract-so-fields", action="store_true",
                        help="Auto-extract code_block→error, text→tried_methods from SO HTML")

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
    if args.format == "hf":
        print(f"  📖 Streaming from HuggingFace dataset '{args.hf_dataset}' …")
        rows = _read_hf_stream(args.hf_dataset, args.hf_split, args.hf_filter, args.limit)
    else:
        print(f"  📖 Reading {args.format} file …")
        rows = _read_file(args.format, args.input, args.limit)
    print(f"     Found {len(rows)} records")

    # ── Self-join mode (Stack Overflow: questions ↔ answers) ────
    if args.join_solution:
        print(f"  🔗 Self-join mode: matching answers to questions …")
        joined = _self_join_solutions(
            rows,
            id_col=args.col_id,
            accepted_col=args.col_accepted_answer,
            post_type_col=args.col_post_type,
            question_type=args.post_type_question,
            answer_type=args.post_type_answer,
            solution_col=args.map_solution,
        )
        print(f"     Joined {len(joined)} questions with accepted answers")
        # Mark all question-type rows as INVALID, then mark joined ones as valid
        for idx, row in enumerate(rows):
            pt = row.get(args.col_post_type)
            if isinstance(pt, str):
                try:
                    pt = int(pt)
                except (ValueError, TypeError):
                    pt = -1
            if pt == args.post_type_question:
                row['_valid'] = False
        for idx_from, solution_text in joined:
            rows[idx_from][args.map_solution] = solution_text
            rows[idx_from]['_valid'] = True
        # Remove invalid rows (questions without answers; non-question rows)
        rows = [r for r in rows if r.get('_valid', True)]
        print(f"     After removing unanswered: {len(rows)} records")

    # ── Apply filters ─────────────────────────────────────────────
    if args.tech_stack_prefix:
        _filter_by_tech_stack(rows, args.tech_stack_prefix, args.map_tags)
        print(f"     After tech_stack filter: {len(rows)} records")

    # ── Parse records ────────────────────────────────────────────
    print(f"  🧠 Parsing {len(rows)} records …")
    t_embed = time.perf_counter()
    dim = settings.embedding_dim

    records: list[tuple[BugRecord, str] | None] = []
    for i, row in enumerate(rows):
        if args.extract_so_fields and args.format == "hf":
            so_fields = extract_so_fields(row)
            record = BugRecord(
                bug_title=so_fields["bug_title"] or "(untitled)",
                error_log_snippet=so_fields["error_log_snippet"] or "(no error log)",
                tried_methods=so_fields["tried_methods"],
                final_solution=so_fields["final_solution"],
                tech_stack=so_fields["tech_stack"] or None,
                create_time=so_fields["create_time"],
            )
        else:
            record = _row_to_record(row, args)

        if record is None:
            records.append(None)
            continue
        records.append((record, record.to_search_text()))

    # ── Parent records need a vector field for LanceDB schema compliance,
    #    but the retrieval pipeline only searches bugvault_chunks.
    #    Zero vector avoids wasteful ONNX inference on long parent texts.
    dummy_vector = [0.0] * settings.embedding_dim

    # Third pass: assemble batch_data (parent records get dummy vectors)
    batch_data: list[dict] = []
    failed = 0
    for i, record_tuple in enumerate(records):
        if record_tuple is None:
            failed += 1
            continue

        record, search_text = record_tuple

        batch_data.append({
            "vector": dummy_vector,  # ← zero vector, never used for search
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
            print(f"     Progress: {i + 1}/{len(records)} ({record.bug_title[:40]})")

    print(f"     Parsed {len(batch_data)} records ({time.perf_counter() - t_embed:.1f}s, zero-vector parents)")

    # ── Generate + embed + upsert chunks (dual-write) ────────────
    if batch_data and embedding_svc:
        chunk_rows: list[dict] = []
        chunk_texts: list[str] = []
        chunk_record_map: list[tuple[int, int]] = []  # (record_idx, chunk_idx)
        for ri, p_record in enumerate(records):
            if p_record is None or p_record[0] is None:
                continue
            rec = p_record[0]
            for ci, ch in enumerate(rec.to_chunks()):
                chunk_texts.append(ch["search_text"])
                chunk_record_map.append((ri, len(chunk_rows)))
                chunk_rows.append(ch)

        if chunk_texts:
            chunk_embs = list(embedding_svc._model.embed(chunk_texts, batch_size=64))
            for idx, emb_vec in enumerate(chunk_embs):
                chunk_rows[idx]["vector"] = emb_vec

            client.ensure_chunks_table()
            client.upsert_chunks(chunk_rows)
            client.create_chunks_fts_index()
            print(f"  🧩 Wrote {len(chunk_rows)} chunks to bugvault_chunks")

    # ── Batch upsert parents (in chunks to avoid spill) ──────────
    if batch_data:
        CHUNK = 200
        total = len(batch_data)
        print(f"  💾 Inserting {total} records into LanceDB (chunk={CHUNK}) …")
        for start in range(0, total, CHUNK):
            chunk = batch_data[start:start + CHUNK]
            client._table.merge_insert("record_id") \
                .when_matched_update_all() \
                .when_not_matched_insert_all() \
                .execute(chunk)  # type: ignore[arg-type]
            print(f"     Inserted {min(start + CHUNK, total)}/{total}")

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
#  HuggingFace streaming reader
# ═══════════════════════════════════════════════════════════════════


def _read_hf_stream(
    dataset_name: str,
    split: str,
    tag_filter: str,
    limit: int,
) -> list[dict]:
    """Stream dataset from HuggingFace with ``streaming=True``.

    Each row is converted to a flat dict with keys expected by
    downstream field mapping and HTML extraction:
      ``title``, ``body``, ``answer_body``, ``tags``, ``creation_date``
    """
    try:
        from datasets import load_dataset
    except ImportError:
        raise ImportError(
            "datasets library required for HF streaming: "
            "pip install datasets"
        )

    dataset = load_dataset(dataset_name, split=split, streaming=True)
    rows: list[dict] = []
    tag_filter_lower = tag_filter.lower() if tag_filter else ""

    for item in dataset:
        # ── Tag filter ────────────────────────────────────────────
        raw_tags = item.get("tags", "") or item.get("Tags", "") or ""
        if isinstance(raw_tags, list):
            tag_str = " ".join(str(t) for t in raw_tags).lower()
        else:
            tag_str = str(raw_tags).lower()
        if tag_filter_lower and tag_filter_lower not in tag_str:
            continue

        # ── Flatten to canonical field names ─────────────────────
        body = item.get("body", "") or item.get("Body", "") or ""
        answers = item.get("answers", None) or item.get("Answers", None)

        row = {
            "title": item.get("title", "") or item.get("Title", "") or "",
            "body": body,
            "answer_body": _pick_answer_body(answers),
            "tags": raw_tags,
            "creation_date": str(item.get("creation_date", "") or item.get("CreationDate", "") or ""),
        }

        # Skip rows without a valid code block in body
        if "<pre><code>" not in body and "```" not in body:
            continue

        rows.append(row)
        if len(rows) % 1000 == 0:
            print(f"     Streamed {len(rows)} rows …")

        if limit > 0 and len(rows) >= limit:
            break

    return rows


def _pick_answer_body(answers) -> str:
    """Extract the best answer body from various answer formats."""
    if not answers:
        return ""
    if isinstance(answers, list):
        # Pick first answer with a body
        for ans in answers:
            if isinstance(ans, dict):
                body = ans.get("body", "") or ans.get("Body", "") or ""
                if body:
                    # Some datasets store accepted answer as first element
                    return body
            elif isinstance(ans, str):
                return ans
        # Fallback to first element
        if isinstance(answers[0], dict):
            return str(answers[0].get("body", answers[0].get("Body", "")))
        return str(answers[0])
    if isinstance(answers, str):
        return answers
    return ""


# ═══════════════════════════════════════════════════════════════════
#  HTML → BugRecord field extraction (for HF streaming mode)
# ═══════════════════════════════════════════════════════════════════


def extract_so_fields(item: dict) -> dict:
    """Extract BugRecord-mapped fields from a Stack Overflow question dict.

    Returns keys: ``bug_title``, ``error_log_snippet``, ``tried_methods``,
    ``final_solution``, ``tech_stack``, ``create_time``.
    """
    import re

    body = item.get("body", "")
    answer_body = item.get("answer_body", "")

    # ── error_log_snippet: first <pre><code> block ──────────────
    code_match = re.search(r"<pre><code>(.*?)</code></pre>", body, re.DOTALL)
    error_snippet = code_match.group(1).strip()[:800] if code_match else "(no code block found)"

    # ── tried_methods: body text after stripping code blocks ─────
    text_only = re.sub(r"<pre><code>.*?</code></pre>", "", body, flags=re.DOTALL)
    text_only = re.sub(r"<.*?>", "", text_only).strip()
    tried_methods = text_only[:2000] if len(text_only) > 50 else "(not recorded in question)"

    # ── final_solution: accepted answer body (cleaned) ──────────
    solution = re.sub(r"<.*?>", "", answer_body).strip()[:2000] if answer_body else "(no answer body)"

    return {
        "bug_title": item.get("title", "")[:256],
        "error_log_snippet": error_snippet,
        "tried_methods": tried_methods,
        "final_solution": solution or "(no answer)",
        "tech_stack": str(item.get("tags", ""))[:256],
        "create_time": item.get("creation_date", ""),
    }


# ═══════════════════════════════════════════════════════════════════
#  Parallel embedding
# ═══════════════════════════════════════════════════════════════════


def _parallel_embed(
    embedding_svc: EmbeddingService,
    texts: list[str],
    workers: int,
) -> list[list[float]]:
    """Split texts into chunks and embed in parallel via ONNX model.

    ONNX Runtime releases the GIL during inference, so
    ``ThreadPoolExecutor`` provides actual parallelism here.
    """
    import concurrent.futures

    chunk_size = max(1, len(texts) // workers)
    chunks = [texts[i:i + chunk_size] for i in range(0, len(texts), chunk_size)]
    BATCH_SIZE = 64

    def _embed_chunk(chunk: list[str]) -> list[list[float]]:
        return list(embedding_svc._model.embed(chunk, batch_size=BATCH_SIZE))  # type: ignore

    results: list[list[float]] = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(_embed_chunk, c) for c in chunks]
        for f in concurrent.futures.as_completed(futures):
            results.extend(f.result())

    return results


# ═══════════════════════════════════════════════════════════════════
#  Self-join (Stack Overflow: questions ← answers)
# ═══════════════════════════════════════════════════════════════════


def _self_join_solutions(
    rows: list[dict],
    id_col: str,
    accepted_col: str,
    post_type_col: str,
    question_type: int,
    answer_type: int,
    solution_col: str,
) -> list[tuple[int, str]]:
    """Build accepted_answer_id → Body lookup, then join to questions.

    Returns list of (row_index, answer_body) for questions that have
    an accepted answer present in the dataset.
    """
    # Build answer lookup: Id → Body
    answer_body: dict[str | int, str] = {}
    for row in rows:
        pt = row.get(post_type_col)
        if isinstance(pt, str):
            try:
                pt = int(pt)
            except (ValueError, TypeError):
                continue
        if pt == answer_type:
            aid = row.get(id_col)
            body = row.get(solution_col, "") or ""
            if aid is not None:
                answer_body[aid] = body

    # Match questions to their accepted answer
    result: list[tuple[int, str]] = []
    for idx, row in enumerate(rows):
        pt = row.get(post_type_col)
        if isinstance(pt, str):
            try:
                pt = int(pt)
            except (ValueError, TypeError):
                continue
        if pt != question_type:
            continue
        accepted_id = row.get(accepted_col)
        if accepted_id is None:
            continue
        body = answer_body.get(accepted_id)
        if body:
            result.append((idx, body))

    return result


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
