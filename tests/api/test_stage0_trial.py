import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast
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
    _ResolvedStatements,
    stage0_trial_context_policy,
    stage0_trial_recipe_definitions,
    stage0_trial_settings,
)
from clue_config import Settings
from clue_core import AccountStatus, OnboardingInputKind
from clue_db import db_lifespan
from clue_research.identity import insert_account_entity
from clue_research.stage0 import (
    NO_CLIENT_KB_CLAIMS,
    NO_PROJECT_STATEMENTS,
    ICPProposal,
    ICPSynthesisResult,
    ICPSynthesisStatus,
    StatementRoute,
    read_statements,
    record_statement,
    submit_onboarding_input,
)
from clue_spine import create_brand, create_product, create_project, create_workspace
from clue_storage import FsStorage, mark_erased
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

    # Lane D D2 moved the capture path itself to `clue_api.conversation_capture.persist_user_turn`
    # (one owner for the trial and the production turn route), so the seam this patches moved with
    # it. What the test asserts is unchanged, and that is the point: the trial still binds the same
    # two subject kinds and still captures `actor='human'` before the model is woken.
    monkeypatch.setattr(
        "clue_api.conversation_capture.submit_onboarding_input", capture_onboarding
    )

    # The turn's first act after capturing the user message is compiling the L3 project card
    # (PC-C8 §10 replaced the stage/readiness snapshot pair with it), so that is where this test
    # stops: everything it asserts about the *capture* has already happened.
    async def stop_after_user_message(self: Stage0Trial) -> ArtifactRef:
        del self
        raise _StopAfterUserMessage

    monkeypatch.setattr(Stage0Trial, "_project_card_ref", stop_after_user_message)
    monkeypatch.setattr(trial, "_components", SimpleNamespace(artifacts=artifacts))
    # PC-C8 §8: the trial runs its Head-of-ABM profile on a named capability surface. Since D2 that
    # resolution happens once, when the shared conversation engine is built, so the turn reads the
    # already-resolved profile off the engine instead of resolving one per turn.
    trial._engine = SimpleNamespace(resolved=None)  # type: ignore[assignment]

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

    async def no_statements(self: Stage0Trial, conn: object) -> _ResolvedStatements:
        del self, conn
        return _ResolvedStatements(statements=(), excluded_statement_ids=())

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

    outcome = run_async(trial.synthesize_icp_proposals())

    assert outcome.status is ICPSynthesisStatus.FLOOR_ONLY
    assert outcome.reason_codes == (NO_CLIENT_KB_CLAIMS, NO_PROJECT_STATEMENTS)
    assert outcome.proposals == ()  # the offerable set is empty, not the ungrounded floor
    payload = json.loads(trial.paths.icp_proposals.read_text(encoding="utf-8"))
    # the floor is recorded for inspection but is NOT a numbered, confirmable proposal
    assert payload["status"] == "floor_only"
    assert payload["proposals"] == []
    assert payload["not_ready_floor"][0]["icp_key"] == "primary"
    assert trial._load_icp_proposals() == ()
    with pytest.raises(ValueError, match="no grounded ICP proposal is available"):
        run_async(trial.confirm_icp_proposal(1))


_ANSWER = "We target neurosurgery practices in the US that run their own imaging."


async def _statement_fixture(
    conn: AsyncConnection,
    artifacts: DurableAgentArtifactStore,
    *,
    state: Stage0TrialState,
    quote_start: int,
    quote_end: int,
    recorded_quote: str,
) -> None:
    """Seed one durable ``project_state`` statement over a really-persisted evidence artifact.

    ``recorded_quote`` is what the row hashes; passing something other than
    ``_ANSWER[quote_start:quote_end]`` reproduces a corrupted/tampered lineage.
    """
    await create_workspace(conn, workspace_id=state.workspace_id, name="Statement resolution")
    brand = await create_brand(
        conn, workspace_id=state.workspace_id, name="B", brand_id=state.brand_id
    )
    product = await create_product(
        conn,
        workspace_id=state.workspace_id,
        brand_id=brand.brand_id,
        name="P",
        product_id=state.product_id,
    )
    await create_project(
        conn,
        workspace_id=state.workspace_id,
        brand_id=brand.brand_id,
        product_id=product.product_id,
        name="Proj",
        project_id=state.project_id,
    )
    client = await insert_account_entity(
        conn,
        canonical_name="Statement Client",
        primary_domain="statements.example",
        workspace_id=state.workspace_id,
        status=AccountStatus.ACTIVE,
    )
    ref = await artifacts.persist_body(
        workspace_id=state.workspace_id,
        data=_ANSWER.encode(),
        media_type="text/plain",
    )
    captured = await submit_onboarding_input(
        conn,
        workspace_id=state.workspace_id,
        brand_id=brand.brand_id,
        product_id=product.product_id,
        project_id=state.project_id,
        client_entity_id=client,
        kind=OnboardingInputKind.USER_TURN,
        artifact_key=ref.artifact_key,
        content_sha256=ref.sha256,
        actor="human",
    )
    await record_statement(
        conn,
        onboarding_input_id=captured.onboarding_input_id,
        workspace_id=state.workspace_id,
        brand_id=brand.brand_id,
        product_id=product.product_id,
        project_id=state.project_id,
        client_entity_id=client,
        entity_id=client,
        route_kind=StatementRoute.PROJECT_STATE,
        route_key="target_segment",
        quote=recorded_quote,
        quote_start=quote_start,
        quote_end=quote_end,
        created_by_actor="human",
    )


