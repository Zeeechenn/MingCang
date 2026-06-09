# 明仓 / MingCang — 路线图（进行中与待做）

> Fresh agents should read this file for current work only. Completed milestone
> detail belongs in `CHANGELOG.md`; architecture navigation belongs in
> `PROJECT.md`; Atlas merge detail belongs in `docs/ATLAS_MERGE.md`.

## 当前接手入口

| 工作线 | 当前状态 | 第一动作 | 停止条件 |
|---|---|---|---|
| M46.5 正确性底线 | complete：一次性审计已完成，真实库为 warning-only / no blockers；前端关键数字显示已有纯函数测试兜底 | M47 接手常驻化：`mingcang evidence lookahead-check`、lineage / provenance 可见化、UI/export 披露 | warning 不影响正式信号；blocked 仍不得自动 promotion；一次性审计不作为产品入口 |
| M46 用户可发现性与上手路径 | complete：README 保持极简分流器，`docs_public` 已有任务手册 / 功能地图 / walkthrough，demo 首屏有信号、行情和示例持仓 | 后续只按用户反馈补截图或微调导航 | 不把 README 变成大而全文档；不把维护者路线图当普通用户下一步 |
| M45 研究定位落地 | 主体完成：source-gated importer、falsification scoreboard、模块分诊、Stage 2b shadow 预注册都已落地；后续只保留守门合同 | 后续导入仍先 dry-run + source fidelity review；Stage 2b 只做 non-promoting shadow | 不复活 quant、不改 production profile、不让未过门 alpha 影响真实决策 |
| M44 Atlas 合并 | complete / dormant：`9820143` 已包含在 `origin/main`；Atlas/test4 Stage 2b signal-overlay shadow starter 已可用；`ATLAS_ENABLED=false` | 只用 `backend.tools.atlas_test4_stage2b_shadow` 做 non-promoting shadow accrual；exit overlay 另走单独任务 | 任何 official signal / test2 / scheduler / shared-infra drift 先停下归因 |
| M29 Forward Evidence | routine read-only check；所有 alpha 证据仍 non-promoting，fresh forward coverage 尚未 ready | 只读跑 `backend.tools.m29_forward_readiness --db-url ...`；ready 后才追加 1d/3d/5d shadow + ledger | 会恢复 quant、改 production profile、接 checkpoint、写真实 `sentiment_cache` 或调额外付费服务时先确认 |
| 后置/低优先 | M24.3 / M25 / M21.4 / M12 / M10.5 / M4 / M5 | 只在触发条件满足时启动 | 不从历史摘要推出新的生产行为 |

---

## M46 用户可发现性与上手路径【complete】

Current fact pattern:

- 0.3.1 trust patch and onboarding fix are complete: A0 baseline, naming/version cleanup, screenshot-backed README preview, `docs/WHY_NOT_AI_STOCK_PICKER.md`, `make demo`, frontend lint summary in `verify`, `mingcang stock`, and bilingual no-key demo path.
- Next product gap from zero-background review: users need a task manual and a capability/status map, not more features or a giant README.

Decision: keep `README.md` / `README_EN.md` as thin GitHub routers; put task walkthroughs in `docs/USER_GUIDE.md`; put capability boundaries and key/provider needs in `docs/FEATURE_MAP.md`; keep architecture/roadmap as depth docs.

Completed tasks:

- [x] Enrich demo data so the first frontend screen does not look like an empty production database: demo seed now adds sample prices, latest signals, CSI 300 rows, and one demo position without touching real data or production providers.
- [x] Rework public docs into docs-site shape under `docs_public/`: `index.md`, `USER_GUIDE.md`, `FEATURE_MAP.md`, `DEVELOPER_GUIDE.md`, `REFERENCE.md`, and `mkdocs.yml`.
- [x] Create `docs_public/FEATURE_MAP.md` with per-feature explanations, entry points, status, side effects, signal impact, and key/provider requirements.
- [x] Review docs navigation after user feedback; add screenshots, expected-output snippets, and a 15-minute walkthrough.
- [x] Slim README after the two docs exist: README stays as a thin GitHub router and links deeper user/developer docs.

