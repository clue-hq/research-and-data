"""``body_sha256`` stability + the Db idempotency store round-trip / TTL (DB-gated)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from clue_toolbelt import DbIdempotencyStore, StoredInvocation, body_sha256
from tests.db.conftest import run_async
from tests.profiling.conftest import conn_session_factory, rollback_conn


def test_body_sha256_is_key_order_independent() -> None:
    a = body_sha256({"a": 1, "b": [2, 3]})
    b = body_sha256({"b": [2, 3], "a": 1})
    assert a == b  # canonicalised — a retry is recognised regardless of serialisation


def test_body_sha256_changes_with_content() -> None:
    assert body_sha256({"value": 1}) != body_sha256({"value": 2})


def test_db_store_record_lookup_and_ttl(require_profiling_db: None) -> None:
    async def scenario() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            store = DbIdempotencyStore(conn_factory=conn_session_factory(conn))
            now = datetime.now(UTC)
            entry = StoredInvocation(
                idempotency_key="tk1",
                body_sha256="abc",
                tool_name="reverse_profile",
                response_json={"tool": "reverse_profile", "version": "1", "references": {"n": 1}},
                created_at=now,
            )
            await store.record(entry)

            # Within TTL: the row is returned with its stored body + response.
            got = await store.lookup("tk1", ttl_s=3600, now=now + timedelta(seconds=10))
            assert got is not None
            assert got.body_sha256 == "abc"
            assert got.response_json["references"] == {"n": 1}

            # Past TTL: reported absent (re-executable).
            assert await store.lookup("tk1", ttl_s=3600, now=now + timedelta(seconds=7200)) is None

            # A reused key past its TTL overwrites (upsert) — no duplicate-key error.
            await store.record(
                StoredInvocation(
                    idempotency_key="tk1",
                    body_sha256="def",
                    tool_name="reverse_profile",
                    response_json={"tool": "reverse_profile", "version": "1", "references": {}},
                    created_at=now + timedelta(seconds=8000),
                )
            )
            refreshed = await store.lookup("tk1", ttl_s=3600, now=now + timedelta(seconds=8001))
            assert refreshed is not None
            assert refreshed.body_sha256 == "def"

    run_async(scenario())


@pytest.mark.parametrize("missing", ["nope"])
def test_db_store_missing_key_is_none(require_profiling_db: None, missing: str) -> None:
    async def scenario() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            store = DbIdempotencyStore(conn_factory=conn_session_factory(conn))
            assert await store.lookup(missing, ttl_s=3600) is None

    run_async(scenario())
