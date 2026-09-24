import { request } from './http';

export interface ResearchSelection { symbol: string; market: 'CN'; start: string; as_of: string; adjustment: 'stored' }
export interface ResearchSource {
  id: string; kind: string; source: string | null; date: string; disclosure_date?: string;
  adjustment?: string | null; currency: string | null; fetched_at: string | null; values: Record<string, number | null>;
  value_units?: Record<string, string>; value_calculations?: Record<string, string>;
}
export interface ResearchContext {
  selection: ResearchSelection; context_sha256: string; sources: ResearchSource[];
  gaps: string[]; limitations: string[]; can_ask: boolean;
}
export type ResearchHorizon = 'short' | 'medium' | 'long';
export interface ResearchTaskSpec extends ResearchSelection {
  question: string;
  horizon: ResearchHorizon;
  budget_tokens: number;
  max_calls: 1;
}
export interface PreparedResearchTask {
  schema_version: 'research_task.v1';
  task: ResearchTaskSpec & { context_sha256: string };
  evidence: ResearchContext;
  prior_judgments: any[];
  execution: { mode: 'prepare_only'; model_calls: 0; max_calls: 1; budget_tokens: number };
  can_ask: boolean;
}
export interface ResearchTaskStatus {
  request_id: string;
  status: 'running' | 'executed' | 'failed' | string;
  execution: Record<string, any>;
  response?: any;
  input_sha256?: string;
}
export const loadResearchContext = (selection: ResearchSelection): Promise<ResearchContext> =>
  request(`/research/${selection.symbol}/page-context?${new URLSearchParams({ ...selection })}`);
export const prepareResearchTask = (task: ResearchTaskSpec): Promise<PreparedResearchTask> => request('/research/task/prepare', {
  method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(task),
});
export const loadResearchTaskStatus = (requestId: string): Promise<ResearchTaskStatus> =>
  request(`/research/tasks/${encodeURIComponent(requestId)}`);
export const loadResearchReviews = (symbol: string): Promise<{ reviews: any[] }> => request(`/research/${symbol}/page-reviews`);
export const saveResearchReview = (payload: any) => request('/research/page-reviews', {
  method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload),
});
export const saveResearchObservation = (id: string, payload: any) => request(`/research/page-reviews/${encodeURIComponent(id)}/outcomes`, {
  method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload),
});
export const loadResearchMessages = (id: string): Promise<any[]> => request(`/ai/sessions/${encodeURIComponent(id)}/messages`);
