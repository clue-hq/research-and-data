"""PC-C8 task 1.3: the project card is what actually reaches the model, and it is reproducible.

Three guarantees the §10 contract delta has to keep, none of which the card compiler can prove on
its own (they are properties of the *wiring*):

* **AC-5 — the model sees the card, not rows.** Walk the messages the real assembler emits and
  assert the L3 body validates as a :class:`Stage0ProjectCard`, with none of the ``to_jsonb(row)``
  column vocabulary the retired stage/readiness snapshots shipped.
* **AC-8 — determinism across a process restart.** The same durable state compiles to the same
  ``content_sha256`` in two *separate interpreters* with different ``PYTHONHASHSEED``. In-process
  repetition cannot catch a set/dict iteration order leaking into the bytes; content-addressed
  artifact reuse (AC-9) is exactly what breaks when it does.
* **The journal role label.** ``agent_artifact_ref.ref_role`` carried ``stage_snapshot`` and
  ``readiness_snapshot``; one turn now writes one ``project_card`` row, and the DB CHECK
  (migration ``933c7b604f1c``) refuses the retired vocabulary.

DB-backed tests follow the ``tests/api`` conventions: a per-branch ``CLUE_DATABASE_URL``, one
rollback-only transaction per scenario, and ``pytest.skip`` when no database is reachable.
"""

from __future__ import annotations

import inspect
import json
import os
import subprocess
import sys
import textwrap
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

import pytest
from pydantic import ValidationError
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_agents import AgentRole
from clue_agents.contracts import MODEL_FORBIDDEN_AUTHORITY_KEYS
from clue_api.account_research_turn_wiring import (
    DbCompiledContextCardReader,
    account_research_card_payload,
)
from clue_api.agent_execution_wiring import _trusted_tool_arguments
from clue_api.agent_platform_wiring import build_agent_context_assembler
from clue_api.agent_registry_wiring import build_agent_profile_registry
from clue_api.agent_turn_wiring import DbAgentTurnJournal, DurableAgentArtifactStore
from clue_api.stage0_tools import RecordInterviewAnswerInput, RecordInterviewAnswerTool
from clue_api.stage0_trial import Stage0Trial, Stage0TrialPaths, stage0_trial_context_policy
from clue_api.toolbelt_wiring import build_toolbelt
from clue_core import (
    AccountStatus,
    EntityId,
    EntityType,
    IdentityBinding,
    MemoryType,
    OnboardingInputKind,
    ProjectRunId,
    RunId,
    UseClass,
    new_operation_id,
)
from clue_db import db_lifespan
from clue_projections import STAGE0_PROJECT_CARD_MEDIA_TYPE, Stage0ProjectCard
from clue_research.claimstore import WorkspaceScope, claims_by_ids
from clue_research.durable import ResearchPlan
from clue_research.identity import insert_account_entity, mark_merged
from clue_research.stage0 import (
    InterviewClaimEntityRefused,
    InterviewRoute,
    InterviewStatement,
    load_client_knowledge_pack,
    resolve_claim_entity,
    route_interview_answer,
    submit_onboarding_input,
)
from clue_research.stage0.fields import CLIENT_PRODUCT
from clue_spine import Project, create_brand, create_product, create_project, create_workspace
from clue_storage import FsStorage
from clue_toolbelt import ToolContext
from tests.agents.conftest import constitution
from tests.api.test_c8_slice0_evidence import (
    _ANSWER,
    _NoMemory,
    _seed_material_turns,
    _state,
    _turn_request,
)
from tests.db.conftest import _db_available, run_async

# Column names only a ``to_jsonb(row)`` dump carries. The retired stage/readiness snapshots shipped
# whole `volunteered_statement` / `readiness_decision` / `icp_spec` rows, so every one of these was
# in front of the model; a typed card must carry none of them.
_ROW_SHAPE_KEYS = (
    "created_by_actor",
    "onboarding_input_id",
    "quote_sha256",
    "superseded_by",
    "correction_of_id",
    "policy_hash",
    "agent_sufficiency_status",
    "gap_refs",
)


@pytest.fixture
def stage0_db_available() -> bool:
    return _db_available()