Stop conditions:

- Do not expose personal trading records, real databases, provider keys, or local-only paths in public docs.
- Do not let demo/sample data affect production DB, scheduler jobs, official signals, or memory promotion.
- Do not move internal Mxx/Atlas/test2 planning into user-facing docs except as clearly marked maintainer context.

---

## M46.5 正确性底线：证据不泄漏、前端不误导【complete】

Rationale: M46 improves discoverability (demo, screenshots, walkthrough). For a
project whose value proposition is "evidence you can trust, no AI guessing", a
lookahead leak or a wrong on-screen price/PnL is a foundation-level correctness
defect. These two gates run in parallel with M46 and take precedence when they
conflict.

Completed tasks:

- [x] Lookahead leakage one-time audit (audit first, do NOT build a tool):
  answer the existing-data question — have past signals / memory-promotion
  paths already been contaminated by future data? A one-off script/notebook is
  fine; product-grade CLI is M47, not now.
  - [x] Check whether news / announcement timestamps post-date the signals they
    influenced.
  - [x] Check whether qfq/hfq, restatement, earnings, or provider fallback fed
    future data into backtest / review windows.
  - [x] Check whether any LLM summary used information dated after the signal day.
  - [x] Write the audit conclusion into a tracked doc (ADR 0001 is local /
    git-ignored — do not rely on it as the only record).
- [x] Key financial-number display tests (frontend): price, percentage, position
  size, PnL, date, null/empty, qfq/hfq display. Wrong display destroys trust as
  surely as a leak; this is pulled out of M48 so it is not deferred behind the
  TypeScript migration.

Audit conclusion (2026-06-09, `backend.tools.m46_5_lookahead_one_time_audit`,
read-only immutable SQLite):

- Overall status: `warning`, no `blocked` findings.
- Pass: signal `data_timestamp` did not post-date signal day; every stored
  signal had price data on/before signal day; financial `disclosure_date` was
  not earlier than `report_date`; review cases did not reference future signals;
  no trusted memory-promotion candidate lacked a review case; PIT guards cover
  Price / Signal / LongTermLabel / FinancialMetric / IndexPrice / NewsItem.
- Warning: 501 `signals.date` rows use timestamp-like strings instead of plain
  `YYYY-MM-DD`; 223 sentiment-bearing signals have same-symbol next-day news
  requiring lineage review; 395 financial rows lack exact `disclosure_date`;
  843,391 price rows lack full `source` / `fetched_at` / `adjustment`
  provenance; 2 review cases were created before their `as_of` date and should
  stay non-promoting unless reviewed.
- No signal freeze or memory-promotion pause was triggered because there were no
  blocked findings. Warnings become M47 standing-check / visibility work, not
  automatic production changes.

Acceptance:

- Audit produces a report that clearly separates pass / warning / blocked.
- Any blocked finding freezes the related signal / pauses the matching memory
  promotion BEFORE M46 demo work continues.
- Key display components carry unit tests; a changed API number field surfaces
  at the type or test layer.

Stop conditions:

- warning does not auto-affect production signals; blocked does not auto-trigger
  memory promotion.
- Do not promote the one-time audit into a productized feature here — that is M47.

---

## M47 数据与证据可信度：lookahead 常驻化 + 健康可见【planned / P1】

Trigger: M46.5 audit口径 stable. Goal: turn the one-time leakage audit into a
repeatable gate, and make data trust visible in the UI.

Open tasks:

- [ ] Integrate `mingcang evidence lookahead-check` as a standing CLI that
  re-runs the M46.5 checks on demand and on sample/demo data.
- [ ] Surface data coverage / provider fallback / freshness in the frontend so a
  user can see WHY a signal is or isn't trustworthy.
