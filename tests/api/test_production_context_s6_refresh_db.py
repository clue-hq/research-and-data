"""S6-A production publication and next-turn refresh acceptance."""

from __future__ import annotations

from pathlib import Path
from typing import Any, cast
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text

from clue_api.agent_turn_fleet_wiring import _ProjectScope
from clue_api.agent_turn_scope_pin import (
    get_agent_turn_scope_pin,
    load_or_create_agent_turn_scope_pin,
)
from clue_api.agent_turn_wiring import DurableAgentArtifactStore
from clue_core import EntityType, OnboardingInputKind, RunId
from clue_research.stage0 import (
    InterviewRoute,
    InterviewStatement,
    current_kb_version,
    read_client_kb_claims,
    route_interview_answer,
    submit_onboarding_input,
)
from clue_research.stage0.fields import CLIENT_PRODUCT_OVERVIEW, CLIENT_VALUE_PROP
from clue_storage import FsStorage
from tests.api.test_production_context_s3_db import (
    _pinned_documents,
    _runner,
    _seed_post_recon,
)
from tests.api.test_production_context_s31_scope_pin_db import _capture_submission
from tests.db.conftest import run_async
from tests.profiling.conftest import conn_session_factory, rollback_conn

pytestmark = pytest.mark.usefixtures("require_profiling_db")


class _CrashOnceCardArtifacts:
    def __init__(
        self,
        delegate: DurableAgentArtifactStore,
        *,
        crash_after_persist: bool,
    ) -> None:
        self._delegate = delegate
        self._crash_after_persist = crash_after_persist
        self._crashed = False

    async def persist_body(self, **kwargs: Any):
        if not self._crashed and not self._crash_after_persist:
            self._crashed = True
            raise RuntimeError("crash-before-card-persistence")
        ref = await self._delegate.persist_body(**kwargs)
        if not self._crashed:
            self._crashed = True
            raise RuntimeError("crash-after-card-persistence")
        return ref

    async def read(self, ref: Any) -> bytes:
        return await self._delegate.read(ref)


