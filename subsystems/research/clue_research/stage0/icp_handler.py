"""The ``ICP_CONFIRMED`` phase handler (M5.2).

M5 owns the campaign-run's first two phases (Doc C §4). After ``REVERSE_PROFILING``, the
``ICP_CONFIRMED`` phase is the **checkpoint over an already-confirmed ICP spec**: the interactive
synthesize → edit → confirm flow (:mod:`clue_research.stage0.icp_synthesis` /
:mod:`clue_research.stage0.icp_confirm`) produced and activated the versioned ``ICPSpec`` for this
campaign's ``(workspace_id, icp_key, icp_version)``; this handler emits the **phase artifact** the
M7
state machine advances on — the compiled field-plan reference (``plan_hash``, the two-pass field
counts) plus the pre-run cost estimate (Doc C §5).

It *implements* the frozen :class:`~clue_core.execution.PhaseHandler` (Beat-0) — imports
``core``, never M7's ``durable``; the concrete instance is registered into the ``ProjectRun`` at
the ``api`` composition root, which dispatches by the declared ``phase`` attribute. The phase is
**pure reads** (read the pinned spec → compile → estimate), so it is naturally idempotent: a
resumed phase recomputes the identical artifact with no double-write. A missing spec (the client
never confirmed this ICP) is a ``FAILED`` — a real misconfiguration, not a budget pause.
"""

from __future__ import annotations

from pydantic import JsonValue

from clue_core import PhaseContext, PhaseResult, PhaseStatus, ProjectPhase
from clue_db import transaction
from clue_obs.otel import ATTR_WORKSPACE_ID, apply_attributes, traced_step
from clue_research.icp import compile_field_plan, get_icp_version
from clue_research.stage0.icp_estimate import EstimateInputs, estimate_campaign


class IcpConfirmedHandler:
    """Implements :class:`~clue_core.execution.PhaseHandler` for ``ICP_CONFIRMED``."""

    phase = ProjectPhase.ICP_CONFIRMED

    def __init__(self, *, estimate_inputs: EstimateInputs | None = None) -> None:
        # The cost-dial priors for the pre-run estimate (versioned config; D7). M7's BudgetEngine
        # supersedes this with a real figure once a discovered count exists.
        self._estimate_inputs = estimate_inputs

    async def run(self, ctx: PhaseContext) -> PhaseResult:
        with traced_step("stage0.icp_confirmed", **{ATTR_WORKSPACE_ID: ctx.workspace_id}) as span:
            async with transaction() as conn:
                spec = await get_icp_version(conn, ctx.workspace_id, ctx.icp_key, ctx.icp_version)
                if spec is None:
                    return PhaseResult(
                        status=PhaseStatus.FAILED,
                        payload={
                            "reason": (
                                f"no confirmed ICP spec for ({ctx.icp_key!r}, v{ctx.icp_version})"
                            )
                        },
                    )
                plan = await compile_field_plan(conn, spec)

            estimate = estimate_campaign(self._estimate_inputs)
            apply_attributes(span, {"icp.field_count": len(plan.fields)})

        payload: dict[str, JsonValue] = {
            "icp_key": spec.icp_key,
            "icp_version": spec.version,
            "plan_hash": plan.plan_hash,
            "field_count": len(plan.fields),
            "scoring_field_count": len(plan.scoring_fields),
            "deep_field_count": len(plan.deep_fields),
            "enabled_packs": list(spec.enabled_packs),
            "estimate": estimate.model_dump(mode="json"),
        }
        return PhaseResult(status=PhaseStatus.COMPLETED, accounts_processed=0, payload=payload)
