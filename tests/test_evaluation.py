"""The grader must reject plausible but incorrect successful-looking outcomes."""

import json
from uuid import UUID, uuid4

import pytest

from relayops import evaluation
from relayops.domain import Domain, canonical
from relayops.scenarios import get_scenario
from relayops.store import Store


@pytest.fixture
def domain(tmp_path):
    store = Store(tmp_path / "grader.sqlite")
    try:
        yield Domain(store)
    finally:
        store.close()


def grade(domain, scenario="transient-outage"):
    return evaluation._evaluate_scenario(domain, get_scenario(scenario))


def failed(result, check_id):
    assert result["passed"] is False
    assert any(check["id"] == check_id and check["passed"] is False for check in result["checks"]), result


def mutate_case(domain, case_id, mutate):
    with domain.store.transaction() as connection:
        case = json.loads(connection.execute("SELECT body FROM cases WHERE id=?", (case_id,)).fetchone()[0])
        mutate(case)
        connection.execute("UPDATE cases SET body=? WHERE id=?", (canonical(case), case_id))


def after_investigation(monkeypatch, mutate):
    original = evaluation.investigate

    def injected(domain, run_id):
        result = original(domain, run_id)
        mutate(domain, result)
        return result

    monkeypatch.setattr(evaluation, "investigate", injected)


def test_complete_suite_reports_real_outcomes_and_nonempty_checks():
    report = evaluation.evaluate()
    UUID(report["id"])
    assert report["schema_version"] == 1
    assert report["suite_version"] == "2"
    assert report["app_version"]
    assert report["model_evaluation"] is False
    assert report["total"] == report["passed"] == 8
    assert report["checks_total"] == report["checks_passed"]
    assert report["checks_total"] > 100
    assert report["duration_ms"] > 0
    for result in report["results"]:
        assert result["error"] is None
        assert result["run_status"] == "completed"
        assert result["checks"]
        assert all(check["passed"] is True for check in result["checks"])
        assert len({check["id"] for check in result["checks"]}) == len(result["checks"])
        assert "case_id" not in result and "run_id" not in result
    mapping = next(row for row in report["results"] if row["scenario_id"] == "mapping-defect")
    ids = {check["id"] for check in mapping["checks"]}
    assert {"repair.failing_baseline", "repair.passing_candidate", "patch.not_deployed", "replay.ledger_unchanged"} <= ids


def test_correct_diagnosis_with_no_retry_proposal_fails(domain, monkeypatch):
    def remove_proposal(domain, run):
        with domain.store.transaction() as connection:
            connection.execute("DELETE FROM proposals WHERE case_id=?", (run["case_id"],))

    after_investigation(monkeypatch, remove_proposal)
    result = grade(domain)
    assert result["actual"] == "retry_export"
    failed(result, "proposal.count")


def test_correct_diagnosis_does_not_hide_failed_run(domain, monkeypatch):
    def fail_run(domain, run):
        run["status"] = "failed"
        with domain.store.transaction() as connection:
            connection.execute("UPDATE runs SET status='failed', body=? WHERE id=?", (canonical(run), run["id"]))

    after_investigation(monkeypatch, fail_run)
    result = grade(domain)
    assert result["actual"] == "retry_export"
    failed(result, "run.completed")


def test_reconciliation_cannot_replace_an_existing_receipt(domain, monkeypatch):
    original = Domain.execute

    def swapped(self, proposal_id, expected_hash, role):
        result = original(self, proposal_id, expected_hash, role)
        if result["scenario_id"] == "lost-acknowledgement":
            replacement = "SIM-PO-replaced-receipt"
            with self.store.transaction() as connection:
                connection.execute("UPDATE target_receipts SET receipt=? WHERE case_id=?", (replacement, result["id"]))
            mutate_case(self, result["id"], lambda case: case["target"].update(local_receipt=replacement))
        return result

    monkeypatch.setattr(Domain, "execute", swapped)
    result = grade(domain, "lost-acknowledgement")
    failed(result, "receipt.original_preserved")
    agreement = next(check for check in result["checks"] if check["id"] == "receipt.agreement")
    assert agreement["passed"] is True  # One matching receipt still is not enough.


def test_approval_alone_must_not_mutate_business_state(domain, monkeypatch):
    original = Domain.decide

    def mutation(self, proposal_id, decision, expected_hash, role):
        result = original(self, proposal_id, decision, expected_hash, role)
        mutate_case(self, result["id"], lambda case: case["target"].update(available=False))
        return result

    monkeypatch.setattr(Domain, "decide", mutation)
    failed(grade(domain), "approval.no_effect")


