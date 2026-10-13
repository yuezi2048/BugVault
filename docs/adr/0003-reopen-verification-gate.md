# Reopen BugVault for the verification-gate slice

**Status:** accepted — supersedes [ADR-0001](0001-stop-bugvault-product-validation.md) in part

ADR-0001 stopped BugVault as an independent product and froze feature expansion. This ADR reopens a deliberately narrow, exploratory next phase: making recorded engineering experience *credible* — a verification gate, a record-status lifecycle, and same-project recurrence detection. See `CONTEXT.md` for the glossary terms.

## Context

ADR-0001 concluded that general-purpose memory components (mem0), filesystem-style context platforms (OpenViking), and in-process retrieval engines (zvec) already cover storage, retrieval, scope, and lifecycle. ADR-0002 then fixed the only condition for reopening: a measurable effect on agent behaviour, not a better memory store.

A survey of four coding-agent memory projects — nova, claude-mem, ECC (everything-claude-code), and mem0 — in [the competitive landscape note](../research/competitive-landscape.md) found that all four cover capture and cross-session recall, but none of them:

- gate promotion to a "verified" state on executable evidence,
- model a record status lifecycle (suspected / verified / invalidated), or
- detect the same failure recurring within one project.

The survey marks these as the unoccupied positions. Two adjacent positions exist but are different: ECC's `hookify-rules` blocks dangerous tool actions, and `skill-comply` measures rule compliance; neither answers "has this fix been verified?".

That slice is narrow enough to be worth one exploratory attempt, so ADR-0001's blanket freeze is lifted for this slice only.

## Decision

Reopen BugVault as an **exploratory next phase** limited to the "engineering-experience credibility" vertical slice:

- **Verification gate** — a Bug Record or Convention Record cannot reach the `verified` status without attached Verification evidence.
- **Record status** — an explicit lifecycle state (`suspected` / `verified` / `invalidated`) with defined transitions.
- **Same-project recurrence detection** — detect and surface the same failure recurring within one project.

The phase is exploratory, not a commitment to ship. It must be falsified or confirmed by the before/after measurement ADR-0002 already requires.

## Scope boundary

**In scope**

- The verification-gate, status-lifecycle, and recurrence-detection behaviours above.
- The minimum record/schema changes needed to express status and evidence.
- A before/after experiment that measures repeat-mistake rate.

**Out of scope (ADR-0001's freeze remains in force)**

- General-purpose memory, the general-purpose memory lifecycle, or new memory components.
- The retrieval kernel: hybrid retrieval, ranking, Cross-Encoder refinement.
- Provider abstraction or additional storage/graph backends.
- Automatic capture triggers and mandatory retrieval.
- Any claim that this slice is a differentiated product.

## Relationship to ADR-0001

This ADR **supersedes ADR-0001 in part**: only the "freeze feature expansion / no product roadmap" clause is lifted, and only for the slice above. ADR-0001's core finding — BugVault is not a viable independent or general-purpose memory product — stands. Everything ADR-0001 declared out of scope (retrieval features, graph features, automatic triggers, strategic-memory abstractions) stays out of scope here.

[ADR-0002](0002-agent-memory-needs-effect-measurement.md) is unaffected and still governs continuation: this reopening is exploratory, and the phase only continues if a project-local before/after experiment shows a measurable reduction in repeated mistakes.

## Re-verification conditions

Re-check this decision — and stop again — when any of these holds:

- The slice cannot be expressed without reopening general memory, the retrieval kernel, or provider abstraction.
- The verification gate collapses to "records have more required fields" without changing agent behaviour.
- No before/after experiment shows a measurable reduction in repeat-mistake rate within the exploratory time box.
- Recurrence detection only reproduces claude-mem's dedup or ECC's cross-project promotion, adding no same-project signal.
- Building the slice requires automatic capture or mandatory retrieval to work at all.

On any of these, return to ADR-0001: freeze the slice, keep the work as a case study, and record the falsification.

## Consequences

- README and [the competitive landscape note](../research/competitive-landscape.md) must point to this ADR so the reopen is not read as a reversal of ADR-0001.
- Work stays at the spec/experiment level until ADR-0002's measurement condition is met; no new retrieval, graph, or provider work is authorised by this ADR.
- If the re-verification conditions fire, the outcome is documented as another falsification, consistent with the project's hypothesis → build → read → falsify method.

## References

- [ADR-0001](0001-stop-bugvault-product-validation.md) — stop decision, superseded in part by this ADR.
- [ADR-0002](0002-agent-memory-needs-effect-measurement.md) — measurement condition that still governs continuation.
- [Competitive landscape: nova / claude-mem / ECC / mem0](../research/competitive-landscape.md) — the survey that identified the unoccupied slice.
