"""Production entrypoint for projections, tools, and C7 structured research views."""

from __future__ import annotations

import uvicorn
from fastapi import FastAPI
from sqlalchemy import text

from clue_api.arv2.account_research_launch import DbArv2LaunchService
from clue_api.arv2.discovery_launch import DbArv2DiscoveryService
from clue_api.arv2.icp_authoring import DbIcpAuthoringService
from clue_api.arv2.read_tools import DbArv2ReadService
from clue_api.arv2_wiring import register_arv2_wiring
from clue_api.auth_wiring import build_principal_service
from clue_api.chat import StartupDevPrincipalResolver
from clue_api.compliance_wiring import register_compliance_wiring
from clue_api.composition import load_research_packs
from clue_api.exa_targeted_enrichment import build_production_exa_targeted_starter
from clue_api.exa_websets_lifecycle import ExaWebhookIngestor, build_exa_webhook_router
from clue_api.execution_wiring import build_tool_invoker
from clue_api.frontend_read.contact_email_lookup import build_contact_email_lookup_service
from clue_api.memory_wiring import memory_write_factory_builder
from clue_api.narrative_wiring import register_narrative_wiring
from clue_api.observability_wiring import build_observability_surface
from clue_api.persona_request_tools import DbPersonaRequestService
from clue_api.phase_c_wiring import Stage0ScrapeBinder, build_stage0_scrape_binder
from clue_api.product_path_preflight import assert_product_path_composition
from clue_api.production_tracing import (
    install_production_langfuse,
    install_production_sentry,
    install_production_tracing,
)
from clue_api.project_document_tools import DbProjectDocumentService
from clue_api.project_library_refresh import ProjectLibraryRefresher
from clue_api.projections_app import create_projections_app
from clue_api.research_view_runtime import (
    ProductionResearchViewRuntime,
    build_production_research_view_runtime,
)
from clue_api.run_composition import (
    bind_stage0_search_resolver,
    build_optional_platform_gateway,
    build_stage0_claim_extractor,
)
from clue_api.storage_wiring import build_storage_backend
from clue_api.sumble_account_gaps import build_production_sumble_account_gap_starter
from clue_api.toolbelt_wiring import build_toolbelt
from clue_api.transactional_account_launch import (
    build_transactional_account_launch_invoker_factory,
)
from clue_config import Secrets, Settings, load_settings
from clue_db import transaction
from clue_obs import get_logger
from clue_research.adapters import default_scrape_backend
from clue_research.durable import BudgetEngine, DbBudgetStore
from clue_research.resolvers import ScrapePolicy
from clue_spine.hostnames import system_hostnames_off_suffix
from clue_toolbelt import DbIdempotencyStore

log = get_logger("clue_api.projections_main")


def _c7_enabled(settings: Settings) -> bool:
    return any(
        (
            settings.c7_research_view_read_enabled,
            settings.c7_snapshot_compose_enabled,
            settings.c7_evidence_actions_enabled,
            settings.c7_recheck_enabled,
            settings.c7_production_handoff_enabled,
            settings.c7_legacy_dossier_alias_enabled,
        )
    )


