# Data-source audit digest

> Dated evidence from 2026-07-04. Current behavior belongs in
> `docs/data-sources/` and code; re-probe before making time-sensitive provider or
> permission claims.

Two long audit narratives were removed from active `docs/dev/` after their live
contracts were absorbed by the data-source manuals. Full originals remain in the
owner's external governance archive.

| Archived source | SHA-256 | Successor authority |
|---|---|---|
| `DATA_AUDIT_EXTERNAL.md` | `d3964d9921bf071295b1a60f1a8fdcdf6473320194f047379af9691de1bd745e` | `docs/data-sources/akshare.md`, `eastmoney.md`, `tushare.md`, `tickflow.md`, `a-stock-data.md`, `anspire-tavily.md` |
| `DATA_AUDIT_IFIND.md` | `bd5e77634dcf7f9d22c41184b090602b22cc9271ac9ab680966e27e3edf6e854` | `docs/data-sources/ifind.md` |

## Durable findings

- Provider registration is not runtime use. Verify the active provider chain,
  current configuration, ledger and persisted `source`/`adjustment` before
  describing a source as active.
- iFinD production use was limited to `search_news` and `search_notice`; other
  tools were probes or candidates. Natural-language tool results can return
  empty text without a hard error, and QPS/timeout behavior requires explicit
  handling. Historical financial periods do not by themselves prove PIT because
  report period and disclosure time differ.
- TickFlow is a daily-price provider, not a fund-flow source. `FLOW_MISSING` was
  a separate news-fusion integration problem. Provider priority and configured
  availability determine whether TickFlow is actually selected.
- Tushare access observed at the audit date covered basic daily price, adjustment
  factor, daily basic and stock list; higher-value financial/news/event endpoints
  were permission-blocked. Raw unadjusted daily prices must not bypass the qfq
  reconstruction path.
- AkShare exposes many untested functions. Local package introspection and live
  probes outrank generated function-name summaries; a documented function name
  is not evidence that the installed version contains or can call it.
- Eastmoney direct integration was a narrow, undocumented news-search path;
  other `_em` functions generally came through AkShare. Undocumented endpoints
  have no SLA and must retain timeout/retry/fallback evidence.
- Anspire/Tavily are current-search sources, not historical PIT backfill. Tavily
  title-only results are not article-content evidence.

## Reuse rule

Read the relevant source manual first, then verify current code/config and run a
read-only probe where needed. Do not restore the archived narratives to active
context or copy their dated counts into `STATUS.md`.
