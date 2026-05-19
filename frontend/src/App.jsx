import { useEffect, useState } from 'react'
import { BrowserRouter, Routes, Route, Link, NavLink } from 'react-router-dom'
import WatchlistPage from './pages/WatchlistPage'
import StockDetailPage from './pages/StockDetailPage'
import AdminPage from './pages/AdminPage'
import ReviewsPage from './pages/ReviewsPage'
import PositionsPage from './pages/PositionsPage'
import ChatPage from './pages/ChatPage'

const NAV_ITEMS = [
  ['/', '脉冲', 'Pulse'],
  ['/reviews', '复盘', 'Review'],
  ['/positions', '持仓', 'Position'],
  ['/chat', '聊天', 'AI'],
  ['/admin', '配置', 'Config'],
]

function Navbar({ theme, onToggleTheme }) {
  return (
    <nav className="sticky top-0 z-20 border-b border-stone-300 bg-[#faf6ec]/95 px-4 py-3 backdrop-blur dark:border-slate-700 dark:bg-[#1d232e]/95 sm:px-5">
      <div className="mx-auto flex max-w-[1500px] flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
        <div className="flex min-w-0 items-center gap-4">
          <Link to="/" className="shrink-0 text-base font-semibold tracking-wide text-slate-950 hover:text-cyan-700 dark:text-slate-100 dark:hover:text-cyan-300">
            StockSage
          </Link>
          <div className="flex min-w-0 flex-1 items-center gap-2 overflow-x-auto pb-1 text-xs font-semibold">
            {NAV_ITEMS.map(([to, label, hint]) => (
              <NavLink
                key={to}
                to={to}
                end={to === '/'}
                className={({ isActive }) => [
                  'shrink-0 rounded-sm border px-3 py-2 text-left transition sm:px-4',
                  isActive
                    ? 'border-cyan-700 bg-cyan-700 text-white shadow-[0_0_0_1px_rgba(14,116,144,0.2)] dark:border-cyan-300 dark:bg-cyan-300 dark:text-slate-950'
                    : 'border-stone-300 bg-[#f3eddc] text-stone-700 hover:border-cyan-700 hover:text-cyan-700 dark:border-slate-700 dark:bg-[#161b25] dark:text-slate-300 dark:hover:border-cyan-300 dark:hover:text-cyan-200',
                ].join(' ')}
              >
                <span className="block text-sm leading-none">{label}</span>
                <span className="mt-1 block font-mono text-[10px] uppercase tracking-[0.14em] opacity-70">{hint}</span>
              </NavLink>
            ))}
            <span className="shrink-0 rounded-sm border border-dashed border-stone-300 px-3 py-2 text-left text-stone-400 dark:border-slate-700 dark:text-slate-500 sm:px-4">
              <span className="block text-sm leading-none">回测</span>
              <span className="mt-1 block font-mono text-[10px] uppercase tracking-[0.14em]">Soon</span>
            </span>
          </div>
        </div>
        <div className="flex shrink-0 items-center justify-between gap-3 text-xs text-slate-500 lg:justify-end">
          <div className="hidden items-center gap-2 sm:flex">
            <span className="h-2 w-2 rounded-full bg-emerald-400 shadow-[0_0_12px_rgba(52,211,153,0.7)]" />
            <span>本地优先</span>
          </div>
          <button
            type="button"
            onClick={onToggleTheme}
            className="rounded-sm border border-stone-300 bg-[#f3eddc] px-3 py-1 text-xs font-medium text-stone-700 hover:border-cyan-700 hover:text-cyan-700 dark:border-slate-700 dark:bg-[#161b25] dark:text-slate-300 dark:hover:border-cyan-400 dark:hover:text-cyan-200"
          >
            {theme === 'dark' ? '浅色' : '深色'}
          </button>
        </div>
      </div>
    </nav>
  )
}

export default function App() {
  const [theme, setTheme] = useState(() => localStorage.getItem('stock-sage-theme') || 'dark')

  useEffect(() => {
    document.documentElement.classList.toggle('dark', theme === 'dark')
    document.documentElement.dataset.theme = theme
    localStorage.setItem('stock-sage-theme', theme)
  }, [theme])

  return (
    <BrowserRouter>
      <div className={theme === 'dark' ? 'dark' : ''}>
        <div className="min-h-screen bg-[#efe9dc] text-stone-950 dark:bg-[#161b25] dark:text-slate-100">
          <Navbar theme={theme} onToggleTheme={() => setTheme((v) => (v === 'dark' ? 'light' : 'dark'))} />
          <main className="mx-auto max-w-[1500px] px-4 py-5 sm:px-5">
            <Routes>
              <Route path="/" element={<WatchlistPage />} />
              <Route path="/stock/:symbol" element={<StockDetailPage theme={theme} />} />
              <Route path="/admin" element={<AdminPage />} />
              <Route path="/reviews" element={<ReviewsPage />} />
              <Route path="/positions" element={<PositionsPage />} />
              <Route path="/chat" element={<ChatPage />} />
            </Routes>
          </main>
        </div>
      </div>
    </BrowserRouter>
  )
}
