"""The brand-knowledge context a production conversation turn opens with (ARV2 onboarding O6, T2).

The Head of ABM does not research a brand from zero: onboarding already wrote the brand's knowledge
documents, and a turn reads them. Two properties are load-bearing and are asserted here from
durable rows, never from an in-memory convenience:

* **A turn's document set is pinned once.** Publishing a newer version mid-turn cannot change what
  a retry of that turn sees — the pin is insert-once and every later attempt reads the winner.
* **Bytes are verified against the pinned digest.** A document whose stored digest has moved is a
  loud refusal, not a silently different file served under ``brand/knowledge/``.

The index card is compiled, not stored, so its two tests are pure: they build the pinned documents
by hand and assert the bounded shape the model actually receives.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_api.agent_turn_submission import insert_submission
from clue_api.agent_turn_wiring import DurableAgentArtifactStore
from clue_api.arv2.icp_confirmation import ConfirmedIcp, pin_project_icp
from clue_api.brand_knowledge_context import (
    INPUT_PREFIX,
    SEED_PREFIX,
    BrandKnowledgeIndexCard,
    KnowledgeDocumentRef,
    KnowledgePinConflict,
    PinnedDocument,
    compile_brand_knowledge_index_card,
    confirmed_icp_for_project,
    current_knowledge_documents,
    current_project_knowledge_refs,
    get_knowledge_pin,
    knowledge_seed_files,
    load_or_create_knowledge_pin,
    read_pinned_documents,
    workspace_paths,
)
from clue_api.thread_store import create_thread
from clue_core import OnboardingInputKind
from clue_research.stage0 import submit_onboarding_input
from clue_spine import ProjectProductSet, create_project
from tests._identity import seed_principal
from tests._workspace import seed_project
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

OVERVIEW = (
    "---\nkind: company-overview\n---\n\n"
    "Acme builds scheduling software for gastroenterology clinics.\n\n"
    "A second paragraph the summary never reaches.\n"
)
CATALOG = "---\nkind: product-catalog\n---\n\nTwo products: Aura and Beta.\n"
DRAFT = "---\nkind: product-research\n---\n\nStill running.\n"


def _icp(*, key: str, status: str, project_id: str | None, selection_version: int | None) -> str:
    confirmation = (
        ""
        if project_id is None
        else (
            f"confirmed_for_project_id: {project_id}\n"
            f"product_selection_version: {selection_version}\n"
        )
    )
    return (
        f"---\nkind: icp-definition\nicp_key: {key}\nstatus: {status}\n"
        f"product_ids: [prd_aura, prd_beta]\n{confirmation}---\n\n"
        f"Independent {key} groups with three to twelve physicians.\n"
    )


async def _seed_document(
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
    artifact_sha256: str | None = None,
    project_id: str | None = None,
    derived_from_document_id: UUID | None = None,
) -> UUID:
    """Insert one knowledge document row over really-stored bytes.

    ``artifact_sha256`` overrides the digest the *row* claims (the table only checks its shape),
    which is how the "stored digest moved" case is reproduced without corrupting a blob.

    ``project_id`` scopes the row to one project (ICP authoring, Task 1's columns): the brand-level
    readers must not see it, and it materializes under the project's own prefix.
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
            "sha": artifact_sha256 or ref.sha256,
            "project": project_id,
            "derived": derived_from_document_id,
        },
    )
    return document_id


