"""Tests for the RecordPersistence local-memory boundary."""

from __future__ import annotations

from bugvault.models.bug_record import BugRecord
from bugvault.models.convention_record import ConventionRecord
from bugvault.services.persistence_svc import RecordPersistence


class FakeDatabase:
    def __init__(self) -> None:
        self.parent_rows: list[dict] = []
        self.chunk_rows: list[dict] = []

    def upsert_record(self, row: dict) -> None:
        self.parent_rows.append(row)

    def upsert_chunks(self, rows: list[dict]) -> None:
        self.chunk_rows.extend(rows)


class FakeEmbeddingService:
    def __init__(self) -> None:
        self.calls: list[list[str]] = []

    def generate_embeddings(self, texts: list[str]) -> list[list[float]]:
        self.calls.append(texts)
        return [[float(index), float(len(text))] for index, text in enumerate(texts)]


def test_bug_persistence_archives_batches_and_projects_graph():
    db = FakeDatabase()
    embedding = FakeEmbeddingService()
    archived: list[BugRecord] = []
    graph_calls: list[tuple[object, dict]] = []
    graph_db = object()
    persistence = RecordPersistence(
        db=db,
        embedding_svc=embedding,
        graph_db=graph_db,
        archive_bug=archived.append,
        write_bug_graph=lambda target, row: graph_calls.append((target, row)),
        write_convention_graph=lambda *_: (_ for _ in ()).throw(
            AssertionError("Convention graph writer must not receive a BugRecord"),
        ),
    )

    prepared = persistence.prepare_bug({
        "bug_title": "Missing default value",
        "error_log_snippet": "KeyError: timeout",
        "tried_methods": "Restarted the worker",
        "final_solution": "Use config.get with a default",
        "project_name": "worker",
        "tech_stack": "Python",
        "root_cause": "Optional configuration was indexed directly",
    })

    assert isinstance(prepared.record, BugRecord)
    assert prepared.is_draft is False
    assert archived == [prepared.record]

    table_row = persistence.persist(prepared.record)
    chunks = prepared.record.to_chunks()
    assert embedding.calls == [[
        prepared.record.to_search_text(),
        *[chunk["search_text"] for chunk in chunks],
    ]]
    assert db.parent_rows == [table_row]
    assert len(db.chunk_rows) == len(chunks)
    assert table_row["record_type"] == "bug"
    assert table_row["vector"] == [0.0, float(len(prepared.record.to_search_text()))]
    assert [row["vector"] for row in db.chunk_rows] == [
        [float(index), float(len(chunk["search_text"]))]
        for index, chunk in enumerate(chunks, start=1)
    ]
    assert graph_calls == [(graph_db, table_row)]


def test_convention_persistence_uses_its_archive_mapping_and_graph_writer():
    db = FakeDatabase()
    embedding = FakeEmbeddingService()
    archived: list[ConventionRecord] = []
    convention_graph_calls: list[tuple[object, dict]] = []
    graph_db = object()
    persistence = RecordPersistence(
        db=db,
        embedding_svc=embedding,
        graph_db=graph_db,
        archive_convention=archived.append,
        write_bug_graph=lambda *_: (_ for _ in ()).throw(
            AssertionError("Bug graph writer must not receive a ConventionRecord"),
        ),
        write_convention_graph=lambda target, row: convention_graph_calls.append(
            (target, row),
        ),
    )

    prepared = persistence.prepare_convention({
        "convention_name": "Repository returns DTOs",
        "trigger_context": "When returning data from repositories",
        "incorrect_behavior": "Return entities directly",
        "correct_behavior": "Map entities to DTOs before returning",
        "scope": "src/repository/",
        "tags": "architecture, Java",
    })

    assert isinstance(prepared.record, ConventionRecord)
    assert archived == [prepared.record]

    table_row = persistence.persist(prepared.record)
    assert len(embedding.calls) == 1
    assert table_row["record_type"] == "convention"
    assert table_row["bug_title"] == "Repository returns DTOs"
    assert table_row["project_name"] == "src/repository/"
    assert table_row["tech_stack"] == "architecture, Java"
    assert all(row["record_type"] == "convention" for row in db.chunk_rows)
    assert convention_graph_calls == [(graph_db, table_row)]


def test_draft_skips_archive_but_remains_persistable():
    db = FakeDatabase()
    archived: list[BugRecord] = []
    persistence = RecordPersistence(
        db=db,
        embedding_svc=FakeEmbeddingService(),
        archive_bug=archived.append,
    )

    prepared = persistence.prepare_bug({
        "bug_title": "Investigating retries",
        "error_log_snippet": "TimeoutError",
        "tried_methods": "   ",
        "final_solution": "Increase the timeout",
    })

    assert isinstance(prepared.record, BugRecord)
    assert prepared.is_draft
    assert prepared.missing_fields == ["tried_methods"]
    assert archived == []

    persistence.persist(prepared.record)
    assert len(db.parent_rows) == 1
    assert len(db.chunk_rows) == 2


def test_invalid_record_has_no_archive_or_persistable_record():
    archived: list[BugRecord] = []
    persistence = RecordPersistence(archive_bug=archived.append)

    prepared = persistence.prepare_bug({"bug_title": "Incomplete"})

    assert prepared.record is None
    assert prepared.validation_error is not None
    assert archived == []


