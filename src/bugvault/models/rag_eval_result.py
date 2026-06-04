"""Pydantic model for optional RAG evaluation results."""

from __future__ import annotations

from pydantic import BaseModel, Field


class RAGEvalResult(BaseModel):
    """Quality evaluation of a retrieval result — three-axis RAGAS-inspired.

    ``rag_confidence_score`` is a computed field: ``context_relevance`` +
    ``faithfulness`` (each 0–5 in simple mode; faithfulness is [0,1] in
    claim_level mode, scaled to 0–5 for the total), yielding a 0–10 total.
    """

    strategy_used: str = Field(
        default="simple",
        description="Which evaluation strategy produced this result: simple | claim_level",
    )
    rag_confidence_score: float | None = Field(
        default=None,
        description="Computed score (0-10), or None on failure",
    )
    evaluation: str | None = Field(
        default=None,
        description="The 'justification' string from the LLM — harsh reasoning for deducted points",
    )

    # ── Three-axis RAGAS fields ───────────────────────────────────
    # simple mode: context_relevance [0,5], faithfulness [0,5]
    # claim_level mode: context_relevance [0,5], faithfulness [0,1]
    context_relevance: float | None = Field(
        default=None,
        description="0.0–5.0: Are the retrieved documents useful for answering the query?",
    )
    faithfulness: float | None = Field(
        default=None,
        description="0.0–5.0 (simple) or 0.0–1.0 (claim_level): Is the info faithful to sources?",
    )
    justification: str | None = Field(
        default=None,
        description="Detailed harsh reasoning for why points were deducted",
    )

    # ── Claim-level fields (None in simple mode) ──────────────────
    claims_analysis: list[dict] | None = Field(
        default=None,
        description="Claim-level: list of {claim, supported, reason} dicts",
    )

    # ── Suggested action for the calling agent ───────────────────
    suggested_action: str | None = Field(
        default=None,
        description="Structured guidance: CONFIDENT | PARTIAL | CAUTION | INSUFFICIENT | UNCERTAIN",
    )

    # ── Token usage from the LLM API response ───────────────────
    prompt_tokens: int | None = Field(
        default=None,
        description="Number of tokens in the prompt sent to the judge LLM",
    )
    completion_tokens: int | None = Field(
        default=None,
        description="Number of tokens in the completion from the judge LLM",
    )
    total_tokens: int | None = Field(
        default=None,
        description="Total tokens (prompt + completion) used by the judge LLM",
    )