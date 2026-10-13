"""Exercise actual ASGI routes, worker completion, and persistence with real SQLite."""
import asyncio
import hashlib
import json
import time

import pytest
from fastapi.testclient import TestClient

from relayops.app import create_app
from relayops.repair import prepare_repair
from relayops.security import LocalBoundaryMiddleware

OPERATOR = {"X-RelayOps-Role": "operator", "X-RelayOps-Request": "1"}
REVIEWER = {**OPERATOR, "X-RelayOps-Role": "reviewer"}


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("RELAYOPS_MODEL", raising=False)
    monkeypatch.setenv("RELAYOPS_ENV", "local")
    with TestClient(create_app(tmp_path / "test.sqlite"), base_url="http://127.0.0.1") as value:
        yield value


def case(client, scenario="transient-outage"):
    response = client.post("/api/cases", json={"scenario_id": scenario}, headers=OPERATOR)
    assert response.status_code == 201, response.text
    return response.json()


def investigated(client, scenario="transient-outage"):
    item = case(client, scenario)
    response = client.post(f"/api/cases/{item['id']}/investigate", json={}, headers=OPERATOR)
    assert response.status_code == 202, response.text
    for _ in range(200):
        item = client.get(f"/api/cases/{item['id']}").json()
        if item["runs"][0]["status"] not in {"queued", "running"}:
            assert item["runs"][0]["status"] == "completed", item["runs"][0]
            return item
        time.sleep(0.025)
    pytest.fail("Investigation worker did not complete")


def export(client, proposal):
    path = f"/api/proposals/{proposal['id']}"
    approval = client.post(path + "/decision", json={"decision": "approve", "expected_hash": proposal["hash"]}, headers=REVIEWER)
    assert approval.status_code == 200, approval.text
    result = client.post(path + "/execute", json={"expected_hash": proposal["hash"]}, headers=OPERATOR)
    assert result.status_code == 200, result.text
    return result.json()


def test_end_to_end_recovery_requires_review_and_replays_without_duplicate(client):
    item = investigated(client)
    proposal = item["proposals"][0]
    path = f"/api/proposals/{proposal['id']}"
    assert client.post(path + "/execute", json={"expected_hash": proposal["hash"]}, headers=OPERATOR).status_code == 409
    assert client.post(path + "/decision", json={"decision": "approve", "expected_hash": proposal["hash"]}, headers=OPERATOR).status_code == 403
    assert client.post(path + "/decision", json={"decision": "approve", "expected_hash": "0" * 64}, headers=REVIEWER).status_code == 409
    finished = export(client, proposal)
    assert finished["status"] == "resolved"
    assert finished["target"]["receipt_count"] == 1
    replay = client.post(path + "/execute", json={"expected_hash": proposal["hash"]}, headers=OPERATOR).json()
    assert replay["operations"] == finished["operations"]
    assert replay["target"]["receipt_count"] == 1
    report = client.get(f"/api/cases/{item['id']}/report")
    assert report.json()["case"]["operations"][0]["verification"]["passed"]
    assert "attachment;" in report.headers["content-disposition"]


def test_verified_patch_download_binds_to_current_exact_export(client):
    item = investigated(client, "mapping-defect")
    path = f"/api/cases/{item['id']}"
    assert client.get(path + "/patch").status_code == 409
    result = client.post(path + "/repair", json={}, headers=OPERATOR)
    assert result.status_code == 200, result.text
    item = result.json()
    repair = item["repair"]
    assert repair["verification"]["passed"] == repair["verification"]["total"]
    assert client.get(path + "/patch").status_code == 409
    finished = export(client, item["proposals"][0])
    assert finished["status"] == "patch_ready"
    assert finished["target"]["job_status"] == "FAILED"
    patch = client.get(path + "/patch")
    assert hashlib.sha256(patch.content).hexdigest() == repair["patch_hash"]
    # A different valid artifact must not inherit the older patch's authorization.
    newer = prepare_repair(candidate="round(decimal(unitPrice) * decimal(quantity), 2)")
    assert newer["status"] == "verified"
    client.app.state.domain.save_repair(item["id"], newer)
    assert client.get(path + "/patch").status_code == 409


