# Contributing Guide

This guide covers two main extension points: adding a **data provider** and
adding an **agent action**.  Both are designed to be additive — you should
be able to plug in new capabilities without touching production signal logic.

---

## Part 1: Adding a Data Provider

### How the Provider Registry Works

MingCang fetches daily OHLCV price data through a **provider registry**
(`backend/data/providers.py`).  The registry holds an ordered list of
`DailyProvider` objects; when data is requested, MingCang walks the list in
priority order and returns the first successful result.  If a provider fails
or returns empty data, it is placed in a cooldown window and the next provider
is tried.

This is the **fallback chain** pattern: you can add a provider at any priority
level without breaking existing providers.

### Provider Interface

A provider fetch function must match `DailyFetcher`:

```python
def fetch_my_source(symbol: str, days: int) -> pd.DataFrame:
    ...
```

Return contract:

| Situation | What to return |
|---|---|
| Data found | DataFrame with columns: `date` (str "YYYY-MM-DD"), `open`, `high`, `low`, `close`, `volume` |
| Symbol not covered by this source | **Empty** `pd.DataFrame()` — triggers fallback to the next provider |
| Hard error (auth failure, network down) | Raise an exception — recorded as a failure, cooldown starts |

### Registration

Call `register_daily_provider` once at application startup:

```python
from backend.data.providers import register_daily_provider

register_daily_provider(
    name="my_source",        # unique provider name
    markets={"CN"},          # market codes: "CN", "HK", "US", or "ALL"
    fetch=fetch_my_source,   # the callable above
    priority=150,            # lower = tried first; built-ins use 100
    cooldown_seconds=60,     # seconds to pause after a failure
    data_type="daily_price",
    observe_only=False,      # True = never called, shows in health only
)
```

The natural place for this call is in `backend/main.py` inside the `lifespan`
function, after `init_db()`.

### Worked Example

A complete, runnable example lives in `examples/provider_plugin/`:

```
examples/provider_plugin/
    my_provider.py    # fetch function + register() helper
    README.md         # integration steps
```

Run the example standalone (no backend needed):

```bash
PYTHONPATH=. python examples/provider_plugin/my_provider.py
```

### Verifying Your Provider

After registration, inspect the fallback chain:

```bash
PYTHONPATH=. python3 -c "
from backend.data.providers import provider_fallback_chains
import json
print(json.dumps(provider_fallback_chains('CN'), indent=2))
"
```

Or check the health counters after a run:

```bash
PYTHONPATH=. python3 -m backend.agent.cli health --pretty
```

### Index Providers

For index price data (CSI 300, etc.) use `register_index_provider` from the
same module.  The fetch signature is identical; `markets` defaults to `{"CN"}`.

---

## Part 2: Adding an Agent Action

### How the Action Registry Works

The agent action registry (`backend/agent/action_registry.py`) is a static
list of `ActionDefinition` objects.  Each action has:

- a **name** (the string callers use, e.g. `watchlist.add`)
- an **input_schema** (JSON Schema object — validated before the handler runs)
- a **risk_level** (`low`, `medium`, `high`)
- a **requires_confirmation** flag
- **allowed_modes** (`("local",)`, `("local", "remote")`, etc.)
- a **handler** function

The agent CLI exposes actions via:

```bash
# Preview (dry-run): show what would happen
PYTHONPATH=. python3 -m backend.agent.cli action <name> --payload-json '<json>'

# Execute: add --confirm to actually run
PYTHONPATH=. python3 -m backend.agent.cli action <name> --payload-json '<json>' --confirm
```

### List Current Actions

```bash
PYTHONPATH=. python3 -m backend.agent.cli tools
```

This reads `backend/tools/registry.py` and prints all registered tool/action
entrypoints grouped by category (`stable`, `maintenance`, `evidence`, `attic`).

### Dry-Run / Confirm Pattern

Every mutating action in MingCang follows the **dry-run / confirm** pattern:

1. **Without `--confirm`**: the action runs its handler in preview mode.
   The handler should return a description of what it *would* do, without
   making any permanent changes.  This is the default.

