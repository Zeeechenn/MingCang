<!-- Thanks for contributing to StockSage. Please fill out the sections below. -->

## Summary

<!-- What does this PR do? One or two sentences. -->

## Why

<!-- Why is this change needed? Link related issue if any: Fixes #123 -->

## Changes

<!-- Bullet list of the key changes. -->

-
-

## Test Plan

<!-- How did you verify this works? -->

- [ ] `PYTHONPATH=. pytest -q` passes locally
- [ ] `cd frontend && npm run build` passes (if frontend changed)
- [ ] Added or updated tests for the changed behavior
- [ ] Manually verified the affected CLI / API / UI path

## Risk / Compatibility

<!-- Any migration, config, or behavior change users should know about? -->

## Checklist

- [ ] Did not commit `.env`, real API keys, local SQLite, or personal
      trading records
- [ ] Respects the project's core trading constraints (ATR-derived stops,
      LLM does not predict prices, position/sector/equity limits)
- [ ] Updated `CHANGELOG.md` / `STATUS.md` / `docs/ROADMAP.md` if the
      milestone state changed
