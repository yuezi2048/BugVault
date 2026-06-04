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
#  Shared helpers
# ===================================================================

class TestFormatContext:
    """Test the format_context helper."""

    def test_format_context_basic(self):
        from bugvault.services.rag_evaluator_svc import format_context

        results = [
            {"bug_title": "Bug A", "error_log_snippet": "Error A", "final_solution": "Fix A"},
            {"bug_title": "Bug B", "error_log_snippet": "Error B", "final_solution": "Fix B"},
        ]
        context = format_context(results, top_k=3)
        assert "Document 1" in context
        assert "Document 2" in context
        assert "Bug A" in context
        assert "Fix B" in context
        assert "Document 3" not in context  # only 2 results, top_k=3

    def test_format_context_respects_top_k(self):
        from bugvault.services.rag_evaluator_svc import format_context

        results = [
            {"bug_title": f"Bug {i}", "error_log_snippet": "", "final_solution": ""}
            for i in range(5)
        ]
        context = format_context(results, top_k=2)
        assert "Document 1" in context
        assert "Document 2" in context
        assert "Document 3" not in context

    def test_format_context_handles_missing_fields(self):
        from bugvault.services.rag_evaluator_svc import format_context

        results = [{"bug_title": "Only Title"}]
        context = format_context(results, top_k=5)
        assert "Only Title" in context
        assert "Error:" in context  # empty string but key exists via .get()


class TestExtractTitles:
    """Test the _extract_titles helper."""

    def test_extract_titles(self):
        from bugvault.services.rag_evaluator_svc import _extract_titles

        context = (
            "Document 1:\n"
            "Title: Bug A\n"
            "Error: ...\n"
            "\n"
            "Document 2:\n"
            "Title: Bug B\n"
            "Error: ...\n"
        )
        titles = _extract_titles(context)
        assert titles == ["Bug A", "Bug B"]

    def test_extract_titles_empty(self):
        from bugvault.services.rag_evaluator_svc import _extract_titles

        assert _extract_titles("No titles here") == []


# ===================================================================
#  SimpleRAGEvalStrategy
# ===================================================================

class TestSimpleRAGEvalStrategy:
    """Test SimpleRAGEvalStrategy parsing and prompt building (no live API)."""

    def test_parse_valid_json(self):
        from bugvault.services.rag_evaluator_svc import SimpleRAGEvalStrategy

        raw = (
            '{"context_relevance": 4.0, "faithfulness": 3.5, '
            '"justification": "Doc 2 is partially off-topic."}'
        )
        result = SimpleRAGEvalStrategy._parse_response(raw)
        assert result.rag_confidence_score == 7.5  # 4.0 + 3.5
        assert result.context_relevance == 4.0
        assert result.faithfulness == 3.5
        assert "off-topic" in (result.evaluation or "")
        assert result.strategy_used == "simple"  # default

    def test_parse_with_markdown_fences(self):
        from bugvault.services.rag_evaluator_svc import SimpleRAGEvalStrategy

        raw = (
            '```json\n{"context_relevance": 3.0, "faithfulness": 4.0, '
            '"justification": "Relevant but verbose."}\n```'
        )
        result = SimpleRAGEvalStrategy._parse_response(raw)
        assert result.rag_confidence_score == 7.0  # 3.0 + 4.0
        assert result.context_relevance == 3.0
        assert result.faithfulness == 4.0

    def test_parse_invalid_json_returns_fallback(self):
        from bugvault.services.rag_evaluator_svc import SimpleRAGEvalStrategy

        result = SimpleRAGEvalStrategy._parse_response("not json at all")
        assert result.rag_confidence_score == 0.0
        assert result.evaluation == "parse_error"

    def test_parse_clamps_scores(self):
        from bugvault.services.rag_evaluator_svc import SimpleRAGEvalStrategy

        raw = (
            '{"context_relevance": 10.0, "faithfulness": -1.0, '
            '"justification": "Out of range test."}'
        )
        result = SimpleRAGEvalStrategy._parse_response(raw)
        assert result.context_relevance == 5.0  # clamped
        assert result.faithfulness == 0.0  # clamped

    def test_build_prompt_contains_query_and_context(self):
        from bugvault.services.rag_evaluator_svc import SimpleRAGEvalStrategy

        strategy = SimpleRAGEvalStrategy(
            api_key="sk-test", model="gpt-4o-mini",
            base_url="https://api.openai.com/v1",
            top_k=3, timeout=15.0,
            log_path=Path("/tmp/test_rag_eval.jsonl"),
        )
        context = (
            "Document 1:\n"
            "Title: test\n"
            "Error: err\n"
            "Solution: sol"
        )
        messages = strategy._build_prompt("KeyError on missing key", context)
        assert len(messages) == 2
        assert messages[1]["role"] == "user"
        assert "KeyError on missing key" in messages[1]["content"]
        assert "test" in messages[1]["content"]


