"""M13.2 — the normalized ``FeedbackDisposition`` record + its taxonomies.

A *disposition* is the atomic unit of feedback (substrate §9/§10): the moment a human reviewer
approves/corrects/rejects a claim (M13.1), **or** the moment a client's sales team accepts / replies
to / books a meeting on an account we scored, that signal becomes *labeled training data* — for the
fit/intent scoring rubric (M3.4) and for the per-source learning loop (staged-flow §7e). M13.2 is
the single, append-only, idempotent capture substrate for **both** origins (one schema), and the
sole input to M13.3 (read only through :func:`~clue_research.review.labeled_dataset`).

This module is the **record + vocabularies** half (the store/emitter live in
``review.disposition_store``; the read view in ``review.labeled_dataset``). The enums are defined
**here, in ``review``** — *not* ``core`` — deliberately: they cross no package boundary ``core``
must broker (M13.1 hands M13.2 a ``ReviewActionOutcome`` through the frozen
``core.ReviewDispositionEmitter`` seam; M13.2 owns everything after that). The record is named
``FeedbackDisposition`` (**not** ``Disposition``) to avoid colliding with
``clue_research.identity.Disposition`` (the M2 entity-merge disposition — a different concept the
api root imports alongside this one).

Architecture sources: substrate §9 (disposition = labeled training data; "the feedback loop is free
in V1"), §10 (corrections = labeled data for extraction *and* scoring); staged-flow §7e/§9 (the same
disposition signal reweights *sources*); Doc D §4 (a contact-keyed disposition is personal data tied
to a ``contact_entity_id`` — erasure/tombstone applies); docs/specs/M13-…-observability.md §M13.2.
"""

from __future__ import annotations

from enum import StrEnum
from typing import NewType
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, JsonValue, model_validator

from clue_core import (
    CampaignRunId,
    ClaimId,
    EntityId,
    EntityType,
    ReviewAction,
    UtcDatetime,
)

# The durable id of one ``disposition`` row. A distinct NewType (like ``ClaimId``/``EntityId``) so a
# disposition id can never be transposed with the claim/entity ids it references.
DispositionId = NewType("DispositionId", UUID)


def new_disposition_id() -> DispositionId:
    """Mint a fresh :class:`DispositionId` (mirrors ``core.new_claim_id``)."""
    return DispositionId(uuid4())


# --- taxonomies (closed StrEnums; each mirrored by a DB enum + a parity test) ---------------------


class DispositionType(StrEnum):
    """What happened — the disposition taxonomy (spec §M13.2 data model).

    The ``claim_*`` triple is emitted by the M13.1 review surface (one per approve/correct/reject);
    the account-level remainder arrives from the client's downstream sales outcomes via
    ``DispositionStore.ingest_downstream``. Closed so the learning loop (M13.3) switches on a typed
    label, never free text."""

    # internal Tier-1 review actions (M13.1)
    CLAIM_APPROVED = "claim_approved"
    CLAIM_CORRECTED = "claim_corrected"
    CLAIM_REJECTED = "claim_rejected"
    # downstream sales outcomes (ingested from the client; CRM-read / webhook / manual)
    ACCOUNT_ACCEPTED = "account_accepted"
    ACCOUNT_REJECTED = "account_rejected"
    ACCOUNT_CONTACTED = "account_contacted"
    REPLY_RECEIVED = "reply_received"
    MEETING_BOOKED = "meeting_booked"
    CLOSED_WON = "closed_won"
    CLOSED_LOST = "closed_lost"


class DispositionActor(StrEnum):
    """Who produced the signal — for scoping reweighting confidence (a client-fed outcome is a
    stronger fit label than an internal reviewer's claim correction; substrate §9)."""

    INTERNAL_REVIEWER = "internal_reviewer"
    CLIENT_SALES = "client_sales"
    SYSTEM = "system"


