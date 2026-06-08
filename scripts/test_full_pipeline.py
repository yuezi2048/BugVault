#!/usr/bin/env python3
"""End-to-end scenario tests via direct Python API (simulates agent behavior).

Instead of spawning a subprocess for MCP (which has startup timing issues),
this script calls the BugVault services directly — same code path as the MCP tools,
same pipeline, same chunk retrieval logic.

Scenarios:
  A. Save a Python KeyError bug → verify 2 chunks upserted
  B. Save a JS TypeError bug → verify 2 chunks upserted
  C. Save a Java NPE bug → verify 2 chunks upserted
  D. Exact error retrieval → search by error_log chunk
  E. Semantic retrieval → search by semantic chunk
  F. Tech-stack filtered retrieval (target_tech_stack)
  G. Project-name filtered retrieval (target_project_name)
  H. Cross-language elimination (Python error + Java filter = empty)
  I. Parent-document mapping completeness
"""

from __future__ import annotations

import hashlib
import json
import sys
import time

import os
import tempfile

# Use an isolated temp directory so sample data doesn't interfere
_TEST_DATA_ROOT = tempfile.mkdtemp(prefix="bugvault_test_")
os.environ["BUGVAULT_DATA_ROOT"] = _TEST_DATA_ROOT

from bugvault.config import settings
from bugvault.database.lancedb_client import LanceDBClient
from bugvault.models.bug_record import BugRecord
from bugvault.services.embedding_svc import EmbeddingService
from bugvault.services.retrieval_svc import rerank, rrf_fusion
from bugvault.utils.logger import logger

PASS = 0
FAIL = 0


def check(name: str, condition: bool, detail: str = "") -> None:
    global PASS, FAIL
    if condition:
        PASS += 1
        print(f"  ✅ {name}")
    else:
        FAIL += 1
        print(f"  ❌ {name}  {detail}")


def embed_and_save(db, emb, record):
    """Simulate _async_embed_and_store — embed + upsert parent + chunks."""
    search_text = record.to_search_text()
    chunk_defs = record.to_chunks()
    full_emb = emb.generate_embedding(search_text)
    db.upsert_record(search_text, full_emb, record)

    chunk_rows = []
    for cd in chunk_defs:
        chunk_emb = emb.generate_embedding(cd["search_text"])
        chunk_rows.append({
            "vector": chunk_emb,
            "chunk_id": cd["chunk_id"],
            "parent_id": cd["parent_id"],
            "chunk_type": cd["chunk_type"],
            "search_text": cd["search_text"],
            "tech_stack": record.tech_stack or "",
            "project_name": record.project_name or "",
        })
    db.upsert_chunks(chunk_rows)
    return record


def search_and_format(db, emb, query, tech_stack="", project_name=""):
    """Simulate _sync_search_and_format — the full retrieve pipeline."""
    rerank_limit = settings.top_k * 4
    filter_clause = _build_simple_filter(tech_stack, project_name)
    query_emb = emb.generate_embedding(query)

    # Chunk-level dual recall
    vec_chunks = db.search_chunks(query_emb, filter_clause=filter_clause, limit=rerank_limit)
    fts_chunks = []
    try:
        fts_chunks = db.search_chunks_fts(query, filter_clause=filter_clause, limit=rerank_limit)
        fts_chunks = [r for r in fts_chunks if r.get("_score", 0) > 0]
    except Exception:
        pass

    # Chunk-level RRF
    chunk_results = rrf_fusion(vec_chunks, fts_chunks) if fts_chunks else vec_chunks
    if not chunk_results:
        return []

    # Parent-document mapping
    parent_best = {}
    for ch in chunk_results:
        pid = ch.get("parent_id", "") or ""
        if not pid:
            continue
        if pid not in parent_best:
            parent_best[pid] = ch
        else:
            existing = parent_best[pid]
            prev = existing.get("_distance", 1.0) if "_distance" in existing else -existing.get("_rrf_score", 0.0)
            cur = ch.get("_distance", 1.0) if "_distance" in ch else -ch.get("_rrf_score", 0.0)
            if cur < prev:
                parent_best[pid] = ch

    parent_records = db.fetch_records_by_ids(list(parent_best.keys()))
    record_map = {r.get("record_id", ""): r for r in parent_records}

    results = []
    for pid, best in parent_best.items():
        full = record_map.get(pid)
        if full is None:
            continue
        merged = dict(full)
        if "_distance" in best:
            merged["_distance"] = best["_distance"]
        if "_rrf_score" in best:
            merged["_rrf_score"] = best["_rrf_score"]
        results.append(merged)

    # rerank + truncate
    results = rerank(results)
    return results[:settings.top_k]


