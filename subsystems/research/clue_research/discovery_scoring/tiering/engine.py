"""The tiering engine (M6.4) — turn Pass-A scores into a tier decision + a pre-run cost estimate.

Where the cutoffs land *is the spend decision* (Pass B runs only on high tiers, depth scales with
tier), so this is deliberately a **pure policy over the stored score object**, not an agent — the
same ``current_value`` discipline as M6.3's scorer (substrate §9, conventions §2):

* :func:`assign_tiers` is the deterministic tier verdict — identical ``(scores, cutoffs)`` always
  yield identical tiers, built on M3.4's pure :func:`~clue_research.icp.rubric.assign_tier` —
  changing cutoffs alone re-tiers with **no** Pass-A re-spend and **no** new scoring claim.
* :func:`estimate_cost` is the pre-run estimate (Doc C §5): (accounts above cutoff per tier) ×
  (per-tier Pass-B band) → ``~M go deep → ~$X``. It re-computes from the stored distribution, so a
  cutoff adjustment re-estimates without re-spending Pass A.
* :func:`load_score_views` reads the M6.3 score object back (the decomposed fit/intent + the
  inspectable evidence links), scoped to *this* campaign's scoring run (D5-safe: a per-ICP read).
* :func:`persist_tier` writes the approved decision as one tenant-private ``account.scoring.tier``
  claim, idempotent on ``(account, cutoff_version)`` (the deterministic checkpoint ``run_id``) and
  ICP-scoped on supersession — exactly mirroring M6.3's score write (one live winner per ICP).

The durable suspend/resume primitive itself is M7's (this component only *implements* the
``tier_checkpoint`` phase behaviour); the integrated handler lives in
:mod:`clue_research.discovery_scoring.phases`.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping, Sequence
from decimal import Decimal

from pydantic import JsonValue
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_core import (
    Claim,
    ClaimId,
    EntityId,
    EntityType,
    Estimate,
    ExtractionMethod,
    ProjectRunId,
    ResearchMode,
    RunId,
    account_claim,
)
from clue_research.claimstore import (
    WorkspaceScope,
    claims_for,
    entities_with_field_claim,
)
from clue_research.discovery_scoring.claim_writes import write_icp_scoped_claim
from clue_research.discovery_scoring.scoring import FIT_FIELD, INTENT_FIELD
from clue_research.discovery_scoring.tiering.config import TieringConfig
from clue_research.discovery_scoring.tiering.results import AccountScoreView
from clue_research.discovery_scoring.tiering.selection import DiscoveryCriteriaAccountView
from clue_research.icp.rubric import TierCutoffs, assign_tier
from clue_research.identity import stamp_reuse, surviving_id

# The reserved (M1.3 / packs.py) tenant-private field the approved tier decision is persisted to —
# the same ``account.scoring.*`` family as the M6.3 fit/intent score object (so the reuse policy
# classifies it tenant-private and the fail-closed write boundary holds).
TIER_FIELD = "account.scoring.tier"
# The explicit-account research threshold includes the least account tier. Current score policies
# emit ``high``/``low`` while imported or client-authored policies may use a four-tier label. Keep
# this as shared policy data so every claim-id-backed provider seam admits tier 4 consistently.
ACCOUNT_RESEARCH_ELIGIBLE_TIERS = frozenset(
    {"top", "high", "standard", "low", "tier1", "tier2", "tier3", "tier4", "4"}
)
# Tier-decision consumers may be given an exact claim id whose provenance comes from any registered
# trust tier. Source tier 4 is the least-trusted supported tier, so this inclusive ceiling keeps it
# admissible while the claim model continues to enforce tier/method/source coherence.
TIER_CLAIM_MAX_SOURCE_TIER = 4


# --- pure: tiering + cost estimate ------------------------------------------
def cutoff_version(cutoffs: TierCutoffs) -> str:
    """A deterministic, content-addressed version label for a set of cutoffs.

    Stable for identical cutoffs and distinct when any band/floor/fallback changes — exactly the
    ``(account_id, cutoff_version)`` idempotency the spec keys tier rows on. A pure hash of the
    canonical cutoff JSON: re-tiering under the same cutoffs reuses the row (a no-op replay); a
    human adjustment yields a new version that supersedes the prior tier (one live winner per ICP).
    Cutoffs are data, not code (conventions §2 / D7), so the version travels with the data, not the
    rubric.
    """
    canonical = json.dumps(cutoffs.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
    return "v-" + hashlib.sha256(canonical.encode()).hexdigest()[:16]


def assign_tiers(views: Iterable[AccountScoreView], cutoffs: TierCutoffs) -> dict[EntityId, str]:
    """Map each account's decomposed fit/intent to a tier under ``cutoffs`` — the deterministic tier
    verdict (the spec's ``assign_tiers(scores, cutoffs) -> {account_id -> tier}``).

    Pure and total: built on M3.4's :func:`~clue_research.icp.rubric.assign_tier` (the first band,
    in order, whose ``min_fit`` **and** ``min_intent`` are both cleared, else ``fallback_tier``), so
    identical ``(views, cutoffs)`` always yield identical assignments and passing different cutoffs
    re-tiers without touching scoring. Not an agent — tiering is policy over scores (§9)."""
    return {view.account_id: assign_tier(cutoffs, view.fit, view.intent) for view in views}


def tier_distribution(assignments: Mapping[EntityId, str], cutoffs: TierCutoffs) -> dict[str, int]:
    """Count accounts per tier. Every tier the cutoffs *name* (each band + the fallback) appears,
    so an empty tier reads as ``0`` rather than vanishing — a clearer client-facing distribution and
    a stable estimate input. Insertion order follows the cutoff bands (most-selective first)."""
    counts: dict[str, int] = {band.tier: 0 for band in cutoffs.bands}
    counts.setdefault(cutoffs.fallback_tier, 0)
    for tier in assignments.values():
        counts[tier] = counts.get(tier, 0) + 1
    return counts


def estimate_cost(distribution: Mapping[str, int], config: TieringConfig) -> Estimate:
    """The pre-run cost estimate (Doc C §5): ``(accounts above cutoff per tier) × (per-tier Pass-B
    band)`` → projected deep count + estimated spend.

    A tier with no configured band is **not** deep-eligible (zero spend, zero projected-deep) — the
    two-pass discipline ("Pass B only on high tiers"). Pure over the distribution + the budget
    bands, so a cutoff adjustment re-estimates with no Pass-A re-spend. ``cost_per_account_cents``
    is the blended per-deep-account cost (``0`` when nothing goes deep)."""
    discovered = sum(distribution.values())
    projected_deep = 0
    estimated = Decimal(0)
    for tier, count in distribution.items():
        band = config.band_cents(tier)
        if band > 0 and count > 0:
            projected_deep += count
            estimated += band * count
    cost_per = (estimated / projected_deep) if projected_deep else Decimal(0)
    return Estimate(
        discovered_count=discovered,
        projected_deep_count=projected_deep,
        estimated_cost_cents=estimated,
        cost_per_account_cents=cost_per,
        confidence=config.estimate_confidence,
    )


# --- read the M6.3 score object back ----------------------------------------
def _score_value(claim: Claim | None) -> float:
    """The ``[0,1]`` score from a persisted score claim's ``value_json`` (``value`` at top level —
    the M6.3 write contract), or ``0.0`` when the claim/shape is absent (an empty score, never a
    fabricated one)."""
    if claim is None:
        return 0.0
    value_json = claim.value_json
    if isinstance(value_json, dict):
        value = value_json.get("value")
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return float(value)
    return 0.0


def _evidence_ids(*claims: Claim | None) -> tuple[str, ...]:
    """The flattened backing-proxy claim ids behind the given score claims (each score's
    ``components[*].evidence_claim_ids``), de-duplicated in first-seen order — the inspectable
    "each score back to its claims" links the checkpoint surfaces."""
    out: list[str] = []
    seen: set[str] = set()
    for claim in claims:
        if claim is None or not isinstance(claim.value_json, dict):
            continue
        components = claim.value_json.get("components")
        if not isinstance(components, list):
            continue
        for component in components:
            if not isinstance(component, dict):
                continue
            ids = component.get("evidence_claim_ids")
            if not isinstance(ids, list):
                continue
            for cid in ids:
                if isinstance(cid, str) and cid not in seen:
                    seen.add(cid)
                    out.append(cid)
    return tuple(out)


def _live_for_run(claims: Sequence[Claim], run_id: RunId) -> Claim | None:
    """The live claim written by ``run_id`` (the score this campaign's scoring phase produced)."""
    return next((c for c in claims if c.run_id == run_id), None)


async def load_score_views(
    conn: AsyncConnection, *, scoring_run: RunId, workspace_id: str
) -> list[AccountScoreView]:
    """The provisional :class:`AccountScoreView`s for the accounts scored in ``scoring_run``.

    Reads the M6.3 score object back from the store (never re-scores): the accounts carrying a live
    ``account.scoring.fit`` claim for this campaign's scoring run, each resolved through its
    ``merged_into`` chain and de-duplicated (a between-phase merge moves the truth to the survivor),
    with the fit/intent values + the inspectable evidence links. Scoped to ``workspace_id`` (the
    score
    object is tenant-private) and pinned to ``scoring_run`` (D5-safe: an account scored under many
    ICPs is read per its own run). Ordered by id for a deterministic review/distribution."""
    scope = WorkspaceScope.for_workspace(workspace_id)
    views: list[AccountScoreView] = []
    seen: set[EntityId] = set()
    for entity_id in await entities_with_field_claim(
        conn, FIT_FIELD, run_id=scoring_run, scope=scope
    ):
        survivor = await surviving_id(conn, entity_id, EntityType.ACCOUNT)
        if survivor in seen:
            continue
        seen.add(survivor)
        fit_claims = await claims_for(conn, survivor, FIT_FIELD, scope=scope)
        fit = _live_for_run(fit_claims, scoring_run)
        if fit is None:
            continue  # the live FIT claim for this run is on a pre-merge member — skip defensively
        intent_claims = await claims_for(conn, survivor, INTENT_FIELD, scope=scope)
        intent = _live_for_run(intent_claims, scoring_run)
        value_json = fit.value_json if isinstance(fit.value_json, dict) else {}
        rubric_version = value_json.get("rubric_version")
        views.append(
            AccountScoreView(
                account_id=survivor,
                fit=_score_value(fit),
                intent=_score_value(intent),
                non_fit_flag=bool(value_json.get("non_fit_flag", False)),
                rubric_version=rubric_version if isinstance(rubric_version, int) else 0,
                fit_claim_id=fit.id,
                intent_claim_id=intent.id if intent is not None else None,
                evidence_claim_ids=_evidence_ids(fit, intent),
            )
        )
    views.sort(key=lambda v: str(v.account_id))
    return views


# --- persist the approved tier decision -------------------------------------
async def persist_tier(
    conn: AsyncConnection,
    *,
    view: AccountScoreView,
    tier: str,
    cutoff_version: str,
    run_id: RunId,
    workspace_id: str,
    icp_key: str,
    icp_version: int,
    project_id: str | None = None,
    project_run_id: ProjectRunId | None = None,
) -> tuple[ClaimId, bool]:
    """Write one account's approved tier decision idempotently, returning ``(claim_id, written)``.

    Idempotency on ``(account, cutoff_version)`` is the deterministic checkpoint ``run_id`` (which
    encodes the cutoff version): an existing live tier claim for this ``run_id`` is reused
    (``written=False`` — no new row). A live tier from a *different* run of the **same ICP** (an
    earlier cutoff version) is **superseded** so the merged truth keeps one live tier per ICP
    (append-only history preserved); a tier from a *different* ICP is left untouched (D5). The claim
    is the human-approved decision at the checkpoint (``extraction_method=human``, no resolver URL)
    and tenant-private (``stamp_reuse`` — fail-closed on the reserved ``account.scoring.*`` set).

    ``project_id`` (FI-2 §6.4) is the project whose checkpoint approved this tier. Stamped into
    ``value_json`` — the claim row has no project column (FI-2 §1.3) — it becomes the *project* leg
    of the supersede key, so a second project tiering the same account under the same ICP now
    **coexists** with the first's tier instead of destroying it. ``project_run_id`` identifies the
    exact approved run and stamps the same ``disposition=selected`` authority consumed by account
    profiling. The discovery-selection path already carries both values; this aligns the numeric
    scoring path. Within one project, successive cutoffs supersede exactly as before. ``None`` is
    the legacy shape — such a tier is absorbed by the first project that re-tiers the account (see
    :func:`~clue_research.claimstore.project_supersedable`).

    The read/replay/supersede-by-ICP sequence is the shared :func:`write_icp_scoped_claim` protocol
    (the same M6.3's score write uses); this builds only the tier claim's shape + value."""
    value_json: dict[str, JsonValue] = {
        "tier": tier,
        "cutoff_version": cutoff_version,
        "fit_score": view.fit,
        "intent_score": view.intent,
        "non_fit_flag": view.non_fit_flag,
        "fit_claim_id": str(view.fit_claim_id) if view.fit_claim_id is not None else None,
        "intent_claim_id": (
            str(view.intent_claim_id) if view.intent_claim_id is not None else None
        ),
        "rubric_version": view.rubric_version,
        "icp_key": icp_key,
        "icp_version": icp_version,
    }
    if project_id is not None:
        value_json["project_id"] = project_id
    if project_run_id is not None:
        value_json["project_run_id"] = str(project_run_id)
        value_json["disposition"] = "selected"
    tier_claim = stamp_reuse(
        account_claim(
            entity_id=view.account_id,
            field_key=TIER_FIELD,
            value_json=value_json,
            source_tier=1,
            extraction_method=ExtractionMethod.HUMAN,
            confidence=1.0,
            run_id=run_id,
            research_mode=ResearchMode.ACCOUNT_PROFILING,
        ),
        workspace_id=workspace_id,
    )
    return await write_icp_scoped_claim(
        conn,
        tier_claim,
        run_id=run_id,
        icp_key=icp_key,
        scope=WorkspaceScope.for_workspace(workspace_id),
    )


async def persist_discovery_selection_tier(
    conn: AsyncConnection,
    *,
    view: DiscoveryCriteriaAccountView,
    tier: str,
    selection_policy_version: str,
    decision_version: str,
    discovery_batch_id: str,
    discovery_seal_sha256: str,
    project_run_id: ProjectRunId,
    run_id: RunId,
    workspace_id: str,
    icp_key: str,
    icp_version: int,
    project_id: str | None = None,
) -> tuple[ClaimId, bool]:
    """Persist the human approval over a criterion-selected account without synthetic scores.

    ``project_id`` (FI-2 §6.4) is stamped alongside the existing ``project_run_id`` pin. It changes
    no supersession here — this path is already pinned to the exact project run, which is strictly
    narrower — but it keeps this writer *out* of the unstamped class that
    :func:`~clue_research.claimstore.project_supersedable` is allowed to absorb, and lets the
    read side (``deep.composition._live_tier_for_project``) tell "this project's selection tier"
    from "some other project's". Optional only so existing callers stay valid; every caller has a
    project and should pass it."""

    value_json: dict[str, JsonValue] = {
        "tier": tier,
        "decision_basis": "discovery_criteria",
        "selection_policy_version": selection_policy_version,
        "decision_version": decision_version,
        # The existing field contract requires this version slot. In criteria mode it is
        # the content-addressed human selection decision, not a numeric-score cutoff.
        "cutoff_version": decision_version,
        "discovery_batch_id": discovery_batch_id,
        "discovery_seal_sha256": discovery_seal_sha256,
        "project_run_id": str(project_run_id),
        "disposition": view.disposition.value,
        "evidence_claim_ids": [str(value) for value in view.evidence_claim_ids],
        "icp_key": icp_key,
        "icp_version": icp_version,
    }
    if project_id is not None:
        value_json["project_id"] = project_id
    tier_claim = stamp_reuse(
        account_claim(
            entity_id=view.account_id,
            field_key=TIER_FIELD,
            value_json=value_json,
            source_tier=1,
            extraction_method=ExtractionMethod.HUMAN,
            confidence=1.0,
            run_id=run_id,
            research_mode=ResearchMode.ACCOUNT_PROFILING,
        ),
        workspace_id=workspace_id,
    )
    return await write_icp_scoped_claim(
        conn,
        tier_claim,
        run_id=run_id,
        icp_key=icp_key,
        scope=WorkspaceScope.for_workspace(workspace_id),
    )


__all__ = [
    "TIER_FIELD",
    "cutoff_version",
    "assign_tiers",
    "tier_distribution",
    "estimate_cost",
    "load_score_views",
    "persist_tier",
    "persist_discovery_selection_tier",
]
