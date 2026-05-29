"""Embedding service — wraps fastembed ONNX model for text vectorisation.

Extracted from ``lancedb_client`` to separate concerns: the database layer
should not own the embedding model.
"""

from __future__ import annotations

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
        self._init_model()

    # ── public API ──────────────────────────────────────────────────

    def generate_embedding(self, text: str) -> list[float]:
        """Embed *text* into a dense vector and return it as a flat list."""
        if self._model is None:
            msg = "Embedding model is not initialised"
            raise RuntimeError(msg)
        # fastembed returns an iterable of lists; consume it
        result = list(self._model.embed([text]))
        return result[0]  # type: ignore[return-value]

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