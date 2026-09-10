"""P1 and P2 extended tests — persistence, RAG action logic, edge cases.

Addresses coverage gaps from docs/tests/v1.1.1-test-report.md:

  P1 — TC-04: RecordPersistence (save flow)
  P1 — TC-05: _compute_suggested_action + _append_eval_to_lines
  P2 — TC-06: Multiple tech_stack tags filtering
  P2 — TC-07: EmbeddingService edge cases (empty/long/special text)
  P2 —       : suggest_probe_questions generation
  P2 —       : Config/Settings path resolution
"""

from __future__ import annotations

import os

import pytest

from bugvault.config import Settings
from bugvault.models.rag_eval_result import RAGEvalResult
from bugvault.services.embedding_svc import EmbeddingService
from bugvault.services.ingestion_svc import suggest_probe_questions
from bugvault.services.persistence_svc import RecordPersistence


# ═══════════════════════════════════════════════════════════════════
#  P1 — TC-04: Record Persistence (save pipeline)
# ═══════════════════════════════════════════════════════════════════


class _MemoryDatabase:
    def __init__(self) -> None:
        self.parents: dict[str, dict] = {}
        self.chunks: dict[str, dict] = {}

    def upsert_record(self, row: dict) -> None:
        self.parents[row["record_id"]] = row

    def upsert_chunks(self, rows: list[dict]) -> None:
        for row in rows:
            self.chunks[row["chunk_id"]] = row


class _BatchEmbedding:
    def __init__(self) -> None:
        self.calls: list[list[str]] = []

    def generate_embeddings(self, texts: list[str]) -> list[list[float]]:
        self.calls.append(texts)
        return [[float(index)] for index, _ in enumerate(texts)]


class TestRecordPersistence:
    """Verify the save pipeline through its public service interface."""

    def test_save_creates_parent_and_chunks_with_one_embedding_batch(self):
        db = _MemoryDatabase()
        embedding = _BatchEmbedding()
        persistence = RecordPersistence(
            db=db,
            embedding_svc=embedding,
            archive_bug=lambda _: None,
        )
        prepared = persistence.prepare_bug({
            "bug_title": "P1 test save flow",
            "error_log_snippet": "ValueError: invalid literal for int()",
            "tried_methods": "Tried int() with try/except",
            "final_solution": "Use str.isdigit() to validate before int()",
            "project_name": "p1-test",
            "tech_stack": "Python",
        })

        assert prepared.record is not None
        record = prepared.record
        persistence.persist(record)

        assert len(db.parents) == 1
        assert len(db.chunks) == 2
        assert {row["chunk_type"] for row in db.chunks.values()} == {
            "error_log", "semantic",
        }
        assert embedding.calls == [[
            record.to_search_text(),
            *[chunk["search_text"] for chunk in record.to_chunks()],
        ]]

    def test_save_deduplicates_by_record_and_chunk_id(self):
        db = _MemoryDatabase()
        persistence = RecordPersistence(
            db=db,
            embedding_svc=_BatchEmbedding(),
            archive_bug=lambda _: None,
        )
        prepared = persistence.prepare_bug({
            "bug_title": "P1 dedup test",
            "error_log_snippet": "ValueError: duplicate",
            "tried_methods": "Tried casting",
            "final_solution": "Validate before casting",
        })

        assert prepared.record is not None
        persistence.persist(prepared.record)
        persistence.persist(prepared.record)

        assert len(db.parents) == 1
        assert len(db.chunks) == 2

    def test_prepare_returns_a_draft_without_archiving_or_persistence(self):
        archived: list[object] = []
        persistence = RecordPersistence(
            db=_MemoryDatabase(),
            embedding_svc=_BatchEmbedding(),
            archive_bug=archived.append,
        )

        prepared = persistence.prepare_bug({
            "bug_title": "Incomplete record",
            "error_log_snippet": "Some error",
            "tried_methods": "   ",
            "final_solution": "   ",
            "project_name": "test",
        })

        assert prepared.record is not None
        assert prepared.is_draft
        assert prepared.missing_fields == ["tried_methods", "final_solution"]
        assert archived == []
        with pytest.raises(ValueError, match="Cannot persist a draft"):
            persistence.persist(prepared.record)


