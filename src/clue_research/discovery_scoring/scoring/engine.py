"""The Pass-A scoring engine (M6.3) — Output 1, cheaply and deterministically.

For every admitted account (discovered or imported — both converge at the M6.2 gate), this computes
a decomposed, explainable, provenance-backed **fit + intent** score: it fills the ICP's scoring-pass
proxy fields via the tier-1–3 waterfall (deterministic-first, *no LLM* — Doc C §1 / substrate §5a),
runs the **already-built** pure scorer (``icp.rubric.score`` / ``score_entity``, M3.4), and persists
the score as two tenant-private claims on the reserved ``account.scoring.fit`` / ``.intent`` fields,
each carrying the backing claim ids ("no score without its evidence"). It is *orchestration over the
substrate*, not a new scorer: the scoring math, the rubric model, and the ``core.Score`` projection
all live in M3.4; the waterfall, idempotency, and reuse-stamping all live in M1/M2/M4.

Design seams (conventions §2):

* **Enumeration is store-derived, campaign-scoped.** ``account_entity`` rows are global (cross-
  client); the accounts *this* campaign admitted are exactly those carrying a
  ``core.discovery_provenance`` claim for the campaign's discovery ``run_id`` (the convergence
  contract M6.2 emits) — so the engine reads them back, never holds a list across phases.
* **Deterministic-first is enforced, not hoped.** :func:`pass_a_fill_fields` strips any tier-4
  source from each scoring field's plan (``ScoringConfig.max_source_tier``), so a tier-4/LLM
  resolver bound for the deep pass can never be invoked at Pass A.
* **Idempotency is the deterministic ``run_id``.** The waterfall dedups input claims on
  ``(entity, field, source, run)``; the score write dedups on the same ``run_id`` (which encodes the
  ICP version ⟺ the rubric version), so a re-entered SCORING phase writes no new claim and yields a
  byte-identical score. A *new* rubric version (a new ICP version → a new ``run_id``) supersedes the
  prior score so the merged ``current_value`` keeps one live winner.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from decimal import Decimal

from pydantic import JsonValue
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_core import (
    ClaimId,
    EntityId,
    EntityType,
    ExtractionMethod,
    FieldClass,
    FieldDef,
    ResearchMode,
    RunId,
    Score,
    account_claim,
    classify_field_key,
)
from clue_research.claimstore import (
    TenantScope,
    entities_with_field_claim,
)
from clue_research.discovery_scoring.claim_writes import write_icp_scoped_claim
from clue_research.discovery_scoring.gate import DISCOVERY_PROVENANCE_FIELD
from clue_research.discovery_scoring.scoring.results import (
    AccountScore,
    AccountScoringOutcome,
    SourceYieldRow,
)
from clue_research.icp.compiler import FieldPlan
from clue_research.icp.rubric import ScoreResult, ScoringRubric, score_entity
from clue_research.identity import get_account, stamp_reuse, surviving_id
from clue_research.sources import (
    DEFAULT_CONFIDENCE_THRESHOLDS,
    ConfidenceThresholds,
    WaterfallResult,
    get_source,
    resolve_fields,
)

# The reserved (M1.3 / ENG-165 W4) tenant-private fields the decomposed score is persisted to.
FIT_FIELD = "account.scoring.fit"
INTENT_FIELD = "account.scoring.intent"


async def admitted_account_ids(
    conn: AsyncConnection, *, run_id: RunId, scope: TenantScope
) -> list[EntityId]:
    """The surviving account ids admitted in the discovery ``run_id`` — the Pass-A score set.

    Derived from the store, not held across phases: an admitted account carries a
    ``core.discovery_provenance`` claim for the campaign's discovery run (M6.2's convergence
    contract). Each id is resolved through its ``merged_into`` chain (a between-phase merge moves
    the truth to the survivor) and de-duplicated, so two candidates that resolved to one entity are
    scored once.
    """
    out: list[EntityId] = []
    seen: set[EntityId] = set()
    for entity_id in await entities_with_field_claim(
        conn, DISCOVERY_PROVENANCE_FIELD, run_id=run_id, scope=scope
    ):
        survivor = await surviving_id(conn, entity_id, EntityType.ACCOUNT)
        if survivor not in seen:
            seen.add(survivor)
            out.append(survivor)
    return out


async def pass_a_fill_fields(
    conn: AsyncConnection,
    field_plan: FieldPlan,
    rubric: ScoringRubric,
    *,
    max_source_tier: int,
) -> list[FieldDef]:
    """The scoring-pass ``FieldDef``s to fill for one account, tier-capped to deterministic tiers.

    Only the proxies the rubric actually reads are filled (filling a scoring field the rubric
    ignores is wasted Pass-A spend — D7), and the reserved ``account.scoring.*`` *outputs* are
    excluded (empty ``tier_plan`` — they are written, not resolved). Each kept field's ``tier_plan``
    is stripped of sources above ``max_source_tier`` (3) so Pass A never invokes a tier-4/LLM
    resolver (a missing/unregistered source is left in — the waterfall then yields an empty, flagged
    field, never a fabricated proxy).
    """
    wanted = set(rubric.field_keys)
    tier_cache: dict[str, int | None] = {}
    out: list[FieldDef] = []
    for entry in field_plan.scoring_fields:
        fd = entry.field
        if fd.field_key not in wanted or not fd.tier_plan:
            continue
        kept: list[str] = []
        for source_key in fd.tier_plan:
            if source_key not in tier_cache:
                manifest = await get_source(conn, source_key)
                tier_cache[source_key] = manifest.tier if manifest is not None else None
            tier = tier_cache[source_key]
            if tier is None or tier <= max_source_tier:
                kept.append(source_key)
        out.append(fd.model_copy(update={"tier_plan": tuple(kept)}))
    return out


async def score_account(
    conn: AsyncConnection,
    account_id: EntityId,
    *,
    rubric: ScoringRubric,
    fill_fields: Sequence[FieldDef],
    run_id: RunId,
    client_id: str,
    icp_key: str,
    icp_version: int,
    budget_envelope: Decimal | None = None,
    thresholds: ConfidenceThresholds = DEFAULT_CONFIDENCE_THRESHOLDS,
) -> AccountScoringOutcome:
    """Fill, score, and persist one account's Pass-A score object (idempotent on ``run_id``).

    Steps: (1) fill ``fill_fields`` via the tier-1–3 waterfall (writes the proxy claims itself,
    idempotent on ``(entity, field, source, run)``, reuse-stamped); (2) run the pure scorer over the
    merged ``current_value`` (tenant-scoped); (3) write the decomposed fit/intent ``core.Score`` —
    each component linking its evidence claim ids — to ``account.scoring.fit`` / ``.intent`` as
    tenant-private claims, superseding any prior-version score. Returns the score object + whether a
    new claim was written (``False`` = idempotent replay) + the per-source yield it produced.
    """
    account = await get_account(conn, account_id)
    if account is None:
        raise ValueError(f"cannot score unknown account_entity {account_id}")

    results: list[WaterfallResult] = []
    if fill_fields:
        results = await resolve_fields(
            conn,
            account.as_entity(),
            list(fill_fields),
            mode=ResearchMode.ACCOUNT_PROFILING,
            run_id=run_id,
            tenant_id=client_id,
            budget_envelope=budget_envelope,
            thresholds=thresholds,
            idempotent=True,
        )

    result = await score_entity(conn, rubric, account_id, scope=TenantScope.for_tenant(client_id))
    fit = result.as_fit_score()
    intent = result.as_intent_score()
    non_fit_flag = rubric.fit_floor is not None and result.fit_score < rubric.fit_floor

    fit_claim_id, fit_written = await _write_score_object(
        conn,
        entity_id=account_id,
        field_key=FIT_FIELD,
        value_json=_fit_value_json(
            fit, rubric, non_fit_flag=non_fit_flag, icp_key=icp_key, icp_version=icp_version
        ),
        run_id=run_id,
        client_id=client_id,
        icp_key=icp_key,
    )
    intent_claim_id, intent_written = await _write_score_object(
        conn,
        entity_id=account_id,
        field_key=INTENT_FIELD,
        value_json=_intent_value_json(intent, rubric, icp_key=icp_key, icp_version=icp_version),
        run_id=run_id,
        client_id=client_id,
        icp_key=icp_key,
    )

    cost = sum((r.total_cost_cents for r in results), Decimal(0))
    score = AccountScore(
        account_id=account_id,
        rubric_version=result.rubric_version,
        fit=fit,
        intent=intent,
        non_fit_flag=non_fit_flag,
        evidence=_evidence_index(result),
        fit_claim_id=fit_claim_id,
        intent_claim_id=intent_claim_id,
        cost_cents=cost,
    )
    return AccountScoringOutcome(
        account_id=account_id,
        score=score,
        written=fit_written or intent_written,
        yield_steps=tuple(_yield_steps(results)),
        cost_cents=cost,
    )


def aggregate_yield(rows: Iterable[SourceYieldRow]) -> list[SourceYieldRow]:
    """Sum per-account :class:`SourceYieldRow`s into one row per ``(source_key, field_class)`` — the
    run-level per-source yield the phase handler emits to ``source_yield`` (Doc C §6)."""
    agg: dict[tuple[str, FieldClass], _YieldAcc] = {}
    for row in rows:
        acc = agg.setdefault((row.source_key, row.field_class), _YieldAcc())
        acc.claims_total += row.claims_total
        acc.fields_filled += row.fields_filled
        acc.cost_cents += row.cost_cents
    return [
        SourceYieldRow(
            source_key=source_key,
            field_class=field_class,
            claims_total=acc.claims_total,
            fields_filled=acc.fields_filled,
            cost_cents=acc.cost_cents,
        )
        for (source_key, field_class), acc in agg.items()
    ]


# --- helpers ---------------------------------------------------------------
@dataclass
class _YieldAcc:
    claims_total: int = 0
    fields_filled: int = 0
    cost_cents: Decimal = field(default_factory=lambda: Decimal(0))


def _evidence_index(result: ScoreResult) -> dict[str, tuple[ClaimId, ...]]:
    """The ``{sub-score field_key -> backing claim ids}`` index — empty for a missing/flagged input
    (a correct empty, never a fabricated proxy). One entry per scored field; a field contributing to
    both Fit and Intent unions its (identical) evidence."""
    index: dict[str, list[ClaimId]] = {}
    for contribution in result.contributions:
        ids = index.setdefault(contribution.field_key, [])
        if contribution.claim_id is not None and contribution.claim_id not in ids:
            ids.append(contribution.claim_id)
    return {field_key: tuple(ids) for field_key, ids in index.items()}


def _yield_steps(results: Sequence[WaterfallResult]) -> list[SourceYieldRow]:
    """Fold one account's waterfall results into per-``(source, field_class)`` yield rows."""
    agg: dict[tuple[str, FieldClass], _YieldAcc] = {}
    for waterfall in results:
        field_class = classify_field_key(waterfall.field_key)
        for step in waterfall.per_tier:
            acc = agg.setdefault((step.source_key, field_class), _YieldAcc())
            acc.claims_total += step.n_claims
            acc.cost_cents += step.cost_cents
            if step.confident:
                acc.fields_filled += 1
    return [
        SourceYieldRow(
            source_key=source_key,
            field_class=field_class,
            claims_total=acc.claims_total,
            fields_filled=acc.fields_filled,
            cost_cents=acc.cost_cents,
        )
        for (source_key, field_class), acc in agg.items()
    ]


