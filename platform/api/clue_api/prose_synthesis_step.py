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

from collections.abc import Sequence
from typing import Protocol
from uuid import UUID

import structlog

from clue_api.account_research_fleet import AccountResearchFleetProjection
from clue_api.contact_research_fleet import ContactResearchFleetProjection
from clue_api.prose_synthesis_tools import (
    SYNTHESIZABLE_OUTCOMES,
    SynthesizeEntityProseTool,
)
from clue_api.value_narrative_tools import SynthesizeValueNarrativeTool
from clue_core.entity_research import ResearchFinalizationOutcome
from clue_core.execution_graph import operation_id_from_key
from clue_db import ConnFactory, transaction
from clue_fleet import WorkResult
from clue_obs.otel import MetricSink, get_metric_sink
from clue_research.narrative import (
    ACCOUNT_SUMMARY,
    CONTACT_OVERVIEW,
    METRIC_PROSE_FAILED,
    VALUE_NARRATIVE,
)
from clue_toolbelt import PreconditionFailed, ToolContext, ToolInvoker

log = structlog.get_logger(__name__)

#: The A9 operation-id scope. Stable forever: changing it would re-mint every operation id and let
#: an already-synthesized job synthesize a second time.
PROSE_OPERATION_SCOPE = "lane_e_prose"


def prose_operation_id(job_id: UUID, field_key: str) -> object:
    """The content-addressed identity of "the prose synthesis for this job's this field"."""
    return operation_id_from_key(PROSE_OPERATION_SCOPE, f"{job_id}:{field_key}")


class _FinalizedJobSummary(Protocol):
    """The two lanes' job summaries agree on exactly the two attributes this step reads, which is
    why one offer path can serve both without either projection type leaking into the other."""

    @property
    def job_id(self) -> UUID: ...

    @property
    def finalization_outcome(self) -> ResearchFinalizationOutcome | None: ...


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
        narrative_enabled: bool = False,
    ) -> None:
        self._invoker: ToolInvoker | None = None
        self._sink = sink
        self._conn_factory = conn_factory
        # Lane E E3. The *offer* is gated here, not only at composition: the narrative tool refuses
        # `value_narrative_not_composed` in an unconfigured process, but a refusal is still a
        # journaled invocation, and one refusal row per finished account job is not an acceptable
        # steady state for a deployment that has the feature switched off. Flag off ⇒ the job is
        # never offered ⇒ zero narrative rows anywhere.
        self._narrative_enabled = narrative_enabled

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
        """Offer one just-finalized account job to the prose tool, then — when the value-narrative
        flag is on — to the positioning tool. NEVER raises.

        The two offers are independent calls with their own gates, their own operation ids, and
        their own catch-all: a prose refusal must not suppress the narrative, and a narrative
        failure must not retro-actively taint the summary that already landed.
        """
        await self._offer(
            job_id=job_id,
            result=result,
            workspace_id=projection.workspace_id,
            jobs=projection.jobs,
            field_key=ACCOUNT_SUMMARY,
        )
        if self._narrative_enabled:
            await self._offer(
                job_id=job_id,
                result=result,
                workspace_id=projection.workspace_id,
                jobs=projection.jobs,
                field_key=VALUE_NARRATIVE,
                tool_name=SynthesizeValueNarrativeTool.name,
                # The narrative is keyed on the job alone: the account, product, ICP pin and client
                # lineage are all read from durable rows, so there is no second parameter to name.
                body={"job_id": str(job_id)},
            )

    async def after_contact_job(
        self,
        *,
        job_id: UUID,
        result: WorkResult,
        projection: ContactResearchFleetProjection,
    ) -> None:
        """Offer one just-finalized contact job to the prose tool. NEVER raises.

        The contact fleet handler carries no suspend-on-error try of its own, so on this lane the
        catch-all below is the *only* thing standing between a synthesis failure and a fleet
        incident. Same gates, same content-addressed identity — with ``contact.overview`` in the
        operation id, so the two lanes cannot collide.
        """
        await self._offer(
            job_id=job_id,
            result=result,
            workspace_id=projection.workspace_id,
            jobs=projection.jobs,
            field_key=CONTACT_OVERVIEW,
        )

    async def _offer(
        self,
        *,
        job_id: UUID,
        result: WorkResult,
        workspace_id: str,
        jobs: Sequence[_FinalizedJobSummary],
        field_key: str,
        tool_name: str = SynthesizeEntityProseTool.name,
        body: dict[str, object] | None = None,
    ) -> None:
        try:
            # Finalized *this cycle*: the inner handler stamps a receipt ref only on the path that
            # actually drove the job terminal. An already-terminal redelivery carries none, and
            # must not re-enter a spend path.
            if "finalization_receipt_ref" not in result.references:
                return
            summary = next((item for item in jobs if item.job_id == job_id), None)
            if summary is None:
                return
            if summary.finalization_outcome not in SYNTHESIZABLE_OUTCOMES:
                return
            if self._invoker is None:
                raise RuntimeError("prose synthesis step is not bound to a tool invoker")
            context = ToolContext(
                workspace_id=workspace_id,
                # Machine-initiated: no human actor and no captured action carried this call, and
                # claiming otherwise would forge a receipt.
                actor="agent",
                conn_factory=self._conn_factory,
                operation_id=prose_operation_id(job_id, field_key),  # type: ignore[arg-type]
            )
            await self._invoker.invoke(
                tool_name,
                body if body is not None else {"job_id": str(job_id), "field_key": field_key},
                context,
            )
        except PreconditionFailed as refusal:
            # An ineligible job is a decision the tool is *supposed* to make, not an incident.
            log.info(
                "prose_synthesis.step_refused",
                job_id=str(job_id),
                field_key=field_key,
                reason_codes=list(refusal.reason_codes),
            )
        except Exception:
            log.warning(
                "prose_synthesis.step_failed",
                job_id=str(job_id),
                field_key=field_key,
                workspace_id=workspace_id,
                exc_info=True,
            )
            sink = self._sink or get_metric_sink()
            sink.add(METRIC_PROSE_FAILED, 1, {"field_key": field_key})


__all__ = ["PROSE_OPERATION_SCOPE", "ProseSynthesisStep", "prose_operation_id"]
