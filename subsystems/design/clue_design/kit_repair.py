"""The brand-kit half of a workspace repair plan (spec 2026-10-25 §3.4 B). Read-only.

After an outage a workspace's brand kit can be missing three things, each healed by one step of
the ``kit_repair`` job the platform offers:

- **descriptions**: AI analyses that ``failed``, rows that were never described (``stale`` with no
  text), and kit assets with no description row at all;
- **a kit version carrying them**: descriptions are frozen into the kit at publish, so a kit
  whose entries lack descriptions that are now ready needs republishing;
- **the ad-DNA card**: a usable harvest with no card and no card job open.

``unsupported`` assets are listed but never re-run: their file type cannot be described.

When a kit-building ingestion or a ``kit_repair`` job is still queued or running, nothing is
planned: the work in flight may heal it, and a plan made under it would race it. When there is no
kit at all and the newest capture failed, the only plan is to capture the website again.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_design import ad_assets, brand, ingestion
from clue_design.errors import DesignNotFoundError

__all__ = ["KIT_BUILDING_KINDS", "KitRepairPlan", "plan_kit_repair"]

KIT_BUILDING_KINDS = ("website", "pdf", "asset_upload")
_OPEN = ("queued", "running")
_FINISHED = ("succeeded", "succeeded_with_gaps")
_RECENT = 50


@dataclass(frozen=True)
class KitRepairPlan:
    capture_website: str | None = None
    describe: tuple[str, ...] = ()
    unsupported: tuple[str, ...] = ()
    republish_brand_kit_id: str | None = None
    offer_card_for_harvest: str | None = None
    in_flight: tuple[str, ...] = ()

    @property
    def is_empty(self) -> bool:
        """Nothing to offer (``unsupported`` and ``in_flight`` are reported, never run)."""
        return not (
            self.capture_website
            or self.describe
            or self.republish_brand_kit_id
            or self.offer_card_for_harvest
        )

    def as_json(self) -> dict[str, Any]:
        return {
            "capture_website": self.capture_website,
            "describe": list(self.describe),
            "unsupported": list(self.unsupported),
            "republish_brand_kit_id": self.republish_brand_kit_id,
            "offer_card_for_harvest": self.offer_card_for_harvest,
            "in_flight": list(self.in_flight),
        }


async def plan_kit_repair(conn: AsyncConnection, *, workspace_id: str) -> KitRepairPlan:
    jobs = await ingestion.list_recent(conn, workspace_id=workspace_id, limit=_RECENT)
    kit_jobs = [job for job in jobs if job["kind"] in KIT_BUILDING_KINDS]
    if kit_jobs and kit_jobs[0]["status"] in _OPEN:
        return KitRepairPlan(
            in_flight=(f"a {kit_jobs[0]['kind']} ingestion is {kit_jobs[0]['status']}",)
        )
    open_repair = next(
        (job for job in jobs if job["kind"] == "kit_repair" and job["status"] in _OPEN), None
    )
    if open_repair is not None:
        return KitRepairPlan(
            in_flight=(f"kit repair {open_repair['job_id']} is {open_repair['status']}",)
        )

    kit_job = next(
        (job for job in kit_jobs if job["status"] in _FINISHED and job.get("brand_kit_id")), None
    )
    if kit_job is None:
        newest = kit_jobs[0] if kit_jobs else None
        url = ((newest or {}).get("request") or {}).get("url")
        if newest is not None and newest["status"] == "failed" and url:
            return KitRepairPlan(capture_website=str(url))
        return KitRepairPlan()

    kit_id = str(kit_job["brand_kit_id"])
    try:
        kit = (await brand.get_brand_kit(conn, workspace_id=workspace_id, brand_kit_id=kit_id))[
            "brand_kit"
        ]
    except DesignNotFoundError:
        return KitRepairPlan()
    entries = _kit_entries(kit)
    rows = await _description_rows(conn, workspace_id)

    describe: set[str] = set()
    unsupported: set[str] = set()
    queued = 0
    for asset_id, row in rows.items():
        status, has_text = row
        if status == "failed" or (status == "stale" and not has_text):
            describe.add(asset_id)
        elif status == "unsupported":
            unsupported.add(asset_id)
        elif status in ("queued", "analyzing"):
            queued += 1
    describe.update(asset_id for asset_id in entries if asset_id not in rows)

    unstamped = any(
        rows.get(asset_id, ("", False))[0] == "ready" and not entry.get("description")
        for asset_id, kit_entries in entries.items()
        for entry in kit_entries
    )
    republish = kit_id if (describe or unstamped) else None

    in_flight = (f"{queued} descriptions are already queued or analysing",) if queued else ()
    harvest, card_note = await _card_harvest(conn, workspace_id, jobs)
    return KitRepairPlan(
        describe=tuple(sorted(describe)),
        unsupported=tuple(sorted(unsupported)),
        republish_brand_kit_id=republish,
        offer_card_for_harvest=harvest,
        in_flight=in_flight + card_note,
    )


def _kit_entries(kit: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    """``asset_id -> [kit entry, ...]`` — the same slots ``describe_kit_assets`` stamps."""
    assets = kit.get("assets") or {}
    entries: dict[str, list[dict[str, Any]]] = {}
    for logo in (assets.get("logos") or {}).values():
        if isinstance(logo, dict):
            variants = [v for v in (logo.get("variants") or []) if isinstance(v, dict)]
            asset_id = str((variants[0] if variants else {}).get("asset_id") or "")
            if asset_id:
                entries.setdefault(asset_id, []).append(logo)
    for image in (assets.get("images") or {}).values():
        if isinstance(image, dict) and image.get("asset_id"):
            entries.setdefault(str(image["asset_id"]), []).append(image)
    return entries


async def _description_rows(
    conn: AsyncConnection, workspace_id: str
) -> dict[str, tuple[str, bool]]:
    rows = await conn.execute(
        text(
            "SELECT asset_id, analysis_status,"
            " (coalesce(title, '') <> '' OR coalesce(description, '') <> '') AS has_text"
            " FROM design_asset_description WHERE workspace_id = :w"
        ),
        {"w": workspace_id},
    )
    return {row.asset_id: (str(row.analysis_status), bool(row.has_text)) for row in rows}


async def _card_harvest(
    conn: AsyncConnection, workspace_id: str, jobs: list[dict[str, Any]]
) -> tuple[str | None, tuple[str, ...]]:
    """The newest usable harvest when it has no card and no card job open."""
    harvest = next(
        (
            job
            for job in jobs
            if job["kind"] == "ad_assets" and (job.get("request") or {}).get("phase") == "harvest"
        ),
        None,
    )
    if harvest is None or harvest["status"] not in _FINISHED:
        return None, ()
    outcome = (harvest.get("evidence") or {}).get("outcome") or {}
    if int(outcome.get("creatives_custodied") or 0) <= 0:
        return None, ()
    harvest_id = str(harvest["job_id"])
    open_card = any(
        job["kind"] == "ad_assets"
        and (job.get("request") or {}).get("phase") == "card"
        and (job.get("request") or {}).get("harvest_job_id") == harvest_id
        and job["status"] in _OPEN
        for job in jobs
    )
    if open_card:
        return None, ("the ad-DNA card job is already queued or running",)
    card = await ad_assets.ad_dna_card_for_harvest_job(
        conn, workspace_id=workspace_id, harvest_job_id=harvest_id
    )
    return (None, ()) if card is not None else (harvest_id, ())
