"""The Brand Ad Assets onboarding job: harvest → filter/dedupe → custody → distill → pre-generate.

The lane's one entrypoint, and the twin of ``lumen_ingestion.pipeline``'s three
``run_*_ingestion`` functions in every structural way: a self-contained "job id in, terminal row
out" function, driven from a frozen ``DesignIngestionEnvelope`` by
``lumen_api.main.execute_ingestion_job`` inside ``asyncio.to_thread`` on a leased worker, wrapped
in ``run_ingestion_job`` so it never raises and always leaves a terminal row.

**Every step's output is durable before the next step runs, and a later step's failure never
un-does an earlier one.** That is the spec's requirement and it is the reason the steps are
ordered and committed the way they are:

1. HARVEST + CUSTODY — the creatives' bytes get durable custody and their asset rows are
   written (``design_register_captured_assets``), then their provenance rows
   (``design_record_ad_creatives``). After this the harvest is safe: nothing below can lose it.
2. DISTILL — a model call. Failure records a reason on the job's evidence and STOPS, with the
   job still completing: a workspace with harvested references and no card is a real, useful,
   honest state, and re-running the job later re-uses the creatives it already has.
3. PRE-GENERATE — N model calls. Each asset is independent; failures are recorded per asset.
   A total failure leaves the card intact, and the card is what the runtime actually needs.

The job's ``evidence`` is the per-step outcome record: what each step did, what it dropped and
why, and what it could not do. It is the thing an operator reads when a harvest disappoints.
"""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, datetime
from typing import Any, Callable, Optional

from clue_storage import StorageBackend, storage_from_settings
from lumen_api.design_store import DesignBlobStore, HybridRepository
from py_lumen_config import settings
from py_lumen_obs import get_logger

from ..jobs import IngestionJobStore, StageReporter, run_ingestion_job
from .company_identity import (
    RESOLVER_AD_LIBRARY_DOMAIN,
    RESOLVER_EXPLICIT,
    RESOLVER_PDL,
    AdvertiserResolution,
    CompanyIdentityError,
    check_advertiser_names,
    resolve_company_identity_resolver,
)
from .distill import AdDnaCard, previews_for, resolve_distiller
from .harvest import (
    DEFAULT_MAX_CREATIVES,
    DEFAULT_MAX_PAGES,
    creative_provenance,
    custody_creatives,
    fetch_pages,
    select_creatives,
)
from .pregenerate import MAX_REFERENCE_IMAGES, pregenerate_for_card
from .provider import AdLibraryError, resolve_provider

JsonObject = dict[str, Any]

logger = get_logger("lumen_ingestion.ad_library.onboarding")

__all__ = ["AdAssetsLaneDisabled", "run_ad_assets_onboarding"]


class AdAssetsLaneDisabled(RuntimeError):
    """The worker reached an ad-assets job while the lane's flag is off.

    Loud rather than a quiet no-op: the only way to be here is for a job row to exist, and a
    job row only exists because the flag-gated route created one — so the flag went off between
    the offer and the claim, which an operator should see rather than infer from a job that
    silently did nothing.
    """


def run_ad_assets_onboarding(
    engine_cache_dir: str,
    job_id: str,
    *,
    workspace_id: str,
    storage: Optional[StorageBackend] = None,
    expected_generation: Optional[int] = None,
    provider: Any = None,
    identity_resolver: Any = None,
    distiller: Any = None,
    generate: Optional[Callable[..., Any]] = None,
    fetch_creative: Optional[Callable[[str], "tuple[bytes, str]"]] = None,
    now: Optional[Callable[[], datetime]] = None,
) -> None:
    """Run one ad-assets onboarding job to a terminal state. Never raises.

    The injectable seams (``provider`` / ``identity_resolver`` / ``distiller`` / ``generate`` /
    ``fetch_creative`` / ``now``) exist for the same reason the ingestion pipeline's ``capture``
    / ``analyze`` / ``describer`` seams do: the suites drive the whole job with none of the
    external systems present, and the production defaults are resolved at call time.

    There are FIVE of them and not four because R3-A added a fifth external system: the
    company-identity resolver that now answers "which LinkedIn page is this domain" BEFORE the
    ad library is asked anything. A suite that stubbed four of the five would still be spending
    a real enrichment credit per test.
    """
    store = IngestionJobStore(
        workspace_id=workspace_id, expected_generation=expected_generation
    )
    repo = HybridRepository(workspace_id=workspace_id)
    resolved_storage = storage or storage_from_settings()
    blobs = DesignBlobStore(resolved_storage, workspace_id)

    def work(reporter: StageReporter) -> "tuple[str, int, Optional[str]]":
        return _onboard(
            store=store,
            repo=repo,
            blobs=blobs,
            storage=resolved_storage,
            cache_dir=engine_cache_dir,
            job_id=job_id,
            reporter=reporter,
            provider=provider,
            identity_resolver=identity_resolver,
            distiller=distiller,
            generate=generate,
            fetch_creative=fetch_creative,
            now=now or (lambda: datetime.now(UTC)),
        )

    run_ingestion_job(store, job_id, work)


