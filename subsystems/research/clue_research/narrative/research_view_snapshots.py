"""C7.4 reference-only saved research views.

A saved view is an append-only receipt over the C7.3 live composer.  It stores the exact scope,
ordering, claim/owner references, bounded policy state, and hashes required to replay the
composition, but never stores a claim value, source locator, evidence body, rationale, or rendered
document.  Resolving a receipt always calls the live composer again, so supersession, erasure,
freshness, and current display policy remain authoritative.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol, cast, runtime_checkable
from uuid import NAMESPACE_URL, UUID, uuid5

from pydantic import BaseModel, ConfigDict, JsonValue
from sqlalchemy import text
from sqlalchemy.engine import Row
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_core import (
    AccountResearchView,
    ContactResearchView,
    EntityType,
    OperationId,
    ResearchAvailability,
    ResearchOwnedReference,
    ResearchPersonalizationItem,
    ResearchSection,
    ResearchStatement,
    ResearchSubjectRef,
    ResearchView,
    ResearchViewComposer,
    ResearchViewId,
    ResearchViewReadRequest,
    ResearchViewReceipt,
    ResearchViewSnapshotId,
    canonical_json,
)
from clue_db import ConnFactory, transaction
from clue_research.narrative.research_views import (
    _VIEW_NAMESPACE,
    _provenance_index,
    _source_state_sha256,
    _status_summary,
)

_SNAPSHOT_NAMESPACE = uuid5(NAMESPACE_URL, "clue-hq:c7:research-view-snapshot:1.0")


class ResearchViewSnapshotConflict(ValueError):
    """An operation id was replayed with a different scope or a composer escaped its request."""


class ResearchViewSnapshotCommand(BaseModel):
    """Idempotent compose-and-save command; ``operation_id`` is the retry identity."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    operation_id: OperationId
    request: ResearchViewReadRequest
    supersedes_snapshot_id: ResearchViewSnapshotId | None = None


@dataclass(frozen=True)
class _SavedItem:
    item_id: str
    claim_id: UUID | None
    missing_state: ResearchAvailability


@dataclass(frozen=True)
class _SavedSection:
    section_id: str
    availability: ResearchAvailability
    reason_codes: tuple[str, ...]
    items: tuple[_SavedItem, ...]


@dataclass(frozen=True)
class _ReplayPlan:
    request: ResearchViewReadRequest
    sections: tuple[_SavedSection, ...]


@runtime_checkable
class SnapshotReachabilityReader(Protocol):
    """Resolve subjects reached through claim/support ids without copying their bodies."""

    async def subjects_for_claims(
        self,
        *,
        workspace_id: str,
        claim_ids: tuple[UUID, ...],
    ) -> tuple[ResearchSubjectRef, ...]: ...


def _statement(item: object) -> ResearchStatement | None:
    if isinstance(item, ResearchStatement):
        return item
    if isinstance(item, ResearchPersonalizationItem):
        return item.statement
    return None


def _item_id(item: object) -> str:
    statement = _statement(item)
    if isinstance(item, ResearchPersonalizationItem):
        return str(item.item_id)
    if statement is not None:
        return str(statement.statement_id)
    if isinstance(item, ResearchOwnedReference):
        return str(item.item_id)
    raise TypeError("unexpected research-view item")


