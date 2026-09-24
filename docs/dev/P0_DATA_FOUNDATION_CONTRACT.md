# P0 data foundation and maintenance contract

Task-scoped acceptance details for queue item 2 in [ROADMAP](../ROADMAP.md).
Current source/runtime facts remain in [STATUS](../../STATUS.md). This is not
write approval or a separate queue.

## Coverage and point-in-time facts

First cover the official pool and **current actual holdings** together. Financial
facts and factors share an `as_of`; report period, disclosure time, fetch time and
revision time remain distinct. Unknown disclosure blocks use. Labels retain
generation, validity and quality; unknown, not-applicable and negative remain
distinct with explainable denominators. Required evidence that cannot fit the text
budget means “cannot judge”. Unknown account state cannot justify a larger numeric
target. Drafts remain pending; strict candidates do not establish default wiring.

Classify source/price evidence as consistent multi-source, conflict, true rebase,
or unknown. The 09-17 public-data authorization covered 26 symbols and 200 total
requests; 72 were used. Results: 21/26 complete TickFlow candidates, 26/26
unadjusted daily-line controls, one independent qfq candidate. Five TickFlow gaps,
four denied financial APIs, corporate-action one-per-hour limits, and the official
volume contract remain unresolved. Do not retry, buy an upgrade, or repeat a
successful query. The 09-24 single approved `603986 search_news` request for
09-21–23, size 5, confirmed iFinD account quota exhaustion with answer-only output;
no notice request or retry. Plan tier and refresh date remain unknown. Do not send
further iFinD requests under that approval. A query authorization is not production
write authorization.

## Reviewed 09-23 drift scope

The immutable 09-23 final snapshot and committed panel identify same-source
blockers for `002409` (7/7 overlapping rows, roughly -0.34 additive offset,
09-11 through 09-21) and `688525` (one divergent 09-11 bar out of seven).
Both were consumed by the same-day broad scan; `688525` also entered deep review.
Their absence from the official 25-stock batch does not establish a false alarm.
The panel metric is day-wide; do not narrow its scope to clear a failed run.

### 09-24 bounded repair evidence

Fresh Sina source-native raw bars and QFQ factors now cover every stored date:
`002409` 1,389 rows (2021-01-04..2026-09-23), `688525` 905 rows
(2022-12-30..2026-09-23). Candidate CSV SHA-256 is
`a57a2f38af500ace86e99db46f4d95d2c9c90f724dadbcc87fa405805e24552e`.
Issuer notices [2026-039](https://file.finance.sina.com.cn/211.154.219.97:9494/MRGG/CNSESZ_STOCK/2026/2026-9/2026-09-15/12600545.PDF)
and [2026-084](https://file.finance.sina.com.cn/211.154.219.97:9494/MRGG/CNSESH_STOCK/2026/2026-9/2026-09-12/12597397.PDF)
confirm cash dividends of CNY 0.35/0.4242 per share, ex-dates 09-22/09-18.
The pre-ex raw closes and dividend terms reproduce both Sina factor changes.
The apparent single-bar 688525 mismatch was not proof of a provider correction:
its recently refreshed rows already use the new basis while older rows differ.

Independent Tushare raw OHLC and volume match all 17 recent dates per symbol
(09-01..23), converting its documented hands to Sina shares. This is recent-window
validation, not full-history independent validation. Of 17 normalized 002409
Tushare closes, 15 match the Sina candidate to cents; factor/rounding differences
are retained. The 688525 factor request returned 40203 and was not retried.
There are 46 stored TickFlow rows with a roughly 100x volume discrepancy; the
candidate preserves source-native Sina volume rather than applying a guessed
conversion to old rows. Full historical action/PIT certification remains absent.

An isolated `run_rebase` rehearsal replaced the 2,294 rows, passed SQLite integrity
checks, preserved all 63 non-price tables and unrelated-symbol prices, and restored
logically identically from backup. Neither symbol has a position row in the
snapshot. Existing signals, panels, ledger and NAV were not recalculated.
Latest ATR (stored / recomputed old OHLC / candidate OHLC): `002409`
4.8584 / 7.0314 / 7.0158; `688525` 6.4821 / 11.0762 / 11.0435.
Thus the large stored-ATR discrepancy predates this candidate; the candidate
changes consistently recomputed ATR by about -0.22%/-0.30%. The exact original
write-time input is not established; downstream signal/stop/NAV impact is not
certified by unchanged stored tables.

Default refresh still permits mixed bases and short-window ATR recomputation.
Strict guard alone does not provide warmup. The market facade now exposes the
existing 240-row warmup opt-in, with integration tests covering unchanged write
dates and rejection before mutation. Routine callers still do not enable it. A
one-time rebase is not a durable fix until guarded refresh activation is reviewed.
`run_rebase` deliberately permits temporary databases only. Production needs a
separate reviewed maintenance operation; do not bypass that restriction or clear
old failed panels. Review receipts and scripts are external under
`mingcang-price-resolution-20260924/` in the Codex workspace (source, independent
checks, rehearsal, ATR impact and recurrence review). Production is unchanged.

## Write and replay gates

P0-B1 strict/warmup remains opt-in and routine callers unchanged. P0-B2 writes
require separate explicit approval, immutable backup, reviewed coverage/impact,
maintenance window, rollback and owner acceptance. Warmup must be same-source,
fixed-end, valid OHLC and have sufficient preceding rows. Clearance is not price
repair or write approval.

Only after affected price bases clear and authoritative corporate actions are
complete, use the existing cash NAV to verify cash/position/cost/fill conservation,
next-open, T+1, gaps, halts, volume limits/partial fills, insufficient cash and
corporate actions. Do not create a second return engine or present qfq proxy values
as actual shares.

P0-C wiring needs old-output comparison and current-window protection, plus
counterexamples for future disclosure/label revisions, tiny text budget, unknown
holdings, negative input and empty source. Coverage or ATR/NAV sensitivity is not
write permission or strategy evidence. Any default wiring remains separately
reviewed.
