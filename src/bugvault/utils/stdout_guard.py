"""MCP stdout guard — safeguards the stdio JSON-RPC transport.

This module performs two safety measures at import time:

1. Sets ``TQDM_DISABLE=1`` so that tqdm progress bars never emit
   escape sequences to stdout.
2. Replaces ``sys.stdout`` with a pass-through proxy that is fully
   compatible with MCP's stdio_server() transport. The proxy
   delegates buffer/readable/fileno to the original stdout so that
   ``anyio.wrap_file(TextIOWrapper(sys.stdout.buffer, ...))`` works
   correctly, while injecting a write-time filter that silently drops
   any non-MCP-protocol output (e.g. stray ``print()`` calls).
"""

import os
import sys
from typing import TextIO


os.environ["TQDM_DISABLE"] = "1"


class _MCPStdoutProxy(TextIO):
    """Pass-through proxy for sys.stdout with write filtering.

    Fully compatible with MCP's stdio_server(): delegates ``.buffer``,
    ``.fileno()``, ``.readable()``, and ``.encoding`` to the original
    stdout so that ``anyio.wrap_file()`` works without modification.
    """

    def __init__(self, original: TextIO) -> None:
        self._original = original

    # ── Delegated properties (required by anyio.wrap_file) ─────────
    @property
    def buffer(self):
        return self._original.buffer

    def fileno(self) -> int:
        return self._original.fileno()

    def readable(self) -> bool:
        return self._original.readable()

    def writable(self) -> bool:
        return True

    def isatty(self) -> bool:
        return False

    @property
    def encoding(self) -> str:
        return self._original.encoding

    # ── Write filter ──────────────────────────────────────────────
    def write(self, text: str) -> int:
        if not text or text == "\n":
            return 0
        stripped = text.strip()
        # Allow MCP protocol frames through unconditionally
        if stripped.startswith("Content-Length:") or stripped.startswith("{"):
            return self._original.write(text)
        # Everything else → silently drop, log to stderr for debugging
        sys.stderr.write(f"[bugvault:stdout_guard] dropped ({len(text)} bytes): {text!r}\n")
        sys.stderr.flush()
        return len(text)

    def flush(self) -> None:
        self._original.flush()


# Install proxy as the global sys.stdout
if not isinstance(sys.stdout, _MCPStdoutProxy):
    sys.stdout = _MCPStdoutProxy(sys.stdout)