"""Verify one restricted decimal mapping expression; never execute generated code.

This is an interpreter for a small, documented expression language. It is not a
JavaScript runtime, general code sandbox, or arbitrary repository repair agent.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, DecimalException, ROUND_HALF_UP, localcontext
import difflib
import hashlib
import json
from pathlib import Path
import re
from typing import Any


FIXTURES = Path(__file__).resolve().parent.parent / "fixtures"
FILENAME = "fixtures/decimal_mapping.expr"
MAX_SOURCE_LENGTH = 512
MAX_TOKENS = 128
MAX_NODES = 64
MAX_DEPTH = 16
MAX_MAGNITUDE = Decimal("1e40")
MAX_INPUT = Decimal("1e18")
DEFAULT_CANDIDATE = "round(decimal(quantity) * decimal(unitPrice), 2)"
_NUMBER = re.compile(r"(?:0|[1-9][0-9]*)(?:\.[0-9]+)?", re.ASCII)
_IDENTIFIER = re.compile(r"[A-Za-z_][A-Za-z_0-9]*", re.ASCII)
_INPUT = re.compile(r"(?:0|[1-9][0-9]*)(?:\.[0-9]{1,6})?", re.ASCII)
_SYMBOLS = frozenset("+-*/(),")

GRAMMAR = """expression := term ((\"+\" | \"-\") term)*
term       := unary ((\"*\" | \"/\") unary)*
unary      := (\"+\" | \"-\") unary | primary
primary    := NUMBER | quantity | unitPrice | \"(\" expression \")\"
            | decimal( expression ) | round( expression, SCALE )
NUMBER     := (0 | [1-9][0-9]*)(.[0-9]+)?  [literal decimal point]
SCALE      := one literal integer in 0..6
Only ASCII identifiers/operators and ASCII whitespace are supported.
No strings, properties, arrays, comments, assignments, exponent notation, or
other calls exist. Both inputs are nonnegative decimal strings, at most 1e18,
with at most six decimal places. All values use Decimal with precision 80;
round uses ROUND_HALF_UP. decimal converts inputs exactly (never binary float).
The requested result is the product rounded ONCE to two decimal places.
Limits: 512 source characters, 128 tokens, 64 AST nodes, nesting 16; absolute
intermediate/result values must not exceed 1e40. This is NOT JavaScript."""

LIMITATIONS = [
    "Restricted expression repair only: no arbitrary JavaScript, Python, shell, or repository code executes.",
    "The fixture provider proposes a deterministic known correction; it is not an AI coding benchmark.",
    "Sixteen fixed protected checks provide regression evidence, not a proof of correctness for every input.",
    "Protected means excluded from the model's source-context tool, not secret or cryptographically isolated; the cases are public in this repository.",
    "The artifact is a proposed expression-file patch. It is not deployed or applied to an external system.",
]


class ExpressionError(ValueError):
    """A candidate is outside the language or cannot be evaluated safely."""


@dataclass(frozen=True)
class _Node:
    kind: str
    value: str = ""
    children: tuple[_Node, ...] = ()


def _tokens(source: str) -> list[str]:
    if not isinstance(source, str):
        raise ExpressionError("Candidate must be a string.")
    if not source or len(source) > MAX_SOURCE_LENGTH:
        raise ExpressionError(f"Candidate must contain 1..{MAX_SOURCE_LENGTH} characters.")
    tokens: list[str] = []
    position = 0
    while position < len(source):
        char = source[position]
        if char in " \t\r\n":
            position += 1
            continue
        if char in _SYMBOLS:
            token = char
        else:
            match = _NUMBER.match(source, position) or _IDENTIFIER.match(source, position)
            if match is None:
                raise ExpressionError(f"Unsupported character at offset {position}.")
            token = match.group()
        tokens.append(token)
        if len(tokens) > MAX_TOKENS:
            raise ExpressionError("Candidate exceeds the token limit.")
        position += len(token)
    if not tokens:
        raise ExpressionError("Candidate has no expression.")
    return tokens


class _Parser:
    def __init__(self, source: str):
        self.tokens = _tokens(source)
        self.position = 0
        self.nodes = 0

    def peek(self) -> str | None:
        return self.tokens[self.position] if self.position < len(self.tokens) else None

    def take(self, expected: str | None = None) -> str:
        token = self.peek()
        if token is None or (expected is not None and token != expected):
            raise ExpressionError(f"Expected {expected or 'an expression'}.")
        self.position += 1
        return token

    def node(self, kind: str, value: str = "", *children: _Node) -> _Node:
        self.nodes += 1
        if self.nodes > MAX_NODES:
            raise ExpressionError("Candidate exceeds the expression-node limit.")
        return _Node(kind, value, children)

    @staticmethod
    def check_depth(depth: int) -> None:
        if depth > MAX_DEPTH:
            raise ExpressionError("Candidate exceeds the nesting limit.")

    def parse(self) -> _Node:
        node = self.expression(0)
        if self.peek() is not None:
            raise ExpressionError("Unexpected trailing token.")
        return node

    def expression(self, depth: int) -> _Node:
        self.check_depth(depth)
        result = self.term(depth)
        while self.peek() in ("+", "-"):
            operator = self.take()
            result = self.node("binary", operator, result, self.term(depth))
        return result

    def term(self, depth: int) -> _Node:
        result = self.unary(depth)
        while self.peek() in ("*", "/"):
            operator = self.take()
            result = self.node("binary", operator, result, self.unary(depth))
        return result

    def unary(self, depth: int) -> _Node:
        self.check_depth(depth)
        if self.peek() in ("+", "-"):
            operator = self.take()
            return self.node("unary", operator, self.unary(depth + 1))
        return self.primary(depth)

    def primary(self, depth: int) -> _Node:
        self.check_depth(depth)
        token = self.take()
        if token == "(":
            child = self.expression(depth + 1)
            self.take(")")
            return child
        if _NUMBER.fullmatch(token):
            if len(token) > 32:
                raise ExpressionError("Numeric literal is too long.")
            value = Decimal(token)
            if value > MAX_INPUT:
                raise ExpressionError("Numeric literal exceeds 1e18.")
            return self.node("number", token)
        if token in ("quantity", "unitPrice"):
            return self.node("variable", token)
        if token in ("decimal", "round"):
            self.take("(")
            child = self.expression(depth + 1)
            scale = ""
            if token == "round":
                self.take(",")
                scale = self.take()
                if scale not in tuple(str(value) for value in range(7)):
                    raise ExpressionError("Rounding scale must be one literal integer from 0 through 6.")
            self.take(")")
            return self.node(token, scale, child)
        raise ExpressionError("Only quantity, unitPrice, decimal, and round identifiers are supported.")


def _input_decimal(value: str) -> Decimal:
    if not isinstance(value, str) or len(value) > 32 or not _INPUT.fullmatch(value):
        raise ExpressionError("Inputs must be nonnegative decimal strings with at most six decimal places.")
    result = Decimal(value)
    if result > MAX_INPUT:
        raise ExpressionError("Input exceeds 1e18.")
    return result


def _interpret(node: _Node, inputs: dict[str, Decimal]) -> Decimal:
    if node.kind == "number":
        result = Decimal(node.value)
    elif node.kind == "variable":
        result = inputs[node.value]
    else:
        first = _interpret(node.children[0], inputs)
        if node.kind == "decimal":
            result = first
        elif node.kind == "round":
            result = first.quantize(Decimal(1).scaleb(-int(node.value)), rounding=ROUND_HALF_UP)
        elif node.kind == "unary":
            result = first if node.value == "+" else -first
        elif node.kind == "binary":
            second = _interpret(node.children[1], inputs)
            if node.value == "+":
                result = first + second
            elif node.value == "-":
                result = first - second
            elif node.value == "*":
                result = first * second
            else:
                result = first / second
        else:  # Only trusted parser-produced nodes reach this interpreter.
            raise ExpressionError("Unsupported expression node.")
    if not result.is_finite() or abs(result) > MAX_MAGNITUDE:
        raise ExpressionError("Expression produced an out-of-range value.")
    return result


def _evaluate_tree(tree: _Node, quantity: str, unit_price: str) -> Decimal:
    inputs = {"quantity": _input_decimal(quantity), "unitPrice": _input_decimal(unit_price)}
    try:
        with localcontext() as context:
            context.prec = 80
            context.rounding = ROUND_HALF_UP
            return _interpret(tree, inputs)
    except DecimalException as error:
        raise ExpressionError("Expression produced an invalid decimal operation.") from error


def evaluate_expression(source: str, *, quantity: str, unit_price: str) -> Decimal:
    """Evaluate the allowlisted language, useful for independent tests/tools."""
    return _evaluate_tree(_Parser(source).parse(), quantity, unit_price)


def source_context() -> dict[str, Any]:
    """The entire model-visible coding context; deliberately excludes test data."""
    return {
        "filename": FILENAME,
        "original": (FIXTURES / "decimal_mapping.expr").read_text(encoding="utf-8").strip(" \t\r\n"),
        "task": (
            "Repair this line-total mapping. Inputs quantity and unitPrice are decimal strings. "
            "Multiply exactly, then round the final product to two decimal places using half-up "
            "rounding. Preserve fractional quantities and decimal precision. Return only an expression "
            "in the allowed grammar, without Markdown, explanations, or source-file changes."
        ),
        "allowed_grammar": GRAMMAR,
        "language": "restricted-expression",
    }


def _protected_cases() -> list[dict[str, str]]:
    # Static hand-checked expected results, not derived by the candidate parser.
    return json.loads((FIXTURES / "protected_mapping_cases.json").read_text(encoding="utf-8"))


def _verify(tree: _Node, cases: list[dict[str, str]]) -> dict[str, Any]:
    results = []
    for case in cases:
        error = None
        actual = None
        try:
            value = _evaluate_tree(tree, case["quantity"], case["unitPrice"])
            actual = format(value, "f")
            passed = value == Decimal(case["expected"])
        except ExpressionError as failure:
            error = str(failure)
            passed = False
        results.append({
            "name": case["name"], "passed": passed,
            "actual": actual, "expected": case["expected"], "error": error,
        })
    return {"passed": sum(item["passed"] for item in results), "total": len(results), "results": results}


def prepare_repair(*, candidate: str | None = None, mode: str = "fixture") -> dict[str, Any]:
    """Prepare a real unified patch, then independently verify its expression.

    Invalid syntax returns a rejected report. Valid but incorrect expressions
    return a failed report. Only a changed expression passing every protected
    case can return verified. No files are changed by this function.
    """
    if mode not in ("fixture", "openai"):
        raise ValueError("Repair mode must be fixture or openai.")
    original = source_context()["original"]
    cases = _protected_cases()
    baseline = _verify(_Parser(original).parse(), cases)
    error = None
    if candidate is None:
        if mode == "fixture":
            candidate = DEFAULT_CANDIDATE
        else:
            candidate = ""
            error = "Live mode requires a model-provided candidate; no fixture fallback is used."
    normalized = candidate.strip(" \t\r\n") if isinstance(candidate, str) else ""
    tree = None
    try:
        if error is not None:
            raise ExpressionError(error)
        # Check the original input, before whitespace removal, against size limits.
        tree = _Parser(candidate).parse()
    except ExpressionError as failure:
        error = str(failure)
    diff = ""
    if tree is not None:
        diff = "".join(difflib.unified_diff(
            (original + "\n").splitlines(keepends=True),
            (normalized + "\n").splitlines(keepends=True),
            fromfile="a/" + FILENAME, tofile="b/" + FILENAME,
        ))
        verification = _verify(tree, cases)
        verified = (
            bool(diff) and baseline["passed"] < baseline["total"]
            and verification["total"] > 0 and verification["passed"] == verification["total"]
        )
        status = "verified" if verified else "failed"
        explanation = (
            "The expression passes every protected check; the original fails decimal-rounding checks. "
            "The patch changes only the mapping expression and has not been applied."
            if verified else "The candidate is valid syntax but does not repair all protected cases."
        )
    else:
        status = "rejected"
        verification = {"passed": 0, "total": len(cases), "results": [
            {"name": case["name"], "passed": False, "actual": None, "expected": case["expected"],
             "error": "Not executed: candidate rejected by language validation."}
            for case in cases
        ]}
        explanation = error or "Candidate rejected by language validation."
    return {
        "status": status, "mode": mode, "language": "restricted-expression", "filename": FILENAME,
        "original": original, "candidate": normalized[:MAX_SOURCE_LENGTH], "diff": diff,
        "baseline": baseline, "verification": verification,
        "patch_hash": hashlib.sha256(diff.encode("utf-8")).hexdigest(),
        "explanation": explanation, "limitations": list(LIMITATIONS),
    }
