# Provider Plugin Example

This directory contains a minimal, self-contained example of how to add a
custom data provider to MingCang.

## Files

| File | Purpose |
|---|---|
| `my_provider.py` | A standalone example provider with inline documentation |

## How Providers Work

MingCang fetches daily OHLCV price data through a **provider registry** in
`backend/data/providers.py`.  The registry holds an ordered list of providers;
when data is requested, MingCang tries each provider in priority order and
returns the first successful result (fallback chain).

Each provider is a plain Python callable with the signature:

```python
def fetch(symbol: str, days: int) -> pd.DataFrame:
    ...
```

The DataFrame must contain at least these columns:
`date` (str "YYYY-MM-DD"), `open`, `high`, `low`, `close`, `volume`.

Return an **empty** DataFrame when the symbol is not covered by your source.
Raise an exception only for hard errors (network failure, auth failure).

## Integration Steps

**Step 1**: Copy `my_provider.py` into your project (or write a new file).

**Step 2**: Implement `fetch_my_daily` (or equivalent) using your data source.
Keep the return contract: empty DataFrame for missing symbols, real data
otherwise.

**Step 3**: Call `register()` at application startup.  The natural place is in
`backend/main.py` inside the `lifespan` function, after `init_db()`:

```python
# backend/main.py  (inside lifespan, after init_db())
import examples.provider_plugin.my_provider as my_provider
my_provider.register()
```

Or in a dedicated provider-initialisation module that is imported early.

**Step 4**: Verify with the provider health endpoint:

```bash
PYTHONPATH=. python3 -m backend.agent.cli health --pretty
```

The output will list registered providers and their health counters.

**Step 5**: Test your provider in isolation:

```bash
PYTHONPATH=. python examples/provider_plugin/my_provider.py
```

## Priority and Markets

| Parameter | Default | Effect |
|---|---|---|
| `priority` | 100 | Lower = tried first.  Set < 100 to prefer your provider. |
| `markets` | `{"CN"}` | Set of market codes this provider covers.  Use `{"ALL"}` for a universal provider. |
| `cooldown_seconds` | 0 | Seconds to wait after a failure before retrying.  Prevents hammering a failing source. |
| `observe_only` | `False` | If `True`, the provider is never called in the live fallback chain but appears in health reports. |

## Fallback Chain Inspection

```bash
# List all registered daily providers for market CN:
PYTHONPATH=. python3 -c "
from backend.data.providers import provider_fallback_chains
import json
print(json.dumps(provider_fallback_chains('CN'), indent=2))
"
```

## Index Providers

For index price data (e.g. CSI 300), use `register_index_provider` from
`backend/data/providers.py`.  The interface is identical except the function
signature is `fetch(index_symbol: str, days: int) -> pd.DataFrame` and the
`markets` parameter defaults to `{"CN"}`.

## Further Reading

- `backend/data/providers.py` — the full provider registry implementation.
- `backend/data/market.py` — how built-in providers (Tushare, TickFlow) are
  registered.
- `docs_public/CONTRIBUTING_GUIDE.md` — full contributing guide including the
  action registry.
