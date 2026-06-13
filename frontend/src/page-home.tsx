// ============================================================
// 主页 — 明仓终端 / 大对话框 / 结果驾驶台
// ============================================================
import React from 'react';
import { Badge, MCStore, MKT, Markdown, McIcon, Spark, fmt, navigate, toast, useStore } from './shared';
const {
  useState: useHState,
  useRef: useHRef,
  useEffect: useHEffect,
} = React;

const QUICK_PROMPTS = [
  ['研究股票', '研究 300308 现在还能加仓吗'],
  ['生成复盘', '复盘上周卖飞的仓位'],
  ['加自选', '把海光信息 688041 加入自选股'],
  ['配置凭证', '配置 Tushare 凭证'],
  ['调规则', '把单股仓位上限改成 12%'],
];

const HELP_CAPABILITIES = [
  ['研究标的', '查个股案卷、今日裁决、长期标签、研究副驾驶影子意见。', 'search'],
  ['生成报告', '把研究过程压缩成复盘、证伪清单、来源摘要和后续任务。', 'reports'],
  ['驾驶台展示', '把文字结论变成分数、仪表、来源、动作卡和风险表单。', 'pulse'],
  ['Agent 动作', '加自选、写复盘、改规则、配置凭证;写入前都先确认。', 'agents'],
  ['终端与副驾驶', '终端是全系统入口;研究副驾驶负责个股深度研究链。', 'admin'],
];

const INTENT_LABELS = {
  api_key: '凭证配置',
  watchlist: '自选动作',
  rule: '规则草稿',
  review: '复盘候选',
  health: '来源健康',
  long: '长期研究',
  decision: '今日裁决',
  stock: '个股研究',
  help: '帮助',
};

const SOURCE_STATUS_LABELS = {
  pass: '通过',
  warning: '警告',
  blocked: '阻塞',
};

function symbolFromText(text, fallback = '300308') {
  if (/海光信息/.test(text)) return '688041';
  const hit = String(text).match(/\b\d{6}\b|\b0\d{4}\b|\b[A-Z]{1,5}\b/i);
  return hit ? hit[0].toUpperCase() : fallback;
}

function stockOf(symbol, state) {
  const D = window.MC_DATA;
  return state.watchlist.find((w) => w.symbol === symbol)
    || D.SEARCH_POOL.find((s) => s.symbol === symbol)
    || state.watchlist.find((w) => w.symbol === '300308')
    || D.SEARCH_POOL[0];
}

function detectIntent(text) {
  if (/api\s*key|apikey|凭证|key|tushare|tavily|anspire/i.test(text)) return 'api_key';
  if (/加.*自选|加入自选|自选股|关注池|watchlist/i.test(text)) return 'watchlist';
  if (/修改|调整|改成|上限|阈值|权重|规则|仓位上限/.test(text)) return 'rule';
  if (/复盘|卖飞|错|记忆|沉淀/.test(text)) return 'review';
  if (/来源|健康|出处|provider|新鲜|审计/.test(text)) return 'health';
  if (/长期|研究团队|辩论|skill|skills/i.test(text)) return 'long';
  if (/裁决|盘前|盘后|今日|持仓/.test(text)) return 'decision';
  if (/\d{6}|加仓|减仓|能买吗|怎么看|研究/.test(text)) return 'stock';
  return 'help';
}

function newsFor(symbol) {
  const D = window.MC_DATA;
  return (D.NEWS[symbol] || D.NEWS._default || []).slice(0, 3).map((n) => ({
    label: n.source,
    status: n.audit === 'warning' ? 'warning' : 'pass',
    note: n.title,
    meta: n.published_at,
  }));
}

function defaultSignal(state, symbol) {
  const stock = state.watchlist.find((w) => w.symbol === symbol) || state.watchlist.find((w) => w.latest_signal);
  return stock?.latest_signal || state.watchlist.find((w) => w.latest_signal)?.latest_signal;
}

