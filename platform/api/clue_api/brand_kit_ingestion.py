"""Brand-kit × onboarding slice 2 — the first-time-onboarding website-ingestion trigger.

One narrow seam: when a self-serve-provisioned workspace submits its onboarding website,
enqueue exactly ONE brand-kit website ingestion for it, so the client's Brand-context screen
has a real (``draft``) kit to review instead of an empty page. The kit lands behind the human
approval gate — nothing here approves anything, ever.

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

**Idempotent, and serialized across concurrent replays.** The workspace gets one ingestion,
full stop: the trigger skips when ANY ``design_ingestion_job`` row already exists for it
(kind-agnostic on purpose — a workspace that already has an ingestion of any shape does not
need an auto-fired one). Two concurrent setup POSTs would otherwise both read "no job" and both
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
from typing import Protocol

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

#: Short by design: the onboarding request waits on this, and a slow design API must cost the
#: client seconds, not the request. A timeout is just another fail-soft skip.
DEFAULT_TIMEOUT_S = 5.0

_ADVISORY_LOCK_SQL = text("SELECT pg_try_advisory_xact_lock(hashtextextended(:lock_key, 0))")


def _lock_key(workspace_id: str) -> str:
    return f"brand-kit-ingest:{workspace_id}"


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
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._conn_factory = conn_factory
        self._timeout_s = timeout_s
        self._client_factory = client_factory or (
            lambda: httpx.AsyncClient(timeout=self._timeout_s)
        )

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
            existing = await list_recent(conn, workspace_id=workspace_id, limit=1)
            if existing:
                log.info(
                    "brand_kit_ingestion.already_ingested",
                    workspace_id=workspace_id,
                    job_id=str(existing[0].get("job_id", "")),
                )
                return None
            job_id = await self._enqueue(workspace_id=workspace_id, website=website)
            log.info(
                "brand_kit_ingestion.enqueued",
                workspace_id=workspace_id,
                job_id=job_id,
            )
            return job_id

    async def _enqueue(self, *, workspace_id: str, website: str) -> str | None:
        async with self._client_factory() as client:
            response = await client.post(
                f"{self._base_url}{INGEST_WEBSITE_PATH}",
                json={"url": website},
                headers={WORKSPACE_HEADER: workspace_id},
            )
            response.raise_for_status()
            body = response.json()
        job = body.get("job") if isinstance(body, dict) else None
        if not isinstance(job, dict):
            return None
        job_id = job.get("job_id")
        return str(job_id) if job_id else None


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
    return BrandKitWebsiteIngestion(base_url=base_url, conn_factory=conn_factory)


__all__ = [
    "INGEST_WEBSITE_PATH",
    "WORKSPACE_HEADER",
    "BrandKitIngestionTrigger",
    "BrandKitWebsiteIngestion",
    "build_brand_kit_ingestion_trigger",
]
