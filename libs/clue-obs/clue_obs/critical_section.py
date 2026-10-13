"""Time a lock-holding database section and log it when it runs long.

Research slowness fix (2026-10-03, spec ``docs/superpowers/specs/
2026-10-03-research-slowness-fixes-design.md`` part 0): the production diagnosis could see that
transactions held shared locks for seconds but not *which code* held them. ``critical_section``
wraps such a section, always measures it, and logs one ``db.critical_section`` event when it took
at least ``CLUE_DB_CRITICAL_SECTION_LOG_MS`` milliseconds (default 500) — quiet in normal
operation, self-naming when slow.
"""

from __future__ import annotations

import os
import time
from collections.abc import Iterator
from contextlib import contextmanager

from clue_obs.config import get_logger

__all__ = ["CRITICAL_SECTION_LOG_MS_ENV", "critical_section", "slow_threshold_ms"]

CRITICAL_SECTION_LOG_MS_ENV = "CLUE_DB_CRITICAL_SECTION_LOG_MS"
_DEFAULT_THRESHOLD_MS = 500.0

log = get_logger("clue_obs.critical_section")


def slow_threshold_ms() -> float:
    """The ``CLUE_DB_CRITICAL_SECTION_LOG_MS`` threshold, for callers timing their own waits."""
    return _threshold_ms()


def _threshold_ms() -> float:
    raw = os.environ.get(CRITICAL_SECTION_LOG_MS_ENV, "").strip()
    if not raw:
        return _DEFAULT_THRESHOLD_MS
    try:
        return float(raw)
    except ValueError:
        return _DEFAULT_THRESHOLD_MS


@contextmanager
def critical_section(name: str, **fields: object) -> Iterator[None]:
    """Measure the wrapped block; log ``db.critical_section`` if it was slow (even if it raised)."""
    started = time.monotonic()
    try:
        yield
    finally:
        held_ms = (time.monotonic() - started) * 1000
        if held_ms >= _threshold_ms():
            log.info("db.critical_section", name=name, held_ms=round(held_ms, 1), **fields)
