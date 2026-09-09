"""Deep retrieval module for BugVault's local memory."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Literal, TypeAlias

from bugvault.config import settings
from bugvault.models.bug_record import BugRecord
from bugvault.models.convention_record import ConventionRecord
from bugvault.utils.logger import logger


Record: TypeAlias = BugRecord | ConventionRecord


@dataclass(frozen=True, slots=True)
class RetrievalRequest:
    """Domain input for a Bug Record or Convention Record retrieval."""

    query: str
    target_tech_stack: str = ""
    target_project_name: str = ""
    record_type: Literal["bug", "convention"] = "bug"


@dataclass(slots=True)
class RetrievalResult:
    """Ranked records and execution metadata owned by the retrieval module."""

    records: list[Record] = field(default_factory=list)
    vector_count: int = 0
    fts_count: int = 0
    used_cross_encoder: bool = False
    had_candidates: bool = False
    error_message: str | None = None

    @property
    def strategy(self) -> str:
        if self.used_cross_encoder:
            return "hybrid + Cross-Encoder reranking"
        if self.fts_count:
            return "hybrid (vector + FTS + RRF fusion)"
        return "vector-only"


class RetrievalModule:
    """Own the complete local-memory retrieval implementation.

    The module accepts one domain request and returns ranked records plus the
    metadata needed by an adapter to present them. MCP transports results as
    text, while other adapters can consume the records directly.
    """

    def __init__(
        self,
        db: Any,
        embedding_svc: Any | None = None,
        reranker_factory: Callable[[], Any | None] | None = None,
    ) -> None:
        self._db = db
        self._embedding_svc = embedding_svc
        self._reranker_factory = reranker_factory

    def retrieve(self, request: RetrievalRequest) -> RetrievalResult:
        """Collect, map, rank, and optionally refine matching records."""
        if not request.query.strip():
            return RetrievalResult(
                error_message="Query is empty. Please provide an error description.",
            )
        if not self._db.is_ready:
            return RetrievalResult(
                error_message="BugVault is still initialising. Please try again in a moment.",
            )

        embedding_svc = self._embedding_svc or self._create_embedding_svc()
        rerank_limit = settings.top_k * 4
        filter_clause = _record_type_filter(
            build_filter_clause(
                request.target_tech_stack,
                request.target_project_name,
            ),
            request.record_type,
        )
        query_embedding = embedding_svc.generate_embedding(request.query)
        records, vector_count, fts_count = self._collect_records(
            request.query,
            query_embedding,
            filter_clause,
            rerank_limit,
        )
        if not records:
            return RetrievalResult(
                vector_count=vector_count,
                fts_count=fts_count,
            )

        ranked = rerank(records)
        used_cross_encoder = False
        if settings.enable_reranker and ranked:
            try:
                reranker = self._get_reranker()
                if reranker is not None:
                    ranked = reranker.rerank(request.query, ranked)
                    used_cross_encoder = True
                    logger.info("Cross-Encoder reranked %d candidates", len(ranked))
            except Exception:
                logger.warning("Cross-Encoder reranking failed — using RRF order")

        return RetrievalResult(
            records=self._to_records(ranked[:settings.top_k], request.record_type),
            vector_count=vector_count,
            fts_count=fts_count,
            used_cross_encoder=used_cross_encoder,
            had_candidates=True,
        )

    def _to_records(
        self,
        rows: list[dict],
        record_type: Literal["bug", "convention"],
    ) -> list[Record]:
        """Hide shared-table aliases after ranking has completed."""
        factory = (
            ConventionRecord.from_table_row
            if record_type == "convention"
            else BugRecord.from_table_row
        )
        records: list[Record] = []
        for row in rows:
            if row.get("record_type", "bug") != record_type:
                logger.warning("Skipping mismatched %s retrieval row", record_type)
                continue
            try:
                records.append(factory(row))
            except Exception:
                logger.exception("Cannot map retrieved %s row to a domain record", record_type)
        return records

    def _collect_records(
        self,
        query: str,
        query_embedding: list[float],
        filter_clause: str,
        limit: int,
    ) -> tuple[list[dict], int, int]:
        """Use chunk recall first, then retain the parent-table fallback."""
        vector_chunks = self._db.search_chunks(
            query_embedding,
            filter_clause=filter_clause,
            limit=limit,
        )
        fts_chunks = self._search_chunk_fts(query, filter_clause, limit)
        chunk_results = rrf_fusion(vector_chunks, fts_chunks) if fts_chunks else vector_chunks

        if not chunk_results:
            return self._search_parent_fts(query, filter_clause, limit)

        records = self._map_chunks_to_parent_records(chunk_results)
        if not records:
            logger.info("Chunks found but no matching parent records in bug_records")
        return records, len(vector_chunks), len(fts_chunks)

    def _search_chunk_fts(
        self,
        query: str,
        filter_clause: str,
        limit: int,
    ) -> list[dict]:
        if not settings.enable_fts:
            return []
        try:
            results = self._db.search_chunks_fts(
                query,
                filter_clause=filter_clause,
                limit=limit,
            )
            return [row for row in results if row.get("_score", 0) > 0]
        except Exception:
            logger.warning("Chunks FTS search failed, falling back to vector-only")
            return []

    def _search_parent_fts(
        self,
        query: str,
        filter_clause: str,
        limit: int,
    ) -> tuple[list[dict], int, int]:
        if not settings.enable_fts:
            return [], 0, 0
        try:
            results = self._db.search_fts(
                query,
                filter_clause=filter_clause,
                limit=limit,
            )
            results = [row for row in results if row.get("_score", 0) > 0]
            return rrf_fusion([], results) if results else [], 0, len(results)
        except Exception:
            logger.warning("FTS search failed, falling back to vector-only")
            return [], 0, 0

    def _map_chunks_to_parent_records(self, chunk_results: list[dict]) -> list[dict]:
        """Keep the best chunk per parent and restore full parent records."""
        parent_best: dict[str, dict] = {}
        for chunk in chunk_results:
            parent_id = chunk.get("parent_id", "") or ""
            if not parent_id:
                continue
            if (
                parent_id not in parent_best
                or _chunk_score(chunk) < _chunk_score(parent_best[parent_id])
            ):
                parent_best[parent_id] = chunk

        parent_records = self._db.fetch_records_by_ids(list(parent_best))
        record_map = {
            record_id: record
            for record in parent_records
            if (record_id := record.get("record_id", "") or "")
        }
        records: list[dict] = []
        for parent_id, best_chunk in parent_best.items():
            parent_record = record_map.get(parent_id)
            if parent_record is None:
                continue
            merged = dict(parent_record)
            for key in ("_distance", "_rrf_score"):
                if key in best_chunk:
                    merged[key] = best_chunk[key]
            records.append(merged)
        return records

    def _create_embedding_svc(self) -> Any:
        from bugvault.services.embedding_svc import EmbeddingService

        return EmbeddingService()

    def _get_reranker(self) -> Any | None:
        if self._reranker_factory is not None:
            return self._reranker_factory()
        from bugvault.services.reranker_svc import get_reranker

        return get_reranker()


_TECH_EXCLUSIONS: dict[str, list[str]] = {
    "java": ["javascript"],
}


def sanitise_filter_value(raw: str) -> str:
    """Retain only the filter characters supported by LanceDB clauses."""
    import re

    return re.sub(r"[^a-zA-Z0-9_\-\s. ]", "", raw.strip())


def build_filter_clause(
    target_tech_stack: str,
    target_project_name: str,
) -> str | None:
    """Build a metadata clause while preserving Java/JavaScript exclusion."""
    clauses: list[str] = []
    if target_tech_stack:
        value = sanitise_filter_value(target_tech_stack)
        if value:
            normalized = value.lower()
            clauses.append(f"LOWER(tech_stack) LIKE '%{normalized}%'")
            for excluded in _TECH_EXCLUSIONS.get(normalized, []):
                clauses.append(f"LOWER(tech_stack) NOT LIKE '%{excluded}%'")
    if target_project_name:
        value = sanitise_filter_value(target_project_name)
        if value:
            clauses.append(f"LOWER(project_name) LIKE '%{value.lower()}%'")
    return " AND ".join(clauses) if clauses else None


def _record_type_filter(filter_clause: str | None, record_type: str) -> str:
    type_filter = f"record_type = '{record_type}'"
    return f"({filter_clause}) AND {type_filter}" if filter_clause else type_filter


def _chunk_score(chunk: dict) -> float:
    if "_distance" in chunk:
        return chunk["_distance"]
    return -chunk.get("_rrf_score", 0.0)


def time_decay_score(create_time_str: str, half_life_days: int | None = None) -> float:
    """Compute a recency score in [0, 1] using exponential decay.

    A record created *now* gets score 1.0. After `half_life_days` it
    decays to 0.5.  The curve asymptotically approaches 0.
    """
    if half_life_days is None:
        half_life_days = settings.recency_half_life_days

    if not create_time_str:
        return 0.5  # neutral default for records without timestamps

    try:
        created = datetime.fromisoformat(create_time_str)
    except (ValueError, TypeError):
        return 0.5

    now = datetime.now(timezone.utc)
    # naive → assume UTC
    if created.tzinfo is None:
        created = created.replace(tzinfo=timezone.utc)

    elapsed_days = (now - created).total_seconds() / 86400.0
    if elapsed_days <= 0:
        return 1.0

    # Exponential decay: score = 2^(-elapsed/half_life)
    return 2.0 ** (-elapsed_days / half_life_days)


# ═══════════════════════════════════════════════════════════════════
#  RRF (Reciprocal Rank Fusion)
# ═══════════════════════════════════════════════════════════════════


def rrf_fusion(
    vec_results: list[dict],
    fts_results: list[dict],
    k: int = 60,
) -> list[dict]:
    """Fuse two ranked result lists via Reciprocal Rank Fusion.

    Each result in the fused output gains a ``_rrf_score`` field.

    Args:
        vec_results: Results from vector ANN search (ordered by _distance).
        fts_results: Results from FTS search (ordered by _score).
        k: RRF smoothing constant (default 60, per industry standard).

    Returns:
        Deduplicated list of dicts sorted by RRF score descending.
    """
    from collections import OrderedDict

    scores: dict[str, float] = {}
    docs: dict[str, dict] = {}
    seen_id: int = 0

    def _key(row: dict) -> str:
        nonlocal seen_id
        rid = row.get("record_id", "") or ""
        if not rid:
            seen_id += 1
            return f"_anon_{seen_id}"
        return rid

    # Vector results (ranked by _distance ascending)
    for rank, row in enumerate(vec_results, 1):
        key = _key(row)
        scores[key] = scores.get(key, 0.0) + 1.0 / (k + rank)
        docs[key] = row

    # FTS results (ranked by _score descending)
    for rank, row in enumerate(fts_results, 1):
        key = _key(row)
        scores[key] = scores.get(key, 0.0) + 1.0 / (k + rank)
        docs[key] = row  # FTS doc replaces vec doc if same key (they're identical records)

    # Sort by combined RRF score descending
    ranked = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)

    result: list[dict] = []
    seen_dedup: set[str] = set()
    for key, rrf_score in ranked:
        if key in seen_dedup:
            continue
        seen_dedup.add(key)
        doc = docs[key]
        doc = dict(doc)  # shallow copy so we don't mutate the original
        doc["_rrf_score"] = rrf_score
        result.append(doc)

    return result


# ═══════════════════════════════════════════════════════════════════
#  Rerank
# ═══════════════════════════════════════════════════════════════════


def rerank(
    results: list[dict],
    query_embedding: list[float] | None = None,
) -> list[dict]:
    """Rerank results: vector semantic + time decay, or RRF score + time decay.

    For pure vector results (``_distance`` present):
        - Compute ``semantic = 1 - _distance/2``
        - Discard rows below ``min_semantic_score``
        - Combine with recency decay

    For RRF-fused results (``_rrf_score`` present):
        - Use RRF score as base
        - Apply time decay as secondary signal
        - Semantic threshold already applied at the vector phase

    For rows that have neither (fallback), sort by recency only.
    """
    scored: list[tuple[float, dict]] = []

    for row in results:
        has_distance = "_distance" in row and row["_distance"] is not None
        has_rrf = "_rrf_score" in row and row["_rrf_score"] is not None

        if has_distance:
            # Pure vector path
            semantic = 1.0 - row["_distance"] / 2.0
            semantic = max(0.0, min(1.0, semantic))
            if semantic < settings.min_semantic_score:
                continue
            base_score = semantic
        elif has_rrf:
            # Hybrid RRF path — semantic threshold already applied in vector phase
            base_score = row["_rrf_score"]
        else:
            # Fallback: use recency only
            base_score = 0.5

        recency = time_decay_score(row.get("create_time", ""))
        if settings.enable_recency_decay:
            combined = (
                (1 - settings.recency_weight) * base_score
                + settings.recency_weight * recency
            )
        else:
            combined = base_score
        scored.append((combined, row))

    # Sort descending by combined score
    scored.sort(key=lambda x: x[0], reverse=True)

    # Dedup by record_id
    seen: set[str] = set()
    deduped: list[dict] = []
    for row in (r for _, r in scored):
        rid = row.get("record_id", "") or ""
        if rid and rid in seen:
            continue
        if rid:
            seen.add(rid)
        deduped.append(row)

    return deduped
