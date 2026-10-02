"""Row models for the memory substrate (Doc M §5) — in-package views over the ``memory`` tables.

These are *implementation* shapes: the outside world sees only the ``clue_core.memory`` seam
types (submissions in, bundles out); nothing may import this package (Rule S1). ``Memory`` is the
full record the write/read/lifecycle engines operate on; ``to_label``/``to_candidate`` project it
onto the seam's label/reconciliation shapes.
"""

from __future__ import annotations

from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field

from clue_core import (
    TRUST_MAX,
    TRUST_MIN,
    MemoryLabel,
    MemoryProvenanceClass,
    MemoryScopeType,
    MemoryStatus,
    MemoryType,
    ReconcileCandidate,
    ScopeRef,
    UtcDatetime,
)

#: Content sentinel written by DSAR tombstoning (the one sanctioned content mutation — erasure
#: is not silent). No personal substring of an erased value survives at rest.
ERASED = "[erased]"


def new_memory_id() -> str:
    return "mem_" + uuid4().hex


class Memory(BaseModel):
    """One ``memory`` row + its claim refs (Doc M §5)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    memory_id: str
    workspace_id: str
    scope_type: MemoryScopeType
    scope_id: str  # canonical scope-instance key (== workspace_id for workspace scope)
    type: MemoryType
    trigger: str
    body: str
    provenance_class: MemoryProvenanceClass
    trust_grade: int = Field(ge=TRUST_MIN, le=TRUST_MAX)
    creating_quote: str | None = None
    status: MemoryStatus
    superseded_by: str | None = None
    confirmation_count: int = Field(default=0, ge=0)
    last_confirmed_at: UtcDatetime | None = None
    cycles_since_confirmed: int = Field(default=0, ge=0)
    subject_entity_id: UUID | None = None
    source_thread_id: str | None = None
    retention_class: str = "standard"
    created_at: UtcDatetime
    claim_refs: tuple[UUID, ...] = ()

    @property
    def scope(self) -> ScopeRef:
        scope_id = None if self.scope_type is MemoryScopeType.WORKSPACE else self.scope_id
        return ScopeRef(scope_type=self.scope_type, scope_id=scope_id)

    def to_label(self) -> MemoryLabel:
        """The full label — everything the consuming agent needs to reconcile advice
        (Doc M §10.4). Claim refs sorted so labels — and bundles — are deterministic."""
        return MemoryLabel(
            scope_type=self.scope_type,
            scope_id=self.scope.scope_id,
            type=self.type,
            trigger=self.trigger,
            provenance_class=self.provenance_class,
            trust_grade=self.trust_grade,
            cycles_since_confirmed=self.cycles_since_confirmed,
            confirmation_count=self.confirmation_count,
            claim_refs=tuple(sorted(self.claim_refs, key=str)),
        )

    def to_candidate(self) -> ReconcileCandidate:
        return ReconcileCandidate(
            memory_id=self.memory_id, body=self.body, trigger=self.trigger, status=self.status
        )