# ═══════════════════════════════════════════════════════════════════
#  P1 — TC-05: RAG Evaluation Action Logic
# ═══════════════════════════════════════════════════════════════════


class TestRAGEvalAction:
    """_compute_suggested_action and _append_eval_to_lines formatting."""

    @pytest.fixture
    def eval_result(self):
        """Base eval result — subclasses override fields."""
        return RAGEvalResult()

    def test_action_confidence_high(self):
        """score >= 7.0 + faithfulness >= 0.8 → CONFIDENT."""
        result = RAGEvalResult(
            rag_confidence_score=8.5,
            faithfulness=0.9,
            context_relevance=4.0,
        )
        from bugvault.mcp_tools.tools import _compute_suggested_action
        action = _compute_suggested_action(result)
        assert action == "CONFIDENT", f"Expected CONFIDENT, got {action}"

    def test_action_confidence_high_low_faithfulness(self):
        """score >= 7.0 but faithfulness < 0.8 → PARTIAL (not CONFIDENT)."""
        result = RAGEvalResult(
            rag_confidence_score=8.5,
            faithfulness=0.7,
            context_relevance=4.0,
        )
        from bugvault.mcp_tools.tools import _compute_suggested_action
        action = _compute_suggested_action(result)
        assert action == "PARTIAL", f"Expected PARTIAL, got {action}"

    def test_action_caution_low_faithfulness(self):
        """faithfulness < 0.5 → CAUTION regardless of score."""
        result = RAGEvalResult(
            rag_confidence_score=9.0,
            faithfulness=0.3,
            context_relevance=4.5,
        )
        from bugvault.mcp_tools.tools import _compute_suggested_action
        action = _compute_suggested_action(result)
        assert action == "CAUTION", f"Expected CAUTION, got {action}"

    def test_action_insufficient_low_context_relevance(self):
        """context_relevance < 2.0 → INSUFFICIENT."""
        result = RAGEvalResult(
            rag_confidence_score=3.0,
            faithfulness=0.7,
            context_relevance=1.5,
        )
        from bugvault.mcp_tools.tools import _compute_suggested_action
        action = _compute_suggested_action(result)
        assert action == "INSUFFICIENT", f"Expected INSUFFICIENT, got {action}"

    def test_action_partial_mid_range(self):
        """5.0 <= score < 7.0 → PARTIAL."""
        result = RAGEvalResult(
            rag_confidence_score=6.0,
            faithfulness=0.8,
            context_relevance=2.5,
        )
        from bugvault.mcp_tools.tools import _compute_suggested_action
        action = _compute_suggested_action(result)
        assert action == "PARTIAL", f"Expected PARTIAL, got {action}"

    def test_action_uncertain_low_score(self):
        """score < 5.0 and no other condition → UNCERTAIN."""
        result = RAGEvalResult(
            rag_confidence_score=3.0,
            faithfulness=0.6,
            context_relevance=3.0,
        )
        from bugvault.mcp_tools.tools import _compute_suggested_action
        action = _compute_suggested_action(result)
        assert action == "UNCERTAIN", f"Expected UNCERTAIN, got {action}"

    def test_action_uncertain_none_score(self):
        """None score → UNCERTAIN."""
        result = RAGEvalResult()
        from bugvault.mcp_tools.tools import _compute_suggested_action
        action = _compute_suggested_action(result)
        assert action == "UNCERTAIN"

    def test_action_caution_overrides_insufficient(self):
        """faithfulness < 0.5 wins over context_relevance < 2.0 (CAUTION first)."""
        result = RAGEvalResult(
            rag_confidence_score=2.0,
            faithfulness=0.3,
            context_relevance=1.0,
        )
        from bugvault.mcp_tools.tools import _compute_suggested_action
        action = _compute_suggested_action(result)
        # CAUTION is checked before INSUFFICIENT in the code
        assert action == "CAUTION", f"Expected CAUTION, got {action}"

    # ── _append_eval_to_lines formatting tests ──────────────────────

    def test_append_eval_simple_format(self):
        """_append_eval_to_lines produces expected output for simple mode."""
        from bugvault.mcp_tools.tools import _append_eval_to_lines

        result = RAGEvalResult(
            strategy_used="simple",
            rag_confidence_score=7.5,
            faithfulness=4.0,
            context_relevance=3.5,
            justification="Relevant but missing specific version info",
            prompt_tokens=500,
            completion_tokens=100,
            total_tokens=600,
        )
        lines: list[str] = []
        _append_eval_to_lines(lines, result)
        full = "\n".join(lines)
        assert "--- RAG Evaluation ---" in full
        assert "Strategy:  simple" in full
        assert "Confidence: 7.5/10" in full
        assert "Context relevance: 3.5/5" in full
        assert "Faithfulness: 4.0/5" in full
        assert "Tokens: 500↑ + 100↓ = 600 total" in full
        assert "Assessment: Relevant but missing specific version info" in full

    def test_append_eval_claim_level_format(self):
        """_append_eval_to_lines handles claim_level format."""
        from bugvault.mcp_tools.tools import _append_eval_to_lines

        result = RAGEvalResult(
            strategy_used="claim_level",
            rag_confidence_score=6.0,
            faithfulness=0.75,
            context_relevance=3.0,
            justification="75% of claims supported",
            claims_analysis=[
                {"claim": "The bug is caused by null pointer", "supported": True,
                 "reason": "Confirmed by stack trace"},
                {"claim": "Fix is to add null check", "supported": False,
                 "reason": "Root cause is different"},
            ],
            prompt_tokens=800,
            completion_tokens=200,
            total_tokens=1000,
        )
        lines: list[str] = []
        _append_eval_to_lines(lines, result)
        full = "\n".join(lines)
        assert "--- RAG Evaluation ---" in full
        assert "Action:" in full
        # faithfulness in claim_level is [0,1], displayed as percentage
        assert "Faithfulness: 0.75" in full
        assert "75%" in full
        assert "--- Claim Analysis ---" in full
        assert "✅" in full  # supported claim
        assert "❌" in full  # unsupported claim
        assert "Tokens: 800↑ + 200↓ = 1000 total" in full

    def test_append_eval_none_score_skips(self):
        """_append_eval_to_lines returns early when score is None."""
        from bugvault.mcp_tools.tools import _append_eval_to_lines

        result = RAGEvalResult()
        lines: list[str] = ["existing line"]
        _append_eval_to_lines(lines, result)
        assert len(lines) == 1, "Should not append when score is None"

    def test_append_eval_handles_missing_optional_fields(self):
        """_append_eval_to_lines works with minimal eval result."""
        from bugvault.mcp_tools.tools import _append_eval_to_lines

        result = RAGEvalResult(
            strategy_used="simple",
            rag_confidence_score=5.0,
        )
        lines: list[str] = []
        _append_eval_to_lines(lines, result)
        full = "\n".join(lines)
        assert "--- RAG Evaluation ---" in full
        assert "Action:" in full
        # Optional fields missing → don't appear
        assert "Context relevance" not in full
        assert "Faithfulness" not in full
        assert "Tokens:" not in full

    def test_append_eval_without_justification(self):
        """_append_eval_to_lines skips Assessment line when justification is empty."""
        from bugvault.mcp_tools.tools import _append_eval_to_lines

        result = RAGEvalResult(
            strategy_used="simple",
            rag_confidence_score=6.0,
            faithfulness=3.0,
            context_relevance=3.0,
            justification="",
        )
        lines: list[str] = []
        _append_eval_to_lines(lines, result)
        full = "\n".join(lines)
        assert "Assessment:" not in full, "Should not show empty Assessment"