def _fit_value_json(
    fit: Score, rubric: ScoringRubric, *, non_fit_flag: bool, icp_key: str, icp_version: int
) -> dict[str, JsonValue]:
    """The ``account.scoring.fit`` claim payload: the decomposed score (with per-component evidence)
    plus the rubric version, the non-fit flag (D6), and the ICP it was scored under. ``value`` (the
    [0,1] fit score) is at top level, satisfying the field's value-schema."""
    payload: dict[str, JsonValue] = dict(fit.model_dump(mode="json"))
    payload["rubric_version"] = rubric.version
    payload["non_fit_flag"] = non_fit_flag
    payload["fit_floor"] = rubric.fit_floor
    payload["icp_key"] = icp_key
    payload["icp_version"] = icp_version
    return payload


def _intent_value_json(
    intent: Score, rubric: ScoringRubric, *, icp_key: str, icp_version: int
) -> dict[str, JsonValue]:
    """The ``account.scoring.intent`` claim payload (no fit floor — non-fit is a Fit concept)."""
    payload: dict[str, JsonValue] = dict(intent.model_dump(mode="json"))
    payload["rubric_version"] = rubric.version
    payload["icp_key"] = icp_key
    payload["icp_version"] = icp_version
    return payload


async def _write_score_object(
    conn: AsyncConnection,
    *,
    entity_id: EntityId,
    field_key: str,
    value_json: dict[str, JsonValue],
    run_id: RunId,
    client_id: str,
    icp_key: str,
) -> tuple[ClaimId, bool]:
    """Write one score claim idempotently, returning ``(claim_id, written)``.

    Idempotency on ``(account, rubric_version)`` is the deterministic ``run_id`` (which encodes the
    ICP/rubric version): an existing live score claim for this ``run_id`` is reused
    (``written=False`` — no new row, no double-charge). A live score from a *different* run of the
    **same ICP** (an earlier rubric version) is **superseded** so the merged ``current_value`` keeps
    one live winner per ICP (append-only history preserved); a score from a *different* ICP is left
    untouched (D5: an account may be scored under several ICPs independently). The claim is
    tenant-private (``stamp_reuse`` — the write boundary is fail-closed on these reserved fields).

    The read/replay/supersede-by-ICP sequence is the shared :func:`write_icp_scoped_claim` protocol
    (M6.4's tier write uses the same); this builds only the score claim's shape + value.
    """
    score_claim = stamp_reuse(
        account_claim(
            entity_id=entity_id,
            field_key=field_key,
            value_json=value_json,
            source_tier=1,
            extraction_method=ExtractionMethod.HUMAN,
            confidence=1.0,
            run_id=run_id,
            research_mode=ResearchMode.ACCOUNT_PROFILING,
        ),
        tenant_id=client_id,
    )
    return await write_icp_scoped_claim(
        conn,
        score_claim,
        run_id=run_id,
        icp_key=icp_key,
        scope=TenantScope.for_tenant(client_id),
    )


__all__ = [
    "FIT_FIELD",
    "INTENT_FIELD",
    "admitted_account_ids",
    "pass_a_fill_fields",
    "score_account",
    "aggregate_yield",
]
