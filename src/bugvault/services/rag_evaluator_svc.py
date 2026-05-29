"""RAG evaluator — optional quality assessment of retrieval results.

Uses an external OpenAI-compatible LLM to score retrieved documents on
Context Relevance and Faithfulness (RAGAS-inspired).  This runs as an
optional post-processing step inside the executor thread via a
synchronous ``httpx.Client()`` call.

Evaluation records are persisted to ``{data_root}/log/rag_eval.jsonl``
for offline analysis.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import httpx

from bugvault.config import settings
from bugvault.models.rag_eval_result import RAGEvalResult
from bugvault.utils.logger import logger


class RAGEvaluator:
    """Optional RAG quality evaluator using an OpenAI-compatible endpoint.

    When disabled or misconfigured, ``evaluate_sync()`` returns an empty
    ``RAGEvalResult`` (both fields ``None``) — it never blocks retrieval.
    """

    def __init__(self) -> None:
        self.enabled = settings.enable_rag_eval
        self.api_key: str = settings.eval_llm_api_key
        self.model: str = settings.eval_llm_model
        # default to OpenAI when base_url is empty
        raw_url: str = settings.eval_llm_base_url or "https://api.openai.com/v1"
        self.base_url = raw_url.rstrip("/")
        self.top_k: int = settings.eval_top_k
        self._timeout: float = 15.0  # seconds

        # ── Persistence ───────────────────────────────────────────
        self._log_dir = Path(settings.data_root) / "log"
        self._log_dir.mkdir(parents=True, exist_ok=True)
        self._log_path = self._log_dir / "rag_eval.jsonl"

    # ── public API ──────────────────────────────────────────────────

    def evaluate_sync(self, query: str, results: list[dict]) -> RAGEvalResult:
        """Score the top-*k* retrieved *results* against *query*.

        Returns an empty ``RAGEvalResult`` when the evaluator is
        disabled, misconfigured, or the API call fails — the caller
        should never block or fail because of evaluation.
        """
        if not self.enabled or not self.api_key:
            return RAGEvalResult()

        eval_candidates = results[: self.top_k]
        if not eval_candidates:
            return RAGEvalResult()

        prompt = self._build_prompt(query, eval_candidates)

        # Retry once on parse failure (exception or parse_error marker)
        max_attempts = 2
        for attempt in range(max_attempts):
            try:
                raw = self._call_llm(prompt)
                result = self._parse_response(raw)

                # If the LLM returned malformed JSON on first try, retry
                if attempt == 0 and result.evaluation == "parse_error":
                    logger.warning("RAG eval parse error on attempt 1, retrying…")
                    continue

                self._persist_eval(query, eval_candidates, result)
                return result
            except Exception:
                if attempt == 0:
                    logger.warning("RAG eval exception on attempt 1, retrying…")
                    continue
                logger.exception("RAG evaluation failed (results returned without scores)")
                self._persist_eval(
                    query, eval_candidates,
                    RAGEvalResult(rag_confidence_score=None, evaluation="error"),
                )
                return RAGEvalResult()

        # Safety fallback (should not be reached)
        return RAGEvalResult()

    # ── internal helpers ────────────────────────────────────────────

    def _build_prompt(self, query: str, results: list[dict]) -> list[dict]:
        """Build a chat-message prompt for the external LLM."""
        docs_lines: list[str] = []
        for i, row in enumerate(results):
            docs_lines.append(
                f"Document {i + 1}:\n"
                f"Title: {row.get('bug_title', '')}\n"
                f"Error: {row.get('error_log_snippet', '')[:500]}\n"
                f"Solution: {row.get('final_solution', '')[:500]}"
            )
        docs_text = "\n\n".join(docs_lines)

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
                "content": f"Query: {query}\n\nRetrieved documents:\n{docs_text}",
            },
        ]

    def _call_llm(self, messages: list[dict]) -> str:
        """POST to the OpenAI-compatible chat completions endpoint."""
        with httpx.Client(timeout=httpx.Timeout(self._timeout)) as client:
            resp = client.post(
                f"{self.base_url}/chat/completions",
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": self.model,
                    "response_format": {"type": "json_object"},
                    "messages": messages,
                    "temperature": 0.1,
                    "max_tokens": 256,
                },
            )
            resp.raise_for_status()
            return resp.json()["choices"][0]["message"]["content"]

    @staticmethod
    def _parse_response(raw: str) -> RAGEvalResult:
        """Extract ``RAGEvalResult`` from the LLM's tri-axis JSON response.

        ``rag_confidence_score`` = ``context_relevance`` + ``faithfulness`` (0–10).
        ``evaluation`` is an alias for ``justification``.

        Tolerates minor formatting variations (e.g. `````json`` fences).
        """
        text = raw.strip()
        # Strip optional markdown code fences
        if text.startswith("```"):
            text = text.split("\n", 1)[-1]
            text = text.rsplit("```", 1)[0]
        text = text.strip()

        try:
            data = json.loads(text)
            cr = float(data.get("context_relevance", 0.0))
            fa = float(data.get("faithfulness", 0.0))
            just = str(data.get("justification", ""))
            # Clamp each axis to [0.0, 5.0]
            cr = max(0.0, min(5.0, cr))
            fa = max(0.0, min(5.0, fa))
            total = cr + fa  # 0–10
            return RAGEvalResult(
                rag_confidence_score=total,
                evaluation=just,
                context_relevance=cr,
                faithfulness=fa,
                justification=just,
            )
        except (json.JSONDecodeError, ValueError, TypeError):
            logger.warning("Failed to parse RAG eval response: %s", raw[:200])
            return RAGEvalResult(rag_confidence_score=0.0, evaluation="parse_error")

    # ── persistence ─────────────────────────────────────────────────

    def _persist_eval(
        self,
        query: str,
        candidates: list[dict],
        result: RAGEvalResult,
    ) -> None:
        """Append one evaluation record to the JSONL log file."""
        record = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "query": query,
            "rag_confidence_score": result.rag_confidence_score,
            "evaluation": result.evaluation,
            "context_relevance": result.context_relevance,
            "faithfulness": result.faithfulness,
            "justification": result.justification,
            "top_k_titles": [r.get("bug_title", "") for r in candidates],
        }
        try:
            with open(self._log_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
        except OSError:
            logger.exception("Failed to persist RAG eval log to %s", self._log_path)