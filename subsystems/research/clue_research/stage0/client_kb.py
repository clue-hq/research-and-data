"""Client reverse-profiling → the versioned Client Knowledge Base (M5.1).

Before we research targets, we research the **client themselves** (Doc B §2): the same machinery
the subsystem uses on accounts (identity resolution → trust-tiered waterfall → typed claims with
provenance) pointed *inward* at the client's footprint. Worst-case input is a name + website (Doc B
§1); everything else is derived, never required. The output is a typed, **versioned Client
Knowledge Base** — the client side of every later value narrative (Output 4), whose depth sets the
quality ceiling downstream (substrate §8).

The base is *just claims* (conventions §2 — no bespoke "client object"): client facts live in the
shared ``claim`` store keyed on the client's resolved ``account_entity``, in the ``client.*``
namespace, stamped ``tenant_private`` (M5.1 is client-knowledge —
:mod:`clue_research.stage0.reuse`). The **version ledger is itself a claim** (the
``client.kb_version`` marker), so versioning adds no new table and stays append-only with the rest
of the store: a new run bumps the version and supersedes the prior marker, while every prior claim
remains queryable.

This module owns the bounded converge-pattern orchestration (staged-flow §5) over a single resolved
entity — the client — driving the M4 waterfall (tiers 1–3) per ``client.*`` field, shortcutting
from volunteered materials, enforcing a per-client budget cap, and producing a coverage read.
Tier-4 client synthesis is left to a tier-4 resolver behind the M9 judge (consumed, not built
here).
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping, Sequence
from decimal import Decimal
from typing import Literal, cast
from uuid import NAMESPACE_URL, uuid5

from pydantic import BaseModel, ConfigDict, JsonValue
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_core import (
    AccountEntity,
    AccountStatus,
    BudgetTracker,
    Claim,
    Entity,
    EntityId,
    EntityType,
    ExtractionMethod,
    FaithfulnessJudge,
    JudgeResult,
    PreSpendGate,
    PreSpendRequest,
    PreSpendVerdict,
    ProductScopePolicy,
    ResearchMode,
    RunId,
    SourceGate,
    SourceManifest,
    VerificationStatus,
    account_claim,
    new_run_id,
    resolve_product_scope,
)
from clue_obs.otel import (
    ATTR_COST_CENTS,
    ATTR_ENTITY_ID,
    ATTR_N_CLAIMS,
    ATTR_WORKSPACE_ID,
    apply_attributes,
    traced_step,
)
from clue_research.claimstore import (
    FieldFilters,
    FieldRegistryScope,
    ValueSchemaError,
    WorkspaceScope,
    claims_for,
    get_effective_field,
    get_field,
    insert_claim,
    list_effective_fields,
    record_run_lineage,
    supersede_claim,
)
from clue_research.identity import (
    Observation,
    embed_account,
    get_account,
    insert_account_entity,
    resolve,
    resolve_alias,
    set_status,
    stamp_reuse,
    surviving_id,
)
from clue_research.sources import StopReason, resolve_field
from clue_research.stage0.fields import (
    CLIENT_BASELINE_FIELDS,
    CLIENT_KB_VERSION,
    PRODUCT_KNOWLEDGE_FIELDS,
    SURFACE_CLASS_FIELDS,
    load_client_knowledge_pack,
)
from clue_research.stage0.reuse import CLIENT_KNOWLEDGE_REUSE_POLICY
from clue_research.stage0.types import (
    ClientInput,
    ClientKnowledgeBaseRef,
    CoverageReport,
    FieldProgressStatus,
    ReverseProfileResult,
    SurfaceCoverage,
    VolunteeredMaterial,
)

# Reverse-profiling profiles the client → research mode M2 (account profiling).
_MODE = ResearchMode.ACCOUNT_PROFILING
# Volunteered materials are the client's own assertion: tier-1, maximally trusted (like CRM).
_MATERIAL_TIER = 1
_EVIDENCE_SPAN_MAX = 2000  # cap a raw excerpt used as an evidence_span
# Minimum match score to reuse an existing entity as *the client* (vs admitting a fresh one). A
# deterministic strong-key hit scores 1.0; a fuzzy name+geo match caps well below this, so this
# threshold reuses the client's own prior-run entity (exact self-match) without risking a collapse
# onto a merely similar company. Identity-resolution policy lives in M2; this is the
# workspace-identity
# reuse knob for the (degenerate) no-registrable-domain case.
_CLIENT_REUSE_MIN_SCORE = 0.85

# The per-field progress seam: called once with STARTED as the loop reaches a field, then exactly
# once more with its terminal status (RESOLVED / EMPTY / FAILED). The **lane connection** is the
# first argument so a same-transaction sink can write on it without opening (and deadlocking on) a
# second connection; a sink wanting mid-lane visibility to other readers brings its own factory.
FieldProgress = Callable[[AsyncConnection, str, FieldProgressStatus], Awaitable[None]]


def _knowledge_fields_for_run(
    *,
    knowledge_scope: Literal["company", "product"],
    product_id: str | None,
    company_field_keys: Sequence[str] | None,
) -> tuple[str, ...]:
    """Resolve one run's field policy before identity, storage, or provider work begins."""

    if knowledge_scope == "product":
        if product_id is None:
            raise ValueError("product knowledge scope requires product_id")
        if company_field_keys is not None:
            raise ValueError("product knowledge scope cannot accept company_field_keys")
        return PRODUCT_KNOWLEDGE_FIELDS

    knowledge_fields = (
        CLIENT_BASELINE_FIELDS if company_field_keys is None else tuple(company_field_keys)
    )
    if not knowledge_fields:
        raise ValueError("company_field_keys must not be empty")
    if len(knowledge_fields) != len(set(knowledge_fields)):
        raise ValueError("company_field_keys must not contain duplicates")
    unknown_fields = sorted(set(knowledge_fields) - set(CLIENT_BASELINE_FIELDS))
    if unknown_fields:
        raise ValueError(f"company_field_keys contain non-company fields: {unknown_fields}")
    return knowledge_fields


