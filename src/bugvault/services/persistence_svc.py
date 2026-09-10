"""Deep record-persistence module for BugVault's local memory."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from bugvault.database.graph_db import (
    write_bug_graph_edges,
    write_convention_graph_edges,
)
from bugvault.models.bug_record import BugRecord
from bugvault.models.convention_record import ConventionRecord
from bugvault.services.archive_svc import (
    write_convention_archive,
    write_markdown_archive,
)
from bugvault.services.ingestion_svc import (
    validate_and_prepare,
    validate_convention_record,
)
from bugvault.utils.logger import logger


Record = BugRecord | ConventionRecord


@dataclass(slots=True)
class PreparedRecord:
    """Validation and archive outcome before background local-memory writes."""

    record: Record | None
    record_type: str
    missing_fields: list[str] = field(default_factory=list)
    validation_error: str | None = None

    @property
    def is_draft(self) -> bool:
        return self.record is not None and bool(self.missing_fields)


@dataclass(slots=True)
class EmbeddedRecord:
    """LanceDB parent and chunk rows produced for a record."""

    table_row: dict
    chunk_rows: list[dict]


class RecordPersistence:
    """Own validation, archive, embedding, local-memory, and Graph work."""

    def __init__(
        self,
        db: Any | None = None,
        embedding_svc: Any | None = None,
        graph_db: Any | None = None,
        archive_bug: Callable[[BugRecord], Any] = write_markdown_archive,
        archive_convention: Callable[[ConventionRecord], Any] = write_convention_archive,
        write_bug_graph: Callable[[Any, dict], None] = write_bug_graph_edges,
        write_convention_graph: Callable[[Any, dict], None] = write_convention_graph_edges,
    ) -> None:
        self._db = db
        self._embedding_svc = embedding_svc
        self._graph_db = graph_db
        self._archive_bug = archive_bug
        self._archive_convention = archive_convention
        self._write_bug_graph = write_bug_graph
        self._write_convention_graph = write_convention_graph

    def prepare_bug(self, arguments: dict) -> PreparedRecord:
        """Validate and archive a Bug Record when it is complete."""
        return self._prepare(
            arguments,
            "bug",
            BugRecord,
            validate_and_prepare,
            self._archive_bug,
        )

    def prepare_convention(self, arguments: dict) -> PreparedRecord:
        """Validate and archive a Convention Record when it is complete."""
        return self._prepare(
            arguments,
            "convention",
            ConventionRecord,
            validate_convention_record,
            self._archive_convention,
        )

    def embed(self, record: Record) -> EmbeddedRecord:
        """Build all storage rows with one embedding batch for the record."""
        if self._embedding_svc is None:
            raise RuntimeError("RecordPersistence requires an embedding service")
        table_row = _table_row(record)
        chunks = record.to_chunks()
        texts = [table_row["search_text"], *[chunk["search_text"] for chunk in chunks]]
        vectors = self._embedding_svc.generate_embeddings(texts)
        if len(vectors) != len(texts):
            raise RuntimeError("Embedding service returned an unexpected vector count")

        table_row["vector"] = vectors[0]
        chunk_rows = [
            _chunk_row(chunk, vector)
            for chunk, vector in zip(chunks, vectors[1:], strict=True)
        ]
        return EmbeddedRecord(table_row=table_row, chunk_rows=chunk_rows)

    def persist(self, record: Record) -> dict:
        """Batch-embed and write one parent record, its chunks, and Graph edges."""
        if self._db is None:
            raise RuntimeError("RecordPersistence requires a database")
        if record.missing_required_fields():
            raise ValueError("Cannot persist a draft record")

        embedded = self.embed(record)
        table_row = embedded.table_row
        self._db.upsert_record(table_row)
        self._db.upsert_chunks(embedded.chunk_rows)
        self._project_graph(record, table_row)
        logger.info(
            "Record persistence completed: %s",
            table_row.get("bug_title", table_row.get("record_id", "?")),
        )
        return table_row

    def _prepare(
        self,
        arguments: dict,
        record_type: str,
        record_factory: Callable[..., Record],
        validator: Callable[[Any], list[str]],
        archive_writer: Callable[[Any], Any],
    ) -> PreparedRecord:
        try:
            record = record_factory(**arguments)
        except Exception as exc:
            return PreparedRecord(
                record=None,
                record_type=record_type,
                validation_error=str(exc),
            )

        missing_fields = validator(record)
        if missing_fields:
            return PreparedRecord(
                record=record,
                record_type=record_type,
                missing_fields=missing_fields,
            )

        try:
            archive_writer(record)
        except Exception:
            logger.exception("Failed to archive %s record (non-fatal)", record_type)
        return PreparedRecord(record=record, record_type=record_type)

    def _project_graph(self, record: Record, table_row: dict) -> None:
        try:
            if isinstance(record, BugRecord):
                self._write_bug_graph(self._graph_db, table_row)
            else:
                self._write_convention_graph(self._graph_db, table_row)
        except Exception:
            logger.exception("Failed to project record into Graph (non-fatal)")


def _table_row(record: Record) -> dict:
    if isinstance(record, ConventionRecord):
        return record.to_table_row()
    return {
        "record_id": record.record_id or "",
        "bug_title": record.bug_title,
        "error_log_snippet": record.error_log_snippet,
        "tried_methods": record.tried_methods,
        "final_solution": record.final_solution,
        "project_name": record.project_name or "",
        "tech_stack": record.tech_stack or "",
        "root_cause": record.root_cause or "",
        "create_time": record.create_time,
        "search_text": record.to_search_text(),
        "record_type": "bug",
    }


def _chunk_row(chunk: dict, vector: list[float]) -> dict:
    return {
        "vector": vector,
        "chunk_id": chunk["chunk_id"],
        "parent_id": chunk["parent_id"],
        "chunk_type": chunk["chunk_type"],
        "search_text": chunk["search_text"],
        "tech_stack": chunk.get("tech_stack", ""),
        "project_name": chunk.get("project_name", ""),
        "record_type": chunk.get("record_type", "bug"),
    }
