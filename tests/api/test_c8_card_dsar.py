"""PC-C8 §9 / AC-11 — the card copy's DSAR path, end to end.

The card is a **derived copy** of interview personal data that this slice created, so erasure ships
with it rather than after it. The headline test walks the whole life of one quoted statement:

    compile a card that quotes statement X
      → journal a turn against that card
      → erase X and its evidence
      → the old card body is unreadable
      → recompiling omits X *and says so*
      → cold replay of the journaled turn cannot recover the erased bytes

Each of those is a separate way the copy could have leaked, and the test asserts all six in one
scenario because they are only meaningful in sequence: a recompile that omits X proves nothing if
the previous card body is still on disk, and an unreadable body proves nothing if a replay can
fetch it back.

Supporting tests cover the two halves the headline depends on: the reverse bindings the erasure
*finds* the card through, and the fail-closed refusal that stops one workspace erasing another's
statement.

DB-backed, following ``tests/api`` conventions: a per-branch ``CLUE_DATABASE_URL``, one
rollback-only transaction per scenario, and ``pytest.skip`` without a database.
"""

from __future__ import annotations

from pathlib import Path
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text

from clue_agents import AgentRole
from clue_api.agent_registry_wiring import build_agent_profile_registry
from clue_api.agent_turn_wiring import (
    AgentPrivacyService,
    DbAgentReplayReader,
    DbAgentTurnJournal,
)
from clue_api.stage0_card_dsar import (
    STAGE0_CARD_QUOTE_BINDING_KIND,
    Stage0StatementEraser,
    Stage0StatementNotFound,
    card_artifacts_quoting_statement,
    stage0_card_subject_bindings,
)
from clue_api.toolbelt_wiring import build_toolbelt
from clue_core import EntityId, OnboardingInputKind
from clue_projections import Stage0CardOmissionKind, Stage0ProjectCard
from clue_research.stage0 import StatementRoute, record_statement, submit_onboarding_input
from clue_storage import ArtifactNotFound, FsStorage
from tests.agents.workspace_helpers import make_workspace
from tests.api.test_c8_project_card_wiring import _seeded_trial
from tests.api.test_c8_slice0_evidence import (
    _ANSWER,
    _QUOTE_END,
    _QUOTE_START,
    _turn_request,
)
from tests.db.conftest import _db_available, run_async


@pytest.fixture
def stage0_db_available() -> bool:
    return _db_available()


def _erasure_stack(
    tmp_path: Path,
    trial: object,
    connection_factory: object,
) -> tuple[Stage0StatementEraser, DbAgentReplayReader, object]:
    """The production erasure/replay pair over one throwaway storage root + workspace harness."""

    state = trial.state  # type: ignore[attr-defined]
    storage = FsStorage(tmp_path / "artifacts")
    harness = make_workspace(
        tmp_path / "runtime",
        execution_id=_execution_id(state),
        workspace_id=state.workspace_id,
        project_id=state.project_id,
    )
    privacy = AgentPrivacyService(
        storage=storage,
        workspaces=harness.factory,
        conn_factory=connection_factory,  # type: ignore[arg-type]
    )
    eraser = Stage0StatementEraser(
        privacy=privacy,
        conn_factory=connection_factory,  # type: ignore[arg-type]
    )
    replay = DbAgentReplayReader(
        storage=storage,
        conn_factory=connection_factory,  # type: ignore[arg-type]
    )
    return eraser, replay, harness


def _execution_id(state: object) -> object:
    from uuid import uuid5

    from clue_core import ExecutionId

    return ExecutionId(uuid5(state.session_id, "c8-slice0-execution"))  # type: ignore[attr-defined]


async def _journal_turn(trial: object, connection_factory: object, card_ref: object) -> object:
    """Journal one turn whose L3 project card is ``card_ref`` — the replay surface under test."""

    registry = build_agent_profile_registry(build_toolbelt(storage=None, gateway=None))
    resolved = registry.resolve(AgentRole.HEAD_OF_ABM)
    budget_ref = await trial._artifact(  # type: ignore[attr-defined]
        "application/vnd.clue.agent-budget-envelope+json",
        {"schema_version": "1", "limit_millicents": 1_000_000},
    )
    manifest_ref = await trial._artifact(  # type: ignore[attr-defined]
        "application/vnd.clue.agent-resource-manifest+json",
        resolved.resource_manifest.model_dump(mode="json"),
    )
    user_ref = await trial._components.artifacts.persist_body(  # type: ignore[attr-defined]
        workspace_id=trial.state.workspace_id,  # type: ignore[attr-defined]
        data=_ANSWER.encode(),
        media_type="text/plain",
    )
    request = _turn_request(
        state=trial.state,  # type: ignore[attr-defined]
        resolved=resolved,
        card_ref=card_ref,  # type: ignore[arg-type]
        budget_ref=budget_ref,
        manifest_ref=manifest_ref,
        user_ref=user_ref,
    )
    await DbAgentTurnJournal(conn_factory=connection_factory).create(  # type: ignore[arg-type]
        request=request, profile=resolved.profile
    )
    return request