def _reference_manifest(view: ResearchView) -> dict[str, object]:
    """Return the body-free canonical structure whose hash is the receipt composition hash."""

    sections: list[dict[str, object]] = []
    for section_ordinal, section in enumerate(view.sections):
        items: list[dict[str, object]] = []
        for item_ordinal, item in enumerate(section.items):
            statement = _statement(item)
            if statement is not None:
                items.append(
                    {
                        "ordinal": item_ordinal,
                        "item_id": _item_id(item),
                        "item_kind": item.item_kind,
                        "statement_id": str(statement.statement_id),
                        "claim_id": str(statement.claim_id),
                        "statement_kind": statement.statement_kind.value,
                        "field_key": str(statement.field_key),
                        "subject": statement.subject.model_dump(mode="json"),
                        "product_id": statement.product_id,
                        "state": statement.state.model_dump(mode="json"),
                        "identity_binding": (
                            statement.identity_binding.value
                            if statement.identity_binding is not None
                            else None
                        ),
                        "use_class": (
                            statement.use_class.value if statement.use_class is not None else None
                        ),
                        "selection_reason_code": (
                            item.selection_reason_code
                            if isinstance(item, ResearchPersonalizationItem)
                            else None
                        ),
                        "supports": [
                            support.model_dump(mode="json") for support in statement.supports
                        ],
                        "evidence_actions": [
                            action.model_dump(mode="json") for action in statement.evidence_actions
                        ],
                    }
                )
                continue
            if not isinstance(item, ResearchOwnedReference):
                raise TypeError("unexpected research-view item")
            items.append(
                {
                    "ordinal": item_ordinal,
                    "item_id": str(item.item_id),
                    "item_kind": item.item_kind,
                    "owner_ref": str(item.owner_ref),
                    "data_species": item.data_species.value,
                    "relation": item.relation.value,
                    "subject": item.subject.model_dump(mode="json"),
                    "product_id": item.product_id,
                    "evidence_claim_ids": [str(value) for value in item.evidence_claim_ids],
                }
            )
        sections.append(
            {
                "ordinal": section_ordinal,
                "section_id": section.section_id,
                "section_kind": section.kind.value,
                "block_kind": section.block_kind.value if section.block_kind is not None else None,
                "availability": section.availability.value,
                "reason_codes": list(section.reason_codes),
                "items": items,
            }
        )
    return {
        "schema_version": view.schema_version,
        "view_id": str(view.view_id),
        "workspace_id": view.workspace_id,
        "project_id": view.project_id,
        "project_run_id": str(view.project_run_id),
        "subject": view.subject.model_dump(mode="json"),
        "product_id": view.product_id,
        "source_state_sha256": view.source_state_sha256,
        "sections": sections,
    }


def reference_composition_sha256(view: ResearchView) -> str:
    """Hash only the canonical reference manifest, never research/evidence bodies."""

    return hashlib.sha256(
        canonical_json(cast(JsonValue, _reference_manifest(view))).encode("utf-8")
    ).hexdigest()


