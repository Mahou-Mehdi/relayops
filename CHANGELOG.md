# Changelog

## 0.2.1 — 2026-10-25

The dashboard now puts the incident queue and evidence ahead of introductory copy.

- Use a compact navigation rail, page headers, and status summary.
- Present scenarios as a list with expected behavior and a direct create action.
- Simplify evaluation headers and report totals while retaining history and individual checks.
- Use consistent slate surfaces, system typography, and restrained status colors.
- Rewrite interface labels and the README around concrete operations and setup steps.

## 0.2.0 — 2026-10-23

Evaluation reports now test controlled outcomes and survive server restarts.

- Require completed investigations, correct diagnoses, valid citations, scoped proposals, approval boundaries, matching receipts, unchanged immutable requests, and idempotent replay.
- Exercise the mapping-repair workflow through independent verification and reviewed patch export. Verify that export does not deploy code or resolve the business incident.
- Continue the suite after a scenario exception and retain explicit failed checks with sanitized errors.
- Save completed reports in SQLite, browse recent history, inspect individual checks, and download an exact report.
- Add `--report PATH` to CLI evaluation and retain JSON reports as GitHub Actions artifacts.
- Upgrade existing databases additively, preserving incident history.
- Add fault-injection, history, restart, concurrency, CLI, and dashboard regression coverage.

The project still uses eight authored deterministic scenarios. This release does not add a live-model benchmark, production authentication, remote ERP integration, or arbitrary-code execution.

## 0.1.0 — 2026-10-13

Initial local control center with a LangGraph investigator, optional Responses provider, scoped tools, exact-action approvals, verified fictional ERP recovery, restricted transform repair, React dashboard, and deterministic scenario checks.
