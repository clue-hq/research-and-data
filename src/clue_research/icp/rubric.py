"""The scoring-rubric model + pure score function (M3.4 / ENG-121).

The market's own critique is that a single opaque "87/100" tells a rep nothing; multi-dimensional,
**explainable** scoring is the differentiator (substrate §9). This module defines the versioned
``scoring_rubric`` data model — structured **fit + intent** weights over the active fields — and the
pure, provenance-aware :func:`score` function that consumes it, so every score decomposes into
inspectable Fit and Intent sub-scores, each traceable to the ``claim_id`` behind it (the
``account_handoff.fit_score/intent_score`` "decomposed, each linked to claims" of conventions §4).

It is the **model and contract only**: :func:`score` is pure/deterministic/no-LLM over
``current_value(entity, field)`` (M1); M6 wires it to the live claim store at Pass A and assigns
tiers, M12 embeds the decomposition in the handoff, M13 writes reweighted rubric versions. None of
that lives here (boundary note, ENG-121).

Where it is stored: the rubric is a **slot of the ICP spec** (``icp_spec.scoring_rubric``, M3.1) —
no new table, no claim-store schema change. Its durable, append-only versioning *is* M3.1's: editing
weights writes a new ``icp_spec`` version carrying the new rubric, and a campaign pinned to a prior
``(client_id, icp_key, version)`` re-reads — and so re-scores — identically.

Design seams (conventions §2):
* **Data, not code.** The rubric is per-ICP, versioned config; the aggregation is data-driven
  (weights + declarative transforms), so swapping linear weights for a learned model (M13) stays
  behind :func:`score` and the per-field ``claim_id`` explainability contract is preserved.
* **Reads ``current_value`` only.** Decoupled from how claims are produced (any M4 resolver feeding
  the same ``field_key`` works unchanged) and from the durable backend (Postgres→Temporal is
  invisible to scoring).
* **Empty is correct (conventions §5).** A missing / stale / low-confidence input contributes per an
  explicit, configured rule (zero + a flag in ``contributions``), never a fabricated default.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from enum import StrEnum
from typing import Annotated, Any

from annotated_types import Ge
from pydantic import BaseModel, ConfigDict, Field, JsonValue
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_core import (
    ClaimId,
    Confidence,
    CurrentValue,
    EntityId,
    FieldKey,
    FreshnessState,
    Score,
    ScoreComponent,
    UnitInterval,
)
from clue_research.claimstore import TenantScope, current_values
from clue_research.icp.compiler import FieldPlan
from clue_research.icp.spec import get_active_icp, get_icp_version

# A non-negative, finite rubric weight (relative within its sub-rubric; normalization makes the
# scale moot). ``allow_inf_nan=False`` rejects inf/nan at construction — an inf weight would make
# normalization compute inf/inf = NaN and silently corrupt the score (the way UnitInterval's Le(1.0)
# already excludes inf for factors/scores).
Weight = Annotated[float, Ge(0.0), Field(allow_inf_nan=False)]


class ScoreDimension(StrEnum):
    """The two sub-scores, kept **separate and inspectable** — never collapsed (substrate §9)."""

    FIT = "fit"  # firmographic / technographic / vertical match (core.* / account.* / <pack>.*)
    INTENT = "intent"  # the scoring-tagged deterministic proxies (Doc C §1)


class ScoringTransform(StrEnum):
    """How a raw ``current_value`` maps to a ``[0,1]`` factor before weighting (data-driven, so the
    rubric stays config). Each is pure and deterministic; an un-coercible value yields ``0.0`` (it
    cannot satisfy the predicate) rather than raising — empty-is-correct, not an error."""

    BOOLEAN = "boolean"  # truthy -> 1.0 else 0.0 (presence / a match_predicate already evaluated)
    THRESHOLD = "threshold"  # value >= params['threshold'] -> 1.0 else 0.0
    LINEAR = "linear"  # clamp((value - params['lo']) / (params['hi'] - params['lo']), 0, 1)
    CATEGORICAL = "categorical"  # params['weights'][str(value)] -> factor (default 0.0), clamped
    IDENTITY = "identity"  # value is already a 0..1 factor (clamped)


class MissingValueRule(StrEnum):
    """How an absent / stale / low-confidence input contributes. ``ZERO`` (zero contribution + a
    flag) is the only rule shipped — empty-is-correct (conventions §5); the enum reserves room for
    future policies (e.g. a neutral-prior) without changing the score signature."""

    ZERO = "zero"


class ContributionFlag(StrEnum):
    """Why a field contributed as it did — surfaced per-field so the score is auditable, never a
    silent fabricated default (substrate §1/§6: the merge surfaces, never silently drops)."""

    OK = "ok"
    MISSING = "missing"  # no eligible current_value (current_value returned None)
    STALE = "stale"  # the winning claim is past its field's freshness TTL (FreshnessState.STALE)
    LOW_CONFIDENCE = "low_confidence"  # below the rubric's configured min_confidence floor


class RubricEntry(BaseModel):
    """One weighted contribution: a ``field_key``, its ``weight``, and the declarative ``transform``
    (+ ``params``) mapping its value to a ``[0,1]`` factor. ``(field_key, weight, transform)`` is
    the shape ENG-121 names; ``params`` carries the transform's knobs and ``match_predicate`` (e.g.
    the ``threshold`` / ``lo``-``hi`` / category ``weights``)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    field_key: FieldKey
    weight: Weight = 1.0
    transform: ScoringTransform = ScoringTransform.BOOLEAN
    params: dict[str, JsonValue] = {}
    label: str | None = None  # human-readable, for the explainability surface


