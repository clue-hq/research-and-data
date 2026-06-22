"""The result + decision shapes the tier checkpoint exchanges (M6.4).

These are *references and decompositions*, never blobs (conventions §2):

* :class:`AccountScoreView` is the provisional, provenance-linked score the checkpoint reads back
  from the M6.3 score object (the fit/intent value plus the inspectable claim ids) — the pure input
  to :func:`~clue_research.discovery_scoring.tiering.engine.assign_tiers`.
* :class:`AccountTierView` is that view with its assigned ``tier`` — one row of the review payload.
* :class:`CheckpointReview` is the durable, re-presentable review surface the client sees at the
  suspension: proposed cutoffs, the tier distribution, per-account provisional scores with working
  evidence links, and the pre-run cost estimate.
* :class:`CheckpointDecision` is the ``resume(...)`` payload the client submits (adjust cutoffs /
  raise-lower the budget cap / approve / pause), parsed from the phase ``params`` the M7 state
  machine hands back.
* :class:`TierAssignment` is the persisted per-account decision Pass B (M8) + the audit trail read.
"""

from __future__ import annotations

from collections.abc import Mapping
from decimal import Decimal, InvalidOperation
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, JsonValue, ValidationError

from clue_research.core import ClaimId, CostCents, EntityId, Estimate
from clue_research.icp.rubric import TierCutoffs

# The key under which the M7 state machine threads the client's ``resume(...)`` decision into the
# phase ``params`` (substrate §10 secure-input). Absent ⟹ the initial durable suspension (no
# decision yet) — :meth:`CheckpointDecision.from_params` returns the empty decision.
CHECKPOINT_DECISION_PARAM = "checkpoint_decision"


class CheckpointAction(StrEnum):
    """The two terminal client actions the ``resume(...)`` contract accepts (the spec's
    ``action: approve|pause``). ``APPROVE`` resumes into Pass B (``deep``); ``PAUSE`` keeps the run
    durably suspended and resumable. The absence of an action is a third, implicit state —
    *awaiting* (the initial suspension / a cutoff-only adjustment) — modelled as
    ``CheckpointDecision.action is None`` rather than an enum member, so an empty decision never
    reads as a terminal one."""

    APPROVE = "approve"
    PAUSE = "pause"


class CheckpointStatus(StrEnum):
    """The checkpoint record's lifecycle (the spec's ``status: awaiting|resumed``). ``AWAITING`` is
    the durable suspension (initial, paused, or halted-over-cap); ``RESUMED`` is the approved,
    tiers-persisted decision that advances the run to ``deep``."""

    AWAITING = "awaiting"
    RESUMED = "resumed"


class AccountScoreView(BaseModel):
    """One account's provisional, provenance-linked score (read back from the M6.3 score object).

    ``fit`` / ``intent`` are the decomposed scores' ``[0,1]`` values; ``fit_claim_id`` /
    ``intent_claim_id`` reference the persisted ``account.scoring.fit`` / ``.intent`` claims (each
    inspectable to its component evidence), and ``evidence_claim_ids`` flattens the backing proxy
    claim ids behind both — so every score the client reviews links to its claims ("no score without
    its evidence"). The pure input to :func:`assign_tiers`; carries no tier itself."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    account_id: EntityId
    fit: float
    intent: float
    non_fit_flag: bool = False
    rubric_version: int = 0
    fit_claim_id: ClaimId | None = None
    intent_claim_id: ClaimId | None = None
    evidence_claim_ids: tuple[str, ...] = ()


class AccountTierView(AccountScoreView):
    """An :class:`AccountScoreView` plus the ``tier`` it was assigned — one row of the review
    payload. Tiering is a pure function of the view + cutoffs, so this is the score view with its
    deterministic verdict attached (never a re-score)."""

    tier: str

    @classmethod
    def from_view(cls, view: AccountScoreView, tier: str) -> AccountTierView:
        """Attach a ``tier`` to a scored view (no re-scoring; the score is carried verbatim)."""
        return cls(tier=tier, **view.model_dump())


class TierAssignment(BaseModel):
    """The persisted per-account tier decision (the durable seam Pass B / M8 + the audit trail).

    ``cutoff_version`` is the content-addressed version of the approved cutoffs (so a re-tier under
    new cutoffs is a new version, idempotent on ``(account_id, cutoff_version)``). ``tier_claim_id``
    references the persisted ``account.scoring.tier`` claim; ``written`` is ``False`` on an
    idempotent replay (the decision already existed for this ``(account, cutoff_version)``)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    account_id: EntityId
    tier: str
    cutoff_version: str
    fit_score: float
    intent_score: float
    tier_claim_id: ClaimId | None = None
    written: bool = False


