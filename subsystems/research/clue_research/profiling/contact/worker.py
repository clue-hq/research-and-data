"""Contact profiling — the M8.4 worker (mode M4).

``profile_contact`` runs on each admitted committee member (from M8.3): it computes the deep
contact-field gaps, fills each through the facet-aware fill (which tags ``identity_binding`` +
``use_class`` born-correct), and may request **facet sub-workers** (the level-2 fan-out, Doc C §3)
for the richest aspects — capped per tier by the M7 recursion knob (top-tier only; lower tiers get
single-level depth). It is closed and target-locked per person (the contact-axis analogue of M2).

It returns the per-claim handoff views (the ``ProfileClaimView`` shape) + references, never blobs.
:class:`ContactProfileAspectWorker` adapts it to the M7 ``AspectWorker`` seam (``aspect=
'contact.facet'`` so it is recursion-eligible); the orchestrator hands an ``AspectContext`` whose
``entity_id`` is the *contact* and whose ``params`` carry the account + client + recursion budget.
"""

from __future__ import annotations

from collections.abc import Sequence
from decimal import Decimal
from uuid import UUID

from pydantic import JsonValue
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_config import (
    ConfidenceThresholds,
    OverlayStore,
    RecursionPolicy,
    SourcePlanPolicy,
    get_config,
)
from clue_core import (
    CONTACT_CHANNEL_FIELD_KEYS,
    AspectContext,
    ClaimId,
    EntityId,
    EntityType,
    FieldClass,
    FieldDef,
    ICPSpec,
    PreSpendGate,
    ProfileClaimView,
    RunId,
    WorkerResult,
    WorkerStatus,
)
from clue_db import ConnFactory
from clue_research.claimstore import WorkspaceScope, claims_by_ids
from clue_research.icp.spec import get_icp_version
from clue_research.identity import get_account, get_contact, surviving_id
from clue_research.profiling.contact.binding import DEFAULT_BINDING_CLASSIFIER, BindingClassifier
from clue_research.profiling.contact.fill import FacetFillResult, fill_contact_field
from clue_research.profiling.contact.gaps import compute_contact_gap_fields
from clue_research.profiling.contact.results import (
    DEFAULT_CONTACT_PROFILE_CONFIG,
    ContactProfileConfig,
    ContactProfileResult,
)
from clue_research.profiling.contact.use_class import DEFAULT_USE_CLASS_TAGGER, UseClassTagger

# The conservative default dial (top tier depth 2, lower tiers single-level) — the ``api`` root
# injects the run's versioned :class:`RecursionPolicy`; tests use this default.
_DEFAULT_RECURSION_POLICY = RecursionPolicy()


def _facet_request(field_def: FieldDef) -> dict[str, JsonValue]:
    """A level-2 facet sub-worker request for the M7 orchestrator (routed via its spawn guard)."""
    return {"aspect": field_def.field_key, "field_keys": [field_def.field_key], "depth": 1}


def _is_rich_facet(field_def: FieldDef, fill: FacetFillResult, min_values: int) -> bool:
    """Whether a filled facet is rich enough (a list with ≥ ``min_values`` items) to warrant a
    facet sub-worker — and only ``contact.facet.*`` fields are recursion-eligible (Doc C §3)."""
    if field_def.field_class is not FieldClass.CONTACT_FACET:
        return False
    return any(
        isinstance(view.value_json, list) and len(view.value_json) >= min_values
        for view in fill.profile_views
    )


