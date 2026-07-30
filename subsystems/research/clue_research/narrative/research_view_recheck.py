"""C7.5 additive research-view re-check and section-staleness receipts.

The service compares body-free snapshot references, optionally delegates bounded research through
an injected replay-certified operation seam, creates a new C7.4 snapshot, and appends one immutable
change report plus body-free events. It never calls a resolver/model, mutates an old snapshot, or
accepts caller-owned policy settings.
"""

from __future__ import annotations

import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol
from uuid import NAMESPACE_URL, UUID, uuid5

from pydantic import BaseModel, ConfigDict
from sqlalchemy import text
from sqlalchemy.engine import Row
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_core import (
    EntityId,
    EntityType,
    OperationId,
    ProjectRunId,
    ResearchSectionKind,
    ResearchStatement,
    ResearchStatementId,
    ResearchSubjectRef,
    ResearchView,
    ResearchViewChangeReportId,
    ResearchViewChangeReportRef,
    ResearchViewReadRequest,
    ResearchViewRecheckRequest,
    ResearchViewSnapshotId,
    RunId,
)
from clue_db import ConnFactory, transaction
from clue_research.narrative.research_view_snapshots import (
    ResearchViewSnapshotCommand,
    ResearchViewSnapshotService,
)

_REPORT_NAMESPACE = uuid5(NAMESPACE_URL, "clue-hq:c7:research-view-change-report:1.0")
_RESEARCH_OPERATION_NAMESPACE = uuid5(
    NAMESPACE_URL, "clue-hq:c7:research-view-recheck-research:1.0"
)
_SNAPSHOT_OPERATION_NAMESPACE = uuid5(
    NAMESPACE_URL, "clue-hq:c7:research-view-recheck-snapshot:1.0"
)
_STALENESS_NAMESPACE = uuid5(NAMESPACE_URL, "clue-hq:c7:research-view-staleness:1.0")
_EVENT_NAMESPACE = uuid5(NAMESPACE_URL, "clue-hq:c7:research-view-event:1.0")

_CHANGE_KINDS = ("unchanged", "added", "removed", "stale", "restricted")


class ResearchViewRecheckConflict(ValueError):
    """A retry changed scope or selected an invalid section."""


class ResearchViewRecheckUnavailable(RuntimeError):
    """Governed re-research was requested but no durable requester is composed."""