@asynccontextmanager
async def _seeded_trial(tmp_path: Path, *, slug: str) -> AsyncIterator[tuple[Any, ...]]:
    """One rollback-only transaction holding a seeded Stage-0 project and a shell trial."""

    state = _state(slug)
    async with db_lifespan() as engine:
        conn = await engine.connect()
        outer = await conn.begin()

        @asynccontextmanager
        async def connection_factory() -> AsyncIterator[AsyncConnection]:
            yield conn

        try:
            await create_workspace(conn, workspace_id=state.workspace_id, name="C8 card wiring")
            brand = await create_brand(
                conn, workspace_id=state.workspace_id, name="Aura", brand_id=state.brand_id
            )
            product = await create_product(
                conn,
                workspace_id=state.workspace_id,
                brand_id=brand.brand_id,
                name="Aura ABM",
                product_id=state.product_id,
            )
            await create_project(
                conn,
                workspace_id=state.workspace_id,
                brand_id=brand.brand_id,
                product_id=product.product_id,
                name="Aura Stage 0 trial",
                project_id=state.project_id,
            )
            client = await insert_account_entity(
                conn,
                canonical_name="Aura AI",
                primary_domain="aura.invalid",
                workspace_id=state.workspace_id,
                status=AccountStatus.ACTIVE,
            )
            seeded = state.model_copy(update={"client_entity_id": client})
            artifacts = DurableAgentArtifactStore(
                storage=FsStorage(tmp_path / "artifacts"),
                conn_factory=connection_factory,
            )
            trial = object.__new__(Stage0Trial)
            trial.state = seeded
            trial.paths = Stage0TrialPaths.for_session(tmp_path, seeded.session_slug)
            trial._components = SimpleNamespace(artifacts=artifacts)  # type: ignore[assignment]
            trial._conn_factory = connection_factory  # type: ignore[assignment]
            # A turn's context receipt and artifact refs are journaled against its execution, so
            # the execution row is the one non-Stage-0 durable prerequisite these tests need.
            await conn.execute(
                text(
                    "INSERT INTO execution (id, workspace_id, project_id, started_by, "
                    "parameter_manifest_hash, pin_manifest_hash) "
                    "VALUES (:id, :workspace, :project, 'human', :hash, :hash)"
                ),
                {
                    "id": uuid5(seeded.session_id, "c8-slice0-execution"),
                    "workspace": seeded.workspace_id,
                    "project": seeded.project_id,
                    "hash": "0" * 64,
                },
            )
            await _seed_material_turns(conn, artifacts, state=seeded, statements=6, decisions=5)
            yield trial, conn, artifacts, connection_factory
        finally:
            await outer.rollback()
            await conn.close()


def test_the_assembled_l3_messages_carry_the_card_schema_and_no_row_dumps(
    tmp_path: Path,
    stage0_db_available: bool,
) -> None:
    """AC-5: walk what the model is actually handed, not what the compiler returned."""

    if not stage0_db_available:
        pytest.skip("requires a migrated per-branch Postgres database")

    async def scenario() -> None:
        async with _seeded_trial(tmp_path, slug=f"ac5-{uuid4().hex[:8]}") as (
            trial,
            _conn,
            artifacts,
            connection_factory,
        ):
            card_ref = await trial._project_card_ref()
            budget_ref = await trial._artifact(
                "application/vnd.clue.agent-budget-envelope+json",
                {"schema_version": "1", "limit_millicents": 1_000_000},
            )
            registry = build_agent_profile_registry(build_toolbelt(storage=None, gateway=None))
            resolved = registry.resolve(AgentRole.HEAD_OF_ABM)
            manifest_ref = await trial._artifact(
                "application/vnd.clue.agent-resource-manifest+json",
                resolved.resource_manifest.model_dump(mode="json"),
            )
            user_ref = await artifacts.persist_body(
                workspace_id=trial.state.workspace_id,
                data=_ANSWER.encode(),
                media_type="text/plain",
            )
            assembler = build_agent_context_assembler(
                resolved_profile=resolved,
                artifacts=artifacts,
                cards=DbCompiledContextCardReader(conn_factory=connection_factory),
                memory=cast(Any, _NoMemory()),
                memory_recipe="recipe0-stage0@3",
                requested_memory_types=(MemoryType.PREFERENCE, MemoryType.BEHAVIORAL_LEARNING),
                policy=stage0_trial_context_policy(),
                conn_factory=connection_factory,
            )
            request = _turn_request(
                state=trial.state,
                resolved=resolved,
                card_ref=card_ref,
                budget_ref=budget_ref,
                manifest_ref=manifest_ref,
                user_ref=user_ref,
            )
            await DbAgentTurnJournal(conn_factory=connection_factory).create(
                request=request, profile=resolved.profile
            )
            context = await assembler.assemble(
                request=request, profile=resolved.profile, history=()
            )

            # The card reaches the model as one materialized L3 file, and it round-trips through
            # the frozen schema — so it is the typed projection, not a dump that happens to fit.
            l3 = [
                item
                for item in context.materializations
                if item.path.startswith("context/project/")
            ]
            assert sorted(item.path for item in l3) == [
                "context/project/budget.json",
                "context/project/project_card.json",
            ]
            card_file = next(
                item for item in l3 if item.path == "context/project/project_card.json"
            )
            card = Stage0ProjectCard.model_validate_json(card_file.data)
            assert card.canonical_bytes() == card_file.data
            assert card.project.project_id == trial.state.project_id
            assert card_ref.media_type == STAGE0_PROJECT_CARD_MEDIA_TYPE

            # No row vocabulary anywhere in what the model reads, L3 messages included.
            bodies = "".join(str(getattr(item, "content", "")) for item in context.messages)
            for key in _ROW_SHAPE_KEYS:
                assert key not in card_file.data.decode()
                assert f'"{key}"' not in bodies

    run_async(scenario())