def build_application(
    settings: Settings | None = None, *, secrets: Secrets | None = None
) -> FastAPI:
    """Build one fully wired process application; no enabled C7 collaborator is optional."""

    resolved = settings if settings is not None else load_settings()
    resolved_secrets = secrets if secrets is not None else Secrets()
    # Startup gate: a declared product path that is missing a provider credential refuses here,
    # before any collaborator is composed, rather than serving silently-degraded provider slots.
    assert_product_path_composition(resolved, resolved_secrets)
    # Lane 3 slice 2: the process's tracer provider (and Sentry) before any collaborator exists,
    # so every span this process opens belongs to one provider. Both are no-ops without an
    # endpoint / a DSN, which is the shipped default.
    tracing = install_production_tracing(
        resolved, resolved_secrets, service_name="clue-projections-api"
    )
    install_production_sentry(resolved, resolved_secrets, service_name="clue-projections-api")
    install_production_langfuse(
        resolved, resolved_secrets, runtime=tracing, service_name="clue-projections-api"
    )
    storage = build_storage_backend(resolved)
    research_views: ProductionResearchViewRuntime | None = (
        build_production_research_view_runtime(storage=storage) if _c7_enabled(resolved) else None
    )
    if research_views is not None:
        register_compliance_wiring()
        register_narrative_wiring()
    # Unconditional, unlike its C7-gated neighbours above: this process runs `load_research_packs`
    # whenever *either* self-serve provisioning or a C7 view is live (see the call below), and the
    # ARV2 fields must be registered in both cases — appending a loader is a pure list append with
    # no cost when the packs are never loaded.
    register_arv2_wiring()
    # FI-4 slice 2 (charter composition-backlog item 2): the live Stage-0 official-surface
    # scrape composition — without it every production `start_recon` refuses before spend.
    # Gated on the SAME flag as the /stage0/setup routes (review BE-M4): an unconfigured
    # deployment is byte-identical to pre-slice-2 — `start_recon` keeps refusing everywhere,
    # including via the generic POST /tools route, so the flag bounds the whole new paid
    # scrape surface, not just the onboarding entry point.
    # Slice 3: the extractor is the REAL one — `LlmClaimExtractor` — whenever this deployment has a
    # model credential, so recon now drafts grounded `client.*` values from what it scraped instead
    # of storing snapshots nobody ever claimed from. Without a credential
    # `build_optional_platform_gateway` warns and returns None, and the composition degrades to the
    # slice-2 empty extractor (scrape + snapshot, no values) rather than failing this process's
    # import. (It used to be built only when this flag was on; since the memory consumer below
    # it is built once unconditionally, so a flag-off deployment with no credential now also
    # logs the builder's `stage0.claim_extraction_disabled_no_gateway` warning.)
    #
    # Lane D2 note: this composes a gateway *instance* in the HTTP process for the Stage-0 scrape
    # resolver, but the D2 boundary is untouched — the toolbelt is still built with no `gateway=`
    # argument, and no chat/turn-serving module reaches this wiring (both guarded by
    # tests/api/test_lane_d2_http_gateway_isolation.py).
    #
    # 2026-09-19: a SECOND sanctioned consumer joins the Stage-0 extractor — the project home's
    # memory panel, whose write seam needs the reconciliation judge (a human's note is reconciled
    # against what is already remembered, exactly as an agent-distilled one is). Both take the
    # SAME instance: one process, one gateway. It is still not a turn-path consumer — the memory
    # routes hang off `/frontend/v1`, the toolbelt below is still built with no `gateway=`, and
    # tests/api/test_lane_d2_http_gateway_isolation.py keeps both halves of that honest. Without a
    # credential the builder warns and returns None, and the memory writes then refuse
    # `MEMORY_UNAVAILABLE` rather than writing notes no judge ever saw.
    gateway = build_optional_platform_gateway(resolved)
    stage0_scrape_binder: Stage0ScrapeBinder | None = None
    # 2026-09-12: the old recon is its own switch (ledger A4); provisioning no longer implies it.
    if resolved.legacy_stage0_recon_enabled:
        stage0_extractor = build_stage0_claim_extractor(gateway)
        stage0_scrape_binder = build_stage0_scrape_binder(
            extractor=stage0_extractor,
            # Pass the resolved settings' backend explicitly — a None scraper would construct
            # a fresh Settings() inside the resolver registration (one settings truth per
            # process).
            scraper=default_scrape_backend(resolved),
            policy=ScrapePolicy(),
        )
        # Slice 3 task 7: the tier-3 open-web source behind `client.competitor` /
        # `client.buyer_profile`. It takes the SAME extractor instance and the SAME account
        # lookup as the scrape lane (the binder holds the client's record once identity
        # resolution produces it), and binds only when this deployment has an Exa credential.
        bind_stage0_search_resolver(
            extractor=stage0_extractor,
            accounts=stage0_scrape_binder,
            secrets=resolved_secrets,
        )
    # ARV2 Track R, R2 (seam 1). Composed only behind the lane's own flag; with it off the two
    # launch/read tools still register and refuse `arv2_account_research_not_composed` before any
    # spend, so this deployment is byte-identical to pre-R2 for every other surface.
    arv2_account_launch = (
        DbArv2LaunchService(resolved, storage) if resolved.arv2_account_research_enabled else None
    )
    arv2_discovery_launch = (
        DbArv2DiscoveryService(resolved, storage) if resolved.arv2_discovery_enabled else None
    )
    # The project library's refresher. Since F3 (AW-20) each chat syncs its own library copy at
    # the start of its turn, so this process writes nothing to disk and needs no workspace
    # factory: a forced refresh (a DSAR erasure) bumps the project's library epoch, which every
    # chat's next turn sees in the library digest.
    project_library = ProjectLibraryRefresher(conn_factory=transaction)
    # ICP authoring needs no flag of its own: writing a proposal spends nothing and confirms
    # nothing. What it needs is the storage the knowledge documents live in, so it composes where
    # the composed backend is. Without a service the tool registers and refuses by name.
    icp_authoring = DbIcpAuthoringService(storage, library=project_library)
    # The persona request DOES need the onboarding flag: what it opens is an onboarding run, and
    # with the lane off no worker would ever drive it — the row would sit ``queued`` forever,
    # holding that ICP document's one open slot. Off, the tool refuses by name. The queue is this
    # app's default ``DbWorkQueue``, exactly as ``DbOnboardingEnqueuer``'s is.
    persona_requests = DbPersonaRequestService() if resolved.onboarding_v2_enabled else None
    # The project plan has no flag of its own either: writing it down spends nothing and confirms
    # nothing, and it needs only the storage the knowledge documents live in. Without a service the
    # tool registers and refuses by name.
    project_documents = DbProjectDocumentService(storage, library=project_library)
    # The ARV2 reads have no flag at all, and need no storage: they read rows that exist on
    # every deployment (account membership, display blocks, claims, discovery runs) and reading
    # them spends nothing. Composed unconditionally; the tools refuse by name only where the
    # read surface itself is absent. ``settings`` is here for one predicate: the claims read
    # mirrors the account page's display gate, whose tier-4 arm is armed by
    # ``verification_enabled``.
    arv2_reads = DbArv2ReadService(settings=resolved)
    registry = build_toolbelt(
        storage=storage,
        settings=resolved,
        arv2_account_launch=arv2_account_launch,
        arv2_discovery_launch=arv2_discovery_launch,
        arv2_reads=arv2_reads,
        icp_authoring=icp_authoring,
        persona_requests=persona_requests,
        project_documents=project_documents,
        stage0_scrape_binder=stage0_scrape_binder,
        research_view_composer=(research_views.composer if research_views is not None else None),
        research_view_snapshots=(research_views.snapshots if research_views is not None else None),
        research_view_recheck=(research_views.recheck if research_views is not None else None),
        targeted_enrichment_starter=build_production_exa_targeted_starter(
            resolved,
            secrets=resolved_secrets,
            storage=storage,
        ),
        account_gap_enrichment_starter=build_production_sumble_account_gap_starter(
            resolved,
            secrets=resolved_secrets,
            storage=storage,
        ),
    )
    invoker = build_tool_invoker(
        registry=registry,
        idempotency_store=DbIdempotencyStore(),
        storage=storage,
        settings=resolved,
    )
    if research_views is not None:
        research_views.bind_tool_invoker(invoker)
        if resolved.c7_recheck_enabled and not research_views.deferred_requester.is_bound:
            raise RuntimeError("C7 recheck is enabled but its governed requester is unbound")
    budget = BudgetEngine(store=DbBudgetStore())
    auth_service = None
    auth_closer = None
    if resolved.auth_enabled:
        auth_service, auth_closer = build_principal_service(
            settings=resolved,
            conn_factory=transaction,
        )
    contact_email_lookup = (
        build_contact_email_lookup_service(
            ai_ark_api_key=resolved_secrets.ai_ark_api_key,
            ai_ark_min_gap_s=resolved.arv2_ai_ark_min_gap_s,
            storage=storage,
            poll_after_s=resolved.frontend_contact_email_poll_after_s,
        )
        if resolved.frontend_contact_email_lookup_enabled
        else None
    )

    # --- the chat surface's identity source: exactly one, decided here -------------------------
    # FI Lane B ⇄ Lane D join. Before the join this process built the development principal
    # whenever chat was enabled *and* the real principal service whenever auth was enabled, and
    # said nothing about the case where both were true — the chat surface would then have been
    # handed a development identity while the rest of the app authenticated properly. That is
    # resolved explicitly:
    #
    #   auth_enabled          -> Lane B's real chain governs the chat surface; NO dev resolver.
    #   not auth_enabled      -> the guarded, Postgres-provisioned development principal.
    #
    # and the two settings that select them must agree, or the process refuses to start. The
    # development principal's rows can only be provisioned once the process has a database, so the
    # resolver is handed over now and bound from the startup check below; a process that cannot
    # provision its identity fails to start rather than serving chat under a fictional one.
    if resolved.chat_enabled:
        if resolved.auth_enabled and resolved.projections_auth_mode == "local_header":
            raise RuntimeError(
                "contradictory chat identity configuration: CLUE_AUTH_ENABLED=true selects the "
                "authenticated principal, but CLUE_PROJECTIONS_AUTH_MODE=local_header selects the "
                "development one; set CLUE_PROJECTIONS_AUTH_MODE=authenticated_principal"
            )
        if not resolved.auth_enabled and resolved.projections_auth_mode != "local_header":
            raise RuntimeError(
                "the chat surface has no authenticated principal: CLUE_AUTH_ENABLED is false and "
                f"CLUE_PROJECTIONS_AUTH_MODE={resolved.projections_auth_mode!r} forbids the "
                "development principal; enable CLUE_AUTH_ENABLED or select local_header"
            )
    chat_principal = (
        StartupDevPrincipalResolver()
        if resolved.chat_enabled and not resolved.auth_enabled
        else None
    )

    async def _warn_on_hostname_suffix_drift() -> None:
        async with transaction() as conn:
            off = await system_hostnames_off_suffix(conn, resolved.pages_system_suffix)
        if off:
            log.warning(
                "pages.system_hostnames_off_suffix",
                suffix=resolved.pages_system_suffix,
                count=len(off),
                sample=off[:5],
            )

    async def startup_check() -> None:
        if resolved.projections_auth_mode == "service":
            raise RuntimeError(
                "service authentication mode is selected but no service-auth resolver is wired"
            )
        if (
            resolved.projections_auth_mode == "authenticated_principal"
            and not resolved.auth_enabled
        ):
            raise RuntimeError(
                "authenticated-principal projections mode requires CLUE_AUTH_ENABLED=true"
            )
        if chat_principal is not None:
            ids = await chat_principal.bind(resolved)
            log.info(
                "chat.dev_principal.provisioned",
                user_id=ids.user_id,
                membership_id=ids.membership_id,
                workspace_id=ids.workspace_id,
                role_key=ids.role_key,
            )
        async with transaction() as conn:
            await conn.execute(text("SELECT 1"))
            # The Stage-0 waterfall reads source manifests from Postgres. A fresh deployment can
            # enable self-serve onboarding without enabling any C7 research-view capability, so
            # tying registry seeding only to ``research_views`` makes every planned source look
            # unregistered: both recon lanes then finish almost instantly with only empty fields.
            # Load the same idempotent registry whenever either consumer is live.
            # 2026-09-12: the old recon is its own switch (ledger A4); provisioning no longer
            # implies it.
            if resolved.legacy_stage0_recon_enabled or research_views is not None:
                await load_research_packs(conn)
            if research_views is not None:
                required = (
                    await conn.execute(
                        text(
                            """
                            SELECT
                                to_regclass('research_view_field_route') IS NOT NULL,
                                to_regclass('research_subject_activity') IS NOT NULL,
                                EXISTS (
                                    SELECT 1 FROM information_schema.columns
                                    WHERE table_name = 'account_entity'
                                      AND column_name = 'canonical_version'
                                ),
                                EXISTS (
                                    SELECT 1 FROM information_schema.columns
                                    WHERE table_name = 'workspace_policy'
                                      AND column_name = 'display_professional_public'
                                )
                            """
                        )
                    )
                ).one()
                if not all(bool(value) for value in required):
                    raise RuntimeError(
                        "C7 is enabled but its production-reader migration is not applied"
                    )
                route_count = int(
                    (
                        await conn.execute(
                            text("SELECT count(*) FROM research_view_field_route WHERE active")
                        )
                    ).scalar_one()
                )
                if resolved.c7_research_view_read_enabled and route_count == 0:
                    raise RuntimeError(
                        "C7 reads are enabled but no active field routes are registered"
                    )
        log.info(
            "c7.runtime.ready",
            read=resolved.c7_research_view_read_enabled,
            snapshot=resolved.c7_snapshot_compose_enabled,
            evidence=resolved.c7_evidence_actions_enabled,
            recheck=resolved.c7_recheck_enabled,
            canary_restricted=bool(resolved.c7_workspace_canary_ids),
        )
        # Custom-domain publishing S1: every workspace's permanent system hostname is
        # `<label>.<CLUE_PAGES_SYSTEM_SUFFIX>`, allocated at workspace creation. If the suffix
        # setting is later changed, the rows already at rest keep the OLD suffix — their public
        # URLs silently stop resolving through the new edge. That is a config error the operator
        # must see, not a reason to refuse to serve the whole API, so it warns and lists a sample.
        await _warn_on_hostname_suffix_drift()

    return create_projections_app(
        surface=build_observability_surface(budget=budget),
        tool_invoker=invoker,
        settings=resolved,
        ingestion_storage=storage,
        project_library=project_library,
        research_view_composer=(research_views.composer if research_views is not None else None),
        research_view_snapshots=(research_views.snapshots if research_views is not None else None),
        research_view_evidence_access=(
            research_views.evidence_access if research_views is not None else None
        ),
        research_view_owner_references=(
            research_views.owner_references if research_views is not None else None
        ),
        startup_check=startup_check,
        chat_principal_resolver=chat_principal,
        discovery_webhook_router=(
            build_exa_webhook_router(
                ExaWebhookIngestor(
                    secret=resolved_secrets.exa_websets_webhook_secret,
                    storage=storage,
                )
            )
            if resolved_secrets.exa_websets_webhook_secret is not None
            else None
        ),
        auth_service=auth_service,
        auth_closer=auth_closer,
        contact_email_lookup=contact_email_lookup,
        # Slice B founder ruling: a budget-controls-disabled directive approval confirms and
        # launches in one SQL transaction. This factory composes only the launch controller and
        # queue writer over that request's connection — never the model/provider worker runtime.
        transactional_tool_invoker_factory=(
            build_transactional_account_launch_invoker_factory(
                settings=resolved,
                storage=storage,
            )
            if resolved.entity_research_runtime_enabled and not resolved.budget_controls_enabled
            else None
        ),
        tracing=tracing,
        # The project home's memory panel writes through the scoped-memory seam; no gateway, no
        # seam (the panel's list still serves, its writes refuse loudly).
        memory_write_factory=(
            None if gateway is None else memory_write_factory_builder(resolved, gateway)
        ),
    )


app = build_application()


def main() -> None:
    """Serve the production application using the configured local bind address."""

    settings = load_settings()
    uvicorn.run(app, host=settings.projections_host, port=settings.projections_port)


if __name__ == "__main__":
    main()
