"""``read_artifact@1`` against the rows the gallery itself reads (DB-gated).

What would rot here is a *containment* answer. A design document carries a workspace, not a
project, so "is this artifact ours?" is a join through the legs of this project's threads — the
same join the rail's feed uses. Get it wrong in the loose direction and the agent opens another
project's landing page inside this conversation; get it wrong in the strict direction and it tells
the human their own artifact does not exist. Both are confident sentences, not errors, so the rows
are seeded by hand and the tool's answers are asserted against them.

The other thing asserted here is the cap. ``section="content"`` serves the document's page JSON as
text, and a real web document is far larger than one receipt may carry, so the read must cut at
``READ_REFERENCES_BUDGET_BYTES`` and *say* that it cut — a silently truncated page read as a whole
one is how an agent comes to describe a section that was never in its context.
"""

from __future__ import annotations

import json
from typing import Any
from uuid import NAMESPACE_URL, uuid5

import pytest
from sqlalchemy import text

from clue_api.artifact_read_tools import READ_REFERENCES_BUDGET_BYTES, ReadArtifactTool
from clue_core import new_operation_id
from clue_design import legs as design_legs
from clue_toolbelt import PreconditionFailed, ToolContext, ToolResult
from tests._identity import seed_principal
from tests._workspace import seed_project as _seed_project_row
from tests.db.conftest import run_async
from tests.profiling.conftest import (
    conn_session_factory,
    migrated_db,  # noqa: F401 -- exposes the fixture to this test module
    rollback_conn,
)

USER_ID = "usr_read_artifact_test"


@pytest.fixture
def require_artifact_db(request: pytest.FixtureRequest) -> None:
    if not request.getfixturevalue("migrated_db"):
        pytest.skip("requires a migrated per-branch Postgres database")


async def _seed_design_document(
    conn: Any,
    *,
    workspace_id: str,
    document_id: str,
    doc_kind: str = "web",
    title: str = "Landing page",
    scene: dict[str, Any] | None = None,
) -> None:
    await conn.execute(
        text(
            "INSERT INTO design_document"
            " (id, workspace_id, title, status, doc_kind, current_scene_json, current_version)"
            " VALUES (:id, :w, :title, 'draft', :kind, CAST(:scene AS jsonb), 3)"
        ),
        {
            "id": document_id,
            "w": workspace_id,
            "title": title,
            "kind": doc_kind,
            "scene": json.dumps(scene if scene is not None else {}),
        },
    )


async def _seed_thread(conn: Any, *, workspace_id: str, project_id: str, thread_id: str) -> str:
    await conn.execute(
        text(
            "INSERT INTO agent_thread (id, workspace_id, project_id, created_by_user_id) "
            "VALUES (:id, :workspace, :project, :user)"
        ),
        {"id": thread_id, "workspace": workspace_id, "project": project_id, "user": USER_ID},
    )
    return thread_id


async def _seed_execution(conn: Any, *, workspace_id: str, project_id: str, key: str) -> Any:
    """One ``execution`` row — the turn's own coordinate, which is where the project comes from."""

    execution_id = uuid5(NAMESPACE_URL, f"read-artifact:{workspace_id}:{key}")
    await conn.execute(
        text(
            "INSERT INTO execution "
            "(id, workspace_id, project_id, started_by, parameter_manifest_hash, "
            " pin_manifest_hash) "
            "VALUES (:id, :workspace, :project, 'agent', :hash, :hash)"
        ),
        {"id": execution_id, "workspace": workspace_id, "project": project_id, "hash": "0" * 64},
    )
    return execution_id


async def _seed_leg(
    conn: Any,
    *,
    workspace_id: str,
    thread_id: str,
    execution_id: Any,
    document_id: str,
) -> None:
    leg = await design_legs.open_leg(
        conn,
        workspace_id=workspace_id,
        thread_id=thread_id,
        parent_execution_id=execution_id,
        document_id=document_id,
    )
    # Spec §3.2: the leg's document SET is what the feed derives from, and the shipped
    # tool always writes it (position 0 for a single-document leg). The DAL writes only
    # the column, so the seed adds the child row production guarantees.
    await design_legs.add_leg_documents(
        conn,
        workspace_id=workspace_id,
        leg_id=str(leg["id"]),
        documents=[design_legs.LegDocumentSpec(document_id=document_id, position=0)],
    )


def _ctx(conn: Any, *, workspace_id: str, execution_id: Any) -> ToolContext:
    return ToolContext(
        workspace_id=workspace_id,
        actor="agent",
        conn_factory=conn_session_factory(conn),
        operation_id=new_operation_id(),
        execution_id=execution_id,
    )


