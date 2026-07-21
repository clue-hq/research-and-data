"""``run_pipeline`` — the fetch → adapt → extract dispatch (M4.3 / ENG-116).

Given a source's manifest (``modality`` / ``requires_adapter``), select the right adapter, run its
three stages, and turn the resulting :class:`~clue_core.ClaimDraft`s into typed ``Claim``s
written through the M1.1 store — so a resolver that needs adaptation (M4.5 Firecrawl) or a deep-pass
worker (M8) calls one function instead of hand-rolling fetch/transcribe/parse. Adding a new modality
is a :func:`~clue_research.adapters.registry.register_adapter` call — no pipeline fork (§7b).

Invariants enforced (substrate §4 / D7 / the M4.3 acceptance criteria):

* **Adaptation never upgrades trust.** The claim's ``source_tier`` + ``extraction_method`` come from
  the *manifest*, not the extractor — a transcribed podcast stays its manifest tier, never tier-1.
* **Span grounded.** Every draft's ``evidence_span`` must be an exact slice of the normalized text,
  else the pipeline fails loud (a value with no source span is the one real failure — substrate §4).
* **Gated spend.** The caller's ``gate_decision`` is honored verbatim: ``skip`` makes **no** fetch /
  transcription call (M4.3 exposes ``cost_estimate`` + obeys; M4.6/M8/M7 *decide*, staged-flow §7d).
* **Costly ops once.** The (optional, caller-owned) content-addressed ``cache`` reuses a normalized
  artifact for a repeated ``ref`` at zero re-incur, respecting the manifest ``freshness_profile``.
* **Per-stage observability.** fetch / adapt / extract each emit their own cost+latency span; the
  transcription cost is the ``adapt`` span for audio/video (a distinct, queryable cost — M7.5/M13).

Reuse-scope note (M4.5, decision #6): when ``persist=True`` this function is a *composer* (it writes
claims), so — exactly like the M4.1 waterfall — it **tenant-stamps every claim** via
``identity.stamp_reuse`` before insert: public-footprint facts amortize; ``crm_import`` / resonance
/ personal / scoring claims become ``tenant_private`` bound to the supplied ``workspace_id`` (and a
private-classifying claim with no ``workspace_id`` fails loud — no silent public leak). A resolver
that
wants the waterfall to be the sole writer (M4.5's Firecrawl) calls :func:`run_chain` with
``persist=False`` instead; the waterfall then stamps. (ENG-165 makes this stamping structural and
fail-closed across *all* writers; this is M4's per-writer wiring.)
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timedelta
from decimal import Decimal
from time import perf_counter

from pydantic import JsonValue
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_core import (
    AdaptContext,
    Claim,
    ClaimDraft,
    CostCents,
    Entity,
    EntityType,
    ExtractionMethod,
    FieldDef,
    GateDecision,
    Modality,
    ModalityAdapter,
    NormalizedText,
    ResearchMode,
    RunId,
    account_claim,
    contact_claim,
    revalidate_with,
    to_value_json,
)
from clue_obs.otel import (
    ATTR_CACHE_HIT,
    ATTR_COST_CENTS,
    ATTR_COST_ESTIMATE_CENTS,
    ATTR_ENTITY_ID,
    ATTR_FIELD_KEY,
    ATTR_GATE_DECISION,
    ATTR_LATENCY_MS,
    ATTR_MODALITY,
    ATTR_N_CLAIMS,
    ATTR_RESEARCH_MODE,
    ATTR_RUN_ID,
    ATTR_SOURCE_KEY,
    ATTR_SOURCE_TIER,
    adapter_span,
    apply_attributes,
    traced_step,
)
from clue_research.adapters.cache import (
    ArtifactCache,
    CachedArtifact,
    content_key,
    freshness_ttl,
    is_fresh,
    utc_now,
)
from clue_research.adapters.concrete import PassthroughAdapter
from clue_research.adapters.registry import (
    AdapterNotRegisteredError,
    get_adapter,
    is_adapter_registered,
)
from clue_research.adapters.seams import AdaptError, ClaimExtractor
from clue_research.claimstore import insert_claim
from clue_research.identity import DEFAULT_REUSE_POLICY, ReusePolicy, stamp_reuse
from clue_research.sources import RegistrySourceManifest, get_source
from clue_storage import SnapshotSink, StorageBackend, flush_snapshots


class UnknownSourceError(LookupError):
    """``run_pipeline`` / ``cost_estimate`` was called for an unregistered ``source_key`` (M4.2)."""


# Modality → claim ``extraction_method`` (so adaptation records HOW, never upgrading trust).
# Tier-4 is LLM synthesis by the claim invariant (substrate §4) — M4.3 ships tiers 1–3, so this only
# guards a mis-tiered source; tier-4 synthesis extraction itself is M11.
_EXTRACTION_BY_MODALITY: dict[Modality, ExtractionMethod] = {
    Modality.STRUCTURED: ExtractionMethod.API,
    Modality.TEXT: ExtractionMethod.SCRAPE,
    Modality.PDF: ExtractionMethod.SCRAPE,
    Modality.VIDEO: ExtractionMethod.SCRAPE,
    Modality.AUDIO: ExtractionMethod.SCRAPE,
}
_TRANSCRIBED_MODALITIES = frozenset({Modality.AUDIO, Modality.VIDEO})


def _estimate(manifest: RegistrySourceManifest, ref: str) -> CostCents:
    """The pre-spend cost estimate for adapting ``ref`` (the manifest's declared per-call cost — the
    gating input the planner reads, D7). ``ref`` lets a future adapter refine it (e.g. a
    podcast's duration); both :func:`cost_estimate` and run_pipeline's span estimate route through
    here so the gate input and the trace estimate never drift."""
    return manifest.cost_cents


async def cost_estimate(conn: AsyncConnection, source_key: str, ref: str) -> CostCents:
    """The pre-spend cost estimate for adapting ``ref`` from ``source_key`` (see :func:`_estimate`).
    Raises :class:`UnknownSourceError` if the source is not registered."""
    manifest = await get_source(conn, source_key)
    if manifest is None:
        raise UnknownSourceError(f"source {source_key!r} is not registered (M4.2)")
    return _estimate(manifest, ref)


async def run_pipeline(
    conn: AsyncConnection,
    source_key: str,
    ref: str,
    entity: Entity,
    field: FieldDef,
    *,
    run_id: RunId,
    research_mode: ResearchMode,
    extractor: ClaimExtractor,
    gate_decision: GateDecision = GateDecision.RUN,
    cache: ArtifactCache | None = None,
    clock: Callable[[], datetime] = utc_now,
    persist: bool = True,
    workspace_id: str | None = None,
    reuse_policy: ReusePolicy = DEFAULT_REUSE_POLICY,
    params: dict[str, JsonValue] | None = None,
    snapshots: SnapshotSink | None = None,
    storage: StorageBackend | None = None,
) -> list[Claim]:
    """Run ``source_key``'s ``fetch → adapt → extract`` for ``ref`` and return the resulting claims.

    Args:
        conn: the caller-owned transaction (claims are inserted inside it when ``persist``).
        source_key: a registered M4.2 source; its manifest selects the adapter + stamps tier/cost.
        ref: the artifact reference (URL / path / inline) the adapter's transport fetches.
        entity, field: the resolved entity and the field being populated (the claims' target-lock).
        run_id, research_mode: the run provenance on every claim (the resolver can't know it).
        extractor: the field-specific extraction seam (normalized text → claim drafts). The adapter
            is a pure normalizer (``fetch`` + ``adapt``), so extraction is **always** this per-call
            seam — and it also enables the built-in text/structured passthrough when no adapter is
            registered. A SKIP gate short-circuits before it runs, but the caller still declares it.
        gate_decision: ``skip`` returns ``[]`` without any fetch/transcription (still tracing the
            ``cost_estimate``); ``run`` proceeds.
        cache: an optional content-addressed artifact cache; pass a per-run instance to dedupe
            costly fetch/transcription across fields within a run (``None`` = no caching).
        clock: the time source (injected for deterministic freshness-TTL tests).
        persist: write the claims through M1.1 (default). ``False`` returns unwritten claims — the
            seam M4.5's Firecrawl resolver uses to return claims to the waterfall without a
            double-write (the waterfall is then the sole writer + tenant-stamper).
        workspace_id: the run's workspace. When ``persist`` (this function is the writer), every
            claim is
            tenant-stamped before insert (decision #6): public facts amortize; a private-classifying
            claim (crm_import / resonance / personal / scoring) is bound to ``workspace_id`` — and a
            private claim with **no** ``workspace_id`` fails loud, never silently written public.
        reuse_policy: the versioned reuse-classification policy the stamping reads.
        params: free-form fetch params handed to the adapter via the :class:`AdaptContext`.
        snapshots: an optional per-run evidence-snapshot sink (PB-B2.3): the fetched bytes are
            captured at the moment they exist and every claim carries the snapshot's
            ``artifact_key``, so its evidence resolves offline after the live URL rots.
        storage: the durable backend the sink flushes to. When ``persist`` and both are supplied,
            pending captures are flushed (blob + ``artifact`` row) *before* the claims are
            inserted (the FK ordering). With ``persist=False`` the caller that writes the claims
            (the waterfall) owns the flush.

    Returns the claims (written, with persisted ids, when ``persist``). Adding a brand-new modality
    adapter makes its source consumable here with **no** change to the waterfall (M4.1) or a worker.
    """
    manifest = await get_source(conn, source_key)
    if manifest is None:
        raise UnknownSourceError(f"source {source_key!r} is not registered (M4.2)")
    claims = run_chain(
        manifest,
        ref,
        entity,
        field,
        run_id=run_id,
        research_mode=research_mode,
        extractor=extractor,
        gate_decision=gate_decision,
        cache=cache,
        clock=clock,
        params=params,
        snapshots=snapshots,
    )
    if persist:
        # Flush captured evidence snapshots BEFORE the claims that reference them (the
        # claim.artifact_key FK lands on an existing artifact row). Idempotent: a re-run or a
        # shared sink converges on one blob + one row per distinct content.
        if snapshots is not None and storage is not None and snapshots.pending:
            await flush_snapshots(conn, storage, snapshots)
        # As a composer (the writer), stamp the cross-tenant reuse scope on every claim before
        # insert — identical to the M4.1 waterfall (decision #6), so an adapter-backed
        # tenant-private claim (M8 resonance/facet) is never written public_footprint by default.
        return [
            await _persist(conn, stamp_reuse(c, workspace_id=workspace_id, policy=reuse_policy))
            for c in claims
        ]
    return claims


async def _persist(conn: AsyncConnection, claim: Claim) -> Claim:
    """Write one (already tenant-stamped) claim through M1.1 and return it (ids are
    client-generated, so the returned object is the one the caller gets back)."""
    await insert_claim(conn, claim)
    return claim


def run_chain(
    manifest: RegistrySourceManifest,
    ref: str,
    entity: Entity,
    field: FieldDef,
    *,
    run_id: RunId,
    research_mode: ResearchMode,
    extractor: ClaimExtractor,
    gate_decision: GateDecision = GateDecision.RUN,
    cache: ArtifactCache | None = None,
    clock: Callable[[], datetime] = utc_now,
    params: dict[str, JsonValue] | None = None,
    snapshots: SnapshotSink | None = None,
) -> list[Claim]:
    """The **synchronous** ``fetch → adapt → extract → materialize`` core of :func:`run_pipeline`,
    over an already-loaded ``manifest`` and **without** persistence — the seam a *resolver* uses.

    The ``Resolver`` protocol is synchronous and connection-less (the waterfall calls ``resolve``
    sync and writes the returned claims), but the adapter chain itself is pure/sync — only
    ``get_source`` and ``insert_claim`` are async DB work. So M4.5's Firecrawl resolver, given the
    seed manifest, calls this from inside ``resolve`` to run the M4.3 HTML→markdown adapter (it does
    **not** hand-roll fetch/parse) and returns the materialized-but-unwritten claims to the
    waterfall, which persists them and stamps the engine-owned ``run_id``/``source_key``. The
    relationship is exactly ``run_pipeline = get_source + run_chain + (persist)`` — one chain, one
    materialize, no duplication (conventions §2 DRY). ``run_id``/``research_mode`` may be the
    resolver's placeholders; the waterfall overwrites them (adaptation never owns run provenance).
    """
    source_key = manifest.source_key
    estimate = _estimate(manifest, ref)
    ctx = AdaptContext(
        source_key=source_key,
        auth_ref=manifest.auth_ref,
        freshness_profile=manifest.freshness_profile,
        params=dict(params or {}),
    )

    with traced_step(
        adapter_span("pipeline", source_key),
        **{
            ATTR_SOURCE_KEY: source_key,
            ATTR_SOURCE_TIER: manifest.tier,
            ATTR_ENTITY_ID: entity.entity_id,
            ATTR_FIELD_KEY: field.field_key,
            ATTR_RUN_ID: run_id,
            ATTR_RESEARCH_MODE: research_mode,
            ATTR_MODALITY: manifest.modality.value,
            ATTR_GATE_DECISION: gate_decision.value,
            ATTR_COST_ESTIMATE_CENTS: estimate,
        },
    ) as span:
        if gate_decision is GateDecision.SKIP:
            # Expensive call NOT made: the planner/worker decided this source isn't worth it. The
            # estimate is still on the span (exposed) so the gate's cost reasoning is observable.
            apply_attributes(span, {ATTR_N_CLAIMS: 0, ATTR_CACHE_HIT: False})
            return []

        adapter = _select_adapter(manifest)
        normalized, realized_cost, cache_hit, snapshot_key = _fetch_and_adapt(
            adapter,
            ref,
            ctx,
            manifest,
            cache=cache,
            clock=clock,
            estimate=estimate,
            snapshots=snapshots,
        )
        drafts = _extract(extractor, normalized, entity, field, source_key)
        claims = _materialize(
            drafts,
            manifest=manifest,
            ref=ref,
            run_id=run_id,
            research_mode=research_mode,
            entity=entity,
            realized_cost=realized_cost,
            artifact_key=snapshot_key,
        )
        # The realized cost lives on the fetch/adapt *stage* span (a child of this one), not here:
        # emitting it on both levels would double-count a span-tree SUM of cost_cents. The parent
        # carries only the cost ESTIMATE (set at open) + the outcome counters.
        apply_attributes(span, {ATTR_N_CLAIMS: len(claims), ATTR_CACHE_HIT: cache_hit})
        return claims


def _select_adapter(manifest: RegistrySourceManifest) -> ModalityAdapter:
    """Pick the adapter for a source: a source-specific ``requires_adapter`` key, else the modality
    default; for ``text``/``structured`` that declared **no** specific adapter, the built-in
    passthrough normalizer. ``pdf``/``audio``/``video`` — and any source that explicitly named a
    ``requires_adapter`` — REQUIRE a registered adapter; a missing one is
    :class:`AdapterNotRegisteredError`, not a crash."""
    adapter_key = manifest.requires_adapter or manifest.modality.value
    if is_adapter_registered(adapter_key):
        return get_adapter(adapter_key)
    # The passthrough is a convenience ONLY for a text/structured source that declared no specific
    # adapter. A source that explicitly named a ``requires_adapter`` (e.g. firecrawl_site →
    # firecrawl_html) whose adapter is unregistered must fail loud — substituting passthrough
    # would extract from the un-normalized ref (a misconfiguration masquerading as a fallback).
    if manifest.requires_adapter is None and manifest.modality in (
        Modality.TEXT,
        Modality.STRUCTURED,
    ):
        return PassthroughAdapter(modality=manifest.modality)
    raise AdapterNotRegisteredError(
        f"no adapter registered for key {adapter_key!r} (source {manifest.source_key!r}, modality "
        f"{manifest.modality.value}); register one with register_adapter"
    )


def _fetch_and_adapt(
    adapter: ModalityAdapter,
    ref: str,
    ctx: AdaptContext,
    manifest: RegistrySourceManifest,
    *,
    cache: ArtifactCache | None,
    clock: Callable[[], datetime],
    estimate: CostCents,
    snapshots: SnapshotSink | None = None,
) -> tuple[NormalizedText, CostCents, bool, str | None]:
    """Run transport + normalization (with per-stage cost+latency spans + the content-addressed
    cache). Returns ``(normalized, realized_cost, cache_hit, artifact_key)``; a cache hit costs
    nothing to re-incur and re-uses the original fetch's snapshot key. The realized cost is
    attributed to the ``adapt`` span for audio/video (the distinct transcription cost) and to the
    ``fetch`` span otherwise (the scrape/download)."""
    source_key = manifest.source_key
    cost_on_adapt = manifest.modality in _TRANSCRIBED_MODALITIES
    ttl = freshness_ttl(manifest.freshness_profile)

    if cache is not None:
        cached = cache.get(content_key(source_key, ref))
        if cached is not None and is_fresh(cached, ttl, now=clock()):
            return cached.normalized, Decimal(0), True, cached.artifact_key

    with traced_step(
        adapter_span("fetch", source_key),
        **{ATTR_SOURCE_KEY: source_key, ATTR_SOURCE_TIER: manifest.tier},
    ) as fetch_span:
        start = perf_counter()
        artifact = adapter.fetch(ref, ctx)
        fetch_attrs: dict[str, object] = {ATTR_LATENCY_MS: _elapsed_ms(start)}
        if not cost_on_adapt:
            fetch_attrs[ATTR_COST_CENTS] = estimate
        apply_attributes(fetch_span, fetch_attrs)

    # Capture the evidence snapshot at the exact moment the fetched bytes exist (PB-B2.3): pure
    # sha256 work into the caller-owned sink — the durable put/row happen at the async flush.
    snapshot_key = (
        snapshots.capture(artifact, source_key=source_key) if snapshots is not None else None
    )

    with traced_step(
        adapter_span("adapt", source_key),
        **{ATTR_SOURCE_KEY: source_key, ATTR_SOURCE_TIER: manifest.tier},
    ) as adapt_span:
        start = perf_counter()
        normalized = adapter.adapt(artifact, ctx)
        adapt_attrs: dict[str, object] = {ATTR_LATENCY_MS: _elapsed_ms(start)}
        if cost_on_adapt:
            adapt_attrs[ATTR_COST_CENTS] = estimate  # the distinct transcription cost
        apply_attributes(adapt_span, adapt_attrs)

    if cache is not None and ttl > timedelta(0):
        cache.put(
            content_key(source_key, ref),
            CachedArtifact(
                normalized=normalized,
                stored_at=clock(),
                cost_cents=estimate,
                artifact_key=snapshot_key,
            ),
        )
    return normalized, estimate, False, snapshot_key


def _extract(
    extractor: ClaimExtractor,
    normalized: NormalizedText,
    entity: Entity,
    field: FieldDef,
    source_key: str,
) -> list[ClaimDraft]:
    """Run the extraction stage (its own span) and assert every draft's span is grounded in the
    normalized text. Extraction is always the per-call ``extractor`` — the adapter only normalizes
    (``fetch`` + ``adapt``); claim extraction varies by field, not modality."""
    with traced_step(
        adapter_span("extract", source_key),
        **{ATTR_SOURCE_KEY: source_key, ATTR_FIELD_KEY: field.field_key},
    ) as extract_span:
        start = perf_counter()
        drafts = list(extractor.extract(normalized, entity, field))
        apply_attributes(
            extract_span, {ATTR_LATENCY_MS: _elapsed_ms(start), ATTR_N_CLAIMS: len(drafts)}
        )
    for draft in drafts:
        if draft.evidence_span not in normalized.text:
            raise AdaptError(
                f"extractor for source {source_key!r} produced an evidence_span not present in the "
                f"normalized text (substrate §4 grounding): {draft.evidence_span!r}"
            )
    return drafts


def _materialize(
    drafts: list[ClaimDraft],
    *,
    manifest: RegistrySourceManifest,
    ref: str,
    run_id: RunId,
    research_mode: ResearchMode,
    entity: Entity,
    realized_cost: CostCents,
    artifact_key: str | None = None,
) -> list[Claim]:
    """Turn drafts into typed ``Claim``s, stamping tier/extraction_method/source_key from the
    manifest (never the extractor). The per-call cost goes to the first claim (a source call costs
    once, regardless of how many claims it yields; a cache hit makes that zero). A *paid-but-empty*
    call (a costly fetch/transcription with no drafts) carries its cost on the trace span only,
    not on any claim — mirroring the M4.1 waterfall. A CONTACT draft must carry a ``use_class`` (the
    ``contact_claim`` factory requires governance provenance from the moment the claim exists);
    account claims are the M4.3-shipped path, contact/facet support is here for M8."""
    method = _extraction_method(manifest)
    tier = manifest.tier
    identity_binding = manifest.identity_binding_strength
    claims: list[Claim] = []
    for index, draft in enumerate(drafts):
        source_url = draft.source_url or ref
        cost = realized_cost if index == 0 else Decimal(0)
        if entity.entity_type is EntityType.ACCOUNT:
            claim = account_claim(
                entity_id=entity.entity_id,
                field_key=draft.field_key,
                value_json=to_value_json(draft.value),
                source_tier=tier,
                extraction_method=method,
                confidence=draft.confidence,
                run_id=run_id,
                research_mode=research_mode,
                source_url=source_url,
                evidence_span=draft.evidence_span,
                observed_at=draft.observed_at,
                cost_cents=cost,
            )
        else:
            # A personal claim carries its governance provenance from the moment it exists: the
            # identity-binding from the manifest (authoritative) + the use-class the extractor set.
            if identity_binding is None:
                raise AdaptError(
                    f"source {manifest.source_key!r} produced a contact claim but its manifest "
                    "declares no identity_binding_strength (staged-flow §6)"
                )
            if draft.use_class is None:
                raise AdaptError(
                    f"contact claim draft {draft.field_key!r} must carry a use_class — a contact "
                    "claim carries its governance provenance from the moment it exists (Doc D §2)"
                )
            claim = contact_claim(
                entity_id=entity.entity_id,
                field_key=draft.field_key,
                value_json=to_value_json(draft.value),
                source_tier=tier,
                extraction_method=method,
                confidence=draft.confidence,
                run_id=run_id,
                research_mode=research_mode,
                identity_binding=identity_binding,
                use_class=draft.use_class,
                source_url=source_url,
                evidence_span=draft.evidence_span,
                observed_at=draft.observed_at,
                cost_cents=cost,
            )
        claims.append(_stamp_source_key(claim, manifest.source_key, artifact_key))
    return claims


def _stamp_source_key(claim: Claim, source_key: str, artifact_key: str | None = None) -> Claim:
    """Stamp the producing ``source_key`` + the evidence snapshot's ``artifact_key`` (the
    factories don't take them) and re-validate, via the shared :func:`~clue_core.revalidate_with`
    helper — the same provenance-stamp path the M4.1 waterfall uses, so the
    model_copy-skips-validators subtlety lives in exactly one place (conventions §2 DRY) and
    per-source yield/telemetry keys on the source."""
    return revalidate_with(claim, source_key=source_key, artifact_key=artifact_key)


def _extraction_method(manifest: RegistrySourceManifest) -> ExtractionMethod:
    if manifest.tier == 4:
        return ExtractionMethod.LLM_SYNTHESIS  # tier-4 ⟺ llm_synthesis (claim invariant)
    return _EXTRACTION_BY_MODALITY[manifest.modality]


def _elapsed_ms(start: float) -> float:
    return round((perf_counter() - start) * 1000.0, 3)
