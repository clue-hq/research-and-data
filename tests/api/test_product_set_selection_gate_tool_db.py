"""``open_product_set_selection_gate@1`` — the set-valued product gate (ARV2 onboarding O6, T3).

The Head of ABM may decide the conversation is ready to ask, but it cannot author the candidates,
the addressee, the brand, or the chosen set. Every one of those is derived here from durable rows:
the presenting turn, the project's brand, that brand's ``product`` rows, the current
``product-catalog`` knowledge document with its ``onboarding_product_lineage`` flags, and the
project's confirmed set. Nothing on this path reads a Client-KB version, a readiness decision or a
Stage-0 pin (standing rule, catalog contract §10).
"""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4, uuid5

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_api.agent_gate import KIND_PRODUCT_SET_SELECTION, get_gate
from clue_api.agent_turn_wiring import DurableAgentArtifactStore
from clue_api.product_set_selection_gate_tools import (
    OpenProductSetSelectionGateInput,
    build_product_set_selection_gate_tools,
)
from clue_api.turn_action import derive_turn_action_ref
from clue_core import new_operation_id
from clue_spine import confirm_project_product_set, create_product, get_project
from clue_storage import FsStorage
from clue_toolbelt import ToolContext
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

_FINGERPRINT = "sha256:" + "d" * 64


def _catalog_body(entries: list[dict[str, Any]]) -> str:
    lines = ["---", "kind: product-catalog", "products:"]
    for entry in entries:
        lines.append(f"  - name: {entry['name']}")
        for key in ("short_description", "offering_kind", "family", "lifecycle", "official_url"):
            lines.append(f"    {key}: {entry[key]}")
    lines += ["---", "", "# Product catalog", ""]
    return "\n".join(lines) + "\n"


def _icp_body(*, key: str, status: str, product_ids: list[str], project_id: str | None) -> str:
    confirmation = "" if project_id is None else f"confirmed_for_project_id: {project_id}\n"
    ids = ", ".join(product_ids)
    return (
        f"---\nkind: icp-definition\nicp_key: {key}\nstatus: {status}\n"
        f"product_ids: [{ids}]\n{confirmation}---\n\n"
        "Independent groups with three to twelve physicians.\n"
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
    project_id: str | None = None,
) -> UUID:
    ref = await artifacts.persist_body(
        workspace_id=workspace_id,
        data=body.encode(),
        media_type="text/markdown",
    )
    document_id = uuid4()
    await conn.execute(
        text(
            "INSERT INTO brand_knowledge_document (document_id, workspace_id, brand_id, folder, "
            "path, kind, version, status, artifact_key, artifact_sha256, project_id) "
            "VALUES (:id, :ws, :brand, :folder, :path, :kind, :version, :status, :key, :sha, "
            ":project)"
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
        },
    )
    return document_id


async def _seed_lineage(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    brand_id: str,
    document_id: UUID,
    entry_ordinal: int,
    product_id: str | None,
    resolution_state: str,
    reconcile_confidence: str | None = None,
    reconcile_reason: str | None = None,
) -> None:
    await conn.execute(
        text(
            "INSERT INTO onboarding_product_lineage (lineage_id, workspace_id, brand_id, "
            " document_id, entry_ordinal, entry_fingerprint_sha256, product_id, resolution_state, "
            " reconcile_confidence, reconcile_reason) "
            "VALUES (:id, :ws, :brand, :doc, :ordinal, :fingerprint, :product, :state, "
            " :confidence, :reason)"
        ),
        {
            "id": uuid4(),
            "ws": workspace_id,
            "brand": brand_id,
            "doc": document_id,
            "ordinal": entry_ordinal,
            "fingerprint": _FINGERPRINT,
            "product": product_id,
            "state": resolution_state,
            "confidence": reconcile_confidence,
            "reason": reconcile_reason,
        },
    )


class _Fixture:
    def __init__(self, **values: Any) -> None:
        self.__dict__.update(values)


