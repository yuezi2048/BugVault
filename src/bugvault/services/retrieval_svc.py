"""Retrieval service — embedding-based ANN search with time-decay reranking."""

from __future__ import annotations

from datetime import datetime, timezone

from bugvault.config import settings


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
