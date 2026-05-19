import { useEffect, useState } from 'react'
import { archiveChatSession, chatWithAI, confirmAIAction, createChatSession, getChatMessages, getChatSessions } from '../api'
import { getArchiveState, nextArchiveIntent } from './chatArchive'

const PANEL = 'rounded-sm border border-stone-300/80 bg-[#faf6ec] dark:border-slate-700 dark:bg-[#1d232e]'
const INSET = 'rounded-sm border border-stone-300 bg-[#f3eddc] dark:border-slate-700 dark:bg-[#161b25]'
const LABEL = 'text-[10px] font-semibold uppercase tracking-[0.2em] text-stone-500 dark:text-slate-400'

function normalizeMessage(row) {
  if (row.answer || row.pending_action || row.used_resources) return row
  return {
    role: row.role,
    content: row.content,
    answer: row.role === 'assistant' ? row.content : undefined,
    used_resources: row.used_resources || [],
    pending_action: row.pending_action,
  }
}

export default function ChatPage() {
  const [mode, setMode] = useState('general')
  const [message, setMessage] = useState('')
  const [rows, setRows] = useState([])
  const [sessions, setSessions] = useState([])
  const [activeSession, setActiveSession] = useState(null)
  const [confirmingArchive, setConfirmingArchive] = useState(null)
  const [busy, setBusy] = useState(false)

  async function loadSessions() {
    const data = await getChatSessions().catch(() => [])
    setSessions(data)
    return data
  }

  async function openSession(id) {
    setActiveSession(id)
    const messages = await getChatMessages(id).catch(() => [])
    setRows(messages.map(normalizeMessage))
  }

  async function newSession() {
    const session = await createChatSession({ title: '新对话', mode })
    await loadSessions()
    await openSession(session.id)
  }

  useEffect(() => {
    loadSessions().then((data) => {
      if (data[0]) openSession(data[0].id)
    })
  }, [])

  async function ensureActiveSession() {
    if (activeSession) return activeSession
    const session = await createChatSession({ title: message.trim().slice(0, 18) || '新对话', mode })
    setActiveSession(session.id)
    await loadSessions()
    return session.id
  }

  async function send(e) {
    e.preventDefault()
    if (!message.trim()) return
    const user = { role: 'user', content: message.trim() }
    setRows((v) => [...v, user])
    setMessage('')
    setBusy(true)
    try {
      const sessionId = await ensureActiveSession()
      const res = await chatWithAI({ message: user.content, mode, session_id: sessionId })
      setRows((v) => [...v, { role: 'assistant', ...res }])
      await loadSessions()
    } catch (err) {
      setRows((v) => [...v, { role: 'assistant', answer: err.message }])
    } finally {
      setBusy(false)
    }
  }

  async function confirm(actionId) {
    const result = await confirmAIAction(actionId)
    setRows((v) => [...v, { role: 'assistant', answer: `已执行：${JSON.stringify(result.result || result)}` }])
    await loadSessions()
  }

  async function archiveSession(id) {
    await archiveChatSession(id)
    setConfirmingArchive(null)
    const data = await loadSessions()
    if (activeSession === id) {
      if (data[0]) {
        await openSession(data[0].id)
      } else {
        setActiveSession(null)
        setRows([])
      }
    }
  }

  async function requestArchiveSession(id) {
    const intent = nextArchiveIntent(confirmingArchive, id)
    if (intent.action === 'confirm') {
      setConfirmingArchive(intent.confirmingId)
      return
    }
    setConfirmingArchive(intent.confirmingId)
    await archiveSession(id)
  }

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <div className={LABEL}>AI Copilot</div>
          <h1 className="mt-1 text-2xl font-semibold text-stone-950 dark:text-slate-50">项目对话</h1>
        </div>
        <div className="inline-flex overflow-hidden rounded-sm border border-stone-300 dark:border-slate-700">
          {[
            ['general', '通用助手'],
            ['long_term_team', '长期研究团队'],
          ].map(([id, label]) => (
            <button key={id} type="button" onClick={() => setMode(id)} className={`px-3 py-2 text-xs font-semibold ${mode === id ? 'bg-cyan-700 text-white dark:bg-cyan-400 dark:text-slate-950' : 'text-stone-500 dark:text-slate-400'}`}>
              {label}
            </button>
          ))}
        </div>
      </div>
      <section className={`${PANEL} grid min-h-[680px] min-w-[760px] grid-cols-[280px_minmax(0,1fr)] overflow-hidden`}>
        <aside className="border-r border-stone-300 dark:border-slate-700">
          <div className="flex items-center justify-between border-b border-stone-300 p-4 dark:border-slate-700">
            <div>
              <div className={LABEL}>Windows</div>
              <div className="mt-1 text-sm font-semibold text-stone-950 dark:text-slate-100">对话窗口</div>
            </div>
            <button onClick={newSession} className="rounded-sm bg-cyan-700 px-3 py-1.5 text-xs font-semibold text-white dark:bg-cyan-400 dark:text-slate-950">
              新建
            </button>
          </div>
          <div className="max-h-[620px] overflow-y-auto p-2">
            {sessions.length === 0 ? (
              <div className="p-4 text-sm text-stone-500 dark:text-slate-400">暂无历史窗口</div>
            ) : sessions.map((session) => {
              const archiveState = getArchiveState(session.id, confirmingArchive)
              return (
                <div
                  key={session.id}
                  className={`mb-2 rounded-sm border p-3 ${
                    activeSession === session.id
                      ? 'border-cyan-700 bg-cyan-700/10 dark:border-cyan-300'
                      : 'border-stone-300 bg-[#f3eddc] hover:border-cyan-700 dark:border-slate-700 dark:bg-[#161b25]'
                  }`}
                >
                  <button type="button" onClick={() => openSession(session.id)} className="w-full text-left">
                    <div className="truncate text-sm font-semibold text-stone-950 dark:text-slate-100">{session.title}</div>
                    <div className="mt-1 truncate text-xs text-stone-500 dark:text-slate-400">{session.last_message || '空窗口'}</div>
                  </button>
                  <div className="mt-3 flex flex-wrap items-center gap-2">
                    <button
                      type="button"
                      onClick={() => requestArchiveSession(session.id)}
                      className={`rounded-sm border px-2 py-1 text-xs ${
                        archiveState.isConfirming
                          ? 'border-red-600 bg-red-600 text-white dark:border-red-300 dark:bg-red-300 dark:text-slate-950'
                          : 'border-stone-300 text-stone-500 hover:border-red-600 hover:text-red-700 dark:border-slate-700 dark:text-slate-400 dark:hover:border-red-300 dark:hover:text-red-200'
                      }`}
                    >
                      {archiveState.label}
                    </button>
                    {archiveState.isConfirming && (
                      <button
                        type="button"
                        onClick={() => setConfirmingArchive(null)}
                        className="rounded-sm border border-stone-300 px-2 py-1 text-xs text-stone-500 hover:border-cyan-700 hover:text-cyan-700 dark:border-slate-700 dark:text-slate-400 dark:hover:border-cyan-300 dark:hover:text-cyan-200"
                      >
                        取消
                      </button>
                    )}
                  </div>
                </div>
              )
            })}
          </div>
        </aside>
        <div className="flex min-w-0 flex-col">
          <div className="flex-1 space-y-4 overflow-y-auto p-4">
            {rows.length === 0 && (
              <div className="rounded-sm border border-cyan-700/30 bg-cyan-700/10 p-4 text-sm leading-relaxed text-cyan-900 dark:text-cyan-100">
                每个窗口只继承本窗口上下文；窗口外历史不会进入对话记忆。AI 仍可调取 StockSage 的自选股、持仓、信号、复盘和研究资源。
              </div>
            )}
            {rows.map((row, index) => (
              <div key={row.id || index} className={`max-w-[86%] rounded-sm border p-3 text-sm leading-relaxed ${row.role === 'user' ? 'ml-auto border-cyan-700/40 bg-cyan-700/10 text-stone-900 dark:text-slate-100' : 'border-stone-300 bg-[#f3eddc] text-stone-700 dark:border-slate-700 dark:bg-[#161b25] dark:text-slate-300'}`}>
                <div className="whitespace-pre-wrap">{row.content || row.answer}</div>
                {row.used_resources?.length > 0 && (
                  <div className="mt-2 font-mono text-[10px] text-stone-500 dark:text-slate-500">resources: {row.used_resources.join(', ')}</div>
                )}
                {row.pending_action && (
                  <div className="mt-3 rounded-sm border border-amber-500/40 bg-amber-500/10 p-3">
                    <div className="font-mono text-xs text-amber-800 dark:text-amber-200">{row.pending_action.action}</div>
                    <pre className="mt-2 whitespace-pre-wrap text-[11px] text-stone-600 dark:text-slate-300">{JSON.stringify(row.pending_action.payload, null, 2)}</pre>
                    <button onClick={() => confirm(row.pending_action.id)} className="mt-3 rounded-sm bg-cyan-700 px-3 py-1.5 text-xs font-semibold text-white">确认执行</button>
                  </div>
                )}
              </div>
            ))}
            {busy && <div className="text-sm text-stone-500 dark:text-slate-400">思考中...</div>}
          </div>
          <form onSubmit={send} className="border-t border-stone-300 p-4 dark:border-slate-700">
            <div className="flex gap-2">
              <input value={message} onChange={(e) => setMessage(e.target.value)} placeholder={mode === 'long_term_team' ? '输入：研究 300308' : '向 StockSage 提问或下达项目操作'} className="flex-1 rounded-sm border border-stone-300 bg-[#fffaf0] px-3 py-2 text-sm outline-none focus:border-cyan-700 dark:border-slate-700 dark:bg-[#161b25] dark:text-slate-100" />
              <button disabled={busy} className="rounded-sm bg-cyan-700 px-4 py-2 text-sm font-semibold text-white disabled:opacity-50">发送</button>
            </div>
          </form>
        </div>
      </section>
    </div>
  )
}
