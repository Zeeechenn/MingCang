import { request } from './http';

export type DailyLifecycle = 'stable' | 'shadow' | 'dormant' | 'rejected' | string;
export type DailyCardStatus = 'ready' | 'degraded' | 'missing' | 'blocked' | string;

export interface DailyPanelCard {
  card_type: string;
  product_group?: string | null;
  lifecycle: DailyLifecycle;
  status: DailyCardStatus;
  summary: string;
  payload: Record<string, any>;
  evidence_refs: Array<Record<string, any>>;
  run_ref: Record<string, any> | null;
  drilldown: {
    kind: string;
    href: string | null;
    label: string;
  };
}

export interface DailyPanel {
  schema_version: 'daily_panel.v1' | string;
  mode: string;
  as_of: string | null;
  generated_at: string | null;
  status: string;
  cards: DailyPanelCard[];
  lifecycle_visibility: Record<string, string[]>;
  source_contract: Record<string, any>;
}

export function getDailyPanelLatest(mode = 'postmarket'): Promise<DailyPanel> {
  return request(`/daily/panel/latest?mode=${encodeURIComponent(mode)}`);
}

export type ReviewChoice = 'accepted' | 'modified' | 'rejected';
export type ReviewOutcome = 'supported' | 'contradicted' | 'inconclusive' | 'not_observed';
export interface HumanReviewSource {
  item_id: string; panel_as_of: string; panel_sha256: string; run_id: string;
  card_type: string; subject: string; name: string; summary: string;
  original: Record<string, unknown>; expires_at: string | null;
  validity: 'valid' | 'expired' | 'unknown'; source_status: string; reviewable: boolean;
}
export interface HumanReview {
  review_id: string; source: HumanReviewSource; can_execute: false;
  result: {
    version: number; recorded_at: string; actual_execution: string; queue_task_completed: false;
    decision: { choice: ReviewChoice; rationale: string; revised_text: string };
    outcomes: Array<{ observation_id: string; status: ReviewOutcome; note: string; recorded_at: string; source: string }>;
  };
}
export interface DailyReviews {
  panel_as_of: string | null; panel_sha256: string | null; warning: string | null;
  items: Array<HumanReviewSource & { review: HumanReview | null }>;
  history: HumanReview[]; history_limit: number; can_execute: false;
}
export const getDailyReviews = (asOf: string): Promise<DailyReviews> =>
  request(`/daily/reviews?as_of=${encodeURIComponent(asOf)}`);
export const saveDailyReview = (payload: {
  as_of: string; panel_sha256: string; item_id: string; choice: ReviewChoice; rationale: string; revised_text: string;
}): Promise<HumanReview> => request('/daily/reviews', {
  method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload),
});
export const saveDailyReviewOutcome = (reviewId: string, payload: {
  expected_version: number; observation_id: string; status: ReviewOutcome; note: string;
}): Promise<HumanReview> => request(`/daily/reviews/${encodeURIComponent(reviewId)}/outcomes`, {
  method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload),
});
