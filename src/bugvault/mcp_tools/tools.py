"""MCP tool definitions for BugVault.

Registration
------------
    server = Server(settings.server_name)
    db = LanceDBClient()
    executor = ThreadPoolExecutor(...)
    register_tools(server, db, embedding_svc, reflection_svc, rag_evaluator, executor)

This module owns the schema / metadata for each tool and delegates all
business logic to the ``services`` layer.  The ``database`` layer is
never imported directly — only accessed through service objects.
"""

from __future__ import annotations

import asyncio
import concurrent.futures

from mcp.server import Server
import mcp.types as types

from bugvault.config import settings
from bugvault.models.bug_record import BugRecord
from bugvault.services.archive_svc import write_markdown_archive
from bugvault.services.ingestion_svc import validate_and_prepare
from bugvault.services.retrieval_svc import rerank, rrf_fusion
from bugvault.utils.logger import logger

# Lazy imports (to avoid circular deps at module level):
#   EmbeddingService  → services.embedding_svc  (conditionally imported)
#   ReflectionService → services.reflection_svc  (conditionally imported)
#   RAGEvaluator      → services.rag_evaluator_svc  (conditionally imported)
#   format_context    → services.rag_evaluator_svc  (conditionally imported)


# ===================================================================
#  JSON Schemas for MCP tool input
# ===================================================================

_RETRIEVE_SCHEMA = {
    "type": "object",
    "properties": {
        "query": {
            "type": "string",
            "description": (
                "Error message, stack trace, or natural-language "
                "description of the bug"
            ),
        },
        "eval_depth": {
            "type": "string",
            "enum": ["none", "simple", "claim_level"],
            "description": (
                "RAG evaluation depth. "
                "'none' = skip evaluation. "
                "'simple' (default) = fast holistic scoring. "
                "'claim_level' = atomic claim extraction + verification "
                "(more tokens, richer signal, session-capped)"
            ),
        },
        "target_tech_stack": {
            "type": "string",
            "description": (
                "CRITICAL: When you can infer the programming language, "
                "framework, or runtime from the error message or code "
                "context, you MUST pass it here to filter retrieval. "
                "Examples: 'Python', 'Java', 'Go', 'TypeScript', "
                "'Django', 'Spring Boot', 'Kubernetes'. "
                "Case-insensitive. This eliminates cross-language "
                "confusion (e.g. Python ModuleNotFoundError vs Java "
                "ClassNotFoundException)."
            ),
        },
        "target_project_name": {
            "type": "string",
            "description": (
                "Optional: The specific project or service name to "
                "narrow the search to (e.g. 'bugvault-v2', "
                "'order-svc', 'frontend-api'). "
                "Only records whose project_name field matches will "
                "be searched. Case-insensitive."
            ),
        },
    },
    "required": ["query"],
}

_SAVE_SCHEMA = {
    "type": "object",
    "properties": {
        "bug_title": {"type": "string", "description": "Short descriptive title"},
        "error_log_snippet": {"type": "string", "description": "Error message or stack trace"},
        "tried_methods": {"type": "string", "description": "Methods already attempted"},
        "final_solution": {"type": "string", "description": "The working fix"},
        "project_name": {"type": "string", "description": "Affected project (optional)"},
        "tech_stack": {"type": "string", "description": "Technology tags (optional)"},
        "root_cause": {"type": "string", "description": "Root cause analysis (optional)"},
    },
    "required": ["bug_title", "error_log_snippet", "tried_methods", "final_solution"],
}

_REFLECT_SCHEMA = {
    "type": "object",
    "properties": {
        "reflection_text": {
            "type": "string",
            "description": (
                "Detailed analysis of what caused the bug — e.g., "
                "\"misunderstood user intent about config file location\""
            ),
        },
        "error_category": {
            "type": "string",
            "enum": [
                "understanding_bias",
                "code_logic_error",
                "api_misuse",
                "environment_issue",
                "other",
            ],
            "description": "Category of the error root cause",
        },
        "preventive_rule": {
            "type": "string",
            "description": (
                "Concise actionable rule to prevent recurrence. "
                "This will be persisted to CLAUDE.md."
            ),
        },
    },
    "required": ["reflection_text", "error_category", "preventive_rule"],
}


