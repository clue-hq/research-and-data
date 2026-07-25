"""Confirm an edited ICP proposal into a versioned ICP spec (M5.2).

The platform suggests, the client confirms (Doc B §1): :func:`confirm_icp` takes a synthesized
:class:`~clue_research.stage0.icp_types.ICPProposal` plus the client's
:class:`~clue_research.stage0.icp_types.ICPProposalEdits`, and:

1. applies the edits (drops removed dimensions/signals/seeds, adds added fields/packs, reweights the
   rubric) → a *confirmed selection*;
2. records the **suggested-vs-confirmed diff** (labeled feedback — substrate §9/§10), persisted
   claim-native (no new table — Beat-0; see :mod:`clue_research.stage0.icp_fields`);
3. **delegates compilation to the M3 research-schema compiler** — it pre-validates the selection by
   compiling it (:func:`~clue_research.icp.compile_field_plan`) and validating the rubric against
   the plan (:func:`~clue_research.icp.validate_rubric`), then persists the versioned ``ICPSpec``
   via :func:`~clue_research.icp.create_icp_spec` (``created_from=synthesis``, activated). M5.2
   picks *which* fields/packs/rubric; the compiler owns tier-plans, source-profile serving, and the
   field plan — never authored inline (conventions §2).

The result is reproducible: re-reading the pinned ``(workspace_id, icp_key, version)`` and
recompiling
yields the same ``FieldPlan`` (same ``plan_hash``) — staged-flow §2 "reproducible because
versioned". A confirmed spec is the single contract M6/M4 execute against; the proposal is never
seen downstream, so the synthesis model is swappable behind this seam.
"""

from __future__ import annotations

from dataclasses import dataclass
from dataclasses import field as dc_field

from pydantic import JsonValue
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_core import (
    Claim,
    EntityId,
    ExtractionMethod,
    ICPCreatedFrom,
    ICPSpec,
    ResearchMode,
    RunId,
    account_claim,
    new_run_id,
)
from clue_obs.otel import ATTR_ENTITY_ID, ATTR_WORKSPACE_ID, apply_attributes, traced_step
from clue_research.claimstore import insert_claim
from clue_research.icp import (
    RubricEntry,
    ScoringRubric,
    ScoringTransform,
    SubRubric,
    TierBand,
    TierCutoffs,
    compile_field_plan,
    create_icp_spec,
    get_active_icp,
    rubric_to_slot,
    validate_rubric,
)
from clue_research.identity import stamp_reuse
from clue_research.stage0.icp_estimate import EstimateInputs, estimate_campaign
from clue_research.stage0.icp_fields import ICP_CONFIRM_DIFF, load_icp_feedback_pack
from clue_research.stage0.icp_types import (
    ICPConfirmation,
    ICPProposal,
    ICPProposalDiff,
    ICPProposalEdits,
    ICPSpecRef,
    RubricWeightChange,
    SeedAccount,
)
from clue_research.stage0.reuse import ICP_REUSE_POLICY

_MODE = ResearchMode.ACCOUNT_PROFILING
_EMPTY_EDITS = ICPProposalEdits()


