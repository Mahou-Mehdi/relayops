import { describe, it, expect } from 'vitest';
import { activeRun, canOperate, proposalPermission, citedEvidence, filterCases } from './policy';
import type { Proposal, CaseSummary, Evidence } from './types';
const proposal = {
  status: 'pending',
  hash: 'verified-hash',
  case_revision: 3,
  expires_at: '2030-01-01T00:00:00Z',
} as Proposal;
const now = Date.parse('2026-10-13T12:00:00Z');
describe('role and approval boundaries', () => {
  it('operators cannot approve their own execution requests', () => {
    expect(proposalPermission('operator', proposal, 3, now).approve).toBe(false);
  });
  it('reviewers approve but cannot execute', () => {
    expect(proposalPermission('reviewer', proposal, 3, now).approve).toBe(true);
    expect(
      proposalPermission('reviewer', { ...proposal, status: 'approved' }, 3, now).execute,
    ).toBe(false);
  });
  it('operators execute only an approved exact-current proposal', () => {
    expect(
      proposalPermission('operator', { ...proposal, status: 'approved' }, 3, now).execute,
    ).toBe(true);
    expect(
      proposalPermission('operator', { ...proposal, status: 'approved' }, 4, now).execute,
    ).toBe(false);
  });
  it('expired, malformed, rejected and hashless proposals cannot execute', () => {
    for (const changed of [
      { expires_at: '2020-01-01' },
      { expires_at: 'invalid' },
      { status: 'rejected' },
      { hash: '' },
    ])
      expect(
        proposalPermission('operator', { ...proposal, status: 'approved', ...changed }, 3, now)
          .execute,
      ).toBe(false);
  });
  it('observers cannot mutate', () => {
    expect(canOperate('observer')).toBe(false);
    expect(Object.values(proposalPermission('observer', proposal, 3, now)).slice(0, 3)).toEqual([
      false,
      false,
      false,
    ]);
  });
});
describe('case rendering and polling', () => {
  it('polls only unfinished run states', () => {
    for (const status of ['queued', 'running', 'cancel_requested'])
      expect(activeRun({ status })).toBe(true);
    for (const status of ['completed', 'failed', 'cancelled', 'interrupted'])
      expect(activeRun({ status })).toBe(false);
  });
  it('citations cannot resolve to invented evidence', () => {
    const evidence = [{ id: 'known', title: 'Record' }] as Evidence[];
    expect(citedEvidence(['missing', 'known', 'known'], evidence)).toEqual(evidence);
  });
  it('combines case search with status filters', () => {
    const cases = [
      {
        id: 'a',
        title: 'Lost receipt',
        status: 'new',
        order_id: 'PO-10',
        scenario_id: 'lost-acknowledgement',
      },
      {
        id: 'b',
        title: 'Gateway issue',
        status: 'resolved',
        order_id: 'PO-11',
        scenario_id: 'transient',
      },
    ] as CaseSummary[];
    expect(filterCases(cases, ' po-10 ', 'new')).toHaveLength(1);
    expect(filterCases(cases, 'receipt', 'resolved')).toHaveLength(0);
  });
});