# ===================================================================
#  Tool registration
# ===================================================================


def register_tools(
    server: Server,
    db,  # LanceDBClient
    embedding_svc=None,  # EmbeddingService | None
    reflection_svc=None,  # ReflectionService | None
    rag_evaluator=None,  # RAGEvaluator | None
    executor: concurrent.futures.ThreadPoolExecutor | None = None,
) -> None:
    """Register list-tools and call-tool handlers on *server*.

    Parameters
    ----------
    db : LanceDBClient
        Data-access layer for LanceDB.
    embedding_svc : EmbeddingService | None
        Optional — required for async embedding hook.
    reflection_svc : ReflectionService | None
        Optional — required for ``reflect_and_prevent_error`` tool.
    rag_evaluator : RAGEvaluator | None
        Optional — required for RAG evaluation on retrieval.
    executor : ThreadPoolExecutor | None
        Shared thread pool; created internally if not provided.
    """
    if executor is None:
        executor = concurrent.futures.ThreadPoolExecutor(
            max_workers=settings.thread_pool_workers,
            thread_name_prefix="bugvault-io",
        )

    @server.list_tools()
    async def handle_list_tools() -> list[types.Tool]:
        tools: list[types.Tool] = [
            types.Tool(
                name="retrieve_bug_experience",
                description=(
                    "CRITICAL: You MUST ALWAYS call this tool FIRST before providing any fix, suggestion, or analysis for a bug, error log, stack trace, or exception. "
                    "NEVER rely on your general knowledge or training data until you have queried this local BugVault database for historical context. "
                    "MANDATORY WORKFLOW: When user presents ANY error message, crash report, debugging issue, or code problem → IMMEDIATELY invoke this tool with the error details. "
                    "ONLY after retrieving past experiences from the knowledge base should you proceed to analyze and propose solutions. "
                    "This ensures you leverage accumulated project-specific insights instead of repeating past mistakes. "
                    "FAILURE TO CALL THIS TOOL FIRST will result in suboptimal debugging and ignored organizational knowledge."
                ),
                inputSchema=_RETRIEVE_SCHEMA,
            ),
            types.Tool(
                name="save_bug_experience",
                description=(
                    "CRITICAL: You MUST call this tool IMMEDIATELY after successfully resolving ANY bug, error, or unexpected behavior — without exception. "
                    "MANDATORY TRIGGER: Every time a debugging session concludes with a working solution, you are REQUIRED to persist this experience using save_bug_experience. "
                    "REQUIRED FIELDS: bug_title (concise descriptive title), error_log_snippet (exact error message or stack trace), tried_methods (what you attempted that failed), final_solution (the working fix). "
                    "OPTIONAL ENRICHMENT: project_name, tech_stack, root_cause can be added later but core fields are mandatory NOW. "
                    "WARNING: Skipping this step means losing valuable institutional knowledge and forcing future developers to re-solve the same problem. "
                    "ALWAYS capture the lesson while it's fresh — do NOT delay or skip this critical knowledge preservation step."
                ),
                inputSchema=_SAVE_SCHEMA,
            ),
        ]

        if reflection_svc is not None:
            tools.append(
                types.Tool(
                    name="reflect_and_prevent_error",
                    description=(
                        "CRITICAL: After fixing a significant or recurring bug, you MUST call this tool to perform root cause analysis and generate preventive rules. "
                        "MANDATORY FOR: Architecture-level mistakes, repeated errors, design pattern violations, or bugs revealing systemic issues. "
                        "WORKFLOW: Analyze WHY the bug occurred → Identify the fundamental misunderstanding or flawed assumption → Formulate an actionable rule → Persist to CLAUDE.md. "
                        "REQUIRED FIELDS: reflection_text (detailed analysis of what caused the bug and why), error_category (classification from predefined enum), preventive_rule (concise, actionable guideline to prevent recurrence). "
                        "IMPACT: This transforms individual debugging sessions into organizational learning — the generated rules become permanent guardrails in CLAUDE.md. "
                        "DO NOT SKIP: Failing to reflect means the same mistake will likely recur. Capture the lesson permanently."
                    ),
                    inputSchema=_REFLECT_SCHEMA,
                ),
            )

        return tools

    @server.call_tool()
    async def handle_call_tool(
        name: str, arguments: dict,
    ) -> list[types.TextContent | types.ImageContent | types.EmbeddedResource]:
        loop = asyncio.get_running_loop()

        try:
            if name == "retrieve_bug_experience":
                return await _handle_retrieve(
                    loop, executor, db, embedding_svc, rag_evaluator,
                    arguments,
                )

            if name == "save_bug_experience":
                return await _handle_save(
                    loop, executor, db, embedding_svc, arguments,
                )

            if name == "reflect_and_prevent_error":
                if reflection_svc is None:
                    return [types.TextContent(
                        type="text",
                        text="Reflection tool is not enabled. "
                             "Set BUGVAULT_ENABLE_REFLECTION_TOOL=true in .env",
                    )]
                return await loop.run_in_executor(
                    executor,
                    _sync_reflect,
                    reflection_svc,
                    arguments,
                )

            return [types.TextContent(
                type="text",
                text=f"Unknown tool: {name}",
            )]

        except Exception as exc:
            logger.exception("Tool call failed: %s", name)
            return [types.TextContent(
                type="text",
                text=f"Error executing {name}: {exc}",
            )]


