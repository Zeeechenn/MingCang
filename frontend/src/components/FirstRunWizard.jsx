import { useState } from 'react'
import { Link } from 'react-router-dom'
import { useUiStore } from '../store/uiStore'

/**
 * FirstRunWizard
 *
 * A dismissible modal overlay shown on first visit.  Mount it once inside
 * App.jsx — it renders nothing when the user has already dismissed it.
 *
 * Steps:
 *  1. 选择使用模式
 *  2. 导入 / 创建关注标的（可跳过）
 *  3. 只读研究提示
 *  4. 示例 Review 提示
 *  5. 免责声明确认
 */

const TOTAL_STEPS = 5

const MODE_OPTIONS = [
  { id: 'research', label: 'A股研究', hint: '每日信号、多空辩论、深度研究' },
  { id: 'review', label: '复盘', hint: '每日 / 长期复盘生成与历史回溯' },
  { id: 'watchlist', label: '自选跟踪', hint: '关注池管理与标的走势跟踪' },
  { id: 'demo', label: '只看 demo', hint: '用示例数据了解系统，不录入真实数据' },
]

const PANEL = 'rounded-sm border border-stone-300/80 bg-[#faf6ec] dark:border-slate-700 dark:bg-[#1d232e]'
const LABEL = 'text-[10px] font-semibold uppercase tracking-[0.2em] text-stone-500 dark:text-slate-400'

function StepDots({ current, total }) {
  return (
    <div className="flex items-center gap-1.5">
      {Array.from({ length: total }, (_, i) => (
        <div
          key={i}
          className={[
            'h-1.5 rounded-full transition-all',
            i < current
              ? 'w-4 bg-cyan-700 dark:bg-cyan-300'
              : i === current
              ? 'w-4 bg-cyan-500 dark:bg-cyan-400'
              : 'w-1.5 bg-stone-300 dark:bg-slate-600',
          ].join(' ')}
        />
      ))}
    </div>
  )
}

function Step1({ mode, onMode }) {
  return (
    <div className="space-y-4">
      <div>
        <div className={LABEL}>第一步</div>
        <h2 className="mt-1 text-base font-semibold text-stone-950 dark:text-slate-50">
          选择使用模式
        </h2>
        <p className="mt-1.5 text-sm text-stone-500 dark:text-slate-400">
          你打算怎样使用 MingCang？选一个最符合的模式，随时可以在配置页切换。
        </p>
      </div>
      <div className="grid gap-2 sm:grid-cols-2">
        {MODE_OPTIONS.map((opt) => (
          <button
            key={opt.id}
            type="button"
            onClick={() => onMode(opt.id)}
            className={[
              'rounded-sm border px-4 py-3 text-left transition',
              mode === opt.id
                ? 'border-cyan-700 bg-cyan-700/10 dark:border-cyan-300 dark:bg-cyan-300/10'
                : 'border-stone-300 bg-[#f3eddc] hover:border-cyan-700 dark:border-slate-700 dark:bg-[#161b25] dark:hover:border-cyan-400',
            ].join(' ')}
          >
            <div className="text-sm font-semibold text-stone-950 dark:text-slate-100">
              {opt.label}
            </div>
            <div className="mt-1 text-xs text-stone-500 dark:text-slate-400">{opt.hint}</div>
          </button>
        ))}
      </div>
    </div>
  )
}