- [ ] Wire results into data coverage / FEATURE_MAP / review export.
- [ ] Record an explicit open decision: do we ever re-activate the dormant
  "brain" (quant weight, Kronos, Atlas, non-promoted alpha)? This round: NO
  (consistent with non-promoting gates). But log it as a decision, not a default
  drift. The M29 IC/ICIR/monotonic-bucket/fresh-sample gate is the reactivation
  path if it ever happens.

Acceptance:

- lookahead-check runs on demo data and emits pass / warning / blocked.
- warning does not affect production signal; blocked does not trigger promotion.
- Reactivation decision is written down with its gate, not left implicit.

---

## M48 前端可靠性【planned / P1】

WorkBuddy's frontend-weakness判断 still holds even with the TS / Zustand / UI
primitive地基 in place. Key financial-number display tests已提前到 M46.5; M48
carries the rest of frontend hardening.

Open tasks:

- [ ] Type API responses, covering signal / review / position / data coverage first.
- [ ] Extend frontend tests from the current set toward critical user paths.
- [ ] Migrate key pages to TS/TSX; do not attempt a single big-bang migration.
- [ ] Consolidate SignalCard / EvidenceCard / ReviewTable / StatusBadge onto the
  UI primitive library.

Acceptance:

- A changed API field surfaces at the type or test layer.
- No horizontal overflow / hidden critical state on mobile.

---

## M49 工具入口与可观测性【planned / P2】

Tools attic已开始 (`refactor(tools)` 归档零引用脚本)，但还需要系统治理。

Open tasks:

- [ ] Build a tools classification table: stable / maintenance / evidence / attic.
- [ ] Give stable capabilities a unified CLI or doc entry.
- [ ] Annotate historical Mxx scripts: still runnable? read-only? writes DB?
- [ ] Pass `correlation_id` through key pipeline / API / export / memory-candidate
  paths (structlog地基已有).
- [ ] Continue converging runtime patch with Alembic migration discipline.

Acceptance:

- Every retained `backend/tools/` script has a purpose, read/write boundary, and
  recommended entry point.
- A single request / research run is traceable through logs.

---

## M45 研究定位落地：放大器为主、源受门控【complete / guardrails】

Completed summary:

- The direction is settled: 明仓是 human-judgment amplifier, not a price-pattern oracle. AI handles breadth, falsification, and short-term risk discipline; any alpha-like output must remain outcome-gated before it can influence real decisions.
- `backend.tools.m45_import_ateacher_theses` is the canonical dry-run-first importer. Execute requires direct-source fidelity (`source_kind=direct_source`, verified source, explicit `source_ref`, locator) and writes only `ForwardThesis(draft)` plus L0 `pending`.
- `backend.tools.m45_falsification_scoreboard` writes ReviewCase scoreboard events and optional pending promotion candidates; `not_due` rows never create promotion candidates.
- Module ownership is triaged: dossier / deep research / long-term analyst channels are breadth; forward thesis / review loop / stress test / M45 tools are falsification; risk manager surfaces are short-term risk; weighted long-term-label voting remains legacy/quarantine unless re-gated.
- Stage 2b is pre-registered as non-promoting shadow evidence: imported-human-thesis, falsification-warning, short-term-risk, and breadth-hit arms; small samples stay qualitative.

Live contract for future work:

- Later imports still require dry-run review before `--execute`; imported rows remain draft/pending and do not become trusted memory automatically.
- Do not touch official signals, test2, scheduler jobs, production profile, stops, sizing, or position state from M45 tooling.
- Promotion requires forward evidence plus explicit user confirmation; anecdotal wins are not enough.
- ADR 0001 is local/git-ignored, so tracked docs and code comments must carry any conclusion future agents need.

---

## M44 Atlas 合并与 L0-L4 主架构升级【complete / dormant】

Current fact pattern:

