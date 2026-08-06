"""M8C C6 provider-neutral preparation, cancellation, wake, and composition gates."""

from __future__ import annotations

from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
from tests.db.conftest import run_async

from clue_api.contact_research_preparation import (
    ContactPreparationAdapterResult,
    RegisteredContactResearchPreparer,
    build_production_contact_channel_coordinator,
    build_production_contact_research_preparer,
)
from clue_api.external_research_wake import ExternalResearchWakeDispatcher
from clue_config import (
    ConfidenceThresholds,
    ContactResearchPolicy,
    Secrets,
    Settings,
    SourcePlanPolicy,
)
from clue_core import (
    CONTACT_CHANNEL_FIELD_KEYS,
    ContactPreparationStatus,
    ContactResearchIntent,
    ContactResearchPreparation,
    ContactResearchSelection,
    ContactResearchSelectionBody,
    ContactResearchTarget,
    IdentityBinding,
    PreSpendDecision,
    PreSpendVerdict,
    ProjectRunId,
    ResearchDirectiveId,
    ResearchDirectivePin,
    RunId,
    UseClass,
    new_claim_id,
    new_entity_id,
    new_run_id,
)
from clue_research.durable import ProjectRunStatus
from clue_research.profiling import profile_contact
from clue_storage import FsStorage


def _intent() -> ContactResearchIntent:
    account_id = new_entity_id()
    directive_id = ResearchDirectiveId(uuid4())
    body = ContactResearchSelectionBody(
        workspace_id="workspace-c6",
        project_id="project-c6",
        project_run_id=ProjectRunId(uuid4()),
        account_entity_id=account_id,
        research_directive=ResearchDirectivePin(
            directive_id=directive_id,
            directive_ref=f"research-directive:{directive_id}:v1",
            version=1,
            canonical_json_sha256="a" * 64,
            account_id=account_id,
        ),
        targets=(
            ContactResearchTarget(
                contact_entity_id=new_entity_id(),
                committee_claim_ids=(new_claim_id(),),
                strong_identity_claim_ids=(new_claim_id(),),
                field_keys=("contact.current_title",),
            ),
        ),
        policy=ContactResearchPolicy().pin(),
        source_profile_ref="source-profile:c6",
        jurisdiction_policy_ref="jurisdiction:c6",
        use_policy_ref="use:c6",
        retention_policy_ref="retention:c6",
        budget_reservation_ref="budget:c6",
        approved_by="human:c6",
        approved_at=datetime(2026, 8, 5, tzinfo=UTC),
    )
    selection = ContactResearchSelection.from_body(body, effective_policy=body.policy)
    return ContactResearchIntent.from_selection(
        selection,
        contact_entity_id=body.targets[0].contact_entity_id,
    )


class _TrackedConnFactory:
    def __init__(self) -> None:
        self.active = 0

    @asynccontextmanager
    async def __call__(self) -> AsyncIterator[object]:
        self.active += 1
        try:
            yield object()
        finally:
            self.active -= 1


class _Adapter:
    def __init__(
        self,
        tracker: _TrackedConnFactory,
        *,
        claimed_sources: frozenset[str] | None = None,
        status: ContactPreparationStatus = ContactPreparationStatus.READY,
    ) -> None:
        self.tracker = tracker
        self.claimed_sources = claimed_sources
        self.status = status
        self.calls = 0

    def claimed_source_keys(self, intent: ContactResearchIntent) -> frozenset[str]:
        return self.claimed_sources or frozenset(intent.source_plan)

    async def prepare(
        self,
        *,
        intent: ContactResearchIntent,
        effective_policy: object,
        run_id: RunId,
    ) -> ContactPreparationAdapterResult:
        del intent, effective_policy, run_id
        assert self.tracker.active == 0, "external preparation ran under a DB context"
        self.calls += 1
        return ContactPreparationAdapterResult(
            preparation=ContactResearchPreparation(
                status=self.status,
                snapshot_reference_ids=("snapshot:c6",),
                operation_reference_ids=(
                    ("operation:c6",)
                    if self.status is ContactPreparationStatus.WAITING_EXTERNAL
                    else ()
                ),
                next_wake_at=(
                    datetime(2026, 8, 5, 1, tzinfo=UTC)
                    if self.status is ContactPreparationStatus.WAITING_EXTERNAL
                    else None
                ),
            )
        )


