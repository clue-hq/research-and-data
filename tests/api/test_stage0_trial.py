import json
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
    Stage0ProductNotConfirmed,
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
from clue_research.stage0 import (
    NO_CLIENT_KB_CLAIMS,
    NO_PROJECT_STATEMENTS,
    ICPProposal,
    ICPSynthesisResult,
    ICPSynthesisStatus,
)
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
    assert artifacts.bindings == [((trial.state.client_entity_id, STAGE0_CONTEXT_BINDING_KIND),)]
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
                    subject_bindings=((state.client_entity_id, STAGE0_USER_MESSAGE_BINDING_KIND),),
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


class _Project:
    def __init__(self, product_id: str | None) -> None:
        self.product_id = product_id
        self.workspace_id = "irrelevant"


def _gated_trial(tmp_path: Path) -> Stage0Trial:
    """A trial whose only live seams are the connection factory and the injected synthesis fakes."""
    trial = object.__new__(Stage0Trial)
    trial.state = _state()
    trial.paths = Stage0TrialPaths.for_session(tmp_path, trial.state.session_slug)

    @asynccontextmanager
    async def connection_factory() -> AsyncIterator[object]:
        yield object()

    trial._conn_factory = connection_factory  # type: ignore[assignment]
    trial._gateway = SimpleNamespace()
    trial._settings = Settings(_env_file=None)
    return trial


def test_synthesis_is_refused_until_the_human_confirms_the_product(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The trial defect: /synthesize-icp ran with project.product_id null while /confirm-icp
    correctly refused. Both gates must be the same gate."""
    trial = _gated_trial(tmp_path)

    async def unconfirmed_project(conn: object, project_id: str) -> _Project:
        del conn, project_id
        return _Project(product_id=None)

    def refuse_synthesis(*args: object, **kwargs: object) -> None:
        raise AssertionError("synthesis must not run before the product is confirmed")

    monkeypatch.setattr("clue_api.stage0_trial.get_project", unconfirmed_project)
    monkeypatch.setattr("clue_api.stage0_trial.synthesize_icps", refuse_synthesis)

    with pytest.raises(Stage0ProductNotConfirmed, match="run /confirm-product first"):
        run_async(trial.synthesize_icp_proposals())

    # ...and the same refusal still guards confirmation (parity with the pre-existing gate)
    trial.paths.root.mkdir(parents=True, exist_ok=True)
    trial.paths.icp_proposals.write_text(
        json.dumps(
            {
                "workspace_id": trial.state.workspace_id,
                "client_entity_id": str(trial.state.client_entity_id),
                "client_kb_version": trial.state.client_kb_version,
                "product_id": trial.state.product_id,
                "proposals": [{"icp_key": "primary"}],
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(Stage0ProductNotConfirmed, match="run /confirm-product first"):
        run_async(trial.confirm_icp_proposal(1))


def test_not_ready_synthesis_offers_no_confirmable_proposal(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    trial = _gated_trial(tmp_path)
    floor = ICPProposal(icp_key="primary", label="Ungrounded baseline (no evidence)")

    async def confirmed_project(conn: object, project_id: str) -> _Project:
        del conn, project_id
        return _Project(product_id=trial.state.product_id)

    async def no_statements(self: Stage0Trial, conn: object) -> tuple[object, ...]:
        del self, conn
        return ()

    async def not_ready(*args: object, **kwargs: object) -> ICPSynthesisResult:
        del args, kwargs
        return ICPSynthesisResult(
            proposals=(floor,),
            status=ICPSynthesisStatus.FLOOR_ONLY,
            reason_codes=(NO_CLIENT_KB_CLAIMS, NO_PROJECT_STATEMENTS),
        )

    async def no_report(self: Stage0Trial) -> None:
        del self

    monkeypatch.setattr("clue_api.stage0_trial.get_project", confirmed_project)
    monkeypatch.setattr("clue_api.stage0_trial.synthesize_icps", not_ready)
    monkeypatch.setattr(Stage0Trial, "_project_statements", no_statements)
    monkeypatch.setattr(Stage0Trial, "export_report", no_report)

    result = run_async(trial.synthesize_icp_proposals())

    assert result.status is ICPSynthesisStatus.FLOOR_ONLY
    assert result.reason_codes == (NO_CLIENT_KB_CLAIMS, NO_PROJECT_STATEMENTS)
    payload = json.loads(trial.paths.icp_proposals.read_text(encoding="utf-8"))
    # the floor is recorded for inspection but is NOT a numbered, confirmable proposal
    assert payload["status"] == "floor_only"
    assert payload["proposals"] == []
    assert payload["not_ready_floor"][0]["icp_key"] == "primary"
    assert trial._load_icp_proposals() == ()
    with pytest.raises(ValueError, match="no grounded ICP proposal is available"):
        run_async(trial.confirm_icp_proposal(1))


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
