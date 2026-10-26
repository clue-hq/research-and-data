from __future__ import annotations

from collections.abc import AsyncIterator, Sequence
from datetime import datetime
from pathlib import Path
from uuid import UUID

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from clue_agents import AgentExecutionStatus
from clue_agents.context import (
    ContextAssemblyPolicy,
    ContextCandidate,
    DeterministicAgentContextAssembler,
    LayerBudget,
    TurnLayerSource,
)
from clue_agents.contracts import (
    AgentFinalizeEnvelope,
    AgentProfile,
    AgentTurnRequest,
    ArtifactRef,
    ContextLayer,
    FinalizeStatus,
)
from clue_agents.ports import HistoryMessageRef
from clue_agents.turns import AgentModelCallReceipt, AgentModelCallStatus
from clue_api.agent_turn_wiring import (
    AgentPrivacyService,
    DbAgentContextReceiptStore,
    DbAgentHistoryStore,
    DbAgentReplayReader,
    DbAgentTurnJournal,
    DurableAgentArtifactStore,
)
from clue_core import new_execution_id
from clue_projections import (
    agent_progress,
    agent_telemetry,
    agent_turn,
    agent_turns_for_project,
)
from clue_storage.protocol import ArtifactNotFound
from tests._workspace import seed_project
from tests.agents.conftest import NOW, SHA_B, constitution, domain_ref
from tests.agents.test_contracts import profile
from tests.agents.workspace_helpers import make_workspace
from tests.db.conftest import run_async
from tests.profiling.conftest import (
    conn_session_factory,
    migrated_db,  # noqa: F401 -- exposes the fixture to this test module
    rollback_conn,
)


@pytest.fixture
def require_c63_db(request: pytest.FixtureRequest) -> None:
    if not request.getfixturevalue("migrated_db"):
        pytest.skip("requires a migrated per-branch Postgres database")


class _Storage:
    def __init__(self) -> None:
        self.objects: dict[str, tuple[bytes, str]] = {}

    async def put(self, key: str, data: bytes, *, media_type: str) -> None:
        self.objects[key] = (data, media_type)

    async def get(self, key: str) -> bytes:
        try:
            return self.objects[key][0]
        except KeyError as exc:
            raise ArtifactNotFound(key) from exc

    async def delete(self, key: str) -> None:
        self.objects.pop(key, None)

    async def exists(self, key: str) -> bool:
        return key in self.objects

    async def presign(self, key: str, *, expires_in: int = 3600) -> str:
        del expires_in
        return key

    async def list_blobs(self) -> AsyncIterator[tuple[str, datetime]]:
        if False:
            yield "", NOW


class _Source:
    def __init__(self, layer: ContextLayer, ref: ArtifactRef) -> None:
        self.layer = layer
        self._ref = ref

    async def load(
        self,
        *,
        request: AgentTurnRequest,
        profile: AgentProfile,
        history: Sequence[HistoryMessageRef],
    ) -> Sequence[ContextCandidate]:
        del profile, history
        return (
            ContextCandidate(
                stable_key=self.layer.value,
                ref=(
                    self._ref
                    if self.layer is ContextLayer.L1_IDENTITY
                    else request.user_message_artifact_ref
                    if self.layer is ContextLayer.L7_TURN
                    else domain_ref(
                        self.layer.value,
                        workspace_id=request.constitution.workspace_id,
                    )
                ),
                body=(
                    "Research this person"
                    if self.layer is ContextLayer.L7_TURN
                    else f"compiled {self.layer.value}"
                ),
                role="user" if self.layer is ContextLayer.L7_TURN else "system",
                origin=(
                    "current_user_instruction"
                    if self.layer is ContextLayer.L7_TURN
                    else "trusted_context"
                ),
                materialized_path=(
                    f"context/{self.layer.value}.md"
                    if self.layer
                    not in {
                        ContextLayer.L1_IDENTITY,
                        ContextLayer.L6_CONVERSATION,
                    }
                    else None
                ),
                required=self.layer is ContextLayer.L7_TURN,
            ),
        )


