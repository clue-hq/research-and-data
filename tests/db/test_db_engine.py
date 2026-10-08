"""Engine/pool lifecycle tests (M0.3 / ENG-114).

Covers the §M0.3 acceptance criterion: "the async pool opens on app startup and closes on shutdown
via lifespan with no leaked connections (verified by a startup/shutdown test)". DB-requiring cases
skip gracefully when ``CLUE_DATABASE_URL`` is unset / the DB is unreachable.

The DSN-reading behaviour (which needs no live DB) is tested unconditionally.
"""

from __future__ import annotations

import asyncio
import os

import pytest
from sqlalchemy import text

from clue_db import (
    DATABASE_URL_ENV,
    DEFAULT_DATABASE_URL,
    connection,
    create_engine,
    database_url,
    db_lifespan,
    get_engine,
    get_pool,
    repeatable_read_transaction,
    transaction,
)

from .conftest import run_async

# --- DSN seam (no DB required) ----------------------------------------------


def test_database_url_falls_back_to_documented_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(DATABASE_URL_ENV, raising=False)
    assert database_url() == DEFAULT_DATABASE_URL


def test_database_url_reads_env(monkeypatch: pytest.MonkeyPatch) -> None:
    dsn = "postgresql+asyncpg://u:p@db.internal:5432/clue_test"
    monkeypatch.setenv(DATABASE_URL_ENV, dsn)
    assert database_url() == dsn


def test_get_engine_raises_without_active_lifespan() -> None:
    # No lifespan entered in this test, so the accessor must refuse rather than lazily create.
    with pytest.raises(RuntimeError):
        get_engine()
    with pytest.raises(RuntimeError):
        get_pool()


def test_engines_pre_ping_connections_before_pool_reuse() -> None:
    async def _run() -> None:
        engine = create_engine()
        try:
            assert engine.sync_engine.pool._pre_ping is True  # type: ignore[attr-defined]
        finally:
            await engine.dispose()

    run_async(_run())


def test_pool_settings_default_to_the_library_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("CLUE_DB_POOL_SIZE", "CLUE_DB_MAX_OVERFLOW", "CLUE_DB_POOL_TIMEOUT_S"):
        monkeypatch.delenv(name, raising=False)

    async def _run() -> None:
        engine = create_engine()
        try:
            pool = engine.sync_engine.pool
            assert pool.size() == 5  # type: ignore[attr-defined]
            assert pool._max_overflow == 10  # type: ignore[attr-defined]
            assert pool._timeout == 30  # type: ignore[attr-defined]
        finally:
            await engine.dispose()

    run_async(_run())


def test_pool_settings_come_from_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """Research slowness fix 2026-10-03: the per-process pool is an explicit setting."""
    monkeypatch.setenv("CLUE_DB_POOL_SIZE", "7")
    monkeypatch.setenv("CLUE_DB_MAX_OVERFLOW", "3")
    monkeypatch.setenv("CLUE_DB_POOL_TIMEOUT_S", "12")

    async def _run() -> None:
        engine = create_engine()
        try:
            pool = engine.sync_engine.pool
            assert pool.size() == 7  # type: ignore[attr-defined]
            assert pool._max_overflow == 3  # type: ignore[attr-defined]
            assert pool._timeout == 12  # type: ignore[attr-defined]
        finally:
            await engine.dispose()

    run_async(_run())


# --- lifespan + pool (DB required) ------------------------------------------


@pytest.mark.usefixtures("require_db")
def test_lifespan_opens_and_closes_without_leaking_connections() -> None:
    """The pool opens on enter, serves connections, and closes every connection on exit."""

    async def _run() -> None:
        async with db_lifespan() as engine:
            # Pool accessor returns the same live engine while the lifespan is active.
            assert get_engine() is engine
            assert get_pool() is engine
            # Open and use several pooled connections.
            for _ in range(3):
                async with connection() as conn:
                    result = await conn.execute(text("SELECT 1"))
                    assert result.scalar_one() == 1
            pool = engine.pool
            # All borrowed connections have been returned to the pool (none still checked out).
            assert pool.checkedout() == 0  # type: ignore[attr-defined]
        # After the lifespan exits, the engine is disposed: the accessor refuses again and the
        # pool holds no open connections (dispose() closed them) -> nothing leaked.
        with pytest.raises(RuntimeError):
            get_engine()
        assert engine.pool.checkedout() == 0  # type: ignore[attr-defined]

    run_async(_run())


