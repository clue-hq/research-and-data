"""The project's own documents against the real tables: one plan, versioned, editable by both hands.

Two writers share one version chain here, and the tests are mostly about what each of them may
*not* do. The agent writes ``project/plan.md`` through :func:`write_project_plan`, and it must say
which version it read — a plan written against a version the human has since edited is refused by
name rather than silently overwriting their words. The human writes through
:func:`save_project_document`, the project-scoped twin of the Knowledge PUT, and their edit can
never carry another version's approval stamp forward: a ``confirmed`` project-local ICP they retype
comes back as ``proposed``.

Everything is read and written inside **one project's** scope. A document belonging to another
project is not an error here, it is *absent* — the same answer a document that never existed gets.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_api.arv2.project_documents import (
    PLAN_KIND,
    PLAN_PATH,
    PLAN_WORKSPACE_PATH,
    ProjectDocumentRefused,
    ProjectPlanWrite,
    current_plan_version,
    list_project_documents,
    plan_document_id,
    read_project_document,
    save_project_document,
    write_project_plan,
)
from clue_storage.fs import FsStorage
from tests._workspace import seed_project
from tests.arv2.icp_fixture import seed_icp_document

# The claim-store harness lives in a sibling test package; a fixture is only visible to a module
# that imports it, so re-export both (``require_claimstore_db`` depends on ``migrated_db``).
from tests.claimstore.conftest import (  # noqa: F401
    migrated_db,
    require_claimstore_db,
    rollback_conn,
)
from tests.db.conftest import run_async

pytestmark = pytest.mark.usefixtures("require_claimstore_db")

WORKSPACE = "ws_project_documents"
USER_ID = "usr_project_documents"

BODY = """# Q4 expansion plan

## Outcome
Twenty qualified conversations with GI-focused ASCs by the end of the quarter.

## Next steps
1. Confirm the account list.
"""

#: A project-local ICP a human said yes to, with the approval stamp a confirmation writes. The
#: point of the fixture is those four keys: a human's text edit must not carry them forward.
CONFIRMED_ICP = """---
kind: icp-definition
icp_key: gi-dac
product_ids: [prd_aura]
hard_gates:
  - {key: specialty, rule: GI-focused ASC, test: website lists GI procedures}
status: confirmed
confirmed_by: usr_founder
confirmed_at: '2026-09-11T10:00:00+00:00'
confirmed_for_project_id: prj_x
product_selection_version: 3
---

# GI-focused ASCs

