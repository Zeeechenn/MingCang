// ============================================================
// MingCang 明仓 — 原型演示数据层(全部为示例数据)
// ============================================================
export const MC_DATA: any = (function () {
  // 确定性伪随机,保证每次刷新图表一致
  function prng(seed) {
    let s = seed >>> 0;
    return function () {
      s = (s * 1664525 + 1013904223) >>> 0;
      return s / 4294967296;
    };
  }

  function genPrices(seed, base, drift, vol, days) {
    const rnd = prng(seed);
    const out: any[] = [];
    let close = base;
    const end = new Date('2026-06-09');
    const dates: Date[] = [];
    let d = new Date(end);
    while (dates.length < days) {
      const dow = d.getDay();
      if (dow !== 0 && dow !== 6) dates.push(new Date(d));
      d = new Date(d); d.setDate(d.getDate() - 1);
    }
    dates.reverse().forEach((date) => {
      const chg = (rnd() - 0.5 + drift) * vol;
      const open = close;
      close = Math.max(1, close * (1 + chg));
      const high = Math.max(open, close) * (1 + rnd() * vol * 0.4);
      const low = Math.min(open, close) * (1 - rnd() * vol * 0.4);
      const volu = Math.round(8e5 + rnd() * 2.4e6 * (1 + Math.abs(chg) * 30));
      out.push({
        date: date.toISOString().slice(0, 10),
        open: +open.toFixed(2), close: +close.toFixed(2),
        high: +high.toFixed(2), low: +low.toFixed(2), volume: volu,
      });
    });
    return out;
  }

  const PRICES = {
    '300308': genPrices(11, 128, 0.012, 0.034, 120),
    '300394': genPrices(22, 96, 0.010, 0.036, 120),
    '600519': genPrices(33, 1450, 0.001, 0.014, 120),
    '603986': genPrices(44, 84, 0.004, 0.030, 120),
    '000725': genPrices(55, 4.1, 0.001, 0.022, 120),
    '002230': genPrices(66, 42, -0.007, 0.028, 120),
    '00700': genPrices(77, 372, 0.004, 0.020, 120),
    'AAPL': genPrices(88, 228, 0.003, 0.016, 120),
  };
  const last = (s) => PRICES[s][PRICES[s].length - 1];

  const SIG_DATE = '2026-06-09';
  const DEMO_META = { is_demo: true, snapshot_as_of: SIG_DATE, label: '示例快照' };

  function mkSignal(symbol, rec, score, tech, senti, conf, bull, bear, rationale, bias) {
    const px = last(symbol).close;
    return {
      symbol, date: SIG_DATE, recommendation: rec,
      composite_score: score, quant_score: 0, technical_score: tech, sentiment_score: senti,
      confidence: conf,
      stop_loss: +(px * 0.93).toFixed(2), take_profit: +(px * 1.12).toFixed(2),
      llm_arbitration: { bull_points: bull, bear_points: bear, rationale, action_bias: bias },
    };
  }

  const WATCHLIST = [
    {
      symbol: '300308', name: '中际旭创', market: 'CN', industry: '光模块 / AI 算力',
      long_term_label: { label: '值得持有', score: 72.5, date: '2026-06-08', expires_at: '2026-06-22', constraint_eligible: true, quality: 'pass', key_findings: ['800G 出货持续放量，收入与盈利增速维持高位。', '估值分位偏高，短线信号转弱时应优先降仓。', '行业拥挤度上升，与 300394 暴露需合并计算。'], quality_notes: ['财务数据完整 5 年', '新闻证据 14 条经审计'] },
      latest_signal: mkSignal('300308', '可小仓试错', 36.0, 48.0, 0.55, '中',
        ['技术趋势占优，价格站稳关键均线上方', '800G 光模块订单兑现度高，产业催化密集', '长期标签为值得持有，允许短线小仓试错'],
        ['板块拥挤度升高，追高风险加大', '估值分位处于历史 85% 以上', '与同板块持仓暴露重叠，需合并计算'],
        '趋势与产业景气共振，但估值已部分透支预期。允许规则内小仓试错，禁止追高加仓。', '谨慎偏多'),
    },
    {
      symbol: '300394', name: '天孚通信', market: 'CN', industry: '光器件 / AI 算力',
      long_term_label: { label: '值得持有', score: 68.0, date: '2026-06-08', expires_at: '2026-06-22', constraint_eligible: true, quality: 'pass', key_findings: ['光引擎和无源器件双线放量。', '与 300308 高度同向，二选一持有。'], quality_notes: ['财务数据完整'] },
      latest_signal: mkSignal('300394', '可小仓试错', 31.5, 42.0, 0.51, '中',
        ['量价配合良好，趋势结构完整', '上游器件环节议价能力增强'],
        ['同板块暴露与 300308 重叠', '短期涨幅过快，波动放大'],
        '强度保持，但与中际旭创高度重叠，组合层面只保留最强一只。', '谨慎偏多'),
    },
    {
      symbol: '600519', name: '贵州茅台', market: 'CN', industry: '白酒 / 消费',
      long_term_label: { label: '观望', score: 41.0, date: '2026-06-08', expires_at: '2026-06-22', constraint_eligible: false, quality: 'insufficient', key_findings: ['财务质量稳定，但增速弹性不足。', '消费复苏强度一般，缺少短线催化。'], quality_notes: ['景气证据不足，待补充渠道数据'] },
      latest_signal: mkSignal('600519', '可关注', 18.0, 22.0, 0.06, '低',
        ['估值回到合理区间，股息率有支撑'],
        ['量能确认不足，缺少催化', '系统不应因品牌质量自动给高短线分'],
        '质量稳定但缺乏短线弹性，只加入观察，不新增仓位。', '中性'),
    },
    {
      symbol: '603986', name: '兆易创新', market: 'CN', industry: '存储芯片 / 半导体',
      long_term_label: { label: '估值偏高', score: 38.0, date: '2026-06-08', expires_at: '2026-06-22', constraint_eligible: true, quality: 'pass', key_findings: ['存储周期底部修复中，国产替代共振。', '价格已提前反映修复预期，仓位建议打折。'], quality_notes: ['估值分位 88%'] },
      latest_signal: mkSignal('603986', '可关注', 12.0, 17.0, 0.05, '低',
        ['存储价格企稳，周期修复方向明确'],
        ['兑现节奏不稳定，财报波动大', '估值偏高，短线强信号需打折处理'],
        '周期修复方向认可，但价格领先基本面，等待财报或成交确认。', '中性'),
    },
    {
      symbol: '000725', name: '京东方A', market: 'CN', industry: '面板 / 显示',
      latest_signal: mkSignal('000725', '可关注', 6.0, 8.0, 0.03, '低',
        ['面板价格温和上行，稼动率回升'],
        ['突破未获成交量确认', '上月假突破案例已写入记忆'],
        '仍需等待放量突破，技术分必须结合量能确认。', '中性'),
    },
    {
      symbol: '002230', name: '科大讯飞', market: 'CN', industry: 'AI 应用 / 软件',
      long_term_label: { label: '规避', score: -22.0, date: '2026-06-08', expires_at: '2026-06-22', constraint_eligible: true, quality: 'pass', key_findings: ['业绩兑现不足，盈利下修与技术破位共振。'], quality_notes: ['连续两季盈利下修'] },
      latest_signal: mkSignal('002230', '规避', -24.0, -30.0, -0.08, '中',
        ['新闻热度高，主题催化频繁'],
        ['技术破位，趋势走弱', '新闻分歧大，价格弱确认', '盈利下修未结束'],
        '新闻高热但价格弱确认，新闻分不得单独触发买入。维持规避。', '偏空'),
    },
    { symbol: '00700', name: '腾讯控股', market: 'HK', industry: '互联网平台', latest_signal: null, observe: true },
    { symbol: 'AAPL', name: 'Apple Inc.', market: 'US', industry: '消费电子', latest_signal: null, observe: true },
  ];

  const POSITIONS = [
    { id: 1, symbol: '300308', name: '中际旭创', market: 'CN', status: 'open', quantity: 200, avg_cost: 98.6, latest_price: last('300308').close, stop_loss: +(last('300308').close * 0.93).toFixed(2), take_profit: +(last('300308').close * 1.12).toFixed(2), entry_date: '2026-05-12' },
    { id: 2, symbol: '600519', name: '贵州茅台', market: 'CN', status: 'open', quantity: 100, avg_cost: 1368.0, latest_price: last('600519').close, stop_loss: +(last('600519').close * 0.94).toFixed(2), take_profit: +(last('600519').close * 1.1).toFixed(2), entry_date: '2026-04-28' },
    { id: 3, symbol: '000725', name: '京东方A', market: 'CN', status: 'open', quantity: 8000, avg_cost: 3.86, latest_price: last('000725').close, stop_loss: 3.78, take_profit: 4.65, entry_date: '2026-05-22' },
    { id: 4, symbol: '00700', name: '腾讯控股', market: 'HK', status: 'open', quantity: 100, avg_cost: 358.0, latest_price: last('00700').close, stop_loss: 334, take_profit: 412, entry_date: '2026-05-06' },
    { id: 5, symbol: '300394', name: '天孚通信', market: 'CN', status: 'closed', quantity: 300, avg_cost: 88.4, close_price: 101.2, opened_at: '2026-04-14', closed_at: '2026-05-20', realized_pnl: 3840, realized_pnl_pct: 14.48 },
    { id: 6, symbol: '002230', name: '科大讯飞', market: 'CN', status: 'closed', quantity: 500, avg_cost: 46.8, close_price: 43.9, opened_at: '2026-04-02', closed_at: '2026-04-30', realized_pnl: -1450, realized_pnl_pct: -6.2 },
  ];

  const SEARCH_POOL = [
    { symbol: '300308', name: '中际旭创', market: 'CN' }, { symbol: '300394', name: '天孚通信', market: 'CN' },
    { symbol: '600519', name: '贵州茅台', market: 'CN' }, { symbol: '603986', name: '兆易创新', market: 'CN' },
    { symbol: '000725', name: '京东方A', market: 'CN' }, { symbol: '002230', name: '科大讯飞', market: 'CN' },
    { symbol: '601318', name: '中国平安', market: 'CN' }, { symbol: '000063', name: '中兴通讯', market: 'CN' },
    { symbol: '002475', name: '立讯精密', market: 'CN' }, { symbol: '688041', name: '海光信息', market: 'CN' },
    { symbol: '00700', name: '腾讯控股', market: 'HK' }, { symbol: '09988', name: '阿里巴巴-W', market: 'HK' },
    { symbol: 'AAPL', name: 'Apple Inc.', market: 'US' }, { symbol: 'NVDA', name: 'NVIDIA', market: 'US' },
  ];

  const NEWS = {
    '300308': [
      { title: '中际旭创 800G 光模块月度出货再创新高，1.6T 送样进度超预期', source: '财联社', published_at: '2026-06-09 08:42', sentiment: 0.72, audit: 'pass' },
      { title: '北美云厂商上调资本开支指引，光模块板块集体走强', source: '证券时报', published_at: '2026-06-08 21:15', sentiment: 0.61, audit: 'pass' },
      { title: '机构研报:光模块行业拥挤度升至历史高位，警惕短期回撤', source: '中金研究', published_at: '2026-06-08 16:30', sentiment: -0.28, audit: 'pass' },
      { title: '中际旭创回应海外建厂传闻:泰国基地产能爬坡顺利', source: '上证报', published_at: '2026-06-07 19:05', sentiment: 0.35, audit: 'warning' },
    ],
    '002230': [
      { title: '科大讯飞发布星火 V5，发布会关注度高但股价冲高回落', source: '财联社', published_at: '2026-06-09 10:18', sentiment: 0.15, audit: 'pass' },
      { title: '机构下修科大讯飞全年盈利预期，G 端回款仍承压', source: '券商研报', published_at: '2026-06-08 14:00', sentiment: -0.55, audit: 'pass' },
      { title: 'AI 应用板块情绪分歧加大，资金流出迹象明显', source: '证券时报', published_at: '2026-06-07 20:40', sentiment: -0.32, audit: 'pass' },
    ],
    _default: [
      { title: '沪深两市成交额连续三日维持万亿上方', source: '财联社', published_at: '2026-06-09 09:30', sentiment: 0.2, audit: 'pass' },
      { title: '北向资金本周净流入 182 亿元，集中加仓电子与医药', source: '证券时报', published_at: '2026-06-08 18:00', sentiment: 0.3, audit: 'pass' },
    ],
  };

  function mkHistory(symbol, score) {
    const recs = ['可小仓试错', '可关注', '观望', '可关注', '规避', '可关注', '观望', '可小仓试错'];
    const dates = ['2026-06-09', '2026-06-06', '2026-06-05', '2026-06-04', '2026-06-03', '2026-06-02', '2026-05-30', '2026-05-29'];
    const rnd = prng(symbol.charCodeAt(0) * 7 + 3);
    return dates.map((date, i) => ({
      id: i + 1, date,
      recommendation: i === 0 ? null : recs[(i + Math.floor(score / 10)) % recs.length],
      composite_score: i === 0 ? score : +(score - (i * 4) + (rnd() - 0.5) * 18).toFixed(1),
    })).map((r, i, arr) => i === 0 ? { ...r, recommendation: WATCHLIST.find(w => w.symbol === symbol)?.latest_signal?.recommendation || '观望' } : r);
  }

  const EVIDENCE = {
    '300308': [
      { id: 'ev-1', kind: 'decision_run', date: '2026-06-09', title: '盘后决策运行 #482', detail: '技术分 +48.0(趋势/量能/MACD 共振) · 情绪分 +0.55(4 条新闻，2 强 1 中 1 弱) · 长期标签约束通过', status: 'pass' },
      { id: 'ev-2', kind: 'news_audit', date: '2026-06-09', title: '新闻审计', detail: '4 条新闻全部来源可信;1 条传闻类标记 warning，不参与情绪加分', status: 'warning' },
      { id: 'ev-3', kind: 'risk_check', date: '2026-06-09', title: '风险经理拦截检查', detail: '单股仓位 12.8% < 15% 上限;板块暴露 24.1% < 30% 上限;通过', status: 'pass' },
      { id: 'ev-4', kind: 'lookahead', date: '2026-06-08', title: '反穿越检查', detail: '全部证据时间戳早于信号生成时间，无未来数据', status: 'pass' },
    ],
    _default: [
      { id: 'ev-d1', kind: 'decision_run', date: '2026-06-09', title: '盘后决策运行', detail: '信号由技术 0.6 + 情绪 0.4 加权生成，量化权重 0(休眠)', status: 'pass' },
      { id: 'ev-d2', kind: 'lookahead', date: '2026-06-08', title: '反穿越检查', detail: '证据链时间戳校验通过', status: 'pass' },
    ],
  };

  const COPILOT = {
    '300308': {
      stance: '支持', stanceTone: 'support', conflict: null,
      summary: '影子意见与官方规则一致:趋势与景气共振成立，但估值约束要求小仓。若两日内放量滞涨，优先减仓而非补仓。',
      shadow_position: '5%(试错仓)', position_note: '与官方一致，受长期标签约束',
      event_read: '北美资本开支上调是真实催化，但已被连续两周上涨部分定价。',
      technical_read: '站稳 20 日线，量价配合良好;短期乖离率偏高。',
      risks: ['板块拥挤度历史高位，回撤会放大', '泰国产能爬坡不及预期为证伪条件', '1.6T 进度若低于预期，估值逻辑受损'],
      next_steps: ['跟踪周度出货数据', '监控板块成交额是否背离', '复核与 300394 的合并暴露'],
    },
    _default: {
      stance: '中性', stanceTone: 'neutral', conflict: null,
      summary: '暂无足够新证据形成独立影子观点，维持与官方规则一致。',
      shadow_position: '观察', position_note: '等待下一次决策运行',
      event_read: '近期无重大事件催化。', technical_read: '技术结构中性，无明确方向。',
      risks: ['证据不足本身即是风险'], next_steps: ['等待盘后信号更新'],
    },
  };

  const EVAL = {
    '300308': { days: 60, total: 14, hit: 9, hit_rate: 64.3, avg_gain: 4.2, avg_loss: -2.8, best: '+11.4% (05-13 可小仓试错)', worst: '-4.1% (04-22 可关注)', note: '试错类信号胜率高于观察类;假突破案例已写入记忆。' },
    _default: { days: 60, total: 8, hit: 4, hit_rate: 50.0, avg_gain: 2.6, avg_loss: -2.2, best: '+6.2%', worst: '-3.5%', note: '样本偏少，评估仅供参考。' },
  };

  const DOSSIER = {
    '300308': {
      final_position: '5%', trader_position: '8%', constrained: '已被长期标签约束', constraint_count: 2, conflict_count: 1,
      conflicts: [{ severity: 'medium', summary: '短线强趋势 vs 估值分位 85%+:仓位上限从 8% 压缩至 5%' }],
      constraints: [{ summary: '长期标签「值得持有」允许试错，但禁止追高加仓' }, { summary: '与 300394 合并计算板块暴露' }],
      deep_research_count: 2, first_deep_research: '《AI 光模块供需推演 2026-2027》:1.6T 渗透节奏是核心变量，关注北美四大云厂资本开支节奏。',
    },
    _default: { final_position: '-', trader_position: '-', constrained: '无约束触发', constraint_count: 0, conflict_count: 0, conflicts: [], constraints: [], deep_research_count: 0, first_deep_research: null },
  };

  // ---------- 复盘 ----------
  const REVIEW_DAILY_CONTENT = `# 明仓每日复盘 — 2026-06-09

## 摘要
- 当日信号:6 条
- 可小仓试错:2 条
- 可关注:3 条
- 规避:1 条
- 异动监控:2 条
- 安全审计:pass

## 大盘环境
- 沪深300 收盘小幅上涨，扩散度处于中性区间。
- 光模块、AI 服务器链条相对强势，但短线拥挤度上升。
- 今日适合保留观察仓，不适合大幅提高总仓位。

## 当日信号明细
| 股票 | 综合分 | 建议 | 置信度 | 技术 | 情感 | 风险 |
|---|---:|---|---|---:|---:|---|
| 300308 中际旭创 | +36.0 | 可小仓试错 | 中 | +48.0 | +0.55 | 趋势强但波动放大 |
| 300394 天孚通信 | +31.5 | 可小仓试错 | 中 | +42.0 | +0.51 | 同板块暴露需控制 |
| 600519 贵州茅台 | +18.0 | 可关注 | 低 | +22.0 | +0.06 | 量能确认不足 |
| 603986 兆易创新 | +12.0 | 可关注 | 低 | +17.0 | +0.05 | 估值偏高 |
| 000725 京东方A | +6.0 | 可关注 | 低 | +8.0 | +0.03 | 仍需等待突破 |
| 002230 科大讯飞 | -24.0 | 规避 | 中 | -30.0 | -0.08 | 新闻分歧与技术破位 |

## 持仓复核
- 300308 接近止盈观察线，若明日高开回落，优先观察成交量。
- 同一板块的重复暴露，需要合并计算总仓位。
- 已有 AI 算力链持仓，今日新增仓位只补最强信号，不做平均加仓。

## 今日动作建议
1. 对「可小仓试错」只按规则小仓，不突破单股上限。
2. 对「可关注」只加入主动观察，不新增持仓。
3. 对「规避」标的不做补仓，等待下一次有效信号。
4. 明日重点看大盘扩散度、板块成交额和持仓止损位。

## 免责声明
本复盘用于记录和辅助决策，不构成投资建议，不自动触发交易。`;

  const REVIEW_LT_CONTENT = `# 明仓长期复盘 — 2026-W24

## 长期研究团队摘要
- 值得持有:2
- 估值偏高:1
- 观望:2
- 规避:1

## 组合层结论
本周核心矛盾不是「有没有产业趋势」，而是「趋势已经被价格反映了多少」。短线信号可以继续使用，但仓位上限需要受到长期标签约束。

## 标签变化
| 股票 | 上周 | 本周 | 变化原因 |
|---|---|---|---|
| 300308 | 值得持有 | 值得持有 | 景气维持，估值风险增加 |
| 603986 | 观望 | 估值偏高 | 价格提前反映修复预期 |
| 002230 | 观望 | 规避 | 盈利下修与破位共振 |

## 团队视角
- 质量分析师:核心标的盈利质量没有明显恶化。
- 景气分析师:AI 算力链仍强，但边际预期正在变钝。
- 资金流分析师:QFII 与机构未形成一致加仓。
- 风险经理:估值分位偏高的标的需降低短线信号权重。

## 下周观察清单
1. 财报披露窗口是否改变长期标签。
2. 强势行业是否出现成交额背离。
3. 长期「规避」标的若出现短线强信号，仍需风险经理二次拦截。

## 记忆写入
- 保存「强趋势但估值偏高」的冲突案例。
- 保存 AI 算力链重复暴露提醒。
- 不保存一次性新闻标题，避免噪声污染长期记忆。`;

  const REVIEWS = [
    { id: 'r-d-0609', kind: 'daily', as_of: '2026-06-09', summary: '今日生成 6 条信号，2 条进入可小仓试错;新闻情绪偏强但大盘扩散度一般。', metrics: [['信号', '6'], ['试错', '2'], ['规避', '1']], highlights: ['中际旭创动量延续，仓位建议保持小仓。', '大盘仍处中性区，新增仓位控制在规则上限内。'], content: REVIEW_DAILY_CONTENT },
    { id: 'r-l-w24', kind: 'long_term', as_of: '2026-W24', summary: '长期团队完成核心自选复核:2 只维持值得持有，1 只因估值偏高下调仓位建议。', metrics: [['持有', '2'], ['观望', '2'], ['规避', '1']], highlights: ['财务质量评分稳定，现金流和 ROE 是主要支撑。', '估值分位偏高的股票仅保留观察，不主动加仓。'], content: REVIEW_LT_CONTENT },
    { id: 'r-d-0606', kind: 'daily', as_of: '2026-06-06', summary: '生成 5 条信号，AI 算力链继续占优，消费和地产链保持观察。', metrics: [['信号', '5'], ['试错', '1'], ['规避', '2']], highlights: ['300394 强度保持，但与 300308 暴露高度重叠。'], content: '# 明仓每日复盘 — 2026-06-06\n\n## 摘要\n- 当日信号:5 条 · 试错 1 · 规避 2\n- 安全审计:pass\n\n## 复盘动作\n1. AI 算力链只保留最强一只作为试错候选。\n2. 消费和金融只加入观察，不新增仓位。\n3. 已持仓标的若回撤至移动止损线，按规则处理。' },
    { id: 'r-d-0605', kind: 'daily', as_of: '2026-06-05', summary: '防守日，系统没有给出高置信买入，重点记录止损和异常新闻。', metrics: [['信号', '4'], ['试错', '0'], ['规避', '3']], highlights: ['总仓位建议下调到观察区间。'], content: '# 明仓每日复盘 — 2026-06-05\n\n## 风险状态\n- 大盘扩散度转弱，强势行业补跌风险上升。\n- 新闻情绪与价格走势背离，不能用标题热度替代交易确认。\n\n## 持仓纪律\n1. 已触发止损的标的不得因盘中反抽取消纪律。\n2. 同板块多个持仓需合并计算风险暴露。' },
    { id: 'r-l-w23', kind: 'long_term', as_of: '2026-W23', summary: '长期团队复核 6 只核心标的，质量因子稳定，估值约束变强。', metrics: [['持有', '2'], ['观察', '4'], ['冲突', '2']], highlights: ['长期标签用于限制短线仓位，而不是替代短线信号。'], content: '# 明仓长期复盘 — 2026-W23\n\n## 本周长期结论\n- 值得持有:2 · 观察:4 · 与短线信号冲突:2\n\n## 写入记忆\n1. 保存「强趋势但估值偏高」的冲突案例。\n2. 保存 AI 算力链重复暴露提醒。' },
    { id: 'r-d-0604', kind: 'daily', as_of: '2026-06-04', summary: '系统记录一次假突破案例，用于校准技术分和新闻分权重。', metrics: [['信号', '3'], ['假突破', '1'], ['记忆', '2']], highlights: ['突破后量能不足的案例已写入复盘记忆。'], content: '# 明仓每日复盘 — 2026-06-04\n\n## 复盘案例\n| 股票 | 现象 | 原因 | 后续规则 |\n|---|---|---|---|\n| 000725 京东方A | 突破失败 | 成交额未放大 | 技术分需要量能确认 |\n| 002230 科大讯飞 | 新闻高热 | 价格弱确认 | 新闻分不得单独触发 |\n\n## 规则校准\n1. 技术突破必须结合成交额。\n2. 新闻催化需要价格确认。\n3. 低置信信号只进入观察，不进入试错。' },
  ];

  // ---------- 数据健康 ----------
  const COVERAGE = {
    status: 'pass',
    provider_chains: {
      CN: ['akshare', 'tushare_qfq', 'local_cache'],
      HK: ['akshare_hk', 'local_cache'],
      US: ['yfinance', 'local_cache'],
    },
    policies: { CN: '盘中只读缓存，收盘后增量拉取', HK: 'observe-only，日线收盘拉取', US: 'observe-only，日线收盘拉取' },
    max_lag_days: { CN: 1, HK: 2, US: 2 },
    checks: { 价格新鲜度: true, 新闻审计覆盖: true, 反穿越检查: true, 财务数据完整性: true, 指数数据: true, 情绪缓存命中: false },
    warnings: [
      { code: 'SENTIMENT_CACHE_MISS', message: '002230 最近 2 条新闻未命中情绪缓存，下次盘后将调用 LLM 重算(预计 ¥0.04)。' },
      { code: 'HK_PRICE_LAG', message: '00700 港股日线滞后 1 天，处于 2 天容忍范围内，observe-only 不影响 CN 官方信号。' },
    ],
    stocks: WATCHLIST.map((w) => ({
      symbol: w.symbol, name: w.name, market: w.market,
      latest_price_date: w.market === 'HK' ? '2026-06-08' : '2026-06-09',
      status: w.market === 'HK' ? 'warning' : 'ok',
    })),
  };

  // ---------- 配置 / 系统 ----------
  const RUNTIME = {
    profile: 'new_framework', entry_threshold: 25, director_min_confidence: 60,
    weights: { quant: 0, technical: 60, sentiment: 40 },
    regime_filter: true, adx_filter: false, multi_agent: true, risk_manager: true,
    long_term_team: true, long_term_constraints: true, trailing_stop: true,
    debate_rounds: 3,
    max_stock_pct: 15, max_sector_pct: 30, max_total_pct: 80, new_signal_trial_pct: 5,
    financial_years: 5, tavily_threshold: 3, anspire_days: 2, anspire_max_results: 5, anspire_max_add: 2, anspire_min_score: 75,
    daily_review_time: '15:00', longterm_monday_time: '09:00', longterm_friday_time: '15:00',
    kill_switch: false, scheduler_enabled: false,
    llm_provider: 'local_cli',
  };

  const LLM_USAGE = {
    days: 7, total_cny: 3.42, total_calls: 86,
    buckets: [
      { name: '新闻情绪', calls: 41, cny: 0.92 }, { name: '多空辩论', calls: 18, cny: 1.24 },
      { name: '研究副驾驶', calls: 12, cny: 0.68 }, { name: 'AI 对话', calls: 11, cny: 0.40 },
      { name: '长期团队', calls: 4, cny: 0.18 },
    ],
    daily: [0.36, 0.52, 0.48, 0.61, 0.44, 0.55, 0.46],
  };

  const MEMORY = {
    overview: { total: 47, trusted: 28, candidate: 11, audit_events: 132 },
    items: [
      { id: 'm1', scope: 'stock:000725', category: '复盘案例', trust: 'trusted', text: '假突破案例:技术突破必须结合成交额确认，否则技术分打折。', date: '2026-06-04' },
      { id: 'm2', scope: 'stock:002230', category: '规则', trust: 'trusted', text: '新闻高热但价格弱确认:新闻分不得单独触发买入。', date: '2026-06-04' },
      { id: 'm3', scope: 'global', category: '风险提醒', trust: 'trusted', text: 'AI 算力链多标的暴露需合并计算，组合层只保留最强一只试错。', date: '2026-06-08' },
      { id: 'm4', scope: 'stock:300308', category: '冲突案例', trust: 'candidate', text: '强趋势但估值偏高:仓位上限从 8% 压缩至 5%，待两周后复核结论。', date: '2026-06-09' },
      { id: 'm5', scope: 'global', category: '用户偏好', trust: 'trusted', text: '用户偏好小仓试错策略，不接受单股超过 15% 的建议。', date: '2026-05-20' },
    ],
    audit: [
      { time: '2026-06-09 15:42', action: '召回', target: 'm3', context: '盘后信号生成 · 300394 决策运行' },
      { time: '2026-06-09 15:41', action: '写入候选', target: 'm4', context: '每日复盘 · 冲突案例沉淀' },
      { time: '2026-06-08 09:12', action: '召回', target: 'm5', context: 'AI 对话 · 仓位建议' },
      { time: '2026-06-04 15:30', action: '升级 trusted', target: 'm1', context: '用户确认复盘案例' },
    ],
  };

  // ---------- 多空辩论(多智能体三轮辩论全记录) ----------
  // 管线:四路分析师 → 研究总监(定议题) → 研究员三轮辩论 → 交易员 → 风控
  const DEBATE = {
    '300308': {
      symbol: '300308', name: '中际旭创', date: SIG_DATE, used_llm: true, round_count: 3,
      analysts: [
        { role: '技术', key: 'technical', score: 48.0, confidence: 0.80, findings: ['价站稳 20/60 日均线，量价配合', 'MACD 金叉延续，趋势结构完整', '短期乖离率偏高'] },
        { role: '量化', key: 'quant', score: 0.0, confidence: 0.30, findings: ['模型=休眠(WEIGHT_QUANT=0)', '不参与生产信号'] },
        { role: '情感', key: 'sentiment', score: 55.0, confidence: 0.55, findings: ['北美资本开支上调，情绪偏强', '影响周期: 中线'] },
        { role: '新闻', key: 'news', score: 30.0, confidence: 0.45, findings: ['800G 出货月度新高(+)', '机构警示板块拥挤度(−)', '泰国产能传闻待证'] },
      ],
      director: {
        avg_confidence: 0.53, score_stdev: 24.5, diverged: true,
        debate_topic: '情感信号 +55 与量化信号 0 出现重大分歧(量化休眠，实际由技术 +48 主导);请论证多头趋势与估值/拥挤度风险在当前环境下孰更可信。',
        quality_notes: ['量化置信度低 (0.30，休眠)', '四路多数可用，质量门通过'],
        weak_roles: ['量化'],
      },
      rounds: [
        {
          round_num: 1, speaker: 'bull', key_signal: '技术 +48 / 新闻 800G',
          points: [
            '800G 出货月度创新高，1.6T 送样进度超预期，景气兑现确定性高',
            '价站稳 20/60 日均线，量价配合，技术分 +48 主导四路',
            '长期标签『值得持有』，规则允许小仓试错',
          ],
        },
        {
          round_num: 2, speaker: 'bear',
          rebuttals: [
            { target: '景气兑现确定性高', counter: '板块拥挤度升至历史高位，利好已被两周上涨提前定价' },
            { target: '技术 +48 主导', counter: '短期乖离率偏高，追高回撤风险放大' },
            { target: '允许小仓试错', counter: '估值分位 85%+，长期标签同时把仓位上限压到 5%' },
          ],
          additional: ['泰国产能爬坡为未证伪传闻，证据等级仅 social_lead', '与 300394 暴露高度重叠，组合层需合并计算'],
        },
        {
          round_num: 3, speaker: 'adjudicator', winning_side: 'tie', action_bias: '谨慎偏多',
          bull_response: [
            '承认拥挤度风险，但订单与出货是硬证据，强于估值担忧',
            '接受仓位压缩，维持 5% 试错而非追高加仓',
          ],
          rationale: '趋势与景气共振成立(多方胜在硬证据)，但估值与拥挤度要求让位(空方胜在风险纪律)。裁定谨慎偏多:规则内小仓试错、禁止追高。',
        },
      ],
      trader: { position_pct: 8.0, reasoning: '技术主导 + 景气催化，交易视角建议试错仓 8%。' },
      risk: { approved: true, trader_position_pct: 8.0, adjusted_position_pct: 5.0, veto_reason: null,
        risk_notes: ['单股仓位 12.8% < 15% 上限', '板块暴露 24.1% < 30% 上限', '长期标签约束:试错仓 8% → 5%'] },
    },
    '002230': {
      symbol: '002230', name: '科大讯飞', date: SIG_DATE, used_llm: true, round_count: 3,
      analysts: [
        { role: '技术', key: 'technical', score: -30.0, confidence: 0.50, findings: ['趋势破位，跌破关键均线', '量能放大但方向向下'] },
        { role: '量化', key: 'quant', score: 0.0, confidence: 0.30, findings: ['模型=休眠(WEIGHT_QUANT=0)'] },
        { role: '情感', key: 'sentiment', score: -8.0, confidence: 0.35, findings: ['新闻热度高但情绪分歧大', '影响周期: 短线'] },
        { role: '新闻', key: 'news', score: 12.0, confidence: 0.40, findings: ['星火 V5 发布，主题催化(+)', '盈利下修，G 端回款承压(−)'] },
      ],
      director: {
        avg_confidence: 0.39, score_stdev: 17.4, diverged: true,
        debate_topic: '新闻信号 +12(主题催化)与技术信号 −30(破位)分歧;请论证新闻热度能否对抗技术破位与盈利下修。',
        quality_notes: ['平均置信度 0.39 偏低，建议谨慎对待结论'],
        weak_roles: ['量化', '情感'],
      },
      rounds: [
        { round_num: 1, speaker: 'bull', key_signal: '新闻主题催化',
          points: ['星火 V5 发布，AI 应用主题热度高', '市场关注度带来短线交易性机会'] },
        { round_num: 2, speaker: 'bear',
          rebuttals: [
            { target: '主题热度高', counter: '新闻高热但价格弱确认，记忆库已记录"新闻分不得单独触发买入"' },
            { target: '短线交易机会', counter: '技术破位 −30，连续两季盈利下修，趋势与基本面共振向下' },
          ],
          additional: ['G 端回款持续承压，现金流质量下滑'] },
        { round_num: 3, speaker: 'adjudicator', winning_side: 'bear', action_bias: '偏空',
          bull_response: ['主题催化无法对抗破位与下修，撤回看多'],
          rationale: '新闻热度不构成买入依据。技术破位 + 盈利下修共振，空方完胜。维持规避。' },
      ],
      trader: { position_pct: 0.0, reasoning: '破位 + 下修，交易视角不建议任何仓位。' },
      risk: { approved: true, trader_position_pct: 0.0, adjusted_position_pct: 0.0, veto_reason: null,
        risk_notes: ['维持规避，不新增暴露', '记忆规则命中:新闻高热弱确认'] },
    },
    _default: {
      symbol: '', name: '', date: SIG_DATE, used_llm: false, round_count: 0,
      analysts: [
        { role: '技术', key: 'technical', score: 0, confidence: 0.3, findings: ['趋势结构中性'] },
        { role: '量化', key: 'quant', score: 0, confidence: 0.3, findings: ['模型=休眠'] },
        { role: '情感', key: 'sentiment', score: 0, confidence: 0.3, findings: ['情绪中性'] },
        { role: '新闻', key: 'news', score: 0, confidence: 0.1, findings: ['无关键事件'] },
      ],
      director: { avg_confidence: 0.3, score_stdev: 6.0, diverged: false, debate_topic: '', quality_notes: ['四路方向一致，未触发辩论'], weak_roles: [] },
      rounds: [],
      fallback_reason: '四路均值方向一致，标准差 < 阈值，跳过辩论(quick_consensus，零 LLM)。',
      trader: { position_pct: 0, reasoning: '方向不明，维持观察。' },
      risk: { approved: true, trader_position_pct: 0, adjusted_position_pct: 0, veto_reason: null, risk_notes: ['无新增暴露'] },
    },
  };

  // ---------- 深度研究报告(deep research,含来源审计 + 证伪问题 + 报告闸门) ----------
  const DEEP_RESEARCH = [
    {
      id: 'dr-1', title: 'AI 光模块供需推演 2026–2027', topic: '光模块 1.6T 渗透节奏与北美云厂资本开支',
      symbols: ['300308', '300394'], as_of: '2026-06-08', stance: '谨慎偏多', confidence: 0.62,
      gate_status: 'pass', gate_reasons: [], source_count: 9, weak_source_count: 2, llm_cny: 0.34,
      sections: [
        { role: '景气', catalysts: ['北美四大云厂 2026 资本开支指引上调', '1.6T 送样进度超预期'], risks: ['板块拥挤度历史高位', '价格已部分透支预期'] },
        { role: '供需', catalysts: ['800G 出货持续放量', '上游器件议价能力增强'], risks: ['新进入者扩产，2027 供给或转松'] },
      ],
      audits: [
        { source: '北美云厂季报电话会', tier: 'primary', usable: true, risk_flags: [], published_at: '2026-06-05' },
        { source: '交易所互动易公司回复', tier: 'ir', usable: true, risk_flags: [], published_at: '2026-06-06' },
        { source: '中金行业研究', tier: 'industry', usable: true, risk_flags: [], published_at: '2026-06-04' },
        { source: '产业链调研纪要', tier: 'industry', usable: true, risk_flags: [], published_at: '2026-06-03' },
        { source: '泰国产能爬坡传闻', tier: 'social_lead', usable: false, risk_flags: ['网传', '未证伪'], published_at: '2026-06-07' },
      ],
      falsification: ['北美资本开支指引若 Q3 下修，景气逻辑受损', '1.6T 渗透若慢于送样进度，估值难维持', '新增产能若 2027 集中释放，供需转松'],
      content: `# AI 光模块供需推演 2026–2027

## 论题
1.6T 渗透节奏是核心变量，北美四大云厂资本开支节奏决定需求曲线。本报告为 observe-only 研究，不构成买入依据，不改官方信号。

## 关键发现
- **需求侧**:北美云厂上调 2026 资本开支指引，800G 出货持续放量，1.6T 送样超预期。
- **供给侧**:上游器件议价能力增强;但需警惕 2027 新增产能集中释放使供需转松。
- **估值**:板块拥挤度处历史高位，好消息已被两周上涨部分定价。

## 证据与来源
| 来源 | 等级 | 可用 | 备注 |
|---|---|---|---|
| 北美云厂季报电话会 | primary | 是 | 一手资本开支指引 |
| 交易所互动易回复 | ir | 是 | 公司回复≠审计事实 |
| 中金行业研究 | industry | 是 | 第三方测算 |
| 泰国产能爬坡传闻 | social_lead | 否 | 网传，未证伪，不作唯一证据 |

## 证伪条件
1. 北美资本开支指引 Q3 下修 → 景气逻辑受损。
2. 1.6T 渗透慢于送样进度 → 估值难维持。
3. 2027 新增产能集中释放 → 供需转松。

## 报告闸门
来源完整性 pass · 时间线 pass · 叙事证据 pass(含一手来源) · 越界措辞 pass。`,
    },
    {
      id: 'dr-2', title: '科大讯飞 G 端回款与盈利质量', topic: '盈利下修是否结束 + 现金流质量',
      symbols: ['002230'], as_of: '2026-06-08', stance: '偏空', confidence: 0.48,
      gate_status: 'warning', gate_reasons: ['弱证据(媒体叙事)占比偏高，已携带 warning 输出'], source_count: 5, weak_source_count: 3, llm_cny: 0.22,
      sections: [
        { role: '质量', catalysts: ['星火 V5 发布，主题热度'], risks: ['连续两季盈利下修', 'G 端回款承压，现金流质量下滑'] },
      ],
      audits: [
        { source: '公司半年报', tier: 'filing', usable: true, risk_flags: [], published_at: '2026-04-28' },
        { source: '券商盈利预测下修', tier: 'industry', usable: true, risk_flags: [], published_at: '2026-06-08' },
        { source: '自媒体解读', tier: 'social_lead', usable: false, risk_flags: ['网传'], published_at: '2026-06-09' },
      ],
      falsification: ['若下季 G 端回款回正，盈利下修逻辑反转', '若现金流改善，质量担忧解除'],
      content: `# 科大讯飞 G 端回款与盈利质量

## 论题
盈利下修是否见底，现金流质量能否改善。observe-only，不构成投资建议。

## 关键发现
- 连续两季盈利下修，G 端回款承压，现金流质量下滑。
- 星火 V5 发布带来主题热度，但属新闻催化，价格弱确认。

## 报告闸门 ⚠ warning
弱证据(媒体叙事)占比偏高，报告携带 warning 输出。结论仅作风险参考，**不自动影响生产信号，不自动促进记忆**。

## 证伪条件
1. 下季 G 端回款回正 → 盈利下修逻辑反转。
2. 现金流改善 → 质量担忧解除。`,
    },
    {
      id: 'dr-3', title: '存储周期修复持续性', topic: '存储价格企稳与国产替代共振',
      symbols: ['603986'], as_of: '2026-06-06', stance: '中性', confidence: 0.50,
      gate_status: 'pass', gate_reasons: [], source_count: 6, weak_source_count: 1, llm_cny: 0.19,
      sections: [
        { role: '景气', catalysts: ['存储价格企稳，周期底部修复', '国产替代共振'], risks: ['兑现节奏不稳，财报波动大', '估值分位 88%，价格领先基本面'] },
      ],
      audits: [
        { source: '行业价格数据库', tier: 'official', usable: true, risk_flags: [], published_at: '2026-06-05' },
        { source: '公司季报', tier: 'filing', usable: true, risk_flags: [], published_at: '2026-05-10' },
      ],
      falsification: ['价格修复若停滞，周期逻辑证伪', '财报兑现若低预期，估值打折'],
      content: `# 存储周期修复持续性

## 论题
存储价格企稳能否延续，国产替代共振强度。observe-only。

## 关键发现
- 存储价格企稳，周期底部修复方向明确，国产替代共振。
- 兑现节奏不稳定，财报波动大;估值分位 88%，价格领先基本面。

## 结论
方向认可但等待财报或成交确认，维持中性。`,
    },
  ];

  // ---------- 外部论题进口(ForwardThesis,带失效条件与复盘节奏) ----------
  const FORWARD_THESES = [
    {
      id: 'ft-1', title: '光模块 1.6T 渗透周期', symbol: '300308', name: '中际旭创',
      source_type: '外部研究者', source_name: 'A-teacher 框架', as_of: '2026-05-28', status: 'active',
      review_cadence: '每两周', next_review: '2026-06-22',
      summary: '把成熟外部研究者关于 1.6T 渗透节奏的判断进口为可跟踪论题，带失效条件，长期持续跟踪。论题只作论据，不直接抬高买入分。',
      follow_metrics: ['北美四大云厂季度资本开支', '1.6T 送样 → 量产时间表', '光模块板块成交额扩散度'],
      kill_conditions: ['北美资本开支连续两季下修', '1.6T 量产时间表明显推迟', '板块成交额持续背离价格'],
    },
    {
      id: 'ft-2', title: '存储国产替代', symbol: '603986', name: '兆易创新',
      source_type: '景气框架', source_name: '行业景气位置', as_of: '2026-05-20', status: 'watch',
      review_cadence: '每月', next_review: '2026-06-20',
      summary: '以行业景气位置框架进口的存储周期修复论题，需结果验证才升级为可信记忆。',
      follow_metrics: ['存储现货价格指数', '渠道库存周转', '季度毛利率拐点'],
      kill_conditions: ['价格修复停滞或回落', '库存去化不及预期'],
    },
  ];

  // ---------- 短期信号因子分解(技术 + 情感) ----------
  const SIGNAL_FACTORS = {
    '300308': {
      technical: [
        { name: '趋势 / 均线', value: '多头排列', score: 18, note: '站稳 20 / 60 日均线' },
        { name: 'MACD', value: '金叉延续', score: 12, note: 'DIF 上穿 DEA，红柱走阔' },
        { name: 'RSI(14)', value: '62.5', score: 6, note: '偏强，未超买' },
        { name: 'ADX(14)', value: '28.4', score: 8, note: '趋势成立(>25)' },
        { name: '量能', value: '温和放量', score: 4, note: '量价配合' },
      ],
      sentiment: { score: 0.55, news_count: 4, positive: 2, neutral: 1, warning: 1, impact: '中线', note: '北美资本开支上调驱动，情绪偏强' },
      formula: '技术 0.6 × 48.0 + 情感 0.4 × 55.0 = 综合 36.0(量化权重 0，休眠)',
    },
    '002230': {
      technical: [
        { name: '趋势 / 均线', value: '空头排列', score: -16, note: '跌破 20 / 60 日均线' },
        { name: 'MACD', value: '死叉', score: -10, note: 'DIF 下穿 DEA' },
        { name: 'RSI(14)', value: '38.2', score: -2, note: '偏弱' },
        { name: 'ADX(14)', value: '22.1', score: -2, note: '趋势偏弱' },
        { name: '量能', value: '放量下跌', score: 0, note: '量增价跌' },
      ],
      sentiment: { score: -0.08, news_count: 3, positive: 1, neutral: 0, warning: 2, impact: '短线', note: '星火 V5 主题热，但价格弱确认' },
      formula: '技术 0.6 × (−30.0) + 情感 0.4 × (−8.0) = 综合 −24.0',
    },
    _default: {
      technical: [
        { name: '趋势 / 均线', value: '中性', score: 0, note: '方向不明' },
        { name: 'MACD', value: '粘合', score: 0, note: '无明确信号' },
        { name: 'RSI(14)', value: '50.0', score: 0, note: '中性区' },
        { name: '量能', value: '平淡', score: 0, note: '无放量确认' },
      ],
      sentiment: { score: 0.0, news_count: 2, positive: 1, neutral: 1, warning: 0, impact: '短线', note: '近期无重大催化' },
      formula: '技术 0.6 + 情感 0.4 加权;量化权重 0(休眠)',
    },
  };

  // ---------- 公司财务状况 ----------
  const FINANCIALS = {
    '300308': {
      quality: 'pass', years: 5,
      metrics: [
        ['市盈率 PE(TTM)', '38.5', '分位 85%', 'warn'],
        ['市净率 PB', '6.2', '分位 78%', 'warn'],
        ['营收同比', '+42.3%', '高增长', 'up'],
        ['净利同比', '+56.8%', '盈利提速', 'up'],
        ['毛利率', '32.1%', '稳中有升', 'up'],
        ['ROE', '18.6%', '优于行业', 'up'],
        ['资产负债率', '28.4%', '稳健', ''],
        ['Piotroski F', '7 / 9', '质量良好', 'up'],
      ],
      rows: [
        { year: '2023', revenue: 89.2, profit: 12.1, roe: 14.2, margin: 28.5 },
        { year: '2024', revenue: 142.6, profit: 21.4, roe: 16.8, margin: 30.4 },
        { year: '2025E', revenue: 203.0, profit: 33.6, roe: 18.6, margin: 32.1 },
      ],
      cash_flow: '经营性现金流连续为正，与净利匹配，盈利质量良好。',
      qfii: 'QFII 在前十大流通股东中小幅增持，无减持信号。',
    },
    '002230': {
      quality: 'pass', years: 5,
      metrics: [
        ['市盈率 PE(TTM)', '52.1', '分位 70%', 'warn'],
        ['市净率 PB', '4.1', '分位 55%', ''],
        ['营收同比', '+6.2%', '增速放缓', 'warn'],
        ['净利同比', '−18.4%', '连续下修', 'down'],
        ['毛利率', '41.2%', '高位回落', 'warn'],
        ['ROE', '6.8%', '弱于行业', 'down'],
        ['资产负债率', '46.7%', '偏高', 'warn'],
        ['Piotroski F', '4 / 9', '质量一般', 'warn'],
      ],
      rows: [
        { year: '2023', revenue: 196.5, profit: 6.4, roe: 9.1, margin: 42.8 },
        { year: '2024', revenue: 208.6, profit: 5.6, roe: 7.4, margin: 41.9 },
        { year: '2025E', revenue: 221.5, profit: 4.6, roe: 6.8, margin: 41.2 },
      ],
      cash_flow: 'G 端回款承压，经营性现金流低于净利，盈利质量下滑。',
      qfii: 'QFII 持股环比下降，列入反向规避参考。',
    },
    '600519': {
      quality: 'insufficient', years: 5,
      metrics: [
        ['市盈率 PE(TTM)', '22.4', '分位 35%', ''],
        ['市净率 PB', '7.8', '分位 40%', ''],
        ['营收同比', '+11.2%', '稳健', 'up'],
        ['净利同比', '+13.1%', '稳健', 'up'],
        ['毛利率', '91.8%', '极高', 'up'],
        ['ROE', '31.2%', '行业领先', 'up'],
        ['资产负债率', '18.9%', '极稳健', 'up'],
        ['Piotroski F', '8 / 9', '质量优秀', 'up'],
      ],
      rows: [
        { year: '2023', revenue: 1476, profit: 735, roe: 30.1, margin: 91.5 },
        { year: '2024', revenue: 1640, profit: 831, roe: 31.0, margin: 91.7 },
        { year: '2025E', revenue: 1823, profit: 940, roe: 31.2, margin: 91.8 },
      ],
      cash_flow: '现金流极其充沛，分红稳定，质量行业标杆。',
      qfii: 'QFII 长期重仓，持股稳定。',
    },
    _default: {
      quality: 'insufficient', years: 0,
      metrics: [
        ['市盈率 PE(TTM)', '—', '数据待回填', ''],
        ['ROE', '—', '数据待回填', ''],
        ['Piotroski F', '—', '需 5 年财务', ''],
      ],
      rows: [],
      cash_flow: '财务数据待回填。港股 / 美股为 observe-only，财务面仅作研究参考。',
      qfii: 'QFII 数据仅 A 股适用。',
    },
  };

  // ---------- 个股分析文字 ----------
  const ANALYSIS = {
    '300308': `## 个股分析 · 中际旭创

**一句话**:全球光模块龙头，AI 算力链最直接受益标的之一;趋势与景气共振，但估值已部分透支预期。

### 基本面
公司是 800G / 1.6T 高速光模块的核心供应商，深度绑定北美云厂资本开支周期。2024 年以来收入与净利维持高增速(营收 +42%、净利 +57%)，毛利率稳中有升至 32%，ROE 升至 18.6%，Piotroski 财务质量评分 7/9，经营性现金流与净利匹配，盈利质量良好。

### 短期催化
- 800G 出货月度创新高，1.6T 送样进度超预期;
- 北美四大云厂上调 2026 资本开支指引，板块整体走强。

### 主要风险
- 板块拥挤度升至历史高位，好消息已被两周上涨部分定价;
- 估值分位处 85% 以上，短期乖离率偏高，追高回撤风险放大;
- 与 300394 暴露高度重叠，组合层需合并计算;泰国产能爬坡为未证伪传闻。

### 结论
官方信号「可小仓试错」(综合 +36)，长期标签「值得持有」允许试错但压缩仓位上限至 5%。**规则内小仓试错、禁止追高加仓**;若两日内放量滞涨，优先减仓而非补仓。`,
    '002230': `## 个股分析 · 科大讯飞

**一句话**:AI 应用主题热度高，但业绩兑现不足，盈利下修与技术破位共振，维持规避。

### 基本面
公司为 AI 应用龙头，但近两季净利连续下修(−18%)，G 端回款承压，经营性现金流低于净利，盈利质量下滑;ROE 降至 6.8%，Piotroski 评分 4/9。

### 短期信号
星火 V5 发布带来主题热度，但股价冲高回落，价格弱确认。技术上跌破 20/60 日均线，MACD 死叉，放量下跌。

### 结论
官方信号「规避」(综合 −24)。记忆库规则命中:**新闻高热但价格弱确认时，新闻分不得单独触发买入**。维持规避，不补仓，等待下一次有效信号。`,
    '600519': `## 个股分析 · 贵州茅台

**一句话**:财务质量行业标杆，但短线缺乏弹性与催化，只加入观察。

### 基本面
极高毛利率(92%)、ROE 31%、负债率仅 19%，现金流充沛、分红稳定，Piotroski 8/9，质量无可挑剔。

### 短期信号
估值回到合理区间(PE 分位 35%)，股息率有支撑;但量能确认不足，缺少短线催化。系统不应因品牌质量自动给高短线分。

### 结论
官方信号「可关注」(综合 +18)，长期标签「观望」。质量稳定但缺乏短线弹性，**只加入观察，不新增仓位**。`,
    _default: `## 个股分析

该标的暂无完整研究档案。可在 AI 对话中运行「深度研究」或「长期研究团队」生成结构化分析;港股 / 美股为 observe-only，数据仅用于研究，不进入 A 股官方信号。`,
  };

  const WORKFLOWS = [
    { id: 'premarket', label: '盘前', status: '就绪', tone: 'badge-accent', summary: '同步前检查、覆盖缺口、当日入口', side_effect: '默认只读预检' },
    { id: 'intraday', label: '盘中', status: '只读', tone: 'badge-dim', summary: '缓存行情、持仓风险、止损观察', side_effect: '不触网、不写信号' },
    { id: 'postmarket', label: '盘后', status: '主流程', tone: 'badge-up', summary: '全市场信号、复盘、导出、记忆候选', side_effect: '写 signals / reviews' },
    { id: 'weekend', label: '周末', status: '慢变量', tone: 'badge-warn', summary: '长期标签、周度反思、研究题库', side_effect: '写 long-term / review' },
  ];

  const VALIDATION = {
    alpha_state: {
      profile: 'new_framework',
      quant_weight: 0,
      technical_weight: 0.6,
      sentiment_weight: 0.4,
      conclusion: '量化继续休眠;M29 只做 forward shadow，不提升生产权重。',
      updated_at: '2026-06-10',
    },
    m29: {
      ready: false,
      readiness: 'blocked',
      coverage_through: '2026-06-02',
      required_window: '100 标的完整覆盖 + 1d / 3d / 5d baseline artifacts',
      missing: ['100-symbol coverage after 2026-06-02', '1d baseline artifact', '3d baseline artifact', '5d baseline artifact'],
      next_action: '先只读诊断覆盖和 baseline artifact 缺口，ready 后再追加 shadow bundle。',
    },
    promotion_gates: [
      ['IC >= 0.04', 'blocked', '样本不足'],
      ['ICIR >= 0.40', 'blocked', '缺 fresh forward window'],
      ['单调分桶', 'warning', '旧样本可看，但不能推广'],
      ['non-overlap / stride', 'blocked', 'baseline artifacts 缺失'],
      ['provenance / PIT', 'pass', 'lookahead check 已披露'],
      ['人工确认', 'blocked', '未进入 promotion review'],
    ],
    reports: [
      { id: 'm29-readiness', title: 'M29 Forward Readiness', kind: 'forward evidence', status: 'blocked', date: '2026-06-09', summary: 'ready_to_run_forward_shadow=false;先修覆盖与 baseline artifact。' },
      { id: 'm42-qfq', title: 'M42 QFQ/HFQ 污染防护', kind: 'data guard', status: 'pass', date: '2026-06-08', summary: '前复权/后复权口径污染被 dry-run 检测与修复路径隔离。' },
      { id: 'lookahead-standing', title: 'Standing Lookahead Check', kind: 'evidence trust', status: 'warning', date: '2026-06-10', summary: 'warning 只披露，blocked 不允许自动 promotion。' },
      { id: 'm31-cache', title: 'M31 Cache / Provider Fallback', kind: 'runtime', status: 'pass', date: '2026-06-07', summary: '本地缓存优先，L3 不默认调用付费远端。' },
    ],
  };

  const SOURCE_GATES = {
    summary: { pass: 7, warning: 3, blocked: 2, latest_gate: 'ResearchReportGate', latest_status: 'warning' },
    tiers: [
      ['primary', '一手来源', 3, '可支撑核心论点'],
      ['official', '官方/交易所', 4, '优先引用'],
      ['filing', '定报/公告', 5, '财务与事实锚点'],
      ['industry', '行业资料', 6, '需要交叉验证'],
      ['social_lead', '社媒线索', 2, '只能作为待查线索'],
    ],
    gate_rules: [
      { rule: '来源完整性', status: 'pass', note: '核心结论至少一条 official / filing / primary 支撑。' },
      { rule: '禁用越界措辞', status: 'pass', note: '报告不得出现强买、稳赚、确定性收益。' },
      { rule: 'Serenity 字段', status: 'warning', note: '供应链层级齐全，替代风险需补二级来源。' },
      { rule: 'blocked 写入', status: 'pass', note: 'blocked 报告不落盘、不建 memory candidate。' },
    ],
  };

  const MEMORY_CENTER = {
    overview: { total: 47, trusted: 18, pending: 6, refuted: 3, stock_items: 21, l0_atoms: 38 },
    lanes: [
      ['AI Memory', '全局规则 / 偏好 / 风险提醒', 12, 'trusted 8'],
      ['Stock Memory', '个股经验 / 研究指针 / 风险案例', 21, 'pending 4'],
      ['L0 Atoms', '带来源和 trust_state 的原子记忆', 38, 'refuted 3'],
      ['Layered Memory', '场景化召回与决策记忆', 9, '只读上下文'],
    ],
    queue: [
      { id: 'mc-1', symbol: '300308', title: '光模块拥挤度高时禁止追高补仓', source: 'review_case#42', trust: 'pending', evidence: '两次放量滞涨后回撤案例', action: '建议升级为 stock_memory trusted' },
      { id: 'mc-2', symbol: '002230', title: '新闻热度不能单独触发买入', source: 'daily_review 2026-06-09', trust: 'pending', evidence: '发布会高热但价格弱确认', action: '保留为全局风险提醒' },
      { id: 'mc-3', symbol: '600519', title: '质量稳定但缺少短线弹性时只观察', source: 'long_term W24', trust: 'candidate', evidence: '长期质量高，短线量能不足', action: '等待下次复盘验证' },
    ],
    audit: [
      ['09:12', 'recall', '300308', '召回 3 条 trusted stock memory'],
      ['09:18', 'candidate', 'review_case#42', '产生待确认记忆候选'],
      ['09:22', 'refute', 'old-thesis#7', '旧需求假设被财报证伪'],
    ],
  };

  const CASE_LOOP = {
    '300308': {
      thesis: 'AI 光模块景气仍强，但估值与拥挤度要求小仓试错。',
      status: 'active',
      gate_status: 'warning',
      research_priority: '够查',
      next_review: '2026-06-14 或放量滞涨触发',
      source_mix: [['official', 2], ['filing', 3], ['industry', 5], ['social_lead', 1]],
      loop: [
        ['进口判断', '北美资本开支上调带动 800G/1.6T 需求'],
        ['证据来源', '公告/财报/行业链跟踪/新闻审计'],
        ['证伪条件', '订单兑现低于预期、板块成交额背离、估值分位继续抬升'],
        ['跟踪指标', '周度出货、板块扩散度、与 300394 合并暴露'],
        ['复盘结果', '最近一次试错仓胜率高，但追高案例已写入风险记忆'],
        ['记忆更新', '1 条待确认 stock memory，不自动 trusted'],
      ],
      questions: ['如果北美 CAPEX 放缓，收入弹性是否仍能覆盖估值?', '板块拥挤度回落时是风险释放还是趋势结束?', '与 300394 二选一持有时保留哪条证据更强?'],
      artifacts: ['decision_run#482', 'research_dossier#300308', 'memory_candidate#mc-1', 'm29_non_promoting_shadow'],
    },
    _default: {
      thesis: '该标的还没有完整 Case Loop，需要先运行 research.prepare 或 deep research。',
      status: 'draft',
      gate_status: 'warning',
      research_priority: '暂缓',
      next_review: '等待下一次研究运行',
      source_mix: [['official', 0], ['filing', 0], ['industry', 1]],
      loop: [
        ['进口判断', '等待用户或外部研究输入'],
        ['证据来源', '先补充官方/定报/行业来源'],
        ['证伪条件', '暂无'],
        ['跟踪指标', '暂无'],
        ['复盘结果', '暂无'],
        ['记忆更新', '不生成 trusted memory'],
      ],
      questions: ['这个标的为什么值得进入研究池?', '有哪些来源可以证伪原始判断?'],
      artifacts: [],
    },
  };

  const TOOLS_REGISTRY = {
    counts: { stable: 6, maintenance: 13, evidence: 18, attic: 4 },
    items: [
      { module: 'coverage_snapshot', category: 'stable', boundary: 'read-only', purpose: '输出当前数据覆盖快照' },
      { module: 'm29_forward_readiness', category: 'evidence', boundary: 'read-only', purpose: '守住下一次 forward shadow readiness' },
      { module: 'm45_import_ateacher_theses', category: 'maintenance', boundary: 'dry-run first', purpose: '导入外部论题，只写 ForwardThesis / pending atoms' },
      { module: 'm45_falsification_scoreboard', category: 'maintenance', boundary: 'dry-run first', purpose: '记录证伪记分牌事件' },
      { module: 'm42_remediate_hfq_contamination', category: 'maintenance', boundary: 'dry-run/report safe', purpose: '检测和修复复权污染' },
      { module: 'atlas_test4_stage2b_shadow', category: 'evidence', boundary: 'non-promoting', purpose: 'Atlas 信号叠加影子观察' },
    ],
  };

  const SYSTEM = {
    version: '0.5.1', release: [['v0.5.1', '上下文脱敏'], ['Status', '安全版本面'], ['Atlas', '休眠静默'], ['Quant', '生产关闭']],
    market_overview: { available: true, name: '沪深300', close: 4082.35, change_pct: 0.42, date: '2026-06-09',
      indices: [
        { name: '上证指数', close: 3421.56, change_pct: 0.38 },
        { name: '深证成指', close: 11248.70, change_pct: 0.51 },
      ] },
    health: { db: true, agent_mode: 'local_cli', watchlist: 8, positions: 4, memory: 47, scheduler: '未启用(手动模式)' },
    model: { qlib: '休眠(权重 0)', kronos: '默认关闭', last_train: '—' },
  };

  const COPILOT_ORCHESTRATION = {
    target: { symbol: '300308', name: '中际旭创', dossier: 'research_dossier#300308', stock_route: '/stock/300308' },
    stages: [
      ['意图解析', '识别标的、问题类型和是否会产生写入动作', 'read-only'],
      ['证据检索', '拉取信号、新闻审计、复盘案卷、记忆召回', 'read-only'],
      ['Skill 编排', '按任务选择个股案卷、来源审计、风险经理等技能', 'tooling'],
      ['多轮辩论', 'Bull / Bear / Adjudicator 多轮交锋，轮数可调', 'llm'],
      ['研究落点', '写入影子意见、候选记忆或待确认动作', 'pending'],
    ],
    skills: [
      { name: 'source_audit', label: '来源审计', status: 'active', boundary: '只读证据' },
      { name: 'stock_dossier', label: '个股案卷', status: 'active', boundary: '更新影子研究' },
      { name: 'debate_director', label: '辩论总监', status: 'active', boundary: '决定议题与轮数' },
      { name: 'risk_manager', label: '风险经理', status: 'active', boundary: '只能降级/拦截' },
      { name: 'memory_recall', label: '记忆召回', status: 'active', boundary: '只读 trusted' },
      { name: 'review_writer', label: '复盘写入', status: 'guarded', boundary: '只建候选' },
    ],
    round_templates: [
      ['R1 多方开场', '整理支持 thesis 的硬证据和价格确认。'],
      ['R2 空方反驳', '逐条挑战估值、拥挤度、证据等级和时间戳。'],
      ['R3 研究总监裁定', '合并分歧，给出谨慎/中性/回避的影子结论。'],
      ['R4 风险压力测试', '检查仓位上限、同板块暴露和止损约束。'],
      ['R5 证伪清单', '形成后续跟踪指标和失效条件，进入复盘案卷。'],
    ],
    outputs: [
      ['个股案卷', '更新副驾驶影子意见与证伪问题', '/stock/300308'],
      ['复盘案卷', '沉淀论据、复盘记录和候选记忆', '/reports'],
      ['待确认动作', '添加自选/持仓/记忆升级都需人工确认', '/chat'],
    ],
  };

  // ---------- AI 聊天脚本 ----------
  const CHAT_SESSIONS = [
    { id: 's1', title: '300308 研究讨论', mode: 'general', last_message: '试错仓建议保持 5%，不要追高加仓', messages: [
      { role: 'user', content: '300308 现在还能加仓吗?' },
      { role: 'assistant', answer: '根据今日信号(综合分 **+36.0**，可小仓试错):\n\n- 趋势与产业景气共振成立，技术分 +48.0\n- 但估值分位已在 85% 以上，长期标签触发约束\n- 最终仓位上限被压缩到 **5%**，你当前已持有 12.8%\n\n**结论:不建议加仓。** 若两日内放量滞涨，优先减仓而非补仓。', used_resources: ['signals/300308/latest', 'research/300308/dossier', 'memory/m3'] },
    ] },
    { id: 's2', title: '本周复盘要点', mode: 'general', last_message: '已生成长期复盘 2026-W24', messages: [] },
  ];

  const CHAT_SCRIPTS = [
    { match: /添加自选|加自选|watchlist/i, reply: '好的，我准备把该标的加入自选池。添加后系统会在下次收盘后自动生成信号。\n\n请确认以下操作:', action: { id: 'act-1', action: 'watchlist.add', payload: { symbol: '002475', name: '立讯精密', market: 'CN' }, risk: 'medium' }, resources: ['stocks/search'] },
    { match: /添加持仓|买入|position/i, reply: '我已解析出持仓参数。**注意:明仓不接券商，这只是记录，不会真实下单。**\n\n请确认以下操作:', action: { id: 'act-2', action: 'position.add', payload: { symbol: '300308', quantity: 100, avg_cost: 150.0, market: 'CN' }, risk: 'high' }, resources: ['positions'] },
    { match: /研究|分析|怎么看/i, reply: '## 研究摘要\n\n基于最新信号与证据链:\n\n- **官方建议**:可小仓试错(综合分 +36.0，置信度中)\n- **多方**:技术趋势占优;产业催化密集;长期标签允许试错\n- **空方**:板块拥挤度历史高位;估值分位 85%+\n- **风险经理**:单股 12.8% < 15% 上限，通过;但与 300394 需合并计算暴露\n\n**裁决**:趋势与景气共振，但估值已部分透支。规则内小仓试错，禁止追高。', resources: ['signals/300308/latest', 'signals/300308/evidence', 'memory/context'] },
    { match: /复盘/i, reply: '今日复盘(2026-06-09)已生成:\n\n- 当日信号 6 条:试错 2 · 观察 3 · 规避 1\n- 大盘扩散度中性，不适合大幅提高总仓位\n- 300308 接近止盈观察线，明日重点看量\n\n完整报告可在「复盘」页查看。', resources: ['reviews/daily/2026-06-09'] },
    { match: /止损|风险/i, reply: '当前持仓风险状态:\n\n| 标的 | 现价距止损 | 状态 |\n|---|---|---|\n| 300308 | +7.5% | 安全，移动止损已上移 |\n| 600519 | +6.4% | 安全 |\n| 000725 | +3.1% | 接近观察线 |\n\n移动止损(ATR 跟踪)已启用，触发时会通过复盘和推送提醒，**不会自动卖出**。', resources: ['positions', 'config/trailing_stop'] },
  ];
  const CHAT_FALLBACK = '我可以帮你:\n\n- **查询**:「300308 怎么看」「今天复盘说了什么」「持仓风险如何」\n- **操作**(需确认):「添加自选 002475」「添加持仓 300308 100股 成本150」\n\n所有写入操作都会生成待确认动作，确认前不会执行。';

  return {
    DEMO_META, PRICES, WATCHLIST, POSITIONS, SEARCH_POOL, NEWS, EVIDENCE, COPILOT, EVAL, DOSSIER,
    REVIEWS, COVERAGE, RUNTIME, LLM_USAGE, MEMORY, SYSTEM,
    DEBATE, DEEP_RESEARCH, FORWARD_THESES, SIGNAL_FACTORS, FINANCIALS, ANALYSIS,
    CHAT_SESSIONS, CHAT_SCRIPTS, CHAT_FALLBACK, COPILOT_ORCHESTRATION,
    WORKFLOWS, VALIDATION, SOURCE_GATES, MEMORY_CENTER, CASE_LOOP, TOOLS_REGISTRY,
    SIG_DATE, mkHistory, last,
  };
})();

// window 挂载仅为运行时兼容保留（部分模块仍按 window.MC_DATA 读取）
window.MC_DATA = MC_DATA;