async def profile_contact(
    conn: AsyncConnection,
    *,
    contact_entity_id: EntityId,
    account_entity_id: EntityId,
    run_id: RunId,
    workspace_id: str,
    tier: str,
    spec: ICPSpec | None = None,
    facet_subworker_budget: int = 0,
    field_keys: Sequence[str] | None = None,
    prepared_claim_refs: Sequence[ClaimId] | None = None,
    binding_classifier: BindingClassifier = DEFAULT_BINDING_CLASSIFIER,
    use_class_tagger: UseClassTagger = DEFAULT_USE_CLASS_TAGGER,
    pre_spend_gate: PreSpendGate | None = None,
    config: ContactProfileConfig = DEFAULT_CONTACT_PROFILE_CONFIG,
    thresholds: ConfidenceThresholds | None = None,
    plan_policy: SourcePlanPolicy | None = None,
    icp_key: str | None = None,
    config_store: OverlayStore | None = None,
) -> ContactProfileResult:
    """Profile one verified committee member (mode M4).

    ``facet_subworker_budget`` is the per-tier level-2 fan-out allowance (= the M7 recursion knob's
    ``max_facet_workers_per_aspect`` for this tier, ``0`` ⇒ single-level depth) — M8.4 requests at
    most this many facet sub-workers; the M7 ``SpawnGuard`` is the hard cap. ``workspace_id`` binds
    the
    tenant-private contact claims. When ``prepared_claim_refs`` is supplied, the C6 external
    preparation seam has already acquired and materialized the selected fields. The worker then
    performs a reference-only projection and never enters the resolver waterfall; that is the
    runtime no-network-under-claim-transaction boundary for composed contact research.

    ``thresholds`` (the waterfall stop bar, lever 1) and ``plan_policy`` (the planner tier reach,
    lever 2) default to the per-run layered config keyed by ``(workspace_id, icp_key)``; pass them
    explicitly to override. This is the single config-resolution point for the contact axis — the
    live deep path calls this callable directly, so resolving here (not only in the aspect-worker
    adapter) keeps it config-aware. ``config_store=None`` reads the process default store."""
    if thresholds is None or plan_policy is None:
        cfg = get_config(workspace_id, icp_key, store=config_store)
        thresholds = thresholds if thresholds is not None else cfg.confidence_thresholds
        plan_policy = plan_policy if plan_policy is not None else cfg.source_plan_policy
    contact = await get_contact(
        conn, await surviving_id(conn, contact_entity_id, EntityType.CONTACT)
    )
    if contact is None:
        raise ValueError(f"contact {contact_entity_id} not found — cannot profile it")
    account = await get_account(
        conn, await surviving_id(conn, account_entity_id, EntityType.ACCOUNT)
    )
    if account is None:
        raise ValueError(f"account {account_entity_id} not found — cannot target-lock the contact")

    if prepared_claim_refs is not None:
        channel_fields = set(CONTACT_CHANNEL_FIELD_KEYS.values())
        selected_fields = tuple(
            dict.fromkeys(
                field_key for field_key in (field_keys or ()) if field_key not in channel_fields
            )
        )
        claims = await claims_by_ids(
            conn,
            prepared_claim_refs,
            scope=WorkspaceScope.for_workspace(workspace_id),
        )
        by_field: dict[str, list[ProfileClaimView]] = {
            field_key: [] for field_key in selected_fields
        }
        for claim_id in prepared_claim_refs:
            claim = claims.get(claim_id)
            if (
                claim is None
                or claim.entity_id != contact.id
                or str(claim.field_key) not in by_field
            ):
                continue
            by_field[str(claim.field_key)].append(
                ProfileClaimView(
                    claim_id=claim.id,
                    value_json=claim.value_json,
                    evidence_span=claim.evidence_span,
                    source_tier=claim.source_tier,
                    identity_binding=claim.identity_binding,
                    use_class=claim.use_class,
                )
            )
        return ContactProfileResult(
            contact_entity_id=contact.id,
            account_entity_id=account.id,
            profile_claims=tuple(view for views in by_field.values() for view in views),
            fields_filled=sum(bool(views) for views in by_field.values()),
            fields_empty=sum(not views for views in by_field.values()),
        )

    gaps = await compute_contact_gap_fields(
        conn, contact.id, workspace_id=workspace_id, field_keys=field_keys
    )

    views: list[ProfileClaimView] = []
    cost = Decimal(0)
    filled = empty = 0
    facet_requests: list[dict[str, JsonValue]] = []

    for field_def in gaps:
        fill = await fill_contact_field(
            conn,
            contact,
            account,
            field_def,
            run_id=run_id,
            workspace_id=workspace_id,
            tier=tier,
            spec=spec,
            binding_classifier=binding_classifier,
            use_class_tagger=use_class_tagger,
            pre_spend_gate=pre_spend_gate,
            thresholds=thresholds,
            plan_policy=plan_policy,
        )
        views.extend(fill.profile_views)
        cost += fill.cost_cents
        if fill.claim_refs:
            filled += 1
        else:
            empty += 1
        # Request a facet sub-worker for a rich facet, bounded by the per-tier recursion budget.
        if len(facet_requests) < facet_subworker_budget and _is_rich_facet(
            field_def, fill, config.facet_subworker_min_values
        ):
            facet_requests.append(_facet_request(field_def))

    return ContactProfileResult(
        contact_entity_id=contact.id,
        account_entity_id=account.id,
        profile_claims=tuple(views),
        cost_cents=cost,
        fields_filled=filled,
        fields_empty=empty,
        facet_requests=tuple(facet_requests),
    )


