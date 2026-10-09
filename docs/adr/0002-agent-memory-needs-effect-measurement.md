# Reopen BugVault only for effect measurement

**Status:** accepted

ADR-0001 froze BugVault as an independent product. This ADR records the single condition under which it may be reopened: a measurable effect on agent behaviour, not a better memory store.

## Context

The memory and retrieval layer is commoditised. General memory components (mem0), context platforms (OpenViking), and in-process retrieval engines (zvec) already cover storage, retrieval, scope, and lifecycle. Adding another store cannot differentiate BugVault, and small or manually curated knowledge bases are well served by Markdown/Git plus `grep`.

## Decision

Do not add retrieval, graph, or automation features. Reopen the product question only if a project-local, before/after experiment shows that structured experience — especially recorded failed attempts — measurably reduces repeated mistakes.

## Consequences

- The measurable claim is a reduction in repeated mistakes (repeat-mistake rate), not retrieval metrics alone.
- Retrieval-quality metrics (e.g. Recall@5) are necessary but not sufficient evidence of value.
- Until such an experiment exists, the repository stays a case study rather than a roadmap.
- See [ADR-0001](0001-stop-bugvault-product-validation.md) for the stop decision and [the landscape note](../research/zvec-openviking-reading-and-direction.md) for the capability survey.