def test_one_turn_journals_one_project_card_ref_and_no_retired_snapshot_roles(
    tmp_path: Path,
    stage0_db_available: bool,
) -> None:
    """The journal vocabulary flipped with the constitution, and the DB enforces the new one."""

    if not stage0_db_available:
        pytest.skip("requires a migrated per-branch Postgres database")

    async def scenario() -> None:
        async with _seeded_trial(tmp_path, slug=f"role-{uuid4().hex[:8]}") as (
            trial,
            conn,
            artifacts,
            connection_factory,
        ):
            card_ref = await trial._project_card_ref()
            budget_ref = await trial._artifact(
                "application/vnd.clue.agent-budget-envelope+json",
                {"schema_version": "1", "limit_millicents": 1_000_000},
            )
            registry = build_agent_profile_registry(build_toolbelt(storage=None, gateway=None))
            resolved = registry.resolve(AgentRole.HEAD_OF_ABM)
            manifest_ref = await trial._artifact(
                "application/vnd.clue.agent-resource-manifest+json",
                resolved.resource_manifest.model_dump(mode="json"),
            )
            user_ref = await artifacts.persist_body(
                workspace_id=trial.state.workspace_id,
                data=_ANSWER.encode(),
                media_type="text/plain",
            )
            request = _turn_request(
                state=trial.state,
                resolved=resolved,
                card_ref=card_ref,
                budget_ref=budget_ref,
                manifest_ref=manifest_ref,
                user_ref=user_ref,
            )
            journal = DbAgentTurnJournal(conn_factory=connection_factory)
            await journal.create(request=request, profile=resolved.profile)

            roles = [
                row[0]
                for row in (
                    await conn.execute(
                        text(
                            "SELECT ref_role, artifact_key FROM agent_artifact_ref "
                            "WHERE turn_id = :turn ORDER BY ref_role"
                        ),
                        {"turn": request.turn_id},
                    )
                ).all()
            ]
            assert roles == [
                "budget_envelope",
                "project_card",
                "resource_manifest",
                "user_message",
            ]
            card_row = (
                await conn.execute(
                    text(
                        "SELECT artifact_key FROM agent_artifact_ref "
                        "WHERE turn_id = :turn AND ref_role = 'project_card'"
                    ),
                    {"turn": request.turn_id},
                )
            ).scalar_one()
            assert card_row == card_ref.artifact_key

            # And the retired vocabulary is refused by the schema, not merely unused.
            with pytest.raises(Exception, match="agent_artifact_ref_role"):
                await conn.execute(
                    text(
                        "INSERT INTO agent_artifact_ref (id, turn_id, workspace_id, owner_kind, "
                        "owner_id, ref_role, ordinal, artifact_key, artifact_sha256, "
                        "retention_class) VALUES (:id, :turn, :ws, 'turn', :turn, "
                        "'stage_snapshot', 0, :key, :sha, 'agent-turn-standard')"
                    ),
                    {
                        "id": uuid5(request.turn_id, "retired-role"),
                        "turn": request.turn_id,
                        "ws": trial.state.workspace_id,
                        "key": card_ref.artifact_key,
                        "sha": card_ref.sha256,
                    },
                )

    run_async(scenario())


def test_a_claim_route_statement_from_the_cards_id_lands_as_a_tier_1_claim(
    tmp_path: Path,
    stage0_db_available: bool,
) -> None:
    """R1 (PC-C8 §8, B1): the card's id survives the whole real routing path as tier-1 evidence.

    Task 1.3 shipped layer 1 — ``Stage0CardProject.client_entity_id``, because 1.3 had closed both
    other channels (the tool field became engine-injected authority; the stage snapshot that said
    "use the supplied client entity id" was deleted with its artifact). That only mattered if the
    id actually *worked*, and the 1.3 test stopped at model construction.

    This runs it end to end through the production ``route_interview_answer``: read the id out of
    the card (never out of ``trial.state`` — taking it from the card is the whole point, and a
    state-sourced test would still pass with the field missing), author a claim statement with it,
    route it, and read the durable claim back. ``source_tier == 1`` is the assertion that carries
    the meaning: tier 1 is "the client stating a fact about itself", so it proves the id the card
    advertised is the same entity the claim store recognised as this project's client.
    """

    if not stage0_db_available:
        pytest.skip("requires a migrated per-branch Postgres database")

    async def scenario() -> None:
        async with _seeded_trial(tmp_path, slug=f"claim-{uuid4().hex[:8]}") as (
            trial,
            conn,
            artifacts,
            _factory,
        ):
            card_ref = await trial._project_card_ref()
            card = Stage0ProjectCard.model_validate_json(await artifacts.read(card_ref))

            shown = card.project.client_entity_id
            assert shown is not None
            assert shown == str(trial.state.client_entity_id)

            await load_client_knowledge_pack(conn)
            user_ref = await artifacts.persist_body(
                workspace_id=trial.state.workspace_id,
                data=_ANSWER.encode(),
                media_type="text/plain",
            )
            captured = await submit_onboarding_input(
                conn,
                workspace_id=trial.state.workspace_id,
                brand_id=trial.state.brand_id,
                product_id=trial.state.product_id,
                project_id=trial.state.project_id,
                client_entity_id=EntityId(UUID(shown)),
                kind=OnboardingInputKind.USER_TURN,
                artifact_key=user_ref.artifact_key,
                content_sha256=user_ref.sha256,
                actor="human",
            )
            result = await route_interview_answer(
                conn,
                workspace_id=trial.state.workspace_id,
                brand_id=trial.state.brand_id,
                product_id=trial.state.product_id,
                project_id=trial.state.project_id,
                client_entity_id=EntityId(UUID(shown)),
                onboarding_input_id=captured.onboarding_input_id,
                artifact_key=user_ref.artifact_key,
                answer=_ANSWER,
                statements=(
                    InterviewStatement(
                        route=InterviewRoute.CLAIM,
                        route_key=CLIENT_PRODUCT,
                        quote=_ANSWER,
                        entity_id=EntityId(UUID(shown)),
                        entity_type=EntityType.ACCOUNT,
                        field_key=CLIENT_PRODUCT,
                        value=_ANSWER,
                    ),
                ),
                actor="agent",
            )

            assert len(result.claim_refs) == 1
            written = await claims_by_ids(
                conn,
                result.claim_refs,
                scope=WorkspaceScope.private_for_workspace(trial.state.workspace_id),
            )
            claim = written[result.claim_refs[0]]
            assert str(claim.entity_id) == shown
            assert claim.source_tier == 1

    run_async(scenario())


