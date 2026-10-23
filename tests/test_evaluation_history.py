"""Durable reports, additive migration, and API history/role boundaries."""

from concurrent.futures import ThreadPoolExecutor
import copy
import sqlite3
import threading
from uuid import uuid4

from fastapi.testclient import TestClient
import pytest

from relayops.app import create_app
from relayops.domain import Domain
from relayops.evaluation_history import EvaluationHistory
from relayops.store import Store


OPERATOR = {"X-RelayOps-Role": "operator", "X-RelayOps-Request": "1"}
OBSERVER = {"X-RelayOps-Role": "observer", "X-RelayOps-Request": "1"}


def report(*, passed=True, generated_at="2026-10-23T12:00:00+00:00"):
    return {"id": str(uuid4()), "generated_at": generated_at, "schema_version": 1,
            "suite_version": "2", "app_version": "0.2.0", "kind": "deterministic-regression",
            "model_evaluation": False, "total": 1, "passed": int(passed), "checks_total": 1,
            "checks_passed": int(passed), "duration_ms": 12.5, "limitations": ["Authored fixture"],
            "results": [{"scenario_id": "test-fixture", "title": "Test fixture", "expected": "escalate",
                         "actual": "escalate", "passed": passed, "duration_ms": 12.5,
                         "run_status": "completed", "error": None,
                         "checks": [{"id": "no-effect", "label": "No business mutation",
                                     "passed": passed, "expected": 0, "actual": 0 if passed else 1}]}]}


def test_saved_reports_are_immutable_ordered_and_survive_restart(tmp_path):
    path = tmp_path / "history.sqlite"
    store = Store(path)
    history = EvaluationHistory(store)
    first = report()
    original = copy.deepcopy(first)
    history.save(first)
    first["results"][0]["checks"][0]["actual"] = "changed caller object"
    # Completion order remains deterministic even if the wall clock moves backward.
    second = report(passed=False, generated_at="2026-10-22T12:00:00+00:00")
    history.save(second)
    assert history.get(original["id"]) == original
    with pytest.raises(sqlite3.IntegrityError):
        history.save(original)
    assert history.list(1)[0]["id"] == second["id"]
    assert "results" not in history.list()[0]
    store.close()
    reopened = Store(path)
    try:
        restored = EvaluationHistory(reopened)
        assert restored.latest() == second
        assert restored.get(original["id"]) == original
        assert len(restored.list()) == 2
    finally:
        reopened.close()


def test_v1_database_is_upgraded_without_losing_incident_history(tmp_path):
    path = tmp_path / "v1.sqlite"
    store = Store(path)
    domain = Domain(store)
    incident = domain.create_case("lost-acknowledgement")
    with store.transaction() as connection:
        connection.execute("DROP TABLE evaluations")
        connection.execute("PRAGMA user_version = 1")
    store.close()
    upgraded = Store(path)
    try:
        assert Domain(upgraded).get_case(incident["id"]) == incident
        history = EvaluationHistory(upgraded)
        assert history.latest()["id"] is None
        history.save(report())
        assert len(history.list()) == 1
        with upgraded.read() as connection:
            assert connection.execute("PRAGMA user_version").fetchone()[0] == 2
    finally:
        upgraded.close()


def test_api_persists_failed_and_successful_reports_and_exports_exact_selection(tmp_path, monkeypatch):
    import relayops.evaluation
    outcomes = iter([report(passed=False), report()])
    monkeypatch.setattr(relayops.evaluation, "evaluate", lambda: next(outcomes))
    path = tmp_path / "api.sqlite"
    with TestClient(create_app(path), base_url="http://127.0.0.1") as client:
        assert client.get("/api/evaluations").json()["id"] is None
        assert client.get("/api/evaluations/history").json() == []
        first = client.post("/api/evaluations/run", json={}, headers=OPERATOR).json()
        second = client.post("/api/evaluations/run", json={}, headers=OPERATOR).json()
        assert first["passed"] == 0
        assert second["passed"] == 1
        assert [value["id"] for value in client.get("/api/evaluations/history").json()] == [second["id"], first["id"]]
        assert client.get(f"/api/evaluations/{first['id']}", headers=OBSERVER).json() == first
        download = client.get(f"/api/evaluations/{first['id']}/report", headers=OBSERVER)
        assert download.json() == first
        assert first["id"] in download.headers["content-disposition"]
        assert client.get("/api/cases").json() == []
    with TestClient(create_app(path), base_url="http://127.0.0.1") as restarted:
        assert restarted.get("/api/evaluations").json() == second
        assert restarted.get(f"/api/evaluations/{first['id']}/report").json() == first


def test_history_routes_validate_limit_and_enforce_persona_permissions(tmp_path):
    with TestClient(create_app(tmp_path / "api.sqlite"), base_url="http://127.0.0.1") as client:
        assert client.post("/api/evaluations/run", json={}, headers=OBSERVER).status_code == 403
        assert client.get("/api/evaluations/history", headers={"X-RelayOps-Role": "unknown"}).status_code == 403
        for limit in (0, 101, "not-a-number"):
            assert client.get(f"/api/evaluations/history?limit={limit}").status_code == 422
        assert client.get("/api/evaluations/history?limit=100").status_code == 200
        assert client.get(f"/api/evaluations/{uuid4()}").status_code == 404
        assert client.get(f"/api/evaluations/{uuid4()}/report").status_code == 404


def test_only_one_suite_runs_at_a_time_and_lock_releases_after_completion(tmp_path, monkeypatch):
    import relayops.evaluation
    entered, release = threading.Event(), threading.Event()
    def evaluate():
        entered.set()
        assert release.wait(10), "Test did not release evaluation"
        return report()
    monkeypatch.setattr(relayops.evaluation, "evaluate", evaluate)
    with TestClient(create_app(tmp_path / "api.sqlite"), base_url="http://127.0.0.1") as client:
        with ThreadPoolExecutor(max_workers=1) as pool:
            running = pool.submit(client.post, "/api/evaluations/run", json={}, headers=OPERATOR)
            try:
                assert entered.wait(5)
                assert client.post("/api/evaluations/run", json={}, headers=OPERATOR).status_code == 409
                assert client.get("/api/evaluations/history").json() == []
            finally:
                release.set()
            assert running.result(timeout=5).status_code == 200
        assert client.post("/api/evaluations/run", json={}, headers=OPERATOR).status_code == 200
        assert len(client.get("/api/evaluations/history").json()) == 2


def test_failed_persistence_does_not_report_success_or_keep_run_lock(tmp_path, monkeypatch):
    import relayops.evaluation
    monkeypatch.setattr(relayops.evaluation, "evaluate", report)
    original = EvaluationHistory.save
    def unavailable(self, value):
        raise sqlite3.OperationalError("test database unavailable")
    with TestClient(create_app(tmp_path / "api.sqlite"), base_url="http://127.0.0.1", raise_server_exceptions=False) as client:
        monkeypatch.setattr(EvaluationHistory, "save", unavailable)
        assert client.post("/api/evaluations/run", json={}, headers=OPERATOR).status_code == 500
        assert client.get("/api/evaluations/history").json() == []
        monkeypatch.setattr(EvaluationHistory, "save", original)
        assert client.post("/api/evaluations/run", json={}, headers=OPERATOR).status_code == 200
