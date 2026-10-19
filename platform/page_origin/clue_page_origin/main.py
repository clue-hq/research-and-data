"""Production entrypoint: ``python -m clue_page_origin.main`` (Railway) or
``uvicorn --factory clue_page_origin.main:build_application`` (dev stack). No app is built at import
time, so importing this module never reads settings or opens a database."""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI

import clue_obs
from clue_config import Secrets, Settings
from clue_db import db_lifespan, transaction
from clue_obs import get_logger
from clue_page_origin.app import create_page_origin_app
from clue_page_origin.edge import EdgeGate
from clue_page_origin.reads import DbPageReads
from clue_spine.hostnames import parse_suffixes, system_hostnames_off_suffix
from clue_storage import close_shared_s3_clients, storage_from_settings

log = get_logger("clue_page_origin.main")


def build_gate(settings: Settings, secrets: Secrets) -> EdgeGate:
    secret = secrets.pages_edge_secret.get_secret_value() if secrets.pages_edge_secret else None
    return EdgeGate(secret=secret, trust_host_header=settings.pages_trust_host_header)


def build_reads(settings: Settings, secrets: Secrets) -> DbPageReads:
    """Review finding K3-6: system addresses are served on the system suffix AND every legacy one,
    so throughout a published-pages domain move each link keeps working whichever domain its row
    names (docs/specs/pages-hosting-runbook.md §8)."""
    suffixes = parse_suffixes(
        f"{settings.pages_system_suffix},{settings.pages_legacy_system_suffixes}"
    )
    return DbPageReads(storage_from_settings(settings, secrets), system_suffixes=suffixes)


def build_application(settings: Settings | None = None, secrets: Secrets | None = None) -> FastAPI:
    resolved = settings if settings is not None else Settings()
    resolved_secrets = secrets if secrets is not None else Secrets()
    gate = build_gate(resolved, resolved_secrets)
    reads = build_reads(resolved, resolved_secrets)

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        clue_obs.setup()
        async with db_lifespan():
            async with transaction() as conn:
                off = await system_hostnames_off_suffix(conn, resolved.pages_system_suffix)
            if off:
                log.warning(
                    "pages.system_hostnames_off_suffix",
                    suffix=resolved.pages_system_suffix,
                    count=len(off),
                    sample=off[:5],
                )
            log.info(
                "page_origin.ready",
                suffix=resolved.pages_system_suffix,
                served_suffixes=list(reads.system_suffixes),
                trust_host_header=resolved.pages_trust_host_header,
            )
            try:
                yield
            finally:
                await close_shared_s3_clients()

    return create_page_origin_app(reads=reads, gate=gate, lifespan=lifespan)


if __name__ == "__main__":
    port = int(os.environ.get("PORT") or Settings().pages_origin_port)
    uvicorn.run(
        "clue_page_origin.main:build_application",
        factory=True,
        host="0.0.0.0",
        port=port,
        log_level="info",
    )
