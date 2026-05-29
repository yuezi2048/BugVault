"""Tests for BugVault core models, services, and utilities."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest
from pydantic import ValidationError

from bugvault.models.bug_record import BugRecord
from bugvault.models.reflection_rule import PreventionRule
from bugvault.models.rag_eval_result import RAGEvalResult
from bugvault.services.archive_svc import (
    _clean_timestamp,
    _clean_tech_stack,
    _strip_llm_prefix,
    record_to_markdown,
    write_markdown_archive,
)
from bugvault.services.retrieval_svc import time_decay_score
from bugvault.utils.text_utils import StackTraceTruncator


# ===================================================================
#  BugRecord model
# ===================================================================

class TestBugRecord:
    def test_minimal_valid_record(self):
        r = BugRecord(
            bug_title="test bug",
            error_log_snippet="ValueError: something broke",
            tried_methods="restarted server",
            final_solution="fixed config",
        )
        assert r.bug_title == "test bug"
        assert r.create_time
        assert r.project_name is None

    def test_missing_required_fields_are_whitespace_only(self):
        r = BugRecord(
            bug_title="test",
            error_log_snippet="err",
            tried_methods="  ",
            final_solution="worked",
        )
        missing = r.missing_required_fields()
        assert "tried_methods" in missing
        assert "final_solution" not in missing

    def test_all_fields(self):
        r = BugRecord(
            bug_title="full bug",
            error_log_snippet="error",
            tried_methods="restart",
            final_solution="patch",
            project_name="myapp",
            tech_stack="Python 3.13, FastAPI",
            root_cause="race condition",
        )
        assert r.project_name == "myapp"
        assert r.root_cause == "race condition"
        assert r.to_search_text() == "full bug\nerror\nrestart\npatch\nrace condition"

    def test_probe_round_limits(self):
        r = BugRecord(
            bug_title="test",
            error_log_snippet="err",
            tried_methods="x",
            final_solution="y",
        )
        assert not r.probe_round_exhausted()
        for _ in range(r.MAX_PROBE_ROUNDS):
            r.increment_probe()
        assert r.probe_round_exhausted()

    def test_ansi_escape_removal(self):
        r = BugRecord(
            bug_title="test",
            error_log_snippet="\x1b[31mERROR\x1b[0m: \x1b[1mcrash\x1b[0m",
            tried_methods="x",
            final_solution="y",
        )
        assert "\x1b" not in r.error_log_snippet
        assert "ERROR" in r.error_log_snippet

    def test_title_max_length(self):
        with pytest.raises(ValidationError):
            BugRecord(
                bug_title="x" * 300,
                error_log_snippet="err",
                tried_methods="x",
                final_solution="y",
            )


# ===================================================================
#  StackTraceTruncator
# ===================================================================

SAMPLE_TRACE = "\n".join([
    "java.lang.NullPointerException",
    "\tat com.mycompany.app.Service.process(Service.java:42)",
    "\tat com.mycompany.app.Service.handle(Service.java:88)",
    "\tat org.spring.web.servlet.FrameworkServlet.doGet(FrameworkServlet.java:900)",
    "\tat javax.servlet.http.HttpServlet.service(HttpServlet.java:660)",
    "\tat org.apache.catalina.core.StandardWrapperValve.invoke(WrapperValve.java:200)",
    "\tat org.apache.coyote.http11.Http11Processor.process(Http11Processor.java:500)",
    "\tat org.apache.catalina.connector.CoyoteAdapter.service(CoyoteAdapter.java:350)",
    "\tat org.apache.coyote.http11.Http11Processor.service(Http11Processor.java:380)",
    "\tat org.apache.catalina.core.StandardEngineValve.invoke(EngineValve.java:120)",
    "\tat org.apache.catalina.valves.ErrorReportValve.invoke(ErrorReportValve.java:90)",
    "\tat org.apache.catalina.core.StandardHostValve.invoke(HostValve.java:140)",
    "\tat org.apache.catalina.valves.AccessLogValve.invoke(AccessLogValve.java:70)",
    "\tat org.apache.catalina.core.StandardPipeline.invoke(Pipeline.java:80)",
    "\tat org.apache.catalina.core.StandardWrapperValve.invoke(WrapperValve.java:150)",
    "\tat org.apache.catalina.core.StandardContextValve.invoke(ContextValve.java:100)",
    "Caused by: java.io.IOException: connection reset",
    "\tat com.mycompany.app.db.Database.connect(Database.java:15)",
    "\tat com.mycompany.app.db.Database.query(Database.java:30)",
    "\tat com.mycompany.app.Service.process(Service.java:40)",
    "\t... 15 common frames omitted",
])


class TestStackTraceTruncator:
    def test_level_3_raw(self):
        t = StackTraceTruncator(raw=SAMPLE_TRACE)
        assert t.truncate(level=3) == SAMPLE_TRACE

    def test_level_1_truncation_with_gap(self):
        """A trace with non-project frames between head and project frames."""
        trace = "\n".join([
            "--- logging start ---",
            "INFO: loading config",
            "WARNING: deprecated flag",
            "--- stack trace ---",
            "Traceback: ValueError",
            '\tat django.core.handlers.exception(wsgi.py:100)',
            '\tat django.middleware.security(security.py:50)',
            '\tat django.contrib.sessions.middleware(sessions.py:30)',
            '\tat django.core.handlers.base(base.py:200)',
            '\tat django.urls.resolvers(resolvers.py:400)',
            '\tat django.http.request(request.py:150)',
            '\tat urllib3.connectionpool(connectionpool.py:300)',
            '\tat requests.adapters(adapters.py:200)',
            '\tat httpx._transport(transport.py:100)',
            '\tat httpx._client.send(client.py:50)',
            '\tat httpcore._sync.connection(connection.py:30)',
            'Caused by: KeyError: "missing_field"',
            '\tat com.mycompany.app.process(foo.py:42)',
            '\tat com.mycompany.app.cleanup(foo.py:88)',
            '\tat com.mycompany.app.validate(foo.py:120)',
        ])
        t = StackTraceTruncator(raw=trace)
        result = t.truncate(level=1)
        assert "ValueError" in result, f"missing ValueError in:\n{result}"
        # Non-project lines between head and project block should not appear
        assert "urllib3" not in result or "Caused by" in result
        # Project frames should remain
        assert "com.mycompany.app.process" in result
        assert len(result) < len(trace), f"expected truncation, got {len(result)} >= {len(trace)}"

    def test_no_duplicates_in_truncated_output(self):
        """Verify the 'Caused by' line appears exactly once."""
        t = StackTraceTruncator(raw=SAMPLE_TRACE)
        result = t.truncate(level=1)
        assert result.count("Caused by") == 1

    def test_empty_trace(self):
        t = StackTraceTruncator(raw="")
        assert t.truncate() == ""

    def test_short_trace_not_truncated(self):
        short = "Error\n    at main.py:1"
        t = StackTraceTruncator(raw=short)
        assert t.truncate() == short


# ===================================================================
#  Retrieval service
# ===================================================================

class TestTimeDecayScore:
    def test_now_is_approx_1(self):
        now = datetime.now(timezone.utc).isoformat()
        score = time_decay_score(now)
        assert score > 0.999

    def test_empty_string_is_neutral(self):
        assert time_decay_score("") == 0.5

    def test_decay_over_time(self):
        past = datetime(2024, 1, 1, tzinfo=timezone.utc).isoformat()
        score = time_decay_score(past, half_life_days=90)
        assert 0.0 < score < 0.5

    def test_invalid_date_is_neutral(self):
        assert time_decay_score("not-a-date") == 0.5


# ===================================================================
#  PreventionRule model
# ===================================================================

class TestPreventionRule:
    def test_minimal_valid(self):
        rule = PreventionRule(
            rule_number=1,
            error_category="code_logic_error",
            preventive_rule="Always check for None before .get()",
            reflection_text="Forgot that dict.get() can return None",
            created_at="2026-01-01 12:00 UTC",
        )
        assert rule.rule_number == 1
        assert rule.error_category == "code_logic_error"

    def test_error_category_enum_values(self):
        valid = {
            "understanding_bias",
            "code_logic_error",
            "api_misuse",
            "environment_issue",
            "other",
        }
        for cat in valid:
            r = PreventionRule(
                rule_number=1, error_category=cat,
                preventive_rule="x", reflection_text="x",
                created_at="now",
            )
            assert r.error_category == cat


# ===================================================================
#  RAGEvalResult model
# ===================================================================

class TestRAGEvalResult:
    def test_empty_defaults(self):
        r = RAGEvalResult()
        assert r.rag_confidence_score is None
        assert r.evaluation is None

    def test_full_result(self):
        r = RAGEvalResult(rag_confidence_score=9.2, evaluation="highly_relevant")
        assert r.rag_confidence_score == 9.2
        assert r.evaluation == "highly_relevant"


# ===================================================================
#  Archive service helpers
# ===================================================================

class TestArchiveHelpers:
    def test_clean_timestamp_utc(self):
        result = _clean_timestamp("2026-05-29T10:27:15+00:00")
        assert result == "2026-05-29T10:27:15+00:00"

    def test_clean_timestamp_naive(self):
        result = _clean_timestamp("2026-05-29T10:27:15")
        assert result == "2026-05-29T10:27:15+00:00"

    def test_clean_timestamp_invalid(self):
        assert _clean_timestamp("garbage") == "garbage"

    def test_clean_tech_stack_none(self):
        assert _clean_tech_stack(None) == ["bug"]

    def test_clean_tech_stack_empty(self):
        assert _clean_tech_stack("") == ["bug"]

    def test_clean_tech_stack_mixed(self):
        result = _clean_tech_stack("Python 3.13, FastAPI，LanceDB")
        assert result == ["Python 3.13", "FastAPI", "LanceDB"]

    def test_strip_llm_prefix(self):
        result = _strip_llm_prefix(
            "root_cause: The issue was a race condition",
            "root_cause",
        )
        assert result == "The issue was a race condition"

    def test_strip_llm_prefix_no_match(self):
        result = _strip_llm_prefix("Just some text", "root_cause")
        assert result == "Just some text"


class TestRecordToMarkdown:
    def test_basic_structure(self):
        record = BugRecord(
            bug_title="test bug",
            error_log_snippet="ValueError: x",
            tried_methods="restart",
            final_solution="fix config",
            project_name="demo",
            tech_stack="Python",
        )
        md = record_to_markdown(record)
        assert "---" in md
        assert "test bug" in md
        assert "ValueError: x" in md
        assert "restart" in md
        assert "fix config" in md
        assert "demo" in md

    def test_with_root_cause(self):
        record = BugRecord(
            bug_title="bug with root cause",
            error_log_snippet="err",
            tried_methods="x",
            final_solution="y",
            root_cause="design flaw",
        )
        md = record_to_markdown(record)
        assert "设计 flaw" in md or "design flaw" in md

    def test_without_root_cause(self):
        record = BugRecord(
            bug_title="simple bug",
            error_log_snippet="err",
            tried_methods="x",
            final_solution="y",
        )
        md = record_to_markdown(record)
        assert "根因分析" not in md


class TestWriteMarkdownArchive:
    def test_write_to_temp_dir(self, tmp_path: Path):
        record = BugRecord(
            bug_title="archive test",
            error_log_snippet="oops",
            tried_methods="retry",
            final_solution="patch",
        )
        out = write_markdown_archive(record)
        assert out.exists()
        content = out.read_text(encoding="utf-8")
        assert "archive test" in content
        assert "oops" in content
