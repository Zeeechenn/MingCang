# StockSage — 路线图（进行中与待做）

> Fresh agents should read this file for current work only. Completed milestone
> detail belongs in `CHANGELOG.md`; architecture navigation belongs in
> `PROJECT.md`; Atlas merge detail belongs in `docs/ATLAS_MERGE.md`.

## 当前接手入口

| 工作线 | 当前状态 | 第一动作 | 停止条件 |
|---|---|---|---|
| M45 研究定位落地 | 当前主线：amplifier-primary, source-gated；tracked docs below are self-contained, while local ADR 0001 stays git-ignored under `docs/adr/` for private follow-up | M45.1: 用 `backend.tools.m45_import_ateacher_theses` 先 dry-run A老师进口判断，再显式 `--execute` 落成 ForwardThesis + L0 pending atom | 不复活 quant、不改 production profile、不让未过门 alpha 影响真实决策 |
| M44 Atlas 合并 | complete locally: dormant `--no-ff` merge landed on local `main` at `9820143`, `ATLAS_ENABLED=false`, not pushed | 保持 dormant；push / publish only after explicit user authorization | 任何 official signal / test2 / scheduler / shared-infra drift 先停下归因或 revert merge |
| M29 Forward Evidence | routine read-only check；所有 alpha 证据仍 non-promoting，fresh forward coverage 尚未 ready | 只读跑 `backend.tools.m29_forward_readiness --db-url ...`；ready 后才追加 1d/3d/5d shadow + ledger | 会恢复 quant、改 production profile、接 checkpoint、写真实 `sentiment_cache` 或调额外付费服务时先确认 |
| 后置/低优先 | M24.3 / M25 / M21.4 / M12 / M10.5 / M4 / M5 | 只在触发条件满足时启动 | 不从历史摘要推出新的生产行为 |

---

## M45 研究定位落地：放大器为主、源受门控【P1】

Decision summary:

- test4 Stage 1 / 2a in `docs/ATLAS_TEST4_EXPERIMENT.md` found no historical edge in the backtestable signal component: technical IC flat/negative, regime signs reversed, quant already `WEIGHT_QUANT=0.0`, and test2 remains too small for promotion evidence.
- Offense / alpha should come from imported human judgment and the user's own filter / veto / sizing, not from manufacturing a price-pattern oracle.
- AI's role is breadth, falsification, and short-term risk discipline. AI-surfaced alpha attempts and trusted-memory promotion must pass forward, outcome-gated falsification before influencing real decisions.
- Atlas L0-L4 implements the loop: import -> record -> falsify -> review -> learn. M29 quant-alpha reset is now one unproven input, not the north star.

Boundaries:

- Keep Atlas dormant by default: `ATLAS_ENABLED=false`.
- Do not change official signals, test2, scheduler, production profile, stops, sizing, or position state.
- ADR 0001 remains local/private under `docs/adr/` and is intentionally git-ignored; tracked docs must carry enough context to stand alone.

### M45.1 进口通道结构化（first action）

