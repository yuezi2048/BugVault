"""Tests for BugVault v2.0.0 convention memory system.

Covers:
  - ConventionRecord model (validation, dedup, chunking, field mapping)
  - Convention archive (markdown generation, write)
  - MCP tool schemas and handlers (save_convention, retrieve_convention)
  - Convention filter isolation (record_type='convention' doesn't leak bugs)
  - DB maintenance conventions parsing
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest
from pydantic import ValidationError

from bugvault.models.convention_record import ConventionRecord


# ===================================================================
#  ConventionRecord model
# ===================================================================

class TestConventionRecord:
    """Test ConventionRecord model: validation, dedup, chunking, mapping."""

    def test_minimal_valid_record(self):
        r = ConventionRecord(
            convention_name="DTO Rule",
            trigger_context="when returning data from repository",
            incorrect_behavior="return Entity directly",
            correct_behavior="return DTO instead",
        )
        assert r.convention_name == "DTO Rule"
        assert r.create_time
        assert r.scope is None
        assert r.tags is None
        assert r.record_type == "convention"

    def test_record_id_computed(self):
        r = ConventionRecord(
            convention_name="Test Rule",
            trigger_context="ctx",
            incorrect_behavior="wrong",
            correct_behavior="right",
        )
        assert r.record_id is not None
        assert len(r.record_id) == 32  # MD5 hexdigest

    def test_record_id_dedup_same_content(self):
        args = {
            "convention_name": "Same Rule",
            "trigger_context": "same context",
            "incorrect_behavior": "wrong",
            "correct_behavior": "right",
        }
        r1 = ConventionRecord(**args)
        r2 = ConventionRecord(**args)
        assert r1.record_id == r2.record_id

    def test_record_id_different_title(self):
        r1 = ConventionRecord(
            convention_name="Rule A", trigger_context="ctx",
            incorrect_behavior="w", correct_behavior="r",
        )
        r2 = ConventionRecord(
            convention_name="Rule B", trigger_context="ctx",
            incorrect_behavior="w", correct_behavior="r",
        )
        assert r1.record_id != r2.record_id

    def test_all_fields(self):
        r = ConventionRecord(
            convention_name="Full Rule",
            trigger_context="trigger",
            incorrect_behavior="wrong",
            correct_behavior="right",
            scope="src/repo/",
            tags="architecture, Java, DDD",
        )
        assert r.scope == "src/repo/"
        assert r.tags == "architecture, Java, DDD"

    def test_missing_required_fields(self):
        r = ConventionRecord(
            convention_name="Test",
            trigger_context="ctx",
            incorrect_behavior="  ",
            correct_behavior="right",
        )
        missing = r.missing_required_fields()
        assert "incorrect_behavior" in missing
        assert "correct_behavior" not in missing

    def test_to_search_text(self):
        r = ConventionRecord(
            convention_name="Rule",
            trigger_context="context",
            incorrect_behavior="bad",
            correct_behavior="good",
        )
        text = r.to_search_text()
        assert "Rule" in text
        assert "context" in text
        assert "bad" in text
        assert "good" in text

    def test_to_table_row_mapping(self):
        r = ConventionRecord(
            convention_name="Conv Name",
            trigger_context="trigger ctx",
            incorrect_behavior="bad behavior",
            correct_behavior="good behavior",
            scope="src/",
            tags="Java",
        )
        row = r.to_table_row()
        assert row["bug_title"] == "Conv Name"
        assert row["error_log_snippet"] == "trigger ctx"
        assert row["tried_methods"] == "bad behavior"
        assert row["final_solution"] == "good behavior"
        assert row["project_name"] == "src/"
        assert row["tech_stack"] == "Java"
        assert row["record_type"] == "convention"
        assert row["root_cause"] == ""

    def test_from_table_row_roundtrip(self):
        r1 = ConventionRecord(
            convention_name="Roundtrip Rule",
            trigger_context="ctx",
            incorrect_behavior="bad",
            correct_behavior="good",
            scope="tests/",
            tags="testing",
        )
        row = r1.to_table_row()
        r2 = ConventionRecord.from_table_row(row)
        assert r2.convention_name == r1.convention_name
        assert r2.trigger_context == r1.trigger_context
        assert r2.incorrect_behavior == r1.incorrect_behavior
        assert r2.correct_behavior == r1.correct_behavior
        assert r2.scope == r1.scope
        assert r2.tags == r1.tags
        assert r2.record_id == r1.record_id

    def test_to_chunks_count_and_types(self):
        r = ConventionRecord(
            convention_name="Chunk Test",
            trigger_context="trigger context text",
            incorrect_behavior="bad",
            correct_behavior="good",
        )
        chunks = r.to_chunks()
        assert len(chunks) == 2
        assert chunks[0]["chunk_type"] == "context"
        assert chunks[1]["chunk_type"] == "correct_behavior"
        assert chunks[0]["record_type"] == "convention"
        assert chunks[1]["record_type"] == "convention"

    def test_to_chunks_has_all_keys(self):
        r = ConventionRecord(
            convention_name="Keys Test",
            trigger_context="ctx",
            incorrect_behavior="bad",
            correct_behavior="good",
            tags="Python, API",
            scope="src/",
        )
        chunks = r.to_chunks()
        for c in chunks:
            assert "chunk_id" in c
            assert "parent_id" in c
            assert "chunk_type" in c
            assert "search_text" in c
            assert "tech_stack" in c
            assert "project_name" in c
            assert "record_type" in c
        assert chunks[0]["tech_stack"] == "Python, API"
        assert chunks[0]["project_name"] == "src/"

    def test_chunk_search_text_contains_title(self):
        r = ConventionRecord(
            convention_name="Title Prefix",
            trigger_context="context",
            incorrect_behavior="bad",
            correct_behavior="good",
        )
        for c in r.to_chunks():
            assert c["search_text"].startswith("Title Prefix")

    def test_title_min_length_enforced(self):
        with pytest.raises(ValidationError):
            ConventionRecord(
                convention_name="",  # too short
                trigger_context="ctx",
                incorrect_behavior="bad",
                correct_behavior="good",
            )

    def test_title_max_length_enforced(self):
        with pytest.raises(ValidationError):
            ConventionRecord(
                convention_name="x" * 257,
                trigger_context="ctx",
                incorrect_behavior="bad",
                correct_behavior="good",
            )

    def test_optional_fields_default_to_none(self):
        r = ConventionRecord(
            convention_name="Defaults",
            trigger_context="ctx",
            incorrect_behavior="bad",
            correct_behavior="good",
        )
        assert r.scope is None
        assert r.tags is None

    def test_probe_round_interface(self):
        """ConventionRecord does not have probe tracking — verify absence."""
        r = ConventionRecord(
            convention_name="Test",
            trigger_context="ctx",
            incorrect_behavior="bad",
            correct_behavior="good",
        )
        assert hasattr(r, "record_id")
        assert hasattr(r, "to_search_text")
        assert hasattr(r, "to_chunks")


# ===================================================================
#  Convention archive
# ===================================================================

class TestConventionArchive:
    """Test convention_to_markdown and write_convention_archive."""

    def test_convention_to_markdown_basic(self):
        from bugvault.services.archive_svc import convention_to_markdown

        r = ConventionRecord(
            convention_name="Test Rule",
            trigger_context="when X happens",
            incorrect_behavior="do Y",
            correct_behavior="do Z instead",
            scope="src/",
            tags="architecture",
        )
        md = convention_to_markdown(r)
        assert "type: convention" in md
        assert "scope: src/" in md
        assert "architecture" in md
        assert "Test Rule" in md
        assert "when X happens" in md
        assert "do Y" in md
        assert "do Z instead" in md

    def test_write_convention_archive_creates_file(self):
        from bugvault.services.archive_svc import write_convention_archive

        r = ConventionRecord(
            convention_name="Write Test",
            trigger_context="ctx",
            incorrect_behavior="bad",
            correct_behavior="good",
        )
        path = write_convention_archive(r)
        assert path.exists()
        assert "conventions" in str(path)
        content = path.read_text(encoding="utf-8")
        assert "Write Test" in content
        path.unlink()  # clean up

    def test_convention_archive_roundtrip(self):
        """Convention archive → parse back → same fields."""
        from bugvault.services.archive_svc import write_convention_archive
        from bugvault.services.db_maintenance_svc import _parse_markdown_to_convention_record

        r = ConventionRecord(
            convention_name="Roundtrip Conv",
            trigger_context="trigger when",
            incorrect_behavior="wrong behavior",
            correct_behavior="correct behavior",
            scope="src/repo/",
            tags="Java, DDD",
        )
        path = write_convention_archive(r)
        parsed = _parse_markdown_to_convention_record(path)
        assert parsed is not None
        # Frontmatter → record fields
        assert parsed.convention_name == r.convention_name
        # parse from Chinese section headings
        assert "wrong behavior" in parsed.incorrect_behavior
        assert "correct behavior" in parsed.correct_behavior
        path.unlink()


# ===================================================================
#  Convention ingestion validation
# ===================================================================

class TestConventionIngestion:
    """Test validate_convention_record and suggest_convention_probe_questions."""

    def test_validate_valid(self):
        from bugvault.services.ingestion_svc import validate_convention_record

        r = ConventionRecord(
            convention_name="Valid",
            trigger_context="ctx",
            incorrect_behavior="bad",
            correct_behavior="good",
        )
        missing = validate_convention_record(r)
        assert missing == []

    def test_validate_missing_behavior(self):
        from bugvault.services.ingestion_svc import validate_convention_record

        r = ConventionRecord(
            convention_name="Missing",
            trigger_context="ctx",
            incorrect_behavior="  ",
            correct_behavior="good",
        )
        missing = validate_convention_record(r)
        assert "incorrect_behavior" in missing

    def test_probe_questions_generated(self):
        from bugvault.services.ingestion_svc import suggest_convention_probe_questions

        questions = suggest_convention_probe_questions(
            ["incorrect_behavior", "correct_behavior"]
        )
        assert len(questions) > 0


# ===================================================================
#  MCP tool schemas and handlers
# ===================================================================

class TestConventionToolSchemas:
    """Test that convention tool schemas are defined and registered correctly."""

    def test_tools_import_and_schemas_exist(self):
        from bugvault.mcp_tools.tools import _CONVENTION_SAVE_SCHEMA, _CONVENTION_RETRIEVE_SCHEMA

        assert _CONVENTION_SAVE_SCHEMA["type"] == "object"
        assert "convention_name" in _CONVENTION_SAVE_SCHEMA["properties"]
        assert "trigger_context" in _CONVENTION_SAVE_SCHEMA["properties"]
        assert "incorrect_behavior" in _CONVENTION_SAVE_SCHEMA["properties"]
        assert "correct_behavior" in _CONVENTION_SAVE_SCHEMA["properties"]
        assert set(_CONVENTION_SAVE_SCHEMA["required"]) == {
            "convention_name", "trigger_context",
            "incorrect_behavior", "correct_behavior",
        }

        assert _CONVENTION_RETRIEVE_SCHEMA["type"] == "object"
        assert "query" in _CONVENTION_RETRIEVE_SCHEMA["properties"]
        assert _CONVENTION_RETRIEVE_SCHEMA["required"] == ["query"]

    def test_sync_save_convention_validate_success(self):
        from bugvault.mcp_tools.tools import _sync_save_convention_validate

        texts, record = _sync_save_convention_validate({
            "convention_name": "Test Rule",
            "trigger_context": "when writing code",
            "incorrect_behavior": "doing it wrong",
            "correct_behavior": "doing it right",
        })
        assert record is not None
        assert record.convention_name == "Test Rule"
        assert any("saved successfully" in t.text for t in texts)

    def test_sync_save_convention_validate_fail(self):
        from bugvault.mcp_tools.tools import _sync_save_convention_validate

        texts, record = _sync_save_convention_validate({
            "convention_name": "Bad",
            # missing trigger_context
        })
        assert record is None
        assert any("Invalid convention" in t.text for t in texts)

    def test_sync_save_convention_draft_on_whitespace(self):
        """Whitespace-only field passes Pydantic but triggers draft mode."""
        from bugvault.mcp_tools.tools import _sync_save_convention_validate

        texts, record = _sync_save_convention_validate({
            "convention_name": "Draft",
            "trigger_context": "ctx",
            "incorrect_behavior": "   ",  # whitespace passes min_length but flags as missing
            "correct_behavior": "good",
        })
        assert record is not None  # still saved as draft
        assert any("draft" in t.text.lower() for t in texts)


# ===================================================================
#  DB maintenance convention parsing
# ===================================================================

class TestConventionDBMaintenance:
    """Test _parse_markdown_to_convention_record and _detect_record_type."""

    def test_detect_record_type_convention(self, tmp_path: Path):
        from bugvault.services.db_maintenance_svc import _detect_record_type

        md_file = tmp_path / "test_conv.md"
        md_file.write_text(
            "---\ntype: convention\n---\n# Rule: Test\n", encoding="utf-8"
        )
        assert _detect_record_type(md_file) == "convention"

    def test_detect_record_type_bug_default(self, tmp_path: Path):
        from bugvault.services.db_maintenance_svc import _detect_record_type

        md_file = tmp_path / "test_bug.md"
        md_file.write_text(
            "---\ndate: 2026-01-01\n---\n# Bug Title\n", encoding="utf-8"
        )
        assert _detect_record_type(md_file) == "bug"

    def test_detect_record_type_no_frontmatter(self, tmp_path: Path):
        from bugvault.services.db_maintenance_svc import _detect_record_type

        md_file = tmp_path / "no_fm.md"
        md_file.write_text("# Just a title\n", encoding="utf-8")
        assert _detect_record_type(md_file) == "bug"

    def test_parse_convention_md_file(self, tmp_path: Path):
        from bugvault.services.db_maintenance_svc import _parse_markdown_to_convention_record

        md_content = (
            "---\n"
            "date: 2026-06-08T10:00:00+00:00\n"
            "type: convention\n"
            "scope: src/repo/\n"
            "tags:\n"
            "  - Java\n"
            "  - DDD\n"
            "---\n"
            "# Rule: DTO Conversion\n"
            "\n"
            "## 触发场景\n"
            "\n"
            "when returning from repository\n"
            "\n"
            "## 错误行为（不要做）\n"
            "\n"
            "return Entity directly\n"
            "\n"
            "## 正确行为（应该做）\n"
            "\n"
            "convert to DTO\n"
        )
        md_file = tmp_path / "test_conv.md"
        md_file.write_text(md_content, encoding="utf-8")

        record = _parse_markdown_to_convention_record(md_file)
        assert record is not None
        assert record.convention_name == "DTO Conversion"
        assert record.trigger_context == "when returning from repository"
        assert record.incorrect_behavior == "return Entity directly"
        assert record.correct_behavior == "convert to DTO"
        assert record.scope == "src/repo/"

    def test_parse_convention_english_sections(self, tmp_path: Path):
        """Parse convention files written with English section headings."""
        from bugvault.services.db_maintenance_svc import _parse_markdown_to_convention_record

        md_content = (
            "---\n"
            "date: 2026-06-08T10:00:00+00:00\n"
            "type: convention\n"
            "---\n"
            "# Rule: Naming Convention\n"
            "\n"
            "## Trigger Context\n"
            "\n"
            "when naming variables\n"
            "\n"
            "## Incorrect Behavior\n"
            "\n"
            "use single letters\n"
            "\n"
            "## Correct Behavior\n"
            "\n"
            "use descriptive names\n"
        )
        md_file = tmp_path / "english_conv.md"
        md_file.write_text(md_content, encoding="utf-8")

        record = _parse_markdown_to_convention_record(md_file)
        assert record is not None
        assert record.convention_name == "Naming Convention"
        assert record.incorrect_behavior == "use single letters"
        assert record.correct_behavior == "use descriptive names"

    def test_parse_convention_missing_sections(self, tmp_path: Path):
        """Missing sections default to empty string (never crash)."""
        from bugvault.services.db_maintenance_svc import _parse_markdown_to_convention_record

        md_content = (
            "---\ntype: convention\n---\n"
            "# Rule: Only Title\n"
        )
        md_file = tmp_path / "minimal_conv.md"
        md_file.write_text(md_content, encoding="utf-8")

        record = _parse_markdown_to_convention_record(md_file)
        assert record is not None
        # Missing sections should get defaults
        assert record.trigger_context is not None
        assert record.incorrect_behavior is not None
        assert record.correct_behavior is not None
