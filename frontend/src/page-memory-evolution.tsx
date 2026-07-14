// ============================================================
// Memory Evolution — M57 候选治理台
// ============================================================
import React from 'react';
import {
  archiveMemoryEvolutionCandidate,
  getMemoryEvolutionCandidate,
  getMemoryEvolutionCandidates,
  promoteMemoryEvolutionCandidate,
  rejectMemoryEvolutionCandidate,
} from './services/api';
import { Badge, Card, Metric, PageHead, Seg, toast } from './shared';

const { useCallback, useEffect, useMemo, useState } = React;

const STATUS_OPTIONS = [
  ['pending', '待处理'],
  ['trusted', '已升级'],
  ['rejected', '已拒绝'],
  ['archived', '已归档'],
];

function statusTone(status) {
  if (status === 'trusted') return 'badge-up';
  if (status === 'rejected') return 'badge-down';
  if (status === 'archived') return 'badge-dim';
  return 'badge-warn';
}

function CandidateList({ items, selectedId, onSelect }: any) {
  if (!items.length) return <div className="empty">当前筛选下没有候选。</div>;
  return (
    <div className="grid" style={{ gap: 8 }}>
      {items.map((item) => (
        <button
          key={item.id}
          type="button"
          className="glass-inset"
          onClick={() => onSelect(item.id)}
          style={{
            padding: '11px 13px',
            textAlign: 'left',
            borderColor: selectedId === item.id ? 'var(--accent)' : undefined,
          }}
        >
          <div className="spread" style={{ gap: 8, flexWrap: 'wrap' }}>
            <div className="row" style={{ gap: 6, flexWrap: 'wrap' }}>
              <Badge tone={statusTone(item.source_trust)}>{item.source_trust}</Badge>
              <Badge tone="badge-dim">{item.memory_type}</Badge>
              <span className="t-num t-faint" style={{ fontSize: 11.5 }}>{item.symbol}</span>
            </div>
            <span className="t-num t-faint" style={{ fontSize: 11 }}>{item.created_at || ''}</span>
          </div>
          <div style={{ fontSize: 13, lineHeight: 1.5, marginTop: 7, color: 'var(--ink-2)' }}>
            {item.summary}
          </div>
        </button>
      ))}
    </div>
  );
}

function EvidenceChain({ events }: any) {
  if (!events?.length) return <div className="empty">没有可展示的 trace 证据。</div>;
  return (
    <div className="grid" style={{ gap: 8 }}>
      {events.map((event) => (
        <div key={event.id} className="glass-inset" style={{ padding: '10px 12px' }}>
          <div className="spread" style={{ gap: 8, flexWrap: 'wrap' }}>
            <div className="row" style={{ gap: 6, flexWrap: 'wrap' }}>
              <Badge tone="badge-accent">trace #{event.id}</Badge>
              <Badge tone="badge-dim">{event.trace_type}</Badge>
              <span className="t-faint" style={{ fontSize: 11.5 }}>{event.namespace}</span>
            </div>
            <span className="t-num t-faint" style={{ fontSize: 11 }}>{event.event_time}</span>
          </div>
          <div style={{ fontSize: 12.5, lineHeight: 1.55, marginTop: 7, color: 'var(--ink-2)' }}>
            {event.content}
          </div>
          {(event.symbols?.length || event.themes?.length) && (
            <div className="row" style={{ gap: 5, flexWrap: 'wrap', marginTop: 7 }}>
              {(event.symbols || []).map((symbol) => <Badge key={`s-${event.id}-${symbol}`} tone="badge-dim">{symbol}</Badge>)}
              {(event.themes || []).map((theme) => <Badge key={`t-${event.id}-${theme}`} tone="badge-warn">{theme}</Badge>)}
            </div>
          )}
        </div>
      ))}
    </div>
  );
}

function CandidateDiff({ diff }: any) {
  return (
    <div className="grid" style={{ gridTemplateColumns: 'minmax(0, 1fr) minmax(0, 1fr)', gap: 10 }}>
      <div className="glass-inset" style={{ padding: 13 }}>
        <div className="t-eyebrow">新候选</div>
        <div style={{ fontSize: 13, lineHeight: 1.6, marginTop: 8 }}>{diff?.candidate || '无内容'}</div>
      </div>
      <div className="glass-inset" style={{ padding: 13 }}>
        <div className="t-eyebrow">同主题现有记忆</div>
        {diff?.existing?.length ? (
          <div className="grid" style={{ gap: 7, marginTop: 8 }}>
            {diff.existing.map((row) => (
              <div key={`${row.source}-${row.id}`} style={{ fontSize: 12.5, lineHeight: 1.5, color: 'var(--ink-2)' }}>
                <Badge tone={row.status === 'trusted' || row.status === 'active' ? 'badge-up' : 'badge-dim'}>{row.status}</Badge>
                <span style={{ marginLeft: 7 }}>{row.summary}</span>
              </div>
            ))}
          </div>
        ) : (
          <div className="empty" style={{ marginTop: 8 }}>未找到同主题 trusted/active 记忆。</div>
        )}
      </div>
    </div>
  );
}

