export type Role = 'operator' | 'reviewer' | 'observer';
export type Mode = 'fixture' | 'openai';
export interface Config {
  version: string;
  mode: Mode;
  model: string | null;
  live_available: boolean;
  roles: Role[];
  limits: { max_tool_calls: number; max_model_calls: number };
  storage: string;
  coding_mode: string;
}
export interface Scenario {
  id: string;
  title: string;
  description: string;
  category: string;
  severity: string;
  expected_behavior: string;
}
export interface CaseSummary {
  id: string;
  title: string;
  scenario_id: string;
  category: string;
  severity: string;
  status: string;
  order_id: string;
  job_id: string;
  created_at: string;
  updated_at: string;
  revision: number;
  latest_run_status: string | null;
}
export interface Evidence {
  id: string;
  kind: string;
  title: string;
  content: string;
  source: string;
  observed_at: string;
  sha256: string;
}
export interface TimelineEvent {
  id: string;
  kind: string;
  title: string;
  detail: string;
  created_at: string;
}
export interface Run {
  id: string;
  case_id: string;
  status: string;
  mode: Mode;
  created_at: string;
  updated_at: string;
  tool_calls: number;
  model_calls: number;
  error: string | null;
  events: TimelineEvent[];
  usage: Record<string, unknown> | null;
}
export interface Diagnosis {
  summary: string;
  cause: string;
  evidence_ids: string[];
  hypotheses: string[];
  recommendation: string;
  action: string;
}
export interface Proposal {
  id: string;
  case_id: string;
  kind: string;
  title: string;
  description: string;
  status: string;
  hash: string;
  case_revision: number;
  created_at: string;
  expires_at: string;
  approved_by: string | null;
  payload: Record<string, unknown>;
  verification: Record<string, unknown> | null;
}
export interface Operation {
  id: string;
  kind: string;
  status: string;
  idempotency_key: string;
  payload_hash: string;
  receipt: string | null;
  created_at: string;
  updated_at: string;
}
export interface Verification {
  passed: number;
  total: number;
  results: unknown[];
}
export interface Repair {
  status: string;
  mode: Mode;
  language: string;
  filename: string;
  original: string;
  candidate: string;
  diff: string;
  baseline: Verification;
  verification: Verification;
  patch_hash: string;
  explanation: string;
  limitations: string[];
}
export interface CaseDetail extends CaseSummary {
  evidence: Evidence[];
  runs: Run[];
  proposals: Proposal[];
  events: TimelineEvent[];
  operations: Operation[];
  diagnosis: Diagnosis | null;
  repair: Repair | null;
  target: Record<string, unknown>;
}
export interface Evaluation {
  kind: string;
  model_evaluation: boolean;
  generated_at: string | null;
  total: number;
  passed: number;
  results: {
    scenario_id: string;
    title: string;
    expected: unknown;
    actual: unknown;
    passed: boolean;
    duration_ms: number;
  }[];
  limitations: string[];
}
export interface Knowledge {
  id: string;
  title: string;
  body: string;
}
