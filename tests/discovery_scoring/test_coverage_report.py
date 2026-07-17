"""M6.5 (ENG-150) — the durable coverage read path + the M6.4 checkpoint integration, live Postgres.

End to end: the discovery telemetry (``source_yield``) + the source registry (``source_manifest``)
are read back by ``run_id`` into a :class:`CoverageReport` with no in-memory run state — the
"queryable by run_id" seam — and the TIER_CHECKPOINT phase surfaces that report in its review
payload (the M6.4 consumption hook). One test per read-path concern + the checkpoint integration.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_core import EntityScope, Modality, RunId, SourceManifest, new_run_id
from clue_research.discovery_scoring import (
    CoverageConfidence,
    StoppingReason,
    TierCheckpointPhaseHandler,
    coverage_report,
)
from clue_research.discovery_scoring.phases import _discovery_run_id
from clue_research.sources import RegistrySourceManifest, register_source
from clue_research.sources.source_yield import record_source_yield

from .conftest import icp_spec, rollback_conn, run_async
from .test_tier_checkpoint_phase import _ctx, _seed_and_score

pytestmark = pytest.mark.usefixtures("require_discovery_db")


def _tf(conn: AsyncConnection) -> Callable[[], AbstractAsyncContextManager[AsyncConnection]]:
    @asynccontextmanager
    async def _session() -> AsyncIterator[AsyncConnection]:
        yield conn

    return _session


async def _register_account_source(
    conn: AsyncConnection,
    key: str,
    *,
    scope: EntityScope = EntityScope.ACCOUNT,
    tier: int = 2,
    geo: tuple[str, ...] = (),
) -> None:
    """Register one account-scope (or contact-scope, for the exclusion test) registry channel."""
    await register_source(
        conn,
        RegistrySourceManifest(
            manifest=SourceManifest(
                source_key=key,
                modality=Modality.STRUCTURED,
                entity_scope=scope,
                yields=("account",) if scope is not EntityScope.CONTACT else ("contact",),
                tier=tier,
                geo_coverage=geo,
            )
        ),
    )


async def _write_discovery_yield(
    conn: AsyncConnection,
    *,
    run_id: RunId,
    source_key: str,
    records_returned: int,
    new_candidates: int,
    stopping_reason: StoppingReason = StoppingReason.MARGINAL_YIELD,
    admitted: int = 0,
    needs_review: int = 0,
    rejected: int = 0,
    cost_cents: Decimal = Decimal(0),
    workspace_id: str = "acme",
    icp_key: str = "default",
) -> None:
    """Write one per-channel discovery telemetry row exactly as the DISCOVERY phase does (the
    run-level facts — stopping reason + admitted-vs-seen — denormalised onto the row)."""
    await record_source_yield(
        conn,
        workspace_id=workspace_id,
        icp_key=icp_key,
        icp_version=1,
        source_key=source_key,
        run_id=run_id,
        cost_cents=cost_cents,
        disposition={
            "kind": "discovery",
            "records_returned": records_returned,
            "new_candidates": new_candidates,
            "queries_issued": 1,
            "errors": 0,
            "stopping_reason": stopping_reason.value,
            "admitted": admitted,
            "needs_review": needs_review,
            "rejected": rejected,
        },
    )


# --- AC: queryable by run_id; universe − searched; account-scope only --------
def test_coverage_report_reads_telemetry_and_registry_universe() -> None:
    async def _run() -> None:
        async with rollback_conn() as conn:
            run_id = new_run_id()
            await _register_account_source(conn, "exa")
            await _register_account_source(conn, "apollo")  # account-scope, not searched
            await _register_account_source(conn, "linkedin", scope=EntityScope.CONTACT)  # excluded
            await _write_discovery_yield(
                conn,
                run_id=run_id,
                source_key="exa",
                records_returned=100,
                new_candidates=20,
                stopping_reason=StoppingReason.MARGINAL_YIELD,
                admitted=15,
                needs_review=2,
                rejected=3,
            )

            report = await coverage_report(
                conn, run_id=run_id, spec=icp_spec({"channels": ["exa"]})
            )
            assert report is not None
            assert report.channels_searched == ("exa",)
            not_searched = {c.source_key for c in report.channels_not_searched}
            assert not_searched == {"apollo"}  # account-scope, unsearched — contact excluded
            assert report.stopping_reason is StoppingReason.MARGINAL_YIELD
            assert report.total_records == 100 and report.distinct_candidates == 20
            assert (report.admitted, report.needs_review, report.rejected) == (15, 2, 3)
            assert report.coverage_estimate_band.confidence is not CoverageConfidence.NONE

    run_async(_run())


def test_coverage_report_is_none_without_telemetry() -> None:
    async def _run() -> None:
        async with rollback_conn() as conn:
            await _register_account_source(conn, "exa")
            report = await coverage_report(conn, run_id=new_run_id())
            assert report is None  # nothing to report for an unknown run

    run_async(_run())


def test_coverage_report_takes_latest_row_per_source_on_replay() -> None:
    async def _run() -> None:
        async with rollback_conn() as conn:
            run_id = new_run_id()
            # a M7 replay appends a SECOND identical discovery row for the same (run_id, source_key)
            for _ in range(2):
                await _write_discovery_yield(
                    conn, run_id=run_id, source_key="exa", records_returned=50, new_candidates=50
                )
            report = await coverage_report(conn, run_id=run_id)
            assert report is not None
            assert report.total_records == 50  # latest measurement, NOT the summed 100
            assert len(report.per_channel_new_candidate_curve) == 1

    run_async(_run())


def test_coverage_report_orders_curve_by_planned_channels() -> None:
    async def _run() -> None:
        async with rollback_conn() as conn:
            run_id = new_run_id()
            await _write_discovery_yield(
                conn, run_id=run_id, source_key="exa", records_returned=40, new_candidates=10
            )
            await _write_discovery_yield(
                conn, run_id=run_id, source_key="apollo", records_returned=60, new_candidates=30
            )
            # planned order puts apollo first — the curve follows search priority, not source_key
            report = await coverage_report(
                conn, run_id=run_id, spec=icp_spec({"channels": ["apollo", "exa"]})
            )
            assert report is not None
            assert tuple(p.source_key for p in report.per_channel_new_candidate_curve) == (
                "apollo",
                "exa",
            )

    run_async(_run())


def test_coverage_report_reads_target_geos_from_strategy() -> None:
    async def _run() -> None:
        async with rollback_conn() as conn:
            run_id = new_run_id()
            await _register_account_source(conn, "exa", geo=("US",))
            await _register_account_source(conn, "de_dir", geo=("DE",))
            await _write_discovery_yield(
                conn, run_id=run_id, source_key="exa", records_returned=80, new_candidates=20
            )
            report = await coverage_report(
                conn,
                run_id=run_id,
                spec=icp_spec({"channels": ["exa"], "icp_filters": {"regions": ["US", "DE"]}}),
            )
            assert report is not None
            # the searched channel covers US; DE is an uncovered target geo + de_dir is an
            # unsearched DE channel the client could add
            assert report.geo_gaps == ("DE",)
            assert "de_dir" in {c.source_key for c in report.channels_not_searched}

    run_async(_run())


# --- AC: consumed by the M6.4 checkpoint payload ----------------------------
def test_checkpoint_payload_includes_coverage() -> None:
    async def _run() -> None:
        async with rollback_conn() as conn:
            campaign_run_id = await _seed_and_score(conn)
            disc_run = _discovery_run_id(_ctx(campaign_run_id))
            await _register_account_source(conn, "exa")
            await _register_account_source(conn, "apollo")  # an unsearched gap
            await _write_discovery_yield(
                conn,
                run_id=disc_run,
                source_key="exa",
                records_returned=200,
                new_candidates=20,
                stopping_reason=StoppingReason.MARGINAL_YIELD,
                admitted=3,
            )

            handler = TierCheckpointPhaseHandler(session_factory=_tf(conn))
            result = await handler.run(_ctx(campaign_run_id))

            coverage = result.payload["coverage"]
            assert isinstance(coverage, dict)
            assert coverage["channels_searched"] == ["exa"]
            not_searched = {c["source_key"] for c in coverage["channels_not_searched"]}
            assert "apollo" in not_searched
            assert coverage["stopping_reason"] == "marginal_yield"
            # the review payload carries the same coverage object (the durable M6.4 hook)
            review = result.payload["review"]
            assert isinstance(review, dict)
            assert review["coverage"] == coverage

    run_async(_run())


def test_checkpoint_coverage_is_none_without_discovery_telemetry() -> None:
    async def _run() -> None:
        async with rollback_conn() as conn:
            # scored campaign but NO discovery telemetry written → coverage stays unpopulated, and
            # the checkpoint never fails on its absence (the placeholder is simply None).
            campaign_run_id = await _seed_and_score(conn)
            handler = TierCheckpointPhaseHandler(session_factory=_tf(conn))
            result = await handler.run(_ctx(campaign_run_id))
            assert result.payload["coverage"] is None

    run_async(_run())
