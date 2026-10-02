"""Alembic migration environment — async (SQLAlchemy 2.0 + asyncpg), M0.3 / ENG-114.

Runs migrations against the Postgres system of record using the same async engine and DSN as the
runtime connection layer (:mod:`clue_db`), so the migrations and the app never disagree on
which database they target. The DSN is read from ``CLUE_DATABASE_URL`` (the shared seam) — it is
never stored in ``alembic.ini``.

Autogenerate is intentionally minimal: there are no ORM models registered here (no domain tables in
M0; they land in M1+), so ``target_metadata`` is ``None`` and migrations are written by hand and
reviewed — not diffed from models (§M0.3 — "autogenerate off by default").
"""

from __future__ import annotations

import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy import text

from clue_config import Settings
from clue_db import create_engine, database_url

# Alembic Config object (values from alembic.ini).
config = context.config

# Configure logging from the ini file (if present).
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# No ORM models / declarative metadata: migrations are hand-written and reviewed (§M0.3).
target_metadata = None


def _do_run_migrations(connection: object) -> None:
    """Configure the migration context against an open (sync-facing) connection and run."""
    context.configure(
        connection=connection,  # type: ignore[arg-type]
        target_metadata=target_metadata,
        # Compare server defaults / types only matters for autogenerate, which is off; keep the
        # context minimal and explicit.
        render_as_batch=False,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode — emit SQL against the URL without a live DBAPI.

    Used for generating SQL scripts (``alembic upgrade head --sql``); the live up/down workflow
    uses the online (async) path below.
    """
    context.configure(
        url=database_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


async def _run_async_migrations() -> None:
    """Create the async engine, open one connection, and run migrations across the greenlet bridge.

    :meth:`AsyncConnection.run_sync` runs :func:`_do_run_migrations` on the synchronous facade;
    that function opens its own ``context.begin_transaction()`` block, so the DDL is committed
    before the connection closes. The engine is disposed in ``finally`` — no leaked connections.
    """
    engine = create_engine()
    try:
        async with engine.connect() as connection:
            # Session settings migrations read via ``current_setting`` (never a value baked into
            # a revision): ``clue.pages_system_suffix`` is the suffix system hostnames are written
            # under (``770bf20802e1`` turns F5 handles into ``<handle>.<suffix>`` rows). Session
            # scope (``is_local`` false) so it outlives the commit below; the commit ends the
            # autobegun transaction, so alembic's ``begin_transaction()`` still owns — and
            # commits — the DDL rather than finding a transaction already open.
            await connection.execute(
                text("SELECT set_config('clue.pages_system_suffix', :suffix, false)"),
                {"suffix": Settings().pages_system_suffix},
            )
            await connection.commit()
            await connection.run_sync(_do_run_migrations)
    finally:
        await engine.dispose()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode against the live async engine."""
    asyncio.run(_run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
