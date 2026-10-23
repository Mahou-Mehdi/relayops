# Roadmap: from local incident lab to agent control center

This document describes planned work. The implemented release is the local v0.2 described in the [README](../README.md). The schedule below is a planning range of approximately **16–22 weeks at 20 hours per week**, not a delivery commitment or a claim of completed experience. Each stage has an observable exit condition; scope should change when experiments show that a proposed feature is not useful.

## Current foundation

v0.1 already joins an actual LangGraph investigation loop, a model transport, a domain-controlled approval workflow, durable local records, fictional ERP recovery, and independently checked expression patches in one interface. It establishes the workflow and its boundaries. It does not yet implement general code execution, multiagent orchestration, a remote integration queue, or comparative model evaluations.

v0.2 adds outcome-based regression grading, saved evaluation history, report downloads, and retained CI evidence. These are completed foundations for Stage 5; the larger dataset and comparative model experiments below remain future work.

## Stage 1 — Durable control and remote effects

Approximate focus: weeks 1–3.

- Introduce authenticated identities and enforce authorization independently of the UI. Preserve the distinction between proposing, approving, and executing.
- Move the control ledger toward PostgreSQL, with workers, leases, operation identities, bounded retry/backoff, and a transactional outbox.
- Add a separate network target with persistent idempotency receipts. Inject failure before dispatch, after remote acceptance, before local completion, and during worker recovery.
- Add cooperative cancellation, explicit unknown outcomes, reconciliations, and an operator stop mechanism. Avoid claiming that cancellation can undo an already accepted external action.

Exit gate: concurrent/repeated requests and restart sequences cause zero duplicate effective operations in the documented fault matrix; approvals cannot be reused for changed actors, arguments, targets, revisions, or expired requests. Report which guarantees require target-side idempotency.

## Stage 2 — Isolated repository repair

Approximate focus: weeks 4–7.

- Keep the restricted expression exercise as a fast regression case and add a separate disposable code runner.
- Start with a small connector repository: decimal conversions, date handling, payload mapping, schema validation, and error classification. Reproduce a failure before proposing a change.
- Run candidate code in a reviewed isolation boundary with no host credentials, unrestricted network, container-management socket, or writable host project mount. Set CPU, memory, storage, and time limits.
- Keep trusted tests and grading outside candidate control; require failing checks to pass and existing checks to remain passing. Bind approval to exact patch bytes and a source revision.
- Export patches or draft review artifacts; deployment remains a separate authorized workflow.

Exit gate: actual generated patches pass independently maintained tests, attempted test tampering does not produce success, and resource/escape tests demonstrate the defined isolation properties. Name the runner and its limits rather than labeling arbitrary subprocess execution a sandbox.

## Stage 3 — Agent development and comparative orchestration

Approximate focus: weeks 8–11.

- Version agent instructions, model configuration, tool schemas, policy, and evaluation manifests; make a run reproducible from those identities.
- Add investigation replay, side-by-side trace comparison, tool-result inspection, failure categorization, and explicit budgets.
- Compare an ordinary runbook/search baseline, a single tool-using investigator, and a coordinator with two or three scoped specialists.
- Start with independently useful roles such as telemetry investigation and recent-change analysis. Add a verifier only if it improves independently measured outcomes.
- Apply one aggregate budget across the coordinator and every worker. Prevent recursive delegation from escaping call, time, token, and spend limits.

Exit gate: explain a measured quality, latency, or cost tradeoff. If multiagent coordination does not beat a simpler alternative for a task class, keep the simpler route as its default.

## Stage 4 — Connectors, MCP, and an SAP-oriented workflow

Approximate focus: weeks 12–15.

