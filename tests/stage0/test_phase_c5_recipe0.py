"""C5.4 parity and durability checks for the executable Recipe #0 revision."""

from __future__ import annotations

import asyncio
import hashlib
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from typing import Any
from uuid import UUID

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_api import ExecutionRunEventWriter, StorageParameterArtifactStore, build_tool_invoker
from clue_api.execution_wiring import StorageExecutionParameterStore
from clue_api.phase_c_wiring import Stage0ScrapeBinder, build_stage0_scrape_binder
from clue_api.recipe_wiring import (
    build_recipe_pin_registry,
    load_system_recipe_definitions,
    seed_system_recipes,
)
from clue_api.stage0_recipe import RecipeStep, Stage0StepPinProvider, ToolbeltRecipeRunner
from clue_api.toolbelt_wiring import build_toolbelt
from clue_config import Settings
from clue_core import (
    AccountEntity,
    AdaptContext,
    ClaimDraft,
    ContactEntity,
    Entity,
    EntityId,
    FieldDef,
    ICPCreatedFrom,
    NormalizedText,
    OnboardingInputKind,
    PreSpendDecision,
    PreSpendRequest,
    PreSpendVerdict,
    RawArtifact,
    TargetLock,
    new_operation_id,
)
from clue_db import ConnFactory
from clue_execution import (
    CompatibilityLoader,
    DbExecutionJournal,
    DbExecutionStarter,
    DbRecipeReader,
    DbRecipeRepository,
    ExecutionStatus,
    RecipeExecutor,
    RecipeLifecycle,
)
from clue_fleet import WorkId, acquire_work_lease
from clue_research.adapters import CallableClaimExtractor
from clue_research.icp import create_icp_spec
from clue_research.sources import unbind_resolver
from clue_research.stage0 import compile_product_context
from clue_research.stage0.fields import CLIENT_VALUE_PROP
from clue_spine import create_brand, create_product, create_project
from clue_storage import artifact_key as make_artifact_key
from clue_storage import record_artifact
from clue_toolbelt import ToolContext
from tests._workspace import seed_workspace
from tests.stage0.conftest import rollback_conn, run_async
from tests.toolbelt.conftest import InMemoryStore

pytestmark = pytest.mark.usefixtures("require_stage0_db")


class _MemoryStorage:
    def __init__(self) -> None:
        self.blobs: dict[str, bytes] = {}

    async def put(self, key: str, data: bytes, *, media_type: str) -> None:
        self.blobs[key] = data

    async def get(self, key: str) -> bytes:
        return self.blobs[key]

    async def delete(self, key: str) -> None:
        self.blobs.pop(key, None)

    async def exists(self, key: str) -> bool:
        return key in self.blobs

    async def presign(self, key: str, *, expires_in: int = 3600) -> str:
        return f"memory://{key}"

    async def list_blobs(self) -> AsyncIterator[tuple[str, datetime]]:
        return
        yield


class _ReconScraper:
    def scrape(self, ref: str, ctx: AdaptContext) -> RawArtifact:
        del ctx
        return RawArtifact(
            ref=ref,
            media_type="text/markdown",
            content=b"# Client\nOur value proposition is revenue clarity.",
        )


class _PassGate:
    async def check(self, request: PreSpendRequest) -> PreSpendDecision:
        del request
        return PreSpendDecision(verdict=PreSpendVerdict.PASS)

    async def assemble_target_lock(
        self,
        entity: AccountEntity | ContactEntity,
        field: FieldDef,
    ) -> TargetLock:
        return TargetLock(
            entity_id=entity.id,
            no_drift_instruction=f"Remain locked to {entity.id} for {field.field_key}",
        )


def _factory(conn: AsyncConnection) -> ConnFactory:
    lock = asyncio.Lock()

    @asynccontextmanager
    async def factory() -> AsyncIterator[AsyncConnection]:
        async with lock:
            nested = await conn.begin_nested()
            try:
                yield conn
            except BaseException:
                await nested.rollback()
                raise
            else:
                await nested.commit()

    return factory


