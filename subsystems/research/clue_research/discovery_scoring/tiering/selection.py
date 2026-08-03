"""Explicit no-numeric-scoring policy over one immutable D5 discovery seal.

This module never calls a provider and never manufactures fit/intent values.  It classifies the
exact sealed account set from the Exa-style criterion observations already preserved as discovery
claims, while treating terminally missing/conflicting required account fields as a hold.  The
result is the input to the existing human tier checkpoint, not an automatic deep-research grant.
"""

from __future__ import annotations

import hashlib
import json
import unicodedata
from collections.abc import Mapping, Sequence
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, JsonValue, model_validator
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_core import (
    Claim,
    ClaimId,
    DiscoveryEvaluationState,
    DiscoveryFieldResolution,
    DiscoveryFieldResolutionState,
    EntityId,
    SealedDiscoveryAccounts,
)
from clue_research.claimstore import WorkspaceScope, claims_by_ids

DISCOVERY_PROVENANCE_FIELD = "core.discovery_provenance"


class ScoringMode(StrEnum):
    ENABLED = "enabled"
    DISABLED = "disabled"


class SelectionMode(StrEnum):
    SCORING_RUBRIC = "scoring_rubric"
    DISCOVERY_CRITERIA = "discovery_criteria"


class DiscoverySelectionDisposition(StrEnum):
    SELECTED = "selected"
    HOLD = "hold"
    EXCLUDED = "excluded"


class DiscoveryCriterionDecision(StrEnum):
    YES = "yes"
    NO = "no"
    UNCLEAR = "unclear"
    MISSING = "missing"