def test_an_account_claim_defaults_its_entity_and_an_unknown_one_is_refused(
    tmp_path: Path,
    stage0_db_available: bool,
) -> None:
    """B1 layer 2 (PC-C8 §8, v2.2): the engine owns the claim entity, in both directions.

    Two halves of the same ruling, and they are only meaningful together:

    * **Default.** An ``account`` claim with no ``entity_id`` is no longer a validation error — the
      engine fills in the caller's trusted ``client_entity_id`` and the claim still lands tier 1.
      So the model does not have to carry the id at all, which is the actual fix for B1.
    * **Refusal.** A supplied id that resolves to nothing is refused with
      ``interview_entity_not_found`` and writes nothing. The old behaviour accepted any well-formed
      UUID and expressed its doubt as a *silent* tier-3 downgrade — a durable claim about an entity
      that does not exist. Without this half, the default above would just be a nicer way to reach
      the same hole.
    """

    if not stage0_db_available:
        pytest.skip("requires a migrated per-branch Postgres database")

    async def scenario() -> None:
        async with _seeded_trial(tmp_path, slug=f"default-{uuid4().hex[:8]}") as (
            trial,
            conn,
            artifacts,
            _factory,
        ):
            await load_client_knowledge_pack(conn)
            user_ref = await artifacts.persist_body(
                workspace_id=trial.state.workspace_id,
                data=_ANSWER.encode(),
                media_type="text/plain",
            )
            captured = await submit_onboarding_input(
                conn,
                workspace_id=trial.state.workspace_id,
                brand_id=trial.state.brand_id,
                product_id=trial.state.product_id,
                project_id=trial.state.project_id,
                client_entity_id=EntityId(trial.state.client_entity_id),
                kind=OnboardingInputKind.USER_TURN,
                artifact_key=user_ref.artifact_key,
                content_sha256=user_ref.sha256,
                actor="human",
            )

            async def route(statement: InterviewStatement) -> Any:
                return await route_interview_answer(
                    conn,
                    workspace_id=trial.state.workspace_id,
                    brand_id=trial.state.brand_id,
                    product_id=trial.state.product_id,
                    project_id=trial.state.project_id,
                    client_entity_id=EntityId(trial.state.client_entity_id),
                    onboarding_input_id=captured.onboarding_input_id,
                    artifact_key=user_ref.artifact_key,
                    answer=_ANSWER,
                    statements=(statement,),
                    actor="agent",
                )

            defaulted = await route(
                InterviewStatement(
                    route=InterviewRoute.CLAIM,
                    route_key=CLIENT_PRODUCT,
                    quote=_ANSWER,
                    entity_type=EntityType.ACCOUNT,
                    field_key=CLIENT_PRODUCT,
                    value=_ANSWER,
                )
            )
            written = await claims_by_ids(
                conn,
                defaulted.claim_refs,
                scope=WorkspaceScope.private_for_workspace(trial.state.workspace_id),
            )
            claim = written[defaulted.claim_refs[0]]
            assert str(claim.entity_id) == str(trial.state.client_entity_id)
            assert claim.source_tier == 1

            before = await _claim_count(conn, trial.state.workspace_id)
            with pytest.raises(InterviewClaimEntityRefused) as refused:
                await route(
                    InterviewStatement(
                        route=InterviewRoute.CLAIM,
                        route_key=CLIENT_PRODUCT,
                        quote=_ANSWER,
                        entity_id=EntityId(uuid4()),
                        entity_type=EntityType.ACCOUNT,
                        field_key=CLIENT_PRODUCT,
                        value=_ANSWER,
                    )
                )
            assert refused.value.reason_code == "interview_entity_not_found"
            assert await _claim_count(conn, trial.state.workspace_id) == before

            # A contact claim has no trusted default — there is no "this project's contact".
            with pytest.raises(ValidationError, match="contact claim route requires entity_id"):
                InterviewStatement(
                    route=InterviewRoute.CLAIM,
                    route_key="contact.facet.interest",
                    quote=_ANSWER,
                    entity_type=EntityType.CONTACT,
                    field_key="contact.facet.interest",
                    value=_ANSWER,
                    identity_binding=IdentityBinding.STRONG,
                    use_class=UseClass.PROFESSIONAL_PUBLIC,
                )

    run_async(scenario())


