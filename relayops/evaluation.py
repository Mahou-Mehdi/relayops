"""Outcome-based fixture regression checks. This is not an LLM benchmark."""

from copy import deepcopy
from datetime import datetime, timezone
import hashlib
from pathlib import Path
from tempfile import TemporaryDirectory
from time import perf_counter
from uuid import uuid4

from . import __version__
from .domain import Domain, DomainError
from .repair import prepare_repair
from .store import Store
from .scenarios import SCENARIOS
from .workflow import investigate


# Independent expectations prevent fixture metadata from silently redefining a pass.
EXPECTATIONS = {
    "transient-outage": ("retry_export", "transient_transport_failure", "awaiting_approval"),
    "lost-acknowledgement": ("reconcile_receipt", "lost_acknowledgement", "awaiting_approval"),
    "mapping-defect": ("prepare_patch", "decimal_mapping_defect", "repair_required"),
    "authorization-denied": ("escalate", "connector_authorization_denied", "escalated"),
    "business-rejection": ("escalate", "business_rule_rejection", "escalated"),
    "misleading-log": ("retry_export", "transient_transport_failure", "awaiting_approval"),
    "insufficient-evidence": ("escalate", "insufficient_evidence", "escalated"),
    "healthy-export": ("none", "no_active_failure", "resolved"),
}
IMMUTABLE_FIELDS = ("order_id", "job_id", "immutable_payload", "payload_hash", "idempotency_key")


class Checks:
    def __init__(self):
        self.items = []

    def equal(self, identity, label, expected, actual):
        self.items.append({"id": identity, "label": label, "passed": actual == expected,
                           "expected": expected, "actual": actual})

    def true(self, identity, label, actual):
        self.equal(identity, label, True, actual)


def _same_identity(before, after):
    return all(before.get(key) == after.get(key) for key in IMMUTABLE_FIELDS)


def _proposal(checks, case, kind):
    proposals = case["proposals"]
    checks.equal("proposal.count", "Exactly one proposal exists", 1, len(proposals))
    if len(proposals) != 1:
        return None
    proposal = proposals[0]
    checks.equal("proposal.kind", "Proposal matches the permitted action", kind, proposal.get("kind"))
    checks.equal("proposal.pending", "Proposal awaits human approval", "pending", proposal.get("status"))
    target, payload = case["target"], proposal.get("payload", {})
    checks.true("proposal.scope", "Proposal binds the exact export and current revisions",
                all(payload.get(key) == target[key] for key in ("order_id", "job_id", "payload_hash", "idempotency_key"))
                and payload.get("expected_order_revision") == target["revision"]
                and payload.get("expected_job_revision") == target["job_revision"]
                and proposal.get("case_revision") == case["revision"])
    return proposal


def _approve(checks, domain, case, proposal):
    """Check the guard and approval itself before authorizing the test operation."""
    before = deepcopy(case)
    refused = False
    try:
        domain.execute(proposal["id"], proposal["hash"], "operator")
    except DomainError as error:
        refused = error.status_code == 409
    checks.true("approval.required", "Execution without approval is refused", refused)
    observed = domain.get_case(case["id"])
    checks.true("approval.denied_no_effect", "Refused execution leaves the target and ledger unchanged",
                observed["target"] == before["target"] and observed["operations"] == before["operations"])
    domain.decide(proposal["id"], "approve", proposal["hash"], "reviewer")
    approved = domain.get_case(case["id"])
    checks.true("approval.recorded", "The reviewer approves this proposal",
                len(approved["proposals"]) == 1 and approved["proposals"][0].get("status") == "approved"
                and approved["proposals"][0].get("approved_by") == "reviewer")
    checks.true("approval.no_effect", "Approval alone does not change the target or operation ledger",
                approved["target"] == before["target"] and approved["operations"] == before["operations"])


