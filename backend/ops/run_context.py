"""Ambient run context so writers can stamp the owning RunEnvelope.

The job ledger records *that* a tracked run happened; this module makes the
identity of that run visible to the code paths which persist official output,
so a signal row can be bound to exactly one run instead of being matched to a
trade date after the fact.
"""
from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass


@dataclass(frozen=True)
class RunContext:
    """Identity of the tracked run currently executing on this task/thread."""

    run_id: str
    job_name: str
    trigger_source: str
    as_of: str | None = None
    persisted: bool = True


_CURRENT_RUN: ContextVar[RunContext | None] = ContextVar("mingcang_current_run", default=None)


def current_run() -> RunContext | None:
    """Return the tracked run wrapping this call, or None when untracked."""
    return _CURRENT_RUN.get()


def current_run_id() -> str | None:
    """Return the run id of the owning tracked run, or None when untracked.

    Only persisted runs yield an id: a best-effort ledger row that failed to
    persist must not stamp official output with an id no auditor can resolve.
    """
    run = _CURRENT_RUN.get()
    if run is None or not run.persisted:
        return None
    return run.run_id


@contextmanager
def bind_run_context(context: RunContext | None) -> Iterator[RunContext | None]:
    """Bind ``context`` for the duration of the block and restore it afterwards."""
    token = _CURRENT_RUN.set(context)
    try:
        yield context
    finally:
        _CURRENT_RUN.reset(token)