function buildRun(text, state) {
  const D = window.MC_DATA;
  const intent = detectIntent(text);
  const symbol = symbolFromText(text);
  const stock = stockOf(symbol, state);
  const signal = defaultSignal(state, stock.symbol);
  const position = state.positions.find((p) => p.symbol === stock.symbol && p.status !== 'closed');
  const open = state.positions.filter((p) => p.status !== 'closed');
  const marketValue = open.reduce((sum, p) => sum + p.latest_price * p.quantity, 0);
  const name = stock.name || stock.symbol;
  const baseSources = newsFor(stock.symbol);
  const baseMetrics = [
    ['综合分', fmt.signed(signal?.composite_score || 0), signal?.composite_score >= 0 ? 'up' : 'down', signal?.recommendation || '观察'],
    ['技术', fmt.signed(signal?.technical_score || 0), signal?.technical_score >= 0 ? 'up' : 'down', '趋势/量能/MACD'],
    ['情绪', fmt.signed(signal?.sentiment_score || 0, 2), signal?.sentiment_score >= 0 ? 'up' : 'down', '来源审计后参与'],
    ['持仓', position ? `${position.quantity} 股` : '未持有', '', position ? `成本 ${fmt.price(position.avg_cost)}` : '仅观察'],
  ];

  if (intent === 'watchlist') {
    const target = stockOf(symbol, state);
    return {
      intent,
      title: `加入自选 · ${target.name}`,
      summary: `识别到你想把 ${target.name} ${target.symbol} 加入关注池。`,
      answer: `## 已准备加入自选\n\n目标: **${target.name} ${target.symbol}**\n\n明仓会先把它放进关注池，后续可以读取个股案卷、生成今日裁决、进入长期研究团队。\n\n这属于写入类动作，所以不会直接执行。请在下面确认卡里确认。`,
      modules: ['个股案卷', '今日裁决', '持仓纪律'],
      trace: ['识别股票代码', '检查关注池是否已存在', '生成待确认动作'],
      metrics: [
        ['目标', target.symbol, '', target.name],
        ['市场', MKT[target.market] || target.market, '', target.industry || '待标注'],
        ['动作', '加入', 'up', '自选股'],
      ],
      cards: [
        ['为什么要确认', '加自选会改变后续裁决范围，所以先显示待确认动作。'],
        ['加入后能做什么', '可继续问“研究这只股票”或“生成今日裁决”。'],
      ],
      sources: [{ label: '演示股票池', status: 'pass', note: '来自本地演示股票池', meta: target.symbol }],
      pending: { type: 'watchlist.add', label: `确认加入自选:${target.name}`, note: '写入终端示例状态，刷新后不会持久化', payload: target },
      actions: [[`打开 ${target.name} 案卷`, `/stock/${target.symbol}`], ['打开今日裁决', '/pulse']],
    };
  }

  if (intent === 'api_key') {
    return {
      intent,
      title: '配置 Tushare 凭证',
      summary: '识别到凭证配置请求。聊天只负责发起流程，真实密钥应在本地安全输入框填写。',
      answer: `## 已准备配置凭证\n\n目标: **Tushare 凭证**\n\n为了避免误写和泄露，明仓不会鼓励你把真实密钥发进聊天记录。真实产品里会打开本地安全输入框，写入本机凭证槽位，并在治理台留下配置时间与来源记录。\n\n当前原型只演示配置状态，不要输入真实密钥。`,
      modules: ['治理台', '来源健康'],
      trace: ['识别凭证类型', '提醒不要在聊天里输入密钥', '生成本地配置确认卡'],
      metrics: [
        ['凭证槽', 'TUSHARE', '', '行情/财务数据'],
        ['写入模式', '本地', 'up', '本地优先'],
        ['风险', '需确认', 'down', '不会自动提交'],
      ],
      cards: [
        ['安全边界', '密钥不应该出现在报告、复盘、截图或消息历史里。'],
        ['下一步', '确认后治理台可显示“已配置”，来源健康重新评估覆盖率。'],
      ],
      sources: [{ label: '治理台', status: 'warning', note: '凭证配置需要二次确认', meta: '本地凭证槽位' }],
      pending: { type: 'api_key.update', label: '确认打开 Tushare 凭证配置', note: '真实密钥应在本地安全输入框填写，不会进入聊天记录', payload: { provider: 'Tushare', masked: '本地安全输入' } },
      actions: [['打开治理台', '/admin'], ['查看来源健康', '/health']],
    };
  }

  if (intent === 'rule') {
    return {
      intent,
      title: '修改内部规则',
      summary: '识别到规则变更请求。明仓会先形成草稿，等待确认。',
      answer: `## 已生成规则修改草稿\n\n请求: **${text}**\n\n建议草稿:\n\n- 单股仓位上限:12%\n- 同板块合并暴露继续保留\n- 对估值分位 85%+ 的标的，仓位自动打折\n\n这会影响后续持仓纪律和今日裁决，所以必须确认后才生效。`,
      modules: ['治理台', '持仓纪律', '今日裁决'],
      trace: ['解析规则目标', '检查影响范围', '生成治理台草稿'],
      metrics: [
        ['规则', '仓位上限', '', 'position.max_single'],
        ['新值', '12%', 'up', '草稿'],
        ['影响', '裁决/纪律', 'down', '需确认'],
      ],
      cards: [
        ['影响范围', '会改变个股案卷和今日裁决里的仓位建议。'],
        ['回滚方式', '治理台保留旧值，确认前不覆盖现有规则。'],
      ],
      sources: [{ label: '治理台', status: 'warning', note: '规则变更需人工确认', meta: '规则草稿' }],
      pending: { type: 'rule.update', label: '确认应用规则草稿', note: '终端示例状态生效，刷新后不会持久化', payload: { key: 'max_single_position', value: '12%' } },
      actions: [['打开治理台', '/admin'], ['看持仓纪律', '/positions']],
    };
  }

  if (intent === 'review') {
    return {
      intent,
      title: '复盘候选',
      summary: '已把卖飞问题整理成可确认的复盘候选。',
      answer: `## 复盘候选已生成\n\n这条复盘不会自动写入。候选结论如下:\n\n- 问题:强趋势标的卖出后没有区分 **纪律止盈** 和 **情绪性离场**。\n- 证据:同板块强度仍在，但估值分位已高，应该用移动止损而不是一次性清仓。\n- 可复用规则:卖出后若产业景气未破、价格仍在 20 日线以上，先降仓而不是清零。\n\n确认后进入 **复盘案卷 / 复盘记录**，再由人工决定是否沉淀为 trusted memory。`,
      modules: ['复盘案卷', '持仓纪律', '个股案卷'],
      trace: ['读取已平仓记录', '匹配当时信号', '抽取错误模式', '等待确认写入'],
      metrics: [
        ['复盘类型', '卖飞', 'down', '纪律 vs 情绪'],
        ['候选记忆', '+1', 'up', '等待确认'],
        ['复用规则', '降仓优先', '', '非清零'],
      ],
      cards: [
        ['核心教训', '趋势没破时，不要把估值焦虑直接变成清仓动作。'],
        ['后续观察', '若重新站上 20 日线并保持板块强度，优先小仓补回。'],
      ],
      sources: [
        { label: '持仓记录', status: 'pass', note: '已平仓与当前持仓演示记录', meta: '本地演示' },
        { label: '复盘案卷', status: 'warning', note: '候选复盘尚未进入可信记忆', meta: '候选' },
      ],
      pending: { type: 'review.write', label: '确认写入复盘案卷', note: '写入终端示例状态，刷新后不会持久化' },
      actions: [['打开复盘案卷', '/reports'], ['看持仓纪律', '/positions']],
    };
  }

  if (intent === 'health') {
    return {
      intent,
      title: '来源健康',
      summary: '来源链路可用，但传闻类材料只能作为警告。',
      answer: `## 来源健康检查\n\n**状态:** 演示数据下来源链路可用，但仍有警告需要人工看一眼。\n\n- 官方 / 财报 / 交易所材料优先级最高。\n- 传闻类材料只进入警告，不能单独推动裁决。\n- 来源不足时，今日裁决只降级置信度，不强行补结论。`,
      modules: ['来源健康', '治理台', '今日裁决'],
      trace: ['检查来源等级', '查看警告 / 阻塞', '返回可用证据范围'],
      metrics: [
        ['通过', '7', 'up', '可信来源'],
        ['警告', '3', 'down', '需人工看'],
        ['阻塞', '2', 'down', '不进入裁决'],
      ],
      cards: [
        ['来源边界', '传闻类材料可以提醒你，但不能单独改变信号分。'],
        ['治理动作', '凭证、数据源优先级和熔断都在治理台调整。'],
      ],
      sources: [
        { label: '财联社', status: 'pass', note: '新闻覆盖正常', meta: '2026-06-09' },
        { label: '中金研究', status: 'pass', note: '研报摘要可用', meta: '研报' },
        { label: '传闻材料', status: 'warning', note: '仅提示，不加分', meta: '警告' },
      ],
      actions: [['打开来源健康', '/health'], ['打开治理台', '/admin']],
    };
  }

  if (intent === 'long') {
    return {
      intent,
      title: `${name} 长期研究`,
      summary: '已组织长期研究团队，把文字结论落成标签、风险和证伪清单。',
      answer: `## ${name} ${stock.symbol} 长期研究\n\n已按高保真演示创建一条研究运行:\n\n- 轮数:5 轮 LLM 辩论\n- 参与:多方、空方、研究总监、风险经理、证伪清单\n- 输出:长期标签候选、仓位约束、证据缺口\n\n影子结论不会覆盖今日裁决，但会影响个股案卷里的长期研究和纪律边界。`,
      modules: ['研究副驾驶', '个股案卷', '复盘案卷', '持仓纪律'],
      trace: ['读取个股案卷', '调用 skills', '多轮辩论', '生成长期标签候选'],
      metrics: [
        ['长期标签', '值得持有', 'up', '+72.5'],
        ['辩论轮数', '5', '', '可调整'],
        ['风险约束', '仓位打折', 'down', '估值高位'],
      ],
      cards: [
        ['多方观点', 'AI 光模块景气仍强，订单兑现度高。'],
        ['空方观点', '估值分位偏高，拥挤度上升，回撤会放大。'],
        ['研究总监', '保留长期标签，但短期仓位只允许小仓试错。'],
      ],
      sources: baseSources,
      actions: [['打开研究副驾驶', '/chat'], [`打开 ${name} 案卷`, `/stock/${stock.symbol}`]],
      spark: stock.symbol,
    };
  }

  if (intent === 'decision') {
    return {
      intent,
      title: '今日持仓裁决',
      summary: '已合并信号、持仓纪律、来源健康和复盘记忆。',
      answer: `## 今日持仓裁决\n\n**主结论:** 最强可执行标的是 **${name} ${stock.symbol}**，综合分 ${fmt.signed(signal?.composite_score || 0)}。\n\n- 当前打开持仓 ${open.length} 笔，演示市值约 ${fmt.money(marketValue)}。\n- ${name} 技术分 ${fmt.signed(signal?.technical_score || 0)}，情绪分 ${fmt.signed(signal?.sentiment_score || 0, 2)}。\n- 允许规则内小仓试错，禁止追高加仓。\n- 系统只生成研究记录和待确认动作，不自动下单。`,
      modules: ['今日裁决', '持仓纪律', '来源健康', '复盘案卷'],
      trace: ['读取信号', '合并持仓纪律', '审计来源', '生成裁决摘要'],
      metrics: baseMetrics,
      cards: [
        ['动作建议', '可小仓试错，但不能追高加仓。'],
        ['风险经理', '估值分位高，板块暴露需要合并计算。'],
      ],
      sources: baseSources,
      actions: [['打开今日裁决', '/pulse'], [`打开 ${name} 案卷`, `/stock/${stock.symbol}`]],
      spark: stock.symbol,
    };
  }

  if (intent === 'stock') {
    const held = position ? `当前持有 ${position.quantity} 股，成本 ${fmt.price(position.avg_cost)}，现价 ${fmt.price(position.latest_price)}。` : '当前没有打开持仓。';
    return {
      intent,
      title: `${name} ${stock.symbol}`,
      summary: `${signal?.recommendation || '观察'}，先看纪律边界再决定动作。`,
      answer: `## ${name} ${stock.symbol}\n\n**结论:** ${signal?.recommendation || '观察'}，不建议用纯新闻热度追高加仓。\n\n- 综合分 ${fmt.signed(signal?.composite_score || 0)}，技术 ${fmt.signed(signal?.technical_score || 0)}，情绪 ${fmt.signed(signal?.sentiment_score || 0, 2)}。\n- ${held}\n- 若要新增动作，应先看仓位上限、板块合并暴露和长期标签约束。\n- 研究副驾驶可以继续发起多轮辩论，结果先作为影子意见进入案卷。`,
      modules: ['个股案卷', '今日裁决', '持仓纪律', '研究副驾驶'],
      trace: ['读取个股案卷', '合并今日裁决', '检查持仓纪律', '读取影子意见'],
      metrics: baseMetrics,
      cards: [
        ['多方依据', '趋势与产业景气共振，技术结构仍强。'],
        ['空方约束', '估值和拥挤度要求控制仓位。'],
        ['下一步', '可以继续输入“发起长期研究团队，辩论 5 轮”。'],
      ],
      sources: baseSources,
      actions: [[`打开 ${name} 案卷`, `/stock/${stock.symbol}`], ['发起研究副驾驶', '/chat']],
      spark: stock.symbol,
    };
  }

  return {
    intent,
    title: '可以直接输入',
    summary: '明仓会把自然语言转成研究、复盘、治理或待确认动作。',
    answer: `## 你可以像终端一样用明仓\n\n直接输入自然语言即可，例如:\n\n- 研究 300308 现在还能加仓吗\n- 把海光信息 688041 加入自选股\n- 复盘上周卖飞的仓位\n- 配置 Tushare 凭证\n- 把单股仓位上限改成 12%`,
    modules: ['明仓终端'],
    trace: ['识别意图', '选择模块', '只读优先', '写入前确认'],
    metrics: [],
    cards: [],
    sources: [],
    actions: [],
  };
}