async def _seed_brand_catalog(
    conn: AsyncConnection,
    tmp_path: Path,
    *,
    workspace_id: str,
    label: str,
    with_products: bool = True,
    with_icp: bool = True,
) -> Any:
    """The lane-D4 seed plus a brand product set, its catalog document and its lineage flags."""

    seeded = await _seed(conn, tmp_path, workspace_id=workspace_id, label=label)
    project = await get_project(conn, seeded.project_id)
    assert project is not None
    storage = FsStorage(tmp_path / f"o6-knowledge-{label}")
    artifacts = DurableAgentArtifactStore(
        storage=storage,
        conn_factory=conn_session_factory(conn),
    )
    products = []
    catalog_document_id: UUID | None = None
    if with_products:
        for name in ("Aura AI Scribe", "Phone Triage AI Agent"):
            products.append(
                await create_product(
                    conn,
                    brand_id=project.brand_id,
                    workspace_id=workspace_id,
                    name=name,
                )
            )
        entries = [
            {
                "name": "Aura AI Scribe",
                "short_description": "Ambient documentation for clinic visits.",
                "offering_kind": "product",
                "family": "Aura",
                "lifecycle": "active",
                "official_url": "https://example.test/aura",
            },
            {
                "name": "Phone Triage AI Agent",
                "short_description": "Answers and triages inbound patient calls.",
                "offering_kind": "product",
                "family": "Triage",
                "lifecycle": "beta",
                "official_url": "https://example.test/triage",
            },
        ]
        catalog_document_id = await _seed_document(
            conn,
            artifacts=artifacts,
            workspace_id=workspace_id,
            brand_id=project.brand_id,
            path="product/catalog.md",
            kind="product-catalog",
            version=3,
            status="ready",
            body=_catalog_body(entries),
        )
        # ``products`` is name-ordered, and "Aura AI Scribe" < "Phone Triage AI Agent".
        await _seed_lineage(
            conn,
            workspace_id=workspace_id,
            brand_id=project.brand_id,
            document_id=catalog_document_id,
            entry_ordinal=0,
            product_id=products[0].product_id,
            resolution_state="created",
        )
        await _seed_lineage(
            conn,
            workspace_id=workspace_id,
            brand_id=project.brand_id,
            document_id=catalog_document_id,
            entry_ordinal=1,
            product_id=products[1].product_id,
            resolution_state="model_unsure",
            reconcile_confidence="medium",
            reconcile_reason="suggested: Phone Triage — the catalog name differs from the row",
        )
    if with_icp and products:
        await _seed_document(
            conn,
            artifacts=artifacts,
            workspace_id=workspace_id,
            brand_id=project.brand_id,
            path="audience/icp-clinics.md",
            kind="icp-definition",
            version=1,
            status="proposed",
            body=_icp_body(
                key="clinics",
                status="proposed",
                product_ids=[products[1].product_id],
                project_id=None,
            ),
        )
    return _Fixture(
        seeded=seeded,
        project=project,
        brand_id=project.brand_id,
        products=products,
        catalog_document_id=catalog_document_id,
        storage=storage,
        artifacts=artifacts,
        conn_factory=conn_session_factory(conn),
    )


def _ctx(fixture: Any) -> ToolContext:
    return ToolContext(
        workspace_id=fixture.seeded.workspace_id,
        actor="agent",
        conn_factory=fixture.conn_factory,
        operation_id=new_operation_id(),
    )


def _tool(fixture: Any) -> Any:
    (tool,) = build_product_set_selection_gate_tools(
        conn_factory=fixture.conn_factory,
        storage=fixture.storage,
    )
    return tool