- [x] Define and implement a dry-run-first import contract in `backend/tools/m45_import_ateacher_theses.py`: source, as_of, symbol/theme, statement, invalidation conditions, follow-up metrics, review cadence, decision_owner=`human`, trust=`pending`.
- [x] Store the thesis layer through existing Atlas-safe surfaces: `ForwardThesis` for statement / invalidation / evidence manifest plus L0 pending atom for memory context.
- [x] Prepared a local seed input and dry-run output under `/private/tmp/stocksage_m45_ateacher_seed_20260605*.json`; no DB writes were made.
- [x] Add execute-time source fidelity guard: `--execute` requires `source_kind=direct_source`, `source_verified=true`, `source_verified_by`, explicit `source_ref`, and source locator; dry-run surfaces `source_fidelity.execute_blockers`.
- [x] Reviewed and executed the first direct-source seed (`ateacher-20260603-connectivity-mrvl-direct`): `ForwardThesis` remains `draft`, L0 memory remains `pending`, and production signals / test2 / scheduler were not touched.
- [x] Reviewed remaining local handoff seeds against `/Users/zeeechenn/Desktop/站在光里，未来已来.md`: `300308`, `300502`, and `603986` remain blocked because the direct local source supports sector themes but does not name those companies/symbols.
- [x] Narrowed and executed the AVGO direct-source seed (`ateacher-20260603-connectivity-avgo-direct`) as a Broadcom networking / switching-chip / 1.6T DSP connectivity anchor only; `ForwardThesis` remains `draft`, L0 memory remains `pending`, and broader accelerator/backlog/custom-silicon wording was excluded.
- [x] Execute later imports only after reviewing dry-run output; imported rows remain draft/pending and do not become trusted automatically.
- [ ] Use `backend/research/thesis_ledger.py` only where its thinner `symbol/title/kill_conditions/status` shape is sufficient, or extend it deliberately after tests.
- [ ] Ensure imports are idempotent and do not create trusted memory automatically.
- [ ] A-teacher hook updates should become ledger entries, not markdown-only notes.

### M45.2 放大器证伪记分牌

- [x] Add dry-run-first `backend.tools.m45_falsification_scoreboard`: execute writes ReviewCase rows and optional pending MemoryPromotionCandidate rows only; it does not promote trusted memory or touch official signals / decisions / positions.
- [x] Harden execute preflight: scoreboard execute now refuses missing `ForwardThesis` links or unverified / non-direct source inputs before writing ReviewCase rows.
- [x] Recorded initial `not_due` baselines for the imported MRVL and narrowed AVGO theses after dry-run review; both write only ReviewCase rows and create no pending memory candidates.
- [ ] Invalidation-catch ledger: when a held thesis breaks, record whether the alarm fired before loss materialized or was missed.
- [ ] Defensive-value ledger: compare system-on/off drawdown and loss rate for the short-term risk lane; do not judge this lane by IC.
- [ ] Track breadth hits separately: AI-surfaced, human-adopted theses that later work are slow secondary evidence.
- [x] Route review outcomes through ReviewCase / pending memory-candidate surfaces so trusted promotion remains outcome-gated.

### M45.3 模块三连分诊

- [x] Classify existing modules into breadth / falsification / short-term risk.
- [x] For each kept module, record one primary lane only: breadth = source/import/context expansion; falsification = invalidation checks, review cases, and thesis break alarms; short-term risk = drawdown, stop/take, exposure, and defensive warning support.
- [x] Mark modules that fit none of those buckets as removal or quarantine candidates.
- [x] Quarantine anything that implies autonomous alpha promotion, official-signal mutation, test2 mutation, scheduler behavior drift, or production profile changes.
- [x] Treat A-teacher / jingqi / Piotroski skills as first-class import channels.
- [x] Keep triage as documentation/ownership mapping first; code removal or routing changes require a separate reviewed implementation task.

Module matrix:

| Module / surface | M45 lane | Decision | Boundary |
|---|---|---|---|
| `backend/research/dossier.py`, `deep_research.py`, `research/agents.py` | breadth | keep | Context and candidate expansion only; no official signal writes. |
| `backend/agents/long_term/a_teacher_analyst.py`, `jingqi_analyst.py`, `piotroski_analyst.py` | breadth import channel | keep / reframe | First-class import channels that write `ForwardThesis(draft)` + L0 `pending` only after source/provenance checks. |
| `backend/research/forward_thesis.py`, `review_loop.py`, `stress_test.py`, `backend/tools/m45_*` | falsification | keep | Canonical thesis storage, ReviewCase/outcome gate, and dry-run-first M45 tooling. |
| `backend/tools/m29_*` | falsification | keep as non-promoting evidence | Old alpha evidence remains shadow/provenance input, not the roadmap center. |
| `backend/decision/research_constraints.py`, `backend/agents/risk_manager.py` | short-term risk | keep | Consume only trusted/outcome-gated memory; risk warnings must not manufacture alpha. |
| `backend/research/copilot.py` | breadth / short-term risk | keep shadow-only | Questions and risk prompts only; no official action path. |
| `backend/agents/long_term/team.py` weighted `LongTermLabel` aggregation | quarantine_candidate | legacy display unless re-gated | Decision-coupled label voting must not directly constrain production without outcome gates. |
| `backend/agents/researcher.py` debate path | quarantine_candidate | explicit stress/falsification mode only | Do not use as daily production decision coupling. |
| `backend/research/thesis_ledger.py` | quarantine_candidate / thin falsification | use only when shape fits | Its thin `symbol/title/kill_conditions/status` shape is insufficient for richer imported thesis evidence without deliberate extension and tests. |

