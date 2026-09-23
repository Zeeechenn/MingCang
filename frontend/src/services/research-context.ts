import { request } from './http';

export interface ResearchSelection { symbol: string; market: 'CN'; start: string; as_of: string; adjustment: 'stored' }
export interface ResearchSource {
  id: string; kind: string; source: string | null; date: string; disclosure_date?: string;
  adjustment?: string | null; currency: string | null; fetched_at: string | null; values: Record<string, number | null>;
}
export interface ResearchContext {
  selection: ResearchSelection; context_sha256: string; sources: ResearchSource[];
  gaps: string[]; limitations: string[]; can_ask: boolean;
}
export const loadResearchContext = (selection: ResearchSelection): Promise<ResearchContext> =>
  request(`/research/${selection.symbol}/page-context?${new URLSearchParams({ ...selection })}`);
export const loadResearchReviews = (symbol: string): Promise<{ reviews: any[] }> => request(`/research/${symbol}/page-reviews`);
export const saveResearchReview = (payload: any) => request('/research/page-reviews', {
  method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload),
});
export const saveResearchObservation = (id: string, payload: any) => request(`/research/page-reviews/${encodeURIComponent(id)}/outcomes`, {
  method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload),
});
export const loadResearchMessages = (id: string): Promise<any[]> => request(`/ai/sessions/${encodeURIComponent(id)}/messages`);