def _onboard(
    *,
    store: IngestionJobStore,
    repo: HybridRepository,
    blobs: DesignBlobStore,
    storage: StorageBackend,
    cache_dir: str,
    job_id: str,
    reporter: StageReporter,
    provider: Any,
    identity_resolver: Any,
    distiller: Any,
    generate: Optional[Callable[..., Any]],
    fetch_creative: Optional[Callable[[str], "tuple[bytes, str]"]],
    now: Callable[[], datetime],
) -> "tuple[str, int, Optional[str]]":
    if not settings.lumen_brand_ad_assets:
        raise AdAssetsLaneDisabled(
            "LUMEN_BRAND_AD_ASSETS is off, but an ad-assets job was claimed for execution"
        )

    # Imported here, not at module load: `pipeline` reaches the design toolbelt wiring and the
    # engine client, and this module is imported by the route to name its request shape.
    from ..pipeline import _RecordingCore, _core_client, _register_captured_assets
    from ..pipeline import _worker_design_tools

    job = store.require(job_id)
    request = job["request"]
    company_domain = request.get("company_domain")
    page_id = request.get("page_id")
    brand_kit_id = str(request["brand_kit_id"])
    brand_kit_version = int(request["brand_kit_version"])
    advertiser_name = request.get("advertiser_name")
    max_pages = int(request.get("max_pages") or DEFAULT_MAX_PAGES)
    max_creatives = int(request.get("max_creatives") or DEFAULT_MAX_CREATIVES)

    core = _RecordingCore(_core_client(), blobs, cache_dir)
    tools = _worker_design_tools(storage)
    evidence: JsonObject = {
        "schema_version": 1,
        "steps": {},
        "brand_kit": {"id": brand_kit_id, "version": brand_kit_version},
    }
    fetched_at = now().isoformat()

    # --- step 0: resolve WHO the advertiser is, before asking the ad library anything --------
    #
    # R3-A. This step exists because the vendor's own domain resolution is not evidence: for
    # apollo.io it answered a real page with zero ads while the brand's true page had 135, and
    # the lane had no way to notice. Resolution now happens first, against a source that is not
    # the ad library, and the harvest is addressed by the id it produced.
    reporter("Confirming who you are on LinkedIn…", 0.05)
    resolution = _resolve_advertiser(
        company_domain=company_domain,
        page_id=page_id,
        advertiser_name=advertiser_name,
        resolver=identity_resolver,
    )

    # --- step 1: harvest, filter, dedupe, custody -------------------------------------------
    reporter("Reading your published ads…", 0.1)
    resolved_provider = provider or resolve_provider()
    # A resolved id ALWAYS wins the selector. The domain is only ever sent when nothing could
    # be resolved from it — that is the fallback, and it is recorded as such rather than being
    # allowed to look like the verified path.
    harvest_page_id = resolution.linkedin_page_id
    pages = fetch_pages(
        resolved_provider,
        company_domain=None if harvest_page_id else company_domain,
        page_id=harvest_page_id,
        max_pages=max_pages,
        date_filter=request.get("date_filter"),
    )
    observed_page_id = (pages[0].page_id if pages else None) or harvest_page_id
    resolution = replace(resolution, observed_page_id=observed_page_id)
    evidence["resolution"] = resolution.to_json()

    selection = select_creatives(
        pages, advertiser_name=advertiser_name, max_creatives=max_creatives
    )
    # THE UNIVERSAL GUARD. It runs on all three resolution paths — verified, fallback and
    # operator-asserted — because harvesting a stranger's creatives into a brand's reference
    # library is worse than an empty lane on every one of them.
    advertiser_check = check_advertiser_names(
        [ad.advertiser_name for ad in selection.kept],
        expected=resolution.resolved_name,
        resolution=resolution,
    )
    evidence["steps"]["harvest"] = {
        "status": "ok",
        "pages_fetched": len(pages),
        "ads_considered": selection.considered,
        "kept": len(selection.kept),
        "dropped": selection.drop_counts(),
        "advertiser_name": selection.advertiser_name,
        "advertiser_check": advertiser_check.to_json(),
    }
    if advertiser_check.blocks_custody:
        # KEEP NOTHING. Not "keep the ones that matched" — a page serving two advertisers is a
        # page whose majority answer cannot be trusted, and a half-right reference library is
        # the kind of wrong that only shows up later, in an ad.
        evidence["steps"]["harvest"]["status"] = "advertiser_mismatch"
        evidence["steps"]["harvest"]["kept"] = 0
        return _complete(brand_kit_id, brand_kit_version, evidence, reporter=reporter)
    if not selection.kept:
        # An honest empty is a correct outcome, not a failure: a brand with no static company
        # ads has nothing to harvest, and saying so is more useful than a red job row.
        evidence["steps"]["harvest"]["status"] = "empty"
        return _complete(brand_kit_id, brand_kit_version, evidence, reporter=reporter)

    reporter("Saving your ad creatives…", 0.3)
    custody = custody_creatives(
        selection,
        core=core,
        cache_dir=cache_dir,
        fetched_at=fetched_at,
        provider_name=getattr(resolved_provider, "name", "unknown"),
        advertiser_page_id=observed_page_id,
        fetch=fetch_creative,
        max_bytes=settings.lumen_asset_max_bytes,
    )
    evidence["steps"]["custody"] = {
        "status": "ok" if custody.creatives else "empty",
        "custodied": len(custody.creatives),
        "failures": [{"ad_id": ad_id, "reason": reason} for ad_id, reason in custody.failures],
    }
    if not custody.creatives:
        return _complete(brand_kit_id, brand_kit_version, evidence, reporter=reporter)

    # The asset rows FIRST (governed, bulk, content-derived ids), then the provenance rows that
    # point at them — a creative row whose asset does not exist yet would fail its foreign key.
    _register_captured_assets(tools, repo.workspace_id, custody.asset_records)
    provider_name = getattr(resolved_provider, "name", "unknown")
    advertiser_page_id = observed_page_id
    creative_rows = [
        {
            "creative_id": creative.creative_id,
            "harvest_job_id": job_id,
            "provider": provider_name,
            "ad_id": creative.ad.ad_id,
            "advertiser_name": creative.ad.advertiser_name,
            "advertiser_page_id": advertiser_page_id,
            "creative_url": creative.image_url,
            "view_details_link": creative.ad.view_details_link,
            "headline": creative.ad.headline_title,
            "commentary": creative.ad.commentary_text,
            "asset_id": creative.asset_id,
            "fetched_at": fetched_at,
            # The SAME provenance the asset record carries, built by the same function, so the
            # queryable row and the durable asset can never tell two different stories.
            "provenance": creative_provenance(
                creative.ad,
                provider_name=provider_name,
                advertiser_page_id=advertiser_page_id,
                fetched_at=fetched_at,
                creative_id=creative.creative_id,
            ),
        }
        for creative in custody.creatives
    ]
    recorded = tools.invoke(
        "design_record_ad_creatives",
        {"creatives": creative_rows},
        workspace_id=repo.workspace_id,
        actor="agent",
    ).references
    evidence["steps"]["record"] = {"status": "ok", "count": recorded["count"]}

    # >>> Everything above is now durable. Nothing below may lose it. <<<

    # --- step 2: distil the ad-DNA card ------------------------------------------------------
    reporter("Learning your ad style…", 0.55)
    card = _distil(custody.creatives, distiller=distiller, evidence=evidence)
    if card is None:
        return _complete(brand_kit_id, brand_kit_version, evidence, reporter=reporter)

    card_id = request.get("card_id") or f"adna_{brand_kit_id}"
    published = tools.invoke(
        "design_publish_ad_dna_card",
        {
            "card_id": card_id,
            "brand_kit_id": brand_kit_id,
            "brand_kit_version": brand_kit_version,
            "card": card.to_json(),
            "source_creative_ids": [c.creative_id for c in custody.creatives],
            "harvest_job_id": job_id,
            "model": card.model,
        },
        workspace_id=repo.workspace_id,
        actor="agent",
    ).references
    evidence["steps"]["distill"] = {
        "status": "ok",
        "card_id": published["card_id"],
        "version": published["version"],
        "style_groups": published["style_group_count"],
        "model": card.model,
    }

    # --- step 3: pre-generate imagery per style group -----------------------------------------
    reporter("Creating brand imagery…", 0.8)
    _pregenerate(
        card,
        creatives=custody.creatives,
        core=core,
        cache_dir=cache_dir,
        tools=tools,
        repo=repo,
        generate=generate,
        card_id=published["card_id"],
        card_version=int(published["version"]),
        brand_name=selection.advertiser_name,
        evidence=evidence,
    )

    reporter("Finishing up…", 0.95)
    return _complete(brand_kit_id, brand_kit_version, evidence, reporter=reporter)


