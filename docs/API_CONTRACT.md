# MingCang REST API Contract — v1.0

All endpoints are mounted under `/api`. The base URL in local development is
`http://localhost:8000/api`.

---

## Versioning and stability intent

This document covers the **stable surface** as of the 1.0 release. Endpoints
listed here are considered public for local tooling, dashboards, and the MCP
agent bridge. No path versioning prefix (e.g. `/v1/`) is used; breaking changes
will be called out in `CHANGELOG.md` and this document will be updated.

Endpoints inside the Atlas research cluster (`/research/theses`,
`/research/themes`, `/research/hypotheses`, etc.) are guarded by the
`atlas_enabled` feature flag and return `503` when the flag is off. They are
documented here for completeness but should be treated as **beta** until Atlas
is promoted.

---

## Correlation tracing

Every response that originates a new ID — or echoes one supplied by the
caller — sets the `X-Correlation-ID` header. The value is a 32-character
lowercase hex UUID fragment generated per request. Callers may inject their own
value; the backend cleans and echoes it. CSV export responses and the HTML
postmarket-review export always include this header. Log lines emitted during
the request are tagged with the same `correlation_id` field via structlog.

---

## Read-only vs write / confirm boundary

| Method | Behaviour |
|---|---|
| `GET` | Always read-only. No side effects. |
| `POST /research/{symbol}/prepare` | Write — adds stock + triggers price backfill. |
| `POST /research/{symbol}/review` | Write — runs LLM signal attribution. |
| `POST /research/{symbol}/copilot` | Write — calls runtime LLM, persists copilot card. |
| `POST /research/deep/run` | Write — fans out LLM + search, persists report. |
| `POST /reviews/daily/ensure` | Write — creates daily review row if due. |
| `POST /reviews/long-term/ensure` | Write — creates long-term review row if due. |
| `POST /positions` | Write — creates manual position. |
| `PATCH /positions/{id}` | Write — updates position fields. |
| `PATCH /positions/{id}/close` | Write — closes position, persists realized PnL. |
| `DELETE /positions/{id}` | Write — soft-closes open position. |
| `DELETE /positions/{id}/closed` | Write — permanently deletes a closed position record. |
| `POST /watchlist` | Write — adds stock to watchlist + triggers backfill. |
| `DELETE /watchlist/{symbol}` | Write — soft-removes stock (sets active=False). |
| `POST /long-term/{symbol}/run` | Write — runs long-term analyst team for one symbol. |
| `POST /long-term/run` | Write — triggers full active-watchlist long-term team (background). |
| `PATCH /system/runtime-config` | Write — updates whitelisted in-process settings. |
| `POST /system/kill-switch/trigger` | Write — activates kill switch. |
| `POST /system/kill-switch/reset` | Write — clears kill switch. |
| `POST /system/initialize` | Write — cold-start: price backfill + financials + signals. |
| `POST /model/train` | Write — triggers LightGBM Alpha retraining in background. |
| `POST /memory/l0/atoms/{id}/promote` | Write, human-gated — promotes L0 atom to trusted. |
| `POST /memory/l0/atoms/{id}/refute` | Write, human-gated — marks L0 atom refuted. |
| `POST /memory/stock-items/{id}/archive` | Write — archives a stock-memory row. |
| `PATCH /memory/stock-items/{id}` | Write — patches status / importance / TTL. |
| `DELETE /memory/stock-items/{id}` | Write — deletes a stock-memory row. |
| `DELETE /memory/{id}` | Write — deletes an ai_memory row. |
| `POST /memory/{id}/pin` | Write — clears TTL so memory row never expires. |
| `PATCH /memory/{id}` | Write — patches ttl_days and/or category. |
| Atlas write paths | Write, feature-flag gated — see Atlas section below. |
| `POST /ai/chat` | Write — appends message, may trigger LLM, streams SSE. |
| `POST /ai/actions/{id}/confirm` | Write — confirms a pending AI action. |

Mutating endpoints in remote agent mode additionally require either the
`X-MingCang-Agent-API-Key` header or `Authorization: Bearer <key>`, validated
by `backend.agent.http_guard.agent_write_guard`. In local mode no key is
required for normal development workflows.

