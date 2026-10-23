# RelayOps v0.2 implementation contract

Developer reference for the local, single-process control center and its SQLite operation ledger. PostgreSQL/multi-host scheduling and live SAP writes remain roadmap items. The React/TypeScript frontend calls a FastAPI backend with a LangGraph investigation graph and fixture or OpenAI Responses providers. Fixture mode requires no model key and is explicitly labelled deterministic.

## JSON API used by frontend

Local personas in X-RelayOps-Role header: operator, reviewer, observer. Public demo identities, NOT authentication; localhost only. Default UI operator. Mutations carry X-RelayOps-Request: 1, validated same-origin. Server refuses non-loopback binding and production mode. All timestamps ISO UTC.

- GET /api/config -> {version, mode:'fixture'|'openai', model:string|null, live_available:bool, roles:[...], limits:{max_tool_calls,max_model_calls}, storage:'sqlite', coding_mode:'restricted-expression'}
- GET /api/scenarios -> array {id,title,description,category,severity:'medium'|'high'|'low',expected_behavior}
- GET /api/cases -> array case summaries; newest first
- POST /api/cases {scenario_id} -> case detail
- GET /api/cases/{id} -> case detail
- POST /api/cases/{id}/investigate {mode:'fixture'|'openai'} -> run record (202); polls detail for updates
- POST /api/runs/{id}/cancel {} -> run
- POST /api/proposals/{id}/decision {decision:'approve'|'reject', expected_hash:string} -> case detail; reviewer only; approve records authorization (does not execute)
- POST /api/proposals/{id}/execute {expected_hash:string} -> case detail; operator only
- POST /api/cases/{id}/repair {mode:'fixture'|'openai'} -> case detail; operator; synchronous bounded transform verification
- GET /api/cases/{id}/report -> downloadable JSON (fetch with role header then Blob)
- GET /api/cases/{id}/patch -> downloadable diff; requires an executed export proposal and verification matching the current patch hash
- GET /api/evaluations -> latest saved full report; initial response {id:null,total:0,passed:0,checks_total:0,checks_passed:0,results:[],...}
- GET /api/evaluations/history?limit=20 -> saved report summaries, newest completion first; limit 1–100
- GET /api/evaluations/{id} -> exact saved full report, or 404
- GET /api/evaluations/{id}/report -> exact saved JSON as an attachment
- POST /api/evaluations/run {} -> evaluates and saves a full report; operator only; simulated actions use a temporary database, never the live case history; overlapping run returns 409
- GET /api/knowledge -> array {id,title,body}

Error HTTP 4xx/5xx {detail:string}. Poll every 1s while a run queued/running/cancel_requested; cleanup timers on unmount. Only provider-reported token usage is displayed; no simulated AI cost numbers.

Evaluation summary: {id,generated_at,schema_version:1,suite_version:'2',app_version,kind:'deterministic-regression',model_evaluation:false,total,passed,checks_total,checks_passed,duration_ms}.
Full report adds {results:[{scenario_id,title,expected,actual,passed,duration_ms,run_status,error,checks:[{id,label,passed,expected,actual}]}],limitations:[]}. Counts `total` and `passed` refer to scenarios. `checks_total` and `checks_passed` refer to recorded checks within those scenarios. A scenario exception records a failure and does not abort the other scenarios. No check count is a model-quality score.

Case summary: {id,title,scenario_id,category,severity,status,order_id,job_id,created_at,updated_at,revision,latest_run_status:string|null}
Case detail adds {evidence: Evidence[], runs:Run[], proposals:Proposal[], events:Event[], operations:Operation[], diagnosis:Diagnosis|null, repair:Repair|null, target:object}.
Evidence: {id,kind,title,content:string,source:string,observed_at,sha256}
Run: {id,case_id,status:'queued'|'running'|'completed'|'failed'|'cancel_requested'|'cancelled'|'interrupted',mode,created_at,updated_at,tool_calls:int,model_calls:int,error:string|null,events:[{id,kind,title,detail,created_at}],usage:object|null}
Diagnosis: {summary,cause,evidence_ids:string[],hypotheses:string[],recommendation,action:'retry_export'|'reconcile_receipt'|'prepare_patch'|'escalate'|'none'}
Proposal: {id,case_id,kind:'retry_export'|'reconcile_receipt'|'publish_patch',title,description,status:'pending'|'approved'|'rejected'|'executed'|'expired'|'stale',hash,case_revision,created_at,expires_at,approved_by:string|null,payload:object,verification:object|null}
Event: {id,kind,title,detail,created_at}
Operation: {id,kind,status,idempotency_key,payload_hash,receipt:string|null,created_at,updated_at}
Repair: {status,mode,language:'restricted-expression',filename,original,candidate,diff,baseline:{passed,total,results:[]},verification:{passed,total,results:[]},patch_hash,explanation,limitations:string[]}

## Domain interface

Store(path) SQLite and methods in store.py (thread-safe separate connections). Domain(store) primary facade:
- create_case(scenario_id)->detail; list_cases()->list; get_case(id)->detail
- create_run(case_id, mode)->run (reject active run); get_run(id)->run; update_run(id, **fields); add_run_event(id,kind,title,detail)
- cancel_run(id)->run; run_cancelled(id)->bool
- record_diagnosis(case_id,run_id,diagnosis)->detail; validates evidence IDs and allowed action for CURRENT observed target facts, no unsafe action bypass from model
- decide(proposal_id, decision, expected_hash, role)->detail
- execute(proposal_id, expected_hash, role)->detail
- save_repair(case_id,repair)->detail; creates publish_patch proposal only if independent verifier all-pass and baseline failed
- event(case_id,kind,title,detail)
- add_evidence(case_id,kind,title,content,source)->item; deduplicates matching observations without changing the business revision
- recover_interrupted_runs()->int; stale running/queued runs become interrupted on startup, explicitly rerunnable with prior evidence retained. Approval/operation state survives. Do not claim arbitrary in-flight model execution resumes.
- list_scenarios() module function in scenarios.py.

DomainError(message,status_code=400). All JSON serializable. Scenarios scenario IDs: transient-outage, lost-acknowledgement, mapping-defect, authorization-denied, business-rejection, misleading-log, insufficient-evidence, healthy-export.

Embedded ERP simulator ledger is distinct from operation ledger; immutable key/payload receipt semantics, explicit fictional data. This release uses an in-process deterministic target, not real SAP or network. Lost acknowledgement seeded with target receipt but missing local receipt; execute reconcile recovers it. Targets must be scoped to case/order/job; revision/hash/expiry checks, one operation identity, safe duplicate approval/execute, outcome verification. No real company services accessed.

## Coding interface

repair.py exports prepare_repair(*, candidate:str|None=None, mode:str='fixture')->Repair; and source_context()->dict. A candidate is a decimal mapping expression in a strict allowlisted grammar evaluated by a trusted interpreter; generated code never reaches eval, exec, or subprocess. The original/candidate source diff is a real patch artifact, and protected cases verify transform semantics. Both fixture and live-model candidates pass through the same independent verifier. An isolated general-purpose repository repair runner remains a roadmap item.