def test_the_card_binds_every_statement_it_quotes_so_the_reverse_query_is_direct(
    tmp_path: Path,
    stage0_db_available: bool,
) -> None:
    """Spec §9's first requirement: per-source bindings, not one client-level binding.

    Without them "which card artifacts quote statement X" would be a body scan over every card a
    conversation ever persisted — which is exactly the shape of DSAR gap that gets deferred and
    then never closed. With them it is one indexed read, which is what makes the erasure below a
    query rather than a search.
    """

    if not stage0_db_available:
        pytest.skip("requires a migrated per-branch Postgres database")

    async def scenario() -> None:
        async with _seeded_trial(tmp_path, slug=f"bind-{uuid4().hex[:8]}") as (
            trial,
            conn,
            artifacts,
            _factory,
        ):
            card_ref = await trial._project_card_ref()
            card = Stage0ProjectCard.model_validate_json(await artifacts.read(card_ref))
            quoted = [
                UUID(entry.statement_id) for entry in card.interview.current_effective_statements
            ]
            assert quoted, "the fixture must produce a card that actually quotes something"

            # Every quoted statement resolves to this exact card body.
            for statement_id in quoted:
                assert await card_artifacts_quoting_statement(
                    conn, workspace_id=trial.state.workspace_id, statement_id=statement_id
                ) == (card_ref.artifact_key,)

            # The client-level binding is not replaced by the per-statement ones — the card is
            # still personal data about the client, and a client-wide DSAR must still reach it.
            bound = {
                (str(row[0]), row[1])
                for row in (
                    await conn.execute(
                        text(
                            "SELECT subject_entity_id, binding_kind FROM agent_artifact_subject "
                            "WHERE workspace_id = :ws AND artifact_key = :key"
                        ),
                        {"ws": trial.state.workspace_id, "key": card_ref.artifact_key},
                    )
                ).all()
            }
            assert (str(trial.state.client_entity_id), "context") in bound
            assert {
                (str(statement_id), STAGE0_CARD_QUOTE_BINDING_KIND) for statement_id in quoted
            } <= bound

            # A statement the card did NOT quote is not bound: the bindings describe the bytes,
            # not the project. (Nothing in this fixture is dropped, so the negative is asserted
            # against an id that exists nowhere.)
            assert (
                await card_artifacts_quoting_statement(
                    conn,
                    workspace_id=trial.state.workspace_id,
                    statement_id=UUID(int=0),
                )
                == ()
            )

    run_async(scenario())


def test_the_binding_builder_describes_the_card_it_is_persisting_and_nothing_else() -> None:
    """A no-DB shape check on the one function the persist site calls.

    It reads the *compiled card*, so the bindings cannot drift from the bytes; ``base`` is passed
    through untouched so the existing client-level binding survives the change.
    """

    card = Stage0ProjectCard.model_validate(
        {
            "compiler_policy_version": "stage0-card-policy-v1",
            "project": {
                "project_id": "p",
                "name": "n",
                "workspace_id": "w",
                "brand_id": "b",
                "client_entity_id": "00000000-0000-0000-0000-0000000000c1",
            },
            "product": {"confirmed": False},
            "registered_client_claim_fields": [],
            "client_knowledge": {"version": 1, "known_fields": [], "open_gaps": []},
            "interview": {
                "current_effective_statements": [
                    {
                        "statement_id": "00000000-0000-0000-0000-0000000000a1",
                        "route_key": "target_segment",
                        "route_kind": "project_state",
                        "quoted_text": "we sell to neurosurgery practices",
                        "quote_truncated": False,
                    },
                    {
                        "statement_id": "00000000-0000-0000-0000-0000000000a2",
                        "route_key": "channel_preference",
                        "route_kind": "project_state",
                        "quoted_text": "email first",
                        "quote_truncated": False,
                    },
                ],
                "selection": {"included": 2, "total_effective": 2, "deduped_count": 0},
                "unmapped_count": 0,
                "superseded_count": 0,
            },
            "readiness": {"latest_by_gate": [], "ledger_length": 0},
            "icp": {"confirmed": [], "proposals_pending": False, "proposals_stale": False},
            "omissions": [],
            "compiled_from": {
                "client_kb_version": 1,
                "statement_selection_digest": "sha256:0",
                "readiness_decision_ids": [],
                "confirmed_icps": [],
                "compiler_policy_version": "stage0-card-policy-v1",
            },
        }
    )
    client = UUID("00000000-0000-0000-0000-0000000000c1")

    assert stage0_card_subject_bindings(card=card, base=((client, "context"),)) == (
        (client, "context"),
        (UUID("00000000-0000-0000-0000-0000000000a1"), STAGE0_CARD_QUOTE_BINDING_KIND),
        (UUID("00000000-0000-0000-0000-0000000000a2"), STAGE0_CARD_QUOTE_BINDING_KIND),
    )
    # No base: the per-statement bindings stand alone rather than silently inventing a client.
    assert len(stage0_card_subject_bindings(card=card)) == 2