async def _read(
    conn: Any,
    *,
    workspace_id: str,
    execution_id: Any,
    artifact_id: str,
    section: str = "summary",
) -> dict[str, Any]:
    tool = ReadArtifactTool(conn_factory=conn_session_factory(conn))
    inputs = tool.input_model.model_validate({"artifact_id": artifact_id, "section": section})
    result = await tool.invoke(
        inputs, _ctx(conn, workspace_id=workspace_id, execution_id=execution_id)
    )
    assert isinstance(result, ToolResult)
    return dict(result.references)


async def _gallery(
    conn: Any,
    *,
    workspace_id: str,
    project_id: str,
    thread_id: str,
    document_id: str,
    **kwargs: Any,
) -> Any:
    """A document this project's own thread worked on, plus the execution a turn would carry."""

    await _seed_design_document(conn, workspace_id=workspace_id, document_id=document_id, **kwargs)
    await _seed_thread(conn, workspace_id=workspace_id, project_id=project_id, thread_id=thread_id)
    execution_id = await _seed_execution(
        conn, workspace_id=workspace_id, project_id=project_id, key=thread_id
    )
    await _seed_leg(
        conn,
        workspace_id=workspace_id,
        thread_id=thread_id,
        execution_id=execution_id,
        document_id=document_id,
    )
    return execution_id


def test_the_summary_names_the_artifact_and_carries_no_body(require_artifact_db: None) -> None:
    """The default read: everything the gallery card knows, and not one byte of the page."""

    del require_artifact_db

    async def scenario() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            project = await _seed_project_row(conn, "ws-read-artifact", name="Read artifact")
            await seed_principal(conn, workspace_id=project.workspace_id, user_id=USER_ID)
            execution_id = await _gallery(
                conn,
                workspace_id=project.workspace_id,
                project_id=project.project_id,
                thread_id="thr_read_artifact",
                document_id="doc_read_artifact",
                scene={"title": "Landing page", "pages": [{"id": "p1"}]},
            )

            references = await _read(
                conn,
                workspace_id=project.workspace_id,
                execution_id=execution_id,
                artifact_id="doc_read_artifact",
            )

            assert references["artifact_id"] == "doc_read_artifact"
            assert references["kind"] == "web"
            assert references["title"] == "Landing page"
            assert references["status"] == "draft"
            assert references["current_version_id"] == "3"
            assert references["origin_thread_id"] == "thr_read_artifact"
            assert references["updated_at"]
            # The summary is a *summary*: the page never rides along unasked.
            assert references["body_text"] == ""
            assert references["body_truncated"] is False

    run_async(scenario())


def test_a_scene_document_is_served_as_the_ad_kind(require_artifact_db: None) -> None:
    """The rail's own mapping, not a second one: ``scene`` is what a marketer calls an ad."""

    del require_artifact_db

    async def scenario() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            project = await _seed_project_row(conn, "ws-read-artifact-ad", name="Read ad")
            await seed_principal(conn, workspace_id=project.workspace_id, user_id=USER_ID)
            execution_id = await _gallery(
                conn,
                workspace_id=project.workspace_id,
                project_id=project.project_id,
                thread_id="thr_read_ad",
                document_id="doc_read_ad",
                doc_kind="scene",
                title="Q4 ad set",
            )

            references = await _read(
                conn,
                workspace_id=project.workspace_id,
                execution_id=execution_id,
                artifact_id="doc_read_ad",
            )

            assert references["kind"] == "ad"
            assert references["title"] == "Q4 ad set"

    run_async(scenario())


def test_the_content_section_serves_the_documents_own_json(require_artifact_db: None) -> None:
    """A small page comes back whole, in the canonical text the receipt is measured in."""

    del require_artifact_db

    async def scenario() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            project = await _seed_project_row(conn, "ws-read-artifact-body", name="Read body")
            await seed_principal(conn, workspace_id=project.workspace_id, user_id=USER_ID)
            scene = {"title": "Landing page", "pages": [{"id": "p1", "blocks": ["hero"]}]}
            execution_id = await _gallery(
                conn,
                workspace_id=project.workspace_id,
                project_id=project.project_id,
                thread_id="thr_read_body",
                document_id="doc_read_body",
                scene=scene,
            )

            references = await _read(
                conn,
                workspace_id=project.workspace_id,
                execution_id=execution_id,
                artifact_id="doc_read_body",
                section="content",
            )

            assert references["body_text"] == json.dumps(
                scene, sort_keys=True, separators=(",", ":")
            )
            assert references["body_truncated"] is False

    run_async(scenario())


