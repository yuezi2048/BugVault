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


# Minimum semantic score threshold — documents below this are discarded
# as irrelevant ("宁缺毋滥").  0.55 corresponds to an ANN distance of ~0.90.
MIN_SEMANTIC_SCORE = 0.55


def rerank(
    results: list[dict],
    query_embedding: list[float] | None = None,
) -> list[dict]:
    """Apply hybrid reranking: semantic similarity × recency decay.

    Documents whose semantic similarity falls below ``MIN_SEMANTIC_SCORE``
    (0.55 by default) are discarded before scoring — "宁缺毋滥".
    """
    scored: list[tuple[float, dict]] = []

    for row in results:
        recency = time_decay_score(row.get("create_time", ""))
        # `_distance` is the ANN distance from LanceDB (lower = more similar)
        # Convert to a similarity score in [0, 1]
        semantic = 1.0 - row.get("_distance", 0.0) / 2.0
        semantic = max(0.0, min(1.0, semantic))

        # ── Relevance floor: discard documents that are too far ──
        if semantic < MIN_SEMANTIC_SCORE:
            continue

        combined = (
            settings.semantic_weight * semantic
            + settings.recency_weight * recency
        )
        scored.append((combined, row))

    # Sort descending by combined score
    scored.sort(key=lambda x: x[0], reverse=True)

    # Dedup by record_id — O(N) set filter as safety net against
    # any duplicate entries that survived the LanceDB upsert.
    seen: set[str] = set()
    deduped: list[dict] = []
    for row in (r for _, r in scored):
        rid = row.get("record_id", "") or ""
        if rid in seen:
            continue
        seen.add(rid)
        deduped.append(row)

    return deduped