async def confirm_icp(
    conn: AsyncConnection,
    proposal: ICPProposal,
    edits: ICPProposalEdits | None = None,
    *,
    workspace_id: str,
    client_entity_id: EntityId,
    created_by: str | None = None,
    estimate_inputs: EstimateInputs | None = None,
    client_kb_version: int | None = None,
    product_id: str | None = None,
) -> ICPConfirmation:
    """Confirm ``proposal`` (with optional client ``edits``) into a versioned, active ``ICPSpec``.

    Returns the spec reference, the suggested-vs-confirmed diff, and the pre-run cost estimate
    (Doc C §5). Raises :class:`~clue_research.icp.CompileError` /
    :class:`~clue_research.icp.ICPSpecValidationError` if the confirmed selection references a field
    not in the registry or a pack not in the catalog (the client cannot add an unknown field/pack),
    and :class:`~clue_research.icp.RubricValidationError` if a rubric entry is not a Pass-A scoring
    field.

    **Idempotent on an identical re-confirm:** a confirm whose compiled selection (field set, packs,
    discovery strategy, source-profile ref, rubric) equals the currently-*active* spec for
    ``(workspace_id, icp_key)`` returns that spec and writes nothing — so a retried/double-clicked
    confirm never spawns a duplicate version or diff claim. A genuinely *edited* re-confirm differs,
    so it appends a new version (and a new diff) — the intended append-only confirm history. Run
    inside a transaction (the spec write + diff claim commit together; a retry then re-reads the
    committed active spec and the idempotency check short-circuits)."""
    if (client_kb_version is None) != (product_id is None):
        raise ValueError("C4 ICP confirmation requires both client_kb_version and product_id")
    edits = edits if edits is not None else _EMPTY_EDITS

    with traced_step("stage0.icp_confirm", **{ATTR_WORKSPACE_ID: workspace_id}) as span:
        apply_attributes(span, {ATTR_ENTITY_ID: client_entity_id})
        await load_icp_feedback_pack(conn)  # the icp.* feedback field must exist before we write it

        base = _select(proposal, _EMPTY_EDITS)
        confirmed = _select(proposal, edits)
        diff = _diff(base, confirmed, notes=edits.notes)

        rubric = _build_rubric(confirmed)
        # The full would-be spec (all five slots), built once and reused for pre-validation, the
        # idempotency comparison, and the write — so they can never disagree.
        draft = ICPSpec(
            workspace_id=workspace_id,
            icp_key=confirmed.icp_key,
            created_from=ICPCreatedFrom.SYNTHESIS,
            field_keys=confirmed.field_keys,
            enabled_packs=confirmed.packs,
            discovery_strategy=_discovery_strategy(confirmed),
            source_profile_ref={"packs": list(confirmed.packs)},
            scoring_rubric=rubric_to_slot(rubric),
            client_entity_id=client_entity_id if client_kb_version is not None else None,
            client_kb_version=client_kb_version,
            product_id=product_id,
        )
        # Pre-validate against the compiled plan BEFORE persisting (append-only → no rollback of a
        # bad spec): the compiler checks every field_key/pack exists; validate_rubric checks the
        # rubric reads only Pass-A scoring fields. The compiler owns the plan — not authored here.
        plan = await compile_field_plan(conn, draft)
        validate_rubric(rubric, plan)

        active = await get_active_icp(conn, workspace_id, confirmed.icp_key)
        if active is not None and _same_selection(active, draft):
            spec = active  # idempotent re-confirm of the active spec → write nothing
        else:
            spec = await create_icp_spec(
                conn,
                workspace_id=workspace_id,
                icp_key=draft.icp_key,
                created_from=ICPCreatedFrom.SYNTHESIS,
                field_keys=draft.field_keys,
                enabled_packs=draft.enabled_packs,
                discovery_strategy=draft.discovery_strategy,
                source_profile_ref=draft.source_profile_ref,
                scoring_rubric=draft.scoring_rubric,
                created_by=created_by,
                label=proposal.label,
                description=proposal.rationale,
                activate=True,
                client_entity_id=draft.client_entity_id,
                client_kb_version=draft.client_kb_version,
                product_id=draft.product_id,
            )
            await _persist_diff(
                conn,
                client_entity_id=client_entity_id,
                workspace_id=workspace_id,
                icp_key=spec.icp_key,
                icp_version=spec.version,
                diff=diff,
                run_id=new_run_id(),
            )

    return ICPConfirmation(
        ref=ICPSpecRef(workspace_id=workspace_id, icp_key=spec.icp_key, icp_version=spec.version),
        diff=diff,
        estimate=estimate_campaign(estimate_inputs),
    )


def _same_selection(active: ICPSpec, draft: ICPSpec) -> bool:
    """True when the active spec's five compiled slots equal the would-be ``draft``'s — i.e. this
    confirm would re-create the active spec byte-for-byte (the idempotency check). Slots round-trip
    through JSON identically (tuples↔lists, floats, enum strings), so a stored active spec compares
    equal to a freshly-built draft of the same selection; any mismatch simply appends a new version
    (degrades to the append-only path, never a wrong reuse)."""
    return (
        active.field_keys == draft.field_keys
        and active.enabled_packs == draft.enabled_packs
        and active.discovery_strategy == draft.discovery_strategy
        and active.source_profile_ref == draft.source_profile_ref
        and active.scoring_rubric == draft.scoring_rubric
        and active.client_entity_id == draft.client_entity_id
        and active.client_kb_version == draft.client_kb_version
        and active.product_id == draft.product_id
    )


# --- the confirmed selection (proposal ⊕ edits, normalized) -----------------


