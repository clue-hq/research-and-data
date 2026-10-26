"""Start onboarding for a workspace: the one start both routes use (spec 2026-10-25 §3.2).

``POST /onboarding`` (the setting-up screen) and the operator route call this. In order:
normalize the domain; run the provider pre-flight and refuse before anything exists when a
required provider is dead; then, under the per-workspace start lock, resolve the brand, refuse
while a ``full`` or ``repair`` run is open, and record the run; offer it to the fleet (a failed
offer fails the run); and ask for the brand-kit ingestion (fail-soft, gap-aware ``ensure``).
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from uuid import UUID, uuid4

from sqlalchemy import text

from clue_api.arv2.onboarding_store import create_run, fail_run
from clue_api.workspace_ops.operators import OpsRefused
from clue_api.workspace_ops.preflight import PreflightReport
from clue_db import ConnFactory
from clue_obs import get_logger
from clue_spine import get_brand, list_brands_for_workspace

log = get_logger("clue_api.workspace_ops.onboarding_start")

Preflight = Callable[[str], Awaitable[PreflightReport]]

_LOCK_SQL = text("SELECT pg_advisory_xact_lock(hashtextextended(:lock_key, 0))")


def normalize_domain(company_domain: str) -> str:
    return (
        company_domain.strip().lower().removeprefix("https://").removeprefix("http://").rstrip("/")
    )


async def start_onboarding(
    conn_factory: ConnFactory,
    *,
    workspace_id: str,
    domain: str,
    brand_id: str | None,
    company_name: str | None,
    requested_by_user_id: str,
    enqueuer: object,
    brand_kit_ingestion: object | None,
    preflight: Preflight | None,
) -> UUID:
    domain = normalize_domain(domain)
    if not domain:
        raise OpsRefused(422, "blank_domain", "company_domain is blank")
    if preflight is not None:
        report = await preflight(workspace_id)
        if report.blocking:
            raise OpsRefused(
                503,
                "providers_unavailable",
                "a provider onboarding needs is not usable; nothing was started",
                detail={"providers": [result.as_json() for result in report.blocking]},
            )
    async with conn_factory() as conn:
        if brand_id is not None:
            # ``get_brand`` is workspace-scoped, so a foreign brand id reads as absent.
            brand = await get_brand(conn, workspace_id=workspace_id, brand_id=brand_id)
        else:
            brands = await list_brands_for_workspace(conn, workspace_id)
            brand = brands[0] if len(brands) == 1 else None
        if brand is None:
            raise OpsRefused(409, "brand_unavailable", "name one brand of this workspace")
        # One walk — full or repair — at a time per workspace: two would race on the same
        # brand's document paths and double the spend. A ``personas`` run is not one. The read
        # and the insert are one decision, under a transaction-scoped advisory lock.
        await conn.execute(_LOCK_SQL, {"lock_key": f"onboarding-start:{workspace_id}"})
        open_run = (
            await conn.execute(
                text(
                    "SELECT run_id FROM onboarding_run WHERE workspace_id = :ws "
                    "AND kind IN ('full', 'repair') AND status IN ('queued', 'running') LIMIT 1"
                ),
                {"ws": workspace_id},
            )
        ).scalar_one_or_none()
        if open_run is not None:
            raise OpsRefused(409, "onboarding_in_progress", str(open_run))
        run_id = uuid4()
        await create_run(
            conn,
            run_id=run_id,
            workspace_id=workspace_id,
            brand_id=brand.brand_id,
            company_domain=domain,
            requested_by_user_id=requested_by_user_id,
        )
    # The row lands before the offer: a task that arrives at a worker always finds its run. A
    # run recorded but never offered would block every later start, so a failed offer (or a
    # refused one, impossible for a fresh uuid) fails the run.
    offer_error: Exception | None = None
    try:
        offered = await enqueuer.enqueue(  # type: ignore[attr-defined]
            run_id=run_id,
            workspace_id=workspace_id,
            brand_id=brand.brand_id,
            company_domain=domain,
            company_name=(company_name or "").strip() or domain,
        )
    except Exception as error:  # noqa: BLE001 - any failure means the run was not offered
        log.exception("onboarding.enqueue_failed", run_id=str(run_id), workspace_id=workspace_id)
        offered, offer_error = False, error
    if not offered:
        if offer_error is None:
            log.error("onboarding.enqueue_refused", run_id=str(run_id), workspace_id=workspace_id)
        async with conn_factory() as conn:
            await fail_run(conn, run_id=run_id)
        raise OpsRefused(503, "enqueue_failed", "the onboarding job could not be queued; try again")
    if brand_kit_ingestion is not None:
        # Fail-soft by contract (``ensure`` never raises): no brand kit must fail onboarding.
        await brand_kit_ingestion.ensure(  # type: ignore[attr-defined]
            workspace_id=workspace_id, website=f"https://{domain}"
        )
    return run_id
