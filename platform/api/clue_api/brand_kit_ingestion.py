"""Brand-kit × onboarding slice 2 — the first-time-onboarding website-ingestion trigger.

One narrow seam: when a self-serve-provisioned workspace submits its onboarding website,
enqueue exactly ONE brand-kit website ingestion for it, so the client's Brand-context screen
has a real (``draft``) kit to review instead of an empty page. The kit lands behind the human
approval gate — nothing here approves anything, ever.

Since 2026-09-28 the same seam also offers ONE ad-assets harvest (``POST
/brand-ad-assets/onboard``, ``phase=harvest``) for the company's own recent static LinkedIn ads,
in parallel with the website ingestion. It needs no kit — the design side distils the ad-DNA card
later, once both the harvest and a kit exist — and it is fail-soft on its own: an ad outage never
costs the kit, and a kit outage never costs the ads. Each kind is offered once per workspace.

Three rulings shape the implementation, and none of them is re-decidable here:

**The enqueue is a server-side HTTP call to the design API**, never a platform-side write of
the ``design_ingestion_job`` row. The design API's ``POST /brand-kits/ingest/website`` is the
only sanctioned door: it runs the SSRF guard over the submitted URL and then writes the job row
*and* its ``design_job`` fleet task in ONE transaction inside the design toolbelt (the D6
no-bypass pattern). A platform-side INSERT would fork that pipeline and skip the guard. The
call is made from the platform web process; ``lumen_api`` is deliberately NOT imported here
(that is the whole point of using HTTP). The ``clue_design`` DAL import below is the sanctioned
one — a read, through the platform's own port onto the design tables.

**Fail-soft.** A design API that is down, slow, or refuses the URL must not fail or delay the
onboarding request that triggered it: :meth:`BrandKitWebsiteIngestion.ensure` never raises and
never returns an error to its caller — it logs and yields. Because ``POST /stage0/setup`` is
replayed by the setting-up screen while onboarding runs, and this trigger re-attempts whenever
no job row exists, a transient failure self-heals on the next replay.

**Idempotent, and serialized across concurrent replays.** The workspace gets one kit ingestion,
full stop: the trigger skips when a kit-building ``design_ingestion_job`` row (any of
``KIT_INGESTION_KINDS``) already exists for it — a workspace that already has an ingestion of any
kit-building shape does not need an auto-fired one. The ad harvest is checked the same way against
``ad_assets`` rows only. Two concurrent setup POSTs would otherwise both read "no job" and both
enqueue, so the check and the enqueue run under a per-workspace Postgres advisory transaction
lock. The lock is a ``try`` acquire: the loser does not queue up behind a live enqueue, it
simply declines — the winner is already doing the one thing that needed doing.

The advisory lock is held across the HTTP call, which is the one place this module holds a
pooled connection over network I/O. That is deliberate and bounded: the design API's own
transaction must COMMIT the job row before a concurrent replay is allowed to look for it, the
timeout is a few seconds, and this fires at most once per onboarding.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Protocol
from urllib.parse import urlsplit

import httpx
from sqlalchemy import text

from clue_config import Settings
from clue_db import ConnFactory
from clue_design.ingestion import list_recent
from clue_obs import get_logger

log = get_logger("clue_api.brand_kit_ingestion")

#: The design API's guarded website-ingestion route (``lumen_api.main``).
INGEST_WEBSITE_PATH = "/brand-kits/ingest/website"

#: The design API's strict tenant seam — it 401s without this header and has no fallback.
WORKSPACE_HEADER = "X-Workspace-Id"

#: The design API's flag-gated ad-assets route; onboarding offers its harvest phase.
ONBOARD_AD_ASSETS_PATH = "/brand-ad-assets/onboard"
#: Short by design: the onboarding request waits on this, and a slow design API must cost the
#: client seconds, not the request. A timeout is just another fail-soft skip.
DEFAULT_TIMEOUT_S = 5.0

#: The ingestion kinds that build a brand kit. An ``ad_assets`` job builds none, so it neither
#: stands in for the website ingestion nor shows on the "Creating brand kit" checklist row.
KIT_INGESTION_KINDS = ("website", "pdf", "asset_upload")
AD_INGESTION_KINDS = ("ad_assets",)

_ADVISORY_LOCK_SQL = text("SELECT pg_try_advisory_xact_lock(hashtextextended(:lock_key, 0))")


def _lock_key(workspace_id: str) -> str:
    return f"brand-kit-ingest:{workspace_id}"


@dataclass(frozen=True)
class AdHarvestConfig:
    """How much of the company's own ad library onboarding asks for."""

    max_creatives: int
    max_pages: int