Memory promote/reject paths (`/research/memory-candidates/{id}/promote`,
`/research/memory-candidates/{id}/reject`, `/memory/l0/atoms/{id}/promote`,
`/memory/l0/atoms/{id}/refute`) are **human-gated**: they return `403` in
remote agent mode and require a non-empty `confirmed_by` field in the request
body.

---

## Endpoint reference

### Dashboard

| Method | Path | Description |
|---|---|---|
| GET | `/dashboard/summary` | Read-only cockpit snapshot: system, positions, market overview, coverage, latest signals. Accepts `?as_of=YYYY-MM-DD`. |

### Signals

| Method | Path | Description |
|---|---|---|
| GET | `/signals/{symbol}/latest` | Most recent signal for a symbol. |
| GET | `/signals/{symbol}` | Signal history; `?limit=N` (default 30). |
| GET | `/signals/eval/{symbol}` | Signal accuracy eval over past `?days=N` (default 60). |
| GET | `/signals/{symbol}/evidence` | Recent decision-harness records; `?limit=N` (default 10). |

### Prices

| Method | Path | Description |
|---|---|---|
| GET | `/prices/{symbol}` | OHLCV bars for the past `?days=N` (default 120). |

### Watchlist and long-term labels

| Method | Path | Description |
|---|---|---|
| GET | `/watchlist` | All active watchlist stocks with latest signal and long-term label. |
| POST | `/watchlist` | Add or reactivate a stock. Params: `symbol`, `name`, `market`. Triggers price backfill. |
| DELETE | `/watchlist/{symbol}` | Soft-remove a stock (active=False). |
| GET | `/long-term/{symbol}` | Most recent active long-term label for a symbol. |
| POST | `/long-term/{symbol}/run` | Run long-term analyst team for one symbol. |
| POST | `/long-term/run` | Trigger full active-watchlist long-term team (background). |

### Positions

| Method | Path | Description |
|---|---|---|
| GET | `/positions` | List positions; `?status=open\|closed\|all` (default `open`). |
| POST | `/positions` | Create manual position. |
| PATCH | `/positions/{id}` | Update position fields. |
| PATCH | `/positions/{id}/close` | Close position, persists realized PnL. |
| POST | `/positions/{id}/close` | Alias for the PATCH close path. |
| DELETE | `/positions/{id}` | Soft-close an open position. |
| DELETE | `/positions/{id}/closed` | Permanently delete a closed position record. |

### Stocks

| Method | Path | Description |
|---|---|---|
| GET | `/stocks/search` | Search by symbol or Chinese name; `?q=&market=CN&limit=8`. |

### News

| Method | Path | Description |
|---|---|---|
| GET | `/news/{symbol}` | Recent news items; `?hours=48`. Returns up to 30 items. |

### Reviews

| Method | Path | Description |
|---|---|---|
| GET | `/reviews` | Recent review run records; `?kind=&limit=20`. |
| GET | `/reviews/latest` | Latest daily and long-term review records. |
| GET | `/reviews/{id}` | Single review record with full report content. |
| POST | `/reviews/daily/ensure` | Create today's daily review if due (after 15:00 local). |
| POST | `/reviews/long-term/ensure` | Create long-term review if due (Mon/Fri schedule). |

### Exports

| Method | Path | Description |
|---|---|---|
| GET | `/export/signals.csv` | Signals as UTF-8 BOM CSV; `?symbol=&limit=500`. |
| GET | `/export/positions.csv` | Positions CSV; `?status=open\|closed`. |
| GET | `/export/reviews.csv` | Review runs CSV; `?kind=&limit=200`. |
| GET | `/export/coverage.csv` | Data coverage snapshot as a metric/value CSV. |
| GET | `/export/postmarket-review.html` | Postmarket review HTML (or `?format=word` for .doc); `?as_of=YYYY-MM-DD`. |

All CSV export responses include the `X-Correlation-ID` header and use
UTF-8 BOM encoding for Excel compatibility. Column headers are in Chinese.