async def _submitted_turn(
    conn: AsyncConnection,
    *,
    artifacts: DurableAgentArtifactStore,
    workspace_id: str,
    project_id: str,
    brand_id: str,
    label: str,
) -> UUID:
    """One really-submitted turn, because the pin's anchor is a submission row."""

    principal = await seed_principal(
        conn,
        workspace_id=workspace_id,
        user_id=f"usr-o6-{label}",
    )
    thread_id = f"thr-o6-{label}-{uuid4().hex[:8]}"
    await create_thread(
        conn,
        thread_id=thread_id,
        workspace_id=workspace_id,
        project_id=project_id,
        created_by_user_id=principal.user_id,
        created_via_membership_id=principal.membership_id,
    )
    message = await artifacts.persist_body(
        workspace_id=workspace_id,
        data=f"O6 turn {label}".encode(),
        media_type="text/plain",
    )
    captured = await submit_onboarding_input(
        conn,
        workspace_id=workspace_id,
        brand_id=brand_id,
        project_id=project_id,
        kind=OnboardingInputKind.USER_TURN,
        artifact_key=message.artifact_key,
        content_sha256=message.sha256,
        actor="human",
    )
    turn_id = uuid4()
    _, created = await insert_submission(
        conn,
        turn_id=turn_id,
        workspace_id=workspace_id,
        project_id=project_id,
        thread_id=thread_id,
        submitted_by_user_id=principal.user_id,
        submitted_via_membership_id=principal.membership_id,
        onboarding_input_id=captured.onboarding_input_id,
        message_artifact_key=message.artifact_key,
        message_sha256=message.sha256,
        idempotency_key=f"o6-{label}-{turn_id}",
    )
    assert created is True
    return turn_id


def test_current_knowledge_documents_serve_the_max_servable_version_of_each_path() -> None:
    async def scenario() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            workspace_id = f"o6-current-{uuid4().hex[:6]}"
            project = await seed_project(conn, workspace_id, name="O6 current")
            storage = _MemoryStorage()
            artifacts = DurableAgentArtifactStore(
                storage=storage, conn_factory=conn_session_factory(conn)
            )
            for version, status in ((1, "ready"), (2, "ready")):
                await _seed_document(
                    conn,
                    artifacts=artifacts,
                    workspace_id=workspace_id,
                    brand_id=project.brand_id,
                    path="company/overview.md",
                    kind="company-overview",
                    version=version,
                    status=status,
                    body=f"{OVERVIEW}\nv{version}\n",
                )
            await _seed_document(
                conn,
                artifacts=artifacts,
                workspace_id=workspace_id,
                brand_id=project.brand_id,
                path="product/catalog.md",
                kind="product-catalog",
                version=1,
                status="ready",
                body=CATALOG,
            )
            await _seed_document(
                conn,
                artifacts=artifacts,
                workspace_id=workspace_id,
                brand_id=project.brand_id,
                path="product/aura.md",
                kind="product-research",
                version=1,
                status="running",
                body=DRAFT,
            )

            documents = await current_knowledge_documents(
                conn, workspace_id=workspace_id, brand_id=project.brand_id
            )

            assert [(doc.path, doc.version) for doc in documents] == [
                ("company/overview.md", 2),
                ("product/catalog.md", 1),
            ]
            assert all(doc.artifact_key for doc in documents)

    run_async(scenario())


