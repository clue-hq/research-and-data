"""The project library: one project's settled state, compiled once and refreshed on change.

The turn's seeds compile ``status.md``, ``decisions.md`` and the project's documents *again for
every turn*, and pin them per turn. The library does it the other way round: the same state is
compiled once, beside the threads, at ``<ws>/projects/<project>/library/``, and every thread of
that project mounts that one frozen tree read-only at ``project/``. It is rewritten only when a
cheap digest over the rows it is compiled from moves.

Three properties are load-bearing and are asserted here against real rows and a real filesystem:

* **Digest-refreshed.** Two ``ensure`` calls over an unmoved project write nothing at all — the
  tree keeps its inode and its mtime. Record one ``project_state`` statement and the digest moves,
  the tree is replaced, and ``decisions.md`` carries the new words.
* **One version per path (W3).** The library holds exactly one file per document path: the
  project's *pinned* ICP version, even when a newer version has been authored at that path. No
  version-qualified ``.vN`` sibling exists here — that spelling belongs to the per-turn seeds.
* **Artifacts by reference (W4).** ``artifacts/index.json`` names each design document by id,
  kind, title, status, version, time and origin thread. Never its scene or its pages.

Postgres stays the truth: the tree is a rendering of those rows, and nothing server-side reads it
to decide anything.
"""

from __future__ import annotations

import json
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_agents import MountRequest, WorkspacePolicy
from clue_api.agent_turn_wiring import DurableAgentArtifactStore
from clue_api.project_context_files import PROJECT_LIBRARY_PREFIX
from clue_api.project_library import (
    compile_project_library,
    ensure_project_library,
    project_library_digest,
)
from clue_core import OnboardingInputKind
from clue_research.stage0 import StatementRoute, record_statement, submit_onboarding_input
from clue_spine import Project
from tests._workspace import seed_project
from tests.agents.workspace_helpers import (
    DEFAULT_READABLE_PREFIXES,
    EXECUTION_ID,
    make_factory,
    policy,
)
from tests.api.test_project_context_files_db import (
    _NEWER_ICP,
    _PINNED_ICP,
    _pin_project_icp,
    _seed_project_document,
)
from tests.api.test_stage0_setup_db import _MemoryStorage
from tests.db.conftest import run_async
from tests.profiling.conftest import (
    conn_session_factory,
    migrated_db,  # noqa: F401 -- exposes the fixture to this test module
    rollback_conn,
)


@pytest.fixture
def require_profiling_db(request: pytest.FixtureRequest) -> None:
    if not request.getfixturevalue("migrated_db"):
        pytest.skip("requires a migrated per-branch Postgres database")


pytestmark = pytest.mark.usefixtures("require_profiling_db")

_ANSWER = "We only sell to ambulatory GI groups that own their anesthesia service line."
_QUOTE = "ambulatory GI groups that own their anesthesia service line"
#: Page content that must never reach the artifact index — the index is by reference.
_PAGE_MARKER = "SECRET-SCENE-CONTENT"


def _library_policy() -> WorkspacePolicy:
    """A policy that can read the ``project`` mount and files the size of a real status file."""

    return policy(
        readable=(*DEFAULT_READABLE_PREFIXES, "project"),
        max_total_bytes=1_000_000,
        max_file_bytes=200_000,
        max_file_count=200,
    )


async def _seed_statement(
    conn: AsyncConnection,
    project: Project,
    artifacts: DurableAgentArtifactStore,
) -> None:
    """One ``project_state`` statement, through the real capture-then-record write path."""

    ref = await artifacts.persist_body(
        workspace_id=project.workspace_id, data=_ANSWER.encode(), media_type="text/plain"
    )
    captured = await submit_onboarding_input(
        conn,
        workspace_id=project.workspace_id,
        brand_id=project.brand_id,
        project_id=project.project_id,
        kind=OnboardingInputKind.USER_TURN,
        artifact_key=ref.artifact_key,
        content_sha256=ref.sha256,
        actor="human",
    )
    start = _ANSWER.index(_QUOTE)
    await record_statement(
        conn,
        onboarding_input_id=captured.onboarding_input_id,
        workspace_id=project.workspace_id,
        brand_id=project.brand_id,
        project_id=project.project_id,
        route_kind=StatementRoute.PROJECT_STATE,
        route_key="target_segment",
        quote=_QUOTE,
        quote_start=start,
        quote_end=start + len(_QUOTE),
        created_by_actor="human",
    )


