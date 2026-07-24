"""B4 slice-3 — the A4 run-manifest projection over a live (DB-seeded) run + op validation.

Exit gates: the manifest renders a live run (phase spine nodes in canonical order with
``depends_on`` chaining, the human-gate flag on ``tier_checkpoint``, per-account nodes under DEEP
with tier-band cost priors); ops are validated pure — only pause/resume/adjust have real semantics
today, everything else yields the ``unsupported_op`` reason (the 422 body the HTTP surface serves).
"""

from __future__ import annotations

import pytest

from clue_core import ProjectPhase, new_project_run_id
from clue_projections import (
    MANIFEST_OP_TOOLS,
    UNSUPPORTED_OP,
    run_manifest,
    validate_manifest_op,
)
from clue_research.durable import AccountRunStatus, PhaseCheckpointStatus
from tests.db.conftest import run_async
from tests.profiling.conftest import conn_session_factory, rollback_conn
from tests.projections._helpers import seed_account_run, seed_checkpoint, seed_run

_WS = "ws-acme"

pytestmark = pytest.mark.usefixtures("require_profiling_db")


def test_manifest_renders_live_run_with_phase_spine_and_account_nodes() -> None:
    async def _run() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            cf = conn_session_factory(conn)
            run_id = await seed_run(conn, workspace_id=_WS, phase=ProjectPhase.DEEP)
            # Committed checkpoints for the phases the run already passed.
            for phase in (
                ProjectPhase.REVERSE_PROFILING,
                ProjectPhase.ICP_CONFIRMED,
                ProjectPhase.DISCOVERY,
                ProjectPhase.SCORING,
                ProjectPhase.TIER_CHECKPOINT,
            ):
                await seed_checkpoint(
                    conn,
                    project_run_id=run_id,
                    phase=phase,
                    status=PhaseCheckpointStatus.COMMITTED,
                )
            top = await seed_account_run(
                conn, project_run_id=run_id, tier="high", status=AccountRunStatus.RUNNING
            )
            view = await run_manifest(conn_factory=cf, project_run_id=run_id, workspace_id=_WS)
        assert view is not None
        assert view.current_phase == ProjectPhase.DEEP
        by_key = {n.node_key: n for n in view.nodes}

        # The fixed Recipe-#1 phase spine, in canonical order, chained by depends_on.
        phases = list(ProjectPhase)
        for prev, phase in zip(phases, phases[1:], strict=False):
            node = by_key[f"phase:{phase.value}"]
            assert node.depends_on == (f"phase:{prev.value}",)
        assert by_key[f"phase:{phases[0].value}"].depends_on == ()

        # Statuses: committed for the passed phases, in_progress for the current, pending after.
        assert by_key["phase:scoring"].status == "committed"
        assert by_key["phase:deep"].status == "in_progress"
        assert by_key["phase:verification"].status == "pending"
        # The human gate is flagged on tier_checkpoint only.
        assert by_key["phase:tier_checkpoint"].gate is True
        assert sum(1 for n in view.nodes if n.gate) == 1

        # The account node hangs under DEEP with its tier-band cost prior.
        acct = by_key[f"account:{top}"]
        assert acct.depends_on == ("phase:deep",)
        assert acct.account_scope == str(top)
        assert acct.status == "running"
        assert acct.est_cost_cents is not None and float(acct.est_cost_cents) > 0

    run_async(_run())


def test_manifest_cross_tenant_and_missing_run_are_none() -> None:
    async def _run() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            cf = conn_session_factory(conn)
            run_id = await seed_run(conn, workspace_id=_WS)
            assert (
                await run_manifest(conn_factory=cf, project_run_id=run_id, workspace_id="ws-other")
                is None
            )
            assert (
                await run_manifest(
                    conn_factory=cf, project_run_id=new_project_run_id(), workspace_id=_WS
                )
                is None
            )

    run_async(_run())


def test_validate_manifest_op_accepts_only_real_semantics() -> None:
    """Pure: pause/resume/adjust are accepted (mapped to slice-2 run-control tools); anything else
    is the machine-readable ``unsupported_op`` refusal — never a silent accept (pre-mortem #2)."""
    for op in MANIFEST_OP_TOOLS:
        assert validate_manifest_op(op) is None
    for op in ("retry_node", "skip_phase", "reorder", "cancel", "", "PAUSE"):
        assert validate_manifest_op(op) == UNSUPPORTED_OP
    # The op → tool map names only the slice-2 run controls.
    assert MANIFEST_OP_TOOLS == {
        "pause": "pause_run",
        "resume": "resume_run",
        "adjust": "adjust_budget",
    }