class ResearchViewSnapshotService:
    """Compose, persist, and replay reference-only C7 research-view receipts."""

    def __init__(
        self,
        composer: ResearchViewComposer,
        reachability: SnapshotReachabilityReader,
        *,
        conn_factory: ConnFactory = transaction,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._composer = composer
        self._reachability = reachability
        self._conn_factory = conn_factory
        self._clock = clock or (lambda: datetime.now(UTC))

    async def compose_and_save(self, command: ResearchViewSnapshotCommand) -> ResearchViewReceipt:
        """Compose once per operation id and atomically save its body-free ordered receipt."""

        async with self._conn_factory() as conn:
            existing = await _receipt_for_operation(
                conn,
                workspace_id=command.request.workspace_id,
                operation_id=command.operation_id,
            )
        if existing is not None:
            _require_matching_request(existing, command.request)
            return existing

        view = await self._composer.compose(command.request)
        _require_matching_view(view, command.request)
        manifest_hash = reference_composition_sha256(view)
        snapshot_id = ResearchViewSnapshotId(
            uuid5(
                _SNAPSHOT_NAMESPACE,
                f"{command.request.workspace_id}:{command.operation_id}",
            )
        )
        created_at = self._clock()

        claim_ids = {UUID(str(reference.claim_id)) for reference in view.provenance_index}
        for section in view.sections:
            for item in section.items:
                if isinstance(item, ResearchOwnedReference):
                    claim_ids.update(UUID(str(value)) for value in item.evidence_claim_ids)
                statement = _statement(item)
                if statement is not None:
                    claim_ids.update(UUID(str(value.claim_id)) for value in statement.supports)
        reached = await self._reachability.subjects_for_claims(
            workspace_id=view.workspace_id,
            claim_ids=tuple(sorted(claim_ids, key=str)),
        )

        async with self._conn_factory() as conn:
            inserted = await conn.execute(
                text(
                    """
                    INSERT INTO research_view_snapshot (
                        snapshot_id, operation_id, workspace_id, project_id, project_run_id,
                        view_id, subject_entity_id, subject_entity_type, subject_entity_version,
                        parent_account_entity_id, product_id, schema_version, source_state_sha256,
                        composition_sha256, supersedes_snapshot_id, created_at
                    )
                    VALUES (
                        :snapshot_id, :operation_id, :workspace_id, :project_id, :project_run_id,
                        :view_id, :subject_entity_id, :subject_entity_type,
                        :subject_entity_version, :parent_account_entity_id, :product_id,
                        :schema_version, :source_state_sha256, :composition_sha256,
                        :supersedes_snapshot_id, :created_at
                    )
                    ON CONFLICT (workspace_id, operation_id) DO NOTHING
                    RETURNING snapshot_id
                    """
                ),
                {
                    "snapshot_id": str(snapshot_id),
                    "operation_id": str(command.operation_id),
                    "workspace_id": view.workspace_id,
                    "project_id": view.project_id,
                    "project_run_id": str(view.project_run_id),
                    "view_id": str(view.view_id),
                    "subject_entity_id": str(view.subject.entity_id),
                    "subject_entity_type": view.subject.entity_type.value,
                    "subject_entity_version": view.subject.canonical_entity_version,
                    "parent_account_entity_id": (
                        str(view.subject.parent_account_id)
                        if view.subject.parent_account_id is not None
                        else None
                    ),
                    "product_id": view.product_id,
                    "schema_version": view.schema_version,
                    "source_state_sha256": view.source_state_sha256,
                    "composition_sha256": manifest_hash,
                    "supersedes_snapshot_id": (
                        str(command.supersedes_snapshot_id)
                        if command.supersedes_snapshot_id is not None
                        else None
                    ),
                    "created_at": created_at,
                },
            )
            if inserted.first() is None:
                receipt = await _receipt_for_operation(
                    conn,
                    workspace_id=view.workspace_id,
                    operation_id=command.operation_id,
                )
                if receipt is None:  # pragma: no cover - defensive against a broken transaction
                    raise RuntimeError("snapshot idempotency conflict did not resolve a receipt")
                _require_matching_request(receipt, command.request)
                return receipt

            await _write_sections(conn, snapshot_id=snapshot_id, view=view)
            subjects: dict[tuple[UUID, str], tuple[ResearchSubjectRef, str]] = {
                (UUID(str(view.subject.entity_id)), "view_subject"): (
                    view.subject,
                    "view_subject",
                )
            }
            for section in view.sections:
                for item in section.items:
                    if isinstance(item, ResearchOwnedReference):
                        subjects[(UUID(str(item.subject.entity_id)), item.relation.value)] = (
                            item.subject,
                            item.relation.value,
                        )
            for subject in reached:
                subjects[(UUID(str(subject.entity_id)), "claim_reachable")] = (
                    subject,
                    "claim_reachable",
                )
            for subject, relation in subjects.values():
                await conn.execute(
                    text(
                        """
                        INSERT INTO research_view_snapshot_subject (
                            snapshot_id, subject_entity_id, subject_entity_type,
                            parent_account_entity_id, relation
                        ) VALUES (
                            :snapshot_id, :subject_entity_id, :subject_entity_type,
                            :parent_account_entity_id, :relation
                        )
                        """
                    ),
                    {
                        "snapshot_id": str(snapshot_id),
                        "subject_entity_id": str(subject.entity_id),
                        "subject_entity_type": subject.entity_type.value,
                        "parent_account_entity_id": (
                            str(subject.parent_account_id)
                            if subject.parent_account_id is not None
                            else None
                        ),
                        "relation": relation,
                    },
                )

        return ResearchViewReceipt(
            snapshot_id=snapshot_id,
            view_id=view.view_id,
            workspace_id=view.workspace_id,
            project_id=view.project_id,
            project_run_id=view.project_run_id,
            subject=view.subject,
            product_id=view.product_id,
            source_state_sha256=view.source_state_sha256,
            composition_sha256=manifest_hash,
            created_at=created_at,
            fetch_ref=f"research-view-snapshot:{snapshot_id}",
        )

    async def resolve(
        self,
        *,
        workspace_id: str,
        snapshot_id: ResearchViewSnapshotId,
    ) -> ResearchView | None:
        """Recompose the saved scope now; no historical value is read from the receipt."""

        async with self._conn_factory() as conn:
            plan = await _replay_plan_for_snapshot(
                conn, workspace_id=workspace_id, snapshot_id=snapshot_id
            )
        if plan is None:
            return None
        current = await self._composer.compose(plan.request)
        _require_matching_view(current, plan.request)
        return _replay_saved_references(current, plan, snapshot_id=snapshot_id)


async def _write_sections(
    conn: AsyncConnection, *, snapshot_id: ResearchViewSnapshotId, view: ResearchView
) -> None:
    for section_ordinal, section in enumerate(view.sections):
        await conn.execute(
            text(
                """
                INSERT INTO research_view_snapshot_section (
                    snapshot_id, ordinal, section_id, section_kind, block_kind,
                    availability, reason_codes
                ) VALUES (
                    :snapshot_id, :ordinal, :section_id, :section_kind, :block_kind,
                    :availability, :reason_codes
                )
                """
            ),
            {
                "snapshot_id": str(snapshot_id),
                "ordinal": section_ordinal,
                "section_id": section.section_id,
                "section_kind": section.kind.value,
                "block_kind": section.block_kind.value if section.block_kind is not None else None,
                "availability": section.availability.value,
                "reason_codes": list(section.reason_codes),
            },
        )
        for item_ordinal, item in enumerate(section.items):
            statement = _statement(item)
            if statement is None and not isinstance(item, ResearchOwnedReference):
                raise TypeError("unexpected research-view item")
            subject = (
                statement.subject
                if statement is not None
                else cast(ResearchOwnedReference, item).subject
            )
            state = statement.state if statement is not None else None
            await conn.execute(
                text(
                    """
                    INSERT INTO research_view_snapshot_item (
                        snapshot_id, section_ordinal, ordinal, item_id, item_kind,
                        statement_id, claim_id, statement_kind, field_key, owner_ref,
                        data_species, relation, item_subject_entity_id,
                        item_subject_entity_type, item_subject_version, item_parent_account_id,
                        item_product_id, availability, verification, freshness, conflict_state,
                        display_decision, outreach_decision, identity_binding, use_class,
                        selection_reason_code, reason_codes
                    ) VALUES (
                        :snapshot_id, :section_ordinal, :ordinal, :item_id, :item_kind,
                        :statement_id, :claim_id, :statement_kind, :field_key, :owner_ref,
                        :data_species, :relation, :item_subject_entity_id,
                        :item_subject_entity_type, :item_subject_version, :item_parent_account_id,
                        :item_product_id, :availability, :verification, :freshness, :conflict_state,
                        :display_decision, :outreach_decision, :identity_binding, :use_class,
                        :selection_reason_code, :reason_codes
                    )
                    """
                ),
                {
                    "snapshot_id": str(snapshot_id),
                    "section_ordinal": section_ordinal,
                    "ordinal": item_ordinal,
                    "item_id": _item_id(item),
                    "item_kind": item.item_kind,
                    "statement_id": (
                        str(statement.statement_id) if statement is not None else None
                    ),
                    "claim_id": str(statement.claim_id) if statement is not None else None,
                    "statement_kind": (
                        statement.statement_kind.value if statement is not None else None
                    ),
                    "field_key": str(statement.field_key) if statement is not None else None,
                    "owner_ref": (
                        str(item.owner_ref) if isinstance(item, ResearchOwnedReference) else None
                    ),
                    "data_species": (
                        item.data_species.value
                        if isinstance(item, ResearchOwnedReference)
                        else None
                    ),
                    "relation": (
                        item.relation.value if isinstance(item, ResearchOwnedReference) else None
                    ),
                    "item_subject_entity_id": str(subject.entity_id),
                    "item_subject_entity_type": subject.entity_type.value,
                    "item_subject_version": subject.canonical_entity_version,
                    "item_parent_account_id": (
                        str(subject.parent_account_id)
                        if subject.parent_account_id is not None
                        else None
                    ),
                    "item_product_id": (
                        statement.product_id
                        if statement is not None
                        else cast(ResearchOwnedReference, item).product_id
                    ),
                    "availability": state.availability.value if state is not None else None,
                    "verification": state.verification.value if state is not None else None,
                    "freshness": state.freshness.value if state is not None else None,
                    "conflict_state": state.conflict.value if state is not None else None,
                    "display_decision": (
                        state.display_decision.value if state is not None else None
                    ),
                    "outreach_decision": (
                        state.outreach_decision.value if state is not None else None
                    ),
                    "identity_binding": (
                        statement.identity_binding.value
                        if statement is not None and statement.identity_binding is not None
                        else None
                    ),
                    "use_class": (
                        statement.use_class.value
                        if statement is not None and statement.use_class is not None
                        else None
                    ),
                    "selection_reason_code": (
                        item.selection_reason_code
                        if isinstance(item, ResearchPersonalizationItem)
                        else None
                    ),
                    "reason_codes": list(state.reason_codes) if state is not None else [],
                },
            )
            if statement is None:
                owner_item = cast(ResearchOwnedReference, item)
                for ordinal, claim_id in enumerate(owner_item.evidence_claim_ids):
                    await conn.execute(
                        text(
                            """
                            INSERT INTO research_view_snapshot_support (
                                snapshot_id, section_ordinal, item_ordinal, ordinal,
                                claim_id, reference_kind, support_role, required
                            ) VALUES (
                                :snapshot_id, :section_ordinal, :item_ordinal, :ordinal,
                                :claim_id, 'owner_evidence', NULL, true
                            )
                            """
                        ),
                        {
                            "snapshot_id": str(snapshot_id),
                            "section_ordinal": section_ordinal,
                            "item_ordinal": item_ordinal,
                            "ordinal": ordinal,
                            "claim_id": str(claim_id),
                        },
                    )
                continue
            for support in statement.supports:
                await conn.execute(
                    text(
                        """
                        INSERT INTO research_view_snapshot_support (
                            snapshot_id, section_ordinal, item_ordinal, ordinal,
                            claim_id, reference_kind, support_role, required
                        ) VALUES (
                            :snapshot_id, :section_ordinal, :item_ordinal, :ordinal,
                            :claim_id, 'derived_support', :support_role, :required
                        )
                        """
                    ),
                    {
                        "snapshot_id": str(snapshot_id),
                        "section_ordinal": section_ordinal,
                        "item_ordinal": item_ordinal,
                        "ordinal": support.ordinal,
                        "claim_id": str(support.claim_id),
                        "support_role": support.role.value,
                        "required": support.required,
                    },
                )
            for action_ordinal, action in enumerate(statement.evidence_actions):
                if action.action_id is None:
                    continue
                await conn.execute(
                    text(
                        """
                        INSERT INTO research_view_snapshot_evidence_action (
                            snapshot_id, section_ordinal, item_ordinal, ordinal, action_id,
                            statement_id, claim_id, action_kind, provider_label, media_type
                        ) VALUES (
                            :snapshot_id, :section_ordinal, :item_ordinal, :ordinal, :action_id,
                            :statement_id, :claim_id, :action_kind, :provider_label, :media_type
                        )
                        """
                    ),
                    {
                        "snapshot_id": str(snapshot_id),
                        "section_ordinal": section_ordinal,
                        "item_ordinal": item_ordinal,
                        "ordinal": action_ordinal,
                        "action_id": str(action.action_id),
                        "statement_id": str(statement.statement_id),
                        "claim_id": str(statement.claim_id),
                        "action_kind": action.kind.value,
                        "provider_label": action.provider_label,
                        "media_type": action.media_type,
                    },
                )


async def _receipt_for_operation(
    conn: AsyncConnection, *, workspace_id: str, operation_id: OperationId
) -> ResearchViewReceipt | None:
    row = (
        await conn.execute(
            text(
                """
                SELECT snapshot_id, view_id, workspace_id, project_id, project_run_id,
                       subject_entity_id, subject_entity_type, subject_entity_version,
                       parent_account_entity_id, product_id, schema_version,
                       source_state_sha256, composition_sha256, created_at
                FROM research_view_snapshot
                WHERE workspace_id = :workspace_id AND operation_id = :operation_id
                """
            ),
            {"workspace_id": workspace_id, "operation_id": str(operation_id)},
        )
    ).first()
    return _receipt_from_row(row) if row is not None else None


def _receipt_from_row(row: Row[Any]) -> ResearchViewReceipt:
    subject = ResearchSubjectRef(
        entity_id=row[5],
        entity_type=EntityType(row[6]),
        canonical_entity_version=row[7],
        parent_account_id=row[8],
    )
    return ResearchViewReceipt(
        snapshot_id=row[0],
        view_id=row[1],
        workspace_id=row[2],
        project_id=row[3],
        project_run_id=row[4],
        subject=subject,
        product_id=row[9],
        schema_version=row[10],
        source_state_sha256=row[11],
        composition_sha256=row[12],
        created_at=row[13],
        fetch_ref=f"research-view-snapshot:{row[0]}",
    )


async def _replay_plan_for_snapshot(
    conn: AsyncConnection, *, workspace_id: str, snapshot_id: ResearchViewSnapshotId
) -> _ReplayPlan | None:
    row = (
        await conn.execute(
            text(
                """
                SELECT workspace_id, project_id, project_run_id, subject_entity_id,
                       product_id, schema_version
                FROM research_view_snapshot
                WHERE workspace_id = :workspace_id AND snapshot_id = :snapshot_id
                """
            ),
            {"workspace_id": workspace_id, "snapshot_id": str(snapshot_id)},
        )
    ).first()
    if row is None:
        return None
    request = ResearchViewReadRequest(
        workspace_id=row[0],
        project_id=row[1],
        project_run_id=row[2],
        subject_entity_id=row[3],
        product_id=row[4],
        schema_version=row[5],
    )
    section_rows = (
        await conn.execute(
            text(
                """
                SELECT ordinal, section_id, availability, reason_codes
                FROM research_view_snapshot_section
                WHERE snapshot_id = :snapshot_id
                ORDER BY ordinal
                """
            ),
            {"snapshot_id": str(snapshot_id)},
        )
    ).all()
    item_rows = (
        await conn.execute(
            text(
                """
                SELECT i.section_ordinal, i.ordinal, i.item_id, i.claim_id,
                       CASE
                           WHEN i.claim_id IS NULL THEN 'unavailable'
                           WHEN d.erased_claim_id IS NOT NULL THEN 'redacted'
                           WHEN c.id IS NULL THEN 'unavailable'
                           WHEN c.superseded_by IS NOT NULL THEN 'unavailable'
                           ELSE 'restricted'
                       END AS missing_state
                FROM research_view_snapshot_item i
                LEFT JOIN claim c ON c.id = i.claim_id
                LEFT JOIN dsar_tombstone d
                  ON d.erased_claim_id = i.claim_id
                 AND d.workspace_id = :workspace_id
                WHERE i.snapshot_id = :snapshot_id
                ORDER BY i.section_ordinal, i.ordinal
                """
            ),
            {"snapshot_id": str(snapshot_id), "workspace_id": workspace_id},
        )
    ).all()
    items_by_section: dict[int, list[_SavedItem]] = {}
    for item in item_rows:
        items_by_section.setdefault(item[0], []).append(
            _SavedItem(
                item_id=item[2],
                claim_id=item[3],
                missing_state=ResearchAvailability(item[4]),
            )
        )
    return _ReplayPlan(
        request=request,
        sections=tuple(
            _SavedSection(
                section_id=section[1],
                availability=ResearchAvailability(section[2]),
                reason_codes=tuple(section[3]),
                items=tuple(items_by_section.get(section[0], ())),
            )
            for section in section_rows
        ),
    )


def _replay_saved_references(
    current: ResearchView,
    plan: _ReplayPlan,
    *,
    snapshot_id: ResearchViewSnapshotId,
) -> ResearchView:
    """Filter a live composition to the receipt's exact ordered refs.

    Current values/policy come only from ``current``. New statements are excluded because they were
    not part of the saved version. A saved ref that current policy no longer returns contributes a
    bounded section reason; no historical body is reconstructed.
    """

    current_sections = {section.section_id: section for section in current.sections}
    replayed_sections: list[ResearchSection] = []
    for saved in plan.sections:
        current_section = current_sections.get(saved.section_id)
        if current_section is None:
            raise ResearchViewSnapshotConflict(
                f"live composer omitted frozen schema section {saved.section_id!r}"
            )
        current_items = {_item_id(item): item for item in current_section.items}
        present = tuple(
            current_items[item.item_id] for item in saved.items if item.item_id in current_items
        )
        missing = tuple(item for item in saved.items if item.item_id not in current_items)
        if present:
            missing_reasons = tuple(
                dict.fromkeys(f"snapshot_reference_{item.missing_state.value}" for item in missing)
            )
            replayed_sections.append(
                current_section.model_copy(
                    update={
                        "availability": ResearchAvailability.AVAILABLE,
                        "reason_codes": missing_reasons,
                        "items": present,
                    }
                )
            )
            continue
        if not saved.items:
            replayed_sections.append(
                current_section.model_copy(
                    update={
                        "availability": saved.availability,
                        "reason_codes": saved.reason_codes,
                        "items": (),
                    }
                )
            )
            continue
        missing_states = {item.missing_state for item in missing}
        if ResearchAvailability.REDACTED in missing_states:
            availability = ResearchAvailability.REDACTED
        elif ResearchAvailability.RESTRICTED in missing_states:
            availability = ResearchAvailability.RESTRICTED
        else:
            availability = ResearchAvailability.UNAVAILABLE
        replayed_sections.append(
            current_section.model_copy(
                update={
                    "availability": availability,
                    "reason_codes": (f"snapshot_reference_{availability.value}",),
                    "items": (),
                }
            )
        )

    sections = tuple(replayed_sections)
    source_hash = _source_state_sha256(
        request=plan.request,
        subject=current.subject,
        sections=sections,
        coverage=current.coverage_summary,
    )
    view_id = ResearchViewId(
        uuid5(
            _VIEW_NAMESPACE,
            ":".join(
                (
                    plan.request.workspace_id,
                    plan.request.project_id,
                    str(plan.request.project_run_id),
                    str(current.subject.entity_id),
                    plan.request.product_id or "-",
                    source_hash,
                )
            ),
        )
    )
    payload = {
        **current.model_dump(mode="python"),
        "view_id": view_id,
        "snapshot_id": snapshot_id,
        "source_state_sha256": source_hash,
        "status_summary": _status_summary(sections),
        "sections": sections,
        "provenance_index": _provenance_index(sections),
    }
    if current.subject.entity_type is EntityType.ACCOUNT:
        return AccountResearchView.model_validate(payload)
    return ContactResearchView.model_validate(payload)


def _require_matching_request(
    receipt: ResearchViewReceipt, request: ResearchViewReadRequest
) -> None:
    if (
        receipt.workspace_id != request.workspace_id
        or receipt.project_id != request.project_id
        or receipt.project_run_id != request.project_run_id
        or receipt.subject.entity_id != request.subject_entity_id
        or receipt.product_id != request.product_id
        or receipt.schema_version != request.schema_version
    ):
        raise ResearchViewSnapshotConflict(
            "operation_id was already used for a different research-view scope"
        )


def _require_matching_view(view: ResearchView, request: ResearchViewReadRequest) -> None:
    if (
        view.workspace_id != request.workspace_id
        or view.project_id != request.project_id
        or view.project_run_id != request.project_run_id
        or view.subject.entity_id != request.subject_entity_id
        or view.product_id != request.product_id
        or view.schema_version != request.schema_version
    ):
        raise ResearchViewSnapshotConflict(
            "live composer returned a research view outside the requested scope"
        )
