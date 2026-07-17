"""M8.4 facet sub-worker gating (DB-gated) — tier-driven, via the recursion knob.

Facet sub-workers (the level-2 fan-out) are gated by ``config.RecursionPolicy.caps_for(tier)``, not
by a per-call hint: a low-tier contact gets single-level depth even with a rich facet, top tier may
fan out, and a sub-worker (depth≥1) never spawns more.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncConnection

from clue_config import RecursionPolicy
from clue_core import AspectContext
from clue_research.profiling.contact import ContactProfileAspectWorker
from clue_research.profiling.fields import FACET_STATED_INTERESTS
from clue_research.sources import bind_resolver

from ..conftest import (
    FakeFacetResolver,
    insert_test_account,
    insert_test_contact,
    rollback_conn,
    run_async,
    seed_packs,
)

_RUN = UUID("99999999-9999-9999-9999-999999999999")
_TENANT = "acme"
_FACET_SOURCE = "exa_deep"
# A rich facet (a list with >= facet_subworker_min_values (3) items).
_RICH = ["robotics", "running", "chess"]


def _rich_resolver() -> FakeFacetResolver:
    return FakeFacetResolver(
        tier=4,
        extractions=[
            {
                "value_json": _RICH,
                "evidence_span": f"Jane CFO: {', '.join(_RICH)}.",
                "source_url": "https://linkedin.com/in/jane-cfo",
                "confidence": 0.95,
            }
        ],
    )


async def _run_worker(tier: str, *, depth: int = 0):  # type: ignore[no-untyped-def]
    """Run the contact worker for one contact at ``tier``/``depth`` and return its WorkerResult."""
    async with rollback_conn() as conn:
        await seed_packs(conn)
        account = await insert_test_account(conn)
        contact = await insert_test_contact(conn, account)

        @asynccontextmanager
        async def session_factory() -> AsyncIterator[AsyncConnection]:
            yield conn

        worker = ContactProfileAspectWorker(session_factory=session_factory)
        ctx = AspectContext(
            entity_id=contact.id,
            campaign_run_id="aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
            run_id=_RUN,
            tier=tier,
            aspect="contact.facet",
            field_keys=(FACET_STATED_INTERESTS,),
            depth=depth,
            params={
                "account_entity_id": str(account.id),
                "workspace_id": _TENANT,
                "icp_key": "default",
                "icp_version": 1,
            },
        )
        return await worker.research(ctx)


def test_top_tier_requests_facet_subworker(require_profiling_db: None) -> None:
    async def scenario() -> None:
        bind_resolver(_FACET_SOURCE, _rich_resolver())
        result = await _run_worker("top")
        requests = result.detail["facet_requests"]
        assert isinstance(requests, list) and len(requests) == 1
        assert requests[0]["aspect"] == FACET_STATED_INTERESTS
        assert requests[0]["depth"] == 1  # a level-1 sub-worker
        # never exceeds the tier's cap.
        assert len(requests) <= RecursionPolicy().caps_for("top").max_facet_workers_per_aspect

    run_async(scenario())


def test_low_tier_never_requests_even_with_rich_facet(require_profiling_db: None) -> None:
    async def scenario() -> None:
        bind_resolver(_FACET_SOURCE, _rich_resolver())
        # "low" is unlisted → default_caps.max_facet_workers_per_aspect == 0 → single-level depth.
        assert RecursionPolicy().caps_for("low").max_facet_workers_per_aspect == 0
        result = await _run_worker("low")
        assert result.detail["facet_requests"] == []

    run_async(scenario())


def test_subworker_depth_never_spawns_more(require_profiling_db: None) -> None:
    async def scenario() -> None:
        bind_resolver(_FACET_SOURCE, _rich_resolver())
        # Even at top tier, a level-1 worker (depth=1) requests no further sub-workers.
        result = await _run_worker("top", depth=1)
        assert result.detail["facet_requests"] == []

    run_async(scenario())
