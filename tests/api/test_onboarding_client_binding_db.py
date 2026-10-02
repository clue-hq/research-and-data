"""The onboarding lane's client-entity seam: resolve once, adopt an existing binding, stamp the run.

Nothing here calls a provider: ``prepare_client_kb_run`` loads the pack, records the run lineage
and resolves the entity — all of it against this connection, with the default offline embedder.
"""

from __future__ import annotations

from uuid import UUID, uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_api.arv2.onboarding_store import create_run
from clue_api.client_context_binding import bind_workspace_client, workspace_client_entity_id
from clue_api.onboarding_client_binding import Stage0ClientEntityBinder
from clue_core import EntityId
from tests._identity import seed_principal
from tests._workspace import seed_project
from tests.db.conftest import run_async
from tests.profiling.conftest import rollback_conn

pytestmark = pytest.mark.usefixtures("require_profiling_db")

_USER = "usr_o3_binder"
_DOMAIN = "insighthealth.ai"


async def _seed_run(
    conn: AsyncConnection, *, run_id: UUID, workspace_id: str, brand_id: str
) -> None:
    await create_run(
        conn,
        run_id=run_id,
        workspace_id=workspace_id,
        brand_id=brand_id,
        company_domain=_DOMAIN,
        requested_by_user_id=_USER,
    )


async def _ensure(
    conn: AsyncConnection, *, workspace_id: str, brand_id: str, run_id: UUID
) -> UUID | None:
    return await Stage0ClientEntityBinder().ensure(
        conn,
        workspace_id=workspace_id,
        brand_id=brand_id,
        company_domain=_DOMAIN,
        run_id=run_id,
    )


async def _stamped_client(conn: AsyncConnection, *, run_id: UUID) -> UUID | None:
    row = (
        await conn.execute(
            text("SELECT client_entity_id FROM onboarding_run WHERE run_id = :run_id"),
            {"run_id": run_id},
        )
    ).first()
    return None if row is None or row[0] is None else UUID(str(row[0]))


async def _insert_entity(conn: AsyncConnection, *, workspace_id: str, name: str) -> UUID:
    entity_id = uuid4()
    await conn.execute(
        text(
            "INSERT INTO account_entity (id, workspace_id, canonical_name, status) "
            "VALUES (:id, :ws, :name, 'active')"
        ),
        {"id": entity_id, "ws": workspace_id, "name": name},
    )
    return entity_id


def test_the_binder_creates_a_client_once_and_reuses_it() -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            ws = "ws-o3-binder"
            project = await seed_project(conn, ws, name="O3 binder")
            await seed_principal(conn, workspace_id=ws, user_id=_USER)
            first_run, second_run = uuid4(), uuid4()
            for run in (first_run, second_run):
                await _seed_run(conn, run_id=run, workspace_id=ws, brand_id=project.brand_id)

            first = await _ensure(
                conn, workspace_id=ws, brand_id=project.brand_id, run_id=first_run
            )
            assert first is not None
            assert await workspace_client_entity_id(conn, workspace_id=ws) == first
            assert await _stamped_client(conn, run_id=first_run) == first

            # A second run for the same company adopts the same client and stamps its own row.
            second = await _ensure(
                conn, workspace_id=ws, brand_id=project.brand_id, run_id=second_run
            )
            assert second == first
            assert await _stamped_client(conn, run_id=second_run) == first

    run_async(scenario())


def test_an_existing_workspace_binding_wins_and_is_never_repointed() -> None:
    """A workspace already bound (by Stage-0 recon, say) is not re-resolved. Repointing a binding
    is a refusal by design, so the binder reads the binding first and adopts whatever it names."""

    async def scenario() -> None:
        async with rollback_conn() as conn:
            ws = "ws-o3-binder-prebound"
            project = await seed_project(conn, ws, name="O3 binder prebound")
            await seed_principal(conn, workspace_id=ws, user_id=_USER)
            bound = await _insert_entity(conn, workspace_id=ws, name="Already the client")
            await bind_workspace_client(conn, workspace_id=ws, client_entity_id=EntityId(bound))

            run_id = uuid4()
            await _seed_run(conn, run_id=run_id, workspace_id=ws, brand_id=project.brand_id)
            assert (
                await _ensure(conn, workspace_id=ws, brand_id=project.brand_id, run_id=run_id)
                == bound
            )
            assert await _stamped_client(conn, run_id=run_id) == bound

    run_async(scenario())


def test_the_binder_leaves_an_already_stamped_run_alone() -> None:
    """The run stamp is write-once: a run that already names a client is never repointed."""

    async def scenario() -> None:
        async with rollback_conn() as conn:
            ws = "ws-o3-binder-stamped"
            project = await seed_project(conn, ws, name="O3 binder stamped")
            await seed_principal(conn, workspace_id=ws, user_id=_USER)
            run_id = uuid4()
            await _seed_run(conn, run_id=run_id, workspace_id=ws, brand_id=project.brand_id)
            other = await _insert_entity(conn, workspace_id=ws, name="Stamped by an earlier try")
            await conn.execute(
                text("UPDATE onboarding_run SET client_entity_id = :id WHERE run_id = :run_id"),
                {"id": other, "run_id": run_id},
            )

            bound = await _ensure(conn, workspace_id=ws, brand_id=project.brand_id, run_id=run_id)
            assert bound is not None
            assert bound != other
            assert await _stamped_client(conn, run_id=run_id) == other

    run_async(scenario())