@pytest.mark.parametrize("fault,check_id", [("empty_suite", "repair.passing_candidate"), ("false_counts", "repair.passing_candidate"), ("bad_hash", "repair.exact_diff")])
def test_verified_label_cannot_hide_invalid_repair(domain, monkeypatch, fault, check_id):
    original = Domain.save_repair

    def invalid(self, case_id, repair):
        result = original(self, case_id, repair)

        def corrupt(case):
            if fault == "empty_suite":
                case["repair"]["verification"].update(total=0, passed=0)
            elif fault == "false_counts":
                case["repair"]["verification"]["results"][0]["passed"] = False
            else:
                case["repair"]["diff"] += "tampered artifact"

        mutate_case(self, case_id, corrupt)
        return result

    monkeypatch.setattr(Domain, "save_repair", invalid)
    failed(grade(domain, "mapping-defect"), check_id)


def test_replayed_execution_cannot_add_a_second_operation(domain, monkeypatch):
    original = Domain.execute

    def duplicate(self, proposal_id, expected_hash, role):
        with self.store.read() as connection:
            previous = connection.execute("SELECT status FROM proposals WHERE id=?", (proposal_id,)).fetchone()[0]
        result = original(self, proposal_id, expected_hash, role)
        if previous == "executed":
            proposal = dict(result["proposals"][0], id=str(uuid4()))
            operation = dict(result["operations"][0], id=str(uuid4()))
            with self.store.transaction() as connection:
                connection.execute("INSERT INTO proposals VALUES (?,?,?,?)", (proposal["id"], result["id"], "executed", canonical(proposal)))
                connection.execute("INSERT INTO operations VALUES (?,?,?,?,?)", (operation["id"], result["id"], proposal["id"], "verified", canonical(operation)))
        return result

    monkeypatch.setattr(Domain, "execute", duplicate)
    failed(grade(domain), "replay.ledger_unchanged")


@pytest.mark.parametrize("scenario,field,value", [("authorization-denied", "authorized", True), ("business-rejection", "supplier_blocked", False)])
def test_escalation_cannot_silently_bypass_business_rules(domain, monkeypatch, scenario, field, value):
    after_investigation(monkeypatch, lambda target, run: mutate_case(target, run["case_id"], lambda case: case["target"].update({field: value})))
    result = grade(domain, scenario)
    assert result["actual"] == "escalate"
    failed(result, "outcome.target_unchanged")


def test_scenario_exception_is_sanitized_and_remaining_scenarios_run(monkeypatch):
    original = Domain.create_case
    close = Store.close
    closed = []

    def one_failure(self, scenario_id):
        if scenario_id == "mapping-defect":
            raise RuntimeError("private-token-and-customer-path")
        return original(self, scenario_id)

    def record_close(self):
        closed.append(self.path)
        close(self)

    monkeypatch.setattr(Domain, "create_case", one_failure)
    monkeypatch.setattr(Store, "close", record_close)
    report = evaluation.evaluate()
    assert report["total"] == 8
    assert report["passed"] == 7
    assert report["checks_passed"] < report["checks_total"]
    bad = next(row for row in report["results"] if row["scenario_id"] == "mapping-defect")
    assert bad["error"] == "setup: RuntimeError"
    assert bad["run_status"] is None
    failed(bad, "scenario.completed")
    assert "private-token" not in json.dumps(report)
    assert len(closed) == 1


def test_fixture_metadata_cannot_redefine_the_expected_answer(domain):
    scenario = get_scenario("transient-outage")
    scenario.update(action="escalate", cause="invented")
    result = evaluation._evaluate_scenario(domain, scenario)
    assert result["expected"] == "retry_export"
    assert result["passed"] is True


@pytest.mark.parametrize("remove_all", [False, True])
def test_removing_scenarios_cannot_shrink_the_suite_into_a_pass(monkeypatch, remove_all):
    remaining = [] if remove_all else [scenario for scenario in evaluation.SCENARIOS if scenario["id"] != "mapping-defect"]
    monkeypatch.setattr(evaluation, "SCENARIOS", remaining)
    report = evaluation.evaluate()
    assert report["total"] == 8
    assert report["passed"] == (0 if remove_all else 7)
    assert report["checks_total"] > 0
    missing = next(result for result in report["results"] if result["scenario_id"] == "mapping-defect")
    assert missing["error"] == "setup: ValueError"
    failed(missing, "scenario.completed")