@dataclass(frozen=True)
class _Cell:
    dimension: str
    weight: float
    transform: str
    params: dict[str, JsonValue]


@dataclass(frozen=True)
class _Selection:
    """A proposal reduced to exactly what compiles into a spec, after edits — the normalized form
    both the diff and the spec-write read, so the persisted spec and the recorded diff can never
    disagree about what was confirmed."""

    icp_key: str
    field_keys: tuple[str, ...]
    packs: tuple[str, ...]
    signal_classes: tuple[str, ...]
    seeds: tuple[SeedAccount, ...]
    rubric: dict[str, _Cell] = dc_field(default_factory=dict)
    fit_threshold: float = 0.0
    intent_threshold: float = 0.0
    firmographic: dict[str, str] = dc_field(default_factory=dict)


def _select(proposal: ICPProposal, edits: ICPProposalEdits) -> _Selection:
    removed_fields = set(edits.removed_field_keys)
    removed_packs = set(edits.removed_packs)
    removed_signals = set(edits.removed_signal_classes)
    removed_seeds = set(edits.removed_seed_ids)
    overrides = edits.rubric_weight_overrides

    firmo_keys = [fk for fk in proposal.firmographic.field_keys if fk not in removed_fields]
    signals = [s for s in proposal.candidate_signals if s.signal_class not in removed_signals]
    techno = [
        t
        for t in proposal.technographic
        if t.field_key not in removed_fields and t.pack_key not in removed_packs
    ]
    seeds = tuple(s for s in proposal.seed_accounts if s.account_entity_id not in removed_seeds)

    packs: list[str] = []
    for pack in (*proposal.source_profile.packs, *(t.pack_key for t in techno), *edits.added_packs):
        if pack and pack not in removed_packs and pack not in packs:
            packs.append(pack)

    rubric: dict[str, _Cell] = {}
    for weight in proposal.rubric.weights:
        if weight.field_key in removed_fields:
            continue
        value = overrides.get(weight.field_key, weight.weight)
        if value == 0.0:
            continue  # an override of 0.0 drops the contribution
        rubric[weight.field_key] = _Cell(
            dimension=weight.dimension,
            weight=value,
            transform=weight.transform,
            params=dict(weight.params),
        )

    ordered: list[str] = []
    for key in (
        *firmo_keys,
        *(t.field_key for t in techno),
        *(fk for s in signals for fk in (*s.proxy_field_keys, *s.narrative_field_keys)),
        *rubric,
        *edits.added_field_keys,
    ):
        if key not in removed_fields and key not in ordered:
            ordered.append(key)

    firmographic = {
        k: v
        for k, v in (
            ("industry", proposal.firmographic.industry),
            ("size_band", proposal.firmographic.size_band),
            ("geo", proposal.firmographic.geo),
            ("revenue_band", proposal.firmographic.revenue_band),
        )
        if v is not None
    }

    return _Selection(
        icp_key=edits.icp_key or proposal.icp_key,
        field_keys=tuple(ordered),
        packs=tuple(packs),
        signal_classes=tuple(s.signal_class for s in signals),
        seeds=seeds,
        rubric=rubric,
        fit_threshold=(
            edits.fit_threshold
            if edits.fit_threshold is not None
            else proposal.rubric.fit_threshold
        ),
        intent_threshold=(
            edits.intent_threshold
            if edits.intent_threshold is not None
            else proposal.rubric.intent_threshold
        ),
        firmographic=firmographic,
    )


def _build_rubric(sel: _Selection) -> ScoringRubric:
    """Build the M3.4 :class:`ScoringRubric` from the confirmed rubric cells (fit/intent SubRubrics
    + a single default tier band over the confirmed thresholds). The human re-adjusts cutoffs at the
    M6 checkpoint without re-versioning (cutoffs are data)."""
    fit = tuple(
        RubricEntry(
            field_key=fk,
            weight=cell.weight,
            transform=_transform(cell.transform),
            params=cell.params,
        )
        for fk, cell in sel.rubric.items()
        if cell.dimension == "fit"
    )
    intent = tuple(
        RubricEntry(
            field_key=fk,
            weight=cell.weight,
            transform=_transform(cell.transform),
            params=cell.params,
        )
        for fk, cell in sel.rubric.items()
        if cell.dimension == "intent"
    )
    return ScoringRubric(
        fit=SubRubric(entries=fit),
        intent=SubRubric(entries=intent),
        tier_cutoffs=TierCutoffs(
            bands=(
                TierBand(tier="high", min_fit=sel.fit_threshold, min_intent=sel.intent_threshold),
            ),
            fallback_tier="low",
        ),
    )