def test_project_documents_are_invisible_to_brand_readers_and_seed_under_inputs_project() -> None:
    """A project-scoped row belongs to one project: the brand's readers must not see it at all.

    It is still real knowledge — it is read by the project-scoped reader, and it materializes under
    the *project's* prefix rather than the brand's, so the two can never collide on one workspace
    path. The brand seeds skip it: plan 1's project files pin is what puts it on disk.
    """

    async def scenario() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            workspace_id = f"o6-scope-{uuid4().hex[:6]}"
            project = await seed_project(conn, workspace_id, name="O6 scope")
            storage = _MemoryStorage()
            artifacts = DurableAgentArtifactStore(
                storage=storage, conn_factory=conn_session_factory(conn)
            )
            brand_body = _icp(key="gi", status="proposed", project_id=None, selection_version=None)
            project_body = _icp(
                key="gi-dac", status="proposed", project_id=None, selection_version=None
            )
            brand_doc = await _seed_document(
                conn,
                artifacts=artifacts,
                workspace_id=workspace_id,
                brand_id=project.brand_id,
                path="audience/icp-gi.md",
                kind="icp-definition",
                version=1,
                status="proposed",
                body=brand_body,
            )
            project_doc = await _seed_document(
                conn,
                artifacts=artifacts,
                workspace_id=workspace_id,
                brand_id=project.brand_id,
                path="audience/icp-gi-dac.md",
                kind="icp-definition",
                version=1,
                status="proposed",
                body=project_body,
                project_id=project.project_id,
                derived_from_document_id=brand_doc,
            )

            refs = await current_knowledge_documents(
                conn, workspace_id=workspace_id, brand_id=project.brand_id
            )
            assert [ref.document_id for ref in refs] == [brand_doc]
            assert refs[0].project_id is None

            project_refs = await current_project_knowledge_refs(
                conn, workspace_id=workspace_id, project_id=project.project_id
            )
            assert [(ref.document_id, ref.project_id) for ref in project_refs] == [
                (project_doc, project.project_id)
            ]

            pinned = (
                PinnedDocument(
                    ref=refs[0], body=brand_body.encode(), front_matter={}, body_text=""
                ),
                PinnedDocument(
                    ref=project_refs[0],
                    body=project_body.encode(),
                    front_matter={},
                    body_text="",
                ),
            )
            paths = workspace_paths(pinned)
            assert paths[brand_doc] == "brand/knowledge/audience/icp-gi.md"
            assert paths[project_doc] == "project/audience/icp-gi-dac.md"
            # The seed surface applies the same rule under its own prefix.
            assert [seed.path for seed in knowledge_seed_files(pinned)] == [
                "inputs/brand/knowledge/audience/icp-gi.md"
            ]

            # …and the brand's index card lists only what the brand seeds (review M4). The
            # project's own card carries the variant, off the project's own rows; listing it in
            # both spends the brand card's budget twice on one file, and — once the pinned and
            # current versions of one path differ — puts two disagreeing descriptions of that file
            # in one turn's opening context.
            card = compile_brand_knowledge_index_card(
                brand_id=project.brand_id,
                documents=pinned,
                confirmed_icp=confirmed_icp_for_project(pinned, pinned_document_id=project_doc),
                product_set=None,
            )
            assert [entry.document_id for entry in card.documents] == [str(brand_doc)]
            # The pin is unchanged: naming the project's pinned document is still this card's job,
            # whatever that document's scope.
            assert card.confirmed_icp is not None
            assert card.confirmed_icp.document_id == project_doc

    run_async(scenario())


def test_the_turn_pin_is_written_once_and_a_newer_document_cannot_change_it() -> None:
    async def scenario() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            workspace_id = f"o6-pin-{uuid4().hex[:6]}"
            project = await seed_project(conn, workspace_id, name="O6 pin")
            storage = _MemoryStorage()
            artifacts = DurableAgentArtifactStore(
                storage=storage, conn_factory=conn_session_factory(conn)
            )
            await _seed_document(
                conn,
                artifacts=artifacts,
                workspace_id=workspace_id,
                brand_id=project.brand_id,
                path="company/overview.md",
                kind="company-overview",
                version=1,
                status="ready",
                body=OVERVIEW,
            )
            turn_id = await _submitted_turn(
                conn,
                artifacts=artifacts,
                workspace_id=workspace_id,
                project_id=project.project_id,
                brand_id=project.brand_id,
                label="pin",
            )

            first, created = await load_or_create_knowledge_pin(
                conn,
                workspace_id=workspace_id,
                turn_id=turn_id,
                brand_id=project.brand_id,
                project_id=project.project_id,
            )
            assert created is True
            assert [doc.path for doc in first.documents] == ["company/overview.md"]

            again, created_again = await load_or_create_knowledge_pin(
                conn,
                workspace_id=workspace_id,
                turn_id=turn_id,
                brand_id=project.brand_id,
                project_id=project.project_id,
            )
            assert created_again is False
            assert again.documents_sha256 == first.documents_sha256

            # A background publish between two attempts of the same turn.
            await _seed_document(
                conn,
                artifacts=artifacts,
                workspace_id=workspace_id,
                brand_id=project.brand_id,
                path="company/overview.md",
                kind="company-overview",
                version=2,
                status="ready",
                body=f"{OVERVIEW}\nnewer\n",
            )
            retry, retry_created = await load_or_create_knowledge_pin(
                conn,
                workspace_id=workspace_id,
                turn_id=turn_id,
                brand_id=project.brand_id,
                project_id=project.project_id,
            )
            assert retry_created is False
            assert [(doc.path, doc.version) for doc in retry.documents] == [
                ("company/overview.md", 1)
            ]
            assert retry.documents_sha256 == first.documents_sha256

            read_back = await get_knowledge_pin(conn, workspace_id=workspace_id, turn_id=turn_id)
            assert read_back is not None
            assert read_back.documents == first.documents
            assert read_back.brand_id == project.brand_id
            # A foreign workspace cannot tell a pin it does not own from an absent one.
            assert (
                await get_knowledge_pin(conn, workspace_id="o6-other-ws", turn_id=turn_id)
            ) is None

            rows = (
                await conn.execute(
                    text(
                        "SELECT documents_sha256 FROM agent_turn_knowledge_pin "
                        "WHERE turn_id = :turn"
                    ),
                    {"turn": turn_id},
                )
            ).all()
            assert [str(row[0]) for row in rows] == [first.documents_sha256]

    run_async(scenario())