2. **With `--confirm`**: the handler runs for real.  This requires an
   explicit flag that the operator must pass — there is no auto-confirm path.

Implement this in your handler by checking a `"dry_run"` key in the payload
(the CLI injects it automatically when `--confirm` is absent):

```python
def handle_my_action(payload: dict, db: object) -> dict:
    dry_run = payload.get("dry_run", True)
    if dry_run:
        return {"status": "dry_run", "would_do": "..."}
    # ... perform real side effects ...
    return {"status": "ok", "done": "..."}
```

### Allowlist and Remote Mode

The security layer (`backend/agent/security.py`) enforces:

- **Local mode** (default): all actions are permitted.  No key required.
- **Remote mode** (`MINGCANG_AGENT_MODE=remote`): all operations require
  `MINGCANG_AGENT_API_KEY`.  Mutating operations additionally require
  `MINGCANG_AGENT_REMOTE_WRITE_ENABLED=true`.
- **Action-level allowlist**: if `MINGCANG_AGENT_REMOTE_WRITE_ACTIONS` is set
  to a comma-separated list, only those action names can be called remotely.

When registering an action that should never be exposed remotely, set
`allowed_modes=("local",)`:

```python
ActionDefinition(
    name="my_action",
    ...
    allowed_modes=("local",),  # local-only; blocked in remote mode
)
```

For an action safe to expose remotely in read mode:

```python
allowed_modes=("local", "remote"),
```

### Adding a New Action: Step-by-Step

**Step 1**: Write the handler function.

```python
def handle_my_action(payload: dict, db: object) -> dict:
    dry_run = payload.get("dry_run", True)
    symbol = payload["symbol"]
    if dry_run:
        return {"status": "dry_run", "symbol": symbol, "would_do": "add to watchlist"}
    # real side effect here
    return {"status": "ok", "symbol": symbol}
```

**Step 2**: Define the `ActionDefinition` and add it to the registry list in
`backend/agent/action_registry.py`:

```python
ActionDefinition(
    name="my_action",
    input_schema={
        "type": "object",
        "required": ["symbol"],
        "properties": {
            "symbol": {"type": "string"},
        },
        "additionalProperties": False,
    },
    risk_level="low",
    requires_confirmation=True,
    allowed_modes=("local",),
    handler=handle_my_action,
),
```

**Step 3**: Add a test in `tests/test_agent_action_registry.py` following the
existing pattern.

**Step 4**: Test dry-run and confirm:

```bash
# Dry-run (default):
PYTHONPATH=. python3 -m backend.agent.cli action my_action \
    --payload-json '{"symbol": "300308"}'

# Execute:
PYTHONPATH=. python3 -m backend.agent.cli action my_action \
    --payload-json '{"symbol": "300308"}' --confirm
```

### Adding a Tool to the Tools Registry

If you are adding a standalone module (not an inline action but a runnable
script under `backend/tools/`), also add a metadata entry to the static
registry in `backend/tools/registry.py`:

```python
{
    "module": "backend.tools.my_tool",
    "category": "stable",          # stable / maintenance / evidence / attic
    "purpose": "One-line description of what this tool does.",
    "read_write_boundary": "Read-only; describe exactly what it reads and what it writes.",
    "recommended_entrypoint": "python3 -m backend.tools.my_tool",
    "still_runnable": True,
},
```

The tools registry is exposed via:

```bash
PYTHONPATH=. python3 -m backend.agent.cli tools
```

---

## Code Style

- Python 3.11, type hints, `from __future__ import annotations`.
- `ruff` for lint and format: `make fmt` and `make lint`.
- `mypy` for type checking: `make typecheck`.
- Tests in `pytest`: `make test`.
- Run `make check` before opening a PR (lint + typecheck + test).

## Boundaries: What Not to Touch

- Production signal weights (`weight_quant`, `weight_technical`,
  `weight_sentiment`) — do not change without evidence.  See
  `docs/evidence/m29_quant_off.md`.
- Scheduler, postmarket, stop-loss, and position-sizing logic — coordinate
  with the project maintainer before modifying.
- The `.env` file — never commit real API keys or personal credentials.