def _transform(value: str) -> ScoringTransform:
    try:
        return ScoringTransform(value)
    except ValueError:
        return ScoringTransform.BOOLEAN  # an unknown transform degrades to presence (never raises)


def _discovery_strategy(sel: _Selection) -> dict[str, JsonValue]:
    """The mode-M1 discovery strategy slot M6 interprets: the firmographic targets, the seed
    account ids (lookalike vs open discovery), and the candidate signal classes to weigh."""
    firmographic: dict[str, JsonValue] = dict(sel.firmographic)
    seed_ids: list[JsonValue] = [str(s.account_entity_id) for s in sel.seeds]
    signal_classes: list[JsonValue] = list(sel.signal_classes)
    return {
        "mode": "lookalike" if seed_ids else "discovery",
        "firmographic": firmographic,
        "seed_account_ids": seed_ids,
        "candidate_signal_classes": signal_classes,
    }


# --- the suggested-vs-confirmed diff (labeled feedback) ---------------------


def _diff(base: _Selection, confirmed: _Selection, *, notes: str | None) -> ICPProposalDiff:
    base_fields, conf_fields = set(base.field_keys), set(confirmed.field_keys)
    base_packs, conf_packs = set(base.packs), set(confirmed.packs)
    base_signals, conf_signals = set(base.signal_classes), set(confirmed.signal_classes)
    base_seeds = {s.account_entity_id for s in base.seeds}
    conf_seeds = {s.account_entity_id for s in confirmed.seeds}

    reweighted: list[RubricWeightChange] = []
    for fk in sorted(set(base.rubric) | set(confirmed.rubric)):
        before = base.rubric[fk].weight if fk in base.rubric else None
        after = confirmed.rubric[fk].weight if fk in confirmed.rubric else None
        if before != after:
            reweighted.append(RubricWeightChange(field_key=fk, before=before, after=after))

    fit_changed = base.fit_threshold != confirmed.fit_threshold
    intent_changed = base.intent_threshold != confirmed.intent_threshold

    return ICPProposalDiff(
        added_field_keys=tuple(sorted(conf_fields - base_fields)),
        removed_field_keys=tuple(sorted(base_fields - conf_fields)),
        added_packs=tuple(sorted(conf_packs - base_packs)),
        removed_packs=tuple(sorted(base_packs - conf_packs)),
        removed_signal_classes=tuple(sorted(base_signals - conf_signals)),
        removed_seed_ids=tuple(base_seeds - conf_seeds),
        reweighted=tuple(reweighted),
        fit_threshold_before=base.fit_threshold if fit_changed else None,
        fit_threshold_after=confirmed.fit_threshold if fit_changed else None,
        intent_threshold_before=base.intent_threshold if intent_changed else None,
        intent_threshold_after=confirmed.intent_threshold if intent_changed else None,
        notes=notes,
    )


async def _persist_diff(
    conn: AsyncConnection,
    *,
    client_entity_id: EntityId,
    workspace_id: str,
    icp_key: str,
    icp_version: int,
    diff: ICPProposalDiff,
    run_id: RunId,
) -> Claim:
    """Write the confirm diff as one immutable ``icp.confirm_diff`` claim on the client entity
    (append-only confirm history; one per confirmed version — the corrections-as-labeled-data
    discipline, substrate §9/§10). Tenant-private (an ICP is client-tuned)."""
    value: dict[str, JsonValue] = {
        "icp_key": icp_key,
        "icp_version": icp_version,
        "diff": diff.model_dump(mode="json"),
    }
    claim = account_claim(
        entity_id=client_entity_id,
        field_key=ICP_CONFIRM_DIFF,
        value_json=value,
        source_tier=1,
        extraction_method=ExtractionMethod.HUMAN,
        confidence=1.0,
        run_id=run_id,
        research_mode=_MODE,
        evidence_span=f"client confirmed ICP {icp_key} v{icp_version}",
    )
    claim = stamp_reuse(claim, workspace_id=workspace_id, policy=ICP_REUSE_POLICY)
    await insert_claim(conn, claim)
    return claim
