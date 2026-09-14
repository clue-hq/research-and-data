"""The project's own documents against the real tables: versioned, and editable by both hands.

Two writers share one version chain here, and the tests are mostly about what each of them may
*not* do. The agent writes any path under ``project/`` through :func:`write_project_document` (and,
for the retired plan tool that is still replayable, through :func:`write_project_plan`), and it must
say which version it read — a document written against a version the human has since edited is
refused by name rather than silently overwriting their words. The human writes through
:func:`save_project_document`, the project-scoped twin of the Knowledge PUT, and their edit can
never carry another version's approval stamp forward: a ``confirmed`` project-local ICP they retype
comes back as ``proposed``.

Everything is read and written inside **one project's** scope. A document belonging to another
project is not an error here, it is *absent* — the same answer a document that never existed gets.
"""

from __future__ import annotations

from hashlib import sha256
from typing import Any, cast
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_api.arv2.project_documents import (
    DEFAULT_DOCUMENT_KIND,
    PLAN_PATH,
    PLAN_WORKSPACE_PATH,
    ProjectDocumentRefused,
    ProjectDocumentWrite,
    ProjectPlanWrite,
    current_plan_version,
    list_project_documents,
    plan_document_id,
    read_project_document,
    save_project_document,
    write_project_document,
    write_project_plan,
)
from clue_storage import StorageBackend
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

    The front matter the *platform* owns is stamped over whatever the model wrote: the version, the
    status, the scope the row is in, and who wrote it on which turn. A plan is no longer a kind —
    this one says nothing about what it is, so it is a ``document``.
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
            assert written.workspace_path == PLAN_WORKSPACE_PATH == "project/plan.md"
            assert written.document_id == plan_document_id(
                turn_id=request.turn_id,
                expected_version=None,
                body_sha256=sha256(BODY.encode("utf-8")).hexdigest(),
            )
            row = await _row(conn, written.document_id)
            assert (row["project_id"], row["folder"], row["kind"], row["status"]) == (
                project_id,
                "project",
                DEFAULT_DOCUMENT_KIND,
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
            # The stamp is six facts and no more: a document that said nothing about its kind
            # still says nothing, while the row carries the ``document`` the writer derived.
            assert "kind" not in front
            assert front["status"] == "ready"
            assert front["project_id"] == project_id
            assert front["brand_id"] == brand_id
            assert front["authored_by"] == {
                "turn_id": str(request.turn_id),
                "user_id": USER_ID,
            }
            assert isinstance(front["authored_at"], str) and front["authored_at"]
            assert body == BODY
            assert (served.version, served.kind, served.icp_key) == (
                1,
                DEFAULT_DOCUMENT_KIND,
                None,
            )

    run_async(scenario())


def test_a_document_at_any_path_keeps_its_own_words_and_takes_the_platforms_six(
    tmp_path: Any,
) -> None:
    """The generic writer, at a path nothing in the platform has ever named.

    ``notes/competitive-brief.md`` is stored under the folder its own path names, with the kind the
    document claims, and the role a human agreed to pin it under survives verbatim. Six facts are
    the platform's and are stamped over whatever the model wrote for them.
    """

    async def scenario() -> None:
        async with rollback_conn() as conn:
            storage = FsStorage(tmp_path)
            workspace_id, project_id, brand_id = await _seed(conn)
            text_ = (
                "---\nkind: brief\nrole: plan\nversion: 9\nstatus: superseded\n"
                "owner: sasha\n---\n\n# Who else is in this deal\n\nTwo vendors.\n"
            )
            request = ProjectDocumentWrite(
                workspace_id=workspace_id,
                brand_id=brand_id,
                project_id=project_id,
                turn_id=uuid4(),
                user_id=USER_ID,
                path="notes/competitive-brief.md",
                document_text=text_,
                expected_version=None,
            )

            written = await write_project_document(conn, storage, request)

            assert (written.version, written.replayed) == (1, False)
            assert written.workspace_path == "project/notes/competitive-brief.md"
            row = await _row(conn, written.document_id)
            assert (row["folder"], row["path"], row["kind"], row["status"]) == (
                "notes",
                "notes/competitive-brief.md",
                "brief",
                "ready",
            )
            found = await read_project_document(
                conn,
                storage,
                workspace_id=workspace_id,
                project_id=project_id,
                document_id=written.document_id,
            )
            assert found is not None
            _served, front, body = found
            assert (front["kind"], front["role"], front["owner"]) == ("brief", "plan", "sasha")
            assert (front["version"], front["status"]) == (1, "ready")
            assert body.startswith("# Who else is in this deal")

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
                assert "project/plan.md" in str(excinfo.value)
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

            assert (saved.version, saved.status, saved.kind) == (
                3,
                "ready",
                DEFAULT_DOCUMENT_KIND,
            )
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


# =================================================================================================
# what the two writers may not do to each other (final-review I1, I2, M2, M6, M7, M8)
# =================================================================================================


def _sql(statement: Any) -> str:
    """One statement as a single line, for order assertions."""

    return " ".join(str(statement).split())


class _RecordingConn:
    """The real connection, with every statement it runs written down in order.

    Lock *order* is the property under test and it is invisible in results — the only evidence is
    which statement ran before which. A two-connection deadlock test would be the stronger proof,
    but the DB harness here hands out one rolled-back connection, and a real deadlock would either
    hang the suite or depend on ``deadlock_timeout``; recording the order proves the same
    invariant deterministically.
    """

    def __init__(self, conn: AsyncConnection, log: list[str]) -> None:
        self._conn = conn
        self._log = log

    async def execute(self, statement: Any, parameters: Any = None, *args: Any, **kw: Any) -> Any:
        self._log.append(_sql(statement))
        return await self._conn.execute(statement, parameters, *args, **kw)

    async def scalar(self, statement: Any, parameters: Any = None, *args: Any, **kw: Any) -> Any:
        self._log.append(_sql(statement))
        return await self._conn.scalar(statement, parameters, *args, **kw)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._conn, name)


