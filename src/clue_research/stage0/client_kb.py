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

from decimal import Decimal

from pydantic import JsonValue
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_core import (
    AccountStatus,
    Claim,
    Entity,
    EntityId,
    EntityType,
    ExtractionMethod,
    FaithfulnessJudge,
    JudgeResult,
    ResearchMode,
    RunId,
    account_claim,
    new_run_id,
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
    ValueSchemaError,
    WorkspaceScope,
    claims_for,
    get_field,
    insert_claim,
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
    CLIENT_KB_VERSION,
    CLIENT_KNOWLEDGE_FIELDS,
    SURFACE_CLASS_FIELDS,
    load_client_knowledge_pack,
)
from clue_research.stage0.reuse import CLIENT_KNOWLEDGE_REUSE_POLICY
from clue_research.stage0.types import (
    ClientInput,
    ClientKnowledgeBaseRef,
    CoverageReport,
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


async def reverse_profile(
    conn: AsyncConnection,
    client_input: ClientInput,
    *,
    workspace_id: str,
    run_id: RunId | None = None,
    budget_cap_cents: Decimal | None = None,
    judge: FaithfulnessJudge | None = None,
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

    ``judge`` is the injected M9 seam used only for tier-4 client claims (consumed behind the judge
    — the tier-4 *synthesis* is M11). It is optional: the default tiers-1–3 pass needs no judge.
    """
    scope = WorkspaceScope.for_workspace(workspace_id)
    run = run_id if run_id is not None else new_run_id()

    with traced_step(
        "stage0.reverse_profile",
        **{ATTR_WORKSPACE_ID: workspace_id},
    ) as span:
        # Field registry must carry the client.* fields before any client claim is written.
        await load_client_knowledge_pack(conn)

        client_entity_id = await _resolve_client(conn, client_input)
        apply_attributes(span, {ATTR_ENTITY_ID: client_entity_id})

        # Fields already filled by a volunteered (HUMAN) claim under THIS run — for idempotent
        # re-entry, so resuming neither re-ingests a material nor re-spends on a field it filled.
        material_fields = {
            c.field_key
            for c in await claims_for(conn, client_entity_id, scope=scope)
            if c.run_id == run and c.extraction_method is ExtractionMethod.HUMAN
        }

        spent = Decimal(0)
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
            )
            claims_written += len(wrote)
        filled_fields |= material_fields  # incl. fields carried in from a re-entered run
        attempted_fields |= material_fields

        # 2) Drive the waterfall (tiers 1–3) over each still-empty client field, honoring the cap.
        budget_exhausted = False
        for field_key in CLIENT_KNOWLEDGE_FIELDS:
            if field_key in material_fields:
                continue  # a volunteered fact already fills it — do not spend to re-derive
            if budget_cap_cents is not None and spent >= budget_cap_cents:
                budget_exhausted = True
                break  # outer cap: do not reach later fields (they stay un-attempted)
            field_def = await get_field(conn, field_key)
            if field_def is None:
                continue  # defensive: pack load above guarantees presence
            attempted_fields.add(field_key)
            result = await resolve_field(
                conn,
                _entity_ref(client_entity_id),
                field_def,
                mode=_MODE,
                run_id=run,
                workspace_id=workspace_id,
                budget_envelope=budget_cap_cents,
                cost_so_far=spent,
                reuse_policy=CLIENT_KNOWLEDGE_REUSE_POLICY,
            )
            spent += result.total_cost_cents
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
        coverage = _coverage(filled_fields, attempted_fields)
        version = await _write_version_marker(
            conn,
            client_entity_id=client_entity_id,
            workspace_id=workspace_id,
            run_id=run,
            coverage=coverage,
        )

        apply_attributes(span, {ATTR_COST_CENTS: spent, ATTR_N_CLAIMS: claims_written})

    return ReverseProfileResult(
        ref=ClientKnowledgeBaseRef(client_entity_id=client_entity_id, client_kb_version=version),
        run_id=run,
        coverage=coverage,
        cost_cents=spent,
        fields_resolved=len(filled_fields),
        budget_exhausted=budget_exhausted,
    )


# --- helpers ----------------------------------------------------------------


def _entity_ref(entity_id: EntityId) -> Entity:
    return Entity(entity_id=entity_id, entity_type=EntityType.ACCOUNT)


async def _resolve_client(conn: AsyncConnection, client_input: ClientInput) -> EntityId:
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
    result = await resolve(conn, observation)
    top = result.top
    if top is not None and result.top_score >= _CLIENT_REUSE_MIN_SCORE:
        return await _ensure_active(
            conn, await surviving_id(conn, top.entity_id, observation.entity_type), observation
        )

    existing = await resolve_alias(conn, client_input.name, observation.entity_type)
    if existing is not None:
        return await _ensure_active(conn, existing, observation)

    entity_id = await insert_account_entity(
        conn,
        canonical_name=client_input.name,
        primary_domain=client_input.website,
        aliases=(client_input.name,),  # so a no-domain re-run resolves here via name-key (step 2)
        status=AccountStatus.ACTIVE,
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
        if field_key in already_written:
            continue  # idempotent re-entry / already filled by an earlier material
        if await get_field(conn, field_key) is None:
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


def _coverage(filled: set[str], attempted: set[str]) -> CoverageReport:
    """Build the per-field / per-surface-class coverage read for one run.

    ``filled`` = client fields that gained a live claim this run; ``attempted`` = fields the run
    actually reached (a superset of ``filled`` — it includes fields a resolver was consulted for but
    that missed, and excludes fields cut off by a budget halt). A surface is ``attempted`` iff the
    run reached ≥1 of its fields, so a budget-truncated run honestly reports later surfaces as
    *not* attempted (rather than a constant ``True``)."""
    empty = tuple(f for f in CLIENT_KNOWLEDGE_FIELDS if f not in filled)
    surfaces = tuple(
        SurfaceCoverage(
            surface_class=surface_class,
            attempted=any(f in attempted for f in fields),
            filled_fields=tuple(f for f in fields if f in filled),
            empty_fields=tuple(f for f in fields if f not in filled),
        )
        for surface_class, fields in SURFACE_CLASS_FIELDS.items()
    )
    return CoverageReport(
        filled_fields=tuple(f for f in CLIENT_KNOWLEDGE_FIELDS if f in filled),
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


# --- read API (consumed by M5.2 ICP synthesis, M12 positioning) -------------


async def current_kb_version(
    conn: AsyncConnection, client_entity_id: EntityId, *, workspace_id: str
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
    versions = [_marker_version(m) for m in markers]
    return max(versions) if versions else None


async def _pinned_marker(
    conn: AsyncConnection,
    client_entity_id: EntityId,
    *,
    scope: WorkspaceScope,
    version: int | None,
) -> Claim | None:
    """The ``client.kb_version`` marker pinning a KB version (latest when ``version is None``), or
    ``None`` if the client has never been profiled / the asked-for version does not exist. The one
    version-resolution rule shared by :func:`read_client_kb` and :func:`read_client_kb_claims`."""
    markers = await claims_for(
        conn, client_entity_id, CLIENT_KB_VERSION, include_superseded=True, scope=scope
    )
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
) -> dict[str, Claim]:
    """The Client Knowledge Base as ``{field_key: winning Claim}`` for a version (the latest claim
    per field written by the pinned version's run). Version-scoped exactly like
    :func:`read_client_kb` (a field the run did not (re-)derive is absent)."""
    marker = await _pinned_marker(conn, client_entity_id, scope=scope, version=version)
    if marker is None:
        return {}
    run_id = marker.run_id
    pinned: dict[str, Claim] = {}
    for claim in await claims_for(conn, client_entity_id, include_superseded=True, scope=scope):
        if (
            claim.run_id == run_id
            and claim.field_key in CLIENT_KNOWLEDGE_FIELDS
            and claim.field_key not in pinned
        ):
            pinned[claim.field_key] = claim
    return pinned


async def read_client_kb(
    conn: AsyncConnection,
    client_entity_id: EntityId,
    *,
    workspace_id: str,
    version: int | None = None,
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
    pinned = await _pinned_field_claims(conn, client_entity_id, scope=scope, version=version)
    return {field_key: claim.value_json for field_key, claim in pinned.items()}


async def read_client_kb_claims(
    conn: AsyncConnection,
    client_entity_id: EntityId,
    *,
    workspace_id: str,
    version: int | None = None,
) -> dict[str, Claim]:
    """Like :func:`read_client_kb`, but returns the underlying ``{field_key: Claim}`` for a version.

    M5.2 ICP synthesis reads through this so every proposed dimension can cite the **claim_id** of
    the client fact that justifies it (``justifying_claim_ids`` — no proposal element justified by
    "synthesis thought it was a good idea"). Same version-scoping as :func:`read_client_kb`."""
    scope = WorkspaceScope.for_workspace(workspace_id)
    return await _pinned_field_claims(conn, client_entity_id, scope=scope, version=version)