### M45.4 Stage 2b forward shadow（slow evidence path）

- [x] Pre-register test4 Stage 2b arms, metrics, failure conditions, sample window, and small-sample handling.
- [x] Arms: baseline/no-thesis, imported-human-thesis shadow, falsification-warning on/off, short-term-risk lane on/off, and breadth-hit secondary tracking; evaluate each as non-promoting shadow evidence only.
- [x] Metrics: invalidation catch rate, missed-break count, defensive drawdown/loss-rate delta, human-adopted breadth hit rate, review latency, and provenance/source-fidelity blockers.
- [x] Failure conditions: unverifiable source lineage, sample too small to interpret, worse drawdown without earlier warning, stale review cadence, or any drift into official signals / test2 / scheduler / production profile.
- [x] Small-sample handling: report counts and confidence qualitatively; do not promote from anecdotal wins, and require explicit user confirmation even after a Stage 2b pass.
- [x] Use M45.1 theses as shadow objects. test2 stays frozen.
- [x] Promotion requires Stage 2b pass plus explicit user confirmation; test4 never changes official signals by itself.

---

## M44 Atlas 合并与 L0-L4 主架构升级【complete locally / dormant】

Current fact pattern:

- Local `main` includes M43 baseline merge `4882d49` and dormant Atlas merge `9820143`.
- Atlas remains off by default via `ATLAS_ENABLED=false` / `settings.atlas_enabled=False`.
- Local `main` has not been pushed.
- Full verification recorded for the readiness / merge package: `make verify`, test2 raw zero diff at `--end 2026-06-05`, DB copy-smoke, dormant-context guard, official-signal fixture, and `git diff --check`.

Still-live boundaries:

- Do not use Atlas behavior in official signals, test2/test3, 标的1, scheduler, postmarket, stop/take, sizing, or production scoring while dormant.
- Shared-infra changes are not protected merely by the dormant flag. Database migrations, runtime schema, dependency/lockfile, scheduler helpers, API helpers, and data-loading helpers still need parity checks.
- If user authorizes push or release, first rerun a lightweight publish gate: `git status`, branch divergence, `git diff --check`, focused dormant/official-signal/test2 smoke, and only then full `make verify` if release quality is needed.
- Revert target remains `9820143` if Atlas merge causes behavior drift; `pre-atlas-m43-baseline` points to `4882d49`.

Post-merge follow-up:

- [ ] Keep M31/M41/M42/M43 mainline capabilities protected.
- [ ] Phase 3-full remains 后置: full legacy adapters/backfill, A-teacher/long-term/topic reports, native ResearchCase / ActionProposal L0 wiring.
- [ ] Push local `main` only after explicit user authorization.

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

- M30 engineering quality convergence.
- M31 cache / provider fallback / rhythm CLI / postmarket exports.
- M41 read-only A/HK/US global data and research facade.
- M42 qfq/hfq contamination guard and remediation.
- M43 architecture boundary hardening.
- M28 research integration.
- M27 alpha evidence closure, not promoted.
- M26 quant/Kronos reassessment, not promoted.
- M0-M25 historical buildout and cleanup.
