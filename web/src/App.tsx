import { useCallback, useEffect, useRef, useState } from 'react';
import type { ReactNode } from 'react';
import {
  Activity,
  ArrowDownToLine,
  ArrowRight,
  BookOpen,
  Check,
  CheckCircle2,
  ChevronRight,
  Clock3,
  Code2,
  FileCheck2,
  FlaskConical,
  Layers3,
  LoaderCircle,
  LockKeyhole,
  Play,
  Plus,
  RefreshCw,
  Search,
  ShieldCheck,
  Square,
  Terminal,
  X,
  AlertCircle,
  CircleDot,
} from 'lucide-react';
import { api, downloadReport, downloadPatch } from './api';
import EvaluationPanel from './EvaluationPanel';
import {
  activeRun,
  canOperate,
  citedEvidence,
  filterCases,
  label,
  proposalPermission,
} from './policy';
import type {
  CaseDetail,
  CaseSummary,
  Config,
  Evidence,
  Knowledge,
  Mode,
  Proposal,
  Role,
  Run,
  Scenario,
} from './types';

type Page = 'cases' | 'lab' | 'evaluations' | 'knowledge';
type DetailTab = 'overview' | 'evidence' | 'activity' | 'repair';
const pageTitles: Record<Page, string> = {
  cases: 'Operations',
  lab: 'Scenario lab',
  evaluations: 'Evaluations',
  knowledge: 'Runbooks',
};
const short = (value: string) => value?.slice(0, 8) || '—';
const date = (value: string) =>
  value
    ? new Date(value).toLocaleString(undefined, {
        month: 'short',
        day: 'numeric',
        hour: '2-digit',
        minute: '2-digit',
      })
    : '—';
const errorText = (error: unknown) =>
  error instanceof Error ? error.message : 'The request could not be completed.';
const statusTone = (value: string) =>
  /resolved|completed|executed|approved|healthy|passed/.test(value)
    ? 'green'
    : /failed|rejected|denied|stale|expired/.test(value)
      ? 'red'
      : /running|queued|investigating/.test(value)
        ? 'blue'
        : /pending|review|approval|cancel_requested/.test(value)
          ? 'amber'
          : 'neutral';

function Badge({ children, tone = 'neutral' }: { children: ReactNode; tone?: string }) {
  return <span className={`badge ${tone}`}>{children}</span>;
}
function Status({ value }: { value: string }) {
  return (
    <Badge tone={statusTone(value)}>
      <span className="badge-dot" />
      {label(value)}
    </Badge>
  );
}
function Empty({
  icon,
  heading,
  children,
}: {
  icon: ReactNode;
  heading: string;
  children: ReactNode;
}) {
  return (
    <div className="empty-state">
      <div className="empty-icon">{icon}</div>
      <h3>{heading}</h3>
      <p>{children}</p>
    </div>
  );
}
function JsonDetails({ title, value }: { title: string; value: unknown }) {
  return (
    <details className="json-details">
      <summary>{title}</summary>
      <pre>{JSON.stringify(value, null, 2)}</pre>
    </details>
  );
}

