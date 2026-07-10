"""contextvars binding — the ambient fields stamped on every event.

Bind once at a boundary (a run, a turn, a request) and every subsequent log
event within that async/thread context carries the fields automatically via the
``merge_contextvars`` processor. This is how ``request_id`` stops being threaded
through every call and how the CLI viewer knows which role/round an event
belongs to.
"""
from __future__ import annotations

import contextlib
from typing import Any, Iterator

import structlog


def bind_context(**fields: Any) -> None:
    """Bind arbitrary fields into the ambient logging context."""
    structlog.contextvars.bind_contextvars(**fields)


def unbind_context(*keys: str) -> None:
    """Remove specific fields from the ambient context."""
    structlog.contextvars.unbind_contextvars(*keys)


def clear_context() -> None:
    """Drop every ambient field (e.g. at the end of a run/request)."""
    structlog.contextvars.clear_contextvars()


@contextlib.contextmanager
def bound_context(**fields: Any) -> Iterator[None]:
    """Scoped binding: fields are bound for the block and restored on exit."""
    tokens = structlog.contextvars.bind_contextvars(**fields)
    try:
        yield
    finally:
        structlog.contextvars.reset_contextvars(**tokens)


# --- Convenience binders for the canonical trace dimensions ---------------


def bind_run_id(run_id: str) -> None:
    bind_context(run_id=run_id)


def bind_turn(turn: int | str) -> None:
    bind_context(turn=turn)


def bind_round(round_: int | str) -> None:
    bind_context(round=round_)


def bind_role(role: str) -> None:
    bind_context(role=role)


def bind_request_id(request_id: str) -> None:
    bind_context(request_id=request_id)