function ScoreGauge({ label, value, tone, sub }: any) {
  const raw = Number(String(value).replace(/[+,%]/g, ''));
  const pct = Math.max(0, Math.min(100, Number.isFinite(raw) ? Math.abs(raw) : 50));
  return (
    <div className="glass-inset desk-gauge" style={{ '--pct': `${pct}%` } as React.CSSProperties}>
      <div className="desk-gauge-ring"><span className={`t-num ${tone || ''}`}>{value}</span></div>
      <div>
        <div style={{ fontWeight: 720 }}>{label}</div>
        <div className="t-faint" style={{ fontSize: 12 }}>{sub}</div>
      </div>
    </div>
  );
}

function SourceCard({ source }: any) {
  const tone = source.status === 'pass' ? 'badge-down' : source.status === 'warning' ? 'badge-warn' : 'badge-dim';
  return (
    <div className="glass-inset desk-source">
      <div className="spread" style={{ gap: 8 }}>
        <strong>{source.label}</strong>
        <Badge tone={tone}>{SOURCE_STATUS_LABELS[source.status] || source.status}</Badge>
      </div>
      <p>{source.note}</p>
      <span className="t-num t-faint">{source.meta}</span>
    </div>
  );
}

function ResultDashboard({ run, onConfirm }: any) {
  if (!run) return null;
  return (
    <section className="glass result-desk pop-2">
      <div className="card-head">
        <div>
          <div className="t-eyebrow">结果驾驶台</div>
          <h2 className="t-title" style={{ margin: '2px 0 0' }}>{run.title}</h2>
        </div>
        <Badge tone="badge-accent">{INTENT_LABELS[run.intent] || run.intent}</Badge>
      </div>
      <div className="card-body grid" style={{ gap: 14 }}>
        <div className="desk-summary">
          <div>
            <div className="t-eyebrow">摘要</div>
            <p>{run.summary}</p>
          </div>
          {run.spark && <Spark symbol={run.spark} width={150} height={42} />}
        </div>

        {run.metrics?.length > 0 && (
          <div className="desk-gauge-grid">
            {run.metrics.map(([label, value, tone, sub]) => (
              <ScoreGauge key={`${label}-${value}`} label={label} value={value} tone={tone} sub={sub} />
            ))}
          </div>
        )}

        <div className="desk-two">
          <div className="grid" style={{ gap: 9 }}>
            <div className="t-eyebrow">关键信息卡</div>
            {(run.cards || []).map(([title, body]) => (
              <div key={title} className="glass-inset desk-card">
                <strong>{title}</strong>
                <p>{body}</p>
              </div>
            ))}
            {run.pending && (
              <div className="glass-inset desk-pending">
                <div className="t-eyebrow">待确认动作</div>
                <strong>{run.pending.label}</strong>
                <p>{run.pending.note}</p>
                {run.pendingConfirmed ? (
                  <Badge tone="badge-down">已确认</Badge>
                ) : (
                  <button type="button" className="btn btn-sm btn-primary" style={{ marginTop: 10 }} onClick={onConfirm}>确认</button>
                )}
              </div>
            )}
          </div>
          <div className="grid" style={{ gap: 9 }}>
            <div className="t-eyebrow">数据来源 / 出处</div>
            {(run.sources || []).map((source) => <SourceCard key={`${source.label}-${source.meta}`} source={source} />)}
            <div className="glass-inset desk-card">
              <strong>调用模块</strong>
              <div className="row" style={{ gap: 6, flexWrap: 'wrap', marginTop: 8 }}>
                {(run.modules || []).map((m) => <Badge key={m} tone="badge-accent">{m}</Badge>)}
              </div>
            </div>
          </div>
        </div>

        {run.actions?.length > 0 && (
          <div className="row" style={{ gap: 8, flexWrap: 'wrap' }}>
            {run.actions.map(([label, route]) => (
              <button key={label} type="button" className="btn btn-sm" onClick={() => navigate(route)}>{label}</button>
            ))}
          </div>
        )}
      </div>
    </section>
  );
}