- Introduce a versioned connector contract with scoped reads, typed actions, receipt lookup, capability declarations, and policy-controlled execution.
- Add MCP as an integration interface with an explicit server/tool allowlist. Treat descriptions and returned content as untrusted; a tool's declaration is not authorization to execute it.
- Connect to the separate procurement portfolio application first, clearly labeling that application and its simulator. Add an SAP read-only adapter only when an appropriate real tenant, endpoint, credentials, and permissions are available.
- Make any later SAP mutation an explicit integration project: map the actual API contract, business rules, destinations/authentication, idempotency/reconciliation semantics, approval, and audit requirements.

Exit gate: contract tests pass against the actual connected system, credentials are not exposed to agents, and the documentation distinguishes simulated behavior from verified SAP behavior. Do not relabel the current fictional ERP as an SAP integration.

## Stage 5 — Evaluate and harden

Approximate focus: weeks 16–18, with weeks 19–22 available for hardening, documentation, and unresolved findings.

Build toward **120 authored cases: 60 development, 20 validation, and 40 test**. This is a proposed dataset size, not an existing benchmark. Group related incident templates, repeated deployment incidents, and repair bug families into the same split. Renaming services or changing a random seed does not make a near-duplicate an independent test case.

Include transient failures, lost acknowledgements, invalid credentials, business rejections, mapping defects, misleading changes, stale/missing evidence, healthy systems, and adversarial tool content. Add richer observed signals so models cannot pass merely by reading explicit fixture error labels. Report unfamiliar fault families separately. Keep expected outcomes and grader access outside the agent tool surface.

Freeze prompts, retrieval, model identifiers, budgets, and task versions before the final run. A published frozen test set is a reproducible **frozen benchmark**, not a private evaluation set. Once failures guide further tuning, those tasks become regression material; use a fresh holdout for later generalization claims.

Compare the deterministic baseline, single agent, and multiagent variants with identical tool access and aggregate budgets. Reset target state and memory between attempts, randomize order, repeat agent variants three times, and count errors/timeouts/budget exhaustion rather than excluding them. Use executable outcome checks where possible and blinded human review for narrative claims. Report paired uncertainty intervals at incident level, first-attempt success, and the fraction of tasks passing all repeated attempts.

### Proposed targets, not measured results

| Measure | Initial target or reporting requirement |
| --- | --- |
| Correct root cause with supporting evidence | At least 80% on the frozen test set |
| Citation precision | At least 95%; report evidence coverage separately |
| Insufficient evidence | Report correct escalation and false confident diagnosis rates |
| Control invariants | Zero unauthorized effects, duplicate effects, or cross-case disclosures in the specified suite |
| Investigation latency | p95 below 120 seconds excluding human wait; report failures at the deadline |
| Per-run limits | Proposed ceiling of 180 seconds, 30 tool calls, and $0.50 across all agents; enforce reservations before dispatch |
| Repair limits | Separate proposed $2/five-minute ceiling, with resource limits and test outcomes |
| Economics | Actual cost per attempt and per successful incident, including retries and workers |

These future budgets are not current application settings. Model selection and live pricing determine whether they are practical. A small test set produces wide uncertainty; a numerical improvement alone does not establish a reliable advantage. Require a repeatable benefit before making multiagent execution the default.

## Failure matrix to retain throughout development

| Failure | Required observation |
| --- | --- |
| Tool-output prompt injection or forged approval | No expanded tool authority; attempt and decision recorded |
| Changed patch/arguments/target after approval | Reject execution or require a fresh authorization |
| Worker crash after remote acceptance | Reconcile using the original operation identity, without a second effective action |
| Concurrent workers or repeated approval clicks | Atomic authorization/claim semantics and one effective operation |
| Timeout, throttling, invalid response, stale evidence | Bounded retry where appropriate; uncertainty remains explicit |
| Cancellation or budget exhaustion | Stop new work and reconcile already dispatched effects |
| Candidate modifies tests or attacks runner boundary | Independent grading cannot be made to report a false success |

The portfolio's final evidence should include a working demo, versioned evaluation manifests, raw outcomes, failure examples, cost/latency results, and explanations of remaining limits. None of the targets above should be presented as achieved until its reproducible experiment exists.
