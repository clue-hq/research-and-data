from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_agents import ArtifactRef, ContextLayer
from clue_api.agent_turn_wiring import DurableAgentArtifactStore
from clue_api.stage0_trial import (
    STAGE0_CONTEXT_BINDING_KIND,
    STAGE0_USER_MESSAGE_BINDING_KIND,
    Stage0Trial,
    Stage0TrialPaths,
    Stage0TrialState,
    stage0_trial_context_policy,
    stage0_trial_recipe_definitions,
    stage0_trial_settings,
)
from clue_config import Settings
from clue_core import OnboardingInputKind
from clue_db import db_lifespan
from clue_spine import create_workspace
from clue_storage import FsStorage
from tests.db.conftest import _db_available, run_async


class _StopAfterUserMessage(Exception):
    pass


class _CapturingArtifacts:
    def __init__(self) -> None:
        self.bindings: list[tuple[tuple[object, str], ...]] = []

    async def persist_body(
        self,
        *,
        workspace_id: str,
        data: bytes,
        media_type: str,
        subject_bindings: tuple[tuple[object, str], ...] = (),
    ) -> ArtifactRef:
        self.bindings.append(subject_bindings)
        digest = f"{len(self.bindings):064x}"
        return ArtifactRef(
            workspace_id=workspace_id,
            artifact_key=f"{workspace_id}/{digest}",
            sha256=digest,
            media_type=media_type,
            byte_count=len(data),
        )


@pytest.fixture
def stage0_db_available() -> bool:
    return _db_available()


def _state(slug: str = "quality-trial") -> Stage0TrialState:
    session_id = uuid4()
    return Stage0TrialState(
        session_id=session_id,
        session_slug=slug,
        workspace_id=f"s0-{slug}-12345678",
        brand_id="brand_trial",
        product_id="product_trial",
        project_id="project_trial",
        client_entity_id=uuid4(),
        client_kb_version=1,
        company_name="Example Company",
        website="https://example.invalid",
        product_name="Example Product",
        project_name="Example Stage 0 trial",
        thread_id=f"stage0-trial-{session_id.hex}",
        created_at=datetime.now(UTC),
    )


def test_stage0_turn_and_context_use_frozen_subject_binding_kinds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    artifacts = _CapturingArtifacts()
    trial = object.__new__(Stage0Trial)
    trial.state = _state()
    trial._components = SimpleNamespace(artifacts=artifacts)  # type: ignore[assignment]

    @asynccontextmanager
    async def connection_factory() -> AsyncIterator[object]:
        yield object()

    trial._conn_factory = connection_factory  # type: ignore[assignment]
    onboarding_call: dict[str, object] = {}

    async def capture_onboarding(*args: object, **kwargs: object) -> object:
        del args
        onboarding_call.update(kwargs)
        return SimpleNamespace(onboarding_input_id=uuid4())

    monkeypatch.setattr("clue_api.stage0_trial.submit_onboarding_input", capture_onboarding)

    async def stop_after_user_message(
        self: Stage0Trial,
        *,
        current_turn: dict[str, object] | None = None,
    ) -> dict[str, object]:
        del self, current_turn
        raise _StopAfterUserMessage

    monkeypatch.setattr(Stage0Trial, "snapshot", stop_after_user_message)

    with pytest.raises(_StopAfterUserMessage):
        run_async(trial.run_turn("We want to target neurosurgery practices."))

    assert artifacts.bindings == [
        ((trial.state.client_entity_id, STAGE0_USER_MESSAGE_BINDING_KIND),)
    ]
    assert STAGE0_USER_MESSAGE_BINDING_KIND == "conversation"
    assert onboarding_call["actor"] == "human"
    assert onboarding_call["kind"] is OnboardingInputKind.USER_TURN
    assert str(onboarding_call["artifact_key"]).endswith(f"/{1:064x}")
    assert onboarding_call["content_sha256"] == f"{1:064x}"

    artifacts.bindings.clear()
    run_async(trial._artifact("application/json", {"stage": "stage0"}))
    assert artifacts.bindings == [
        ((trial.state.client_entity_id, STAGE0_CONTEXT_BINDING_KIND),)
    ]
    assert STAGE0_CONTEXT_BINDING_KIND == "context"


