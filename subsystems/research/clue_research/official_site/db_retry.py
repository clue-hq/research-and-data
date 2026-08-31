"""Narrow PostgreSQL deadlock retry support for repository-sized transactions.

Only SQLSTATE ``40P01`` is retried.  The decorator belongs on methods whose complete body is one
database transaction; it must never wrap provider or artifact I/O.  PostgreSQL aborts the losing
transaction before raising ``40P01``, so re-entering the repository method starts from a clean
transaction and preserves the method's existing idempotency fences.
"""

from __future__ import annotations

import asyncio
import random
from collections.abc import Callable, Coroutine
from functools import wraps
from typing import ParamSpec, TypeVar, cast

from sqlalchemy.exc import DBAPIError

from clue_obs import get_logger

_P = ParamSpec("_P")
_T = TypeVar("_T")

_DEADLOCK_SQLSTATE = "40P01"
_MAX_DEADLOCK_RETRIES = 3
_INITIAL_RETRY_SECONDS = 0.01
_MAX_RETRY_SECONDS = 0.1

log = get_logger("clue_research.official_site.db_retry")


def _privacy_safe_scope(args: tuple[object, ...], kwargs: dict[str, object]) -> dict[str, object]:
    """Extract only durable identifiers/fences; never inspect URLs, bodies, or parameters."""

    fields: dict[str, object] = {}
    for candidate in (*args, *kwargs.values()):
        for name in ("workspace_id", "crawl_run_id", "page_id", "lease_generation"):
            value = getattr(candidate, name, None)
            if value is not None and name not in fields:
                fields[name] = str(value) if name != "lease_generation" else value
    return fields


def database_sqlstate(exc: BaseException) -> str | None:
    """Return a driver SQLSTATE without exposing statement text or bound parameters."""

    pending: list[BaseException] = [exc]
    seen: set[int] = set()
    while pending:
        current = pending.pop()
        if id(current) in seen:
            continue
        seen.add(id(current))
        for attribute in ("sqlstate", "pgcode"):
            value = getattr(current, attribute, None)
            if isinstance(value, str) and value:
                return value
        for nested in (
            getattr(current, "orig", None),
            getattr(current, "__cause__", None),
            getattr(current, "__context__", None),
        ):
            if isinstance(nested, BaseException):
                pending.append(nested)
    return None


def retry_deadlocked_transaction(
    *, stage: str, max_retries: int = _MAX_DEADLOCK_RETRIES
) -> Callable[
    [Callable[_P, Coroutine[object, object, _T]]],
    Callable[_P, Coroutine[object, object, _T]],
]:
    """Retry one transaction-sized async operation after PostgreSQL deadlock victimization."""

    if not stage or max_retries < 0:
        raise ValueError("a stage and non-negative retry count are required")

    def decorate(
        operation: Callable[_P, Coroutine[object, object, _T]],
    ) -> Callable[_P, Coroutine[object, object, _T]]:
        @wraps(operation)
        async def wrapped(*args: _P.args, **kwargs: _P.kwargs) -> _T:
            for retry_index in range(max_retries + 1):
                try:
                    return await operation(*args, **kwargs)
                except DBAPIError as exc:
                    sqlstate = database_sqlstate(exc)
                    if sqlstate != _DEADLOCK_SQLSTATE or retry_index >= max_retries:
                        raise
                    base_delay = min(
                        _MAX_RETRY_SECONDS,
                        _INITIAL_RETRY_SECONDS * (2**retry_index),
                    )
                    delay = base_delay * random.uniform(0.75, 1.25)
                    log.warning(
                        "stage0_official_site.repository_transaction_retry",
                        **_privacy_safe_scope(
                            cast(tuple[object, ...], args),
                            cast(dict[str, object], kwargs),
                        ),
                        repository_stage=stage,
                        sqlstate=sqlstate,
                        retry_number=retry_index + 1,
                        max_retries=max_retries,
                        delay_ms=round(delay * 1000, 3),
                    )
                    await asyncio.sleep(delay)
            raise AssertionError("deadlock retry loop exhausted without returning or raising")

        return cast(Callable[_P, Coroutine[object, object, _T]], wrapped)

    return decorate


__all__ = ["database_sqlstate", "retry_deadlocked_transaction"]
