"""Verification gates — the M9 contracts other milestones call (Beat-0).

Verification is a *library of callable gates* (substrate §6, Doc D §5), not just a phase: M9 runs
them itself during the ``VERIFICATION`` phase, but they are also called mid-flight by other
milestones — M8's deep workers call :class:`PreSpendGate` before spend, :class:`FaithfulnessJudge`
on every tier-4 claim, and :class:`IdentityBindingGate` on contact claims; M5.1 calls the judge on
tier-4 client claims; M7.5's scheduler calls :class:`Freshness` to find re-research candidates.

Because those callers live in *other* packages and must stay import-independent of ``verification``
(the import-linter contract), the gate **protocols** live here in ``core`` — exactly like
:class:`~clue_core.resolver.Resolver` — while M9 supplies the **implementations** behind
them. Concrete gates are injected at the ``api`` composition root; no milestone imports another.

This module is the *accuracy / identity-binding* gate only (is it true, and is it *this* entity?).
The distinct *appropriateness / use* gate (``use_class × jurisdiction × workspace_policy``) is M10
and
is deliberately not here (Doc D §5 — they must be separately measurable). The structural promotion
predicate already lives on the claim itself (:func:`~clue_core.claim.can_be_promoted`); M9
calls it and these gates decide the actual transition.

Beat-0 ships only the seam (protocols + frozen value types). Corroboration (the M9-internal
standalone pass), the eval harness (CI-only), the ``verify()`` umbrella, and all M9 config/audit
tables are built on the M9 branch. Architecture sources: substrate §6, Doc D,
docs/specs/M09-verification-layer.md.
"""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal
from typing import Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, JsonValue, model_validator

from clue_core.claim import Claim
from clue_core.entity import AccountEntity, ContactEntity
from clue_core.enums import (
    EntityType,
    EnumerationScope,
    FreshnessState,
    IdentityBinding,
    JudgeVerdict,
    PreSpendKind,
    PreSpendVerdict,
)
from clue_core.field import FieldDef, FieldKey
from clue_core.primitives import (
    ClaimId,
    Confidence,
    CostCents,
    EntityId,
    RunId,
    SourceTier,
    UnitInterval,
    UtcDatetime,
)

# --- M9.1: pre-spend schema/identity gate -----------------------------------


class PreSpendRequest(BaseModel):
    """A request to spend on producing claims (M9.1). Two kinds (Option C):

    ``FIELD`` (the default) — fill one ``(entity, field, tier)`` claim; carries ``field_key`` and
    never a ``scope``. ``value_json`` is optional: present when the value is already in hand
    (validate it), absent when the gate is consulted *before* a resolver call. ``ENUMERATION`` — a
    discovery spend that fans out over a ``scope`` to enumerate members that do not yet exist as
    entities (committee people-discovery within an account); carries ``scope`` and never a
    ``field_key`` (there is no single field) or ``value_json``. Either kind requires an
    already-resolved ``entity`` — the gate never sees a free-text name."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    entity_id: EntityId
    entity_type: EntityType
    kind: PreSpendKind = PreSpendKind.FIELD
    field_key: FieldKey | None = None
    scope: EnumerationScope | None = None
    source_tier: SourceTier
    run_id: RunId
    value_json: JsonValue | None = None

    @model_validator(mode="after")
    def _check_kind(self) -> PreSpendRequest:
        """Enforce the kind ⇄ field_key ⇄ scope coherence (mirrors the DB CHECK)."""
        if self.kind is PreSpendKind.FIELD:
            if self.field_key is None:
                raise ValueError("a FIELD pre-spend requires a field_key")
            if self.scope is not None:
                raise ValueError("a FIELD pre-spend must not carry an enumeration scope")
        else:  # ENUMERATION
            if self.scope is None:
                raise ValueError("an ENUMERATION pre-spend requires a scope")
            if self.field_key is not None:
                raise ValueError("an ENUMERATION pre-spend must not carry a field_key")
            if self.value_json is not None:
                raise ValueError("an ENUMERATION pre-spend has no value_json")
        return self


class PreSpendDecision(BaseModel):
    """The pre-spend gate verdict (M9.1). ``REJECT`` carries the reasons (FIELD: field unknown, tier
    not in plan, value fails schema; ENUMERATION: scope tier not sanctioned; either: entity
    unresolved/merged, lock held by another run) — no resolver runs, no spend."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    verdict: PreSpendVerdict
    reasons: tuple[str, ...] = ()


class TargetLock(BaseModel):
    """Target-lock context for mode-M2 profiling (M9.1 ``assemble_target_lock`` + M8.1; the M09
    spec's ``PromptContext``). Pins synthesis/scrape to *this* entity — a canonical-domain ``site:``
    filter plus a no-drift instruction built from the entity's name/domain/geo/aliases — so a
    same-name company never leaks in (the prototype's failure; substrate §6)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    entity_id: EntityId
    no_drift_instruction: str
    canonical_domain: str | None = None
    identifiers: dict[str, JsonValue] = {}


@runtime_checkable
class PreSpendGate(Protocol):
    """The pre-spend gate (M9.1) — called before every claim-producing path. Returns ``PASS`` only
    when schema (field exists, tier in plan, value valid) and identity (entity resolved, active,
    strongly keyed) checks clear; otherwise ``REJECT`` with reasons. Emits the
    ``verification.pre_spend_gate`` span."""

    async def check(self, request: PreSpendRequest) -> PreSpendDecision: ...

    async def assemble_target_lock(
        self, entity: AccountEntity | ContactEntity, field: FieldDef
    ) -> TargetLock: ...


# --- M9.3: faithfulness judge -----------------------------------------------


class JudgeResult(BaseModel):
    """The faithfulness judge's verdict on one claim (M9.3): is ``value_json`` entailed by the
    claim's ``evidence_span``? Carries the model + cost so ``llm.gateway_call`` /
    ``verification.faithfulness_judge`` spend is queryable. The judge is the least-trusted source's
    last defence — a tier-4 claim with no span is auto-``UNSUPPORTED`` (free, structural)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    claim_id: ClaimId
    verdict: JudgeVerdict
    score: Confidence
    rationale: str = ""
    judge_model: str | None = None
    cost_cents: CostCents = Decimal(0)


