# 明仓前端(v0.4.x · 玻璃拟态高保真)

基于 2026-06 高保真原型(mingcang_frontend_v2)接入后端的正式前端,替换旧版 Tailwind 前端。
旧版实现保留在 Git 历史中。

## 运行

```bash
# 后端(项目根目录)
PYTHONPATH=. .venv/bin/python -m uvicorn backend.main:app --port 8000

# 前端
cd frontend && npm run dev   # http://localhost:5173,/api 代理到 :8000
```

后端不可达时自动落回演示数据,导航栏右上角显示「演示数据」;连上后端显示「本地后端」。

## 架构

- **全局接线风格**:源码沿用原型的 window 全局共享(`Object.assign(window, {...})`),
  `src/boot.js` 把 npm 的 React/ReactDOM 挂到 window,`src/main.jsx` 的 import 顺序即求值顺序:
  boot → data(demo MC_DATA)→ shared(MCStore)→ 各页面 → live。
- **数据层**:
  - `src/data.js` — 演示数据(MC_DATA),也是后端字段缺失时的兜底形状
  - `src/api.js` — 后端 HTTP 客户端(带重试/超时,沿用旧前端)
  - `src/live.js` — 接入层:启动并行预取(自选/持仓/复盘/配置/系统/记忆/覆盖/会话 + 前 30 只股票 K线),
    归一化成 MC_DATA 形状覆写;个股详情(K线/新闻/证据/归因/案卷)按需懒取;
    写操作统一走 `window.MC_LIVE`(live 调后端,demo 时调用方落回演示行为)
- **已接后端的写路径**:自选增删、持仓记录/平仓/删除、复盘 ensure(按钮触发,不再自动写)、
  运行时配置保存、记忆确认/删除、AI 聊天(SSE 流式 + 会话 + 待确认动作 confirm)、报告导出(HTML/CSV)、
  记忆候选 promote/reject(`/research/memory-candidates`)。
- **ATLAS 账本(已接线,随开关自动切换)**:外部论题(ForwardThesis)、论题账本、记忆候选队列、
  CASE_LOOP(case-view)。这些路由挂着 `atlas_dormant_guard`(`config.py` 的 `atlas_enabled`,默认 False):
  开关关闭时接口返回 503,前端自动回落演示内容;开启后无需改前端即显示真实账本(已用
  `ATLAS_ENABLED=true` 本地验证过含 promote/reject 的完整闭环)。开关的开启时机归 ATLAS 门 A/门 B 治理。
- **仍为演示数据的板块**:多空辩论全文、深度研究报告(live 模式下索引里标注「演示 ·」)、
  财务/分析面板、工作流/验证/来源门控展板 —— 后端无落库 API,出现后在 `live.js` 补映射即可。

## 冒烟

```bash
npm run smoke   # 需要 playwright;MC_SMOKE_BASE_URL 可覆盖默认 http://127.0.0.1:5173
```
