"""LanceDB client — data access layer for BugVault.

Encapsulates LanceDB connection lifecycle, vector search, and record
insertion behind a clean OOP interface.

This layer does NOT own the embedding model — callers must provide
pre-computed embeddings via ``search()`` and ``upsert_record()``.
"""

from __future__ import annotations

import threading

import lancedb
import pyarrow as pa

from bugvault.config import settings
from bugvault.models.bug_record import BugRecord
from bugvault.utils.logger import logger


class LanceDBClient:
    """OOP wrapper around LanceDB.

    Usage
    -----
        client = LanceDBClient()
        client.initialize()
        rows = client.search(query_embedding)
        client.upsert_record(search_text, emb, record)
    """

    TABLE_NAME = "bug_records"

    def __init__(self) -> None:
        self._table = None
        self._db = None
        self._lock = threading.Lock()

    # ── Lifecycle ───────────────────────────────────────────────────

    def initialize(self) -> None:
        """Open (or create) the LanceDB table.

        Called once during server startup.  Embedding-model warm-up is
        handled separately by ``EmbeddingService``.
        """
        self._init_table()

    def drop_table(self) -> None:
        """Drop the entire table and re-create an empty one.

        This is the most thorough way to clear all data — no stale
        records survive. Safe to call when the table doesn't exist.
        """
        if self._db is not None:
            try:
                if self.TABLE_NAME in self._db.list_tables().tables:
                    self._db.drop_table(self.TABLE_NAME)
                    logger.info("Dropped table: %s", self.TABLE_NAME)
            except Exception:
                logger.exception("Failed to drop table (non-fatal, will recreate)")
        self._table = None
        self._init_table()

    @property
    def is_ready(self) -> bool:
        return self._table is not None

    # ── Public API ──────────────────────────────────────────────────

    def search(self, embedding: list[float]) -> list[dict]:
        """Perform ANN search with a pre-computed *embedding*.

        Returns raw rows from LanceDB (list of dicts).
        """
        if not self.is_ready:
            raise RuntimeError("BugVault is still initialising")
        with self._lock:
            return self._table.search(embedding).limit(settings.top_k).to_list()  # type: ignore[union-attr]

    def upsert_record(
        self,
        search_text: str,
        embedding: list[float],
        record: BugRecord,
    ) -> None:
        """Write a single record (with its pre-computed *embedding*) to LanceDB.

        Markdown archiving is NOT handled here — callers should use
        ``archive_svc.write_markdown_archive()`` separately.
        """
        if not self.is_ready:
            raise RuntimeError("BugVault is still initialising")

        data_dict = {
            "vector": embedding,
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
        }

        # ── True upsert via merge_insert ────────────────────────────
        # Matches on ``record_id``: existing record → update all fields;
        # new record → insert all fields.  This guarantees no duplicate
        # entries for the same (bug_title + error_log_snippet).
        with self._lock:
            self._table.merge_insert("record_id") \
                .when_matched_update_all() \
                .when_not_matched_insert_all() \
                .execute([data_dict])

        logger.info("Saved bug record: %s (record_id=%s)", record.bug_title, record.record_id)

    # ── Internal helpers ────────────────────────────────────────────

    def _init_table(self) -> None:
        self._db = lancedb.connect(settings.db_uri)
        logger.info("LanceDB connected at: %s", settings.db_uri)

        existing = self._db.list_tables()
        existing_names: list[str] = existing.tables
        if self.TABLE_NAME in existing_names:
            self._table = self._db.open_table(self.TABLE_NAME)
            logger.info("Opened existing table: %s", self.TABLE_NAME)
        else:
            schema = pa.schema([
                pa.field("vector", pa.list_(pa.float32(), settings.embedding_dim)),
                pa.field("record_id", pa.utf8()),
                pa.field("bug_title", pa.utf8()),
                pa.field("error_log_snippet", pa.utf8()),
                pa.field("tried_methods", pa.utf8()),
                pa.field("final_solution", pa.utf8()),
                pa.field("project_name", pa.utf8()),
                pa.field("tech_stack", pa.utf8()),
                pa.field("root_cause", pa.utf8()),
                pa.field("create_time", pa.utf8()),
                pa.field("search_text", pa.utf8()),
            ])
            self._table = self._db.create_table(self.TABLE_NAME, schema=schema, mode="overwrite")
            logger.info("Created new table: %s", self.TABLE_NAME)