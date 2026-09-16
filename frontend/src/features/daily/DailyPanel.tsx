import { Badge, Card, navigate } from '../../shared';
import type { DailyPanel, DailyPanelCard } from '../../services/daily';

const CARD_LABEL: Record<string, string> = {
  batch_integrity: '批次完整性',
  candidate: '候选变化',
  position_health: '持仓体检',
  event_risk: '新闻/事件风险',
  watchtower: '观察哨',
  daily_delta: '上一交易日变化',
  human_confirmation: '人工确认',
  review_attribution: '复盘归因',
};

const STATUS_TONE: Record<string, string> = {
  ready: 'badge-up',
  ready_zero: 'badge-up',
  not_applicable: 'badge-dim',
  degraded: 'badge-warn',
  missing: 'badge-dim',
  blocked: 'badge-down',
};

const STATUS_LABEL: Record<string, string> = {
  ready: '已就绪', ready_zero: '已核对 · 无新增', not_applicable: '本次未启用',
  degraded: '证据不完整', missing: '缺少证据', blocked: '待处理',
};
const PAYLOAD_LABEL: Record<string, string> = {
  items: '明细', vetoed_items: '排除项', shadow_discretion_cards: '影子研究',
  stale_discretion_count: '过期研究数', verification: '核对状态',
  risk_budget: '风险预算', stop_loss_buffer: '止损余量', followups: '扫描结果',
  confirm: '确认记录', notification_contract: '通知规则', suppression_history_status: '通知历史',
  direction_weights: '方向权重', panel_payload: '事件概览', pending_queue: '待确认项',
  queue_stale_count: '历史待办数', queue_status: '队列状态', panel_as_of: '交易日',
  structured_delta: '名单变化', m63_report: '盘后报告', missing_reason: '缺失原因',
  selector_status: '批次状态', candidate_count: '完整批次数', source_flags: '来源提示',
  no_synthetic_batch: '仅使用真实批次',
};

function SourceExplanation({ card }: { card: DailyPanelCard }) {
  const payload = card.payload || {};
  const delta = payload.structured_delta;
  const reason = payload.reason || payload.followups?.reason || delta?.reason;
  const oldCount = payload.queue_stale_count || 0;
  if (!reason && !delta && !oldCount) return null;
  return <div className="glass-inset" style={{ padding: 10, fontSize: 13, lineHeight: 1.6, overflowWrap: 'anywhere' }}>
    {reason && <div>{reason}</div>}
    {delta && <div>当前 {delta.current_as_of || '未知'} · 对比 {delta.previous_as_of || '暂无已提交记录'}</div>}
    {delta?.candidate_added?.length > 0 && <div>新增候选：{delta.candidate_added.join('、')}</div>}
    {delta?.candidate_removed?.length > 0 && <div>移出候选：{delta.candidate_removed.join('、')}</div>}
    {oldCount > 0 && <div>{oldCount} 项来自历史交易日，仍待人工处理；未回复的事项继续保留。</div>}
  </div>;
}

const LIFE_TONE: Record<string, string> = {
  stable: 'badge-accent',
  shadow: 'badge-warn',
  dormant: 'badge-dim',
  rejected: 'badge-down',
};

function tone(map: Record<string, string>, key: string) {
  return map[key] || 'badge-dim';
}

function compactValue(value: any): string {
  if (value == null || value === '') return '—';
  if (typeof value === 'string' || typeof value === 'number' || typeof value === 'boolean') return String(value);
  if (Array.isArray(value)) return `${value.length} 项`;
  if (typeof value === 'object') {
    const keys = Object.keys(value);
    return keys.length ? keys.slice(0, 3).join(' / ') : '空';
  }
  return String(value);
}

function EvidenceRefs({ card }: { card: DailyPanelCard }) {
  const refs = card.evidence_refs || [];
  return (
    <div className="grid" style={{ gap: 6 }}>
      <div className="t-eyebrow">Evidence / Run Trace</div>
      <div className="row" style={{ gap: 6, flexWrap: 'wrap' }}>
        {card.run_ref ? (
          <Badge tone="badge-accent">Run {card.run_ref.run_id || card.run_ref.batch_id || 'linked'}</Badge>
        ) : (
          <Badge tone="badge-warn">RunEnvelope missing</Badge>
        )}
        {refs.length ? refs.slice(0, 3).map((ref, idx) => (
          <Badge key={`${ref.source_type || 'ref'}-${idx}`} tone={ref.status === 'stale' ? 'badge-warn' : 'badge-dim'}>
            {ref.source_type || 'evidence'} {ref.status || ''}
          </Badge>
        )) : <Badge tone="badge-warn">evidence missing</Badge>}
      </div>
    </div>
  );
}