def _claim_statement(entity_id: EntityId | None) -> InterviewStatement:
    return InterviewStatement(
        route=InterviewRoute.CLAIM,
        route_key=CLIENT_PRODUCT,
        quote=_ANSWER,
        entity_id=entity_id,
        entity_type=EntityType.ACCOUNT,
        field_key=CLIENT_PRODUCT,
        value=_ANSWER,
    )


def test_a_merged_away_entity_is_refused_and_its_survivor_is_accepted(
    tmp_path: Path,
    stage0_db_available: bool,
) -> None:
    """A claim may only be keyed to a *canonical* entity (slice-1 closing round, M2).

    ``get_account``/``get_contact`` deliberately do not follow ``merged_into`` — chasing the
    pointer is ``surviving_id``'s job — so an existence check alone happily accepted a row identity
    resolution had already retired. That is the documented M9.4×M2.3 read-side hazard, except worse
    here: the mis-keyed claim is **durable** and outlives the read that made it.

    Refusal rather than silent redirection, deliberately. ``resolve_claim_entity``'s contract is "a
    live entity", and quietly moving a client's own words onto a different entity than the caller
    named is not a repair anyone asked for; the reason code carries the survivor so the caller can
    re-route on purpose. The survivor half is the control — it proves the refusal is about the
    merge, not about the merge's fixture.
    """

    if not stage0_db_available:
        pytest.skip("requires a migrated per-branch Postgres database")

    async def scenario() -> None:
        async with _seeded_trial(tmp_path, slug=f"merged-{uuid4().hex[:8]}") as (
            trial,
            conn,
            artifacts,
            _factory,
        ):
            await load_client_knowledge_pack(conn)
            survivor = await insert_account_entity(
                conn,
                canonical_name="Aura AI (canonical)",
                primary_domain="aura-canonical.invalid",
                workspace_id=trial.state.workspace_id,
                status=AccountStatus.ACTIVE,
            )
            loser = await insert_account_entity(
                conn,
                canonical_name="Aura AI (duplicate)",
                primary_domain="aura-duplicate.invalid",
                workspace_id=trial.state.workspace_id,
                status=AccountStatus.ACTIVE,
            )
            await mark_merged(conn, EntityType.ACCOUNT, loser, survivor)

            user_ref = await artifacts.persist_body(
                workspace_id=trial.state.workspace_id,
                data=_ANSWER.encode(),
                media_type="text/plain",
            )
            captured = await submit_onboarding_input(
                conn,
                workspace_id=trial.state.workspace_id,
                brand_id=trial.state.brand_id,
                product_id=trial.state.product_id,
                project_id=trial.state.project_id,
                client_entity_id=EntityId(trial.state.client_entity_id),
                kind=OnboardingInputKind.USER_TURN,
                artifact_key=user_ref.artifact_key,
                content_sha256=user_ref.sha256,
                actor="human",
            )

            async def route(statement: InterviewStatement) -> Any:
                return await route_interview_answer(
                    conn,
                    workspace_id=trial.state.workspace_id,
                    brand_id=trial.state.brand_id,
                    product_id=trial.state.product_id,
                    project_id=trial.state.project_id,
                    client_entity_id=EntityId(trial.state.client_entity_id),
                    onboarding_input_id=captured.onboarding_input_id,
                    artifact_key=user_ref.artifact_key,
                    answer=_ANSWER,
                    statements=(statement,),
                    actor="agent",
                )

            before = await _claim_count(conn, trial.state.workspace_id)
            with pytest.raises(InterviewClaimEntityRefused) as refused:
                await route(_claim_statement(loser))
            assert refused.value.reason_code == "interview_entity_merged"
            assert str(survivor) in str(refused.value)
            assert await _claim_count(conn, trial.state.workspace_id) == before

            accepted = await route(_claim_statement(survivor))
            written = await claims_by_ids(
                conn,
                accepted.claim_refs,
                scope=WorkspaceScope.private_for_workspace(trial.state.workspace_id),
            )
            claim = written[accepted.claim_refs[0]]
            assert claim.entity_id == survivor
            # Not the client entity, so tier 3 — explicitly, about a *verified* other entity.
            assert claim.source_tier == 3

    run_async(scenario())