def _execute(checks, domain, case, proposal, initial):
    domain.execute(proposal["id"], proposal["hash"], "operator")
    result = domain.get_case(case["id"])
    target, operations = result["target"], result["operations"]
    patch = proposal["kind"] == "publish_patch"
    checks.equal("outcome.status", "Case has the expected final disposition", "patch_ready" if patch else "resolved", result["status"])
    checks.true("outcome.identity", "The original export bytes and identity remain unchanged", _same_identity(initial, target))
    checks.equal("operation.count", "Exactly one operation is recorded", 1, len(operations))
    checks.true("operation.verified", "The operation ledger contains a verified matching action",
                len(operations) == 1 and operations[0].get("status") == "verified"
                and operations[0].get("kind") == proposal["kind"]
                and operations[0].get("order_id") == target["order_id"]
                and operations[0].get("job_id") == target["job_id"]
                and operations[0].get("payload_hash") == (result["repair"]["patch_hash"] if patch else target["payload_hash"])
                and operations[0].get("idempotency_key") == (f"patch:{result['repair']['patch_hash']}" if patch else target["idempotency_key"])
                and operations[0].get("receipt") == (None if patch else target.get("external_receipt"))
                and operations[0].get("verification", {}).get("passed") is True)
    executed = result["proposals"]
    verification = (executed[0].get("verification") or {}) if len(executed) == 1 else {}
    checks.true("proposal.executed", "The approved proposal records successful verification",
                len(executed) == 1 and executed[0].get("status") == "executed"
                and verification.get("passed") is True)
    if patch:
        checks.true("patch.target_unchanged", "Exporting a patch does not modify the failed business export", target == initial)
        checks.true("patch.not_deployed", "The patch is exported without deployment or a false resolution claim",
                    verification.get("deployed") is False and verification.get("business_incident_resolved") is False)
        checks.true("patch.exact_artifact", "Verification and ledger bind the independently checked patch",
                    verification.get("patch_hash") == result["repair"]["patch_hash"]
                    and len(operations) == 1 and operations[0].get("payload_hash") == result["repair"]["patch_hash"])
    else:
        checks.equal("receipt.count", "Exactly one authoritative receipt exists", 1, target["receipt_count"])
        checks.true("receipt.agreement", "The application and authoritative ERP receipt agree",
                    target.get("receipt_present") is True and bool(target.get("external_receipt"))
                    and target.get("local_receipt") == target.get("external_receipt"))
        checks.true("receipt.export_completed", "The export and integration job are both completed",
                    target.get("order_status") == "EXPORTED" and target.get("job_status") == "SENT" and target.get("error_code") == "NONE")
        checks.true("receipt.verification", "Independent readback verifies the exact receipt and payload",
                    verification.get("kind") == "simulator-receipt-readback"
                    and verification.get("receipt") == target.get("external_receipt")
                    and verification.get("payload_hash") == target["payload_hash"]
                    and verification.get("order_id") == target["order_id"]
                    and verification.get("job_id") == target["job_id"]
                    and verification.get("receipt_count") == 1)
        if proposal["kind"] == "reconcile_receipt":
            checks.true("receipt.original_preserved", "Reconciliation recovers the pre-existing receipt",
                        bool(initial.get("external_receipt")) and initial["external_receipt"] == target["external_receipt"])
    before_replay = deepcopy(result)
    domain.execute(proposal["id"], proposal["hash"], "operator")
    replay = domain.get_case(case["id"])
    checks.true("replay.target_unchanged", "Repeated execution leaves the business target unchanged", replay["target"] == before_replay["target"])
    checks.true("replay.ledger_unchanged", "Repeated execution creates no additional operation", replay["operations"] == before_replay["operations"])
    checks.true("replay.proposal_unchanged", "Repeated execution preserves the verified proposal", replay["proposals"] == before_replay["proposals"])


