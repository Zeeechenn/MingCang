# 明仓 / MingCang — 路线图（进行中与待做）

> Fresh agents should read this file for current work only. Completed milestone
> detail belongs in `CHANGELOG.md`; architecture navigation belongs in
> `PROJECT.md`; Atlas merge detail belongs in `docs/ATLAS_MERGE.md`.

## 当前接手入口

| 工作线 | 当前状态 | 第一动作 | 停止条件 |
|---|---|---|---|
| M46 用户可发现性与上手路径 | P1：0.3.1 可信度补丁已完成并通过完整 verify；子 agent 零背景试用发现入口分流、demo 前端、英文 README、功能地图仍需收口 | 先把 GitHub 首页做成极简分流器，再补任务型 `docs/USER_GUIDE.md` 与状态型 `docs/FEATURE_MAP.md` | 不把 README 变成大而全文档；不把维护者路线图当普通用户下一步 |
| M45 研究定位落地 | 主体完成：source-gated importer、falsification scoreboard、模块分诊、Stage 2b shadow 预注册都已落地；后续只保留守门合同 | 后续导入仍先 dry-run + source fidelity review；Stage 2b 只做 non-promoting shadow | 不复活 quant、不改 production profile、不让未过门 alpha 影响真实决策 |
| M44 Atlas 合并 | complete / dormant：`9820143` 已包含在 `origin/main`，`ATLAS_ENABLED=false` | 维持 dormant；任何启用或 Phase 3-full 都走单独任务 | 任何 official signal / test2 / scheduler / shared-infra drift 先停下归因 |
| M29 Forward Evidence | routine read-only check；所有 alpha 证据仍 non-promoting，fresh forward coverage 尚未 ready | 只读跑 `backend.tools.m29_forward_readiness --db-url ...`；ready 后才追加 1d/3d/5d shadow + ledger | 会恢复 quant、改 production profile、接 checkpoint、写真实 `sentiment_cache` 或调额外付费服务时先确认 |
| 后置/低优先 | M24.3 / M25 / M21.4 / M12 / M10.5 / M4 / M5 | 只在触发条件满足时启动 | 不从历史摘要推出新的生产行为 |

---

## M46 用户可发现性与上手路径【P1】

Current fact pattern:

- 0.3.1 trust patch and onboarding fix are complete: A0 baseline, naming/version cleanup, screenshot-backed README preview, `docs/WHY_NOT_AI_STOCK_PICKER.md`, `make demo`, frontend lint summary in `verify`, `mingcang stock`, and bilingual no-key demo path.
- Next product gap from zero-background review: users need a task manual and a capability/status map, not more features or a giant README.

Decision: keep `README.md` / `README_EN.md` as thin GitHub routers; put task walkthroughs in `docs/USER_GUIDE.md`; put capability boundaries and key/provider needs in `docs/FEATURE_MAP.md`; keep architecture/roadmap as depth docs.

Open tasks:

- [ ] Enrich demo data so the first frontend screen does not look like an empty production database: add at least one latest signal / price row if it can be done without touching real data or production providers.
- [x] Create initial `docs/USER_GUIDE.md` project manual draft: quick start, demo cases, feature inventory, frontend/backend guide, AI/data/memory/quant boundaries, and developer extension notes.
- [ ] Review and finalize `docs/USER_GUIDE.md` after user feedback; add screenshots, expected-output snippets, and a 15-minute walkthrough.
- [ ] Create `docs/FEATURE_MAP.md` with capability boundaries and key/provider requirements.
- [ ] Slim README after the two docs exist: keep architecture in the lower half or link out when it distracts from first use.

Stop conditions:

- Do not expose personal trading records, real databases, provider keys, or local-only paths in public docs.
- Do not let demo/sample data affect production DB, scheduler jobs, official signals, or memory promotion.
- Do not move internal Mxx/Atlas/test2 planning into user-facing docs except as clearly marked maintainer context.

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