def _resolve_advertiser(
    *,
    company_domain: str | None,
    page_id: str | None,
    advertiser_name: str | None,
    resolver: Any,
) -> AdvertiserResolution:
    """Decide which LinkedIn page this harvest will address, and how well that is known.

    Three paths, and the point of the whole function is that they stay TOLD APART rather than
    collapsing into one green "resolved":

    * **explicit** — the operator supplied the page id. No resolver is called, because the id
      IS the assertion; it is not verification, though, so ``verified`` stays false and the
      advertiser-name check is what actually tests it.
    * **pdl** — an independent resolver named the page from the domain. The only path that
      earns ``verified``.
    * **ad_library_domain** — nothing could resolve the domain, so the ad library resolves it
      itself. Exactly the pre-R3-A behaviour, kept deliberately, and now labelled.

    NOTHING here raises. Every way identity resolution can go wrong — no key, unknown domain, a
    vendor outage, a resolver that answered without a page id — degrades to the fallback with a
    recorded note, because a harvest that could still work must not be lost to an enrichment
    call that did not.
    """
    explicit = (page_id or "").strip()
    if explicit:
        return AdvertiserResolution(
            resolver_used=RESOLVER_EXPLICIT,
            linkedin_page_id=explicit,
            resolved_name=advertiser_name,
            verified=False,
            note=(
                "the LinkedIn page id was supplied by the operator, so no identity resolver was "
                "called — an assertion rather than a verification, tested by the advertiser-name "
                "check"
            ),
        )

    domain = (company_domain or "").strip()

    def fallback(note: str) -> AdvertiserResolution:
        return AdvertiserResolution(
            resolver_used=RESOLVER_AD_LIBRARY_DOMAIN,
            linkedin_page_id=None,
            resolved_name=advertiser_name,
            verified=False,
            note=note,
        )

    try:
        engine = resolver if resolver is not None else resolve_company_identity_resolver()
        identity = engine.resolve(domain)
    except CompanyIdentityError as error:
        return fallback(
            f"the company-identity resolver could not answer ({error.code}); the ad library "
            "resolved the domain itself and NOTHING verified which page was harvested"
        )
    except Exception as error:  # noqa: BLE001 - an injected resolver may raise anything
        return fallback(
            f"the company-identity resolver failed ({type(error).__name__}); the ad library "
            "resolved the domain itself and NOTHING verified which page was harvested"
        )

    if identity is None:
        return fallback(
            f"the company-identity resolver has no record of {domain!r}; the ad library "
            "resolved the domain itself and NOTHING verified which page was harvested"
        )
    if not identity.addresses_a_page:
        # A named company with no LinkedIn page is a real record, and its NAME is still worth
        # keeping: it cannot address the harvest, but it can still gate custody.
        return replace(
            fallback(
                f"{identity.provider} knows {domain!r} as {identity.name!r} but lists no "
                "LinkedIn page, so the ad library resolved the domain itself"
            ),
            resolved_name=identity.name or advertiser_name,
        )

    return AdvertiserResolution(
        resolver_used=RESOLVER_PDL,
        linkedin_page_id=identity.linkedin_id,
        linkedin_url=identity.linkedin_url,
        # The RESOLVER's name, not the request's: the whole point is to compare the harvested
        # ads against an independently-sourced identity. A request-supplied name compared
        # against itself would verify nothing.
        resolved_name=identity.name or advertiser_name,
        verified=True,
    )


