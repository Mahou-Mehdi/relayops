import { useEffect, useReducer, useRef, useState } from 'react';
import {
  AlertCircle,
  ArrowDownToLine,
  Check,
  ChevronRight,
  History,
  LoaderCircle,
  Play,
  RefreshCw,
  X,
} from 'lucide-react';
import { api, downloadEvaluationReport } from './api';
import { evaluationReducer, initialEvaluationState } from './evaluations';
import { canOperate, label } from './policy';
import type { Evaluation, EvaluationSummary, Role } from './types';

const date = (value: string) =>
  new Date(value).toLocaleString(undefined, {
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  });
const errorText = (error: unknown) =>
  error instanceof Error ? error.message : 'The request could not be completed.';
const valueText = (value: unknown) => JSON.stringify(value, null, 2) ?? 'Not recorded';

function ResultBadge({ passed }: { passed: boolean }) {
  return (
    <span className={`badge ${passed ? 'green' : 'red'}`}>
      {passed ? <Check size={12} /> : <X size={12} />}
      {passed ? 'Passed' : 'Failed'}
    </span>
  );
}

export function EvaluationResults({ report }: { report: Evaluation }) {
  return (
    <>
      <div className="evaluation-totals" aria-label="Selected regression results">
        <div>
          <span>Scenarios passed</span>
          <strong className={report.passed === report.total ? '' : 'has-failures'}>
            {report.passed}
            <small> / {report.total}</small>
          </strong>
        </div>
        <div>
          <span>Individual checks passed</span>
          <strong className={report.checks_passed === report.checks_total ? '' : 'has-failures'}>
            {report.checks_passed}
            <small> / {report.checks_total}</small>
          </strong>
        </div>
        <div>
          <span>Duration</span>
          <strong>
            {Math.round(report.duration_ms)}
            <small> ms</small>
          </strong>
          <p>
            Suite {report.suite_version} · RelayOps {report.app_version}
          </p>
        </div>
      </div>
      <div className="evaluation-scenarios">
        <div className="evaluation-section-heading">
          <h3>Scenario results</h3>
          <span>Open a scenario to inspect its checks</span>
        </div>
        {report.results.map((result) => (
          <details
            className={`evaluation-scenario ${result.passed ? '' : 'failed'}`}
            key={`${report.id}:${result.scenario_id}`}
            open={!result.passed}
          >
            <summary>
              <ChevronRight size={16} className="evaluation-chevron" />
              <div className="evaluation-scenario-title">
                <strong>{result.title}</strong>
                <small>{result.scenario_id}</small>
              </div>
              <span className="evaluation-check-count">
                {result.checks.filter((check) => check.passed).length}/{result.checks.length} checks
              </span>
              <ResultBadge passed={result.passed} />
            </summary>
            <div className="evaluation-scenario-meta">
              <span>
                Investigation:{' '}
                <strong>{result.run_status ? label(result.run_status) : 'Not recorded'}</strong>
              </span>
              <span>{Math.round(result.duration_ms)} ms</span>
            </div>
            {result.error && (
              <p className="evaluation-run-error" role="alert">
                <AlertCircle size={15} />
                {result.error}
              </p>
            )}
            {result.checks.length ? (
              <div className="evaluation-table-wrap">
                <table className="evaluation-table evaluation-check-table">
                  <caption className="sr-only">Checks for {result.title}</caption>
                  <thead>
                    <tr>
                      <th scope="col">Check</th>
                      <th scope="col">Result</th>
                      <th scope="col">Expected</th>
                      <th scope="col">Actual</th>
                    </tr>
                  </thead>
                  <tbody>
                    {result.checks.map((check) => (
                      <tr key={check.id} className={check.passed ? '' : 'check-failed'}>
                        <td>
                          <strong>{check.label}</strong>
                          <small>{check.id}</small>
                        </td>
                        <td>
                          <ResultBadge passed={check.passed} />
                        </td>
                        <td>
                          <pre>{valueText(check.expected)}</pre>
                        </td>
                        <td>
                          <pre>{valueText(check.actual)}</pre>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : (
              <p className="evaluation-no-checks">
                No individual checks were recorded. Download the report for details.
              </p>
            )}
          </details>
        ))}
      </div>
      {!!report.limitations.length && (
        <div className="evaluation-limitations">
          <h3>Report scope</h3>
          <ul>
            {report.limitations.map((item, index) => (
              <li key={index}>{item}</li>
            ))}
          </ul>
        </div>
      )}
    </>
  );
}

interface Props {
  role: Role;
  busy: string | null;
  refreshKey: number;
  onAction: (name: string, work: () => Promise<void>) => Promise<void>;
  onNotice: (message: string) => void;
}

export default function EvaluationPanel({ role, busy, refreshKey, onAction, onNotice }: Props) {
  const [state, dispatch] = useReducer(evaluationReducer, initialEvaluationState);
  const [retry, setRetry] = useState(0);
  const historyRequest = useRef(0);
  const reportRef = useRef(state.report);
  reportRef.current = state.report;

  useEffect(() => {
    const controller = new AbortController();
    const request = ++historyRequest.current;
    dispatch({ type: 'history-loading' });
    api<EvaluationSummary[]>('/evaluations/history?limit=20', role, undefined, controller.signal)
      .then((history) => {
        if (!controller.signal.aborted && request === historyRequest.current)
          dispatch({ type: 'history-loaded', history });
      })
      .catch((error) => {
        if (!controller.signal.aborted && request === historyRequest.current)
          dispatch({ type: 'history-error', error: errorText(error) });
      });
    return () => controller.abort();
  }, [role, refreshKey, retry]);

  useEffect(() => {
    const id = state.selectedId;
    if (!id || reportRef.current?.id === id) return;
    const controller = new AbortController();
    dispatch({ type: 'report-loading', id });
    api<Evaluation>(`/evaluations/${encodeURIComponent(id)}`, role, undefined, controller.signal)
      .then((report) => {
        if (!controller.signal.aborted) dispatch({ type: 'report-loaded', id, report });
      })
      .catch((error) => {
        if (!controller.signal.aborted)
          dispatch({ type: 'report-error', id, error: errorText(error) });
      });
    return () => controller.abort();
  }, [state.selectedId, role, refreshKey, retry]);

  const report = state.report;
  const problem = state.historyError || state.reportError;
  const loading = state.reportLoading || (state.historyLoading && !state.history.length);

  return (
    <section className="evaluation-panel panel" aria-label="Regression evaluations">
      <div className="evaluation-hero">
        <div>
          <h2>Regression runs</h2>
          <p>
            Run recovery and repair checks in a deterministic simulation. This suite does not
            measure model quality.
          </p>
        </div>
        <button
          className="button"
          disabled={!canOperate(role) || !!busy}
          onClick={() =>
            onAction('evaluate', async () => {
              const saved = await api<Evaluation>('/evaluations/run', role, {});
              // A history request started before this run must not hide its saved result.
              historyRequest.current += 1;
              dispatch({ type: 'saved', report: saved });
              onNotice(
                `Regression report saved: ${saved.passed}/${saved.total} scenarios and ${saved.checks_passed}/${saved.checks_total} checks passed.`,
              );
            })
          }
        >
          {busy === 'evaluate' ? <LoaderCircle className="spin" size={16} /> : <Play size={14} />}
          {busy === 'evaluate' ? 'Running regression…' : 'Run regression'}
        </button>
      </div>
      {state.history.length > 0 && (
        <div className="evaluation-history">
          <label htmlFor="evaluation-history">
            <History size={16} />
            <span>
              Saved run<small>Most recent 20 reports</small>
            </span>
          </label>
          <select
            id="evaluation-history"
            value={state.selectedId || ''}
            disabled={!!busy}
            onChange={(event) => dispatch({ type: 'select', id: event.target.value })}
          >
            {state.history.map((entry, index) => (
              <option value={entry.id} key={entry.id}>
                {index === 0 ? 'Latest · ' : ''}
                {date(entry.generated_at)} · {entry.passed}/{entry.total} scenarios ·{' '}
                {entry.checks_passed}/{entry.checks_total} checks · {entry.id.slice(0, 8)}
              </option>
            ))}
          </select>
          <button
            className="button secondary small"
            disabled={!!busy || !report || loading}
            onClick={() =>
              report &&
              onAction('download-evaluation', () => downloadEvaluationReport(report.id, role))
            }
          >
            <ArrowDownToLine size={15} />
            Download JSON
          </button>
        </div>
      )}
      {problem && (
        <div className="evaluation-fetch-error" role="alert">
          <AlertCircle size={17} />
          <div>
            <strong>Could not load {state.historyError ? 'saved history' : 'this report'}</strong>
            <p>{problem}</p>
          </div>
          <button
            className="button secondary small"
            disabled={!!busy}
            onClick={() => setRetry((value) => value + 1)}
          >
            <RefreshCw size={14} />
            Try again
          </button>
        </div>
      )}
      {loading ? (
        <div className="loading-state" role="status">
          <LoaderCircle className="spin" />
          <p>Loading {state.selectedId ? 'the selected report' : 'saved regression history'}…</p>
        </div>
      ) : report ? (
        <>
          <div className="evaluation-report-meta">
            <span>Recorded {date(report.generated_at)}</span>
            <span className="mono">Run {report.id.slice(0, 8)}</span>
          </div>
          <EvaluationResults report={report} />
        </>
      ) : (
        !problem && (
          <div className="empty-state">
            <h3>No saved runs</h3>
            <p>Run the suite as Operator to save a report.</p>
          </div>
        )
      )}
      {!canOperate(role) && (
        <p className="evaluation-role-note">
          This role can read and download reports. Switch to Operator to run the suite.
        </p>
      )}
    </section>
  );
}
