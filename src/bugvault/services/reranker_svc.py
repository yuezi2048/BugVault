"""Cross-Encoder reranker — lightweight local re-ranking via fastembed.

Used as the final re-ranking stage after RRF fusion:
  Vector + FTS → RRF → rerank() → **CrossEncoderReranker** → Top-K

The model is **lazy-loaded** (first call triggers download) and held as
a module-level singleton so it survives across requests.
"""

from __future__ import annotations

from bugvault.config import settings
from bugvault.utils.logger import logger


# ── Singleton holder ───────────────────────────────────────────────

_reranker_instance: "CrossEncoderReranker | None" = None


def get_reranker() -> "CrossEncoderReranker | None":
    """Return the shared CrossEncoderReranker singleton (or None on failure)."""
    global _reranker_instance
    if _reranker_instance is None:
        try:
            _reranker_instance = CrossEncoderReranker(settings.reranker_model)
        except Exception:
            logger.exception(
                "Failed to initialise Cross-Encoder reranker "
                "(reranking will be skipped)"
            )
            return None
    return _reranker_instance


# ── Cross-Encoder wrapper ──────────────────────────────────────────


class CrossEncoderReranker:
    """Wrapper around fastembed ``TextCrossEncoder`` with lazy loading.

    Usage
    -----
        reranker = CrossEncoderReranker()
        docs = reranker.rerank(query, raw_docs)
        # docs now sorted by ``_ce_score`` descending
    """

    def __init__(self, model_name: str) -> None:
        self._model_name = model_name
        self._model = None

    # ── Public API ──────────────────────────────────────────────────

    def rerank(self, query: str, documents: list[dict]) -> list[dict]:
        """Re-rank *documents* by cross-encoder relevance to *query*.

        Each document gains a ``_ce_score`` field.  Empty / single-doc
        lists are returned unchanged (no scoring needed).
        """
        if len(documents) <= 1:
            return documents

        self._ensure_model()
        texts = [_doc_text(doc) for doc in documents]

        try:
            scores = list(self._model.rerank(query, texts))  # type: ignore[union-attr]
        except Exception:
            logger.exception("Cross-Encoder reranking failed — returning original order")
            return documents

        # Pair, sort descending by score
        paired = sorted(
            zip(scores, documents),
            key=lambda x: x[0],
            reverse=True,
        )
        result: list[dict] = []
        for score, doc in paired:
            doc = dict(doc)  # shallow copy to avoid mutating originals
            doc["_ce_score"] = score
            result.append(doc)
        return result

    # ── Internal ────────────────────────────────────────────────────

    def _ensure_model(self) -> None:
        """Lazy-load the ONNX cross-encoder model (first call only)."""
        if self._model is not None:
            return
        from fastembed.rerank.cross_encoder import TextCrossEncoder

        logger.info("Loading Cross-Encoder reranker: %s …", self._model_name)
        self._model = TextCrossEncoder(model_name=self._model_name)
        logger.info("Cross-Encoder reranker ready")


# ── Helpers ────────────────────────────────────────────────────────


def _doc_text(doc: dict) -> str:
    """Build a single search-text string from a result dict."""
    parts = [
        doc.get("bug_title", ""),
        doc.get("error_log_snippet", ""),
        doc.get("final_solution", ""),
        doc.get("root_cause", ""),
    ]
    return "\n".join(p for p in parts if p)
