"""C7.5 governed additive research-view re-check."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_api.research_view_tools import (
    RecheckResearchViewInput,
    RecheckResearchViewTool,
)
from clue_api.research_view_wiring import ToolInvokerResearchOperationRequester
from clue_api.tool_outputs import ResearchViewChangeReportOutput
from clue_core import (
    FreshnessState,
    OperationId,
    ResearchAvailability,
    ResearchSectionKind,
    ResearchStatement,
    ResearchView,
    ResearchViewRecheckRequest,
    ResearchViewSnapshotId,
    new_operation_id,
)
from clue_research.narrative import (
    GovernedResearchOperationRequest,
    ResearchViewRecheckConflict,
    ResearchViewRecheckService,
    ResearchViewSectionStalenessService,
    ResearchViewSnapshotCommand,
    ResearchViewSnapshotService,
)
from clue_research.narrative.research_view_recheck import (
    _classify_changes,
    _SnapshotItem,
)
from clue_toolbelt import ReplayPolicy, ToolContext, ToolEffectClass

from .conftest import rollback_conn, run_async
from .test_research_view_snapshots import (
    _Composer,
    _Reachability,
    _seed_scope,
)
from .test_research_views import _compose_account_fixture

_MIGRATION = (
    Path(__file__).resolve().parents[2]
    / "alembic/versions/9df19defc755_c7_5_governed_research_view_recheck.py"
)
_SERVICE = (
    Path(__file__).resolve().parents[2]
    / "subsystems/research/clue_research/narrative/research_view_recheck.py"
)


@asynccontextmanager
async def _fixed(conn: AsyncConnection) -> AsyncIterator[AsyncConnection]:
    yield conn


class _ResearchRequester:
    def __init__(self) -> None:
        self.calls: list[GovernedResearchOperationRequest] = []
        self.committed: set[OperationId] = set()
        self.spend_count = 0

    async def request(self, request: GovernedResearchOperationRequest) -> OperationId:
        self.calls.append(request)
        if request.operation_id not in self.committed:
            self.committed.add(request.operation_id)
            self.spend_count += 1
        return request.operation_id


class _CrashOnce:
    def __init__(self, point: str) -> None:
        self.point = point
        self.crashed = False

    async def __call__(self, point: str) -> None:
        if point == self.point and not self.crashed:
            self.crashed = True
            raise RuntimeError(f"crash:{point}")


class _RecordingInvoker:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, object], ToolContext, str | None]] = []

    async def invoke(
        self,
        name: str,
        body: dict[str, object],
        context: ToolContext,
        *,
        version: str | None = None,
    ) -> object:
        self.calls.append((name, body, context, version))
        return object()


def _recheck_request(
    view: ResearchView,
    snapshot_id: ResearchViewSnapshotId,
    *,
    operation_id: OperationId | None = None,
    section_kinds: tuple[ResearchSectionKind, ...] = (),
    request_research: bool = False,
) -> ResearchViewRecheckRequest:
    return ResearchViewRecheckRequest(
        operation_id=operation_id or new_operation_id(),
        workspace_id=view.workspace_id,
        project_id=view.project_id,
        subject_entity_id=view.subject.entity_id,
        snapshot_id=snapshot_id,
        section_kinds=section_kinds,
        request_research=request_research,
    )


def _with_stale_statement(
    view: ResearchView,
    statement_id: UUID,
) -> ResearchView:
    sections = tuple(
        section.model_copy(
            update={
                "items": tuple(
                    item.model_copy(
                        update={
                            "state": item.state.model_copy(
                                update={
                                    "freshness": FreshnessState.STALE,
                                    "reason_codes": ("freshness_ttl_elapsed",),
                                }
                            )
                        }
                    )
                    if isinstance(item, ResearchStatement) and item.statement_id == statement_id
                    else item
                    for item in section.items
                )
            }
        )
        for section in view.sections
    )
    return view.model_copy(update={"sections": sections})


def _without_statement(
    view: ResearchView,
    statement_id: UUID,
    *,
    restricted: bool,
) -> ResearchView:
    sections = []
    for section in view.sections:
        items = tuple(
            item
            for item in section.items
            if not (isinstance(item, ResearchStatement) and item.statement_id == statement_id)
        )
        if len(items) == len(section.items):
            sections.append(section)
            continue
        sections.append(
            section.model_copy(
                update={
                    "items": items,
                    "availability": (
                        ResearchAvailability.RESTRICTED
                        if restricted
                        else ResearchAvailability.UNAVAILABLE
                    )
                    if not items
                    else ResearchAvailability.AVAILABLE,
                    "reason_codes": (
                        ("display_policy_denied",) if restricted else ("claim_superseded",)
                    ),
                }
            )
        )
    return view.model_copy(update={"sections": tuple(sections)})


async def _snapshot_fixture(
    conn: AsyncConnection,
) -> tuple[ResearchView, _Composer, ResearchViewSnapshotService, ResearchViewSnapshotId]:
    view, read_request, _fixture_composer, _candidates = await _compose_account_fixture()
    await _seed_scope(conn, view)
    composer = _Composer(view)
    snapshots = ResearchViewSnapshotService(
        composer,
        _Reachability(view),
        conn_factory=lambda: _fixed(conn),
    )
    receipt = await snapshots.compose_and_save(
        ResearchViewSnapshotCommand(
            operation_id=new_operation_id(),
            request=read_request,
        )
    )
    return view, composer, snapshots, receipt.snapshot_id


def test_recheck_request_rejects_policy_weakening_and_duplicate_sections() -> None:
    view, _request, _composer, _candidates = run_async(_compose_account_fixture())
    payload = {
        "operation_id": str(new_operation_id()),
        "workspace_id": view.workspace_id,
        "project_id": view.project_id,
        "subject_entity_id": str(view.subject.entity_id),
        "snapshot_id": str(uuid4()),
        "section_kinds": ["summary"],
        "request_research": False,
    }
    with pytest.raises(ValidationError, match="extra_forbidden"):
        ResearchViewRecheckRequest.model_validate({**payload, "verification_threshold": 0.1})
    with pytest.raises(ValidationError, match="must be unique"):
        ResearchViewRecheckRequest.model_validate(
            {**payload, "section_kinds": ["summary", "summary"]}
        )
    with pytest.raises(ValidationError):
        ResearchViewRecheckRequest.model_validate(
            {**payload, "section_kinds": ["invented_section"]}
        )


def test_recheck_schema_is_reference_only_and_append_only() -> None:
    source = _MIGRATION.read_text(encoding="utf-8").lower()
    ddl = source[source.index("def upgrade()") :]
    forbidden = (
        "value_json",
        "evidence_span",
        "source_url",
        "storage_key",
        "signed_url",
        "rendered_body",
        "html_body",
        "rationale",
        "prompt",
        "model_id",
        "verification_threshold",
    )
    assert all(token not in ddl for token in forbidden)
    assert '"research_view_change_report",' in source
    assert '"research_view_event",' in source
    assert 'f"create trigger {table}_append_only "' in source


def test_recheck_service_has_no_model_resolver_or_claim_mutation_authority() -> None:
    source = _SERVICE.read_text(encoding="utf-8").lower()
    forbidden = (
        "llmgateway",
        "derivationentailmentjudge",
        "clue_research.resolvers",
        "clue_research.verification",
        "verification_threshold",
        "quality_mode",
        "presign(",
        "update claim ",
        "delete from claim ",
    )
    assert all(token not in source for token in forbidden)
    assert "governedresearchoperationrequester" in source
    assert "researchviewsnapshotservice" in source


def test_recheck_tool_contract_is_typed_and_replay_certified() -> None:
    tool = RecheckResearchViewTool(object())  # type: ignore[arg-type]
    descriptor = tool.descriptor
    assert descriptor.address == "recheck_research_view@1"
    assert descriptor.replay.policy is ReplayPolicy.OPERATION_IDEMPOTENT
    assert descriptor.replay.operation_id_required is True
    assert descriptor.effect_class is ToolEffectClass.WRITE
    assert descriptor.output_model is ResearchViewChangeReportOutput
    assert descriptor.recipe_safe


def test_change_classifier_covers_stale_policy_supersession_and_erasure() -> None:
    def item(
        item_id: UUID,
        *,
        freshness: str = "fresh",
        availability: str = "available",
        display: str = "allowed",
        missing: str | None = None,
    ) -> _SnapshotItem:
        return _SnapshotItem(
            item_id=str(item_id),
            statement_id=item_id,
            section_id="research.summary",
            section_kind=ResearchSectionKind.SUMMARY,
            claim_id=uuid4(),
            availability=availability,
            freshness=freshness,
            display_decision=display,
            current_missing_state=missing,
        )

    unchanged_id, stale_id, policy_id, superseded_id, erased_id = (
        uuid4(),
        uuid4(),
        uuid4(),
        uuid4(),
        uuid4(),
    )
    old = (
        item(unchanged_id),
        item(stale_id),
        item(policy_id),
        item(superseded_id, missing="unavailable"),
        item(erased_id, missing="redacted"),
    )
    new = (
        item(unchanged_id),
        item(stale_id, freshness="stale"),
        item(policy_id, availability="restricted", display="denied"),
    )
    changes = _classify_changes(
        old_items=old,
        new_items=new,
        old_live_item_ids={str(unchanged_id), str(stale_id), str(policy_id)},
        section_kinds=(),
    )
    by_id = {UUID(value.item_id): value.kind for value in changes}
    assert by_id == {
        unchanged_id: "unchanged",
        stale_id: "stale",
        policy_id: "restricted",
        superseded_id: "removed",
        erased_id: "restricted",
    }


@pytest.mark.usefixtures("require_narrative_db")
def test_recheck_tool_enforces_scope_and_returns_only_report_references() -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            view, _composer, snapshots, old_snapshot_id = await _snapshot_fixture(conn)
            tool = RecheckResearchViewTool(
                ResearchViewRecheckService(
                    snapshots=snapshots,
                    conn_factory=lambda: _fixed(conn),
                )
            )
            inputs = RecheckResearchViewInput(
                project_id=view.project_id,
                subject_entity_id=UUID(str(view.subject.entity_id)),
                snapshot_id=UUID(str(old_snapshot_id)),
            )
            context = ToolContext(
                workspace_id=view.workspace_id,
                actor="human",
                conn_factory=lambda: _fixed(conn),
                operation_id=new_operation_id(),
            )
            assert await tool.preconditions(inputs, context) == ()
            result = await tool.invoke(inputs, context)
            output = ResearchViewChangeReportOutput.model_validate(result.references)
            assert output.operation_id == str(context.operation_id)
            assert output.old_snapshot_id == str(old_snapshot_id)
            assert output.fetch_ref.startswith("research-view-change-report:")
            assert "value_json" not in result.references

            denied = await tool.preconditions(
                inputs,
                ToolContext(
                    workspace_id="another-workspace",
                    actor="human",
                    conn_factory=lambda: _fixed(conn),
                    operation_id=new_operation_id(),
                ),
            )
            assert [item.reason_code for item in denied] == ["research_view_snapshot_not_found"]

    run_async(scenario())


@pytest.mark.usefixtures("require_narrative_db")
def test_noop_recheck_is_idempotent_body_free_and_emits_one_completion() -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            view, composer, snapshots, old_snapshot_id = await _snapshot_fixture(conn)
            service = ResearchViewRecheckService(
                snapshots=snapshots,
                conn_factory=lambda: _fixed(conn),
            )
            request = _recheck_request(view, old_snapshot_id)
            first = await service.recheck(request)
            second = await service.recheck(request)

            assert first == second
            assert first.old_snapshot_id == old_snapshot_id
            assert first.new_snapshot_id != old_snapshot_id
            assert first.reason_codes == ("no_change",)
            assert first.unchanged_statement_ids
            assert not first.added_statement_ids
            assert not first.removed_statement_ids
            assert composer.calls == 3  # old snapshot, old live resolution, new snapshot
            assert (
                await service.get_report(
                    workspace_id=view.workspace_id,
                    report_id=first.report_id,
                )
                == first
            )
            assert (
                await service.get_report(
                    workspace_id="wrong-workspace",
                    report_id=first.report_id,
                )
                is None
            )

            counts = (
                await conn.execute(
                    text(
                        """
                        SELECT
                            (SELECT count(*) FROM research_view_change_report
                             WHERE operation_id = :operation_id),
                            (SELECT count(*) FROM research_view_event
                             WHERE report_id = :report_id),
                            (SELECT count(*) FROM research_view_snapshot
                             WHERE supersedes_snapshot_id = :old_snapshot_id)
                        """
                    ),
                    {
                        "operation_id": str(request.operation_id),
                        "report_id": str(first.report_id),
                        "old_snapshot_id": str(old_snapshot_id),
                    },
                )
            ).one()
            assert counts == (1, 1, 1)

            serialized = (
                await conn.execute(
                    text(
                        """
                        SELECT concat_ws(
                            ' ',
                            (SELECT jsonb_agg(to_jsonb(r))::text
                             FROM research_view_change_report r
                             WHERE r.report_id = :report_id),
                            (SELECT jsonb_agg(to_jsonb(i))::text
                             FROM research_view_change_item i
                             WHERE i.report_id = :report_id),
                            (SELECT jsonb_agg(to_jsonb(e))::text
                             FROM research_view_event e
                             WHERE e.report_id = :report_id)
                        )
                        """
                    ),
                    {"report_id": str(first.report_id)},
                )
            ).scalar_one()
            assert "verified summary" not in serialized.lower()
            assert "synthetic evidence" not in serialized.lower()
            assert "://" not in serialized

    run_async(scenario())


@pytest.mark.usefixtures("require_narrative_db")
def test_section_selector_bounds_stale_and_restricted_changes() -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            view, composer, snapshots, old_snapshot_id = await _snapshot_fixture(conn)
            summary = next(
                item
                for section in view.sections
                if section.kind is ResearchSectionKind.SUMMARY
                for item in section.items
                if isinstance(item, ResearchStatement)
            )
            summary_section_id = next(
                section.section_id
                for section in view.sections
                if section.kind is ResearchSectionKind.SUMMARY
            )
            about = next(
                item
                for section in view.sections
                if section.kind is ResearchSectionKind.ABOUT
                for item in section.items
                if isinstance(item, ResearchStatement)
            )
            composer.view = _without_statement(
                _with_stale_statement(view, UUID(str(summary.statement_id))),
                UUID(str(about.statement_id)),
                restricted=True,
            )
            service = ResearchViewRecheckService(
                snapshots=snapshots,
                conn_factory=lambda: _fixed(conn),
            )
            report = await service.recheck(
                _recheck_request(
                    view,
                    old_snapshot_id,
                    section_kinds=(ResearchSectionKind.SUMMARY,),
                )
            )
            assert report.stale_statement_ids == (summary.statement_id,)
            assert not report.restricted_statement_ids
            assert "section_selector_applied" in report.reason_codes

            rows = (
                await conn.execute(
                    text(
                        "SELECT topic, section_ids FROM research_view_event "
                        "WHERE report_id = :report_id ORDER BY topic"
                    ),
                    {"report_id": str(report.report_id)},
                )
            ).all()
            assert {row[0] for row in rows} == {
                "research_view.recheck_completed",
                "research_view.section_stale",
                "research_view.updated",
            }
            assert all(set(row[1]) <= {summary_section_id} for row in rows)

    run_async(scenario())


@pytest.mark.usefixtures("require_narrative_db")
@pytest.mark.parametrize(
    "crash_point",
    ("after_research_request", "after_snapshot", "before_report_commit"),
)
def test_recheck_crash_replay_has_one_spend_snapshot_report_and_event_set(
    crash_point: str,
) -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            view, _composer, snapshots, old_snapshot_id = await _snapshot_fixture(conn)
            requester = _ResearchRequester()
            crash = _CrashOnce(crash_point)
            service = ResearchViewRecheckService(
                snapshots=snapshots,
                research_requester=requester,
                conn_factory=lambda: _fixed(conn),
                crash_hook=crash,
            )
            request = _recheck_request(
                view,
                old_snapshot_id,
                request_research=True,
            )
            with pytest.raises(RuntimeError, match=f"crash:{crash_point}"):
                await service.recheck(request)
            report = await service.recheck(request)
            replayed = await service.recheck(request)

            assert replayed == report
            assert requester.spend_count == 1
            assert len({call.operation_id for call in requester.calls}) == 1
            assert report.requested_operation_ids == (requester.calls[0].operation_id,)
            counts = (
                await conn.execute(
                    text(
                        """
                        SELECT
                            (SELECT count(*) FROM research_view_snapshot
                             WHERE supersedes_snapshot_id = :old_snapshot_id),
                            (SELECT count(*) FROM research_view_change_report
                             WHERE operation_id = :operation_id),
                            (SELECT count(*) FROM research_view_event
                             WHERE report_id = :report_id)
                        """
                    ),
                    {
                        "old_snapshot_id": str(old_snapshot_id),
                        "operation_id": str(request.operation_id),
                        "report_id": str(report.report_id),
                    },
                )
            ).one()
            assert counts == (1, 1, 1)

    run_async(scenario())


@pytest.mark.usefixtures("require_narrative_db")
def test_recheck_replay_rejects_changed_scope_and_invalid_view_section() -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            view, _composer, snapshots, old_snapshot_id = await _snapshot_fixture(conn)
            service = ResearchViewRecheckService(
                snapshots=snapshots,
                conn_factory=lambda: _fixed(conn),
            )
            request = _recheck_request(view, old_snapshot_id)
            await service.recheck(request)
            with pytest.raises(ResearchViewRecheckConflict, match="different re-check"):
                await service.recheck(request.model_copy(update={"project_id": "other-project"}))

            contact_only = request.model_copy(
                update={
                    "operation_id": new_operation_id(),
                    "section_kinds": (ResearchSectionKind.CAREER,),
                }
            )
            with pytest.raises(ResearchViewRecheckConflict, match="not valid"):
                await service.recheck(contact_only)

    run_async(scenario())


@pytest.mark.usefixtures("require_narrative_db")
def test_reverse_reference_staleness_is_idempotent_and_body_free() -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            view, _composer, _snapshots, old_snapshot_id = await _snapshot_fixture(conn)
            derived = next(
                item
                for section in view.sections
                for item in section.items
                if isinstance(item, ResearchStatement) and item.supports
            )
            derived_section_id = next(
                section.section_id for section in view.sections if derived in section.items
            )
            support_id = UUID(str(derived.supports[0].claim_id))
            service = ResearchViewSectionStalenessService(conn_factory=lambda: _fixed(conn))
            operation_id = new_operation_id()
            first = await service.mark_claims_changed(
                workspace_id=view.workspace_id,
                operation_id=operation_id,
                claim_ids=(support_id,),
                reason_code="support_superseded",
            )
            second = await service.mark_claims_changed(
                workspace_id=view.workspace_id,
                operation_id=operation_id,
                claim_ids=(support_id,),
                reason_code="support_superseded",
            )
            assert first == second
            assert first

            count = (
                await conn.execute(
                    text(
                        """
                        SELECT count(*)
                        FROM research_view_section_staleness
                        WHERE operation_id = :operation_id
                          AND snapshot_id = :snapshot_id
                        """
                    ),
                    {
                        "operation_id": str(operation_id),
                        "snapshot_id": str(old_snapshot_id),
                    },
                )
            ).scalar_one()
            assert count == 1
            event = (
                await conn.execute(
                    text(
                        """
                        SELECT topic, section_ids, item_ids, reason_codes, fetch_ref
                        FROM research_view_event
                        WHERE event_key = :event_key
                        """
                    ),
                    {"event_key": f"section-stale:{operation_id}:{old_snapshot_id}"},
                )
            ).one()
            assert event[0] == "research_view.section_stale"
            assert event[1] == [derived_section_id]
            assert str(derived.statement_id) in event[2]
            assert event[3] == ["support_superseded"]
            assert event[4] == f"research-view-snapshot:{old_snapshot_id}"

    run_async(scenario())


@pytest.mark.usefixtures("require_narrative_db")
def test_api_requester_uses_exact_run_scope_and_stable_tool_operation() -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            view, _composer, _snapshots, _old_snapshot_id = await _snapshot_fixture(conn)
            account_run_id = uuid4()
            await conn.execute(
                text(
                    """
                    INSERT INTO account_run (
                        id, project_run_id, entity_id, tier, status
                    ) VALUES (
                        :id, :project_run_id, :entity_id, 'tier_1', 'done'
                    )
                    """
                ),
                {
                    "id": str(account_run_id),
                    "project_run_id": str(view.project_run_id),
                    "entity_id": str(view.subject.entity_id),
                },
            )
            invoker = _RecordingInvoker()
            requester = ToolInvokerResearchOperationRequester(
                invoker,  # type: ignore[arg-type]
                conn_factory=lambda: _fixed(conn),
            )
            operation_id = new_operation_id()
            result = await requester.request(
                GovernedResearchOperationRequest(
                    operation_id=operation_id,
                    workspace_id=view.workspace_id,
                    project_id=view.project_id,
                    project_run_id=UUID(str(view.project_run_id)),
                    subject=view.subject,
                    account_entity_id=UUID(str(view.subject.entity_id)),
                    section_kinds=(ResearchSectionKind.SUMMARY,),
                    field_keys=("account.summary",),
                )
            )
            assert result == operation_id
            assert len(invoker.calls) == 1
            name, body, context, version = invoker.calls[0]
            assert name == "run_deep_account"
            assert version == "1"
            assert body == {
                "account_entity_id": str(view.subject.entity_id),
                "icp_key": "default",
                "tier": "tier_1",
                "project_run_id": str(view.project_run_id),
            }
            assert context.operation_id == operation_id
            assert context.workspace_id == view.workspace_id
            assert context.quality_mode is None

    run_async(scenario())
