"""Entry point for the BugVault MCP server.

Usage
-----
Run directly::

    python -m bugvault.main

Or via the installed CLI::

    bugvault

Expected to be launched as a subprocess by Claude Desktop (or any
MCP-compatible client) via stdio transport.
"""

# ── MUST be the very first lines ──────────────────────────────────
# 1) __future__ annotations must precede any other statement.
# 2) Protect stdout before any third-party library has a chance to
#    register output handlers (tqdm, rich, etc.).
from __future__ import annotations

from bugvault.utils.stdout_guard import _MCPStdoutProxy  # noqa: F401

import asyncio
import concurrent.futures
from pathlib import Path

from mcp.server import Server
from mcp.server.models import InitializationOptions
import mcp.server.stdio
import mcp.types as types

from bugvault.config import settings
from bugvault.models.bug_record import BugRecord
from bugvault.services.ingestion_svc import record_to_markdown, validate_and_prepare
from bugvault.services.retrieval_svc import rerank
from bugvault.utils.logger import logger

# ── Thread-pool for offloading synchronous I/O ─────────────────────
# LanceDB and fastembed are synchronous libraries. We run all their
# operations in this dedicated thread-pool to avoid blocking the MCP
# server's asyncio event loop.
_executor = concurrent.futures.ThreadPoolExecutor(
    max_workers=settings.thread_pool_workers,
    thread_name_prefix="bugvault-io",
)

# ── Global references (populated during initialisation) ────────────
# LanceDB table handle; set after db.open() in _init_services().
_table = None

# Embedding model singleton; set after model.load() in _init_services().
_embedder = None


# ===================================================================
#  Service initialisation
# ===================================================================
def _init_services() -> None:
    """Warm up embeddings and open the LanceDB connection.

    Called once during server startup so that the first tool
    invocation does not pay a cold-start penalty.
    """
    global _embedder, _table

    # ── Warm up embedding model ────────────────────────────────────
    logger.info("Loading embedding model: %s", settings.embedding_model)
    from fastembed import TextEmbedding

    _embedder = TextEmbedding(
        model_name=settings.embedding_model,
        max_length=512,
    )
    # Warm-up: run one dummy embedding through ONNX runtime to
    # pre-compile the execution graph. Without this, the first
    # real inference has a ~500ms cold-start overhead.
    list(_embedder.embed(["warmup"]))
    logger.info("Embedding model loaded and warmed up")

    # ── Open LanceDB ───────────────────────────────────────────────
    import lancedb

    db = lancedb.connect(settings.db_uri)
    logger.info("LanceDB connected at: %s", settings.db_uri)

    table_names = db.list_tables()
    TABLE_NAME = "bug_records"
    existing = db.list_tables()
    existing_names: list[str] = existing.tables

    if TABLE_NAME in existing_names:
        _table = db.open_table(TABLE_NAME)
        logger.info("Opened existing table: %s", TABLE_NAME)
    else:
        import pyarrow as pa

        schema = pa.schema([
            pa.field("vector", pa.list_(pa.float32(), settings.embedding_dim)),
            pa.field("bug_title", pa.utf8()),
            pa.field("error_log_snippet", pa.utf8()),
            pa.field("tried_methods", pa.utf8()),
            pa.field("final_solution", pa.utf8()),
            pa.field("project_name", pa.utf8()),
            pa.field("tech_stack", pa.utf8()),
            pa.field("root_cause", pa.utf8()),
            pa.field("create_time", pa.utf8()),
            pa.field("search_text", pa.utf8()),
        ])
        _table = db.create_table(TABLE_NAME, schema=schema, mode="create")
        logger.info("Created new table: %s", TABLE_NAME)

    logger.info("BugVault initialisation complete")


# ===================================================================
#  MCP Tool handlers
# ===================================================================
server = Server(settings.server_name)


@server.list_tools()
async def handle_list_tools() -> list[types.Tool]:
    return [
        types.Tool(
            name="retrieve_bug_experience",
            description=(
                "Search the bug knowledge base for past experiences matching "
                "the given error. Returns semantically similar records with "
                "their tried_methods and final_solution."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Error message, stack trace, or natural-language description of the bug",
                    },
                },
                "required": ["query"],
            },
        ),
        types.Tool(
            name="save_bug_experience",
            description=(
                "Persist a resolved bug experience into the knowledge base. "
                "Only the 4 core fields (bug_title, error_log_snippet, "
                "tried_methods, final_solution) are required. Optional fields "
                "can be enriched later."
            ),
            inputSchema={
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
            },
        ),
    ]