# ===================================================================
#  Save — zero-blocking async flow
# ===================================================================


async def _handle_save(loop, executor, db, embedding_svc, arguments):
    """Synchronous validate + archive, then fire-and-forget async embedding."""
    # ── SYNC PATH (in executor) ──────────────────────────────────────
    texts, record = await loop.run_in_executor(
        executor,
        _sync_save_validate,  # returns (list[TextContent], BugRecord | None)
        arguments,
    )

    # If validation failed, record is None and texts contain the error
    if record is None:
        return texts

    # ── ASYNC HOOK (fire-and-forget) ────────────────────────────────
    if settings.enable_async_embedding and embedding_svc is not None:
        asyncio.ensure_future(
            _async_embed_and_store(loop, executor, db, embedding_svc, record),
        )

    return texts


def _sync_save_validate(
    arguments: dict,
) -> tuple[list[types.TextContent], BugRecord | None]:
    """Pydantic-validate, check required fields, write Markdown archive.

    Returns ``(TextContent list, BugRecord)`` on success, or
    ``(TextContent list, None)`` on validation failure.
    """
    try:
        record = BugRecord(**arguments)
    except Exception as exc:
        return (
            [types.TextContent(type="text", text=f"Invalid record: {exc}")],
            None,
        )

    missing = validate_and_prepare(record)
    if missing:
        return (
            [types.TextContent(
                type="text",
                text=(
                    f"Record saved as draft. Missing fields: "
                    f"{', '.join(missing)}. "
                    f"You can update the record later."
                ),
            )],
            record,
        )

    # ── Markdown archive (fast, sync I/O) ────────────────────────
    try:
        write_markdown_archive(record)
    except Exception:
        logger.exception("Failed to write markdown archive (non-fatal)")

    return (
        [types.TextContent(
            type="text",
            text=(
                f"Bug record '{record.bug_title}' saved successfully. "
                f"I can now retrieve it in future troubleshooting sessions."
            ),
        )],
        record,
    )