class GovernedResearchOperationRequest(BaseModel):
    """Reference-only handoff to the existing governed C5/C6 operation path."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    operation_id: OperationId
    workspace_id: str
    project_id: str
    project_run_id: UUID
    subject: ResearchSubjectRef
    account_entity_id: UUID
    section_kinds: tuple[ResearchSectionKind, ...]
    field_keys: tuple[str, ...]


class GovernedResearchOperationRequester(Protocol):
    """Request one replay-certified research operation; implementations own admission/spend."""

    async def request(self, request: GovernedResearchOperationRequest) -> OperationId: ...


class SubjectActivityAppender(Protocol):
    """Injected owner seam for projecting a body-free research-view event into activity."""

    async def __call__(
        self,
        conn: AsyncConnection,
        *,
        workspace_id: str,
        project_id: str,
        project_run_id: ProjectRunId,
        account_run_id: RunId,
        subject_entity_id: EntityId,
        subject_entity_type: EntityType,
        product_id: str | None,
        owner_event_ref: str,
        event_kind: str,
        occurred_at: datetime,
        actor_category: str | None = None,
    ) -> None: ...


type RecheckCrashHook = Callable[[str], Awaitable[None]]


async def _no_crash(_point: str) -> None:
    return None


@dataclass(frozen=True)
class _SnapshotItem:
    item_id: str
    statement_id: UUID | None
    section_id: str
    section_kind: ResearchSectionKind
    claim_id: UUID | None
    availability: str | None
    freshness: str | None
    display_decision: str | None
    current_missing_state: str | None


@dataclass(frozen=True)
class _ChangeItem:
    item_id: str
    statement_id: UUID | None
    section_id: str
    kind: str


@dataclass(frozen=True)
class _StoredReport:
    report: ResearchViewChangeReportRef
    workspace_id: str
    project_id: str
    subject_entity_id: UUID
    selected_section_kinds: tuple[ResearchSectionKind, ...]
    request_research: bool


def _view_item_ids(view: ResearchView) -> set[str]:
    ids: set[str] = set()
    for section in view.sections:
        for item in section.items:
            if isinstance(item, ResearchStatement):
                ids.add(str(item.statement_id))
            elif item.item_kind == "personalization":
                ids.add(str(item.item_id))
            else:
                ids.add(str(item.item_id))
    return ids


def _selected(
    item: _SnapshotItem,
    section_kinds: tuple[ResearchSectionKind, ...],
) -> bool:
    return not section_kinds or item.section_kind in section_kinds


def _classify_changes(
    *,
    old_items: tuple[_SnapshotItem, ...],
    new_items: tuple[_SnapshotItem, ...],
    old_live_item_ids: set[str],
    section_kinds: tuple[ResearchSectionKind, ...],
) -> tuple[_ChangeItem, ...]:
    old_by_id = {item.item_id: item for item in old_items if _selected(item, section_kinds)}
    new_by_id = {item.item_id: item for item in new_items if _selected(item, section_kinds)}
    changes: list[_ChangeItem] = []
    for item_id in sorted(set(old_by_id) | set(new_by_id)):
        old = old_by_id.get(item_id)
        new = new_by_id.get(item_id)
        source = new or old
        assert source is not None
        if old is None:
            kind = "added"
        elif new is None:
            if old.current_missing_state == "redacted":
                kind = "restricted"
            elif old.current_missing_state == "unavailable":
                kind = "removed"
            else:
                kind = "restricted" if item_id not in old_live_item_ids else "removed"
        elif new.availability in {"restricted", "redacted"} or new.display_decision == "denied":
            kind = "restricted"
        elif new.freshness == "stale":
            kind = "stale"
        else:
            kind = "unchanged"
        changes.append(
            _ChangeItem(
                item_id=item_id,
                statement_id=source.statement_id,
                section_id=source.section_id,
                kind=kind,
            )
        )
    return tuple(changes)


def _reason_codes(
    changes: tuple[_ChangeItem, ...],
    *,
    request_research: bool,
    selected: bool,
) -> tuple[str, ...]:
    changed = {item.kind for item in changes if item.kind != "unchanged"}
    reasons: list[str] = []
    if not changed:
        reasons.append("no_change")
    else:
        for kind in ("added", "removed", "stale", "restricted"):
            if kind in changed:
                reasons.append(f"{kind}_references")
    if request_research:
        reasons.append("research_requested")
    if selected:
        reasons.append("section_selector_applied")
    return tuple(reasons)


class ResearchViewRecheckService:
    """One idempotent, crash-resumable additive re-check."""

    def __init__(
        self,
        *,
        snapshots: ResearchViewSnapshotService,
        research_requester: GovernedResearchOperationRequester | None = None,
        subject_activity_appender: SubjectActivityAppender | None = None,
        conn_factory: ConnFactory = transaction,
        clock: Callable[[], datetime] | None = None,
        crash_hook: RecheckCrashHook = _no_crash,
    ) -> None:
        self._snapshots = snapshots
        self._research_requester = research_requester
        self._subject_activity_appender = subject_activity_appender
        self._conn_factory = conn_factory
        self._clock = clock or (lambda: datetime.now(UTC))
        self._crash_hook = crash_hook

    async def recheck(
        self,
        request: ResearchViewRecheckRequest,
    ) -> ResearchViewChangeReportRef:
        existing = await self._existing(request.workspace_id, request.operation_id)
        if existing is not None:
            _require_matching_recheck(existing, request)
            return existing.report

        old_receipt = await self._snapshots.receipt(
            workspace_id=request.workspace_id,
            snapshot_id=request.snapshot_id,
        )
        if old_receipt is None:
            raise ResearchViewRecheckConflict("snapshot is not available in this workspace")
        if (
            old_receipt.project_id != request.project_id
            or old_receipt.subject.entity_id != request.subject_entity_id
        ):
            raise ResearchViewRecheckConflict("re-check scope does not match the saved snapshot")

        old_live = await self._snapshots.resolve(
            workspace_id=request.workspace_id,
            snapshot_id=request.snapshot_id,
        )
        if old_live is None:  # pragma: no cover - receipt and resolution share one scope lookup
            raise ResearchViewRecheckConflict("snapshot disappeared during re-check")
        available_kinds = {section.kind for section in old_live.sections}
        invalid_sections = set(request.section_kinds) - available_kinds
        if invalid_sections:
            raise ResearchViewRecheckConflict(
                f"section selector is not valid for this view: "
                f"{sorted(item.value for item in invalid_sections)}"
            )

        async with self._conn_factory() as conn:
            field_keys = await _selected_field_keys(
                conn,
                snapshot_id=request.snapshot_id,
                section_kinds=request.section_kinds,
            )

        requested_operation_ids: tuple[OperationId, ...] = ()
        if request.request_research:
            if self._research_requester is None:
                raise ResearchViewRecheckUnavailable(
                    "request_research requires the governed research operation requester"
                )
            child_operation_id = OperationId(
                uuid5(_RESEARCH_OPERATION_NAMESPACE, str(request.operation_id))
            )
            account_entity_id = (
                old_receipt.subject.entity_id
                if old_receipt.subject.entity_type is EntityType.ACCOUNT
                else old_receipt.subject.parent_account_id
            )
            if account_entity_id is None:  # pragma: no cover - guarded by ResearchSubjectRef
                raise ResearchViewRecheckConflict("contact snapshot has no parent account")
            returned_operation_id = await self._research_requester.request(
                GovernedResearchOperationRequest(
                    operation_id=child_operation_id,
                    workspace_id=request.workspace_id,
                    project_id=request.project_id,
                    project_run_id=UUID(str(old_receipt.project_run_id)),
                    subject=old_receipt.subject,
                    account_entity_id=UUID(str(account_entity_id)),
                    section_kinds=request.section_kinds,
                    field_keys=field_keys,
                )
            )
            if returned_operation_id != child_operation_id:
                raise ResearchViewRecheckConflict(
                    "governed research requester redirected the operation identity"
                )
            requested_operation_ids = (child_operation_id,)
            await self._crash_hook("after_research_request")

        new_receipt = await self._snapshots.compose_and_save(
            ResearchViewSnapshotCommand(
                operation_id=OperationId(
                    uuid5(_SNAPSHOT_OPERATION_NAMESPACE, str(request.operation_id))
                ),
                request=ResearchViewReadRequest(
                    workspace_id=old_receipt.workspace_id,
                    project_id=old_receipt.project_id,
                    project_run_id=old_receipt.project_run_id,
                    subject_entity_id=old_receipt.subject.entity_id,
                    product_id=old_receipt.product_id,
                    schema_version=old_receipt.schema_version,
                ),
                supersedes_snapshot_id=old_receipt.snapshot_id,
            )
        )
        await self._crash_hook("after_snapshot")

        async with self._conn_factory() as conn:
            existing = await _report_for_operation(
                conn,
                workspace_id=request.workspace_id,
                operation_id=request.operation_id,
            )
            if existing is not None:
                _require_matching_recheck(existing, request)
                return existing.report

            old_items = await _snapshot_items(
                conn,
                request.snapshot_id,
                workspace_id=request.workspace_id,
            )
            new_items = await _snapshot_items(
                conn,
                new_receipt.snapshot_id,
                workspace_id=request.workspace_id,
            )
            changes = _classify_changes(
                old_items=old_items,
                new_items=new_items,
                old_live_item_ids=_view_item_ids(old_live),
                section_kinds=request.section_kinds,
            )
            reasons = _reason_codes(
                changes,
                request_research=request.request_research,
                selected=bool(request.section_kinds),
            )
            report_id = ResearchViewChangeReportId(
                uuid5(_REPORT_NAMESPACE, f"{request.workspace_id}:{request.operation_id}")
            )
            inserted = await conn.execute(
                text(
                    """
                    INSERT INTO research_view_change_report (
                        report_id, operation_id, workspace_id, project_id, project_run_id,
                        subject_entity_id, subject_entity_type, parent_account_entity_id,
                        product_id,
                        old_snapshot_id, new_snapshot_id,
                        old_source_state_sha256, new_source_state_sha256,
                        old_composition_sha256, new_composition_sha256,
                        selected_section_kinds, request_research, reason_codes, created_at
                    ) VALUES (
                        :report_id, :operation_id, :workspace_id, :project_id, :project_run_id,
                        :subject_entity_id, :subject_entity_type, :parent_account_entity_id,
                        :product_id,
                        :old_snapshot_id, :new_snapshot_id,
                        :old_source_state_sha256, :new_source_state_sha256,
                        :old_composition_sha256, :new_composition_sha256,
                        :selected_section_kinds, :request_research, :reason_codes, :created_at
                    )
                    ON CONFLICT (workspace_id, operation_id) DO NOTHING
                    RETURNING report_id
                    """
                ),
                {
                    "report_id": str(report_id),
                    "operation_id": str(request.operation_id),
                    "workspace_id": request.workspace_id,
                    "project_id": request.project_id,
                    "project_run_id": str(old_receipt.project_run_id),
                    "subject_entity_id": str(old_receipt.subject.entity_id),
                    "subject_entity_type": old_receipt.subject.entity_type.value,
                    "parent_account_entity_id": (
                        str(old_receipt.subject.parent_account_id)
                        if old_receipt.subject.parent_account_id is not None
                        else None
                    ),
                    "product_id": old_receipt.product_id,
                    "old_snapshot_id": str(old_receipt.snapshot_id),
                    "new_snapshot_id": str(new_receipt.snapshot_id),
                    "old_source_state_sha256": old_receipt.source_state_sha256,
                    "new_source_state_sha256": new_receipt.source_state_sha256,
                    "old_composition_sha256": old_receipt.composition_sha256,
                    "new_composition_sha256": new_receipt.composition_sha256,
                    "selected_section_kinds": [item.value for item in request.section_kinds],
                    "request_research": request.request_research,
                    "reason_codes": list(reasons),
                    "created_at": self._clock(),
                },
            )
            if inserted.first() is None:
                concurrent = await _report_for_operation(
                    conn,
                    workspace_id=request.workspace_id,
                    operation_id=request.operation_id,
                )
                if concurrent is None:  # pragma: no cover - defensive
                    raise RuntimeError("re-check idempotency conflict has no durable report")
                _require_matching_recheck(concurrent, request)
                return concurrent.report

            for change in changes:
                await conn.execute(
                    text(
                        """
                        INSERT INTO research_view_change_item (
                            report_id, item_id, statement_id, section_id, change_kind
                        ) VALUES (
                            :report_id, :item_id, :statement_id, :section_id, :change_kind
                        )
                        """
                    ),
                    {
                        "report_id": str(report_id),
                        "item_id": change.item_id,
                        "statement_id": (
                            str(change.statement_id) if change.statement_id is not None else None
                        ),
                        "section_id": change.section_id,
                        "change_kind": change.kind,
                    },
                )
            for ordinal, operation_id in enumerate(requested_operation_ids):
                await conn.execute(
                    text(
                        """
                        INSERT INTO research_view_change_operation (
                            report_id, ordinal, requested_operation_id
                        ) VALUES (:report_id, :ordinal, :requested_operation_id)
                        """
                    ),
                    {
                        "report_id": str(report_id),
                        "ordinal": ordinal,
                        "requested_operation_id": str(operation_id),
                    },
                )
            report = _report_ref(
                report_id=report_id,
                operation_id=request.operation_id,
                old_snapshot_id=old_receipt.snapshot_id,
                new_snapshot_id=new_receipt.snapshot_id,
                old_source_hash=old_receipt.source_state_sha256,
                new_source_hash=new_receipt.source_state_sha256,
                old_composition_hash=old_receipt.composition_sha256,
                new_composition_hash=new_receipt.composition_sha256,
                changes=changes,
                requested_operation_ids=requested_operation_ids,
                reason_codes=reasons,
            )
            await _write_recheck_events(
                conn,
                workspace_id=request.workspace_id,
                project_id=request.project_id,
                project_run_id=UUID(str(old_receipt.project_run_id)),
                subject_entity_id=UUID(str(old_receipt.subject.entity_id)),
                old_snapshot_id=old_receipt.snapshot_id,
                new_snapshot_id=new_receipt.snapshot_id,
                report=report,
                changes=changes,
                created_at=self._clock(),
                subject_activity_appender=self._subject_activity_appender,
            )
            await self._crash_hook("before_report_commit")
            return report

    async def get_report(
        self,
        *,
        workspace_id: str,
        report_id: ResearchViewChangeReportId,
    ) -> ResearchViewChangeReportRef | None:
        """Resolve a body-free fetch reference under its exact workspace scope."""

        async with self._conn_factory() as conn:
            operation_id = (
                await conn.execute(
                    text(
                        """
                        SELECT operation_id
                        FROM research_view_change_report
                        WHERE workspace_id = :workspace_id AND report_id = :report_id
                        """
                    ),
                    {
                        "workspace_id": workspace_id,
                        "report_id": str(report_id),
                    },
                )
            ).scalar_one_or_none()
            if operation_id is None:
                return None
            stored = await _report_for_operation(
                conn,
                workspace_id=workspace_id,
                operation_id=OperationId(UUID(str(operation_id))),
            )
            return stored.report if stored is not None else None

    async def _existing(
        self,
        workspace_id: str,
        operation_id: OperationId,
    ) -> _StoredReport | None:
        async with self._conn_factory() as conn:
            return await _report_for_operation(
                conn,
                workspace_id=workspace_id,
                operation_id=operation_id,
            )


class ResearchViewSectionStalenessService:
    """Append body-free reverse-reference invalidations without rebuilding a view."""

    def __init__(
        self,
        *,
        subject_activity_appender: SubjectActivityAppender | None = None,
        conn_factory: ConnFactory = transaction,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._conn_factory = conn_factory
        self._subject_activity_appender = subject_activity_appender
        self._clock = clock or (lambda: datetime.now(UTC))

    async def mark_claims_changed(
        self,
        *,
        workspace_id: str,
        operation_id: OperationId,
        claim_ids: tuple[UUID, ...],
        reason_code: str,
    ) -> tuple[UUID, ...]:
        if not claim_ids:
            return ()
        if re.fullmatch(r"[a-z][a-z0-9_]{0,79}", reason_code) is None:
            raise ValueError("reason_code must be a bounded machine code")
        created_at = self._clock()
        async with self._conn_factory() as conn:
            rows = await _sections_reached_by_claims(
                conn,
                workspace_id=workspace_id,
                claim_ids=tuple(sorted(set(claim_ids), key=str)),
            )
            ids: list[UUID] = []
            event_groups: dict[UUID, list[Row[Any]]] = {}
            for row in rows:
                staleness_id = uuid5(
                    _STALENESS_NAMESPACE,
                    ":".join(
                        (
                            workspace_id,
                            str(operation_id),
                            str(row[0]),
                            str(row[1]),
                            str(row[3]),
                            reason_code,
                        )
                    ),
                )
                await conn.execute(
                    text(
                        """
                        INSERT INTO research_view_section_staleness (
                            staleness_id, operation_id, workspace_id, snapshot_id,
                            section_ordinal, section_id, claim_id, reason_code, created_at
                        ) VALUES (
                            :staleness_id, :operation_id, :workspace_id, :snapshot_id,
                            :section_ordinal, :section_id, :claim_id, :reason_code, :created_at
                        )
                        ON CONFLICT (
                            workspace_id, operation_id, snapshot_id,
                            section_ordinal, claim_id, reason_code
                        ) DO NOTHING
                        RETURNING staleness_id
                        """
                    ),
                    {
                        "staleness_id": str(staleness_id),
                        "operation_id": str(operation_id),
                        "workspace_id": workspace_id,
                        "snapshot_id": str(row[0]),
                        "section_ordinal": row[1],
                        "section_id": row[2],
                        "claim_id": str(row[3]),
                        "reason_code": reason_code,
                        "created_at": created_at,
                    },
                )
                ids.append(staleness_id)
                event_groups.setdefault(UUID(str(row[0])), []).append(row)

            for snapshot_id, group in event_groups.items():
                first = group[0]
                section_ids = tuple(dict.fromkeys(str(item[2]) for item in group))
                item_ids = tuple(
                    dict.fromkeys(str(item[4]) for item in group if item[4] is not None)
                )
                await append_research_view_event(
                    conn,
                    event_key=f"section-stale:{operation_id}:{snapshot_id}",
                    topic="research_view.section_stale",
                    workspace_id=workspace_id,
                    project_id=str(first[5]),
                    project_run_id=UUID(str(first[6])),
                    subject_entity_id=UUID(str(first[7])),
                    snapshot_id=ResearchViewSnapshotId(snapshot_id),
                    report_id=None,
                    section_ids=section_ids,
                    item_ids=item_ids,
                    reason_codes=(reason_code,),
                    fetch_ref=f"research-view-snapshot:{snapshot_id}",
                    created_at=created_at,
                    subject_activity_appender=self._subject_activity_appender,
                )
            return tuple(ids)


async def _selected_field_keys(
    conn: AsyncConnection,
    *,
    snapshot_id: ResearchViewSnapshotId,
    section_kinds: tuple[ResearchSectionKind, ...],
) -> tuple[str, ...]:
    rows = (
        await conn.execute(
            text(
                """
                SELECT DISTINCT i.field_key
                FROM research_view_snapshot_item i
                JOIN research_view_snapshot_section s
                  ON s.snapshot_id = i.snapshot_id
                 AND s.ordinal = i.section_ordinal
                WHERE i.snapshot_id = :snapshot_id
                  AND i.field_key IS NOT NULL
                  AND (
                    CAST(:all_sections AS boolean)
                    OR s.section_kind = ANY(CAST(:section_kinds AS text[]))
                  )
                ORDER BY i.field_key
                """
            ),
            {
                "snapshot_id": str(snapshot_id),
                "all_sections": not section_kinds,
                "section_kinds": [item.value for item in section_kinds],
            },
        )
    ).all()
    return tuple(str(row[0]) for row in rows)


async def _snapshot_items(
    conn: AsyncConnection,
    snapshot_id: ResearchViewSnapshotId,
    *,
    workspace_id: str,
) -> tuple[_SnapshotItem, ...]:
    rows = (
        await conn.execute(
            text(
                """
                SELECT i.item_id, i.statement_id, s.section_id, s.section_kind,
                       i.claim_id, i.availability, i.freshness, i.display_decision,
                       CASE
                           WHEN i.claim_id IS NULL THEN NULL
                           WHEN d.erased_claim_id IS NOT NULL THEN 'redacted'
                           WHEN c.id IS NULL OR c.superseded_by IS NOT NULL THEN 'unavailable'
                           WHEN EXISTS (
                               SELECT 1
                               FROM research_view_snapshot_support rs
                               LEFT JOIN claim support_claim ON support_claim.id = rs.claim_id
                               LEFT JOIN dsar_tombstone support_tombstone
                                 ON support_tombstone.erased_claim_id = rs.claim_id
                                AND support_tombstone.workspace_id = :workspace_id
                               WHERE rs.snapshot_id = i.snapshot_id
                                 AND rs.section_ordinal = i.section_ordinal
                                 AND rs.item_ordinal = i.ordinal
                                 AND (
                                     support_tombstone.erased_claim_id IS NOT NULL
                                     OR support_claim.id IS NULL
                                     OR support_claim.superseded_by IS NOT NULL
                                 )
                           ) THEN 'unavailable'
                           ELSE NULL
                       END AS current_missing_state
                FROM research_view_snapshot_item i
                JOIN research_view_snapshot_section s
                  ON s.snapshot_id = i.snapshot_id
                 AND s.ordinal = i.section_ordinal
                LEFT JOIN claim c ON c.id = i.claim_id
                LEFT JOIN dsar_tombstone d
                  ON d.erased_claim_id = i.claim_id
                 AND d.workspace_id = :workspace_id
                WHERE i.snapshot_id = :snapshot_id
                ORDER BY s.ordinal, i.ordinal
                """
            ),
            {
                "snapshot_id": str(snapshot_id),
                "workspace_id": workspace_id,
            },
        )
    ).all()
    return tuple(
        _SnapshotItem(
            item_id=str(row[0]),
            statement_id=UUID(str(row[1])) if row[1] is not None else None,
            section_id=str(row[2]),
            section_kind=ResearchSectionKind(str(row[3])),
            claim_id=UUID(str(row[4])) if row[4] is not None else None,
            availability=str(row[5]) if row[5] is not None else None,
            freshness=str(row[6]) if row[6] is not None else None,
            display_decision=str(row[7]) if row[7] is not None else None,
            current_missing_state=str(row[8]) if row[8] is not None else None,
        )
        for row in rows
    )


def _report_ref(
    *,
    report_id: ResearchViewChangeReportId,
    operation_id: OperationId,
    old_snapshot_id: ResearchViewSnapshotId,
    new_snapshot_id: ResearchViewSnapshotId,
    old_source_hash: str,
    new_source_hash: str,
    old_composition_hash: str,
    new_composition_hash: str,
    changes: tuple[_ChangeItem, ...],
    requested_operation_ids: tuple[OperationId, ...],
    reason_codes: tuple[str, ...],
) -> ResearchViewChangeReportRef:
    by_kind = {
        kind: tuple(
            ResearchStatementId(item.statement_id)
            for item in changes
            if item.kind == kind and item.statement_id is not None
        )
        for kind in _CHANGE_KINDS
    }
    return ResearchViewChangeReportRef(
        report_id=report_id,
        operation_id=operation_id,
        old_snapshot_id=old_snapshot_id,
        new_snapshot_id=new_snapshot_id,
        old_source_state_sha256=old_source_hash,
        new_source_state_sha256=new_source_hash,
        old_composition_sha256=old_composition_hash,
        new_composition_sha256=new_composition_hash,
        unchanged_statement_ids=by_kind["unchanged"],
        added_statement_ids=by_kind["added"],
        removed_statement_ids=by_kind["removed"],
        stale_statement_ids=by_kind["stale"],
        restricted_statement_ids=by_kind["restricted"],
        requested_operation_ids=requested_operation_ids,
        reason_codes=reason_codes,
        fetch_ref=f"research-view-change-report:{report_id}",
    )


async def _report_for_operation(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    operation_id: OperationId,
) -> _StoredReport | None:
    row = (
        await conn.execute(
            text(
                """
                SELECT report_id, operation_id, workspace_id, project_id, subject_entity_id,
                       old_snapshot_id, new_snapshot_id,
                       old_source_state_sha256, new_source_state_sha256,
                       old_composition_sha256, new_composition_sha256,
                       selected_section_kinds, request_research, reason_codes
                FROM research_view_change_report
                WHERE workspace_id = :workspace_id AND operation_id = :operation_id
                """
            ),
            {"workspace_id": workspace_id, "operation_id": str(operation_id)},
        )
    ).first()
    if row is None:
        return None
    item_rows = (
        await conn.execute(
            text(
                """
                SELECT statement_id, change_kind
                FROM research_view_change_item
                WHERE report_id = :report_id AND statement_id IS NOT NULL
                ORDER BY item_id
                """
            ),
            {"report_id": str(row[0])},
        )
    ).all()
    operation_rows = (
        await conn.execute(
            text(
                """
                SELECT requested_operation_id
                FROM research_view_change_operation
                WHERE report_id = :report_id
                ORDER BY ordinal
                """
            ),
            {"report_id": str(row[0])},
        )
    ).all()
    changes = tuple(
        _ChangeItem(
            item_id=str(item[0]),
            statement_id=UUID(str(item[0])),
            section_id="persisted",
            kind=str(item[1]),
        )
        for item in item_rows
    )
    report_id = ResearchViewChangeReportId(UUID(str(row[0])))
    report = _report_ref(
        report_id=report_id,
        operation_id=OperationId(UUID(str(row[1]))),
        old_snapshot_id=ResearchViewSnapshotId(UUID(str(row[5]))),
        new_snapshot_id=ResearchViewSnapshotId(UUID(str(row[6]))),
        old_source_hash=str(row[7]),
        new_source_hash=str(row[8]),
        old_composition_hash=str(row[9]),
        new_composition_hash=str(row[10]),
        changes=changes,
        requested_operation_ids=tuple(OperationId(UUID(str(item[0]))) for item in operation_rows),
        reason_codes=tuple(row[13]),
    )
    return _StoredReport(
        report=report,
        workspace_id=str(row[2]),
        project_id=str(row[3]),
        subject_entity_id=UUID(str(row[4])),
        selected_section_kinds=tuple(ResearchSectionKind(str(item)) for item in row[11]),
        request_research=bool(row[12]),
    )


def _require_matching_recheck(
    stored: _StoredReport,
    request: ResearchViewRecheckRequest,
) -> None:
    if (
        stored.workspace_id != request.workspace_id
        or stored.project_id != request.project_id
        or stored.subject_entity_id != UUID(str(request.subject_entity_id))
        or stored.report.old_snapshot_id != request.snapshot_id
        or stored.selected_section_kinds != request.section_kinds
        or stored.request_research != request.request_research
    ):
        raise ResearchViewRecheckConflict(
            "operation_id was already used for a different re-check scope"
        )


async def _write_recheck_events(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    project_id: str,
    project_run_id: UUID,
    subject_entity_id: UUID,
    old_snapshot_id: ResearchViewSnapshotId,
    new_snapshot_id: ResearchViewSnapshotId,
    report: ResearchViewChangeReportRef,
    changes: tuple[_ChangeItem, ...],
    created_at: datetime,
    subject_activity_appender: SubjectActivityAppender | None,
) -> None:
    affected = tuple(item for item in changes if item.kind != "unchanged")
    section_ids = tuple(dict.fromkeys(item.section_id for item in affected))
    item_ids = tuple(item.item_id for item in affected)
    if affected:
        await append_research_view_event(
            conn,
            event_key=f"recheck:{report.report_id}:stale",
            topic="research_view.section_stale",
            workspace_id=workspace_id,
            project_id=project_id,
            project_run_id=ProjectRunId(project_run_id),
            subject_entity_id=subject_entity_id,
            snapshot_id=old_snapshot_id,
            report_id=report.report_id,
            section_ids=section_ids,
            item_ids=item_ids,
            reason_codes=report.reason_codes,
            fetch_ref=f"research-view-snapshot:{old_snapshot_id}",
            created_at=created_at,
            subject_activity_appender=subject_activity_appender,
        )
        await append_research_view_event(
            conn,
            event_key=f"recheck:{report.report_id}:updated",
            topic="research_view.updated",
            workspace_id=workspace_id,
            project_id=project_id,
            project_run_id=ProjectRunId(project_run_id),
            subject_entity_id=subject_entity_id,
            snapshot_id=new_snapshot_id,
            report_id=report.report_id,
            section_ids=section_ids,
            item_ids=item_ids,
            reason_codes=report.reason_codes,
            fetch_ref=f"research-view-snapshot:{new_snapshot_id}",
            created_at=created_at,
            subject_activity_appender=subject_activity_appender,
        )
    await append_research_view_event(
        conn,
        event_key=f"recheck:{report.report_id}:completed",
        topic="research_view.recheck_completed",
        workspace_id=workspace_id,
        project_id=project_id,
        project_run_id=project_run_id,
        subject_entity_id=subject_entity_id,
        snapshot_id=new_snapshot_id,
        report_id=report.report_id,
        section_ids=section_ids,
        item_ids=item_ids,
        reason_codes=report.reason_codes,
        fetch_ref=report.fetch_ref,
        created_at=created_at,
        subject_activity_appender=subject_activity_appender,
    )


async def append_research_view_event(
    conn: AsyncConnection,
    *,
    event_key: str,
    topic: str,
    workspace_id: str,
    project_id: str,
    project_run_id: UUID,
    subject_entity_id: UUID,
    snapshot_id: ResearchViewSnapshotId,
    report_id: ResearchViewChangeReportId | None,
    section_ids: tuple[str, ...],
    item_ids: tuple[str, ...],
    reason_codes: tuple[str, ...],
    fetch_ref: str,
    created_at: datetime,
    subject_activity_appender: SubjectActivityAppender | None = None,
) -> None:
    """Append one idempotent scope/ref/reason event; arbitrary body fields are impossible."""
    event_id = uuid5(_EVENT_NAMESPACE, f"{workspace_id}:{event_key}")
    await conn.execute(
        text(
            """
            INSERT INTO research_view_event (
                event_id, event_key, topic, workspace_id, project_id, project_run_id,
                subject_entity_id, snapshot_id, report_id, section_ids, item_ids,
                reason_codes, fetch_ref, created_at
            ) VALUES (
                :event_id, :event_key, :topic, :workspace_id, :project_id, :project_run_id,
                :subject_entity_id, :snapshot_id, :report_id, :section_ids, :item_ids,
                :reason_codes, :fetch_ref, :created_at
            )
            ON CONFLICT (workspace_id, event_key) DO NOTHING
            """
        ),
        {
            "event_id": str(event_id),
            "event_key": event_key,
            "topic": topic,
            "workspace_id": workspace_id,
            "project_id": project_id,
            "project_run_id": str(project_run_id),
            "subject_entity_id": str(subject_entity_id),
            "snapshot_id": str(snapshot_id),
            "report_id": str(report_id) if report_id is not None else None,
            "section_ids": list(section_ids),
            "item_ids": list(item_ids),
            "reason_codes": list(reason_codes),
            "fetch_ref": fetch_ref,
            "created_at": created_at,
        },
    )
    if subject_activity_appender is None:
        return
    scope_rows = (
        await conn.execute(
            text(
                """
                SELECT snapshot.subject_entity_type, snapshot.product_id, account_run.id
                FROM research_view_snapshot snapshot
                LEFT JOIN contact_entity contact
                  ON snapshot.subject_entity_type = 'contact'
                 AND contact.id = snapshot.subject_entity_id
                 AND contact.workspace_id = snapshot.workspace_id
                JOIN account_run
                  ON account_run.project_run_id = snapshot.project_run_id
                 AND account_run.entity_id = CASE
                     WHEN snapshot.subject_entity_type = 'contact'
                     THEN contact.account_entity_id
                     ELSE snapshot.subject_entity_id
                 END
                WHERE snapshot.snapshot_id = :snapshot_id
                  AND snapshot.workspace_id = :workspace_id
                  AND snapshot.project_id = :project_id
                  AND snapshot.project_run_id = :project_run_id
                  AND snapshot.subject_entity_id = :subject_entity_id
                """
            ),
            {
                "snapshot_id": snapshot_id,
                "workspace_id": workspace_id,
                "project_id": project_id,
                "project_run_id": project_run_id,
                "subject_entity_id": subject_entity_id,
            },
        )
    ).all()
    if len(scope_rows) == 1:
        subject_type, product_id, account_run_id = scope_rows[0]
        await subject_activity_appender(
            conn,
            workspace_id=workspace_id,
            project_id=project_id,
            project_run_id=ProjectRunId(project_run_id),
            account_run_id=RunId(account_run_id),
            subject_entity_id=EntityId(subject_entity_id),
            subject_entity_type=EntityType(str(subject_type)),
            product_id=product_id,
            owner_event_ref=f"research-view-event:{event_id}",
            event_kind=topic,
            actor_category="system",
            occurred_at=created_at,
        )


async def _sections_reached_by_claims(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    claim_ids: tuple[UUID, ...],
) -> tuple[Row[Any], ...]:
    return tuple(
        (
            await conn.execute(
                text(
                    """
                    WITH reached AS (
                        SELECT i.snapshot_id, i.section_ordinal, i.item_id, i.claim_id
                        FROM research_view_snapshot_item i
                        WHERE i.claim_id = ANY(CAST(:claim_ids AS uuid[]))
                        UNION
                        SELECT s.snapshot_id, s.section_ordinal, i.item_id, s.claim_id
                        FROM research_view_snapshot_support s
                        JOIN research_view_snapshot_item i
                          ON i.snapshot_id = s.snapshot_id
                         AND i.section_ordinal = s.section_ordinal
                         AND i.ordinal = s.item_ordinal
                        WHERE s.claim_id = ANY(CAST(:claim_ids AS uuid[]))
                    )
                    SELECT r.snapshot_id, r.section_ordinal, ss.section_id, r.claim_id,
                           r.item_id, snap.project_id, snap.project_run_id,
                           snap.subject_entity_id
                    FROM reached r
                    JOIN research_view_snapshot snap ON snap.snapshot_id = r.snapshot_id
                    JOIN research_view_snapshot_section ss
                      ON ss.snapshot_id = r.snapshot_id
                     AND ss.ordinal = r.section_ordinal
                    WHERE snap.workspace_id = :workspace_id
                    ORDER BY r.snapshot_id, r.section_ordinal, r.claim_id, r.item_id
                    """
                ),
                {
                    "workspace_id": workspace_id,
                    "claim_ids": [str(item) for item in claim_ids],
                },
            )
        ).all()
    )
