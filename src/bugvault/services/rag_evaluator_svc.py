"""RAG evaluator — strategy-based quality assessment of retrieval results.

Each strategy implements the ``RAGEvalStrategy`` protocol and is selected
at runtime by the ``eval_depth`` parameter of the retrieve tool.

Evaluation records are persisted to ``{data_root}/log/rag_eval.jsonl``.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Protocol

import httpx

from bugvault.config import settings
from bugvault.models.rag_eval_result import RAGEvalResult
from bugvault.utils.logger import logger


# ═══════════════════════════════════════════════════════════════════
#  Strategy Protocol
# ═══════════════════════════════════════════════════════════════════


class RAGEvalStrategy(Protocol):
    """Protocol for RAG evaluation strategies.

    Each strategy retrieves query + pre-formatted context and scores
    the retrieval quality by calling an external LLM.
    """

    async def evaluate(self, query: str, context: str) -> RAGEvalResult:
        """Score retrieved documents against the query.

        Args:
            query: The user's search query.
            context: Pre-formatted retrieved documents as text block.

        Returns:
            RAGEvalResult with scores, justification, and optional claims data.
        """
        ...


# ═══════════════════════════════════════════════════════════════════
#  Shared helpers
# ═══════════════════════════════════════════════════════════════════


def format_context(results: list[dict], top_k: int) -> str:
    """Format top-k results into a text block for LLM evaluation."""
    parts: list[str] = []
    for i, row in enumerate(results[:top_k], 1):
        parts.append(
            f"Document {i}:\n"
            f"Title: {row.get('bug_title', '')}\n"
            f"Error: {row.get('error_log_snippet', '')[:500]}\n"
            f"Solution: {row.get('final_solution', '')[:500]}"
        )
    return "\n\n".join(parts)


def _persist_eval(
    log_path: Path,
    query: str,
    candidates_titles: list[str],
    result: RAGEvalResult,
) -> None:
    """Append one evaluation record to the JSONL log file."""
    record = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "query": query,
        "strategy_used": result.strategy_used,
        "rag_confidence_score": result.rag_confidence_score,
        "evaluation": result.evaluation,
        "context_relevance": result.context_relevance,
        "faithfulness": result.faithfulness,
        "justification": result.justification,
        "claims_analysis": result.claims_analysis,
        "prompt_tokens": result.prompt_tokens,
        "completion_tokens": result.completion_tokens,
        "total_tokens": result.total_tokens,
        "top_k_titles": candidates_titles,
    }
    try:
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    except OSError:
        logger.exception("Failed to persist RAG eval log to %s", log_path)


def _strip_json_fence(raw: str) -> str:
    """Strip optional markdown code fences from LLM output."""
    text = raw.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[-1]
        text = text.rsplit("```", 1)[0]
    return text.strip()


# ═══════════════════════════════════════════════════════════════════
#  SimpleRAGEvalStrategy — holistic scoring
# ═══════════════════════════════════════════════════════════════════


class SimpleRAGEvalStrategy:
    """Holistic scoring: single LLM call for context_relevance + faithfulness (0–5 each).

    This is the same logic as the original ``RAGEvaluator.evaluate_sync()``
    but ported to async HTTP and the strategy interface.
    """

    def __init__(
        self,
        api_key: str,
        model: str,
        base_url: str,
        top_k: int,
        timeout: float,
        log_path: Path,
    ) -> None:
        self._api_key = api_key
        self._model = model
        self._base_url = base_url
        self._top_k = top_k
        self._timeout = timeout
        self._log_path = log_path

    async def evaluate(self, query: str, context: str) -> RAGEvalResult:
        """Holistic two-axis scoring (context_relevance + faithfulness)."""
        if not context.strip():
            return RAGEvalResult(strategy_used="simple")

        prompt = self._build_prompt(query, context)

        # Retry once on parse failure
        max_attempts = 2
        for attempt in range(max_attempts):
            try:
                raw, usage = await self._call_llm(prompt)
                result = self._parse_response(raw)
                self._attach_usage(result, usage)

                if attempt == 0 and result.evaluation == "parse_error":
                    logger.warning("SimpleRAGEval: parse error on attempt 1, retrying…")
                    continue

                result.strategy_used = "simple"
                titles = _extract_titles(context)
                _persist_eval(self._log_path, query, titles, result)
                return result
            except Exception:
                if attempt == 0:
                    logger.warning("SimpleRAGEval: exception on attempt 1, retrying…")
                    continue
                logger.exception("SimpleRAGEval: failed after retry")
                result = RAGEvalResult(
                    rag_confidence_score=None,
                    evaluation="error",
                    strategy_used="simple",
                )
                titles = _extract_titles(context)
                _persist_eval(self._log_path, query, titles, result)
                return result

        return RAGEvalResult(strategy_used="simple")

    def _build_prompt(self, query: str, context: str) -> list[dict]:
        """Build a chat-message prompt for holistic scoring."""
        return [
            {
                "role": "system",
                "content": (
                    "You are a strict RAG evaluation assistant. Given a user query "
                    "and retrieved documents, score the retrieval quality on "
                    "two independent criteria (0.0-5.0 each):\n"
                    "1. context_relevance: How useful are the retrieved documents "
                    "for answering this query? Deduct points for off-topic docs.\n"
                    "2. faithfulness: Is the extracted information faithful to "
                    "the source documents? Deduct points for hallucination.\n"
                    "3. justification: A HARSH paragraph explaining every "
                    "point deduction — be critical.\n"
                    "Return ONLY valid JSON with no markdown formatting:\n"
                    '{"context_relevance": <0.0-5.0>, '
                    '"faithfulness": <0.0-5.0>, '
                    '"justification": "<critical reasoning>"}'
                ),
            },
            {
                "role": "user",
                "content": f"Query: {query}\n\nRetrieved documents:\n{context}",
            },
        ]

    async def _call_llm(self, messages: list[dict]) -> tuple[str, dict | None]:
        """POST to the OpenAI-compatible chat completions endpoint.

        Returns:
            (content_text, usage_dict) where usage has prompt_tokens,
            completion_tokens, total_tokens keys, or None if unavailable.
        """
        async with httpx.AsyncClient(timeout=httpx.Timeout(self._timeout)) as client:
            resp = await client.post(
                f"{self._base_url}/chat/completions",
                headers={
                    "Authorization": f"Bearer {self._api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": self._model,
                    "response_format": {"type": "json_object"},
                    "messages": messages,
                    "temperature": 0.1,
                    "max_tokens": 256,
                },
            )
            resp.raise_for_status()
            data = resp.json()
            content = data["choices"][0]["message"]["content"]
            usage = data.get("usage")  # {prompt_tokens, completion_tokens, total_tokens}
            return content, usage

    @staticmethod
    def _attach_usage(result: RAGEvalResult, usage: dict | None) -> None:
        """Set token usage fields on *result* from the API usage dict."""
        if usage:
            result.prompt_tokens = usage.get("prompt_tokens")
            result.completion_tokens = usage.get("completion_tokens")
            result.total_tokens = usage.get("total_tokens")

    @staticmethod
    def _parse_response(raw: str) -> RAGEvalResult:
        """Extract ``RAGEvalResult`` from the LLM's two-axis JSON.

        ``rag_confidence_score`` = ``context_relevance`` + ``faithfulness`` (0–10).
        """
        text = _strip_json_fence(raw)

        try:
            data = json.loads(text)
            cr = float(data.get("context_relevance", 0.0))
            fa = float(data.get("faithfulness", 0.0))
            just = str(data.get("justification", ""))
            cr = max(0.0, min(5.0, cr))
            fa = max(0.0, min(5.0, fa))
            return RAGEvalResult(
                rag_confidence_score=cr + fa,
                evaluation=just,
                context_relevance=cr,
                faithfulness=fa,
                justification=just,
            )
        except (json.JSONDecodeError, ValueError, TypeError):
            logger.warning("SimpleRAGEval: parse error: %s", raw[:200])
            return RAGEvalResult(rag_confidence_score=0.0, evaluation="parse_error")


# ═══════════════════════════════════════════════════════════════════
#  ClaimLevelRAGEvalStrategy — claim extraction + verification
# ═══════════════════════════════════════════════════════════════════


class ClaimLevelRAGEvalStrategy:
    """Claim-level evaluation: extraction → verification → scoring.

    Forces the LLM to:
    1. Extract atomic factual claims from the retrieved documents.
    2. Verify each claim against the source context.
    3. Score faithfulness as supported_claims / total_claims.
    4. Score context_relevance by checking information-need coverage.
    """

    def __init__(
        self,
        api_key: str,
        model: str,
        base_url: str,
        top_k: int,
        timeout: float,
        log_path: Path,
    ) -> None:
        self._api_key = api_key
        self._model = model
        self._base_url = base_url
        self._top_k = top_k
        self._timeout = timeout
        self._log_path = log_path

    async def evaluate(self, query: str, context: str) -> RAGEvalResult:
        """Claim-level evaluation with CoT extraction + verification."""
        if not context.strip():
            return RAGEvalResult(strategy_used="claim_level")

        prompt = self._build_claim_prompt(query, context)

        max_attempts = 2
        for attempt in range(max_attempts):
            try:
                raw, usage = await self._call_llm(prompt)
                result = self._parse_claim_response(raw, query)
                SimpleRAGEvalStrategy._attach_usage(result, usage)

                if attempt == 0 and (
                    result.rag_confidence_score is None
                    and result.evaluation == "parse_error"
                ):
                    logger.warning(
                        "ClaimLevelRAGEval: parse error on attempt 1, retrying…"
                    )
                    continue

                result.strategy_used = "claim_level"
                titles = _extract_titles(context)
                _persist_eval(self._log_path, query, titles, result)
                return result
            except Exception:
                if attempt == 0:
                    logger.warning(
                        "ClaimLevelRAGEval: exception on attempt 1, retrying…"
                    )
                    continue
                logger.exception("ClaimLevelRAGEval: failed after retry")
                return RAGEvalResult(
                    rag_confidence_score=None,
                    evaluation="error",
                    strategy_used="claim_level",
                )

        return RAGEvalResult(strategy_used="claim_level")

    def _build_claim_prompt(self, query: str, context: str) -> list[dict]:
        """Build a CoT prompt forcing claim extraction → verification → scoring."""
        return [
            {
                "role": "system",
                "content": (
                    "You are a strict RAG evaluation assistant. Your task is to "
                    "evaluate retrieval quality through **atomic claim analysis**.\n\n"

                    "Follow these steps in your reasoning:\n\n"

                    "## Step 1: Claim Extraction\n"
                    "From the **retrieved documents**, extract every atomic factual "
                    "claim that is relevant to the user's query. An atomic claim is a "
                    "single verifiable statement (e.g. 'ValueError is raised if x is "
                    "not found'). List each claim separately.\n\n"

                    "## Step 2: Claim Verification\n"
                    "For each claim, determine whether it is FULLY supported by "
                    "the source documents, PARTIALLY supported, or UNSUPPORTED. "
                    "Be harsh — if the source documents don't explicitly confirm "
                    "a claim, mark it as UNSUPPORTED.\n\n"

                    "## Step 3: Scoring\n"
                    "- faithfulness = (number of FULLY supported claims) / (total claims)\n"
                    "- context_relevance: How many of the user's key information "
                    "needs (implicit in the query) are covered by the retrieved "
                    "documents? Score 0.0-5.0.\n"
                    "- justification: A harsh paragraph explaining WHY points were "
                    "deducted. Mention specific claims that were unsupported.\n\n"

                    "Return ONLY valid JSON with this exact schema:\n"
                    '{\n'
                    '  "claims_analysis": [\n'
                    '    {\n'
                    '      "claim": "<the atomic claim text>",\n'
                    '      "supported": true|false|"partial",\n'
                    '      "reason": "<why this claim is supported or not>"\n'
                    '    }\n'
                    '  ],\n'
                    '  "faithfulness": <0.0-1.0>,\n'
                    '  "context_relevance": <0.0-5.0>,\n'
                    '  "justification": "<harsh critical paragraph>"\n'
                    '}'
                ),
            },
            {
                "role": "user",
                "content": (
                    f"## User Query\n{query}\n\n"
                    f"## Retrieved Documents\n{context}"
                ),
            },
        ]

    async def _call_llm(self, messages: list[dict]) -> tuple[str, dict | None]:
        """POST to the OpenAI-compatible chat completions endpoint.

        Returns:
            (content_text, usage_dict) where usage has prompt_tokens,
            completion_tokens, total_tokens keys, or None if unavailable.
        """
        async with httpx.AsyncClient(timeout=httpx.Timeout(self._timeout)) as client:
            resp = await client.post(
                f"{self._base_url}/chat/completions",
                headers={
                    "Authorization": f"Bearer {self._api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": self._model,
                    "response_format": {"type": "json_object"},
                    "messages": messages,
                    "temperature": 0.1,
                    "max_tokens": 2048,
                },
            )
            resp.raise_for_status()
            data = resp.json()
            content = data["choices"][0]["message"]["content"]
            usage = data.get("usage")
            return content, usage

    @staticmethod
    def _parse_claim_response(raw: str, query: str) -> RAGEvalResult:
        """Parse the LLM's claim-level JSON into RAGEvalResult."""
        text = _strip_json_fence(raw)

        try:
            data = json.loads(text)

            # ── Parse claims_analysis ──────────────────────────────
            claims = data.get("claims_analysis", [])
            if not isinstance(claims, list):
                claims = []

            # ── Compute faithfulness from claims ───────────────────
            total_claims = len(claims)
            supported_count = sum(
                1 for c in claims if c.get("supported") is True
            )
            faithfulness = (
                round(supported_count / total_claims, 4)
                if total_claims > 0
                else 0.0
            )

            # ── Parse context_relevance ────────────────────────────
            cr = float(data.get("context_relevance", 0.0))
            cr = max(0.0, min(5.0, cr))

            # ── Parse justification ────────────────────────────────
            just = str(data.get("justification", ""))

            # ── Build total confidence score ───────────────────────
            # Scale faithfulness [0,1] → [0,5] so total stays 0–10
            total = round(faithfulness * 5.0 + cr, 2)

            return RAGEvalResult(
                rag_confidence_score=total,
                evaluation=just,
                context_relevance=cr,
                faithfulness=faithfulness,
                justification=just,
                claims_analysis=claims,
            )
        except (json.JSONDecodeError, ValueError, TypeError):
            logger.warning("ClaimLevelRAGEval: parse error: %s", raw[:200])
            return RAGEvalResult(
                rag_confidence_score=0.0,
                evaluation="parse_error",
                claims_analysis=[],
            )