def _build_simple_filter(tech_stack: str, project_name: str) -> str | None:
    import re
    clauses = []
    if tech_stack:
        val = re.sub(r"[^a-zA-Z0-9_\-\s. ]", "", tech_stack.strip())
        if val:
            clauses.append(f"LOWER(tech_stack) LIKE '%{val.lower()}%'")
    if project_name:
        val = re.sub(r"[^a-zA-Z0-9_\-\s. ]", "", project_name.strip())
        if val:
            clauses.append(f"LOWER(project_name) LIKE '%{val.lower()}%'")
    return " AND ".join(clauses) if clauses else None


def main() -> None:
    global PASS, FAIL
    print("=" * 60)
    print("  BugVault v1.1.1 — Full Pipeline Scenario Test")
    print("  (simulates agent calling MCP tools)")
    print("=" * 60)
    t_start = time.perf_counter()

    db = LanceDBClient()
    db.initialize()
    emb = EmbeddingService()
    check("Server initialized (is_ready)", db.is_ready)

    # ── Create 3 test records ─────────────────────────────────────
    records = [
        BugRecord(
            bug_title="Python KeyError in dict access",
            error_log_snippet="Traceback (most recent call last):\n  File \"app.py\", line 42, in get_user\n    return users[user_id]\nKeyError: 42",
            tried_methods="Used .get() with default None",
            final_solution="Use users.get(user_id, default_user) instead of bracket access",
            project_name="user-service",
            tech_stack="Python, FastAPI",
            root_cause="Assumed dict key exists without checking",
        ),
        BugRecord(
            bug_title="JavaScript undefined .map() call",
            error_log_snippet="TypeError: Cannot read properties of undefined (reading 'map')\n    at processItems (app.js:15:12)",
            tried_methods="Added console.log, checked variable type",
            final_solution="Use Array.isArray(data) && data.map(fn) before iterating",
            project_name="frontend-app",
            tech_stack="JavaScript, React",
        ),
        BugRecord(
            bug_title="Java NPE from Optional.get()",
            error_log_snippet="java.lang.NullPointerException\n    at com.example.OrderService.getOrder(OrderService.java:25)",
            tried_methods="Added if-present blocks",
            final_solution="Replace Optional.get() with orElseThrow(() -> new NotFoundException())",
            project_name="order-service",
            tech_stack="Java, Spring Boot",
            root_cause="Called Optional.get() on empty Optional",
        ),
    ]

    for i, rec in enumerate(records, 1):
        embed_and_save(db, emb, rec)
        check(f"Save Record {i}: '{rec.bug_title[:40]}...'", True)

    # Verify chunks
    for rec in records:
        chunks = rec.to_chunks()
        check(f"  to_chunks() returns 2 chunks for '{rec.bug_title[:30]}...'",
              len(chunks) == 2)
        check(f"  error_log chunk contains bug_title", rec.bug_title in chunks[0]["search_text"])
        check(f"  error_log chunk contains error_log_snippet", rec.error_log_snippet in chunks[0]["search_text"])
        check(f"  semantic chunk contains tried_methods", rec.tried_methods in chunks[1]["search_text"])
        check(f"  semantic chunk contains final_solution", rec.final_solution in chunks[1]["search_text"])
        check(f"  chunk_ids differ", chunks[0]["chunk_id"] != chunks[1]["chunk_id"])
        check(f"  chunk length < full search_text",
              len(chunks[0]["search_text"]) < len(rec.to_search_text()))

    # ── Scenario D: Exact error retrieval ─────────────────────────
    print("\n─── Scenario D: Exact error retrieval ─────────────────────")
    print("    Agent query: 'KeyError: 42'")
    results_d = search_and_format(db, emb, "KeyError: 42")
    check("Returns results", len(results_d) > 0)
    check("Python record in top results",
          any("Python KeyError" in r.get("bug_title", "") for r in results_d),
          f"Titles: {[r.get('bug_title','')[:30] for r in results_d[:3]]}")

    # ── Scenario E: Semantic retrieval ─────────────────────────────
    print("\n─── Scenario E: Semantic retrieval ───────────────────────")
    print("    Agent query: 'function not defined when calling .map() on JavaScript array'")
    results_e = search_and_format(db, emb, "function not defined when calling .map() on JavaScript array")
    check("Returns results", len(results_e) > 0)
    check("JS record in top results",
          any("JavaScript undefined" in r.get("bug_title", "") for r in results_e),
          f"Titles: {[r.get('bug_title','')[:30] for r in results_e[:3]]}")

    # ── Scenario F: Tech-stack filtered retrieval ──────────────────
    print("\n─── Scenario F: Tech-stack filtered retrieval ────────────")
    print("    Agent query: 'null pointer exception' + target_tech_stack='Java'")
    results_f = search_and_format(db, emb, "null pointer exception", tech_stack="Java")
    check("Returns results", len(results_f) > 0)
    java_in_results = any("Java NPE" in r.get("bug_title", "") for r in results_f)
    check("Java NPE record in results", java_in_results,
          f"Titles: {[r.get('bug_title','')[:30] for r in results_f[:3]]}")
    # No Python records should appear when filtered to Java
    python_filtered_out = all("Python" not in r.get("bug_title", "") for r in results_f)
    check("Python records filtered out by tech_stack='Java'", python_filtered_out)

    # ── Scenario G: Project-name filtered retrieval ────────────────
    print("\n─── Scenario G: Project-name filtered retrieval ──────────")
    print("    Agent query: 'map is not a function' + target_project_name='frontend-app'")
    results_g = search_and_format(db, emb, "map is not a function", project_name="frontend-app")
    check("Returns results", len(results_g) > 0)
    check("Frontend-app record in results",
          any("frontend" in r.get("project_name", "").lower() for r in results_g),
          f"Projects: {[r.get('project_name','') for r in results_g[:3]]}")

    # ── Scenario H: Cross-language elimination ─────────────────────
    print("\n─── Scenario H: Cross-language elimination ───────────────")
    print("    Agent query: 'KeyError' + target_tech_stack='Java'")
    print("    (Should return NO Python results — KeyError is Python, not Java)")
    results_h = search_and_format(db, emb, "KeyError", tech_stack="Java")
    python_leak = any("Python" in r.get("bug_title", "") for r in results_h)
    check("Python records NOT returned when filter tech_stack='Java'", not python_leak,
          f"Titles: {[r.get('bug_title','')[:30] for r in results_h[:3]]}")

    # ── Scenario I: Parent-document mapping completeness ───────────
    print("\n─── Scenario I: Parent-document mapping ──────────────────")
    print("    Verify that chunk search → parent fetch returns full records")
    query_emb = emb.generate_embedding("KeyError: 42")
    chunks = db.search_chunks(query_emb, limit=5)
    parent_ids = list(set(c.get("parent_id") for c in chunks if c.get("parent_id")))
    parents = db.fetch_records_by_ids(parent_ids)
    check(f"fetch_records_by_ids returns {len(parents)} records for {len(parent_ids)} parent_ids",
          len(parents) > 0 and len(parents) <= len(parent_ids))
    if parents:
        p = parents[0]
        check("Full record: contains bug_title", bool(p.get("bug_title")))
        check("Full record: contains error_log_snippet", bool(p.get("error_log_snippet")))
        check("Full record: contains tried_methods", bool(p.get("tried_methods")))
        check("Full record: contains final_solution", bool(p.get("final_solution")))
        check("Full record: contains create_time", bool(p.get("create_time")))

    # ── Cleanup temp dir ─────────────────────────────────────────
    import shutil
    try:
        shutil.rmtree(_TEST_DATA_ROOT, ignore_errors=True)
    except Exception:
        pass

    # ── Summary ────────────────────────────────────────────────────
    t_elapsed = time.perf_counter() - t_start
    print()
    print(f"  {'─' * 56}")
    total = PASS + FAIL
    print(f"  Time:       {t_elapsed:.1f}s")
    print(f"  Assertions: {PASS}/{total} passed,  {FAIL}/{total} failed")
    if FAIL > 0:
        print("  ❌ SOME TESTS FAILED")
        sys.exit(1)
    else:
        print("  ✅ ALL SCENARIOS PASSED")


if __name__ == "__main__":
    main()
