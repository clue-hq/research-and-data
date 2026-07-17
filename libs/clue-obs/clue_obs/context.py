"""contextvars binding — the ambient fields stamped on every event.

Bind once at a boundary (a run, a request, a worker slot) and every subsequent
log event within that async/thread context carries the fields automatically via
the ``merge_contextvars`` processor.

The platform's canonical bound-context spine (Doc R §4): ``request_id``,
``workspace_id``, ``project_id``, ``run_id``, ``account_id``, ``actor``
(human | agent | delegated-agent — REQ-20's actor on every line for free), and
the pinned ``profile_version``. Arbitrary extra fields ride ``bind_context``.
"""

from __future__ import annotations

import contextlib
from collections.abc import Iterator
from typing import Any

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


# --- Convenience binders for the canonical platform dimensions ---------------


def bind_request_id(request_id: str) -> None:
    bind_context(request_id=request_id)


def bind_workspace(workspace_id: str) -> None:
    bind_context(workspace_id=workspace_id)


def bind_project(project_id: str) -> None:
    bind_context(project_id=project_id)


def bind_run_id(run_id: str) -> None:
    bind_context(run_id=run_id)


def bind_account(account_id: str) -> None:
    bind_context(account_id=account_id)


def bind_actor(actor: str) -> None:
    """``human`` | ``agent`` | ``delegated-agent`` (REQ-20 actor identity)."""
    bind_context(actor=actor)


def bind_profile_version(profile_version: str) -> None:
    bind_context(profile_version=profile_version)