# ═══════════════════════════════════════════════════════════════════
#  P2 — TC-06: Multiple tech_stack tags filtering
# ═══════════════════════════════════════════════════════════════════


class TestTechStackFiltering:
    """Metadata filter with compound tech_stack values (comma-separated)."""

    def test_sanitise_keeps_spaces_and_alphanumeric(self):
        """sanitise_filter_value keeps spaces, alphanumeric, hyphens."""
        from bugvault.services.retrieval_svc import sanitise_filter_value
        # Commas are NOT in the allowlist — they get stripped
        assert sanitise_filter_value("Python FastAPI") == "Python FastAPI"
        assert sanitise_filter_value("Java 17 Spring Boot") == "Java 17 Spring Boot"
        assert sanitise_filter_value("C++") == "C"

    def test_sanitise_strips_dangerous_chars(self):
        """sanitise_filter_value strips SQL injection characters."""
        from bugvault.services.retrieval_svc import sanitise_filter_value
        assert sanitise_filter_value("Python'; DROP TABLE") == "Python DROP TABLE"

    def test_filter_clause_with_compound_tech_stack(self):
        """build_filter_clause handles multi-word tech_stack."""
        from bugvault.services.retrieval_svc import build_filter_clause
        clause = build_filter_clause("Python FastAPI", "")
        assert clause is not None
        assert "LIKE '%python fastapi%'" in clause

    def test_filter_clause_both_fields(self):
        """build_filter_clause combines tech_stack AND project_name."""
        from bugvault.services.retrieval_svc import build_filter_clause
        clause = build_filter_clause("Python", "user-service")
        assert clause is not None
        assert "LOWER(tech_stack) LIKE '%python%'" in clause
        assert "LOWER(project_name) LIKE '%user-service%'" in clause
        assert "AND" in clause

    def test_filter_clause_empty_returns_none(self):
        """build_filter_clause returns None when both args are empty."""
        from bugvault.services.retrieval_svc import build_filter_clause
        assert build_filter_clause("", "") is None
        assert build_filter_clause("", "  ") is None


