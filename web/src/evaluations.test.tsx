import { renderToStaticMarkup } from 'react-dom/server';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { downloadEvaluationReport } from './api';
import { EvaluationResults } from './EvaluationPanel';
import { evaluationReducer, initialEvaluationState } from './evaluations';
import type { Evaluation } from './types';

const report = (id: string): Evaluation => ({
  id,
  schema_version: 1,
  suite_version: '2',
  app_version: '0.2.0',
  kind: 'deterministic-regression',
  model_evaluation: false,
  generated_at: '2026-10-23T10:00:00Z',
  total: 2,
  passed: 1,
  checks_total: 3,
  checks_passed: 1,
  duration_ms: 123,
  results: [
    {
      scenario_id: 'lost-acknowledgement',
      title: 'Lost acknowledgement',
      expected: { action: 'reconcile_receipt' },
      actual: null,
      passed: false,
      duration_ms: 100,
      run_status: 'failed',
      error: 'Investigation failed: receipt lookup unavailable.',
      checks: [
        {
          id: 'workflow-completed',
          label: 'Investigation completes',
          passed: false,
          expected: 'completed',
          actual: 'failed',
        },
        {
          id: 'receipt-count',
          label: 'Only one receipt exists',
          passed: false,
          expected: 1,
          actual: 2,
        },
      ],
    },
    {
      scenario_id: 'healthy-export',
      title: 'Healthy export',
      expected: { action: 'none' },
      actual: { action: 'none' },
      passed: true,
      duration_ms: 23,
      run_status: 'completed',
      error: null,
      checks: [
        { id: 'no-write', label: 'No recovery write', passed: true, expected: 0, actual: 0 },
      ],
    },
  ],
  limitations: ['Authored simulations; not a model-quality benchmark.'],
});

describe('saved regression selection', () => {
  it('opens the newest saved run and preserves an older selection when history refreshes', () => {
    const history = [report('new'), report('old')];
    let state = evaluationReducer(initialEvaluationState, { type: 'history-loaded', history });
    expect(state.selectedId).toBe('new');
    state = evaluationReducer(state, { type: 'select', id: 'old' });
    state = evaluationReducer(state, { type: 'report-loaded', id: 'old', report: report('old') });
    state = evaluationReducer(state, {
      type: 'history-loaded',
      history: [report('newer'), ...history],
    });
    expect(state.selectedId).toBe('old');
    expect(state.report?.id).toBe('old');
  });

  it('never shows or downloads the previous report while a newly selected one loads', () => {
    let state = evaluationReducer(initialEvaluationState, {
      type: 'history-loaded',
      history: [report('new'), report('old')],
    });
    state = evaluationReducer(state, { type: 'report-loaded', id: 'new', report: report('new') });
    state = evaluationReducer(state, { type: 'select', id: 'old' });
    expect(state.report).toBeNull();
    expect(state.reportLoading).toBe(true);
    state = evaluationReducer(state, { type: 'report-loaded', id: 'new', report: report('new') });
    state = evaluationReducer(state, {
      type: 'report-error',
      id: 'new',
      error: 'Late network failure',
    });
    expect(state.report).toBeNull();
    expect(state.reportError).toBe('');
    state = evaluationReducer(state, { type: 'report-loaded', id: 'old', report: report('old') });
    expect(state.report?.id).toBe('old');
    expect(state.reportLoading).toBe(false);
  });

  it('shows a report failure without silently replacing it with the latest report', () => {
    let state = evaluationReducer(initialEvaluationState, {
      type: 'history-loaded',
      history: [report('new'), report('old')],
    });
    state = evaluationReducer(state, { type: 'select', id: 'old' });
    state = evaluationReducer(state, {
      type: 'report-error',
      id: 'old',
      error: 'Report unavailable',
    });
    expect(state.selectedId).toBe('old');
    expect(state.report).toBeNull();
    expect(state.reportLoading).toBe(false);
    expect(state.reportError).toBe('Report unavailable');
    state = evaluationReducer(state, { type: 'report-loading', id: 'old' });
    expect(state.reportError).toBe('');
    expect(state.reportLoading).toBe(true);
  });

  it('selects the newly saved run and rejects late content from the previous selection', () => {
    let state = evaluationReducer(initialEvaluationState, {
      type: 'history-loaded',
      history: [report('old')],
    });
    state = evaluationReducer(state, { type: 'saved', report: report('fresh') });
    state = evaluationReducer(state, { type: 'report-loaded', id: 'old', report: report('old') });
    expect(state.history.map((entry) => entry.id)).toEqual(['fresh', 'old']);
    expect(state.report?.id).toBe('fresh');
    expect(state.selectedId).toBe('fresh');
    expect(state.historyLoading || state.reportLoading).toBe(false);
  });

  it('distinguishes an empty history from a failed history request', () => {
    const empty = evaluationReducer(initialEvaluationState, {
      type: 'history-loaded',
      history: [],
    });
    const failed = evaluationReducer(initialEvaluationState, {
      type: 'history-error',
      error: 'Connection lost',
    });
    expect(empty.selectedId).toBeNull();
    expect(empty.historyLoading).toBe(false);
    expect(empty.historyError).toBe('');
    expect(failed.historyError).toBe('Connection lost');
    expect(failed.historyLoading).toBe(false);
  });
});

