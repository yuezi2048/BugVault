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

BugVault is a **local-first MCP (Model Context Protocol) server** — a dedicated "Memory Agent" that pairs with your LLM (the "Decision Agent") to form a **two-agent collaborative system** for bug troubleshooting.

- **Decision Agent** (Claude / any LLM): Diagnoses bugs, devises fixes, decides what to save and reflect on.
- **Memory Agent** (BugVault): Provides semantic retrieval, persists resolutions, evaluates RAG quality, and writes prevention rules.

All data stays **100% local** — no cloud, no API fees, no data leaks.

### Agent Self-Evolution Flywheel

```
 Troubleshooting ──→ Resolution ──→ Reflection ──→ Never repeat
   (retrieve)          (save)          (reflect)
        ↑                                       │
        └───────── Knowledge Base ──────────────┘
                  (LanceDB + .md + CLAUDE.md)
```

Each completed cycle makes the Agent smarter — past solutions are retrievable, and prevention rules prevent the same mistake twice.

### Key Features

- **Semantic Retrieval** — Find past bugs by natural-language query, not keyword search
- **Auto-persistence** — Save resolved bugs with zero manual effort (4 required fields)
- **Dedup & Upsert** — MD5 hash primary key (`record_id`) + LanceDB `merge_insert` guarantees zero duplicate entries
- **Concurrency Safe** — `threading.Lock` protects read/write across async threads
- **Relevance Floor** — `MIN_SEMANTIC_SCORE=0.55` discards irrelevant documents ("宁缺毋滥")
- **Smart Truncation** — Stack traces are intelligently cropped to preserve tokens without losing signal
- **Time-decay Reranking** — Recent solutions rank higher; obsolete ones fade automatically
- **Optional RAG Evaluation** — Tri-axis LLM judge scores `context_relevance` (0–5) + `faithfulness` (0–5) for quality monitoring
- **Agent Self-Evolution** — `reflect_and_prevent_error` writes prevention rules to CLAUDE.md so the Agent never repeats the same mistake
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

# Run all 43 tests to verify
uv run pytest -v
```

---

## Architecture: Two-Agent Collaboration

```
┌─────────────────────────────────────────────────────────────────┐
│                    Decision Agent (Claude)                       │
│                                                                  │
│  1. User reports bug                                             │
│  2. Agent calls retrieve_bug_experience ←───────────────────┐   │
│     → gets past solutions + RAG confidence score             │   │
│  3. Agent diagnoses + fixes the bug                          │   │
│  4. Agent calls save_bug_experience ─────────────────────────┘   │
│     → MD archived immediately                                  │
│     → vector indexed asynchronously                            │
│  5. Agent calls reflect_and_prevent_error                      │
│     → prevention rule written to CLAUDE.md                     │
│  6. Next session: CLAUDE.md loaded → Agent never repeats       │
└──────────────────┬────────────────────────────────────────────┘
                   │ JSON-RPC via stdio (MCP)
                   ▼
