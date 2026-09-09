"""Tests for the Retrieval module's stable domain interface."""

from __future__ import annotations

import pytest

from bugvault.config import settings
from bugvault.models.bug_record import BugRecord
from bugvault.models.convention_record import ConventionRecord
from bugvault.services.retrieval_svc import (
    RetrievalModule,
    RetrievalRequest,
    build_filter_clause,
)


class FakeEmbedding:
    def generate_embedding(self, text: str) -> list[float]:
        return [float(len(text))]


class FakeReranker:
    def rerank(self, query: str, records: list[dict]) -> list[dict]:
        return list(reversed(records))


class FakeDatabase:
    is_ready = True

    def __init__(self, chunks: list[dict], parents: list[dict]) -> None:
        self.chunks = chunks
        self.parents = parents
        self.filters: list[str] = []

    def search_chunks(self, embedding, filter_clause: str, limit: int) -> list[dict]:
        self.filters.append(filter_clause)
        return self.chunks

    def search_chunks_fts(self, query: str, filter_clause: str, limit: int) -> list[dict]:
        self.filters.append(filter_clause)
        return []

    def search_fts(self, query: str, filter_clause: str, limit: int) -> list[dict]:
        self.filters.append(filter_clause)
        return []

    def fetch_records_by_ids(self, record_ids: list[str]) -> list[dict]:
        return [row for row in self.parents if row["record_id"] in record_ids]


def _bug_row(record_id: str, title: str) -> dict:
    return {
        "record_id": record_id,
        "record_type": "bug",
        "bug_title": title,
        "error_log_snippet": "TimeoutError",
        "tried_methods": "Restarted the worker",
        "final_solution": "Increase the timeout",
        "create_time": "2026-01-01T00:00:00+00:00",
    }


@pytest.fixture
def disable_optional_reranker():
    old_reranker = settings.enable_reranker
    old_fts = settings.enable_fts
    settings.enable_reranker = False
    settings.enable_fts = False
    try:
        yield
    finally:
        settings.enable_reranker = old_reranker
        settings.enable_fts = old_fts


def test_retrieval_module_maps_chunks_to_ranked_parent_records(disable_optional_reranker):
    database = FakeDatabase(
        chunks=[
            {"parent_id": "first", "_distance": 0.4},
            {"parent_id": "second", "_distance": 0.1},
        ],
        parents=[
            _bug_row("first", "First"),
            _bug_row("second", "Second"),
        ],
    )

    result = RetrievalModule(database, FakeEmbedding()).retrieve(
        RetrievalRequest("null pointer", target_tech_stack="Java"),
    )

    assert result.error_message is None
    assert [record.bug_title for record in result.records] == ["Second", "First"]
    assert all(isinstance(record, BugRecord) for record in result.records)
    assert result.vector_count == 2
    assert result.fts_count == 0
    assert result.strategy == "vector-only"
    assert database.filters == [
        "(LOWER(tech_stack) LIKE '%java%' AND LOWER(tech_stack) "
        "NOT LIKE '%javascript%') AND record_type = 'bug'",
    ]


def test_retrieval_module_keeps_empty_and_unready_messages_stable(disable_optional_reranker):
    database = FakeDatabase([], [])
    module = RetrievalModule(database, FakeEmbedding())

    assert module.retrieve(RetrievalRequest(" ")).error_message == (
        "Query is empty. Please provide an error description."
    )

    database.is_ready = False
    assert module.retrieve(RetrievalRequest("anything")).error_message == (
        "BugVault is still initialising. Please try again in a moment."
    )


def test_retrieval_module_preserves_a_filtered_candidate_result(disable_optional_reranker):
    database = FakeDatabase(
        chunks=[{"parent_id": "weak", "_distance": 1.9}],
        parents=[{"record_id": "weak", "bug_title": "Weak", "create_time": ""}],
    )

    result = RetrievalModule(database, FakeEmbedding()).retrieve(
        RetrievalRequest("query"),
    )

    assert result.records == []
    assert result.had_candidates is True


def test_retrieval_module_uses_cross_encoder_adapter_when_enabled(monkeypatch):
    database = FakeDatabase(
        chunks=[
            {"parent_id": "first", "_distance": 0.1},
            {"parent_id": "second", "_distance": 0.2},
        ],
        parents=[
            _bug_row("first", "First"),
            _bug_row("second", "Second"),
        ],
    )
    monkeypatch.setattr(settings, "enable_reranker", True)
    monkeypatch.setattr(settings, "enable_fts", False)

    result = RetrievalModule(
        database,
        FakeEmbedding(),
        reranker_factory=FakeReranker,
    ).retrieve(RetrievalRequest("query"))

    assert result.used_cross_encoder is True
    assert result.strategy == "hybrid + Cross-Encoder reranking"
    assert [record.bug_title for record in result.records] == ["Second", "First"]


def test_retrieval_module_returns_convention_records(disable_optional_reranker):
    database = FakeDatabase(
        chunks=[{"parent_id": "rule", "_distance": 0.1}],
        parents=[{
            "record_id": "rule",
            "record_type": "convention",
            "bug_title": "Return DTOs",
            "error_log_snippet": "When returning repository data",
            "tried_methods": "Return entities directly",
            "final_solution": "Map entities to DTOs",
            "project_name": "src/repository/",
            "tech_stack": "Python",
            "create_time": "2026-01-01T00:00:00+00:00",
        }],
    )

    result = RetrievalModule(database, FakeEmbedding()).retrieve(
        RetrievalRequest("repository return type", record_type="convention"),
    )

    assert len(result.records) == 1
    assert isinstance(result.records[0], ConventionRecord)
    assert result.records[0].scope == "src/repository/"
    assert result.records[0].correct_behavior == "Map entities to DTOs"


def test_filter_clause_is_owned_by_the_retrieval_module():
    assert build_filter_clause("Python'; DROP TABLE", "project' OR '1'='1") == (
        "LOWER(tech_stack) LIKE '%python drop table%' AND "
        "LOWER(project_name) LIKE '%project or 11%'"
    )
