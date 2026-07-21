"""Scoped-memory seam contracts (Doc M; PB-B3 contract-delta).

The memory substrate (subsystem two) is reachable ONLY through its two seams — every writer
submits through :class:`MemoryWriteSeam`, every consumer receives context through
:class:`ContextAssembly` — and no package may import the implementation (``clue_memory``; Rule S1
plus the agents contract enforce this). These contracts therefore live here in ``core``, the
shared-contracts package, exactly the way ``LLMGateway`` fronts ``clue_gateway``: future writers
(the Phase-C kickoff interview, the content subsystem's distiller, mid-run agents) bind to these
shapes and are handed an implementation at the composition root.

Two species of knowledge, two substrates, never mixed (Doc M §2): **facts are claims** (the CKB);
memory holds only advisory **preferences / behavioral learnings**. A memory references a claim by
id, never duplicates its content — the write seam rejects fact-shaped or personal-claim-quoting
submissions (:class:`MemoryRejected`), and person-adjacent content without a resolved subject is
a malformed proposal (:class:`MemoryPreconditionFailed` — an *error*, unlike the quiet typed
:class:`MemoryDisabled` no-op the kill-switch returns).

Scope vocabulary note (founder rulings 2026-07-17 / 2026-07-21): the third-level scope is
``project`` **from birth** (never ``campaign`` — harness doc §1a), and the ``account`` scope of
Doc M §4 is **deferred**: appending it later (enum member + FK column + CHECK arm) is additive;
until then the write seam rejects it loudly rather than the enum advertising support that does
not exist (PB-B3 §0 ruling 5).
"""

from __future__ import annotations

import hashlib
import json
from enum import StrEnum
from typing import Literal, Protocol, runtime_checkable
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

# --- closed taxonomies (DB CHECKs mirror these; parity-tested) ---------------


class MemoryScopeType(StrEnum):
    """The owning scope of a memory record — the object-spine level it attaches to (Doc M §4).

    A three-level tree, not a chain: ``product`` and ``project`` are siblings (orthogonal axes),
    so "most-specific-wins" is undefined between them — cross-branch tension is surfaced and
    labeled, never resolved (Doc M §10). ``account`` is deferred (module docstring).
    """

    WORKSPACE = "workspace"
    BRAND = "brand"
    PRODUCT = "product"
    PROJECT = "project"


class MemoryType(StrEnum):
    """The species tag — the two coarse v1 types (a finer vocabulary is deferred, Doc M §17)."""

    PREFERENCE = "preference"
    BEHAVIORAL_LEARNING = "behavioral_learning"


class MemoryProvenanceClass(StrEnum):
    """Who produced the record — the born-trust axis (Doc M §8)."""

    USER_STATED = "user_stated"
    EDIT_DISTILLED = "edit_distilled"
    AGENT_OBSERVED = "agent_observed"


class MemoryStatus(StrEnum):
    """Record lifecycle (Doc M §5). Rows transition status, never silently mutate content
    (the one sanctioned exception: tombstoning redacts content — erasure is not silent)."""

    PROPOSED = "proposed"  # submitted, not yet activation-eligible
    ACTIVE = "active"  # eligible for bundles
    DORMANT = "dormant"  # crowded out by the store cap; still believed true
    SUPERSEDED = "superseded"  # replaced by a successor (superseded_by link)
    INVALIDATED = "invalidated"  # shown wrong, no successor
    LOCKED = "locked"  # Art. 21 objection lock: survives, excluded from every bundle
    TOMBSTONED = "tombstoned"  # DSAR erasure (content redacted)


class MemoryEventType(StrEnum):
    """The journaled lifecycle events — every transition carries actor + cause (Doc M §5)."""

    CREATED = "created"
    ACTIVATED = "activated"
    CONFIRMED = "confirmed"
    CONTRADICTED = "contradicted"
    SUPERSEDED = "superseded"
    INVALIDATED = "invalidated"
    REACTIVATED = "reactivated"
    EVICTED = "evicted"
    BACKFILLED = "backfilled"
    LOCKED = "locked"
    TOMBSTONED = "tombstoned"
    KICKOFF_CYCLE = "kickoff_cycle"


class MemoryRejectReason(StrEnum):
    """Why the write seam rejected a submission (a *rejection*, not an error — Doc M §7)."""

    FACT_SHAPED = "fact_shaped"  # verifiable world-statement: route to the claim store (CKB)
    BODY_RULE = "body_rule"  # body quotes personal-claim content; refs carry the facts