┌─────────────────────────────────────────────────────────────────┐
│                   Memory Agent (BugVault)                        │
│                                                                  │
│  ┌─────────────────────────────────────────────────────────┐    │
│  │  Three Single-Responsibility Tools                      │    │
│  │                                                         │    │
│  │  🛠️  RETRIEVE ────  🧠  SAVE ────────  📝  REFLECT   │    │
│  │  (independent     (MD sync +       (classify root     │    │
│  │   ANN + rerank    async vector)     cause + write      │    │
│  │   + RAG eval)                       to CLAUDE.md)      │    │
│  └─────────────────────────────────────────────────────────┘    │
│                                                                  │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐       │
│  │ LanceDB  │  │ fastembed│  │ RAG LLM │  │ Archive  │       │
│  │ (vector) │  │ (ONNX)   │  │ (judge)  │  │ (.md)    │       │
│  └──────────┘  └──────────┘  └──────────┘  └──────────┘       │
└─────────────────────────────────────────────────────────────────┘
```

### Key Principle: Clean Separation

| Layer | Responsibility | Never Does |
|-------|---------------|------------|
| **Decision Agent** (Claude) | Diagnose, fix, decide what to save/reflect | ❌ Direct DB access |
| **Memory Agent** (BugVault) | Retrieve, persist, evaluate, write rules | ❌ Fix bugs or make decisions |
| **RAG Eval** | Returns confidence data only | ❌ Modifies Claude's response |

---

## The Three Tools

### 🛠️ `retrieve_bug_experience` — Proactive Memory Recall

When the Agent encounters a bug (or the user asks about past bugs), it calls this tool **independently on the BugVault side** — not by Claude itself. BugVault handles the full pipeline:

```
1. embed query → 2. ANN search → 3. hybrid rerank + semantic threshold → 4. [optional] RAG evaluation
```

**RAG evaluation** runs as an independent hook (not blocking Claude). It returns **tri-axis confidence data** so Claude knows exactly how trustworthy each result is:

```json
{
  "rag_confidence_score": 8.5,       // context_relevance(3.5) + faithfulness(5.0)
  "evaluation": "Doc1 is directly on-topic; Doc2 partially relevant...",
  "context_relevance": 3.5,          // 0-5: how useful are the retrieved docs?
  "faithfulness": 5.0,               // 0-5: is the info faithful to sources?
  "justification": "Deducted points because Doc3 is off-topic..."
}
```

### 💾 `save_bug_experience` — Zero-Blocking Persistence

After fixing the bug, the Agent saves both the **attempt path** (`tried_methods`) and **final result** (`final_solution`). The save is split into two paths:

| Path | Speed | What happens |
|------|-------|-------------|
| **SYNC** (in executor) | **~ms** | Pydantic validation → MD5 record_id → write human-readable .md archive → return "saved successfully" |
| **ASYNC** (fire-and-forget) | ~100ms | ONNX embedding → LanceDB `merge_insert` (auto-dedup by `record_id`) |

The .md file is written **before** the Agent gets the response — the archive is always safe even if the async task fails later.

### 🧠 `reflect_and_prevent_error` — Agent Self-Evolution

This is what makes BugVault **smarter over time**. After resolving a bug, the Agent proactively reflects on the root cause:

| Category | Meaning | Example |
|----------|---------|---------|
| `understanding_bias` | Misunderstood user's implicit intent | "Customer didn't explicitly say env vars were configured" |
| `code_logic_error` | Code handling mistake | "Forgot to check .get() return for None" |
| `api_misuse` | Wrong API usage | "Called async function without await" |
| `environment_issue` | Environment/config problem | "Missing system dependency" |
| `other` | Catch-all | — |

The prevention rule is written to **CLAUDE.md** under `## Bug Prevention Rules`. Since CLAUDE.md is loaded as part of the Agent's system prompt on the next session, the Agent **never makes the same mistake again**.

---

## Project Structure

```
bugvault/
├── pyproject.toml                 # Project config & dependencies
├── .env.example                   # Environment variable template
├── scripts/
│   └── rag_evaluation_report.py   # End-to-end RAG evaluation runner
├── src/
│   └── bugvault/
│       ├── main.py                # MCP entry point (~70 lines)
│       ├── config.py              # Pydantic settings (env-based)
│       ├── models/
│       │   ├── bug_record.py      # BugRecord: 4 required + record_id + MD5
│       │   ├── rag_eval_result.py # Tri-axis RAGAS result model
│       │   └── reflection_rule.py # Prevention rule model
│       ├── services/
│       │   ├── retrieval_svc.py   # ANN + rerank + semantic threshold
│       │   ├── ingestion_svc.py   # Validation + probe questions
│       │   ├── rag_evaluator_svc.py # Optional: tri-axis LLM judge + retry
│       │   ├── embedding_svc.py   # fastembed ONNX wrapper
│       │   ├── archive_svc.py     # Markdown archive writer
│       │   └── reflection_svc.py  # CLAUDE.md prevention rules
│       ├── database/
│       │   └── lancedb_client.py  # LanceDB: merge_insert + Lock + overwrite
│       ├── mcp_tools/
│       │   └── tools.py           # MCP tool registration + dispatch
│       └── utils/
│           ├── stdout_guard.py    # MCP stdio transport protection
│           ├── logger.py          # stderr-only logging
│           └── text_utils.py      # Stack trace truncation
└── tests/
    ├── test_core.py               # 20+ unit tests
    ├── test_v2_services.py        # Reflection + RAG evaluator
    ├── test_integration.py        # Save → Retrieve round-trip (subprocess)
    └── test_mcp_protocol.py       # MCP handshake smoke test
```

---

## Data Model

```python
class BugRecord(BaseModel):
    # ── Required ──
    bug_title: str              # Short descriptive title
    error_log_snippet: str      # Error message / stack trace
    tried_methods: str          # Methods attempted (even failed)
    final_solution: str         # The working fix

    # ── Optional ──
    project_name: str | None
    tech_stack: str | None
    root_cause: str | None

    # ── System-managed ──
    record_id: str | None       # MD5(bug_title + error_log_snippet) — auto-computed
    create_time: str            # ISO-8601 UTC timestamp (auto-generated)
```

### `record_id` — Automated Dedup Key

```python
@model_validator(mode="after")
def _compute_record_id(self) -> "BugRecord":
    import hashlib
    raw = (self.bug_title + self.error_log_snippet).encode("utf-8")
    self.record_id = hashlib.md5(raw).hexdigest()
    return self
```