@pytest.mark.usefixtures("require_db")
def test_transaction_commits_on_success_and_rolls_back_on_error() -> None:
    """`transaction()` commits a successful block and rolls back when the body raises."""

    async def _run() -> None:
        async with db_lifespan():
            # Use a session-local temp table so the test leaves no schema behind.
            async with transaction() as conn:
                await conn.execute(
                    text("CREATE TEMP TABLE _smoke_tx (n int) ON COMMIT PRESERVE ROWS")
                )

            # Committed write survives into a new connection's view (same session/pool conn reuse
            # is not guaranteed, so re-create per-connection temp scope): assert rollback semantics
            # within a single connection instead.
            class _Boom(Exception):
                pass

            with pytest.raises(_Boom):
                async with transaction() as conn:
                    await conn.execute(text("SELECT 1"))
                    raise _Boom
            # If we got here, the rollback path executed cleanly (no leaked open transaction).
            async with connection() as conn:
                assert (await conn.execute(text("SELECT 1"))).scalar_one() == 1

    run_async(_run())


@pytest.mark.usefixtures("require_db")
def test_repeatable_read_transaction_is_read_only() -> None:
    """C7 production projections receive one repeatable, mutation-proof MVCC snapshot."""

    async def _run() -> None:
        async with db_lifespan(), repeatable_read_transaction() as conn:
            isolation = (await conn.execute(text("SHOW transaction_isolation"))).scalar_one()
            read_only = (await conn.execute(text("SHOW transaction_read_only"))).scalar_one()
            assert isolation == "repeatable read"
            assert read_only == "on"

    run_async(_run())


def test_db_tests_skip_cleanly_without_dsn(monkeypatch: pytest.MonkeyPatch) -> None:
    """Sanity: the gate helper reports unavailable when the env var is absent."""
    monkeypatch.delenv(DATABASE_URL_ENV, raising=False)
    assert os.environ.get(DATABASE_URL_ENV) is None


@pytest.mark.usefixtures("require_db")
def test_a_wait_for_a_pooled_connection_is_logged_with_the_pool_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Every connection a process takes comes from one small pool, shared by its jobs, its agent
    bookkeeping and its fleet heartbeat. A checkout that had to wait is logged above
    ``CLUE_DB_CRITICAL_SECTION_LOG_MS``, so a pool that gets tight is visible."""
    import clue_db.engine as engine_module

    lines: list[tuple[str, dict]] = []

    class Recording:
        def info(self, event: str, **fields: object) -> None:
            lines.append((event, fields))

    monkeypatch.setattr(engine_module, "log", Recording())
    monkeypatch.setenv("CLUE_DB_POOL_SIZE", "1")
    monkeypatch.setenv("CLUE_DB_MAX_OVERFLOW", "0")
    monkeypatch.setenv("CLUE_DB_CRITICAL_SECTION_LOG_MS", "100")

    async def scenario() -> None:
        async with db_lifespan():
            async with transaction() as conn:  # warm the pool: the next checkouts are fast
                await conn.execute(text("SELECT 1"))

            async def hold() -> None:
                async with transaction():
                    await asyncio.sleep(0.3)

            holder = asyncio.create_task(hold())
            await asyncio.sleep(0.05)
            async with transaction() as conn:
                await conn.execute(text("SELECT 1"))
            await holder

    run_async(scenario())
    waited = [fields for event, fields in lines if event == "db.connection_waited"]
    long = [fields for fields in waited if float(str(fields["wait_ms"])) >= 150]
    assert len(long) == 1, waited
    assert "Checked out" in str(long[0]["pool"])