class _RecordingStorage:
    """The real storage, with each ``put`` written into the same log as the SQL around it."""

    def __init__(self, storage: StorageBackend, log: list[str]) -> None:
        self._storage = storage
        self._log = log

    async def put(self, key: str, data: bytes, *, media_type: str) -> None:
        self._log.append(f"STORAGE PUT {key}")
        await self._storage.put(key, data, media_type=media_type)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._storage, name)


class _NoRows:
    """An empty result, for the reads a concurrent twin made before the winner committed."""

    def mappings(self) -> _NoRows:
        return self

    def one_or_none(self) -> None:
        return None


class _TwinWonTheInsert:
    """Both calls read before either inserted: this one's pre-insert reads see the earlier state.

    It hides exactly two reads — the replay lookup and ``MAX(version)`` — which is what the loser
    of a genuine race sees. Everything after them is the real connection, so the INSERT really does
    hit ``ON CONFLICT (document_id) DO NOTHING`` against the row the winner already wrote.
    """

    def __init__(self, conn: AsyncConnection) -> None:
        self._conn = conn
        self._hid_replay = False
        self._hid_max = False

    async def execute(self, statement: Any, parameters: Any = None, *args: Any, **kw: Any) -> Any:
        if not self._hid_replay and "SELECT path, version FROM brand_knowledge_document" in _sql(
            statement
        ):
            self._hid_replay = True
            return _NoRows()
        return await self._conn.execute(statement, parameters, *args, **kw)

    async def scalar(self, statement: Any, parameters: Any = None, *args: Any, **kw: Any) -> Any:
        if not self._hid_max and "SELECT MAX(version)" in _sql(statement):
            self._hid_max = True
            return None
        return await self._conn.scalar(statement, parameters, *args, **kw)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._conn, name)


def _index(log: list[str], needle: str) -> int:
    for position, statement in enumerate(log):
        if needle in statement:
            return position
    raise AssertionError(f"no statement matching {needle!r} in {log}")


def test_a_second_body_in_one_turn_is_refused_rather_than_silently_discarded(
    tmp_path: Any,
) -> None:
    """I1. The same turn, the same ``expected_version``, *different words* is a rewrite.

    The replay key carries the body's digest, so the corrected plan is not mistaken for a retry of
    the first one: it mints its own id, fails the revision check against the version it just wrote,
    and comes back as the named conflict the agent recovers from by re-reading. Before the digest
    was in the key this returned ``replayed=True`` with a version number, i.e. told the agent its
    correction was stored while the first body stayed at rest.
    """

    async def scenario() -> None:
        async with rollback_conn() as conn:
            storage = FsStorage(tmp_path)
            workspace_id, project_id, brand_id = await _seed(conn)
            request = _write(workspace_id, brand_id, project_id)

            first = await write_project_plan(conn, storage, request)

            corrected = ProjectPlanWrite(
                workspace_id=request.workspace_id,
                brand_id=request.brand_id,
                project_id=request.project_id,
                turn_id=request.turn_id,
                user_id=request.user_id,
                body=BODY + "\n2. Name Aura and Lumen.\n",
                expected_version=request.expected_version,
            )
            with pytest.raises(ProjectDocumentRefused) as excinfo:
                await write_project_plan(conn, storage, corrected)

            assert excinfo.value.code == "project_document_revision_conflict"
            assert "version 1" in str(excinfo.value)
            # An honest retry — the identical call — is still a replay, on its own row.
            again = await write_project_plan(conn, storage, request)
            assert again.replayed is True
            assert (again.document_id, again.version) == (first.document_id, 1)
            assert [row["version"] for row in await _rows_at(conn, workspace_id, PLAN_PATH)] == [1]

    run_async(scenario())