def _statement_trial(
    conn: AsyncConnection,
    tmp_path: Path,
    artifacts: DurableAgentArtifactStore,
    state: Stage0TrialState,
) -> Stage0Trial:
    trial = object.__new__(Stage0Trial)
    trial.state = state
    trial.paths = Stage0TrialPaths.for_session(tmp_path, state.session_slug)
    trial._components = SimpleNamespace(artifacts=artifacts)  # type: ignore[assignment]

    @asynccontextmanager
    async def connection_factory() -> AsyncIterator[AsyncConnection]:
        yield conn

    trial._conn_factory = connection_factory  # type: ignore[assignment]
    return trial


def _run_statement_scenario(
    tmp_path: Path,
    stage0_db_available: bool,
    *,
    quote_start: int,
    quote_end: int,
    recorded_quote: str,
    erase: bool,
    check: object,
) -> None:
    if not stage0_db_available:
        pytest.skip("requires a migrated per-branch Postgres database")

    async def scenario() -> None:
        state = _state(f"stmt-{uuid4().hex[:8]}")
        async with db_lifespan() as engine:
            conn = await engine.connect()
            outer = await conn.begin()

            @asynccontextmanager
            async def connection_factory() -> AsyncIterator[AsyncConnection]:
                yield conn

            try:
                artifacts = DurableAgentArtifactStore(
                    storage=FsStorage(tmp_path / "artifacts"),
                    conn_factory=connection_factory,
                )
                await _statement_fixture(
                    conn,
                    artifacts,
                    state=state,
                    quote_start=quote_start,
                    quote_end=quote_end,
                    recorded_quote=recorded_quote,
                )
                if erase:
                    key = (
                        await conn.execute(
                            text(
                                "SELECT artifact_key FROM onboarding_input "
                                "WHERE workspace_id = :workspace"
                            ),
                            {"workspace": state.workspace_id},
                        )
                    ).scalar_one()
                    await mark_erased(conn, key)
                trial = _statement_trial(conn, tmp_path, artifacts, state)
                await check(trial, conn)  # type: ignore[operator]
            finally:
                await outer.rollback()
                await conn.close()

    run_async(scenario())


def test_project_statements_resolve_the_real_captured_quote(
    tmp_path: Path,
    stage0_db_available: bool,
) -> None:
    async def check(trial: Stage0Trial, conn: AsyncConnection) -> None:
        resolved = await trial._project_statements(conn)
        assert [item.quote for item in resolved.statements] == ["neurosurgery practices"]
        assert [item.route_key for item in resolved.statements] == ["target_segment"]
        assert resolved.excluded_statement_ids == ()

    _run_statement_scenario(
        tmp_path,
        stage0_db_available,
        quote_start=10,
        quote_end=32,
        recorded_quote="neurosurgery practices",
        erase=False,
        check=check,
    )


def test_project_statement_that_no_longer_hashes_to_its_evidence_raises(
    tmp_path: Path,
    stage0_db_available: bool,
) -> None:
    """Corruption or tampering is fail-closed: the span the row hashed is not the span the
    artifact now yields, so synthesis must refuse rather than quietly use the wrong words."""

    async def check(trial: Stage0Trial, conn: AsyncConnection) -> None:
        with pytest.raises(RuntimeError, match="does not match its captured evidence quote"):
            await trial._project_statements(conn)

    _run_statement_scenario(
        tmp_path,
        stage0_db_available,
        quote_start=0,
        quote_end=10,  # the offsets select "We target " ...
        recorded_quote="neurosurgery practices",  # ... but the row hashed something else
        erase=False,
        check=check,
    )


