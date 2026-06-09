# Verification Baseline — 2026-06-06

**Branch:** release/0.3.1-trust-patch  
**Date:** 2026-06-06  
**Purpose:** Pre-change baseline so 0.3.1 regressions can be distinguished from pre-existing state.

---

## Subtarget Results

| Subtarget       | Result | Notes                                                                 |
|-----------------|--------|-----------------------------------------------------------------------|
| `make lint`     | PASS   | ruff check — "All checks passed!" 0 errors, 0 warnings               |
| `make typecheck`| PASS   | mypy — "Success: no issues found in 207 source files"                 |
| `make test`     | PASS   | 1101 passed, 5 skipped, 1 warning in 50.07s                           |
| `make frontend-test` | PASS | 19 tests, 19 pass, 0 fail, 0 skip — duration ~55ms              |
| `make build`    | PASS   | vite v6.4.3 — 62 modules transformed, built in 1.02s                 |

---

## Key Counts

- **Backend test count:** 1101 passed, 5 skipped
- **Frontend test count:** 19 passed, 0 failed

---

## Pre-existing Warnings (Not failures)

- `StarletteDeprecationWarning` in `fastapi/testclient.py`: "Using `httpx` with `starlette.testclient` is deprecated; install `httpx2` instead." — advisory only, does not affect test outcomes.
- 5 backend tests are skipped (pre-existing, not caused by 0.3.1 changes).

---

## Pre-existing Failures

None. All five subtargets returned exit code 0.

---

## Build Artifact Summary

| File                              | Size      | Gzip       |
|-----------------------------------|-----------|------------|
| `dist/index.html`                 | 0.76 kB   | 0.49 kB    |
| `dist/assets/index-7uVEBW6W.css`  | 37.44 kB  | 7.04 kB    |
| `dist/assets/index-Ckd7NWZ9.js`   | 498.07 kB | 150.40 kB  |

---

## Post-0.3.1 Verify

**Date:** 2026-06-06  
**Branch:** release/0.3.1-trust-patch  
**Run by:** VERIFY agent (Claude Sonnet 4.6)

### Subtarget Results

| Subtarget            | Result | Notes                                                                                     |
|----------------------|--------|-------------------------------------------------------------------------------------------|
| `make lint`          | PASS   | ruff check — "All checks passed!" 0 errors, 0 warnings                                   |
| `make typecheck`     | PASS   | mypy — "Success: no issues found in 207 source files"                                     |
| `make test`          | PASS   | 1101 passed, 5 skipped, 1 warning in 51.27s                                               |
| `make frontend-test` | PASS   | 19 tests, 19 pass, 0 fail, 0 skip — duration ~62ms                                        |
| `make build`         | PASS   | vite v6.4.3 — 64 modules transformed (up from 62; new 0.3.1 modules), built in 1.03s     |

### Comparison vs Baseline

| Subtarget            | Baseline      | Post-0.3.1    | Delta            | Regression? |
|----------------------|---------------|---------------|------------------|-------------|
| `make lint`          | PASS (0 err)  | PASS (0 err)  | no change        | No          |
| `make typecheck`     | PASS (207 src) | PASS (207 src) | no change       | No          |
| `make test`          | 1101p / 5s    | 1101p / 5s    | identical        | No          |
| `make frontend-test` | 19p / 0f      | 19p / 0f      | identical        | No          |
| `make build`         | 62 modules    | 64 modules    | +2 (new modules) | No          |

### Post-0.3.1 Build Artifact Summary

| File                              | Size      | Gzip       |
|-----------------------------------|-----------|------------|
| `dist/index.html`                 | 0.76 kB   | 0.49 kB    |
| `dist/assets/index-7uVEBW6W.css`  | 37.44 kB  | 7.04 kB    |
| `dist/assets/index-DD5slcdg.js`   | 498.14 kB | 150.41 kB  |

### Notes

- JS bundle hash changed (`Ckd7NWZ9` → `DD5slcdg`) and module count increased from 62 to 64. This is expected: the 0.3.1 edits added new source modules that Vite picked up. Bundle size delta is negligible (+0.07 kB raw / +0.01 kB gzip).
- The pre-existing `StarletteDeprecationWarning` from `fastapi/testclient.py` is still advisory-only; no test outcomes affected.
- 5 backend skips remain unchanged from baseline.
- No fixes were needed; all subtargets passed on the first run.