def test_erasing_a_statement_purges_the_cards_that_quoted_it_and_nothing_recovers_it(
    tmp_path: Path,
    stage0_db_available: bool,
) -> None:
    """AC-DSAR (spec §9/§12-11), executable end to end.

    The six assertions, in the order the spec states them:

    1. a card exists that quotes statement X, and a turn is journaled against it;
    2. erasure reaches the card *through the reverse bindings* — the card key it purged is the one
       the binding query returns, not one the test told it about;
    3. the old card body is unreadable (``ArtifactNotFound``) while its artifact row survives as
       audit — the B2 dangling-ref pattern, not a delete;
    4. recompiling omits X **by construction** (the shared evidence reader returns
       ``ExcludedEvidence`` for the purged artifact) and surfaces
       ``excluded_statement_evidence_missing`` rather than quietly returning a shorter card;
    5. cold replay of the journaled turn fails *soft* with the tombstone reason
       (``artifact_erased:project_card``) instead of resurrecting or re-reading the body;
    6. re-persisting the identical card bytes is refused — content addressing must not become a
       resurrection path.
    """

    if not stage0_db_available:
        pytest.skip("requires a migrated per-branch Postgres database")

    async def scenario() -> None:
        async with _seeded_trial(tmp_path, slug=f"dsar-{uuid4().hex[:8]}") as (
            trial,
            conn,
            artifacts,
            connection_factory,
        ):
            workspace_id = trial.state.workspace_id
            eraser, replay, harness = _erasure_stack(tmp_path, trial, connection_factory)
            try:
                # 1. a card that quotes X, and a turn journaled against it.
                card_ref = await trial._project_card_ref()
                card = Stage0ProjectCard.model_validate_json(await artifacts.read(card_ref))
                original_bytes = card.canonical_bytes()
                target = card.interview.current_effective_statements[0]
                statement_id = UUID(target.statement_id)
                assert target.quoted_text
                request = await _journal_turn(trial, connection_factory, card_ref)

                # 2. erasure finds the card through the bindings, not through the test.
                expected_cards = await card_artifacts_quoting_statement(
                    conn, workspace_id=workspace_id, statement_id=statement_id
                )
                assert expected_cards == (card_ref.artifact_key,)
                erasure = await eraser.erase_statement(
                    workspace_id=workspace_id, statement_id=statement_id
                )
                assert erasure.card_artifact_keys == expected_cards
                assert card_ref.artifact_key in erasure.erase.tombstoned_artifact_keys
                assert erasure.evidence_artifact_key in erasure.erase.tombstoned_artifact_keys
                assert request.turn_id in erasure.erase.affected_turn_ids

                # 3. the body is gone; the row survives as audit (B2 dangling ref).
                with pytest.raises(ArtifactNotFound):
                    await artifacts.read(card_ref)
                audit = (
                    (
                        await conn.execute(
                            text(
                                "SELECT erased_at IS NOT NULL AS erased, "
                                "purged_at IS NOT NULL AS purged "
                                "FROM artifact WHERE storage_key = :key"
                            ),
                            {"key": card_ref.artifact_key},
                        )
                    )
                    .mappings()
                    .one()
                )
                assert audit["erased"] and audit["purged"]

                # 4. the recompile omits X by construction and says it did.
                recompiled_ref = await trial._project_card_ref()
                assert recompiled_ref.artifact_key != card_ref.artifact_key
                recompiled = Stage0ProjectCard.model_validate_json(
                    await artifacts.read(recompiled_ref)
                )
                shown = {
                    entry.statement_id
                    for entry in recompiled.interview.current_effective_statements
                }
                assert target.statement_id not in shown
                # The erased statement is named nowhere in the new bytes — not in the selection,
                # not in the lineage digest inputs, not in an omission id list (there are none).
                # (A "the *words* are absent" assertion would be meaningless in this fixture: its
                # turns all quote the same span, so the text legitimately survives on the other
                # statements. The identity of what was dropped is the real check.)
                assert target.statement_id not in recompiled.canonical_bytes().decode()
                omissions = {omission.kind: omission.count for omission in recompiled.omissions}
                assert (
                    omissions.get(Stage0CardOmissionKind.EXCLUDED_STATEMENT_EVIDENCE_MISSING) == 1
                )

                # 5. cold replay fails soft with the tombstone reason.
                blocked = await replay.inspect(workspace_id=workspace_id, turn_id=request.turn_id)
                assert not blocked.replayable
                assert "artifact_erased:project_card" in blocked.blocker_codes
                card_state = next(
                    item
                    for item in blocked.artifacts
                    if item.ref.artifact_key == card_ref.artifact_key
                )
                assert card_state.state.value in {"erased", "purged"}

                # 6. content addressing is not a resurrection path.
                with pytest.raises(ValueError, match="cannot be resurrected"):
                    await artifacts.persist_body(
                        workspace_id=workspace_id,
                        data=original_bytes,
                        media_type=card_ref.media_type,
                    )
            finally:
                harness.close()

    run_async(scenario())