---

## RAG Evaluation (Optional)

When enabled (`BUGVAULT_ENABLE_RAG_EVAL=true` + a valid API key), every retrieval triggers an independent tri-axis evaluation. The results are appended as metadata — Claude uses the confidence score to decide how much to trust the retrieved results.

### Three Axes

| Axis | Range | Meaning |
|------|-------|---------|
| `context_relevance` | 0.0–5.0 | How useful are the retrieved documents for this query? |
| `faithfulness` | 0.0–5.0 | Is the extracted information faithful to source docs? |
| `justification` | text | Harsh, specific reasoning for every point deducted |

**Total**: `context_relevance + faithfulness` = 0–10 final score.

### Resilience
- `response_format={"type": "json_object"}` forces valid JSON from the LLM
- If parsing fails → auto-retry once
- If both attempts fail → gracefully returns empty result (never blocks retrieval)

---

## Deployment

### Configuration File

Add BugVault as an MCP server in your client's config:

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

> **Config locations:** Claude Code: `~/.claude/settings.json` | Claude Desktop: `~/Library/Application Support/Claude/claude_desktop_config.json` (macOS)

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `BUGVAULT_EMBEDDING_MODEL` | `BAAI/bge-small-zh-v1.5` | Embedding model (bilingual) |
| `BUGVAULT_TOP_K` | `5` | Max retrieval results |
| `BUGVAULT_ENABLE_RAG_EVAL` | `false` | Enable LLM judge evaluation |
| `BUGVAULT_EVAL_LLM_API_KEY` | `""` | API key for judge LLM |
| `BUGVAULT_EVAL_LLM_MODEL` | `gpt-4o-mini` | Judge LLM model name |
| `BUGVAULT_EVAL_LLM_BASE_URL` | `""` | Custom API endpoint |
| `BUGVAULT_ENABLE_REFLECTION_TOOL` | `true` | Enable preventive rules tool |
| `BUGVAULT_THREAD_POOL_WORKERS` | `2` | I/O threads for async save/retrieve |

See [.env.example](.env.example) for all options.

---

## Development

### Running Tests

```bash
# All 43 tests
uv run pytest -v

# Specific test groups
uv run pytest tests/test_core.py -v         # Unit tests (~1s)
uv run pytest tests/test_v2_services.py -v  # Reflection + RAG evaluator
uv run pytest tests/test_integration.py -v  # E2E subprocess test (~15s)
```

### Programmatic Usage

```python
from bugvault.database.lancedb_client import LanceDBClient
from bugvault.models.bug_record import BugRecord
from bugvault.services.embedding_svc import EmbeddingService
from bugvault.services.archive_svc import write_markdown_archive

db = LanceDBClient()
db.initialize()
emb = EmbeddingService()

record = BugRecord(
    bug_title="Connection timeout after 30s",
    error_log_snippet="requests.exceptions.ConnectTimeout",
    tried_methods="Increased timeout to 60s",
    final_solution="Set timeout=120 in production config",
)

search_text = record.to_search_text()
vector = emb.generate_embedding(search_text)
db.upsert_record(search_text, vector, record)  # auto-dedup by record_id
write_markdown_archive(record)                 # human-readable backup
```

---

## Design Decisions

| Decision | Rationale |
|----------|-----------|
| **Why not LangChain?** | Linear CRUD + vector search. A framework adds abstraction without value. |
| **Why `threading.Lock`?** | LanceDB's Python `_table` is not thread-safe. Without explicit locking, `search()` can read stale snapshots after `merge_insert()` on another thread. |
| **Why `mode='overwrite'`?** | LanceDB's `drop_table + create_table(mode='create')` leaves stale version references causing "file not found" errors. |
| **Why `response_format=json_object`?** | Without it, LLMs wrap JSON in markdown fences causing `JSONDecodeError`. Forced mode + retry-on-error double-locks parse stability. |
| **Why 0.55 semantic threshold?** | Corresponds to ANN cosine distance ~0.90 — empirically the boundary below which documents are universally irrelevant. |
| **Why tri-axis RAGAS?** | A single score conflates "bad retrieval" with "hallucination". Three axes let Claude adjust trust: ignore off-topic results but trust faithful ones. |

---

## Troubleshooting

| Problem | Solution |
|---------|----------|
| Embedding model download fails behind proxy | `unset all_proxy ALL_PROXY`; cache at `~/.cache/fastembed/` |
| E2E test times out | First run ~1 min (model download); subsequent runs ~15s |
| Tools not showing in Claude Code | Check absolute paths in config; verify `uv run python -m bugvault.main` works |
| LanceDB file-not-found errors | `rm -rf ~/.bugvault/lancedb` then restart (fixed in v3 by `mode='overwrite'`) |

---

## License

MIT
