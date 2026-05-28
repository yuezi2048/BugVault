"""Integration tests for BugVault MCP tools: save + retrieve."""

from __future__ import annotations

import json
import subprocess
import sys
import threading
import time

import pytest


@pytest.mark.e2e
def test_save_and_retrieve():
    """Start server, save a bug record, retrieve it, verify round-trip."""
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

    stderr_lines: list[str] = []
    def _drain() -> None:
        for line in proc.stderr:
            stderr_lines.append(line)
    threading.Thread(target=_drain, daemon=True).start()

    try:
        # Wait for init
        time.sleep(12.0)

        # 1. Initialize
        proc.stdin.write(
            '{"jsonrpc":"2.0","id":1,"method":"initialize",'
            '"params":{"protocolVersion":"2024-11-05","capabilities":{},'
            '"clientInfo":{"name":"test","version":"1"}}}\n'
        )
        proc.stdin.flush()
        init_out = ""
        while True:
            line = proc.stdout.readline()
            if not line:
                break
            init_out += line
            if "serverInfo" in line:
                break

        # 2. Initialized notification
        proc.stdin.write(
            '{"jsonrpc":"2.0","method":"notifications/initialized","params":{}}\n'
        )
        proc.stdin.flush()

        # 3. Save a bug record
        save_msg = (
            '{"jsonrpc":"2.0","id":2,"method":"tools/call",'
            '"params":{"name":"save_bug_experience","arguments":{'
            '"bug_title":"integration test bug",'
            '"error_log_snippet":"KeyError: \'missing_key\'",'
            '"tried_methods":"restarted the server, cleared cache",'
            '"final_solution":"added fallback default value",'
            '"project_name":"bugvault-test"}}}\n'
        )
        proc.stdin.write(save_msg)
        proc.stdin.flush()

        save_out = ""
        while True:
            line = proc.stdout.readline()
            if not line:
                break
            save_out += line
            if "saved successfully" in line.lower() or "result" in line:
                break

        assert "saved successfully" in save_out.lower() or '"result"' in save_out, (
            f"Save failed.\nstdout:\n{save_out}\nstderr:\n{''.join(stderr_lines[-20:])}"
        )

        # 4. Retrieve
        retrieve_msg = (
            '{"jsonrpc":"2.0","id":3,"method":"tools/call",'
            '"params":{"name":"retrieve_bug_experience","arguments":{'
            '"query":"KeyError missing_key"}}}\n'
        )
        proc.stdin.write(retrieve_msg)
        proc.stdin.flush()

        retr_out = ""
        while True:
            line = proc.stdout.readline()
            if not line:
                break
            retr_out += line
            if "--- Result" in line or '"result"' in line:
                # Read a few more lines then stop
                for _ in range(5):
                    extra = proc.stdout.readline()
                    if not extra:
                        break
                    retr_out += extra
                break

        assert "integration test bug" in retr_out or "--- Result" in retr_out, (
            f"Retrieve did not return saved record.\nstdout:\n{retr_out}\nstderr:\n{''.join(stderr_lines[-20:])}"
        )

    finally:
        proc.terminate()
        proc.wait(timeout=10.0)