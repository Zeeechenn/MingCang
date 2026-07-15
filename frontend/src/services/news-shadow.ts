import { request } from './http';

export const getNewsShadowSummary = (asOf = '') =>
  request(`/news-shadow/summary${asOf ? `?as_of=${encodeURIComponent(asOf)}` : ''}`);

export const getNewsShadowRuns = ({ asOf = '', symbol = '', onlyDivergent = false, limit = 200 } = {}) => {
  const params = new URLSearchParams();
  if (asOf) params.set('as_of', asOf);
  if (symbol) params.set('symbol', symbol);
  if (onlyDivergent) params.set('only_divergent', 'true');
  params.set('limit', String(limit));
  return request(`/news-shadow/runs?${params.toString()}`);
};

export const getNewsShadowRun = (runId) =>
  request(`/news-shadow/runs/${encodeURIComponent(runId)}`);

export const createNewsShadowFeedback = (runId, payload) =>
  request(`/news-shadow/runs/${encodeURIComponent(runId)}/feedback`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