def test_an_oversized_page_is_cut_at_the_budget_and_says_so(require_artifact_db: None) -> None:
    """The cap is the cap, and the flag is how the agent knows the rest exists."""

    del require_artifact_db

    async def scenario() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            project = await _seed_project_row(conn, "ws-read-artifact-cap", name="Read cap")
            await seed_principal(conn, workspace_id=project.workspace_id, user_id=USER_ID)
            # Comfortably past the budget: one block per kilobyte, twenty-odd times over.
            scene = {"pages": [{"id": f"p{i}", "text": "x" * 1024} for i in range(20)]}
            whole = json.dumps(scene, sort_keys=True, separators=(",", ":"))
            assert len(whole.encode()) > READ_REFERENCES_BUDGET_BYTES
            execution_id = await _gallery(
                conn,
                workspace_id=project.workspace_id,
                project_id=project.project_id,
                thread_id="thr_read_cap",
                document_id="doc_read_cap",
                scene=scene,
            )

            references = await _read(
                conn,
                workspace_id=project.workspace_id,
                execution_id=execution_id,
                artifact_id="doc_read_cap",
                section="content",
            )

            body = references["body_text"]
            assert references["body_truncated"] is True
            assert len(body.encode()) <= READ_REFERENCES_BUDGET_BYTES
            assert whole.startswith(body)

    run_async(scenario())


def test_another_projects_artifact_is_refused_as_missing(require_artifact_db: None) -> None:
    """THE requirement: containment is the leg join, and a neighbour's document is not ours.

    Same workspace, same tenant — so tenancy alone would serve it. The refusal is the *project*
    boundary, and it is the same code a document that never existed gets: the read never tells one
    project that another project's artifact is out there.
    """

    del require_artifact_db

    async def scenario() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            ours = await _seed_project_row(conn, "ws-read-artifact-cross", name="Ours")
            theirs = await _seed_project_row(conn, ours.workspace_id, name="Theirs")
            await seed_principal(conn, workspace_id=ours.workspace_id, user_id=USER_ID)
            await _gallery(
                conn,
                workspace_id=ours.workspace_id,
                project_id=theirs.project_id,
                thread_id="thr_read_theirs",
                document_id="doc_read_theirs",
            )
            our_execution = await _seed_execution(
                conn, workspace_id=ours.workspace_id, project_id=ours.project_id, key="ours"
            )

            with pytest.raises(PreconditionFailed) as refused:
                await _read(
                    conn,
                    workspace_id=ours.workspace_id,
                    execution_id=our_execution,
                    artifact_id="doc_read_theirs",
                )

            assert refused.value.reason_codes == ("artifact_not_found",)

    run_async(scenario())


def test_an_unknown_artifact_id_is_refused_the_same_way(require_artifact_db: None) -> None:
    """No existence leak between "not yours" and "not there": one code for both."""

    del require_artifact_db

    async def scenario() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            project = await _seed_project_row(conn, "ws-read-artifact-404", name="Read 404")
            await seed_principal(conn, workspace_id=project.workspace_id, user_id=USER_ID)
            execution_id = await _seed_execution(
                conn,
                workspace_id=project.workspace_id,
                project_id=project.project_id,
                key="unknown",
            )

            with pytest.raises(PreconditionFailed) as refused:
                await _read(
                    conn,
                    workspace_id=project.workspace_id,
                    execution_id=execution_id,
                    artifact_id="doc_never_existed",
                )

            assert refused.value.reason_codes == ("artifact_not_found",)

    run_async(scenario())


def test_a_turn_with_no_project_coordinate_refuses_by_name(require_artifact_db: None) -> None:
    """The project is ambient, so a call outside one is refused rather than guessed at."""

    del require_artifact_db

    async def scenario() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            project = await _seed_project_row(conn, "ws-read-artifact-noexec", name="No exec")
            await seed_principal(conn, workspace_id=project.workspace_id, user_id=USER_ID)
            await _gallery(
                conn,
                workspace_id=project.workspace_id,
                project_id=project.project_id,
                thread_id="thr_read_noexec",
                document_id="doc_read_noexec",
            )

            tool = ReadArtifactTool(conn_factory=conn_session_factory(conn))
            inputs = tool.input_model.model_validate({"artifact_id": "doc_read_noexec"})
            ctx = ToolContext(
                workspace_id=project.workspace_id,
                actor="agent",
                conn_factory=conn_session_factory(conn),
                operation_id=new_operation_id(),
            )
            with pytest.raises(PreconditionFailed) as refused:
                await tool.invoke(inputs, ctx)

            assert refused.value.reason_codes == ("project_not_found",)

    run_async(scenario())
