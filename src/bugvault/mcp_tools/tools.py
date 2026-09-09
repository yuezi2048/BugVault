"""MCP tool definitions for BugVault.

Registration
------------
    server = Server(settings.server_name)
    db = LanceDBClient()
    executor = ThreadPoolExecutor(...)
    register_tools(
        server, db, embedding_svc, reflection_svc, rag_evaluator, graph_db, executor,
    )

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
from bugvault.services.persistence_svc import PreparedRecord, RecordPersistence
from bugvault.services.retrieval_svc import RetrievalModule, RetrievalRequest
from bugvault.utils.logger import logger, set_trace_id

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

_CONVENTION_SAVE_SCHEMA = {
    "type": "object",
    "properties": {
        "convention_name": {
            "type": "string",
            "description": "Short descriptive rule name — e.g. 'DTO 转换规则'",
        },
        "trigger_context": {
            "type": "string",
            "description": "When / where this convention applies — e.g. '在 Repository 层返回数据时'",
        },
        "incorrect_behavior": {
            "type": "string",
            "description": "What the AI should NOT do — e.g. '直接返回 Entity 对象'",
        },
        "correct_behavior": {
            "type": "string",
            "description": "What the AI SHOULD do — e.g. '转换为 DTO 后返回'",
        },
        "scope": {
            "type": "string",
            "description": "Scope of applicability — e.g. 'src/repository/', 'tests/' (optional)",
        },
        "tags": {
            "type": "string",
            "description": "Categorisation tags — e.g. 'architecture, Java, DDD' (optional)",
        },
    },
    "required": ["convention_name", "trigger_context", "incorrect_behavior", "correct_behavior"],
}

_CONVENTION_RETRIEVE_SCHEMA = {
    "type": "object",
    "properties": {
        "query": {
            "type": "string",
            "description": (
                "Natural-language description of the convention scenario — "
                "e.g. 'how should repository layer return data', "
                "'what naming convention for test files'"
            ),
        },
        "target_scope": {
            "type": "string",
            "description": (
                "Optional: Narrow search to a specific scope — "
                "e.g. 'src/repository/', 'tests/', 'Python'. "
                "Case-insensitive matching against the convention's scope field."
            ),
        },
        "target_tags": {
            "type": "string",
            "description": (
                "Optional: Filter by tags — "
                "e.g. 'architecture', 'Java', 'testing'. "
                "Case-insensitive matching against the convention's tags field."
            ),
        },
    },
    "required": ["query"],
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
    graph_db=None,  # GraphDB | None
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
    graph_db : GraphDB | None
        Optional graph overlay projected after successful LanceDB writes.
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
                    "开工前查历史坑。与 retrieve_convention 配合使用，见下方决策树。\n\n"
                    "决策树：\n"
                    "  准备改代码？\n"
                    "  ├─ 涉及业务逻辑 / 数据库 / API / 性能 / 安全\n"
                    "  │  → 先调 retrieve_bug_experience（查历史坑）\n"
                    "  │  → 再调 retrieve_convention（查项目规范）\n"
                    "  ├─ 涉及架构 / 命名 / UI 规范\n"
                    "  │  → 调 retrieve_convention 即可\n"
                    "  └─ 纯样式 / 纯文案 / 构建配置\n"
                    "     → 跳过，直接开工"
                ),
                inputSchema=_RETRIEVE_SCHEMA,
            ),
            types.Tool(
                name="save_bug_experience",
                description=(
                    "保存 Bug 修复记录。适用于：修 Bug、修异常、改错误逻辑。\n\n"
                    "与 save_convention 的区别：\n"
                    "- 修 Bug（运行结果不对）→ 用 save_bug_experience\n"
                    "- 定规范（代码该怎么写）→ 用 save_convention\n"
                    "- 根因是系统性误解 → 再追加 reflect_and_prevent_error\n\n"
                    "必须与 reasonix-doc/ 文档双写（各存一份，缺一违规）。"
                ),
                inputSchema=_SAVE_SCHEMA,
            ),
            types.Tool(
                name="save_convention",
                description=(
                    "保存项目规范（架构规则/命名约定/部署配置/测试约定等）。\n\n"
                    "适用于：发现了可复用的模式或规则，希望 Agent 以后自动遵守。\n\n"
                    "判断标准：\n"
                    "  \"这次踩的坑，下次换个地方也可能踩\" → save_convention\n"
                    "  \"这个 Bug 是这个函数独有的，换个场景不会复现\" → 只 save_bug_experience 即可"
                ),
                inputSchema=_CONVENTION_SAVE_SCHEMA,
            ),
            types.Tool(
                name="retrieve_convention",
                description=(
                    "查项目规范（命名/架构/数据库/部署等约定）。\n"
                    "配合 bugvault_retrieve_bug_experience 使用 —— 先查坑再查规范。\n\n"
                    "纯样式/文案修改可以跳过此工具。"
                ),
                inputSchema=_CONVENTION_RETRIEVE_SCHEMA,
            ),
        ]

        if reflection_svc is not None:
            tools.append(
                types.Tool(
                    name="reflect_and_prevent_error",
                    description=(
                        "根因反思 + 生成预防规则。仅在以下情况调用：\n"
                        "1. Agent 自身的系统性误解（不是代码 Bug，是 Agent 想错了）\n"
                        "2. 同一个模式的 Bug 反复出现\n"
                        "3. 架构层面的错误决策\n\n"
                        "一般修 Bug 只需要 save_bug_experience，不必每次都用这个。"
                    ),
                    inputSchema=_REFLECT_SCHEMA,
                ),
            )

        return tools

    @server.call_tool()
    async def handle_call_tool(
        name: str, arguments: dict,
    ) -> list[types.TextContent | types.ImageContent | types.EmbeddedResource]:
        # ── Generate trace_id for this request ────────────────────
        trace_id = set_trace_id()
        loop = asyncio.get_running_loop()

        # ── Structured entry log ──────────────────────────────────
        from bugvault.observability import AiCallLogEntry, append_ai_call_log, _classify_error
        import time

        entry_log = AiCallLogEntry(
            event_type="entry", tool_name=name,
            metadata={"arguments": {k: v for k, v in arguments.items() if k != "eval_llm_api_key"}},
        )
        append_ai_call_log(entry_log)
        logger.info("Tool start: %s [trace=%s]", name, trace_id)

        start = time.monotonic()

        try:
            if name == "retrieve_bug_experience":
                result = await _handle_retrieve(
                    loop, executor, db, embedding_svc, rag_evaluator,
                    arguments,
                )
            elif name == "save_bug_experience":
                result = await _handle_save_record(
                    loop,
                    executor,
                    db,
                    embedding_svc,
                    graph_db,
                    arguments,
                    "bug",
                )
            elif name == "save_convention":
                result = await _handle_save_record(
                    loop,
                    executor,
                    db,
                    embedding_svc,
                    graph_db,
                    arguments,
                    "convention",
                )
            elif name == "retrieve_convention":
                result = await _handle_retrieve_convention(
                    loop, executor, db, embedding_svc, arguments,
                )
            elif name == "reflect_and_prevent_error":
                if reflection_svc is None:
                    result = [types.TextContent(
                        type="text",
                        text="Reflection tool is not enabled. "
                             "Set BUGVAULT_ENABLE_REFLECTION_TOOL=true in .env",
                    )]
                else:
                    result = await loop.run_in_executor(
                        executor,
                        _sync_reflect,
                        reflection_svc,
                        arguments,
                    )
            else:
                result = [types.TextContent(
                    type="text",
                    text=f"Unknown tool: {name}",
                )]

            duration = (time.monotonic() - start) * 1000

            # ── Structured exit log (success) ─────────────────────
            exit_log = AiCallLogEntry(
                event_type="exit", tool_name=name,
                status="ok", error_code="ok",
                duration_ms=round(duration, 2),
            )
            append_ai_call_log(exit_log)
            logger.info(
                "Tool done: %s [trace=%s] (%.0f ms)",
                name, trace_id, duration,
            )

            return result

        except Exception as exc:
            duration = (time.monotonic() - start) * 1000

            # ── Structured exit log (error) ───────────────────────
            error_code = _classify_error(exc)
            exit_log = AiCallLogEntry(
                event_type="exit", tool_name=name,
                status="error", error_code=error_code,
                error_message=str(exc)[:500],
                duration_ms=round(duration, 2),
            )
            append_ai_call_log(exit_log)
            logger.exception(
                "Tool error: %s [trace=%s] (%.0f ms) code=%s",
                name, trace_id, duration, error_code,
            )

            return [types.TextContent(
                type="text",
                text=f"Error executing {name}: {exc}",
            )]


# ===================================================================
#  Save — zero-blocking async flow
# ===================================================================


async def _handle_save_record(
    loop,
    executor,
    db,
    embedding_svc,
    graph_db,
    arguments: dict,
    record_type: str,
) -> list[types.TextContent]:
    """Prepare a record now and schedule its local-memory persistence."""
    persistence = RecordPersistence(
        db=db,
        embedding_svc=embedding_svc,
        graph_db=graph_db,
    )
    prepare = (
        persistence.prepare_convention
        if record_type == "convention"
        else persistence.prepare_bug
    )
    prepared = await loop.run_in_executor(executor, prepare, arguments)

    if (
        prepared.record is not None
        and settings.enable_async_embedding
        and embedding_svc is not None
    ):
        asyncio.create_task(
            _persist_record_in_background(
                loop,
                executor,
                persistence,
                prepared.record,
            ),
        )

    return _present_save_outcome(prepared)


async def _persist_record_in_background(loop, executor, persistence, record) -> None:
    """Keep failed background persistence non-fatal to the MCP caller."""
    try:
        await loop.run_in_executor(executor, persistence.persist, record)
    except Exception:
        logger.exception(
            "Async record persistence failed: %s",
            getattr(record, "record_id", "?"),
        )


def _present_save_outcome(prepared: PreparedRecord) -> list[types.TextContent]:
    """Translate a persistence outcome into the stable MCP text contract."""
    if prepared.record is None:
        prefix = (
            "Invalid convention"
            if prepared.record_type == "convention"
            else "Invalid record"
        )
        return [types.TextContent(
            type="text",
            text=f"{prefix}: {prepared.validation_error}",
        )]

    if prepared.is_draft:
        prefix = "Convention" if prepared.record_type == "convention" else "Record"
        return [types.TextContent(
            type="text",
            text=(
                f"{prefix} saved as draft. Missing fields: "
                f"{', '.join(prepared.missing_fields)}. "
                f"You can update the record later."
            ),
        )]

    if prepared.record_type == "convention":
        return [types.TextContent(
            type="text",
            text=(
                f"Convention '{prepared.record.convention_name}' saved successfully. "
                f"I will remember this rule for future sessions."
            ),
        )]

    return [types.TextContent(
        type="text",
        text=(
            f"Bug record '{prepared.record.bug_title}' saved successfully. "
            f"I can now retrieve it in future troubleshooting sessions."
        ),
    )]


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

    result = await _retrieve_records(
        loop,
        executor,
        db,
        embedding_svc,
        RetrievalRequest(
            query=query,
            target_tech_stack=target_tech_stack,
            target_project_name=target_project_name,
        ),
    )
    if result.error_message:
        return [types.TextContent(type="text", text=result.error_message)]
    if not result.records and not result.had_candidates:
        return [types.TextContent(
            type="text",
            text="No matching bug experiences found in the knowledge base.",
        )]

    lines = _format_retrieval_result(result, "bug")

    # ── Async RAG evaluation (I/O-bound, outside executor) ──────
    if (
        rag_evaluator
        and rag_evaluator.enabled
        and eval_depth != "none"
        and result.records
    ):
        try:
            from bugvault.services.rag_evaluator_svc import format_context

            context = format_context(result.records, rag_evaluator.top_k)
            eval_result = await rag_evaluator.evaluate(
                query, context, eval_depth,
            )
            _append_eval_to_lines(lines, eval_result)
        except Exception:
            logger.exception(
                "RAG evaluation failed (results returned without scores)"
            )

    return [types.TextContent(type="text", text="\n".join(lines))]


# ===================================================================
#  Retrieve Convention — filtered by record_type='convention'
# ===================================================================


async def _handle_retrieve_convention(
    loop,
    executor,
    db,
    embedding_svc,
    arguments: dict,
) -> list[types.TextContent]:
    """Convention search with automatic record_type='convention' filtering.

    Uses the same hybrid retrieval pipeline but filters to convention records
    only and formats output with convention semantics.
    """
    query = arguments.get("query", "")
    target_scope = arguments.get("target_scope", "")
    target_tags = arguments.get("target_tags", "")

    result = await _retrieve_records(
        loop,
        executor,
        db,
        embedding_svc,
        RetrievalRequest(
            query=query,
            target_tech_stack=target_tags,
            target_project_name=target_scope,
            record_type="convention",
        ),
    )
    if result.error_message:
        return [types.TextContent(type="text", text=result.error_message)]
    if not result.records and not result.had_candidates:
        return [types.TextContent(
            type="text",
            text="No matching bug experiences found in the knowledge base.",
        )]

    lines = _format_retrieval_result(result, "convention")
    return [types.TextContent(type="text", text="\n".join(lines))]


async def _retrieve_records(
    loop,
    executor,
    db,
    embedding_svc,
    request: RetrievalRequest,
):
    """Run the domain retrieval module away from the MCP event loop."""
    retrieval = RetrievalModule(db, embedding_svc)
    return await loop.run_in_executor(executor, retrieval.retrieve, request)


def _format_retrieval_result(result, record_type: str) -> list[str]:
    """Present domain records using the existing MCP text contract."""
    lines = ["--- Retrieval Info ---"]
    lines.append(f"Strategy: {result.strategy}")
    lines.append(
        f"Sources:  {result.vector_count} vector + {result.fts_count} FTS"
        if result.fts_count else f"Sources:  {result.vector_count} vector results"
    )
    lines.append("")

    is_convention = record_type == "convention"
    error_label = "Context:" if is_convention else "Error:"
    tried_label = "Incorrect:" if is_convention else "Tried:"
    solution_label = "Correct:" if is_convention else "Solution:"
    for index, record in enumerate(result.records, 1):
        lines.append(f"--- Result {index} ---")
        if is_convention:
            title = record.convention_name
            scope = record.scope or "(any)"
            context = record.trigger_context
            incorrect = record.incorrect_behavior
            correct = record.correct_behavior
        else:
            title = record.bug_title
            scope = record.project_name or "(any)"
            context = record.error_log_snippet
            incorrect = record.tried_methods
            correct = record.final_solution
        lines.append(f"Title:    {title}")
        lines.append(f"Scope:    {scope}")
        lines.append(f"Time:     {record.create_time or '(unknown)'}")
        lines.append(
            f"{error_label}\n{context[:settings.max_record_chars]}"
        )
        lines.append(
            f"{tried_label}\n{incorrect[:settings.max_record_chars]}"
        )
        lines.append(
            f"{solution_label}\n{correct[:settings.max_record_chars]}"
        )
        if not is_convention and record.root_cause:
            lines.append(f"Note:\n{record.root_cause[:settings.max_record_chars]}")
        lines.append("")
    return lines


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
