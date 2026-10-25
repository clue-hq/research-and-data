"""Offer the ad-DNA card job once a workspace has both a finished harvest and a brand kit.

Auto ad ingestion at onboarding (2026-09-28). Onboarding starts two jobs at once: the website
brand-kit ingestion and an ad-assets HARVEST, which needs no kit. The CARD phase (distil the
ad-DNA card, pin it to the kit, pre-generate imagery) needs both, so it cannot start until the
slower of the two has finished. Neither job waits for the other: each one, when it succeeds,
calls :func:`offer_card_if_ready`, and whichever finishes second finds both halves and offers the
card. Waiting inside a job instead would park a worker on the single ingestion coordinator slot
that the kit ingestion itself needs.

**Exactly once, without a lock.** The card job's ids are derived from the workspace and the
harvest job, so two callers racing each other propose the SAME job id and fleet work id: the job
row's primary key and the queue's dedup key accept the first and refuse the second. The existence
read below only saves the refused round trip.
"""

from __future__ import annotations

import hashlib
from typing import Any, Callable, Optional
from uuid import NAMESPACE_URL, uuid5

from clue_design.enums import DesignIngestionKind
from clue_design.envelopes import DesignIngestionEnvelope
from py_lumen_config import settings
from py_lumen_obs import get_logger

from ..jobs import IngestionJobStore

JsonObject = dict[str, Any]

logger = get_logger("lumen_ingestion.ad_library.auto_card")

__all__ = ["KIT_INGESTION_KINDS", "card_job_id", "card_offer_hook", "offer_card_if_ready"]

#: The ingestion kinds that end with a brand kit. An ``ad_assets`` job builds none.
KIT_INGESTION_KINDS = ("website", "pdf", "asset_upload")

#: A job that finished with a usable result — a gapped one included (spec 2026-10-25 §5.1).
_FINISHED = ("succeeded", "succeeded_with_gaps")

#: How far back the readiness check looks. A workspace has a handful of ingestion jobs.
_RECENT = 50


def _attempt_suffix(attempt: int) -> str:
    return f":{attempt}" if attempt else ""


def card_job_id(workspace_id: str, harvest_job_id: str, attempt: int = 0) -> str:
    """A harvest's card job for one attempt. Attempt 0 is the id the automatic hook has always
    used; a workspace repair re-offers a failed card as attempt 1, 2, … (spec 2026-10-25)."""
    key = f"{workspace_id}:{harvest_job_id}{_attempt_suffix(attempt)}"
    return f"ingest_adcard_{hashlib.sha256(key.encode()).hexdigest()[:24]}"


def offer_card_if_ready(
    workspace_id: str, *, tools: Any = None, retry: bool = False
) -> Optional[str]:
    """Offer the card job if a finished harvest and a kit both exist. Returns its id, or None.

    ``None`` covers every "nothing to do": the lane is off, no harvest has finished, the newest
    harvest kept no ads, no kit exists yet, or this harvest's card job was already offered.

    ``retry`` is the workspace repair's re-offer of a card that never got written: when the
    harvest has no card and none of its card jobs is still queued or running, the next attempt
    is offered. The automatic hook never retries — a failed card stays failed until someone asks.
    """
    if not settings.lumen_brand_ad_assets:
        return None
    store = IngestionJobStore(workspace_id=workspace_id)
    harvest = _newest_usable_harvest(store)
    kit = _newest_kit(store)
    if harvest is None or kit is None:
        return None

    harvest_job_id = str(harvest["job_id"])
    attempt = 0
    if retry:
        card_jobs = _card_jobs(store, harvest_job_id)
        if any(job.get("status") in ("queued", "running") for job in card_jobs):
            return None
        if _harvest_has_card(workspace_id, harvest_job_id):
            return None
        attempt = len(card_jobs)
    job_id = card_job_id(workspace_id, harvest_job_id, attempt)
    if store.get(job_id) is not None:
        return None
    work_id = uuid5(
        NAMESPACE_URL, f"clue:adcard:{workspace_id}:{harvest_job_id}{_attempt_suffix(attempt)}"
    )
    request: JsonObject = {
        "phase": "card",
        "harvest_job_id": harvest_job_id,
        "brand_kit_id": str(kit["brand_kit_id"]),
        "brand_kit_version": int(kit["brand_kit_version"]),
    }
    envelope = DesignIngestionEnvelope(
        work_id=work_id,
        workspace_id=workspace_id,
        kind="ingestion",
        job_id=job_id,
        ingestion_kind=DesignIngestionKind.AD_ASSETS,
    ).model_dump(mode="json")
    invoker = tools if tools is not None else _default_tools()
    try:
        invoker.invoke(
            "design_ingest_ad_assets",
            {"job_id": job_id, "work_id": str(work_id), "request": request, "envelope": envelope},
            workspace_id=workspace_id,
            actor="agent",
        )
    except Exception:
        if store.get(job_id) is not None:
            # A concurrent caller won the race for the same deterministic job: already offered.
            return None
        raise
    logger.info(
        "ad_assets.card_offered",
        workspace_id=workspace_id,
        job_id=job_id,
        harvest_job_id=harvest_job_id,
        brand_kit_id=request["brand_kit_id"],
    )
    return job_id


def card_offer_hook(workspace_id: str, *, tools: Any = None) -> Callable[[], Any]:
    """The ``run_ingestion_job(on_complete=...)`` callback a finished job hands over."""
    return lambda: offer_card_if_ready(workspace_id, tools=tools)


def _newest_usable_harvest(store: IngestionJobStore) -> Optional[JsonObject]:
    """The newest finished harvest-phase job, if it kept at least one ad."""
    for job in store.list_recent(_RECENT, kinds=("ad_assets",)):
        request = job.get("request") or {}
        if request.get("phase") != "harvest":
            continue
        if job.get("status") not in _FINISHED:
            return None
        outcome = (job.get("evidence") or {}).get("outcome") or {}
        return job if int(outcome.get("creatives_custodied") or 0) > 0 else None
    return None


def _card_jobs(store: IngestionJobStore, harvest_job_id: str) -> list[JsonObject]:
    """Every card job already offered for this harvest, whatever became of it."""
    return [
        job
        for job in store.list_recent(_RECENT, kinds=("ad_assets",))
        if (job.get("request") or {}).get("phase") == "card"
        and (job.get("request") or {}).get("harvest_job_id") == harvest_job_id
    ]


def _harvest_has_card(workspace_id: str, harvest_job_id: str) -> bool:
    from clue_design.ad_assets import ad_dna_card_for_harvest_job
    from lumen_api.design_store import DesignStoreBridge

    async def read(conn: Any) -> Any:
        return await ad_dna_card_for_harvest_job(
            conn, workspace_id=workspace_id, harvest_job_id=harvest_job_id
        )

    return DesignStoreBridge(workspace_id)._run(read) is not None


def _newest_kit(store: IngestionJobStore) -> Optional[JsonObject]:
    """The newest kit-building ingestion that finished with a kit."""
    for job in store.list_recent(_RECENT, kinds=KIT_INGESTION_KINDS):
        if job.get("status") in _FINISHED and job.get("brand_kit_id"):
            return job
    return None


def _default_tools() -> Any:
    from clue_storage import storage_from_settings

    from ..pipeline import _worker_design_tools

    return _worker_design_tools(storage_from_settings())
