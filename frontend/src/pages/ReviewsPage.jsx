import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { ensureDailyReview, ensureLongTermReview, getLatestReviews, getReview, getReviews } from '../api'
import { buildReviewHistory, parseMarkdownBlocks } from './reviewContent'

const PANEL = 'rounded-sm border border-stone-300/80 bg-[#faf6ec] dark:border-slate-700 dark:bg-[#1d232e]'
const INSET = 'rounded-sm border border-stone-300 bg-[#f3eddc] dark:border-slate-700 dark:bg-[#161b25]'
const LABEL = 'text-[10px] font-semibold uppercase tracking-[0.2em] text-stone-500 dark:text-slate-400'

const DEMO_REVIEWS = {
  daily: {
    id: 'demo-daily',
    kind: 'daily',
    as_of: '2026-05-18',
    summary: '示例：今日生成 6 条信号，2 条进入可小仓试错，新闻情绪偏强但大盘扩散度一般。',
    path: '示例数据 · 真实复盘生成后自动替换',
    metrics: [
      ['信号', '6'],
      ['试错', '2'],
      ['规避', '1'],
    ],
    highlights: ['中际旭创动量延续，仓位建议保持小仓。', '大盘仍处中性区，新增仓位控制在规则上限内。'],
    content: `# MingCang 每日复盘 — 示例

## 摘要
- 当日信号：6 条
- 可小仓试错：2 条
- 可关注：3 条
- 规避：1 条
- 异动监控：2 条
- 安全审计：pass

## 大盘环境
- 沪深300 收盘偏弱，扩散度仍在中性下沿。
- 光模块、AI 服务器链条相对强势，但短线拥挤度上升。
- 今日适合保留观察仓，不适合大幅提高总仓位。

## 当日信号明细
| 股票 | 综合分 | 建议 | 置信度 | 量化 | 技术 | 情感 | 新闻 | 风险 |
|---|---:|---|---|---:|---:|---:|---:|---|
| 300308 中际旭创 | +36.0 | 可小仓试错 | 中 | +0.0 | +48.0 | +55.0 | 4 | 趋势强但波动放大 |
| 300394 天孚通信 | +31.5 | 可小仓试错 | 中 | +0.0 | +42.0 | +51.0 | 3 | 同板块暴露需控制 |
| 600519 贵州茅台 | +18.0 | 可关注 | 低 | +0.0 | +22.0 | +6.0 | 1 | 量能确认不足 |
| 603986 兆易创新 | +12.0 | 可关注 | 低 | +0.0 | +17.0 | +5.0 | 2 | 芯片链情绪改善 |
| 000725 京东方A | +6.0 | 可关注 | 低 | +0.0 | +8.0 | +3.0 | 1 | 仍需等待突破 |
| 002230 科大讯飞 | -24.0 | 规避 | 中 | +0.0 | -30.0 | -8.0 | 5 | 新闻分歧与技术破位 |

## 持仓复核
- 当前持仓应优先检查是否触及止损、止盈或移动止损条件。
- 对同一板块的重复暴露，需要合并计算总仓位。
- 如果已有 AI 算力链持仓，今日新增仓位建议只补最强信号，不做平均加仓。

## 异动监控
- [medium] 300308 接近止盈观察线，若次日高开回落，优先观察成交量。
- [low] 000725 价格跌破短均线但未触发系统性规避，暂不动作。

## 多空评论
### 多方
- 技术趋势仍然占优，强势股维持在关键均线上方。
- 新闻与产业催化集中在 AI 算力链，短期资金仍愿意交易。
- 长期标签若为“值得持有”，可允许短线信号小仓试错。

### 空方
- 板块拥挤度升高，追高风险加大。
- 大盘扩散度不足，容易出现强势股单独回撤。
- 新闻情绪存在重复引用和滞后风险，不能替代价格确认。

## 今日动作建议
1. 对“可小仓试错”只按规则小仓，不突破单股上限。
2. 对“可关注”只加入主动观察，不新增持仓。
3. 对“规避”标的不做补仓，等待下一次有效信号。
4. 明日重点看大盘扩散度、板块成交额和持仓止损位。

## 免责声明
本复盘用于记录和辅助决策，不构成投资建议，不自动触发交易。`,
    demo: true,
  },
  long_term: {
    id: 'demo-long',
    kind: 'long_term',
    as_of: '2026-W21',
    summary: '示例：长期研究团队完成核心自选股复核，2 只维持值得持有，1 只因估值偏高下调仓位建议。',
    path: '示例数据 · 周一 09:00 / 周五 15:00 后按规则生成',
    metrics: [
      ['持有', '2'],
      ['观望', '3'],
      ['规避', '1'],
    ],
    highlights: ['财务质量评分稳定，现金流和 ROE 是主要支撑。', '估值分位偏高的股票仅保留观察，不主动加仓。'],
    content: `# MingCang 长期复盘 — 示例

## 长期研究团队摘要
- 值得持有：2
- 估值偏高：1
- 观望：3
- 规避：1

## 组合层结论
长期研究团队认为，本周核心矛盾不是“有没有产业趋势”，而是“趋势已经被价格反映了多少”。因此短线信号可以继续使用，但仓位上限需要受到长期标签约束。

## 重点标的
### 300308 中际旭创
- 标签：值得持有
- 财务质量：收入增速和盈利能力仍在高位。
- 景气度：AI 光模块需求仍然强，但订单预期已经被市场充分交易。
- 风险：估值分位偏高，若短线信号转弱，应优先降仓而不是硬扛。

### 600519 贵州茅台
- 标签：观望
- 财务质量：稳定，但增速弹性不足。
- 景气度：消费复苏强度一般，缺少短线催化。
- 风险：系统不应因为品牌质量自动给高短线分。

### 603986 兆易创新
- 标签：估值偏高
- 财务质量：周期底部修复中。
- 景气度：国产替代与存储周期共振，但兑现节奏不稳定。
- 风险：若短线综合分进入可小仓试错，仓位建议打折。

## 标签变化
| 股票 | 上周 | 本周 | 变化原因 |
|---|---|---|---|
| 300308 | 值得持有 | 值得持有 | 景气度维持，但估值风险增加 |
| 603986 | 观望 | 估值偏高 | 价格提前反映修复预期 |
| 000725 | 观望 | 观望 | 基本面改善仍需数据确认 |

## 下周观察清单
1. 财报披露窗口是否改变长期标签。
2. 强势行业是否出现成交额背离。
3. 长期“规避”标的若出现短线强信号，仍需由风险经理二次拦截。
4. 若总仓位接近上限，优先保留长期标签更好的持仓。

## 记忆写入
- 保存本周标签变化，供后续短线信号仲裁使用。
- 保存估值偏高但短线强势的冲突案例，供下周复盘比较。
- 不保存一次性新闻标题，避免噪声污染长期记忆。`,
    demo: true,
  },
}

