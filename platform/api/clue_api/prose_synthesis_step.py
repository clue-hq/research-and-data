"""Lane E E1 — the fail-soft post-finalize prose step.

This is the seam between the account-research fleet and the governed
``synthesize_entity_prose@1`` tool. Two properties define it:

* **It never raises.** The call site sits *after* the fleet handler's suspend-on-error try, so it
  inherits no protection — and it must not gain any, because routing a prose failure into fleet
  suspension would let a summary problem stop research. Its own catch-all is therefore the whole
  safety story: a synthesis that explodes is logged and counted, the job stays terminal, and the
  handler returns exactly what it would have returned anyway.
* **It authorizes nothing.** It cannot decide to synthesize; it can only *offer* a finalized job to
  the governed tool, which re-checks every precondition against the durable row. The two gates the
  step applies (finalized-this-cycle, synthesizable outcome) are cheap declines that keep an
  obviously ineligible job out of the invocation journal — never a substitute for the tool's own.

Idempotency rides :attr:`ToolContext.operation_id`, derived from ``(job_id, field_key)``: the
invoker's A9 key and the invocation journal both key off it, so a redelivered task or a crashed
worker collapses onto one synthesis instead of a second paid one.
"""

from __future__ import annotations

from uuid import UUID

import structlog

from clue_api.account_research_fleet import AccountResearchFleetProjection
from clue_api.prose_synthesis_tools import (
    SYNTHESIZABLE_OUTCOMES,
    SynthesizeEntityProseTool,
)
from clue_core.execution_graph import operation_id_from_key
from clue_db import ConnFactory, transaction
from clue_fleet import WorkResult
from clue_obs.otel import MetricSink, get_metric_sink
from clue_research.narrative import ACCOUNT_SUMMARY, METRIC_PROSE_FAILED
from clue_toolbelt import PreconditionFailed, ToolContext, ToolInvoker

log = structlog.get_logger(__name__)

#: The A9 operation-id scope. Stable forever: changing it would re-mint every operation id and let
#: an already-synthesized job synthesize a second time.
PROSE_OPERATION_SCOPE = "lane_e_prose"


def prose_operation_id(job_id: UUID, field_key: str) -> object:
    """The content-addressed identity of "the prose synthesis for this job's this field"."""
    return operation_id_from_key(PROSE_OPERATION_SCOPE, f"{job_id}:{field_key}")


class ProseSynthesisStep:
    """Deferred-bound because the fleet is composed before the tool invoker exists.

    The fleet's launch services feed ``build_toolbelt``, and the invoker is built from the resulting
    registry — so the handler cannot be handed an invoker at construction time. This is the same
    cycle ``DeferredGovernedResearchOperationRequester`` breaks, with the same rule: binding twice
    raises rather than silently replacing a delegate.
    """

    def __init__(
        self,
        *,
        sink: MetricSink | None = None,
        conn_factory: ConnFactory = transaction,
    ) -> None:
        self._invoker: ToolInvoker | None = None
        self._sink = sink
        self._conn_factory = conn_factory

    @property
    def is_bound(self) -> bool:
        return self._invoker is not None

    def bind(self, invoker: ToolInvoker) -> None:
        if self._invoker is not None:
            raise RuntimeError("prose synthesis step is already bound")
        self._invoker = invoker

    async def after_account_job(
        self,
        *,
        job_id: UUID,
        result: WorkResult,
        projection: AccountResearchFleetProjection,
    ) -> None:
        """Offer one just-finalized account job to the prose tool. NEVER raises."""
        try:
            # Finalized *this cycle*: the inner handler stamps a receipt ref only on the path that
            # actually drove the job terminal. An already-terminal redelivery carries none, and
            # must not re-enter a spend path.
            if "finalization_receipt_ref" not in result.references:
                return
            summary = next((item for item in projection.jobs if item.job_id == job_id), None)
            if summary is None:
                return
            if summary.finalization_outcome not in SYNTHESIZABLE_OUTCOMES:
                return
            if self._invoker is None:
                raise RuntimeError("prose synthesis step is not bound to a tool invoker")
            context = ToolContext(
                workspace_id=projection.workspace_id,
                # Machine-initiated: no human actor and no captured action carried this call, and
                # claiming otherwise would forge a receipt.
                actor="agent",
                conn_factory=self._conn_factory,
                operation_id=prose_operation_id(job_id, ACCOUNT_SUMMARY),  # type: ignore[arg-type]
            )
            await self._invoker.invoke(
                SynthesizeEntityProseTool.name,
                {"job_id": str(job_id), "field_key": ACCOUNT_SUMMARY},
                context,
            )
        except PreconditionFailed as refusal:
            # An ineligible job is a decision the tool is *supposed* to make, not an incident.
            log.info(
                "prose_synthesis.step_refused",
                job_id=str(job_id),
                field_key=ACCOUNT_SUMMARY,
                reason_codes=list(refusal.reason_codes),
            )
        except Exception:
            log.warning(
                "prose_synthesis.step_failed",
                job_id=str(job_id),
                field_key=ACCOUNT_SUMMARY,
                workspace_id=projection.workspace_id,
                exc_info=True,
            )
            sink = self._sink or get_metric_sink()
            sink.add(METRIC_PROSE_FAILED, 1, {"field_key": ACCOUNT_SUMMARY})


__all__ = ["PROSE_OPERATION_SCOPE", "ProseSynthesisStep", "prose_operation_id"]
