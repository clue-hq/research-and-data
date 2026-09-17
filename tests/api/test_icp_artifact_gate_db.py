"""``open_icp_confirmation_gate@2`` — the ICP gate over a knowledge document (ARV2 onboarding O6).

The ``@1`` gate presents a draft ``icp_spec`` row resolved through a Stage-0 project scope. This
one presents the artefact a human can actually read: the brand's current ``icp-definition``
knowledge document, named by document id and pinned by the digest of its exact bytes. Everything
the gate carries is derived here — the presenting turn supplies the project, the thread and the
addressee; the project supplies the brand; the brand's own documents supply the subject.

Nothing on this path reads a Client-KB version, a readiness decision or a Stage-0 pin (standing
rule ``_memory/2026-09-07-no-old-lane-gate-may-block-new-lane.md``).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_api.agent_gate import KIND_ICP_CONFIRMATION, get_gate
from clue_api.agent_turn_wiring import DurableAgentArtifactStore
from clue_api.arv2.icp_confirmation import (
    IcpConfirmationStale,
    confirm_icp_document,
    current_icp_document,
)
from clue_api.icp_artifact_gate_tools import (
    OpenIcpArtifactGateInput,
    build_icp_artifact_gate_tools,
)
from clue_api.turn_action import derive_turn_action_ref
from clue_core import new_operation_id
from clue_spine import create_product, create_project, get_project
from clue_storage import FsStorage
from clue_toolbelt import ReplayPolicy, ToolContext, ToolEffectClass
from tests.api.test_lane_d4_agent_gate_db import USER_ID, _seed
from tests.db.conftest import run_async
from tests.profiling.conftest import (
    conn_session_factory,
    migrated_db,  # noqa: F401 -- exposes the fixture to this test module
    rollback_conn,
)


@pytest.fixture
def require_gate_db(request: pytest.FixtureRequest) -> None:
    if not request.getfixturevalue("migrated_db"):
        pytest.skip("requires a migrated per-branch Postgres database")


pytestmark = pytest.mark.usefixtures("require_gate_db")


def icp_body(
    *,
    key: str,
    status: str,
    product_ids: list[str],
    project_id: str | None = None,
    title: str = "Independent multi-site clinic groups",
) -> str:
    confirmation = "" if project_id is None else f"confirmed_for_project_id: {project_id}\n"
    ids = ", ".join(product_ids)
    return (
        f"---\nkind: icp-definition\nicp_key: {key}\nversion: 1\nstatus: {status}\n"
        f"title: {title}\nproduct_ids: [{ids}]\n{confirmation}---\n\n"
        "# Independent multi-site clinic groups\n\n"
        "Independent groups with three to twelve physicians.\n"
    )


async def seed_document(
    conn: AsyncConnection,
    *,
    artifacts: DurableAgentArtifactStore,
    workspace_id: str,
    brand_id: str,
    path: str,
    kind: str,
    version: int,
    status: str,
    body: str,
    project_id: str | None = None,
    derived_from_document_id: UUID | None = None,
) -> tuple[UUID, str, str]:
    """Insert one ``brand_knowledge_document`` over really-stored bytes.

    ``project_id`` scopes the row to one project (ICP authoring, Task 1's columns);
    ``derived_from_document_id`` is the brand document a project-local variant was cut from.
    """

    ref = await artifacts.persist_body(
        workspace_id=workspace_id,
        data=body.encode(),
        media_type="text/markdown",
    )
    document_id = uuid4()
    await conn.execute(
        text(
            "INSERT INTO brand_knowledge_document (document_id, workspace_id, brand_id, folder, "
            "path, kind, version, status, artifact_key, artifact_sha256, project_id, "
            "derived_from_document_id) "
            "VALUES (:id, :ws, :brand, :folder, :path, :kind, :version, :status, :key, :sha, "
            ":project, :derived)"
        ),
        {
            "id": document_id,
            "ws": workspace_id,
            "brand": brand_id,
            "folder": path.split("/", 1)[0],
            "path": path,
            "kind": kind,
            "version": version,
            "status": status,
            "key": ref.artifact_key,
            "sha": ref.sha256,
            "project": project_id,
            "derived": derived_from_document_id,
        },
    )
    return document_id, ref.artifact_key, ref.sha256


class _Fixture:
    def __init__(self, **values: Any) -> None:
        self.__dict__.update(values)


async def _seed_icp(
    conn: AsyncConnection,
    tmp_path: Path,
    *,
    workspace_id: str,
    label: str,
    status: str = "proposed",
    confirmed_for_project_id: str | None = None,
    with_document: bool = True,
    icp_key: str = "clinics",
) -> Any:
    seeded = await _seed(conn, tmp_path, workspace_id=workspace_id, label=label)
    project = await get_project(conn, seeded.project_id)
    assert project is not None
    storage = FsStorage(tmp_path / f"o6-icp-{label}")
    artifacts = DurableAgentArtifactStore(
        storage=storage,
        conn_factory=conn_session_factory(conn),
    )
    product = await create_product(
        conn,
        brand_id=project.brand_id,
        workspace_id=workspace_id,
        name="Aura AI Scribe",
    )
    document_id: UUID | None = None
    artifact_sha256: str | None = None
    if with_document:
        document_id, _key, artifact_sha256 = await seed_document(
            conn,
            artifacts=artifacts,
            workspace_id=workspace_id,
            brand_id=project.brand_id,
            path=f"audience/icp-{icp_key}.md",
            kind="icp-definition",
            version=1,
            status=status,
            body=icp_body(
                key=icp_key,
                status=status,
                product_ids=[product.product_id],
                project_id=confirmed_for_project_id,
            ),
        )
    return _Fixture(
        seeded=seeded,
        project=project,
        brand_id=project.brand_id,
        product=product,
        document_id=document_id,
        artifact_sha256=artifact_sha256,
        storage=storage,
        artifacts=artifacts,
        conn_factory=conn_session_factory(conn),
    )


async def _icp_rows(conn: AsyncConnection, fixture: Any) -> list[dict[str, Any]]:
    rows = (
        await conn.execute(
            text(
                "SELECT document_id, version, status, supersedes_document_id "
                "FROM brand_knowledge_document WHERE workspace_id = :ws "
                " AND path = 'audience/icp-clinics.md' ORDER BY version"
            ),
            {"ws": fixture.seeded.workspace_id},
        )
    ).mappings()
    return [dict(row) for row in rows.all()]


async def _artifact_count(conn: AsyncConnection, fixture: Any) -> int:
    return int(
        (
            await conn.execute(
                text("SELECT count(*) FROM artifact WHERE workspace_id = :ws"),
                {"ws": fixture.seeded.workspace_id},
            )
        ).scalar_one()
    )


def _ctx(fixture: Any) -> ToolContext:
    return ToolContext(
        workspace_id=fixture.seeded.workspace_id,
        actor="agent",
        conn_factory=fixture.conn_factory,
        operation_id=new_operation_id(),
    )


def _tool(fixture: Any) -> Any:
    (tool,) = build_icp_artifact_gate_tools(
        conn_factory=fixture.conn_factory,
        storage=fixture.storage,
    )
    return tool


def test_the_gate_presents_the_current_icp_document_by_ref_and_digest(tmp_path: Path) -> None:
    """The subject is the document: its id, its version, and the digest of its exact bytes."""

    async def scenario() -> None:
        async with rollback_conn() as conn:
            fixture = await _seed_icp(
                conn, tmp_path, workspace_id="ws-o6-icp-open", label="icpopen"
            )
            tool = _tool(fixture)
            inputs = OpenIcpArtifactGateInput(
                icp_key="clinics",
                source_turn_ref=derive_turn_action_ref(fixture.seeded.turn_id),
            )
            assert await tool.preconditions(inputs, _ctx(fixture)) == ()
            result = await tool.invoke(inputs, _ctx(fixture))

            assert result.version == "2"
            assert result.references["gate_kind"] == KIND_ICP_CONFIRMATION
            assert result.references["created"] is True
            assert result.references["addressee_user_id"] == USER_ID
            assert result.references["subject_ref"] == (
                f"brand-knowledge-document:{fixture.document_id}:v1"
            )
            assert result.references["expected_subject_sha256"] == fixture.artifact_sha256

            view = await get_gate(
                conn,
                workspace_id=fixture.seeded.workspace_id,
                gate_id=UUID(str(result.references["gate_id"])),
            )
            assert view is not None
            gate = view.gate
            assert gate.kind == KIND_ICP_CONFIRMATION
            assert gate.max_spend_cents is None and gate.currency is None
            assert gate.project_id == fixture.seeded.project_id
            assert gate.thread_id == fixture.seeded.thread_id
            assert gate.subject_revision == 1
            assert gate.expected_subject_sha256 == fixture.artifact_sha256
            assert gate.permitted_decisions == ("approved", "rejected", "revised")

            snapshot = gate.subject_snapshot
            assert snapshot["subject_kind"] == "brand_knowledge_document"
            assert snapshot["document_id"] == str(fixture.document_id)
            assert snapshot["brand_id"] == fixture.brand_id
            assert snapshot["path"] == "audience/icp-clinics.md"
            assert snapshot["icp_key"] == "clinics"
            assert snapshot["version"] == 1
            assert snapshot["status"] == "proposed"
            assert snapshot["artifact_sha256"] == fixture.artifact_sha256
            assert snapshot["product_ids"] == [fixture.product.product_id]
            assert snapshot["title"] == "Independent multi-site clinic groups"

    run_async(scenario())


def test_an_unknown_icp_key_is_refused(tmp_path: Path) -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            fixture = await _seed_icp(
                conn, tmp_path, workspace_id="ws-o6-icp-none", label="icpnone"
            )
            failures = await _tool(fixture).preconditions(
                OpenIcpArtifactGateInput(
                    icp_key="nope",
                    source_turn_ref=derive_turn_action_ref(fixture.seeded.turn_id),
                ),
                _ctx(fixture),
            )
            assert [failure.reason_code for failure in failures] == ["icp_document_not_found"]

    run_async(scenario())


def test_a_ready_document_is_presentable_because_the_gate_is_what_pins_it(tmp_path: Path) -> None:
    """A document the agent wrote is born ``ready``, and the gate is what makes it the ICP.

    Before 2026-09-14 the writer decided that a file at ``audience/icp-<key>.md`` was a *proposal*
    and everything else was input, so a ``ready`` document was refused here. The agent now writes
    documents, not proposals: the human's yes at this gate is the pin, so every servable version of
    the document they read can be put in front of them.
    """

    async def scenario() -> None:
        async with rollback_conn() as conn:
            fixture = await _seed_icp(
                conn,
                tmp_path,
                workspace_id="ws-o6-icp-ready",
                label="icpready",
                status="ready",
            )
            inputs = OpenIcpArtifactGateInput(
                icp_key="clinics",
                source_turn_ref=derive_turn_action_ref(fixture.seeded.turn_id),
            )

            failures = await _tool(fixture).preconditions(inputs, _ctx(fixture))
            result = await _tool(fixture).invoke(inputs, _ctx(fixture))

            assert list(failures) == []
            assert result.references["subject_revision"] == 1
            assert result.references["created"] is True

    run_async(scenario())


def test_an_icp_already_confirmed_for_this_project_is_not_asked_again(tmp_path: Path) -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            # The document is seeded after the fixture because its confirmation names the project
            # the fixture's own seeding creates.
            fixture = await _seed_icp(
                conn,
                tmp_path,
                workspace_id="ws-o6-icp-done",
                label="icpdone",
                with_document=False,
            )
            await seed_document(
                conn,
                artifacts=fixture.artifacts,
                workspace_id=fixture.seeded.workspace_id,
                brand_id=fixture.brand_id,
                path="audience/icp-clinics.md",
                kind="icp-definition",
                version=1,
                status="confirmed",
                body=icp_body(
                    key="clinics",
                    status="confirmed",
                    product_ids=[fixture.product.product_id],
                    project_id=fixture.seeded.project_id,
                ),
            )
            failures = await _tool(fixture).preconditions(
                OpenIcpArtifactGateInput(
                    icp_key="clinics",
                    source_turn_ref=derive_turn_action_ref(fixture.seeded.turn_id),
                ),
                _ctx(fixture),
            )
            assert [failure.reason_code for failure in failures] == [
                "icp_already_confirmed_for_project"
            ]

    run_async(scenario())


def test_an_icp_confirmed_for_another_project_is_presentable(tmp_path: Path) -> None:
    """A brand's ICPs are shared; another project's confirmation is not this project's answer."""

    async def scenario() -> None:
        async with rollback_conn() as conn:
            fixture = await _seed_icp(
                conn,
                tmp_path,
                workspace_id="ws-o6-icp-other",
                label="icpother",
                status="confirmed",
                confirmed_for_project_id="prj_somebody_else",
            )
            tool = _tool(fixture)
            inputs = OpenIcpArtifactGateInput(
                icp_key="clinics",
                source_turn_ref=derive_turn_action_ref(fixture.seeded.turn_id),
            )
            assert await tool.preconditions(inputs, _ctx(fixture)) == ()
            result = await tool.invoke(inputs, _ctx(fixture))
            view = await get_gate(
                conn,
                workspace_id=fixture.seeded.workspace_id,
                gate_id=UUID(str(result.references["gate_id"])),
            )
            assert view is not None
            assert view.gate.subject_snapshot["status"] == "confirmed"

    run_async(scenario())


def test_a_second_presentation_of_the_same_turn_replays_the_same_gate(tmp_path: Path) -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            fixture = await _seed_icp(
                conn, tmp_path, workspace_id="ws-o6-icp-replay", label="icpreplay"
            )
            tool = _tool(fixture)
            inputs = OpenIcpArtifactGateInput(
                icp_key="clinics",
                source_turn_ref=derive_turn_action_ref(fixture.seeded.turn_id),
            )
            first = await tool.invoke(inputs, _ctx(fixture))
            second = await tool.invoke(inputs, _ctx(fixture))
            assert first.references["created"] is True
            assert second.references["created"] is False
            assert second.references["gate_id"] == first.references["gate_id"]

    run_async(scenario())


def test_a_turn_that_does_not_resolve_is_refused_before_anything_is_read(tmp_path: Path) -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            fixture = await _seed_icp(
                conn, tmp_path, workspace_id="ws-o6-icp-noturn", label="icpnoturn"
            )
            failures = await _tool(fixture).preconditions(
                OpenIcpArtifactGateInput(
                    icp_key="clinics",
                    source_turn_ref=f"turn-action:{uuid4()}",
                ),
                _ctx(fixture),
            )
            assert [failure.reason_code for failure in failures] == ["gate_turn_not_found"]

    run_async(scenario())


def test_a_malformed_turn_ref_is_refused(tmp_path: Path) -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            fixture = await _seed_icp(
                conn, tmp_path, workspace_id="ws-o6-icp-badref", label="icpbadref"
            )
            failures = await _tool(fixture).preconditions(
                OpenIcpArtifactGateInput(icp_key="clinics", source_turn_ref="not-a-turn-ref"),
                _ctx(fixture),
            )
            assert [failure.reason_code for failure in failures] == ["gate_turn_ref_malformed"]

    run_async(scenario())


def test_the_tool_is_free_domain_idempotent_and_pins_the_project(tmp_path: Path) -> None:
    """It writes an immutable question and nothing else — no spend, no confirmation."""

    async def scenario() -> None:
        async with rollback_conn() as conn:
            fixture = await _seed_icp(
                conn, tmp_path, workspace_id="ws-o6-icp-shape", label="icpshape"
            )
            tool = _tool(fixture)
            descriptor = tool.descriptor
            assert descriptor.name == "open_icp_confirmation_gate"
            assert descriptor.version == "2"
            assert tool.pin_requirements == ("project",)
            assert tool.parameter_policy.safe_display_fields == ("icp_key",)
            assert tool.effect_class is ToolEffectClass.WRITE
            assert tool.replay.policy is ReplayPolicy.DOMAIN_IDEMPOTENT
            estimate = tool.estimate(
                OpenIcpArtifactGateInput(
                    icp_key="clinics",
                    source_turn_ref=derive_turn_action_ref(fixture.seeded.turn_id),
                )
            )
            assert estimate.cost_cents == 0

    run_async(scenario())


def test_a_project_local_icp_is_served_only_to_its_own_project(tmp_path: Path) -> None:
    """A project-local ICP variant is this project's document, and nobody else's.

    The same key read for another project — or read with no project at all — is honestly absent
    rather than answered with a document that project never authored. The gate opens on it because
    the presenting turn supplies the project scope, exactly as it supplies the brand.
    """

    async def scenario() -> None:
        async with rollback_conn() as conn:
            fixture = await _seed_icp(
                conn,
                tmp_path,
                workspace_id="ws-o6-icp-proj",
                label="icpproj",
                with_document=False,
            )
            workspace_id = fixture.seeded.workspace_id
            document_id, _key, artifact_sha256 = await seed_document(
                conn,
                artifacts=fixture.artifacts,
                workspace_id=workspace_id,
                brand_id=fixture.brand_id,
                path="audience/icp-clinics-dac.md",
                kind="icp-definition",
                version=1,
                status="proposed",
                body=icp_body(
                    key="clinics-dac",
                    status="proposed",
                    product_ids=[fixture.product.product_id],
                ),
                project_id=fixture.seeded.project_id,
            )
            other = await create_project(
                conn,
                workspace_id=workspace_id,
                brand_id=fixture.brand_id,
                name="Another project on the same brand",
            )

            mine = await current_icp_document(
                conn,
                fixture.storage,
                workspace_id=workspace_id,
                brand_id=fixture.brand_id,
                icp_key="clinics-dac",
                project_id=fixture.seeded.project_id,
            )
            assert mine is not None
            assert mine.document_id == document_id
            assert mine.project_id == fixture.seeded.project_id
            assert mine.derived_from_document_id is None

            assert (
                await current_icp_document(
                    conn,
                    fixture.storage,
                    workspace_id=workspace_id,
                    brand_id=fixture.brand_id,
                    icp_key="clinics-dac",
                    project_id=other.project_id,
                )
                is None
            )
            assert (
                await current_icp_document(
                    conn,
                    fixture.storage,
                    workspace_id=workspace_id,
                    brand_id=fixture.brand_id,
                    icp_key="clinics-dac",
                )
                is None
            )

            tool = _tool(fixture)
            inputs = OpenIcpArtifactGateInput(
                icp_key="clinics-dac",
                source_turn_ref=derive_turn_action_ref(fixture.seeded.turn_id),
            )
            assert await tool.preconditions(inputs, _ctx(fixture)) == ()
            result = await tool.invoke(inputs, _ctx(fixture))
            assert result.references["subject_ref"] == (
                f"brand-knowledge-document:{document_id}:v1"
            )
            assert result.references["expected_subject_sha256"] == artifact_sha256

    run_async(scenario())


def test_confirming_the_same_document_twice_mints_exactly_one_version(tmp_path: Path) -> None:
    """The replay unit test: the confirmed version is derived, so a second call finds its row."""

    async def scenario() -> None:
        async with rollback_conn() as conn:
            fixture = await _seed_icp(
                conn, tmp_path, workspace_id="ws-o6-icp-mint", label="icpmint"
            )
            subject = await current_icp_document(
                conn,
                fixture.storage,
                workspace_id=fixture.seeded.workspace_id,
                brand_id=fixture.brand_id,
                icp_key="clinics",
            )
            assert subject is not None
            first = await confirm_icp_document(
                conn,
                fixture.storage,
                workspace_id=fixture.seeded.workspace_id,
                brand_id=fixture.brand_id,
                project_id=fixture.seeded.project_id,
                proposed=subject,
                expected_sha256=subject.artifact_sha256,
                confirmed_by_user_id=USER_ID,
                product_selection_version=None,
            )
            second = await confirm_icp_document(
                conn,
                fixture.storage,
                workspace_id=fixture.seeded.workspace_id,
                brand_id=fixture.brand_id,
                project_id=fixture.seeded.project_id,
                proposed=subject,
                expected_sha256=subject.artifact_sha256,
                confirmed_by_user_id=USER_ID,
                product_selection_version=None,
            )
            assert first.document_id == second.document_id
            assert first.version == second.version == 2
            assert first.artifact_sha256 == second.artifact_sha256
            assert first.supersedes_document_id == fixture.document_id
            rows = await _icp_rows(conn, fixture)
            assert [(row["version"], row["status"]) for row in rows] == [
                (1, "superseded"),
                (2, "confirmed"),
            ]

    run_async(scenario())


def test_a_confirmation_against_moved_bytes_is_refused(tmp_path: Path) -> None:
    """The digest is the whole point: bytes that moved cannot be confirmed by a stale click."""

    async def scenario() -> None:
        async with rollback_conn() as conn:
            fixture = await _seed_icp(
                conn, tmp_path, workspace_id="ws-o6-icp-stale", label="icpstale"
            )
            subject = await current_icp_document(
                conn,
                fixture.storage,
                workspace_id=fixture.seeded.workspace_id,
                brand_id=fixture.brand_id,
                icp_key="clinics",
            )
            assert subject is not None
            with pytest.raises(IcpConfirmationStale):
                await confirm_icp_document(
                    conn,
                    fixture.storage,
                    workspace_id=fixture.seeded.workspace_id,
                    brand_id=fixture.brand_id,
                    project_id=fixture.seeded.project_id,
                    proposed=subject,
                    expected_sha256="0" * 64,
                    confirmed_by_user_id=USER_ID,
                    product_selection_version=None,
                )
            assert (
                await conn.execute(
                    text(
                        "SELECT count(*) FROM brand_knowledge_document "
                        "WHERE workspace_id = :ws AND path = 'audience/icp-clinics.md'"
                    ),
                    {"ws": fixture.seeded.workspace_id},
                )
            ).scalar_one() == 1

    run_async(scenario())


def test_another_projects_confirmation_is_not_retired_by_this_ones(tmp_path: Path) -> None:
    """A brand's ICPs are shared, so a confirmation is never taken away from its own project.

    Project A's confirmed row is what A's launches pin by artifact key
    (``arv2.account_research_launch._pinned_icp`` requires ``status = 'confirmed'``), so B
    confirming the same profile mints a further version and leaves A's row exactly as it was.
    """

    async def scenario() -> None:
        async with rollback_conn() as conn:
            fixture = await _seed_icp(conn, tmp_path, workspace_id="ws-o6-icp-two", label="icptwo")
            project_a = fixture.seeded.project_id
            project_b = "prj_o6_icp_two_b"

            proposal = await current_icp_document(
                conn,
                fixture.storage,
                workspace_id=fixture.seeded.workspace_id,
                brand_id=fixture.brand_id,
                icp_key="clinics",
            )
            assert proposal is not None
            confirmed_a = await confirm_icp_document(
                conn,
                fixture.storage,
                workspace_id=fixture.seeded.workspace_id,
                brand_id=fixture.brand_id,
                project_id=project_a,
                proposed=proposal,
                expected_sha256=proposal.artifact_sha256,
                confirmed_by_user_id=USER_ID,
                product_selection_version=None,
            )
            # The proposal was A's to retire.
            rows = await _icp_rows(conn, fixture)
            assert [(row["version"], row["status"]) for row in rows] == [
                (1, "superseded"),
                (2, "confirmed"),
            ]

            # B now confirms what is currently on file — A's confirmed version.
            subject_b = await current_icp_document(
                conn,
                fixture.storage,
                workspace_id=fixture.seeded.workspace_id,
                brand_id=fixture.brand_id,
                icp_key="clinics",
            )
            assert subject_b is not None
            assert subject_b.document_id == confirmed_a.document_id
            assert subject_b.confirmed_for_project_id == project_a
            confirmed_b = await confirm_icp_document(
                conn,
                fixture.storage,
                workspace_id=fixture.seeded.workspace_id,
                brand_id=fixture.brand_id,
                project_id=project_b,
                proposed=subject_b,
                expected_sha256=subject_b.artifact_sha256,
                confirmed_by_user_id=USER_ID,
                product_selection_version=None,
            )
            assert confirmed_b.document_id != confirmed_a.document_id
            assert confirmed_b.supersedes_document_id == confirmed_a.document_id
            rows = await _icp_rows(conn, fixture)
            assert [(row["version"], row["status"]) for row in rows] == [
                (1, "superseded"),
                (2, "confirmed"),
                (3, "confirmed"),
            ]
            # A's confirmation is untouched and still pinnable.
            assert rows[1]["document_id"] == confirmed_a.document_id

    run_async(scenario())


def test_a_replayed_confirmation_stores_no_second_artifact(tmp_path: Path) -> None:
    """A replay returns the row it already minted — it does not re-render or re-store anything."""

    async def scenario() -> None:
        async with rollback_conn() as conn:
            fixture = await _seed_icp(
                conn, tmp_path, workspace_id="ws-o6-icp-orphan", label="icporphan"
            )
            subject = await current_icp_document(
                conn,
                fixture.storage,
                workspace_id=fixture.seeded.workspace_id,
                brand_id=fixture.brand_id,
                icp_key="clinics",
            )
            assert subject is not None
            kwargs: dict[str, Any] = {
                "workspace_id": fixture.seeded.workspace_id,
                "brand_id": fixture.brand_id,
                "project_id": fixture.seeded.project_id,
                "proposed": subject,
                "expected_sha256": subject.artifact_sha256,
                "confirmed_by_user_id": USER_ID,
                "product_selection_version": None,
            }
            first = await confirm_icp_document(conn, fixture.storage, **kwargs)
            after_first = await _artifact_count(conn, fixture)
            second = await confirm_icp_document(conn, fixture.storage, **kwargs)
            assert await _artifact_count(conn, fixture) == after_first
            assert second == first

    run_async(scenario())