export function MemoryEvolutionPage() {
  const [status, setStatus] = useState('pending');
  const [items, setItems] = useState<any[]>([]);
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [detail, setDetail] = useState<any>(null);
  const [loading, setLoading] = useState(false);
  const [acting, setActing] = useState('');
  const [reason, setReason] = useState('');

  const loadList = useCallback(async (nextStatus) => {
    setLoading(true);
    try {
      const payload = await getMemoryEvolutionCandidates(nextStatus, 50, 0);
      const nextItems = payload.items || [];
      setItems(nextItems);
      setSelectedId((currentId) => nextItems.some((item) => item.id === currentId) ? currentId : nextItems[0]?.id || null);
    } catch (err: any) {
      setItems([]);
      setSelectedId(null);
      toast(`候选加载失败:${err?.message || '后端错误'}`);
    } finally {
      setLoading(false);
    }
  }, []);

  const loadDetail = useCallback(async (id) => {
    if (!id) { setDetail(null); return; }
    try {
      setDetail(await getMemoryEvolutionCandidate(id));
    } catch (err: any) {
      setDetail(null);
      toast(`详情加载失败:${err?.message || '后端错误'}`);
    }
  }, []);

  useEffect(() => { loadList(status); }, [status, loadList]);
  useEffect(() => { loadDetail(selectedId); }, [selectedId, loadDetail]);

  const counts = useMemo(() => ({
    total: items.length,
    pending: items.filter((item) => item.source_trust === 'pending').length,
    selected: selectedId || '-',
  }), [items, selectedId]);

  async function act(kind) {
    if (!selectedId) return;
    if ((kind === 'reject' || kind === 'archive') && !reason.trim()) {
      toast('请先填写原因');
      return;
    }
    setActing(kind);
    try {
      if (kind === 'promote') await promoteMemoryEvolutionCandidate(selectedId);
      if (kind === 'reject') await rejectMemoryEvolutionCandidate(selectedId, reason.trim());
      if (kind === 'archive') await archiveMemoryEvolutionCandidate(selectedId, reason.trim());
      toast(kind === 'promote' ? '候选已通过人审升级' : kind === 'reject' ? '候选已拒绝' : '候选已归档');
      setReason('');
      await loadList(status);
    } catch (err: any) {
      toast(`操作失败:${err?.message || '后端错误'}`);
    } finally {
      setActing('');
    }
  }

  const candidate = detail?.candidate;
  const pending = candidate?.source_trust === 'pending';

  return (
    <div className="grid" style={{ gap: 14 }}>
      <PageHead
        eyebrow="M57 Memory Evolution"
        title="记忆自进化治理台"
        desc="审查 profile miner 生成的 pending 候选、trace 证据链和同主题记忆差异。升级必须走本地人审 gate。"
        right={<Badge tone="badge-warn">Shadow Eval 暂未开放</Badge>}
      />

      <div className="grid" style={{ gridTemplateColumns: 'repeat(3, minmax(0, 1fr))', gap: 8 }}>
        <Metric label="当前筛选候选" value={loading ? '...' : counts.total} />
        <Metric label="待处理" value={counts.pending} tone="up" />
        <Metric label="选中 ID" value={counts.selected} />
      </div>

      <div className="grid" style={{ gridTemplateColumns: '340px minmax(0, 1fr)', gap: 14, alignItems: 'start' }}>
        <Card eyebrow="Candidates" title="候选列表" className="pop">
          <Seg value={status} options={STATUS_OPTIONS} onChange={setStatus} />
          <div style={{ marginTop: 12 }}>
            <CandidateList items={items} selectedId={selectedId} onSelect={setSelectedId} />
          </div>
        </Card>

        <div className="grid" style={{ gap: 14 }}>
          <Card eyebrow="Detail" title={candidate ? `候选 #${candidate.id}` : '候选详情'} className="pop">
            {!candidate ? (
              <div className="empty">请选择一个候选。</div>
            ) : (
              <div className="grid" style={{ gap: 12 }}>
                <div className="spread" style={{ gap: 8, flexWrap: 'wrap' }}>
                  <div className="row" style={{ gap: 6, flexWrap: 'wrap' }}>
                    <Badge tone={statusTone(candidate.source_trust)}>{candidate.source_trust}</Badge>
                    <Badge tone="badge-dim">{candidate.memory_type}</Badge>
                    <Badge tone="badge-accent">{candidate.symbol}</Badge>
                  </div>
                  <span className="t-num t-faint" style={{ fontSize: 11.5 }}>{candidate.source_ref}</span>
                </div>
                <CandidateDiff diff={detail.diff} />
                <div className="glass-inset" style={{ padding: 13 }}>
                  <div className="spread" style={{ gap: 10, flexWrap: 'wrap' }}>
                    <div>
                      <div className="t-eyebrow">治理动作</div>
                      <div className="t-faint" style={{ fontSize: 12, marginTop: 4 }}>
                        promote 复用本地 human gate；reject 必须写原因并回写 trace。
                      </div>
                    </div>
                    <div className="row" style={{ gap: 7, flexWrap: 'wrap' }}>
                      <button className="btn btn-sm" disabled={!pending || !!acting} onClick={() => act('promote')}>{acting === 'promote' ? '处理中...' : 'Promote'}</button>
                      <button className="btn btn-sm btn-danger" disabled={!pending || !!acting} onClick={() => act('reject')}>{acting === 'reject' ? '处理中...' : 'Reject'}</button>
                      <button className="btn btn-sm btn-quiet" disabled={!pending || !!acting} onClick={() => act('archive')}>{acting === 'archive' ? '处理中...' : 'Archive'}</button>
                      <button className="btn btn-sm btn-quiet" disabled title="Shadow evaluator 属于后续 Phase">Run Shadow Eval</button>
                    </div>
                  </div>
                  <textarea
                    className="field"
                    value={reason}
                    onChange={(event) => setReason(event.target.value)}
                    placeholder="拒绝或归档原因"
                    style={{ marginTop: 10, width: '100%', minHeight: 70, resize: 'vertical' }}
                  />
                </div>
              </div>
            )}
          </Card>

          <Card eyebrow="Evidence" title="Trace 证据链" className="pop">
            <EvidenceChain events={detail?.source_events || []} />
          </Card>
        </div>
      </div>
    </div>
  );
}

window.MemoryEvolutionPage = MemoryEvolutionPage;