export default function App() {
  const [page, setPage] = useState<Page>('cases');
  const [role, setRole] = useState<Role>('operator');
  const [mode, setMode] = useState<Mode>('fixture');
  const [config, setConfig] = useState<Config | null>(null);
  const [scenarios, setScenarios] = useState<Scenario[]>([]);
  const [cases, setCases] = useState<CaseSummary[]>([]);
  const [selected, setSelected] = useState<string | null>(null);
  const [detail, setDetail] = useState<CaseDetail | null>(null);
  const [evaluationRefresh, setEvaluationRefresh] = useState(0);
  const [knowledge, setKnowledge] = useState<Knowledge[]>([]);
  const [query, setQuery] = useState('');
  const [filter, setFilter] = useState('all');
  const [tab, setTab] = useState<DetailTab>('overview');
  const [busy, setBusy] = useState<string | null>(null);
  const [initialLoading, setInitialLoading] = useState(true);
  const [detailLoading, setDetailLoading] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [confirm, setConfirm] = useState<{
    proposal: Proposal;
    action: 'approve' | 'reject' | 'execute';
  } | null>(null);
  const [evidenceOpen, setEvidenceOpen] = useState<string | null>(null);
  const mutationLock = useRef(false);
  const selectedRef = useRef(selected);
  selectedRef.current = selected;

  useEffect(() => {
    if (!confirm) return;
    const previous = document.activeElement as HTMLElement | null;
    const dialog = document.querySelector<HTMLElement>('[role="dialog"]');
    const controls = () =>
      Array.from(dialog?.querySelectorAll<HTMLButtonElement>('button:not(:disabled)') || []);
    controls()[0]?.focus();
    const handleKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape' && !mutationLock.current) {
        event.preventDefault();
        setConfirm(null);
      }
      if (event.key === 'Tab') {
        const buttons = controls();
        if (!buttons.length) {
          event.preventDefault();
          return;
        }
        const first = buttons[0],
          last = buttons[buttons.length - 1];
        if (event.shiftKey && document.activeElement === first) {
          event.preventDefault();
          last.focus();
        } else if (!event.shiftKey && document.activeElement === last) {
          event.preventDefault();
          first.focus();
        }
      }
    };
    document.addEventListener('keydown', handleKey);
    return () => {
      document.removeEventListener('keydown', handleKey);
      previous?.focus();
    };
  }, [confirm]);

  const loadAll = useCallback(
    async (signal?: AbortSignal) => {
      const [configuration, scenarioList, caseList, articles] = await Promise.all([
        api<Config>('/config', role, undefined, signal),
        api<Scenario[]>('/scenarios', role, undefined, signal),
        api<CaseSummary[]>('/cases', role, undefined, signal),
        api<Knowledge[]>('/knowledge', role, undefined, signal),
      ]);
      setConfig(configuration);
      setScenarios(scenarioList);
      setCases(caseList);
      setEvaluationRefresh((value) => value + 1);
      setKnowledge(articles);
      setSelected((previous) => previous || caseList[0]?.id || null);
    },
    [role],
  );

  useEffect(() => {
    const controller = new AbortController();
    setInitialLoading(true);
    setError('');
    loadAll(controller.signal)
      .catch((failure) => {
        if (!controller.signal.aborted) setError(errorText(failure));
      })
      .finally(() => {
        if (!controller.signal.aborted) setInitialLoading(false);
      });
    return () => controller.abort();
  }, [loadAll]);

  useEffect(() => {
    if (!selected) {
      setDetail(null);
      return;
    }
    const controller = new AbortController();
    setDetailLoading(true);
    setDetail(null);
    api<CaseDetail>(`/cases/${encodeURIComponent(selected)}`, role, undefined, controller.signal)
      .then(setDetail)
      .catch((failure) => {
        if (!controller.signal.aborted) setError(errorText(failure));
      })
      .finally(() => {
        if (!controller.signal.aborted) setDetailLoading(false);
      });
    return () => controller.abort();
  }, [selected, role]);

  const hasActive = casesHaveActive(cases) || Boolean(detail?.runs.some(activeRun));
  useEffect(() => {
    if (!hasActive) return;
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout>;
    const poll = async () => {
      try {
        const list = await api<CaseSummary[]>('/cases', role, undefined, controller.signal);
        setCases(list);
        const id = selectedRef.current;
        if (id) {
          const current = await api<CaseDetail>(
            `/cases/${encodeURIComponent(id)}`,
            role,
            undefined,
            controller.signal,
          );
          if (selectedRef.current === id) setDetail(current);
        }
      } catch (failure) {
        if (!controller.signal.aborted) setError(`Updates paused: ${errorText(failure)}`);
      }
      if (!controller.signal.aborted) timer = setTimeout(poll, 1000);
    };
    timer = setTimeout(poll, 1000);
    return () => {
      controller.abort();
      clearTimeout(timer);
    };
  }, [hasActive, role]);

  async function mutate(name: string, work: () => Promise<void>) {
    if (mutationLock.current) return;
    mutationLock.current = true;
    setBusy(name);
    setError('');
    setNotice('');
    try {
      await work();
    } catch (failure) {
      setError(errorText(failure));
    } finally {
      mutationLock.current = false;
      setBusy(null);
    }
  }
  async function refreshCase(id: string) {
    const [list, current] = await Promise.all([
      api<CaseSummary[]>('/cases', role),
      api<CaseDetail>(`/cases/${encodeURIComponent(id)}`, role),
    ]);
    setCases(list);
    if (selectedRef.current === id) setDetail(current);
  }
  function selectCase(id: string) {
    setSelected(id);
    setPage('cases');
    setTab('overview');
    setEvidenceOpen(null);
    setError('');
  }
  async function createCase(scenario: Scenario) {
    await mutate(`create:${scenario.id}`, async () => {
      const result = await api<CaseDetail>('/cases', role, { scenario_id: scenario.id });
      setCases(await api<CaseSummary[]>('/cases', role));
      selectCase(result.id);
      setDetail(result);
      setNotice('Scenario created. The target and evidence are isolated to this case.');
    });
  }
  async function investigate() {
    if (!detail) return;
    const id = detail.id;
    await mutate('investigate', async () => {
      await api<Run>(`/cases/${encodeURIComponent(id)}/investigate`, role, { mode });
      await refreshCase(id);
      setTab('activity');
      setNotice(
        `${mode === 'fixture' ? 'Deterministic fixture' : 'OpenAI'} investigation started.`,
      );
    });
  }
  async function repair() {
    if (!detail) return;
    const id = detail.id;
    await mutate('repair', async () => {
      const result = await api<CaseDetail>(`/cases/${encodeURIComponent(id)}/repair`, role, {
        mode,
      });
      if (selectedRef.current === id) setDetail(result);
      setCases(await api<CaseSummary[]>('/cases', role));
      setTab('repair');
      setNotice('Restricted transform verification completed. Review the actual results below.');
    });
  }
  async function decide() {
    if (!confirm || !detail) return;
    const { proposal, action } = confirm;
    const id = detail.id;
    await mutate(action, async () => {
      const path =
        action === 'execute'
          ? `/proposals/${proposal.id}/execute`
          : `/proposals/${proposal.id}/decision`;
      const body =
        action === 'execute'
          ? { expected_hash: proposal.hash }
          : { decision: action, expected_hash: proposal.hash };
      const result = await api<CaseDetail>(path, role, body);
      if (selectedRef.current === id) setDetail(result);
      setCases(await api<CaseSummary[]>('/cases', role));
      setConfirm(null);
      setNotice(
        action === 'approve'
          ? 'Authorization recorded. An operator must execute the approved proposal.'
          : action === 'reject'
            ? 'Proposal rejected. No operation was executed.'
            : proposal.kind === 'publish_patch'
              ? 'Verified patch artifact recorded. No repository or deployment was changed.'
              : 'Operation completed. Review its verified outcome in the case record.',
      );
    });
  }
  const filtered = filterCases(cases, query, filter);
  const currentActive = detail?.runs.find(activeRun);
  const activeCount = cases.filter((item) =>
    activeRun({ status: item.latest_run_status || '' }),
  ).length;
  const statuses = [...new Set(cases.map((item) => item.status))];
  const selectedEvidence = detail?.evidence.find((item) => item.id === evidenceOpen);

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <a
          className="brand"
          href="#"
          onClick={(event) => {
            event.preventDefault();
            setPage('cases');
          }}
          aria-label="RelayOps home"
        >
          <span className="brand-mark">
            <Layers3 size={20} />
          </span>
          <span>RelayOps</span>
        </a>

        <nav aria-label="Main navigation">
          {(
            [
              { id: 'cases', label: 'Operations', icon: Activity },
              { id: 'lab', label: 'Scenario lab', icon: FlaskConical },
              { id: 'evaluations', label: 'Evaluations', icon: FileCheck2 },
              { id: 'knowledge', label: 'Runbooks', icon: BookOpen },
            ] as const
          ).map((item) => (
            <button
              key={item.id}
              className={`nav-item ${page === item.id ? 'active' : ''}`}
              aria-current={page === item.id ? 'page' : undefined}
              aria-label={item.label}
              title={item.label}
              onClick={() => setPage(item.id)}
            >
              <item.icon size={18} />
              <span className="nav-text">{item.label}</span>
              {item.id === 'cases' && <span className="nav-count">{cases.length}</span>}
            </button>
          ))}
        </nav>
        <div className="sidebar-footer">
          <span className="mono">v{config?.version || '0.2'}</span>
          <span>Local demo</span>
        </div>
      </aside>

      <div className="main-shell">
        <header className="topbar">
          <div className="breadcrumb">
            <span className="tiny-dot" /> Local console
          </div>
          <div className="topbar-controls">
            <Badge tone={mode === 'fixture' ? 'amber' : 'blue'}>
              {mode === 'fixture' ? <FlaskConical size={12} /> : <CircleDot size={12} />}{' '}
              {mode === 'fixture' ? 'Fixture · deterministic' : 'OpenAI · live model'}
            </Badge>
            <label className="role-control">
              <span>Demo role</span>
              <select
                value={role}
                disabled={!!busy}
                onChange={(event) => {
                  setRole(event.target.value as Role);
                  setConfirm(null);
                }}
                aria-label="Local demo role"
              >
                <option value="operator">Operator</option>
                <option value="reviewer">Reviewer</option>
                <option value="observer">Observer</option>
              </select>
            </label>
          </div>
        </header>
        <main>
          <section className="page-heading">
            <div>
              <h1>{pageTitles[page]}</h1>
              <p className="page-lead">
                {page === 'cases'
                  ? 'Integration cases, evidence, and recovery approvals.'
                  : page === 'lab'
                    ? 'Create an isolated case from a predefined integration scenario.'
                    : page === 'evaluations'
                      ? 'Saved regression runs and check results.'
                      : 'Investigation rules, recovery procedures, and runtime limits.'}
              </p>
            </div>
            <div className="heading-actions">
              <button
                className="button secondary"
                disabled={!!busy || initialLoading}
                onClick={() =>
                  mutate('refresh', async () => {
                    await loadAll();
                    if (selected) await refreshCase(selected);
                  })
                }
              >
                <RefreshCw size={15} className={busy === 'refresh' ? 'spin' : ''} />
                Refresh
              </button>
              {page === 'cases' && (
                <button className="button" onClick={() => setPage('lab')}>
                  <Plus size={16} />
                  Create case
                </button>
              )}
            </div>
          </section>

          {error && (
            <div className="banner error" role="alert">
              <AlertCircle size={18} />
              <div>
                <strong>Request failed</strong>
                <p>{error}</p>
              </div>
              <button aria-label="Dismiss error" onClick={() => setError('')}>
                <X size={16} />
              </button>
            </div>
          )}
          {notice && (
            <div className="banner success" role="status">
              <CheckCircle2 size={18} />
              <p>{notice}</p>
              <button aria-label="Dismiss notification" onClick={() => setNotice('')}>
                <X size={16} />
              </button>
            </div>
          )}
          {!initialLoading && !config && (
            <Empty icon={<AlertCircle />} heading="The local service is unavailable">
              Start the RelayOps backend, then choose Refresh to connect.
            </Empty>
          )}
          {initialLoading && !config ? (
            <div className="loading-state">
              <LoaderCircle className="spin" />
              <p>Loading workspace…</p>
            </div>
          ) : (
            config && (
              <>
                {page === 'cases' && (
                  <>
                    <dl className="status-strip" aria-label="Case status summary">
                      <div>
                        <dt>Unresolved</dt>
                        <dd>{cases.filter((item) => item.status !== 'resolved').length}</dd>
                      </div>
                      <div>
                        <dt>Awaiting review</dt>
                        <dd>
                          {cases.filter((item) => item.status === 'awaiting_approval').length}
                        </dd>
                      </div>
                      <div>
                        <dt>Active</dt>
                        <dd>{activeCount}</dd>
                      </div>
                      <div>
                        <dt>Resolved</dt>
                        <dd>{cases.filter((item) => item.status === 'resolved').length}</dd>
                      </div>
                    </dl>
                    <div className="workspace-grid">
                      <section className="case-list panel">
                        <div className="panel-heading">
                          <h2>Case queue</h2>
                          <span className="count-chip">{filtered.length}</span>
                        </div>
                        <div className="case-filters">
                          <label className="search-box">
                            <Search size={15} />
                            <input
                              value={query}
                              onChange={(event) => setQuery(event.target.value)}
                              placeholder="Search cases or orders"
                              aria-label="Search cases"
                            />
                          </label>
                          <select
                            value={filter}
                            onChange={(event) => setFilter(event.target.value)}
                            aria-label="Filter case status"
                          >
                            <option value="all">All statuses</option>
                            {statuses.map((status) => (
                              <option key={status} value={status}>
                                {label(status)}
                              </option>
                            ))}
                          </select>
                        </div>
                        <div className="case-items">
                          {filtered.map((item) => (
                            <button
                              key={item.id}
                              className={`case-row ${selected === item.id ? 'selected' : ''}`}
                              onClick={() => selectCase(item.id)}
                              aria-pressed={selected === item.id}
                            >
                              <div className="case-row-top">
                                <span className={`severity-dot ${item.severity}`} />
                                <span className="mono">{short(item.id)}</span>
                                <span className="case-time">{date(item.updated_at)}</span>
                              </div>
                              <h3>{item.title}</h3>
                              <p>{item.order_id || label(item.category)}</p>
                              <div className="case-row-bottom">
                                <Status value={item.status} />
                                <ChevronRight size={15} />
                              </div>
                            </button>
                          ))}
                          {!filtered.length && (
                            <Empty
                              icon={<Layers3 />}
                              heading={cases.length ? 'No matching cases' : 'No cases yet'}
                            >
                              {cases.length
                                ? 'Try another search or status filter.'
                                : 'Choose Create case to load a simulated incident.'}
                            </Empty>
                          )}
                        </div>
                        <div className="list-footer">
                          <LockKeyhole size={12} />
                          Demo roles are not sign-in accounts.
                        </div>
                      </section>
                      <section className="case-detail panel">
                        {detailLoading ? (
                          <div className="loading-state">
                            <LoaderCircle className="spin" />
                            <p>Loading case evidence…</p>
                          </div>
                        ) : detail ? (
                          <>
                            <div className="detail-header">
                              <div className="detail-kicker">
                                <span className="mono">CASE {short(detail.id).toUpperCase()}</span>
                                <Status value={detail.status} />
                              </div>
                              <h2>{detail.title}</h2>
                              <div className="detail-meta">
                                <span>{detail.order_id || 'Fictional integration'}</span>
                                <span>Revision {detail.revision}</span>
                                <span>Updated {date(detail.updated_at)}</span>
                              </div>
                              <div className="detail-actions">
                                <label className="mode-picker">
                                  <span>Investigation mode</span>
                                  <select
                                    value={mode}
                                    disabled={!!busy || !!currentActive}
                                    onChange={(event) => setMode(event.target.value as Mode)}
                                  >
                                    <option value="fixture">Fixture · deterministic</option>
                                    <option value="openai" disabled={!config.live_available}>
                                      OpenAI{!config.live_available ? ' · key not configured' : ''}
                                    </option>
                                  </select>
                                </label>
                                <button
                                  className="button"
                                  disabled={!canOperate(role) || !!busy || !!currentActive}
                                  onClick={investigate}
                                >
                                  {busy === 'investigate' ? (
                                    <LoaderCircle className="spin" size={15} />
                                  ) : (
                                    <Play size={14} />
                                  )}
                                  Investigate
                                </button>
                                <button
                                  className="icon-button"
                                  title="Download case report JSON"
                                  aria-label="Download case report JSON"
                                  disabled={!!busy}
                                  onClick={() =>
                                    mutate('download', () => downloadReport(detail.id, role))
                                  }
                                >
                                  <ArrowDownToLine size={17} />
                                </button>
                              </div>
                              {role !== 'operator' && (
                                <p className="role-hint">
                                  {role === 'reviewer'
                                    ? 'Reviewers authorize proposals. Switch to Operator to investigate or execute.'
                                    : 'Observer mode is read only.'}
                                </p>
                              )}
                            </div>
                            <div className="detail-tabs" role="tablist" aria-label="Case sections">
                              {(
                                [
                                  { id: 'overview', text: 'Overview', icon: Layers3 },
                                  {
                                    id: 'evidence',
                                    text: `Evidence (${detail.evidence.length})`,
                                    icon: BookOpen,
                                  },
                                  { id: 'activity', text: 'Run activity', icon: Activity },
                                  { id: 'repair', text: 'Code repair', icon: Code2 },
                                ] as const
                              ).map((item) => (
                                <button
                                  key={item.id}
                                  role="tab"
                                  aria-selected={tab === item.id}
                                  className={tab === item.id ? 'active' : ''}
                                  onClick={() => setTab(item.id)}
                                >
                                  <item.icon size={14} />
                                  {item.text}
                                </button>
                              ))}
                            </div>
                            <div className="detail-body" role="tabpanel">
                              {tab === 'overview' && (
                                <>
                                  <div className="section-label">Diagnosis</div>
                                  {detail.diagnosis ? (
                                    <>
                                      <div className="diagnosis-card">
                                        <div className="diagnosis-title">
                                          <ShieldCheck size={18} />
                                          <h3>{detail.diagnosis.summary}</h3>
                                        </div>
                                        <p>{detail.diagnosis.cause}</p>
                                        <div className="citation-links">
                                          {citedEvidence(
                                            detail.diagnosis.evidence_ids,
                                            detail.evidence,
                                          ).map((evidence, index) => (
                                            <button
                                              key={evidence.id}
                                              onClick={() => {
                                                setTab('evidence');
                                                setEvidenceOpen(evidence.id);
                                              }}
                                            >
                                              <BookOpen size={12} />[{index + 1}] {evidence.title}
                                            </button>
                                          ))}
                                        </div>
                                        {detail.diagnosis.hypotheses.length > 0 && (
                                          <div className="hypotheses">
                                            <strong>Unconfirmed hypotheses</strong>
                                            <ul>
                                              {detail.diagnosis.hypotheses.map(
                                                (hypothesis, index) => (
                                                  <li key={index}>{hypothesis}</li>
                                                ),
                                              )}
                                            </ul>
                                          </div>
                                        )}
                                      </div>
                                      <div className="recommendation">
                                        <ArrowRight size={16} />
                                        <div>
                                          <strong>Recommended next step</strong>
                                          <p>{detail.diagnosis.recommendation}</p>
                                        </div>
                                      </div>
                                    </>
                                  ) : (
                                    <div className="inline-empty">
                                      <CircleDot size={20} />
                                      <div>
                                        <strong>No diagnosis yet</strong>
                                        <p>
                                          Choose Investigate to inspect the evidence and record a
                                          diagnosis.
                                        </p>
                                      </div>
                                    </div>
                                  )}
                                  <div className="section-label">Proposals and decisions</div>
                                  {detail.proposals.length ? (
                                    detail.proposals.map((proposal) => (
                                      <ProposalCard
                                        key={proposal.id}
                                        proposal={proposal}
                                        role={role}
                                        revision={detail.revision}
                                        busy={!!busy}
                                        onAction={(action) => setConfirm({ proposal, action })}
                                      />
                                    ))
                                  ) : (
                                    <p className="muted empty-copy">
                                      No recovery proposal recorded.
                                    </p>
                                  )}
                                  {!!detail.operations.length && (
                                    <>
                                      <div className="section-label">Recorded operations</div>
                                      {detail.operations.map((operation) => (
                                        <div className="operation-card" key={operation.id}>
                                          <div>
                                            <strong>{label(operation.kind)}</strong>
                                            <Status value={operation.status} />
                                          </div>
                                          <p className="mono">Key: {operation.idempotency_key}</p>
                                          {operation.receipt && (
                                            <p>
                                              Receipt: <strong>{operation.receipt}</strong>
                                            </p>
                                          )}
                                          <details>
                                            <summary>Operation integrity</summary>
                                            <p className="mono wrap">
                                              Payload hash: {operation.payload_hash}
                                            </p>
                                            <p>{date(operation.updated_at)}</p>
                                          </details>
                                        </div>
                                      ))}
                                    </>
                                  )}
                                  {detail.scenario_id === 'mapping-defect' && !detail.repair && (
                                    <button
                                      className="button secondary wide"
                                      disabled={!canOperate(role) || !!busy || !!currentActive}
                                      onClick={repair}
                                    >
                                      <Code2 size={16} />
                                      Prepare restricted transform repair
                                    </button>
                                  )}
                                </>
                              )}
                              {tab === 'evidence' && (
                                <>
                                  <div className="section-intro">
                                    <h3>Evidence collection</h3>
                                    <p>
                                      Observed source records, with origin and content hash. Logs
                                      are evidence, never instructions.
                                    </p>
                                  </div>
                                  {detail.evidence.map((item, index) => (
                                    <EvidenceCard
                                      key={item.id}
                                      item={item}
                                      index={index}
                                      open={evidenceOpen === item.id}
                                      onToggle={() =>
                                        setEvidenceOpen(evidenceOpen === item.id ? null : item.id)
                                      }
                                    />
                                  ))}
                                  {!detail.evidence.length && (
                                    <Empty icon={<BookOpen />} heading="No evidence collected">
                                      The investigation will only use available records and must
                                      acknowledge missing evidence.
                                    </Empty>
                                  )}
                                </>
                              )}
                              {tab === 'activity' && (
                                <>
                                  <div className="section-intro">
                                    <h3>Investigation activity</h3>
                                    <p>Tool calls, results, and run errors.</p>
                                  </div>
                                  {detail.runs.map((run) => (
                                    <div className="run-card" key={run.id}>
                                      <div className="run-heading">
                                        <div>
                                          <strong>Run {short(run.id)}</strong>
                                          <small>{date(run.created_at)}</small>
                                        </div>
                                        <Status value={run.status} />
                                      </div>
                                      <div className="run-stats">
                                        <Badge tone={run.mode === 'fixture' ? 'amber' : 'blue'}>
                                          {run.mode === 'fixture'
                                            ? 'Deterministic fixture'
                                            : 'OpenAI model'}
                                        </Badge>
                                        <span>{run.tool_calls} tool calls</span>
                                        <span>{run.model_calls} model calls</span>
                                      </div>
                                      {run.error && <p className="run-error">{run.error}</p>}
                                      <div className="timeline">
                                        {run.events.map((event) => (
                                          <div className="timeline-item" key={event.id}>
                                            <span className="timeline-dot" />
                                            <div>
                                              <strong>{event.title}</strong>
                                              <p>{event.detail}</p>
                                              <small>{date(event.created_at)}</small>
                                            </div>
                                          </div>
                                        ))}
                                      </div>
                                      {activeRun(run) && canOperate(role) && (
                                        <button
                                          className="button secondary small"
                                          disabled={!!busy || run.status === 'cancel_requested'}
                                          onClick={() =>
                                            mutate('cancel', async () => {
                                              await api(`/runs/${run.id}/cancel`, role, {});
                                              await refreshCase(detail.id);
                                            })
                                          }
                                        >
                                          <Square size={12} />
                                          {run.status === 'cancel_requested'
                                            ? 'Cancellation requested'
                                            : 'Cancel run'}
                                        </button>
                                      )}
                                      {run.usage && (
                                        <JsonDetails
                                          title="Reported provider usage"
                                          value={run.usage}
                                        />
                                      )}
                                    </div>
                                  ))}
                                  {!detail.runs.length && (
                                    <Empty icon={<Activity />} heading="No investigation runs yet">
                                      Choose Investigate to start a run. Tool results will appear
                                      here.
                                    </Empty>
                                  )}
                                  <details className="case-events">
                                    <summary>Case ledger · {detail.events.length} events</summary>
                                    <div className="timeline">
                                      {detail.events.map((event) => (
                                        <div className="timeline-item" key={event.id}>
                                          <span className="timeline-dot" />
                                          <div>
                                            <strong>{event.title}</strong>
                                            <p>{event.detail}</p>
                                            <small>{date(event.created_at)}</small>
                                          </div>
                                        </div>
                                      ))}
                                    </div>
                                  </details>
                                </>
                              )}
                              {tab === 'repair' && (
                                <>
                                  <div className="section-intro">
                                    <h3>Restricted transform repair</h3>
                                    <p>
                                      Verify a mapping expression against protected checks. Repairs
                                      are limited to the supported expression language.
                                    </p>
                                  </div>
                                  {detail.repair ? (
                                    <RepairView detail={detail} />
                                  ) : (
                                    <Empty
                                      icon={<Code2 />}
                                      heading={
                                        detail.scenario_id === 'mapping-defect'
                                          ? 'No repair prepared'
                                          : 'No transform repair for this case'
                                      }
                                    >
                                      {detail.scenario_id === 'mapping-defect'
                                        ? 'Prepare a candidate expression and inspect the original failure, independent verification, and exact patch.'
                                        : 'Use the mapping-defect scenario to prepare and verify an expression repair.'}
                                    </Empty>
                                  )}
                                  {detail.proposals.some(
                                    (proposal) =>
                                      proposal.kind === 'publish_patch' &&
                                      proposal.status === 'executed',
                                  ) && (
                                    <button
                                      className="button secondary wide"
                                      disabled={!!busy}
                                      onClick={() =>
                                        mutate('downloadpatch', () =>
                                          downloadPatch(detail.id, role),
                                        )
                                      }
                                    >
                                      <ArrowDownToLine size={15} />
                                      Download verified patch
                                    </button>
                                  )}
                                  {detail.scenario_id === 'mapping-defect' && (
                                    <button
                                      className="button"
                                      disabled={!canOperate(role) || !!busy || !!currentActive}
                                      onClick={repair}
                                    >
                                      {busy === 'repair' ? (
                                        <LoaderCircle size={15} className="spin" />
                                      ) : (
                                        <Code2 size={15} />
                                      )}{' '}
                                      {detail.repair
                                        ? 'Prepare another repair'
                                        : 'Prepare restricted repair'}
                                    </button>
                                  )}
                                  {detail.repair && (
                                    <p className="muted">
                                      A passing repair creates a proposal in Overview. Review
                                      authorization is separate from exporting the patch artifact.
                                    </p>
                                  )}
                                </>
                              )}
                            </div>
                          </>
                        ) : (
                          <Empty icon={<Layers3 />} heading="Select a case to begin">
                            Select a case from the queue to inspect its evidence and proposed
                            actions.
                          </Empty>
                        )}
                      </section>
                    </div>
                  </>
                )}

                {page === 'lab' && (
                  <>
                    <div className="lab-note">
                      <FlaskConical size={16} />
                      <p>
                        Fictional local targets. These scenarios do not access a live SAP or company
                        system.
                      </p>
                    </div>
                    <section className="scenario-list panel" aria-label="Available scenarios">
                      <div className="scenario-list-heading">
                        <span>Scenario</span>
                        <span>Expected result</span>
                        <span className="sr-only">Action</span>
                      </div>
                      {scenarios.map((scenario) => (
                        <article className="scenario-row" key={scenario.id}>
                          <div className="scenario-primary">
                            <h2>{scenario.title}</h2>
                            <p>{scenario.description}</p>
                            <span className="scenario-category">
                              {label(scenario.category)} · {label(scenario.severity)} severity
                            </span>
                          </div>
                          <div className="expected">
                            <span>Expected result</span>
                            <p>{scenario.expected_behavior}</p>
                          </div>
                          <button
                            className="button secondary small"
                            disabled={!canOperate(role) || !!busy}
                            onClick={() => createCase(scenario)}
                            aria-label={`Create case: ${scenario.title}`}
                          >
                            {busy === `create:${scenario.id}` ? (
                              <LoaderCircle className="spin" size={14} />
                            ) : (
                              <Plus size={14} />
                            )}
                            Create case
                          </button>
                        </article>
                      ))}
                    </section>
                    {role !== 'operator' && (
                      <p className="muted">Select Operator to create cases.</p>
                    )}
                  </>
                )}

                <div hidden={page !== 'evaluations'}>
                  <EvaluationPanel
                    role={role}
                    busy={busy}
                    refreshKey={evaluationRefresh}
                    onAction={mutate}
                    onNotice={setNotice}
                  />
                </div>

                {page === 'knowledge' && (
                  <div className="knowledge-layout">
                    <div className="knowledge-articles">
                      {knowledge.map((article) => (
                        <details className="knowledge-card panel" key={article.id}>
                          <summary>
                            <BookOpen size={16} />
                            <h2>{article.title}</h2>
                            <ChevronRight size={16} />
                          </summary>
                          <div className="knowledge-body">{article.body}</div>
                        </details>
                      ))}
                      {!knowledge.length && (
                        <Empty icon={<BookOpen />} heading="No runbooks loaded">
                          Refresh after the service has loaded its operating notes.
                        </Empty>
                      )}
                    </div>
                    <aside className="boundary-card">
                      <Terminal size={22} />
                      <h3>Runtime limits</h3>
                      <p>
                        Local single-process service.
                        <br />
                        SQLite operation ledger.
                        <br />
                        Fictional integration targets.
                        <br />
                        Restricted expression repairs.
                      </p>
                      <hr />
                      <p>
                        Tool limit: <strong>{config.limits.max_tool_calls}</strong>
                        <br />
                        Model-call limit: <strong>{config.limits.max_model_calls}</strong>
                      </p>
                      <p className="muted">Demo roles are not production authentication.</p>
                    </aside>
                  </div>
                )}
              </>
            )
          )}
          <footer className="main-footer">
            <span>
              <span className="tiny-dot" />{' '}
              {config ? 'SQLite ledger · Local demo' : 'Waiting for local service'}
            </span>
            <span>RelayOps {config?.version || '0.2'}</span>
          </footer>
        </main>
      </div>
      {selectedEvidence && tab === 'evidence' && (
        <span className="sr-only" role="status">
          Opened evidence: {selectedEvidence.title}
        </span>
      )}
      {confirm && detail && (
        <div
          className="modal-backdrop"
          onClick={(event) => {
            if (event.target === event.currentTarget && !busy) setConfirm(null);
          }}
        >
          <section
            className="confirm-modal"
            role="dialog"
            aria-modal="true"
            aria-labelledby="confirmation-title"
          >
            <div className="modal-icon">
              <ShieldCheck size={25} />
            </div>
            <h2 id="confirmation-title">
              {confirm.action === 'approve'
                ? 'Authorize this exact proposal?'
                : confirm.action === 'reject'
                  ? 'Reject this proposal?'
                  : confirm.proposal.kind === 'publish_patch'
                    ? 'Export the verified patch?'
                    : 'Execute the approved action?'}
            </h2>
            <p>{confirm.proposal.title}</p>
            <div className="confirmation-facts">
              <span>
                Case revision <strong>{confirm.proposal.case_revision}</strong>
              </span>
              <span>
                Proposal hash <strong className="mono">{short(confirm.proposal.hash)}…</strong>
              </span>
              <span>
                Expires <strong>{date(confirm.proposal.expires_at)}</strong>
              </span>
            </div>
            <p className="muted">
              {confirm.action === 'approve'
                ? 'This records authorization only. An operator must execute it separately.'
                : confirm.action === 'reject'
                  ? 'No operation will be executed. The decision remains in the case history.'
                  : confirm.proposal.kind === 'publish_patch'
                    ? 'Records a verified patch artifact in this case report. It does not change GitHub, deploy software, or execute arbitrary code.'
                    : 'The backend rechecks the revision, proposal hash, approval and expiry before applying the scoped operation.'}
            </p>
            <div className="modal-actions">
              <button
                className="button secondary"
                disabled={!!busy}
                onClick={() => setConfirm(null)}
              >
                Cancel
              </button>
              <button className="button" disabled={!!busy} onClick={decide}>
                {busy ? <LoaderCircle size={15} className="spin" /> : <Check size={15} />}{' '}
                {confirm.action === 'approve'
                  ? 'Approve proposal'
                  : confirm.action === 'reject'
                    ? 'Reject proposal'
                    : confirm.proposal.kind === 'publish_patch'
                      ? 'Export verified patch'
                      : 'Execute action'}
              </button>
            </div>
          </section>
        </div>
      )}
    </div>
  );
}

