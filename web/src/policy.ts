import type { CaseSummary, Evidence, Proposal, Role, Run } from './types';
export const activeRun = (run: Pick<Run, 'status'>) =>
  ['queued', 'running', 'cancel_requested'].includes(run.status);
export const canOperate = (role: Role) => role === 'operator';
export function proposalPermission(
  role: Role,
  proposal: Proposal,
  revision: number,
  now = Date.now(),
) {
  const deadline = Date.parse(proposal.expires_at);
  const expired = !Number.isFinite(deadline) || deadline <= now;
  const stale = proposal.case_revision !== revision;
  const valid = !expired && !stale && Boolean(proposal.hash);
  return {
    approve: role === 'reviewer' && proposal.status === 'pending' && valid,
    reject: role === 'reviewer' && proposal.status === 'pending' && valid,
    execute: role === 'operator' && proposal.status === 'approved' && valid,
    expired,
    stale,
  };
}
export function citedEvidence(ids: string[], evidence: Evidence[]) {
  const wanted = new Set(ids);
  return evidence.filter((item) => wanted.has(item.id));
}
export function filterCases(cases: CaseSummary[], query: string, status: string) {
  const search = query.trim().toLowerCase();
  return cases.filter(
    (item) =>
      (status === 'all' || item.status === status) &&
      (!search ||
        [item.title, item.id, item.order_id, item.scenario_id].some((value) =>
          (value || '').toLowerCase().includes(search),
        )),
  );
}
export const label = (value: string) =>
  String(value || '')
    .replace(/[_-]/g, ' ')
    .replace(/^\w/, (c) => c.toUpperCase());