def test_the_gate_presents_every_candidate_with_its_lineage_flags(tmp_path: Path) -> None:
    """Every spine product is a candidate; the catalog and lineage only annotate them."""

    async def scenario() -> None:
        async with rollback_conn() as conn:
            fixture = await _seed_brand_catalog(
                conn, tmp_path, workspace_id="ws-o6-set-open", label="set-open"
            )
            tool = _tool(fixture)
            inputs = OpenProductSetSelectionGateInput(
                icp_key="clinics",
                source_turn_ref=derive_turn_action_ref(fixture.seeded.turn_id),
            )
            assert await tool.preconditions(inputs, _ctx(fixture)) == ()
            result = await tool.invoke(inputs, _ctx(fixture))

            assert result.references["gate_kind"] == KIND_PRODUCT_SET_SELECTION
            assert result.references["candidate_count"] == 2
            assert result.references["suggested_count"] == 1
            assert result.references["addressee_user_id"] == USER_ID
            assert result.references["created"] is True

            view = await get_gate(
                conn,
                workspace_id=fixture.seeded.workspace_id,
                gate_id=UUID(str(result.references["gate_id"])),
            )
            assert view is not None
            gate = view.gate
            assert gate.kind == KIND_PRODUCT_SET_SELECTION
            assert gate.max_spend_cents is None and gate.currency is None
            assert gate.addressee_user_id == USER_ID
            assert gate.subject_ref == (
                f"brand-product-catalog:{fixture.brand_id}:{fixture.catalog_document_id}"
            )
            assert gate.subject_revision == 3

            snapshot = gate.subject_snapshot
            assert snapshot["brand_id"] == fixture.brand_id
            assert snapshot["catalog_document_id"] == str(fixture.catalog_document_id)
            assert snapshot["catalog_version"] == 3
            assert snapshot["current_selection"] is None
            assert snapshot["suggested_product_ids"] == [fixture.products[1].product_id]
            products = snapshot["products"]
            assert isinstance(products, list) and len(products) == 2
            first, second = products
            assert isinstance(first, dict) and isinstance(second, dict)
            assert first["product_id"] == fixture.products[0].product_id
            assert first["name"] == "Aura AI Scribe"
            assert first["short_description"] == "Ambient documentation for clinic visits."
            assert first["family"] == "Aura"
            assert first["official_url"] == "https://example.test/aura"
            assert first["resolution_state"] == "created"
            assert first["reconcile_confidence"] is None
            assert second["product_id"] == fixture.products[1].product_id
            assert second["lifecycle"] == "beta"
            assert second["resolution_state"] == "model_unsure"
            assert second["reconcile_confidence"] == "medium"
            assert str(second["reconcile_reason"]).startswith("suggested: Phone Triage")

    run_async(scenario())


def test_a_second_presentation_of_the_same_turn_replays_the_same_gate(tmp_path: Path) -> None:
    """A retried turn presents *the* gate, never a second one addressing the same question."""

    async def scenario() -> None:
        async with rollback_conn() as conn:
            fixture = await _seed_brand_catalog(
                conn, tmp_path, workspace_id="ws-o6-set-replay", label="set-replay"
            )
            tool = _tool(fixture)
            inputs = OpenProductSetSelectionGateInput(
                icp_key="clinics",
                source_turn_ref=derive_turn_action_ref(fixture.seeded.turn_id),
            )
            first = await tool.invoke(inputs, _ctx(fixture))
            second = await tool.invoke(inputs, _ctx(fixture))
            assert first.references["created"] is True
            assert second.references["created"] is False
            assert second.references["gate_id"] == first.references["gate_id"]

    run_async(scenario())


def test_an_unknown_icp_key_is_refused_rather_than_silently_unsuggested(tmp_path: Path) -> None:
    """A pre-check the agent asked for and did not get is a refusal, never an empty list."""

    async def scenario() -> None:
        async with rollback_conn() as conn:
            fixture = await _seed_brand_catalog(
                conn, tmp_path, workspace_id="ws-o6-set-icp", label="set-icp"
            )
            failures = await _tool(fixture).preconditions(
                OpenProductSetSelectionGateInput(
                    icp_key="nope",
                    source_turn_ref=derive_turn_action_ref(fixture.seeded.turn_id),
                ),
                _ctx(fixture),
            )
            assert [failure.reason_code for failure in failures] == ["icp_key_unknown"]

    run_async(scenario())


def test_an_archived_product_is_not_offered(tmp_path: Path) -> None:
    """An operator can retire a product by archiving its row (2026-10-14: a client whose
    onboarding split one platform's features into products). Archived rows stay for history and
    lineage, but a project can no longer be pointed at them, so the gate does not offer them."""

    async def scenario() -> None:
        async with rollback_conn() as conn:
            fixture = await _seed_brand_catalog(
                conn, tmp_path, workspace_id="ws-o6-set-archived", label="set-archived"
            )
            archived = fixture.products[0].product_id
            await conn.execute(
                text("UPDATE product SET status = 'archived' WHERE product_id = :p"),
                {"p": archived},
            )
            result = await _tool(fixture).invoke(
                OpenProductSetSelectionGateInput(
                    icp_key="clinics",
                    source_turn_ref=derive_turn_action_ref(fixture.seeded.turn_id),
                ),
                _ctx(fixture),
            )
            assert result.references["candidate_count"] == 1
            view = await get_gate(
                conn,
                workspace_id=fixture.seeded.workspace_id,
                gate_id=UUID(str(result.references["gate_id"])),
            )
            assert view is not None
            offered = [p["product_id"] for p in view.gate.subject_snapshot["products"]]
            assert offered == [fixture.products[1].product_id]

    run_async(scenario())


