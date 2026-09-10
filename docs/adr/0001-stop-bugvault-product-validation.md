# Stop BugVault as an independent product

**Status:** accepted

BugVault's original product hypothesis was that a dedicated MCP memory layer for coding agents would be valuable because it could persist bugs, failed attempts, project conventions, and prevention rules. We decided to stop validating BugVault as an independent product and freeze feature expansion. The implemented system remains a useful engineering prototype and portfolio artifact, but it is not currently justified as a standalone replacement for general memory components or established skill/spec/review workflows.

## Decision

Treat BugVault as a completed product-validation experiment, not an active product roadmap. Preserve the repository and its engineering assets, but do not add more retrieval features, graph features, automatic triggers, or strategic-memory abstractions unless a new, independently validated user problem is identified.

## Why

- General-purpose agent memory components already cover persistence, retrieval, filtering, and memory lifecycle operations.
- Skill/spec/ADR/review workflows already cover the deliberate capture and execution of project decisions.
- Markdown, Git, ADRs, logs, and existing observability tools are sufficient for passive recording of execution feedback.
- Making every agent action trigger a memory check adds latency and integration cost that is not justified without a measurable outcome improvement.
- Letting the agent decide whether to retrieve does not provide a reliable product boundary; making retrieval mandatory makes the runtime cost unacceptable.
- The repository demonstrates a working local MCP, structured records, hybrid retrieval, archive/index separation, evaluation hooks, and graceful degradation, but it does not yet demonstrate reduced repair time, fewer repeated attempts, or real user adoption.

## What remains valuable

The code and design work remain reusable evidence of experience with MCP tool contracts, domain modeling, local persistence, retrieval pipelines, asynchronous consistency, tracing, evaluation, and product hypothesis testing. The strongest interview framing is that the project validated the engineering feasibility of a vertical memory MCP and then falsified the assumption that this capability, by itself, forms a sufficiently differentiated product.

## Reconsideration trigger

Reopen this decision only if a concrete workflow is found where BugVault changes an externally visible outcome that Markdown/Git, existing skills, or general memory components cannot provide, and that outcome can be measured with a before/after experiment.
