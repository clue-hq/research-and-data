"""M13.4 acceptance — the DB-backed observability paths (Postgres).

Covers the spec §M13.4 criteria that need real Postgres: per-source yield equals what M13.3 consumes
(the single shared ``get_source_yield`` materialization); the ``claims_for_runs`` campaign scan the
verification-health reader is built on; the ``cost_estimate`` snapshot the ``pre_run_estimate``
panel
writes (and its named CHECKs); and the no-domain-mutation guarantee (a read call writes nothing into
the claim/campaign-run write path). These ``pytest.skip`` without a reachable DB.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from clue_core import (
    Estimate,
    ExtractionMethod,
    ResearchMode,
    account_claim,
    new_entity_id,
    new_project_run_id,
    new_run_id,
)
from clue_research.claimstore import ALL_WORKSPACES, claims_for_runs, insert_claim
from clue_research.review import (
    InMemoryCampaignStateReader,
    InMemoryCostBurnDownReader,
    InMemoryCoverageReportReader,
    InMemoryPreRunEstimator,
    InMemoryVerificationHealthReader,
    ObservabilitySurface,
)
from clue_research.sources import get_source_yield, record_source_yield

from .conftest import rollback_conn, run_async

pytestmark = pytest.mark.usefixtures("require_review_db")

_CLIENT = "acme"
_ICP = "seg1"

_FIXED_ESTIMATE = Estimate(
    discovered_count=120,
    projected_deep_count=24,
    estimated_cost_cents=Decimal("60000"),
    cost_per_account_cents=Decimal("2500"),
)


def _surface() -> ObservabilitySurface:
    """A surface whose cross-package readers are inert fakes — the DB tests exercise only the
    in-boundary paths (``source_yield`` over ``get_source_yield``; ``pre_run_estimate`` over a fixed
    estimate + the ``cost_estimate`` write)."""
    return ObservabilitySurface(
        campaign_reader=InMemoryCampaignStateReader(),
        burndown_reader=InMemoryCostBurnDownReader(),
        estimator=InMemoryPreRunEstimator(lambda *_: _FIXED_ESTIMATE),
        health_reader=InMemoryVerificationHealthReader(),
        coverage_reader=InMemoryCoverageReportReader(),
    )


def _account_claim(entity_id, run_id):  # type: ignore[no-untyped-def]
    return account_claim(
        entity_id=entity_id,
        field_key="account.headcount",
        value_json=1000,
        source_tier=2,
        extraction_method=ExtractionMethod.API,
        confidence=0.9,
        run_id=run_id,
        research_mode=ResearchMode.ACCOUNT_PROFILING,
        source_url="https://example.com/api",
    )


def test_source_yield_equals_get_source_yield() -> None:
    """AC: ``source_yield`` returns the same numbers M13.3 consumes (one shared materialization)."""

    async def _run() -> None:
        async with rollback_conn() as conn:
            await record_source_yield(
                conn,
                workspace_id=_CLIENT,
                icp_key=_ICP,
                source_key="arxiv",
                claims_total=10,
                claims_verified=8,
                fields_filled=3,
                cost_cents=Decimal(5),
            )
            await record_source_yield(
                conn,
                workspace_id=_CLIENT,
                icp_key=_ICP,
                source_key="builtwith",
                claims_total=4,
                claims_verified=4,
                fields_filled=2,
                cost_cents=Decimal(2),
            )
            surface = _surface()
            via_surface = await surface.source_yield(conn, workspace_id=_CLIENT, icp_key=_ICP)
            via_helper = await get_source_yield(conn, workspace_id=_CLIENT, icp_key=_ICP)
            # the spec's explicit "a test asserts equality" — same helper, so byte-for-byte equal.
            assert list(via_surface) == list(via_helper)
            assert {s.source_key for s in via_surface} == {"arxiv", "builtwith"}

    run_async(_run())


def test_claims_for_runs_scopes_by_run_id() -> None:
    """The campaign-scoped claim scan the verification-health reader is built on: claims for a set
    of
    account ``run_id``s, and only those."""

    async def _run() -> None:
        async with rollback_conn() as conn:
            run_a, run_b, run_c = new_run_id(), new_run_id(), new_run_id()
            e1, e2, e3 = new_entity_id(), new_entity_id(), new_entity_id()
            await insert_claim(conn, _account_claim(e1, run_a), validate_field=False)
            await insert_claim(conn, _account_claim(e2, run_b), validate_field=False)
            await insert_claim(conn, _account_claim(e3, run_c), validate_field=False)

            scoped = await claims_for_runs(conn, [run_a, run_b], scope=ALL_WORKSPACES)
            got_runs = {c.run_id for c in scoped}
            assert got_runs == {run_a, run_b}  # run_c excluded
            assert len(scoped) == 2

            # empty run set → empty (no query, no error).
            assert await claims_for_runs(conn, [], scope=ALL_WORKSPACES) == []

    run_async(_run())


def test_pre_run_estimate_writes_cost_estimate_snapshot() -> None:
    """AC: the pre-run estimate snapshot is recorded (the one materialization the surface writes); a
    ``conn``-less call is side-effect free."""

    async def _run() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            run = new_project_run_id()
            surface = _surface()

            # conn=None → pure read, writes nothing.
            await surface.pre_run_estimate(
                project_run_id=run, workspace_id=_CLIENT, discovered_count=120, conn=None
            )
            before = (
                await conn.execute(
                    text("SELECT count(*) FROM cost_estimate WHERE project_run_id = :r"),
                    {"r": run},
                )
            ).scalar_one()
            assert before == 0

            # conn supplied → one snapshot appended with the projected figures.
            result = await surface.pre_run_estimate(
                project_run_id=run,
                workspace_id=_CLIENT,
                discovered_count=120,
                tier_cutoffs={"top": 0.8},
                conn=conn,
            )
            assert result.projected_deep_count == 24
            row = (
                (
                    await conn.execute(
                        text(
                            "SELECT discovered_count, projected_deep_count, estimated_cents, "
                            "cutoffs_json FROM cost_estimate WHERE project_run_id = :r"
                        ),
                        {"r": run},
                    )
                )
                .mappings()
                .one()
            )
            assert row["discovered_count"] == 120
            assert row["projected_deep_count"] == 24
            assert Decimal(row["estimated_cents"]) == Decimal("60000")
            assert row["cutoffs_json"] == {"top": 0.8}

    run_async(_run())


def test_cost_estimate_check_rejects_negative_counts() -> None:
    """The named CHECK constraints reject a malformed snapshot (defense in depth)."""

    async def _run() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            with pytest.raises(DBAPIError):
                await conn.execute(
                    text(
                        "INSERT INTO cost_estimate "
                        "(project_run_id, discovered_count, projected_deep_count) "
                        "VALUES (:r, -1, 0)"
                    ),
                    {"r": new_project_run_id()},
                )

    run_async(_run())


def test_read_methods_make_no_domain_writes() -> None:
    """AC: the surface writes nothing into the domain write path — a read leaves claim /
    project_run
    row counts unchanged (the only sanctioned write is the cost_estimate snapshot, exercised
    above)."""

    async def _run() -> None:
        async with rollback_conn() as conn:
            run = new_run_id()
            await insert_claim(conn, _account_claim(new_entity_id(), run), validate_field=False)
            claims_before = (await conn.execute(text("SELECT count(*) FROM claim"))).scalar_one()
            runs_before = (
                await conn.execute(text("SELECT count(*) FROM project_run"))
            ).scalar_one()

            surface = _surface()
            await surface.source_yield(conn, workspace_id=_CLIENT)
            await surface.pre_run_estimate(
                project_run_id=new_project_run_id(),
                workspace_id=_CLIENT,
                discovered_count=10,
                conn=None,  # pure read — no snapshot
            )

            assert (await conn.execute(text("SELECT count(*) FROM claim"))).scalar_one() == (
                claims_before
            )
            assert (
                await conn.execute(text("SELECT count(*) FROM project_run"))
            ).scalar_one() == runs_before

    run_async(_run())
