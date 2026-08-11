"""Production entrypoint for projections, tools, and C7 structured research views."""

from __future__ import annotations

import uvicorn
from fastapi import FastAPI
from sqlalchemy import text

from clue_api.auth_wiring import build_principal_service
from clue_api.chat import StartupDevPrincipalResolver
from clue_api.compliance_wiring import register_compliance_wiring
from clue_api.composition import load_research_packs
from clue_api.exa_targeted_enrichment import build_production_exa_targeted_starter
from clue_api.exa_websets_lifecycle import ExaWebhookIngestor, build_exa_webhook_router
from clue_api.execution_wiring import build_tool_invoker
from clue_api.narrative_wiring import register_narrative_wiring
from clue_api.observability_wiring import build_observability_surface
from clue_api.phase_c_wiring import build_stage0_scrape_binder
from clue_api.projections_app import create_projections_app
from clue_api.research_view_runtime import (
    ProductionResearchViewRuntime,
    build_production_research_view_runtime,
)
from clue_api.storage_wiring import build_storage_backend
from clue_api.sumble_account_gaps import build_production_sumble_account_gap_starter
from clue_api.toolbelt_wiring import build_toolbelt
from clue_config import Secrets, Settings, load_settings
from clue_db import transaction
from clue_obs import get_logger
from clue_research.adapters import CallableClaimExtractor, default_scrape_backend
from clue_research.durable import BudgetEngine, DbBudgetStore
from clue_research.resolvers import ScrapePolicy
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
    storage = build_storage_backend(resolved)
    research_views: ProductionResearchViewRuntime | None = (
        build_production_research_view_runtime(storage=storage) if _c7_enabled(resolved) else None
    )
    if research_views is not None:
        register_compliance_wiring()
        register_narrative_wiring()
    # FI-4 slice 2 (charter composition-backlog item 2): the live Stage-0 official-surface
    # scrape composition — without it every production `start_recon` refuses before spend.
    # The extractor is EXPLICITLY empty: no production ClaimExtractor exists yet (the LLM
    # extractor is its own scoped work item), so recon resolves the client, scrapes the
    # official site under target-lock, and captures durable snapshot evidence — but drafts
    # no client.* values from it. The interview remains the tier-1 client.* fill path.
    stage0_scrape_binder = build_stage0_scrape_binder(
        extractor=CallableClaimExtractor(lambda normalized, entity, field: []),
        # Pass the resolved settings' backend explicitly — a None scraper would construct a
        # fresh Settings() inside the resolver registration (one settings truth per process).
        scraper=default_scrape_backend(resolved),
        policy=ScrapePolicy(),
    )
    registry = build_toolbelt(
        storage=storage,
        settings=resolved,
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
            if research_views is not None:
                await load_research_packs(conn)
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

    return create_projections_app(
        surface=build_observability_surface(budget=budget),
        tool_invoker=invoker,
        settings=resolved,
        ingestion_storage=storage,
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
    )


app = build_application()


def main() -> None:
    """Serve the production application using the configured local bind address."""

    settings = load_settings()
    uvicorn.run(app, host=settings.projections_host, port=settings.projections_port)


if __name__ == "__main__":
    main()
