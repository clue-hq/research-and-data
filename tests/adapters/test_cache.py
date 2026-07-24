"""M4.3: the content-addressed artifact cache (DB-free).

content_key determinism + separator-safety, the freshness_profile→TTL policy, the freshness check,
and the in-memory store. The cache is the idempotency mechanism that makes a costly fetch /
transcription happen once per ref (substrate §4 / D7).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from clue_core import NormalizedText
from clue_research.adapters import (
    CachedArtifact,
    InMemoryArtifactCache,
    content_key,
    freshness_ttl,
    is_fresh,
)


def test_content_key_is_deterministic_and_separator_safe() -> None:
    assert content_key("firecrawl_site", "https://x.com", None) == content_key(
        "firecrawl_site", "https://x.com", None
    )
    # (a, bc) and (ab, c) must not collide — the NUL separator guards that.
    assert content_key("a", "bc", None) != content_key("ab", "c", None)
    assert content_key("firecrawl_site", "https://x.com", None) != content_key(
        "firecrawl_site", "https://y.com", None
    )


def test_content_key_is_workspace_scoped() -> None:
    # No cross-tenant cache sharing ([B3×research]): the same (source, ref) in different workspaces
    # — and the None public/unscoped lane — are three distinct partitions.
    a = content_key("src", "ref", "ws_a")
    b = content_key("src", "ref", "ws_b")
    n = content_key("src", "ref", None)
    assert len({a, b, n}) == 3


def test_freshness_ttl_maps_profiles_and_defaults() -> None:
    assert freshness_ttl("daily") == timedelta(days=1)
    assert freshness_ttl("weekly") == timedelta(weeks=1)
    assert freshness_ttl("quarterly") == timedelta(days=90)
    # realtime / livecrawl => never cache
    assert freshness_ttl("realtime") == timedelta(0)
    assert freshness_ttl("livecrawl") == timedelta(0)
    # unknown / unset => a conservative default, never an error
    assert freshness_ttl(None) == timedelta(days=1)
    assert freshness_ttl("weird-profile") == timedelta(days=1)


def test_is_fresh_respects_ttl() -> None:
    stored = datetime(2026, 1, 1, tzinfo=UTC)
    entry = CachedArtifact(normalized=NormalizedText(text="t"), stored_at=stored, cost_cents=5)
    # within TTL
    assert is_fresh(entry, timedelta(days=2), now=stored + timedelta(days=1))
    # past TTL
    assert not is_fresh(entry, timedelta(days=2), now=stored + timedelta(days=3))
    # a zero TTL (realtime/livecrawl) is never fresh
    assert not is_fresh(entry, timedelta(0), now=stored)


def test_in_memory_cache_get_put_clear() -> None:
    cache = InMemoryArtifactCache()
    assert cache.get("k") is None
    entry = CachedArtifact(
        normalized=NormalizedText(text="hi"),
        stored_at=datetime(2026, 1, 1, tzinfo=UTC),
        cost_cents=0,
    )
    cache.put("k", entry)
    assert cache.get("k") is entry
    cache.clear()
    assert cache.get("k") is None
