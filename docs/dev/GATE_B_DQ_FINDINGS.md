# Gate-B Data-Quality Finding: qfq/hfq price contamination

**Status:** diagnosed (read-only, on a copy of production `stock-sage.db`).
The Gate-B tracker is now robust to it; the underlying price data still needs
remediation on the production side (main owns price quality).

## Symptom
~30% (79 / 266) of realized 5-day forward returns were implausible
(`|forward_return_net| > 1.5`), which the hardened `report()` flagged via
`dq_exclusion_rate ≈ 0.297` — sitting just below the 0.30 ABORT threshold.

## Root cause (high confidence)
A batch of **hfq (后复权)** price rows for **~336–344 symbols on 2026-05-25 and
2026-05-26** was ingested into the `prices` table with `adjustment = NULL` and
`source = NULL` — indistinguishable from the surrounding **qfq** rows. The
`prices` table enforces `UNIQUE(symbol, date)` (no adjustment in the key), so each
(symbol, date) slot holds exactly one row; on those two dates that row is the
hfq value (close in the hundreds–thousands) rather than the expected qfq value.

A 5-trading-day forward window for signals dated **2026-05-18 / 2026-05-19** has
its exit land on **2026-05-25 / 2026-05-26**, so a qfq entry is divided by an hfq
exit:

| symbol | entry (qfq) | exit (hfq) | "5-day" return |
|---|---|---|---|
| 000002 万科A | 3.71 | 1225.49 | +329x |
| 000001 平安银行 | 10.86 | 2098.01 | +192x |
| 000651 格力 | 39.71 | 5869.81 | +147x |

All 79 bad rows match this entry(qfq)/exit(hfq) arithmetic exactly. **Zero** were
caused by data gaps, near-zero entries, or anything else. `adjustment` is NULL for
99.95% of rows (847,128 NULL vs 392 qfq vs 108 forward_additive), so the rows
cannot be separated by tag after the fact.

Likely mechanism: `backfill_if_needed` appends only dates strictly after the
latest existing date (when `refresh_today=False`), so legacy hfq rows on those
dates were never overwritten once the qfq pipeline came online.

## Detection query (run against production, read-only)
```sql
-- rows whose close is wildly above the symbol's recent level (hfq contamination)
SELECT symbol, date, close, adjustment, source
FROM prices p
WHERE date IN ('2026-05-25','2026-05-26')
  AND close > 5 * (
    SELECT AVG(close) FROM prices q
    WHERE q.symbol = p.symbol AND q.date < p.date
    ORDER BY q.date DESC LIMIT 10
  );
```

## Mitigation already in place (tracker side, this branch)
`realize_returns` now marks an observation `data_error` (never `realized`) when
the exit/entry ratio is outside `[0.1, 3.0]` (impossible under A-share 5-day
daily limits) or the window spans > 16 calendar days. `report()` keeps a 1.5
plausibility cap as a second layer. On the prod copy this dropped
`dq_exclusion_rate` from 29.7% → 1.06%; the tracker is no longer fooled.

## Recommended production remediation (main — not done here)
1. Delete the contaminated rows: the (symbol, date) pairs on 2026-05-25/26
   identified by the detection query above.
2. Re-fetch those dates with the canonical qfq provider, inserting with explicit
   `adjustment='qfq'` and `source` set.
3. (Robustness) add a write-time data-quality check rejecting `close/prev_close`
   ratios > ~5x on ingest, and consider making `adjustment` part of the prices
   unique key so two bases can never silently collide on one (symbol, date).
4. After remediation, reset the affected Gate-B observations
   (`signal_date IN ('2026-05-18','2026-05-19')`) to `forward_status='pending'`
   and re-run `realize` to recompute them with correct qfq exits.

This aligns with the price-quality-gate work already underway on `main`.
