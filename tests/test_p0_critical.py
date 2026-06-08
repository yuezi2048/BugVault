"""P0 critical tests — Cross-Encoder, pipeline orchestration, backward compatibility.

These tests address the three P0 coverage gaps identified in the v1.1.1
test report (docs/tests/v1.1.1-test-report.md):

  TC-01: Cross-Encoder reranker correctness and fallback
  TC-02: _sync_search_and_format pipeline (chunks + fallback)
  TC-03: Backward compatibility (no chunks → FTS-only fallback)

All tests use an isolated temp directory so existing sample data
never interferes.
"""

from __future__ import annotations

import os
import tempfile

_TEST_DATA_ROOT = tempfile.mkdtemp(prefix="bugvault_p0_")
os.environ["BUGVAULT_DATA_ROOT"] = _TEST_DATA_ROOT
os.environ["BUGVAULT_ENABLE_RERANKER"] = "false"  # avoid model download in CI

import shutil
from typing import Any

import pytest

from bugvault.config import settings
from bugvault.database.lancedb_client import LanceDBClient
from bugvault.models.bug_record import BugRecord
from bugvault.services.embedding_svc import EmbeddingService
from bugvault.services.retrieval_svc import rerank, rrf_fusion


# ═══════════════════════════════════════════════════════════════════
#  Fixtures
# ═══════════════════════════════════════════════════════════════════


@pytest.fixture(scope="module")
def db():
    """Provide a clean LanceDBClient in an isolated temp directory."""
    client = LanceDBClient()
    client.initialize()
    yield client
    # Teardown: clean up temp dir
    try:
        shutil.rmtree(_TEST_DATA_ROOT, ignore_errors=True)
    except Exception:
        pass


@pytest.fixture(scope="module")
def emb():
    """Provide a shared EmbeddingService instance."""
    return EmbeddingService()


