# Stop BugVault as an independent product

**Status:** accepted — superseded in part by [ADR-0003](0003-reopen-verification-gate.md)

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

## 2026-10 conclusion update (public note)

This addendum does not change the Decision above; it states the conclusion explicitly for readers and points to further reading.

- **Conclusion:** BugVault is not a viable independent or general-purpose memory product, and productisation is frozen. The repository is kept as a case study in validating — and then falsifying — a product hypothesis.
- **New evidence:** a survey of the same space shows the vertical layer is covered from both ends — [mem0](https://github.com/mem0ai/mem0) (general memory lifecycle), [OpenViking](https://github.com/volcengine/OpenViking) (filesystem-style context/asset platform with lifecycle hooks and async memory extraction), and [zvec](https://github.com/alibaba/zvec) (in-process vector/FTS/hybrid retrieval engine). See [ADR-0002](0002-agent-memory-needs-effect-measurement.md) for the measurement framing.
- **Reserved value:** the method — hypothesis → build → competitive/source reading → falsification → boundary drawing — is the reusable outcome.
- **Further reading:** [Agent memory / retrieval landscape and BugVault conclusion](../research/zvec-openviking-reading-and-direction.md) — capability notes and when to use OpenViking, zvec, or mem0.
- **Only path to reopen:** see the Reconsideration trigger above; the one remaining hypothesis worth testing is measuring whether a memory actually changes agent behaviour.

### 2026-10 partial supersede

- **[ADR-0003](0003-reopen-verification-gate.md)** lifts this ADR's freeze for one exploratory slice only — making recorded engineering experience credible (verification gate, record status, same-project recurrence detection). The core finding above still stands, and ADR-0001's freeze remains in force for general memory, the retrieval kernel, and provider abstraction.