@server.call_tool()
async def handle_call_tool(
    name: str, arguments: dict
) -> list[types.TextContent | types.ImageContent | types.EmbeddedResource]:
    loop = asyncio.get_running_loop()

    try:
        if name == "retrieve_bug_experience":
            return await loop.run_in_executor(
                _executor, _sync_retrieve, arguments.get("query", ""),
            )
        elif name == "save_bug_experience":
            return await loop.run_in_executor(
                _executor, _sync_save, arguments,
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
#  Synchronous implementations (called via thread-pool)
# ===================================================================
def _sync_retrieve(query: str) -> list[types.TextContent]:
    if not query.strip():
        return [types.TextContent(type="text", text="Query is empty. Please provide an error description.")]

    if _embedder is None or _table is None:
        return [types.TextContent(
            type="text",
            text="BugVault is still initialising. Please try again in a moment.",
        )]

    # Compute query embedding
    emb = list(_embedder.embed([query]))[0].tolist()

    # ANN search + metadata retrieval
    results = (
        _table.search(emb)
        .limit(settings.top_k)
        .to_list()
    )

    if not results:
        return [types.TextContent(
            type="text",
            text="No matching bug experiences found in the knowledge base.",
        )]

    # Hybrid reranking: semantic × recency
    results = rerank(results, emb)

    # Format results as structured text blocks
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


def _sync_save(arguments: dict) -> list[types.TextContent]:
    """Save a bug record: validate → embed → write to LanceDB."""
    if _embedder is None or _table is None:
        return [types.TextContent(
            type="text",
            text="BugVault is still initialising. Please try again in a moment.",
        )]

    # Validate via Pydantic model
    try:
        record = BugRecord(**arguments)
    except Exception as exc:
        return [types.TextContent(
            type="text",
            text=f"Invalid record: {exc}",
        )]

    # Check for missing required fields
    missing = validate_and_prepare(record)
    if missing:
        return [types.TextContent(
            type="text",
            text=f"Record saved as draft. Missing fields: {', '.join(missing)}. "
                 f"You can update the record later.",
        )]

    # Build search text + embed
    search_text = record.to_search_text()
    emb = list(_embedder.embed([search_text]))[0].tolist()

    # Write to LanceDB
    _table.add([{
        "vector": emb,
        "bug_title": record.bug_title,
        "error_log_snippet": record.error_log_snippet,
        "tried_methods": record.tried_methods,
        "final_solution": record.final_solution,
        "project_name": record.project_name or "",
        "tech_stack": record.tech_stack or "",
        "root_cause": record.root_cause or "",
        "create_time": record.create_time,
        "search_text": search_text,
    }])

    logger.info("Saved bug record: %s", record.bug_title)

    # Archive to markdown (non-critical, fire-and-forget)
    try:
        md_path = settings.data_root / "archive" / f"{record.create_time[:10]}_{record.bug_title[:40]}.md"
        md_path.parent.mkdir(parents=True, exist_ok=True)
        md_path.write_text(record_to_markdown(record), encoding="utf-8")
    except Exception:
        logger.exception("Failed to write markdown archive")

    return [types.TextContent(
        type="text",
        text=f"Bug record '{record.bug_title}' saved successfully. "
             f"I can now retrieve it in future troubleshooting sessions.",
    )]


# ===================================================================
#  Main
# ===================================================================
async def main() -> None:
    logger.info("BugVault server starting (version %s)", settings.server_version)

    # Cold-start initialisation (blocking, but happens before MCP handshake)
    _init_services()

    # Enter MCP stdio event loop
    async with mcp.server.stdio.stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            InitializationOptions(
                server_name=settings.server_name,
                server_version=settings.server_version,
                capabilities=server.get_capabilities(
                    notification_options=mcp.server.NotificationOptions(),
                    experimental_capabilities={},
                ),
            ),
        )


if __name__ == "__main__":
    asyncio.run(main())