function casesHaveActive(cases: CaseSummary[]) {
  return cases.some((item) => activeRun({ status: item.latest_run_status || '' }));
}
function EvidenceCard({
  item,
  index,
  open,
  onToggle,
}: {
  item: Evidence;
  index: number;
  open: boolean;
  onToggle: () => void;
}) {
  return (
    <div className={`evidence-card ${open ? 'open' : ''}`}>
      <button className="evidence-heading" onClick={onToggle} aria-expanded={open}>
        <span className="evidence-index">{String(index + 1).padStart(2, '0')}</span>
        <div>
          <strong>{item.title}</strong>
          <small>
            {item.source} · {label(item.kind)}
          </small>
        </div>
        <ChevronRight size={16} />
      </button>
      {open && (
        <div className="evidence-content">
          <pre>{item.content}</pre>
          <p>Observed {date(item.observed_at)}</p>
          <p className="mono wrap">SHA-256 {item.sha256}</p>
        </div>
      )}
    </div>
  );
}
function ProposalCard({
  proposal,
  role,
  revision,
  busy,
  onAction,
}: {
  proposal: Proposal;
  role: Role;
  revision: number;
  busy: boolean;
  onAction: (action: 'approve' | 'reject' | 'execute') => void;
}) {
  const permissions = proposalPermission(role, proposal, revision);
  return (
    <article className="proposal-card">
      <div className="proposal-heading">
        <span className="proposal-icon">
          {proposal.kind === 'publish_patch' ? <Code2 size={18} /> : <ShieldCheck size={18} />}
        </span>
        <div>
          <h3>{proposal.title}</h3>
          <p>{proposal.description}</p>
        </div>
        <Status value={proposal.status} />
      </div>
      <div className="proposal-integrity">
        <span className="mono">{short(proposal.hash)}…</span>
        <span>Revision {proposal.case_revision}</span>
        <span>
          <Clock3 size={11} /> {date(proposal.expires_at)}
        </span>
      </div>
      {proposal.verification && (
        <JsonDetails title="Verification evidence" value={proposal.verification} />
      )}
      <JsonDetails title="Exact proposed action" value={proposal.payload} />
      {permissions.expired && proposal.status === 'pending' && (
        <p className="muted">
          This proposal expired. Run a fresh investigation before reviewing a new proposal.
        </p>
      )}
      {permissions.stale && ['pending', 'approved'].includes(proposal.status) && (
        <p className="muted">
          The case revision changed. This proposal cannot be authorized or executed from this view.
        </p>
      )}
      <div className="proposal-actions">
        {permissions.approve && (
          <button className="button small" disabled={busy} onClick={() => onAction('approve')}>
            <Check size={13} />
            Approve
          </button>
        )}
        {permissions.reject && (
          <button
            className="button secondary small"
            disabled={busy}
            onClick={() => onAction('reject')}
          >
            Reject
          </button>
        )}
        {permissions.execute && (
          <button className="button small" disabled={busy} onClick={() => onAction('execute')}>
            <Play size={12} />
            {proposal.kind === 'publish_patch'
              ? 'Export verified patch'
              : 'Execute approved action'}
          </button>
        )}
        {proposal.status === 'pending' && role !== 'reviewer' && (
          <p className="role-hint">
            <LockKeyhole size={12} /> Switch to Reviewer to authorize this proposal.
          </p>
        )}
        {proposal.status === 'approved' && role !== 'operator' && (
          <p className="role-hint">
            <LockKeyhole size={12} /> Switch to Operator to execute the approved proposal.
          </p>
        )}
      </div>
    </article>
  );
}
function RepairView({ detail }: { detail: CaseDetail }) {
  const repair = detail.repair!;
  return (
    <div className="repair-view">
      <div className="repair-mode">
        <Badge tone={repair.mode === 'fixture' ? 'amber' : 'blue'}>
          {repair.mode === 'fixture' ? 'Deterministic fixture repair' : 'Model-proposed repair'}
        </Badge>
        <span className="mono">{repair.language}</span>
      </div>
      <p>{repair.explanation}</p>
      <div className="verification-grid">
        <div>
          <span>Before repair</span>
          <strong>
            {repair.baseline.passed}/{repair.baseline.total}
          </strong>
          <small>Checks passed before repair</small>
        </div>
        <div
          className={
            repair.verification.passed === repair.verification.total &&
            repair.verification.total > 0
              ? 'verified'
              : ''
          }
        >
          <span>Candidate verification</span>
          <strong>
            {repair.verification.passed}/{repair.verification.total}
          </strong>
          <small>Checks passed for candidate</small>
        </div>
      </div>
      <div className="diff-panel">
        <div>
          <Code2 size={14} />
          <span>{repair.filename}</span>
        </div>
        <pre>
          {repair.diff.split('\n').map((line, index) => (
            <span
              key={index}
              className={
                line.startsWith('+') && !line.startsWith('+++')
                  ? 'added'
                  : line.startsWith('-') && !line.startsWith('---')
                    ? 'removed'
                    : ''
              }
            >
              {line}
              {'\n'}
            </span>
          ))}
        </pre>
      </div>
      <JsonDetails title="Original expression" value={repair.original} />
      <JsonDetails title="Candidate expression" value={repair.candidate} />
      <JsonDetails
        title="Baseline and protected verifier results"
        value={{ baseline: repair.baseline, verification: repair.verification }}
      />
      <p className="mono wrap hash-label">Patch hash: {repair.patch_hash}</p>
      {repair.limitations.length > 0 && (
        <div className="repair-limitations">
          <strong>Execution boundary</strong>
          <ul>
            {repair.limitations.map((item, index) => (
              <li key={index}>{item}</li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}