function TerminalMessage({ msg, onConfirm }: any) {
  const isUser = msg.role === 'user';
  return (
    <article className={`command-msg ${isUser ? 'user' : 'assistant'}`}>
      <div className="command-msg-meta">
        <span>{isUser ? '你' : '明仓'}</span>
        <span>{msg.time}</span>
      </div>
      <div className="command-bubble">
        {msg.loading ? (
          <div className="row" style={{ gap: 8 }}>
            <span className="pulse-dot" style={{ background: 'var(--accent)' }}></span>
            <span className="t-dim">正在理解指令并读取模块...</span>
          </div>
        ) : isUser ? (
          <div className="t-num">{msg.content}</div>
        ) : (
          <Markdown text={msg.answer} />
        )}
      </div>
      {!isUser && !msg.loading && msg.trace?.length > 0 && (
        <div className="command-trace">
          {msg.trace.map((step, i) => <span key={step}><b>{i + 1}</b>{step}</span>)}
        </div>
      )}
      {!isUser && !msg.loading && msg.pending && (
        <div className="glass-inset command-pending">
          <div>
            <div style={{ fontWeight: 720 }}>{msg.pending.label}</div>
            <div className="t-faint" style={{ fontSize: 12, marginTop: 2 }}>{msg.pending.note}</div>
          </div>
          {msg.confirmed ? (
            <Badge tone="badge-down">已确认</Badge>
          ) : (
            <button type="button" className="btn btn-sm btn-primary" onClick={() => onConfirm(msg.id)}>确认</button>
          )}
        </div>
      )}
    </article>
  );
}

