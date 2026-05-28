"""Quick E2E smoke test — launches the server and checks init succeeds.

The MCP stdio transport uses newline-delimited JSON (one JSON object per
line), NOT the Content-Length framing format from the spec.
"""

from __future__ import annotations

import subprocess
import sys
import threading
import time


def _read_until(stream, marker: str, timeout: float = 30.0) -> list[str]:
    """Read lines until *marker* is seen (or timeout), return all lines."""
    lines: list[str] = []
    start = time.time()
    while time.time() - start < timeout:
        line = stream.readline()
        if not line:
            break
        lines.append(line.rstrip("\n"))
        if marker in line:
            break
    return lines


def test_server_starts_and_initializes():
    """Verify the server process starts, loads models, and responds to init."""
    proc = subprocess.Popen(
        [sys.executable, "-m", "bugvault.main"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        cwd="/home/ljy/Documents/myprogram/my-demo/BugVault",
        text=True,
    )

    assert proc.stdin is not None
    assert proc.stdout is not None
    assert proc.stderr is not None

    # Drain stderr on a daemon thread
    stderr_output: list[str] = []
    def _drain() -> None:
        for line in proc.stderr:
            stderr_output.append(line)
    threading.Thread(target=_drain, daemon=True).start()

    try:
        # Wait for the server to finish initializing before sending.
        # _init_services() blocks for ~5-15s loading the embedding model.
        time.sleep(12.0)

        # MCP stdio transport uses newline-delimited JSON, one msg per line.
        init_msg = (
            '{"jsonrpc": "2.0", "id": 1, "method": "initialize", '
            '"params": {"protocolVersion": "2024-11-05", "capabilities": {}, '
            '"clientInfo": {"name": "bugvault-test", "version": "0.1.0"}}}\n'
        )
        proc.stdin.write(init_msg)
        proc.stdin.flush()

        # Read response -- 5s is enough since init msg is processed immediately
        out = _read_until(proc.stdout, "bugvault", timeout=10.0)
        full = "\n".join(out)
        print(f"[debug] stdout lines: {len(out)}", file=sys.stderr)
        assert any("bugvault" in line for line in out), (
            f"Server name not found.\nstdout:\n{full}\nstderr:\n{''.join(stderr_output[-30:])}"
        )
        assert any("result" in line for line in out), (
            f"No result in response.\nstdout:\n{full}\nstderr:\n{''.join(stderr_output[-30:])}"
        )

    finally:
        proc.terminate()
        proc.wait(timeout=10.0)


if __name__ == "__main__":
    test_server_starts_and_initializes()
    print("E2E smoke test PASSED")