async def _seed_design_document(
    conn: AsyncConnection,
    project: Project,
    *,
    title: str,
) -> tuple[str, str]:
    """One design document reachable from this project, through a thread's leg.

    The minimal shape of the genweb fixture (``test_genweb_leg_document_birth_db``): a design
    document belongs to a project only through the leg of one of the project's threads, so the
    thread, the execution the leg hangs off, the document and the leg are all seeded here.
    """

    thread_id = f"thr-lib-{uuid4().hex[:8]}"
    await conn.execute(
        text("INSERT INTO agent_thread (id, workspace_id, project_id) VALUES (:id, :ws, :project)"),
        {"id": thread_id, "ws": project.workspace_id, "project": project.project_id},
    )
    execution_id = uuid4()
    await conn.execute(
        text(
            "INSERT INTO execution "
            "(id, workspace_id, project_id, started_by, parameter_manifest_hash, pin_manifest_hash)"
            " VALUES (:id, :ws, :project, 'human', :hash, :hash)"
        ),
        {
            "id": execution_id,
            "ws": project.workspace_id,
            "project": project.project_id,
            "hash": "0" * 64,
        },
    )
    document_id = f"doc_{uuid4().hex[:12]}"
    scene = {
        "id": document_id,
        "title": title,
        "schema_version": 1,
        "meta": {"artifact_type": "landing_page"},
        "pages": [{"id": "page-1", "blocks": [{"text": _PAGE_MARKER}]}],
    }
    await conn.execute(
        text(
            "INSERT INTO design_document "
            "(id, workspace_id, title, status, doc_kind, current_scene_json, current_version) "
            "VALUES (:id, :ws, :title, 'draft', 'web', CAST(:scene AS jsonb), 3)"
        ),
        {
            "id": document_id,
            "ws": project.workspace_id,
            "title": title,
            "scene": json.dumps(scene),
        },
    )
    await conn.execute(
        text(
            "INSERT INTO design_leg "
            "(id, workspace_id, thread_id, parent_execution_id, state, document_id) "
            "VALUES (:id, :ws, :thread, :execution, 'open_awaiting_user', :document)"
        ),
        {
            "id": uuid4(),
            "ws": project.workspace_id,
            "thread": thread_id,
            "execution": execution_id,
            "document": document_id,
        },
    )
    return document_id, thread_id


async def _seed(
    conn: AsyncConnection, label: str
) -> tuple[Project, _MemoryStorage, DurableAgentArtifactStore]:
    workspace_id = f"plib-{label}-{uuid4().hex[:6]}"
    project = await seed_project(conn, workspace_id, name=f"Project library {label}")
    storage = _MemoryStorage()
    artifacts = DurableAgentArtifactStore(storage=storage, conn_factory=conn_session_factory(conn))
    return project, storage, artifacts


