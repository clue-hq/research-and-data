"""The two indexes behind the evidence recovery check (W2-17 of the research cost/speed audit).

``recover_acquisitions`` runs after every evidence call and asks for one job's settled ledger
results that have no evidence source yet. Without an index on the ledger's job column and on the
evidence source's ledger id, Postgres reads both tables whole on every call, so the check grows
with every research run ever stored (measured on a scaled copy: about 1 ms at one run, 96 ms at
300 runs; 0.3 ms at 300 runs with these indexes).

The plan test seeds many jobs' rows (inside a transaction that rolls back) and checks that the
planner, left to itself, answers the exact query the code runs from both indexes.
"""

from __future__ import annotations

import hashlib
import importlib.util
from pathlib import Path
from uuid import UUID

import pytest
from alembic import command
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_api.arv2.quality_acquisition import RECOVERY_QUERY
from clue_db import db_lifespan

from .conftest import run_async

_REPO_ROOT = Path(__file__).resolve().parents[2]
_ALEMBIC_INI = _REPO_ROOT / "alembic.ini"
_MIGRATION = _REPO_ROOT / "alembic" / "versions" / "702784fe02b7_arv2_recovery_lookup_indexes.py"
_INDEXES = {
    "provider_call_ledger_job": (
        "CREATE INDEX provider_call_ledger_job ON public.provider_call_ledger "
        "USING btree (entity_research_job_id) WHERE (phase = 'result'::text)"
    ),
    "arv2_evidence_source_ledger": (
        "CREATE INDEX arv2_evidence_source_ledger ON public.arv2_evidence_source "
        "USING btree (workspace_id, ledger_id)"
    ),
}


def _alembic_config() -> Config:
    cfg = Config(str(_ALEMBIC_INI))
    cfg.set_main_option("script_location", str(_REPO_ROOT / "alembic"))
    return cfg


async def _index_definitions(conn: AsyncConnection) -> dict[str, str]:
    rows = await conn.execute(
        text(
            "SELECT indexname, indexdef FROM pg_indexes WHERE indexname = ANY(:names) "
            "AND schemaname = 'public'"
        ),
        {"names": list(_INDEXES)},
    )
    return {str(r.indexname): str(r.indexdef) for r in rows}


def _run_this_migration(step: str) -> None:
    """This migration's own ``upgrade()`` or ``downgrade()``, and nothing else. An alembic downgrade
    to the revision before it no longer works for that: since the website release merged, that
    revision is where main and the website line split, so the downgrade would unwind the website's
    migrations too — and they rightly refuse while site documents exist."""
    spec = importlib.util.spec_from_file_location("recovery_indexes_migration", _MIGRATION)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    def run(sync_conn) -> None:  # noqa: ANN001 - a SQLAlchemy sync Connection
        with Operations.context(MigrationContext.configure(sync_conn)):
            getattr(module, step)()

    async def go() -> None:
        async with db_lifespan() as engine, engine.connect() as conn:
            await conn.run_sync(run)
            await conn.commit()

    run_async(go())


async def _definitions() -> dict[str, str]:
    async with db_lifespan() as engine, engine.connect() as conn:
        return await _index_definitions(conn)


@pytest.mark.usefixtures("require_db")
def test_the_recovery_indexes_exist_with_their_definitions() -> None:
    command.upgrade(_alembic_config(), "head")
    assert run_async(_definitions()) == _INDEXES


_SEED = (
    # Twenty workspaces, ten jobs each, forty settled results per job, every one already indexed:
    # enough rows that the planner's choice is a real one. Foreign-key triggers are skipped
    # (``session_replication_role``) and the whole seed rolls back with the connection.
    """
    INSERT INTO provider_call_ledger
        (ledger_id, call_id, provider, operation, label, phase, outcome, workspace_id,
         entity_research_job_id, recorded_at)
    SELECT gen_random_uuid(), gen_random_uuid(), 'exa', 'search', 'plan', 'result', 'ok',
           'ws-' || (j % 20), md5('job-' || j)::uuid, now() - make_interval(secs => r)
    FROM generate_series(1, 200) j, generate_series(1, 40) r
    """,
    """
    INSERT INTO arv2_evidence_source
        (source_id, workspace_id, run_id, account_id, job_id, subject_id, revision, kind,
         artifact_key, artifact_sha256, byte_size, media_type, observed_at, origin_locator,
         normalizer_version, ledger_id)
    SELECT gen_random_uuid(), l.workspace_id, l.entity_research_job_id, l.entity_research_job_id,
           l.entity_research_job_id, gen_random_uuid(),
           row_number() OVER (PARTITION BY l.entity_research_job_id ORDER BY l.ledger_id),
           'provider_record', 'k', repeat('a', 64), 1, 'application/json', now(), 'x', 'v',
           l.ledger_id
    FROM provider_call_ledger l WHERE l.label = 'plan'
    """,
)


@pytest.mark.usefixtures("require_db")
def test_the_planner_answers_the_recovery_query_from_the_indexes() -> None:
    """With many jobs' rows present, the planner itself picks both indexes; nothing is forced."""
    command.upgrade(_alembic_config(), "head")

    async def plan() -> str | None:
        async with db_lifespan() as engine, engine.connect() as conn:
            superuser = (
                await conn.execute(
                    text("SELECT rolsuper FROM pg_roles WHERE rolname = current_user")
                )
            ).scalar_one()
            if not superuser:
                return None  # the seed needs session_replication_role (review M-6)
            await conn.execute(text("SET LOCAL session_replication_role = replica"))
            for statement in _SEED:
                await conn.execute(text(statement))
            await conn.execute(text("ANALYZE provider_call_ledger"))
            await conn.execute(text("ANALYZE arv2_evidence_source"))
            rows = await conn.execute(
                text("EXPLAIN " + RECOVERY_QUERY.text),
                {"ws": "ws-7", "job": _job_id(7), "seen": [], "batch": 20},
            )
            found = "\n".join(str(r[0]) for r in rows)
            await conn.rollback()
            return found

    found = run_async(plan())
    if found is None:
        pytest.skip("seeding past foreign keys needs a superuser database role")
    assert "provider_call_ledger_job" in found, found
    assert "arv2_evidence_source_ledger" in found, found


def _job_id(j: int) -> UUID:
    """The job id the seed gives job ``j`` (``md5('job-' || j)::uuid``)."""
    return UUID(hashlib.md5(f"job-{j}".encode()).hexdigest())


@pytest.mark.usefixtures("require_db")
def test_the_recovery_indexes_round_trip_down_and_up() -> None:
    cfg = _alembic_config()
    command.upgrade(cfg, "head")
    assert run_async(_definitions()) == _INDEXES

    _run_this_migration("downgrade")
    assert run_async(_definitions()) == {}

    _run_this_migration("upgrade")
    assert run_async(_definitions()) == _INDEXES