def test_read_pinned_documents_refuses_a_document_whose_stored_digest_moved() -> None:
    async def scenario() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            workspace_id = f"o6-digest-{uuid4().hex[:6]}"
            project = await seed_project(conn, workspace_id, name="O6 digest")
            storage = _MemoryStorage()
            artifacts = DurableAgentArtifactStore(
                storage=storage, conn_factory=conn_session_factory(conn)
            )
            await _seed_document(
                conn,
                artifacts=artifacts,
                workspace_id=workspace_id,
                brand_id=project.brand_id,
                path="company/overview.md",
                kind="company-overview",
                version=1,
                status="ready",
                body=OVERVIEW,
                artifact_sha256="b" * 64,
            )
            turn_id = await _submitted_turn(
                conn,
                artifacts=artifacts,
                workspace_id=workspace_id,
                project_id=project.project_id,
                brand_id=project.brand_id,
                label="digest",
            )
            pin, _ = await load_or_create_knowledge_pin(
                conn,
                workspace_id=workspace_id,
                turn_id=turn_id,
                brand_id=project.brand_id,
                project_id=project.project_id,
            )

            with pytest.raises(KnowledgePinConflict):
                await read_pinned_documents(conn, storage, pin=pin)

    run_async(scenario())


def test_pinned_documents_seed_read_only_files_under_the_knowledge_prefix() -> None:
    async def scenario() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            workspace_id = f"o6-seed-{uuid4().hex[:6]}"
            project = await seed_project(conn, workspace_id, name="O6 seed")
            storage = _MemoryStorage()
            artifacts = DurableAgentArtifactStore(
                storage=storage, conn_factory=conn_session_factory(conn)
            )
            await _seed_document(
                conn,
                artifacts=artifacts,
                workspace_id=workspace_id,
                brand_id=project.brand_id,
                path="company/overview.md",
                kind="company-overview",
                version=1,
                status="ready",
                body=OVERVIEW,
            )
            await _seed_document(
                conn,
                artifacts=artifacts,
                workspace_id=workspace_id,
                brand_id=project.brand_id,
                path="audience/icp-gi.md",
                kind="icp-definition",
                version=1,
                status="proposed",
                body=_icp(key="gi", status="proposed", project_id=None, selection_version=None),
            )
            turn_id = await _submitted_turn(
                conn,
                artifacts=artifacts,
                workspace_id=workspace_id,
                project_id=project.project_id,
                brand_id=project.brand_id,
                label="seed",
            )
            pin, _ = await load_or_create_knowledge_pin(
                conn,
                workspace_id=workspace_id,
                turn_id=turn_id,
                brand_id=project.brand_id,
                project_id=project.project_id,
            )

            documents = await read_pinned_documents(conn, storage, pin=pin)
            assert [doc.ref.path for doc in documents] == [
                "audience/icp-gi.md",
                "company/overview.md",
            ]
            overview = next(doc for doc in documents if doc.ref.path == "company/overview.md")
            assert overview.front_matter == {"kind": "company-overview"}
            assert overview.body_text.startswith("Acme builds scheduling software")

            seeds = knowledge_seed_files(documents)
            assert [seed.path for seed in seeds] == [
                f"{SEED_PREFIX}audience/icp-gi.md",
                f"{SEED_PREFIX}company/overview.md",
            ]
            assert all(seed.path.startswith(SEED_PREFIX) for seed in seeds)
            assert all(seed.media_type == "text/markdown" for seed in seeds)
            assert {seed.sha256 for seed in seeds} == {doc.ref.artifact_sha256 for doc in documents}

    run_async(scenario())


