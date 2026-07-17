"""The ``REVERSE_PROFILING`` phase handler (M5.1).

M5 owns the campaign-run's first phase (Doc C §4). The handler *implements* the frozen
:class:`~clue_core.execution.PhaseHandler` protocol from ``core`` (Beat-0) — it imports
``core``, never M7's ``durable``; the concrete instance is constructed (with the injected M9 judge
/ M0.4 gateway) and registered into the ``CampaignRun`` state machine at the ``api`` composition
root, which dispatches by the declared ``phase`` attribute without importing this package.

The handler is a thin durable wrapper: it opens its own transaction, derives a **stable run id**
from the campaign run id (so a resumed phase re-enters the *same* reverse-profiling run and the
pipeline deduplicates instead of double-spending), runs
:func:`~clue_research.stage0.client_kb.reverse_profile`, and reports the versioned base by
reference (never claim bodies). A budget graceful-stop returns ``PAUSED`` so the state machine
holds the run at a durable boundary (raise the cap → resume → the same run id continues), per
:class:`~clue_core.enums.PhaseStatus`.
"""

from __future__ import annotations

from uuid import NAMESPACE_URL, uuid5

from pydantic import JsonValue

from clue_core import (
    CampaignPhase,
    CampaignRunId,
    FaithfulnessJudge,
    PhaseContext,
    PhaseResult,
    PhaseStatus,
    RunId,
)
from clue_db import transaction
from clue_research.stage0.client_kb import reverse_profile
from clue_research.stage0.types import ClientInput


def reverse_profiling_run_id(campaign_run_id: CampaignRunId) -> RunId:
    """Derive the deterministic per-client research run id for a campaign's reverse-profiling phase.

    Stable across retries/restarts (no clock, no randomness — like ``core.idempotency``), so a
    re-entered phase reuses it and the waterfall/material/marker writes deduplicate."""
    return RunId(uuid5(NAMESPACE_URL, f"reverse_profiling:{campaign_run_id}"))


def _client_input_from_params(params: dict[str, JsonValue]) -> ClientInput:
    """Build the :class:`ClientInput` from the phase params (the keys-not-blobs escape hatch).
    Accepts a nested ``client_input`` object or top-level ``name``/``website``/``materials``."""
    raw = params.get("client_input")
    if isinstance(raw, dict):
        return ClientInput.model_validate(raw)
    return ClientInput.model_validate(
        {
            "name": params.get("name"),
            "website": params.get("website"),
            "materials": params.get("materials", []),
        }
    )


class ReverseProfilingHandler:
    """Implements :class:`~clue_core.execution.PhaseHandler` for ``REVERSE_PROFILING``."""

    phase = CampaignPhase.REVERSE_PROFILING

    def __init__(self, *, judge: FaithfulnessJudge | None = None) -> None:
        self._judge = judge

    async def run(self, ctx: PhaseContext) -> PhaseResult:
        client_input = _client_input_from_params(ctx.params)
        run_id = reverse_profiling_run_id(ctx.campaign_run_id)

        async with transaction() as conn:
            result = await reverse_profile(
                conn,
                client_input,
                workspace_id=ctx.workspace_id,
                run_id=run_id,
                budget_cap_cents=ctx.budget_cap_cents,
                judge=self._judge,
            )

        status = PhaseStatus.PAUSED if result.budget_exhausted else PhaseStatus.COMPLETED
        payload: dict[str, JsonValue] = {
            "client_entity_id": str(result.ref.client_entity_id),
            "client_kb_version": result.ref.client_kb_version,
            "run_id": str(result.run_id),
            "fields_resolved": result.fields_resolved,
            "fields_filled": result.coverage.filled_count,
            "fields_total": result.coverage.total_count,
            "budget_exhausted": result.budget_exhausted,
        }
        return PhaseResult(
            status=status,
            accounts_processed=1,  # the client is the single entity profiled
            cost_cents=result.cost_cents,
            payload=payload,
        )