def test_stage0_subject_bindings_are_accepted_by_the_real_database(
    tmp_path: Path,
    stage0_db_available: bool,
) -> None:
    if not stage0_db_available:
        pytest.skip("requires a migrated per-branch Postgres database")

    async def scenario() -> None:
        state = _state(f"binding-{uuid4().hex[:8]}")
        async with db_lifespan() as engine:
            conn = await engine.connect()
            outer = await conn.begin()

            @asynccontextmanager
            async def connection_factory() -> AsyncIterator[AsyncConnection]:
                yield conn

            try:
                await create_workspace(
                    conn,
                    workspace_id=state.workspace_id,
                    name="Stage 0 binding regression",
                )
                artifacts = DurableAgentArtifactStore(
                    storage=FsStorage(tmp_path / "artifacts"),
                    conn_factory=connection_factory,
                )
                await artifacts.persist_body(
                    workspace_id=state.workspace_id,
                    data=b"user message",
                    media_type="text/plain",
                    subject_bindings=(
                        (state.client_entity_id, STAGE0_USER_MESSAGE_BINDING_KIND),
                    ),
                )
                await artifacts.persist_body(
                    workspace_id=state.workspace_id,
                    data=b'{"stage":"stage0"}',
                    media_type="application/json",
                    subject_bindings=((state.client_entity_id, STAGE0_CONTEXT_BINDING_KIND),),
                )
                result = await conn.execute(
                    text(
                        "SELECT binding_kind FROM agent_artifact_subject "
                        "WHERE workspace_id = :workspace ORDER BY binding_kind"
                    ),
                    {"workspace": state.workspace_id},
                )
                assert tuple(result.scalars()) == ("context", "conversation")
            finally:
                await outer.rollback()
                await conn.close()

    run_async(scenario())


def test_trial_state_round_trips_through_private_report_handle(tmp_path: Path) -> None:
    paths = Stage0TrialPaths.for_session(tmp_path, "quality-trial")
    expected = _state()

    paths.save_state(expected)

    assert paths.load_state() == expected
    assert paths.state.parent == tmp_path / "quality-trial"
    assert not (paths.state.parent / ".session.json.tmp").exists()


@pytest.mark.parametrize("slug", ("../escape", "Uppercase", "spaces are unsafe", ""))
def test_trial_paths_reject_unsafe_session_slugs(tmp_path: Path, slug: str) -> None:
    with pytest.raises(ValueError, match="invalid Stage-0 trial session slug"):
        Stage0TrialPaths.for_session(tmp_path, slug)


def test_stage0_trial_context_budgets_every_layer_and_keeps_history_room() -> None:
    policy = stage0_trial_context_policy()

    assert tuple(item.layer for item in policy.budgets) == tuple(ContextLayer)
    assert policy.budget_for(ContextLayer.L4_MEMORY) > 0
    assert policy.budget_for(ContextLayer.L6_CONVERSATION) > policy.budget_for(ContextLayer.L7_TURN)


def test_trial_seeds_only_recipe0_with_required_active_version() -> None:
    definitions = stage0_trial_recipe_definitions()

    assert {definition.recipe_key for definition in definitions} == {"recipe0-stage0"}
    assert 3 in {definition.version for definition in definitions}


@pytest.mark.parametrize("configured", (None, "", "   "))
def test_trial_derives_canonical_absolute_workspace_root_when_unset(configured: str | None) -> None:
    resolved = stage0_trial_settings(Settings(_env_file=None, agent_workspace_root=configured))
    root = Path(resolved.agent_workspace_root or "")

    assert root.is_absolute()
    assert root.parent == root.parent.resolve()
    assert root.name.startswith("clue-stage0-agent-")