# ===================================================================
#  ClaimLevelRAGEvalStrategy
# ===================================================================

class TestClaimLevelRAGEvalStrategy:
    """Test ClaimLevelRAGEvalStrategy parsing and prompt building (no live API)."""

    def test_parse_valid_claims(self):
        from bugvault.services.rag_evaluator_svc import ClaimLevelRAGEvalStrategy

        raw = (
            '{\n'
            '  "claims_analysis": [\n'
            '    {"claim": "ValueError is raised on missing key", "supported": true, "reason": "Explicitly stated in doc 1"},\n'
            '    {"claim": "Python 3.11+ required", "supported": false, "reason": "No version info in retrieved docs"},\n'
            '    {"claim": "Use .get() to avoid", "supported": true, "reason": "Mentioned in solution section"}\n'
            '  ],\n'
            '  "faithfulness": 0.67,\n'
            '  "context_relevance": 4.0,\n'
            '  "justification": "One unsupported claim about version requirement."\n'
            '}'
        )
        result = ClaimLevelRAGEvalStrategy._parse_claim_response(raw, "test query")
        # 2 out of 3 supported → 0.6667
        assert result.faithfulness == pytest.approx(0.6667, rel=1e-3)
        assert result.context_relevance == 4.0
        assert result.rag_confidence_score == pytest.approx(
            0.6667 * 5.0 + 4.0, rel=1e-3
        )  # faithfulness*5 + cr
        assert result.claims_analysis is not None
        assert len(result.claims_analysis) == 3
        # strategy_used is set by evaluate(), not the static parser
        # assert result.strategy_used == "claim_level"

    def test_parse_empty_claims(self):
        from bugvault.services.rag_evaluator_svc import ClaimLevelRAGEvalStrategy

        raw = (
            '{\n'
            '  "claims_analysis": [],\n'
            '  "faithfulness": 0.0,\n'
            '  "context_relevance": 2.0,\n'
            '  "justification": "No relevant documents found."\n'
            '}'
        )
        result = ClaimLevelRAGEvalStrategy._parse_claim_response(raw, "test query")
        assert result.faithfulness == 0.0
        assert result.context_relevance == 2.0
        assert result.claims_analysis == []

    def test_parse_invalid_json_returns_parse_error(self):
        from bugvault.services.rag_evaluator_svc import ClaimLevelRAGEvalStrategy

        result = ClaimLevelRAGEvalStrategy._parse_claim_response(
            "not json at all", "query"
        )
        assert result.rag_confidence_score == 0.0
        assert result.evaluation == "parse_error"
        assert result.claims_analysis == []

    def test_build_prompt_contains_claim_instructions(self):
        from bugvault.services.rag_evaluator_svc import ClaimLevelRAGEvalStrategy

        strategy = ClaimLevelRAGEvalStrategy(
            api_key="sk-test", model="gpt-4o-mini",
            base_url="https://api.openai.com/v1",
            top_k=3, timeout=15.0,
            log_path=Path("/tmp/test_rag_eval.jsonl"),
        )
        messages = strategy._build_claim_prompt(
            "KeyError test",
            "Document 1:\nTitle: test\nError: err\nSolution: sol",
        )
        assert len(messages) == 2
        content = messages[0]["content"]
        assert "Claim Extraction" in content
        assert "Claim Verification" in content
        assert "claims_analysis" in content
        user_content = messages[1]["content"]
        assert "KeyError test" in user_content
        assert "test" in user_content

    def test_parse_handles_missing_claims_key(self):
        """LLM output missing claims_analysis key should not crash."""
        from bugvault.services.rag_evaluator_svc import ClaimLevelRAGEvalStrategy

        raw = '{"context_relevance": 4.0, "faithfulness": 0.8, "justification": "OK"}'
        result = ClaimLevelRAGEvalStrategy._parse_claim_response(raw, "query")
        assert result.claims_analysis == []
        # faithfulness is computed from claims_analysis, not from the JSON field
        # empty claims → 0.0 faithfulness
        assert result.faithfulness == 0.0
        assert result.context_relevance == 4.0


# ===================================================================
#  RAGEvaluator — facade + circuit breaker
# ===================================================================