def test_a_brand_with_no_products_has_nothing_to_ask_about(tmp_path: Path) -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            fixture = await _seed_brand_catalog(
                conn,
                tmp_path,
                workspace_id="ws-o6-set-empty",
                label="set-empty",
                with_products=False,
            )
            failures = await _tool(fixture).preconditions(
                OpenProductSetSelectionGateInput(
                    source_turn_ref=derive_turn_action_ref(fixture.seeded.turn_id),
                ),
                _ctx(fixture),
            )
            assert [failure.reason_code for failure in failures] == ["product_set_no_candidates"]

    run_async(scenario())


def test_a_turn_that_does_not_resolve_is_refused_before_anything_is_read(tmp_path: Path) -> None:
    """The presenting turn is the tool's only trusted input, so it is the first thing that fails."""

    async def scenario() -> None:
        async with rollback_conn() as conn:
            fixture = await _seed_brand_catalog(
                conn, tmp_path, workspace_id="ws-o6-set-noturn", label="set-noturn"
            )
            failures = await _tool(fixture).preconditions(
                OpenProductSetSelectionGateInput(
                    source_turn_ref=f"turn-action:{uuid4()}",
                ),
                _ctx(fixture),
            )
            assert [failure.reason_code for failure in failures] == ["product_set_turn_not_found"]

    run_async(scenario())


def test_a_turn_with_no_human_has_nobody_to_address(tmp_path: Path) -> None:
    """An agent-only turn cannot open a gate: a gate is addressed to the person who is here."""

    async def scenario() -> None:
        async with rollback_conn() as conn:
            fixture = await _seed_brand_catalog(
                conn, tmp_path, workspace_id="ws-o6-set-nohuman", label="set-nohuman"
            )
            agent_turn_id = uuid5(uuid.NAMESPACE_URL, "o6:set-nohuman:agent-turn")
            agent_execution_id = uuid5(uuid.NAMESPACE_URL, "o6:set-nohuman:agent-execution")
            await conn.execute(
                text(
                    "INSERT INTO execution "
                    "(id, workspace_id, project_id, started_by, parameter_manifest_hash, "
                    " pin_manifest_hash) "
                    "VALUES (:id, :ws, :project, 'agent', :hash, :hash)"
                ),
                {
                    "id": agent_execution_id,
                    "ws": fixture.seeded.workspace_id,
                    "project": fixture.seeded.project_id,
                    "hash": "0" * 64,
                },
            )
            await conn.execute(
                text(
                    "INSERT INTO agent_turn "
                    "(id, execution_id, workspace_id, project_id, thread_id, actor_id, role, "
                    " workspace_root_id, profile_name, profile_version, profile_sha256, "
                    " resource_manifest_key, resource_manifest_artifact_sha256, "
                    " resource_manifest_sha256, retention_class, requested_at) "
                    "SELECT :new_id, :execution_id, workspace_id, project_id, thread_id, actor_id, "
                    " role, workspace_root_id, profile_name, profile_version, profile_sha256, "
                    " resource_manifest_key, resource_manifest_artifact_sha256, "
                    " resource_manifest_sha256, retention_class, requested_at "
                    "FROM agent_turn WHERE id = :old_id"
                ),
                {
                    "new_id": agent_turn_id,
                    "execution_id": agent_execution_id,
                    "old_id": fixture.seeded.turn_id,
                },
            )
            failures = await _tool(fixture).preconditions(
                OpenProductSetSelectionGateInput(
                    source_turn_ref=derive_turn_action_ref(agent_turn_id),
                ),
                _ctx(fixture),
            )
            assert [failure.reason_code for failure in failures] == [
                "product_set_addressee_missing"
            ]

    run_async(scenario())


