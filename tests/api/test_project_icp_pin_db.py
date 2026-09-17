"""The durable project ICP pin (ARV2 onboarding O6, Task 9b — founder rulings 2026-09-10).

A project pins exactly one confirmed ICP document version, by document id, written when a human
approves the ICP confirmation gate. What this suite pins, from durable rows:

* an approval pins the document it just minted, at ``pin_seq`` 1, carrying the product selection
  the project had confirmed at that moment (or nothing, in the ICP-first order);
* a replayed approval writes no second pin — the receipt stays the first one's;
* **another project confirming the same path pins its own document and leaves the first project's
  pin, and the row it names, exactly as they were**. This is the ruling: a newer version on a path
  must not change what an existing project reads or launches with;
* the pin is append-only at the database — a row that could be edited would not be a receipt.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_api.agent_turn_wiring import DurableAgentArtifactStore
from clue_api.arv2.icp_confirmation import (
    confirm_icp_document,
    current_icp_document,
    current_project_icp_pin,
    pin_project_icp,
)
from clue_spine import create_project
from tests._workspace import seed_project
from tests.api.test_stage0_setup_db import _MemoryStorage
from tests.db.conftest import run_async
from tests.profiling.conftest import (
    conn_session_factory,
    migrated_db,  # noqa: F401 -- exposes the fixture to this test module
    rollback_conn,
)


@pytest.fixture
def require_pin_db(request: pytest.FixtureRequest) -> None:
    if not request.getfixturevalue("migrated_db"):
        pytest.skip("requires a migrated per-branch Postgres database")


pytestmark = pytest.mark.usefixtures("require_pin_db")

USER_ID = "usr-o6-pin"


def _icp_body(*, key: str) -> str:
    return (
        f"---\nkind: icp-definition\nicp_key: {key}\nversion: 1\nstatus: proposed\n"
        f"title: {key} groups\nproduct_ids: []\n---\n\n"
        f"# {key} groups\n\nIndependent {key} groups with three to twelve physicians.\n"
    )


async def _seed_proposal(
    conn: AsyncConnection,
    *,
    artifacts: DurableAgentArtifactStore,
    workspace_id: str,
    brand_id: str,
    key: str,
) -> UUID:
    ref = await artifacts.persist_body(
        workspace_id=workspace_id,
        data=_icp_body(key=key).encode(),
        media_type="text/markdown",
    )
    document_id = uuid4()
    await conn.execute(
        text(
            "INSERT INTO brand_knowledge_document (document_id, workspace_id, brand_id, folder, "
            "path, kind, version, status, artifact_key, artifact_sha256) "
            "VALUES (:id, :ws, :brand, 'audience', :path, 'icp-definition', 1, 'proposed', "
            " :key, :sha)"
        ),
        {
            "id": document_id,
            "ws": workspace_id,
            "brand": brand_id,
            "path": f"audience/icp-{key}.md",
            "key": ref.artifact_key,
            "sha": ref.sha256,
        },
    )
    return document_id


async def _subject(
    conn: AsyncConnection,
    storage: Any,
    *,
    workspace_id: str,
    brand_id: str,
    icp_key: str,
) -> Any:
    """The document a gate would present right now — the brand's current servable version."""

    subject = await current_icp_document(
        conn,
        storage,
        workspace_id=workspace_id,
        brand_id=brand_id,
        icp_key=icp_key,
    )
    assert subject is not None
    return subject


async def _confirm_and_pin(
    conn: AsyncConnection,
    storage: Any,
    *,
    workspace_id: str,
    brand_id: str,
    project_id: str,
    subject: Any,
    product_selection_version: int | None,
    user_id: str = USER_ID,
) -> Any:
    """The gate-approval act, exactly as ``chat/router`` performs it: confirm, then pin.

    ``subject`` is the document the human was shown. A *replay* re-approves that same subject —
    re-reading "the current document" instead would find the confirmation just minted and mint a
    version of it, which is a second approval, not a retry of the first.
    """

    confirmed = await confirm_icp_document(
        conn,
        storage,
        workspace_id=workspace_id,
        brand_id=brand_id,
        project_id=project_id,
        proposed=subject,
        expected_sha256=subject.artifact_sha256,
        confirmed_by_user_id=user_id,
        product_selection_version=product_selection_version,
    )
    return await pin_project_icp(
        conn,
        workspace_id=workspace_id,
        project_id=project_id,
        brand_id=brand_id,
        document=confirmed,
        product_selection_version=product_selection_version,
        pinned_by_user_id=user_id,
    )


async def _pin_rows(conn: AsyncConnection, *, project_id: str) -> list[dict[str, Any]]:
    rows = (
        await conn.execute(
            text(
                "SELECT pin_seq, workspace_id, brand_id, document_id, icp_key, artifact_key, "
                " artifact_sha256, product_selection_version, pinned_by_user_id "
                "FROM project_icp_pin WHERE project_id = :project ORDER BY pin_seq"
            ),
            {"project": project_id},
        )
    ).mappings()
    return [dict(row) for row in rows.all()]


