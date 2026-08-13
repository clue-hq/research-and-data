"""Closed C0 state-transition graphs for crawl runs, pages, and fetch attempts."""

from __future__ import annotations

from collections.abc import Mapping
from types import MappingProxyType
from typing import TypeVar

from clue_research.official_site.contracts import (
    CrawlPageState,
    CrawlRunStatus,
    FetchAttemptState,
)

StateT = TypeVar("StateT", CrawlRunStatus, CrawlPageState, FetchAttemptState)

RUN_TRANSITIONS: Mapping[CrawlRunStatus, frozenset[CrawlRunStatus]] = MappingProxyType(
    {
        CrawlRunStatus.QUEUED: frozenset(
            {CrawlRunStatus.FAST_ACTIVE, CrawlRunStatus.FAILED, CrawlRunStatus.CANCELLED}
        ),
        CrawlRunStatus.FAST_ACTIVE: frozenset(
            {CrawlRunStatus.FAST_CLOSING, CrawlRunStatus.FAILED, CrawlRunStatus.CANCELLED}
        ),
        CrawlRunStatus.FAST_CLOSING: frozenset(
            {CrawlRunStatus.FAST_COMPLETE, CrawlRunStatus.FAILED, CrawlRunStatus.CANCELLED}
        ),
        CrawlRunStatus.FAST_COMPLETE: frozenset(
            {
                CrawlRunStatus.BACKGROUND_ACTIVE,
                CrawlRunStatus.COMPLETED,
                CrawlRunStatus.FAILED,
                CrawlRunStatus.CANCELLED,
            }
        ),
        CrawlRunStatus.BACKGROUND_ACTIVE: frozenset(
            {CrawlRunStatus.COMPLETED, CrawlRunStatus.FAILED, CrawlRunStatus.CANCELLED}
        ),
        CrawlRunStatus.COMPLETED: frozenset(),
        CrawlRunStatus.FAILED: frozenset(),
        CrawlRunStatus.CANCELLED: frozenset(),
    }
)

PAGE_TRANSITIONS: Mapping[CrawlPageState, frozenset[CrawlPageState]] = MappingProxyType(
    {
        CrawlPageState.DISCOVERED: frozenset(
            {CrawlPageState.QUEUED, CrawlPageState.REFUSED, CrawlPageState.FAILED}
        ),
        CrawlPageState.QUEUED: frozenset(
            {CrawlPageState.LEASED, CrawlPageState.REFUSED, CrawlPageState.FAILED}
        ),
        CrawlPageState.LEASED: frozenset(
            {
                CrawlPageState.QUEUED,
                CrawlPageState.PROVIDER_STARTED,
                CrawlPageState.FAILED,
                CrawlPageState.QUARANTINED,
                CrawlPageState.REFUSED,
            }
        ),
        CrawlPageState.PROVIDER_STARTED: frozenset(
            {
                CrawlPageState.RECONCILIATION_PENDING,
                CrawlPageState.PERSISTENCE_PENDING,
                CrawlPageState.RETRY_WAIT,
                CrawlPageState.FAILED,
                CrawlPageState.QUARANTINED,
                CrawlPageState.REFUSED,
            }
        ),
        CrawlPageState.RECONCILIATION_PENDING: frozenset(
            {
                CrawlPageState.PERSISTENCE_PENDING,
                CrawlPageState.RETRY_WAIT,
                CrawlPageState.QUARANTINED,
            }
        ),
        CrawlPageState.PERSISTENCE_PENDING: frozenset(
            {CrawlPageState.FETCHED, CrawlPageState.QUARANTINED}
        ),
        CrawlPageState.RETRY_WAIT: frozenset(
            {CrawlPageState.QUEUED, CrawlPageState.FAILED, CrawlPageState.QUARANTINED}
        ),
        CrawlPageState.FETCHED: frozenset(),
        CrawlPageState.FAILED: frozenset(),
        CrawlPageState.QUARANTINED: frozenset(),
        CrawlPageState.REFUSED: frozenset(),
    }
)

ATTEMPT_TRANSITIONS: Mapping[FetchAttemptState, frozenset[FetchAttemptState]] = MappingProxyType(
    {
        FetchAttemptState.PREPARED: frozenset(
            {FetchAttemptState.DISPATCHED, FetchAttemptState.FAILED}
        ),
        FetchAttemptState.DISPATCHED: frozenset(
            {
                FetchAttemptState.PROVIDER_SUCCEEDED,
                FetchAttemptState.RETRYABLE_NO_SPEND,
                FetchAttemptState.FAILED,
                FetchAttemptState.SPEND_UNKNOWN,
            }
        ),
        FetchAttemptState.PROVIDER_SUCCEEDED: frozenset(
            {FetchAttemptState.PERSISTED, FetchAttemptState.QUARANTINED}
        ),
        FetchAttemptState.PERSISTED: frozenset(),
        FetchAttemptState.RETRYABLE_NO_SPEND: frozenset(),
        FetchAttemptState.FAILED: frozenset(),
        FetchAttemptState.SPEND_UNKNOWN: frozenset(
            {
                FetchAttemptState.RECONCILED_NO_SPEND,
                FetchAttemptState.RECONCILED_SUCCEEDED,
                FetchAttemptState.QUARANTINED,
            }
        ),
        FetchAttemptState.RECONCILED_NO_SPEND: frozenset(),
        FetchAttemptState.RECONCILED_SUCCEEDED: frozenset(
            {FetchAttemptState.PERSISTED, FetchAttemptState.QUARANTINED}
        ),
        FetchAttemptState.QUARANTINED: frozenset(),
    }
)


def allows_transition(  # noqa: UP047 - mypy still consumes the shared bounded TypeVar cleanly
    graph: Mapping[StateT, frozenset[StateT]], old: StateT, new: StateT
) -> bool:
    """Return whether ``old → new`` is in the frozen graph; self-transitions are not implicit."""

    return new in graph[old]


def transition_manifest() -> dict[str, dict[str, list[str]]]:
    """Stable JSON-ready graph pinned by the canonical C0 fixture."""

    def render(graph: Mapping[StateT, frozenset[StateT]]) -> dict[str, list[str]]:
        return {
            state.value: sorted(next_state.value for next_state in graph[state]) for state in graph
        }

    return {
        "crawl_run": render(RUN_TRANSITIONS),
        "crawl_page": render(PAGE_TRANSITIONS),
        "fetch_attempt": render(ATTEMPT_TRANSITIONS),
    }


__all__ = [
    "ATTEMPT_TRANSITIONS",
    "PAGE_TRANSITIONS",
    "RUN_TRANSITIONS",
    "allows_transition",
    "transition_manifest",
]
