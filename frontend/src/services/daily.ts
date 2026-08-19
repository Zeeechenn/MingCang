import { request } from './http';

export type DailyLifecycle = 'stable' | 'shadow' | 'dormant' | 'rejected' | string;
export type DailyCardStatus = 'ready' | 'degraded' | 'missing' | 'blocked' | string;

export interface DailyPanelCard {
  card_type: string;
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