# ═══════════════════════════════════════════════════════════════════
#  Shared helper — extract titles from formatted context
# ═══════════════════════════════════════════════════════════════════


def _extract_titles(context: str) -> list[str]:
    """Extract document titles from a formatted context block."""
    titles: list[str] = []
    for line in context.split("\n"):
        if line.startswith("Title: "):
            titles.append(line[7:])
    return titles


# ═══════════════════════════════════════════════════════════════════
#  RAGEvaluator — facade with strategy selection + circuit breaker
# ═══════════════════════════════════════════════════════════════════


class RAGEvaluator:
    """Facade that selects a RAG evaluation strategy at runtime.

    Thread-safe class-level counter tracks ``claim_level`` invocations;
    auto-falls back to ``simple`` when the session budget is exhausted
    (circuit breaker).
    """

    _claim_counter: int = 0  # session-scoped, never reset

    def __init__(self) -> None:
        self.enabled = settings.enable_rag_eval
        self.api_key: str = settings.eval_llm_api_key
        self.model: str = settings.eval_llm_model
        raw_url: str = settings.eval_llm_base_url or "https://api.openai.com/v1"
        self.base_url = raw_url.rstrip("/")
        self.top_k: int = settings.eval_top_k
        self._timeout: float = 15.0

        # ── Persistence ───────────────────────────────────────────
        self._log_dir = Path(settings.data_root) / "log"
        self._log_dir.mkdir(parents=True, exist_ok=True)
        self._log_path = self._log_dir / "rag_eval.jsonl"

        # ── Shared strategy instances (lazy init) ─────────────────
        self._simple_strategy: SimpleRAGEvalStrategy | None = None
        self._claim_strategy: ClaimLevelRAGEvalStrategy | None = None

    # ── Public API ──────────────────────────────────────────────────

    async def evaluate(
        self,
        query: str,
        context: str,
        eval_depth: str = "simple",
    ) -> RAGEvalResult:
        """Evaluate retrieval quality with the strategy selected by *eval_depth*.

        Args:
            query: User's search query.
            context: Pre-formatted retrieved documents text block.
            eval_depth: ``"simple"`` (holistic, cheap) or ``"claim_level"``
                (claim extraction + verification, expensive).

        Returns:
            RAGEvalResult. Falls back to simple when claim_level budget
            is exhausted; returns empty result when disabled.
        """
        if not self.enabled or not self.api_key:
            return RAGEvalResult(strategy_used=eval_depth)

        if eval_depth == "claim_level":
            return await self._claim_level_or_fallback(query, context)

        # "simple" or any unrecognized value
        return await self._get_simple().evaluate(query, context)

    # ── Circuit breaker logic ───────────────────────────────────────

    async def _claim_level_or_fallback(
        self,
        query: str,
        context: str,
    ) -> RAGEvalResult:
        """Run claim_level eval or fall back to simple if budget exhausted."""
        if RAGEvaluator._claim_counter >= settings.max_claim_evals_per_session:
            logger.warning(
                "Claim-level eval budget (%d) exhausted, falling back to simple",
                settings.max_claim_evals_per_session,
            )
            result = await self._get_simple().evaluate(query, context)
            result.strategy_used = "simple"
            return result

        RAGEvaluator._claim_counter += 1
        return await self._get_claim().evaluate(query, context)

    # ── Lazy strategy constructors ──────────────────────────────────

    def _get_simple(self) -> SimpleRAGEvalStrategy:
        if self._simple_strategy is None:
            self._simple_strategy = SimpleRAGEvalStrategy(
                api_key=self.api_key,
                model=self.model,
                base_url=self.base_url,
                top_k=self.top_k,
                timeout=self._timeout,
                log_path=self._log_path,
            )
        return self._simple_strategy

    def _get_claim(self) -> ClaimLevelRAGEvalStrategy:
        if self._claim_strategy is None:
            self._claim_strategy = ClaimLevelRAGEvalStrategy(
                api_key=self.api_key,
                model=self.model,
                base_url=self.base_url,
                top_k=self.top_k,
                timeout=self._timeout,
                log_path=self._log_path,
            )
        return self._claim_strategy