def test_the_projects_icp_is_the_document_it_pinned_not_a_front_matter_scan() -> None:
    """Founder rulings 2026-09-10: the pin is the selector, the front matter is only data."""

    async def scenario() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            workspace_id = f"o6-icp-{uuid4().hex[:6]}"
            project = await seed_project(conn, workspace_id, name="O6 icp")
            other = await create_project(
                conn,
                workspace_id=workspace_id,
                brand_id=project.brand_id,
                name="O6 other project",
            )
            storage = _MemoryStorage()
            artifacts = DurableAgentArtifactStore(
                storage=storage, conn_factory=conn_session_factory(conn)
            )
            gi_document_id = await _seed_document(
                conn,
                artifacts=artifacts,
                workspace_id=workspace_id,
                brand_id=project.brand_id,
                path="audience/icp-gi.md",
                kind="icp-definition",
                version=2,
                status="confirmed",
                body=_icp(
                    key="gi",
                    status="confirmed",
                    project_id=project.project_id,
                    selection_version=3,
                ),
            )
            asc_document_id = await _seed_document(
                conn,
                artifacts=artifacts,
                workspace_id=workspace_id,
                brand_id=project.brand_id,
                path="audience/icp-asc.md",
                kind="icp-definition",
                version=2,
                status="confirmed",
                body=_icp(
                    key="asc",
                    status="confirmed",
                    project_id=other.project_id,
                    selection_version=1,
                ),
            )
            await _seed_document(
                conn,
                artifacts=artifacts,
                workspace_id=workspace_id,
                brand_id=project.brand_id,
                path="audience/icp-hosp.md",
                kind="icp-definition",
                version=1,
                status="proposed",
                body=_icp(key="hosp", status="proposed", project_id=None, selection_version=None),
            )
            turn_id = await _submitted_turn(
                conn,
                artifacts=artifacts,
                workspace_id=workspace_id,
                project_id=project.project_id,
                brand_id=project.brand_id,
                label="icp",
            )
            pin, _ = await load_or_create_knowledge_pin(
                conn,
                workspace_id=workspace_id,
                turn_id=turn_id,
                brand_id=project.brand_id,
                project_id=project.project_id,
            )
            documents = await read_pinned_documents(conn, storage, pin=pin)

            confirmed = confirmed_icp_for_project(documents, pinned_document_id=gi_document_id)
            assert confirmed is not None
            assert confirmed.document_id == gi_document_id
            assert confirmed.icp_key == "gi"
            assert confirmed.version == 2
            assert confirmed.product_ids == ("prd_aura", "prd_beta")
            assert confirmed.product_selection_version == 3

            # The other project's pin names the other document — from the same pinned set. The
            # front matter of `icp-gi` still says it was confirmed for the first project; that is
            # a fact about the document, and it is not what decides.
            for_other = confirmed_icp_for_project(documents, pinned_document_id=asc_document_id)
            assert for_other is not None
            assert for_other.icp_key == "asc"

            # A project that has pinned nothing has no confirmed ICP, and a pin whose bytes this
            # turn does not hold is honestly absent rather than half-known.
            assert confirmed_icp_for_project(documents, pinned_document_id=None) is None
            assert confirmed_icp_for_project(documents, pinned_document_id=uuid4()) is None

            # The confirmed ref rides the card, so it must survive the JSON round trip Task 7
            # persists the card through.
            card = compile_brand_knowledge_index_card(
                brand_id=project.brand_id,
                documents=documents,
                confirmed_icp=confirmed,
                product_set=None,
            )
            assert card.model_dump(mode="json")["confirmed_icp"] == {
                "document_id": str(confirmed.document_id),
                "icp_key": "gi",
                "version": 2,
                "artifact_key": confirmed.artifact_key,
                "artifact_sha256": confirmed.artifact_sha256,
                "product_ids": ["prd_aura", "prd_beta"],
                "product_selection_version": 3,
            }
            assert card.content_sha256().startswith("sha256:")

    run_async(scenario())


