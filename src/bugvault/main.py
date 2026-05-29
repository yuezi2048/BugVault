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

from mcp.server import Server
from mcp.server.models import InitializationOptions
import mcp.server.stdio
from bugvault.config import settings
from bugvault.database.lancedb_client import LanceDBClient
from bugvault.mcp_tools.tools import register_tools
from bugvault.utils.logger import logger


async def main() -> None:
    logger.info("BugVault server starting (version %s)", settings.server_version)

    # ── Thread-pool for offloading synchronous I/O ─────────────────
    executor = concurrent.futures.ThreadPoolExecutor(
        max_workers=settings.thread_pool_workers,
        thread_name_prefix="bugvault-io",
    )

    # ── Database layer (LanceDB connection — no embedder) ──────────
    db = LanceDBClient()
    db.initialize()

    # ── Embedding service (optional, required for async hook) ──────
    embedding_svc = None
    if settings.enable_async_embedding:
        from bugvault.services.embedding_svc import EmbeddingService  # slow import

        embedding_svc = EmbeddingService()

    # ── Reflection service (optional) ──────────────────────────────
    reflection_svc = None
    if settings.enable_reflection_tool:
        from bugvault.services.reflection_svc import ReflectionService

        reflection_svc = ReflectionService()

    # ── RAG evaluator (optional, configured via env) ───────────────
    from bugvault.services.rag_evaluator_svc import RAGEvaluator

    rag_evaluator = RAGEvaluator()

    # ── MCP server + tool registration ─────────────────────────────
    server = Server(settings.server_name)
    register_tools(server, db, embedding_svc, reflection_svc, rag_evaluator, executor)

    # ── Enter MCP stdio event loop ─────────────────────────────────
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