def test_durable_turn_history_replay_and_dsar_are_body_free_and_fail_closed(
    tmp_path: Path,
    require_c63_db: None,
) -> None:
    del require_c63_db

    async def scenario() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            project = await seed_project(conn, "ws-c63", name="C6.3 durable turn")
            execution_id = new_execution_id()
            await conn.execute(
                text(
                    "INSERT INTO execution "
                    "(id, workspace_id, project_id, started_by, parameter_manifest_hash, "
                    " pin_manifest_hash) "
                    "VALUES (:id, :workspace, :project, 'human', :hash, :hash)"
                ),
                {
                    "id": execution_id,
                    "workspace": project.workspace_id,
                    "project": project.project_id,
                    "hash": "0" * 64,
                },
            )
            factory = conn_session_factory(conn)
            storage = _Storage()
            artifacts = DurableAgentArtifactStore(storage=storage, conn_factory=factory)

            async def put(body: str) -> ArtifactRef:
                return await artifacts.persist_body(
                    workspace_id=project.workspace_id,
                    data=body.encode(),
                    media_type="text/plain",
                )

            card = await put('{"card_kind":"stage0_project","project":{}}')
            budget = await put('{"remaining":100}')
            manifest = await put('{"resources":[]}')
            user_message = await put("Research this person")

            harness = make_workspace(
                tmp_path,
                execution_id=execution_id,
                workspace_id=project.workspace_id,
                project_id=project.project_id,
                thread_id="thread-c63",
            )
            runtime_profile = profile()
            turn_request = AgentTurnRequest(
                turn_id=UUID("00000000-0000-0000-0000-000000000639"),
                thread_id="thread-c63",
                constitution=constitution(
                    workspace_id=project.workspace_id,
                    project_id=project.project_id,
                    execution_id=execution_id,
                    workspace_root_id=harness.lease.identity.workspace_root_id,
                    brand_id=project.brand_id,
                    product_id=None,
                    project_card_ref=card,
                    budget_envelope_ref=budget,
                    resource_manifest_ref=manifest,
                    resource_manifest_sha256=SHA_B,
                    focus_refs=(),
                ),
                user_message_artifact_ref=user_message,
                requested_at=NOW,
            )
            turns = DbAgentTurnJournal(conn_factory=factory)
            created = await turns.create(request=turn_request, profile=runtime_profile)
            replayed_create = await turns.create(request=turn_request, profile=runtime_profile)
            assert replayed_create == created

            history = DbAgentHistoryStore(conn_factory=factory)
            first_message_id = UUID("00000000-0000-0000-0000-000000000640")
            first = await history.append(
                message_id=first_message_id,
                turn_id=turn_request.turn_id,
                workspace_id=project.workspace_id,
                thread_id=turn_request.thread_id,
                role="user",
                body_ref=user_message,
            )
            assert (
                await history.append(
                    message_id=first_message_id,
                    turn_id=turn_request.turn_id,
                    workspace_id=project.workspace_id,
                    thread_id=turn_request.thread_id,
                    role="user",
                    body_ref=user_message,
                )
                == first
            )
            assert tuple(
                await history.load(
                    workspace_id=project.workspace_id,
                    thread_id=turn_request.thread_id,
                )
            ) == (first,)

            receipt_store = DbAgentContextReceiptStore(conn_factory=factory)
            assembler = DeterministicAgentContextAssembler(
                sources=(
                    *(
                        _Source(layer, manifest)
                        for layer in ContextLayer
                        if layer is not ContextLayer.L7_TURN
                    ),
                    TurnLayerSource(artifacts),
                ),
                policy=ContextAssemblyPolicy(
                    version="opening-v1",
                    token_counter_version="utf8-bytes-v1",
                    budgets=tuple(
                        LayerBudget(layer=layer, max_tokens=1_000) for layer in ContextLayer
                    ),
                ),
                receipts=receipt_store,
                clock=lambda: NOW,
            )
            assembled = await assembler.assemble(
                request=turn_request,
                profile=runtime_profile,
                history=(first,),
            )
            assert len(assembled.manifest.layers) == 7

            model_receipt = AgentModelCallReceipt(
                model_call_id=UUID("00000000-0000-0000-0000-000000000641"),
                turn_id=turn_request.turn_id,
                execution_id=execution_id,
                workspace_id=project.workspace_id,
                sequence=1,
                requested_model="openai/gpt-4.1",
                answering_model="openai/gpt-4.1",
                status=AgentModelCallStatus.COMPLETED,
                input_tokens=100,
                cache_read_input_tokens=40,
                cache_creation_input_tokens=5,
                output_tokens=20,
                cost_millicredits=12,
                latency_ms=25,
                started_at=NOW,
                completed_at=NOW,
            )
            await turns.record_model_call(receipt=model_receipt)
            await turns.record_model_call(receipt=model_receipt)
            await turns.record_workspace_usage(
                turn_id=turn_request.turn_id,
                workspace_id=project.workspace_id,
                usage=harness.lease.usage_snapshot(),
            )
            finalization = AgentFinalizeEnvelope(
                finalization_id=UUID("00000000-0000-0000-0000-000000000642"),
                execution_id=execution_id,
                status=FinalizeStatus.COMPLETED,
                user_message_artifact_ref=user_message,
                finalized_at=NOW,
            )
            await turns.record_finalization(
                turn_id=turn_request.turn_id,
                workspace_id=project.workspace_id,
                envelope=finalization,
            )

            turn_view = await agent_turn(
                workspace_id=project.workspace_id,
                turn_id=turn_request.turn_id,
                conn_factory=factory,
            )
            assert turn_view is not None
            assert turn_view.profile_address == "profile:head-of-abm@1.0.0"
            assert turn_view.workspace_root_id == harness.lease.identity.workspace_root_id
            assert (
                await agent_turn(
                    workspace_id="another-workspace",
                    turn_id=turn_request.turn_id,
                    conn_factory=factory,
                )
                is None
            )
            project_turns = await agent_turns_for_project(
                workspace_id=project.workspace_id,
                project_id=project.project_id,
                conn_factory=factory,
            )
            # FI Lane D D0 gave this reader keyset pagination (FI-1 defect L6). The summaries are
            # unchanged; they now arrive as one page, and a single turn is the whole of it.
            assert tuple(item.turn_id for item in project_turns.items) == (turn_request.turn_id,)
            assert project_turns.next_cursor is None
            progress = await agent_progress(
                workspace_id=project.workspace_id,
                turn_id=turn_request.turn_id,
                conn_factory=factory,
            )
            assert progress is not None
            assert progress.model_call_count == 1
            telemetry = await agent_telemetry(
                workspace_id=project.workspace_id,
                turn_id=turn_request.turn_id,
                conn_factory=factory,
            )
            assert telemetry is not None
            assert telemetry.input_tokens == 100
            assert telemetry.cache_read_input_tokens == 40
            assert telemetry.cache_creation_input_tokens == 5
            assert telemetry.cache_read_ratio == pytest.approx(0.4)
            assert telemetry.workspace_files == 0
            await turns.record_finalization(
                turn_id=turn_request.turn_id,
                workspace_id=project.workspace_id,
                envelope=finalization,
            )
            finalization_ref = await artifacts.persist_body(
                workspace_id=project.workspace_id,
                data=finalization.model_dump_json(exclude_none=False).encode(),
                media_type="application/vnd.clue.agent-finalization+json",
            )
            await turns.commit_finalization_authority(
                turn_id=turn_request.turn_id,
                workspace_id=project.workspace_id,
                envelope=finalization,
                envelope_ref=finalization_ref,
            )
            committed = await turns.load_committed_outcome(
                turn_id=turn_request.turn_id,
                workspace_id=project.workspace_id,
            )
            assert committed is not None
            assert committed.status is AgentExecutionStatus.COMPLETED
            assert committed.finalization_ref == finalization_ref
            assert (
                await turns.load_committed_outcome(
                    turn_id=turn_request.turn_id,
                    workspace_id="another-workspace",
                )
                is None
            )

            replay = DbAgentReplayReader(storage=storage, conn_factory=factory)
            live = await replay.require_replayable(
                workspace_id=project.workspace_id,
                turn_id=turn_request.turn_id,
            )
            assert live.context is not None
            assert live.context.manifest == assembled.manifest
            assert live.context.policy_version == "opening-v1"
            assert live.context.layer_token_budgets == (1_000,) * 7
            assert live.replayable
            with pytest.raises(KeyError):
                await replay.inspect(
                    workspace_id="another-workspace",
                    turn_id=turn_request.turn_id,
                )

            savepoint = await conn.begin_nested()
            try:
                with pytest.raises(DBAPIError):
                    await conn.execute(
                        text("UPDATE agent_thread_message SET role='assistant' WHERE id=:id"),
                        {"id": first_message_id},
                    )
            finally:
                await savepoint.rollback()

            await artifacts.bind_subject(
                ref=user_message,
                subject_entity_id=UUID("00000000-0000-0000-0000-000000000699"),
                binding_kind="direct",
            )
            # Review of F3 Phase 2: the DSAR purge is about the keys this erasure marked.
            # ``purge_erased_artifacts`` opens with an unfiltered
            # ``UPDATE artifact … WHERE expires_at <= now()`` and a sequential scan — the
            # keyless maintenance sweep's job, not a subject erasure's to do on rows belonging
            # to other owners (research quality artifacts and ARV2 media both set ``expires_at``).
            expiring = f"{project.workspace_id}/{'e' * 64}"
            await storage.put(expiring, b"another owner's bytes", media_type="text/plain")
            await conn.execute(
                text(
                    "INSERT INTO artifact (storage_key, workspace_id, content_sha256, "
                    "media_type, size_bytes, expires_at) VALUES (:key, :ws, :sha, "
                    "'text/plain', 21, now() - interval '1 second')"
                ),
                {"key": expiring, "ws": project.workspace_id, "sha": "e" * 64},
            )
            erased = await AgentPrivacyService(
                storage=storage,
                workspaces=harness.factory,
                conn_factory=factory,
            ).erase_subject(
                workspace_id=project.workspace_id,
                subject_entity_id=UUID("00000000-0000-0000-0000-000000000699"),
            )
            assert erased.affected_turn_ids == (turn_request.turn_id,)
            assert not harness.thread_path.exists()
            untouched = (
                await conn.execute(
                    text(
                        "SELECT erased_at, purged_at, privacy_erased FROM artifact "
                        "WHERE storage_key = :key"
                    ),
                    {"key": expiring},
                )
            ).one()
            assert tuple(untouched) == (None, None, False)
            assert await storage.exists(expiring)
            with pytest.raises(ArtifactNotFound):
                await artifacts.read(user_message)
            blocked = await replay.inspect(
                workspace_id=project.workspace_id,
                turn_id=turn_request.turn_id,
            )
            assert not blocked.replayable
            assert "artifact_erased:user_message" in blocked.blocker_codes
            with pytest.raises(ValueError, match="cannot be resurrected"):
                await artifacts.persist_body(
                    workspace_id=project.workspace_id,
                    data=b"Research this person",
                    media_type="text/plain",
                )
            harness.close()

    run_async(scenario())