def _distil(creatives: list[Any], *, distiller: Any, evidence: JsonObject) -> AdDnaCard | None:
    """One vision pass, and a recorded reason whenever it produces nothing."""
    engine = distiller if distiller is not None else resolve_distiller()
    if not getattr(engine, "active", False):
        evidence["steps"]["distill"] = {
            "status": "skipped",
            "reason": "the ad-DNA distiller is not configured (no model key)",
        }
        return None
    try:
        previews = previews_for(creatives)
    except Exception as error:  # noqa: BLE001 - a preview failure is not a job failure
        evidence["steps"]["distill"] = {"status": "failed", "reason": _reason(error)}
        return None
    if not previews:
        evidence["steps"]["distill"] = {
            "status": "failed",
            "reason": "no harvested creative could be downscaled into a preview",
        }
        return None
    card = engine.distil(previews)
    if card is None:
        evidence["steps"]["distill"] = {
            "status": "failed",
            "reason": getattr(engine, "last_failure_reason", None) or "the model returned no card",
        }
        return None
    return card


def _pregenerate(
    card: AdDnaCard,
    *,
    creatives: list[Any],
    core: Any,
    cache_dir: str,
    tools: Any,
    repo: HybridRepository,
    generate: Optional[Callable[..., Any]],
    card_id: str,
    card_version: int,
    brand_name: str | None,
    evidence: JsonObject,
) -> None:
    """Generate and link imagery per style group. Its own outcome; never raises past here."""
    if generate is None:
        from lumen_api import image_provider

        if not image_provider.is_configured():
            evidence["steps"]["pregenerate"] = {
                "status": "skipped",
                "reason": "the image model is not configured",
            }
            return
        generate = image_provider.generate

    references = [
        (creative.image_bytes, creative.mime_type)
        for creative in creatives[:MAX_REFERENCE_IMAGES]
    ]
    # The generation ledger, wired the way the `/assets/generate` route wires it: a key
    # computed from the request, a READ that avoids the spend, and a governed write that claims
    # the key. Reference DIGESTS participate, so a later harvest that changed the references
    # correctly gets a different key rather than silently re-using the old ground.
    reference_digests = [_digest(payload) for payload, _mime in references]
    generation_key_for, find_generated = _generation_ledger(repo, reference_digests)

    try:
        outcome = pregenerate_for_card(
            card.to_json(),
            core=core,
            cache_dir=cache_dir,
            generate=generate,
            reference_images=references,
            brand_name=brand_name,
            generation_key_for=generation_key_for,
            find_generated=find_generated,
            max_bytes=settings.lumen_asset_max_bytes,
        )
    except Exception as error:  # noqa: BLE001 - the card is already durable; never lose it
        evidence["steps"]["pregenerate"] = {"status": "failed", "reason": _reason(error)}
        return

    for asset in outcome.assets:
        # A freshly generated asset claims its ledger key in the same governed write that
        # registers it; one re-used from the ledger is already registered and needs nothing.
        if asset.generation_key is None:
            continue
        tools.invoke(
            "design_register_generated_asset",
            {"record": asset.record, "generation_key": asset.generation_key},
            workspace_id=repo.workspace_id,
            actor="agent",
        )
    if outcome.assets:
        tools.invoke(
            "design_link_ad_pregenerated_assets",
            {
                "card_id": card_id,
                "card_version": card_version,
                "links": outcome.links(),
            },
            workspace_id=repo.workspace_id,
            actor="agent",
        )
    evidence["steps"]["pregenerate"] = {
        "status": "ok" if outcome.assets else "empty",
        "generated": len(outcome.assets),
        "failures": [{"target": target, "reason": reason} for target, reason in outcome.failures],
    }


