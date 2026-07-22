"""DB-backed test for the ``REVERSE_PROFILING`` phase handler (M5.1).

The handler implements the frozen ``PhaseHandler`` protocol and opens its own (committing)
transaction, so this exercises it against a real DB. The claim table is append-only (deletes are
blocked — erasure is M10.5), so rather than clean up we use a fresh tenant + domain per run, which
yields a brand-new client entity at version 1. ``reverse_profile`` itself is covered exhaustively in
``test_reverse_profile.py``; this pins the handler's protocol conformance and its ``PhaseContext`` →
``PhaseResult`` mapping.
"""

from __future__ import annotations

from decimal import Decimal
from uuid import uuid4

import pytest

from clue_core import (
    CostCents,
    PhaseContext,
    PhaseHandler,
    PhaseStatus,
    ProjectPhase,
    ProjectRunId,
    new_project_run_id,
)
from clue_db import db_lifespan, transaction
from clue_research.claimstore import load_core_pack
from clue_research.sources import bind_resolver, seed_source_manifests
from clue_research.stage0 import ReverseProfilingHandler
from clue_research.stage0.fields import CLIENT_VALUE_PROP
from tests.stage0._fakes import FakeResolver
from tests.stage0.conftest import run_async

pytestmark = pytest.mark.usefixtures("require_stage0_db", "resolver_bindings")


def test_handler_conforms_to_protocol() -> None:
    handler = ReverseProfilingHandler()
    assert isinstance(handler, PhaseHandler)
    assert handler.phase is ProjectPhase.REVERSE_PROFILING


async def _seed_committed() -> None:
    """Commit the registry state the waterfall reads (idempotent — load is a no-op if present)."""
    async with transaction() as conn:
        await load_core_pack(conn)
        await seed_source_manifests(conn)


def _ctx(
    suffix: str,
    *,
    project_run_id: ProjectRunId | None = None,
    budget_cap_cents: CostCents | None = None,
) -> PhaseContext:
    return PhaseContext(
        project_run_id=project_run_id if project_run_id is not None else new_project_run_id(),
        phase=ProjectPhase.REVERSE_PROFILING,
        workspace_id=f"tenant-handler-{suffix}",
        icp_key="__reverse_profiling__",
        icp_version=0,
        budget_cap_cents=budget_cap_cents,
        params={
            "client_input": {
                "name": f"Handler Test {suffix}",
                "website": f"https://handler-{suffix}.example",
            }
        },
    )


def test_handler_runs_reverse_profiling_phase() -> None:
    async def _run() -> None:
        async with db_lifespan():
            await _seed_committed()
            # fresh tenant + domain → a brand-new client entity at version 1 (no cleanup needed)
            bind_resolver("firecrawl_site", FakeResolver(tier=2, values={CLIENT_VALUE_PROP: "ci"}))
            result = await ReverseProfilingHandler().run(_ctx(uuid4().hex[:12]))
            assert result.status is PhaseStatus.COMPLETED
            assert result.accounts_processed == 1
            assert result.payload["client_kb_version"] == 1
            assert "client_entity_id" in result.payload
            assert result.payload["budget_exhausted"] is False

    run_async(_run())


def test_handler_pauses_on_budget_exhaustion() -> None:
    async def _run() -> None:
        async with db_lifespan():
            await _seed_committed()
            # cost 1.0/field, cap 1.0 → budget halts → the phase PAUSES (a durable boundary), not
            # FAILED — the state machine can hold, raise the cap, and resume the same run.
            bind_resolver("firecrawl_site", FakeResolver(tier=2, values={CLIENT_VALUE_PROP: "ci"}))
            ctx = _ctx(uuid4().hex[:12], budget_cap_cents=Decimal("1.0"))
            result = await ReverseProfilingHandler().run(ctx)
            assert result.status is PhaseStatus.PAUSED
            assert result.payload["budget_exhausted"] is True

    run_async(_run())


def test_handler_idempotent_resume_across_commits() -> None:
    async def _run() -> None:
        async with db_lifespan():
            await _seed_committed()
            bind_resolver("firecrawl_site", FakeResolver(tier=2, values={CLIENT_VALUE_PROP: "ci"}))
            # Same project run id → same derived run id. Two separate committing handler runs
            # (a crash-and-resume) must NOT double-write: the version stays 1 (no bump) and the
            # client resolves to the same entity — the "no double-charge" half of the AC, proven
            # across a real commit boundary (not just within one rolled-back transaction).
            suffix = uuid4().hex[:12]
            crid = new_project_run_id()
            first = await ReverseProfilingHandler().run(_ctx(suffix, project_run_id=crid))
            second = await ReverseProfilingHandler().run(_ctx(suffix, project_run_id=crid))
            assert first.payload["client_kb_version"] == 1
            assert second.payload["client_kb_version"] == 1  # re-entry did not bump the version
            assert second.payload["client_entity_id"] == first.payload["client_entity_id"]
            assert second.payload["run_id"] == first.payload["run_id"]

    run_async(_run())