def test_interview_claims_publish_scope_correct_versions_for_only_the_next_turn(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            seeded = await _seed_post_recon(conn, suffix=uuid4().hex[:8])
            factory = conn_session_factory(conn)
            artifacts = DurableAgentArtifactStore(
                storage=FsStorage(tmp_path / "s6-refresh"),
                conn_factory=factory,
            )
            original = await _capture_submission(
                conn,
                artifacts=artifacts,
                workspace_id=seeded.workspace_id,
                project_id=seeded.project_a.project_id,
                brand_id=seeded.brand.brand_id,
                product_id=seeded.product.product_id,
                client_entity_id=seeded.client_entity_id,
                label="original",
            )
            pin_v1, created = await load_or_create_agent_turn_scope_pin(conn, submission=original)
            assert created is True
            assert pin_v1.client_kb_version == seeded.client_kb_version
            assert pin_v1.product_kb_version == seeded.product_kb_version

            body = (
                "Company promise is faster activation. "
                "Product focus is autonomous call routing. "
                "Project goal is a healthcare launch."
            )
            body_ref = await artifacts.persist_body(
                workspace_id=seeded.workspace_id,
                data=body.encode(),
                media_type="text/plain",
                subject_bindings=((UUID(str(seeded.client_entity_id)), "context"),),
                project_bindings=((seeded.project_a.project_id, "project_conversation_context"),),
            )
            captured = await submit_onboarding_input(
                conn,
                workspace_id=seeded.workspace_id,
                brand_id=seeded.brand.brand_id,
                product_id=seeded.product.product_id,
                project_id=seeded.project_a.project_id,
                client_entity_id=seeded.client_entity_id,
                kind=OnboardingInputKind.USER_TURN,
                artifact_key=body_ref.artifact_key,
                content_sha256=body_ref.sha256,
                actor="human",
            )
            statements = (
                InterviewStatement(
                    route=InterviewRoute.CLAIM,
                    route_key=CLIENT_VALUE_PROP,
                    quote="faster activation",
                    entity_type=EntityType.ACCOUNT,
                    field_key=CLIENT_VALUE_PROP,
                    value="faster activation",
                ),
                InterviewStatement(
                    route=InterviewRoute.CLAIM,
                    route_key=CLIENT_PRODUCT_OVERVIEW,
                    quote="autonomous call routing",
                    entity_type=EntityType.ACCOUNT,
                    field_key=CLIENT_PRODUCT_OVERVIEW,
                    value="autonomous call routing",
                ),
                InterviewStatement(
                    route=InterviewRoute.PROJECT_STATE,
                    route_key="project.goal",
                    quote="healthcare launch",
                ),
            )
            operation_run = RunId(uuid4())

            before_counts = (
                await conn.execute(
                    text(
                        "SELECT (SELECT count(*) FROM claim WHERE workspace_id=:workspace), "
                        "(SELECT count(*) FROM volunteered_statement WHERE workspace_id=:workspace)"
                    ),
                    {"workspace": seeded.workspace_id},
                )
            ).one()
            published = await route_interview_answer(
                conn,
                workspace_id=seeded.workspace_id,
                brand_id=seeded.brand.brand_id,
                product_id=seeded.product.product_id,
                project_id=seeded.project_a.project_id,
                client_entity_id=seeded.client_entity_id,
                onboarding_input_id=captured.onboarding_input_id,
                artifact_key=body_ref.artifact_key,
                answer=body,
                statements=statements,
                actor="agent",
                run_id=operation_run,
            )
            assert published.client_kb_version == seeded.client_kb_version + 1
            assert published.product_kb_version == seeded.product_kb_version + 1
            assert len(published.claim_refs) == 2
            assert len(published.project_state_refs) == 1
            assert (
                await current_kb_version(
                    conn,
                    seeded.client_entity_id,
                    workspace_id=seeded.workspace_id,
                )
                == published.client_kb_version
            )
            assert (
                await current_kb_version(
                    conn,
                    seeded.client_entity_id,
                    workspace_id=seeded.workspace_id,
                    product_id=seeded.product.product_id,
                )
                == published.product_kb_version
            )

            old_company = await read_client_kb_claims(
                conn,
                seeded.client_entity_id,
                workspace_id=seeded.workspace_id,
                version=seeded.client_kb_version,
            )
            new_company = await read_client_kb_claims(
                conn,
                seeded.client_entity_id,
                workspace_id=seeded.workspace_id,
                version=published.client_kb_version,
            )
            new_product = await read_client_kb_claims(
                conn,
                seeded.client_entity_id,
                workspace_id=seeded.workspace_id,
                version=published.product_kb_version,
                product_id=seeded.product.product_id,
            )
            assert old_company[CLIENT_VALUE_PROP].value_json != "faster activation"
            assert new_company[CLIENT_VALUE_PROP].value_json == "faster activation"
            assert CLIENT_PRODUCT_OVERVIEW not in new_company
            assert new_product[CLIENT_PRODUCT_OVERVIEW].value_json == "autonomous call routing"
            assert CLIENT_VALUE_PROP not in new_product

            # The current turn cannot drift after publication. A later turn observes the new pair.
            assert (
                await get_agent_turn_scope_pin(
                    conn,
                    workspace_id=seeded.workspace_id,
                    turn_id=original.turn_id,
                )
                == pin_v1
            )
            next_a = await _capture_submission(
                conn,
                artifacts=artifacts,
                workspace_id=seeded.workspace_id,
                project_id=seeded.project_a.project_id,
                brand_id=seeded.brand.brand_id,
                product_id=seeded.product.product_id,
                client_entity_id=seeded.client_entity_id,
                label="next-a",
            )
            pin_next_a, _ = await load_or_create_agent_turn_scope_pin(conn, submission=next_a)
            assert pin_next_a.client_kb_version == published.client_kb_version
            assert pin_next_a.product_kb_version == published.product_kb_version
            next_b = await _capture_submission(
                conn,
                artifacts=artifacts,
                workspace_id=seeded.workspace_id,
                project_id=seeded.project_b.project_id,
                brand_id=seeded.brand.brand_id,
                product_id=None,
                client_entity_id=seeded.client_entity_id,
                label="next-b",
            )
            pin_next_b, _ = await load_or_create_agent_turn_scope_pin(conn, submission=next_b)
            assert pin_next_b.client_kb_version == published.client_kb_version
            assert pin_next_b.product_kb_version is None

            # The project statement belongs to Project A alone. Asserted at its durable source:
            # since ARV2 onboarding O6 (ruling D5) the production conversation no longer compiles
            # a Stage-0 project-state card, so the isolation is read from the statement rows the
            # compiler itself reads (the card's own per-project isolation is owned by
            # ``tests/projections/test_production_context_db.py``).
            statement_projects = set(
                (
                    await conn.execute(
                        text(
                            "SELECT project_id FROM volunteered_statement "
                            "WHERE workspace_id=:workspace AND route_kind='project_state' "
                            "AND route_key='project.goal'"
                        ),
                        {"workspace": seeded.workspace_id},
                    )
                ).scalars()
            )
            assert statement_projects == {seeded.project_a.project_id}

            replayed = await route_interview_answer(
                conn,
                workspace_id=seeded.workspace_id,
                brand_id=seeded.brand.brand_id,
                product_id=seeded.product.product_id,
                project_id=seeded.project_a.project_id,
                client_entity_id=seeded.client_entity_id,
                onboarding_input_id=captured.onboarding_input_id,
                artifact_key=body_ref.artifact_key,
                answer=body,
                statements=statements,
                actor="agent",
                run_id=operation_run,
            )
            assert replayed == published
            after_counts = (
                await conn.execute(
                    text(
                        "SELECT (SELECT count(*) FROM claim WHERE workspace_id=:workspace), "
                        "(SELECT count(*) FROM volunteered_statement WHERE workspace_id=:workspace)"
                    ),
                    {"workspace": seeded.workspace_id},
                )
            ).one()
            assert after_counts[0] == before_counts[0] + 4  # two markers plus two exact claims
            assert after_counts[1] == before_counts[1] + 3

    run_async(scenario())


def test_project_state_only_interview_does_not_publish_either_kb_sequence(tmp_path: Path) -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            seeded = await _seed_post_recon(conn, suffix=uuid4().hex[:8])
            artifacts = DurableAgentArtifactStore(
                storage=FsStorage(tmp_path / "s6-project-only"),
                conn_factory=conn_session_factory(conn),
            )
            body = "This project's goal is a hospital launch."
            ref = await artifacts.persist_body(
                workspace_id=seeded.workspace_id,
                data=body.encode(),
                media_type="text/plain",
            )
            captured = await submit_onboarding_input(
                conn,
                workspace_id=seeded.workspace_id,
                brand_id=seeded.brand.brand_id,
                product_id=seeded.product.product_id,
                project_id=seeded.project_a.project_id,
                client_entity_id=seeded.client_entity_id,
                kind=OnboardingInputKind.USER_TURN,
                artifact_key=ref.artifact_key,
                content_sha256=ref.sha256,
                actor="human",
            )
            result = await route_interview_answer(
                conn,
                workspace_id=seeded.workspace_id,
                brand_id=seeded.brand.brand_id,
                product_id=seeded.product.product_id,
                project_id=seeded.project_a.project_id,
                client_entity_id=seeded.client_entity_id,
                onboarding_input_id=captured.onboarding_input_id,
                artifact_key=ref.artifact_key,
                answer=body,
                statements=(
                    InterviewStatement(
                        route=InterviewRoute.PROJECT_STATE,
                        route_key="project.goal",
                        quote="hospital launch",
                    ),
                ),
                actor="agent",
            )
            assert result.client_kb_version is None
            assert result.product_kb_version is None
            assert (
                await current_kb_version(
                    conn,
                    seeded.client_entity_id,
                    workspace_id=seeded.workspace_id,
                )
                == seeded.client_kb_version
            )
            assert (
                await current_kb_version(
                    conn,
                    seeded.client_entity_id,
                    workspace_id=seeded.workspace_id,
                    product_id=seeded.product.product_id,
                )
                == seeded.product_kb_version
            )

    run_async(scenario())


def test_product_fact_without_human_selected_product_is_refused_without_publication(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            seeded = await _seed_post_recon(conn, suffix=uuid4().hex[:8])
            artifacts = DurableAgentArtifactStore(
                storage=FsStorage(tmp_path / "s6-product-refusal"),
                conn_factory=conn_session_factory(conn),
            )
            body = "Our product autonomously routes patient calls."
            ref = await artifacts.persist_body(
                workspace_id=seeded.workspace_id,
                data=body.encode(),
                media_type="text/plain",
            )
            captured = await submit_onboarding_input(
                conn,
                workspace_id=seeded.workspace_id,
                brand_id=seeded.brand.brand_id,
                product_id=None,
                project_id=seeded.project_b.project_id,
                client_entity_id=seeded.client_entity_id,
                kind=OnboardingInputKind.USER_TURN,
                artifact_key=ref.artifact_key,
                content_sha256=ref.sha256,
                actor="human",
            )
            before_claims = int(
                (
                    await conn.execute(
                        text("SELECT count(*) FROM claim WHERE workspace_id=:workspace"),
                        {"workspace": seeded.workspace_id},
                    )
                ).scalar_one()
            )
            with pytest.raises(ValueError, match="human-confirmed project product"):
                async with conn.begin_nested():
                    await route_interview_answer(
                        conn,
                        workspace_id=seeded.workspace_id,
                        brand_id=seeded.brand.brand_id,
                        product_id=None,
                        project_id=seeded.project_b.project_id,
                        client_entity_id=seeded.client_entity_id,
                        onboarding_input_id=captured.onboarding_input_id,
                        artifact_key=ref.artifact_key,
                        answer=body,
                        statements=(
                            InterviewStatement(
                                route=InterviewRoute.CLAIM,
                                route_key=CLIENT_PRODUCT_OVERVIEW,
                                quote="autonomously routes patient calls",
                                entity_type=EntityType.ACCOUNT,
                                field_key=CLIENT_PRODUCT_OVERVIEW,
                                value="autonomously routes patient calls",
                            ),
                        ),
                        actor="agent",
                    )
            after_claims = int(
                (
                    await conn.execute(
                        text("SELECT count(*) FROM claim WHERE workspace_id=:workspace"),
                        {"workspace": seeded.workspace_id},
                    )
                ).scalar_one()
            )
            assert after_claims == before_claims

    run_async(scenario())


@pytest.mark.parametrize(
    ("crash_after_persist", "persisted_before_retry", "error"),
    [
        (False, 0, "crash-before-card-persistence"),
        (True, 1, "crash-after-card-persistence"),
    ],
)
def test_card_compilation_retries_converge_across_persistence_crash_boundaries(
    tmp_path: Path,
    crash_after_persist: bool,
    persisted_before_retry: int,
    error: str,
) -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            seeded = await _seed_post_recon(conn, suffix=uuid4().hex[:8])
            factory = conn_session_factory(conn)
            durable = DurableAgentArtifactStore(
                storage=FsStorage(tmp_path / f"s6-card-crash-{crash_after_persist}"),
                conn_factory=factory,
            )
            crashing = _CrashOnceCardArtifacts(
                durable,
                crash_after_persist=crash_after_persist,
            )
            runner = _runner(
                artifacts=cast(DurableAgentArtifactStore, crashing),
                conn_factory=factory,
            )
            submission = await _capture_submission(
                conn,
                artifacts=durable,
                workspace_id=seeded.workspace_id,
                project_id=seeded.project_a.project_id,
                brand_id=seeded.brand.brand_id,
                product_id=seeded.product.product_id,
                client_entity_id=seeded.client_entity_id,
                label=f"card-crash-{crash_after_persist}",
            )
            pin, _ = await load_or_create_agent_turn_scope_pin(conn, submission=submission)
            scope = _ProjectScope.from_pin(pin)
            baseline = int(
                (
                    await conn.execute(
                        text("SELECT count(*) FROM artifact WHERE workspace_id=:workspace"),
                        {"workspace": seeded.workspace_id},
                    )
                ).scalar_one()
            )

            documents = _pinned_documents(project_id=seeded.project_a.project_id)

            with pytest.raises(RuntimeError, match=error):
                await runner._compose_project_context(
                    submission=submission,
                    scope=scope,
                    documents=documents,
                )
            after_crash = int(
                (
                    await conn.execute(
                        text("SELECT count(*) FROM artifact WHERE workspace_id=:workspace"),
                        {"workspace": seeded.workspace_id},
                    )
                ).scalar_one()
            )
            assert after_crash == baseline + persisted_before_retry

            first = await runner._compose_project_context(
                submission=submission,
                scope=scope,
                documents=documents,
            )
            second = await runner._compose_project_context(
                submission=submission,
                scope=scope,
                documents=documents,
            )
            assert first == second
            assert {item.name for item in first.artifacts} == {"brand_knowledge_index"}
            completed = int(
                (
                    await conn.execute(
                        text("SELECT count(*) FROM artifact WHERE workspace_id=:workspace"),
                        {"workspace": seeded.workspace_id},
                    )
                ).scalar_one()
            )
            # The card is content-addressed, so the crashed attempt's copy (if any) and the two
            # convergent retries are one durable row.
            assert completed == baseline + 1

    run_async(scenario())
