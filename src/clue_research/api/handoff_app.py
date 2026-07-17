"""M12.3 — the output/handoff **HTTP surface** (FastAPI), the terminal seam of the subsystem.

This is the exact place the research subsystem ends (overview §3): a *narrow, read-only* HTTP
contract over the M12.2 ``account_handoff`` objects + their ``provenance_index`` — the one stable
boundary the downstream content layer (and, through it, the design subsystem) consumes. It is a
**thin adapter** over the transport-agnostic :class:`~clue_research.narrative.HandoffService`: the
routes parse and authorise, call the service, and stamp the schema version; all read/emit logic
lives in ``narrative`` (a worker), so the seam can later be served over event push or a D2
design-system adapter without touching the service (M12.3 AC8). FastAPI with the
lifespan/``asynccontextmanager`` pattern the rest of the stack uses for pools (substrate §12).

**Read-only by construction:** every route is a ``GET``. There is no write endpoint — no
content/design write ever flows back through this API into the claim store (Postgres-only source of
truth, conventions §6 / substrate §5c). The emit/notify *push* is the one-directional
``handoff_event`` outbox, driven by the campaign-run state machine (``api/handoff_wiring``), never
by a request here.

**Tenancy:** access is scoped to ``client_id`` via the injected ``tenant_resolver`` dependency (the
auth seam). The default reads the ``X-Client-Id`` header; production swaps in real service-auth
(M0.4) of the same shape. A client can never fetch another client's assembled handoff (substrate
§2): the service's reads are tenant-scoped, so a cross-tenant fetch is a ``404`` (indistinguishable
from absent — never leak another tenant's existence).
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, FastAPI, Header, HTTPException, Query, Response
from sqlalchemy.ext.asyncio import AsyncConnection

import clue_obs
from clue_core import CampaignRunId, ClaimId, EntityId, Persona
from clue_research.db import connection, db_lifespan
from clue_research.narrative import (
    HANDOFF_SCHEMA_VERSION,
    HandoffListPage,
    HandoffNotFoundError,
    HandoffService,
    ProvenanceRefResponse,
    ServedHandoff,
)

# The response header pinning the served ``account_handoff`` contract version (M12.3 AC5): a
# consumer reads it to confirm the shape it negotiated; an additive bump keeps a pinned consumer ok.
HANDOFF_SCHEMA_HEADER = "X-Handoff-Schema-Version"

TenantResolver = Callable[..., str]
ConnDependency = Callable[..., AsyncIterator[AsyncConnection]]


def header_tenant_resolver(
    x_client_id: Annotated[str | None, Header(alias="X-Client-Id")] = None,
) -> str:
    """The default tenant/auth seam: derive ``client_id`` from the ``X-Client-Id`` header (``401``
    if absent). Production replaces this with real service-auth (M0.4 — token validation → tenant)
    of the same ``-> client_id`` shape, swapped via the ``tenant_resolver`` factory arg or
    ``app.dependency_overrides``; the routes do not change."""
    if not x_client_id:
        raise HTTPException(status_code=401, detail="missing X-Client-Id (tenant) header")
    return x_client_id


async def read_conn_dependency() -> AsyncIterator[AsyncConnection]:
    """Yield a pooled read connection per request (no surrounding transaction — the handoff API only
    reads). Tests override this to yield a rollback-scoped connection."""
    async with connection() as conn:
        yield conn


# The per-request injected dependencies as module-level Annotated aliases. They MUST be module-level
# (not closure locals): ``from __future__ import annotations`` stringifies every annotation, and
# FastAPI resolves those strings via ``get_type_hints`` against the function's *module globals* — a
# closure-local alias would not resolve, and FastAPI would silently treat ``conn`` / ``client_id``
# as query params. The auth + connection seams swap via ``app.dependency_overrides`` (the idiomatic
# FastAPI way), wired by :func:`create_handoff_app`; the routes never change (M12.3 AC8).
ConnDep = Annotated[AsyncConnection, Depends(read_conn_dependency)]
TenantDep = Annotated[str, Depends(header_tenant_resolver)]


def create_handoff_router(service: HandoffService) -> APIRouter:
    """Build the read-only handoff :class:`APIRouter` over ``service``. The auth + connection seams
    are the module-level :data:`TenantDep` / :data:`ConnDep` dependencies, swapped via
    ``app.dependency_overrides`` (see :func:`create_handoff_app`). Every route is a ``GET`` — there
    is deliberately no write path (AC4)."""
    router = APIRouter()

    @router.get("/campaign_runs/{campaign_run_id}/handoffs", response_model=HandoffListPage)
    async def list_run_handoffs(
        campaign_run_id: UUID,
        response: Response,
        conn: ConnDep,
        client_id: TenantDep,
        tier: Annotated[str | None, Query()] = None,
        persona: Annotated[Persona | None, Query()] = None,
        min_verification_pass_rate: Annotated[float | None, Query(ge=0.0, le=1.0)] = None,
    ) -> HandoffListPage:
        """List the ready handoffs for a run (only handoff-phase accounts; an account still in
        deep/verification is absent — AC2). Optional ``tier`` / ``persona`` /
        ``min_verification_pass_rate`` filters. The envelope carries the run's phase so a consumer
        can poll rather than guess."""
        response.headers[HANDOFF_SCHEMA_HEADER] = HANDOFF_SCHEMA_VERSION
        return await service.list_handoffs(
            conn,
            client_id=client_id,
            campaign_run_id=CampaignRunId(campaign_run_id),
            tier=tier,
            persona=persona,
            min_verification_pass_rate=min_verification_pass_rate,
        )

    @router.get("/accounts/{account_entity_id}/handoff", response_model=ServedHandoff)
    async def get_account_handoff(
        account_entity_id: UUID,
        response: Response,
        conn: ConnDep,
        client_id: TenantDep,
        icp_spec_version: Annotated[int, Query(ge=1)],
        icp_key: Annotated[str, Query()] = "",
    ) -> ServedHandoff:
        """Fetch one ``account_handoff`` (with its ``provenance_index`` + ``verification_health``).
        ``404`` if not yet assembled or not this tenant's (AC1/AC6)."""
        response.headers[HANDOFF_SCHEMA_HEADER] = HANDOFF_SCHEMA_VERSION
        try:
            return await service.get_handoff(
                conn,
                client_id=client_id,
                account_entity_id=EntityId(account_entity_id),
                icp_spec_version=icp_spec_version,
                icp_key=icp_key,
            )
        except HandoffNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @router.get(
        "/accounts/{account_entity_id}/handoff/provenance/{claim_id}",
        response_model=ProvenanceRefResponse,
    )
    async def get_handoff_provenance(
        account_entity_id: UUID,
        claim_id: UUID,
        response: Response,
        conn: ConnDep,
        client_id: TenantDep,
        icp_spec_version: Annotated[int, Query(ge=1)],
        icp_key: Annotated[str, Query()] = "",
    ) -> ProvenanceRefResponse:
        """Resolve one value's ``claim_id`` to its full source provenance within a served handoff —
        the "every line is sourced" traversal (AC1). ``404`` if the handoff/claim is absent."""
        response.headers[HANDOFF_SCHEMA_HEADER] = HANDOFF_SCHEMA_VERSION
        try:
            ref = await service.resolve_provenance(
                conn,
                client_id=client_id,
                account_entity_id=EntityId(account_entity_id),
                icp_spec_version=icp_spec_version,
                claim_id=ClaimId(claim_id),
                icp_key=icp_key,
            )
        except HandoffNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return ProvenanceRefResponse(claim_id=ClaimId(claim_id), provenance=ref)

    return router


