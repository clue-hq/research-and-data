"""The result shapes the Pass-A scoring engine returns (M6.3).

These are *references and decompositions*, never blobs (conventions §2): :class:`AccountScore` is
the provenance-backed score object — the decomposed Fit/Intent (each a ``core.Score`` carrying its
backing claim ids) plus the persisted score-claim ids — exactly the Output-1 primitive
``account_handoff`` consumes (D1). :class:`SourceYieldRow` is the per-``(source, field_class)``
yield the engine measured (Doc C §6). :class:`AccountScoringOutcome` is the per-account engine
return: the score, whether a new claim was written (vs an idempotent replay), and the yield emitted.
"""

from __future__ import annotations

from decimal import Decimal

from pydantic import BaseModel, ConfigDict

from clue_core import ClaimId, CostCents, EntityId, FieldClass, Score


class SourceYieldRow(BaseModel):
    """Per-``(source_key, field_class)`` yield from one account's scoring-field fills (Doc C §6).

    ``claims_total`` is how many claims the source produced, ``fields_filled`` how many scoring
    fields it *confidently* won, ``cost_cents`` what it cost. Pass A *emits* this (the learning loop
    M13 consumes it); it does not reweight on it here.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    source_key: str
    field_class: FieldClass
    claims_total: int = 0
    fields_filled: int = 0
    cost_cents: CostCents = Decimal(0)


class AccountScore(BaseModel):
    """The decomposed, provenance-backed score object for one account (Output 1; substrate §9).

    ``fit`` / ``intent`` are distinct ``core.Score``s (never one collapsed number), each with its
    per-sub-score components and ``evidence_claim_ids``. ``evidence`` is the flattened
    ``{sub-score field_key -> backing claim ids}`` index (empty tuple for a missing/flagged input —
    a correct empty, never a fabricated proxy). ``non_fit_flag`` realizes D6 (flag-and-proceed below
    the ICP's Fit floor). ``fit_claim_id`` / ``intent_claim_id`` reference the persisted
    ``account.scoring.fit`` / ``account.scoring.intent`` claims (tenant-private).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    account_id: EntityId
    product_id: str | None = None
    rubric_version: int
    fit: Score
    intent: Score
    non_fit_flag: bool = False
    evidence: dict[str, tuple[ClaimId, ...]] = {}
    fit_claim_id: ClaimId | None = None
    intent_claim_id: ClaimId | None = None
    cost_cents: CostCents = Decimal(0)


class AccountScoringOutcome(BaseModel):
    """The per-account engine return: the score, the write disposition, and the yield it produced.

    ``written`` is ``True`` when this call wrote a *new* score claim and ``False`` on an idempotent
    replay (the score already existed for this ``(account, rubric_version)``) — so a re-run is
    distinguishable from first-scoring while ``score`` is identical either way. ``yield_steps`` are
    the per-source rows the phase handler aggregates into ``source_yield`` telemetry.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    account_id: EntityId
    score: AccountScore
    written: bool
    yield_steps: tuple[SourceYieldRow, ...] = ()
    cost_cents: CostCents = Decimal(0)