### Verdict

**PASS — no regressions vs baseline.** All five subtargets return exit code 0. Backend test count (1101) is equal to baseline. Frontend tests (19/19) unchanged. Lint, typecheck, and build all clean.

---

## Post-0.4–1.0 Follow-up Verify

**Date:** 2026-06-09
**Branch:** feat/0.4-1.0-followups
**Run by:** VERIFY agent (Claude Sonnet 4.6)

### Subtarget Results

| Subtarget            | Result | Notes                                                                                                        |
|----------------------|--------|--------------------------------------------------------------------------------------------------------------|
| `make lint`          | PASS   | ruff check — "All checks passed!" 0 errors, 0 warnings                                                      |
| `make typecheck`     | PASS   | mypy — "Success: no issues found in 226 source files" (+19 vs baseline 207)                                  |
| `make test`          | PASS   | 1115 passed, 5 skipped, 1 warning in 58.22s                                                                  |
| `make frontend-test` | PASS   | 33 tests, 33 pass, 0 fail, 0 skip — duration ~99ms                                                           |
| `make build`         | PASS   | vite v6.4.3 — 75 modules transformed, built in 1.13s                                                        |
| `make reproduce-evidence` | PASS | exit 0; all 5 demo sections printed correctly, production signal profile confirmed (technical 0.6 + sentiment 0.4 + ATR 2.5, WEIGHT_QUANT=0.0) |
| `demo_seed.py`       | PASS   | exit 0; ForwardThesis, ReviewCase, MemoryPromotionCandidate all seeded cleanly                               |

### Comparison vs Baseline (pre-0.3.1)

| Subtarget            | Baseline        | Post-follow-up   | Delta                       | Regression? |
|----------------------|-----------------|------------------|-----------------------------|-------------|
| `make lint`          | PASS (0 err)    | PASS (0 err)     | no change                   | No          |
| `make typecheck`     | PASS (207 src)  | PASS (226 src)   | +19 source files (new code) | No          |
| `make test`          | 1101p / 5s      | 1115p / 5s       | +14 tests                   | No          |
| `make frontend-test` | 19p / 0f        | 33p / 0f         | +14 tests                   | No          |
| `make build`         | 62 modules      | 75 modules       | +13 (new modules)           | No          |

### Post-Follow-up Build Artifact Summary

| File                              | Size      | Gzip       |
|-----------------------------------|-----------|------------|
| `dist/index.html`                 | 0.76 kB   | 0.49 kB    |
| `dist/assets/index-DKcsThTE.css`  | 40.09 kB  | 7.35 kB    |
| `dist/assets/index-DNqZlSAZ.js`   | 526.44 kB | 156.95 kB  |

### Notes

- mypy source file count increased 207 → 226 (+19 files), reflecting new modules added by the 0.4–1.0 follow-up edits.
- Backend test count increased 1101 → 1115 (+14 tests); all skips (5) unchanged from baseline.
- Frontend test count increased 19 → 33 (+14 tests); new tests cover additional store/page/component paths.
- Bundle size grew from 498 kB to 526 kB (+28 kB raw / +6.5 kB gzip) and module count from 64 to 75, consistent with new frontend modules.
- The pre-existing `StarletteDeprecationWarning` from `fastapi/testclient.py` is still advisory-only; no test outcomes affected.
- Both evidence smoke paths (`make reproduce-evidence` and `demo_seed.py`) exit 0 with correct output.
- Production signal behavior confirmed unchanged: technical 0.6 + sentiment 0.4 + ATR 2.5, WEIGHT_QUANT=0.0.
- No fixes were needed; all subtargets passed on the first run.

### Verdict

**PASS — no regressions vs baseline.** All seven subtargets (5 make targets + 2 smoke tests) return exit code 0. Backend test count (1115) exceeds baseline (1101). Frontend tests (33/33) exceed baseline (19/19). Lint, typecheck, and build all clean. Evidence path intact.