class CheckpointReview(BaseModel):
    """The durable, re-presentable review payload surfaced at the ``tier_checkpoint`` suspension.

    Deterministic in (persisted scores × cutoffs × config), so a crash/restart re-presents byte-
    identical state (phase idempotency). ``accounts`` carries each provisional score with its
    working evidence links; ``estimate`` is the pre-run cost projection; ``projected_over_cap``
    flags the graceful-stop condition (projected spend exceeds the effective cap → the client raises
    the cap or tighten cutoffs). ``coverage`` is the M6.5 coverage-report hook (populated when M6.5
    lands; ``None`` until then) — surfacing it through this payload is M6.5's stated seam."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    status: CheckpointStatus
    proposed_cutoffs: TierCutoffs
    cutoff_version: str
    tier_distribution: dict[str, int]
    accounts: tuple[AccountTierView, ...]
    estimate: Estimate
    cap_cents: CostCents | None = None
    projected_over_cap: bool = False
    scored_count: int = 0
    coverage: JsonValue | None = None


class CheckpointDecision(BaseModel):
    """The client's ``resume(...)`` decision, parsed from the phase ``params`` (M7 secure-input).

    ``action`` (``None`` = no decision yet / a cutoff-only adjustment), an optional ``cutoffs``
    override (re-tiers + re-estimates without re-spending Pass A), and an optional
    ``budget_cap_cents`` (raise/lower the per-campaign cap for the over-cap check). Parsing is
    defensive: a malformed field degrades to its empty value rather than raising — a bad decision
    must not crash the durable phase (it just re-presents the review)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    action: CheckpointAction | None = None
    cutoffs: TierCutoffs | None = None
    budget_cap_cents: CostCents | None = None

    @classmethod
    def from_params(cls, params: Mapping[str, JsonValue]) -> CheckpointDecision:
        """Parse the decision out of the phase ``params`` (under :data:`CHECKPOINT_DECISION_PARAM`).

        Returns the empty decision (``action is None``) when no decision is present — the initial
        durable suspension. Each field is parsed defensively so a malformed payload re-presents the
        review rather than failing the phase."""
        raw = params.get(CHECKPOINT_DECISION_PARAM)
        if not isinstance(raw, Mapping):
            return cls()

        action: CheckpointAction | None = None
        action_raw = raw.get("action")
        if isinstance(action_raw, str):
            try:
                action = CheckpointAction(action_raw)
            except ValueError:
                action = None

        cutoffs: TierCutoffs | None = None
        cutoffs_raw = raw.get("cutoffs")
        if isinstance(cutoffs_raw, Mapping):
            try:
                cutoffs = TierCutoffs.model_validate(cutoffs_raw)
            except ValidationError:
                cutoffs = None

        cap: CostCents | None = None
        cap_raw = raw.get("budget_cap_cents")
        if isinstance(cap_raw, (int, float, str)) and not isinstance(cap_raw, bool):
            try:
                parsed = Decimal(str(cap_raw))
            except (InvalidOperation, ValueError):
                parsed = None
            # ``is_finite()`` is checked first (and short-circuits): ``Decimal(str(float("inf")))``
            # *succeeds* (yields ``Infinity``), and a ``NaN >= 0`` comparison itself signals — so
            # without this guard a non-finite cap would either raise here or fail the finite
            # ``CostCents`` constructor below, crashing the durable phase instead of degrading.
            if parsed is not None and parsed.is_finite() and parsed >= 0:
                cap = parsed

        return cls(action=action, cutoffs=cutoffs, budget_cap_cents=cap)