class SubRubric(BaseModel):
    """A Fit or Intent sub-rubric: weighted entries + whether to normalize the weighted sum into
    ``[0,1]``. Normalization divides by the **total declared weight** (including missing fields'
    weight), so a missing field correctly drags the sub-score down rather than being ignored."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    entries: tuple[RubricEntry, ...] = ()
    normalize: bool = True

    @property
    def total_weight(self) -> float:
        return sum(e.weight for e in self.entries)


class TierBand(BaseModel):
    """A default tier-cutoff band: the ``tier`` an account lands in when its Fit **and** Intent each
    clear the band's floors. Fit and Intent stay separate (substrate §9) — a band names a minimum on
    each, not one collapsed threshold."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    tier: str  # e.g. "high" | "medium" | "low" (free-form; M6 maps to its tier vocabulary)
    min_fit: UnitInterval = 0.0
    min_intent: UnitInterval = 0.0


class TierCutoffs(BaseModel):
    """The default cutoffs Pass A *proposes* (staged-flow §4). Bands are evaluated **in order**
    (most-selective first); the first band an account clears wins, else ``fallback_tier``. These are
    emitted with the score distribution and adjusted by the human **at the checkpoint without
    mutating the rubric version** (D7: cutoffs are data, so confirming budget bands needs no model
    change) — :func:`assign_tier` takes cutoffs as an argument for exactly that reason."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    bands: tuple[TierBand, ...] = ()
    fallback_tier: str = "untiered"


class ScoringRubric(BaseModel):
    """The versioned fit + intent scoring rubric — a slot of the ICP spec (M3.1).

    ``version`` is the rubric's own semantic label; the durable **append-only store of record is
    the ``icp_spec`` version** this rides in (editing weights → ``create_icp_spec`` writes a new
    ICP-spec version carrying the new rubric). ``feedback_basis`` is the model-only hook for M13's
    disposition reweighting (reserved here; M13 implements the loop) — see :func:`reweighted`.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    fit: SubRubric = SubRubric()
    intent: SubRubric = SubRubric()
    tier_cutoffs: TierCutoffs = TierCutoffs()
    missing_value_rule: MissingValueRule = MissingValueRule.ZERO
    # A value whose winning claim is below this confidence is treated as low-confidence (flagged +
    # contributes per missing_value_rule). None = no floor (confidence does not gate contribution).
    min_confidence: Confidence | None = None
    # A STALE winner (past its field's freshness_ttl, M1) is discounted (flagged + per the rule).
    # Stale winners are surfaced, never dropped (substrate §1) — scoring discounts them here.
    discount_stale: bool = True
    # The ICP's **Fit floor** (D6; read by the M6.3 Pass-A engine). An account whose ``fit_score``
    # falls below this is flagged ``non_fit`` — *flag-and-proceed* (surfaced for review with the
    # evidence behind the low fit, never excluded), the realization of D6 for imported accounts.
    # ``None`` = no floor (no account is flagged non-fit). It rides the ``icp_spec.scoring_rubric``
    # slot, so it versions with the rubric (a change is a new rubric/ICP version) — policy as data,
    # not code. ``score`` itself does not read it (the flag is applied at Pass A, not in the math).
    fit_floor: UnitInterval | None = None
    version: int = 1
    label: str | None = None
    notes: str | None = None
    # Reserved for M13: the labeled accept/reject dispositions a reweight was derived from. Opaque
    # here (model-only hook); M13 defines its internals and runs the loop.
    feedback_basis: dict[str, JsonValue] = {}

    @property
    def field_keys(self) -> tuple[str, ...]:
        """Every field_key the rubric reads (fit then intent, de-duplicated, first-seen order) — the
        exact set :func:`score_entity` fetches ``current_value`` for."""
        return tuple(
            dict.fromkeys(e.field_key for sub in (self.fit, self.intent) for e in sub.entries)
        )


