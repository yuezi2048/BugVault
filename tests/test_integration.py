"""Integration tests for BugVault MCP tools — save + retrieve.

Uses the official ``mcp.client.stdio.stdio_client`` transport and
``ClientSession`` for proper JSON-RPC 2.0 framing, eliminating the
earlier subprocess/Popen deadlock-prone approach.
"""

from __future__ import annotations

import sys

import pytest
from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client


@pytest.mark.anyio
@pytest.mark.e2e
async def test_save_and_retrieve() -> None:
    """Start server via stdio_client, save a bug record, retrieve it, verify round-trip."""
    server_params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "bugvault.main"],
        cwd="/home/ljy/Documents/myprogram/my-demo/BugVault",
    )

    async with stdio_client(server_params) as (read_stream, write_stream):
        async with ClientSession(read_stream, write_stream) as session:
            # ── 1. Initialize handshake ─────────────────────────────
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
            retrieve_result = await session.call_tool(
                "retrieve_bug_experience",
                arguments={"query": "KeyError missing_key"},
            )
            assert not retrieve_result.isError, (
                f"Retrieve failed: {retrieve_result.content}"
            )
            retrieve_text = " ".join(
                c.text for c in retrieve_result.content if hasattr(c, "text")
            )
            assert "integration test bug" in retrieve_text, (
                f"Retrieve did not return saved record:\n{retrieve_text}"
            )


@pytest.mark.anyio
@pytest.mark.e2e
async def test_save_and_retrieve_convention() -> None:
    """Save a convention, retrieve it, verify round-trip with correct semantics."""
    server_params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "bugvault.main"],
        cwd="/home/ljy/Documents/myprogram/my-demo/BugVault",
    )

    async with stdio_client(server_params) as (read_stream, write_stream):
        async with ClientSession(read_stream, write_stream) as session:
            # ── 1. Initialize handshake ─────────────────────────────
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
            retrieve_result = await session.call_tool(
                "retrieve_convention",
                arguments={"query": "repository DTO conversion"},
            )
            assert not retrieve_result.isError, (
                f"Convention retrieve failed: {retrieve_result.content}"
            )
            retrieve_text = " ".join(
                c.text for c in retrieve_result.content if hasattr(c, "text")
            )
            assert "DTO Conversion" in retrieve_text, (
                f"Retrieve did not return saved convention:\n{retrieve_text}"
            )
            # Convention-specific labels should appear
            assert "Context:" in retrieve_text or "Incorrect:" in retrieve_text or "Correct:" in retrieve_text, (
                f"Convention semantics missing from output:\n{retrieve_text}"
            )