- `origin/main` now contains dormant Atlas merge `9820143`; `ATLAS_ENABLED=false` / `settings.atlas_enabled=False`.
- Historical readiness package covered `make verify`, test2 raw zero diff at `--end 2026-06-05`, DB copy-smoke, dormant-context guard, official-signal fixture, and `git diff --check`.
- Keep M31/M41/M42/M43 behavior protected. Phase 3-full remains 后置: legacy adapters/backfill, A-teacher/long-term/topic reports, native ResearchCase / ActionProposal L0 wiring.
- Atlas/test4 Stage 2b has a signal-overlay shadow starter:
  `backend.tools.atlas_test4_stage2b_shadow`. It emits non-promoting artifacts
  under `/private/tmp` by default, leaves `ATLAS_ENABLED=false`, and does not
  mutate `paper_trading/test2_ab_state.json`. Exit-overlay and entry+exit arms
  are registered but not started.

Still-live boundaries: no Atlas behavior in official signals, test2/test3, 标的1, scheduler, postmarket, stop/take, sizing, or production scoring while dormant. Shared-infra changes still need parity checks because the dormant flag does not protect database/runtime/dependency/API helper drift.

---

## M29 Alpha Reset / Forward Evidence Engine【active / non-promoting】

Production remains `new_framework`, `WEIGHT_QUANT=0.0`, Kronos disabled. No candidate has passed the promotion gate:

- IC >= 0.04
- ICIR >= 0.40
- monotonic buckets
- non-overlapping / stride evidence
- sufficient fresh forward sample
- no cache, fallback, provenance, or data-quality blockers
- human confirmation

Current execution:

1. Read `STATUS.md` and this section, then run `git status --short`.
2. First action is read-only: `backend.tools.m29_forward_readiness --db-url ...`.
3. If not ready, stop and wait. Do not treat partial local data as fresh evidence.
4. If ready, run 1d/3d/5d forward shadow bundle and add artifacts to `m29_evidence_ledger`.
5. Update M29.5 residual attribution in the same forward window. If still non-promoting, keep quant off.

Stop before any production change, checkpoint wiring, Kronos long training, true `sentiment_cache` writes, new dependency download, or extra paid external service.

---

## Other Open Items

| Item | Trigger | Action |
|---|---|---|
| M32 Forward Hypothesis Bridge | Review data becomes thick enough | Register sector / supply-chain theses as forward hypotheses; output falsifiable thesis, not Strong Buy labels |
| M24.3 Long-term constraint reconnect | Suggested checkpoint 2026-06-10 and later test2 freeze end >= 2026-07-18 | Shadow-only outcome analysis; enable constraints only if false positives fall without meaningful missed entries |
| M25 product/community leftovers | Low priority / actual need | README demo, verified quickstart, mobile core paths, virtual list only after watchlist >200 causes lag |
| M21.4 ATR narrow-stop analysis | After 2026-07-18 | Analyze closed test1/test2 positions before changing stop rules |
| M12 external data governance | Any new endpoint | Add provider health, PIT timestamp, field normalization, and tests before DB writes |
| M10.5 migrations | SQLite runtime patch becomes bottleneck | Consider Alembic baseline |
| M4 / M5 automation | Strong validated evidence and explicit user intent | LangGraph / FinMem / broker automation stay deferred; no real trades |

---

## Completed Milestones Index

Detailed history is intentionally not repeated here. Read `CHANGELOG.md` for:

- M46 onboarding/demo clarity and user-discovery follow-up.
- M45 source-gated research positioning, importer, scoreboard, and Stage 2b shadow preregistration.
- M44 dormant Atlas L0-L4 merge.
- M30 engineering quality convergence.
- M31 cache / provider fallback / rhythm CLI / postmarket exports.
- M41 read-only A/HK/US global data and research facade.
- M42 qfq/hfq contamination guard and remediation.
- M43 architecture boundary hardening.
- M28 research integration.
- M27 alpha evidence closure, not promoted.
- M26 quant/Kronos reassessment, not promoted.
- M0-M25 historical buildout and cleanup.