function Step2() {
  return (
    <div className="space-y-4">
      <div>
        <div className={LABEL}>第二步</div>
        <h2 className="mt-1 text-base font-semibold text-stone-950 dark:text-slate-50">
          导入或创建 3 个关注标的
        </h2>
        <p className="mt-1.5 text-sm text-stone-500 dark:text-slate-400">
          在自选股管理里点「添加标的」，或通过 AI 对话说
          <span className="mx-1 rounded-sm bg-stone-200 px-1 py-0.5 font-mono text-xs dark:bg-slate-700">
            "添加自选 300308"
          </span>
          来快速导入。
        </p>
      </div>
      <div className="space-y-2">
        <div className="rounded-sm border border-stone-300 bg-[#f3eddc] px-4 py-3 dark:border-slate-700 dark:bg-[#161b25]">
          <div className="text-sm font-medium text-stone-950 dark:text-slate-100">方式一：脉冲页手动添加</div>
          <div className="mt-1 text-xs text-stone-500 dark:text-slate-400">
            前往{' '}
            <Link to="/" className="text-cyan-700 underline underline-offset-2 dark:text-cyan-300">
              脉冲页
            </Link>
            {' '}→ 自选股管理 → 点击「添加标的」
          </div>
        </div>
        <div className="rounded-sm border border-stone-300 bg-[#f3eddc] px-4 py-3 dark:border-slate-700 dark:bg-[#161b25]">
          <div className="text-sm font-medium text-stone-950 dark:text-slate-100">方式二：AI 对话导入</div>
          <div className="mt-1 text-xs text-stone-500 dark:text-slate-400">
            前往{' '}
            <Link to="/chat" className="text-cyan-700 underline underline-offset-2 dark:text-cyan-300">
              AI 对话
            </Link>
            {' '}，告诉系统你想跟踪哪些标的
          </div>
        </div>
      </div>
      <p className="text-xs text-stone-400 dark:text-slate-500">
        这一步可以跳过，稍后在自选股管理里随时添加。
      </p>
    </div>
  )
}

function Step3() {
  return (
    <div className="space-y-4">
      <div>
        <div className={LABEL}>第三步</div>
        <h2 className="mt-1 text-base font-semibold text-stone-950 dark:text-slate-50">
          跑一次「只读研究」
        </h2>
        <p className="mt-1.5 text-sm text-stone-500 dark:text-slate-400">
          进入任意标的详情页，点击「研究助手」按钮，系统会拉取基本面数据并生成多空论点草稿。
          这次运行只读取数据，不触发信号、不写入持仓。
        </p>
      </div>
      <div className="rounded-sm border border-cyan-700/30 bg-cyan-700/5 px-4 py-3 dark:border-cyan-300/20 dark:bg-cyan-300/5">
        <div className="text-sm font-medium text-cyan-700 dark:text-cyan-300">操作路径</div>
        <ol className="mt-2 space-y-1 text-xs text-stone-600 dark:text-slate-300">
          <li className="flex gap-2"><span className="font-mono font-semibold text-cyan-700 dark:text-cyan-300">1.</span> 在自选股列表里点击任意标的名称</li>
          <li className="flex gap-2"><span className="font-mono font-semibold text-cyan-700 dark:text-cyan-300">2.</span> 进入标的详情页，找到「研究助手」面板</li>
          <li className="flex gap-2"><span className="font-mono font-semibold text-cyan-700 dark:text-cyan-300">3.</span> 点击「生成分析」，等待系统输出摘要和多空论点</li>
          <li className="flex gap-2"><span className="font-mono font-semibold text-cyan-700 dark:text-cyan-300">4.</span> 摘要会保存到研究记忆，供后续复盘引用</li>
        </ol>
      </div>
    </div>
  )
}

function Step4() {
  return (
    <div className="space-y-4">
      <div>
        <div className={LABEL}>第四步</div>
        <h2 className="mt-1 text-base font-semibold text-stone-950 dark:text-slate-50">
          生成一份示例 Review
        </h2>
        <p className="mt-1.5 text-sm text-stone-500 dark:text-slate-400">
          复盘中心会按时间规则自动生成每日和长期复盘。你也可以手动触发一次来感受输出格式。
        </p>
      </div>
      <div className="rounded-sm border border-stone-300 bg-[#f3eddc] px-4 py-3 dark:border-slate-700 dark:bg-[#161b25]">
        <div className="text-sm font-medium text-stone-950 dark:text-slate-100">
          前往{' '}
          <Link to="/reviews" className="text-cyan-700 underline underline-offset-2 dark:text-cyan-300">
            复盘中心
          </Link>
        </div>
        <ul className="mt-2 space-y-1 text-xs text-stone-500 dark:text-slate-400">
          <li>· 点击「每日复盘」卡片的「立即检查」，系统检查今日是否需要生成新复盘</li>
          <li>· 复盘结果包含当日信号明细、多空评论、持仓复核和动作建议</li>
          <li>· 示例数据已预置，可先浏览格式，真实数据生成后自动替换</li>
        </ul>
      </div>
    </div>
  )
}

