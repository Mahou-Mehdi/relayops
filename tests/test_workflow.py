"""Independent checks of the real LangGraph loop, without external model calls."""

import json
from pathlib import Path
import tempfile
import unittest

from relayops.domain import Domain
from relayops.repair import prepare_repair
from relayops.store import Store
from relayops.workflow import investigate


def observed_diagnosis(messages, *, action="retry_export", evidence_override=None):
    results = [json.loads(item["output"]) for item in messages if item.get("type") == "function_call_output"]
    export = next(item for item in results if "target" in item)
    receipt = next(item for item in results if "receipt" in item)
    evidence = [export["evidence"][-1]["id"], receipt["evidence"][0]["id"]]
    return {"summary": "The observed temporary failure has a scoped recovery path.",
            "cause": "transient_transport_failure", "recommendation": "Request review before changing the exact export.",
            "hypotheses": [], "evidence_ids": evidence_override or evidence, "action": action}


class ScriptedProvider:
    """Mock only the model boundary; graph, tools, ledger and policies remain real."""

    def __init__(self, steps, hook=None):
        self.steps = steps
        self.hook = hook
        self.requests = []

    def next(self, messages):
        self.requests.append(json.loads(json.dumps(messages)))
        if self.hook:
            self.hook(len(self.requests))
        name, arguments = self.steps[min(len(self.requests) - 1, len(self.steps) - 1)]
        if callable(arguments):
            arguments = arguments(messages)
        call = {"type": "function_call", "call_id": f"model-call-{len(self.requests)}",
                "name": name, "arguments": json.dumps(arguments)}
        return {"output": [call], "calls": [call],
                "usage": {"input_tokens": 11, "output_tokens": 3, "total_tokens": 14}}


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.directory.name) / "workflow.sqlite")
        self.domain = Domain(self.store)

    def tearDown(self):
        self.store.close()
        self.directory.cleanup()

    def start(self, scenario="transient-outage", mode="openai"):
        case = self.domain.create_case(scenario)
        run = self.domain.create_run(case["id"], mode)
        return case, run

    def standard_provider(self, finish=observed_diagnosis):
        return ScriptedProvider([("read_export_evidence", {}), ("lookup_receipt", {}),
                                 ("finish_investigation", finish)])

    def assert_no_action(self, case_id):
        case = self.domain.get_case(case_id)
        self.assertEqual(case["proposals"], [])
        self.assertEqual(case["operations"], [])

    def test_all_eight_fixture_scenarios_complete_real_workflow_and_boundaries(self):
        expected = {
            "transient-outage": ("retry_export", "awaiting_approval"),
            "lost-acknowledgement": ("reconcile_receipt", "awaiting_approval"),
            "mapping-defect": ("prepare_patch", "repair_required"),
            "authorization-denied": ("escalate", "escalated"),
            "business-rejection": ("escalate", "escalated"),
            "misleading-log": ("retry_export", "awaiting_approval"),
            "insufficient-evidence": ("escalate", "escalated"),
            "healthy-export": ("none", "resolved"),
        }
        for scenario, (action, status) in expected.items():
            with self.subTest(scenario=scenario):
                case, run = self.start(scenario, "fixture")
                before = case["target"]["immutable_payload"]
                completed = investigate(self.domain, run["id"])
                self.assertEqual(completed["status"], "completed")
                self.assertEqual(completed["model_calls"], 0)
                self.assertIsNone(completed["usage"])
                self.assertIn("Deterministic fixture", completed["events"][0]["detail"])
                self.assertEqual(completed["tool_calls"], 5 if action == "prepare_patch" else 4)
                detail = self.domain.get_case(case["id"])
                self.assertEqual(detail["diagnosis"]["action"], action)
                self.assertEqual(detail["status"], status)
                self.assertEqual(detail["operations"], [])
                self.assertEqual(detail["target"]["immutable_payload"], before)
                if action == "prepare_patch":
                    detail = self.domain.save_repair(case["id"], prepare_repair())
                if detail["proposals"]:
                    proposal = detail["proposals"][0]
                    self.domain.decide(proposal["id"], "approve", proposal["hash"], "reviewer")
                    exported = self.domain.execute(proposal["id"], proposal["hash"], "operator")
                    self.assertEqual(exported["status"], "patch_ready" if action == "prepare_patch" else "resolved")
                    self.assertEqual(exported["target"]["receipt_count"], 0 if action == "prepare_patch" else 1)
                    self.assertEqual(exported["target"]["immutable_payload"], before)

    def test_model_loop_receives_real_tool_results_and_records_usage(self):
        case, run = self.start()
        provider = self.standard_provider()
        result = investigate(self.domain, run["id"], provider=provider)
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["model_calls"], 3)
        self.assertEqual(result["tool_calls"], 3)
        self.assertEqual(result["usage"], {"input_tokens": 33, "output_tokens": 9, "total_tokens": 42})
        self.assertEqual(len(provider.requests), 3)
        self.assertTrue(any(item.get("type") == "function_call_output" for item in provider.requests[1]))
        detail = self.domain.get_case(case["id"])
        self.assertEqual(detail["proposals"][0]["status"], "pending")
        self.assertEqual(detail["target"]["receipt_count"], 0)

    def test_cannot_finish_without_both_required_reads(self):
        case, run = self.start()
        diagnosis = {"summary": "Unverified statement", "cause": "unknown", "recommendation": "Escalate",
                     "hypotheses": [], "evidence_ids": [case["evidence"][0]["id"]], "action": "escalate"}
        result = investigate(self.domain, run["id"], provider=ScriptedProvider([("finish_investigation", diagnosis)]))
        self.assertEqual(result["status"], "failed")
        self.assertIn("Read export evidence", result["error"])
        self.assert_no_action(case["id"])

    def test_valid_case_evidence_still_must_have_been_read_by_this_run(self):
        case, run = self.start()
        unread_receipt = next(item["id"] for item in case["evidence"] if item["kind"] == "receipt")
        provider = self.standard_provider(lambda messages: observed_diagnosis(messages, evidence_override=[unread_receipt]))
        result = investigate(self.domain, run["id"], provider=provider)
        self.assertEqual(result["status"], "failed")
        self.assertIn("did not read", result["error"])
        self.assert_no_action(case["id"])

    def test_cross_case_evidence_cannot_be_cited(self):
        case, run = self.start()
        unrelated = self.domain.create_case("healthy-export")
        provider = self.standard_provider(lambda messages: observed_diagnosis(messages, evidence_override=[unrelated["evidence"][0]["id"]]))
        result = investigate(self.domain, run["id"], provider=provider)
        self.assertEqual(result["status"], "failed")
        self.assert_no_action(case["id"])

    def test_model_cannot_call_mutating_tool_or_replace_target(self):
        for name, args in (("execute_approved_operation", {}), ("read_export_evidence", {"case_id": "other-case"})):
            with self.subTest(name=name):
                case, run = self.start()
                result = investigate(self.domain, run["id"], provider=ScriptedProvider([(name, args)]))
                self.assertEqual(result["status"], "failed")
                self.assert_no_action(case["id"])

    def test_read_evidence_does_not_authorize_wrong_action(self):
        case, run = self.start("authorization-denied")
        result = investigate(self.domain, run["id"], provider=self.standard_provider())
        self.assertEqual(result["status"], "failed")
        self.assert_no_action(case["id"])
        self.assertEqual(self.domain.get_case(case["id"])["target"]["authorized"], False)

    def test_tool_and_model_budgets_stop_before_extra_work(self):
        for budget, expected_models, expected_tools in (({"max_models": 2}, 2, 2), ({"max_tools": 1}, 2, 1)):
            with self.subTest(budget=budget):
                case, run = self.start()
                provider = self.standard_provider()
                result = investigate(self.domain, run["id"], provider=provider, **budget)
                self.assertEqual(result["status"], "failed")
                self.assertIn("budget exhausted", result["error"])
                self.assertEqual(result["model_calls"], expected_models)
                self.assertEqual(result["tool_calls"], expected_tools)
                self.assert_no_action(case["id"])

    def test_cancellation_before_model_request_uses_no_budget(self):
        case, run = self.start()
        self.domain.cancel_run(run["id"])
        provider = self.standard_provider()
        result = investigate(self.domain, run["id"], provider=provider)
        self.assertEqual(result["status"], "cancelled")
        self.assertEqual(provider.requests, [])
        self.assertEqual(result["model_calls"], 0)
        self.assert_no_action(case["id"])

    def test_cancellation_during_model_request_discards_returned_tool_call(self):
        case, run = self.start()
        provider = ScriptedProvider([("read_export_evidence", {})], hook=lambda _: self.domain.cancel_run(run["id"]))
        result = investigate(self.domain, run["id"], provider=provider)
        self.assertEqual(result["status"], "cancelled")
        self.assertEqual(result["tool_calls"], 0)
        self.assertEqual(result["model_calls"], 1)
        self.assert_no_action(case["id"])

    def test_time_budget_rechecked_after_model_request(self):
        case, run = self.start()
        current = [0]
        provider = ScriptedProvider([("read_export_evidence", {})], hook=lambda _: current.__setitem__(0, 5))
        result = investigate(self.domain, run["id"], provider=provider, clock=lambda: current[0], max_seconds=2)
        self.assertEqual(result["status"], "failed")
        self.assertIn("time budget exhausted", result["error"])
        self.assertEqual(result["tool_calls"], 0)
        self.assert_no_action(case["id"])

    def test_untrusted_provider_exception_text_is_not_persisted(self):
        case, run = self.start()
        class BrokenProvider:
            def next(self, messages):
                raise RuntimeError("secret-example-key-and-private-request")
        result = investigate(self.domain, run["id"], provider=BrokenProvider())
        self.assertEqual(result["status"], "failed")
        self.assertNotIn("secret-example", json.dumps(self.domain.get_case(case["id"])))
        self.assert_no_action(case["id"])


if __name__ == "__main__":
    unittest.main()