async def _async_embed_and_store(loop, executor, db, embedding_svc, record):
    """Background task: generate embedding + LanceDB upsert + chunk upsert.

    Never awaited by the caller — runs as a fire-and-forget coroutine.
    Failures are logged but do not propagate to the client.

    .. versionchanged:: 1.1.1

       Also generates two parent-child chunks (``error_log`` and
       ``semantic``) and upserts them into ``bugvault_chunks``.
    """
    try:
        search_text = record.to_search_text()
        chunk_defs = record.to_chunks()

        def _work():
            # ── 1. Embed and upsert the full parent record ────────
            full_emb = embedding_svc.generate_embedding(search_text)
            db.upsert_record(search_text, full_emb, record)

            # ── 2. Embed and upsert each chunk ────────────────────
            chunk_rows: list[dict] = []
            for cd in chunk_defs:
                chunk_emb = embedding_svc.generate_embedding(cd["search_text"])
                chunk_rows.append({
                    "vector": chunk_emb,
                    "chunk_id": cd["chunk_id"],
                    "parent_id": cd["parent_id"],
                    "chunk_type": cd["chunk_type"],
                    "search_text": cd["search_text"],
                    "tech_stack": record.tech_stack or "",
                    "project_name": record.project_name or "",
                })
            db.upsert_chunks(chunk_rows)

        await loop.run_in_executor(executor, _work)
        logger.info(
            "Async embedding + storage completed: %s (2 chunks upserted)",
            record.bug_title,
        )
    except Exception:
        logger.exception("Async embedding + storage failed: %s", record.bug_title)


# ===================================================================
#  Retrieve — hybrid search + optional async RAG evaluation
# ===================================================================


async def _handle_retrieve(
    loop,
    executor,
    db,
    embedding_svc,
    rag_evaluator,
    arguments: dict,
) -> list[types.TextContent]:
    """ANN search → hybrid rerank → optional async RAG eval → format text."""
    query = arguments.get("query", "")
    eval_depth = arguments.get("eval_depth", "simple")
    target_tech_stack = arguments.get("target_tech_stack", "")
    target_project_name = arguments.get("target_project_name", "")

    # ── Sync search + format runs in executor ────────────────────
    result = await loop.run_in_executor(
        executor,
        _sync_search_and_format,
        db,
        embedding_svc,
        query,
        target_tech_stack,
        target_project_name,
    )

    # Early-exit for error / empty responses
    if isinstance(result, list):
        return result  # already a list[TextContent] (error or empty)

    lines, results = result

    # ── Async RAG evaluation (I/O-bound, outside executor) ──────
    if (
        rag_evaluator
        and rag_evaluator.enabled
        and eval_depth != "none"
        and results
    ):
        try:
            from bugvault.services.rag_evaluator_svc import format_context

            context = format_context(results, rag_evaluator.top_k)
            eval_result = await rag_evaluator.evaluate(
                query, context, eval_depth,
            )
            _append_eval_to_lines(lines, eval_result)
        except Exception:
            logger.exception(
                "RAG evaluation failed (results returned without scores)"
            )

    return [types.TextContent(type="text", text="\n".join(lines))]


# ── Tech-stack exclusion dictionary ──────────────────────────────
# Prevents LIKE '%java%' from matching "javascript".
# Key = search term the user entered; Value = list of substrings to exclude.
# Extend this dict as new false-positive patterns are discovered.
_TECH_EXCLUSIONS: dict[str, list[str]] = {
    "java": ["javascript"],
}


def _sanitise_filter_value(raw: str) -> str:
    """Strip anything that isn't alphanumeric, space, underscore, hyphen, or dot."""
    import re
    return re.sub(r"[^a-zA-Z0-9_\-\s. ]", "", raw.strip())


def _build_filter_clause(
    target_tech_stack: str,
    target_project_name: str,
) -> str | None:
    """Build a case-insensitive WHERE clause from optional filter values.

    Applies exclusion sub-strings (e.g. ``java → javascript``) to prevent
    ambiguous ``LIKE '%java%'`` from matching unrelated technologies.
    """
    clauses: list[str] = []
    if target_tech_stack:
        val = _sanitise_filter_value(target_tech_stack)
        if val:
            val_lower = val.lower()
            clauses.append(f"LOWER(tech_stack) LIKE '%{val_lower}%'")
            # Append NOT LIKE for exclusion terms
            for exclude_word in _TECH_EXCLUSIONS.get(val_lower, []):
                clauses.append(f"LOWER(tech_stack) NOT LIKE '%{exclude_word}%'")
    if target_project_name:
        val = _sanitise_filter_value(target_project_name)
        if val:
            clauses.append(f"LOWER(project_name) LIKE '%{val.lower()}%'")
    return " AND ".join(clauses) if clauses else None


