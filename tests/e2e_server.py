"""Offline MCP server entry point used only by the end-to-end tests.

The production server loads a FastEmbed model, which may require a model
download. Protocol tests instead use deterministic local vectors while still
exercising MCP, persistence, LanceDB, and retrieval together.
"""

from __future__ import annotations

from bugvault.utils.stdout_guard import _MCPStdoutProxy  # noqa: F401

import asyncio
import concurrent.futures
import hashlib
import math
import re

import mcp.server.stdio
from mcp.server import Server
from mcp.server.models import InitializationOptions

from bugvault.config import settings
from bugvault.database.lancedb_client import LanceDBClient
from bugvault.mcp_tools.tools import register_tools


class DeterministicEmbeddingService:
    """Small local embedding substitute with stable token-overlap vectors."""

    def generate_embedding(self, text: str) -> list[float]:
        return self.generate_embeddings([text])[0]

    def generate_embeddings(self, texts: list[str]) -> list[list[float]]:
        return [self._embed(text) for text in texts]

    @staticmethod
    def _embed(text: str) -> list[float]:
        vector = [0.0] * settings.embedding_dim
        # ``\w`` is the regex character class for word characters.  It must
        # not be escaped twice: ``r"[\\w]+"`` searches for a literal
        # backslash (or ``w``), producing empty/all-zero vectors for normal
        # text and making retrieval silently miss saved records.
        for token in re.findall(r"[\w]+", text.lower()):
            digest = hashlib.sha256(token.encode("utf-8")).digest()
            index = int.from_bytes(digest[:4], "big") % settings.embedding_dim
            vector[index] += 1.0
        magnitude = math.sqrt(sum(value * value for value in vector))
        return [value / magnitude for value in vector] if magnitude else vector


async def main() -> None:
    db = LanceDBClient()
    db.initialize()
    executor = concurrent.futures.ThreadPoolExecutor(
        max_workers=settings.thread_pool_workers,
        thread_name_prefix="bugvault-e2e",
    )
    server = Server(settings.server_name)
    register_tools(
        server,
        db,
        embedding_svc=DeterministicEmbeddingService(),
        executor=executor,
    )

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
