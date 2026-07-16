import React from 'react';

export type LiveMode = 'demo' | 'live' | 'degraded' | 'offline';
export type SourceMode = 'live' | 'demo' | 'stale' | 'error';
export type LiveSources = Record<string, SourceMode>;

export function deriveLiveMode(sources: LiveSources): LiveMode {
  const values = Object.values(sources);
  if (!values.length || values.every((value) => value === 'demo')) return 'demo';
  return values.every((value) => value === 'live') ? 'live' : 'degraded';
}

const MODE_LABEL: Record<LiveMode, string> = {
  live: '本地后端',
  degraded: '部分实时',
  offline: '后端断开',
  demo: '示例快照',
};

export function LiveStatusBadgeView({
  mode,
  sources = {},
  snapshotAsOf,
  issues = [],
}: {
  mode: LiveMode;
  sources?: LiveSources;
  snapshotAsOf?: string;
  issues?: string[];
}) {
  const nonLive = Object.entries(sources)
    .filter(([, value]) => value !== 'live')
    .map(([name, value]) => `${name}:${value}`);
  const detail = mode === 'live'
    ? '已连接本地后端，核心数据域均来自 /api'
    : mode === 'offline'
      ? '后端连接中断，保留最后一次页面数据'
      : mode === 'degraded'
        ? issues.length
          ? `运行身份或数据域降级：${issues.join('；')}；${nonLive.join('、') || '未知'}`
          : `部分数据域回退：${nonLive.join('、') || '未知'}；示例快照 ${snapshotAsOf || '日期未知'}`
        : `后端未连接，当前展示示例快照 ${snapshotAsOf || '日期未知'}`;

  return (
    <span className="nav-status" title={detail} data-live-mode={mode}>
      <span className="pulse-dot" style={mode === 'live' ? undefined : { background: 'var(--warn)' }} />
      <span className="nav-local-label">{MODE_LABEL[mode]}</span>
    </span>
  );
}