def _extract(
    normalized: NormalizedText,
    entity: Entity,
    field: FieldDef,
) -> list[ClaimDraft]:
    del normalized, entity, field
    return []


async def _recipe_runner(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    storage: _MemoryStorage,
    binder: Stage0ScrapeBinder,
    gate: _PassGate,
    project_id: str,
    crash_hook: Any | None = None,
) -> tuple[ToolbeltRecipeRunner, RecipeExecutor, int, object]:
    factory = _factory(conn)
    registry = build_toolbelt(
        storage=storage,
        conn_factory=factory,
        pre_spend_gate=gate,
        stage0_scrape_binder=binder,
    )
    pin_registry = build_recipe_pin_registry(
        tool_registry=registry,
        conn_factory=factory,
    )
    compatibility = CompatibilityLoader(pin_registry)
    repository = DbRecipeRepository(conn_factory=factory)
    lifecycle = RecipeLifecycle(
        repository=repository,
        tool_catalog=registry,
        compatibility_loader=compatibility,
    )
    definitions = tuple(
        definition
        for definition in load_system_recipe_definitions()
        if definition.recipe_key == "recipe0-stage0"
    )
    revisions = await seed_system_recipes(
        repository=repository,
        lifecycle=lifecycle,
        definitions=definitions,
    )
    recipe0_v3 = next(
        revision
        for definition, revision in zip(definitions, revisions, strict=True)
        if definition.recipe_key == "recipe0-stage0" and definition.version == 3
    )
    artifact_store = StorageParameterArtifactStore(
        storage=storage,
        conn_factory=factory,
    )
    parameters = StorageExecutionParameterStore(artifact_store)
    artifact_key, digest = await parameters.snapshot(
        workspace_id=workspace_id,
        parameters={},
    )
    journal = DbExecutionJournal(transport=ExecutionRunEventWriter())
    starter = DbExecutionStarter(
        conn_factory=factory,
        recipes=DbRecipeReader(conn_factory=factory),
        compatibility=compatibility,
        journal=journal,
    )
    started = await starter.start(
        workspace_id=workspace_id,
        recipe_revision_id=recipe0_v3.recipe_revision_id,
        parameters={},
        parameter_artifact_key=artifact_key,
        parameter_manifest_hash=digest,
        actor="human",
        project_id=project_id,
    )
    invoker = build_tool_invoker(
        registry=registry,
        idempotency_store=InMemoryStore(),
        storage=storage,
        settings=Settings(_env_file=None),
        conn_factory=factory,
        crash_hook=crash_hook,
    )
    executor = RecipeExecutor(
        conn_factory=factory,
        recipes=DbRecipeReader(conn_factory=factory),
        compatibility=compatibility,
        journal=journal,
        parameters=parameters,
        tool_invoker=invoker,
    )
    lease = await acquire_work_lease(
        conn,
        work_id=WorkId(started.execution_id),
        worker_id="recipe0-test",
        ttl=timedelta(seconds=60),
    )
    assert lease is not None
    opened = await executor.execute(
        started.execution_id,
        worker_id="recipe0-test",
        lease_generation=lease.generation,
    )
    assert opened.status is ExecutionStatus.AWAITING_INPUT
    return (
        ToolbeltRecipeRunner(
            executor=executor,
            pin_provider=Stage0StepPinProvider(
                compatibility=compatibility,
                conn_factory=factory,
            ),
        ),
        executor,
        lease.generation,
        started.execution_id,
    )