def test_a_project_that_already_chose_a_set_is_shown_it_and_asked_again(tmp_path: Path) -> None:
    """A confirmed set is context for the next question, never a reason to refuse it."""

    async def scenario() -> None:
        async with rollback_conn() as conn:
            fixture = await _seed_brand_catalog(
                conn, tmp_path, workspace_id="ws-o6-set-current", label="set-current"
            )
            confirmed = await confirm_project_product_set(
                conn,
                workspace_id=fixture.seeded.workspace_id,
                project_id=fixture.seeded.project_id,
                product_ids=[fixture.products[0].product_id],
                gate_id=uuid4(),
                confirmed_by_user_id=USER_ID,
            )
            assert confirmed is not None
            tool = _tool(fixture)
            inputs = OpenProductSetSelectionGateInput(
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
            assert view.gate.subject_snapshot["current_selection"] == {
                "selection_version": 1,
                "product_ids": [fixture.products[0].product_id],
            }
            # No ``icp_key`` and no confirmed ICP for this project: honestly empty, not a guess.
            assert view.gate.subject_snapshot["suggested_product_ids"] == []

    run_async(scenario())


def test_the_tool_is_free_domain_idempotent_and_confirms_nothing(tmp_path: Path) -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            fixture = await _seed_brand_catalog(
                conn, tmp_path, workspace_id="ws-o6-set-shape", label="set-shape"
            )
            tool = _tool(fixture)
            assert tool.descriptor.address == "open_product_set_selection_gate@1"
            assert tool.descriptor.effect_class.value == "write"
            assert tool.descriptor.replay.policy.value == "domain_idempotent"
            assert tool.descriptor.replay.external_boundary.value == "none"
            assert tool.descriptor.pin_requirements == ("project",)
            assert (
                tool.estimate(
                    OpenProductSetSelectionGateInput(source_turn_ref="turn-action:x")
                ).cost_cents
                == 0
            )

    run_async(scenario())


def test_a_project_scoped_catalog_document_never_becomes_this_gates_catalog(
    tmp_path: Path,
) -> None:
    """Review M5: the gate reads both scopes for the ICP, but the catalog is the brand's alone.

    The union exists so the ICP pre-check finds the project's own variant when it authored one.
    The catalog is the other kind of question — what this brand *sells* is a brand fact, and the
    gate's whole job is confirming a selection from it — so a project-scoped ``product-catalog``
    row must not become the authority for that project's product set. Nothing in the schema
    forbids one, and the set of project-scoped kinds keeps growing, so the filter is the guard.

    The seeded decoy sorts *before* ``product/catalog.md``, which is what makes this a real test:
    the lookup takes the path-smallest catalog, so an unfiltered union would pick the decoy.
    """

    async def scenario() -> None:
        async with rollback_conn() as conn:
            fixture = await _seed_brand_catalog(
                conn, tmp_path, workspace_id="ws-o6-set-scope", label="set-scope"
            )
            await _seed_document(
                conn,
                artifacts=fixture.artifacts,
                workspace_id=fixture.seeded.workspace_id,
                brand_id=fixture.brand_id,
                path="product/brand-catalog.md",
                kind="product-catalog",
                version=9,
                status="ready",
                body=_catalog_body(
                    [
                        {
                            "name": "A project's private idea of the catalog",
                            "short_description": "Not what this brand sells.",
                            "offering_kind": "product",
                            "family": "Decoy",
                            "lifecycle": "active",
                            "official_url": "https://example.test/decoy",
                        }
                    ]
                ),
                project_id=fixture.project.project_id,
            )

            tool = _tool(fixture)
            inputs = OpenProductSetSelectionGateInput(
                icp_key="clinics",
                source_turn_ref=derive_turn_action_ref(fixture.seeded.turn_id),
            )
            result = await tool.invoke(inputs, _ctx(fixture))

            view = await get_gate(
                conn,
                workspace_id=fixture.seeded.workspace_id,
                gate_id=UUID(str(result.references["gate_id"])),
            )
            assert view is not None
            assert view.gate.subject_ref == (
                f"brand-product-catalog:{fixture.brand_id}:{fixture.catalog_document_id}"
            )
            assert view.gate.subject_revision == 3
            snapshot = view.gate.subject_snapshot
            assert snapshot["catalog_document_id"] == str(fixture.catalog_document_id)
            assert snapshot["catalog_version"] == 3
            # The brand's two real products are still the candidates and the suggestion stands.
            assert result.references["candidate_count"] == 2
            assert snapshot["suggested_product_ids"] == [fixture.products[1].product_id]

    run_async(scenario())