def test_both_writers_take_the_projects_lock_before_any_document_row(tmp_path: Any) -> None:
    """I2. One total lock order — project row first, always — or the two writers deadlock.

    The agent used to take no lock and retire the previous version last, while the human locked the
    document row first and the project row second; that cycle aborts one side with ``40P01``, which
    is an ``OperationalError`` neither writer's ``IntegrityError`` handler catches, so the human
    gets a 500 and the agent an untyped exception instead of "someone wrote first".
    """

    async def scenario() -> None:
        async with rollback_conn() as conn:
            storage = FsStorage(tmp_path)
            workspace_id, project_id, brand_id = await _seed(conn)

            agent_log: list[str] = []
            written = await write_project_plan(
                cast("AsyncConnection", _RecordingConn(conn, agent_log)),
                storage,
                _write(workspace_id, brand_id, project_id),
            )
            project_lock = _index(agent_log, "FROM project WHERE workspace_id")
            assert "FOR UPDATE" in agent_log[project_lock]
            assert project_lock < _index(agent_log, "SELECT MAX(version)")
            assert project_lock < _index(agent_log, "INSERT INTO brand_knowledge_document")

            human_log: list[str] = []
            await save_project_document(
                cast("AsyncConnection", _RecordingConn(conn, human_log)),
                storage,
                workspace_id=workspace_id,
                project_id=project_id,
                document_id=written.document_id,
                body="# The human's plan\n",
                expected_revision=1,
                user_id=USER_ID,
            )
            human_project_lock = _index(human_log, "FROM project WHERE workspace_id")
            assert "FOR UPDATE" in human_log[human_project_lock]
            document_lock = _index(
                human_log,
                "FROM brand_knowledge_document WHERE workspace_id = :workspace_id "
                "AND project_id = :project_id AND document_id = :document_id FOR UPDATE",
            )
            assert human_project_lock < document_lock

    run_async(scenario())


def test_the_bytes_are_stored_only_after_the_row_that_cites_them(tmp_path: Any) -> None:
    """M2. ``storage.put`` last, so a refused write leaves no unreferenced object behind.

    The artifact *row* still precedes the INSERT — the document row references it — but it lives
    inside the transaction and rolls back with it, while an object already written to the store
    does not and nothing sweeps it.
    """

    async def scenario() -> None:
        async with rollback_conn() as conn:
            workspace_id, project_id, brand_id = await _seed(conn)

            agent_log: list[str] = []
            storage = cast("StorageBackend", _RecordingStorage(FsStorage(tmp_path), agent_log))
            written = await write_project_plan(
                cast("AsyncConnection", _RecordingConn(conn, agent_log)),
                storage,
                _write(workspace_id, brand_id, project_id),
            )
            document_insert = _index(agent_log, "INSERT INTO brand_knowledge_document")
            assert _index(agent_log, "INSERT INTO artifact") < document_insert
            assert document_insert < _index(agent_log, "STORAGE PUT")

            human_log: list[str] = []
            human_storage = cast(
                "StorageBackend", _RecordingStorage(FsStorage(tmp_path), human_log)
            )
            await save_project_document(
                cast("AsyncConnection", _RecordingConn(conn, human_log)),
                human_storage,
                workspace_id=workspace_id,
                project_id=project_id,
                document_id=written.document_id,
                body="# The human's plan\n",
                expected_revision=1,
                user_id=USER_ID,
            )
            human_insert = _index(human_log, "INSERT INTO brand_knowledge_document")
            put = _index(human_log, "STORAGE PUT")
            assert human_insert < put
            # ...and after the version it replaces has been retired.
            assert _index(human_log, "SET status = 'superseded'") < put

    run_async(scenario())


def test_every_one_of_this_projects_documents_is_human_editable(tmp_path: Any) -> None:
    """No kind gate on the human's surface (founder ruling 2026-09-14).

    The gate used to admit three kinds, so a project document of any other kind came back as "no
    such editable document" — which was the right answer while the agent could only write three
    shapes. It writes anything now, and a document this project owns is a document its human may
    edit: the save mints version 2 of the very same path.
    """

    async def scenario() -> None:
        async with rollback_conn() as conn:
            storage = FsStorage(tmp_path)
            workspace_id, project_id, brand_id = await _seed(conn)
            brief, _, _ = await seed_icp_document(
                conn,
                storage,
                workspace_id=workspace_id,
                brand_id=brand_id,
                project_id=project_id,
                path="project/brief.md",
                kind="design-brief",
                status="ready",
                body="# Brief\n\nBody.\n",
            )

            saved = await save_project_document(
                conn,
                storage,
                workspace_id=workspace_id,
                project_id=project_id,
                document_id=brief,
                body="# Edited by the human\n",
                expected_revision=1,
                user_id=USER_ID,
            )

            assert (saved.version, saved.kind, saved.status) == (2, "design-brief", "ready")
            assert [
                row["version"] for row in await _rows_at(conn, workspace_id, "project/brief.md")
            ] == [1, 2]

    run_async(scenario())