class ReconcileVerdictKind(StrEnum):
    """Write-time reconciliation verdicts over ``active ∪ dormant`` of the same scope+type
    (Doc M §9). Same-scope contradictions resolve at write time via supersession; the read
    path never arbitrates records."""

    ADD = "add"  # genuinely new
    UPDATE = "update"  # refines an existing record → supersession with link
    SUPERSEDE = "supersede"  # contradicts → supersede/invalidate the old, trail preserved
    NOOP = "noop"  # restatement → confirmation_count += 1, freshness reset


# --- born trust (provenance-graded activation, Doc M §8) ---------------------

TRUST_MIN = 0
TRUST_MAX = 4

#: Born ``trust_grade`` by provenance class — ordinal, transparent, never blended: +1 per
#: confirmation (capped), −1 per contradiction (floored), every change journaled. The grading is
#: the memory-poisoning defense: untrusted content can never write an *active* memory directly.
BORN_TRUST: dict[MemoryProvenanceClass, int] = {
    MemoryProvenanceClass.USER_STATED: 3,
    MemoryProvenanceClass.EDIT_DISTILLED: 2,
    MemoryProvenanceClass.AGENT_OBSERVED: 1,
}

#: Born ``status`` by provenance class: the client literally said it → active; everything
#: inferred is born ``proposed`` (pattern strength / review queue gate activation).
BORN_STATUS: dict[MemoryProvenanceClass, MemoryStatus] = {
    MemoryProvenanceClass.USER_STATED: MemoryStatus.ACTIVE,
    MemoryProvenanceClass.EDIT_DISTILLED: MemoryStatus.PROPOSED,
    MemoryProvenanceClass.AGENT_OBSERVED: MemoryStatus.PROPOSED,
}


# --- errors ------------------------------------------------------------------


class MemoryPreconditionFailed(ValueError):
    """The submission/request is malformed — not merely unwelcome (Doc M §7).

    Raised for: person-adjacent content without ``subject_entity_id``; an unknown/deferred scope
    (``account``); a scope id that does not name a live spine row in the submission's workspace.
    Distinct from :class:`MemoryRejected` (a well-formed proposal the species/body rules refuse)
    and from :class:`MemoryDisabled` (a quiet typed no-op — the user chose that state).
    """


# --- the write seam ----------------------------------------------------------


class ScopeRef(BaseModel):
    """The owning scope instance. ``scope_id`` names a spine row (brand/product/project id);
    ``None`` for workspace scope, where the workspace itself is the instance."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    scope_type: MemoryScopeType
    scope_id: str | None = None


class MemorySubmission(BaseModel):
    """A candidate memory, submitted through the write seam — no writer inserts rows (Doc M §7).

    ``claim_refs`` carry the facts (ids into the claim store, never content); ``body`` carries
    the learning. ``subject_entity_id`` is the resolved contact key, mandatory for any
    person-adjacent memory (fail-closed at the seam).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    workspace_id: str
    scope: ScopeRef
    type: MemoryType
    trigger: str
    body: str
    provenance_class: MemoryProvenanceClass
    claim_refs: tuple[UUID, ...] = ()
    subject_entity_id: UUID | None = None
    creating_quote: str | None = None


class MemoryAccepted(BaseModel):
    """The submission landed. ``verdict`` says how reconciliation disposed of it; ``memory_id``
    is the surviving record (the reactivated dormant twin on ``noop``/``update`` matches —
    never a zombie duplicate)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    outcome: Literal["accepted"] = "accepted"
    verdict: ReconcileVerdictKind
    memory_id: str
    status: MemoryStatus


class MemoryRejected(BaseModel):
    """The species/body rules refused the submission (Doc M §2/§5): a fact-shaped statement
    belongs in the claim store; a body quoting personal-claim content smuggles facts past the
    use gate. ``detail`` names the correct path."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    outcome: Literal["rejected"] = "rejected"
    reason: MemoryRejectReason
    detail: str


class MemoryDisabled(BaseModel):
    """The workspace kill-switch (or the deploy master default) is off — a quiet typed no-op,
    NOT an error (Doc M §17a). Typed precisely so skills honor it conversationally: the agent
    never implies retention that is not happening."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    outcome: Literal["memory_disabled"] = "memory_disabled"


SubmissionOutcome = MemoryAccepted | MemoryRejected | MemoryDisabled


@runtime_checkable
class MemoryWriteSeam(Protocol):
    """The one write path. Enforces — identically for every writer — tenancy stamping
    (fail-closed), the kill-switch, species check + body rule, subject binding, scope validity,
    provenance-graded born trust, and write-time reconciliation (Doc M §7–§9).

    Implementations bind their own storage access; the seam is connection-free by contract
    (``core`` imports nothing but pydantic).
    """

    async def submit(self, submission: MemorySubmission) -> SubmissionOutcome: ...


# --- the read seam -----------------------------------------------------------


class ScopeStack(BaseModel):
    """The scope stack a recipe execution carries: ``(workspace, brand, product?, project?)``
    (Doc M §4). Assembly gates on membership; order here carries no semantics."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    workspace_id: str
    brand_id: str
    product_id: str | None = None
    project_id: str | None = None