def test_registered_preparer_closes_db_context_before_adapter_and_cancellation_is_zero_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tracker = _TrackedConnFactory()
    adapter = _Adapter(tracker)
    intent = _intent()
    cancellation: object | None = None

    async def _run_row(_conn: object, _project_run_id: ProjectRunId) -> object:
        return SimpleNamespace(
            workspace_id=intent.workspace_id,
            status=ProjectRunStatus.ACTIVE,
        )

    async def _cancellation(_conn: object, **_kwargs: object) -> object | None:
        return cancellation

    monkeypatch.setattr(
        "clue_api.contact_research_preparation.get_project_run",
        _run_row,
    )
    monkeypatch.setattr(
        "clue_api.contact_research_preparation.contact_research_selection_cancellation",
        _cancellation,
    )
    preparer = RegisteredContactResearchPreparer(
        adapters=(adapter,),
        conn_factory=tracker,  # type: ignore[arg-type]
    )

    async def scenario() -> None:
        nonlocal cancellation
        ready = await preparer.prepare(intent=intent, run_id=new_run_id())
        assert ready.preparation.status is ContactPreparationStatus.READY
        assert adapter.calls == 1
        cancellation = SimpleNamespace(reason_code="human_cancelled")
        stopped = await preparer.prepare(intent=intent, run_id=new_run_id())
        assert stopped.preparation.status is ContactPreparationStatus.NOT_ELIGIBLE
        assert stopped.preparation.reason_codes == ("selection_cancelled:human_cancelled",)
        assert adapter.calls == 1

        cancellation = None
        partial = _Adapter(
            tracker,
            claimed_sources=frozenset({intent.source_plan[0]}),
        )
        incomplete = await RegisteredContactResearchPreparer(
            adapters=(partial,),
            conn_factory=tracker,  # type: ignore[arg-type]
        ).prepare(intent=intent, run_id=new_run_id())
        assert incomplete.preparation.status is ContactPreparationStatus.NOT_ELIGIBLE
        assert incomplete.preparation.reason_codes[0].startswith("contact_adapters_unregistered:")
        assert partial.calls == 0

    run_async(scenario())


