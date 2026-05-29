"""Pydantic model for optional RAG evaluation results."""

from __future__ import annotations

from pydantic import BaseModel, Field


class RAGEvalResult(BaseModel):
    """Quality evaluation of a retrieval result."""

    rag_confidence_score: float | None = Field(
        default=None,
        description="Average relevance+faithfulness score (0-10), or None on failure",
    )
    evaluation: str | None = Field(
        default=None,
        description="Natural-language assessment, or None on failure",
    )