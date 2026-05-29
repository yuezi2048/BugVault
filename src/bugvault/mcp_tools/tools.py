"""MCP tool definitions for BugVault.

Registration
------------
    server = Server(settings.server_name)
    client = LanceDBClient()
    executor = ThreadPoolExecutor(...)
    register_tools(server, client, executor)

This module owns the schema / metadata for each tool but delegates
all data-access logic to the ``LanceDBClient`` instance.
"""

from __future__ import annotations

import asyncio
import concurrent.futures

from mcp.server import Server
import mcp.types as types

from bugvault.models.bug_record import BugRecord
from bugvault.services.ingestion_svc import validate_and_prepare
from bugvault.services.retrieval_svc import rerank
from bugvault.utils.logger import logger
from bugvault.database.lancedb_client import LanceDBClient


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


def register_tools(
    server: Server,
    db: LanceDBClient,
    executor: concurrent.futures.ThreadPoolExecutor,
) -> None:
    """Register list-tools and call-tool handlers on *server*.

    All synchronous database operations are offloaded to *executor*
    to keep the asyncio event loop responsive.
    """

    @server.list_tools()
    async def handle_list_tools() -> list[types.Tool]:
        return [
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

    @server.call_tool()
    async def handle_call_tool(
        name: str, arguments: dict,
    ) -> list[types.TextContent | types.ImageContent | types.EmbeddedResource]:
        loop = asyncio.get_running_loop()

        try:
            if name == "retrieve_bug_experience":
                return await loop.run_in_executor(
                    executor, _sync_retrieve, db, arguments.get("query", ""),
                )
            elif name == "save_bug_experience":
                return await loop.run_in_executor(
                    executor, _sync_save, db, arguments,
                )
            else:
                return [types.TextContent(type="text", text=f"Unknown tool: {name}")]
        except Exception as exc:
            logger.exception("Tool call failed: %s", name)
            return [types.TextContent(
                type="text",
                text=f"Error executing {name}: {exc}",
            )]


# ===================================================================
#  Synchronous implementations (run in thread-pool)
# ===================================================================

def _sync_retrieve(db: LanceDBClient, query: str) -> list[types.TextContent]:
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

    results = db.search(query)
    if not results:
        return [types.TextContent(
            type="text",
            text="No matching bug experiences found in the knowledge base.",
        )]

    # Apply hybrid reranking: semantic × recency
    from bugvault.config import settings
    results = rerank(results, None)

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

    return [types.TextContent(type="text", text="\n".join(lines))]


def _sync_save(db: LanceDBClient, arguments: dict) -> list[types.TextContent]:
    if not db.is_ready:
        return [types.TextContent(
            type="text",
            text="BugVault is still initialising. Please try again in a moment.",
        )]

    try:
        record = BugRecord(**arguments)
    except Exception as exc:
        return [types.TextContent(
            type="text",
            text=f"Invalid record: {exc}",
        )]

    missing = validate_and_prepare(record)
    if missing:
        return [types.TextContent(
            type="text",
            text=(
                f"Record saved as draft. Missing fields: "
                f"{', '.join(missing)}. "
                f"You can update the record later."
            ),
        )]

    db.insert(record)

    return [types.TextContent(
        type="text",
        text=f"Bug record '{record.bug_title}' saved successfully. "
             f"I can now retrieve it in future troubleshooting sessions.",
    )]