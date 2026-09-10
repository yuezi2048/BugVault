"""Integration tests for BugVault MCP tools — save + retrieve.

Uses the official ``mcp.client.stdio.stdio_client`` transport and
``ClientSession`` for proper JSON-RPC 2.0 framing, eliminating the
earlier subprocess/Popen deadlock-prone approach.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import anyio
import pytest
from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client


ROOT = Path(__file__).resolve().parents[1]
E2E_SERVER = ROOT / "tests" / "e2e_server.py"


def _server_params(data_root: Path) -> StdioServerParameters:
    """Start an isolated server that never downloads embedding models."""
    env = {
        **os.environ,
        "BUGVAULT_DATA_ROOT": str(data_root),
        "BUGVAULT_ENABLE_RERANKER": "false",
        "BUGVAULT_ENABLE_RAG_EVAL": "false",
        "BUGVAULT_ENABLE_REFLECTION_TOOL": "false",
        "BUGVAULT_ENABLE_FTS": "false",
    }
    return StdioServerParameters(
        command=sys.executable,
        args=[str(E2E_SERVER)],
        cwd=str(ROOT),
        env=env,
    )


async def _retrieve_until_present(
    session: ClientSession,
    tool_name: str,
    arguments: dict[str, str],
    expected_text: str,
) -> str:
    """Wait for the intentionally eventual vector/FTS index projection."""
    last_text = ""
    with anyio.fail_after(15):
        while True:
            result = await session.call_tool(tool_name, arguments=arguments)
            assert not result.isError, f"Retrieve failed: {result.content}"
            last_text = " ".join(
                content.text for content in result.content if hasattr(content, "text")
            )
            if expected_text in last_text:
                return last_text
            await anyio.sleep(0.1)
    return last_text


@pytest.mark.anyio
@pytest.mark.e2e
async def test_save_and_retrieve(tmp_path: Path) -> None:
    """Start server via stdio_client, save a bug record, retrieve it, verify round-trip."""
    server_params = _server_params(tmp_path)

    async with stdio_client(server_params) as (read_stream, write_stream):
        async with ClientSession(read_stream, write_stream) as session:
            # ── 1. Initialize handshake ─────────────────────────────
            with anyio.fail_after(30):
                init_result = await session.initialize()
            assert init_result.serverInfo.name == "bugvault"

            # ── 2. Save a bug record ────────────────────────────────
            save_result = await session.call_tool(
                "save_bug_experience",
                arguments={
                    "bug_title": "integration test bug",
                    "error_log_snippet": "KeyError: 'missing_key'",
                    "tried_methods": "restarted the server, cleared cache",
                    "final_solution": "added fallback default value",
                    "project_name": "bugvault-test",
                },
            )
            assert not save_result.isError, (
                f"Save failed: {save_result.content}"
            )
            save_text = " ".join(
                c.text for c in save_result.content if hasattr(c, "text")
            )
            assert "saved successfully" in save_text.lower(), (
                f"Unexpected save response: {save_text}"
            )

            # ── 3. Retrieve ─────────────────────────────────────────
            retrieve_text = await _retrieve_until_present(
                session,
                "retrieve_bug_experience",
                {"query": "KeyError missing_key"},
                "integration test bug",
            )
            assert "integration test bug" in retrieve_text, (
                f"Retrieve did not return saved record:\n{retrieve_text}"
            )


@pytest.mark.anyio
@pytest.mark.e2e
async def test_save_and_retrieve_convention(tmp_path: Path) -> None:
    """Save a convention, retrieve it, verify round-trip with correct semantics."""
    server_params = _server_params(tmp_path)

    async with stdio_client(server_params) as (read_stream, write_stream):
        async with ClientSession(read_stream, write_stream) as session:
            # ── 1. Initialize handshake ─────────────────────────────
            with anyio.fail_after(30):
                init_result = await session.initialize()
            assert init_result.serverInfo.name == "bugvault"

            # ── 2. Save a convention ────────────────────────────────
            save_result = await session.call_tool(
                "save_convention",
                arguments={
                    "convention_name": "DTO Conversion",
                    "trigger_context": "when returning from repository layer",
                    "incorrect_behavior": "return Entity object directly",
                    "correct_behavior": "convert Entity to DTO before returning",
                    "scope": "src/repository/",
                    "tags": "architecture, Java",
                },
            )
            assert not save_result.isError, (
                f"Convention save failed: {save_result.content}"
            )
            save_text = " ".join(
                c.text for c in save_result.content if hasattr(c, "text")
            )
            assert "saved successfully" in save_text.lower(), (
                f"Unexpected save response: {save_text}"
            )

            # ── 3. Retrieve convention ──────────────────────────────
            retrieve_text = await _retrieve_until_present(
                session,
                "retrieve_convention",
                {"query": "repository DTO conversion"},
                "DTO Conversion",
            )
            assert "DTO Conversion" in retrieve_text, (
                f"Retrieve did not return saved convention:\n{retrieve_text}"
            )
            # Convention-specific labels should appear
            assert "Context:" in retrieve_text or "Incorrect:" in retrieve_text or "Correct:" in retrieve_text, (
                f"Convention semantics missing from output:\n{retrieve_text}"
            )