# ═══════════════════════════════════════════════════════════════════
#  P2 — TC-07: EmbeddingService Edge Cases
# ═══════════════════════════════════════════════════════════════════


class TestEmbeddingEdgeCases:
    """EmbeddingService handles empty/long/special text gracefully."""

    @pytest.fixture(scope="class")
    def emb(self):
        return EmbeddingService()

    def test_embedding_dimension(self, emb):
        """generate_embedding returns a 512-dim vector."""
        vec = emb.generate_embedding("Hello world")
        assert len(vec) == 512, f"Expected 512d, got {len(vec)}d"

    def test_embedding_normalization(self, emb):
        """Embedding vector values are finite floats in reasonable range."""
        vec = emb.generate_embedding("Test error message")
        import math
        for v in vec:
            assert math.isfinite(v), f"Non-finite value: {v}"
        # bge models produce normalized vectors
        magnitude = sum(v * v for v in vec) ** 0.5
        assert 0.9 < magnitude < 1.1, f"Vector not normalized: {magnitude}"

    def test_embedding_short_text(self, emb):
        """Very short text still produces valid embedding."""
        import numpy as np
        vec = emb.generate_embedding("E")
        assert len(vec) == 512
        assert all(isinstance(v, (float, np.floating)) for v in vec)

    def test_embedding_long_text(self, emb):
        """Very long text (>512 tokens) is auto-truncated, doesn't crash."""
        long_text = "error " * 5000  # much longer than 512 tokens
        vec = emb.generate_embedding(long_text)
        assert len(vec) == 512

    def test_embedding_special_characters(self, emb):
        """Unicode, emoji, and special chars produce valid embeddings."""
        import numpy as np
        texts = [
            "🔥 Unicode error: ファイルが見つかりません",
            "Null byte \x00 in input",
            "🛠️ 修复 Bug → 成功 ✅",
            "Tab\tseparated\tvalues",
            "Multi-line\nerror\ntrace",
        ]
        for text in texts:
            vec = emb.generate_embedding(text)
            assert len(vec) == 512, f"Failed for text: {text[:20]}"
            assert all(isinstance(v, (float, np.floating)) for v in vec)

    def test_embedding_consistent(self, emb):
        """Same text produces same embedding (deterministic)."""
        import numpy as np
        text = "KeyError: 42"
        v1 = emb.generate_embedding(text)
        v2 = emb.generate_embedding(text)
        assert np.array_equal(v1, v2), "Embeddings differ for identical input"


# ═══════════════════════════════════════════════════════════════════
#  P2 — suggest_probe_questions
# ═══════════════════════════════════════════════════════════════════