def test_project_bound_context_blocks_orphaning_and_is_erased_before_project_delete(
    tmp_path: Path,
    require_c63_db: None,
) -> None:
    del require_c63_db

    async def scenario() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            project = await seed_project(conn, "ws-a2-project-erasure", name="A2 erasure")
            factory = conn_session_factory(conn)
            storage = _Storage()
            artifacts = DurableAgentArtifactStore(storage=storage, conn_factory=factory)
            context_ref = await artifacts.persist_body(
                workspace_id=project.workspace_id,
                data=b'{"directive_ref":"research-directive:test:v1"}',
                media_type="application/vnd.clue.account-research-directive+json",
                project_bindings=((project.project_id, "account_research_context"),),
            )

            blocked = await conn.begin_nested()
            with pytest.raises(DBAPIError):
                await conn.execute(
                    text(
                        "DELETE FROM project WHERE project_id=:project_id "
                        "AND workspace_id=:workspace_id"
                    ),
                    {
                        "project_id": project.project_id,
                        "workspace_id": project.workspace_id,
                    },
                )
            await blocked.rollback()

            harness = make_workspace(
                tmp_path,
                workspace_id=project.workspace_id,
                project_id=project.project_id,
            )
            try:
                erased = await AgentPrivacyService(
                    storage=storage,
                    workspaces=harness.factory,
                    conn_factory=factory,
                ).erase_project(
                    workspace_id=project.workspace_id,
                    project_id=project.project_id,
                )
                assert erased.tombstoned_artifact_keys == (context_ref.artifact_key,)
                with pytest.raises(ArtifactNotFound):
                    await artifacts.read(context_ref)
                assert (
                    await conn.execute(
                        text(
                            "SELECT count(*) FROM agent_artifact_project "
                            "WHERE workspace_id=:workspace_id AND project_id=:project_id"
                        ),
                        {
                            "workspace_id": project.workspace_id,
                            "project_id": project.project_id,
                        },
                    )
                ).scalar_one() == 0
                await conn.execute(
                    text(
                        "DELETE FROM project WHERE project_id=:project_id "
                        "AND workspace_id=:workspace_id"
                    ),
                    {
                        "project_id": project.project_id,
                        "workspace_id": project.workspace_id,
                    },
                )
            finally:
                harness.close()

    run_async(scenario())