def test_erasing_a_statement_from_another_workspace_is_refused_not_served(
    tmp_path: Path,
    stage0_db_available: bool,
) -> None:
    """Fail-closed erasure scope: a foreign statement id looks exactly like an absent one.

    Erasure is a privileged, destructive path; if it resolved a cross-workspace id it would both
    destroy another tenant's evidence and confirm that the id exists.
    """

    if not stage0_db_available:
        pytest.skip("requires a migrated per-branch Postgres database")

    async def scenario() -> None:
        async with _seeded_trial(tmp_path, slug=f"scope-{uuid4().hex[:8]}") as (
            trial,
            conn,
            _artifacts,
            connection_factory,
        ):
            eraser, _replay, harness = _erasure_stack(tmp_path, trial, connection_factory)
            try:
                statement_id = (
                    await conn.execute(
                        text(
                            "SELECT id FROM volunteered_statement "
                            "WHERE workspace_id = :ws ORDER BY created_at, id LIMIT 1"
                        ),
                        {"ws": trial.state.workspace_id},
                    )
                ).scalar_one()

                # A real statement, asked for from the wrong workspace.
                with pytest.raises(Stage0StatementNotFound):
                    await eraser.erase_statement(
                        workspace_id="ws-somebody-else", statement_id=statement_id
                    )
                # An id that exists nowhere gets the identical refusal (no existence leak).
                with pytest.raises(Stage0StatementNotFound):
                    await eraser.erase_statement(
                        workspace_id=trial.state.workspace_id, statement_id=uuid4()
                    )
                # And the refusal really was a refusal: nothing was tombstoned.
                assert (
                    await conn.execute(
                        text(
                            "SELECT count(*) FROM agent_artifact_tombstone WHERE workspace_id = :ws"
                        ),
                        {"ws": trial.state.workspace_id},
                    )
                ).scalar_one() == 0
            finally:
                harness.close()

    run_async(scenario())