def _generation_ledger(
    repo: HybridRepository, reference_digests: list[str]
) -> "tuple[Callable[..., str], Callable[[str], Optional[JsonObject]]]":
    """The (key builder, pre-spend probe) pair for pre-generation.

    Built here rather than inside ``pregenerate`` because the ledger belongs to the design
    app's repository and the pre-generation step must stay a pure "what to ask for" function
    that a test can drive with no database at all.
    """
    from lumen_api import image_cache, image_provider

    model_id = image_provider.configured_model_id()

    def key_for(*, prompt: str, aspect_ratio: str) -> str:
        return image_cache.generation_key(
            prompt=prompt,
            model=model_id,
            aspect_ratio=aspect_ratio,
            reference_digests=reference_digests or None,
        )

    def find(key: str) -> Optional[JsonObject]:
        try:
            return repo.get_generation_result(key)
        except Exception:  # noqa: BLE001 - a ledger miss must never fail pre-generation
            return None

    return key_for, find


def _digest(data: bytes) -> str:
    import hashlib

    return hashlib.sha256(data).hexdigest()


#: The lane's steps, in the order they run. A job that ran all five to `ok` produced all three
#: of the lane's artifact kinds — custodied creatives, an ad-DNA card, pre-generated imagery.
#: Listed once so the summary and its status can never disagree about what "everything" means.
_LANE_STEPS = ("harvest", "custody", "record", "distill", "pregenerate")