class TestRAGEvaluatorFacade:
    """Test RAGEvaluator facade behavior, circuit breaker, and edge cases."""

    def test_disabled_returns_empty(self):
        """When enable_rag_eval is False, evaluate returns None fields."""
        import asyncio

        from bugvault.config import settings
        from bugvault.services.rag_evaluator_svc import RAGEvaluator

        old = settings.enable_rag_eval
        settings.enable_rag_eval = False
        old_key = settings.eval_llm_api_key
        settings.eval_llm_api_key = "sk-test"
        try:
            evaluator = RAGEvaluator()
            result = asyncio.run(
                evaluator.evaluate("test query", "some context", "simple")
            )
            assert result.rag_confidence_score is None
            assert result.evaluation is None
            assert result.strategy_used == "simple"
        finally:
            settings.enable_rag_eval = old
            settings.eval_llm_api_key = old_key

    def test_no_api_key_returns_empty(self):
        """When api_key is empty, evaluate returns empty result."""
        import asyncio

        from bugvault.config import settings
        from bugvault.services.rag_evaluator_svc import RAGEvaluator

        old = settings.enable_rag_eval
        settings.enable_rag_eval = True
        old_key = settings.eval_llm_api_key
        settings.eval_llm_api_key = ""
        try:
            evaluator = RAGEvaluator()
            result = asyncio.run(
                evaluator.evaluate("test query", "context", "simple")
            )
            assert result.rag_confidence_score is None
        finally:
            settings.enable_rag_eval = old
            settings.eval_llm_api_key = old_key


# ===================================================================
#  Metadata filter helpers
# ===================================================================

class TestMetadataFilter:
    """Test _sanitise_filter_value and _build_filter_clause."""

    # ── _sanitise_filter_value ───────────────────────────────────

    def test_sanitise_keeps_valid_chars(self):
        from bugvault.mcp_tools.tools import _sanitise_filter_value

        assert _sanitise_filter_value("Python 3.13") == "Python 3.13"
        assert _sanitise_filter_value("my-project_v2") == "my-project_v2"

    def test_sanitise_strips_sql_syntax(self):
        from bugvault.mcp_tools.tools import _sanitise_filter_value

        # Semi-colons and quotes stripped; English words (DROP, TABLE) harmless
        result = _sanitise_filter_value("Python'; DROP TABLE; --")
        assert "'" not in result, f"quotes should be stripped: {result}"
        assert ";" not in result, f"semicolons should be stripped: {result}"
        # Only alnum, space, underscore, hyphen, dot survive
        assert result == "Python DROP TABLE --"

    def test_sanitise_empty_returns_empty(self):
        from bugvault.mcp_tools.tools import _sanitise_filter_value

        assert _sanitise_filter_value("") == ""
        assert _sanitise_filter_value("   ") == ""

    # ── _build_filter_clause ─────────────────────────────────────

    def test_filter_tech_stack_only(self):
        from bugvault.mcp_tools.tools import _build_filter_clause

        clause = _build_filter_clause("Python", "")
        assert clause is not None
        assert "LOWER(tech_stack)" in clause
        assert "python" in clause

    def test_filter_project_only(self):
        from bugvault.mcp_tools.tools import _build_filter_clause

        clause = _build_filter_clause("", "order-svc")
        assert clause is not None
        assert "LOWER(project_name)" in clause
        assert "order-svc" in clause

    def test_filter_both_fields(self):
        from bugvault.mcp_tools.tools import _build_filter_clause

        clause = _build_filter_clause("Go", "api-gateway")
        assert clause is not None
        assert "AND" in clause
        assert "LOWER(tech_stack)" in clause
        assert "LOWER(project_name)" in clause
        assert "go" in clause
        assert "api-gateway" in clause

    def test_filter_both_empty_returns_none(self):
        from bugvault.mcp_tools.tools import _build_filter_clause

        clause = _build_filter_clause("", "")
        assert clause is None

    def test_filter_case_insensitive(self):
        from bugvault.mcp_tools.tools import _build_filter_clause

        # Upper-case input should produce lower-cased LIKE value
        clause = _build_filter_clause("PYTHON", "MY-PROJECT")
        assert clause is not None
        assert "LOWER(tech_stack) LIKE '%python%'" in clause
        assert "LOWER(project_name) LIKE '%my-project%'" in clause

    def test_filter_injection_attempt_sanitised(self):
        from bugvault.mcp_tools.tools import _build_filter_clause

        clause = _build_filter_clause(
            "Python'; DROP TABLE bug_records; --",
            "project' OR '1'='1",
        )
        assert clause is not None
        # Dangerous chars sanitised — injected values are just words
        assert "drop" in clause  # 'drop' survives as harmless text inside LIKE
        assert "'DROP'" not in clause  # no standalone SQL keyword
        # Should still have valid filter structure
        assert "LOWER(tech_stack)" in clause
        assert "LOWER(project_name)" in clause
        # The injection tokens ';' and quotes are gone from the sanitised values
        assert "';'" not in clause