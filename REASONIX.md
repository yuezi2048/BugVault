# BugVault — working knowledge

## Stack
- **Python ≥3.13** — `hatchling` build backend, `uv` for dependency management (uv.lock).
- **MCP SDK (`mcp >=1.6.0`)** — Model Context Protocol server over stdio transport.
- **LanceDB (`lancedb >=0.20.0`)** — embedded vector DB for experience retrieval.
- **fastembed (`>=0.6.0`)** — local embedding (default model: `BAAI/bge-small-zh-v1.5`, 512d).
- **pydantic + pydantic-settings** — config & models; env prefix `BUGVAULT_`.

## Layout
- `src/bugvault/` — main Python package:
  - `main.py` — entry point; wires config, DB, services, and MCP tools.
  - `config.py` — `pydantic-settings`-based `Settings`.
  - `database/lancedb_client.py` — DAO for all LanceDB table ops.
  - `mcp_tools/tools.py` — tool schemas & registration (MCP tool definitions).
  - `models/` — pydantic models: `BugRecord`, `PreventionRule`, `RAGEvalResult`.
  - `services/` — business logic: `archive_svc`, `embedding_svc`, `ingestion_svc`,
    `rag_evaluator_svc`, `reflection_svc`, `retrieval_svc`.
  - `utils/` — `logger`, `stdout_guard`, `text_utils`.
- `tests/` — pytest test files (colocated under `tests/`, not alongside source).
- `doc/` — design docs and architecture notes (Chinese).
- `reasonix.toml` — Reasonix assistant configuration.

## Commands
- **Run server:** `python -m bugvault.main` (or `bugvault` after pip install).
- **Test:** `pytest` or `uv run pytest` (VSCode auto-config reads
  `python.testing.pytestArgs: ["tests"]`).
- No lint/format scripts defined in `pyproject.toml` — tool not yet configured.

## Conventions
- Every module starts with a **module-level docstring** and `from __future__ import annotations`.
- `__init__.py` files are **bare** — docstring only, no re-exports.
- Tests import from internal paths (`bugvault.models.*`, `bugvault.services.*`),
  not from `__init__` re-exports.
- Private helpers prefixed `_single_underscore`.
- pytest custom markers: `e2e` (marks MCP protocol tests that spawn subprocesses).
- Config values loaded from environment with `BUGVAULT_` prefix via pydantic-settings.

## Watch out for
- **stdout_guard must be first.** `src/bugvault/utils/stdout_guard.py` is imported
  at the very top of `main.py` — before any third-party lib — to protect MCP's
  stdio transport from library output pollution (tqdm, rich, etc.).
- **LanceDB I/O runs in a ThreadPoolExecutor** to keep the MCP event loop
  responsive. Never call blocking DB operations directly in an async handler.
- **Data lives at `~/.bugvault/`** by default (LanceDB tables + markdown archive).
  Not in VCS, not in the repo. Adjust via `BUGVAULT_DATA_ROOT`.