class ClientKbWriteTarget(BaseModel):
    """The version/run a post-promotion materialization must write into."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    version: int
    run_id: RunId
    created_new_version: bool = False


async def reverse_profile(
    conn: AsyncConnection,
    client_input: ClientInput,
    *,
    workspace_id: str,
    run_id: RunId | None = None,
    budget_cap_cents: Decimal | None = None,
    judge: FaithfulnessJudge | None = None,
    pre_spend_gate: PreSpendGate | None = None,
    product_id: str | None = None,
    knowledge_scope: Literal["company", "product"] = "company",
    company_field_keys: Sequence[str] | None = None,
    max_source_tier: int | None = None,
    on_client_resolved: Callable[[AccountEntity], None] | None = None,
    on_field_progress: FieldProgress | None = None,
) -> ReverseProfileResult:
    """Reverse-profile a client into a versioned Client Knowledge Base.

    Resolves ``client_input`` to a single ``account_entity`` (deterministic on domain, with a
    high-confidence fuzzy fallback so a re-run never spawns a duplicate), ingests any volunteered
    materials as high-trust claims, then drives the trust-tiered waterfall (tiers 1–3) over the
    ``client.*`` field set — stopping gracefully at ``budget_cap_cents`` — and writes the version
    marker. ``workspace_id`` is the tenant the client-knowledge claims are bound to.

    Idempotent on re-entry: pass the *same* ``run_id`` to resume a partial run without
    double-writing (the waterfall dedups per ``(entity, field, source, run)``; materials/marker are
    guarded on the run). Omitting ``run_id`` starts a **new** run → a new KB version.

    **Versioning model.** The store is append-only — a new run writes new claims and supersedes the
    prior *version marker*, never UPDATE-ing field claims. The canonical current-truth read is
    therefore the *version-scoped* :func:`read_client_kb` (it returns exactly the latest run's
    values, so a field the latest run could not re-derive is correctly absent from the current KB).
    The raw ``current_value`` merge seam instead carries a prior value forward under trust+freshness
    until its TTL ages it out (substrate §8 drift) — consumers wanting version-correct truth read
    through :func:`read_client_kb`, not the raw seam.

    ``knowledge_scope`` is explicit because a project-selected ``product_id`` is ambient execution
    context, not permission to turn company-wide onboarding facts into product facts. The default
    ``company`` scope writes the complete account-wide company set with ``product_id=NULL``.
    Trusted composition may pass an ordered ``company_field_keys`` subset for a narrower policy
    boundary such as the eleven-field fast onboarding lane; unknown, duplicate, or empty subsets
    are refused. A ``product`` run requires one exact ``product_id``, rejects a company subset,
    and writes only the independently versioned product-knowledge field set.

    ``judge`` is the injected M9 seam used only for tier-4 client claims (consumed behind the judge
    — the tier-4 *synthesis* is M11). It is optional: the default tiers-1–3 pass needs no judge.

    ``on_field_progress`` is the optional per-field progress seam (D-5 Path B): the loop announces
    ``STARTED`` as it reaches each field and exactly one terminal status after — ``RESOLVED`` when
    the field gained a claim, ``EMPTY`` when no source could answer it (a *correct* outcome, not a
    failure), ``FAILED`` when the resolution attempt itself errored (announced, then re-raised —
    progress reporting never swallows a lane failure). Fields the run never attempts — shortcut by
    a volunteered material, or cut off by the budget halt — announce **nothing**, so a consumer
    reads honest absence rather than fabricated motion.
    """
    knowledge_fields = _knowledge_fields_for_run(
        knowledge_scope=knowledge_scope,
        product_id=product_id,
        company_field_keys=company_field_keys,
    )
    effective_product_id = product_id if knowledge_scope == "product" else None
    knowledge_field_set = frozenset(knowledge_fields)
    scope = WorkspaceScope.for_workspace(workspace_id)
    run = run_id if run_id is not None else new_run_id()

    with traced_step(
        "stage0.reverse_profile",
        **{ATTR_WORKSPACE_ID: workspace_id},
    ) as span:
        client_entity_id = await prepare_client_kb_run(
            conn,
            client_input,
            workspace_id=workspace_id,
            run_id=run,
        )
        apply_attributes(span, {ATTR_ENTITY_ID: client_entity_id})
        if on_client_resolved is not None:
            client_account = await get_account(conn, client_entity_id)
            if client_account is None:  # pragma: no cover - identity resolver just returned it
                raise RuntimeError("resolved client account disappeared before resolver wiring")
            on_client_resolved(client_account)

        # Fields already filled by a volunteered (HUMAN) claim under THIS run — for idempotent
        # re-entry, so resuming neither re-ingests a material nor re-spends on a field it filled.
        material_fields = {
            c.field_key
            for c in await claims_for(conn, client_entity_id, scope=scope)
            if c.run_id == run
            and c.extraction_method is ExtractionMethod.HUMAN
            and c.product_id == effective_product_id
            and c.field_key in knowledge_field_set
        }

        budget = BudgetTracker(envelope_cents=budget_cap_cents)
        claims_written = 0
        filled_fields: set[str] = set()  # fields with a live claim in this run
        attempted_fields: set[str] = set()  # fields the run actually reached (vs cut off by budget)

        # 1) Volunteered materials → high-trust tier-1 claims that shortcut derivation (Doc B §1).
        for material in client_input.materials:
            wrote = await _ingest_material(
                conn,
                material,
                client_entity_id=client_entity_id,
                workspace_id=workspace_id,
                run_id=run,
                already_written=material_fields,
                product_id=effective_product_id,
                allowed_fields=knowledge_field_set,
            )
            claims_written += len(wrote)
        filled_fields |= material_fields  # incl. fields carried in from a re-entered run
        attempted_fields |= material_fields

        # 2) Drive the waterfall (tiers 1–3) over each still-empty client field, honoring the cap.
        budget_exhausted = False
        for field_key in knowledge_fields:
            if field_key in material_fields:
                continue  # a volunteered fact already fills it — do not spend to re-derive
            if budget.exhausted:
                budget_exhausted = True
                break  # outer cap: do not reach later fields (they stay un-attempted)
            field_def = await get_field(conn, field_key)
            if field_def is None:
                continue  # defensive: pack load above guarantees presence
            attempted_fields.add(field_key)
            await _announce(on_field_progress, conn, field_key, FieldProgressStatus.STARTED)
            try:
                result = await resolve_field(
                    conn,
                    _entity_ref(client_entity_id),
                    field_def,
                    mode=_MODE,
                    run_id=run,
                    workspace_id=workspace_id,
                    budget_envelope=budget_cap_cents,
                    cost_so_far=budget.spent_cents,
                    reuse_policy=CLIENT_KNOWLEDGE_REUSE_POLICY,
                    product_id=effective_product_id,
                    source_gate=_source_gate(
                        pre_spend_gate,
                        entity_id=client_entity_id,
                        field_key=field_key,
                        run_id=run,
                        max_source_tier=max_source_tier,
                    ),
                )
            except Exception:
                # Announce the failure, then let it fail the lane exactly as before: the progress
                # seam reports what happened, it never decides whether the run survives.
                await _announce(on_field_progress, conn, field_key, FieldProgressStatus.FAILED)
                raise
            await _announce(
                on_field_progress,
                conn,
                field_key,
                FieldProgressStatus.RESOLVED if result.claim_refs else FieldProgressStatus.EMPTY,
            )
            budget.spend(result.total_cost_cents)
            claims_written += len(result.claim_refs)
            if result.claim_refs:
                filled_fields.add(field_key)
            if result.stop_reason is StopReason.BUDGET_STOP:
                budget_exhausted = True
                break

        # 3) Tier-4 client claims (if any were produced) are gated behind the injected M9 judge.
        if judge is not None:
            await _judge_tier4_claims(conn, client_entity_id, run_id=run, scope=scope, judge=judge)

        # 4) Coverage read (over what THIS run filled/attempted) + version marker.
        coverage = _coverage(
            filled_fields,
            attempted_fields,
            knowledge_fields=knowledge_fields,
        )
        version = await _write_version_marker(
            conn,
            client_entity_id=client_entity_id,
            workspace_id=workspace_id,
            run_id=run,
            coverage=coverage,
            product_id=effective_product_id,
        )

        apply_attributes(span, {ATTR_COST_CENTS: budget.spent_cents, ATTR_N_CLAIMS: claims_written})

    return ReverseProfileResult(
        ref=ClientKnowledgeBaseRef(
            client_entity_id=client_entity_id,
            client_kb_version=version,
            product_id=effective_product_id,
        ),
        run_id=run,
        coverage=coverage,
        cost_cents=budget.spent_cents,
        fields_resolved=len(filled_fields),
        budget_exhausted=budget_exhausted,
    )


# --- helpers ----------------------------------------------------------------


async def prepare_client_kb_run(
    conn: AsyncConnection,
    client_input: ClientInput,
    *,
    workspace_id: str,
    run_id: RunId,
) -> EntityId:
    """Prepare one Stage-0 claim run without resolving any external source.

    Authoritative official-site crawling needs the same workspace-local client identity, field
    registry, and run-lineage prerequisites as :func:`reverse_profile`, but it must not invoke the
    legacy field-level waterfall. Keeping that preparation here makes the C10 cutover reuse the
    normal identity and lineage rules rather than duplicating them in fleet composition.
    """

    await load_client_knowledge_pack(conn)
    await record_run_lineage(conn, run_id=run_id, workspace_id=workspace_id, kind="stage0")
    return await _resolve_client(conn, client_input, workspace_id=workspace_id)


async def finalize_client_kb_version(
    conn: AsyncConnection,
    *,
    client_entity_id: EntityId,
    workspace_id: str,
    run_id: RunId,
    filled_fields: set[str],
    attempted_fields: set[str],
    product_id: str | None,
    base_version: int | None = None,
) -> int:
    """Commit or replay the version marker after grounded materialization is durable.

    The marker is written *after* the checkpoint extractors finish. Browser release therefore
    cannot observe a Client-KB version whose official-site claims are still in flight, and the
    marker's coverage describes the committed run instead of a pre-crawl placeholder.

    ``base_version`` is an explicit immutable snapshot parent. It is used by composed multi-phase
    publication (fast then background) so the later lane overlays its new claims on the exact
    prior checkpoint instead of making a transient field-level failure erase still-pinned fast
    knowledge. Ordinary reverse-profile runs omit it and retain their replace-on-refresh meaning.
    """

    return await _write_version_marker(
        conn,
        client_entity_id=client_entity_id,
        workspace_id=workspace_id,
        run_id=run_id,
        coverage=_coverage(
            filled_fields,
            attempted_fields,
            knowledge_fields=(
                PRODUCT_KNOWLEDGE_FIELDS if product_id is not None else CLIENT_BASELINE_FIELDS
            ),
        ),
        product_id=product_id,
        base_version=base_version,
    )


def _entity_ref(entity_id: EntityId) -> Entity:
    return Entity(entity_id=entity_id, entity_type=EntityType.ACCOUNT)


async def _announce(
    on_field_progress: FieldProgress | None,
    conn: AsyncConnection,
    field_key: str,
    status: FieldProgressStatus,
) -> None:
    """Report one per-field status through the optional progress seam (no-op when unwired)."""
    if on_field_progress is not None:
        await on_field_progress(conn, field_key, status)


def _source_gate(
    gate: PreSpendGate | None,
    *,
    entity_id: EntityId,
    field_key: str,
    run_id: RunId,
    max_source_tier: int | None,
) -> SourceGate:
    async def allow(manifest: SourceManifest) -> bool:
        source_tier = manifest.tier
        if max_source_tier is not None and source_tier > max_source_tier:
            return False
        if gate is None:
            return True
        decision = await gate.check(
            PreSpendRequest(
                entity_id=entity_id,
                entity_type=EntityType.ACCOUNT,
                field_key=field_key,
                source_tier=source_tier,
                source_key=manifest.source_key,
                run_id=run_id,
            )
        )
        return decision.verdict is PreSpendVerdict.PASS

    return allow


async def _resolve_client(
    conn: AsyncConnection, client_input: ClientInput, *, workspace_id: str
) -> EntityId:
    """Resolve the client to a single, active ``account_entity``, idempotently across re-runs.

    The client is authoritative about themselves, so we resolve directly rather than through the
    fuzzy review queue (Doc B §4.1 is the *import* path, not the client's own identity). Three
    steps, each a deterministic-or-high-confidence reuse before admitting anything new:

    1. **resolve** — an exact domain/registry hit (score 1.0) or a high-confidence fuzzy hit
       (``>= _CLIENT_REUSE_MIN_SCORE``) reuses the survivor;
    2. **name-key alias** — a deterministic exact-name lookup (``resolve_alias``) catches the
       client's own prior-run entity when the website has **no registrable domain** (so step 1 goes
       fuzzy and scores below the reuse threshold) — the admit step records the name as an alias, so
       the *next* run finds it here, never spawning a duplicate;
    3. **admit** — only a genuinely unmatched client admits a fresh ``active`` entity (name aliased
       + embedded so subsequent runs and imported rows resolve to it)."""
    observation = Observation(name=client_input.name, domain=client_input.website)
    result = await resolve(conn, observation, workspace_id=workspace_id)
    top = result.top
    if top is not None and result.top_score >= _CLIENT_REUSE_MIN_SCORE:
        return await _ensure_active(
            conn, await surviving_id(conn, top.entity_id, observation.entity_type), observation
        )

    existing = await resolve_alias(
        conn, client_input.name, observation.entity_type, workspace_id=workspace_id
    )
    if existing is not None:
        return await _ensure_active(conn, existing, observation)

    entity_id = await insert_account_entity(
        conn,
        canonical_name=client_input.name,
        primary_domain=client_input.website,
        aliases=(client_input.name,),  # so a no-domain re-run resolves here via name-key (step 2)
        status=AccountStatus.ACTIVE,
        workspace_id=workspace_id,
    )
    # Embed so the next run's resolve (and any imported row naming the client) finds this entity.
    await embed_account(conn, entity_id)
    return entity_id


async def _ensure_active(
    conn: AsyncConnection, entity_id: EntityId, observation: Observation
) -> EntityId:
    """Promote a reused client entity to ``ACTIVE`` if still a candidate; return its id."""
    account = await get_account(conn, entity_id)
    if account is not None and account.status is not AccountStatus.ACTIVE:
        await set_status(conn, observation.entity_type, entity_id, AccountStatus.ACTIVE)
    return entity_id


async def _ingest_material(
    conn: AsyncConnection,
    material: VolunteeredMaterial,
    *,
    client_entity_id: EntityId,
    workspace_id: str,
    run_id: RunId,
    already_written: set[str],
    product_id: str | None,
    allowed_fields: frozenset[str],
) -> list[str]:
    """Write each fact a volunteered material asserts as a tier-1 ``human`` claim (idempotent on the
    run). Returns the field keys written. The raw excerpt becomes the ``evidence_span`` so even a
    volunteered fact is provenance-backed.

    Volunteered material *accelerates, never gates* (Doc B §1): a fact that is unregistered or
    fails its field's ``value_schema`` is **skipped**, not raised — one malformed entry in a deck
    can never abort the whole reverse-profiling run. (The schema check runs before any INSERT, so
    skipping leaves the caller-owned transaction clean.)"""
    written: list[str] = []
    span = (material.content or material.label or "client-volunteered material")[
        :_EVIDENCE_SPAN_MAX
    ]
    for field_key, value in material.asserted_fields.items():
        if field_key not in allowed_fields:
            continue
        if field_key in already_written:
            continue  # idempotent re-entry / already filled by an earlier material
        if (
            await get_effective_field(
                conn,
                scope=FieldRegistryScope.for_workspace(workspace_id),
                field_key=field_key,
            )
            is None
        ):
            continue  # only registered client fields are ingestible
        claim = account_claim(
            entity_id=client_entity_id,
            field_key=field_key,
            value_json=value,
            source_tier=_MATERIAL_TIER,
            extraction_method=ExtractionMethod.HUMAN,
            confidence=1.0,
            run_id=run_id,
            research_mode=_MODE,
            evidence_span=span,
        )
        claim = stamp_reuse(claim, workspace_id=workspace_id, policy=CLIENT_KNOWLEDGE_REUSE_POLICY)
        if product_id is not None:
            claim = claim.model_copy(update={"product_id": product_id})
        try:
            await insert_claim(conn, claim)
        except ValueSchemaError:
            continue  # a wrong-typed volunteered value is skipped, not fatal (Doc B §1)
        written.append(field_key)
        already_written.add(field_key)
    return written


async def _judge_tier4_claims(
    conn: AsyncConnection,
    client_entity_id: EntityId,
    *,
    run_id: RunId,
    scope: WorkspaceScope,
    judge: FaithfulnessJudge,
) -> list[JudgeResult]:
    """Run the injected faithfulness judge over any tier-4 client claims written this run.

    M5.1 *consumes* the judge seam (Beat-0); the tier-4 synthesis itself is a tier-4 resolver (M11)
    and the promotion transition is M9's. A span-less tier-4 claim is auto-``UNSUPPORTED`` and never
    surfaces in the merge regardless (``can_be_promoted`` / ``require_verified_tier4``), so this
    is a pure observability/seam hook today — the default tiers-1–3 pass produces no tier-4 claims.
    """
    verdicts: list[JudgeResult] = []
    for claim in await claims_for(conn, client_entity_id, scope=scope):
        if claim.run_id == run_id and claim.source_tier == 4 and claim.superseded_by is None:
            verdicts.append(await judge.judge(claim))
    return verdicts


def _coverage(
    filled: set[str],
    attempted: set[str],
    *,
    knowledge_fields: tuple[str, ...] = CLIENT_BASELINE_FIELDS,
) -> CoverageReport:
    """Build the per-field / per-surface-class coverage read for one run.

    ``filled`` = client fields that gained a live claim this run; ``attempted`` = fields the run
    actually reached (a superset of ``filled`` — it includes fields a resolver was consulted for but
    that missed, and excludes fields cut off by a budget halt). A surface is ``attempted`` iff the
    run reached ≥1 of its fields, so a budget-truncated run honestly reports later surfaces as
    *not* attempted (rather than a constant ``True``)."""
    empty = tuple(f for f in knowledge_fields if f not in filled)
    company_field_set = set(CLIENT_BASELINE_FIELDS)
    surfaces = (
        tuple(
            SurfaceCoverage(
                surface_class=surface_class,
                attempted=any(f in attempted for f in fields if f in knowledge_fields),
                filled_fields=tuple(f for f in fields if f in knowledge_fields and f in filled),
                empty_fields=tuple(f for f in fields if f in knowledge_fields and f not in filled),
            )
            for surface_class, fields in SURFACE_CLASS_FIELDS.items()
        )
        if set(knowledge_fields).issubset(company_field_set)
        else ()
    )
    return CoverageReport(
        filled_fields=tuple(f for f in knowledge_fields if f in filled),
        empty_fields=empty,
        surfaces=surfaces,
    )


async def _write_version_marker(
    conn: AsyncConnection,
    *,
    client_entity_id: EntityId,
    workspace_id: str,
    run_id: RunId,
    coverage: CoverageReport,
    product_id: str | None,
    base_version: int | None = None,
) -> int:
    """Write (or, on re-entry, reuse) the ``client.kb_version`` marker — the claim-store version
    ledger. A new run bumps the version and supersedes the prior marker; a re-entered run (same
    ``run_id``) reuses its already-written marker (idempotent)."""
    markers = await claims_for(
        conn,
        client_entity_id,
        CLIENT_KB_VERSION,
        include_superseded=True,
        scope=WorkspaceScope.for_workspace(workspace_id),
    )
    # ``None`` is the account-wide KB scope, not a wildcard over product-scoped markers. Keeping
    # these version sequences independent is required by production context composition: a newer
    # product-specific version must never replace the shared onboarding KB inherited by every
    # project in the workspace.
    markers = [marker for marker in markers if marker.product_id == product_id]

    existing_for_run = next((m for m in markers if m.run_id == run_id), None)
    if existing_for_run is not None:
        return _marker_version(existing_for_run)

    prior_versions = [_marker_version(m) for m in markers]
    version = (max(prior_versions) + 1) if prior_versions else 1

    value: dict[str, JsonValue] = {
        "version": version,
        "run_id": str(run_id),
        "filled_fields": coverage.filled_count,
        "total_fields": coverage.total_count,
    }
    if base_version is not None:
        value["base_version"] = base_version
    marker = account_claim(
        entity_id=client_entity_id,
        field_key=CLIENT_KB_VERSION,
        value_json=value,
        source_tier=1,
        extraction_method=ExtractionMethod.HUMAN,
        confidence=1.0,
        run_id=run_id,
        research_mode=_MODE,
    )
    marker = stamp_reuse(marker, workspace_id=workspace_id, policy=CLIENT_KNOWLEDGE_REUSE_POLICY)
    if product_id is not None:
        marker = marker.model_copy(update={"product_id": product_id})

    current_marker = next((m for m in markers if m.superseded_by is None), None)
    if current_marker is not None:
        await supersede_claim(conn, current_marker.id, marker)
    else:
        await insert_claim(conn, marker)
    return version


def _marker_version(claim: Claim) -> int:
    value = claim.value_json
    if isinstance(value, dict):
        version = value.get("version")
        if isinstance(version, int):
            return version
    return 0


def _marker_base_version(claim: Claim) -> int | None:
    value = claim.value_json
    if isinstance(value, dict):
        base = value.get("base_version")
        if isinstance(base, int) and base >= 1:
            return base
    return None


async def _lock_client_kb_scope(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    client_entity_id: EntityId,
    product_id: str | None,
) -> None:
    """Serialize version decisions for one company or exact-product KB sequence."""

    await conn.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
        {"key": (f"dynamic-client-kb:{workspace_id}:{client_entity_id}:{product_id or 'global'}")},
    )


async def ensure_product_kb_baseline(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    client_entity_id: EntityId,
    product_id: str,
    operation_key: str,
) -> ClientKbWriteTarget:
    """Return the current Product-KB, creating an honest empty v1 when none exists.

    Product selection needs a durable knowledge *lineage* even before any product fact has been
    admitted.  Unlike :func:`client_kb_write_target_for_materialization`, this operation never
    derives or advances an existing version: it is an idempotent container bootstrap, not a claim
    write target.  The empty marker reports 0/N coverage and lets the card expose every registered
    product field as an open gap without fabricating a claim or requiring a verification judge.
    """

    if not product_id.strip():
        raise ValueError("a Product-KB baseline requires a non-empty product id")
    await _lock_client_kb_scope(
        conn,
        workspace_id=workspace_id,
        client_entity_id=client_entity_id,
        product_id=product_id,
    )
    marker = await _pinned_marker(
        conn,
        client_entity_id,
        scope=WorkspaceScope.for_workspace(workspace_id),
        version=None,
        product_id=product_id,
    )
    if marker is not None:
        return ClientKbWriteTarget(version=_marker_version(marker), run_id=marker.run_id)

    run_id = RunId(
        uuid5(
            NAMESPACE_URL,
            f"stage0-product-kb-baseline:{workspace_id}:{client_entity_id}:{operation_key}",
        )
    )
    await record_run_lineage(conn, run_id=run_id, workspace_id=workspace_id, kind="stage0")
    version = await _write_version_marker(
        conn,
        client_entity_id=client_entity_id,
        workspace_id=workspace_id,
        run_id=run_id,
        coverage=_coverage(
            set(),
            set(),
            knowledge_fields=PRODUCT_KNOWLEDGE_FIELDS,
        ),
        product_id=product_id,
    )
    return ClientKbWriteTarget(version=version, run_id=run_id, created_new_version=True)


async def client_kb_write_target_for_materialization(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    client_entity_id: EntityId,
    product_id: str | None,
    operation_key: str,
    require_derived_version: bool = False,
) -> ClientKbWriteTarget:
    """Select the active KB run, or append a derived version when the current one is pinned.

    One transaction-scoped advisory lock serializes the read/new-version decision. A derived marker
    points at ``base_version``; its reader inherits those earlier run claims without copying or
    rewriting them, while the old pinned version remains byte- and claim-stable.

    ``require_derived_version`` is the composition seam for a caller that already owns an immutable
    read receipt outside the research subsystem (the production turn pin). It says only that the
    current marker cannot be extended; this module still owns version allocation, lineage,
    locking, and idempotency and therefore does not import the agent runtime or its tables.
    """

    await _lock_client_kb_scope(
        conn,
        workspace_id=workspace_id,
        client_entity_id=client_entity_id,
        product_id=product_id,
    )
    scope = WorkspaceScope.for_workspace(workspace_id)
    marker = await _pinned_marker(
        conn,
        client_entity_id,
        scope=scope,
        version=None,
        product_id=product_id,
    )
    run_id = RunId(
        uuid5(
            NAMESPACE_URL,
            f"stage0-dynamic-client-kb:{workspace_id}:{client_entity_id}:{operation_key}",
        )
    )
    if marker is None:
        # FI-2 P2 (spec §3): a workspace-level stage-0 run (no project). Registered only on the
        # branches that actually mint a new version — the reuse branch below returns the *existing*
        # run, already registered by whoever created it, so nothing is registered that never wrote.
        await record_run_lineage(conn, run_id=run_id, workspace_id=workspace_id, kind="stage0")
        version = await _write_version_marker(
            conn,
            client_entity_id=client_entity_id,
            workspace_id=workspace_id,
            run_id=run_id,
            coverage=_coverage(
                set(),
                set(),
                knowledge_fields=(
                    PRODUCT_KNOWLEDGE_FIELDS if product_id is not None else CLIENT_BASELINE_FIELDS
                ),
            ),
            product_id=product_id,
        )
        return ClientKbWriteTarget(version=version, run_id=run_id, created_new_version=True)

    version = _marker_version(marker)
    pinned = (
        await conn.execute(
            text(
                """
                SELECT EXISTS (
                    SELECT 1 FROM icp_spec
                    WHERE workspace_id = :workspace_id
                      AND client_entity_id = :client_entity_id
                      AND client_kb_version = :version
                      AND product_id IS NOT DISTINCT FROM :product_id
                      AND status = 'active'
                    UNION ALL
                    SELECT 1 FROM product_context_version
                    WHERE workspace_id = :workspace_id
                      AND client_entity_id = :client_entity_id
                      AND client_kb_version = :version
                      AND (
                          :product_id IS NULL
                          OR product_id IS NOT DISTINCT FROM :product_id
                      )
                    UNION ALL
                    SELECT 1 FROM project_run
                    WHERE workspace_id = :workspace_id
                      AND client_entity_id = :client_entity_id
                      AND client_kb_version = :version
                      AND product_id IS NOT DISTINCT FROM :product_id
                )
                """
            ),
            {
                "workspace_id": workspace_id,
                "client_entity_id": client_entity_id,
                "version": version,
                "product_id": product_id,
            },
        )
    ).scalar_one()
    if not pinned and not require_derived_version:
        return ClientKbWriteTarget(version=version, run_id=marker.run_id)

    prior_claims = await _pinned_field_claims(
        conn,
        client_entity_id,
        scope=scope,
        version=version,
        product_id=product_id,
    )
    knowledge_fields = (
        PRODUCT_KNOWLEDGE_FIELDS if product_id is not None else CLIENT_BASELINE_FIELDS
    )
    filled = set(prior_claims).intersection(knowledge_fields)
    # FI-2 P2 (spec §3), the derived-version branch: same workspace-level stage-0 registration as
    # the new-KB branch above, again only where a new version is actually minted.
    await record_run_lineage(conn, run_id=run_id, workspace_id=workspace_id, kind="stage0")
    new_version = await _write_version_marker(
        conn,
        client_entity_id=client_entity_id,
        workspace_id=workspace_id,
        run_id=run_id,
        coverage=_coverage(filled, set(knowledge_fields), knowledge_fields=knowledge_fields),
        product_id=product_id,
        base_version=version,
    )
    return ClientKbWriteTarget(version=new_version, run_id=run_id, created_new_version=True)


# --- read API (consumed by M5.2 ICP synthesis, M12 positioning) -------------


async def current_kb_version(
    conn: AsyncConnection,
    client_entity_id: EntityId,
    *,
    workspace_id: str,
    product_id: str | None = None,
) -> int | None:
    """The current Client Knowledge Base version (the non-superseded marker), or ``None`` if the
    client has never been reverse-profiled."""
    markers = await claims_for(
        conn,
        client_entity_id,
        CLIENT_KB_VERSION,
        include_superseded=False,
        scope=WorkspaceScope.for_workspace(workspace_id),
    )
    markers = [marker for marker in markers if marker.product_id == product_id]
    versions = [_marker_version(m) for m in markers]
    return max(versions) if versions else None


async def _pinned_marker(
    conn: AsyncConnection,
    client_entity_id: EntityId,
    *,
    scope: WorkspaceScope,
    version: int | None,
    product_id: str | None,
) -> Claim | None:
    """The ``client.kb_version`` marker pinning a KB version (latest when ``version is None``), or
    ``None`` if the client has never been profiled / the asked-for version does not exist. The one
    version-resolution rule shared by :func:`read_client_kb` and :func:`read_client_kb_claims`."""
    markers = await claims_for(
        conn, client_entity_id, CLIENT_KB_VERSION, include_superseded=True, scope=scope
    )
    markers = [marker for marker in markers if marker.product_id == product_id]
    if not markers:
        return None
    if version is None:
        return max(markers, key=_marker_version)
    return next((m for m in markers if _marker_version(m) == version), None)


async def _pinned_field_claims(
    conn: AsyncConnection,
    client_entity_id: EntityId,
    *,
    scope: WorkspaceScope,
    version: int | None,
    product_id: str | None,
) -> dict[str, Claim]:
    """The Client Knowledge Base as ``{field_key: winning Claim}`` for a version (the latest claim
    per field written by the pinned version's run). Version-scoped exactly like
    :func:`read_client_kb` (a field the run did not (re-)derive is absent)."""
    marker = await _pinned_marker(
        conn,
        client_entity_id,
        scope=scope,
        version=version,
        product_id=product_id,
    )
    if marker is None:
        return {}
    if scope.workspace_id is None:
        raise ValueError("Client-KB reads require a workspace-scoped claim selector")
    definitions = await list_effective_fields(
        conn,
        scope=FieldRegistryScope.for_workspace(scope.workspace_id),
        filters=FieldFilters(pack="client", active=None),
        include_retired=True,
    )
    allowed_product_scopes = (
        {ProductScopePolicy.FORBIDDEN, ProductScopePolicy.OPTIONAL}
        if product_id is None
        else {ProductScopePolicy.REQUIRED, ProductScopePolicy.OPTIONAL}
    )
    knowledge_fields = {
        item.field_def.field_key
        for item in definitions
        if item.field_def.field_key != CLIENT_KB_VERSION
        and resolve_product_scope(item.field_def) in allowed_product_scopes
    }
    markers = await claims_for(
        conn, client_entity_id, CLIENT_KB_VERSION, include_superseded=True, scope=scope
    )
    markers = [item for item in markers if item.product_id == product_id]
    by_version = {_marker_version(item): item for item in markers}
    run_ids: list[RunId] = []
    seen_versions: set[int] = set()
    current: Claim | None = marker
    while current is not None:
        marker_version = _marker_version(current)
        if marker_version in seen_versions:
            raise RuntimeError("Client-KB marker base-version cycle detected")
        seen_versions.add(marker_version)
        run_ids.append(current.run_id)
        base_version = _marker_base_version(current)
        current = by_version.get(base_version) if base_version is not None else None

    claims = await claims_for(conn, client_entity_id, include_superseded=True, scope=scope)
    pinned: dict[str, Claim] = {}
    for run_id in run_ids:
        for claim in claims:
            if (
                claim.run_id == run_id
                and claim.field_key in knowledge_fields
                and claim.field_key not in pinned
                and claim.product_id == product_id
            ):
                pinned[claim.field_key] = claim
    return pinned


async def read_client_kb(
    conn: AsyncConnection,
    client_entity_id: EntityId,
    *,
    workspace_id: str,
    version: int | None = None,
    product_id: str | None = None,
) -> dict[str, JsonValue]:
    """Read the Client Knowledge Base as a ``{field_key: value}`` map, **scoped to a KB version**.

    With ``version=None`` returns the **current** version's values — the canonical current-truth
    read: it is the latest run's as-written values, so a field the latest run could not re-derive is
    correctly *absent* (not carried forward). With a pinned ``version`` returns that version's
    values, so a value narrative can pin to the base it was built against (substrate §8 drift).

    The raw ``current_value`` merge seam is deliberately NOT used here: that seam carries a prior
    value forward under trust+freshness until its TTL ages it out; this read is version-correct.
    Both paths read with ``include_superseded`` so a prior version stays queryable (append-only)."""
    scope = WorkspaceScope.for_workspace(workspace_id)
    pinned = await _pinned_field_claims(
        conn,
        client_entity_id,
        scope=scope,
        version=version,
        product_id=product_id,
    )
    return {field_key: claim.value_json for field_key, claim in pinned.items()}


async def read_client_kb_claims(
    conn: AsyncConnection,
    client_entity_id: EntityId,
    *,
    workspace_id: str,
    version: int | None = None,
    product_id: str | None = None,
) -> dict[str, Claim]:
    """Like :func:`read_client_kb`, but returns the underlying ``{field_key: Claim}`` for a version.

    M5.2 ICP synthesis reads through this so every proposed dimension can cite the **claim_id** of
    the client fact that justifies it (``justifying_claim_ids`` — no proposal element justified by
    "synthesis thought it was a good idea"). Same version-scoping as :func:`read_client_kb`."""
    scope = WorkspaceScope.for_workspace(workspace_id)
    return await _pinned_field_claims(
        conn,
        client_entity_id,
        scope=scope,
        version=version,
        product_id=product_id,
    )


def client_kb_readiness_metrics(
    claims: Mapping[str, Claim],
    *,
    baseline_field_keys: Sequence[str] = CLIENT_BASELINE_FIELDS,
    required_field_keys: Sequence[str] = (),
) -> dict[str, JsonValue]:
    """Compile the one Client-KB metric set every Stage-0 readiness evaluation is scored against.

    The default is the complete account-wide company-knowledge set for compatibility. Production
    gate callers name their denominator explicitly: ICP synthesis passes its stable nine fields;
    discovery/deep gates pass the broader company set. Onboarding progress is not a readiness gate
    and uses its separate eleven-field checklist policy.

    :func:`~clue_research.stage0.evaluate_readiness` gates on these exact keys, and the metrics are
    persisted verbatim into ``readiness_decision.metrics`` — the human-facing, deterministic
    explanation of a verdict. Two surfaces compiling them independently is how a ledger starts
    telling two stories about one trial, so this is the single definition and every caller uses it.

    Definitions, each meaning what its name says:

    * ``available_field_keys`` — the pinned claims intersected with the effective expected-field
      set: the caller's gate-specific platform baseline plus tenant-local required-field
      extensions. A pinned KB may carry other claims (the ``client.kb_version`` marker itself,
      for one), and counting those would report coverage of fields the policy never asked for;
    * ``coverage_ratio`` — that intersection over the effective expected-field set, so it cannot
      exceed 1.0. An empty effective set reports 0.0 rather than manufacturing 0/0 readiness;
    * ``verified_claims`` — effective expected-field claims that actually reached
      :attr:`~clue_core.VerificationStatus.VERIFIED`, never the raw claim count. The floors read
      this as an *evidence* floor, so counting unverified claims would let unverified work clear
      it, and counting a non-pack bookkeeping claim would let the version marker clear it.

    All three therefore describe the same set — the pack fields this KB version actually carries —
    so a reader cannot compose them into a contradiction.

    ``open_policy_blocks`` is deliberately absent rather than asserted as 0: a caller that tracks
    policy blocks supplies its own count, and the evaluator already defaults a missing key.
    """

    expected_fields = set(baseline_field_keys).union(required_field_keys)
    available = sorted(expected_fields.intersection(claims))
    return {
        "coverage_ratio": (len(available) / len(expected_fields) if expected_fields else 0.0),
        "verified_claims": sum(
            claims[field_key].verification_status is VerificationStatus.VERIFIED
            for field_key in available
        ),
        "available_field_keys": cast(list[JsonValue], available),
    }