def test_erased_evidence_drops_one_statement_instead_of_bricking_synthesis(
    tmp_path: Path,
    stage0_db_available: bool,
) -> None:
    """A DSAR erasure of one conversation turn must not permanently disable ICP synthesis: the
    statement is dropped and surfaced as an exclusion, by id only."""

    async def check(trial: Stage0Trial, conn: AsyncConnection) -> None:
        rows = await read_statements(
            conn,
            workspace_id=trial.state.workspace_id,
            project_id=trial.state.project_id,
        )
        resolved = await trial._project_statements(conn)
        assert resolved.statements == ()
        assert resolved.excluded_statement_ids == tuple(row.id for row in rows)
        # repeatable: erasure is a stable exclusion, not a one-shot failure
        assert (await trial._project_statements(conn)) == resolved

    _run_statement_scenario(
        tmp_path,
        stage0_db_available,
        quote_start=10,
        quote_end=32,
        recorded_quote="neurosurgery practices",
        erase=True,
        check=check,
    )


def test_a_superseded_icp_proposal_file_marks_itself_stale_instead_of_bricking_the_session(
    tmp_path: Path,
    stage0_db_available: bool,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A proposal file from an older Client-KB version must not take the whole session down.

    The live defect: ``_load_icp_proposals`` raised on any lineage drift, and ``snapshot()`` — which
    runs at the *start and end of every turn*, and behind ``/status`` and every report export —
    called it unconditionally. So the first claim-bearing turn after ``/synthesize-icp`` published a
    new Client-KB version and every subsequent turn, status read, report export, and confirmation
    raised, until the human happened to re-synthesize. Reading superseded proposals is a *reference*
    concern; only *confirming* one is an authority concern, so tolerance and strictness split there.

    The Client-KB version bump is applied at the same seam the turn applies it
    (``_refresh_client_kb_from_conversation``'s ``state.model_copy``), because driving a real
    conversation turn would need a live model call, which this suite must not make.
    """

    grounded = ICPProposal(icp_key="primary", label="US neurosurgery practices with own imaging")

    async def synthesized(*args: object, **kwargs: object) -> ICPSynthesisResult:
        del args, kwargs
        return ICPSynthesisResult(
            proposals=(grounded,),
            status=ICPSynthesisStatus.GROUNDED,
            reason_codes=(),
        )

    monkeypatch.setattr("clue_api.stage0_trial.synthesize_icps", synthesized)

    def _keys(snapshot: dict[str, object]) -> list[object]:
        return [
            item["icp_key"] for item in cast(list[dict[str, object]], snapshot["icp_proposals"])
        ]

    async def check(trial: Stage0Trial, conn: AsyncConnection) -> None:
        trial._gateway = cast(Any, SimpleNamespace())
        trial._settings = Settings(_env_file=None)
        object.__setattr__(trial._components, "history", SimpleNamespace(load=_no_history))
        await trial.confirm_product()

        await trial.synthesize_icp_proposals()
        fresh = await trial.snapshot()
        assert _keys(fresh) == ["primary"]
        assert fresh["icp_proposals_stale"] is False
        assert fresh["icp_proposals_stale_reason"] is None

        # The next claim-bearing turn publishes the next immutable Client-KB version.
        superseded = trial.state.client_kb_version
        trial.state = trial.state.model_copy(update={"client_kb_version": superseded + 1})

        # Every read path still works, and says plainly that the saved proposals are superseded.
        stale = await trial.snapshot()  # the per-turn read, and what /status prints
        assert stale["icp_proposals"] == []
        assert stale["icp_proposals_stale"] is True
        assert "client_kb_version" in str(stale["icp_proposals_stale_reason"])
        await trial.export_report()  # the end-of-turn export, and /report
        report = json.loads(trial.paths.report_json.read_text(encoding="utf-8"))
        assert report["current_truth"]["icp_proposals_stale"] is True
        assert report["current_truth"]["icp_proposals"] == []

        # Confirming is where lineage is authority, so it still refuses — loudly and specifically.
        with pytest.raises(ValueError, match="does not match the current Stage-0 trial lineage"):
            await trial.confirm_icp_proposal(1)

        # Re-synthesizing against the current version clears the marker.
        await trial.synthesize_icp_proposals()
        recovered = await trial.snapshot()
        assert _keys(recovered) == ["primary"]
        assert recovered["icp_proposals_stale"] is False

    _run_statement_scenario(
        tmp_path,
        stage0_db_available,
        quote_start=10,
        quote_end=32,
        recorded_quote="neurosurgery practices",
        erase=False,
        check=check,
    )


async def _no_history(**kwargs: object) -> tuple[object, ...]:
    del kwargs
    return ()


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
