"""Domain boundary tests use real temporary SQLite files, including concurrency."""

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from relayops.domain import Domain, DomainError, canonical
from relayops.scenarios import list_scenarios
from relayops.store import Store


class DomainTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.path = Path(self.directory.name) / "ledger.sqlite"
        self.store = Store(self.path)
        self.now = datetime(2026, 1, 1, tzinfo=timezone.utc)
        self.domain = Domain(self.store, clock=lambda: self.now, approval_ttl_seconds=60)

    def tearDown(self):
        self.store.close()
        self.directory.cleanup()

    def diagnosis(self, case, action):
        return {"summary": "Observed fixture facts justify this bounded result.", "cause": "test-observed-cause",
                "evidence_ids": [case["evidence"][0]["id"]], "hypotheses": ["Alternative considered"],
                "recommendation": "Perform the proposed scoped action after reviewer approval.", "action": action}

    def investigate(self, scenario="transient-outage", action="retry_export"):
        case = self.domain.create_case(scenario)
        run = self.domain.create_run(case["id"], "fixture")
        self.domain.update_run(run["id"], status="running")
        case = self.domain.record_diagnosis(case["id"], run["id"], self.diagnosis(case, action))
        self.domain.update_run(run["id"], status="completed")
        return case, run

    def approve(self, proposal):
        return self.domain.decide(proposal["id"], "approve", proposal["hash"], "reviewer")

    def mutate_case(self, case_id, callback):
        with self.store.transaction() as connection:
            row = connection.execute("SELECT body FROM cases WHERE id=?", (case_id,)).fetchone()
            body = json.loads(row[0])
            callback(body)
            connection.execute("UPDATE cases SET body=? WHERE id=?", (canonical(body), case_id))

    def test_eight_scenarios_have_unique_scoped_hashed_evidence(self):
        scenarios = list_scenarios()
        self.assertEqual(len(scenarios), 8)
        ids = set()
        for scenario in scenarios:
            self.assertNotIn("action", scenario)
            case = self.domain.create_case(scenario["id"])
            self.assertTrue(case["target"]["fictional"])
            self.assertEqual(case["target"]["transport"], "in-process")
            ids.add(case["order_id"])
            for evidence in case["evidence"]:
                self.assertEqual(evidence["sha256"], hashlib.sha256(evidence["content"].encode()).hexdigest())
        self.assertEqual(len(ids), 8)
        self.assertEqual(len(self.domain.list_cases()), 8)

    def test_retry_needs_exact_review_then_verifies_one_receipt(self):
        case, _ = self.investigate()
        proposal = case["proposals"][0]
        with self.assertRaises(DomainError):
            self.domain.execute(proposal["id"], proposal["hash"], "operator")
        approved = self.approve(proposal)
        self.assertEqual(approved["revision"], proposal["case_revision"])
        result = self.domain.execute(proposal["id"], proposal["hash"], "operator")
        self.assertEqual(result["status"], "resolved")
        self.assertEqual(result["target"]["receipt_count"], 1)
        self.assertEqual(result["target"]["local_receipt"], result["target"]["external_receipt"])
        self.assertTrue(result["proposals"][0]["verification"]["passed"])

    def test_lost_acknowledgement_recovers_original_receipt(self):
        case, _ = self.investigate("lost-acknowledgement", "reconcile_receipt")
        original = case["target"]["external_receipt"]
        self.assertIsNone(case["target"]["local_receipt"])
        proposal = case["proposals"][0]
        self.approve(proposal)
        result = self.domain.execute(proposal["id"], proposal["hash"], "operator")
        self.assertEqual(result["target"]["local_receipt"], original)
        self.assertEqual(result["target"]["receipt_count"], 1)
        self.assertEqual(len(result["operations"]), 1)

    def test_duplicate_concurrent_execution_creates_one_operation(self):
        case, _ = self.investigate()
        proposal = case["proposals"][0]
        self.approve(proposal)
        # Independent Store instances exercise SQLite locking, beyond the Python lock.
        def execute(_):
            domain = Domain(Store(self.path), clock=lambda: self.now)
            return domain.execute(proposal["id"], proposal["hash"], "operator")["target"]["local_receipt"]
        with ThreadPoolExecutor(max_workers=6) as pool:
            receipts = list(pool.map(execute, range(12)))
        self.assertEqual(len(set(receipts)), 1)
        result = self.domain.get_case(case["id"])
        self.assertEqual(len(result["operations"]), 1)
        self.assertEqual(result["target"]["receipt_count"], 1)
        self.assertEqual(sum(event["kind"] == "verification" for event in result["events"]), 1)

    def test_duplicate_approval_is_idempotent(self):
        case, _ = self.investigate()
        proposal = case["proposals"][0]
        first = self.approve(proposal)
        second = self.approve(proposal)
        self.assertEqual(first, second)

    def test_roles_and_wrong_hash_rejected_without_side_effect(self):
        case, _ = self.investigate()
        proposal = case["proposals"][0]
        for role in ("operator", "observer", "administrator"):
            with self.assertRaises(DomainError) as error:
                self.domain.decide(proposal["id"], "approve", proposal["hash"], role)
            self.assertEqual(error.exception.status_code, 403)
        with self.assertRaises(DomainError):
            self.domain.decide(proposal["id"], "approve", "wrong", "reviewer")
        self.approve(proposal)
        for role in ("reviewer", "observer"):
            with self.assertRaises(DomainError):
                self.domain.execute(proposal["id"], proposal["hash"], role)
        self.assertEqual(self.domain.get_case(case["id"])["target"]["receipt_count"], 0)

    def test_rejection_cannot_execute_and_duplicate_rejection_is_safe(self):
        case, _ = self.investigate()
        proposal = case["proposals"][0]
        self.domain.decide(proposal["id"], "reject", proposal["hash"], "reviewer")
        self.domain.decide(proposal["id"], "reject", proposal["hash"], "reviewer")
        with self.assertRaises(DomainError):
            self.domain.execute(proposal["id"], proposal["hash"], "operator")

    def test_expiry_checked_at_execution_and_persisted(self):
        case, _ = self.investigate()
        proposal = case["proposals"][0]
        self.approve(proposal)
        self.now += timedelta(seconds=61)
        with self.assertRaises(DomainError):
            self.domain.execute(proposal["id"], proposal["hash"], "operator")
        result = self.domain.get_case(case["id"])
        self.assertEqual(result["proposals"][0]["status"], "expired")
        self.assertEqual(result["target"]["receipt_count"], 0)

    def test_expiry_checked_before_approval(self):
        case, _ = self.investigate()
        proposal = case["proposals"][0]
        self.now += timedelta(seconds=60)
        with self.assertRaises(DomainError):
            self.approve(proposal)
        self.assertEqual(self.domain.get_case(case["id"])["proposals"][0]["status"], "expired")

    def test_target_revision_change_invalidates_approval(self):
        case, _ = self.investigate()
        proposal = case["proposals"][0]
        self.approve(proposal)
        self.mutate_case(case["id"], lambda body: body["target"].update(job_revision=2))
        with self.assertRaises(DomainError):
            self.domain.execute(proposal["id"], proposal["hash"], "operator")
        self.assertEqual(self.domain.get_case(case["id"])["proposals"][0]["status"], "stale")

    def test_modified_payload_cannot_reuse_approved_hash(self):
        case, _ = self.investigate()
        proposal = case["proposals"][0]
        self.approve(proposal)
        self.mutate_case(case["id"], lambda body: body["target"]["immutable_payload"].update(total="999.99"))
        with self.assertRaises(DomainError):
            self.domain.execute(proposal["id"], proposal["hash"], "operator")
        self.assertEqual(self.domain.get_case(case["id"])["target"]["receipt_count"], 0)

    def test_cross_case_evidence_and_run_are_rejected(self):
        case = self.domain.create_case("transient-outage")
        other = self.domain.create_case("transient-outage")
        run = self.domain.create_run(case["id"], "fixture")
        with self.assertRaises(DomainError):
            self.domain.record_diagnosis(case["id"], run["id"], self.diagnosis(other, "retry_export"))
        with self.assertRaises(DomainError):
            self.domain.record_diagnosis(other["id"], run["id"], self.diagnosis(other, "retry_export"))

    def test_policy_denies_unsafe_actions_even_with_valid_evidence(self):
        for scenario in ("authorization-denied", "business-rejection", "insufficient-evidence", "mapping-defect", "healthy-export"):
            case = self.domain.create_case(scenario)
            run = self.domain.create_run(case["id"], "fixture")
            with self.assertRaises(DomainError):
                self.domain.record_diagnosis(case["id"], run["id"], self.diagnosis(case, "retry_export"))
            self.assertEqual(self.domain.get_case(case["id"])["proposals"], [])

    def test_untrusted_log_does_not_expand_allowed_action(self):
        case, _ = self.investigate("misleading-log", "retry_export")
        self.assertTrue(any(item["kind"] == "untrusted-log" for item in case["evidence"]))
        self.assertEqual(case["proposals"][0]["kind"], "retry_export")
        self.assertNotIn("invalid.example", canonical(case["proposals"][0]))

    def test_active_run_unique_cancellation_stops_diagnosis(self):
        case = self.domain.create_case("transient-outage")
        run = self.domain.create_run(case["id"], "fixture")
        with self.assertRaises(DomainError):
            self.domain.create_run(case["id"], "fixture")
        self.domain.cancel_run(run["id"])
        self.assertTrue(self.domain.run_cancelled(run["id"]))
        with self.assertRaises(DomainError):
            self.domain.record_diagnosis(case["id"], run["id"], self.diagnosis(case, "retry_export"))
        self.domain.update_run(run["id"], status="cancelled")
        self.assertEqual(self.domain.create_run(case["id"], "fixture")["status"], "queued")

    def test_restart_preserves_approvals_and_recovers_active_runs(self):
        case, _ = self.investigate("lost-acknowledgement", "reconcile_receipt")
        proposal = case["proposals"][0]
        self.approve(proposal)
        pending = self.domain.create_case("transient-outage")
        run = self.domain.create_run(pending["id"], "fixture")
        self.domain.add_run_event(run["id"], "evidence", "Evidence retained", "A saved observation")
        restarted = Domain(Store(self.path), clock=lambda: self.now)
        self.assertEqual(restarted.recover_interrupted_runs(), 1)
        self.assertEqual(restarted.recover_interrupted_runs(), 0)
        self.assertEqual(restarted.get_run(run["id"])["status"], "interrupted")
        self.assertEqual(len(restarted.get_run(run["id"])["events"]), 1)
        self.assertEqual(restarted.get_case(case["id"])["proposals"][0]["status"], "approved")
        self.assertEqual(restarted.execute(proposal["id"], proposal["hash"], "operator")["status"], "resolved")

    def test_new_investigation_stales_prior_approval(self):
        case, _ = self.investigate()
        proposal = case["proposals"][0]
        self.approve(proposal)
        self.domain.create_run(case["id"], "fixture")
        with self.assertRaises(DomainError):
            self.domain.execute(proposal["id"], proposal["hash"], "operator")
        self.assertEqual(self.domain.get_case(case["id"])["proposals"][0]["status"], "stale")

    def test_diagnosis_duplicate_does_not_make_two_proposals(self):
        case = self.domain.create_case("transient-outage")
        run = self.domain.create_run(case["id"], "fixture")
        diagnosis = self.diagnosis(case, "retry_export")
        self.domain.record_diagnosis(case["id"], run["id"], diagnosis)
        self.domain.record_diagnosis(case["id"], run["id"], diagnosis)
        self.assertEqual(len(self.domain.get_case(case["id"])["proposals"]), 1)

    def test_healthy_receipt_agreement_resolves_without_operation(self):
        case, _ = self.investigate("healthy-export", "none")
        self.assertEqual(case["status"], "resolved")
        self.assertEqual(case["operations"], [])
        self.assertEqual(case["proposals"], [])
        self.assertEqual(case["target"]["receipt_count"], 1)

    def test_rollback_keeps_ledgers_atomic(self):
        case, _ = self.investigate()
        proposal = case["proposals"][0]
        self.approve(proposal)
        with self.store.transaction() as connection:
            connection.execute("CREATE TRIGGER fail_operation BEFORE INSERT ON operations BEGIN SELECT RAISE(ABORT,'test failure'); END;")
        with self.assertRaises(Exception):
            self.domain.execute(proposal["id"], proposal["hash"], "operator")
        result = self.domain.get_case(case["id"])
        self.assertEqual(result["target"]["receipt_count"], 0)
        self.assertEqual(result["proposals"][0]["status"], "approved")
        self.assertEqual(result["operations"], [])

    def test_verified_patch_export_does_not_deploy_or_rewrite_payload(self):
        from relayops.repair import prepare_repair
        case, _ = self.investigate("mapping-defect", "prepare_patch")
        immutable = case["target"]["immutable_payload"]
        result = self.domain.save_repair(case["id"], prepare_repair())
        proposal = result["proposals"][0]
        self.assertEqual(proposal["kind"], "publish_patch")
        self.approve(proposal)
        result = self.domain.execute(proposal["id"], proposal["hash"], "operator")
        self.assertEqual(result["status"], "patch_ready")
        self.assertFalse(result["proposals"][0]["verification"]["deployed"])
        self.assertFalse(result["proposals"][0]["verification"]["business_incident_resolved"])
        self.assertEqual(result["target"]["immutable_payload"], immutable)
        self.assertEqual(result["target"]["job_status"], "FAILED")
        self.assertEqual(result["target"]["receipt_count"], 0)

    def test_forged_test_success_is_independently_recomputed(self):
        from relayops.repair import prepare_repair
        case, _ = self.investigate("mapping-defect", "prepare_patch")
        report = prepare_repair(candidate="0")
        report["status"] = "verified"
        report["verification"]["passed"] = report["verification"]["total"]
        result = self.domain.save_repair(case["id"], report)
        self.assertEqual(result["proposals"], [])
        self.assertEqual(result["repair"]["status"], "failed")
        self.assertEqual(result["status"], "repair_failed")

    def test_tampered_patch_artifact_rejected(self):
        from relayops.repair import prepare_repair
        case, _ = self.investigate("mapping-defect", "prepare_patch")
        report = prepare_repair()
        report["diff"] += "\nUnauthorized additional change"
        with self.assertRaises(DomainError):
            self.domain.save_repair(case["id"], report)
        self.assertEqual(self.domain.get_case(case["id"])["proposals"], [])

    def test_changed_verified_patch_invalidates_old_approval(self):
        from relayops.repair import prepare_repair
        case, _ = self.investigate("mapping-defect", "prepare_patch")
        result = self.domain.save_repair(case["id"], prepare_repair())
        proposal = result["proposals"][0]
        self.approve(proposal)
        alternate = prepare_repair(candidate="round(decimal(unitPrice) * decimal(quantity), 2)")
        self.assertEqual(alternate["status"], "verified")
        self.domain.save_repair(case["id"], alternate)
        with self.assertRaises(DomainError):
            self.domain.execute(proposal["id"], proposal["hash"], "operator")

    def test_add_evidence_deduplicates_and_preserves_approval_revision(self):
        case, _ = self.investigate()
        proposal = case["proposals"][0]
        self.approve(proposal)
        one = self.domain.add_evidence(case["id"], "receipt", "Fresh read", '{"receipt":null}', "simulator://fresh")
        two = self.domain.add_evidence(case["id"], "receipt", "Fresh read", '{"receipt":null}', "simulator://fresh")
        self.assertEqual(one, two)
        self.assertEqual(self.domain.get_case(case["id"])["revision"], proposal["case_revision"])
        self.assertEqual(self.domain.execute(proposal["id"], proposal["hash"], "operator")["status"], "resolved")

    def test_target_foreign_job_or_payload_reference_rejected(self):
        for field in ("job_id", "reference"):
            case, _ = self.investigate()
            proposal = case["proposals"][0]
            self.approve(proposal)
            def mutate(body):
                if field == "job_id":
                    body["target"]["job_id"] = "another-job"
                else:
                    body["target"]["immutable_payload"]["reference"] = "another-order"
            self.mutate_case(case["id"], mutate)
            with self.assertRaises(DomainError):
                self.domain.execute(proposal["id"], proposal["hash"], "operator")

    def test_foreign_receipt_cannot_reconcile(self):
        case, _ = self.investigate("lost-acknowledgement", "reconcile_receipt")
        proposal = case["proposals"][0]
        self.approve(proposal)
        with self.store.transaction() as connection:
            connection.execute("UPDATE target_receipts SET job_id='another-job' WHERE case_id=?", (case["id"],))
        with self.assertRaises(DomainError):
            self.domain.execute(proposal["id"], proposal["hash"], "operator")

    def test_shared_memory_store_supports_separate_connections(self):
        store = Store(":memory:")
        try:
            domain = Domain(store)
            case = domain.create_case("healthy-export")
            with ThreadPoolExecutor(max_workers=3) as pool:
                ids = list(pool.map(lambda _: domain.get_case(case["id"])["id"], range(6)))
            self.assertEqual(set(ids), {case["id"]})
        finally:
            store.close()


if __name__ == "__main__":
    unittest.main()
