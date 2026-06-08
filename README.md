<div align="center">

# BugVault

**The AI Bug Vault — Catch every mistake once, never repeat it.**

*A local-first MCP server that gives LLMs persistent, cross-session memory for what "right" looks like in your project.*

[![Python 3.13+](https://img.shields.io/badge/python-3.13+-blue.svg)](https://www.python.org/downloads/)
[![MCP](https://img.shields.io/badge/MCP-2024--11--05-purple.svg)](https://modelcontextprotocol.io)
[![License](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)

---

[English](README.md) | [中文](README.zh.md) | [日本語](README.ja.md)

</div>

---

## What is BugVault?

BugVault is a **local-first MCP (Model Context Protocol) server** that gives AI a memory of what "right" looks like in your project.

**What is an "AI Bug"?**

A bug isn't just a stack trace. An AI Bug is **anything an LLM does that doesn't match your project's expectations**:

| Type | Example |
|------|---------|
| 🐛 **Code Error** | `KeyError: 42` — wrong logic, wrong API call |
| 📐 **Business Rule** | Used CNY yuan instead of cents; used auto-increment ID instead of UUID |
| 🏗️ **Architecture Convention** | Imported lodash when project uses vanilla JS; used Options API when project uses Composition API |
| 🧪 **Test Convention** | Named file `.test.ts` when project uses `.spec.ts`; used Jest when project uses Vitest |
| 🚦 **Style & Structure** | Used SCSS when project uses Tailwind; used class component when project uses functional |

BugVault captures **all of these** — not just crashes — with a single architecture: **retrieve → correct → remember → prevent**.

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

### What's New in v1.1.1 — Parent-Child Chunk Retrieval

- **🧩 Chunk-Level Vector Index** — Each bug record now generates **2 focused vectors** instead of 1
  long concatenation: `error_log` chunk (exact error matching) + `semantic` chunk (title +
  tried-methods + solution), stored in a dedicated `bugvault_chunks` table
- **🎯 Precision Recall** — Searching for a specific stack trace hits the `error_log` chunk
  directly, no longer diluted by long `final_solution` text
- **🔄 Parent-Document Mapping** — Chunk-level RRF fusion → dedup by `parent_id` → batch
  `fetch_records_by_ids()` from `bug_records` → Cross-Encoder reranking on full documents
- **📦 Dual Table Architecture** — `bug_records` (parent metadata + FTS) + `bugvault_chunks`
  (child vectors + redundant `tech_stack`/`project_name` for filter pushdown)
- **🏗️ `rebuild_index.py`** — Updated to generate 1 parent + 2 chunks per source record
- **🔤 Smart Tech-Stack Filtering** — `target_tech_stack="Java"` won't match `"JavaScript"` entries,
  thanks to an exclusion dictionary that keeps `LIKE` flexibility for version suffixes
  (e.g. `"Python"` still matches `"Python 3.13"`) while preventing cross-technology false positives.
  See [test report](docs/tests/v1.1.1-test-report.md#8-v111-p1-问题闭环证明) for P1 closure proof.

### What's New in v2.0 — Project Convention Memory

- **🏷️ Convention Memory** — Two new MCP tools (`save_convention` / `retrieve_convention`) for storing and querying **project conventions** — architecture rules, business rules, test conventions, and style guides
- **🧩 Shared Table Architecture** — Conventions share the same `bug_records` and `bugvault_chunks` tables as bugs, distinguished by `record_type='convention'` discriminator
- **🔄 Same Retrieval Pipeline** — Vector ANN → FTS BM25 → RRF fusion → Cross-Encoder reranking, now filtered by `record_type`
- **📦 ConventionRecord Model** — 4 mandatory fields: `convention_name`, `trigger_context`, `incorrect_behavior`, `correct_behavior`
- **🗄️ Auto Schema Migration** — `_migrate_v2_schema_if_needed()` adds the `record_type` column to existing v1.1.x tables at startup (idempotent, non-destructive)
- **📚 Separate Markdown Archive** — Conventions archived to `~/.bugvault/archive/conventions/`
- See [v2.0 release notes](docs/v2.0/v2.0.0-release-notes.md) and [convention spec](docs/v2.0/convention-spec.md)

### What's New in v1.1

- **🎯 Hybrid Retrieval** — Vector + FTS dual recall fused via RRF (k=60) — see [v1.1 architecture](docs/refer/设计/04.v1.1-architecture.md)
- **⚡ Cross-Encoder Reranking** — Lightweight ONNX cross-encoder for 2nd-pass precision — see [ADR](docs/refer/设计/adr-cross-encoder-vs-colbert.md)
- **🧪 Claim-Level RAG Evaluation** — CoT-based claim extraction + verification with per-claim `Supported/Reason` — see [evaluation strategy](docs/refer/设计/04.v1.1-architecture.md#二评估链路策略模式--双重降级)
- **🛡️ Double Fallback** — Quota-based + exception-based graceful degradation — never crash on LLM parse errors
- **🔍 Metadata Pre-filtering** — `target_tech_stack` + `target_project_name` for cross-language elimination — see [metadata filter design](docs/refer/设计/metadata-filtering.md) and [v1.1 architecture](docs/refer/设计/04.v1.1-architecture.md#三元数据预过滤)
- **📊 Token Tracking** — `prompt_tokens` / `completion_tokens` / `total_tokens` returned per evaluation
- **🧹 DB Maintenance** — `drop_table()` + concurrent batch rebuild via `scripts/rebuild_index.py`
- **🔒 Path Safety** — Global `.expanduser().resolve()` + `mkdir(parents=True, exist_ok=True)` to prevent `~` and missing-directory crashes

### v1.0 Features (retained)

- **Semantic Retrieval** — Find past bugs by natural-language query
- **Auto-persistence** — Save resolved bugs with zero manual effort (4 required fields)
- **Dedup & Upsert** — MD5 hash primary key (`record_id`) + LanceDB `merge_insert`
- **Concurrency Safe** — `threading.Lock` protects read/write across async threads
- **Smart Truncation** — Stack traces intelligently cropped
- **Agent Self-Evolution** — `reflect_and_prevent_error` writes prevention rules to CLAUDE.md
- **MCP-native** — Works with any MCP client: Claude Desktop, Claude Code, Cursor, etc.

---

## Quick Start

### Prerequisites

- Python 3.13+
- [uv](https://docs.astral.sh/uv/) (package manager)

### Installation & Setup

```bash
# Clone the repository
git clone https://github.com/yourusername/bugvault.git
cd bugvault

# Install dependencies (no GPU required, ONNX runs on CPU)
uv sync

# (Optional) Configure RAG judge LLM for quality evaluation
cp .env.example .env
# Edit .env — set BUGVAULT_ENABLE_RAG_EVAL=true and BUGVAULT_EVAL_LLM_API_KEY

# Verify everything works (137+ tests)
uv run pytest -v

# (Optional) Seed the database with sample data
uv run python scripts/rebuild_index.py --skip-clear
```

### Run the MCP Server

Configure your MCP client (Claude Desktop, Claude Code, Cursor, etc.)
to launch BugVault as a subprocess. The standard config entry:

```json
{
  "mcpServers": {
    "bugvault": {
      "command": "uv",
      "args": [
        "run",
        "--directory", "/path/to/bugvault",
        "python", "-m", "bugvault.main"
      ]
    }
  }
}
```

See [docs/refer/分析/05.交付形式.md](docs/refer/分析/05.交付形式.md) for detailed deployment instructions.

---

## Architecture: Two-Agent Collaboration

```
┌─────────────────────────────────────────────────────────────────┐
│                    Decision Agent (Claude)                       │
│                                                                  │
│  1. User reports bug                                             │
│  2. Agent calls retrieve_bug_experience ←───────────────────┐   │
│     → past solutions + RAG score + suggested_action         │   │
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
│                   Memory Agent (BugVault v1.1)                  │
│                                                                  │
│  ┌─────────────────────────────────────────────────────────┐    │
│  │  Retrieve Pipeline (funnel architecture, v1.1.1)         │    │
│  │                                                         │    │
│  │  query                                                  │    │
│  │    ├─→ [chunks]  Vector ANN (top_k×4) ───┐             │    │
│  │    ├─→ [chunks]  FTS BM25   (top_k×4) ───┤             │    │
│  │    │   WHERE tech_stack / project_name    │             │    │
│  │    │                                      │             │    │
│  │    ├── Chunk-level RRF Fusion ────────────┤             │    │
│  │    ├── Parent dedup (by parent_id) ───────┤             │    │
│  │    ├── fetch_records_by_ids(parent_ids) ──┘             │    │
│  │    │                                     ┌──────────────┘    │
│  │    ├── rerank (time decay) ──────────────┤                   │
│  │    ├── Cross-Encoder rerank ─────────────┤                   │
│  │    └── Truncate → top_k ────────────────┘                   │
│  │                                                         │    │
│  │  🛠️  RETRIEVE ──  🧠  SAVE ──  📝  REFLECT            │    │
│  │                                                         │    │
│  └─────────────────────────────────────────────────────────┘    │
│                                                                  │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐       │
│  │ LanceDB  │  │ fastembed│  │ RAG LLM │  │ Archive  │       │
│  │(vec+FTS) │  │(emb+CE)  │  │(judge)   │  │ (.md)    │       │
│  └──────────┘  └──────────┘  └──────────┘  └──────────┘       │
└─────────────────────────────────────────────────────────────────┘
```



### Key Principle: Clean Separation

| Layer                       | Responsibility                             | Never Does                   |
| --------------------------- | ------------------------------------------ | ---------------------------- |
| **Decision Agent** (Claude) | Diagnose, fix, decide what to save/reflect | ❌ Direct DB access           |
| **Memory Agent** (BugVault) | Retrieve, persist, evaluate, write rules   | ❌ Fix bugs or make decisions |
| **RAG Eval**                | Returns confidence + `suggested_action`    | ❌ Modifies Claude's response |

---

## The Five Tools

### 🏷️ `save_convention` — Project Convention Memory (v2.0)

When a user corrects the AI about a project rule (business rule, architecture
convention, test convention, style guide), the AI calls this tool immediately
to persist the rule for future sessions.

**4 mandatory fields:**

| Field | Example |
|-------|---------|
| `convention_name` | "API Response Format" |
| `trigger_context` | "When writing a new REST API endpoint" |
| `incorrect_behavior` | "Returning raw dict" |
| `correct_behavior` | "Use `{\"code\": 0, \"data\": ..., \"message\": \"ok\"}` format" |

**Execution:** synchronous Markdown archive → fire-and-forget embedding + LanceDB upsert
with `record_type='convention'`. Returns confirmation to the AI immediately.

### 🔍 `retrieve_convention` — Proactive Convention Check (v2.0)

Before making code changes, the AI proactively queries this tool to check if
any project conventions govern the area being modified.

Uses the **same retrieval pipeline** as bug search (vector ANN + FTS BM25 → RRF fusion
→ Cross-Encoder reranking), filtered to `record_type='convention'`.

```
retrieve_convention(
    query="API response format",
    target_scope="src/api/",
    target_tags="Python, FastAPI"
)
```

### 🛠️ `retrieve_bug_experience` — Proactive Memory Recall

When the Agent encounters a bug (or the user asks about past bugs), it calls this tool **independently on the BugVault side** — not by Claude itself. BugVault handles the full pipeline:

1. embed query → 2. Vector ANN + FTS BM25 dual recall
   → 3. RRF fusion (k=60) → 4. Cross-Encoder rerank
   → 5. Truncate to top_k → 6. [optional] RAG evaluation

**New in v1.1 — metadata pre-filtering:**

```python
retrieve_bug_experience(
    query="ModuleNotFoundError",
    target_tech_stack="Python",      # ← new: filters by tech stack (case-insensitive)
    target_project_name="order-svc",  # ← new: filters by project name
    eval_depth="claim_level",         # ← new: CoT-based claim verification
)
```

**RAG evaluation** supports two strategies selectable via `eval_depth`:

| `eval_depth` | Strategy | Token cost | Output |
|---|---|---|---|
| `"none"` | Skip | 0 | No evaluation block |
| `"simple"` | Holistic scoring | ~300 | `context_relevance`(0-5) + `faithfulness`(0-5) + `justification` |
| `"claim_level"` | CoT extraction + verification | ~1500 | ← above + `claims_analysis[]` with per-claim `{claim, supported, reason}` |

**Claim-level** forces the judge LLM to:
1. Extract atomic factual claims from the retrieved documents
2. Verify each claim against source context (✅ supported / ❌ unsupported / ⚠️ partial)
3. Compute `faithfulness = supported_claims / total_claims`

See [evaluation strategy](docs/refer/设计/evaluation-strategy.md) for full design details, and [v1.1 architecture](docs/refer/设计/04.v1.1-architecture.md#二评估链路策略模式--双重降级) for the system integration.

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
│   ├── rag_evaluation_report.py   # End-to-end RAG evaluation runner
│   └── migrate_v2.py              # v1.1.x → v2.0 schema migration
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
│       │   └── lancedb_client.py  # LanceDB: dual tables + record_type discriminator + auto schema migration (v2.0)
│       ├── mcp_tools/
│       │   └── tools.py           # MCP tool registration + dispatch (5 tools: bug + convention + reflection)
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

### 🐞 BugRecord — Saved/Retrieved Bug Experience

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

### 🏷️ ConventionRecord — Project Convention Memory (v2.0)

```python
class ConventionRecord(BaseModel):
    # ── Mandatory (4 fields) ──
    convention_name: str         # Short rule name (1-256 chars)
    trigger_context: str         # When/where this applies
    incorrect_behavior: str      # What the AI should NOT do
    correct_behavior: str        # What the AI SHOULD do

    # ── Optional ──
    scope: str | None            # Scope (e.g. "src/api/")
    tags: str | None             # Tags (e.g. "Python, FastAPI")

    # ── System-managed ──
    record_id: str | None        # MD5(convention_name + trigger_context)
    create_time: str             # ISO-8601
    record_type: str = "convention"  # Discriminator
```

Shares the **same database table** as BugRecord via `record_type='convention'` discriminator.
The same retrieval pipeline (vector ANN + FTS BM25 → RRF fusion → Cross-Encoder reranking)
applies to both bug experiences and project conventions.

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

---

## Data Models

### 🐞 `BugRecord` — Saved/Retrieved Bug Experience

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `bug_title` | `str` (1-256) | ✅ | Short descriptive title |
| `error_log_snippet` | `str` (1-32768) | ✅ | Error message or stack trace |
| `tried_methods` | `str` (1-8192) | ✅ | Methods already attempted |
| `final_solution` | `str` (1-16384) | ✅ | The working fix |
| `project_name` | `str \| None` | ❌ | Affected project or service |
| `tech_stack` | `str \| None` | ❌ | Technology tags (e.g. "Python 3.13, Django") |
| `root_cause` | `str \| None` | ❌ | Root cause analysis (≤4096 chars) |
| `record_id` | `str \| None` | 🛠️ auto | MD5(`bug_title` + `error_log_snippet`) — dedup key |
| `create_time` | `str` | 🛠️ auto | ISO-8601 UTC timestamp |

### 📊 `RAGEvalResult` — Evaluation Output (all fields optional)

| Field | Type | Range | Description |
|-------|------|-------|-------------|
| `strategy_used` | `str` | `simple` / `claim_level` / `simple (fallback_from_error)` | Which strategy produced this result |
| `rag_confidence_score` | `float \| None` | 0-10 | Combined: `faithfulness*5 + context_relevance` |
| `context_relevance` | `float \| None` | 0.0-5.0 | How useful are the retrieved docs for the query? |
| `faithfulness` | `float \| None` | 0.0-5.0 (simple) / 0.0-1.0 (claim_level) | % of claims supported by source docs |
| `evaluation` | `str \| None` | — | Alias for `justification` |
| `justification` | `str \| None` | — | Harsh reasoning explaining point deductions |
| `claims_analysis` | `list[dict] \| None` | — | Claim-level: `[{claim, supported, reason}]` |
| `suggested_action` | `str \| None` | `CONFIDENT` / `PARTIAL` / `CAUTION` / `INSUFFICIENT` | Structured guidance for the Agent |
| `prompt_tokens` | `int \| None` | — | Tokens in the prompt sent to judge LLM |
| `completion_tokens` | `int \| None` | — | Tokens in the completion from judge LLM |
| `total_tokens` | `int \| None` | — | Total tokens consumed by the evaluation |

### 🛠️ Tool: `retrieve_bug_experience` — Request Parameters

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `query` | `string` | ✅ | — | Error message, stack trace, or bug description |
| `eval_depth` | `enum` | ❌ | `"simple"` | `"none"` / `"simple"` / `"claim_level"` |
| `target_tech_stack` | `string` | ❌ | — | Tech stack filter (e.g. `"Python"`), case-insensitive |
| `target_project_name` | `string` | ❌ | — | Project name filter (e.g. `"order-svc"`), case-insensitive |

**Return value:** A formatted text block containing:
1. `--- Retrieval Info ---` — strategy used (hybrid / vector-only) + source counts
2. `--- Result N ---` — one section per retrieved bug record (title, project, error, tried, solution, root cause)
3. `--- RAG Evaluation ---` — confidence scores, token usage, claim analysis (if `eval_depth != "none"`)

### 💾 Tool: `save_bug_experience` — Request Parameters

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `bug_title` | `string` | ✅ | Short descriptive title |
| `error_log_snippet` | `string` | ✅ | Error message or stack trace |
| `tried_methods` | `string` | ✅ | Methods already attempted |
| `final_solution` | `string` | ✅ | The working fix |
| `project_name` | `string` | ❌ | Affected project (optional) |
| `tech_stack` | `string` | ❌ | Technology tags (optional) |
| `root_cause` | `string` | ❌ | Root cause analysis (optional) |

### 📝 Tool: `reflect_and_prevent_error` — Request Parameters

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `reflection_text` | `string` | ✅ | Detailed analysis of what caused the bug |
| `error_category` | `enum` | ✅ | `understanding_bias` / `code_logic_error` / `api_misuse` / `environment_issue` / `other` |
| `preventive_rule` | `string` | ✅ | Concise actionable rule to prevent recurrence |

---

## Key Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `BUGVAULT_DATA_ROOT` | `~/.bugvault` | Root directory for LanceDB + markdown archive |
| `BUGVAULT_ENABLE_RAG_EVAL` | `false` | Enable LLM judge RAG evaluation |
| `BUGVAULT_EVAL_LLM_API_KEY` | `""` | API key for judge LLM |
| `BUGVAULT_EVAL_LLM_MODEL` | `gpt-4o-mini` | Judge LLM model name |
| `BUGVAULT_EVAL_LLM_BASE_URL` | `https://api.openai.com/v1` | Custom API endpoint (OpenAI-compatible) |
| `BUGVAULT_TOP_K` | `5` | Max retrieval results |
| `BUGVAULT_ENABLE_FTS` | `true` | Enable full-text search dual recall |
| `BUGVAULT_ENABLE_RERANKER` | `true` | Enable Cross-Encoder reranking |
| `BUGVAULT_RERANKER_MODEL` | `Xenova/ms-marco-MiniLM-L-6-v2` | Cross-Encoder model name |
| `BUGVAULT_ENABLE_RECENCY_DECAY` | `false` | Time-decay reranking (off = old bugs rank equally) |
| `BUGVAULT_MAX_CLAIM_EVALS_PER_SESSION` | `10` | Claim-level eval session cap (circuit breaker) |
| `BUGVAULT_ENABLE_REFLECTION_TOOL` | `true` | Enable preventive rules tool |
| `BUGVAULT_THREAD_POOL_WORKERS` | `2` | I/O threads for async save/retrieve |

See [.env.example](.env.example) for the complete list (20+ options).

---

## Development

### Running Tests

```bash
# All 137 tests
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

## Tech Stack & Design Decisions

| Decision | Rationale | Reference |
|----------|-----------|-----------|
| **Why MCP over Skill/Plugin?** | "Write once, run everywhere" — any MCP client (Claude Desktop, Cursor, Windsurf) can use BugVault without per-platform adapters. Pure local `stdio` transport, no ports, no network. | [why-not-skill.md](docs/refer/分析/02.为什么不做成skill.md) |
| **Why LanceDB over Chroma/FAISS?** | Zero-ops embedded database (like SQLite for vectors). In-process, no Docker. MVCC for lock-free concurrent reads/writes. Native FTS + metadata filtering via columnar storage. | [why-lancedb.md](docs/refer/分析/03.为什么选择LanceDB.md) |
| **Why not LangChain/LangGraph?** | Linear CRUD + vector search — a framework adds abstraction without value. MCP is not an Agent framework; BugVault is a tool endpoint, not a reasoning loop. Full control over prompts and error handling. | [why-sdk.md](docs/refer/分析/04.为什么选择SDK.md) |
| **Why fastembed ONNX over OpenAI embeddings?** | Local inference, zero API cost, offline-capable. ONNX runtime is CPU-only and already loaded for reranking — no GPU needed. | — |
| **Why Cross-Encoder over ColBERT?** | ColBERT requires a separate PyTorch index (~1.5GB) + late interaction storage. For 20-candidate reranking, Cross-Encoder ONNX (80MB) is more accurate and zero new deps. | [ADR](docs/refer/设计/adr-cross-encoder-vs-colbert.md) |
| **Why dual fallback on claim_level?** | Small LLMs (e.g. deepseek-v4-flash) frequently produce malformed JSON on complex CoT prompts. Quota + exception double fallback ensures RAG evaluation never crashes the retrieval pipeline. | [v1.1 architecture](docs/refer/设计/04.v1.1-architecture.md#二评估链路策略模式--双重降级) |
| **Why Metadata Pre-filtering before ANN?** | Pure semantic search mixes Python `ModuleNotFoundError` with Java `ClassNotFoundException`. LanceDB's columnar `LOWER(tech_stack) LIKE '%python%'` filter reduces the candidate pool before vector search — negligible cost, eliminates cross-language hallucination. | [v1.1 architecture](docs/refer/设计/04.v1.1-architecture.md#三元数据预过滤) |
| **Why RRF (rank-based) fusion not score-based?** | Vector distance and BM25 score have incommensurable scales — adding them directly is meaningless. RRF uses rank position (k=60), which is scale-agnostic and empirically robust. | [v1.1 architecture](docs/refer/设计/04.v1.1-architecture.md#1.2-rrf-融合) |
| **Why parent-child chunking (v1.1.1)?** | Single-vector-per-record dilutes `error_log_snippet` when `final_solution` is long. Chunking creates 2 focused vectors per record — `error_log` chunk for exact error matching, `semantic` chunk for problem-topic similarity — with chunk-level RRF and parent-document assembly via `parent_id`. | [v1.1.1 redesign](docs/refer/设计/) |
| **Why `ThreadPoolExecutor` for I/O?** | MCP's `asyncio` event loop must never block. LanceDB table operations and embedding inference run in a dedicated thread pool, keeping the event loop responsive for concurrent requests. | — |
| **Why `response_format=json_object`?** | Without it, LLMs wrap JSON in markdown fences causing `JSONDecodeError`. Forced mode + retry-on-error double-locks parse stability. | — |

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