async def _url_recon_fingerprint(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    durable: bool,
    crash_target: str | None = None,
    memory_disabled: bool = False,
) -> dict[str, object]:
    storage = _MemoryStorage()
    brand = await create_brand(conn, workspace_id=workspace_id, name="Recipe 0 brand")
    product = await create_product(
        conn,
        workspace_id=workspace_id,
        brand_id=brand.brand_id,
        name="Recipe 0 product",
    )
    project = await create_project(
        conn,
        workspace_id=workspace_id,
        brand_id=brand.brand_id,
        name="Recipe 0 project",
    )
    body = "https://recipe0.example"
    digest = hashlib.sha256(body.encode()).hexdigest()
    artifact_key = make_artifact_key(workspace_id, digest)
    await record_artifact(
        conn,
        storage_key=artifact_key,
        workspace_id=workspace_id,
        content_sha256=digest,
        media_type="text/plain",
        size_bytes=len(body),
    )
    binder = build_stage0_scrape_binder(
        extractor=CallableClaimExtractor(_extract),
        scraper=_ReconScraper(),
    )
    factory = _factory(conn)
    gate = _PassGate()
    registry = build_toolbelt(
        storage=storage,
        conn_factory=factory,
        pre_spend_gate=gate,
        stage0_scrape_binder=binder,
    )
    execution_id = None
    runner = None
    executor = None
    generation = None
    crashed = False

    async def crash(
        point: str,
        *,
        context: ToolContext,
        start: object,
    ) -> None:
        del start
        nonlocal crashed
        if (
            crash_target is not None
            and context.execution_node_key == crash_target
            and point == "after_domain_commit"
            and not crashed
        ):
            crashed = True
            raise asyncio.CancelledError

    if durable:
        if memory_disabled:
            await conn.execute(
                text(
                    """
                    INSERT INTO memory_switch (workspace_id, enabled, updated_by)
                    VALUES (:workspace_id, false, 'recipe0-test')
                    ON CONFLICT (workspace_id) DO UPDATE
                    SET enabled = false, updated_by = EXCLUDED.updated_by
                    """
                ),
                {"workspace_id": workspace_id},
            )
        runner, executor, generation, execution_id = await _recipe_runner(
            conn,
            workspace_id=workspace_id,
            storage=storage,
            binder=binder,
            gate=gate,
            project_id=project.project_id,
            crash_hook=crash,
        )

    async def invoke(step: RecipeStep, *, actor: str):
        ctx = ToolContext(
            workspace_id=workspace_id,
            actor=actor,
            conn_factory=factory,
            operation_id=new_operation_id(),
            execution_id=execution_id,
        )
        if runner is not None:
            try:
                return await runner.run_step(step, ctx=ctx)
            except asyncio.CancelledError:
                assert step.step_id == crash_target
                return await runner.run_step(step, ctx=ctx)
        tool = registry.get(step.tool_name, step.tool_version)
        inputs = tool.input_model.model_validate(step.input_refs)
        assert await tool.preconditions(inputs, ctx) == ()
        return await tool.invoke(inputs, ctx)

    submitted = await invoke(
        RecipeStep(
            step_id="website_input",
            tool_name="submit_onboarding_input",
            tool_version="1",
            input_refs={
                "brand_id": brand.brand_id,
                "kind": OnboardingInputKind.WEBSITE.value,
                "artifact_key": artifact_key,
                "content_sha256": digest,
                "product_id": product.product_id,
                "project_id": project.project_id,
            },
        ),
        actor="human",
    )
    recon_inputs = {
        "brand_id": brand.brand_id,
        "name": "Recipe 0 Client",
        "website": body,
        "onboarding_input_ids": [submitted.references["onboarding_input_id"]],
        "product_id": product.product_id,
        "project_id": project.project_id,
    }
    fast = await invoke(
        RecipeStep(
            step_id="fast_recon",
            tool_name="start_recon",
            tool_version="1",
            input_refs=recon_inputs,
            depends_on=("website_input",) if durable else (),
        ),
        actor="agent",
    )
    background = await invoke(
        RecipeStep(
            step_id="background_recon",
            tool_name="start_recon",
            tool_version="1",
            input_refs=recon_inputs,
            depends_on=("fast_recon",) if durable else (),
        ),
        actor="agent",
    )
    confirmed_product = await invoke(
        RecipeStep(
            step_id="confirm_product",
            tool_name="confirm_project_product",
            tool_version="1",
            input_refs={
                "project_id": project.project_id,
                "product_id": product.product_id,
            },
            depends_on=("background_recon",) if durable else (),
        ),
        actor="human",
    )
    client_entity_id = str(background.references["client_entity_id"])
    client_kb_version = int(background.references["fast_client_kb_version"])
    spec = await create_icp_spec(
        conn,
        workspace_id=workspace_id,
        icp_key="primary",
        created_from=ICPCreatedFrom.SYNTHESIS,
        activate=True,
        client_entity_id=EntityId(UUID(client_entity_id)),
        client_kb_version=client_kb_version,
        product_id=product.product_id,
    )
    context = await compile_product_context(
        conn,
        workspace_id=workspace_id,
        brand_id=brand.brand_id,
        product_id=product.product_id,
        client_entity_id=EntityId(UUID(client_entity_id)),
        client_kb_version=client_kb_version,
        claim_refs=(),
    )

    answer = "Our value proposition is pipeline confidence."
    answer_digest = hashlib.sha256(answer.encode()).hexdigest()
    answer_key = make_artifact_key(workspace_id, answer_digest)
    await record_artifact(
        conn,
        storage_key=answer_key,
        workspace_id=workspace_id,
        content_sha256=answer_digest,
        media_type="text/plain",
        size_bytes=len(answer),
    )
    interview_input = await invoke(
        RecipeStep(
            step_id="interview_input",
            tool_name="submit_onboarding_input",
            tool_version="1",
            input_refs={
                "brand_id": brand.brand_id,
                "kind": OnboardingInputKind.USER_TURN.value,
                "artifact_key": answer_key,
                "content_sha256": answer_digest,
                "product_id": product.product_id,
                "project_id": project.project_id,
                "client_entity_id": client_entity_id,
            },
            depends_on=("confirm_product",) if durable else (),
        ),
        actor="human",
    )
    interview = await invoke(
        RecipeStep(
            step_id="interview_answer",
            tool_name="record_interview_answer",
            tool_version="1",
            input_refs={
                "brand_id": brand.brand_id,
                "onboarding_input_id": interview_input.references["onboarding_input_id"],
                "artifact_key": answer_key,
                "answer": answer,
                "client_entity_id": client_entity_id,
                "product_id": product.product_id,
                "project_id": project.project_id,
                "statements": [
                    {
                        "route": "claim",
                        "route_key": CLIENT_VALUE_PROP,
                        "quote_start": 0,
                        "quote_end": len(answer),
                        "entity_id": client_entity_id,
                        "entity_type": "account",
                        "field_key": CLIENT_VALUE_PROP,
                        "value": "pipeline confidence",
                    }
                ],
            },
            depends_on=("interview_input",) if durable else (),
        ),
        actor="human",
    )

    correction = "Correction: our value proposition is revenue certainty."
    correction_digest = hashlib.sha256(correction.encode()).hexdigest()
    correction_key = make_artifact_key(workspace_id, correction_digest)
    await record_artifact(
        conn,
        storage_key=correction_key,
        workspace_id=workspace_id,
        content_sha256=correction_digest,
        media_type="text/plain",
        size_bytes=len(correction),
    )
    correction_input = await invoke(
        RecipeStep(
            step_id="correction_input",
            tool_name="submit_onboarding_input",
            tool_version="1",
            input_refs={
                "brand_id": brand.brand_id,
                "kind": OnboardingInputKind.USER_TURN.value,
                "artifact_key": correction_key,
                "content_sha256": correction_digest,
                "product_id": product.product_id,
                "project_id": project.project_id,
                "client_entity_id": client_entity_id,
            },
            depends_on=("interview_answer",) if durable else (),
        ),
        actor="human",
    )
    corrected = await invoke(
        RecipeStep(
            step_id="correction_answer",
            tool_name="record_interview_answer",
            tool_version="1",
            input_refs={
                "brand_id": brand.brand_id,
                "onboarding_input_id": correction_input.references["onboarding_input_id"],
                "artifact_key": correction_key,
                "answer": correction,
                "client_entity_id": client_entity_id,
                "product_id": product.product_id,
                "project_id": project.project_id,
                "statements": [
                    {
                        "route": "claim",
                        "route_key": CLIENT_VALUE_PROP,
                        "quote_start": 0,
                        "quote_end": len(correction),
                        "entity_id": client_entity_id,
                        "entity_type": "account",
                        "field_key": CLIENT_VALUE_PROP,
                        "value": "revenue certainty",
                        "correction_of_statement_id": interview.references["statement_ids"][0],
                        "correction_of_claim_id": interview.references["claim_refs"][0],
                    }
                ],
            },
            depends_on=("correction_input",) if durable else (),
        ),
        actor="human",
    )
    readiness = await invoke(
        RecipeStep(
            step_id="readiness",
            tool_name="evaluate_stage0_readiness",
            tool_version="1",
            input_refs={
                "brand_id": brand.brand_id,
                "gate": "discovery_spend",
                "metrics": {"open_policy_blocks": 1},
                "product_id": product.product_id,
                "project_id": project.project_id,
                "client_entity_id": client_entity_id,
                "client_kb_version": client_kb_version,
                "icp_key": spec.icp_key,
                "icp_version": spec.version,
                "product_context_version_id": str(context.version_id),
            },
            depends_on=("correction_answer",) if durable else (),
        ),
        actor="agent",
    )
    override = await invoke(
        RecipeStep(
            step_id="readiness_override",
            tool_name="override_stage0_readiness",
            tool_version="1",
            input_refs={
                "readiness_decision_id": readiness.references["readiness_decision_id"],
                "gate": "discovery_spend",
                "reason": "Human accepts the documented gap.",
            },
            depends_on=("readiness",) if durable else (),
        ),
        actor="human",
    )
    run = await invoke(
        RecipeStep(
            step_id="confirmed_run",
            tool_name="start_confirmed_project_run",
            tool_version="1",
            input_refs={
                "project_id": project.project_id,
                "client_entity_id": client_entity_id,
                "client_kb_version": client_kb_version,
                "product_id": product.product_id,
                "product_context_version_id": str(context.version_id),
                "readiness_decision_id": readiness.references["readiness_decision_id"],
                "icp_key": spec.icp_key,
                "icp_version": spec.version,
            },
            depends_on=("readiness_override",) if durable else (),
        ),
        actor="human",
    )
    fingerprint = {
        "input_kind": submitted.references["kind"],
        "fast": (
            fast.references["fast_status"],
            fast.references["background_status"],
        ),
        "background": (
            background.references["fast_status"],
            background.references["background_status"],
        ),
        "same_recon": (fast.references["recon_run_id"] == background.references["recon_run_id"]),
        "confirmed_product": (confirmed_product.references["product_id"] == product.product_id),
        "interview_claims": len(interview.references["claim_refs"]),
        "correction_claims": len(corrected.references["claim_refs"]),
        "readiness": readiness.references["verdict"],
        "override": bool(override.references["readiness_override_id"]),
        "run_phase": run.references["phase"],
    }
    if execution_id is not None:
        rows = (
            await conn.execute(
                text(
                    """
                    SELECT node_key, definition_json
                    FROM execution_node
                    WHERE execution_id = :execution_id
                      AND declared_by_node_id IS NOT NULL
                    ORDER BY node_key
                    """
                ),
                {"execution_id": execution_id},
            )
        ).all()
        assert len(rows) == 11
        serialized_definitions = str([row[1] for row in rows])
        assert body not in serialized_definitions
        assert answer not in serialized_definitions
        assert correction not in serialized_definitions
        handoff_run_id = (
            await conn.execute(
                text(
                    """
                    SELECT payload_json #>> '{result,references,project_run_id}'
                    FROM execution_event e
                    JOIN execution_node n ON n.id = e.node_id
                    WHERE e.execution_id = :execution_id
                      AND n.node_key = 'confirmed_run'
                      AND e.event_type = 'node.completed'
                    """
                ),
                {"execution_id": execution_id},
            )
        ).scalar_one()
        assert handoff_run_id == run.references["project_run_id"]
        assert executor is not None and generation is not None
        await executor.decide_gate(
            execution_id=execution_id,
            node_key="stage0_interactions",
            actor="human",
            decision="stage0_complete",
        )
        completed = await executor.execute(
            execution_id,
            worker_id="recipe0-test",
            lease_generation=generation,
        )
        assert completed.status is ExecutionStatus.COMPLETED
        if crash_target is not None:
            assert crashed
        if memory_disabled:
            memory_statuses = {
                str(row[0])
                for row in (
                    await conn.execute(
                        text(
                            """
                            SELECT resolved_status FROM execution_pin
                            WHERE execution_id = :execution_id
                              AND kind = 'memory_switch'
                            """
                        ),
                        {"execution_id": execution_id},
                    )
                ).all()
            }
            assert memory_statuses == {"disabled"}
    return fingerprint


