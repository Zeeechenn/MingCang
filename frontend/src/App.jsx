import { useEffect, useState } from 'react'
import { BrowserRouter, Routes, Route, Link } from 'react-router-dom'
import WatchlistPage from './pages/WatchlistPage'
import StockDetailPage from './pages/StockDetailPage'
import AdminPage from './pages/AdminPage'

function Navbar({ theme, onToggleTheme }) {
  return (
    <nav className="sticky top-0 z-20 border-b border-stone-300 bg-[#faf6ec]/95 px-5 py-3 backdrop-blur dark:border-slate-700 dark:bg-[#1d232e]/95">
      <div className="mx-auto flex max-w-[1500px] items-center justify-between gap-4">
        <div className="flex items-center gap-5">
          <Link to="/" className="text-base font-semibold tracking-wide text-slate-950 hover:text-cyan-700 dark:text-slate-100 dark:hover:text-cyan-300">
            StockSage
          </Link>
          <div className="hidden items-center gap-1 text-[11px] font-semibold tracking-[0.18em] text-slate-500 sm:flex">
            <Link to="/" className="hover:text-cyan-700 dark:hover:text-cyan-300">脉冲</Link>
            <span>/</span>
            <Link to="/admin" className="hover:text-cyan-700 dark:hover:text-cyan-300">配置</Link>
            <span>/</span>
            <span>回测</span>
          </div>
        </div>
        <div className="flex items-center gap-3 text-xs text-slate-500">
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
            </Routes>
          </main>
        </div>
      </div>
    </BrowserRouter>
  )
}
