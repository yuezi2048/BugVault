"""LanceDB client — data access layer for BugVault.

Encapsulates LanceDB connection lifecycle, vector search, and record
insertion behind a clean OOP interface.

This layer does NOT own the embedding model — callers must provide
pre-computed embeddings via ``search()`` and ``upsert_record()``.

.. versionchanged:: 1.1.1

   Added ``bugvault_chunks`` table for parent-child chunk retrieval.
   See :meth:`upsert_chunks`, :meth:`search_chunks`, :meth:`search_chunks_fts`,
   :meth:`fetch_records_by_ids`.
"""

from __future__ import annotations

import threading

import lancedb
import pyarrow as pa

from bugvault.config import settings
from bugvault.models.bug_record import BugRecord
from bugvault.utils.logger import logger


def _verify_vector_dim(table, expected_dim: int, table_name: str) -> None:
    """Check that *table*'s vector dimension matches *expected_dim*.

    Raises ``ValueError`` on mismatch, which crashes early rather than
    producing silent garbage or cryptic LanceDB errors on insert.
    """
    schema = table.schema
    vec_field = [f for f in schema if "vector" in f.name.lower()]
    if not vec_field:
        return
    field_type = str(vec_field[0].type)
    import re
    m = re.search(r"\[(\d+)\]", field_type)
    if m:
        actual_dim = int(m.group(1))
        if actual_dim != expected_dim:
            raise ValueError(
                f"Vector dimension mismatch for '{table_name}': "
                f"table has {actual_dim}, config has {expected_dim}. "
                f"Set BUGVAULT_EMBEDDING_DIM={actual_dim} or re-import."
            )


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
    CHUNKS_TABLE_NAME = "bugvault_chunks"

    def __init__(self) -> None:
        self._table = None
        self._chunks_table = None
        self._db = None
        self._lock = threading.Lock()

    # ── Lifecycle ───────────────────────────────────────────────────

    def initialize(self) -> None:
        """Open (or create) both LanceDB tables.

        Called once during server startup.  Embedding-model warm-up is
        handled separately by ``EmbeddingService``.
        """
        self._init_table()
        self._init_chunks_table()

    def drop_table(self) -> None:
        """Drop **both** tables and re-create empty ones.

        This is the most thorough way to clear all data — no stale
        records survive. Safe to call when the table doesn't exist.
        """
        if self._db is not None:
            for tname in (self.TABLE_NAME, self.CHUNKS_TABLE_NAME):
                try:
                    if tname in self._db.list_tables().tables:
                        self._db.drop_table(tname)
                        logger.info("Dropped table: %s", tname)
                except Exception:
                    logger.exception(
                        "Failed to drop table '%s' (non-fatal, will recreate)", tname,
                    )
        self._table = None
        self._chunks_table = None
        self._init_table()
        self._init_chunks_table()

    @property
    def is_ready(self) -> bool:
        return self._table is not None and self._chunks_table is not None

    # ── FTS (Full-Text Search) — parent table ──────────────────────

    def create_fts_index(self, replace: bool = True) -> None:
        """Create (or replace) the Tantivy FTS index on ``bug_records.search_text``.

        Called automatically from ``initialize()`` and after
        ``import_from_archive()`` bulk loads.
        """
        if self._table is None:
            logger.warning("bug_records table not ready — skipping FTS index creation")
            return
        try:
            self._table.create_fts_index("search_text", replace=replace)  # type: ignore[union-attr]
            logger.info("FTS index created/replaced on bug_records.search_text")
        except Exception:
            logger.exception("FTS index creation failed (non-fatal, vector search still works)")

    def search_fts(
        self,
        query_text: str,
        filter_clause: str | None = None,
        limit: int | None = None,
    ) -> list[dict]:
        """Full-text search on ``bug_records`` via Tantivy BM25.

        Each result row includes a ``_score`` field (BM25 relevance).
        Returns empty list on failure (FTS index missing, engine error).
        """
        if self._table is None:
            raise RuntimeError("BugVault is still initialising")
        try:
            with self._lock:
                query = self._table.search(query_text)  # type: ignore[union-attr]
                if filter_clause:
                    query = query.where(filter_clause)
                return query.limit(limit or settings.top_k * 4).to_list()
        except Exception:
            logger.exception("FTS search on bug_records failed (fallback to vector-only)")
            return []


    # ── Public API: parent table (bug_records) ──────────────────────

    def search(
        self,
        embedding: list[float],
        filter_clause: str | None = None,
        limit: int | None = None,
    ) -> list[dict]:
        """Perform ANN search on ``bug_records`` with a pre-computed *embedding*.

        Args:
            embedding: The query vector.
            filter_clause: Optional SQL filter applied *before* ANN search.
            limit: Max results (default ``settings.top_k``).

        Returns raw rows from LanceDB (list of dicts).
        """
        if self._table is None:
            raise RuntimeError("BugVault is still initialising")
        with self._lock:
            query = self._table.search(embedding)
            if filter_clause:
                query = query.where(filter_clause)
            return query.limit(limit or settings.top_k).to_list()  # type: ignore[union-attr]

    def upsert_record(
        self,
        search_text: str,
        embedding: list[float],
        record: BugRecord,
    ) -> None:
        """Write a single record (with its pre-computed *embedding*) to ``bug_records``.

        Markdown archiving is NOT handled here — callers should use
        ``archive_svc.write_markdown_archive()`` separately.
        """
        if self._table is None:
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

    # ── Public API: chunks table (bugvault_chunks) ──────────────────

    def upsert_chunks(self, chunks: list[dict]) -> None:
        """Batch-upsert chunk rows into ``bugvault_chunks``.

        Each dict must contain at least:
            chunk_id, parent_id, chunk_type, search_text, vector,
            tech_stack, project_name

        Merge key is ``chunk_id`` — existing rows with the same
        ``chunk_id`` are updated in-place.
        """
        if self._chunks_table is None:
            raise RuntimeError("BugVault is still initialising")
        if not chunks:
            return

        with self._lock:
            self._chunks_table.merge_insert("chunk_id") \
                .when_matched_update_all() \
                .when_not_matched_insert_all() \
                .execute(chunks)  # type: ignore[arg-type]

        logger.debug("Upserted %d chunk(s)", len(chunks))

    def create_chunks_fts_index(self, replace: bool = True) -> None:
        """Create (or replace) the Tantivy FTS index on ``bugvault_chunks.search_text``."""
        if self._chunks_table is None:
            return
        try:
            self._chunks_table.create_fts_index("search_text", replace=replace)  # type: ignore[union-attr]
            logger.info("FTS index on bugvault_chunks.search_text ready")
        except Exception:
            logger.exception("Chunks FTS index creation failed (non-fatal)")

    def search_chunks_fts(
        self,
        query_text: str,
        filter_clause: str | None = None,
        limit: int | None = None,
    ) -> list[dict]:
        """FTS search on ``bugvault_chunks``."""
        if self._chunks_table is None:
            return []
        try:
            with self._lock:
                query = self._chunks_table.search(query_text)
                if filter_clause:
                    query = query.where(filter_clause)
                return query.limit(limit or settings.top_k * 4).to_list()
        except Exception:
            logger.exception("Chunks FTS search failed")
            return []

    def search_chunks(
        self,
        embedding: list[float],
        filter_clause: str | None = None,
        limit: int | None = None,
    ) -> list[dict]:
        """Perform ANN search on ``bugvault_chunks`` with a pre-computed *embedding*.

        Args:
            embedding: The query vector.
            filter_clause: Optional SQL filter applied *before* ANN search.
            limit: Max results (default ``settings.top_k``).

        Returns raw rows from LanceDB (list of dicts), each with
        ``_distance`` and ``parent_id`` for parent-document mapping.
        """
        if self._chunks_table is None:
            raise RuntimeError("BugVault is still initialising")
        with self._lock:
            query = self._chunks_table.search(embedding)
            if filter_clause:
                query = query.where(filter_clause)
            return query.limit(limit or settings.top_k * 4).to_list()  # type: ignore[union-attr]

    def fetch_records_by_ids(self, record_ids: list[str]) -> list[dict]:
        """Batch-fetch full parent records from ``bug_records`` by ``record_id``.

        Args:
            record_ids: List of ``record_id`` values to look up.

        Returns:
            List of full dict rows from ``bug_records`` (with all
            metadata fields).  Order is **not** guaranteed to match
            the input order.
        """
        if self._table is None or not record_ids:
            return []

        # Build a quoted, comma-sep list of ids for the SQL IN clause
        quoted = ", ".join(repr(rid) for rid in record_ids)
        try:
            with self._lock:
                return self._table.search().where(f"record_id IN ({quoted})").to_list()  # type: ignore[union-attr]
        except Exception:
            logger.exception("fetch_records_by_ids failed")
            return []

    # ── Internal helpers ────────────────────────────────────────────

    def _init_table(self) -> None:
        self._db = lancedb.connect(settings.db_uri)
        logger.info("LanceDB connected at: %s", settings.db_uri)

        existing = self._db.list_tables()
        existing_names: list[str] = existing.tables
        if self.TABLE_NAME in existing_names:
            self._table = self._db.open_table(self.TABLE_NAME)
            _verify_vector_dim(self._table, settings.embedding_dim, self.TABLE_NAME)
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

        # Always attempt FTS index creation — lightweight if already exists
        if settings.enable_fts:
            self.create_fts_index(replace=True)

    def _init_chunks_table(self) -> None:
        """Open or create the ``bugvault_chunks`` table."""
        existing = self._db.list_tables()
        existing_names: list[str] = existing.tables
        if self.CHUNKS_TABLE_NAME in existing_names:
            self._chunks_table = self._db.open_table(self.CHUNKS_TABLE_NAME)
            _verify_vector_dim(self._chunks_table, settings.embedding_dim, self.CHUNKS_TABLE_NAME)
            logger.info("Opened existing table: %s", self.CHUNKS_TABLE_NAME)
        else:
            schema = pa.schema([
                pa.field("vector", pa.list_(pa.float32(), settings.embedding_dim)),
                pa.field("chunk_id", pa.utf8()),
                pa.field("parent_id", pa.utf8()),
                pa.field("chunk_type", pa.utf8()),
                pa.field("search_text", pa.utf8()),
                pa.field("tech_stack", pa.utf8()),
                pa.field("project_name", pa.utf8()),
            ])
            self._chunks_table = self._db.create_table(
                self.CHUNKS_TABLE_NAME, schema=schema, mode="overwrite",
            )
            logger.info("Created new table: %s", self.CHUNKS_TABLE_NAME)

        # FTS index on chunks.search_text
        if settings.enable_fts:
            self.create_chunks_fts_index(replace=True)
