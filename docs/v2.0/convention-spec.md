# Convention Memory — Specification

> v2.0.0 feature: "Project convention memory" for BugVault.
> Extends the retrieval‑and‑persist pattern from code bugs to business rules,
> architecture conventions, test conventions, and style guides.

---

## Table of Contents

- [1. ConventionRecord Model](#1-conventionrecord-model)
- [2. MCP Tools](#2-mcp-tools)
- [3. Storage Architecture](#3-storage-architecture)
- [4. Retrieval Pipeline](#4-retrieval-pipeline)
- [5. Schema Migration](#5-schema-migration)
- [6. End-to-End Flow](#6-end-to-end-flow)
- [7. Design Decisions](#7-design-decisions)

---

## 1. ConventionRecord Model

### Definition

```python
class ConventionRecord(BaseModel):
    # ── Mandatory (4 fields) ──
    convention_name: str         # Short rule name (1-256 chars)
    trigger_context: str         # When/where this convention applies (1-32768 chars)
    incorrect_behavior: str      # What the AI should NOT do (1-8192 chars)
    correct_behavior: str        # What the AI SHOULD do (1-16384 chars)

    # ── Optional / async-enriched ──
    scope: str | None            # Scope of applicability (e.g. "src/api/")
    tags: str | None             # Categorisation tags (e.g. "Python, FastAPI, API 规范")

    # ── System-managed ──
    record_id: str | None        # MD5(convention_name + trigger_context) — dedup key
    create_time: str             # ISO-8601 UTC timestamp
    record_type: str = "convention"  # Discriminator — always "convention"
```

### Dedup Key

```python
# MD5(convention_name + trigger_context)
# Same name + context = same record_id → upsert updates existing record
@model_validator(mode="after")
def _compute_record_id(self):
    raw = (self.convention_name + self.trigger_context).encode("utf-8")
    self.record_id = hashlib.md5(raw).hexdigest()
```

### Field Mapping (Convention → bug_records table)

| Convention Field | Table Column | Reason |
|-----------------|-------------|--------|
| `convention_name` | `bug_title` | Reuses the title field |
| `trigger_context` | `error_log_snippet` | Both are "context about the problem" |
| `incorrect_behavior` | `tried_methods` | Both are "what went wrong" |
| `correct_behavior` | `final_solution` | Both are "how to make it right" |
| `scope` | `project_name` | Reuses the project-name filter |
| `tags` | `tech_stack` | Reuses the tech-stack filter |
| *(N/A)* | `root_cause` | Empty string (not applicable to conventions) |
| `record_type` | `record_type` | Discriminator: `'convention'` vs `'bug'` |

### Chunking Strategy

Each convention generates **2 chunks**:

| Chunk | Content | Purpose |
|-------|---------|---------|
| `context` | `convention_name + trigger_context` | Matches the "when" part |
| `correct_behavior` | `convention_name + incorrect_behavior + correct_behavior` | Matches the "what to do" part |

If `correct_behavior` exceeds 800 chars, it is auto-split at paragraph boundaries.

---

## 2. MCP Tools

### `save_convention`

Save a project convention after user correction.

**Request:**
```json
{
  "convention_name": "API 响应统一格式",
  "trigger_context": "在编写 REST API 端点时",
  "incorrect_behavior": "直接返回原始 dict 或随意格式",
  "correct_behavior": "统一使用 {\"code\": 0, \"data\": ..., \"message\": \"ok\"} 格式",
  "scope": "src/api/",
  "tags": "Python, FastAPI, API 规范"
}
```

**Execution (synchronous):**
1. Pydantic validation → `ConventionRecord(**arguments)`
2. Check missing mandatory fields
3. Write Markdown archive to `~/.bugvault/archive/conventions/{timestamp}_{name}.md`

**Execution (background, fire-and-forget):**
4. Compute `search_text = to_search_text()`
5. Generate ONNX embedding (512d)
6. Upsert parent record to `bug_records` with `record_type='convention'`
7. Generate chunk embeddings and upsert to `bugvault_chunks`

**Returns:**
```
Convention '{name}' saved successfully. I will remember this rule for future sessions.
```

### `retrieve_convention`

Proactively query project conventions before making code changes.

**Request:**
```json
{
  "query": "API 响应格式应该是什么",
  "target_scope": "src/api/",
  "target_tags": "Python, FastAPI"
}
```

**Pipeline:**
1. Embed query using same embedding model (512d)
2. **Vector ANN** on `bugvault_chunks` with `filter_clause="record_type='convention'"`
   → return top-k×4 results
3. **FTS BM25** on `bugvault_chunks.search_text` with same filter
   → return top-k×4 results
4. **RRF fusion** (k=60) — combine rank positions from vector + FTS
5. Dedup by `parent_id` — batch-fetch full parent records from `bug_records`
6. **Cross-Encoder reranking** — reorder by `_ce_score`
7. Truncate to `settings.top_k`

**Returns:**
```
--- Retrieval Info ---
Strategy: hybrid + Cross-Encoder reranking
Sources:  3 vector + 2 FTS

--- Result 1 ---
Title:    API 响应统一格式
Scope:    src/api/
Time:     2026-06-08T07:14:38+00:00
Context:
在编写 REST API 端点时
Incorrect:
直接返回原始 dict 或随意格式
Correct:
统一使用 {"code": 0, "data": ..., "message": "ok"} 格式
```

---

## 3. Storage Architecture

### Shared Tables with Discriminator

```
bug_records (parent table)
├── record_id          : str (MD5, PK)
├── bug_title          : str   ← convention_name for conventions
├── error_log_snippet  : str   ← trigger_context for conventions
├── tried_methods      : str   ← incorrect_behavior for conventions
├── final_solution     : str   ← correct_behavior for conventions
├── project_name       : str   ← scope for conventions
├── tech_stack         : str   ← tags for conventions
├── root_cause         : str
├── create_time        : str
├── search_text        : str   (concatenated for embedding)
├── vector             : list[float] (512d)
└── record_type        : str   ← 'bug' | 'convention'  ← v2.0 NEW

bugvault_chunks (chunks table)
├── chunk_id           : str (MD5, PK)
├── parent_id          : str   → FK to bug_records.record_id
├── chunk_type         : str   ← 'context' | 'correct_behavior' | 'error_log' | 'semantic'
├── search_text        : str
├── tech_stack         : str
├── project_name       : str
├── vector             : list[float] (512d)
└── record_type        : str   ← 'bug' | 'convention'  ← v2.0 NEW
```

### Archive Directory Structure

```
~/.bugvault/
├── lancedb/                     # LanceDB database directory
│   ├── bug_records.lance/       # Parent table
│   └── bugvault_chunks.lance/   # Chunks table
├── archive/
│   ├── 20260529_123026_some_bug.md    # Bug experience archives
│   ├── ...
│   └── conventions/                   # Convention archives (v2.0)
│       ├── 20260608_070636_Python_测试文件命名规范.md
│       └── 20260608_071438_API_响应统一格式.md
└── log/
    └── bugvault.log
```

---

## 4. Retrieval Pipeline

Same funnel architecture as v1.1.1 bug retrieval:

```
query
  ├──→ [chunks] Vector ANN  (top_k×4) ───┐
  │     WHERE record_type='convention'    │
  ├──→ [chunks] FTS BM25   (top_k×4) ────┤
  │     WHERE record_type='convention'    │
  │                                      │
  ├── Chunk-level RRF Fusion (k=60) ─────┤
  ├── Parent dedup (by parent_id) ───────┤
  ├── fetch_records_by_ids(parent_ids) ──┘
  │
  ├── Cross-Encoder rerank (optional)
  └── Truncate → top_k (default 5)
```

### Filter Safety

If the `record_type` filter column doesn't exist (pre-migration), the search method gracefully retries without the filter and logs a warning:

```python
except Exception as exc:
    if filter_clause and "No field named" in err_str:
        logger.warning("Filter column missing, retrying without filter")
        query = table.search(embedding)
        return query.limit(limit).to_list()
```

---

## 5. Schema Migration

### Automatic (at server startup)

```python
# src/bugvault/database/lancedb_client.py
@staticmethod
def _migrate_v2_schema_if_needed(table, table_name: str) -> None:
    field_names = [f.name for f in table.schema]
    if "record_type" in field_names:
        return  # already migrated

    logger.info("Schema migration: adding record_type column to %s", table_name)
    table.add_columns({"record_type": "'bug'"})
    logger.info("Applied record_type='bug' to %d rows", table.count_rows())
```

Called from both `_init_table()` and `_init_chunks_table()` after opening existing tables.

### Standalone (manual)

```bash
uv run python scripts/migrate_v2.py
```

### What It Does

1. Adds `record_type: utf8` column to `bug_records` table
2. Adds `record_type: utf8` column to `bugvault_chunks` table
3. Sets `record_type='bug'` for all existing rows (both tables)
4. New convention records carry `record_type='convention'`

### Verification

```python
df = client._table.to_pandas()
df['record_type'].value_counts()
# bug: 2114, convention: 1  (after adding one convention)
```

---

## 6. End-to-End Flow

```
User: "注意！API 返回必须用统一格式"
  │
  ▼
AI calls save_convention(convention_name="API 响应统一格式", ...)
  │
  ├──→ [sync] Markdown archive written
  └──→ [async] Embedded + upserted to LanceDB (record_type='convention')
  │
  ▼
  "Convention saved successfully."
  │
  ▼
[Later] User: "帮我加一个用户列表 API"
  │
  ▼
AI calls retrieve_convention(query="API 端点格式", target_scope="src/api/")
  │
  ├──→ Vector ANN (filtered to 'convention') → 2 chunk hits
  ├──→ FTS BM25 (filtered to 'convention') → 1 chunk hit
  ├──→ RRF fusion → dedup by parent_id
  ├──→ fetch parent records → full convention metadata
  └──→ Cross-Encoder rerank → #1 result: API 响应统一格式
  │
  ▼
AI writes code following the correct_behavior:
  return {"code": 0, "data": users, "message": "ok"}
```

---

## 7. Design Decisions

### Why share the same table as BugRecord?

- **Same retrieval pipeline**: Both benefit from vector ANN + FTS + RRF + Cross-Encoder
- **Single code path**: No need to maintain separate search logic
- **Low migration cost**: Only need to add `record_type` column

### Why `record_type` discriminator instead of separate tables?

- **Query simplicity**: A single `WHERE record_type='convention'` filter is cheaper than cross-table JOINs
- **Historical data reuse**: Conventions can be surfaced alongside bug fixes when relevant
- **Future extensibility**: Adding a 3rd type (e.g. `tip`) doesn't require a new table

### Why Markdown archive for conventions?

- **Human-readable backup**: Same pattern as bug archives
- **Git-trackable**: Can be committed to a docs/ directory
- **Restorable**: Archive → rebuild pipeline works for conventions too

### Why 4 mandatory fields?

The minimum viable convention needs to answer:
- **What is the rule?** (`convention_name`)
- **When does it apply?** (`trigger_context`)
- **What's the violation?** (`incorrect_behavior`)
- **What's the fix?** (`correct_behavior`)

With these 4 fields, the convention is immediately useful for future retrieval. Additional fields (scope, tags) can be enriched later.