def _pinned(
    *,
    path: str,
    kind: str,
    body: str,
    status: str = "ready",
    version: int = 1,
    front_matter: dict[str, object] | None = None,
) -> PinnedDocument:
    digest = f"{abs(hash(path)):064x}"[:64]
    return PinnedDocument(
        ref=KnowledgeDocumentRef(
            document_id=UUID(int=abs(hash(path)) % (2**128)),
            path=path,
            kind=kind,
            version=version,
            status=status,
            artifact_key=f"ws/{digest}",
            artifact_sha256=digest,
            updated_at=datetime(2026, 9, 9, 12, 0, tzinfo=UTC),
        ),
        body=body.encode(),
        front_matter=dict(front_matter or {}),
        body_text=body,
    )


def test_the_index_card_orders_documents_and_bounds_each_summary() -> None:
    long_first_paragraph = "Acme " * 80
    documents = (
        _pinned(path="product/aura.md", kind="product-research", body="Aura research.\n"),
        _pinned(
            path="audience/persona-gi.md",
            kind="audience-persona",
            body="Practice administrators.\n",
            front_matter={"icp_key": "gi"},
        ),
        _pinned(
            path="audience/icp-gi.md",
            kind="icp-definition",
            body="GI groups.\n",
            status="proposed",
            front_matter={"icp_key": "gi", "product_ids": ["prd_aura"]},
        ),
        _pinned(
            path="proof/customer-reviews.md",
            kind="customer-reviews",
            body="# Reviews\n\nClinics praise how quickly a new practice is scheduled.\n",
        ),
        _pinned(path="product/catalog.md", kind="product-catalog", body="Aura and Beta.\n"),
        _pinned(
            path="company/overview.md",
            kind="company-overview",
            body=f"{long_first_paragraph}\n\nSecond paragraph.\n",
        ),
    )

    card = compile_brand_knowledge_index_card(
        brand_id="brn_o6",
        documents=documents,
        confirmed_icp=None,
        product_set=ProjectProductSet(
            workspace_id="ws",
            project_id="prj",
            brand_id="brn_o6",
            selection_version=2,
            product_ids=("prd_aura",),
            gate_id=uuid4(),
            confirmed_by_user_id="usr",
            confirmed_at=datetime(2026, 9, 9, tzinfo=UTC),
        ),
    )

    assert isinstance(card, BrandKnowledgeIndexCard)
    assert [entry.path for entry in card.documents] == [
        "company/overview.md",
        "product/catalog.md",
        "proof/customer-reviews.md",
        "audience/icp-gi.md",
        "audience/persona-gi.md",
        "product/aura.md",
    ]
    assert card.omitted_count == 0
    assert card.product_set == {"selection_version": 2, "product_ids": ["prd_aura"]}
    assert all(entry.workspace_path == INPUT_PREFIX + entry.path for entry in card.documents)
    assert all(len(entry.summary) <= 160 for entry in card.documents)
    overview = card.documents[0]
    assert len(overview.summary) == 160
    assert overview.summary.startswith("Acme Acme")
    # A leading markdown heading is the document's title; the index line is the prose under it.
    reviews = next(entry for entry in card.documents if entry.kind == "customer-reviews")
    assert reviews.summary == "Clinics praise how quickly a new practice is scheduled."
    icp = next(entry for entry in card.documents if entry.kind == "icp-definition")
    assert icp.icp_key == "gi"
    assert icp.product_ids == ["prd_aura"]
    assert card.content_sha256().startswith("sha256:")


