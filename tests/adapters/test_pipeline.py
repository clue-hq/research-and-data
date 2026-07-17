"""M4.3 acceptance: the modality-adapter framework (ENG-116), one test per acceptance criterion.

PDF fetch→adapt→extract; text/structured passthrough; transcription (+ provider swap keeps the claim
contract); the gate skip; content-addressed caching (+ freshness expiry); open-by-registration of a
brand-new adapter; per-stage cost+latency spans (transcription cost distinct); tier/method fidelity;
grounding guard; the persist=False (M4.5) seam. Adapter doubles + registered manifests +
the M1 store exercise the framework end to end against a real DB.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from clue_core import (
    AdaptContext,
    ClaimDraft,
    Entity,
    EntityScope,
    EntityType,
    ExtractionMethod,
    FieldDef,
    IdentityBinding,
    Modality,
    NormalizedText,
    PassKind,
    RawArtifact,
    ResearchMode,
    ReuseScope,
    SourceManifest,
    UseClass,
    new_entity_id,
    new_run_id,
)
from clue_research.adapters import (
    AdapterNotRegisteredError,
    CallableClaimExtractor,
    FirecrawlHtmlAdapter,
    GateDecision,
    InlineBytesFetcher,
    InMemoryArtifactCache,
    PassthroughAdapter,
    PdfAdapter,
    TranscriptionAdapter,
    UnknownSourceError,
    cost_estimate,
    register_adapter,
    run_chain,
    run_pipeline,
    span_for,
)
from clue_research.adapters.seams import AdaptError
from clue_research.claimstore import ALL_TENANTS, claims_for
from clue_research.obs import collect_spans
from clue_research.sources import RegistrySourceManifest, get_source, register_source

from .conftest import rollback_conn, run_async

pytestmark = pytest.mark.usefixtures("require_db")

_MODE = ResearchMode.ACCOUNT_PROFILING


# --- doubles + builders -----------------------------------------------------


class _PdfDouble:
    """A PdfTextExtractor double: decode the artifact bytes as the extracted text (no pypdf)."""

    def __init__(self) -> None:
        self.calls = 0

    def to_text(self, artifact: RawArtifact) -> NormalizedText:
        self.calls += 1
        return NormalizedText(text=artifact.text(), media_type="text/plain", metadata={"pages": 1})


class _Transcriber:
    """A Transcriber double returning a preset transcript and counting calls."""

    def __init__(self, transcript: str) -> None:
        self.transcript = transcript
        self.calls = 0

    def transcribe(self, artifact: RawArtifact) -> NormalizedText:
        self.calls += 1
        return NormalizedText(text=self.transcript, metadata={"duration_seconds": 5400})


class _Clock:
    """A mutable injectable clock for deterministic freshness-TTL tests."""

    def __init__(self, start: datetime) -> None:
        self.now = start

    def __call__(self) -> datetime:
        return self.now

    def advance(self, delta: timedelta) -> None:
        self.now = self.now + delta


def _extractor(
    field_key: str,
    value: object,
    needle: str,
    *,
    source_url: str = "https://src.example/doc",
    use_class: object | None = None,
) -> CallableClaimExtractor:
    """An extractor that lifts ``needle`` from the normalized text as the grounded evidence span."""

    def fn(normalized: NormalizedText, entity: Entity, field: FieldDef) -> list[ClaimDraft]:
        return [
            ClaimDraft(
                field_key=field_key,
                value=value,
                evidence_span=span_for(normalized.text, needle),
                confidence=0.9,
                source_url=source_url,
                use_class=use_class,  # type: ignore[arg-type]
            )
        ]

    return CallableClaimExtractor(fn)


async def _register(
    conn: object,
    source_key: str,
    *,
    modality: Modality,
    tier: int,
    requires_adapter: str | None = None,
    cost_cents: Decimal = Decimal(0),
    freshness_profile: str | None = None,
    yields: tuple[str, ...] = ("account",),
    entity_scope: EntityScope = EntityScope.ACCOUNT,
    auth_ref: str | None = None,
    identity_binding: IdentityBinding | None = None,
) -> None:
    await register_source(
        conn,  # type: ignore[arg-type]
        RegistrySourceManifest(
            manifest=SourceManifest(
                source_key=source_key,
                modality=modality,
                entity_scope=entity_scope,
                yields=yields,
                tier=tier,
                cost_cents=cost_cents,
                freshness_profile=freshness_profile,
                identity_binding_strength=identity_binding,
            ),
            requires_adapter=requires_adapter,
            provider=source_key,
            auth_ref=auth_ref,
        ),
    )


def _account() -> Entity:
    return Entity(entity_id=new_entity_id(), entity_type=EntityType.ACCOUNT)


def _field(field_key: str, value_type: str) -> FieldDef:
    return FieldDef(field_key=field_key, value_type=value_type, pass_kind=PassKind.DEEP)


# --- AC1: PDF fetch→adapt→extract; non-null span; scrape; manifest tier (no upgrade) -------------


def test_pdf_source_writes_claim_with_span_scrape_method_and_manifest_tier() -> None:
    async def _run() -> None:
        async with rollback_conn() as conn:
            await _register(
                conn, "journal_pdf", modality=Modality.PDF, tier=3, requires_adapter="pdf_journal"
            )
            text = "Findings: the firm's operational pain is legacy ETL migration is slow."
            extractor = _extractor(
                "account.operational_pain",
                "legacy ETL migration is slow",
                "legacy ETL migration is slow",
                source_url="https://journal.example/p.pdf",
            )
            adapter = PdfAdapter(pdf_text=_PdfDouble(), fetcher=InlineBytesFetcher())
            register_adapter("pdf_journal", adapter)
            entity = _account()
            claims = await run_pipeline(
                conn,
                "journal_pdf",
                text,
                entity,
                _field("account.operational_pain", "str"),
                run_id=new_run_id(),
                research_mode=_MODE,
                extractor=extractor,
            )
            assert len(claims) == 1
            claim = claims[0]
            assert claim.source_tier == 3  # the manifest tier — NOT upgraded to tier-1
            assert claim.extraction_method is ExtractionMethod.SCRAPE
            assert claim.evidence_span == "legacy ETL migration is slow"
            assert claim.source_key == "journal_pdf"
            assert claim.source_url == "https://journal.example/p.pdf"
            # actually persisted via M1.1
            live = await claims_for(
                conn, entity.entity_id, "account.operational_pain", scope=ALL_TENANTS
            )
            assert [c.id for c in live] == [claim.id]

    run_async(_run())


# --- AC2: text/structured passthrough — no transcription/OCR; correctly-typed claims -------------


def test_text_passthrough_types_a_scrape_claim() -> None:
    async def _run() -> None:
        async with rollback_conn() as conn:
            await _register(conn, "blog", modality=Modality.TEXT, tier=3)
            entity = _account()
            claims = await run_pipeline(
                conn,
                "blog",
                "we are drowning in data silos",
                entity,
                _field("account.operational_pain", "str"),
                run_id=new_run_id(),
                research_mode=_MODE,
                extractor=_extractor("account.operational_pain", "data silos", "data silos"),
            )
            assert len(claims) == 1
            assert claims[0].extraction_method is ExtractionMethod.SCRAPE  # text → scrape
            assert claims[0].source_tier == 3

    run_async(_run())


def test_structured_passthrough_types_an_api_claim() -> None:
    async def _run() -> None:
        async with rollback_conn() as conn:
            await _register(
                conn, "people_api", modality=Modality.STRUCTURED, tier=1, yields=("core",)
            )
            entity = _account()
            claims = await run_pipeline(
                conn,
                "people_api",
                "headcount 1234 confirmed",
                entity,
                _field("core.employee_count", "int"),
                run_id=new_run_id(),
                research_mode=_MODE,
                extractor=_extractor("core.employee_count", 1234, "1234"),
            )
            assert len(claims) == 1
            assert (
                claims[0].extraction_method is ExtractionMethod.API
            )  # structured → api, not scrape
            assert claims[0].value_json == 1234

    run_async(_run())


# --- AC3: transcription; swapping the Transcriber double keeps the claim contract ----------------


def test_audio_routes_through_transcription_and_provider_swap_keeps_contract() -> None:
    async def _run() -> None:
        async with rollback_conn() as conn:
            await _register(
                conn,
                "podcast",
                modality=Modality.AUDIO,
                tier=3,
                requires_adapter="podcast_transcribe",
                cost_cents=Decimal(10),
            )
            entity = _account()
            field = _field("account.operational_pain", "str")
            extractor = _extractor("account.operational_pain", "data silos", "data silos")

            t1 = _Transcriber("the guest said we struggle with data silos across teams")
            register_adapter(
                "podcast_transcribe",
                TranscriptionAdapter(t1, fetcher=InlineBytesFetcher()),
            )
            c1 = (
                await run_pipeline(
                    conn,
                    "podcast",
                    "ref-a",
                    entity,
                    field,
                    run_id=new_run_id(),
                    research_mode=_MODE,
                    extractor=extractor,
                )
            )[0]
            assert t1.calls == 1

            # swap the transcription provider (a config change) — different transcript, SAME
            # contract
            t2 = _Transcriber("verbatim: our biggest issue is data silos in the warehouse")
            register_adapter(
                "podcast_transcribe",
                TranscriptionAdapter(t2, fetcher=InlineBytesFetcher()),
            )
            c2 = (
                await run_pipeline(
                    conn,
                    "podcast",
                    "ref-b",
                    entity,
                    field,
                    run_id=new_run_id(),
                    research_mode=_MODE,
                    extractor=extractor,
                )
            )[0]
            assert t2.calls == 1

            for c in (c1, c2):
                assert c.entity_type is EntityType.ACCOUNT
                assert c.field_key == "account.operational_pain"
                assert c.source_tier == 3  # transcription never upgrades trust
                assert c.extraction_method is ExtractionMethod.SCRAPE
                assert c.source_key == "podcast"
                assert c.evidence_span == "data silos"

    run_async(_run())


# --- AC4: gate 'skip' → no expensive call; cost_estimate exposed on the span --------------------


def test_gate_skip_makes_no_call_but_exposes_cost_estimate() -> None:
    async def _run() -> None:
        async with rollback_conn() as conn:
            await _register(
                conn,
                "podcast",
                modality=Modality.AUDIO,
                tier=3,
                requires_adapter="podcast_transcribe",
                cost_cents=Decimal(10),
            )
            entity = _account()
            field = _field("account.operational_pain", "str")
            transcriber = _Transcriber("nobody should transcribe me")
            register_adapter(
                "podcast_transcribe",
                TranscriptionAdapter(transcriber, fetcher=InlineBytesFetcher()),
            )

            # cost_estimate is the manifest cost (the pre-spend gate input)
            assert await cost_estimate(conn, "podcast", "ref") == Decimal(10)

            with collect_spans() as spans:
                claims = await run_pipeline(
                    conn,
                    "podcast",
                    "ref",
                    entity,
                    field,
                    run_id=new_run_id(),
                    research_mode=_MODE,
                    extractor=_extractor("account.operational_pain", "x", "x"),
                    gate_decision=GateDecision.SKIP,
                )
            assert claims == []
            assert transcriber.calls == 0  # the expensive transcription was NOT made
            assert await claims_for(conn, entity.entity_id, scope=ALL_TENANTS) == []

            by_name = {s.name: s for s in spans.get_finished_spans()}
            pipeline = by_name["adapter.pipeline.podcast"]
            assert pipeline.attributes["gate_decision"] == "skip"
            assert (
                pipeline.attributes["cost_estimate_cents"] == "10"
            )  # estimate exposed even on skip
            assert pipeline.attributes["n_claims"] == 0
            # no fetch/adapt/extract span ran (skipped before any stage)
            assert "adapter.adapt.podcast" not in by_name

    run_async(_run())


# --- AC5: caching — costly op once per ref within a run; freshness governs expiry ----------------


def test_cache_runs_costly_op_once_and_zeros_re_incurred_cost() -> None:
    async def _run() -> None:
        async with rollback_conn() as conn:
            await _register(
                conn,
                "podcast",
                modality=Modality.AUDIO,
                tier=3,
                requires_adapter="podcast_transcribe",
                cost_cents=Decimal(10),
                freshness_profile="daily",
            )
            entity = _account()
            field = _field("account.operational_pain", "str")
            transcriber = _Transcriber("we struggle with data silos")
            extractor = _extractor("account.operational_pain", "data silos", "data silos")
            register_adapter(
                "podcast_transcribe",
                TranscriptionAdapter(transcriber, fetcher=InlineBytesFetcher()),
            )
            cache = InMemoryArtifactCache()

            c1 = (
                await run_pipeline(
                    conn,
                    "podcast",
                    "same-ref",
                    entity,
                    field,
                    run_id=new_run_id(),
                    research_mode=_MODE,
                    extractor=extractor,
                    cache=cache,
                )
            )[0]
            c2 = (
                await run_pipeline(
                    conn,
                    "podcast",
                    "same-ref",
                    entity,
                    field,
                    run_id=new_run_id(),
                    research_mode=_MODE,
                    extractor=extractor,
                    cache=cache,
                )
            )[0]

            assert transcriber.calls == 1  # second run hit the cache — transcription NOT repeated
            assert c1.cost_cents == Decimal(10)  # first run incurred the cost
            assert c2.cost_cents == Decimal(0)  # cache hit → no re-incurred cost

    run_async(_run())


def test_cache_respects_freshness_expiry_and_realtime_never_caches() -> None:
    async def _run() -> None:
        async with rollback_conn() as conn:
            await _register(
                conn,
                "hourly_src",
                modality=Modality.AUDIO,
                tier=3,
                requires_adapter="adp_hourly",
                cost_cents=Decimal(5),
                freshness_profile="hourly",
            )
            await _register(
                conn,
                "live_src",
                modality=Modality.AUDIO,
                tier=2,
                requires_adapter="adp_live",
                cost_cents=Decimal(5),
                freshness_profile="livecrawl",
            )
            entity = _account()
            field = _field("account.operational_pain", "str")
            ex = _extractor("account.operational_pain", "data silos", "data silos")

            hourly_tx = _Transcriber("data silos a")
            register_adapter(
                "adp_hourly", TranscriptionAdapter(hourly_tx, fetcher=InlineBytesFetcher())
            )
            clock = _Clock(datetime(2026, 1, 1, tzinfo=UTC))
            cache = InMemoryArtifactCache()
            await run_pipeline(
                conn,
                "hourly_src",
                "r",
                entity,
                field,
                run_id=new_run_id(),
                research_mode=_MODE,
                extractor=ex,
                cache=cache,
                clock=clock,
            )
            clock.advance(timedelta(minutes=30))  # within the 1h TTL → cache hit
            await run_pipeline(
                conn,
                "hourly_src",
                "r",
                entity,
                field,
                run_id=new_run_id(),
                research_mode=_MODE,
                extractor=ex,
                cache=cache,
                clock=clock,
            )
            assert hourly_tx.calls == 1
            clock.advance(timedelta(hours=2))  # past the TTL → re-fetch
            await run_pipeline(
                conn,
                "hourly_src",
                "r",
                entity,
                field,
                run_id=new_run_id(),
                research_mode=_MODE,
                extractor=ex,
                cache=cache,
                clock=clock,
            )
            assert hourly_tx.calls == 2

            # a livecrawl/realtime source is never served from cache (TTL 0)
            live_tx = _Transcriber("data silos b")
            register_adapter(
                "adp_live", TranscriptionAdapter(live_tx, fetcher=InlineBytesFetcher())
            )
            live_cache = InMemoryArtifactCache()
            await run_pipeline(
                conn,
                "live_src",
                "r",
                entity,
                field,
                run_id=new_run_id(),
                research_mode=_MODE,
                extractor=ex,
                cache=live_cache,
            )
            await run_pipeline(
                conn,
                "live_src",
                "r",
                entity,
                field,
                run_id=new_run_id(),
                research_mode=_MODE,
                extractor=ex,
                cache=live_cache,
            )
            assert live_tx.calls == 2

    run_async(_run())


# --- AC6: open by registration — a brand-new adapter makes a source consumable end-to-end --------


def test_registering_a_brand_new_modality_adapter_makes_the_source_consumable() -> None:
    async def _run() -> None:
        async with rollback_conn() as conn:
            await _register(
                conn,
                "substack",
                modality=Modality.TEXT,
                tier=3,
                requires_adapter="substack_long_form",
            )

            # a bespoke normalizer for a brand-new source — no waterfall (M4.1) or worker (M8)
            # change; extraction is the per-call ClaimExtractor seam, not the adapter's job.
            class _SubstackAdapter:
                modality = Modality.TEXT

                def fetch(self, ref: str, ctx: AdaptContext) -> RawArtifact:
                    return RawArtifact(ref=ref, media_type="text/markdown", content=ref.encode())

                def adapt(self, artifact: RawArtifact, ctx: AdaptContext) -> NormalizedText:
                    return NormalizedText(
                        text=f"NEWSLETTER: {artifact.text()}", media_type="text/markdown"
                    )

            register_adapter("substack_long_form", _SubstackAdapter())
            entity = _account()
            claims = await run_pipeline(
                conn,
                "substack",
                "we wrote about scaling pain",
                entity,
                _field("account.operational_pain", "str"),
                run_id=new_run_id(),
                research_mode=_MODE,
                extractor=_extractor(
                    "account.operational_pain",
                    "scaling pain",
                    "scaling pain",
                    source_url="https://sub.example/post",
                ),
            )
            assert len(claims) == 1
            assert claims[0].source_key == "substack"
            assert claims[0].evidence_span == "scaling pain"

    run_async(_run())


# --- AC7: each stage emits its own cost+latency span; transcription cost is a distinct span -------


def test_each_stage_emits_a_span_and_transcription_cost_is_distinct() -> None:
    async def _run() -> None:
        async with rollback_conn() as conn:
            await _register(
                conn,
                "podcast",
                modality=Modality.AUDIO,
                tier=3,
                requires_adapter="podcast_transcribe",
                cost_cents=Decimal(10),
            )
            register_adapter(
                "podcast_transcribe",
                TranscriptionAdapter(
                    _Transcriber("we struggle with data silos"),
                    fetcher=InlineBytesFetcher(),
                ),
            )
            entity = _account()
            with collect_spans() as spans:
                await run_pipeline(
                    conn,
                    "podcast",
                    "ref",
                    entity,
                    _field("account.operational_pain", "str"),
                    run_id=new_run_id(),
                    research_mode=_MODE,
                    extractor=_extractor("account.operational_pain", "data silos", "data silos"),
                )
            by_name = {s.name: s for s in spans.get_finished_spans()}
            # the wrapper span + the three stage spans are all present
            assert "adapter.pipeline.podcast" in by_name
            # each of fetch / adapt / extract is its own span carrying latency
            for stage in ("fetch", "adapt", "extract"):
                name = f"adapter.{stage}.podcast"
                assert name in by_name, f"missing span {name}"
                assert "latency_ms" in by_name[name].attributes  # each stage records latency
            # the transcription cost is on the ADAPT span (a distinct cost), not the fetch span
            assert by_name["adapter.adapt.podcast"].attributes["cost_cents"] == "10"
            assert "cost_cents" not in by_name["adapter.fetch.podcast"].attributes

    run_async(_run())


def test_non_transcribed_modality_attributes_cost_to_the_fetch_span() -> None:
    async def _run() -> None:
        async with rollback_conn() as conn:
            await _register(
                conn,
                "journal_pdf",
                modality=Modality.PDF,
                tier=3,
                requires_adapter="pdf_journal",
                cost_cents=Decimal(2),
            )
            register_adapter(
                "pdf_journal",
                PdfAdapter(pdf_text=_PdfDouble(), fetcher=InlineBytesFetcher()),
            )
            entity = _account()
            with collect_spans() as spans:
                await run_pipeline(
                    conn,
                    "journal_pdf",
                    "the etl pain is real",
                    entity,
                    _field("account.operational_pain", "str"),
                    run_id=new_run_id(),
                    research_mode=_MODE,
                    extractor=_extractor("account.operational_pain", "etl pain", "etl pain"),
                )
            by_name = {s.name: s for s in spans.get_finished_spans()}
            # for a non-AV modality, the call cost is attributed to the fetch span, not adapt
            assert by_name["adapter.fetch.journal_pdf"].attributes["cost_cents"] == "2"
            assert "cost_cents" not in by_name["adapter.adapt.journal_pdf"].attributes

    run_async(_run())


# --- robustness: grounding guard, persist=False seam, unknown source, missing adapter ------------


def test_ungrounded_evidence_span_fails_loud() -> None:
    async def _run() -> None:
        async with rollback_conn() as conn:
            await _register(conn, "blog", modality=Modality.TEXT, tier=3)
            entity = _account()

            def fn(normalized: NormalizedText, entity: Entity, field: FieldDef) -> list[ClaimDraft]:
                # a span NOT present in the normalized text — fabricated provenance
                return [
                    ClaimDraft(
                        field_key="account.operational_pain",
                        value="x",
                        evidence_span="not in the text",
                        confidence=0.9,
                        source_url="https://x",
                    )
                ]

            with pytest.raises(AdaptError, match="not present in the normalized text"):
                await run_pipeline(
                    conn,
                    "blog",
                    "real content",
                    entity,
                    _field("account.operational_pain", "str"),
                    run_id=new_run_id(),
                    research_mode=_MODE,
                    extractor=CallableClaimExtractor(fn),
                )

    run_async(_run())


def test_persist_false_returns_unwritten_claims() -> None:
    async def _run() -> None:
        async with rollback_conn() as conn:
            await _register(conn, "blog", modality=Modality.TEXT, tier=3)
            entity = _account()
            claims = await run_pipeline(
                conn,
                "blog",
                "data silos everywhere",
                entity,
                _field("account.operational_pain", "str"),
                run_id=new_run_id(),
                research_mode=_MODE,
                extractor=_extractor("account.operational_pain", "data silos", "data silos"),
                persist=False,
            )
            assert len(claims) == 1  # materialized and returned to the caller (the waterfall seam)
            assert (
                await claims_for(conn, entity.entity_id, scope=ALL_TENANTS) == []
            )  # but NOT written

    run_async(_run())


def test_persist_true_fails_loud_on_a_tenant_private_claim_with_no_tenant() -> None:
    # run_pipeline(persist=True) is a writer, so it tenant-stamps (decision #6). A contact.facet.*
    # claim classifies tenant_private — persisting it with NO tenant_id must fail loud, never write
    # the personal claim public (the M8/run_pipeline footgun the M4.5 review flagged).
    async def _run() -> None:
        async with rollback_conn() as conn:
            await _register(
                conn,
                "linkedin",
                modality=Modality.TEXT,
                tier=3,
                requires_adapter="li_posts2",
                yields=("contact.facet",),
                entity_scope=EntityScope.BOTH,
                identity_binding=IdentityBinding.STRONG,
            )
            register_adapter("li_posts2", PassthroughAdapter(modality=Modality.TEXT))
            with pytest.raises(ValueError, match="tenant_private"):
                await run_pipeline(
                    conn,
                    "linkedin",
                    "he spoke at KubeCon last week",
                    _contact(),
                    _field("contact.facet.recent_post", "str"),
                    run_id=new_run_id(),
                    research_mode=ResearchMode.CONTACT_PROFILING,
                    extractor=_extractor(
                        "contact.facet.recent_post",
                        "spoke at KubeCon",
                        "spoke at KubeCon",
                        source_url="https://linkedin.com/in/x",
                        use_class=UseClass.PROFESSIONAL_PUBLIC,
                    ),
                    # no tenant_id → the writer refuses to persist the private claim
                )

    run_async(_run())


def test_run_chain_matches_run_pipeline_persist_false() -> None:
    # run_pipeline = get_source + run_chain + persist. ``run_chain`` is the SYNC seam M4.5's
    # Firecrawl resolver calls from inside the connection-less Resolver protocol; over the same
    # manifest it must yield the same unwritten claims as run_pipeline(persist=False).
    async def _run() -> None:
        async with rollback_conn() as conn:
            await _register(conn, "blog", modality=Modality.TEXT, tier=3)
            manifest = await get_source(conn, "blog")
            assert manifest is not None
            entity, run_id = _account(), new_run_id()
            ext = _extractor("account.operational_pain", "data silos", "data silos")
            via_pipeline = await run_pipeline(
                conn,
                "blog",
                "data silos everywhere",
                entity,
                _field("account.operational_pain", "str"),
                run_id=run_id,
                research_mode=_MODE,
                extractor=ext,
                persist=False,
            )
            via_chain = run_chain(
                manifest,
                "data silos everywhere",
                entity,
                _field("account.operational_pain", "str"),
                run_id=run_id,
                research_mode=_MODE,
                extractor=ext,
            )

            def _key(c: object) -> tuple[object, ...]:
                return (
                    c.field_key,  # type: ignore[attr-defined]
                    c.value_json,  # type: ignore[attr-defined]
                    c.source_tier,  # type: ignore[attr-defined]
                    c.extraction_method,  # type: ignore[attr-defined]
                    c.source_key,  # type: ignore[attr-defined]
                    c.evidence_span,  # type: ignore[attr-defined]
                )

            assert [_key(c) for c in via_chain] == [_key(c) for c in via_pipeline]
            assert via_chain and via_chain[0].source_tier == 3 and via_chain[0].source_key == "blog"

    run_async(_run())


def test_unknown_source_raises() -> None:
    async def _run() -> None:
        async with rollback_conn() as conn:
            with pytest.raises(UnknownSourceError, match="not registered"):
                await run_pipeline(
                    conn,
                    "ghost",
                    "ref",
                    _account(),
                    _field("account.operational_pain", "str"),
                    run_id=new_run_id(),
                    research_mode=_MODE,
                    extractor=_extractor("account.operational_pain", "x", "x"),
                )
            with pytest.raises(UnknownSourceError, match="not registered"):
                await cost_estimate(conn, "ghost", "ref")

    run_async(_run())


def test_pdf_source_without_registered_adapter_raises() -> None:
    async def _run() -> None:
        async with rollback_conn() as conn:
            await _register(
                conn, "orphan_pdf", modality=Modality.PDF, tier=3, requires_adapter="missing"
            )
            with pytest.raises(AdapterNotRegisteredError, match="no adapter registered"):
                await run_pipeline(
                    conn,
                    "orphan_pdf",
                    "ref",
                    _account(),
                    _field("account.operational_pain", "str"),
                    run_id=new_run_id(),
                    research_mode=_MODE,
                    extractor=_extractor("account.operational_pain", "x", "x"),
                )

    run_async(_run())


def test_firecrawl_html_adapter_normalizes_to_markdown_claim() -> None:
    async def _run() -> None:
        async with rollback_conn() as conn:
            await _register(
                conn,
                "firecrawl_site",
                modality=Modality.TEXT,
                tier=2,
                requires_adapter="firecrawl_html",
                cost_cents=Decimal(1),
                freshness_profile="livecrawl",
                auth_ref="CLUE_FIRECRAWL_API_KEY",
            )

            class _Scraper:
                def scrape(self, ref: str, ctx: AdaptContext) -> RawArtifact:
                    return RawArtifact(
                        ref=ref,
                        media_type="text/markdown",
                        content=b"# Acme\n\nWe struggle with data silos.",
                        metadata={"backend": "firecrawl"},
                    )

            register_adapter("firecrawl_html", FirecrawlHtmlAdapter(scraper=_Scraper()))
            entity = _account()
            claims = await run_pipeline(
                conn,
                "firecrawl_site",
                "https://acme.example",
                entity,
                _field("account.operational_pain", "str"),
                run_id=new_run_id(),
                research_mode=_MODE,
                extractor=_extractor(
                    "account.operational_pain",
                    "data silos",
                    "data silos",
                    source_url="https://acme.example",
                ),
            )
            assert len(claims) == 1
            assert claims[0].source_tier == 2  # official-site scrape stays tier-2
            assert claims[0].extraction_method is ExtractionMethod.SCRAPE
            assert claims[0].source_url == "https://acme.example"

    run_async(_run())


# --- CONTACT path: governance provenance (binding from manifest, use_class from draft) ------------


def _contact() -> Entity:
    return Entity(entity_id=new_entity_id(), entity_type=EntityType.CONTACT)


def test_contact_claim_carries_binding_from_manifest_and_use_class_from_draft() -> None:
    async def _run() -> None:
        async with rollback_conn() as conn:
            await _register(
                conn,
                "linkedin",
                modality=Modality.TEXT,
                tier=3,
                requires_adapter="li_posts",
                yields=("contact.facet",),
                entity_scope=EntityScope.BOTH,
                identity_binding=IdentityBinding.STRONG,
            )
            field = _field("contact.facet.recent_post", "str")
            extractor = _extractor(
                "contact.facet.recent_post",
                "spoke at KubeCon",
                "spoke at KubeCon",
                source_url="https://linkedin.com/in/x",
                use_class=UseClass.PROFESSIONAL_PUBLIC,
            )
            register_adapter("li_posts", PassthroughAdapter(modality=Modality.TEXT))
            claim = (
                await run_pipeline(
                    conn,
                    "linkedin",
                    "he spoke at KubeCon last week",
                    _contact(),
                    field,
                    run_id=new_run_id(),
                    research_mode=ResearchMode.CONTACT_PROFILING,
                    extractor=extractor,
                    # a contact.facet.* claim classifies tenant_private (decision #6); run_pipeline,
                    # as the writer, stamps it and so requires the run's tenant_id.
                    tenant_id="tenant-a",
                )
            )[0]
            assert claim.entity_type is EntityType.CONTACT
            assert claim.identity_binding is IdentityBinding.STRONG  # stamped from the manifest
            assert claim.use_class is UseClass.PROFESSIONAL_PUBLIC  # carried from the draft
            assert claim.source_tier == 3
            # the writer stamped the personal claim tenant-private and bound it to the run tenant.
            assert claim.reuse_scope is ReuseScope.TENANT_PRIVATE and claim.tenant_id == "tenant-a"

    run_async(_run())


def test_contact_claim_without_manifest_binding_fails_loud() -> None:
    async def _run() -> None:
        async with rollback_conn() as conn:
            # manifest declares NO identity_binding — a personal claim must carry its binding
            await _register(
                conn,
                "noband",
                modality=Modality.TEXT,
                tier=3,
                requires_adapter="nb",
                yields=("contact.facet",),
                entity_scope=EntityScope.BOTH,
            )
            register_adapter("nb", PassthroughAdapter(modality=Modality.TEXT))
            with pytest.raises(AdaptError, match="identity_binding_strength"):
                await run_pipeline(
                    conn,
                    "noband",
                    "x is here",
                    _contact(),
                    _field("contact.facet.recent_post", "str"),
                    run_id=new_run_id(),
                    research_mode=ResearchMode.CONTACT_PROFILING,
                    extractor=_extractor(
                        "contact.facet.recent_post",
                        "x",
                        "x",
                        use_class=UseClass.PROFESSIONAL_PUBLIC,
                    ),
                )

    run_async(_run())


def test_contact_claim_without_use_class_fails_loud() -> None:
    async def _run() -> None:
        async with rollback_conn() as conn:
            await _register(
                conn,
                "nouc",
                modality=Modality.TEXT,
                tier=3,
                requires_adapter="nu",
                yields=("contact.facet",),
                entity_scope=EntityScope.BOTH,
                identity_binding=IdentityBinding.STRONG,
            )
            # the extractor leaves use_class unset — fail loud (governance provenance is required)
            register_adapter("nu", PassthroughAdapter(modality=Modality.TEXT))
            with pytest.raises(AdaptError, match="use_class"):
                await run_pipeline(
                    conn,
                    "nouc",
                    "x is here",
                    _contact(),
                    _field("contact.facet.recent_post", "str"),
                    run_id=new_run_id(),
                    research_mode=ResearchMode.CONTACT_PROFILING,
                    extractor=_extractor("contact.facet.recent_post", "x", "x"),
                )

    run_async(_run())


# --- a declared-but-unregistered adapter fails loud (never downgrades to passthrough) -----


def test_declared_but_unregistered_adapter_fails_loud_even_with_extractor() -> None:
    async def _run() -> None:
        async with rollback_conn() as conn:
            # a TEXT source that explicitly declares requires_adapter, but the adapter is NOT
            # registered — must raise, NOT extract from the un-normalized ref via passthrough
            await _register(
                conn, "official_site", modality=Modality.TEXT, tier=2, requires_adapter="html_md"
            )
            with pytest.raises(AdapterNotRegisteredError, match="no adapter registered"):
                await run_pipeline(
                    conn,
                    "official_site",
                    "https://x.example",
                    _account(),
                    _field("account.operational_pain", "str"),
                    run_id=new_run_id(),
                    research_mode=_MODE,
                    extractor=_extractor("account.operational_pain", "x", "x"),
                )

    run_async(_run())
