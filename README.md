<div align="center">

# BugVault

**Bug Experience Vault & Intelligent Retrieval System**

*A local-first MCP server that gives LLMs persistent, cross-session bug troubleshooting memory.*

[![Python 3.13+](https://img.shields.io/badge/python-3.13+-blue.svg)](https://www.python.org/downloads/)
[![MCP](https://img.shields.io/badge/MCP-2024--11--05-purple.svg)](https://modelcontextprotocol.io)
[![License](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)

---

[English](README.md) | [中文](README.zh.md) | [日本語](README.ja.md)

</div>

---

## What is BugVault?

BugVault is a **local-first MCP (Model Context Protocol) server** that gives Claude and other MCP-compatible LLM clients persistent, cross-session bug troubleshooting memory.

**The problem:** Every time you troubleshoot a bug with an LLM, it starts from scratch. The same issue resurfaces days later, and the LLM has no memory of the previous fix. Your hard-earned debugging experience evaporates.

**BugVault's solution:** It sits alongside your LLM as a dedicated "bug brain" — automatically saving resolved bugs via `save_bug_experience` and retrieving relevant past solutions via `retrieve_bug_experience`. All data stays **100% local** — no cloud, no API fees, no data leaks.

### Key Features

- **Semantic Retrieval** — Find past bugs by natural-language query, not keyword search
- **Auto-persistence** — Save resolved bugs with zero manual effort (4 required fields)
- **Smart Truncation** — Stack traces are intelligently cropped to preserve tokens without losing signal
- **Time-decay Reranking** — Recent solutions rank higher; obsolete ones fade automatically
- **Pure Local** — All data resides in `~/.bugvault/`. No network, no servers, no uploads
- **MCP-native** — Works with any MCP client: Claude Desktop, Claude Code, Cursor, Cline, Windsurf, etc.

---

## Quick Start

### Prerequisites

- Python 3.13+
- [uv](https://docs.astral.sh/uv/) (package manager)

### Installation

```bash
# Clone the repository
git clone https://github.com/yourusername/bugvault.git
cd bugvault

# Install dependencies (no GPU required)
uv sync

# Run unit tests to verify everything works
uv run pytest tests/test_core.py -v
```

### Exposed MCP Tools

Once configured, Claude can use two additional tools:

| Tool | Description | Required Fields |
|------|-------------|----------------|
| `retrieve_bug_experience` | Search past bug solutions by error description | `query` |
| `save_bug_experience` | Persist a resolved bug into the knowledge base | `bug_title`, `error_log_snippet`, `tried_methods`, `final_solution` |

---

## Architecture

```
┌──────────────────────────────────────────────────────┐
│            MCP Client (Claude Code / Desktop)         │
└───────────────────────┬──────────────────────────────┘
                        │ JSON-RPC via stdio
┌───────────────────────▼──────────────────────────────┐
│               BugVault MCP Server                     │
│                                                       │
│  ┌─────────────────────────────────────────────────┐  │
│  │  mcp_tools/  (Facade Layer)                     │  │
│  │  ┌───────────────────┐ ┌───────────────────┐   │  │
│  │  │  retrieve_bug_    │ │  save_bug_        │   │  │
│  │  │  experience       │ │  experience       │   │  │
│  │  └────────┬──────────┘ └────────┬──────────┘   │  │
│  └───────────┼──────────────────────┼──────────────┘  │
│              │                      │                 │
│  ┌───────────▼──────────────────────▼──────────────┐  │
│  │  services/  (Business Logic)                    │  │
│  │  ┌──────────────────────┐ ┌──────────────────┐  │  │
│  │  │  RetrievalService    │ │ IngestionService │  │  │
│  │  │  · ANN search        │ │ · Validation     │  │  │
│  │  │  · Time-decay re-rank│ │ · Probe questions│  │  │
│  │  │  · Stack truncation  │ │ · MD archive     │  │  │
│  │  └──────────┬───────────┘ └────────┬─────────┘  │  │
│  └─────────────┼──────────────────────┼────────────┘  │
│                │                      │               │
│  ┌─────────────▼──────────────────────▼────────────┐  │
│  │  database/  (Persistence)                       │  │
│  │  ┌──────────────────┐  ┌────────────────────┐   │  │
│  │  │ LanceDBClient    │  │ Markdown Archive   │   │  │
│  │  │ (vector + meta)  │  │ (human-readable)   │   │  │
│  │  └──────────────────┘  └────────────────────┘   │  │
│  └─────────────────────────────────────────────────┘  │
└───────────────────────────────────────────────────────┘
```

### Tech Stack

| Component | Choice | Rationale |
|-----------|--------|-----------|
| **MCP Transport** | Official Python `mcp` SDK via `stdio` | No HTTP server, no ports, pure subprocess |
| **Vector DB** | [LanceDB](https://lancedb.github.io/lancedb/) | Zero-dependency embedded, MVCC, Arrow-native |
| **Embedding** | [fastembed](https://github.com/qdrant/fastembed) (`BAAI/bge-small-zh-v1.5`) | Lightweight ONNX, no PyTorch/CUDA needed |
| **Validation** | Pydantic v2 | Compile-time type safety, fast validators |
| **Config** | Pydantic Settings | `.env` / env-var config loading |
| **Language** | Python 3.13+ | Modern async, improved error messages |

---

## Usage

### Deploy as an MCP Server

BugVault communicates via MCP's **stdio transport** — it runs as a subprocess of your MCP client. There is no HTTP server to start, no port to configure.

### Configuration

#### File Location

MCP server configuration is a JSON file. The location depends on your client:

| Client | Config File Path |
|--------|-----------------|
| **Claude Code (CLI)** | `~/.claude/settings.json` |
| **Claude Desktop** | **macOS:** `~/Library/Application Support/Claude/claude_desktop_config.json`<br>**Windows:** `%APPDATA%\Claude\claude_desktop_config.json`<br>**Linux:** `~/.config/Claude/claude_desktop_config.json` |

#### Configuration Content

Add BugVault as an entry under `mcpServers`:

```json
{
  "mcpServers": {
    "bugvault": {
      "command": "/path/to/uv",
      "args": [
        "run",
        "--directory", "/absolute/path/to/bugvault",
        "python", "-m", "bugvault.main"
      ]
    }
  }
}
```

> **Important:** Use **absolute paths** for both the `uv` binary and the project directory. Do not use `~` or relative paths.
>
> 💡 Run `which uv` (macOS/Linux) or `where uv` (Windows) to find the exact path to `uv`.

### Using the `/mcp` Command (Claude Code)

After editing `~/.claude/settings.json`, restart Claude Code entirely (not just `/mcp` — closing and reopening the terminal suffices). Then type:

```
/mcp
```

This lists all configured MCP servers with one of three statuses:

| Status | Meaning |
|--------|---------|
| **running** ✅ | Server is active and ready |
| **not running** ⏸️ | Normal — BugVault uses **lazy loading** (see below) |
| **error** ❌ | Server failed to start — paths are likely wrong |

> **Lazy loading:** BugVault only starts when you first call one of its tools (`save_bug_experience` or `retrieve_bug_experience`). Seeing "not running" is expected. After the first tool invocation, `/mcp` will show "running".
>
> **Don't panic on first call:** The initial cold start takes **3–5 seconds** (downloading/loading the embedding model + connecting to LanceDB). This is normal — subsequent calls are instant.

If the status shows **"error"**, the most common cause is an incorrect path. Double-check:
- `which uv` gives the correct absolute path
- The `--directory` argument points to the BugVault project root (where `pyproject.toml` lives)
- You didn't use `~` or `$HOME` — expand them to the full path

> **Note:** `/mcp stop`, `/mcp restart`, and similar subcommands are **not available** in all versions of Claude Code. If they don't work, simply restart the terminal or the Claude Desktop app.

### First-Time Startup Tips

1. **Restart is mandatory** — Claude Code and Claude Desktop only read the config file at startup. Closing and reopening is required after editing `settings.json`.
2. **First tool call is slow (~3–5s)** — the embedding model (90 MB) downloads on first use if not cached. The server logs progress to stderr, which is invisible in Claude Code but visible when running manually.
3. **Proxy users:** If behind a corporate VPN/proxy and the first call fails:
   ```bash
   # Start without proxy for the initial model download
   unset all_proxy ALL_PROXY
   uv run python -m bugvault.main  # triggers download
   ```
   After the model is cached at `~/.cache/fastembed/`, re-enable your proxy.
4. **Language mismatch:** If you're using an English Claude but storing Chinese bug records, BugVault handles both — the embedding model (`BAAI/bge-small-zh-v1.5`) is bilingual. Just describe your needs naturally.

### Verify the Deployment

After restarting your MCP client, try these progressively to confirm everything works:

**1. Save a test record:**
> "Save a test bug record: title is 'test deployment', error is 'ConnectionError: timeout', tried restarting the service, final solution was increasing the timeout."

**2. Retrieve it:**
> "I ran into a connection timeout issue before — can you check my past bug records?"

If deployment succeeds, Claude will call the MCP tools and return results.

**If Claude says "I don't have access to that tool"** or nothing happens:
- Check `/mcp` status first (Claude Code)
- Re-read the paths in your config JSON
- Try the manual test below

### Manual Testing

```bash
# Start the server directly (with combined stdout/stderr for debugging)
uv run python -m bugvault.main 2>&1

# Run the unit tests
uv run pytest tests/test_core.py -v

# Run the E2E protocol test (spawns server subprocess)
uv run pytest tests/test_integration.py -v -m e2e
```

---

## Deployment Troubleshooting

### Common Errors and Solutions

#### 1. `[MCP Error] CONNECTION_CLOSED` or `Connection closed`

**Cause:** The server process crashed during startup — typically during embedding model loading or LanceDB initialization.

**Diagnosis:**
```bash
# Start server manually and watch for errors
uv run python -m bugvault.main 2>&1
```

**Solutions:**
- Ensure `uv sync` completed successfully
- Check that Python version is 3.13+: `python --version`
- Verify network access for first-time model download (fastembed downloads `BAAI/bge-small-zh-v1.5` on first run)
- If behind a proxy: `unset all_proxy ALL_PROXY`

#### 2. Table / DB already exists error

```
ValueError: Table 'bug_records' already exists
```

**Cause:** Run multiple times without proper cleanup; LanceDB table already created from a prior session.

**Solution:** The server now handles this gracefully by opening existing tables. If you see this, ensure you're running the latest code and the table existence check is working correctly:
```bash
git pull
uv sync
```

To reset from scratch:
```bash
rm -rf ~/.bugvault/lancedb/bug_records*
```

#### 3. Server starts but tools don't appear in Claude Code

**Cause:** Claude Code only discovers tools after the server successfully responds to an `initialize` handshake. A crash before that handshake means no tools are registered.

**Diagnosis:**
- Run `/mcp` in Claude Code to see registered MCP servers
- If BugVault shows "error" or "not running", check the MCP log: `cat ~/.claude/logs/*.log`
- Run the server manually to confirm it starts without errors: `uv run python -m bugvault.main 2>&1 | head -20`

**Common causes:**
- **Incorrect `uv` path:** Use `which uv` to find the absolute path; don't use `~/.local/bin/uv` if uv is elsewhere
- **Relative project path:** The `--directory` argument must be an absolute path
- **Working directory mismatch:** The server's `cwd` must be the BugVault project root

#### 4. Embedding model download fails

```
ConnectionError: HTTPSConnectionPool ... Name or service not known
```

**Solutions:**
- First-time download requires internet access (~90 MB model file)
- Set `BUGVAULT_EMBEDDING_MODEL` to a different model if the default is inaccessible
- Cache location: `~/.cache/fastembed/` — once downloaded, offline use works
- If using a proxy: unset proxy variables during first download, then re-enable

#### 5. ImportError: cannot import name '...' from 'bugvault...'

**Cause:** The Python package structure doesn't include the new `database/` or `mcp_tools/` subpackages.

**Solution:** Ensure all `__init__.py` files exist (they do in this project). If you're running from a different directory, set `PYTHONPATH` correctly:
```bash
cd /absolute/path/to/bugvault
PYTHONPATH=src uv run python -m bugvault.main
```

#### 6. LanceDB / PyArrow version mismatch

```
ValueError: The LanceDB table has not been created with the same schema
```

**Solution:** LanceDB tables are schema-locked. If the schema changes during development, delete old data:
```bash
rm -rf ~/.bugvault/lancedb
uv run pytest tests/test_integration.py -v -m e2e  # re-creates table
```

### Debugging Checklist

```
□ uv sync completed without errors
□ Python 3.13+ is active (python --version)
□ uv path is absolute (which uv)
───
□ ~/.claude/settings.json uses absolute paths
□ --directory points to the project root containing pyproject.toml
───
□ First-time model download has internet access
□ ~/.bugvault/lancedb is writable
───
□ uv run python -m bugvault.main   starts without errors
□ uv run pytest tests/ -v          all tests pass
```

---

## Project Structure

```
bugvault/
├── pyproject.toml               # Project config & dependencies
├── .env.example                 # Environment variable template
├── README.md
├── src/
│   └── bugvault/
│       ├── main.py              # MCP server entry point (~70 lines)
│       ├── config.py            # Pydantic settings (env-based)
│       ├── models/
│       │   └── bug_record.py    # BugRecord data model
│       ├── services/
│       │   ├── retrieval_svc.py # ANN search + reranking + truncation
│       │   └── ingestion_svc.py # Validation + probing + MD archive
│       ├── database/
│       │   └── lancedb_client.py# LanceDBClient OOP data access layer
│       ├── mcp_tools/
│       │   └── tools.py         # MCP tool registration + handlers
│       └── utils/
│           ├── stdout_guard.py  # MCP stdio transport protection
│           ├── logger.py        # stderr-only logging
│           └── text_utils.py    # Stack trace truncation
└── tests/
    ├── test_core.py             # 15 unit tests (models, services, utils)
    ├── test_mcp_protocol.py     # E2E jsonrpc protocol test
    └── test_integration.py      # Save → Retrieve round-trip
```

---

## Data Model

```python
class BugRecord(BaseModel):
    # ── Required fields ──
    bug_title: str              # Short descriptive title
    error_log_snippet: str      # Error message / stack trace
    tried_methods: str          # Methods attempted (even failed)
    final_solution: str         # The working fix

    # ── Optional (enriched asynchronously) ──
    project_name: str | None
    tech_stack: str | None
    root_cause: str | None

    # ── System-managed ──
    create_time: str            # ISO-8601 timestamp (auto-generated)
```

---

## Development

### Running Tests

```bash
# Unit tests (fast, no external deps)
uv run pytest tests/test_core.py -v

# E2E protocol test (spawns real server subprocess, ~15s)
uv run pytest tests/test_integration.py -v -m e2e

# All tests
uv run pytest tests/ -v
```

### Configuration

Configured via environment variables (prefix `BUGVAULT_`) or `.env`:

```bash
BUGVAULT_EMBEDDING_MODEL=BAAI/bge-small-zh-v1.5
BUGVAULT_TOP_K=5
BUGVAULT_RECENCY_WEIGHT=0.3
BUGVAULT_RECENCY_HALF_LIFE_DAYS=90
BUGVAULT_THREAD_POOL_WORKERS=2
```

See [.env.example](.env.example) for all options.

---

## How MCP Stdio Transport Works

BugVault uses the **stdio transport** — the simplest MCP communication mode:

```
┌─────────────────────┐          JSON-RPC 2.0          ┌─────────────────────┐
│   MCP Client        │  ──────────────────────────►   │   BugVault Server   │
│  (Claude Code /     │  stdin (write to server)       │  (uv run python     │
│   Claude Desktop)   │  ◄──────────────────────────   │   -m bugvault.main) │
│                     │  stdout (read from server)     │                     │
└─────────────────────┘                                └─────────────────────┘
                                                              │ stderr (logs)
                                                              ▼
                                                        terminal / log file
```

Key points:
- The MCP client **spawns** BugVault as a child process via `uv run python -m bugvault.main`
- The client writes JSON-RPC requests to the server's **stdin**
- The server writes JSON-RPC responses to its **stdout** (which the client reads)
- **stderr is reserved for logging** — visible in your terminal but ignored by the MCP protocol
- The `_MCPStdoutProxy` guard ensures that no accidental `print()` calls corrupt the protocol stream

This is why running `uv run python -m bugvault.main 2>&1` shows logging output but no JSON-RPC traffic — the JSON is sent to stdout but only meaningful when a client is writing requests to stdin.

---

## Design Decisions

- **Why not LangChain?** BugVault's logic is linear CRUD + vector search. A framework adds abstraction without value. Native MCP SDK keeps the stack shallow and debuggable.
- **Why not FastAPI?** MCP's `stdio` mode communicates via stdin/stdout, not HTTP. FastAPI only makes sense for SSE (HTTP) transport, which adds port management and dependency weight.
- **Why fastembed instead of sentence-transformers?** A fresh `pip install sentence-transformers` pulls in PyTorch + NVIDIA CUDA libraries (~2.5 GB), even on a CPU-only machine. fastembed uses pure ONNX Runtime (~30 MB) — no GPU required.
- **Why not Content-Length framing?** The MCP Python SDK's `stdio_server()` uses newline-delimited JSON (one JSON object per line), not the Content-Length framing documented in the spec.

---

## Troubleshooting

| Problem | Solution |
|---------|----------|
| Embedding model download fails behind proxy | `unset all_proxy ALL_PROXY` (fastembed uses direct HTTP) |
| E2E test times out | First run downloads model (~1 min); subsequent runs are ~15s |
| No output when starting server | Output goes to stderr — use `uv run python -m bugvault.main 2>&1` |
| Tools not showing in Claude Code | Check absolute paths in `~/.claude/settings.json`; verify `uv run python -m bugvault.main` works |
| "Connection closed" error | Server crashed during init — run manually with `2>&1` to see the traceback |
| LanceDB schema mismatch after update | `rm -rf ~/.bugvault/lancedb` then restart |

---

## Roadmap

- **v1.0 (MVP)** — Core MCP server with save/retrieve + LanceDB + embedding
- **v1.1** — Time-decay reranking, field-level probe questions, .md bulk import
- **v1.2** — Knowledge graph visualization, VSCode/Cursor extension

---

## License

MIT