@runtime_checkable
class FaithfulnessJudge(Protocol):
    """The faithfulness judge (M9.3) — an LLM-as-judge entailment check on a synthesized claim,
    run as a distinct trace span. Called by M11/M8 on tier-4 claims and by M5.1 on tier-4 client
    claims, before promotion. The judge model is config (a gateway model id); swapping it is a
    config change behind this protocol."""

    async def judge(self, claim: Claim) -> JudgeResult: ...


# --- M9.4: identity-binding gate --------------------------------------------


class Binding(BaseModel):
    """The identity-binding classification of one contact claim (M9.4). ``STRONG`` requires a
    verified handle/email or ≥K corroborating identifiers bound to this contact; ``WEAK`` is a
    name-only match. A ``WEAK`` claim never promotes and never drives outreach — better an empty
    hook than someone else's fact (staged-flow §6)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    claim_id: ClaimId
    contact_entity_id: EntityId
    strength: IdentityBinding
    strength_score: UnitInterval
    signals: dict[str, JsonValue] = {}


@runtime_checkable
class IdentityBindingGate(Protocol):
    """The identity-binding gate (M9.4) — classifies a contact claim ``STRONG`` vs ``WEAK`` and
    writes ``claim.identity_binding``. Called at contact-claim ingestion (M8.4/M8.5). Emits
    ``verification.identity_binding``."""

    async def classify(self, claim: Claim) -> Binding: ...


# --- M9.5: freshness TTL engine + re-research cadence -----------------------


class Staleness(BaseModel):
    """The staleness evaluation of one claim against its field's freshness TTL (M9.5). Stale winners
    are surfaced, never silently dropped, so scoring can discount them and a refresh can be
    scheduled (substrate §1/§6). ``EXPIRED`` (personal-claim retention age-out) is added on the M9
    branch with the cadence policy and M10.5 coordination."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    claim_id: ClaimId
    state: FreshnessState
    age_days: float
    ttl_days: float | None = None


class ReResearchCandidate(BaseModel):
    """A re-research candidate emitted to the M7 scheduler (M9.5). M9 *detects* staleness and emits
    these; M7 *schedules and runs* the refresh (M9.5 never executes). ``priority`` is tier-driven
    (lower = sooner)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    entity_id: EntityId
    field_key: FieldKey
    stale_claim_ids: tuple[ClaimId, ...] = ()
    due_at: UtcDatetime
    priority: int = 5


class AgeOutCandidate(BaseModel):
    """A personal claim past its **retention horizon** (``FreshnessState.EXPIRED``), surfaced to
    M10.5 for lawful age-out / erasure — the M9.5↔M10.5 seam (M9.5 detects + surfaces; M10.5 owns
    the tombstone/erasure). One per expired claim (each erased individually); ``claim_id`` is the
    durable reference M10.5 tombstones **before the next merge read**, so ``current_value`` and the
    handoff stop seeing it with no merge-ranking change. ``retention_days`` is the use-class-keyed
    retention horizon it crossed — *distinct from* the freshness TTL (``Staleness.ttl_days``): a
    claim can be FRESH by its field TTL yet EXPIRED by a shorter retention horizon (Doc D §4).

    Promoted to ``core`` in the phase-3 pre-flight contract-delta (it postdates the Beat-0 freeze):
    the M9.5 impl lives in ``verification`` which ``compliance`` may not import, so the *type* must
    live here for M10.5 to consume it via the ``core`` seam."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    claim_id: ClaimId
    entity_id: EntityId
    field_key: FieldKey
    age_days: float
    retention_days: float | None = None


@runtime_checkable
class Freshness(Protocol):
    """The freshness engine (M9.5). ``evaluate`` is a pure staleness verdict for one claim (mirrors
    the merge layer's freshness computation); ``due_for_refresh`` scans the store and returns
    re-research candidates for M7 to schedule; ``due_for_age_out`` scans for personal claims past
    their *retention* horizon (EXPIRED) and surfaces them to M10.5 for tombstone/erasure (the
    M9.5↔M10.5 seam). Both scans return candidates — they never fetch or erase.

    ``evaluate``'s ``ttl`` is an *override*: when given (tests, client-specific cadence) it is used
    directly; when ``None`` the implementation reads the field's configured
    ``field_definition.freshness_ttl``, falling back to a sensible default if that too is unset
    (M09 §M9.5: staleness is ``observed_at`` vs the field's TTL)."""

    def evaluate(
        self, claim: Claim, *, now: UtcDatetime, ttl: timedelta | None = None
    ) -> Staleness: ...

    async def due_for_refresh(
        self,
        *,
        entity_ids: tuple[EntityId, ...] | None = None,
        field_keys: tuple[FieldKey, ...] | None = None,
    ) -> tuple[ReResearchCandidate, ...]: ...

    async def due_for_age_out(
        self,
        *,
        entity_ids: tuple[EntityId, ...] | None = None,
        field_keys: tuple[FieldKey, ...] | None = None,
    ) -> tuple[AgeOutCandidate, ...]: ...