def test_an_approval_pins_the_document_it_minted_and_a_replay_writes_nothing() -> None:
    async def scenario() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            workspace_id = f"o6-pin-{uuid4().hex[:6]}"
            project = await seed_project(conn, workspace_id, name="O6 pin one")
            storage = _MemoryStorage()
            artifacts = DurableAgentArtifactStore(
                storage=storage, conn_factory=conn_session_factory(conn)
            )
            await _seed_proposal(
                conn,
                artifacts=artifacts,
                workspace_id=workspace_id,
                brand_id=project.brand_id,
                key="gi",
            )

            assert (
                await current_project_icp_pin(
                    conn, workspace_id=workspace_id, project_id=project.project_id
                )
            ) is None

            proposal = await _subject(
                conn,
                storage,
                workspace_id=workspace_id,
                brand_id=project.brand_id,
                icp_key="gi",
            )
            pin = await _confirm_and_pin(
                conn,
                storage,
                workspace_id=workspace_id,
                brand_id=project.brand_id,
                project_id=project.project_id,
                subject=proposal,
                product_selection_version=3,
            )
            assert pin.icp_key == "gi"
            assert pin.path == "audience/icp-gi.md"
            assert pin.version == 2
            assert pin.product_selection_version == 3

            rows = await _pin_rows(conn, project_id=project.project_id)
            assert [row["pin_seq"] for row in rows] == [1]
            assert rows[0]["document_id"] == pin.document_id
            assert rows[0]["workspace_id"] == workspace_id
            assert rows[0]["brand_id"] == project.brand_id
            assert rows[0]["artifact_key"] == pin.artifact_key
            assert rows[0]["artifact_sha256"] == pin.artifact_sha256
            assert rows[0]["product_selection_version"] == 3
            assert rows[0]["pinned_by_user_id"] == USER_ID

            # The same approval again — a double click, or a retried request.
            replayed = await _confirm_and_pin(
                conn,
                storage,
                workspace_id=workspace_id,
                brand_id=project.brand_id,
                project_id=project.project_id,
                subject=proposal,
                product_selection_version=4,
                user_id="usr-o6-someone-else",
            )
            assert replayed == pin
            assert await _pin_rows(conn, project_id=project.project_id) == rows

            current = await current_project_icp_pin(
                conn, workspace_id=workspace_id, project_id=project.project_id
            )
            assert current == pin
            # A foreign workspace cannot tell a pin it does not own from an absent one.
            assert (
                await current_project_icp_pin(
                    conn, workspace_id="o6-other-ws", project_id=project.project_id
                )
            ) is None

    run_async(scenario())


def test_a_confirmation_before_any_product_set_pins_no_selection_version() -> None:
    """The "other order": the ICP is confirmed first, so there is no version to record."""

    async def scenario() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            workspace_id = f"o6-pin-{uuid4().hex[:6]}"
            project = await seed_project(conn, workspace_id, name="O6 pin no set")
            storage = _MemoryStorage()
            artifacts = DurableAgentArtifactStore(
                storage=storage, conn_factory=conn_session_factory(conn)
            )
            await _seed_proposal(
                conn,
                artifacts=artifacts,
                workspace_id=workspace_id,
                brand_id=project.brand_id,
                key="gi",
            )

            pin = await _confirm_and_pin(
                conn,
                storage,
                workspace_id=workspace_id,
                brand_id=project.brand_id,
                project_id=project.project_id,
                subject=await _subject(
                    conn,
                    storage,
                    workspace_id=workspace_id,
                    brand_id=project.brand_id,
                    icp_key="gi",
                ),
                product_selection_version=None,
            )
            assert pin.product_selection_version is None
            rows = await _pin_rows(conn, project_id=project.project_id)
            assert rows[0]["product_selection_version"] is None

    run_async(scenario())