def test_recipe0_matches_c4_stage0_normalized_outcomes() -> None:
    async def scenario() -> None:
        async with rollback_conn(workspace_id="recipe0-direct") as conn:
            direct = await _url_recon_fingerprint(
                conn,
                workspace_id="recipe0-direct",
                durable=False,
            )
            try:
                unbind_resolver("firecrawl_site")
                await seed_workspace(conn, "recipe0-durable")
                durable = await _url_recon_fingerprint(
                    conn,
                    workspace_id="recipe0-durable",
                    durable=True,
                )
            finally:
                unbind_resolver("firecrawl_site")
            assert (
                durable
                == direct
                == {
                    "input_kind": "website",
                    "fast": ("completed", "queued"),
                    "background": ("completed", "completed"),
                    "same_recon": True,
                    "confirmed_product": True,
                    "interview_claims": 1,
                    "correction_claims": 1,
                    "readiness": "not_ready",
                    "override": True,
                    "run_phase": "discovery",
                }
            )

    run_async(scenario())


@pytest.mark.parametrize(
    "crash_target",
    ("fast_recon", "background_recon", "interview_answer", "confirmed_run"),
)
def test_recipe0_recovers_stage0_effect_after_domain_commit(crash_target: str) -> None:
    async def scenario() -> None:
        workspace_id = f"recipe0-crash-{crash_target}"
        async with rollback_conn(workspace_id=workspace_id) as conn:
            try:
                fingerprint = await _url_recon_fingerprint(
                    conn,
                    workspace_id=workspace_id,
                    durable=True,
                    crash_target=crash_target,
                )
            finally:
                unbind_resolver("firecrawl_site")
            assert fingerprint["run_phase"] == "discovery"
            assert fingerprint["correction_claims"] == 1

    run_async(scenario())


def test_recipe0_pins_disabled_optional_memory_without_reenabling_it() -> None:
    async def scenario() -> None:
        workspace_id = "recipe0-memory-disabled"
        async with rollback_conn(workspace_id=workspace_id) as conn:
            try:
                fingerprint = await _url_recon_fingerprint(
                    conn,
                    workspace_id=workspace_id,
                    durable=True,
                    memory_disabled=True,
                )
            finally:
                unbind_resolver("firecrawl_site")
            assert fingerprint["interview_claims"] == 1

    run_async(scenario())