def test_a_foreign_workspaces_entity_is_not_found_and_the_tool_says_so_typed(
    tmp_path: Path,
    stage0_db_available: bool,
) -> None:
    """Two gaps the first round left (slice-1 closing round, M3).

    (a) The existence check is workspace-scoped, but every prior fixture refused an id that existed
    *nowhere* — which a check that forgot the workspace clause would also have refused. An entity
    that genuinely exists, in another workspace, is the case that discriminates.

    (b) The typed refusal was only ever asserted at the substrate. The reason the tool re-runs the
    same resolver in ``preconditions`` is so the model reads a reason code instead of a stack
    trace, and nothing proved that path returned one.
    """

    if not stage0_db_available:
        pytest.skip("requires a migrated per-branch Postgres database")

    async def scenario() -> None:
        async with _seeded_trial(tmp_path, slug=f"foreign-{uuid4().hex[:8]}") as (
            trial,
            conn,
            artifacts,
            connection_factory,
        ):
            await load_client_knowledge_pack(conn)
            other_workspace = f"{trial.state.workspace_id}-b"
            await create_workspace(conn, workspace_id=other_workspace, name="C8 foreign workspace")
            foreign = await insert_account_entity(
                conn,
                canonical_name="Somebody Else Ltd",
                primary_domain="somebody-else.invalid",
                workspace_id=other_workspace,
                status=AccountStatus.ACTIVE,
            )

            # (a) The substrate: it exists, just not here.
            with pytest.raises(InterviewClaimEntityRefused) as refused:
                await resolve_claim_entity(
                    conn,
                    classified=_claim_statement(foreign),
                    workspace_id=trial.state.workspace_id,
                    client_entity_id=EntityId(trial.state.client_entity_id),
                )
            assert refused.value.reason_code == "interview_entity_not_found"
            # Control: the same id resolves fine from its own workspace, so the refusal is scope,
            # not a broken fixture.
            assert (
                await resolve_claim_entity(
                    conn,
                    classified=_claim_statement(foreign),
                    workspace_id=other_workspace,
                    client_entity_id=foreign,
                )
                == foreign
            )

            # (b) The model-facing path: a typed reason code, not an exception out of a spend path.
            user_ref = await artifacts.persist_body(
                workspace_id=trial.state.workspace_id,
                data=_ANSWER.encode(),
                media_type="text/plain",
            )
            captured = await submit_onboarding_input(
                conn,
                workspace_id=trial.state.workspace_id,
                brand_id=trial.state.brand_id,
                product_id=trial.state.product_id,
                project_id=trial.state.project_id,
                client_entity_id=EntityId(trial.state.client_entity_id),
                kind=OnboardingInputKind.USER_TURN,
                artifact_key=user_ref.artifact_key,
                content_sha256=user_ref.sha256,
                actor="human",
            )
            # `preconditions` never reaches the gate — it refuses before any spend path — so a
            # bare stand-in is honest here rather than a mock pretending to decide something.
            tool = RecordInterviewAnswerTool(
                conn_factory=connection_factory,
                pre_spend_gate=cast(Any, object()),
            )
            failures = await tool.preconditions(
                RecordInterviewAnswerInput(
                    brand_id=trial.state.brand_id,
                    onboarding_input_id=str(captured.onboarding_input_id),
                    artifact_key=user_ref.artifact_key,
                    answer=_ANSWER,
                    client_entity_id=str(trial.state.client_entity_id),
                    product_id=trial.state.product_id,
                    project_id=trial.state.project_id,
                    statements=[_claim_statement(foreign)],
                ),
                ToolContext(
                    workspace_id=trial.state.workspace_id,
                    actor="agent",
                    conn_factory=connection_factory,
                    operation_id=new_operation_id(),
                ),
            )
            assert [item.reason_code for item in failures] == ["interview_entity_not_found"]
            # And the honest control: the same call with the defaulted client entity passes.
            assert (
                await tool.preconditions(
                    RecordInterviewAnswerInput(
                        brand_id=trial.state.brand_id,
                        onboarding_input_id=str(captured.onboarding_input_id),
                        artifact_key=user_ref.artifact_key,
                        answer=_ANSWER,
                        client_entity_id=str(trial.state.client_entity_id),
                        product_id=trial.state.product_id,
                        project_id=trial.state.project_id,
                        statements=[_claim_statement(None)],
                    ),
                    ToolContext(
                        workspace_id=trial.state.workspace_id,
                        actor="agent",
                        conn_factory=connection_factory,
                        operation_id=new_operation_id(),
                    ),
                )
                == ()
            )

    run_async(scenario())


async def _claim_count(conn: AsyncConnection, workspace_id: str) -> int:
    total = (
        await conn.execute(
            text("SELECT count(*) FROM claim WHERE workspace_id = :workspace"),
            {"workspace": workspace_id},
        )
    ).scalar_one()
    return int(total)


def test_the_account_research_card_still_names_the_project_the_run_belongs_to() -> None:
    """M2: the other surface lost `ProjectLayerSource`'s project row too, so its card carries it.

    "The card subsumes the compiled project row" is only true of a card that describes the
    project. This one describes a *plan for one account*; without the ``project`` block the model
    would be constitution-scoped to a `project_id` with nothing in context naming it.
    """

    project = Project(
        project_id="project-ac",
        workspace_id="ws-ac",
        brand_id="brand-ac",
        product_id="product-ac",
        name="Neurosurgery Q3",
        status="active",
        created_at=datetime(2026, 8, 1, tzinfo=UTC),
        updated_at=datetime(2026, 8, 1, tzinfo=UTC),
    )
    payload = account_research_card_payload(
        workspace_id="ws-ac",
        project=project,
        project_run_id=ProjectRunId(uuid5(NAMESPACE_URL, "c8-m2-project-run")),
        account_run_id=RunId(uuid5(NAMESPACE_URL, "c8-m2-account-run")),
        account_entity_id=EntityId(uuid5(NAMESPACE_URL, "c8-m2-account")),
        account_run_status="running",
        tier="tier_1",
        plan=ResearchPlan(tier="tier_1", aspects=()),
    )

    assert payload["project"] == {
        "project_id": "project-ac",
        "name": "Neurosurgery Q3",
        "status": "active",
        "workspace_id": "ws-ac",
        "brand_id": "brand-ac",
        "product_id": "product-ac",
    }
    # The merged pair is still one card, and it kept both halves of what it replaced.
    assert payload["card_kind"] == "account_research"
    assert payload["tier"] == "tier_1"
    assert isinstance(payload["admission"], dict)
    assert payload["admission"]["account_run_status"] == "running"
    assert "plan" in payload
    # It is JSON, and small: this surface never had the Stage-0 growth problem and must not gain
    # one by merging.
    assert len(json.dumps(payload).encode()) < 4_000


