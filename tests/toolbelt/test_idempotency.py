"""``body_sha256`` stability + the Db idempotency store round-trip / TTL / scope (DB-gated)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from clue_toolbelt import DbIdempotencyStore, body_sha256
from tests.db.conftest import run_async
from tests.profiling.conftest import conn_session_factory, rollback_conn

TTL = 3600.0


def test_body_sha256_is_key_order_independent() -> None:
    a = body_sha256({"a": 1, "b": [2, 3]})
    b = body_sha256({"b": [2, 3], "a": 1})
    assert a == b  # canonicalised — a retry is recognised regardless of serialisation


def test_body_sha256_changes_with_content() -> None:
    assert body_sha256({"value": 1}) != body_sha256({"value": 2})


def test_db_store_reserve_complete_lookup_and_ttl(require_profiling_db: None) -> None:
    async def scenario() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            store = DbIdempotencyStore(conn_factory=conn_session_factory(conn))
            now = datetime.now(UTC)

            # Win the reservation, complete it, and read it back within TTL.
            won = await store.reserve(
                "ws_a", "tk1", tool_name="reverse_profile", body_sha256="abc", ttl_s=TTL, now=now
            )
            assert won
            pending = await store.lookup("ws_a", "tk1", ttl_s=TTL, now=now)
            assert pending is not None and pending.status == "pending"
            assert pending.response_json is None
            await store.complete(
                "ws_a",
                "tk1",
                response_json={"tool": "reverse_profile", "version": "1", "references": {"n": 1}},
            )
            got = await store.lookup("ws_a", "tk1", ttl_s=TTL, now=now + timedelta(seconds=10))
            assert got is not None
            assert got.status == "completed"
            assert got.body_sha256 == "abc"
            assert got.tool_name == "reverse_profile"
            assert got.response_json is not None
            assert got.response_json["references"] == {"n": 1}

            # Past TTL: reported absent (re-executable).
            expired = await store.lookup(
                "ws_a", "tk1", ttl_s=TTL, now=now + timedelta(seconds=7200)
            )
            assert expired is None

            # A live row refuses a competing reservation (S4)...
            assert not await store.reserve(
                "ws_a",
                "tk1",
                tool_name="reverse_profile",
                body_sha256="def",
                ttl_s=TTL,
                now=now + timedelta(seconds=10),
            )
            # ...but a TTL-expired row is taken over (a reused key past its TTL is fresh).
            later = now + timedelta(seconds=8000)
            assert await store.reserve(
                "ws_a", "tk1", tool_name="reverse_profile", body_sha256="def", ttl_s=TTL, now=later
            )
            refreshed = await store.lookup("ws_a", "tk1", ttl_s=TTL, now=later)
            assert refreshed is not None
            assert refreshed.status == "pending"
            assert refreshed.body_sha256 == "def"

    run_async(scenario())


def test_db_store_scope_is_per_workspace(require_profiling_db: None) -> None:
    """B3: the same key in a different workspace is a clean miss — no cross-tenant replay/leak."""

    async def scenario() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            store = DbIdempotencyStore(conn_factory=conn_session_factory(conn))
            now = datetime.now(UTC)
            assert await store.reserve(
                "ws_a", "shared", tool_name="pause_run", body_sha256="aaa", ttl_s=TTL, now=now
            )
            await store.complete(
                "ws_a", "shared", response_json={"tool": "pause_run", "version": "1"}
            )
            # ws_b sees nothing under the same key, and can reserve it independently.
            assert await store.lookup("ws_b", "shared", ttl_s=TTL, now=now) is None
            assert await store.reserve(
                "ws_b", "shared", tool_name="pause_run", body_sha256="bbb", ttl_s=TTL, now=now
            )
            a = await store.lookup("ws_a", "shared", ttl_s=TTL, now=now)
            b = await store.lookup("ws_b", "shared", ttl_s=TTL, now=now)
            assert a is not None and a.status == "completed" and a.body_sha256 == "aaa"
            assert b is not None and b.status == "pending" and b.body_sha256 == "bbb"

    run_async(scenario())


def test_db_store_release_deletes_only_pending(require_profiling_db: None) -> None:
    """S4: a failed invoke's release removes the pending reservation; a completed row survives."""

    async def scenario() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            store = DbIdempotencyStore(conn_factory=conn_session_factory(conn))
            now = datetime.now(UTC)
            assert await store.reserve(
                "ws_a", "rk", tool_name="echo", body_sha256="x", ttl_s=TTL, now=now
            )
            await store.release("ws_a", "rk")
            assert await store.lookup("ws_a", "rk", ttl_s=TTL, now=now) is None

            # A completed row is NOT released.
            assert await store.reserve(
                "ws_a", "rk", tool_name="echo", body_sha256="x", ttl_s=TTL, now=now
            )
            await store.complete("ws_a", "rk", response_json={"tool": "echo", "version": "1"})
            await store.release("ws_a", "rk")
            kept = await store.lookup("ws_a", "rk", ttl_s=TTL, now=now)
            assert kept is not None and kept.status == "completed"

    run_async(scenario())


@pytest.mark.parametrize("missing", ["nope"])
def test_db_store_missing_key_is_none(require_profiling_db: None, missing: str) -> None:
    async def scenario() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            store = DbIdempotencyStore(conn_factory=conn_session_factory(conn))
            assert await store.lookup("ws_a", missing, ttl_s=TTL) is None

    run_async(scenario())
