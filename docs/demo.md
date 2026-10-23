# Demonstration guide

Build and launch the application using the [README](../README.md), then open `http://127.0.0.1:8765`. Keep **Fixture · deterministic** selected for a repeatable demonstration with no model credentials or inference charges.

The case queue starts empty. **Scenario lab** creates original fictional incidents with isolated order/job identities and target receipts. **Demo role** switches public local personas. It does not sign you in as a different real user.

## 1. Investigate and recover an accepted request

1. As **Operator**, open **Scenario lab** and create **Accepted order, missing acknowledgement**.
2. Choose **Investigate**. The Activity view records scoped evidence reads, receipt lookup, runbook search, and diagnosis submission.
3. Open **Overview**. The recommendation should recover the already recorded target receipt rather than retrying the export. Follow its citations into **Evidence** and inspect the receipt observation.
4. Switch to **Reviewer**. Expand **Exact proposed action** and inspect the order/job scope, hash, revisions, and expiry. Choose **Approve** and confirm. This records authorization only.
5. Switch back to **Operator**. Choose **Execute approved action** and confirm.
6. Inspect the operation's receipt and verification evidence. The case becomes resolved; the target still has one receipt. Download the case JSON using the report icon beside **Investigate** and inspect `case.target.receipt_count`.

The simulator's acknowledgement was missing by scenario construction. This demonstrates receipt reconciliation and idempotent local execution, not an actual network interruption against an ERP.

For the retry branch, repeat the workflow with **Temporary ERP outage**. Its original request was not accepted, so the proposal uses the unchanged export payload and key to create one fictional receipt.

## 2. Verify and export a real patch

1. Create **Decimal amount mapping defect** as Operator and investigate it.
2. The source prematurely rounds the final amount to whole currency units. Choose **Prepare restricted transform repair** or use the **Code repair** tab.
3. Inspect the actual baseline and candidate results: the current deterministic fixture passes 8 of 16 checks before correction and 16 of 16 afterward. Expand individual results, original expression, and candidate expression.
4. Read the unified diff and patch hash. This is a change to `fixtures/decimal_mapping.expr` in the project's restricted language.
5. Return to **Overview**, switch to Reviewer, and approve the exact patch-export proposal.
6. Switch to Operator and choose **Export verified patch**. Return to **Code repair** and choose **Download verified patch**. The JSON report also includes the diff and full verification report.

The case becomes **Patch ready**. It does not become a successfully exported business order. No source file is automatically changed, no Git commit is made, no application is deployed, and the failed immutable business payload is retained. This distinction is intentional: producing a verified artifact is not the same operation as applying it and repairing business state.

Fixture mode supplies a known deterministic correction. Optional live mode asks your selected model for a candidate expression, then applies the same independent validation. A live candidate can fail. Neither mode executes arbitrary model-generated code.

## 3. Inspect an adversarial log

1. Create **Untrusted instructions inside a log**.
2. Open **Evidence** and inspect the untrusted log field. It contains instructions to bypass approval and exfiltrate credentials, clearly marked as fictional test data.
3. Investigate in fixture mode. The explicit policy uses observed export facts and proposes the same scoped recovery as the transient-outage scenario.
4. As Operator, observe that a pending proposal cannot execute until a Reviewer approves it. As Observer, observe that mutation controls are unavailable.

This is a deterministic policy demonstration, not a statistical prompt-injection defense result. To inspect actual model behavior, configure live mode and run this scenario separately; review the trace and outcome. The gateway's tool allowlist and the domain's authorization rules remain in force regardless of the model's response.

## Remaining scenarios

| Scenario | Expected outcome |
| --- | --- |
| Connector authorization denied | Escalate; no permission change and no export retry |
| Supplier blocked by business rules | Escalate; do not unblock the supplier |
| Incomplete integration telemetry | State the uncertainty and escalate |
| Already completed export | Verify the matching receipt and propose no mutation |

## Rejection, expiry, cancellation, and restart

- Reject a pending proposal as Reviewer; no operation executes, and the decision remains in the case history.
- Proposals expire after 15 minutes by default. A new investigation creates a fresh observation and makes prior pending/approved proposals stale.
- An active investigation can be cancelled from Activity as Operator. Cancellation is cooperative and may wait for the current provider request to settle. Fixture runs are often too short to cancel interactively.
- Stop and restart the server using the same database. Cases, events, approvals, and operations remain. If the previous process was interrupted with an active run, that run becomes `interrupted`; start a new investigation. The application does not resume hidden model execution.

For reproducible cancellation, concurrency, tampering, and restart checks, use the automated test suite rather than relying on manual timing.

## Run the regression lab

Choose **Evaluations → Run regression** as Operator. The server creates an isolated temporary database and exercises all eight deterministic scenarios. Expand a scenario to inspect each outcome check, including expected and actual values. Diagnosis, approval, recovery, repair export, and no-effect assertions are checked where relevant. Saved cases are unaffected.

The same report is available from the repository root:

```powershell
.\.venv\Scripts\python.exe -m relayops --evaluate --report runtime/evaluation-report.json
```

On Unix use `.venv/bin/python`. Dashboard reports survive restarts in the workspace database; select an older run and download its JSON to retain its precise evidence. CLI reports are saved only to the explicitly requested file, not dashboard history. These checks are authored system regressions, not held-out model evaluations or an accuracy leaderboard. See [evaluations.md](evaluations.md) for the report contract and failure handling.

## Optional live session

Set `OPENAI_API_KEY` and `RELAYOPS_MODEL` in the server's environment and restart the application. Creating a `.env` file alone does not load those values. Select **OpenAI** in the case's **Investigation mode** control, then investigate. The Activity view identifies a live run and shows provider-reported usage when available.

A model/API failure leaves an explicit failed run, not a substituted fixture diagnosis. An investigation may also fail if the model cites unread evidence, requests a forbidden tool, proposes an action inconsistent with current target facts, or exhausts its call/time budget. None of those failures approves an operation.