def _outcome(evidence: JsonObject) -> JsonObject:
    """The job's TOP-LEVEL, machine-readable outcome, derived from the per-step record.

    W5/R2-C. An empty harvest, a distillation skipped for a missing key, and a fully populated
    lane all end `succeeded` — correctly, because none of them is an error (D5: this lane has
    no gates, and a brand with no static ads has honestly nothing to harvest). What was wrong
    was that `succeeded` was the ONLY thing a caller saw. The truth — `kept: 0`, `distill:
    skipped` — sat one level down under `steps`, and the W5 run lost real time to it twice.

    So the outcome stays `succeeded` and gains a summary that says what actually happened, at
    the top of the evidence rather than buried in it, in counts a caller can branch on and one
    plain sentence a human can read. Derived here, at the single point all four exit paths
    return through, so a new early return cannot forget to describe itself.

    `status` is the summary's own word, not the job row's: `empty` when the lane holds nothing,
    `partial` when it holds creatives but is missing the card or the imagery, `ok` when every
    step ran and produced something.

    W5/R3-A adds a FOURTH status, `advertiser_mismatch`, and it is deliberately not folded into
    `empty`. Both leave the lane with nothing, but they mean opposite things: `empty` says the
    brand has no static ads, while `advertiser_mismatch` says ads were found and REFUSED because
    they belong to somebody else. Reading the second as the first is exactly the mistake the
    whole R3-A investigation made, for two rounds.
    """
    steps = evidence.get("steps") or {}
    resolution = evidence.get("resolution")
    resolution = resolution if isinstance(resolution, dict) else {}

    def _step(name: str) -> JsonObject:
        value = steps.get(name)
        return value if isinstance(value, dict) else {}

    check = _step("harvest").get("advertiser_check")
    check = check if isinstance(check, dict) else {}
    mismatch = _step("harvest").get("status") == "advertiser_mismatch"

    kept = int(_step("harvest").get("kept") or 0)
    custodied = int(_step("custody").get("custodied") or 0)
    card_written = _step("distill").get("status") == "ok"
    generated = int(_step("pregenerate").get("generated") or 0)

    skipped = [n for n in _LANE_STEPS if _step(n).get("status") == "skipped"]
    failed = [n for n in _LANE_STEPS if _step(n).get("status") == "failed"]
    # Absent, not skipped: an earlier step ended the run before this one was ever attempted.
    # The W5 report's "no distil or pregenerate key in evidence_json.steps" is exactly this
    # case, and it reads as silence unless it is named.
    not_reached = [n for n in _LANE_STEPS if n not in steps]
    reasons = {
        name: str(_step(name).get("reason"))
        for name in (*skipped, *failed)
        if _step(name).get("reason")
    }

    if mismatch:
        status = "advertiser_mismatch"
    elif custodied == 0:
        status = "empty"
    elif skipped or failed or not_reached or not card_written or generated == 0:
        status = "partial"
    else:
        status = "ok"

    sentences: list[str] = []
    # The advertiser sentence leads, because "whose ads are these" is the question every other
    # number in this summary is conditional on.
    sentences.append(_resolution_sentence(resolution))
    if mismatch:
        sentences.append(str(check.get("conflict") or "The advertiser names did not agree."))
    sentences.append(f"{kept} ad(s) kept, {custodied} custodied.")
    if card_written:
        sentences.append("An ad-DNA card was written.")
    else:
        sentences.append("No ad-DNA card was written.")
    sentences.append(f"{generated} background image(s) were pre-generated.")
    unfinished = [*skipped, *failed, *not_reached]
    if unfinished:
        sentences.append("Steps that produced nothing: " + ", ".join(unfinished) + ".")
    for name, reason in reasons.items():
        sentences.append(f"{name}: {reason}")

    return {
        "status": status,
        "summary": " ".join(s for s in sentences if s),
        "creatives_kept": kept,
        "creatives_custodied": custodied,
        "card_written": card_written,
        "assets_generated": generated,
        "steps_skipped": skipped,
        "steps_failed": failed,
        "steps_not_reached": not_reached,
        "reasons": reasons,
        # R3-A: the four facts an operator needed and could not get — which resolver decided
        # the advertiser, which page was harvested, whether anything independent verified it,
        # and the conflict sentence when the names disagreed.
        "resolver_used": resolution.get("resolver_used"),
        "linkedin_page_id": resolution.get("observed_page_id")
        or resolution.get("linkedin_page_id"),
        "advertiser_verified": bool(resolution.get("verified")),
        "advertiser_conflict": check.get("conflict") if mismatch else None,
    }


