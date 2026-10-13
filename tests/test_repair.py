"""Executable checks of the restricted repair boundary, without a model key."""

from decimal import Decimal
import hashlib
import json
from pathlib import Path
import random
import unittest

from relayops.repair import (
    DEFAULT_CANDIDATE,
    ExpressionError,
    MAX_SOURCE_LENGTH,
    evaluate_expression,
    prepare_repair,
    source_context,
)


FIXTURES = Path(__file__).resolve().parent.parent / "fixtures"


def integer_money_oracle(quantity: str, price: str) -> Decimal:
    """Independent expected arithmetic: integer scaling, not the interpreter."""
    def parts(text: str) -> tuple[int, int]:
        whole, separator, fraction = text.partition(".")
        return int(whole + fraction), len(fraction) if separator else 0

    quantity_units, quantity_scale = parts(quantity)
    price_units, price_scale = parts(price)
    denominator = 10 ** (quantity_scale + price_scale)
    cents, remainder = divmod(quantity_units * price_units * 100, denominator)
    if remainder * 2 >= denominator:
        cents += 1
    return Decimal(f"{cents // 100}.{cents % 100:02d}")


class RepairTests(unittest.TestCase):
    def test_actual_patch_repairs_failing_baseline(self):
        original_bytes = (FIXTURES / "decimal_mapping.expr").read_bytes()
        report = prepare_repair()
        self.assertEqual(report["status"], "verified")
        self.assertEqual(report["mode"], "fixture")
        self.assertEqual(report["language"], "restricted-expression")
        self.assertEqual(report["verification"]["passed"], report["verification"]["total"])
        self.assertGreater(report["baseline"]["passed"], 0)
        self.assertLess(report["baseline"]["passed"], report["baseline"]["total"])
        self.assertEqual(report["verification"]["total"], 16)
        self.assertEqual(report["patch_hash"], hashlib.sha256(report["diff"].encode()).hexdigest())
        self.assertEqual(report["diff"], (
            "--- a/fixtures/decimal_mapping.expr\n"
            "+++ b/fixtures/decimal_mapping.expr\n"
            "@@ -1 +1 @@\n"
            "-round(decimal(quantity) * decimal(unitPrice), 0)\n"
            "+round(decimal(quantity) * decimal(unitPrice), 2)\n"
        ))
        self.assertEqual((FIXTURES / "decimal_mapping.expr").read_bytes(), original_bytes)
        json.dumps(report, allow_nan=False)

    def test_protected_expectations_match_independent_integer_arithmetic(self):
        cases = json.loads((FIXTURES / "protected_mapping_cases.json").read_text(encoding="utf-8"))
        for case in cases:
            with self.subTest(case=case["name"]):
                self.assertEqual(Decimal(case["expected"]), integer_money_oracle(case["quantity"], case["unitPrice"]))

    def test_live_candidate_has_same_verification_and_no_silent_fixture_fallback(self):
        live = prepare_repair(candidate=DEFAULT_CANDIDATE, mode="openai")
        fixture = prepare_repair()
        self.assertEqual(live["status"], "verified")
        self.assertEqual(live["verification"], fixture["verification"])
        self.assertEqual(live["patch_hash"], fixture["patch_hash"])
        missing = prepare_repair(mode="openai")
        self.assertEqual(missing["status"], "rejected")
        self.assertIn("no fixture fallback", missing["explanation"])

    def test_context_contains_task_and_grammar_but_no_protected_examples(self):
        context = source_context()
        self.assertEqual(set(context), {"filename", "original", "task", "allowed_grammar", "language"})
        self.assertIn("ROUND_HALF_UP", context["allowed_grammar"])
        self.assertIn("two decimal places", context["task"])
        serialized = json.dumps(context)
        for private_detail in ("protected_mapping_cases", "9007199254740993", "half_cent_rounds_up", "30.85"):
            self.assertNotIn(private_detail, serialized)

    def test_wrong_patches_are_exercised_and_fail(self):
        wrong = [
            "round(decimal(quantity) * decimal(unitPrice), 0)",
            "round(decimal(quantity) * decimal(unitPrice), 3)",
            "round(decimal(quantity), 2) * round(decimal(unitPrice), 2)",
            "decimal(quantity) * decimal(unitPrice)",
            "round(decimal(quantity) + decimal(unitPrice), 2)",
            "0",
            "1 / 0",
        ]
        for candidate in wrong:
            with self.subTest(candidate=candidate):
                report = prepare_repair(candidate=candidate)
                self.assertEqual(report["status"], "failed")
                self.assertLess(report["verification"]["passed"], report["verification"]["total"])

    def test_alternative_correct_expression_uses_semantics_not_string_matching(self):
        report = prepare_repair(candidate="round(unitPrice * quantity + 0, 2)")
        self.assertEqual(report["status"], "verified")
        self.assertNotEqual(report["candidate"], DEFAULT_CANDIDATE)

    def test_rejects_injection_and_unsupported_language(self):
        attacks = [
            "__import__('os').system('echo unsafe')",
            "process.exit()", "globalThis.fetch('https://example.com')",
            "quantity.constructor.constructor('return process')()",
            "quantity; unitPrice", "quantity = 1", "quantity ** 2", "quantity % 2",
            "Math.round(quantity * unitPrice)", "Number(quantity)", "parseFloat(unitPrice)",
            "round(quantity * unitPrice, 2); require('fs')",
            "round(quantity * unitPrice, 2) // ignore tests",
            "/* approved */ round(quantity * unitPrice, 2)",
            "[quantity][0]", "{quantity: 1}", "quantity['value']",
            "`quantity`", "'quantity'", '"quantity"', "1e309", "NaN", "Infinity",
            "quantity && unitPrice", "quantity ? 1 : 0", "quantity => unitPrice",
            "quantity\u200b", "quаntity", "quantity\x00", "quantity # comment",
            "round(quantity, 2, 3)", "round(quantity, -1)", "round(quantity, 7)",
            "round(quantity, 1 + 1)", "round(quantity, quantity)", "decimal(quantity, unitPrice)",
        ]
        for candidate in attacks:
            with self.subTest(candidate=candidate):
                report = prepare_repair(candidate=candidate)
                self.assertEqual(report["status"], "rejected")
                self.assertEqual(report["diff"], "")
                self.assertEqual(report["verification"]["passed"], 0)

    def test_resource_limits_and_malformed_candidates_are_rejected(self):
        candidates = [
            " " * MAX_SOURCE_LENGTH + "1",
            "(" * 17 + "quantity" + ")" * 17,
            "-" * 17 + "1",
            "+".join(["1"] * 65),
            "9" * 33,
            "1000000000000000001",
            "", "   ", "()", "quantity +", "round(quantity)", "01", "1..2",
            "1 2", "quantity unitPrice", "round(quantity, 2", "decimal()",
        ]
        for candidate in candidates:
            with self.subTest(candidate=candidate):
                self.assertEqual(prepare_repair(candidate=candidate)["status"], "rejected")
        self.assertEqual(prepare_repair(candidate=42)["status"], "rejected")

    def test_invalid_math_is_bounded_and_reported(self):
        for source in ("1 / 0", "1000000000000000000 * 1000000000000000000 * 1000000000000000000"):
            with self.subTest(source=source):
                with self.assertRaises(ExpressionError):
                    evaluate_expression(source, quantity="1", unit_price="1")

    def test_parser_precedence_parentheses_unary_and_division(self):
        cases = {"1 + 2 * 3": "7", "(1 + 2) * 3": "9", "-1 + +2": "1", "8 / 2 / 2": "2", "5 - 2 - 1": "2"}
        for source, expected in cases.items():
            with self.subTest(source=source):
                self.assertEqual(evaluate_expression(source, quantity="1", unit_price="1"), Decimal(expected))

    def test_interpreter_preserves_values_above_float_integer_precision(self):
        result = evaluate_expression(DEFAULT_CANDIDATE, quantity="9007199254740993", unit_price="0.01")
        self.assertEqual(result, Decimal("90071992547409.93"))

    def test_many_inputs_against_integer_oracle(self):
        randomizer = random.Random(731)
        for _ in range(300):
            quantity = f"{randomizer.randrange(0, 1000000)}.{randomizer.randrange(0, 1000000):06d}"
            price = f"{randomizer.randrange(0, 10000)}.{randomizer.randrange(0, 1000000):06d}"
            self.assertEqual(
                evaluate_expression(DEFAULT_CANDIDATE, quantity=quantity, unit_price=price),
                integer_money_oracle(quantity, price),
            )

    def test_input_contract_refuses_implicit_number_coercion(self):
        for value in (1.5, "NaN", "Infinity", "1e3", "-1", "01", "1.0000001", "1000000000000000001", "1;2"):
            with self.subTest(value=value):
                with self.assertRaises(ExpressionError):
                    evaluate_expression(DEFAULT_CANDIDATE, quantity=value, unit_price="1")

    def test_mode_validation_and_deterministic_artifact(self):
        with self.assertRaises(ValueError):
            prepare_repair(mode="pretend-sandbox")
        self.assertEqual(prepare_repair(), prepare_repair())


if __name__ == "__main__":
    unittest.main()