function HelpPanel({ onRun }: any) {
  return (
    <section className="glass terminal-help pop-3">
      <div className="card-head">
        <div>
          <div className="t-eyebrow">帮助</div>
          <h2 className="t-title" style={{ margin: '2px 0 0' }}>可以让明仓做什么</h2>
        </div>
        <Badge tone="badge-dim">自然语言即可</Badge>
      </div>
      <div className="card-body">
        <div className="help-grid">
          {HELP_CAPABILITIES.map(([title, body, icon]) => (
            <div key={title} className="glass-inset help-card">
              <span className="help-card-ic"><McIcon name={icon} size={17} /></span>
              <strong>{title}</strong>
              <p>{body}</p>
            </div>
          ))}
        </div>
        <div className="prompt-row">
          {QUICK_PROMPTS.map(([label, prompt]) => (
            <button key={prompt} type="button" className="btn btn-sm" onClick={() => onRun(prompt)}>{label}</button>
          ))}
        </div>
      </div>
    </section>
  );
}

export function HomePage() {
  const [state, setStore] = useStore();
  const scrollRef = useHRef<any>(null);
  const [input, setInput] = useHState('');
  const [busy, setBusy] = useHState(false);
  const [lastRun, setLastRun] = useHState<any>(null);
  const [messages, setMessages] = useHState<any[]>([]);

  useHEffect(() => {
    if (scrollRef.current) scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
  }, [messages.length, busy]);

  function runCommand(text) {
    const command = String(text || input).trim();
    if (!command || busy) return;
    const stamp = new Date().toTimeString().slice(0, 5);
    const loadingId = `a-${Date.now()}`;
    setInput('');
    setBusy(true);
    setMessages((m) => [
      ...m,
      { id: `u-${Date.now()}`, role: 'user', time: stamp, content: command },
      { id: loadingId, role: 'assistant', time: 'running', loading: true },
    ]);
    setTimeout(() => {
      const run = buildRun(command, MCStore.get());
      setLastRun(run);
      setMessages((m) => m.map((msg) => (msg.id === loadingId ? {
        id: loadingId,
        role: 'assistant',
        time: 'done',
        answer: run.answer,
        trace: run.trace,
        pending: run.pending,
      } : msg)));
      setBusy(false);
    }, 460);
  }

  function confirmMessage(id) {
    const msg = messages.find((m) => m.id === id);
    const pending = msg?.pending || lastRun?.pending;
    setMessages((m) => m.map((item) => (item.id === id ? { ...item, confirmed: true } : item)));
    setLastRun((run) => run ? { ...run, pendingConfirmed: true } : run);

    if (pending?.type === 'review.write') {
      const review = {
        id: `terminal-review-${Date.now()}`,
        date: '2026-06-11',
        title: '终端生成复盘候选',
        type: 'manual_review',
        status: 'candidate',
        content: '卖出后应区分纪律止盈与情绪性离场;若景气未破且仍在关键均线上方，优先降仓而不是清零。',
      };
      setStore((st) => ({ reviews: [review, ...st.reviews] }));
      toast('已写入终端示例复盘候选');
    } else if (pending?.type === 'watchlist.add') {
      const p = pending.payload;
      setStore((st) => st.watchlist.some((w) => w.symbol === p.symbol)
        ? {}
        : { watchlist: [...st.watchlist, { symbol: p.symbol, name: p.name, market: p.market, industry: p.industry || '待标注', latest_signal: null }] });
      toast(`已加入终端示例自选:${p.name}`);
    } else if (pending?.type === 'api_key.update') {
      toast('已更新终端示例凭证状态');
    } else if (pending?.type === 'rule.update') {
      setStore((st) => ({ runtime: { ...st.runtime, max_single_position: '12%' } }));
      toast('规则草稿已在终端示例状态生效');
    }
  }

  function onSubmit(e) {
    e.preventDefault();
    runCommand(input);
  }

  function confirmLatestPending() {
    const pendingMsg = messages.slice().reverse().find((m) => m.pending && !m.confirmed);
    if (pendingMsg) confirmMessage(pendingMsg.id);
  }

  return (
    <div className="grid terminal-page compact-terminal" style={{ gap: 16 }}>
      <header className="spread pop terminal-head">
        <div style={{ minWidth: 0 }}>
          <div className="t-eyebrow">明仓终端</div>
          <h1 className="t-hero" style={{ margin: '4px 0 0' }}>明仓终端</h1>
          <p className="t-dim" style={{ margin: '7px 0 0', fontSize: 13.5, maxWidth: 720 }}>
            直接输入文字使用明仓。研究、复盘、加自选、改规则、更新凭证都先以对话理解，再把结果变成下方驾驶台。
          </p>
        </div>
        <div className="row" style={{ gap: 7, flexWrap: 'wrap', justifyContent: 'flex-end' }}>
          <Badge tone="badge-accent">本地优先</Badge>
          <Badge tone="badge-dim">写入需确认</Badge>
          <Badge tone="badge-dim">终端示例</Badge>
        </div>
      </header>

      <section className="glass command-center pop-1">
        <div className="command-top">
          <div className="row" style={{ gap: 7 }}>
            <span className="terminal-dot red"></span>
            <span className="terminal-dot amber"></span>
            <span className="terminal-dot green"></span>
            <span className="t-faint">桌面示例通道</span>
          </div>
          <Badge tone={messages.length ? 'badge-accent' : 'badge-dim'}>{messages.length ? '已生成驾驶台' : '等待输入'}</Badge>
        </div>

        <div ref={scrollRef} className={`command-stream scroll-thin ${messages.length ? '' : 'is-empty'}`}>
          {messages.length === 0 ? (
            <div className="command-empty">
              <h2>输入一句话开始</h2>
              <p>例如“研究 300308 现在还能加仓吗”，或“把海光信息加入自选股”。对话完成后，下方才会出现仪表、来源和动作卡。</p>
              <div className="prompt-row" style={{ justifyContent: 'center' }}>
                {QUICK_PROMPTS.slice(0, 3).map(([label, prompt]) => (
                  <button key={prompt} type="button" className="btn btn-sm" onClick={() => runCommand(prompt)}>{label}</button>
                ))}
              </div>
            </div>
          ) : (
            messages.map((msg) => <TerminalMessage key={msg.id} msg={msg} onConfirm={confirmMessage} />)
          )}
        </div>

        <form className="command-input" onSubmit={onSubmit}>
          <span className="t-num command-prompt">明仓 &gt;</span>
          <input
            value={input}
            onChange={(e) => setInput(e.target.value)}
            placeholder="输入: 研究 300308 现在还能加仓吗"
            disabled={busy}
          />
          <button type="submit" className="btn btn-primary" disabled={busy || !input.trim()}>
            <McIcon name="chat" size={15} /> 发送
          </button>
        </form>
      </section>

      <ResultDashboard run={lastRun} onConfirm={confirmLatestPending} />
      <HelpPanel onRun={runCommand} />
    </div>
  );
}

window.HomePage = HomePage;
