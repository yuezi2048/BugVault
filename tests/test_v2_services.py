"""Tests for BugVault v2 new services: ReflectionService, RAGEvaluator."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from bugvault.models.rag_eval_result import RAGEvalResult


# ===================================================================
#  ReflectionService
# ===================================================================

class TestReflectionService:
    """Test ReflectionService against a temporary CLAUDE.md file."""

    @pytest.fixture
    def svc(self, tmp_path: Path):
        """Create a ReflectionService that writes to a temp path."""
        from bugvault.services.reflection_svc import ReflectionService

        return ReflectionService(claude_md_path=tmp_path / "CLAUDE.md")

    def test_add_first_rule_creates_file(self, svc, tmp_path: Path):
        meta = svc.add_preventive_rule(
            reflection_text="Forgot to handle None from dict.get()",
            error_category="code_logic_error",
            preventive_rule="Always check .get() return for None before chaining",
        )
        assert meta["rule_number"] == 1
        assert meta["total_rules"] == 1
        assert meta["error_category"] == "code_logic_error"
        assert tmp_path.joinpath("CLAUDE.md").exists()

    def test_add_multiple_rules(self, svc):
        svc.add_preventive_rule("msg1", "understanding_bias", "rule1")
        meta2 = svc.add_preventive_rule("msg2", "api_misuse", "rule2")
        assert meta2["rule_number"] == 2
        assert meta2["total_rules"] == 2

    def test_claude_md_content_structure(self, svc, tmp_path: Path):
        svc.add_preventive_rule(
            reflection_text="Test reflection",
            error_category="environment_issue",
            preventive_rule="Test prevention",
        )
        content = tmp_path.joinpath("CLAUDE.md").read_text(encoding="utf-8")
        assert "## Bug Prevention Rules" in content
        assert "**Rule #1**" in content
        assert "[environment_issue]" in content
        assert "Test reflection" in content
        assert "Test prevention" in content

    def test_second_rule_appended_correctly(self, svc, tmp_path: Path):
        svc.add_preventive_rule("refl1", "other", "rule1")
        svc.add_preventive_rule("refl2", "code_logic_error", "rule2")
        content = tmp_path.joinpath("CLAUDE.md").read_text(encoding="utf-8")
        # Both rules should appear; rule2 after rule1
        assert content.count("**Rule #") == 2
        assert content.index("**Rule #2**") > content.index("**Rule #1**")


# ===================================================================
#  RAGEvaluator
# ===================================================================

class TestRAGEvaluator:
    """Test RAGEvaluator parsing and edge cases (no live API call)."""

    def test_disabled_returns_empty(self):
        """When enable_rag_eval is False, evaluate returns None fields."""
        from bugvault.config import settings
        from bugvault.services.rag_evaluator_svc import RAGEvaluator

        old = settings.enable_rag_eval
        settings.enable_rag_eval = False
        try:
            evaluator = RAGEvaluator()
            result = evaluator.evaluate_sync("test query", [])
            assert result.rag_confidence_score is None
            assert result.evaluation is None
        finally:
            settings.enable_rag_eval = old

    def test_empty_results_returns_empty(self):
        from bugvault.config import settings
        from bugvault.services.rag_evaluator_svc import RAGEvaluator

        old_enable = settings.enable_rag_eval
        old_key = settings.eval_llm_api_key
        settings.enable_rag_eval = True
        settings.eval_llm_api_key = "sk-test"
        try:
            evaluator = RAGEvaluator()
            result = evaluator.evaluate_sync("query", [])
            assert result.rag_confidence_score is None
        finally:
            settings.enable_rag_eval = old_enable
            settings.eval_llm_api_key = old_key

    def test_parse_valid_json(self):
        from bugvault.services.rag_evaluator_svc import RAGEvaluator

        raw = (
            '{"context_relevance": 4.0, "faithfulness": 3.5, '
            '"justification": "Doc 2 is partially off-topic."}'
        )
        result = RAGEvaluator._parse_response(raw)
        assert result.rag_confidence_score == 7.5  # 4.0 + 3.5
        assert result.context_relevance == 4.0
        assert result.faithfulness == 3.5
        assert "off-topic" in (result.evaluation or "")

    def test_parse_with_markdown_fences(self):
        from bugvault.services.rag_evaluator_svc import RAGEvaluator

        raw = (
            '```json\n{"context_relevance": 3.0, "faithfulness": 4.0, '
            '"justification": "Relevant but verbose."}\n```'
        )
        result = RAGEvaluator._parse_response(raw)
        assert result.rag_confidence_score == 7.0  # 3.0 + 4.0
        assert result.context_relevance == 3.0
        assert result.faithfulness == 4.0

    def test_parse_invalid_json_returns_fallback(self):
        from bugvault.services.rag_evaluator_svc import RAGEvaluator

        result = RAGEvaluator._parse_response("not json at all")
        assert result.rag_confidence_score == 0.0
        assert result.evaluation == "parse_error"

    def test_build_prompt_contains_query_and_results(self):
        from bugvault.services.rag_evaluator_svc import RAGEvaluator

        from bugvault.config import settings
        old_enable = settings.enable_rag_eval
        old_key = settings.eval_llm_api_key
        settings.enable_rag_eval = True
        settings.eval_llm_api_key = "sk-test"
        try:
            evaluator = RAGEvaluator()
            messages = evaluator._build_prompt(
                "KeyError on missing key",
                [{"bug_title": "test", "error_log_snippet": "err", "final_solution": "sol"}],
            )
            assert len(messages) == 2
            assert messages[1]["role"] == "user"
            assert "KeyError on missing key" in messages[1]["content"]
            assert "test" in messages[1]["content"]
        finally:
            settings.enable_rag_eval = old_enable
            settings.eval_llm_api_key = old_key