"""S5-F production product-selection and next-turn context acceptance."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

import httpx
import pytest
from httpx import ASGITransport
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from clue_api.agent_gate import get_gate
from clue_api.agent_turn_scope_pin import (
    COMPANY_AND_SELECTED_PRODUCT_SCOPE_POLICY_V3,
    load_or_create_agent_turn_scope_pin,
)
from clue_api.agent_turn_submission import get_submission
from clue_api.agent_turn_wiring import DurableAgentArtifactStore
from clue_api.chat import CHAT_PERMISSIONS, RequestPrincipal
from clue_api.execution_wiring import build_tool_invoker
from clue_api.product_context_compiler import (
    compile_product_knowledge_card,
    compile_product_profile_card,
)
from clue_api.projections_app import create_projections_app
from clue_api.recipe_wiring import build_recipe_pin_registry
from clue_api.stage0_recipe import RecipeStep, Stage0StepPinProvider
from clue_api.toolbelt_wiring import build_toolbelt
from clue_api.turn_action import derive_turn_action_ref
from clue_config import load_settings
from clue_core import ExecutionId, new_operation_id, new_run_id
from clue_db import db_lifespan
from clue_execution import CompatibilityLoader
from clue_research.claimstore import record_run_lineage
from clue_research.stage0 import (
    PRODUCT_KNOWLEDGE_FIELDS,
    current_kb_version,
    finalize_client_kb_version,
)
from clue_spine import (
    confirm_project_product,
    create_brand,
    create_product,
    create_project,
    get_project,
)
from clue_storage import FsStorage
from clue_toolbelt import DbIdempotencyStore, PreconditionFailed, ToolContext, invoke_tool
from tests.api.test_product_context_s5c_db import _seed_product_context
from tests.api.test_production_context_s31_scope_pin_db import _capture_submission
from tests.db.conftest import run_async
from tests.profiling.conftest import conn_session_factory, rollback_conn
from tests.projections._helpers import build_surface

pytestmark = pytest.mark.usefixtures("require_profiling_db")

_AUTHENTICATED_AT = datetime(2026, 8, 15, 12, 0, tzinfo=UTC)


async def _make_presenting_turn(
    conn,
    *,
    artifacts: DurableAgentArtifactStore,
    scope,
    project_id: str,
    label: str,
    expected_product_id: str | None = None,
):
    submission = await _capture_submission(
        conn,
        artifacts=artifacts,
        workspace_id=scope.workspace_id,
        project_id=project_id,
        brand_id=scope.brand_id,
        product_id=expected_product_id,
        client_entity_id=scope.client_entity_id,
        label=label,
    )
    manifest = await artifacts.persist_body(
        workspace_id=scope.workspace_id,
        data=json.dumps({"resources": []}).encode(),
        media_type="application/json",
    )
    execution_id = uuid4()
    await conn.execute(
        text(
            "INSERT INTO execution (id, workspace_id, project_id, started_by, "
            "parameter_manifest_hash, pin_manifest_hash) "
            "VALUES (:id, :workspace, :project, 'human', :hash, :hash)"
        ),
        {
            "id": execution_id,
            "workspace": scope.workspace_id,
            "project": project_id,
            "hash": "0" * 64,
        },
    )
    await conn.execute(
        text(
            "INSERT INTO agent_turn "
            "(id, execution_id, workspace_id, project_id, thread_id, actor_id, role, "
            " workspace_root_id, profile_name, profile_version, profile_sha256, "
            " resource_manifest_key, resource_manifest_artifact_sha256, "
            " resource_manifest_sha256, retention_class, requested_at, "
            " submitted_by_user_id, submitted_via_membership_id) "
            "VALUES (:id, :execution, :workspace, :project, :thread, :user, 'head_of_abm', "
            " :root, 'head-of-abm', 'v27', :profile_sha, :manifest_key, :manifest_sha, "
            " :manifest_sha, 'test', now(), :user, :membership)"
        ),
        {
            "id": submission.turn_id,
            "execution": execution_id,
            "workspace": scope.workspace_id,
            "project": project_id,
            "thread": submission.thread_id,
            "user": submission.submitted_by_user_id,
            "membership": submission.submitted_via_membership_id,
            "root": f"s5f-{label}",
            "profile_sha": "0" * 64,
            "manifest_key": manifest.artifact_key,
            "manifest_sha": manifest.sha256,
        },
    )
    pin, created = await load_or_create_agent_turn_scope_pin(conn, submission=submission)
    assert created is True
    assert pin.product_id == expected_product_id
    if expected_product_id is None:
        assert pin.product_kb_version is None
    return submission, pin


def test_icp_synthesis_pins_company_kb_independently_from_selected_product_kb(
    tmp_path: Path,
) -> None:
    """Company v2 plus Product v1 must not be resolved as ``client|product@2``."""

    async def scenario() -> None:
        async with db_lifespan():
            scope, products, product_version = await _seed_product_context(tmp_path)
        async with rollback_conn() as conn:
            company_run = new_run_id()
            await record_run_lineage(
                conn,
                run_id=company_run,
                workspace_id=scope.workspace_id,
                kind="stage0",
            )
            company_version = await finalize_client_kb_version(
                conn,
                client_entity_id=scope.client_entity_id,
                workspace_id=scope.workspace_id,
                run_id=company_run,
                filled_fields=set(),
                attempted_fields=set(),
                product_id=None,
            )
            assert (company_version, product_version) == (2, 1)

            project = await create_project(
                conn,
                workspace_id=scope.workspace_id,
                brand_id=scope.brand_id,
                name="Independent KB pin project",
            )
            storage = FsStorage(tmp_path / "synthesis-independent-kb-pins")
            cf = conn_session_factory(conn)
            artifacts = DurableAgentArtifactStore(storage=storage, conn_factory=cf)
            _submission, _opening_pin = await _make_presenting_turn(
                conn,
                artifacts=artifacts,
                scope=scope,
                project_id=project.project_id,
                label="independent-kb-pins",
            )
            confirmed = await confirm_project_product(
                conn,
                workspace_id=scope.workspace_id,
                project_id=project.project_id,
                product_id=products[0].product_id,
            )
            assert confirmed is not None
            selected_submission, selected_pin = await _make_presenting_turn(
                conn,
                artifacts=artifacts,
                scope=scope,
                project_id=project.project_id,
                label="independent-kb-pins-selected",
                expected_product_id=products[0].product_id,
            )
            assert selected_pin.product_kb_version == product_version
            execution_id = ExecutionId(
                (
                    await conn.execute(
                        text("SELECT execution_id FROM agent_turn WHERE id = :turn_id"),
                        {"turn_id": selected_submission.turn_id},
                    )
                ).scalar_one()
            )

            registry = build_toolbelt(
                storage=storage,
                settings=load_settings(_env_file=None, chat_enabled=True),
                gateway=None,
                conn_factory=cf,
            )
            pins = await Stage0StepPinProvider(
                compatibility=CompatibilityLoader(
                    build_recipe_pin_registry(tool_registry=registry, conn_factory=cf)
                ),
                conn_factory=cf,
                tools=registry,
            ).pins_for(
                RecipeStep(
                    step_id="synthesize",
                    tool_name="synthesize_icps",
                    tool_version="2",
                    input_refs={},
                ),
                ctx=ToolContext(
                    workspace_id=scope.workspace_id,
                    actor="agent",
                    principal_kind="internal_service",
                    actor_id="svc_agent_execution",
                    conn_factory=cf,
                    operation_id=new_operation_id(),
                    execution_id=execution_id,
                ),
            )
            by_kind = {pin.kind: pin for pin in pins}
            assert (by_kind["client_kb"].key, by_kind["client_kb"].version) == (
                f"{scope.client_entity_id}|-",
                str(company_version),
            )
            assert by_kind["product"].key == products[0].product_id
            assert "product_kb" not in by_kind

    run_async(scenario())


def test_new_turn_repairs_legacy_selected_product_without_kb(tmp_path: Path) -> None:
    """A selected legacy project cannot produce another null Product-KB turn receipt."""

    async def scenario() -> None:
        async with db_lifespan():
            scope, products, _product_version = await _seed_product_context(tmp_path)
        async with rollback_conn() as conn:
            legacy_product = products[1]
            assert (
                await current_kb_version(
                    conn,
                    scope.client_entity_id,
                    workspace_id=scope.workspace_id,
                    product_id=legacy_product.product_id,
                )
                is None
            )
            project = await create_project(
                conn,
                workspace_id=scope.workspace_id,
                brand_id=scope.brand_id,
                product_id=legacy_product.product_id,
                name="Legacy selected-without-knowledge project",
            )
            storage = FsStorage(tmp_path / "selected-product-pin-repair")
            artifacts = DurableAgentArtifactStore(
                storage=storage,
                conn_factory=conn_session_factory(conn),
            )
            _submission, pin = await _make_presenting_turn(
                conn,
                artifacts=artifacts,
                scope=scope,
                project_id=project.project_id,
                label="selected-product-pin-repair",
                expected_product_id=legacy_product.product_id,
            )
            assert pin.product_kb_version == 1
            assert (
                pin.knowledge_scope_policy_version == COMPANY_AND_SELECTED_PRODUCT_SCOPE_POLICY_V3
            )
            card = await compile_product_knowledge_card(
                workspace_id=scope.workspace_id,
                client_entity_id=scope.client_entity_id,
                product_id=legacy_product.product_id,
                product_kb_version=pin.product_kb_version,
                conn_factory=conn_session_factory(conn),
            )
            assert not card.known_fields
            assert set(card.open_gaps) == set(PRODUCT_KNOWLEDGE_FIELDS)
            assert (card.coverage.filled, card.coverage.required) == (
                0,
                len(PRODUCT_KNOWLEDGE_FIELDS),
            )

    run_async(scenario())


def test_catalog_gate_human_selection_and_next_turn_product_pair_for_projects_a_and_b(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        async with db_lifespan():
            scope, products, product_version = await _seed_product_context(tmp_path)
        async with rollback_conn() as conn:
            selection_check = (
                await conn.execute(
                    text(
                        "SELECT pg_get_constraintdef(oid) FROM pg_constraint "
                        "WHERE conname='agent_gate_answer_selection_valid'"
                    )
                )
            ).scalar_one()
            gate_kind_check = (
                await conn.execute(
                    text(
                        "SELECT pg_get_constraintdef(oid) FROM pg_constraint "
                        "WHERE conname='agent_gate_kind'"
                    )
                )
            ).scalar_one()
            assert "selected_option_ref IS NULL" in selection_check
            assert "decision = 'approved'" in selection_check
            assert "product_selection" in gate_kind_check
            project_a = await create_project(
                conn,
                workspace_id=scope.workspace_id,
                brand_id=scope.brand_id,
                name="S5-F Project A",
            )
            project_b = await create_project(
                conn,
                workspace_id=scope.workspace_id,
                brand_id=scope.brand_id,
                name="S5-F Project B",
            )
            storage = FsStorage(tmp_path / "s5f-route")
            cf = conn_session_factory(conn)
            artifacts = DurableAgentArtifactStore(storage=storage, conn_factory=cf)
            opening_a, original_pin_a = await _make_presenting_turn(
                conn,
                artifacts=artifacts,
                scope=scope,
                project_id=project_a.project_id,
                label="a",
            )
            opening_b, original_pin_b = await _make_presenting_turn(
                conn,
                artifacts=artifacts,
                scope=scope,
                project_id=project_b.project_id,
                label="b",
            )

            settings = load_settings(_env_file=None, chat_enabled=True)
            registry = build_toolbelt(
                storage=storage,
                settings=settings,
                gateway=None,
                conn_factory=cf,
            )
            # The real governed agent wrapper has no model-visible project/client/version
            # arguments for this tool. Its execution pins must therefore come from the exact
            # captured turn scope, otherwise graph validation refuses the production call before
            # the otherwise-correct domain tool can open the gate.
            gate_pins = await Stage0StepPinProvider(
                compatibility=CompatibilityLoader(
                    build_recipe_pin_registry(tool_registry=registry, conn_factory=cf)
                ),
                conn_factory=cf,
                tools=registry,
            ).pins_for(
                RecipeStep(
                    step_id="open_selection_gate_a",
                    tool_name="open_product_selection_gate",
                    tool_version="1",
                    input_refs={
                        "source_turn_ref": derive_turn_action_ref(opening_a.turn_id),
                    },
                ),
                ctx=ToolContext(
                    workspace_id=scope.workspace_id,
                    actor="agent",
                    principal_kind="internal_service",
                    actor_id="svc_agent_execution",
                    conn_factory=cf,
                    operation_id=new_operation_id(),
                ),
            )
            assert {(pin.kind, pin.key, pin.version) for pin in gate_pins} == {
                ("project", project_a.project_id, "1"),
                (
                    "client_kb",
                    f"{scope.client_entity_id}|-",
                    str(original_pin_a.client_kb_version),
                ),
            }
            agent_context = ToolContext(
                workspace_id=scope.workspace_id,
                actor="agent",
                conn_factory=cf,
                operation_id=new_operation_id(),
            )
            opened_a = await invoke_tool(
                registry,
                "open_product_selection_gate",
                {"source_turn_ref": derive_turn_action_ref(opening_a.turn_id)},
                agent_context,
                idempotency_ttl_s=60,
            )
            opened_b = await invoke_tool(
                registry,
                "open_product_selection_gate",
                {"source_turn_ref": derive_turn_action_ref(opening_b.turn_id)},
                agent_context,
                idempotency_ttl_s=60,
            )
            assert opened_a.references["candidate_count"] == 3
            assert opened_b.references["candidate_count"] == 3

            # The route validates first for friendly errors, but direct SQL must not bypass the
            # same authority. Exercise the unified trigger before either real answer is recorded.
            gate_a_id = UUID(str(opened_a.references["gate_id"]))
            gate_a = await get_gate(conn, workspace_id=scope.workspace_id, gate_id=gate_a_id)
            assert gate_a is not None

            async def refused_direct_answer(
                *,
                decision: str = "approved",
                selected_option_ref: str | None = products[0].product_id,
                payload: dict[str, str] | None = None,
                digest: str | None = None,
                actor: str | None = None,
                answering_turn=opening_a,
                erase_snapshot: bool = False,
                message: str,
            ) -> None:
                with pytest.raises(DBAPIError, match=message):
                    async with conn.begin_nested():
                        if erase_snapshot:
                            await conn.execute(
                                text(
                                    "UPDATE agent_gate SET subject_snapshot='{}'::jsonb, "
                                    "snapshot_erased_at=now(), snapshot_erasure_reason='test' "
                                    "WHERE gate_id=:gate"
                                ),
                                {"gate": gate_a_id},
                            )
                        await conn.execute(
                            text(
                                "INSERT INTO agent_gate_answer "
                                "(gate_id, workspace_id, turn_id, action_ref, decision, "
                                " expected_subject_sha256, decision_payload, "
                                " selected_option_ref, answered_by_user_id) "
                                "VALUES (:gate, :workspace, :turn, :action, :decision, :digest, "
                                " CAST(:payload AS jsonb), :selection, :actor)"
                            ),
                            {
                                "gate": gate_a_id,
                                "workspace": scope.workspace_id,
                                "turn": answering_turn.turn_id,
                                "action": derive_turn_action_ref(answering_turn.turn_id),
                                "decision": decision,
                                "digest": digest or gate_a.gate.expected_subject_sha256,
                                "payload": json.dumps(payload or {}),
                                "selection": selected_option_ref,
                                "actor": actor or opening_a.submitted_by_user_id,
                            },
                        )

            await refused_direct_answer(
                selected_option_ref=None,
                message="product approval requires one selected option",
            )
            await refused_direct_answer(
                selected_option_ref="product-not-in-presented-catalog",
                message="selected option is not a candidate",
            )
            await refused_direct_answer(
                decision="rejected",
                message="product rejection/revision cannot carry a selected option",
            )
            await refused_direct_answer(
                payload={"revision_request": "smuggled"},
                message="cannot carry both a revision payload and a selection",
            )
            await refused_direct_answer(
                digest="f" * 64,
                message="digest does not match",
            )
            await refused_direct_answer(
                actor="usr_not_the_addressee",
                message="only the gate addressee",
            )
            await refused_direct_answer(
                answering_turn=opening_b,
                message="does not belong to this gate thread",
            )
            await refused_direct_answer(
                erase_snapshot=True,
                message="erased gate snapshot cannot be answered",
            )

            user_id = f"user-s31-{scope.workspace_id}"
            membership_id = f"membership-s31-{scope.workspace_id}"

            def principal(workspace_id: str) -> RequestPrincipal:
                return RequestPrincipal(
                    user_id=user_id,
                    membership_id=membership_id,
                    workspace_id=workspace_id,
                    role_key="owner",
                    permissions=CHAT_PERMISSIONS,
                    authenticated_at=_AUTHENTICATED_AT,
                )

            app = create_projections_app(
                surface=build_surface(conn),
                tool_invoker=build_tool_invoker(
                    registry=registry,
                    idempotency_store=DbIdempotencyStore(conn_factory=cf),
                    storage=storage,
                    settings=settings,
                    conn_factory=cf,
                ),
                settings=settings,
                conn_factory=cf,
                manage_db_lifespan=False,
                ingestion_storage=storage,
                chat_principal_resolver=principal,
            )

            async def select(
                *,
                project_id: str,
                thread_id: str,
                opened,
                product_id: str | None,
                key: str,
                decision: str = "approved",
            ) -> httpx.Response:
                gate_id = UUID(str(opened.references["gate_id"]))
                gate = await get_gate(conn, workspace_id=scope.workspace_id, gate_id=gate_id)
                assert gate is not None
                async with httpx.AsyncClient(
                    transport=ASGITransport(app=app), base_url="http://s5f"
                ) as client:
                    return await client.post(
                        f"/api/v1/projects/{project_id}/threads/{thread_id}/turns",
                        json={
                            "gate_response": {
                                "gate_id": str(gate_id),
                                "decision": decision,
                                "expected_subject_sha256": gate.gate.expected_subject_sha256,
                                "expected_estimated_cost_cents": None,
                                **(
                                    {}
                                    if product_id is None
                                    else {"selected_product_id": product_id}
                                ),
                            }
                        },
                        headers={
                            "X-Workspace-Id": scope.workspace_id,
                            "Idempotency-Key": key,
                        },
                    )

            missing_choice = await select(
                project_id=project_b.project_id,
                thread_id=opening_b.thread_id,
                opened=opened_b,
                product_id=None,
                key="s5f-missing-choice",
            )
            stale_choice = await select(
                project_id=project_b.project_id,
                thread_id=opening_b.thread_id,
                opened=opened_b,
                product_id="product-not-in-presented-catalog",
                key="s5f-stale-choice",
            )
            rejected_with_choice = await select(
                project_id=project_b.project_id,
                thread_id=opening_b.thread_id,
                opened=opened_b,
                product_id=products[1].product_id,
                decision="rejected",
                key="s5f-rejected-with-choice",
            )
            foreign_project = await select(
                project_id=project_a.project_id,
                thread_id=opening_a.thread_id,
                opened=opened_b,
                product_id=products[1].product_id,
                key="s5f-foreign-project",
            )
            assert missing_choice.status_code == 422
            assert missing_choice.json()["error"]["code"] == "GATE_PRODUCT_REQUIRED"
            assert stale_choice.status_code == 409
            assert stale_choice.json()["error"]["code"] == "GATE_PRODUCT_STALE"
            assert rejected_with_choice.status_code == 422
            assert rejected_with_choice.json()["error"]["code"] == "GATE_PRODUCT_UNEXPECTED"
            assert foreign_project.status_code == 404
            assert foreign_project.json()["error"]["code"] == "GATE_NOT_FOUND"
            assert (await get_project(conn, project_b.project_id)).product_id is None  # type: ignore[union-attr]

            response_a = await select(
                project_id=project_a.project_id,
                thread_id=opening_a.thread_id,
                opened=opened_a,
                product_id=products[0].product_id,
                key="s5f-select-a",
            )
            response_b = await select(
                project_id=project_b.project_id,
                thread_id=opening_b.thread_id,
                opened=opened_b,
                product_id=products[1].product_id,
                key="s5f-select-b",
            )
            assert response_a.status_code == 202, response_a.text
            assert response_b.status_code == 202, response_b.text
            replay_a = await select(
                project_id=project_a.project_id,
                thread_id=opening_a.thread_id,
                opened=opened_a,
                product_id=products[0].product_id,
                key="s5f-select-a",
            )
            assert replay_a.status_code == 202, replay_a.text
            assert replay_a.json()["data"]["replayed"] is True
            assert replay_a.json()["data"]["turn_id"] == response_a.json()["data"]["turn_id"]

            selected_a = await get_project(conn, project_a.project_id)
            selected_b = await get_project(conn, project_b.project_id)
            assert selected_a is not None and selected_a.product_id == products[0].product_id
            assert selected_b is not None and selected_b.product_id == products[1].product_id

            # Product selection atomically preserves A's existing knowledge and bootstraps an
            # honest empty v1 for B before either next-turn pin gets a chance to self-repair it.
            assert (
                await current_kb_version(
                    conn,
                    scope.client_entity_id,
                    workspace_id=scope.workspace_id,
                    product_id=products[0].product_id,
                )
                == product_version
            )
            assert (
                await current_kb_version(
                    conn,
                    scope.client_entity_id,
                    workspace_id=scope.workspace_id,
                    product_id=products[1].product_id,
                )
                == 1
            )

            # The structured answers are the next queued production turns. Their scope is resolved
            # only after the selection transaction, and every selected-product V3 turn receives
            # exact Product-KB authority even when all registered knowledge remains an open gap.
            answer_a = await get_submission(
                conn,
                workspace_id=scope.workspace_id,
                turn_id=UUID(response_a.json()["data"]["turn_id"]),
            )
            answer_b = await get_submission(
                conn,
                workspace_id=scope.workspace_id,
                turn_id=UUID(response_b.json()["data"]["turn_id"]),
            )
            assert answer_a is not None and answer_b is not None
            pin_a, _ = await load_or_create_agent_turn_scope_pin(conn, submission=answer_a)
            pin_b, _ = await load_or_create_agent_turn_scope_pin(conn, submission=answer_b)
            assert (pin_a.product_id, pin_a.product_kb_version) == (
                products[0].product_id,
                product_version,
            )
            assert (pin_b.product_id, pin_b.product_kb_version) == (
                products[1].product_id,
                1,
            )
            assert (
                pin_a.knowledge_scope_policy_version
                == pin_b.knowledge_scope_policy_version
                == COMPANY_AND_SELECTED_PRODUCT_SCOPE_POLICY_V3
            )
            assert (
                await compile_product_profile_card(
                    workspace_id=scope.workspace_id,
                    brand_id=scope.brand_id,
                    product_id=pin_b.product_id,
                    conn_factory=cf,
                )
            ).product_id == products[1].product_id
            assert (
                await compile_product_knowledge_card(
                    workspace_id=scope.workspace_id,
                    client_entity_id=scope.client_entity_id,
                    product_id=pin_a.product_id,
                    product_kb_version=pin_a.product_kb_version,
                    conn_factory=cf,
                )
            ).product_kb_version == product_version
            empty_card = await compile_product_knowledge_card(
                workspace_id=scope.workspace_id,
                client_entity_id=scope.client_entity_id,
                product_id=pin_b.product_id,
                product_kb_version=pin_b.product_kb_version,
                conn_factory=cf,
            )
            assert empty_card.product_kb_version == 1
            assert not empty_card.known_fields
            assert set(empty_card.open_gaps) == set(PRODUCT_KNOWLEDGE_FIELDS)
            assert (empty_card.coverage.filled, empty_card.coverage.required) == (
                0,
                len(PRODUCT_KNOWLEDGE_FIELDS),
            )

            # Selection cannot rewrite the already-running opening turn's scope.
            assert original_pin_a.product_id is None and original_pin_a.product_kb_version is None
            assert original_pin_b.product_id is None and original_pin_b.product_kb_version is None

            gate_a = await get_gate(
                conn,
                workspace_id=scope.workspace_id,
                gate_id=UUID(str(opened_a.references["gate_id"])),
            )
            assert gate_a is not None and gate_a.answer is not None
            assert gate_a.answer.selected_option_ref == products[0].product_id

            # The model cannot perform the write, and a human cannot repoint the immutable project.
            with pytest.raises(PreconditionFailed, match="human_required"):
                await invoke_tool(
                    registry,
                    "confirm_project_product",
                    {"project_id": project_a.project_id, "product_id": products[2].product_id},
                    agent_context,
                    idempotency_ttl_s=60,
                )
            human_context = ToolContext(
                workspace_id=scope.workspace_id,
                actor="human",
                principal_kind="human",
                actor_id=user_id,
                membership_id=membership_id,
                action_ref=derive_turn_action_ref(uuid4()),
                conn_factory=cf,
                operation_id=new_operation_id(),
            )
            replayed_selection = await invoke_tool(
                registry,
                "confirm_project_product",
                {"project_id": project_b.project_id, "product_id": products[1].product_id},
                human_context,
                idempotency_ttl_s=60,
            )
            assert replayed_selection.references["product_id"] == products[1].product_id
            assert (
                await current_kb_version(
                    conn,
                    scope.client_entity_id,
                    workspace_id=scope.workspace_id,
                    product_id=products[1].product_id,
                )
                == 1
            )
            with pytest.raises(PreconditionFailed, match="project_product_conflict"):
                await invoke_tool(
                    registry,
                    "confirm_project_product",
                    {"project_id": project_a.project_id, "product_id": products[2].product_id},
                    human_context,
                    idempotency_ttl_s=60,
                )

            foreign_brand = await create_brand(
                conn, workspace_id=scope.workspace_id, name="Foreign S5-F Brand"
            )
            foreign_product = await create_product(
                conn,
                workspace_id=scope.workspace_id,
                brand_id=foreign_brand.brand_id,
                name="Foreign product",
            )
            project_c = await create_project(
                conn,
                workspace_id=scope.workspace_id,
                brand_id=scope.brand_id,
                name="S5-F Project C",
            )
            with pytest.raises(PreconditionFailed, match="project_product_not_found"):
                await invoke_tool(
                    registry,
                    "confirm_project_product",
                    {"project_id": project_c.project_id, "product_id": foreign_product.product_id},
                    human_context,
                    idempotency_ttl_s=60,
                )

    run_async(scenario())
