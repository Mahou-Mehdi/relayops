import type { Evaluation, EvaluationSummary } from './types';

export interface EvaluationState {
  history: EvaluationSummary[];
  selectedId: string | null;
  report: Evaluation | null;
  historyLoading: boolean;
  reportLoading: boolean;
  historyError: string;
  reportError: string;
}

export const initialEvaluationState: EvaluationState = {
  history: [],
  selectedId: null,
  report: null,
  historyLoading: true,
  reportLoading: false,
  historyError: '',
  reportError: '',
};

type EvaluationAction =
  | { type: 'history-loading' }
  | { type: 'history-loaded'; history: EvaluationSummary[] }
  | { type: 'history-error'; error: string }
  | { type: 'select'; id: string }
  | { type: 'report-loading'; id: string }
  | { type: 'report-loaded'; id: string; report: Evaluation }
  | { type: 'report-error'; id: string; error: string }
  | { type: 'saved'; report: Evaluation };

export function evaluationReducer(
  state: EvaluationState,
  action: EvaluationAction,
): EvaluationState {
  switch (action.type) {
    case 'history-loading':
      return { ...state, historyLoading: true, historyError: '' };
    case 'history-loaded': {
      const selectedId = action.history.some((entry) => entry.id === state.selectedId)
        ? state.selectedId
        : action.history[0]?.id || null;
      const report = state.report?.id === selectedId ? state.report : null;
      return {
        ...state,
        history: action.history,
        selectedId,
        report,
        historyLoading: false,
        reportLoading: Boolean(selectedId && !report),
        historyError: '',
        reportError: selectedId === state.selectedId ? state.reportError : '',
      };
    }
    case 'history-error':
      return { ...state, historyLoading: false, historyError: action.error };
    case 'select':
      if (action.id === state.selectedId || !state.history.some((entry) => entry.id === action.id))
        return state;
      return {
        ...state,
        selectedId: action.id,
        report: null,
        reportLoading: true,
        reportError: '',
      };
    case 'report-loading':
      return action.id === state.selectedId
        ? { ...state, report: null, reportLoading: true, reportError: '' }
        : state;
    case 'report-loaded':
      return action.id === state.selectedId && action.report.id === action.id
        ? { ...state, report: action.report, reportLoading: false, reportError: '' }
        : state;
    case 'report-error':
      return action.id === state.selectedId
        ? { ...state, report: null, reportLoading: false, reportError: action.error }
        : state;
    case 'saved':
      return {
        ...state,
        history: [
          action.report,
          ...state.history.filter((entry) => entry.id !== action.report.id),
        ].slice(0, 20),
        selectedId: action.report.id,
        report: action.report,
        historyLoading: false,
        reportLoading: false,
        historyError: '',
        reportError: '',
      };
  }
}