def test_the_front_matter_states_the_version_the_row_holds(tmp_path: Any) -> None:
    """M7 / ruling P. The skill tells the agent to pass "the version of the file you read"; this
    is what puts that number in the file, on both writers' versions."""

    async def scenario() -> None:
        async with rollback_conn() as conn:
            storage = FsStorage(tmp_path)
            workspace_id, project_id, brand_id = await _seed(conn)

            async def front_of(document_id: UUID) -> dict[str, Any]:
                found = await read_project_document(
                    conn,
                    storage,
                    workspace_id=workspace_id,
                    project_id=project_id,
                    document_id=document_id,
                )
                assert found is not None
                return found[1]

            first = await write_project_plan(
                conn, storage, _write(workspace_id, brand_id, project_id)
            )
            assert (await front_of(first.document_id))["version"] == first.version == 1

            second = await write_project_plan(
                conn,
                storage,
                _write(workspace_id, brand_id, project_id, expected_version=1, body="# v2\n"),
            )
            assert (await front_of(second.document_id))["version"] == second.version == 2

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
            assert (await front_of(saved.document_id))["version"] == saved.version == 3

    run_async(scenario())


def test_a_twin_that_lost_the_insert_reports_a_replay(tmp_path: Any) -> None:
    """M8. ``ON CONFLICT DO NOTHING`` matched: this call published nothing, and says so.

    It is the same logical event as the sequential replay short-circuit, and used to be reported as
    its opposite — ``replayed=False``, i.e. "I wrote this version" — for a version another call
    wrote.
    """

    async def scenario() -> None:
        async with rollback_conn() as conn:
            storage = FsStorage(tmp_path)
            workspace_id, project_id, brand_id = await _seed(conn)
            request = _write(workspace_id, brand_id, project_id)
            winner = await write_project_plan(conn, storage, request)

            loser = await write_project_plan(
                cast("AsyncConnection", _TwinWonTheInsert(conn)), storage, request
            )

            assert loser.replayed is True
            assert (loser.document_id, loser.version) == (winner.document_id, 1)
            assert [row["version"] for row in await _rows_at(conn, workspace_id, PLAN_PATH)] == [1]

    run_async(scenario())


async def _versions_in(
    conn: AsyncConnection, workspace_id: str, project_id: str, path: str
) -> list[int]:
    return [
        int(row["version"])
        for row in (
            await conn.execute(
                text(
                    "SELECT version FROM brand_knowledge_document "
                    "WHERE workspace_id = :w AND project_id = :p AND path = :path "
                    "ORDER BY version"
                ),
                {"w": workspace_id, "p": project_id, "path": path},
            )
        )
        .mappings()
        .all()
    ]


def test_the_replay_read_cannot_answer_one_project_with_another_projects_row(tmp_path: Any) -> None:
    """M1. The replay lookup is scoped like every other read here — scope is part of identity.

    Read by id alone, a row belonging to another project answered this project's write: the caller
    was handed a path and a version for a document its project does not own, while its own scope
    stayed empty. Scoped, the write is refused by name and the project is still, honestly, without
    a plan.
    """

    async def scenario() -> None:
        async with rollback_conn() as conn:
            storage = FsStorage(tmp_path)
            workspace_id, project_id, brand_id = await _seed(conn)
            other = await seed_project(conn, workspace_id, name="Another project")
            request = _write(workspace_id, brand_id, project_id)
            await write_project_plan(conn, storage, request)

            with pytest.raises(ProjectDocumentRefused) as excinfo:
                await write_project_plan(
                    conn,
                    storage,
                    ProjectPlanWrite(
                        workspace_id=workspace_id,
                        brand_id=str(other.brand_id),
                        project_id=other.project_id,
                        turn_id=request.turn_id,
                        user_id=request.user_id,
                        body=request.body,
                        expected_version=None,
                    ),
                )

            assert excinfo.value.code == "project_document_version_race"
            assert await _versions_in(conn, workspace_id, other.project_id, PLAN_PATH) == []
            assert await _versions_in(conn, workspace_id, project_id, PLAN_PATH) == [1]

    run_async(scenario())