def test_the_index_card_drops_product_research_entries_to_fit_its_budget() -> None:
    documents = (
        _pinned(path="company/overview.md", kind="company-overview", body="Scheduling.\n"),
        _pinned(path="product/aura.md", kind="product-research", body="Aura.\n"),
        _pinned(path="product/beta.md", kind="product-research", body="Beta.\n"),
    )

    full = compile_brand_knowledge_index_card(
        brand_id="brn_o6",
        documents=documents,
        confirmed_icp=None,
        product_set=None,
    )
    assert full.omitted_count == 0
    assert len(full.documents) == 3

    # A budget one byte under the full card drops exactly the last product-research entry, and the
    # result really is under budget: the loop stops as soon as it fits.
    budget = len(full.canonical_bytes()) - 1
    one_dropped = compile_brand_knowledge_index_card(
        brand_id="brn_o6",
        documents=documents,
        confirmed_icp=None,
        product_set=None,
        max_bytes=budget,
    )
    assert one_dropped.omitted_count == 1
    assert [entry.path for entry in one_dropped.documents] == [
        "company/overview.md",
        "product/aura.md",
    ]
    assert len(one_dropped.canonical_bytes()) <= budget

    # 600 bytes is below the floor a single company entry occupies, so every product-research
    # entry goes and the card stops there: only product research is droppable.
    bounded = compile_brand_knowledge_index_card(
        brand_id="brn_o6",
        documents=documents,
        confirmed_icp=None,
        product_set=None,
        max_bytes=600,
    )
    assert bounded.omitted_count == 2
    assert [entry.kind for entry in bounded.documents] == ["company-overview"]
    assert len(bounded.canonical_bytes()) < len(full.canonical_bytes())


async def _pin_icp(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    project_id: str,
    brand_id: str,
    document_id: UUID,
    icp_key: str,
    product_selection_version: int | None,
) -> Any:
    """Pin an already-seeded confirmed document, the way the gate approval does."""

    row = (
        (
            await conn.execute(
                text(
                    "SELECT version, artifact_key, artifact_sha256 "
                    "FROM brand_knowledge_document WHERE document_id = :id"
                ),
                {"id": document_id},
            )
        )
        .mappings()
        .one()
    )
    return await pin_project_icp(
        conn,
        workspace_id=workspace_id,
        project_id=project_id,
        brand_id=brand_id,
        document=ConfirmedIcp(
            document_id=document_id,
            icp_key=icp_key,
            version=int(row["version"]),
            artifact_key=str(row["artifact_key"]),
            artifact_sha256=str(row["artifact_sha256"]),
            supersedes_document_id=document_id,
            product_selection_version=product_selection_version,
        ),
        product_selection_version=product_selection_version,
        pinned_by_user_id="usr-o6-knowledge",
    )


