"""Pydantic model for optional RAG evaluation results."""

from __future__ import annotations

from pydantic import BaseModel, Field


class RAGEvalResult(BaseModel):
    """Quality evaluation of a retrieval result — three-axis RAGAS-inspired.

    ``rag_confidence_score`` is a computed field: ``context_relevance`` +
    ``faithfulness`` (each 0–5), yielding a 0–10 total.
    """

    rag_confidence_score: float | None = Field(
        default=None,
        description="Computed: context_relevance + faithfulness (0-10), or None on failure",
    )
    evaluation: str | None = Field(
        default=None,
        description="The 'justification' string from the LLM — harsh reasoning for deducted points",
    )

    # ── Three-axis RAGAS fields (each 0.0–5.0) ────────────────────
    context_relevance: float | None = Field(
        default=None,
        description="0.0–5.0: Are the retrieved documents useful for answering the query?",
    )
    faithfulness: float | None = Field(
        default=None,
        description="0.0–5.0: Is the extracted information faithful to the source documents?",
    )
    justification: str | None = Field(
        default=None,
        description="Detailed harsh reasoning for why points were deducted",
    )