function Step5() {
  return (
    <div className="space-y-4">
      <div>
        <div className={LABEL}>第五步 · 重要</div>
        <h2 className="mt-1 text-base font-semibold text-stone-950 dark:text-slate-50">
          这不是投资建议
        </h2>
      </div>
      <div className="space-y-3 rounded-sm border border-amber-400/50 bg-amber-400/5 px-4 py-4 dark:border-amber-300/30 dark:bg-amber-300/5">
        <p className="text-sm leading-relaxed text-stone-700 dark:text-slate-300">
          MingCang 是一个<strong className="font-semibold text-stone-950 dark:text-slate-100">个人研究辅助工具</strong>，
          帮助你<strong className="font-semibold">记录和反驳</strong>自己的投资判断。
        </p>
        <ul className="space-y-2 text-sm text-stone-600 dark:text-slate-300">
          <li className="flex gap-2">
            <span className="mt-0.5 text-amber-600 dark:text-amber-300">▲</span>
            系统输出的信号、建议和研究摘要<strong>不构成投资建议</strong>，不自动触发任何交易。
          </li>
          <li className="flex gap-2">
            <span className="mt-0.5 text-amber-600 dark:text-amber-300">▲</span>
            所有买卖决策<strong>由你本人做出并承担结果</strong>，系统只帮你整理信息和挑战论点。
          </li>
          <li className="flex gap-2">
            <span className="mt-0.5 text-amber-600 dark:text-amber-300">▲</span>
            数据可能存在延迟、缺失或偏差，使用前请在数据健康页确认数据状态。
          </li>
        </ul>
      </div>
      <p className="text-xs text-stone-400 dark:text-slate-500">
        点击「完成」即表示你了解以上内容，开始使用 MingCang 辅助研究系统。
      </p>
    </div>
  )
}

export default function FirstRunWizard() {
  const { wizardDismissed, dismissWizard } = useUiStore()
  const [step, setStep] = useState(0)
  const [mode, setMode] = useState('')

  // Render nothing if already dismissed — safe default for SSR/test environments.
  if (wizardDismissed) return null

  const isFirst = step === 0
  const isLast = step === TOTAL_STEPS - 1

  function prev() {
    setStep((s) => Math.max(0, s - 1))
  }

  function next() {
    if (isLast) {
      dismissWizard()
    } else {
      setStep((s) => s + 1)
    }
  }

  const stepContent = [
    <Step1 key="s1" mode={mode} onMode={setMode} />,
    <Step2 key="s2" />,
    <Step3 key="s3" />,
    <Step4 key="s4" />,
    <Step5 key="s5" />,
  ]

  return (
    /* Backdrop */
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-stone-950/60 p-4 backdrop-blur-sm dark:bg-slate-950/70"
      role="dialog"
      aria-modal="true"
      aria-label="首次使用引导"
    >
      {/* Modal panel */}
      <div className={`${PANEL} w-full max-w-lg shadow-2xl`}>
        {/* Header */}
        <div className="flex items-center justify-between border-b border-stone-300/80 px-5 py-4 dark:border-slate-700">
          <div>
            <div className={LABEL}>欢迎使用 MingCang</div>
            <div className="mt-1 text-sm font-semibold text-stone-950 dark:text-slate-100">
              快速上手引导
            </div>
          </div>
          <button
            type="button"
            onClick={dismissWizard}
            className="rounded-sm border border-stone-300 px-2.5 py-1 text-xs text-stone-500 hover:border-stone-400 hover:text-stone-700 dark:border-slate-700 dark:text-slate-400 dark:hover:text-slate-200"
            title="跳过引导"
          >
            跳过
          </button>
        </div>

        {/* Step content */}
        <div className="min-h-[260px] px-5 py-5">
          {stepContent[step]}
        </div>

        {/* Footer */}
        <div className="flex items-center justify-between border-t border-stone-300/80 px-5 py-4 dark:border-slate-700">
          <StepDots current={step} total={TOTAL_STEPS} />
          <div className="flex items-center gap-2">
            {!isFirst && (
              <button
                type="button"
                onClick={prev}
                className="rounded-sm border border-stone-300 px-3 py-1.5 text-xs text-stone-600 hover:border-stone-400 dark:border-slate-700 dark:text-slate-300"
              >
                上一步
              </button>
            )}
            <button
              type="button"
              onClick={next}
              className="rounded-sm bg-cyan-700 px-4 py-1.5 text-xs font-semibold text-white hover:bg-cyan-600 dark:bg-cyan-600 dark:hover:bg-cyan-500"
            >
              {isLast ? '完成' : '下一步'}
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}