@asynccontextmanager
async def handoff_lifespan(_app: FastAPI) -> AsyncIterator[None]:
    """Production lifespan: configure logging once (Doc R §4 — one ``clue_obs.setup`` per
    entrypoint), then open the DB engine for the app's lifetime (substrate §12). A standalone
    handoff server uses this; tests pass a no-op lifespan and override the connection dependency."""
    clue_obs.setup()
    async with db_lifespan():
        yield


def create_handoff_app(
    service: HandoffService,
    *,
    tenant_resolver: TenantResolver | None = None,
    conn_dependency: ConnDependency | None = None,
    manage_db_lifespan: bool = True,
) -> FastAPI:
    """Construct the handoff FastAPI app (the terminal subsystem seam).

    ``tenant_resolver`` / ``conn_dependency`` swap the auth + connection seams via
    ``app.dependency_overrides`` (the idiomatic FastAPI override of the module-level
    :func:`header_tenant_resolver` / :func:`read_conn_dependency`) — production injects a real
    service-auth resolver; tests inject a rollback-scoped connection. ``manage_db_lifespan`` opens
    the DB engine for the app's lifetime (production); set ``False`` when the surrounding process
    already manages :func:`db_lifespan` (or in tests that drive their own engine)."""
    app = FastAPI(
        title="Clue-HQ research — handoff API",
        version=HANDOFF_SCHEMA_VERSION,
        lifespan=handoff_lifespan if manage_db_lifespan else None,
    )
    if tenant_resolver is not None:
        app.dependency_overrides[header_tenant_resolver] = tenant_resolver
    if conn_dependency is not None:
        app.dependency_overrides[read_conn_dependency] = conn_dependency
    app.include_router(create_handoff_router(service))
    return app
