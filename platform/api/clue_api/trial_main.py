"""Executable local canary server: production projections/C7 plus Clue Trial routes."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

import uvicorn
from fastapi import FastAPI

import clue_obs
from clue_api.projections_main import build_application as build_projections_application
from clue_api.trial.coordinator import ClueTrialCoordinator
from clue_api.trial_app import create_trial_router
from clue_config import Settings, load_settings
from clue_db import db_lifespan
from clue_locks import redis_lifespan


def build_application(settings: Settings | None = None) -> FastAPI:
    """Build the loopback-only trial process, failing closed on missing feature flags."""

    resolved = settings if settings is not None else load_settings()
    if not resolved.trial_enabled:
        raise RuntimeError("Clue Trial is disabled; set CLUE_TRIAL_ENABLED=true")
    if resolved.trial_host not in {"127.0.0.1", "localhost", "::1"}:
        raise RuntimeError("Clue Trial is local-only and must bind to a loopback host")
    if not resolved.c7_research_view_read_enabled:
        raise RuntimeError(
            "Clue Trial requires canonical C7 reads; set CLUE_C7_RESEARCH_VIEW_READ_ENABLED=true"
        )
    coordinator = ClueTrialCoordinator(
        settings=resolved,
        root=Path(resolved.trial_root),
    )
    app = build_projections_application(resolved)
    app.title = "Clue-HQ local Sumble trial"
    app.include_router(create_trial_router(coordinator))
    app.state.trial_coordinator = coordinator

    @asynccontextmanager
    async def trial_lifespan(lifespan_app: FastAPI) -> AsyncIterator[None]:
        clue_obs.setup()
        async with db_lifespan(), redis_lifespan():
            startup_check = getattr(lifespan_app.state, "startup_check", None)
            if startup_check is not None:
                await startup_check()
            yield

    # The base projections app owns its normal DB-only lifespan. The canary also runs production
    # DEEP account locks, so this executable adds Redis while preserving the same startup check.
    app.router.lifespan_context = trial_lifespan
    return app


def main() -> None:
    settings = load_settings()
    app = build_application(settings)
    uvicorn.run(app, host=settings.trial_host, port=settings.trial_port)


if __name__ == "__main__":
    main()