def test_the_library_is_rebuilt_only_when_a_contributing_row_changes(tmp_path: Path) -> None:
    """The whole point of the library: it is compiled once, not once per turn.

    A turn that changed nothing must not churn a tree every other thread of the project is
    holding descriptors on — so the second ``ensure`` over an unmoved project writes nothing at
    all, and the directory keeps its inode and its mtime. A recorded decision moves the digest,
    and the next ``ensure`` installs a generation whose ``decisions.md`` carries the new words.
    """

    async def scenario() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            project, storage, artifacts = await _seed(conn, "digest")
            ws, project_id = project.workspace_id, project.project_id
            await _seed_project_document(
                conn,
                project,
                artifacts,
                path="audience/icp-gi-dac.md",
                body=_PINNED_ICP,
                version=1,
                status="confirmed",
            )

            root, factory, _sink = make_factory(tmp_path)
            try:
                first = await ensure_project_library(
                    conn,
                    storage,
                    artifacts,
                    factory,
                    workspace_id=ws,
                    project_id=project_id,
                )
                tree = root / ws / "projects" / project_id / "library"
                assert (tree / "status.md").is_file()
                assert (tree / "decisions.md").is_file()
                assert "Nothing recorded yet." in (tree / "decisions.md").read_text()
                index = json.loads((tree / "index.json").read_text())
                assert index["card_kind"] == "project_library_index"
                assert index["schema_version"] == "1"
                assert index["project_id"] == project_id
                assert index["library_sha256"] == first.digest
                assert index["artifacts"] == 0
                assert {entry["workspace_path"] for entry in index["files"]} == {
                    f"{PROJECT_LIBRARY_PREFIX}status.md",
                    f"{PROJECT_LIBRARY_PREFIX}decisions.md",
                    f"{PROJECT_LIBRARY_PREFIX}artifacts/index.json",
                    f"{PROJECT_LIBRARY_PREFIX}audience/icp-gi-dac.md",
                }

                # A second ensure over an unmoved project writes nothing at all.
                before = tree.stat()
                second = await ensure_project_library(
                    conn,
                    storage,
                    artifacts,
                    factory,
                    workspace_id=ws,
                    project_id=project_id,
                )
                after = tree.stat()
                assert second.digest == first.digest
                assert (after.st_ino, after.st_mtime_ns) == (before.st_ino, before.st_mtime_ns)
                assert [child.name for child in tree.parent.iterdir()] == ["library"]

                # …and a recorded decision moves the digest, so the next ensure replaces it.
                await _seed_statement(conn, project, artifacts)
                moved = await project_library_digest(conn, workspace_id=ws, project_id=project_id)
                assert moved != first.digest
                third = await ensure_project_library(
                    conn,
                    storage,
                    artifacts,
                    factory,
                    workspace_id=ws,
                    project_id=project_id,
                )
                assert third.digest == moved
                assert tree.stat().st_ino != before.st_ino
                assert _QUOTE in (tree / "decisions.md").read_text()
                assert json.loads((tree / "index.json").read_text())["library_sha256"] == moved

                # The mount serves it read-only, under the ``project`` prefix the policy grants.
                lease = factory.acquire(
                    workspace_id=ws,
                    project_id=project_id,
                    thread_id="thread-1",
                    execution_id=EXECUTION_ID,
                    policy=_library_policy(),
                    mounts=MountRequest(project_library=True),
                )
                status = lease.backend.read_text_sync(f"{PROJECT_LIBRARY_PREFIX}status.md")
                assert f"# Project status — {project.name}" in status
                mounted_index = json.loads(
                    lease.backend.read_text_sync(f"{PROJECT_LIBRARY_PREFIX}index.json")
                )
                assert mounted_index["library_sha256"] == moved
            finally:
                factory.close()

    run_async(scenario())


def test_the_library_shows_one_version_per_document_and_the_pinned_icp_wins(
    tmp_path: Path,
) -> None:
    """W3: one file per path, and for the ICP that file is the version the human agreed to.

    The per-turn seeds carry both versions — the pinned one at the plain name and the newer one
    version-qualified beside it. The library does not: it is the project's *settled* state, so it
    holds exactly one file per path, and ``status.md`` says in words that a newer version exists
    rather than naming a ``.vN`` file that is not there.
    """

    async def scenario() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            project, storage, artifacts = await _seed(conn, "pin")
            ws, project_id = project.workspace_id, project.project_id
            pinned_id = await _seed_project_document(
                conn,
                project,
                artifacts,
                path="audience/icp-gi-dac.md",
                body=_PINNED_ICP,
                version=1,
                status="confirmed",
            )
            await _pin_project_icp(conn, project, pinned_id, icp_key="gi-dac")
            await _seed_project_document(
                conn,
                project,
                artifacts,
                path="audience/icp-gi-dac.md",
                body=_NEWER_ICP,
                version=2,
                status="proposed",
            )

            snapshot = await compile_project_library(
                conn, storage, artifacts, workspace_id=ws, project_id=project_id
            )
            files = {file.path: file for file in snapshot.files}
            assert "audience/icp-gi-dac.v2.md" not in files
            assert files["audience/icp-gi-dac.md"].body == _PINNED_ICP.encode()
            assert files["audience/icp-gi-dac.md"].version == 1
            assert files["audience/icp-gi-dac.md"].status == "confirmed"

            entries = {entry.path: entry for entry in snapshot.index.files}
            assert entries["audience/icp-gi-dac.md"].version == 1
            assert entries["audience/icp-gi-dac.md"].status == "confirmed"
            assert (
                entries["audience/icp-gi-dac.md"].workspace_path
                == f"{PROJECT_LIBRARY_PREFIX}audience/icp-gi-dac.md"
            )

            status = files["status.md"].body.decode()
            assert "icp-gi-dac.v2.md" not in status
            assert "version 1, confirmed" in status
            assert "newer version v2 proposed" in status

            root, factory, _sink = make_factory(tmp_path)
            try:
                await ensure_project_library(
                    conn, storage, artifacts, factory, workspace_id=ws, project_id=project_id
                )
                tree = root / ws / "projects" / project_id / "library"
                assert (tree / "audience" / "icp-gi-dac.md").read_text() == _PINNED_ICP
                assert not (tree / "audience" / "icp-gi-dac.v2.md").exists()
                assert [child.name for child in (tree / "audience").iterdir()] == ["icp-gi-dac.md"]
            finally:
                factory.close()

    run_async(scenario())


