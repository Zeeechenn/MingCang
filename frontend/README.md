# StockSage Frontend

React 18 + Vite + TailwindCSS + TradingView Lightweight Charts

---

## 开发

```bash
npm install
npm run dev          # 开发服务器 http://localhost:5173
npm run build        # 生产构建
npm run preview      # 预览生产构建
```

后端需同时运行（默认 `http://localhost:8000`）：

```bash
cd ..
PYTHONPATH=. uvicorn backend.main:app --reload
```

---

## 页面结构

| 页面 | 路由 | 说明 |
|------|------|------|
| Watchlist | `/` | 自选股总览，展示所有持仓信号 |
| StockDetail | `/stock/:symbol` | 单股详情：K 线 + 信号 + 新闻 + 复盘卡片 |
| SignalHistory | `/history` | 历史信号列表 |

---

## 关键组件

| 组件 | 说明 |
|------|------|
| `Chart.jsx` | TradingView Lightweight Charts K 线图 |
| `SignalBadge.jsx` | 信号标签（可小仓试错 / 可关注 / 观望 / 规避） |
| `SignalEvalCard.jsx` | 信号复盘卡片：胜率 / 平均次日收益 / 30~180 天窗口切换 |

---

## 环境变量

前端通过相对路径 `/api` 调用后端，无需额外配置。
如需修改后端地址，编辑 `src/api.js` 中的 `BASE_URL`。