def test_erasing_one_statement_takes_its_capture_mates_words_with_it(
    tmp_path: Path,
    stage0_db_available: bool,
) -> None:
    """The headline claim of the erasure design, on the fixture that can actually test it.

    A statement's evidence is not private to it: the captured artifact is the *whole client turn*,
    and two statements routed out of one answer quote spans of the same body. Erasing X therefore
    destroys Y's words too, so the eraser widens to every statement citing that capture before
    collecting dependent cards. Erasing only X's cards would leave a card body on disk quoting a
    turn that no longer exists.

    Every other fixture in this suite writes one artifact per statement, which makes the affected
    set trivially ``{X}`` and this widening untested — hence a purpose-built two-statements /
    one-onboarding-input fixture.
    """

    if not stage0_db_available:
        pytest.skip("requires a migrated per-branch Postgres database")

    async def scenario() -> None:
        async with _seeded_trial(tmp_path, slug=f"blast-{uuid4().hex[:8]}") as (
            trial,
            conn,
            artifacts,
            connection_factory,
        ):
            state = trial.state
            eraser, _replay, harness = _erasure_stack(tmp_path, trial, connection_factory)
            try:
                # One capture, two statements — the shape the widening exists for.
                ref = await artifacts.persist_body(
                    workspace_id=state.workspace_id,
                    data=f"{_ANSWER} (shared capture)".encode(),
                    media_type="text/plain",
                )
                captured = await submit_onboarding_input(
                    conn,
                    workspace_id=state.workspace_id,
                    brand_id=state.brand_id,
                    product_id=state.product_id,
                    project_id=state.project_id,
                    client_entity_id=EntityId(state.client_entity_id),
                    kind=OnboardingInputKind.USER_TURN,
                    artifact_key=ref.artifact_key,
                    content_sha256=ref.sha256,
                    actor="human",
                )
                pair = []
                for route_key in ("shared_capture_a", "shared_capture_b"):
                    pair.append(
                        await record_statement(
                            conn,
                            onboarding_input_id=captured.onboarding_input_id,
                            workspace_id=state.workspace_id,
                            brand_id=state.brand_id,
                            product_id=state.product_id,
                            project_id=state.project_id,
                            client_entity_id=EntityId(state.client_entity_id),
                            entity_id=EntityId(state.client_entity_id),
                            route_kind=StatementRoute.PROJECT_STATE,
                            route_key=route_key,
                            quote=_ANSWER[_QUOTE_START:_QUOTE_END],
                            quote_start=_QUOTE_START,
                            quote_end=_QUOTE_END,
                            created_by_actor="agent",
                        )
                    )
                target, capture_mate = (UUID(str(item)) for item in pair)

                card_ref = await trial._project_card_ref()
                card = Stage0ProjectCard.model_validate_json(await artifacts.read(card_ref))
                quoted = {
                    entry.statement_id for entry in card.interview.current_effective_statements
                }
                assert {str(target), str(capture_mate)} <= quoted

                erasure = await eraser.erase_statement(
                    workspace_id=state.workspace_id, statement_id=target
                )

                # The blast radius is named, and it includes the target itself (hence
                # `affected_statement_ids`, not "siblings").
                assert set(erasure.affected_statement_ids) == {target, capture_mate}
                assert erasure.card_artifact_keys == (card_ref.artifact_key,)

                # Both statements lost their words, and the recompile surfaces BOTH omissions
                # rather than one — an under-counted omission would understate the erasure.
                recompiled = Stage0ProjectCard.model_validate_json(
                    await artifacts.read(await trial._project_card_ref())
                )
                still_shown = {
                    entry.statement_id
                    for entry in recompiled.interview.current_effective_statements
                }
                assert not {str(target), str(capture_mate)} & still_shown
                omissions = {omission.kind: omission.count for omission in recompiled.omissions}
                assert omissions[Stage0CardOmissionKind.EXCLUDED_STATEMENT_EVIDENCE_MISSING] == 2
            finally:
                harness.close()

    run_async(scenario())


def test_erasing_a_subject_with_no_bound_artifacts_is_a_clean_no_op(
    tmp_path: Path,
    stage0_db_available: bool,
) -> None:
    """The empty key set is a real case, not a theoretical one.

    A DSAR request for a subject that never had an artifact bound must succeed with nothing
    erased. The affected-turn lookup passes the key set as a Postgres array, so an untyped empty
    list would leave the server inferring an element type from no evidence — hence the explicit
    ``CAST(:keys AS text[])``. This is the test that would have caught it.
    """

    if not stage0_db_available:
        pytest.skip("requires a migrated per-branch Postgres database")

    async def scenario() -> None:
        async with _seeded_trial(tmp_path, slug=f"empty-{uuid4().hex[:8]}") as (
            trial,
            conn,
            _artifacts,
            connection_factory,
        ):
            _eraser, _replay, harness = _erasure_stack(tmp_path, trial, connection_factory)
            try:
                privacy = AgentPrivacyService(
                    storage=FsStorage(tmp_path / "artifacts"),
                    workspaces=harness.factory,
                    conn_factory=connection_factory,
                )
                unbound = uuid4()
                result = await privacy.erase_subject(
                    workspace_id=trial.state.workspace_id, subject_entity_id=unbound
                )
                assert result.tombstoned_artifact_keys == ()
                assert result.affected_turn_ids == ()
                assert result.purged_workspace_root_ids == ()

                # The explicit key-set form takes the same empty path.
                direct = await privacy.erase_artifacts(
                    workspace_id=trial.state.workspace_id,
                    subject_entity_id=unbound,
                    artifact_keys=(),
                )
                assert direct.tombstoned_artifact_keys == ()
                assert (
                    await conn.execute(
                        text(
                            "SELECT count(*) FROM agent_artifact_tombstone WHERE workspace_id = :ws"
                        ),
                        {"ws": trial.state.workspace_id},
                    )
                ).scalar_one() == 0
            finally:
                harness.close()

    run_async(scenario())