def test_live_mode_is_explicit_and_never_silently_falls_back(client):
    config = client.get("/api/config").json()
    assert config["live_available"] is False
    item = case(client)
    response = client.post(f"/api/cases/{item['id']}/investigate", json={"mode": "openai"}, headers=OPERATOR)
    assert response.status_code == 409
    assert client.get(f"/api/cases/{item['id']}").json()["runs"] == []


@pytest.mark.parametrize("headers,expected", [({}, 403), ({"X-RelayOps-Request": "1"}, 403),
    ({**OPERATOR, "X-RelayOps-Role": "observer"}, 403), ({**OPERATOR, "X-RelayOps-Role": "administrator"}, 403),
    ({**OPERATOR, "Origin": "https://attacker.example"}, 403), ({**OPERATOR, "Origin": "http://127.0.0.1:9999"}, 403),
    ({**OPERATOR, "Host": "attacker.example"}, 403), ({**OPERATOR, "Origin": "http://127.0.0.1"}, 201)])
def test_local_boundary_and_persona_roles(client, headers, expected):
    assert client.post("/api/cases", json={"scenario_id": "transient-outage"}, headers=headers).status_code == expected


def test_validation_prevents_client_selected_targets_and_oversized_requests(client):
    assert client.post("/api/cases", json={"scenario_id": "transient-outage", "order_id": "foreign-order"}, headers=OPERATOR).status_code == 422
    assert client.post("/api/cases", json={"scenario_id": "unknown"}, headers=OPERATOR).status_code == 404
    assert client.post("/api/cases", content=b"a" * 33000, headers=OPERATOR).status_code == 413
    assert client.get("/api/cases/not-found").status_code == 404
    assert client.get("/health").headers["x-frame-options"] == "DENY"


def test_actual_streamed_body_limit_does_not_depend_on_content_length():
    reached = []
    responses = []
    chunks = iter([{"type": "http.request", "body": b"x" * 20000, "more_body": True},
                   {"type": "http.request", "body": b"x" * 20000, "more_body": False}])
    async def downstream(scope, receive, send):
        reached.append(True)
    async def receive():
        return next(chunks)
    async def send(message):
        responses.append(message)
    scope = {"type": "http", "method": "POST", "scheme": "http", "path": "/api/cases", "query_string": b"",
             "server": ("127.0.0.1", 80), "headers": [(b"host", b"127.0.0.1"), (b"x-relayops-request", b"1")]}
    asyncio.run(LocalBoundaryMiddleware(downstream)(scope, receive, send))
    assert not reached
    assert responses[0]["status"] == 413


def test_regression_runs_in_isolated_database(client):
    item = case(client)
    before = client.get(f"/api/cases/{item['id']}").json()
    response = client.post("/api/evaluations/run", json={}, headers=OPERATOR)
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["passed"] == result["total"] == 8
    assert result["model_evaluation"] is False
    assert client.get(f"/api/cases/{item['id']}").json() == before
    assert len(client.get("/api/cases").json()) == 1


def test_restart_keeps_case_and_marks_unfinished_run_interrupted(tmp_path):
    path = tmp_path / "persistent.sqlite"
    with TestClient(create_app(path), base_url="http://127.0.0.1") as first:
        item = case(first)
        run = first.app.state.domain.create_run(item["id"], "fixture")
        first.app.state.domain.update_run(run["id"], status="running")
    with TestClient(create_app(path), base_url="http://127.0.0.1") as second:
        saved = second.get(f"/api/cases/{item['id']}").json()
        assert saved["runs"][0]["status"] == "interrupted"
        assert saved["order_id"] == item["order_id"]


def test_production_environment_is_refused(tmp_path, monkeypatch):
    monkeypatch.setenv("RELAYOPS_ENV", "production")
    with pytest.raises(RuntimeError, match="local demo personas"):
        create_app(tmp_path / "prod.sqlite")
