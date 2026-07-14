// ============================================================
// 来源健康页 — 提供商回退链 / 全球数据边界 / 检查项 / 告警 / 覆盖
// ============================================================

import React from 'react';
import { refreshCoverage } from './services/live';
import { Badge, Card, MKT, PageHead, RefreshButton, navigate, toast, useStore } from './shared';

function exportCoverageSnapshot(stocks: any[]) {
  const escape = (value: unknown) => `"${String(value ?? '').replace(/"/g, '""')}"`;
  const lines = [
    ['symbol', 'name', 'market', 'latest_price_date', 'status'],
    ...stocks.map((stock) => [stock.symbol, stock.name, stock.market, stock.latest_price_date, stock.status]),
  ];
  const blob = new Blob([`\uFEFF${lines.map((row) => row.map(escape).join(',')).join('\n')}`], { type: 'text/csv;charset=utf-8' });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement('a');
  anchor.href = url;
  anchor.download = 'mingcang-coverage-demo.csv';
  anchor.click();
  URL.revokeObjectURL(url);
}

export function HealthPage() {
  const [state] = useStore();
  const C = window.MC_DATA.COVERAGE;
  const checks = Object.entries(C.checks);
  const allPass = checks.every(([, v]) => v);

  return (
    <div className="grid" style={{ gap: 14 }}>
      <PageHead eyebrow="Sources · Read Only" title="来源健康"
        desc="展示 CN / HK / US 数据包络、提供商回退链、新鲜度策略、反穿越检查和告警。重新检查只调用只读覆盖接口。"
        right={<div className="row" style={{ gap: 10 }}>
          <RefreshButton label="重新检查" busyLabel="检查中…" onRefresh={refreshCoverage} toastMsg="已重新检查数据覆盖与新鲜度(只读探测)" />
          <Badge tone={C.status === 'pass' && allPass ? 'badge-down' : 'badge-warn'}>{C.status === 'pass' ? '整体通过' : '需复核'}</Badge>
        </div>} />

      <div className="glass-inset spread" style={{ padding: '10px 14px', gap: 12, flexWrap: 'wrap' }}>
        <div>
          <div className="t-eyebrow">当前数据来源</div>
          <div className="t-dim" style={{ fontSize: 12.5, marginTop: 4 }}>
            {Object.entries(state.liveSources || {}).map(([name, mode]) => `${name}:${mode}`).join(' · ') || '示例快照'}
          </div>
        </div>
        <div className="t-num t-faint" style={{ fontSize: 11.5 }}>
          覆盖更新时间 {state.coverageUpdatedAt || C.generated_at || '未连接'} · 示例快照 {state.snapshotAsOf || window.MC_DATA.DEMO_META.snapshot_as_of}
        </div>
      </div>

      <div className="grid pop" style={{ gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))', gap: 10 }}>
        {[
          ['CN 官方信号', 'A 股生产裁决', '盘后增量 + PIT 校验', 'badge-down'],
          ['HK / US 研究', 'observe-only', '可读案卷，不进入官方信号', 'badge-dim'],
          ['反穿越', 'standing check', '证据时间戳早于信号时间', 'badge-accent'],
          ['远端调用', '默认关闭', '本地缓存优先，L3 才补充', 'badge-warn'],
        ].map(([label, value, sub, tone]) => (
          <div key={label} className="glass" style={{ padding: '14px 18px' }}>
            <div className="spread" style={{ gap: 8 }}>
              <span className="t-eyebrow">{label}</span>
              <Badge tone={tone}>{value}</Badge>
            </div>
            <div className="t-dim" style={{ fontSize: 12.5, lineHeight: 1.5, marginTop: 8 }}>{sub}</div>
          </div>
        ))}
      </div>

      <Card eyebrow="Provider Chains" title="各市场提供商回退链" className="pop" tour="provider-chains">
        <div className="grid" style={{ gridTemplateColumns: 'repeat(auto-fit, minmax(260px, 1fr))', gap: 10 }}>
          {['CN', 'HK', 'US'].map((m) => (
            <div key={m} className="glass-inset" style={{ padding: 14 }}>
              <div className="spread">
                <span style={{ fontSize: 14, fontWeight: 650 }}>{MKT[m]}</span>
                <Badge tone={m === 'CN' ? 'badge-down' : 'badge-dim'}>{m === 'CN' ? '官方信号' : 'observe-only'}</Badge>
              </div>
              <div className="t-eyebrow" style={{ marginTop: 12 }}>回退链(日线)</div>
              <div className="row" style={{ flexWrap: 'wrap', gap: 5, marginTop: 7 }}>
                {C.provider_chains[m].map((p, i) => (
                  <React.Fragment key={p}>
                    <span className="badge badge-dim t-num" style={{ fontSize: 11 }}>{p}</span>
                    {i < C.provider_chains[m].length - 1 && <span className="t-faint" style={{ fontSize: 11 }}>→</span>}
                  </React.Fragment>
                ))}
              </div>
              <div className="grid" style={{ gridTemplateColumns: '1fr auto', gap: 8, marginTop: 12 }}>
                <div>
                  <div className="t-eyebrow">盘中策略</div>
                  <div style={{ fontSize: 12.5, marginTop: 3, color: 'var(--ink-2)' }}>{C.policies[m]}</div>
                </div>
                <div style={{ textAlign: 'right' }}>
                  <div className="t-eyebrow">最大滞后</div>
                  <div className="t-num" style={{ fontSize: 13, fontWeight: 650, marginTop: 3 }}>{C.max_lag_days[m]} 天</div>
                </div>
              </div>
            </div>
          ))}
        </div>
      </Card>

      <div className="grid" style={{ gridTemplateColumns: 'repeat(auto-fit, minmax(320px, 1fr))', gap: 14 }}>
        <Card eyebrow="Checks" title="数据完整性与来源门控" className="pop pop-1">
          <div className="grid" style={{ gridTemplateColumns: 'repeat(auto-fill, minmax(150px, 1fr))', gap: 8 }}>
            {checks.map(([k, v]) => (
              <div key={k} className="glass-inset spread" style={{ padding: '9px 12px' }}>
                <span style={{ fontSize: 12.5 }}>{k}</span>
                <Badge tone={v ? 'badge-down' : 'badge-warn'}>{v ? 'pass' : 'miss'}</Badge>
              </div>
            ))}
          </div>
        </Card>

        <Card eyebrow="Warnings" title="当前来源告警" className="pop pop-1"
          right={C.warnings.length > 0 && <Badge tone="badge-warn">{C.warnings.length} 条</Badge>}>
          {C.warnings.length === 0 ? (
            <div className="empty">暂无数据警告，所有检查均通过。</div>
          ) : (
            <div className="grid" style={{ gap: 8 }}>
              {C.warnings.map((w, i) => (
                <div key={i} className="glass-inset" style={{ padding: '11px 14px', borderColor: 'var(--warn)' }}>
                  <div className="t-num" style={{ fontSize: 11.5, fontWeight: 650, color: 'var(--warn)' }}>{w.code}</div>
                  <div style={{ fontSize: 12.5, marginTop: 3, lineHeight: 1.55, color: 'var(--ink-2)' }}>{w.message}</div>
                </div>
              ))}
            </div>
          )}
        </Card>
      </div>

      <Card eyebrow="Coverage" title="研究池覆盖状态" className="pop pop-2" pad={false}
        right={<button className="btn btn-sm" onClick={() => {
          if (window.MC_LIVE?.isLive()) {
            window.open('/api/export/coverage.csv', '_blank', 'noopener,noreferrer');
            return;
          }
          exportCoverageSnapshot(C.stocks);
          toast('已导出示例快照 CSV，未调用后端');
        }}>导出 CSV</button>}>
        <div style={{ overflowX: 'auto' }} className="scroll-thin">
          <table className="mc-table" style={{ minWidth: 560 }}>
            <thead><tr><th>代码</th><th>名称</th><th>市场</th><th>最新价格日期</th><th>状态</th></tr></thead>
            <tbody>
              {C.stocks.map((s) => (
                <tr key={s.symbol}>
                  <td className="t-num">{s.symbol}</td>
                  <td><a className="link" onClick={() => navigate(`/stock/${s.symbol}`)}>{s.name}</a></td>
                  <td>{MKT[s.market]}</td>
                  <td className="t-num">{s.latest_price_date}</td>
                  <td><Badge tone={s.status === 'ok' ? 'badge-down' : 'badge-warn'}>{s.status === 'ok' ? '通过' : '需复核'}</Badge></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>
    </div>
  );
}

window.HealthPage = HealthPage;
