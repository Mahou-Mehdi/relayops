"""Isolated, deterministic regression evaluation. This is not an LLM benchmark."""

from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from time import perf_counter

from .domain import Domain
from .store import Store
from .scenarios import SCENARIOS
from .workflow import investigate


def evaluate() -> dict:
    results = []
    with TemporaryDirectory(prefix="relayops-eval-") as directory:
        domain = Domain(Store(Path(directory) / "evaluation.sqlite"))
        for scenario in SCENARIOS:
            started = perf_counter()
            case = domain.create_case(scenario["id"])
            run = domain.create_run(case["id"], "fixture")
            investigate(domain, run["id"])
            case = domain.get_case(case["id"])
            diagnosis = case["diagnosis"] or {}
            actual = diagnosis.get("action", "no_diagnosis")
            passed = actual == scenario["action"] and diagnosis.get("cause") == scenario["cause"]
            if actual in {"retry_export", "reconcile_receipt"} and case["proposals"]:
                proposal = case["proposals"][0]
                domain.decide(proposal["id"], "approve", proposal["hash"], "reviewer")
                case = domain.execute(proposal["id"], proposal["hash"], "operator")
                replay = domain.execute(proposal["id"], proposal["hash"], "operator")
                passed = passed and case["status"] == "resolved" and replay["target"]["receipt_count"] == 1
            results.append({"scenario_id": scenario["id"], "title": scenario["title"], "expected": scenario["action"],
                            "actual": actual, "passed": bool(passed), "duration_ms": round((perf_counter() - started) * 1000, 2)})
    return {"kind": "deterministic-regression", "model_evaluation": False, "generated_at": datetime.now(timezone.utc).isoformat(),
            "total": len(results), "passed": sum(result["passed"] for result in results), "results": results,
            "limitations": ["Fixture policy uses explicit observed error codes; this is a regression suite, not a model reasoning benchmark.",
                            "Eight authored fictional scenarios; no held-out statistical generalization claim.",
                            "Live model comparisons and network crash-after-effect recovery are future milestones."]}
