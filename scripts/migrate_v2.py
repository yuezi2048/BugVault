#!/usr/bin/env python
"""Migrate existing BugVault v1.1.1 database to v2.0.0 schema.

Adds the ``record_type`` discriminator column to both ``bug_records``
and ``bugvault_chunks`` tables.  Existing rows are tagged ``'bug'``;
new v2.0.0 convention records will carry ``'convention'``.

Safe to run multiple times — missing columns are added once, existing
columns are left untouched.

Usage
-----
    uv run python scripts/migrate_v2.py                  # default data root
    BUGVAULT_DATA_ROOT=/custom/path uv run python scripts/migrate_v2.py
"""

from __future__ import annotations

import sys
from pathlib import Path

# Ensure the package is importable (works with `uv run` or `pip install -e .`)
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from bugvault.config import settings
from bugvault.database.lancedb_client import LanceDBClient
from bugvault.utils.logger import logger


def main() -> None:
    print(f"BugVault v2.0 schema migration")
    print(f"Data root: {settings.data_root}")
    print(f"Database:  {settings.db_uri}")
    print()

    client = LanceDBClient()
    client.initialize()

    # ── bug_records ────────────────────────────────────────────────
    tbl = client._table
    fields = [f.name for f in tbl.schema]
    if "record_type" in fields:
        print(f"  [OK]  bug_records: record_type already present")
    else:
        print(f"  [MIG] bug_records: adding record_type='bug' ...")
        client._migrate_v2_schema_if_needed(tbl, "bug_records")
        print(f"  [OK]  bug_records: migrated")

    # ── bugvault_chunks ────────────────────────────────────────────
    chunks = client._chunks_table
    chunk_fields = [f.name for f in chunks.schema]
    if "record_type" in chunk_fields:
        print(f"  [OK]  bugvault_chunks: record_type already present")
    else:
        print(f"  [MIG] bugvault_chunks: adding record_type='bug' ...")
        client._migrate_v2_schema_if_needed(chunks, "bugvault_chunks")
        print(f"  [OK]  bugvault_chunks: migrated")

    # ── Summary ────────────────────────────────────────────────────
    print()
    df = tbl.to_pandas()
    bug_count = len(df[df["record_type"] == "bug"])
    print(f"Summary: {len(df)} records in bug_records ({bug_count} x 'bug')")

    cd = chunks.to_pandas()
    chunk_bug = len(cd[cd["record_type"] == "bug"])
    print(f"Summary: {len(cd)} chunks in bugvault_chunks ({chunk_bug} x 'bug')")
    print()
    print("Migration complete.")


if __name__ == "__main__":
    main()