class Contribution(BaseModel):
    """One field's contribution to a sub-score, fully decomposed for the explainability contract
    (ENG-121): ``(field_key, claim_id, value, weight, contribution)`` plus the ``factor`` and the
    ``flag``. Every **nonzero** ``contribution`` links a real ``claim_id`` ("no score without its
    evidence"); a zeroed one carries its ``flag`` (missing / stale / low-confidence)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    dimension: ScoreDimension
    field_key: FieldKey
    claim_id: ClaimId | None  # the winning claim behind the value; None when MISSING
    value_json: JsonValue  # the raw current_value; None when MISSING
    factor: UnitInterval  # transform(value) in [0,1]
    weight: float
    contribution: float  # factor * weight (zeroed for a flagged input)
    flag: ContributionFlag = ContributionFlag.OK


class ScoreResult(BaseModel):
    """The output of :func:`score`: distinct ``fit_score`` and ``intent_score`` (never one collapsed
    number — substrate §9) + the flat ``contributions`` list (Fit then Intent). ``rubric_version``
    records which rubric produced it (reproducibility). ``tier_cutoffs`` rides along so the proposal
    travels with the score; the human adjusts it at the checkpoint (M6) without re-scoring."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    entity_id: EntityId
    rubric_version: int
    fit_score: float  # in [0,1] when fit.normalize (the default)
    intent_score: float  # in [0,1] when intent.normalize (the default)
    contributions: tuple[Contribution, ...] = ()
    tier_cutoffs: TierCutoffs = TierCutoffs()

    @property
    def fit_contributions(self) -> tuple[Contribution, ...]:
        return tuple(c for c in self.contributions if c.dimension is ScoreDimension.FIT)

    @property
    def intent_contributions(self) -> tuple[Contribution, ...]:
        return tuple(c for c in self.contributions if c.dimension is ScoreDimension.INTENT)

    def as_fit_score(self) -> Score:
        """Project onto the M0.2 :class:`~clue_core.Score` the ``account_handoff`` embeds
        (M12) — same decomposition, with weights renormalized to ``[0,1]`` relative shares."""
        return _as_core_score(self.fit_score, self.fit_contributions)

    def as_intent_score(self) -> Score:
        return _as_core_score(self.intent_score, self.intent_contributions)


class RubricValidationError(ValueError):
    """Raised by :func:`validate_rubric` when the rubric references a field absent from the compiled
    field plan, or an Intent field that is not a Pass-A scoring proxy (names every offender)."""

    def __init__(self, diagnostics: tuple[str, ...]) -> None:
        self.diagnostics = diagnostics
        super().__init__("invalid scoring rubric: " + "; ".join(diagnostics))


