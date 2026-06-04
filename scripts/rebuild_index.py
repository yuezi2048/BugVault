#!/usr/bin/env python3
"""Clear LanceDB and rebuild index from the Markdown archive.

Usage
-----
    uv run python scripts/rebuild_index.py
    uv run python scripts/rebuild_index.py --path ~/custom/archive --workers 4

Environment
-----------
All ``BUGVAULT_*`` env vars are honoured (data_root, embedding model, etc.).
"""

from __future__ import annotations

import argparse
import sys
import time

# ── Must import stdout_guard BEFORE any other project imports ────
from bugvault.utils.stdout_guard import _MCPStdoutProxy  # noqa: F401

from bugvault.config import settings
from bugvault.database.lancedb_client import LanceDBClient
from bugvault.services.db_maintenance_svc import (
    clear_database,
    import_from_archive,
)
from bugvault.services.embedding_svc import EmbeddingService
from bugvault.utils.logger import logger


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Clear + rebuild BugVault LanceDB index from archive",
    )
    parser.add_argument(
        "--path",
        default=None,
        help="Archive directory (default: BUGVAULT_DATA_ROOT/archive)",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=8,
        help="Thread count for concurrent parsing + embedding (default: 8)",
    )
    parser.add_argument(
        "--skip-clear",
        action="store_true",
        help="Skip the clear step (only import, useful for incremental adds)",
    )
    args = parser.parse_args()

    archive_path = args.path or settings.markdown_archive_dir

    print("=" * 60)
    print("  BugVault — Index Rebuild")
    print("=" * 60)
    print(f"  Archive:    {archive_path}")
    print(f"  LanceDB:    {settings.db_uri}")
    print(f"  Embedding:  {settings.embedding_model}")
    print(f"  Workers:    {args.workers}")
    print()

    # ── Init ───────────────────────────────────────────────────────
    t_start = time.perf_counter()

    print("  ⏳ Initialising LanceDB client …")
    client = LanceDBClient()
    client.initialize()

    print("  ⏳ Loading embedding model …")
    embedding_svc = EmbeddingService()

    # ── Clear ──────────────────────────────────────────────────────
    if not args.skip_clear:
        print("  🗑️  Clearing database …")
        clear_database(client)
    else:
        print("  ⏭️  Skipping clear (--skip-clear)")

    # ── Import ─────────────────────────────────────────────────────
    print("  🔍 Scanning markdown files …\n")
    result = import_from_archive(
        client,
        embedding_svc,
        archive_path,
        max_workers=args.workers,
    )

    # ── Summary ────────────────────────────────────────────────────
    t_elapsed = time.perf_counter() - t_start
    print()
    print(f"  {'─' * 56}")
    print(f"  ✅ Rebuild complete")
    print(f"     Total files:     {result['total']}")
    print(f"     Succeeded:       {result['succeeded']}")
    print(f"     Failed:          {result['failed']}")
    print(f"     Import time:     {result['elapsed_sec']:.1f}s")
    print(f"     Total time:      {t_elapsed:.1f}s")
    print(f"  {'─' * 56}")

    if result["failed"] > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
