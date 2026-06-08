"""Global configuration — loaded from environment / .env at startup."""

from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="BUGVAULT_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # ── Data paths ──────────────────────────────────────────────────
    data_root: Path = Path.home() / ".bugvault"
    db_uri: str = ""  # auto-derived from data_root unless overridden
    markdown_archive_dir: str = ""  # auto-derived from data_root unless overridden

    # ── Embedding ───────────────────────────────────────────────────
    embedding_model: str = "BAAI/bge-small-zh-v1.5"
    embedding_dim: int = 512  # bge-small-zh-v1.5 dimension

    # ── Retrieval ───────────────────────────────────────────────────
    top_k: int = 5
    min_semantic_score: float = 0.50  # ANN relevance floor — docs below this are discarded
    enable_recency_decay: bool = False  # off by default — old bugs may still be valuable
    recency_weight: float = 0.3  # only used when enable_recency_decay is True
    semantic_weight: float = 0.7  # only used when enable_recency_decay is True
    recency_half_life_days: int = 90  # weight halves after N days

    # ── Truncation ──────────────────────────────────────────────────
    max_record_chars: int = 4000  # per-record truncation limit
    truncation_level: int = 1  # 1=default, 2=detailed, 3=raw

    # ── Concurrency ─────────────────────────────────────────────────
    thread_pool_workers: int = 2  # max threads for LanceDB I/O

    # ── MCP ─────────────────────────────────────────────────────────
    server_name: str = "bugvault"
    server_version: str = "2.0.0"

    # ── Async persistence ───────────────────────────────────────────
    enable_async_embedding: bool = True  # background embedding + LanceDB

    # ── RAG Evaluation (optional external judge LLM) ────────────────
    enable_rag_eval: bool = False
    eval_llm_api_key: str = ""
    eval_llm_model: str = "gpt-4o-mini"
    eval_llm_base_url: str = ""  # defaults to OpenAI
    eval_top_k: int = 3  # evaluate top N retrieved records

    # ── Full-Text Search (Tantivy) ───────────────────────────────────
    enable_fts: bool = True  # vector + FTS dual recall with RRF fusion

    # ── Cross-Encoder Reranker ─────────────────────────────────────
    enable_reranker: bool = True  # False → pure RRF, no cross-encoder
    reranker_model: str = "jinaai/jina-reranker-v2-base-multilingual"  # 1.1GB, multilingual

    # ── Claim-Level Eval Circuit Breaker ────────────────────────────
    max_claim_evals_per_session: int = 10  # session-wide cap for claim_level

    # ── Reflection Tool ─────────────────────────────────────────────
    enable_reflection_tool: bool = True

    def model_post_init(self, _ctx) -> None:
        # ── Resolve ~ and symlinks BEFORE any use ─────────────────
        self.data_root = self.data_root.expanduser().resolve()
        if not self.db_uri:
            self.db_uri = str(self.data_root / "lancedb")
        if not self.markdown_archive_dir:
            self.markdown_archive_dir = str(self.data_root / "archive")
        # Ensure data dirs exist at config time
        self.data_root.mkdir(parents=True, exist_ok=True)
        Path(self.markdown_archive_dir).expanduser().resolve().mkdir(parents=True, exist_ok=True)


settings = Settings()