def _sync_search_and_format(
    db,
    embedding_svc,
    query: str,
    target_tech_stack: str = "",
    target_project_name: str = "",
) -> list[types.TextContent] | tuple[list[str], list[dict]]:
    """ANN search → hybrid rerank → format results into text lines.

    Returns either a ``list[TextContent]`` (early exit for errors / empty)
    or a ``(lines, results)`` tuple for further processing.
    """
    if not query.strip():
        return [types.TextContent(
            type="text",
            text="Query is empty. Please provide an error description.",
        )]

    if not db.is_ready:
        return [types.TextContent(
            type="text",
            text="BugVault is still initialising. Please try again in a moment.",
        )]

    # ── embedding + ANN search (use shared EmbeddingService) ───────
    if embedding_svc is None:
        from bugvault.services.embedding_svc import EmbeddingService
        embedding_svc = EmbeddingService()

    rerank_limit = settings.top_k * 4  # expand candidate pool for reranker
    filter_clause = _build_filter_clause(target_tech_stack, target_project_name)
    query_emb = embedding_svc.generate_embedding(query)

    # ── Primary path: search chunks table ────────────────────────────
    # Dual recall on bugvault_chunks (Vector + FTS at chunk level)
    vec_chunks = db.search_chunks(
        query_emb, filter_clause=filter_clause, limit=rerank_limit,
    )
    fts_chunks: list[dict] = []
    if settings.enable_fts:
        try:
            fts_chunks = db.search_chunks_fts(
                query, filter_clause=filter_clause,
                limit=rerank_limit,
            )
            fts_chunks = [r for r in fts_chunks if r.get("_score", 0) > 0]
        except Exception:
            logger.warning("Chunks FTS search failed, falling back to vector-only")

    # ── Chunk-level RRF fusion ──────────────────────────────────────
    if fts_chunks:
        logger.info(
            "Retrieve chunks: vec=%d fts=%d — fusing via RRF(k=60)",
            len(vec_chunks), len(fts_chunks),
        )
        chunk_results = rrf_fusion(vec_chunks, fts_chunks)
    else:
        chunk_results = vec_chunks

    # Variables for format section (populated by either path)
    vec_results: list[dict] = []
    fts_results: list[dict] = []
    ce_used = False

    if not chunk_results:
        # ── Fallback: search parent bug_records via FTS only ────
        # Vector search disabled because all parent vectors are [0.0]*dim
        # (zero-vector optimization — they're never used for ANN)
        logger.info("Chunks empty — fallback to bug_records FTS search")
        vec_results = []
        if settings.enable_fts:
            try:
                fts_results = db.search_fts(
                    query, filter_clause=filter_clause,
                    limit=rerank_limit,
                )
                fts_results = [r for r in fts_results if r.get("_score", 0) > 0]
            except Exception:
                logger.warning("FTS search failed, falling back to vector-only")
        if fts_results:
            results = rrf_fusion(vec_results, fts_results)
        else:
            results = vec_results
    else:
        # ── Parent-document mapping — group chunks by parent_id ────
        parent_best: dict[str, dict] = {}
        for ch in chunk_results:
            pid = ch.get("parent_id", "") or ""
            if not pid:
                continue
            # Keep the chunk with the best score per parent
            if pid not in parent_best:
                parent_best[pid] = ch
            else:
                existing = parent_best[pid]
                prev_score = existing.get("_distance", 1.0) if "_distance" in existing else -existing.get("_rrf_score", 0.0)
                cur_score = ch.get("_distance", 1.0) if "_distance" in ch else -ch.get("_rrf_score", 0.0)
                if cur_score < prev_score:  # lower distance OR higher RRF (=less negative) wins
                    parent_best[pid] = ch

        # ── Fetch full parent records from bug_records ──────────────
        parent_ids = list(parent_best.keys())
        parent_records = db.fetch_records_by_ids(parent_ids)

        # Build a lookup: record_id → full record
        record_map: dict[str, dict] = {}
        for rec in parent_records:
            rid = rec.get("record_id", "") or ""
            if rid:
                record_map[rid] = rec

        # Merge best chunk's score back onto the full record
        results = []
        for pid, best_chunk in parent_best.items():
            full_rec = record_map.get(pid)
            if full_rec is None:
                continue
            merged = dict(full_rec)  # shallow copy
            if "_distance" in best_chunk:
                merged["_distance"] = best_chunk["_distance"]
            if "_rrf_score" in best_chunk:
                merged["_rrf_score"] = best_chunk["_rrf_score"]
            results.append(merged)

        # Populate source count variables for format section
        vec_results = vec_chunks
        fts_results = fts_chunks

        if not results:
            logger.info("Chunks found but no matching parent records in bug_records")
            return [types.TextContent(
                type="text",
                text="No matching bug experiences found in the knowledge base.",
            )]

    if not results:
        logger.info("Retrieve: no results for query '%s'", query[:80])
        return [types.TextContent(
            type="text",
            text="No matching bug experiences found in the knowledge base.",
        )]

    logger.info(
        "Retrieve: %d raw results for query '%s'",
        len(results), query[:80],
    )

    # ── rerank (semantic threshold / RRF score + time decay) ───────
    pre_count = len(results)
    results = rerank(results, None)
    after_count = len(results)
    if after_count < pre_count:
        logger.info(
            "Retrieve: rerank dropped %d docs (%d → %d)",
            pre_count - after_count, pre_count, after_count,
        )

    # ── Cross-Encoder reranking (optional, lazy-loaded) ──────────
    if settings.enable_reranker and results:
        try:
            from bugvault.services.reranker_svc import get_reranker
            reranker = get_reranker()
            if reranker is not None:
                results = reranker.rerank(query, results)
                ce_used = True
                logger.info("Cross-Encoder reranked %d candidates", len(results))
        except Exception:
            logger.warning("Cross-Encoder reranking failed — using RRF order")

    # ── Truncate to final top_k ─────────────────────────────────
    results = results[:settings.top_k]

    # ── format results into text lines ─────────────────────────────
    lines: list[str] = []
    lines.append("--- Retrieval Info ---")
    if ce_used:
        lines.append("Strategy: hybrid + Cross-Encoder reranking")
    elif fts_results:
        lines.append("Strategy: hybrid (vector + FTS + RRF fusion)")
    else:
        lines.append("Strategy: vector-only")
    lines.append(
        f"Sources:  {len(vec_results)} vector + {len(fts_results)} FTS"
        if fts_results else f"Sources:  {len(vec_results)} vector results"
    )
    lines.append("")
    for i, row in enumerate(results, 1):
        lines.append(f"--- Result {i} ---")
        lines.append(f"Title:    {row.get('bug_title', '(untitled)')}")
        lines.append(f"Project:  {row.get('project_name', '(unknown)')}")
        lines.append(f"Time:     {row.get('create_time', '(unknown)')}")
        lines.append(
            f"Error:\n{row.get('error_log_snippet', '')[:settings.max_record_chars]}"
        )
        lines.append(
            f"Tried:\n{row.get('tried_methods', '')[:settings.max_record_chars]}"
        )
        lines.append(
            f"Solution:\n{row.get('final_solution', '')[:settings.max_record_chars]}"
        )
        if row.get("root_cause"):
            lines.append(
                f"Root cause:\n{row['root_cause'][:settings.max_record_chars]}"
            )
        lines.append("")

    return lines, results