function PayloadPreview({ card }: { card: DailyPanelCard }) {
  const payload = card.payload || {};
  const entries = Object.entries(payload).filter(([key]) => key !== 'run_card' && key !== 'reason').slice(0, 4);
  if (!entries.length) return <div className="t-faint" style={{ fontSize: 12 }}>暂无结构化 payload。</div>;
  return (
    <div className="grid" style={{ gridTemplateColumns: 'repeat(auto-fit, minmax(130px, 1fr))', gap: 8 }}>
      {entries.map(([key, value]) => (
        <div key={key} className="glass-inset" style={{ padding: '9px 10px', minWidth: 0 }}>
          <div
            className="t-eyebrow"
            data-payload-key={key}
            style={{ minWidth: 0, whiteSpace: 'normal', overflowWrap: 'anywhere', wordBreak: 'break-word' }}
          >
            {PAYLOAD_LABEL[key] || key}
          </div>
          <div className="t-dim" style={{ fontSize: 12.5, marginTop: 4, lineHeight: 1.4, overflowWrap: 'anywhere' }}>{compactValue(value)}</div>
        </div>
      ))}
    </div>
  );
}

export function DailyCard({ card }: { card: DailyPanelCard }) {
  const href = card.drilldown?.href;
  return (
    <Card
      eyebrow={card.product_group || card.card_type}
      title={CARD_LABEL[card.card_type] || card.card_type}
      className="pop"
      right={(
        <div className="row" style={{ gap: 6, flexWrap: 'wrap', justifyContent: 'flex-end' }}>
          <Badge tone={tone(LIFE_TONE, card.lifecycle)}>{card.lifecycle}</Badge>
          <Badge tone={tone(STATUS_TONE, card.status)}>{STATUS_LABEL[card.status] || card.status}</Badge>
        </div>
      )}
    >
      <div className="grid" style={{ gap: 12 }}>
        <p className="t-dim" style={{ margin: 0, fontSize: 13.5, lineHeight: 1.6 }}>{card.summary || '暂无摘要'}</p>
        <SourceExplanation card={card} />
        <PayloadPreview card={card} />
        <EvidenceRefs card={card} />
        {href && (
          <button
            type="button"
            className="btn btn-sm"
            onClick={() => navigate(href)}
            aria-label={`${CARD_LABEL[card.card_type] || card.card_type} drilldown ${card.drilldown.label}`}
            style={{ justifySelf: 'start' }}
          >
            {card.drilldown.label} →
          </button>
        )}
      </div>
    </Card>
  );
}

export function DailyPanelHeader({ panel }: { panel: DailyPanel }) {
  const visibility = panel.lifecycle_visibility || {};
  return (
    <section className="glass pop" style={{ padding: 16, overflow: 'hidden' }} aria-label="daily-panel-summary">
      <div className="spread" style={{ gap: 12, alignItems: 'flex-start', flexWrap: 'wrap' }}>
        <div style={{ minWidth: 0 }}>
          <div className="t-eyebrow">daily_panel.v1 · {panel.mode}</div>
          <h2 className="t-title" style={{ margin: '3px 0 0' }}>单一日常产品面</h2>
          <div className="t-dim" style={{ marginTop: 6, fontSize: 13 }}>as_of {panel.as_of || 'unknown'} · {panel.status}</div>
        </div>
        <div className="row" style={{ gap: 6, flexWrap: 'wrap', justifyContent: 'flex-end' }}>
          {(['stable', 'shadow', 'dormant', 'rejected'] as const).map((key) => (
            <Badge key={key} tone={tone(LIFE_TONE, key)}>{key} {(visibility[key] || []).length}</Badge>
          ))}
        </div>
      </div>
    </section>
  );
}

export function DailyPanelCards({ cards }: { cards: DailyPanelCard[] }) {
  return (
    <section
      className="grid"
      aria-label="daily-panel-cards"
      style={{ gridTemplateColumns: 'repeat(auto-fit, minmax(min(100%, 290px), 1fr))', gap: 12, minWidth: 0 }}
    >
      {cards.map((card) => <DailyCard key={card.card_type} card={card} />)}
    </section>
  );
}