def _resolution_sentence(resolution: JsonObject) -> str:
    """One plain sentence naming who the advertiser was taken to be, and on whose word.

    A job whose evidence predates R3-A carries no resolution block at all; it gets no sentence
    rather than a fabricated one, so replaying an old row cannot make it claim a provenance it
    never had.
    """
    if not resolution:
        return ""
    used = resolution.get("resolver_used")
    page = resolution.get("observed_page_id") or resolution.get("linkedin_page_id")
    name = resolution.get("resolved_name")
    who = f"{name!r} " if name else ""
    where = f"LinkedIn page {page}" if page else "a page the ad library chose from the domain"
    if used == RESOLVER_PDL:
        return f"Harvested {who}from {where}, verified by an independent identity resolver."
    if used == RESOLVER_EXPLICIT:
        return f"Harvested {who}from {where}, an operator-supplied page id (unverified)."
    return (
        f"Harvested {who}from {where} — resolved by the ad library itself and "
        "UNVERIFIED by an independent identity resolver."
    )


def _complete(
    brand_kit_id: str,
    brand_kit_version: int,
    evidence: JsonObject,
    *,
    reporter: StageReporter | None = None,
) -> "tuple[str, int, Optional[str]]":
    """The job's terminal tuple.

    The result pointer is the brand kit the lane enriched, unchanged: this job publishes no kit
    version (the pre-generated imagery lands in the asset LIBRARY, not in the kit's own asset
    block), so the honest pointer is the kit the harvest was run for.

    W5/R2-C: the top-level outcome summary is stamped here, at the one point every exit path
    passes through, and the same sentence is reported as the job's final stage — so the two
    operator-visible surfaces, the durable evidence and the polled DTO, say the same thing.
    """
    outcome = _outcome(evidence)
    evidence["outcome"] = outcome
    if reporter is not None:
        # Progress really is 1.0 — the job IS done, and `store.complete` forces it anyway. What
        # the stage now carries is WHAT it finished with, instead of whichever step happened to
        # narrate last before an early return.
        reporter(outcome["summary"], 1.0)
    return (brand_kit_id, brand_kit_version, json.dumps(evidence))


def _reason(error: BaseException) -> str:
    code = getattr(error, "code", None)
    if code:
        return str(code)
    if isinstance(error, AdLibraryError):
        return error.message
    return f"{type(error).__name__}: {error}"
