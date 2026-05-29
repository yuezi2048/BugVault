"""LanceDB client — data access layer for BugVault.

Encapsulates embedding-model loading, LanceDB connection lifecycle,
vector search, and record insertion behind a clean OOP interface.
"""

from __future__ import annotations

from pathlib import Path

import lancedb
import pyarrow as pa
from fastembed import TextEmbedding

from bugvault.config import settings
from bugvault.models.bug_record import BugRecord
from bugvault.services.ingestion_svc import record_to_markdown
from bugvault.utils.logger import logger


class LanceDBClient:
    """OOP wrapper around LanceDB and fastembed.

    Usage
    -----
        client = LanceDBClient()
        client.initialize()          # warm model + open table
        rows = client.search("some error")
        client.insert(record)
    """

    TABLE_NAME = "bug_records"

    def __init__(self) -> None:
        self._table = None
        self._embedder: TextEmbedding | None = None

    # ── Lifecycle ───────────────────────────────────────────────────

    def initialize(self) -> None:
        """Warm up the embedding model and open (or create) the LanceDB table.

        Called once during server startup so that subsequent tool
        invocations pay no cold-start penalty.
        """
        self._init_embedder()
        self._init_table()

    @property
    def is_ready(self) -> bool:
        return self._embedder is not None and self._table is not None

    # ── Public API ──────────────────────────────────────────────────

    def search(self, query: str) -> list[dict]:
        """Embed *query* and perform ANN search.

        Returns raw rows from LanceDB (list of dicts).
        """
        if not self.is_ready:
            raise RuntimeError("BugVault is still initialising")
        emb = list(self._embedder.embed([query]))[0].tolist()  # type: ignore[union-attr]
        return self._table.search(emb).limit(settings.top_k).to_list()  # type: ignore[union-attr]

    def insert(self, record: BugRecord) -> None:
        """Build search text, embed, write to LanceDB, and archive as markdown."""
        if not self.is_ready:
            raise RuntimeError("BugVault is still initialising")

        search_text = record.to_search_text()
        emb = list(self._embedder.embed([search_text]))[0].tolist()  # type: ignore[union-attr]

        self._table.add([{  # type: ignore[union-attr]
            "vector": emb,
            "bug_title": record.bug_title,
            "error_log_snippet": record.error_log_snippet,
            "tried_methods": record.tried_methods,
            "final_solution": record.final_solution,
            "project_name": record.project_name or "",
            "tech_stack": record.tech_stack or "",
            "root_cause": record.root_cause or "",
            "create_time": record.create_time,
            "search_text": search_text,
        }])

        logger.info("Saved bug record: %s", record.bug_title)

        # ── Markdown archive (non-critical, best-effort) ──────────
        try:
            md_dir = Path(settings.markdown_archive_dir)
            md_dir.mkdir(parents=True, exist_ok=True)
            md_path = md_dir / f"{record.create_time[:10]}_{record.bug_title[:40]}.md"
            md_path.write_text(record_to_markdown(record), encoding="utf-8")
        except Exception:
            logger.exception("Failed to write markdown archive")

    # ── Internal helpers ────────────────────────────────────────────

    def _init_embedder(self) -> None:
        logger.info("Loading embedding model: %s", settings.embedding_model)
        self._embedder = TextEmbedding(
            model_name=settings.embedding_model,
            max_length=512,
        )
        # Warm-up: one dummy embedding pre-compiles the ONNX graph
        list(self._embedder.embed(["warmup"]))
        logger.info("Embedding model loaded and warmed up")

    def _init_table(self) -> None:
        db = lancedb.connect(settings.db_uri)
        logger.info("LanceDB connected at: %s", settings.db_uri)

        existing = db.list_tables()
        existing_names: list[str] = existing.tables
        if self.TABLE_NAME in existing_names:
            self._table = db.open_table(self.TABLE_NAME)
            logger.info("Opened existing table: %s", self.TABLE_NAME)
        else:
            schema = pa.schema([
                pa.field("vector", pa.list_(pa.float32(), settings.embedding_dim)),
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
            self._table = db.create_table(self.TABLE_NAME, schema=schema, mode="create")
            logger.info("Created new table: %s", self.TABLE_NAME)