const DEMO_HISTORY = [
  DEMO_REVIEWS.daily,
  { ...DEMO_REVIEWS.long_term, id: 'demo-long-history' },
  {
    ...DEMO_REVIEWS.daily,
    id: 'demo-daily-2026-05-17',
    as_of: '2026-05-17',
    summary: '示例：生成 5 条信号，AI 算力链继续占优，消费和地产链保持观察。',
    metrics: [
      ['信号', '5'],
      ['试错', '1'],
      ['规避', '2'],
    ],
    highlights: ['300394 天孚通信强度保持，但与 300308 暴露高度重叠。', '消费白马短线分数改善，仍缺少成交确认。'],
    content: `# MingCang 每日复盘 — 2026-05-17 示例

## 摘要
- 当日信号：5 条
- 可小仓试错：1 条
- 可关注：2 条
- 规避：2 条
- 异动监控：3 条
- 安全审计：pass

## 交易环境
- 指数小幅反弹，但上涨家数不足，属于结构行情。
- AI 算力链继续强于市场，内部开始分化。
- 低位消费股出现修复，但成交额没有同步放大。

## 信号明细
| 股票 | 综合分 | 建议 | 置信度 | 技术 | 新闻 | 风险 |
|---|---:|---|---|---:|---:|---|
| 300394 天孚通信 | +34.0 | 可小仓试错 | 中 | +44.0 | +4 | 同板块拥挤 |
| 600519 贵州茅台 | +16.0 | 可关注 | 低 | +18.0 | +1 | 缺少催化 |
| 000725 京东方A | +11.0 | 可关注 | 低 | +14.0 | +1 | 突破未确认 |
| 002230 科大讯飞 | -18.0 | 规避 | 中 | -24.0 | +5 | 新闻分歧 |
| 601318 中国平安 | -12.0 | 规避 | 低 | -16.0 | +0 | 趋势偏弱 |

## 复盘动作
1. 对 AI 算力链只保留最强一只作为试错候选。
2. 消费和金融只加入观察，不新增仓位。
3. 已持仓标的若回撤至移动止损线，优先按规则处理。

## 备注
本条为前端示例数据，用于展示复盘卡片、历史列表和 Markdown 渲染效果。`,
    demo: true,
  },
  {
    ...DEMO_REVIEWS.daily,
    id: 'demo-daily-2026-05-16',
    as_of: '2026-05-16',
    summary: '示例：防守日，系统没有给出高置信买入，重点记录止损和异常新闻。',
    metrics: [
      ['信号', '4'],
      ['试错', '0'],
      ['规避', '3'],
    ],
    highlights: ['总仓位建议下调到观察区间。', '新闻热度升高但价格没有确认，避免追题材。'],
    content: `# MingCang 每日复盘 — 2026-05-16 示例

## 摘要
- 当日信号：4 条
- 可小仓试错：0 条
- 可关注：1 条
- 规避：3 条
- 异动监控：4 条
- 安全审计：pass

## 风险状态
- 大盘扩散度转弱，强势行业补跌风险上升。
- 新闻情绪与价格走势出现背离，不能用标题热度替代交易确认。
- 系统建议保持低换手，优先执行纪律而不是寻找新机会。

## 规避清单
| 股票 | 综合分 | 建议 | 触发项 | 处理 |
|---|---:|---|---|---|
| 002230 科大讯飞 | -28.0 | 规避 | 技术破位 | 不补仓 |
| 601318 中国平安 | -18.5 | 规避 | 趋势偏弱 | 等待修复 |
| 000063 中兴通讯 | -14.0 | 规避 | 新闻分歧 | 降低关注级别 |

## 持仓纪律
1. 已触发止损的标的不得因为盘中反抽取消纪律。
2. 同板块多个持仓需要合并计算风险暴露。
3. 明日若扩散度继续走弱，新增信号默认降一级处理。`,
    demo: true,
  },
  {
    ...DEMO_REVIEWS.long_term,
    id: 'demo-long-2026-W20',
    as_of: '2026-W20',
    summary: '示例：长期团队复核 6 只核心标的，质量因子稳定，估值约束变强。',
    metrics: [
      ['持有', '2'],
      ['观察', '4'],
      ['冲突', '2'],
    ],
    highlights: ['长期标签用于限制短线仓位，而不是替代短线信号。', '高估值强趋势案例进入下周重点跟踪。'],
    content: `# MingCang 长期复盘 — 2026-W20 示例

## 本周长期结论
- 值得持有：2
- 观察：4
- 规避：0
- 与短线信号冲突：2

## 团队视角
- 质量分析师：核心标的盈利质量没有明显恶化。
- 景气分析师：AI 算力链仍强，但边际预期正在变钝。
- 资金流分析师：外资与机构持仓没有形成一致加仓。
- 风险经理：估值分位偏高的标的需要降低短线信号权重。

## 标签表
| 股票 | 长期标签 | 短线冲突 | 处理建议 |
|---|---|---|---|
| 300308 中际旭创 | 值得持有 | 估值偏高 | 强信号可小仓，不追高 |
| 300394 天孚通信 | 值得持有 | 板块拥挤 | 与 300308 二选一 |
| 600519 贵州茅台 | 观察 | 缺催化 | 保持观察 |
| 603986 兆易创新 | 观察 | 周期未确认 | 等财报或成交确认 |

## 写入记忆
1. 保存“强趋势但估值偏高”的冲突案例。
2. 保存 AI 算力链重复暴露提醒。
3. 保存长期标签对仓位上限的约束规则。`,
    demo: true,
  },
  {
    ...DEMO_REVIEWS.long_term,
    id: 'demo-long-2026-W19',
    as_of: '2026-W19',
    summary: '示例：长期复盘偏防守，基本面稳定但市场风险偏好下降。',
    metrics: [
      ['持有', '1'],
      ['观察', '4'],
      ['规避', '1'],
    ],
    highlights: ['长期仓位不因单日反弹上调。', '规避标签主要来自盈利下修和技术破位共振。'],
    content: `# MingCang 长期复盘 — 2026-W19 示例

## 组合判断
- 基本面没有系统性恶化。
- 市场风险偏好下降，长期标签需要叠加仓位纪律。
- 对盈利下修且价格破位的标的，短线反弹不作为买入依据。

## 长期候选池
| 股票 | 标签 | 质量 | 景气 | 估值 | 备注 |
|---|---|---:|---:|---:|---|
| 300308 中际旭创 | 值得持有 | 86 | 91 | 38 | 高景气高估值 |
| 600519 贵州茅台 | 观察 | 92 | 58 | 61 | 稳定但缺弹性 |
| 000725 京东方A | 观察 | 63 | 67 | 70 | 周期修复待验证 |
| 002230 科大讯飞 | 规避 | 54 | 62 | 45 | 业绩兑现不足 |

## 下周问题
1. 哪些短线强信号有长期质量支撑？
2. 哪些新闻催化只是短期噪声？
3. 是否需要对低质量高热度股票加入额外拦截？`,
    demo: true,
  },
  {
    ...DEMO_REVIEWS.daily,
    id: 'demo-daily-2026-05-15',
    as_of: '2026-05-15',
    summary: '示例：反弹观察日，系统给出 7 条信号但多数置信度偏低。',
    metrics: [
      ['信号', '7'],
      ['试错', '1'],
      ['观察', '5'],
    ],
    highlights: ['低位修复扩散，但强度仍弱于主线。', '适合把观察池更新完整，不适合扩大试错数量。'],
    content: `# MingCang 每日复盘 — 2026-05-15 示例

## 摘要
- 当日信号：7 条
- 可小仓试错：1 条
- 可关注：5 条
- 规避：1 条
- 安全审计：pass

## 机会分层
| 层级 | 数量 | 处理 |
|---|---:|---|
| 主线强势 | 1 | 小仓试错 |
| 低位修复 | 3 | 加入观察 |
| 防守资产 | 2 | 等待确认 |
| 风险标的 | 1 | 规避 |

## 明日检查
1. 主线是否继续放量。
2. 低位修复是否有行业共振。
3. 新闻热度是否能转化为价格确认。`,
    demo: true,
  },
  {
    ...DEMO_REVIEWS.daily,
    id: 'demo-daily-2026-05-14',
    as_of: '2026-05-14',
    summary: '示例：系统记录一次假突破案例，用于后续校准技术分和新闻分权重。',
    metrics: [
      ['信号', '3'],
      ['假突破', '1'],
      ['记忆', '2'],
    ],
    highlights: ['突破后量能不足的案例已写入复盘记忆。', '新闻分较高但技术确认失败，后续需要降低权重。'],
    content: `# MingCang 每日复盘 — 2026-05-14 示例

## 摘要
- 当日信号：3 条
- 假突破案例：1 条
- 写入记忆：2 条
- 安全审计：pass

## 复盘案例
| 股票 | 现象 | 原因 | 后续规则 |
|---|---|---|---|
| 000725 京东方A | 突破失败 | 成交额未放大 | 技术分需要量能确认 |
| 002230 科大讯飞 | 新闻高热 | 价格弱确认 | 新闻分不得单独触发 |

## 规则校准
1. 技术突破必须结合成交额。
2. 新闻催化需要价格确认。
3. 低置信信号只进入观察，不进入试错。`,
    demo: true,
  },
]

