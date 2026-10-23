"""Append-only local evaluation reports, independent of the incident ledger."""

import json
from uuid import UUID

from .domain import DomainError


SUMMARY_FIELDS = (
    "id", "generated_at", "schema_version", "suite_version", "app_version", "kind",
    "model_evaluation", "total", "passed", "checks_total", "checks_passed", "duration_ms",
)


def empty_report():
    return {"id": None, "kind": "deterministic-regression", "model_evaluation": False,
            "generated_at": None, "total": 0, "passed": 0, "checks_total": 0,
            "checks_passed": 0, "results": [],
            "limitations": ["No saved evaluation yet. Run the regression suite to create a report."]}


class EvaluationHistory:
    def __init__(self, store):
        self.store = store

    def save(self, report):
        # Reports are produced by the server, never accepted as client-supplied JSON.
        # A duplicate identity fails instead of silently replacing historical evidence.
        UUID(report["id"])
        for field in SUMMARY_FIELDS:
            if field not in report:
                raise ValueError(f"Evaluation report is missing {field}")
        body = json.dumps(report, sort_keys=True, separators=(",", ":"), allow_nan=False)
        with self.store.transaction() as connection:
            connection.execute("INSERT INTO evaluations (id, generated_at, body) VALUES (?, ?, ?)",
                               (report["id"], report["generated_at"], body))
        return json.loads(body)

    def latest(self):
        with self.store.read() as connection:
            row = connection.execute("SELECT body FROM evaluations ORDER BY sequence DESC LIMIT 1").fetchone()
        return json.loads(row[0]) if row else empty_report()

    def list(self, limit=20):
        if not 1 <= limit <= 100:
            raise ValueError("Choose a history limit between 1 and 100")
        with self.store.read() as connection:
            rows = connection.execute("SELECT body FROM evaluations ORDER BY sequence DESC LIMIT ?", (limit,)).fetchall()
        return [{key: report[key] for key in SUMMARY_FIELDS}
                for report in (json.loads(row[0]) for row in rows)]

    def get(self, report_id):
        with self.store.read() as connection:
            row = connection.execute("SELECT body FROM evaluations WHERE id = ?", (report_id,)).fetchone()
        if row is None:
            raise DomainError("Evaluation report not found", 404)
        return json.loads(row[0])
