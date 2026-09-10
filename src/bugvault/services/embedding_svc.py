"""Embedding service — wraps fastembed ONNX model for text vectorisation.

Extracted from ``lancedb_client`` to separate concerns: the database layer
should not own the embedding model.
"""

from __future__ import annotations

import threading

from bugvault.config import settings
from bugvault.utils.logger import logger


class EmbeddingService:
    """Thin wrapper around a fastembed ``TextEmbedding`` model.

    Usage::

        svc = EmbeddingService()
        vec = svc.generate_embedding("some search text")
    """

    def __init__(self) -> None:
        self._model = None
        self._model_lock = threading.Lock()

    # ── public API ──────────────────────────────────────────────────

    def generate_embedding(self, text: str) -> list[float]:
        """Embed *text* into a dense vector and return it as a flat list."""
        return self.generate_embeddings([text])[0]

    def generate_embeddings(self, texts: list[str]) -> list[list[float]]:
        """Embed a batch of *texts* into dense vectors (ONNX batch-optimized).

        Use this instead of repeated ``generate_embedding`` calls when you
        have many texts — ONNX inference benefits significantly from
        internal batching.
        """
        self._ensure_model()
        return [r for r in self._model.embed(texts)]  # type: ignore[misc]

    # ── internal helpers ────────────────────────────────────────────

    def _init_model(self) -> None:
        """Lazily load the ONNX embedding model and warm it up.

        Warm-up compiles the ONNX graph so the first real inference is
        fast instead of paying a 500+ ms cold-start penalty.
        """
        from fastembed import TextEmbedding  # slow import

        logger.info(
            "Loading embedding model '%s' (dim=%s) …",
            settings.embedding_model,
            settings.embedding_dim,
        )
        self._model = TextEmbedding(
            model_name=settings.embedding_model,
            max_length=512,
        )
        # Warm-up: compile ONNX graph once at startup
        _ = list(self._model.embed(["warmup"]))
        logger.info("Embedding model ready")

    def _ensure_model(self) -> None:
        """Load the model on first use, outside the MCP startup handshake.

        Model construction may consult the local FastEmbed cache or attempt a
        network download.  Keeping it lazy lets the stdio server complete the
        MCP ``initialize`` handshake even when the cache is incomplete or the
        network is unavailable; the eventual tool call receives the concrete
        model-loading error instead of a closed connection.
        """
        if self._model is not None:
            return
        with self._model_lock:
            if self._model is None:
                self._init_model()