def _compute_suggested_action(eval_result) -> str:
    """Derive structured guidance from evaluation scores."""
    if eval_result.rag_confidence_score is None:
        return "UNCERTAIN"

    score = eval_result.rag_confidence_score
    faithfulness = eval_result.faithfulness
    context_rel = eval_result.context_relevance

    # Low faithfulness → potential hallucination
    if faithfulness is not None and faithfulness < 0.5:
        return "CAUTION"

    # Low context relevance → wrong search direction
    if context_rel is not None and context_rel < 2.0:
        return "INSUFFICIENT"

    if score >= 7.0 and (faithfulness is None or faithfulness >= 0.8):
        return "CONFIDENT"

    if score >= 5.0:
        return "PARTIAL"

    return "UNCERTAIN"


def _append_eval_to_lines(
    lines: list[str],
    eval_result,
) -> None:
    """Append RAG evaluation block to formatted lines if applicable."""
    if eval_result.rag_confidence_score is None:
        return

    # ── Compute suggested action and attach to result ────────────
    eval_result.suggested_action = _compute_suggested_action(eval_result)

    logger.info(
        "Retrieve RAG eval: score=%.1f/10 strategy=%s action=%s tokens=%s/%s/%s",
        eval_result.rag_confidence_score,
        eval_result.strategy_used,
        eval_result.suggested_action,
        eval_result.prompt_tokens,
        eval_result.completion_tokens,
        eval_result.total_tokens,
    )

    lines.append("--- RAG Evaluation ---")
    lines.append(
        f"Strategy:  {eval_result.strategy_used}"
    )
    lines.append(
        f"Action:    {eval_result.suggested_action}"
    )
    lines.append(
        f"Confidence: {eval_result.rag_confidence_score:.1f}/10"
    )

    if eval_result.context_relevance is not None:
        lines.append(
            f"Context relevance: {eval_result.context_relevance:.1f}/5"
        )
    if eval_result.faithfulness is not None:
        # claim_level: faithfulness is [0,1]; simple: [0,5]
        if eval_result.strategy_used == "claim_level":
            lines.append(
                f"Faithfulness: {eval_result.faithfulness:.2f} "
                f"({eval_result.faithfulness * 100:.0f}% claims supported)"
            )
        else:
            lines.append(
                f"Faithfulness: {eval_result.faithfulness:.1f}/5"
            )

    # ── Token usage ──────────────────────────────────────────────
    if eval_result.total_tokens is not None:
        lines.append(
            f"Tokens: {eval_result.prompt_tokens}↑ + "
            f"{eval_result.completion_tokens}↓ = "
            f"{eval_result.total_tokens} total"
        )

    if eval_result.justification:
        lines.append(f"Assessment: {eval_result.justification}")

    # Append claim details for claim_level mode
    if eval_result.claims_analysis:
        lines.append("")
        lines.append("--- Claim Analysis ---")
        for i, claim in enumerate(eval_result.claims_analysis, 1):
            status = claim.get("supported")
            status_label = (
                "✅" if status is True
                else "❌" if status is False
                else "⚠️"  # "partial"
            )
            lines.append(
                f"  {i}. {status_label} {claim.get('claim', '')}"
            )
            reason = claim.get("reason", "")
            if reason:
                lines.append(f"     Reason: {reason}")

    lines.append("")


# ===================================================================
#  Reflect — write preventive rule to CLAUDE.md
# ===================================================================


def _sync_reflect(reflection_svc, arguments: dict) -> list[types.TextContent]:
    """Write a preventive rule to CLAUDE.md and return metadata."""
    reflection_text = arguments.get("reflection_text", "").strip()
    error_category = arguments.get("error_category", "").strip()
    preventive_rule = arguments.get("preventive_rule", "").strip()

    if not reflection_text or not error_category or not preventive_rule:
        return [types.TextContent(
            type="text",
            text="Missing required fields: reflection_text, error_category, preventive_rule.",
        )]

    meta = reflection_svc.add_preventive_rule(
        reflection_text=reflection_text,
        error_category=error_category,
        preventive_rule=preventive_rule,
    )

    return [types.TextContent(
        type="text",
        text=(
            f"✅ Prevention rule #{meta['rule_number']} recorded "
            f"(total: {meta['total_rules']} rules).\n"
            f"Category: {meta['error_category']}\n"
            f"The rule has been written to {reflection_svc.path}.\n"
            f"I will now remember this lesson in future troubleshooting sessions."
        ),
    )]