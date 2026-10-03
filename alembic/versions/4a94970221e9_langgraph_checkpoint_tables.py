"""LangGraph checkpoint tables, created by the owner (first production deploy, 2026-10-03).

LangGraph's ``PostgresSaver.setup()`` installs its own tables, and the agent turn, research runtime and
design job each called it on every open. In production those run as ``clue_worker``, which has no
CREATE on schema public, and ``setup()`` always issues ``CREATE TABLE IF NOT EXISTS`` — PostgreSQL
checks the schema privilege before it checks existence — so every turn failed with "permission denied
for schema public". This migration creates the tables as the migrating owner, exactly as ``setup()``
would: the statements are LangGraph's own (``langgraph-checkpoint-postgres`` 3.1.0,
``BasePostgresSaver.MIGRATIONS``), frozen here so a library upgrade can never change an applied
migration, and recorded in ``checkpoint_migrations`` the same way, so a database where ``setup()``
already ran (production after the 2026-10-03 hotfix grant) is left as it is. The runtime now runs
``setup()`` only when ``checkpoint_migrations`` is behind the installed library.

A LangGraph upgrade that adds checkpoint migrations needs a NEW Alembic migration for the new
statements; ``tests/db/test_langgraph_checkpoint_tables.py`` fails until it exists.

Revision ID: 4a94970221e9
Revises: 0a3a88c7e5ed
Create Date: 2026-10-03 09:56:05.201016+00:00
"""

# ruff: noqa: E501  (LangGraph's SQL below is verbatim; wrapping it would change the frozen copy)

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "4a94970221e9"
down_revision: str | None = "0a3a88c7e5ed"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: ``BasePostgresSaver.MIGRATIONS`` of langgraph-checkpoint-postgres 3.1.0, verbatim. Index = version.
LANGGRAPH_CHECKPOINT_MIGRATIONS: tuple[str, ...] = (
    "CREATE TABLE IF NOT EXISTS checkpoint_migrations (\n    v INTEGER PRIMARY KEY\n);",
    "CREATE TABLE IF NOT EXISTS checkpoints (\n    thread_id TEXT NOT NULL,\n    checkpoint_ns TEXT NOT NULL DEFAULT '',\n    checkpoint_id TEXT NOT NULL,\n    parent_checkpoint_id TEXT,\n    type TEXT,\n    checkpoint JSONB NOT NULL,\n    metadata JSONB NOT NULL DEFAULT '{}',\n    PRIMARY KEY (thread_id, checkpoint_ns, checkpoint_id)\n);",
    "CREATE TABLE IF NOT EXISTS checkpoint_blobs (\n    thread_id TEXT NOT NULL,\n    checkpoint_ns TEXT NOT NULL DEFAULT '',\n    channel TEXT NOT NULL,\n    version TEXT NOT NULL,\n    type TEXT NOT NULL,\n    blob BYTEA,\n    PRIMARY KEY (thread_id, checkpoint_ns, channel, version)\n);",
    "CREATE TABLE IF NOT EXISTS checkpoint_writes (\n    thread_id TEXT NOT NULL,\n    checkpoint_ns TEXT NOT NULL DEFAULT '',\n    checkpoint_id TEXT NOT NULL,\n    task_id TEXT NOT NULL,\n    idx INTEGER NOT NULL,\n    channel TEXT NOT NULL,\n    type TEXT,\n    blob BYTEA NOT NULL,\n    PRIMARY KEY (thread_id, checkpoint_ns, checkpoint_id, task_id, idx)\n);",
    "ALTER TABLE checkpoint_blobs ALTER COLUMN blob DROP not null;",
    "SELECT 1;",
    "\n    CREATE INDEX CONCURRENTLY IF NOT EXISTS checkpoints_thread_id_idx ON checkpoints(thread_id);\n    ",
    "\n    CREATE INDEX CONCURRENTLY IF NOT EXISTS checkpoint_blobs_thread_id_idx ON checkpoint_blobs(thread_id);\n    ",
    "\n    CREATE INDEX CONCURRENTLY IF NOT EXISTS checkpoint_writes_thread_id_idx ON checkpoint_writes(thread_id);\n    ",
    "ALTER TABLE checkpoint_writes ADD COLUMN IF NOT EXISTS task_path TEXT NOT NULL DEFAULT '';",
)


def upgrade() -> None:
    # Three of the statements are CREATE INDEX CONCURRENTLY, which cannot run in a transaction.
    with op.get_context().autocommit_block():
        bind = op.get_bind()
        bind.exec_driver_sql(LANGGRAPH_CHECKPOINT_MIGRATIONS[0])
        current = bind.exec_driver_sql("SELECT max(v) FROM checkpoint_migrations").scalar()
        start = -1 if current is None else current
        for version, statement in enumerate(LANGGRAPH_CHECKPOINT_MIGRATIONS):
            if version <= start:
                continue
            bind.exec_driver_sql(statement)
            bind.exec_driver_sql(f"INSERT INTO checkpoint_migrations (v) VALUES ({version})")


def downgrade() -> None:
    op.execute(
        "DROP TABLE IF EXISTS checkpoint_writes, checkpoint_blobs, checkpoints, checkpoint_migrations"
    )