def test_another_projects_confirmation_leaves_this_projects_pin_and_row_alone() -> None:
    """The ruling itself: a brand's ICPs are shared, a pin is not.

    Each project confirms whatever its gate presented, so each mints its own ``confirmed`` version
    of the same shared path. The second confirmation is a newer version than the first — and the
    first project's pin still names the first version, whose row is still ``confirmed`` and still
    readable, because ``_may_retire`` will not retire another project's confirmation.
    """

    async def scenario() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            workspace_id = f"o6-pin-{uuid4().hex[:6]}"
            first = await seed_project(conn, workspace_id, name="O6 pin project A")
            second = await create_project(
                conn,
                workspace_id=workspace_id,
                brand_id=first.brand_id,
                name="O6 pin project B",
            )
            storage = _MemoryStorage()
            artifacts = DurableAgentArtifactStore(
                storage=storage, conn_factory=conn_session_factory(conn)
            )
            await _seed_proposal(
                conn,
                artifacts=artifacts,
                workspace_id=workspace_id,
                brand_id=first.brand_id,
                key="gi",
            )

            pin_a = await _confirm_and_pin(
                conn,
                storage,
                workspace_id=workspace_id,
                brand_id=first.brand_id,
                project_id=first.project_id,
                subject=await _subject(
                    conn,
                    storage,
                    workspace_id=workspace_id,
                    brand_id=first.brand_id,
                    icp_key="gi",
                ),
                product_selection_version=1,
            )
            # Project B's gate presents whatever the brand serves now, which is A's confirmation.
            pin_b = await _confirm_and_pin(
                conn,
                storage,
                workspace_id=workspace_id,
                brand_id=first.brand_id,
                project_id=second.project_id,
                subject=await _subject(
                    conn,
                    storage,
                    workspace_id=workspace_id,
                    brand_id=first.brand_id,
                    icp_key="gi",
                ),
                product_selection_version=2,
            )

            assert pin_a.document_id != pin_b.document_id
            assert pin_b.version > pin_a.version
            assert [
                row["pin_seq"] for row in await _pin_rows(conn, project_id=first.project_id)
            ] == [1]
            assert [
                row["pin_seq"] for row in await _pin_rows(conn, project_id=second.project_id)
            ] == [1]

            # Project A's pin did not move, and the version it names is still confirmed.
            still = await current_project_icp_pin(
                conn, workspace_id=workspace_id, project_id=first.project_id
            )
            assert still == pin_a
            status = (
                await conn.execute(
                    text("SELECT status FROM brand_knowledge_document WHERE document_id = :id"),
                    {"id": pin_a.document_id},
                )
            ).scalar_one()
            assert status == "confirmed"

    run_async(scenario())


def test_the_current_pin_is_the_greatest_pin_seq() -> None:
    """A project that pins a different ICP appends; the newest row is what everything reads."""

    async def scenario() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            workspace_id = f"o6-pin-{uuid4().hex[:6]}"
            project = await seed_project(conn, workspace_id, name="O6 pin switch")
            storage = _MemoryStorage()
            artifacts = DurableAgentArtifactStore(
                storage=storage, conn_factory=conn_session_factory(conn)
            )
            for key in ("gi", "asc"):
                await _seed_proposal(
                    conn,
                    artifacts=artifacts,
                    workspace_id=workspace_id,
                    brand_id=project.brand_id,
                    key=key,
                )

            first = await _confirm_and_pin(
                conn,
                storage,
                workspace_id=workspace_id,
                brand_id=project.brand_id,
                project_id=project.project_id,
                subject=await _subject(
                    conn,
                    storage,
                    workspace_id=workspace_id,
                    brand_id=project.brand_id,
                    icp_key="gi",
                ),
                product_selection_version=1,
            )
            second = await _confirm_and_pin(
                conn,
                storage,
                workspace_id=workspace_id,
                brand_id=project.brand_id,
                project_id=project.project_id,
                subject=await _subject(
                    conn,
                    storage,
                    workspace_id=workspace_id,
                    brand_id=project.brand_id,
                    icp_key="asc",
                ),
                product_selection_version=2,
            )

            rows = await _pin_rows(conn, project_id=project.project_id)
            assert [row["pin_seq"] for row in rows] == [1, 2]
            assert rows[0]["document_id"] == first.document_id
            assert rows[1]["document_id"] == second.document_id
            current = await current_project_icp_pin(
                conn, workspace_id=workspace_id, project_id=project.project_id
            )
            assert current == second
            assert current is not None and current.icp_key == "asc"

    run_async(scenario())


@pytest.mark.parametrize(
    "statement",
    [
        "UPDATE project_icp_pin SET icp_key = 'tampered' WHERE project_id = :project",
        "DELETE FROM project_icp_pin WHERE project_id = :project",
    ],
    ids=["update", "delete"],
)
def test_a_written_pin_can_neither_be_edited_nor_deleted(statement: str) -> None:
    async def scenario() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            workspace_id = f"o6-pin-{uuid4().hex[:6]}"
            project = await seed_project(conn, workspace_id, name="O6 pin immutable")
            storage = _MemoryStorage()
            artifacts = DurableAgentArtifactStore(
                storage=storage, conn_factory=conn_session_factory(conn)
            )
            await _seed_proposal(
                conn,
                artifacts=artifacts,
                workspace_id=workspace_id,
                brand_id=project.brand_id,
                key="gi",
            )
            await _confirm_and_pin(
                conn,
                storage,
                workspace_id=workspace_id,
                brand_id=project.brand_id,
                project_id=project.project_id,
                subject=await _subject(
                    conn,
                    storage,
                    workspace_id=workspace_id,
                    brand_id=project.brand_id,
                    icp_key="gi",
                ),
                product_selection_version=1,
            )
            await conn.execute(text(statement), {"project": project.project_id})

    with pytest.raises(DBAPIError, match="append-only"):
        run_async(scenario())