class DispositionOrigin(StrEnum):
    """How the signal arrived — the swappable ingest channel (spec §M13.2 "swap points"). The
    downstream channels (``crm_ingest``/``webhook``/``manual``) all land as the same record via
    ``ingest_downstream``; the CRM is a **read** source only — never a write-through path (Postgres
    is the only source of truth, substrate §5c/§12)."""

    REVIEW_SURFACE = "review_surface"
    CRM_INGEST = "crm_ingest"
    WEBHOOK = "webhook"
    MANUAL = "manual"


# The two halves of the taxonomy by entity axis. A ``claim_*`` disposition is per-claim (carries a
# ``claim_id``); an account-level one keys on the account (and is the only kind
# ``ingest_downstream``
# admits — a sales outcome is never about one claim).
CLAIM_DISPOSITION_TYPES: frozenset[DispositionType] = frozenset(
    {
        DispositionType.CLAIM_APPROVED,
        DispositionType.CLAIM_CORRECTED,
        DispositionType.CLAIM_REJECTED,
    }
)
ACCOUNT_DISPOSITION_TYPES: frozenset[DispositionType] = (
    frozenset(DispositionType) - CLAIM_DISPOSITION_TYPES
)


# --- natural keys (the idempotent-capture anchors; ``record`` = ``ON CONFLICT DO NOTHING``) -------


def review_natural_key(review_action_id: UUID) -> str:
    """The review-origin idempotency anchor.

    Keys on the **``review_action_id``** — the durable, 1:1 ``review_action`` audit-row id the
    frozen ``ReviewActionOutcome`` already carries. This deliberately supersedes the brief's earlier
    ``review_surface:{campaign_run}:{claim_id}:{type}:{round}`` formula: the seam evolved to hand
    M13.2 a strictly-stronger unique token (the brief pre-dated the frozen ``core.review`` contract,
    whose emitter signature carries no ``review_round``), and M13.1 guarantees exactly one
    ``review_action`` row per logical action (its AC: "replaying the same action is idempotent"). So
    re-emitting the same outcome — the literal "replaying the action" — dedupes to one disposition.
    """
    return f"review_surface:{review_action_id}"


def downstream_natural_key(
    *,
    origin: DispositionOrigin,
    workspace_id: str,
    external_id: str,
    disposition_type: DispositionType,
) -> str:
    """The downstream-origin idempotency anchor: the adapter-supplied external dedup token,
    namespaced by ``origin`` + ``workspace_id`` (two clients may reuse a CRM record id) +
    ``disposition_type`` (one opportunity emits ``contacted`` then ``replied`` then
    ``meeting_booked`` — distinct signals)."""
    return f"{origin.value}:{workspace_id}:{external_id}:{disposition_type.value}"


# --- the record -----------------------------------------------------------------------------------