def _evaluate_scenario(domain, scenario):
    started = perf_counter()
    checks = Checks()
    stage, error, run_status, actual = "setup", None, None, "no_diagnosis"
    expected = EXPECTATIONS.get(scenario["id"], ("unregistered", None, None))
    try:
        if scenario.get("_missing_fixture"):
            raise ValueError("A required fixture is missing from the scenario registry")
        case = domain.create_case(scenario["id"])
        initial = deepcopy(case["target"])
        run = domain.create_run(case["id"], "fixture")
        stage = "investigation"
        investigate(domain, run["id"])
        case = domain.get_case(case["id"])
        run = domain.get_run(run["id"])
        run_status = run["status"]
        diagnosis = case.get("diagnosis") or {}
        actual = diagnosis.get("action", "no_diagnosis")
        checks.equal("run.completed", "Investigation completed successfully", "completed", run_status)
        checks.equal("run.fixture", "The evaluation uses deterministic fixture mode", "fixture", run.get("mode"))
        checks.equal("run.no_model_calls", "The fixture evaluation makes no model calls", 0, run.get("model_calls"))
        checks.equal("diagnosis.action", "Diagnosis selects the expected action", expected[0], actual)
        checks.equal("diagnosis.cause", "Diagnosis identifies the expected cause", expected[1], diagnosis.get("cause"))
        citations = diagnosis.get("evidence_ids") or []
        evidence_ids = {item["id"] for item in case["evidence"]}
        checks.true("diagnosis.citations", "Diagnosis cites nonempty evidence from this incident",
                    bool(citations) and all(identity in evidence_ids for identity in citations))
        checks.equal("investigation.status", "Investigation sets the correct case disposition", expected[2], case["status"])
        checks.true("investigation.no_target_effect", "Investigation leaves the business target unchanged", case["target"] == initial)
        checks.equal("investigation.no_operations", "Investigation executes no operation", 0, len(case["operations"]))
        if expected[0] in {"escalate", "none"}:
            checks.equal("outcome.no_proposals", "This outcome creates no mutation proposal", 0, len(case["proposals"]))
            checks.true("outcome.target_unchanged", "Escalation or verification preserves all business state", case["target"] == initial)
            checks.equal("outcome.no_operations", "This outcome performs no operation", 0, len(case["operations"]))
        else:
            kind = expected[0]
            if kind == "prepare_patch":
                stage = "repair"
                checks.equal("repair.no_early_proposal", "A patch is not proposed before verification", 0, len(case["proposals"]))
                domain.save_repair(case["id"], prepare_repair(mode="fixture"))
                case = domain.get_case(case["id"])
                repair = case.get("repair") or {}
                baseline, verified = repair.get("baseline", {}), repair.get("verification", {})
                checks.equal("repair.verified", "Independent repair verification succeeds", "verified", repair.get("status"))
                checks.true("repair.failing_baseline", "The original expression fails at least one real check",
                            baseline.get("total", 0) > 0 and 0 <= baseline.get("passed", -1) < baseline["total"]
                            and len(baseline.get("results", [])) == baseline["total"]
                            and sum(row.get("passed") is True for row in baseline["results"]) == baseline["passed"])
                checks.true("repair.passing_candidate", "The candidate passes a nonempty complete check suite",
                            verified.get("total", 0) > 0 and verified.get("total") == baseline.get("total")
                            and verified.get("passed") == verified.get("total")
                            and len(verified.get("results", [])) == verified["total"]
                            and all(row.get("passed") is True for row in verified["results"]))
                checks.true("repair.exact_diff", "The nonempty patch bytes match their recorded hash",
                            bool(repair.get("diff")) and hashlib.sha256(repair["diff"].encode()).hexdigest() == repair.get("patch_hash"))
                checks.true("repair.no_target_effect", "Preparing the repair leaves the failed export unchanged", case["target"] == initial)
                kind = "publish_patch"
            stage = "proposal"
            proposal = _proposal(checks, case, kind)
            if proposal:
                stage = "approval"
                _approve(checks, domain, case, proposal)
                stage = "execution"
                _execute(checks, domain, case, proposal, initial)
    except Exception as exception:
        # Exception messages may include paths, provider content or credentials.
        # Fixed stage names and exception classes are enough to identify failures.
        error = f"{stage}: {type(exception).__name__}"
        checks.true("scenario.completed", "The scenario completes without an unexpected exception", False)
    return {"scenario_id": scenario["id"], "title": scenario["title"], "expected": expected[0],
            "actual": actual, "passed": bool(checks.items) and error is None and all(item["passed"] for item in checks.items),
            "duration_ms": round((perf_counter() - started) * 1000, 2), "run_status": run_status,
            "error": error, "checks": checks.items}


def evaluate() -> dict:
    started = perf_counter()
    with TemporaryDirectory(prefix="relayops-eval-") as directory:
        store = Store(Path(directory) / "evaluation.sqlite")
        try:
            domain = Domain(store)
            registered = {scenario["id"]: scenario for scenario in SCENARIOS}
            # Removing fixtures must not turn a failing suite into a smaller pass.
            scenarios = [registered.get(identity, {"id": identity, "title": identity.replace("-", " ").capitalize(),
                                                   "_missing_fixture": True}) for identity in EXPECTATIONS]
            scenarios.extend(scenario for identity, scenario in registered.items() if identity not in EXPECTATIONS)
            results = [_evaluate_scenario(domain, scenario) for scenario in scenarios]
        finally:
            store.close()
    return {"id": str(uuid4()), "schema_version": 1, "suite_version": "2", "app_version": __version__,
            "kind": "deterministic-regression", "model_evaluation": False,
            "generated_at": datetime.now(timezone.utc).isoformat(), "duration_ms": round((perf_counter() - started) * 1000, 2),
            "total": len(results), "passed": sum(result["passed"] for result in results), "results": results,
            "checks_total": sum(len(result["checks"]) for result in results),
            "checks_passed": sum(check["passed"] for result in results for check in result["checks"]),
            "limitations": ["Fixture policy uses explicit observed error codes; this is a regression suite, not a model reasoning benchmark.",
                            "Eight authored fictional scenarios verify outcomes, approval boundaries, repair artifacts and replay; no held-out statistical generalization claim.",
                            "Live model comparisons and network crash-after-effect recovery are future milestones."]}