### System

| Method | Path | Description |
|---|---|---|
| GET | `/system/health` | Tier-4 health check: DB, data freshness, kill switch, consecutive losses, LLM budget. |
| GET | `/system/status` | DB and long-term label status summary, scheduler state. |
| GET | `/system/data-coverage` | Point-in-time data coverage, freshness, and trust warnings. |
| GET | `/system/runtime-config` | Current editable runtime configuration. |
| PATCH | `/system/runtime-config` | Update whitelisted in-process settings (resets on restart). |
| GET | `/system/external-data-sources` | Catalog of external data sources; `?probe=true` to side-effect-free probe. |
| GET | `/system/global-data` | M41 global data envelope; `?market=CN&symbol=600519&intent=daily_ohlcv`. |
| GET | `/system/llm-usage` | LLM token usage and cost summary; `?days=7`. |
| POST | `/system/kill-switch/trigger` | Manually activate kill switch; `?reason=`. |
| POST | `/system/kill-switch/reset` | Reset an active kill switch. |
| POST | `/system/initialize` | Cold-start: price backfill, financials, disclosure dates, signals. |
| GET | `/system/initialize/status` | Poll cold-start progress (last 20 log lines). |

### Model

| Method | Path | Description |
|---|---|---|
| GET | `/model/status` | LightGBM Alpha model file existence and last-modified time. |
| POST | `/model/train` | Trigger retraining in background. |

### Research (core — always available)

| Method | Path | Description |
|---|---|---|
| GET | `/research/{symbol}` | Persistent research state for a symbol. |
| GET | `/research/{symbol}/dossier` | Unified research dossier (signal, long-term label, evidence, memory). |
| POST | `/research/{symbol}/prepare` | Ensure stock exists, backfill prices/financials, return dossier. |
| POST | `/research/{symbol}/review` | Run LLM attribution review for latest evaluable signal. |
| POST | `/research/{symbol}/copilot` | Generate and persist LLM shadow copilot card. |
| POST | `/research/deep/run` | Fan-out deep research; never creates production signals. |

### Research (Atlas cluster — requires `atlas_enabled=true`)

All paths in this group return `503` unless `ATLAS_ENABLED=true` in `.env`.

| Method | Path | Description |
|---|---|---|
| GET | `/research/{symbol}/adapter-review` | Phase-4 minimal dossier adapter review (read-only). |
| GET | `/research/{symbol}/theses` | List theses for a symbol. |
| GET | `/research/theses/{id}` | Single thesis by id. |
| POST | `/research/{symbol}/theses` | Create thesis. |
| POST | `/research/theses/{id}/status` | Transition thesis status. |
| POST | `/research/theses/{id}/confidence` | Append confidence entry. |
| POST | `/research/theses/{id}/attach-review-case` | Attach review case payload to thesis. |
| GET | `/research/themes` | List all themes. |
| GET | `/research/themes/{id}` | Single theme. |
| POST | `/research/themes` | Create theme. |
| GET | `/research/themes/{id}/hypotheses` | List hypotheses for a theme. |
| GET | `/research/hypotheses/{id}` | Single hypothesis. |
| POST | `/research/themes/{id}/hypotheses` | Create hypothesis (supports `ai_supply_chain` template). |
| POST | `/research/hypotheses/{id}/status` | Transition hypothesis status. |
| POST | `/research/hypotheses/{id}/beneficiary-tiers` | Set advisory beneficiary tiers (display metadata only). |
| POST | `/research/hypotheses/{id}/forward-evidence` | Attach forward evidence. |
| GET | `/research/{symbol}/review-cases` | List review cases. |
| GET | `/research/review-cases/{id}` | Single review case. |
| POST | `/research/{symbol}/review-cases` | Create review case. |
| GET | `/research/memory-candidates` | List memory candidates; filterable by symbol / source_trust / review_case_id. |
| GET | `/research/memory-candidates/{id}` | Single memory candidate. |
| POST | `/research/memory-candidates` | Create memory candidate (source_trust always starts as `pending`). |
| POST | `/research/memory-candidates/{id}/promote` | **Human-gated.** Promote to trusted, materialise StockMemoryItem. |
| POST | `/research/memory-candidates/{id}/reject` | **Human-gated.** Reject candidate. |
| GET | `/research/universe-snapshots` | List universe snapshots (requires `universe_guard_enabled`). |
| GET | `/research/universe-snapshots/by-cutoff` | Nearest snapshot on or before `?cutoff_date=`. |
| GET | `/research/universe-snapshots/{id}` | Single snapshot. |
| GET | `/research/universe-provenance` | Provenance completeness report; `?symbols[]=`. |
| POST | `/research/universe-snapshots` | Create universe snapshot. |
| GET | `/research/{symbol}/forward-theses` | List forward theses. |
| GET | `/research/forward-theses/{id}` | Single forward thesis. |
| POST | `/research/{symbol}/forward-theses` | Create forward thesis (requires `forward_thesis_enabled`). |
| POST | `/research/forward-theses/{id}/status` | Transition forward thesis status. |
| POST | `/research/forward-theses/{id}/confidence-band` | Update confidence band. |
| POST | `/research/forward-theses/{id}/evidence` | Attach evidence manifest. |
| GET | `/research/{symbol}/case-view` | Unified cross-module case view (read-only). |
| POST | `/research/{symbol}/stress-test` | Red-team stress test against ResearchCase. Advisory only; never writes signals. |