class AssemblyRequest(BaseModel):
    """A recipe execution's request for memory context. Recipes declare which memory types they
    consume; declaring none means no memory step at all (research unbiased by preference is a
    feature — Doc M §10)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    scope_stack: ScopeStack
    recipe: str
    requested_types: tuple[MemoryType, ...] = ()


class MemoryLabel(BaseModel):
    """Everything the agent needs to reconcile advice at proposal time (Doc M §10.4): ALL
    priority information lives here — position in the bundle means nothing. Freshness is
    cycle-relative (``cycles_since_confirmed``); wall-clock appears nowhere."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    scope_type: MemoryScopeType
    scope_id: str | None
    type: MemoryType
    trigger: str
    provenance_class: MemoryProvenanceClass
    trust_grade: int = Field(ge=TRUST_MIN, le=TRUST_MAX)
    cycles_since_confirmed: int = Field(ge=0)
    confirmation_count: int = Field(ge=0)
    claim_refs: tuple[UUID, ...] = ()


class MemoryBundleEntry(BaseModel):
    """One memory in an assembled bundle: id + body + full label. The bundle is the ONE place
    bodies appear — journals carry ids and label metadata only (Doc M §11)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    memory_id: str
    body: str
    label: MemoryLabel


class MemoryBundle(BaseModel):
    """The deterministically assembled memory context for one recipe execution.

    ``journal_id`` names the bundle-journal row written for this assembly (the REQ-12
    reproducibility record); it is excluded from :meth:`canonical_bytes` — determinism is a
    property of the *content*, witnessed by ``bundle_hash`` in the journal.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    workspace_id: str
    recipe: str
    entries: tuple[MemoryBundleEntry, ...] = ()
    journal_id: str | None = None

    def canonical_bytes(self) -> bytes:
        """Stable serialization: same store state + same request ⇒ byte-identical (Doc M §19)."""
        payload = self.model_dump(mode="json", exclude={"journal_id"})
        return json.dumps(
            payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False
        ).encode()

    def bundle_hash(self) -> str:
        """The determinism witness recorded in the bundle journal."""
        return hashlib.sha256(self.canonical_bytes()).hexdigest()


@runtime_checkable
class ContextAssembly(Protocol):
    """The one read path — inject-only in v1 (no search; Doc M §10/§17).

    Returns ``None`` when there is no memory step at all: the recipe declared no types, or the
    kill-switch is off (no phantom "empty" bundle — the switch audit is the record).
    """

    async def assemble(self, request: AssemblyRequest) -> MemoryBundle | None: ...


# --- write-time reconciliation (the judged part of the write seam) -----------


class ReconcileCandidate(BaseModel):
    """An existing same-scope same-type record (``active ∪ dormant`` — never active-only,
    so a re-stated dormant memory reactivates instead of spawning a zombie twin, Doc M §9)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    memory_id: str
    body: str
    trigger: str
    status: MemoryStatus


class ReconcileJudgment(BaseModel):
    """The judge's verdict on one submission against its candidate set. ``species_ok`` /
    ``body_ok`` are the semantic layer of the species check + body rule (deterministic lexical
    guards run first and fail fast). ``target_memory_id`` names the matched record for
    ``update``/``supersede``/``noop``."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    verdict: ReconcileVerdictKind
    target_memory_id: str | None = None
    species_ok: bool = True
    body_ok: bool = True
    rationale: str = ""


@runtime_checkable
class ReconcileJudge(Protocol):
    """LLM-assisted judgment, engine-executed ("LLM proposes, engine disposes" — Doc M §9).

    Implementations fence submission/candidate text as untrusted data (the M9.3 hardening); an
    unparseable or malformed response must fail safe — the engine parks the submission
    ``proposed``, never silently activates it.
    """

    async def judge(
        self, submission: MemorySubmission, candidates: tuple[ReconcileCandidate, ...]
    ) -> ReconcileJudgment: ...