function InlineText({ text }) {
  const parts = String(text).split(/(`[^`]+`)/g)
  return parts.map((part, index) => {
    if (part.startsWith('`') && part.endsWith('`')) {
      return <code key={index} className="rounded-sm bg-stone-200 px-1 py-0.5 font-mono text-[0.92em] text-stone-800 dark:bg-slate-800 dark:text-slate-100">{part.slice(1, -1)}</code>
    }
    return <span key={index}>{part}</span>
  })
}

function MarkdownReview({ content, empty }) {
  const blocks = parseMarkdownBlocks(content || '')
  if (!blocks.length) {
    return <div className="p-4 text-sm text-stone-500 dark:text-slate-400">{empty}</div>
  }

  return (
    <div className="space-y-5 p-4 text-sm leading-relaxed text-stone-700 dark:text-slate-300">
      {blocks.map((block, index) => {
        if (block.type === 'h1') {
          return <h1 key={index} className="text-xl font-semibold text-stone-950 dark:text-slate-50"><InlineText text={block.text} /></h1>
        }
        if (block.type === 'h2') {
          return <h2 key={index} className="border-b border-stone-300 pb-2 text-base font-semibold text-stone-950 dark:border-slate-700 dark:text-slate-100"><InlineText text={block.text} /></h2>
        }
        if (block.type === 'h3') {
          return <h3 key={index} className="text-sm font-semibold text-stone-900 dark:text-slate-100"><InlineText text={block.text} /></h3>
        }
        if (block.type === 'ul' || block.type === 'ol') {
          const ListTag = block.type
          return (
            <ListTag key={index} className="space-y-2 pl-5">
              {block.items.map((item) => (
                <li key={item} className={block.type === 'ol' ? 'list-decimal' : 'list-disc'}><InlineText text={item} /></li>
              ))}
            </ListTag>
          )
        }
        if (block.type === 'table') {
          return (
            <div key={index} className="overflow-x-auto rounded-sm border border-stone-300 dark:border-slate-700">
              <table className="min-w-full border-collapse text-left text-xs">
                <thead className="bg-[#f3eddc] text-stone-700 dark:bg-[#161b25] dark:text-slate-200">
                  <tr>
                    {block.headers.map((header) => (
                      <th key={header} className="border-b border-stone-300 px-3 py-2 font-semibold dark:border-slate-700"><InlineText text={header} /></th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {block.rows.map((row, rowIndex) => (
                    <tr key={rowIndex} className="odd:bg-white/30 dark:odd:bg-slate-950/20">
                      {row.map((cell, cellIndex) => (
                        <td key={`${rowIndex}-${cellIndex}`} className="border-b border-stone-200 px-3 py-2 last:border-b-0 dark:border-slate-800"><InlineText text={cell} /></td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )
        }
        return <p key={index}><InlineText text={block.text} /></p>
      })}
    </div>
  )
}

function ReviewCard({ title, item, action, busy }) {
  const metrics = item?.metrics || []
  const highlights = item?.highlights || []
  return (
    <section className={PANEL}>
      <div className="flex items-center justify-between border-b border-stone-300 p-4 dark:border-slate-700">
        <div>
          <div className={LABEL}>{title}</div>
          <div className="mt-1 flex flex-wrap items-center gap-2">
            <h2 className="text-sm font-semibold text-stone-950 dark:text-slate-100">{item?.as_of || '尚未生成'}</h2>
            {item?.demo && <span className="rounded-sm border border-amber-400/60 px-2 py-0.5 text-[10px] font-semibold text-amber-700 dark:text-amber-200">示例数据</span>}
          </div>
        </div>
        <button onClick={action} disabled={busy} className="rounded-sm border border-stone-300 bg-[#f3eddc] px-3 py-1.5 text-xs font-semibold text-stone-700 hover:border-cyan-700 hover:text-cyan-700 disabled:opacity-50 dark:border-slate-700 dark:bg-[#161b25] dark:text-slate-300">
          {busy ? '处理中' : '立即检查'}
        </button>
      </div>
      <div className="p-4 text-sm leading-relaxed text-stone-600 dark:text-slate-300">
        {item?.summary || (
          <span>
            尚未生成复盘。点击「立即检查」让系统判断是否需要生成，或前往{' '}
            <Link to="/" className="text-cyan-700 underline underline-offset-2 dark:text-cyan-300">脉冲页</Link>
            {' '}确认自选股池已有标的后再试。
          </span>
        )}
        {metrics.length > 0 && (
          <div className="mt-4 grid grid-cols-3 gap-3">
            {metrics.map(([label, value]) => (
              <div key={label} className={INSET + ' px-3 py-2'}>
                <div className={LABEL}>{label}</div>
                <div className="mt-1 font-mono text-xl font-semibold text-stone-950 dark:text-slate-50">{value}</div>
              </div>
            ))}
          </div>
        )}
        {highlights.length > 0 && (
          <div className="mt-4 space-y-2">
            {highlights.map((line) => (
              <div key={line} className="border-l-2 border-cyan-700/70 pl-3 text-xs text-stone-600 dark:text-slate-300">{line}</div>
            ))}
          </div>
        )}
        {item?.path && <div className="mt-3 font-mono text-xs text-stone-500 dark:text-slate-400">{item.path}</div>}
      </div>
    </section>
  )
}

export default function ReviewsPage() {
  const [latest, setLatest] = useState({})
  const [items, setItems] = useState([])
  const [busy, setBusy] = useState('')
  const [selected, setSelected] = useState(DEMO_REVIEWS.daily)
  const [detailBusy, setDetailBusy] = useState(false)

  async function load() {
    const [latestData, rows] = await Promise.all([
      getLatestReviews().catch(() => ({})),
      getReviews().catch(() => []),
    ])
    setLatest(latestData)
    setItems(rows)
  }

  async function run(key, fn) {
    setBusy(key)
    try {
      await fn()
      await load()
    } finally {
      setBusy('')
    }
  }

  useEffect(() => {
    Promise.all([
      ensureDailyReview().catch(() => null),
      ensureLongTermReview().catch(() => null),
    ]).finally(load)
  }, [])

  const visibleLatest = {
    daily: latest.daily || DEMO_REVIEWS.daily,
    long_term: latest.long_term || DEMO_REVIEWS.long_term,
  }
  const visibleItems = buildReviewHistory(items, DEMO_HISTORY, 8)

  async function openReview(item) {
    if (item.demo) {
      setSelected(item)
      return
    }
    setDetailBusy(true)
    try {
      setSelected(await getReview(item.id))
    } finally {
      setDetailBusy(false)
    }
  }

  return (
    <div className="space-y-4">
      <div>
        <div className={LABEL}>Reviews</div>
        <h1 className="mt-1 text-2xl font-semibold text-stone-950 dark:text-slate-50">复盘中心</h1>
      </div>
      <div className="grid gap-4 lg:grid-cols-2">
        <ReviewCard title="每日复盘" item={visibleLatest.daily} busy={busy === 'daily'} action={() => run('daily', ensureDailyReview)} />
        <ReviewCard title="长期复盘" item={visibleLatest.long_term} busy={busy === 'long'} action={() => run('long', ensureLongTermReview)} />
      </div>
      <section className={PANEL}>
        <div className="border-b border-stone-300 p-4 dark:border-slate-700">
          <div className={LABEL}>History</div>
          <h2 className="mt-1 text-sm font-semibold text-stone-950 dark:text-slate-100">复盘历史</h2>
        </div>
        <div className="divide-y divide-stone-300 dark:divide-slate-700">
          {visibleItems.map((item) => (
            <button key={item.id} type="button" onClick={() => openReview(item)} className="grid w-full gap-3 p-4 text-left text-sm hover:bg-cyan-700/5 md:grid-cols-[92px_120px_1fr]">
              <span className="font-mono text-stone-500 dark:text-slate-400">{item.as_of}</span>
              <span className={INSET + ' inline-flex w-fit px-2 py-1 text-xs'}>{item.kind === 'daily' ? '每日复盘' : '长期复盘'}{item.demo ? ' · 示例' : ''}</span>
              <span className="text-stone-700 dark:text-slate-300">{item.summary}</span>
            </button>
          ))}
        </div>
      </section>
      <section className={PANEL}>
        <div className="flex items-center justify-between border-b border-stone-300 p-4 dark:border-slate-700">
          <div>
            <div className={LABEL}>Detail</div>
            <h2 className="mt-1 text-sm font-semibold text-stone-950 dark:text-slate-100">
              {selected ? `${selected.kind === 'daily' ? '每日复盘' : '长期复盘'} · ${selected.as_of}` : '复盘详情'}
            </h2>
          </div>
          {detailBusy && <span className="text-xs text-stone-500 dark:text-slate-400">加载中...</span>}
        </div>
        <MarkdownReview
          content={selected?.content}
          empty="点击上方复盘历史条目，可在这里展示当天完整复盘报告。示例数据已预置供参考，真实复盘生成后会自动替换。"
        />
      </section>
    </div>
  )
}