Body.
"""


async def _seed(conn: AsyncConnection) -> tuple[str, str, str]:
    project = await seed_project(conn, WORKSPACE)
    return project.workspace_id, project.project_id, str(project.brand_id)


def _write(
    workspace_id: str,
    brand_id: str,
    project_id: str,
    **overrides: Any,
) -> ProjectPlanWrite:
    payload: dict[str, Any] = {
        "workspace_id": workspace_id,
        "brand_id": brand_id,
        "project_id": project_id,
        "turn_id": uuid4(),
        "user_id": USER_ID,
        "body": BODY,
        "expected_version": None,
    }
    payload.update(overrides)
    return ProjectPlanWrite(**payload)


async def _row(conn: AsyncConnection, document_id: UUID) -> dict[str, Any]:
    return dict(
        (
            await conn.execute(
                text(
                    "SELECT project_id, folder, path, kind, version, status, artifact_key, "
                    "       supersedes_document_id "
                    "FROM brand_knowledge_document WHERE document_id = :d"
                ),
                {"d": document_id},
            )
        )
        .mappings()
        .one()
    )


async def _rows_at(conn: AsyncConnection, workspace_id: str, path: str) -> list[dict[str, Any]]:
    return [
        dict(row)
        for row in (
            await conn.execute(
                text(
                    "SELECT document_id, version, status FROM brand_knowledge_document "
                    "WHERE workspace_id = :w AND path = :p ORDER BY version"
                ),
                {"w": workspace_id, "p": path},
            )
        )
        .mappings()
        .all()
    ]


def test_the_first_plan_is_version_one_and_carries_the_platforms_front_matter(
    tmp_path: Any,
) -> None:
    """A project with no plan takes ``expected_version=None`` and gets version 1.

    The front matter is the platform's, not the model's: the kind every reader dispatches on, the
    scope the row is in, and who wrote it on which turn.
    """

    async def scenario() -> None:
        async with rollback_conn() as conn:
            storage = FsStorage(tmp_path)
            workspace_id, project_id, brand_id = await _seed(conn)
            assert (
                await current_plan_version(conn, workspace_id=workspace_id, project_id=project_id)
            ) is None
            request = _write(workspace_id, brand_id, project_id)

            written = await write_project_plan(conn, storage, request)

            assert (written.version, written.replayed) == (1, False)
            assert written.path == PLAN_PATH
            assert written.workspace_path == PLAN_WORKSPACE_PATH == "inputs/project/plan.md"
            assert written.document_id == plan_document_id(
                turn_id=request.turn_id, expected_version=None
            )
            row = await _row(conn, written.document_id)
            assert (row["project_id"], row["folder"], row["kind"], row["status"]) == (
                project_id,
                "project",
                PLAN_KIND,
                "ready",
            )
            assert row["supersedes_document_id"] is None
            assert (
                await current_plan_version(conn, workspace_id=workspace_id, project_id=project_id)
            ) == 1

            found = await read_project_document(
                conn,
                storage,
                workspace_id=workspace_id,
                project_id=project_id,
                document_id=written.document_id,
            )
            assert found is not None
            served, front, body = found
            assert front["kind"] == PLAN_KIND
            assert front["status"] == "ready"
            assert front["project_id"] == project_id
            assert front["brand_id"] == brand_id
            assert front["authored_by"] == {
                "turn_id": str(request.turn_id),
                "user_id": USER_ID,
            }
            assert isinstance(front["authored_at"], str) and front["authored_at"]
            assert body == BODY
            assert (served.version, served.kind, served.icp_key) == (1, PLAN_KIND, None)

    run_async(scenario())


def test_the_next_version_supersedes_the_one_it_was_written_against(tmp_path: Any) -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            storage = FsStorage(tmp_path)
            workspace_id, project_id, brand_id = await _seed(conn)

            first = await write_project_plan(
                conn, storage, _write(workspace_id, brand_id, project_id)
            )
            second = await write_project_plan(
                conn,
                storage,
                _write(workspace_id, brand_id, project_id, expected_version=1, body="# v2\n"),
            )

            assert (first.version, second.version) == (1, 2)
            assert second.document_id != first.document_id
            assert (await _row(conn, first.document_id))["status"] == "superseded"
            second_row = await _row(conn, second.document_id)
            assert (second_row["status"], second_row["supersedes_document_id"]) == (
                "ready",
                first.document_id,
            )

    run_async(scenario())


def test_a_write_against_a_version_that_is_no_longer_current_is_refused_by_name(
    tmp_path: Any,
) -> None:
    """The whole point of the revision check: the human edited the plan, the agent had not read it.

    Both stale directions are refused — an agent that thinks no plan exists, and one that names a
    version that never existed — and the message tells it the version to re-read against.
    """

    async def scenario() -> None:
        async with rollback_conn() as conn:
            storage = FsStorage(tmp_path)
            workspace_id, project_id, brand_id = await _seed(conn)
            await write_project_plan(conn, storage, _write(workspace_id, brand_id, project_id))

            for stale in (None, 5):
                with pytest.raises(ProjectDocumentRefused) as excinfo:
                    await write_project_plan(
                        conn,
                        storage,
                        _write(workspace_id, brand_id, project_id, expected_version=stale),
                    )
                assert excinfo.value.code == "project_document_revision_conflict"
                assert "version 1" in str(excinfo.value)
                assert "inputs/project/plan.md" in str(excinfo.value)
            # The refusal wrote nothing: the human's version 1 is still the only row.
            assert [row["version"] for row in await _rows_at(conn, workspace_id, PLAN_PATH)] == [1]

    run_async(scenario())


def test_an_empty_body_is_refused_before_anything_is_stored(tmp_path: Any) -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            storage = FsStorage(tmp_path)
            workspace_id, project_id, brand_id = await _seed(conn)

            for empty in ("", "   \n\n  "):
                with pytest.raises(ProjectDocumentRefused) as excinfo:
                    await write_project_plan(
                        conn, storage, _write(workspace_id, brand_id, project_id, body=empty)
                    )
                assert excinfo.value.code == "project_document_body_empty"
            assert await _rows_at(conn, workspace_id, PLAN_PATH) == []

    run_async(scenario())


def test_a_retried_write_returns_its_own_row_instead_of_a_second_version(tmp_path: Any) -> None:
    """The id is derived from the turn and the version it was written against, so a retry of one
    tool call finds the row it already wrote rather than publishing the same plan twice."""

    async def scenario() -> None:
        async with rollback_conn() as conn:
            storage = FsStorage(tmp_path)
            workspace_id, project_id, brand_id = await _seed(conn)
            request = _write(workspace_id, brand_id, project_id)

            first = await write_project_plan(conn, storage, request)
            again = await write_project_plan(conn, storage, request)

            assert again.replayed is True
            assert (again.document_id, again.version) == (first.document_id, first.version)
            assert [row["version"] for row in await _rows_at(conn, workspace_id, PLAN_PATH)] == [1]

    run_async(scenario())


def test_the_list_serves_one_row_per_path_and_only_this_projects_own(tmp_path: Any) -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            storage = FsStorage(tmp_path)
            workspace_id, project_id, brand_id = await _seed(conn)
            other = await seed_project(conn, workspace_id, name="Another project")
            await write_project_plan(conn, storage, _write(workspace_id, brand_id, project_id))
            await write_project_plan(
                conn, storage, _write(workspace_id, brand_id, project_id, expected_version=1)
            )
            await seed_icp_document(
                conn,
                storage,
                workspace_id=workspace_id,
                brand_id=brand_id,
                project_id=project_id,
                path="audience/icp-gi-dac.md",
                body=CONFIRMED_ICP,
            )
            # The brand's own document at the same path, and another project's plan: neither is
            # this project's, so neither is listed.
            await seed_icp_document(
                conn,
                storage,
                workspace_id=workspace_id,
                brand_id=brand_id,
                path="audience/icp-gi.md",
            )
            await write_project_plan(
                conn, storage, _write(workspace_id, str(other.brand_id), other.project_id)
            )

            listed = await list_project_documents(
                conn, workspace_id=workspace_id, project_id=project_id
            )

            assert [(row.path, row.version, row.status) for row in listed] == [
                ("audience/icp-gi-dac.md", 1, "confirmed"),
                (PLAN_PATH, 2, "ready"),
            ]
            assert [row.icp_key for row in listed] == ["gi-dac", None]

    run_async(scenario())


def test_another_projects_document_is_absent_rather_than_refused(tmp_path: Any) -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            storage = FsStorage(tmp_path)
            workspace_id, project_id, brand_id = await _seed(conn)
            other = await seed_project(conn, workspace_id, name="Another project")
            written = await write_project_plan(
                conn, storage, _write(workspace_id, brand_id, project_id)
            )

            assert (
                await read_project_document(
                    conn,
                    storage,
                    workspace_id=workspace_id,
                    project_id=other.project_id,
                    document_id=written.document_id,
                )
            ) is None
            assert (
                await read_project_document(
                    conn,
                    storage,
                    workspace_id="ws_someone_else",
                    project_id=project_id,
                    document_id=written.document_id,
                )
            ) is None
            with pytest.raises(ProjectDocumentRefused) as excinfo:
                await save_project_document(
                    conn,
                    storage,
                    workspace_id=workspace_id,
                    project_id=other.project_id,
                    document_id=written.document_id,
                    body="# Not yours\n",
                    expected_revision=1,
                    user_id=USER_ID,
                )
            assert excinfo.value.code == "project_document_not_found"

    run_async(scenario())


def test_the_human_save_mints_the_next_version_with_its_edit_provenance(tmp_path: Any) -> None:
    """The human's PUT is the same append the agent makes, from the other hand: a new version of
    the same path, the old one retired, and ``user_edit`` recording whose words these are."""

    async def scenario() -> None:
        async with rollback_conn() as conn:
            storage = FsStorage(tmp_path)
            workspace_id, project_id, brand_id = await _seed(conn)
            await write_project_plan(conn, storage, _write(workspace_id, brand_id, project_id))
            second = await write_project_plan(
                conn, storage, _write(workspace_id, brand_id, project_id, expected_version=1)
            )

            saved = await save_project_document(
                conn,
                storage,
                workspace_id=workspace_id,
                project_id=project_id,
                document_id=second.document_id,
                body="# Edited by the human\n",
                expected_revision=2,
                user_id=USER_ID,
            )

            assert (saved.version, saved.status, saved.kind) == (3, "ready", PLAN_KIND)
            assert (await _row(conn, second.document_id))["status"] == "superseded"
            found = await read_project_document(
                conn,
                storage,
                workspace_id=workspace_id,
                project_id=project_id,
                document_id=saved.document_id,
            )
            assert found is not None
            _, front, body = found
            assert body == "# Edited by the human\n"
            assert front["user_edit"] == {
                "user_id": USER_ID,
                "edited_at": front["user_edit"]["edited_at"],
                "source_document_id": str(second.document_id),
                "source_version": 2,
            }
            # The agent's next write is against what the human left behind.
            assert (
                await current_plan_version(conn, workspace_id=workspace_id, project_id=project_id)
            ) == 3

            # Saving the same bytes again is a no-op, not a fourth version.
            unchanged = await save_project_document(
                conn,
                storage,
                workspace_id=workspace_id,
                project_id=project_id,
                document_id=saved.document_id,
                body="# Edited by the human\n",
                expected_revision=3,
                user_id=USER_ID,
            )
            assert (unchanged.document_id, unchanged.version) == (saved.document_id, 3)

            # A stale revision is refused — both the version the editor names being behind, and
            # the version they opened having been superseded since — and neither writes anything.
            for stale_id, stale_revision in (
                (saved.document_id, 1),
                (second.document_id, 2),
            ):
                with pytest.raises(ProjectDocumentRefused) as excinfo:
                    await save_project_document(
                        conn,
                        storage,
                        workspace_id=workspace_id,
                        project_id=project_id,
                        document_id=stale_id,
                        body="# Stale\n",
                        expected_revision=stale_revision,
                        user_id=USER_ID,
                    )
                assert excinfo.value.code == "project_document_revision_conflict"
            with pytest.raises(ProjectDocumentRefused) as excinfo:
                await save_project_document(
                    conn,
                    storage,
                    workspace_id=workspace_id,
                    project_id=project_id,
                    document_id=saved.document_id,
                    body="   \n",
                    expected_revision=3,
                    user_id=USER_ID,
                )
            assert excinfo.value.code == "project_document_body_empty"
            assert [row["version"] for row in await _rows_at(conn, workspace_id, PLAN_PATH)] == [
                1,
                2,
                3,
            ]

    run_async(scenario())


def test_a_confirmed_project_icp_the_human_edits_returns_to_proposed(tmp_path: Any) -> None:
    """Ruling I. A human's text edit is not a re-confirmation, so the approval stamp is dropped and
    the new version goes back for review — while the confirmed row it came from stays servable,
    because some project may still be pinned to exactly those bytes."""

    async def scenario() -> None:
        async with rollback_conn() as conn:
            storage = FsStorage(tmp_path)
            workspace_id, project_id, brand_id = await _seed(conn)
            confirmed, _, _ = await seed_icp_document(
                conn,
                storage,
                workspace_id=workspace_id,
                brand_id=brand_id,
                project_id=project_id,
                path="audience/icp-gi-dac.md",
                body=CONFIRMED_ICP,
            )

            saved = await save_project_document(
                conn,
                storage,
                workspace_id=workspace_id,
                project_id=project_id,
                document_id=confirmed,
                body="# GI-focused ASCs\n\nTightened by the human.\n",
                expected_revision=1,
                user_id=USER_ID,
            )

            assert (saved.version, saved.status, saved.icp_key) == (2, "proposed", "gi-dac")
            assert (await _row(conn, confirmed))["status"] == "confirmed"
            found = await read_project_document(
                conn,
                storage,
                workspace_id=workspace_id,
                project_id=project_id,
                document_id=saved.document_id,
            )
            assert found is not None
            _, front, _body = found
            assert front["status"] == "proposed"
            assert front["user_edit"]["source_version"] == 1
            for stamp in (
                "confirmed_by",
                "confirmed_at",
                "confirmed_for_project_id",
                "product_selection_version",
            ):
                assert stamp not in front
            # The model's own content survives the edit.
            assert front["icp_key"] == "gi-dac"
            assert front["product_ids"] == ["prd_aura"]

    run_async(scenario())
