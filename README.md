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
│  │  │ LanceDB          │  │ Markdown Archive   │   │  │
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

### Configure Claude Desktop

Add to `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "bugvault": {
      "command": "/path/to/uv",
      "args": [
        "run",
        "--directory", "/path/to/bugvault",
        "python", "-m", "bugvault.main"
      ]
    }
  }
}
```

### Manual Testing

```bash
# Start the server directly
uv run python -m bugvault.main

# Run the E2E protocol test (spawns server subprocess)
uv run python tests/test_mcp_protocol.py
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
│       ├── main.py              # MCP server entry point
│       ├── config.py            # Pydantic settings (env-based)
│       ├── models/
│       │   └── bug_record.py    # BugRecord data model
│       ├── services/
│       │   ├── retrieval_svc.py # ANN search + reranking + truncation
│       │   └── ingestion_svc.py # Validation + probing + MD archive
│       ├── database/            # LanceDB client (initialized in main.py)
│       ├── mcp_tools/           # Tool definitions (facade layer)
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
uv run python tests/test_mcp_protocol.py

# Integration test (save → retrieve round-trip)
uv run pytest tests/test_integration.py -v -s

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

---

## Roadmap

- **v1.0 (MVP)** — Core MCP server with save/retrieve + LanceDB + embedding
- **v1.1** — Time-decay reranking, field-level probe questions, .md bulk import
- **v1.2** — Knowledge graph visualization, VSCode/Cursor extension

---

## License

MIT
