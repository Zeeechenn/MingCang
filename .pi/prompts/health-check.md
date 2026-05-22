# Health Check

Run:

```bash
python3 -m backend.agent.cli health --pretty
make coverage-snapshot
```

Report database, memory, watchlist, positions, scheduler/data coverage concerns
and the next maintenance command if something is missing.
