# Security and trust boundaries

RelayOps v0.1 is a **local development demonstration**. It uses fictional incidents and an in-process fictional ERP. It is not designed for internet exposure, production credentials, real business execution, or hostile users sharing the local machine.

## Local personas are not authentication

Operator, Reviewer, and Observer are public values in the `X-RelayOps-Role` header. They demonstrate API authorization and a two-step approval/execution workflow, but anyone able to call the local API can select a persona. This is not an authenticated separation-of-duties system.

Use the supported `python -m relayops` launcher, which binds to `127.0.0.1` with one server process. Do not expose it through a public tunnel, reverse proxy, or alternate non-loopback server command. The application rejects a non-local `RELAYOPS_ENV`, checks local Host names, requires a custom mutation header, validates browser write origins, and sets browser security headers. Those controls do not replace identity, tenant isolation, or machine access controls.

## Model and tool authority

The investigation gateway permits only scoped evidence reads, receipt lookup, local runbook search, bounded source inspection, and diagnosis submission. The selected case comes from the persisted run, not model-controlled target arguments. The model has no approve, execute, arbitrary HTTP, filesystem, or shell tool.

Logs, runbooks, source text, and tool responses are untrusted evidence. The system prompt expresses that distinction, but application enforcement is also necessary: the domain validates current target facts, allowed actions, evidence identity, proposal hashes, expiry, and revisions. It separately requires Reviewer approval and Operator execution. A valid citation ID does not establish the truth of an entire generated explanation.

## Effects and recovery

Repeated local operations are constrained by unique operation/receipt identities and SQLite transactions. The fictional target shares the application's database. This release does not promise exactly-once effects or crash-after-effect recovery against a remote API. Starting the server again marks unfinished investigations interrupted; it does not restore an arbitrary model continuation.

Case/event records and SHA-256 values provide workflow evidence, not tamper-proof storage. An attacker with filesystem/database access is outside this release's trust boundary.

## Coding boundary

Candidate repairs are expressions in a strict allowlisted language interpreted by trusted application code. They never enter `eval`, `exec`, a shell, or a JavaScript runtime. Size, token, node, nesting, input, and numeric bounds limit work. Independent expected outputs are excluded from the model's proposal context, and the domain re-verifies a candidate before creating an export proposal.

This is not an arbitrary-code sandbox. The public protected cases are regression evidence, not secret tests. A verified patch is exported for review; it is not applied to a repository or deployed. See [the detailed coding boundary](docs/coding-boundary.md).

## Credentials and data

- Fixture mode requires no API key and makes no model-provider request.
- Live mode requires `OPENAI_API_KEY` and `RELAYOPS_MODEL` in the server environment. `.env` files are not automatically loaded.
- The provider uses a fixed HTTPS API endpoint and does not send credentials to the browser. Do not include credentials in cases, runbooks, tests, screenshots, or committed files.
- Live mode sends selected evidence and source context to the provider. `store: false` is requested, but this is not a substitute for checking your provider/account retention settings and permitted data use.
- The SQLite database and downloaded reports contain case evidence and model output. They are local application data, not encrypted archives. Use fictional data for this release.
- Investigation limits bound calls and step time; there is no monetary spending cap. Live repair is a separate provider request.

## Reporting an issue

For a security issue, use GitHub's private vulnerability reporting from this repository's Security page if that option is available. Otherwise, open a minimal issue requesting a private reporting channel without posting credentials, private data, or exploit details. Include the affected commit/version and a reproduction using fictional data when a private channel is established.

Ordinary bugs and non-sensitive reproducible failures can be reported as repository issues. No response-time or production-support commitment is implied.