### Memory

| Method | Path | Description |
|---|---|---|
| GET | `/memory/overview` | Aggregate counts by scope and category. |
| GET | `/memory/list` | Paginated active ai_memory rows; `?scope=&category=&q=&limit=100`. |
| GET | `/memory/audit` | FTS5 search over audit_log_fts; `?q=&limit=50`. |
| GET | `/memory/layered` | decision_memory_layered rows with content size only. |
| GET | `/memory/l0/context` | Prompt-ready L0 context; filterable by scope_type / scope_key / q. |
| GET | `/memory/l0/atoms` | List L0 memory atoms; filterable by scope_type / scope_key / trust_state / q. |
| POST | `/memory/l0/atoms/{id}/promote` | **Human-gated.** Promote raw/pending/legacy atom to trusted. |
| POST | `/memory/l0/atoms/{id}/refute` | **Human-gated.** Mark atom refuted. |
| GET | `/memory/stock/{symbol}/context` | Prompt-ready structured memory context for one stock. |
| GET | `/memory/stock-items` | List structured stock-memory rows; `?symbol=&type=&status=&q=&limit=100`. |
| POST | `/memory/stock-items/{id}/archive` | Archive a stock-memory row. |
| PATCH | `/memory/stock-items/{id}` | Patch status / importance / TTL. |
| DELETE | `/memory/stock-items/{id}` | Delete a stock-memory row. |
| DELETE | `/memory/{id}` | Delete an ai_memory row by id. |
| POST | `/memory/{id}/pin` | Pin a memory row (clears TTL). |
| PATCH | `/memory/{id}` | Patch ttl_days and/or category. Raw `value` cannot be edited via API. |

### AI chat and actions

| Method | Path | Description |
|---|---|---|
| POST | `/ai/chat` | Stream SSE chat response; body: `AIChatRequest`. |
| GET | `/ai/sessions` | List chat sessions. |
| GET | `/ai/sessions/{id}` | Single session with message history. |
| POST | `/ai/actions/{id}/confirm` | Confirm a pending AI action. |

### Skills

| Method | Path | Description |
|---|---|---|
| GET | `/skills/watch-events` | Recent watchlist change events. |
| POST | `/skills/daily-review` | Manually trigger daily review generation. |

---

## Notes on deprecated / removed aliases

Signal recommendations that were previously `强买`, `买入`, `卖出`, `强卖` are
normalised at the API layer (`_shared.signal_to_schema`) to the current
display strings before returning. Callers should not depend on the raw Chinese
label values.

Runtime-config key `signal_profile` is accepted as an alias for
`paper_trading_profile` and normalised server-side; prefer `paper_trading_profile`
going forward.
