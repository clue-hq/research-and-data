"""Content-addressed artifact cache — a costly fetch/normalize done once per ref (M4.3).

Re-fetching or re-transcribing the same ``ref`` is the most expensive avoidable spend (D7;
transcription/OCR are the costliest non-LLM ops). The cache stores the **normalized text** (the
costly output) keyed by a content hash of ``(source_key, ref)``, so a second ``run_pipeline`` on
the same ref reuses it at **zero** additional cost — the manifest ``freshness_profile`` is the TTL
(a ``realtime`` / ``livecrawl`` source is never cached). The store is a Protocol so production
swaps the in-memory default for Postgres / object storage strictly behind the ``run_pipeline`` seam
(no caller learns where artifacts live).

The cache is **caller-owned** (``run_pipeline`` takes it as a parameter, default off): a per-run
cache instance dedupes within a run and is discarded with it, so there is no hidden process-global
state to leak across runs/tests.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta
from typing import Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict

from clue_core import CostCents, NormalizedText, UtcDatetime


def content_key(source_key: str, ref: str) -> str:
    """A stable content-address for ``(source_key, ref)`` — the cache key (hash of the request)."""
    digest = hashlib.sha256()
    digest.update(source_key.encode("utf-8"))
    digest.update(b"\x00")  # unambiguous separator so (a,bc) != (ab,c)
    digest.update(ref.encode("utf-8"))
    return digest.hexdigest()


def utc_now() -> datetime:
    """The default clock (injected into ``run_pipeline`` / freshness checks for determinism)."""
    return datetime.now(UTC)


# freshness_profile -> cache TTL. Policy as data (conventions §2): the manifest's profile string
# resolves to a TTL. ``realtime`` / ``livecrawl`` => TTL 0 => never served from cache (every call
# re-fetches, e.g. the tier-2 official-site livecrawl). Unknown/None => a conservative 1 day.
_FRESHNESS_TTL: dict[str, timedelta] = {
    "realtime": timedelta(0),
    "livecrawl": timedelta(0),
    "hourly": timedelta(hours=1),
    "daily": timedelta(days=1),
    "weekly": timedelta(weeks=1),
    "monthly": timedelta(days=30),
    "quarterly": timedelta(days=90),
}
_DEFAULT_TTL = timedelta(days=1)


def freshness_ttl(freshness_profile: str | None) -> timedelta:
    """The cache TTL for a manifest ``freshness_profile`` (a 0 TTL means "never cache")."""
    if freshness_profile is None:
        return _DEFAULT_TTL
    return _FRESHNESS_TTL.get(freshness_profile, _DEFAULT_TTL)


class CachedArtifact(BaseModel):
    """One cache entry: the normalized text, when it was stored, and what producing it cost (so a
    cache hit can report a zero re-incur)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    normalized: NormalizedText
    stored_at: UtcDatetime
    cost_cents: CostCents
    # The durable snapshot key of the fetch this entry came from (PB-B2.3): a cache *hit* re-stamps
    # the original's artifact ref onto its claims instead of losing it (no bytes are re-fetched on
    # a hit, so this is the only way a hit's claims keep offline-resolvable evidence). None when
    # the entry predates snapshotting or no sink was active.
    artifact_key: str | None = None


def is_fresh(entry: CachedArtifact, ttl: timedelta, *, now: datetime) -> bool:
    """Whether a cache entry is still within its TTL (a non-positive TTL is never fresh)."""
    if ttl <= timedelta(0):
        return False
    return now - entry.stored_at < ttl


@runtime_checkable
class ArtifactCache(Protocol):
    """The swappable artifact store (in-memory default; Postgres / object storage in production)."""

    def get(self, key: str) -> CachedArtifact | None: ...

    def put(self, key: str, entry: CachedArtifact) -> None: ...


class InMemoryArtifactCache:
    """A process-local dict cache — the dev/CI default and a per-run cache for production."""

    def __init__(self) -> None:
        self._store: dict[str, CachedArtifact] = {}

    def get(self, key: str) -> CachedArtifact | None:
        return self._store.get(key)

    def put(self, key: str, entry: CachedArtifact) -> None:
        self._store[key] = entry

    def clear(self) -> None:
        self._store.clear()