class FeedbackDisposition(BaseModel):
    """One normalized feedback signal — the row ``record`` persists (spec §M13.2 data model).

    Keyed on a **resolved** ``entity_id`` (an account or a contact; never a free-text name —
    conventions §2), with the ``account_entity_id`` rollup (== ``entity_id`` for an account-typed
    disposition; the parent account for a contact-typed one) so the learning loop can aggregate
    "this
    source drove N accepted *accounts*" without re-resolving the contact→account link. Carries the
    ``(workspace_id, icp_key, icp_spec_version)`` scope so reweighting stays per-(ICP, run) and the
    ``labeled_dataset`` view never mixes two ICP segments (D5: version restarts per ``icp_key``)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: DispositionId
    disposition_type: DispositionType
    entity_id: EntityId  # the disposed entity (account or contact)
    entity_type: EntityType
    account_entity_id: EntityId  # the parent account (the dataset / source-rollup key)
    claim_id: ClaimId | None = None  # the reviewed claim (claim_* dispositions only)
    campaign_run_id: CampaignRunId | None = None
    workspace_id: str
    icp_key: str = ""
    icp_spec_version: int | None = None
    actor: DispositionActor
    origin: DispositionOrigin
    # the mirrored M13.1 ``review_action`` audit-row id (review-origin only; the durable backstop).
    review_action_id: UUID | None = None
    reason_code: str | None = None  # the typed reject reason / sales note category, when present
    detail: dict[str, JsonValue] = {}  # free-form adapter payload (CRM fields, webhook body, …)
    occurred_at: UtcDatetime  # when the action/outcome actually happened
    natural_key: str

    @model_validator(mode="after")
    def _check_shape(self) -> FeedbackDisposition:
        # An account-typed disposition's entity *is* its account; a contact-typed one's is not.
        if self.entity_type is EntityType.ACCOUNT and self.entity_id != self.account_entity_id:
            raise ValueError("an account-typed disposition must key entity_id == account_entity_id")
        # A claim_* disposition carries the reviewed claim; an account-level one does not.
        is_claim_type = self.disposition_type in CLAIM_DISPOSITION_TYPES
        if is_claim_type and self.claim_id is None:
            raise ValueError(f"{self.disposition_type} requires a claim_id")
        # Review-origin mirrors a review_action audit row; the other origins never do.
        is_review = self.origin is DispositionOrigin.REVIEW_SURFACE
        if is_review != (self.review_action_id is not None):
            raise ValueError("review_surface origin <=> review_action_id present")
        if self.icp_spec_version is not None and self.icp_spec_version < 1:
            raise ValueError("icp_spec_version must be >= 1 when set")
        return self

    @classmethod
    def for_review_action(
        cls,
        *,
        disposition_type: DispositionType,
        entity_id: EntityId,
        entity_type: EntityType,
        account_entity_id: EntityId,
        claim_id: ClaimId,
        campaign_run_id: CampaignRunId,
        workspace_id: str,
        icp_key: str,
        icp_spec_version: int | None,
        review_action_id: UUID,
        occurred_at: UtcDatetime,
        reason_code: str | None = None,
        detail: dict[str, JsonValue] | None = None,
    ) -> FeedbackDisposition:
        """Build the review-origin record M13.1 emits (one per approve/correct/reject)."""
        if disposition_type not in CLAIM_DISPOSITION_TYPES:
            raise ValueError(f"{disposition_type} is not a review-origin (claim_*) disposition")
        return cls(
            id=new_disposition_id(),
            disposition_type=disposition_type,
            entity_id=entity_id,
            entity_type=entity_type,
            account_entity_id=account_entity_id,
            claim_id=claim_id,
            campaign_run_id=campaign_run_id,
            workspace_id=workspace_id,
            icp_key=icp_key,
            icp_spec_version=icp_spec_version,
            actor=DispositionActor.INTERNAL_REVIEWER,
            origin=DispositionOrigin.REVIEW_SURFACE,
            review_action_id=review_action_id,
            reason_code=reason_code,
            detail=detail or {},
            occurred_at=occurred_at,
            natural_key=review_natural_key(review_action_id),
        )

    @classmethod
    def for_downstream(
        cls,
        *,
        disposition_type: DispositionType,
        account_entity_id: EntityId,
        workspace_id: str,
        external_id: str,
        occurred_at: UtcDatetime,
        icp_key: str = "",
        icp_spec_version: int | None = None,
        campaign_run_id: CampaignRunId | None = None,
        actor: DispositionActor = DispositionActor.CLIENT_SALES,
        origin: DispositionOrigin = DispositionOrigin.CRM_INGEST,
        reason_code: str | None = None,
        detail: dict[str, JsonValue] | None = None,
    ) -> FeedbackDisposition:
        """Build a downstream sales-outcome record (account-level; the entity is the account)."""
        if disposition_type not in ACCOUNT_DISPOSITION_TYPES:
            raise ValueError(f"{disposition_type} is not a downstream (account-level) disposition")
        if origin is DispositionOrigin.REVIEW_SURFACE:
            raise ValueError("downstream dispositions never use the review_surface origin")
        return cls(
            id=new_disposition_id(),
            disposition_type=disposition_type,
            entity_id=account_entity_id,
            entity_type=EntityType.ACCOUNT,
            account_entity_id=account_entity_id,
            campaign_run_id=campaign_run_id,
            workspace_id=workspace_id,
            icp_key=icp_key,
            icp_spec_version=icp_spec_version,
            actor=actor,
            origin=origin,
            reason_code=reason_code,
            detail=detail or {},
            occurred_at=occurred_at,
            natural_key=downstream_natural_key(
                origin=origin,
                workspace_id=workspace_id,
                external_id=external_id,
                disposition_type=disposition_type,
            ),
        )


# --- the downstream ingest contract (resolve-or-reject; never best-guess) -------------------------


class DownstreamOutcome(BaseModel):
    """One row of a downstream sales-outcome batch handed to ``ingest_downstream``.

    Carries an ``external_id`` dedup token (the CRM record / webhook event / manual-entry id) and an
    identity hint: either a pre-resolved ``account_entity_id`` (the adapter resolved it) or a
    free-text ``company_name`` (+ optional ``domain`` / ``registry_ids``) that M13.2 resolves via
    identity (M2) — resolving confidently or **rejecting to the error queue**, never best-guessing
    (conventions §2). The CRM is a read source only; this is the one inbound path."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    external_id: str
    disposition_type: DispositionType
    workspace_id: str
    occurred_at: UtcDatetime
    # identity hint — a pre-resolved id OR a free-text company to resolve.
    account_entity_id: EntityId | None = None
    company_name: str = ""
    domain: str | None = None
    registry_ids: dict[str, str] = {}
    # optional context + audit.
    actor: DispositionActor = DispositionActor.CLIENT_SALES
    origin: DispositionOrigin = DispositionOrigin.CRM_INGEST
    icp_key: str | None = None
    icp_spec_version: int | None = None
    campaign_run_id: CampaignRunId | None = None
    reason_code: str | None = None
    detail: dict[str, JsonValue] = {}

    @model_validator(mode="after")
    def _check(self) -> DownstreamOutcome:
        if self.disposition_type not in ACCOUNT_DISPOSITION_TYPES:
            raise ValueError(f"{self.disposition_type} is not an account-level outcome")
        if self.origin is DispositionOrigin.REVIEW_SURFACE:
            raise ValueError("a downstream outcome cannot claim the review_surface origin")
        if self.account_entity_id is None and not (self.company_name or self.domain):
            raise ValueError(
                "a downstream outcome needs account_entity_id or company_name/domain to resolve"
            )
        return self