def test_mcp_presentation_preserves_bug_and_convention_save_messages():
    from bugvault.mcp_tools.tools import _present_save_outcome

    persistence = RecordPersistence(
        archive_bug=lambda _: None,
        archive_convention=lambda _: None,
    )
    bug = persistence.prepare_bug({
        "bug_title": "Missing default value",
        "error_log_snippet": "KeyError: timeout",
        "tried_methods": "Restarted the worker",
        "final_solution": "Use config.get with a default",
    })
    convention = persistence.prepare_convention({
        "convention_name": "Repository returns DTOs",
        "trigger_context": "When returning data from repositories",
        "incorrect_behavior": "Return entities directly",
        "correct_behavior": "Map entities to DTOs before returning",
    })
    draft = persistence.prepare_bug({
        "bug_title": "Investigating retries",
        "error_log_snippet": "TimeoutError",
        "tried_methods": " ",
        "final_solution": "Increase the timeout",
    })
    invalid = persistence.prepare_convention({"convention_name": "Incomplete"})

    assert _present_save_outcome(bug)[0].text == (
        "Bug record 'Missing default value' saved successfully. "
        "I can now retrieve it in future troubleshooting sessions."
    )
    assert _present_save_outcome(convention)[0].text == (
        "Convention 'Repository returns DTOs' saved successfully. "
        "I will remember this rule for future sessions."
    )
    assert _present_save_outcome(draft)[0].text == (
        "Record saved as draft. Missing fields: tried_methods. "
        "You can update the record later."
    )
    assert _present_save_outcome(invalid)[0].text == (
        f"Invalid convention: {invalid.validation_error}"
    )


def test_mcp_save_passes_graph_and_schedules_background_persistence(monkeypatch):
    import asyncio
    import concurrent.futures

    from bugvault.mcp_tools import tools
    from bugvault.services.persistence_svc import PreparedRecord

    monkeypatch.setattr(tools.settings, "enable_async_embedding", True)

    record = BugRecord(
        bug_title="Background persistence",
        error_log_snippet="TimeoutError",
        tried_methods="Restarted the worker",
        final_solution="Increase the timeout",
    )
    init_arguments: dict = {}
    scheduled_arguments: dict = {}

    async def run_save() -> str:
        completed = asyncio.Event()
        loop = asyncio.get_running_loop()

        class FakePersistence:
            def __init__(self, **kwargs) -> None:
                init_arguments.update(kwargs)

            def prepare_bug(self, arguments: dict) -> PreparedRecord:
                return PreparedRecord(record=record, record_type="bug")

            def prepare_convention(self, arguments: dict) -> PreparedRecord:
                raise AssertionError("Convention preparation must not run")

        async def fake_background(
            background_loop,
            background_executor,
            persistence,
            prepared_record,
        ) -> None:
            scheduled_arguments.update({
                "loop": background_loop,
                "executor": background_executor,
                "persistence": persistence,
                "record": prepared_record,
            })
            completed.set()

        monkeypatch.setattr(tools, "RecordPersistence", FakePersistence)
        monkeypatch.setattr(
            tools,
            "_persist_record_in_background",
            fake_background,
        )
        executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
        try:
            response = await tools._handle_save_record(
                loop,
                executor,
                db=object(),
                embedding_svc=object(),
                graph_db="graph-overlay",
                arguments={},
                record_type="bug",
            )
            await asyncio.wait_for(completed.wait(), timeout=1)
            return response[0].text
        finally:
            executor.shutdown(wait=True)

    assert asyncio.run(run_save()) == (
        "Bug record 'Background persistence' saved successfully. "
        "I can now retrieve it in future troubleshooting sessions."
    )
    assert init_arguments["graph_db"] == "graph-overlay"
    assert scheduled_arguments["record"] is record


def test_archive_rebuild_reuses_the_batch_embedding_boundary(tmp_path):
    from bugvault.services.db_maintenance_svc import _parse_and_embed

    archive_file = tmp_path / "retry.md"
    archive_file.write_text(
        "---\n"
        "date: 2026-07-28T00:00:00+00:00\n"
        "project: worker\n"
        "tags:\n"
        "  - Python\n"
        "---\n\n"
        "# Retry timeout\n\n"
        "## Error\n\n"
        "TimeoutError\n\n"
        "## Tried\n\n"
        "Restarted the worker\n\n"
        "## Solution\n\n"
        "Increase the timeout\n",
        encoding="utf-8",
    )
    embedding = FakeEmbeddingService()

    result = _parse_and_embed(archive_file, embedding)

    assert result is not None
    table_row, chunk_rows = result
    assert table_row["record_type"] == "bug"
    assert len(chunk_rows) == 2
    assert len(embedding.calls) == 1
    assert embedding.calls[0][0] == table_row["search_text"]
    assert [row["search_text"] for row in chunk_rows] == embedding.calls[0][1:]


def test_archive_read_interface_returns_the_record_selected_by_frontmatter(tmp_path):
    from bugvault.services.archive_svc import (
        convention_to_markdown,
        read_archive_record,
        record_to_markdown,
    )

    bug_path = tmp_path / "bug.md"
    bug_path.write_text(record_to_markdown(BugRecord(
        bug_title="Retry timeout",
        error_log_snippet="TimeoutError",
        tried_methods="Restarted the worker",
        final_solution="Increase the timeout",
    )), encoding="utf-8")
    convention_path = tmp_path / "convention.md"
    convention_path.write_text(convention_to_markdown(ConventionRecord(
        convention_name="Return DTOs",
        trigger_context="When returning repository data",
        incorrect_behavior="Return entities directly",
        correct_behavior="Map entities to DTOs",
    )), encoding="utf-8")

    assert isinstance(read_archive_record(bug_path), BugRecord)
    assert isinstance(read_archive_record(convention_path), ConventionRecord)