def test_a_newer_proposal_on_the_pinned_path_is_offered_but_never_called_confirmed() -> None:
    """The ruling, end to end through a turn's composition.

    Onboarding re-synthesizes an ICP and publishes a newer ``proposed`` version of the same path.
    The project pinned the earlier ``confirmed`` version, so that version is still in the turn's
    pinned set, still seeded on disk, and still what the card calls ``confirmed_icp``. The newer
    proposal is not hidden — it rides the set and it is listed — it simply is not the ICP, and it
    materializes beside the pin under a version-qualified name rather than over it.
    """

    async def scenario() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            workspace_id = f"o6-newer-{uuid4().hex[:6]}"
            project = await seed_project(conn, workspace_id, name="O6 newer proposal")
            storage = _MemoryStorage()
            artifacts = DurableAgentArtifactStore(
                storage=storage, conn_factory=conn_session_factory(conn)
            )
            await _seed_document(
                conn,
                artifacts=artifacts,
                workspace_id=workspace_id,
                brand_id=project.brand_id,
                path="company/overview.md",
                kind="company-overview",
                version=1,
                status="ready",
                body=OVERVIEW,
            )
            pinned_document_id = await _seed_document(
                conn,
                artifacts=artifacts,
                workspace_id=workspace_id,
                brand_id=project.brand_id,
                path="audience/icp-gi.md",
                kind="icp-definition",
                version=2,
                status="confirmed",
                body=_icp(
                    key="gi",
                    status="confirmed",
                    project_id=project.project_id,
                    selection_version=3,
                ),
            )
            pin = await _pin_icp(
                conn,
                workspace_id=workspace_id,
                project_id=project.project_id,
                brand_id=project.brand_id,
                document_id=pinned_document_id,
                icp_key="gi",
                product_selection_version=3,
            )
            # Onboarding re-synthesizes: a newer proposal lands on the very same path.
            newer_document_id = await _seed_document(
                conn,
                artifacts=artifacts,
                workspace_id=workspace_id,
                brand_id=project.brand_id,
                path="audience/icp-gi.md",
                kind="icp-definition",
                version=3,
                status="proposed",
                body=_icp(key="gi", status="proposed", project_id=None, selection_version=None),
            )
            # The brand's *current* set serves only the newest version of the path.
            current = await current_knowledge_documents(
                conn, workspace_id=workspace_id, brand_id=project.brand_id
            )
            assert [(ref.path, ref.version) for ref in current] == [
                ("audience/icp-gi.md", 3),
                ("company/overview.md", 1),
            ]

            turn_id = await _submitted_turn(
                conn,
                artifacts=artifacts,
                workspace_id=workspace_id,
                project_id=project.project_id,
                brand_id=project.brand_id,
                label="newer",
            )
            knowledge_pin, created = await load_or_create_knowledge_pin(
                conn,
                workspace_id=workspace_id,
                turn_id=turn_id,
                brand_id=project.brand_id,
                project_id=project.project_id,
            )
            assert created is True
            # The turn holds BOTH: what the brand knows now, and what this project agreed to.
            assert [(ref.path, ref.version) for ref in knowledge_pin.documents] == [
                ("audience/icp-gi.md", 2),
                ("audience/icp-gi.md", 3),
                ("company/overview.md", 1),
            ]

            documents = await read_pinned_documents(conn, storage, pin=knowledge_pin)
            seeds = knowledge_seed_files(documents, pinned_document_id=pin.document_id)
            # Every seed is a distinct real file, and the pinned version owns the natural name.
            assert len({seed.path for seed in seeds}) == len(seeds)
            assert sorted(seed.path for seed in seeds) == [
                f"{SEED_PREFIX}audience/icp-gi.md",
                f"{SEED_PREFIX}audience/icp-gi.v3.md",
                f"{SEED_PREFIX}company/overview.md",
            ]
            pinned_seed = next(
                seed for seed in seeds if seed.path == f"{SEED_PREFIX}audience/icp-gi.md"
            )
            assert pinned_seed.sha256 == pin.artifact_sha256

            confirmed = confirmed_icp_for_project(documents, pinned_document_id=pin.document_id)
            assert confirmed is not None
            assert confirmed.document_id == pinned_document_id
            assert confirmed.version == 2

            card = compile_brand_knowledge_index_card(
                brand_id=project.brand_id,
                documents=documents,
                confirmed_icp=confirmed,
                product_set=None,
            )
            assert card.confirmed_icp is not None
            assert card.confirmed_icp.document_id == pinned_document_id
            listed = {entry.document_id: entry for entry in card.documents}
            assert str(newer_document_id) in listed
            newer_entry = listed[str(newer_document_id)]
            assert newer_entry.status == "proposed"
            assert newer_entry.version == 3
            # The index names files that really exist, so it points at the qualified name too.
            assert newer_entry.workspace_path == f"{INPUT_PREFIX}audience/icp-gi.v3.md"
            assert listed[str(pinned_document_id)].workspace_path == (
                f"{INPUT_PREFIX}audience/icp-gi.md"
            )
            # One naming rule, two surfaces: the card names the mount and the seeds name the
            # seed folder, so the property — the index lists exactly the files the rule produces,
            # version-qualified name included — is asserted on the names below the prefixes.
            assert {
                entry.workspace_path.removeprefix(INPUT_PREFIX) for entry in card.documents
            } == {seed.path.removeprefix(SEED_PREFIX) for seed in seeds}

    run_async(scenario())
