# Restricted transform repair

RelayOps v0.2 implements a small, real part of the planned coding workflow: inspect a decimal mapping expression, propose a change, verify it against independent expectations, and produce a downloadable unified patch. It is a partial foundation for the enterprise incident plus coding workflow, not a general repository-fixing agent.

## What actually runs

The checked-in `fixtures/decimal_mapping.expr` prematurely rounds a line total to an integer. The requested transformation multiplies nonnegative decimal-string quantity and unit price exactly, then rounds the final product to two decimal places using half-up rounding. Fractional quantities and prices with up to six decimal places are supported.

Fixture mode supplies a deterministic known candidate. Live mode requires a model-provided candidate and uses exactly the same parser, interpreter, and verifier; a missing live candidate is rejected rather than replaced with the fixture answer. A different expression can pass if its behavior satisfies the checks. There is no candidate-string equality shortcut.

`source_context()` exposes the original expression, task, filename, and allowed grammar. It does not expose protected inputs, expected answers, or verification reports to the proposal-generating model. The independent verifier loads sixteen static cases from `fixtures/protected_mapping_cases.json`. Their expected answers are hand specified; the candidate interpreter does not compute its own expected answers. Unit tests additionally check those expectations, and 300 seeded inputs, against a separate integer-scaling arithmetic oracle.

Protected here means excluded from the model-visible source-context interface. The cases are public repository files, not a confidential evaluation dataset or a sandbox security boundary. They are regression checks, not proof of correctness on every possible input. Any future iterative repair loop that feeds the test report back to a model must identify those cases as development feedback, not a held-out evaluation.

## Language and execution boundary

This language looks like a tiny JavaScript expression, but it is **not JavaScript**. A trusted Python tokenizer, parser, and interpreter implement only:

```text
expression := term (("+" | "-") term)*
term       := unary (("*" | "/") unary)*
unary      := ("+" | "-") unary | primary
primary    := NUMBER | quantity | unitPrice | "(" expression ")"
            | decimal(expression) | round(expression, SCALE)
NUMBER     := (0 | [1-9][0-9]*)(\.[0-9]+)?
SCALE      := one literal integer in 0..6
```

Arithmetic uses `Decimal` with precision 80. `decimal()` preserves decimal input exactly. `round()` uses `ROUND_HALF_UP`, not JavaScript's binary floating-point or Python's default rounding. Inputs must be decimal strings, nonnegative, at most `1e18`, with up to six decimal places. Unary minus and arithmetic may create negative intermediate values, but the mapping task has nonnegative inputs.

The interpreter never calls `eval`, `exec`, a shell, a subprocess, or a JavaScript engine with candidate content. Expressions cannot access objects, properties, files, the network, environment variables, modules, or other tools. Strings, arrays, statements, assignments, comments, exponent notation, and any unlisted identifiers are rejected. Intermediate and final magnitudes above `1e40`, nonfinite results, and division by zero fail verification.

Bounds are enforced before evaluation: 512 source characters, 128 tokens, 64 syntax-tree nodes, and 16 levels of syntactic nesting. Numeric literals are at most 32 characters and at most `1e18`. Values use a bounded decimal precision. These constraints limit work inside the trusted interpreter; they are not claims about isolation of arbitrary executable code.

**No Docker sandbox or arbitrary-code sandbox is present in this release.** General repository repair would require a separate isolated runner with controlled filesystem mounts, network access, credentials, resource limits, and independent tests. That runner is a roadmap item.

## Verification and artifact

`prepare_repair(candidate=None, mode="fixture")` returns a JSON-compatible report:

- `verified`: the original fails at least one protected test, the changed candidate passes every test, and a real diff exists.
- `failed`: the expression parses but fails at least one protected test.
- `rejected`: the candidate violates the language or resource bounds, or a live candidate is missing. It is not interpreted and has no patch.

The report contains original and candidate expression text, individual baseline and candidate outcomes, a standard unified diff targeting only `fixtures/decimal_mapping.expr`, and SHA-256 of the UTF-8 diff. The hash identifies the exact patch bytes; it is not an author signature. Preparing a report changes no files. A rejected report has an empty diff and the SHA-256 of those empty bytes.

The domain layer independently re-runs verification before storing a repair proposal. Approval and execution concern publishing/exporting the verified artifact, not deployment. A patch is not a compatible drop-in JavaScript expression: applying it changes the restricted-language fixture, which must be consumed by this interpreter or a future equivalent implementation.

## Checks

From the repository root, run:

```console
python -m pytest tests/test_repair.py -q
```

The suite covers real diff/hash generation, failing baseline versus passing repair, fixed protected cases, half-cent ties, final-product rounding, values above binary-float integer precision, alternative correct expressions, incorrect patches, syntax injection, coercion rejection, resource limits, invalid arithmetic, model-context separation, and deterministic reports. These are component regression tests; they do not measure autonomous coding success or live-model quality.