describe('regression evidence rendering', () => {
  it('separates scenario totals from check totals and opens failed scenarios with exact evidence', () => {
    const html = renderToStaticMarkup(<EvaluationResults report={report('saved')} />);
    expect(html).toContain('Scenarios passed');
    expect(html).toContain('Individual checks passed');
    expect(html).toContain(' / 2');
    expect(html).toContain(' / 3');
    expect(html).toMatch(/evaluation-scenario failed" open=""/);
    expect(html).toContain('Investigation failed: receipt lookup unavailable.');
    expect(html).toContain('Only one receipt exists');
    expect(html).toContain('<pre>1</pre>');
    expect(html).toContain('<pre>2</pre>');
    expect(html).toContain('0/2 checks');
    expect(html).toContain('1/1 checks');
    expect(html).toContain('Authored simulations; not a model-quality benchmark.');
  });

  it('renders a failed scenario that stopped before collecting checks and escapes its error', () => {
    const failed = report('failed');
    failed.results[0] = {
      ...failed.results[0],
      checks: [],
      run_status: null,
      error: '<script>untrusted error</script>',
    };
    const html = renderToStaticMarkup(<EvaluationResults report={failed} />);
    expect(html).toContain('No individual checks were recorded.');
    expect(html).toContain('Not recorded');
    expect(html).toContain('&lt;script&gt;untrusted error&lt;/script&gt;');
    expect(html).not.toContain('<script>');
  });
});

describe('selected report download', () => {
  afterEach(() => {
    vi.runOnlyPendingTimers();
    vi.useRealTimers();
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
  });

  it('downloads the selected historical report for a read-only observer', async () => {
    vi.useFakeTimers();
    const request = vi.fn().mockResolvedValue({ ok: true, blob: async () => new Blob(['{}']) });
    vi.stubGlobal('fetch', request);
    const anchor = { href: '', download: '', click: vi.fn() };
    vi.stubGlobal('document', { createElement: vi.fn().mockReturnValue(anchor) });
    vi.spyOn(URL, 'createObjectURL').mockReturnValue('blob:regression-report');
    const revoke = vi.spyOn(URL, 'revokeObjectURL').mockImplementation(() => {});
    let state = evaluationReducer(initialEvaluationState, {
      type: 'history-loaded',
      history: [report('latest'), report('historical')],
    });
    state = evaluationReducer(state, { type: 'select', id: 'historical' });
    state = evaluationReducer(state, {
      type: 'report-loaded',
      id: 'historical',
      report: report('historical'),
    });
    await downloadEvaluationReport(state.report!.id, 'observer');
    expect(request).toHaveBeenCalledWith('/api/evaluations/historical/report', {
      headers: { 'X-RelayOps-Role': 'observer' },
    });
    expect(anchor.download).toBe('relayops-evaluation-historical.json');
    expect(anchor.click).toHaveBeenCalledOnce();
    vi.runAllTimers();
    expect(revoke).toHaveBeenCalledWith('blob:regression-report');
  });

  it('reports a download error instead of saving an error response as a report', async () => {
    vi.useFakeTimers();
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: false, status: 404 }));
    const create = vi.fn();
    vi.stubGlobal('document', { createElement: create });
    await expect(downloadEvaluationReport('gone', 'observer')).rejects.toThrow(
      'Evaluation report download failed (404)',
    );
    expect(create).not.toHaveBeenCalled();
  });
});