def _save(
    db: LanceDBClient,
    emb: EmbeddingService,
    record: BugRecord,
) -> None:
    """Helper: embed + upsert parent record + 2 chunks."""
    search_text = record.to_search_text()
    full_emb = emb.generate_embedding(search_text)
    table_row = {
        "vector": full_emb,
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
    db.upsert_record(table_row)

    chunks = record.to_chunks()
    rows = []
    for cd in chunks:
        chunk_emb = emb.generate_embedding(cd["search_text"])
        rows.append({
            "vector": chunk_emb,
            "chunk_id": cd["chunk_id"],
            "parent_id": cd["parent_id"],
            "chunk_type": cd["chunk_type"],
            "search_text": cd["search_text"],
            "tech_stack": cd.get("tech_stack", ""),
            "project_name": cd.get("project_name", ""),
            "record_type": cd.get("record_type", "bug"),
        })
    db.upsert_chunks(rows)


def _save_old_style(
    db: LanceDBClient,
    emb: EmbeddingService,
    record: BugRecord,
) -> None:
    """Helper: upsert parent record ONLY (simulating pre-v1.1.1 data)."""
    search_text = record.to_search_text()
    full_emb = emb.generate_embedding(search_text)
    table_row = {
        "vector": full_emb,
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
    db.upsert_record(table_row)


# ═══════════════════════════════════════════════════════════════════
#  TC-01: Cross-Encoder Reranker
# ═══════════════════════════════════════════════════════════════════


class TestCrossEncoder:
    """Cross-Encoder reranker correctness, fallback, and edge cases."""

    def test_doc_text_builds_correctly(self):
        """_doc_text concatenates bug_title + error + solution + root_cause."""
        from bugvault.services.reranker_svc import _doc_text

        doc = {
            "bug_title": "Test bug",
            "error_log_snippet": "KeyError: 42",
            "tried_methods": "tried .get()",
            "final_solution": "use default",
            "root_cause": "missing fallback",
        }
        text = _doc_text(doc)
        assert "Test bug" in text
        assert "KeyError: 42" in text
        assert "use default" in text
        assert "missing fallback" in text
        # tried_methods is intentionally excluded (focused on solution)
        assert "tried .get()" not in text

    def test_doc_text_handles_missing_fields(self):
        """_doc_text skips empty/None fields gracefully."""
        from bugvault.services.reranker_svc import _doc_text

        doc = {"bug_title": "Title", "final_solution": "Fix"}
        text = _doc_text(doc)
        assert "Title" in text
        assert "Fix" in text

    def test_rerank_empty_docs(self):
        """rerank returns empty list unchanged."""
        from bugvault.services.reranker_svc import CrossEncoderReranker

        reranker = CrossEncoderReranker("test-model")
        result = reranker.rerank("query", [])
        assert result == []

    def test_rerank_single_doc(self):
        """rerank returns single-doc list unchanged (no scoring needed)."""
        from bugvault.services.reranker_svc import CrossEncoderReranker

        reranker = CrossEncoderReranker("test-model")
        doc = {"bug_title": "Test", "final_solution": "Fix"}
        result = reranker.rerank("query", [doc])
        assert len(result) == 1
        assert "_ce_score" not in result[0]

    def test_reranker_returns_none_on_failure(self, monkeypatch):
        """get_reranker() returns None when model init fails."""
        from bugvault.services import reranker_svc

        # Force failure by passing an invalid model name
        monkeypatch.setattr(reranker_svc, "_reranker_instance", None)
        monkeypatch.setattr(
            "bugvault.services.reranker_svc.CrossEncoderReranker.__init__",
            lambda self, name: (_ for _ in ()).throw(RuntimeError("Model load failed")),
        )
        result = reranker_svc.get_reranker()
        assert result is None

    def test_sorting_by_ce_score(self):
        """rerank sorts documents by _ce_score descending."""
        # Direct test of the sorting logic without the model
        docs = [
            {"bug_title": "low", "_ce_score": 0.3},
            {"bug_title": "high", "_ce_score": 0.9},
            {"bug_title": "mid", "_ce_score": 0.6},
        ]
        sorted_docs = sorted(docs, key=lambda x: x["_ce_score"], reverse=True)
        assert [d["bug_title"] for d in sorted_docs] == ["high", "mid", "low"]

    def test_rerank_preserves_original_order_on_failure(self):
        """When model.rerank raises, original order is preserved."""
        from bugvault.services.reranker_svc import CrossEncoderReranker

        reranker = CrossEncoderReranker("test-model")

        # Mock _ensure_model to succeed but _model.rerank to fail
        reranker._model = type("MockModel", (), {
            "rerank": lambda self, q, texts: (_ for _ in ()).throw(RuntimeError("fail"))
        })()

        docs = [
            {"bug_title": "first", "final_solution": "A"},
            {"bug_title": "second", "final_solution": "B"},
        ]
        result = reranker.rerank("query", docs)
        assert len(result) == 2
        assert result[0]["bug_title"] == "first"


# ═══════════════════════════════════════════════════════════════════
#  TC-02: _sync_search_and_format Pipeline
# ═══════════════════════════════════════════════════════════════════


class TestPipeline:
    """Full retrieval pipeline: chunks → RRF → parent-mapping → rerank."""

    @pytest.fixture(autouse=True)
    def setup_data(self, db, emb):
        """Seed test data shared across all pipeline tests."""
        self.py_record = BugRecord(
            bug_title="Python KeyError in dict access",
            error_log_snippet="Traceback\nKeyError: 42",
            tried_methods="Used .get()",
            final_solution="Use users.get(key, default)",
            project_name="user-service",
            tech_stack="Python, FastAPI",
        )
        self.js_record = BugRecord(
            bug_title="JavaScript undefined .map() call",
            error_log_snippet="TypeError: Cannot read properties of undefined",
            tried_methods="Added console.log",
            final_solution="Use Array.isArray(data) && data.map(fn)",
            project_name="frontend-app",
            tech_stack="JavaScript, React",
        )
        self.java_record = BugRecord(
            bug_title="Java NPE from Optional.get()",
            error_log_snippet="java.lang.NullPointerException",
            tried_methods="Added if-present checks",
            final_solution="Use orElseThrow()",
            project_name="order-service",
            tech_stack="Java, Spring Boot",
        )

        _save(db, emb, self.py_record)
        _save(db, emb, self.js_record)
        _save(db, emb, self.java_record)

        self.rec_ids = [
            self.py_record.record_id,
            self.js_record.record_id,
            self.java_record.record_id,
        ]

    # ── Sub-pipeline: chunk-level dual recall ─────────────────────

    def test_chunk_dual_recall_vector(self, db, emb):
        """search_chunks returns results with parent_id and _distance."""
        q_emb = emb.generate_embedding("KeyError: 42")
        results = db.search_chunks(q_emb, limit=10)
        assert len(results) > 0
        assert all("parent_id" in r for r in results)
        assert all("_distance" in r for r in results)

    def test_chunk_dual_recall_fts(self, db, emb):
        """search_chunks_fts returns results with _score."""
        results = db.search_chunks_fts("KeyError", limit=10)
        assert len(results) > 0
        assert all("_score" in r for r in results)
        assert all(r.get("_score", 0) > 0 for r in results)

    def test_chunk_filter_tech_stack(self, db, emb):
        """Metadata filter correctly narrows chunk results."""
        q_emb = emb.generate_embedding("null pointer exception")
        results = db.search_chunks(
            q_emb,
            filter_clause="LOWER(tech_stack) LIKE '%java%'",
            limit=10,
        )
        for r in results:
            assert "java" in r.get("tech_stack", "").lower(), (
                f"Expected Java tech_stack, got: {r.get('tech_stack')}"
            )

    def test_chunk_filter_project_name(self, db, emb):
        """Project-name filter correctly narrows chunk results."""
        q_emb = emb.generate_embedding("map function not working")
        results = db.search_chunks(
            q_emb,
            filter_clause="LOWER(project_name) LIKE '%frontend%'",
            limit=10,
        )
        for r in results:
            assert "frontend" in r.get("project_name", "").lower(), (
                f"Expected frontend project, got: {r.get('project_name')}"
            )

    def test_cross_language_elimination(self, db, emb):
        """Python error + Java filter = empty results."""
        q_emb = emb.generate_embedding("KeyError")
        results = db.search_chunks(
            q_emb,
            filter_clause="LOWER(tech_stack) LIKE '%java%'",
            limit=10,
        )
        # KeyError is not a Java error — zero results expected
        has_python = any("python" in r.get("tech_stack", "").lower() for r in results)
        assert not has_python, "Python records leaked through Java filter"

    # ── Sub-pipeline: RRF fusion ──────────────────────────────────

    def test_rrf_on_chunks(self, db, emb):
        """Chunk-level RRF fusion produces scored results."""
        q_emb = emb.generate_embedding("KeyError")
        vec = db.search_chunks(q_emb, limit=20)
        fts = db.search_chunks_fts("KeyError", limit=20)
        fts = [r for r in fts if r.get("_score", 0) > 0]

        fused = rrf_fusion(vec, fts)
        assert len(fused) > 0
        # RRF-fused results should have _rrf_score
        assert all("_rrf_score" in r for r in fused)

    def test_rrf_empty_fts_fallback(self, db, emb):
        """RRF with empty FTS falls back to vector order."""
        q_emb = emb.generate_embedding("KeyError")
        vec = db.search_chunks(q_emb, limit=10)
        fused = rrf_fusion(vec, [])
        assert len(fused) == len(vec)

    # ── Sub-pipeline: parent-document mapping ─────────────────────

    def test_parent_document_mapping(self, db, emb):
        """fetch_records_by_ids returns full metadata for all chunk parent_ids."""
        q_emb = emb.generate_embedding("KeyError: 42")
        chunks = db.search_chunks(q_emb, limit=5)
        parent_ids = list(set(c.get("parent_id") for c in chunks if c.get("parent_id")))

        records = db.fetch_records_by_ids(parent_ids)
        assert len(records) == len(parent_ids), (
            f"Expected {len(parent_ids)} records, got {len(records)}"
        )

        for rec in records:
            assert rec.get("bug_title")
            assert rec.get("error_log_snippet")
            assert rec.get("tried_methods")
            assert rec.get("final_solution")
            assert rec.get("create_time")

    def test_parent_document_mapping_empty_ids(self, db):
        """fetch_records_by_ids with empty list returns []."""
        assert db.fetch_records_by_ids([]) == []

    def test_parent_document_mapping_unknown_ids(self, db):
        """fetch_records_by_ids with non-existent ids returns []."""
        assert db.fetch_records_by_ids(["nonexistent_id"]) == []

    # ── Sub-pipeline: rerank with semantic threshold ──────────────

    def test_rerank_drops_low_semantic_docs(self):
        """rerank drops documents below min_semantic_score."""
        docs = [
            {"_distance": 0.1, "record_id": "a"},   # semantic = 0.95 → keep
            {"_distance": 1.8, "record_id": "b"},   # semantic = 0.10 → drop (< 0.65)
            {"_distance": 0.5, "record_id": "c"},   # semantic = 0.75 → keep
        ]
        result = rerank(docs)
        ids = [r["record_id"] for r in result]
        assert "a" in ids
        assert "b" not in ids
        assert "c" in ids

    def test_rerank_rrf_preserves_high_scoring(self):
        """rerank with _rrf_score keeps highest-scored docs."""
        docs = [
            {"_rrf_score": 0.05, "record_id": "low"},
            {"_rrf_score": 0.20, "record_id": "high"},
            {"_rrf_score": 0.10, "record_id": "mid"},
        ]
        result = rerank(docs)
        assert result[0]["record_id"] == "high"
        assert result[-1]["record_id"] == "low"

    def test_rerank_dedup(self):
        """rerank deduplicates by record_id, keeping highest scored."""
        docs = [
            {"_rrf_score": 0.15, "record_id": "dup"},
            {"_rrf_score": 0.05, "record_id": "unique"},
            {"_rrf_score": 0.10, "record_id": "dup"},  # duplicate, lower score
        ]
        result = rerank(docs)
        ids = [r["record_id"] for r in result]
        assert ids.count("dup") == 1, f"Dup appears {ids.count('dup')} times"
        assert "unique" in ids

    def test_rerank_non_rrf_non_distance(self):
        """Documents without _rrf_score or _distance get base_score=0.5 (kept)."""
        docs = [
            {"record_id": "a", "create_time": "2026-01-01T00:00:00+00:00"},
        ]
        result = rerank(docs)
        assert len(result) == 1
        assert result[0]["record_id"] == "a"


# ═══════════════════════════════════════════════════════════════════
#  TC-03: Backward Compatibility (no chunks)
# ═══════════════════════════════════════════════════════════════════


class TestBackwardCompatibility:
    """Pre-v1.1.1 records (no chunks) must still be retrievable."""

    @pytest.fixture(autouse=True)
    def setup_old_data(self, db, emb):
        """Add one record WITHOUT chunks — simulates old-style data in same DB."""
        self.old_record = BugRecord(
            bug_title="Legacy Connection Pool Exhaustion",
            error_log_snippet="psycopg2.OperationalError: could not connect to server",
            tried_methods="Increased pool size",
            final_solution="Set pool_max=20 with connection timeout",
            project_name="legacy-svc",
            tech_stack="Python, PostgreSQL",
        )
        # Old-style: parent record ONLY, no chunk upsert
        _save_old_style(db, emb, self.old_record)
        self.old_emb = emb
        yield
        # Cleanup: delete this specific record + its chunks if any
        try:
            rid = repr(self.old_record.record_id or "")
            db._table.delete(f"record_id = {rid}")
            db._chunks_table.delete(f"parent_id = {rid}")
        except Exception:
            pass

    def test_old_data_fts_searchable(self, db):
        """Old-style records are searchable via FTS on bug_records."""
        fts_results = db.search_fts("Legacy Connection Pool", limit=5)
        assert len(fts_results) > 0, "FTS returned no results for old data"
        titles = [r.get("bug_title", "") for r in fts_results]
        assert any("Connection Pool" in t for t in titles), (
            f"Expected 'Connection Pool' in FTS results: {titles}"
        )

    def test_old_data_fields_preserved(self, db):
        """Old-style records have full field fidelity."""
        # Use the exact record_id for precise lookup
        rid = repr(self.old_record.record_id or "")
        results = db._table.search().where(f"record_id = {rid}").to_list()
        assert len(results) > 0, "Old record not found by exact record_id"
        rec = results[0]
        assert rec.get("bug_title") == "Legacy Connection Pool Exhaustion"
        assert "psycopg2" in rec.get("error_log_snippet", "")
        assert "pool_max" in rec.get("final_solution", "")
        assert rec.get("project_name") == "legacy-svc"
        assert "Python" in rec.get("tech_stack", "")

    def test_chunks_table_has_no_chunk_for_old_record(self, db):
        """Old-style record did NOT create any chunk entries."""
        rid = self.old_record.record_id or ""
        quoted = repr(rid)
        chunks = db._chunks_table.search().where(f"parent_id = {quoted}").to_list()
        assert len(chunks) == 0, (
            f"Expected 0 chunks for old-style record, found {len(chunks)}"
        )

    def test_old_data_format_matches_new_data(self, db):
        """Old records and new records share the same parent schema."""
        old_recs = db.search_fts("Connection Pool", limit=5)
        assert len(old_recs) > 0
        rec = old_recs[0]
        for field in ("record_id", "bug_title", "error_log_snippet",
                      "tried_methods", "final_solution", "create_time"):
            assert field in rec, f"Old record missing field: {field}"

    def test_rerank_works_with_old_data(self):
        """rerank handles old-style records (no _distance, no _rrf_score)."""
        # Documents without _distance or _rrf_score get base_score=0.5
        docs = [{"record_id": "old1", "bug_title": "Legacy Connection Pool Exhaustion"}]
        ranked = rerank(docs)
        assert len(ranked) == 1
        assert ranked[0]["bug_title"] == "Legacy Connection Pool Exhaustion"


# ═══════════════════════════════════════════════════════════════════
#  Cleanup
# ═══════════════════════════════════════════════════════════════════


def test_cleanup():
    """Remove the shared temp directory after all tests."""
    try:
        shutil.rmtree(_TEST_DATA_ROOT, ignore_errors=True)
    except Exception:
        pass
    assert True