class IngestRejection(BaseModel):
    """A downstream row that did not resolve to an account — routed to the error queue, never
    guessed (spec §M13.2 AC2: "resolved or rejected, never silently best-guessed")."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    external_id: str
    disposition_type: DispositionType
    reason: str  # 'unresolved' (no confident match) | 'invalid' (validation/identity error)
    detail: str | None = None


class IngestReport(BaseModel):
    """The outcome of an ``ingest_downstream`` batch: the recorded disposition ids and the rejected
    rows (so the caller can re-queue / surface them)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    recorded: tuple[DispositionId, ...] = ()
    rejected: tuple[IngestRejection, ...] = ()


# --- M13.1 review-action → disposition-type mapping -----------------------------------------------

# The frozen ``core.ReviewAction`` (approve/correct/reject) → the ``claim_*`` disposition type the
# emitter records. Kept here (not ``core``) since it is M13.2's interpretation of the review action.
REVIEW_ACTION_TO_DISPOSITION: dict[ReviewAction, DispositionType] = {
    ReviewAction.APPROVE: DispositionType.CLAIM_APPROVED,
    ReviewAction.CORRECT: DispositionType.CLAIM_CORRECTED,
    ReviewAction.REJECT: DispositionType.CLAIM_REJECTED,
}


# --- observability metric names (emitted on capture; obs counters, not the durable substrate) -----

METRIC_DISPOSITIONS = (
    "research.disposition.captured"  # +1 per recorded disposition (labels: type/origin/actor)
)
METRIC_DISPOSITIONS_REJECTED = (
    "research.disposition.ingest_rejected"  # +1 per rejected ingest row (label: reason)
)