def _normalize(value: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", value).split())


class DiscoverySelectionPolicy(BaseModel):
    """Typed interpretation of the ICP's versioned discovery selection controls."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    scoring_mode: ScoringMode = ScoringMode.ENABLED
    selection_mode: SelectionMode = SelectionMode.SCORING_RUBRIC
    required_criteria: tuple[str, ...] = ()
    approved_tier: str = "high"

    @model_validator(mode="after")
    def _coherent_modes(self) -> DiscoverySelectionPolicy:
        disabled = self.scoring_mode is ScoringMode.DISABLED
        criteria = self.selection_mode is SelectionMode.DISCOVERY_CRITERIA
        if disabled != criteria:
            raise ValueError(
                "scoring_mode='disabled' and selection_mode='discovery_criteria' must be set "
                "together"
            )
        if disabled and not self.required_criteria:
            raise ValueError(
                "discovery-criteria selection requires at least one must-have criterion"
            )
        if not self.approved_tier.strip():
            raise ValueError("approved_tier must not be empty")
        if len(self.required_criteria) != len(set(self.required_criteria)):
            raise ValueError("must-have discovery criteria must be unique")
        return self

    @classmethod
    def from_slot(cls, slot: Mapping[str, JsonValue]) -> DiscoverySelectionPolicy:
        scoring_raw = slot.get("scoring_mode", ScoringMode.ENABLED.value)
        selection_raw = slot.get("selection_mode", SelectionMode.SCORING_RUBRIC.value)
        criteria_raw = slot.get("must_have_criteria", [])
        tier_raw = slot.get("approved_tier", "high")
        if not isinstance(scoring_raw, str) or not isinstance(selection_raw, str):
            raise ValueError("discovery scoring/selection modes must be strings")
        if not isinstance(criteria_raw, list):
            raise ValueError("must_have_criteria must be a list of non-empty strings")
        criteria: list[str] = []
        for value in criteria_raw:
            if not isinstance(value, str) or not value.strip():
                raise ValueError("must_have_criteria must be a list of non-empty strings")
            criteria.append(value)
        if not isinstance(tier_raw, str):
            raise ValueError("approved_tier must be a string")
        try:
            scoring_mode = ScoringMode(scoring_raw)
            selection_mode = SelectionMode(selection_raw)
        except ValueError as exc:
            raise ValueError("unsupported discovery scoring/selection mode") from exc
        return cls(
            scoring_mode=scoring_mode,
            selection_mode=selection_mode,
            required_criteria=tuple(_normalize(value) for value in criteria),
            approved_tier=tier_raw.strip(),
        )

    @property
    def policy_version(self) -> str:
        canonical = json.dumps(self.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
        return "selection-" + hashlib.sha256(canonical.encode()).hexdigest()[:16]


class DiscoveryCriterionReference(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    url: str
    title: str | None = None
    snippet: str | None = None


class DiscoveryCriterionObservation(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    claim_id: ClaimId
    satisfied: DiscoveryEvaluationState
    reasoning: str
    references: tuple[DiscoveryCriterionReference, ...] = ()


class DiscoveryCriterionReview(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    criterion: str
    decision: DiscoveryCriterionDecision
    observations: tuple[DiscoveryCriterionObservation, ...] = ()


class DiscoveryCriteriaAccountView(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    account_id: EntityId
    disposition: DiscoverySelectionDisposition
    criteria: tuple[DiscoveryCriterionReview, ...]
    required_field_states: dict[str, DiscoveryFieldResolutionState]
    hold_reasons: tuple[str, ...] = ()
    evidence_claim_ids: tuple[ClaimId, ...] = ()


class DiscoveryCriteriaSelection(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    policy_version: str
    accounts: tuple[DiscoveryCriteriaAccountView, ...]
    distribution: dict[str, int]


def _reference(raw: object) -> DiscoveryCriterionReference | None:
    if not isinstance(raw, Mapping):
        return None
    url = raw.get("url")
    if not isinstance(url, str) or not url.strip():
        return None
    title = raw.get("title")
    snippet = raw.get("snippet")
    return DiscoveryCriterionReference(
        url=url,
        title=title if isinstance(title, str) else None,
        snippet=snippet if isinstance(snippet, str) else None,
    )


def _claim_observations(
    claim: Claim, required: set[str]
) -> dict[str, list[DiscoveryCriterionObservation]]:
    value = claim.value_json
    if claim.field_key != DISCOVERY_PROVENANCE_FIELD or not isinstance(value, Mapping):
        return {}
    evidence = value.get("evidence")
    if not isinstance(evidence, Mapping):
        return {}
    evaluations = evidence.get("evaluations")
    if not isinstance(evaluations, list):
        return {}
    out: dict[str, list[DiscoveryCriterionObservation]] = {}
    for raw in evaluations:
        if not isinstance(raw, Mapping):
            continue
        criterion = raw.get("criterion")
        satisfied = raw.get("satisfied")
        reasoning = raw.get("reasoning")
        if not isinstance(criterion, str) or not isinstance(satisfied, str):
            continue
        normalized = _normalize(criterion)
        if normalized not in required:
            continue
        try:
            state = DiscoveryEvaluationState(satisfied)
        except ValueError:
            continue
        refs_raw = raw.get("references")
        reference_values = refs_raw if isinstance(refs_raw, list) else []
        references = tuple(
            reference
            for reference in (_reference(value) for value in reference_values)
            if reference is not None
        )
        out.setdefault(normalized, []).append(
            DiscoveryCriterionObservation(
                claim_id=claim.id,
                satisfied=state,
                reasoning=reasoning if isinstance(reasoning, str) else "",
                references=references,
            )
        )
    return out


def _criterion_review(
    criterion: str, observations: Sequence[DiscoveryCriterionObservation]
) -> DiscoveryCriterionReview:
    states = {observation.satisfied for observation in observations}
    if DiscoveryEvaluationState.NO in states:
        decision = DiscoveryCriterionDecision.NO
    elif DiscoveryEvaluationState.UNCLEAR in states:
        decision = DiscoveryCriterionDecision.UNCLEAR
    elif DiscoveryEvaluationState.YES in states:
        decision = DiscoveryCriterionDecision.YES
    else:
        decision = DiscoveryCriterionDecision.MISSING
    return DiscoveryCriterionReview(
        criterion=criterion,
        decision=decision,
        observations=tuple(observations),
    )


def classify_required_criteria_claims(
    *, claims: Sequence[Claim], required_criteria: Sequence[str]
) -> tuple[DiscoveryCriterionReview, ...]:
    """Classify one account's discovery claims without requiring a D5 seal.

    The pre-seal required-field waterfall uses the same criterion interpretation as the later
    scoring-disabled selection phase. Keeping this one pure classifier prevents the spend gate and
    checkpoint from disagreeing about ``yes`` / ``no`` / ``unclear`` evidence.
    """

    normalized = tuple(_normalize(value) for value in required_criteria)
    if not normalized or len(normalized) != len(set(normalized)):
        raise ValueError("required discovery criteria must be non-empty and unique")
    required = set(normalized)
    observations: dict[str, list[DiscoveryCriterionObservation]] = {
        criterion: [] for criterion in normalized
    }
    for claim in claims:
        for criterion, values in _claim_observations(claim, required).items():
            observations[criterion].extend(values)
    return tuple(_criterion_review(criterion, observations[criterion]) for criterion in normalized)


def classify_discovery_criteria(
    *,
    sealed: SealedDiscoveryAccounts,
    claims: Mapping[ClaimId, Claim],
    policy: DiscoverySelectionPolicy,
) -> DiscoveryCriteriaSelection:
    """Classify only the accounts, claims and required-field decisions frozen by ``sealed``."""

    if policy.scoring_mode is not ScoringMode.DISABLED:
        raise ValueError("discovery-criteria classification requires disabled numeric scoring")
    required = set(policy.required_criteria)
    sealed_required = {_normalize(value) for value in sealed.required_criteria}
    if required != sealed_required:
        raise ValueError(
            "discovery selection criteria do not exactly match the immutable discovery plan"
        )
    resolutions: dict[EntityId, dict[str, DiscoveryFieldResolution]] = {}
    for resolution in sealed.field_resolutions:
        resolutions.setdefault(resolution.account_entity_id, {})[
            str(resolution.logical_field_key)
        ] = resolution

    rows: list[DiscoveryCriteriaAccountView] = []
    for account_id in sealed.account_ids:
        evidence_ids: list[ClaimId] = []
        account_claims: list[Claim] = []
        for claim_id in sealed.claim_ids:
            claim = claims.get(claim_id)
            if claim is None or claim.entity_id != account_id:
                continue
            parsed = _claim_observations(claim, required)
            if not parsed:
                continue
            evidence_ids.append(claim.id)
            account_claims.append(claim)

        criterion_rows = classify_required_criteria_claims(
            claims=account_claims,
            required_criteria=policy.required_criteria,
        )
        field_states: dict[str, DiscoveryFieldResolutionState] = {}
        hold_reasons: list[str] = []
        account_resolutions = resolutions.get(account_id, {})
        for field_key in sealed.required_account_fields:
            key = str(field_key)
            account_resolution = account_resolutions.get(key)
            if account_resolution is None:
                hold_reasons.append(f"required_field_missing_decision:{key}")
                continue
            field_states[key] = account_resolution.state
            if account_resolution.state is not DiscoveryFieldResolutionState.RESOLVED:
                hold_reasons.append(f"required_field_{account_resolution.state.value}:{key}")

        criterion_decisions = {row.decision for row in criterion_rows}
        if DiscoveryCriterionDecision.NO in criterion_decisions:
            disposition = DiscoverySelectionDisposition.EXCLUDED
        elif (
            DiscoveryCriterionDecision.UNCLEAR in criterion_decisions
            or DiscoveryCriterionDecision.MISSING in criterion_decisions
            or hold_reasons
        ):
            disposition = DiscoverySelectionDisposition.HOLD
        else:
            disposition = DiscoverySelectionDisposition.SELECTED

        for criterion_row in criterion_rows:
            if criterion_row.decision is not DiscoveryCriterionDecision.YES:
                hold_reasons.append(
                    f"criterion_{criterion_row.decision.value}:{criterion_row.criterion}"
                )
        rows.append(
            DiscoveryCriteriaAccountView(
                account_id=account_id,
                disposition=disposition,
                criteria=criterion_rows,
                required_field_states=field_states,
                hold_reasons=tuple(hold_reasons),
                evidence_claim_ids=tuple(dict.fromkeys(evidence_ids)),
            )
        )

    rows.sort(key=lambda account_view: str(account_view.account_id))
    distribution = {value.value: 0 for value in DiscoverySelectionDisposition}
    for account_view in rows:
        distribution[account_view.disposition.value] += 1
    return DiscoveryCriteriaSelection(
        policy_version=policy.policy_version,
        accounts=tuple(rows),
        distribution=distribution,
    )


async def load_discovery_criteria_selection(
    conn: AsyncConnection,
    *,
    sealed: SealedDiscoveryAccounts,
    workspace_id: str,
    policy: DiscoverySelectionPolicy,
) -> DiscoveryCriteriaSelection:
    claims = await claims_by_ids(
        conn,
        sealed.claim_ids,
        scope=WorkspaceScope.for_workspace(workspace_id),
        include_superseded=True,
    )
    return classify_discovery_criteria(sealed=sealed, claims=claims, policy=policy)


def selection_decision_version(
    *, policy_version: str, seal_sha256: str, approved_account_ids: Sequence[EntityId]
) -> str:
    canonical = json.dumps(
        {
            "policy_version": policy_version,
            "seal_sha256": seal_sha256,
            "approved_account_ids": sorted(str(value) for value in approved_account_ids),
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return "decision-" + hashlib.sha256(canonical.encode()).hexdigest()[:16]


__all__ = [
    "DiscoveryCriteriaAccountView",
    "DiscoveryCriteriaSelection",
    "DiscoveryCriterionDecision",
    "DiscoveryCriterionObservation",
    "DiscoveryCriterionReference",
    "DiscoveryCriterionReview",
    "DiscoverySelectionDisposition",
    "DiscoverySelectionPolicy",
    "ScoringMode",
    "SelectionMode",
    "classify_discovery_criteria",
    "classify_required_criteria_claims",
    "load_discovery_criteria_selection",
    "selection_decision_version",
]