# --- transforms (pure) ------------------------------------------------------
def _as_float(value: JsonValue) -> float | None:
    """Coerce a JSON value to a *finite* float, or ``None`` if it is not a real finite number (bool
    is *not* a number here — a boolean field uses the BOOLEAN transform, not a numeric one; and a
    NaN/inf value or param degrades to ``None`` so the transform returns ``0.0`` per its contract,
    never a NaN factor that would later fail the ``[0,1]`` bound)."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    f = float(value)
    return f if math.isfinite(f) else None


def _clamp_unit(x: float) -> float:
    return 0.0 if x < 0.0 else 1.0 if x > 1.0 else x


def _apply_transform(
    transform: ScoringTransform, value: JsonValue, params: Mapping[str, Any]
) -> float:
    """Map a raw value to a ``[0,1]`` factor per the transform. Pure; an un-coercible value or a
    malformed/absent param yields ``0.0`` (cannot satisfy → contributes nothing)."""
    if transform is ScoringTransform.BOOLEAN:
        return 1.0 if value else 0.0

    if transform is ScoringTransform.THRESHOLD:
        v = _as_float(value)
        threshold = _as_float(params.get("threshold"))
        if v is None or threshold is None:
            return 0.0
        return 1.0 if v >= threshold else 0.0

    if transform is ScoringTransform.LINEAR:
        v = _as_float(value)
        lo = _as_float(params.get("lo"))
        hi = _as_float(params.get("hi"))
        if v is None or lo is None or hi is None or hi <= lo:
            return 0.0
        return _clamp_unit((v - lo) / (hi - lo))

    if transform is ScoringTransform.CATEGORICAL:
        weights = params.get("weights")
        if not isinstance(weights, Mapping):
            return 0.0
        factor = _as_float(weights.get(str(value)))
        return _clamp_unit(factor) if factor is not None else 0.0

    # IDENTITY
    v = _as_float(value)
    return _clamp_unit(v) if v is not None else 0.0


# --- the pure score function ------------------------------------------------
def _score_entry(
    rubric: ScoringRubric, dimension: ScoreDimension, entry: RubricEntry, cv: CurrentValue | None
) -> Contribution:
    """Decompose one entry against its current value (or absence) into a :class:`Contribution`."""
    flag = ContributionFlag.OK
    if cv is None:
        flag = ContributionFlag.MISSING
    elif rubric.discount_stale and cv.freshness_state is FreshnessState.STALE:
        flag = ContributionFlag.STALE
    elif rubric.min_confidence is not None and cv.provenance.confidence < rubric.min_confidence:
        flag = ContributionFlag.LOW_CONFIDENCE

    if flag is not ContributionFlag.OK:
        # MissingValueRule.ZERO: zero contribution + the flag, never a fabricated default. We still
        # surface the claim_id/value when a value exists (stale / low-confidence) for transparency.
        return Contribution(
            dimension=dimension,
            field_key=entry.field_key,
            claim_id=(cv.provenance.claim_id if cv is not None else None),
            value_json=(cv.value_json if cv is not None else None),
            factor=0.0,
            weight=entry.weight,
            contribution=0.0,
            flag=flag,
        )

    assert cv is not None  # flag is OK => a fresh, confident current_value exists
    factor = _apply_transform(entry.transform, cv.value_json, entry.params)
    return Contribution(
        dimension=dimension,
        field_key=entry.field_key,
        claim_id=cv.provenance.claim_id,
        value_json=cv.value_json,
        factor=factor,
        weight=entry.weight,
        contribution=factor * entry.weight,
        flag=ContributionFlag.OK,
    )


def _aggregate(sub: SubRubric, contributions: list[Contribution]) -> float:
    raw = sum(c.contribution for c in contributions)
    if not sub.normalize:
        return raw
    total = sub.total_weight
    return raw / total if total > 0 else 0.0


def score(
    rubric: ScoringRubric,
    current_values: Mapping[str, CurrentValue | None],
    *,
    entity_id: EntityId,
) -> ScoreResult:
    """Score one entity against ``rubric`` over ``current_values`` (``field_key -> CurrentValue`` or
    ``None`` when absent). **Pure, deterministic, no LLM** — the single scoring contract M6 runs at
    Pass A and M12 embeds in the handoff.

    Fit and Intent are aggregated independently and returned as distinct scores; ``contributions``
    enumerates every entry's ``(field_key, claim_id, value, weight, contribution)`` + flag, so the
    score is fully explainable and every nonzero contribution links a real ``claim_id``. Re-running
    with the same rubric + the same ``current_values`` yields byte-identical output.
    """
    contributions: list[Contribution] = []
    fit_contribs: list[Contribution] = []
    for entry in rubric.fit.entries:
        c = _score_entry(rubric, ScoreDimension.FIT, entry, current_values.get(entry.field_key))
        fit_contribs.append(c)
        contributions.append(c)
    intent_contribs: list[Contribution] = []
    for entry in rubric.intent.entries:
        c = _score_entry(rubric, ScoreDimension.INTENT, entry, current_values.get(entry.field_key))
        intent_contribs.append(c)
        contributions.append(c)

    return ScoreResult(
        entity_id=entity_id,
        rubric_version=rubric.version,
        fit_score=_aggregate(rubric.fit, fit_contribs),
        intent_score=_aggregate(rubric.intent, intent_contribs),
        contributions=tuple(contributions),
        tier_cutoffs=rubric.tier_cutoffs,
    )


def _as_core_score(value: float, contributions: tuple[Contribution, ...]) -> Score:
    total = sum(c.weight for c in contributions)
    components = tuple(
        ScoreComponent(
            name=c.field_key,
            weight=(c.weight / total) if total > 0 else 0.0,  # relative share, in [0,1]
            value=c.factor,
            evidence_claim_ids=((c.claim_id,) if c.claim_id is not None else ()),
        )
        for c in contributions
    )
    return Score(value=_clamp_unit(value), components=components)


# --- tiering (default cutoffs; M6 runs this on live data) -------------------
def fit_floor(cutoffs: TierCutoffs) -> float:
    """The ICP-relative **fit floor** — the lowest ``min_fit`` across the cutoff bands, or ``0.0``
    when no band sets one (the ICP set no bar). This is the single source for the "is this account
    fit enough?" threshold that both M5.3 import non-fit-flagging and M5.4 lookalike seeding gate on
    (D6: a non-fit anchor seeds non-fit lookalikes), so the two never drift. Pure; cutoffs are data
    (conventions §2)."""
    floors = [band.min_fit for band in cutoffs.bands]
    return min(floors) if floors else 0.0


def assign_tier(cutoffs: TierCutoffs, fit_score: float, intent_score: float) -> str:
    """Pure helper: the tier ``(fit_score, intent_score)`` lands in under ``cutoffs`` — the first
    band (in order) whose ``min_fit`` and ``min_intent`` are both cleared, else ``fallback_tier``.

    M3.4 ships this as the *default proposal*; **M6 runs it on the live distribution and the human
    adjusts the cutoffs at the checkpoint** (passing different cutoffs here re-tiers without
    touching the rubric — cutoffs are data, conventions §2 / D7). Out of scope here: running Pass A.
    """
    for band in cutoffs.bands:
        if fit_score >= band.min_fit and intent_score >= band.min_intent:
            return band.tier
    return cutoffs.fallback_tier


# --- validation against the field plan (M3.2) ------------------------------
def validate_rubric(rubric: ScoringRubric, field_plan: FieldPlan) -> None:
    """Reject a rubric that references fields the field plan does not carry, or that uses a
    ``deep``-tagged field as a Pass-A input (names every offender). The seam to M3.2: a rubric reads
    only what Pass A can actually compute, and **Intent inputs are the ``scoring``-tagged proxies**
    (Doc C §1) — a ``deep`` narrative field is not a Pass-A Intent input (ENG-121 acceptance).

    Both Fit and Intent entries must resolve to ``scoring``-pass fields: Pass A runs over every
    account cheaply, so anything the rubric reads there must be a Pass-A (scoring) field, never a
    ``deep`` one (which only exists after tiering).
    """
    active = {e.field.field_key for e in field_plan.fields}
    scoring = {e.field.field_key for e in field_plan.scoring_fields}
    diagnostics: list[str] = []
    dims = ((ScoreDimension.FIT, rubric.fit), (ScoreDimension.INTENT, rubric.intent))
    for dimension, sub in dims:
        for entry in sub.entries:
            if entry.field_key not in active:
                diagnostics.append(
                    f"{dimension.value} entry {entry.field_key!r} is not in the field plan "
                    "(not in the active field set)"
                )
            elif entry.field_key not in scoring:
                diagnostics.append(
                    f"{dimension.value} entry {entry.field_key!r} is a deep-pass field, not a "
                    "Pass-A scoring input (Doc C §1: scoring uses the cheap deterministic proxies)"
                )
    if diagnostics:
        raise RubricValidationError(tuple(diagnostics))


# --- disposition-feedback hook (model only; M13 implements the loop) --------
def reweighted(
    rubric: ScoringRubric,
    *,
    fit_weights: Mapping[str, float] | None = None,
    intent_weights: Mapping[str, float] | None = None,
    feedback_basis: Mapping[str, JsonValue] | None = None,
) -> ScoringRubric:
    """Return a **new rubric version** with updated entry weights and a recorded ``feedback_basis``
    — the versioned target the M13 disposition loop writes (substrate §9). Pure: it does not persist
    (M13 stores it as a new ``icp_spec`` version via ``create_icp_spec``). Unlisted entries keep
    their weight; only weights change (the reweighting loop tunes weights, not the field set)."""

    def _rewrite(sub: SubRubric, overrides: Mapping[str, float] | None) -> SubRubric:
        if not overrides:
            return sub
        return sub.model_copy(
            update={
                "entries": tuple(
                    e.model_copy(update={"weight": overrides[e.field_key]})
                    if e.field_key in overrides
                    else e
                    for e in sub.entries
                )
            }
        )

    return rubric.model_copy(
        update={
            "fit": _rewrite(rubric.fit, fit_weights),
            "intent": _rewrite(rubric.intent, intent_weights),
            "version": rubric.version + 1,
            "feedback_basis": dict(feedback_basis or {}),
        }
    )


# --- the ICP-spec slot: serialize / load (M3.1 owns the durable versioning) -
def rubric_to_slot(rubric: ScoringRubric) -> dict[str, JsonValue]:
    """Serialize a rubric to the JSON-able dict stored in ``icp_spec.scoring_rubric`` (M3.1). Pass
    the result as ``create_icp_spec(..., scoring_rubric=...)``; editing weights and re-creating the
    spec is how an append-only new rubric version is written."""
    return rubric.model_dump(mode="json")


def rubric_from_slot(slot: Mapping[str, JsonValue]) -> ScoringRubric | None:
    """Parse a rubric from an ``icp_spec.scoring_rubric`` slot, or ``None`` for the empty slot (an
    ICP spec with no rubric yet — empty is a valid state, not an error)."""
    if not slot:
        return None
    return ScoringRubric.model_validate(slot)


async def get_active_rubric(
    conn: AsyncConnection, client_id: str, icp_key: str
) -> ScoringRubric | None:
    """The rubric in the currently-active ICP spec for ``(client_id, icp_key)``, or ``None`` if no
    active spec exists or it carries no rubric."""
    spec = await get_active_icp(conn, client_id, icp_key)
    return rubric_from_slot(spec.scoring_rubric) if spec is not None else None


async def get_rubric_version(
    conn: AsyncConnection, client_id: str, icp_key: str, version: int
) -> ScoringRubric | None:
    """The rubric in a pinned ICP-spec version — the reproducibility seam: a campaign pinned to
    ``(client_id, icp_key, version)`` re-reads this exact rubric and so re-scores identically."""
    spec = await get_icp_version(conn, client_id, icp_key, version)
    return rubric_from_slot(spec.scoring_rubric) if spec is not None else None


# --- convenience: fetch current_values + score (for M6 / tests) ------------
async def score_entity(
    conn: AsyncConnection,
    rubric: ScoringRubric,
    entity_id: EntityId,
    *,
    scope: TenantScope,
) -> ScoreResult:
    """Convenience over the pure :func:`score`: fetch ``current_value`` for the rubric's fields and
    score one entity. The pure function is the contract; this lifts it over M1's merge read so a
    caller (and the tests) can score against the live store. **M6 owns Pass A orchestration** (the
    full list, tiering, budgets); this is the single-entity primitive it builds on. ``scope`` is
    required (M2.5 fail-closed): client-tuned scoring reads the tenant view, never another tenant's
    private claims."""
    keys = rubric.field_keys
    merged = await current_values(conn, [entity_id], keys, scope=scope)
    current: dict[str, CurrentValue | None] = {k: merged.get((entity_id, k)) for k in keys}
    return score(rubric, current, entity_id=entity_id)


__all__ = [
    "ScoreDimension",
    "ScoringTransform",
    "MissingValueRule",
    "ContributionFlag",
    "RubricEntry",
    "SubRubric",
    "TierBand",
    "TierCutoffs",
    "ScoringRubric",
    "Contribution",
    "ScoreResult",
    "RubricValidationError",
    "score",
    "assign_tier",
    "validate_rubric",
    "reweighted",
    "rubric_to_slot",
    "rubric_from_slot",
    "get_active_rubric",
    "get_rubric_version",
    "score_entity",
]
