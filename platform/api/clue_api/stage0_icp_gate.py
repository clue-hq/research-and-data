"""Pure durable-subject helpers for Stage-0 ICP confirmation gates.

This module intentionally contains no tool or model imports. Both the worker-side gate-opening
tool and the HTTP-side structured answer route use these helpers, so the snapshot bytes presented
to the human and the bytes revalidated immediately before a decision cannot drift.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import cast
from uuid import NAMESPACE_URL, UUID, uuid5

from pydantic import JsonValue
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_api.stage0_project_contracts import (
    DraftIcpSpecRef,
    canonical_subject_sha256,
)
from clue_api.stage0_project_scope import Stage0ProjectScope
from clue_core import ICPSpec, ICPStatus
from clue_research.icp import get_icp_version

__all__ = [
    "IcpGateSubject",
    "IcpGateSubjectError",
    "exact_icp_gate_subject",
    "icp_confirmation_gate_id",
    "icp_spec_subject_ref",
    "icp_spec_subject_snapshot",
]

_GATE_NAMESPACE = uuid5(NAMESPACE_URL, "clue:stage0:icp-confirmation-gate")


class IcpGateSubjectError(ValueError):
    """The requested ICP version is not an answerable draft in this project lineage."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True, slots=True)
class IcpGateSubject:
    spec: ICPSpec
    ref: DraftIcpSpecRef
    subject_ref: str
    snapshot: dict[str, JsonValue]
    sha256: str


def icp_spec_subject_ref(ref: DraftIcpSpecRef) -> str:
    """The stable human/audit label for one composite ``icp_spec`` primary key."""

    return f"icp-spec:{ref.workspace_id}:{ref.icp_key}:v{ref.icp_version}"


def icp_spec_subject_snapshot(spec: ICPSpec) -> dict[str, JsonValue]:
    """Canonicalize every persisted field whose authority approval activates.

    Status is intentionally included. A gate over a draft cannot be answered after some other act
    has already activated or archived that version; the answer route detects that state change as
    subject staleness instead of applying a second interpretation to the old card.
    """

    return cast(dict[str, JsonValue], spec.model_dump(mode="json"))


def icp_confirmation_gate_id(
    *,
    workspace_id: str,
    project_id: str,
    subject_ref: str,
    expected_subject_sha256: str,
) -> UUID:
    """Derive the single gate identity for one exact project-scoped ICP snapshot.

    The presenting turn is deliberately not identity. A fleet retry or a later model round in the
    same thread must rediscover the first immutable gate, not create a second authority object over
    the same draft. The database carries the matching conditional unique index as a backstop for
    callers that do not use this helper.
    """

    framed = "".join(
        f"{len(part)}:{part}"
        for part in (workspace_id, project_id, subject_ref, expected_subject_sha256)
    )
    return uuid5(_GATE_NAMESPACE, framed)


async def exact_icp_gate_subject(
    conn: AsyncConnection,
    *,
    scope: Stage0ProjectScope,
    icp_key: str,
    icp_version: int,
    require_project_synthesis: bool,
) -> IcpGateSubject:
    """Resolve and revalidate one exact draft under trusted Stage-0 lineage.

    ``require_project_synthesis`` is true when opening a gate: a workspace-level ICP from another
    project must not be pulled into this conversation merely because the model knows its key.
    The answer route passes false because that project binding is already frozen into the immutable
    gate; it still rechecks the spec's product/client/KB lineage and complete snapshot.
    """

    spec = await get_icp_version(conn, scope.workspace_id, icp_key, icp_version)
    if spec is None:
        raise IcpGateSubjectError("icp_spec_not_found", "no such ICP spec in this workspace")
    if spec.status is not ICPStatus.DRAFT:
        raise IcpGateSubjectError(
            "icp_spec_not_draft",
            "only the exact persisted draft may be presented or answered",
        )
    if (
        scope.product_id is None
        or scope.client_entity_id is None
        or scope.client_kb_version is None
        or spec.product_id != scope.product_id
        or spec.client_entity_id != scope.client_entity_id
        or spec.client_kb_version != scope.client_kb_version
    ):
        raise IcpGateSubjectError(
            "icp_spec_lineage_stale",
            "the ICP draft does not match this project's current product and Client-KB lineage",
        )

    ref = DraftIcpSpecRef(
        workspace_id=scope.workspace_id,
        icp_key=spec.icp_key,
        icp_version=spec.version,
        status="draft",
    )
    if require_project_synthesis:
        was_synthesized_here = (
            await conn.execute(
                text(
                    """
                    SELECT EXISTS (
                        SELECT 1
                        FROM stage0_icp_synthesis s
                        CROSS JOIN LATERAL jsonb_array_elements(s.icp_spec_refs) item
                        WHERE s.workspace_id = :workspace_id
                          AND s.project_id = :project_id
                          AND s.product_id = :product_id
                          AND s.client_entity_id = :client_entity_id
                          AND s.client_kb_version = :client_kb_version
                          AND item ->> 'workspace_id' = :workspace_id
                          AND item ->> 'icp_key' = :icp_key
                          AND (item ->> 'icp_version')::int = :icp_version
                          AND item ->> 'status' = 'draft'
                    )
                    """
                ),
                {
                    "workspace_id": scope.workspace_id,
                    "project_id": scope.project_id,
                    "product_id": scope.product_id,
                    "client_entity_id": scope.client_entity_id,
                    "client_kb_version": scope.client_kb_version,
                    "icp_key": spec.icp_key,
                    "icp_version": spec.version,
                },
            )
        ).scalar_one()
        if not was_synthesized_here:
            raise IcpGateSubjectError(
                "icp_spec_not_project_proposal",
                "this draft was not synthesized for the current project",
            )

    snapshot = icp_spec_subject_snapshot(spec)
    return IcpGateSubject(
        spec=spec,
        ref=ref,
        subject_ref=icp_spec_subject_ref(ref),
        snapshot=snapshot,
        sha256=canonical_subject_sha256(snapshot),
    )