def test_a_brand_scoped_pin_is_this_projects_icp_in_its_own_library(tmp_path: Path) -> None:
    """The pin names the bytes, whatever scope authored them.

    A project that pinned the *brand's* ICP has no project-scoped document at that path, and the
    brand library is shared by every project of the brand — so the older version this project
    agreed to is readable there under no name at all once the brand publishes a newer one. The
    project's own library is where it stays readable, at the plain project path.
    """

    async def scenario() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            project, storage, artifacts = await _seed(conn, "brandpin")
            ws, project_id = project.workspace_id, project.project_id
            brand_document_id = await _seed_project_document(
                conn,
                project,
                artifacts,
                path="audience/icp-gi.md",
                body=_PINNED_ICP,
                version=1,
                status="confirmed",
                project_scoped=False,
            )
            await _pin_project_icp(conn, project, brand_document_id, icp_key="gi")

            snapshot = await compile_project_library(
                conn, storage, artifacts, workspace_id=ws, project_id=project_id
            )
            files = {file.path: file for file in snapshot.files}
            assert files["audience/icp-gi.md"].body == _PINNED_ICP.encode()
            assert files["audience/icp-gi.md"].version == 1

    run_async(scenario())


def test_the_artifact_index_lists_design_documents_by_reference(tmp_path: Path) -> None:
    """W4: the library names the project's artifacts; it never carries their content.

    A design document's scene is megabytes of engine JSON that no turn should read as context,
    and it is served by the editor, not by a markdown tree. The index is the reference: enough to
    name the artifact and ask for it, and nothing of what is inside it.
    """

    async def scenario() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            project, storage, artifacts = await _seed(conn, "artifacts")
            ws, project_id = project.workspace_id, project.project_id
            document_id, thread_id = await _seed_design_document(
                conn, project, title="Insight Health landing page"
            )

            root, factory, _sink = make_factory(tmp_path)
            try:
                snapshot = await ensure_project_library(
                    conn, storage, artifacts, factory, workspace_id=ws, project_id=project_id
                )
                assert snapshot.index.artifacts == 1
                tree = root / ws / "projects" / project_id / "library"
                raw = (tree / "artifacts" / "index.json").read_text()
                document = json.loads(raw)
                assert document["schema_version"] == "1"
                assert document["project_id"] == project_id
                assert len(document["artifacts"]) == 1
                entry = document["artifacts"][0]
                assert entry["id"] == document_id
                assert entry["doc_kind"] == "web"
                assert entry["title"] == "Insight Health landing page"
                assert entry["status"] == "draft"
                assert entry["current_version"] == 3
                assert entry["origin_thread_id"] == thread_id
                assert entry["artifact_type"] == "landing_page"
                assert isinstance(entry["updated_at"], str) and entry["updated_at"]
                # By reference: no scene, no pages, nothing of the document's content.
                assert set(entry) == {
                    "id",
                    "doc_kind",
                    "title",
                    "status",
                    "current_version",
                    "updated_at",
                    "origin_thread_id",
                    "artifact_type",
                }
                assert _PAGE_MARKER not in raw
                assert "pages" not in raw

                # A new artifact is a contributing row: the digest moves and the index follows.
                before = await project_library_digest(conn, workspace_id=ws, project_id=project_id)
                second_id, _second_thread = await _seed_design_document(
                    conn, project, title="Insight Health ad"
                )
                assert (
                    await project_library_digest(conn, workspace_id=ws, project_id=project_id)
                    != before
                )
                await ensure_project_library(
                    conn, storage, artifacts, factory, workspace_id=ws, project_id=project_id
                )
                refreshed = json.loads((tree / "artifacts" / "index.json").read_text())
                assert {item["id"] for item in refreshed["artifacts"]} == {
                    document_id,
                    second_id,
                }
            finally:
                factory.close()

    run_async(scenario())
