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
from bugvault.services.retrieval_svc import rerank
from bugvault.utils.logger import logger

# Lazy imports (to avoid circular deps at module level):
#   EmbeddingService  → services.embedding_svc  (conditionally imported)
#   ReflectionService → services.reflection_svc  (conditionally imported)
#   RAGEvaluator      → services.rag_evaluator_svc (conditionally imported)


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
                    "Search the bug knowledge base for past experiences "
                    "matching the given error. Returns semantically similar "
                    "records with their tried_methods and final_solution."
                ),
                inputSchema=_RETRIEVE_SCHEMA,
            ),
            types.Tool(
                name="save_bug_experience",
                description=(
                    "Persist a resolved bug experience into the knowledge "
                    "base. Only the 4 core fields (bug_title, "
                    "error_log_snippet, tried_methods, final_solution) are "
                    "required. Optional fields can be enriched later."
                ),
                inputSchema=_SAVE_SCHEMA,
            ),
        ]

        if reflection_svc is not None:
            tools.append(
                types.Tool(
                    name="reflect_and_prevent_error",
                    description=(
                        "After fixing a bug, analyse the root cause and "
                        "persist a preventive rule so the same mistake is "
                        "never made again. The rule is written to the "
                        "project's CLAUDE.md under ## Bug Prevention Rules."
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
                return await loop.run_in_executor(
                    executor,
                    _sync_retrieve,
                    db,
                    embedding_svc,
                    rag_evaluator,
                    arguments.get("query", ""),
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
    """Background task: generate embedding + LanceDB upsert.

    Never awaited by the caller — runs as a fire-and-forget coroutine.
    Failures are logged but do not propagate to the client.
    """
    try:
        search_text = record.to_search_text()

        def _work():
            embedding = embedding_svc.generate_embedding(search_text)
            db.upsert_record(search_text, embedding, record)

        await loop.run_in_executor(executor, _work)
        logger.info("Async embedding + storage completed: %s", record.bug_title)
    except Exception:
        logger.exception("Async embedding + storage failed: %s", record.bug_title)


# ===================================================================
#  Retrieve — hybrid search + optional RAG evaluation
# ===================================================================


def _sync_retrieve(db, embedding_svc, rag_evaluator, query: str) -> list[types.TextContent]:
    """ANN search → hybrid rerank → optional RAG eval → format text."""
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

    query_emb = embedding_svc.generate_embedding(query)
    results = db.search(query_emb)

    if not results:
        return [types.TextContent(
            type="text",
            text="No matching bug experiences found in the knowledge base.",
        )]

    # ── hybrid rerank (semantic × recency) ─────────────────────────
    results = rerank(results, None)

    # ── format results ─────────────────────────────────────────────
    lines: list[str] = []
    for i, row in enumerate(results, 1):
        lines.append(f"--- Result {i} ---")
        lines.append(f"Title:    {row.get('bug_title', '(untitled)')}")
        lines.append(f"Project:  {row.get('project_name', '(unknown)')}")
        lines.append(f"Time:     {row.get('create_time', '(unknown)')}")
        lines.append(f"Error:\n{row.get('error_log_snippet', '')[:settings.max_record_chars]}")
        lines.append(f"Tried:\n{row.get('tried_methods', '')[:settings.max_record_chars]}")
        lines.append(f"Solution:\n{row.get('final_solution', '')[:settings.max_record_chars]}")
        if row.get("root_cause"):
            lines.append(f"Root cause:\n{row['root_cause'][:settings.max_record_chars]}")
        lines.append("")

    # ── optional RAG evaluation ────────────────────────────────────
    if rag_evaluator and rag_evaluator.enabled:
        try:
            eval_result = rag_evaluator.evaluate_sync(query, results)
            if eval_result.rag_confidence_score is not None:
                lines.append("--- RAG Evaluation ---")
                lines.append(f"Confidence: {eval_result.rag_confidence_score:.1f}/10")
                lines.append(f"Assessment: {eval_result.evaluation}")
                lines.append("")
        except Exception:
            logger.exception("RAG evaluation failed (results returned without scores)")

    return [types.TextContent(type="text", text="\n".join(lines))]


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