def test_ordered_preparation_does_not_start_later_adapter_while_predecessor_waits(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tracker = _TrackedConnFactory()
    intent = _intent()
    first_source, second_source = intent.source_plan[:2]
    waiting = _Adapter(
        tracker,
        claimed_sources=frozenset({first_source}),
        status=ContactPreparationStatus.WAITING_EXTERNAL,
    )
    later = _Adapter(tracker, claimed_sources=frozenset({second_source}))

    async def _run_row(_conn: object, _project_run_id: ProjectRunId) -> object:
        return SimpleNamespace(workspace_id=intent.workspace_id, status=ProjectRunStatus.ACTIVE)

    async def _cancellation(_conn: object, **_kwargs: object) -> None:
        return None

    monkeypatch.setattr("clue_api.contact_research_preparation.get_project_run", _run_row)
    monkeypatch.setattr(
        "clue_api.contact_research_preparation.contact_research_selection_cancellation",
        _cancellation,
    )

    async def scenario() -> None:
        result = await RegisteredContactResearchPreparer(
            adapters=(waiting, later),
            conn_factory=tracker,  # type: ignore[arg-type]
        ).prepare(intent=intent, run_id=new_run_id())
        assert result.preparation.status is ContactPreparationStatus.WAITING_EXTERNAL
        assert waiting.calls == 1
        assert later.calls == 0

    run_async(scenario())


def test_prepared_contact_projection_never_reenters_resolver_waterfall(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    contact_id = new_entity_id()
    account_id = new_entity_id()
    claim_id = new_claim_id()

    async def _survivor(_conn: object, entity_id: object, _kind: object) -> object:
        return entity_id

    async def _contact(_conn: object, _entity_id: object) -> object:
        return SimpleNamespace(id=contact_id)

    async def _account(_conn: object, _entity_id: object) -> object:
        return SimpleNamespace(id=account_id)

    async def _claims(_conn: object, _claim_ids: object, **_kwargs: object) -> object:
        return {
            claim_id: SimpleNamespace(
                id=claim_id,
                entity_id=contact_id,
                field_key="contact.current_title",
                value_json="VP Operations",
                evidence_span="Jane Doe is VP Operations at the exact employer.",
                source_tier=1,
                identity_binding=IdentityBinding.STRONG,
                use_class=UseClass.PROFESSIONAL_PUBLIC,
            )
        }

    async def _unexpected_waterfall(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("prepared contact path re-entered resolver waterfall")

    monkeypatch.setattr("clue_research.profiling.contact.worker.surviving_id", _survivor)
    monkeypatch.setattr("clue_research.profiling.contact.worker.get_contact", _contact)
    monkeypatch.setattr("clue_research.profiling.contact.worker.get_account", _account)
    monkeypatch.setattr("clue_research.profiling.contact.worker.claims_by_ids", _claims)
    monkeypatch.setattr(
        "clue_research.profiling.contact.worker.compute_contact_gap_fields",
        _unexpected_waterfall,
    )

    async def scenario() -> None:
        result = await profile_contact(
            object(),  # type: ignore[arg-type]
            contact_entity_id=contact_id,
            account_entity_id=account_id,
            run_id=new_run_id(),
            workspace_id="workspace-c6",
            tier="tier_1",
            field_keys=(
                "contact.current_title",
                CONTACT_CHANNEL_FIELD_KEYS[next(iter(CONTACT_CHANNEL_FIELD_KEYS))],
            ),
            prepared_claim_refs=(claim_id,),
            thresholds=ConfidenceThresholds(),
            plan_policy=SourcePlanPolicy(),
        )
        assert result.claim_refs == (claim_id,)
        assert result.fields_filled == 1
        assert result.fields_empty == 0

    run_async(scenario())


def test_external_wake_deduplicates_runs_and_only_reoffers_owning_project_runs() -> None:
    run_a = ProjectRunId(uuid4())
    run_b = ProjectRunId(uuid4())
    offered: list[ProjectRunId] = []

    @asynccontextmanager
    async def _conn_factory() -> AsyncIterator[object]:
        yield object()

    async def _source_a(_conn: object, _now: datetime, _limit: int) -> Sequence[ProjectRunId]:
        return (run_a, run_b)

    async def _source_b(_conn: object, _now: datetime, _limit: int) -> Sequence[ProjectRunId]:
        return (run_a,)

    async def _wake(run_id: ProjectRunId) -> bool:
        offered.append(run_id)
        return True

    async def scenario() -> None:
        dispatcher = ExternalResearchWakeDispatcher(
            project_run_waker=_wake,
            sources=(_source_a, _source_b),  # type: ignore[arg-type]
            conn_factory=_conn_factory,  # type: ignore[arg-type]
        )
        assert await dispatcher.run_due(now=datetime(2026, 8, 5, tzinfo=UTC)) == 2
        assert offered == [run_a, run_b]

    run_async(scenario())


def test_external_wake_resolves_exact_entity_members_without_widening_project_runs() -> None:
    run_id = ProjectRunId(uuid4())
    project_offers: list[ProjectRunId] = []
    member_offers: list[str] = []

    @asynccontextmanager
    async def _conn_factory() -> AsyncIterator[object]:
        yield object()

    async def _projects(_conn: object, _now: datetime, _limit: int) -> Sequence[ProjectRunId]:
        return (run_id,)

    async def _members(_conn: object, _now: datetime, _limit: int) -> Sequence[str]:
        return (
            "committee-operation:00000000-0000-0000-0000-000000000001",
            "committee-operation:00000000-0000-0000-0000-000000000001",
        )

    async def _wake_project(value: ProjectRunId) -> bool:
        project_offers.append(value)
        return True

    async def _wake_member(value: str) -> int:
        member_offers.append(value)
        return 1

    async def scenario() -> None:
        dispatcher = ExternalResearchWakeDispatcher(
            project_run_waker=_wake_project,
            sources=(_projects,),  # type: ignore[arg-type]
            entity_member_waker=_wake_member,
            entity_wait_sources=(_members,),  # type: ignore[arg-type]
            conn_factory=_conn_factory,  # type: ignore[arg-type]
        )
        assert await dispatcher.run_due(now=datetime(2026, 8, 6, tzinfo=UTC)) == 2
        assert project_offers == [run_id]
        assert member_offers == ["committee-operation:00000000-0000-0000-0000-000000000001"]

    run_async(scenario())


class _PassGate:
    async def check(self, request: object) -> PreSpendDecision:
        del request
        return PreSpendDecision(verdict=PreSpendVerdict.PASS)


def test_production_composition_refuses_channel_activation_without_real_validator(
    tmp_path: Path,
) -> None:
    settings = Settings(
        _env_file=None,
        contact_channel_enrichment_enabled=True,
    )
    with pytest.raises(RuntimeError, match="validator-backed coordinator"):
        build_production_contact_research_preparer(
            settings,
            secrets=Secrets(_env_file=None, exa_api_key=None),
            storage=FsStorage(tmp_path),
            pre_spend_gate=_PassGate(),  # type: ignore[arg-type]
        )


def test_production_composition_admits_an_explicit_validator_backed_channel_adapter(
    tmp_path: Path,
) -> None:
    coordinator = build_production_contact_channel_coordinator(
        transport=SimpleNamespace(),  # type: ignore[arg-type]
        validator=SimpleNamespace(source_key="independent-validator"),  # type: ignore[arg-type]
        storage=FsStorage(tmp_path),
        pre_spend_gate=_PassGate(),  # type: ignore[arg-type]
    )
    preparer = build_production_contact_research_preparer(
        Settings(_env_file=None, contact_channel_enrichment_enabled=True),
        secrets=Secrets(_env_file=None, exa_api_key=None),
        storage=FsStorage(tmp_path),
        pre_spend_gate=_PassGate(),  # type: ignore[arg-type]
        channel_coordinator=coordinator,
    )

    adapters = preparer._preparer._adapters  # noqa: SLF001 - production composition acceptance
    assert type(adapters[-1]).__name__ == "ContactChannelPreparationAdapter"