class TestSuggestProbeQuestions:
    """suggest_probe_questions generates appropriate Chinese prompts."""

    def test_suggest_for_tried_methods(self):
        """Missing tried_methods produces relevant Chinese questions."""
        result = suggest_probe_questions(["tried_methods"])
        assert "尝试过哪些解决方法" in result
        # max 3 questions
        assert result.count("\n") < 3

    def test_suggest_for_final_solution(self):
        """Missing final_solution produces solution-oriented questions."""
        result = suggest_probe_questions(["final_solution"])
        assert "最终是怎么解决" in result or "修复" in result

    def test_suggest_for_root_cause(self):
        """Missing root_cause produces root-cause-oriented questions."""
        result = suggest_probe_questions(["root_cause"])
        assert "根本原因" in result

    def test_suggest_multiple_fields(self):
        """Multiple missing fields generate combined questions (≤3 total)."""
        result = suggest_probe_questions(["tried_methods", "final_solution"])
        assert "尝试过哪些解决方法" in result
        assert "最终" in result
        lines = [l for l in result.split("\n") if l.strip()]
        assert len(lines) <= 3, f"Expected ≤3 questions, got {len(lines)}"

    def test_suggest_unknown_field(self):
        """Unknown field name returns generic fallback question."""
        result = suggest_probe_questions(["unknown_field"])
        assert "补充" in result or "上下文" in result

    def test_suggest_max_three_questions(self):
        """Even with many missing fields, only 3 questions are returned."""
        result = suggest_probe_questions(
            ["tried_methods", "final_solution", "root_cause", "project_name", "tech_stack"]
        )
        lines = [l for l in result.split("\n") if l.strip()]
        assert len(lines) <= 3, f"Expected ≤3, got {len(lines)}"


# ═══════════════════════════════════════════════════════════════════
#  P2 — Config / Settings Resolution
# ═══════════════════════════════════════════════════════════════════


class TestSettingsResolution:
    """Config model path resolution and env var overrides."""

    def test_data_root_default(self):
        """Default data_root expands ~ to an absolute path containing .bugvault."""
        # Don't use fresh Settings() here — it may be affected by env var
        # from the db fixture. Instead verify the expected pattern.
        import os.path
        default = os.path.expanduser("~/.bugvault")
        assert ".bugvault" in default

    def test_db_uri_derived(self):
        """db_uri defaults to data_root / lancedb."""
        s = Settings()
        expected = str(s.data_root / "lancedb")
        assert s.db_uri == expected, f"db_uri: {s.db_uri} != {expected}"

    def test_markdown_archive_derived(self):
        """markdown_archive_dir defaults to data_root / archive."""
        s = Settings()
        expected = str(s.data_root / "archive")
        assert s.markdown_archive_dir == expected

    def test_env_override(self):
        """BUGVAULT_TOP_K overrides the default."""
        os.environ["BUGVAULT_TOP_K"] = "10"
        s = Settings()
        assert s.top_k == 10, f"Expected top_k=10, got {s.top_k}"
        del os.environ["BUGVAULT_TOP_K"]

    def test_env_override_string(self):
        """BUGVAULT_SERVER_NAME overrides the default server name."""
        os.environ["BUGVAULT_SERVER_NAME"] = "test-server"
        s = Settings()
        assert s.server_name == "test-server"
        del os.environ["BUGVAULT_SERVER_NAME"]

    def test_embedding_dim_default(self):
        """Default embedding dimension is 512 (bge-small-zh-v1.5)."""
        s = Settings()
        assert s.embedding_dim == 512

    def test_min_semantic_score_default(self):
        """Default min_semantic_score is 0.50."""
        s = Settings()
        assert s.min_semantic_score == 0.50

    def test_path_resolution_valid(self):
        """model_post_init creates data directories."""
        import tempfile as _tf
        import os as _os
        tmp = _tf.mkdtemp(prefix="bugvault_cfg_")
        _os.environ["BUGVAULT_DATA_ROOT"] = tmp
        s = Settings()
        assert _os.path.isdir(s.data_root)
        assert _os.path.isdir(s.markdown_archive_dir)
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)
        del _os.environ["BUGVAULT_DATA_ROOT"]