def test_a_constitution_without_a_client_entity_fails_a_tool_that_needs_one() -> None:
    """Fail-closed: an absent trusted value is never fabricated, and never silently omitted.

    ``_trusted_authority`` skips a ``None`` rather than injecting it, so a tool whose input model
    *requires* ``client_entity_id`` (``synthesize_icps``) is refused by its own validator on a
    surface that has no client entity — account research, for one, which builds a constitution
    without one. The value can no longer come from the model, so refusing is the only honest
    outcome; guessing would key claims to the wrong account.

    **What surfaces the refusal today is a bare ``ValidationError``** — the merged arguments are
    validated at ``executor.py:992`` (``descriptor.input_model.model_validate(inputs)``), not
    converted into the typed, model-visible plan-issue feedback that
    ``CapturedTurnUnavailable`` gets (``turn_binding_unavailable``, PC-C8 1.2 review F3). The
    outcome is identical (nothing runs); the *legibility* is not, and whether this deserves the
    same typed treatment is a whole-branch call rather than a 1.3 one. Asserted here so the
    difference is recorded rather than discovered in a live session.
    """

    registry = build_toolbelt(storage=None, gateway=None)
    descriptor = registry.descriptor("synthesize_icps", "1")
    assert "client_entity_id" in MODEL_FORBIDDEN_AUTHORITY_KEYS
    assert descriptor.input_model.model_fields["client_entity_id"].is_required()

    without_client = constitution(client_entity_id=None)
    merged = _trusted_tool_arguments(
        arguments={},
        input_model=descriptor.input_model,
        constitution=without_client,
    )
    # Not fabricated, not defaulted: simply absent.
    assert "client_entity_id" not in merged
    with pytest.raises(ValidationError, match="client_entity_id"):
        descriptor.input_model.model_validate(merged)

    # The same call on a constitution that *has* one is served without the model saying anything.
    served = _trusted_tool_arguments(
        arguments={},
        input_model=descriptor.input_model,
        constitution=constitution(client_entity_id="client-1"),
    )
    assert served["client_entity_id"] == "client-1"


# --- AC-8: byte-identical across a process restart -------------------------------------------

# Deliberately self-contained: it runs in a *fresh interpreter*, so it may not import the test
# module. It seeds a fully deterministic Stage-0 project (fixed scope ids, uuid5 input ids, no
# client entity — the account row's id is DB-generated and would be the one non-reproducible
# input), compiles the card, prints its sha, and rolls everything back.
_DETERMINISM_SCRIPT = textwrap.dedent(
    """
    import asyncio, hashlib, sys
    from contextlib import asynccontextmanager
    from uuid import NAMESPACE_URL, uuid5

    from clue_api.agent_turn_wiring import DurableAgentArtifactStore
    from clue_api.statement_evidence import ArtifactStatementEvidenceReader
    from clue_config import DEFAULT_STAGE0_POLICY
    from clue_core import (
        EntityId, OnboardingInputId, OnboardingInputKind, ReadinessDecisionId, ReadinessGate,
    )
    from clue_db import db_lifespan
    from clue_projections import compile_stage0_project_card
    from clue_research.stage0 import (
        StatementRoute, ensure_readiness_spec, evaluate_readiness, record_statement,
        submit_onboarding_input,
    )
    from clue_spine import Project, create_brand, create_product, create_project, create_workspace
    from clue_storage import FsStorage

    # The workspace id is per-invocation so parallel runners (xdist, two branches on one dev DB)
    # cannot collide on it; the *card's* inputs stay fixed, and workspace_id is a card field, so
    # both processes of one comparison are handed the same suffix by argv.
    ROOT, SUFFIX = sys.argv[1], sys.argv[2]
    WS = f"c8-determinism-ws-{SUFFIX}"
    BRAND, PRODUCT, PROJECT = "brand_det", "product_det", "project_det"
    CLIENT = EntityId(uuid5(NAMESPACE_URL, "c8-determinism-client"))
    ANSWER = (
        "We sell an AI-native ABM platform to neurosurgery practices in the US that run "
        "their own imaging."
    )


    async def main() -> None:
        async with db_lifespan() as engine:
            conn = await engine.connect()
            outer = await conn.begin()

            @asynccontextmanager
            async def factory():
                yield conn

            try:
                await create_workspace(conn, workspace_id=WS, name="C8 determinism")
                brand = await create_brand(conn, workspace_id=WS, name="Aura", brand_id=BRAND)
                product = await create_product(
                    conn, workspace_id=WS, brand_id=brand.brand_id, name="Aura ABM",
                    product_id=PRODUCT,
                )
                await create_project(
                    conn, workspace_id=WS, brand_id=brand.brand_id,
                    product_id=product.product_id, name="Aura", project_id=PROJECT,
                )
                artifacts = DurableAgentArtifactStore(
                    storage=FsStorage(ROOT), conn_factory=factory
                )
                for index in range(6):
                    ref = await artifacts.persist_body(
                        workspace_id=WS,
                        data=f"{ANSWER} (turn {index})".encode(),
                        media_type="text/plain",
                    )
                    captured = await submit_onboarding_input(
                        conn, workspace_id=WS, brand_id=BRAND, product_id=PRODUCT,
                        project_id=PROJECT, kind=OnboardingInputKind.USER_TURN,
                        artifact_key=ref.artifact_key, content_sha256=ref.sha256, actor="human",
                        onboarding_input_id=OnboardingInputId(
                            uuid5(NAMESPACE_URL, f"c8-determinism:input:{index}")
                        ),
                    )
                    await record_statement(
                        conn, onboarding_input_id=captured.onboarding_input_id, workspace_id=WS,
                        brand_id=BRAND, product_id=PRODUCT, project_id=PROJECT,
                        route_kind=StatementRoute.PROJECT_STATE,
                        route_key=f"target_segment_{index}", quote=ANSWER[37:59],
                        quote_start=37, quote_end=59, created_by_actor="agent",
                    )
                    await evaluate_readiness(
                        conn, workspace_id=WS, brand_id=BRAND, product_id=PRODUCT,
                        project_id=PROJECT, client_kb_version=1,
                        gate=ReadinessGate.ICP_SYNTHESIS, spec=DEFAULT_STAGE0_POLICY.readiness,
                        metrics={"coverage_ratio": 0.0, "verified_claims": 0},
                        created_by_actor="system",
                        readiness_decision_id=ReadinessDecisionId(
                            uuid5(NAMESPACE_URL, f"c8-determinism:readiness:{index}")
                        ),
                    )
                spec_version = await ensure_readiness_spec(
                    conn, workspace_id=WS, spec=DEFAULT_STAGE0_POLICY.readiness
                )
                card = await compile_stage0_project_card(
                    project_id=PROJECT, workspace_id=WS, client_entity_id=CLIENT,
                    client_kb_version=1,
                    evidence=ArtifactStatementEvidenceReader(
                        artifacts=artifacts, conn_factory=factory
                    ),
                    product_id=PRODUCT, readiness_spec_version=spec_version, conn_factory=factory,
                )
                print(card.content_sha256())
            finally:
                await outer.rollback()
                await conn.close()


    asyncio.run(main())
    """
)