class ContactProfileAspectWorker:
    """Adapts :func:`profile_contact` to the M7 ``AspectWorker`` seam (``aspect='contact.facet'``).

    The orchestrator hands an :class:`AspectContext` whose ``entity_id`` is the *contact* and whose
    ``params`` carry ``account_entity_id`` + ``workspace_id``/``icp_key``/``icp_version``. The facet
    sub-worker budget is derived from the injected :class:`~clue_config.RecursionPolicy`
    (``caps_for(tier).max_facet_workers_per_aspect``, and only if the aspect is recursion-eligible)
    — the versioned dial is the single source of truth, so a low-tier contact gets single-level
    depth regardless of any per-call hint. The worker opens a connection from the injected
    ``ConnFactory`` (the orchestrator never passes one). A level-1 worker (``depth>=1``) requests
    no further sub-workers (single descent)."""

    aspect = "contact.facet"

    def __init__(
        self,
        *,
        session_factory: ConnFactory,
        binding_classifier: BindingClassifier = DEFAULT_BINDING_CLASSIFIER,
        use_class_tagger: UseClassTagger = DEFAULT_USE_CLASS_TAGGER,
        recursion: RecursionPolicy = _DEFAULT_RECURSION_POLICY,
        pre_spend_gate: PreSpendGate | None = None,
        config: ContactProfileConfig = DEFAULT_CONTACT_PROFILE_CONFIG,
        config_store: OverlayStore | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._binding_classifier = binding_classifier
        self._use_class_tagger = use_class_tagger
        self._recursion = recursion
        self._pre_spend_gate = pre_spend_gate
        self._config = config
        # The layered-config seam: the waterfall stop bar + planner tier reach read per-run off the
        # merged Config (keyed by the run's client). ``None`` → the process default store.
        self._config_store = config_store

    async def research(self, ctx: AspectContext) -> WorkerResult:
        params = ctx.params
        # params is JSON (no UUID type), so the account id arrives as a string — parse it back to a
        # real UUID-backed EntityId (not a bare str) so it keys correctly downstream.
        account_entity_id = EntityId(UUID(str(params["account_entity_id"])))
        workspace_id = str(params["workspace_id"])
        icp_key = str(params["icp_key"])
        icp_version = int(params["icp_version"])  # type: ignore[arg-type]
        # The facet-recursion budget is the versioned dial, per tier — a level-0 worker on a
        # recursion-eligible aspect at this tier; a sub-worker (depth>=1) never spawns more (single
        # descent), and a non-eligible aspect / lower tier resolves to 0 (single-level depth).
        budget = 0
        if ctx.depth == 0 and self._recursion.is_eligible(self.aspect):
            budget = self._recursion.caps_for(ctx.tier).max_facet_workers_per_aspect

        async with self._session_factory() as conn:
            spec = await get_icp_version(conn, workspace_id, icp_key, icp_version)
            result = await profile_contact(
                conn,
                contact_entity_id=ctx.entity_id,
                account_entity_id=account_entity_id,
                run_id=ctx.run_id,
                workspace_id=workspace_id,
                tier=ctx.tier,
                spec=spec,
                facet_subworker_budget=budget,
                field_keys=ctx.field_keys or None,
                binding_classifier=self._binding_classifier,
                use_class_tagger=self._use_class_tagger,
                pre_spend_gate=self._pre_spend_gate,
                config=self._config,
                icp_key=icp_key,
                # profile_contact resolves the per-run source policies (lever 1/2) from the layered
                # config keyed by (workspace_id, icp_key); pass the store through for test
                # isolation.
                config_store=self._config_store,
            )

        return WorkerResult(
            aspect=self.aspect,
            status=WorkerStatus.OK,
            claim_refs=result.claim_refs,
            cost_cents=result.cost_cents,
            detail={
                "fields_filled": result.fields_filled,
                "fields_empty": result.fields_empty,
                "strong_binding": result.strong_binding_count,
                "weak_binding": result.weak_binding_count,
                "sensitive": result.sensitive_count,
                "facet_requests": list(result.facet_requests),
            },
        )