def company_domain(website: str) -> str | None:
    """The bare host the ad library is addressed by: no scheme, port, path or ``www.``."""
    raw = website.strip()
    if not raw:
        return None
    host = urlsplit(raw if "://" in raw else f"https://{raw}").hostname or ""
    host = host.lower().removeprefix("www.")
    return host or None


class BrandKitIngestionTrigger(Protocol):
    """What ``POST /stage0/setup`` needs: "make sure this workspace has an ingestion"."""

    async def ensure(self, *, workspace_id: str, website: str) -> str | None:
        """Enqueue the workspace's one website ingestion if it has none. Never raises."""


class BrandKitWebsiteIngestion:
    """The production trigger: advisory lock → existence read → design-API enqueue.

    ``client_factory`` exists so tests can hand in an :class:`httpx.AsyncClient` built on a
    ``MockTransport`` and assert the exact URL, header, and body without a network call. The
    default mints a per-call client: this fires once per onboarding, so connection pooling would
    buy nothing and a long-lived client would need a lifespan to own it.
    """

    def __init__(
        self,
        *,
        base_url: str,
        conn_factory: ConnFactory,
        timeout_s: float = DEFAULT_TIMEOUT_S,
        client_factory: Callable[[], httpx.AsyncClient] | None = None,
        ad_harvest: AdHarvestConfig | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._conn_factory = conn_factory
        self._timeout_s = timeout_s
        self._client_factory = client_factory or (
            lambda: httpx.AsyncClient(timeout=self._timeout_s)
        )
        #: ``None`` = onboarding offers no ad harvest (the pre-2026-09-28 behaviour).
        self._ad_harvest = ad_harvest

    async def ensure(self, *, workspace_id: str, website: str) -> str | None:
        """Return the enqueued job id, or ``None`` when nothing was enqueued.

        ``None`` covers every non-enqueue outcome on purpose — already ingested, a concurrent
        replay holding the lock, a refused URL, a design API that is down. The caller treats
        them identically (continue with onboarding); the log line says which one it was.
        """
        try:
            return await self._ensure(workspace_id=workspace_id, website=website)
        except Exception:  # noqa: BLE001 — fail-soft is this seam's contract (module docstring)
            log.exception("brand_kit_ingestion.enqueue_failed", workspace_id=workspace_id)
            return None

    async def _ensure(self, *, workspace_id: str, website: str) -> str | None:
        async with self._conn_factory() as conn:
            acquired = bool(
                (
                    await conn.execute(_ADVISORY_LOCK_SQL, {"lock_key": _lock_key(workspace_id)})
                ).scalar_one()
            )
            if not acquired:
                # A concurrent setup replay owns the enqueue for this workspace. Declining is
                # the correct answer, not a failure: the holder is enqueueing right now.
                log.info("brand_kit_ingestion.enqueue_contended", workspace_id=workspace_id)
                return None
            job_id: str | None = None
            existing = await list_recent(
                conn, workspace_id=workspace_id, limit=1, kinds=KIT_INGESTION_KINDS
            )
            if existing:
                log.info(
                    "brand_kit_ingestion.already_ingested",
                    workspace_id=workspace_id,
                    job_id=str(existing[0].get("job_id", "")),
                )
            else:
                try:
                    job_id = await self._post(
                        workspace_id=workspace_id, path=INGEST_WEBSITE_PATH, body={"url": website}
                    )
                    log.info(
                        "brand_kit_ingestion.enqueued",
                        workspace_id=workspace_id,
                        job_id=job_id,
                    )
                except Exception:  # noqa: BLE001 — fail-soft; the ad offer below still runs
                    log.exception("brand_kit_ingestion.enqueue_failed", workspace_id=workspace_id)
            if self._ad_harvest is not None:
                await self._ensure_ad_harvest(conn, workspace_id=workspace_id, website=website)
            return job_id

    async def _ensure_ad_harvest(self, conn: Any, *, workspace_id: str, website: str) -> None:
        """Offer the workspace's one ad harvest. Fail-soft on its own: never touches the kit."""
        assert self._ad_harvest is not None
        try:
            existing = await list_recent(
                conn, workspace_id=workspace_id, limit=1, kinds=AD_INGESTION_KINDS
            )
            if existing:
                log.info("ad_harvest.already_offered", workspace_id=workspace_id)
                return
            domain = company_domain(website)
            if domain is None:
                log.info("ad_harvest.no_domain", workspace_id=workspace_id)
                return
            job_id = await self._post(
                workspace_id=workspace_id,
                path=ONBOARD_AD_ASSETS_PATH,
                body={
                    "phase": "harvest",
                    "company_domain": domain,
                    "max_creatives": self._ad_harvest.max_creatives,
                    "max_pages": self._ad_harvest.max_pages,
                },
            )
            log.info("ad_harvest.enqueued", workspace_id=workspace_id, job_id=job_id)
        except Exception:  # noqa: BLE001 — an ad outage must never cost the kit or onboarding
            log.exception("ad_harvest.enqueue_failed", workspace_id=workspace_id)

    async def _post(self, *, workspace_id: str, path: str, body: dict[str, Any]) -> str | None:
        async with self._client_factory() as client:
            response = await client.post(
                f"{self._base_url}{path}",
                json=body,
                headers={WORKSPACE_HEADER: workspace_id},
            )
            response.raise_for_status()
            payload = response.json()
        job = payload.get("job") if isinstance(payload, dict) else None
        if not isinstance(job, dict):
            return None
        job_id = job.get("job_id")
        return str(job_id) if job_id else None


async def read_newest_ingestion_job(
    conn_factory: ConnFactory, *, workspace_id: str
) -> tuple[str, str] | None:
    """The workspace's newest brand-kit ingestion job as ``(job_id, status)``, or None.

    One workspace-keyed read through the sanctioned ``clue_design`` DAL port — the same port
    this module's trigger uses for its idempotency check. ``list_recent`` is workspace-scoped
    and ordered newest-first, and ``limit=1`` is all a checklist row needs.

    It lives here rather than in a router because BOTH setting-up surfaces need it: the legacy
    ``GET /stage0/setup/current`` and the new ``GET /onboarding/current``. Nothing is derived —
    the ``design_ingestion_status`` enum is served as stored and each surface maps it onto its
    own row vocabulary.
    """
    async with conn_factory() as conn:
        jobs = await list_recent(
            conn, workspace_id=workspace_id, limit=1, kinds=KIT_INGESTION_KINDS
        )
    if not jobs:
        return None
    job = jobs[0]
    return str(job["job_id"]), str(job["status"])


def build_brand_kit_ingestion_trigger(
    *, settings: Settings, conn_factory: ConnFactory
) -> BrandKitWebsiteIngestion | None:
    """The composition-root builder: ``None`` when no design API base URL is configured.

    Config-off is a deployment posture, not an error — a platform deployed without the design
    service simply never fires the trigger, and every other part of onboarding is unaffected.
    """
    base_url = (settings.design_api_base_url or "").strip()
    if not base_url:
        log.info("brand_kit_ingestion.unconfigured")
        return None
    ad_harvest = (
        AdHarvestConfig(
            max_creatives=settings.brand_ad_assets_auto_max_creatives,
            max_pages=settings.brand_ad_assets_auto_max_pages,
        )
        if settings.brand_ad_assets_auto_onboard
        else None
    )
    return BrandKitWebsiteIngestion(
        base_url=base_url, conn_factory=conn_factory, ad_harvest=ad_harvest
    )


__all__ = [
    "AD_INGESTION_KINDS",
    "INGEST_WEBSITE_PATH",
    "KIT_INGESTION_KINDS",
    "ONBOARD_AD_ASSETS_PATH",
    "WORKSPACE_HEADER",
    "AdHarvestConfig",
    "BrandKitIngestionTrigger",
    "BrandKitWebsiteIngestion",
    "build_brand_kit_ingestion_trigger",
    "company_domain",
    "read_newest_ingestion_job",
]