def test_the_same_durable_state_compiles_the_same_card_in_a_second_process(
    tmp_path: Path,
    stage0_db_available: bool,
) -> None:
    """AC-8's restart half: two interpreters, two hash seeds, one ``content_sha256``.

    A card whose bytes depend on ``PYTHONHASHSEED`` — one set iteration, one unordered dict —
    still looks perfectly deterministic inside a single process, and would silently defeat the
    content-addressed reuse AC-9 depends on: every turn would persist a "new" card.
    """

    if not stage0_db_available:
        pytest.skip("requires a migrated per-branch Postgres database")

    shas: list[str] = []
    suffix = uuid4().hex[:8]
    for index, seed in enumerate(("0", "424242")):
        root = tmp_path / f"run-{index}"
        root.mkdir()
        result = subprocess.run(  # noqa: S603 - fixed argv, this interpreter
            [sys.executable, "-c", _DETERMINISM_SCRIPT, str(root), suffix],
            capture_output=True,
            text=True,
            timeout=180,
            cwd=Path(__file__).resolve().parents[2],
            env={**os.environ, "PYTHONHASHSEED": seed},
        )
        assert result.returncode == 0, result.stderr
        shas.append(result.stdout.strip().splitlines()[-1])

    assert len(shas[0]) == 64
    assert shas[0] == shas[1], (
        f"the same durable state compiled two different cards across processes: {shas}"
    )


def test_the_card_is_content_addressed_so_an_unchanged_project_persists_no_second_artifact(
    tmp_path: Path,
    stage0_db_available: bool,
) -> None:
    """AC-9's mechanism: identical state re-persists the identical key, not a duplicate."""

    if not stage0_db_available:
        pytest.skip("requires a migrated per-branch Postgres database")

    async def scenario() -> None:
        async with _seeded_trial(tmp_path, slug=f"addr-{uuid4().hex[:8]}") as (
            trial,
            conn,
            _artifacts,
            _factory,
        ):
            first = await trial._project_card_ref()
            second = await trial._project_card_ref()
            assert first == second
            rows = (
                await conn.execute(
                    text("SELECT count(*) FROM artifact WHERE storage_key = :key"),
                    {"key": first.artifact_key},
                )
            ).scalar_one()
            assert rows == 1
            assert first.artifact_key.endswith(f"/{first.sha256}")

    run_async(scenario())


def test_the_report_snapshot_stopped_naming_the_current_turn() -> None:
    """Turn identity has one owner (L7): the human inspection surface no longer names it too.

    A no-DB shape check on the production signature. ``snapshot()`` used to take a
    ``current_turn`` block and echo it as ``current_turn_input``, which is how the model came to
    read an id out of L3 and hand it back as if it had chosen it.
    """

    signature = inspect.signature(Stage0Trial.snapshot)
    assert list(signature.parameters) == ["self"]
    source = inspect.getsource(Stage0Trial.snapshot)
    assert "current_turn_input" not in source
