"""The ``CampaignPhase.VERIFICATION`` composition root — wires the concrete M9/M10 seams.

Constructs :class:`~clue_research.api.verification.handler.VerificationPhaseHandler` with the real
M9.2 :class:`~clue_research.verification.Corroborator`, the M9.3
:class:`~clue_research.verification.FaithfulnessJudgeImpl` (over the shared
:class:`~clue_research.core.gateway.LLMGateway`), and the live-claims loader
(:func:`clue_research.claimstore.claims_for` with ``field_key=None``), then registers it into the M7
phase-handler registry so ``CampaignRun.advance()`` dispatches ``VERIFICATION`` instead of raising
``NoPhaseHandlerRegistered(VERIFICATION)``.

``api`` is the import-linter-exempt seam, so this module imports the otherwise-independent
``verification`` / ``claimstore`` packages directly (nothing imports ``api`` — Rule 5).

**Account set:** pass the SAME ``account_resolver`` the DEEP composition built
(:func:`clue_research.api.deep.composition.build_high_tier_resolver`), so verification runs over
exactly the accounts DEEP processed — one source of the high-tier set.

**Use gate (M10.3):** optional and defaulted off here. The handler drives it over
``contact.facet.*`` claims, but the production v1 ``account_resolver`` yields *account* entities
(no facet claims), so the gate is a no-op until the committee-contact loader lands (the documented
follow-on); wiring the per-client :class:`~clue_research.compliance.UseGateImpl` belongs there.
"""

from __future__ import annotations

from collections.abc import Sequence

from clue_research.api.verification.handler import (
    ClaimCorroborator,
    VerificationAccountResolver,
    VerificationPhaseHandler,
)
from clue_research.claimstore import TenantScope, claims_for
from clue_research.core import Claim, EntityId
from clue_research.core.compliance import UseGate
from clue_research.core.gateway import LLMGateway
from clue_research.db import transaction
from clue_research.durable import register_phase_handler
from clue_research.obs import MetricSink
from clue_research.profiling.runtime import SessionFactory
from clue_research.verification import (
    DEFAULT_CORROBORATION_POLICY,
    DEFAULT_JUDGE_POLICY,
    CorroborationPolicy,
    Corroborator,
    FaithfulnessJudgeImpl,
    JudgePolicy,
)


def build_verification_phase_handler(
    *,
    gateway: LLMGateway,
    account_resolver: VerificationAccountResolver,
    session_factory: SessionFactory = transaction,
    judge_policy: JudgePolicy = DEFAULT_JUDGE_POLICY,
    corroboration_policy: CorroborationPolicy = DEFAULT_CORROBORATION_POLICY,
    use_gate: UseGate | None = None,
    health_sink: MetricSink | None = None,
) -> VerificationPhaseHandler:
    """Construct the ``CampaignPhase.VERIFICATION`` handler with the concrete M9 seams.

    ``account_resolver`` is the high-tier resolver shared with DEEP. The corroborator and judge each
    manage their own committed transaction per call (``session_factory``); the live-claims loader
    reads all live fields for an entity in one tenant-scoped read."""
    corroborator = Corroborator(
        policy=corroboration_policy, conn_factory=session_factory, sink=health_sink
    )
    judge = FaithfulnessJudgeImpl(
        gateway=gateway, policy=judge_policy, conn_factory=session_factory, sink=health_sink
    )

    async def load_claims(entity_id: EntityId, scope: TenantScope) -> Sequence[Claim]:
        async with session_factory() as conn:
            return await claims_for(conn, entity_id, scope=scope)

    return VerificationPhaseHandler(
        account_resolver=account_resolver,
        load_claims=load_claims,
        corroborator=corroborator,
        judge=judge,
        use_gate=use_gate,
        health_sink=health_sink,
    )


def register_verification_phase_handler(
    *,
    gateway: LLMGateway,
    account_resolver: VerificationAccountResolver,
    session_factory: SessionFactory = transaction,
    judge_policy: JudgePolicy = DEFAULT_JUDGE_POLICY,
    corroboration_policy: CorroborationPolicy = DEFAULT_CORROBORATION_POLICY,
    use_gate: UseGate | None = None,
    health_sink: MetricSink | None = None,
) -> VerificationPhaseHandler:
    """Build + register the ``VERIFICATION`` handler into the process-default phase registry (the
    api-root binder; mirrors ``register_deep_phase_handler`` / the handoff registrant)."""
    handler = build_verification_phase_handler(
        gateway=gateway,
        account_resolver=account_resolver,
        session_factory=session_factory,
        judge_policy=judge_policy,
        corroboration_policy=corroboration_policy,
        use_gate=use_gate,
        health_sink=health_sink,
    )
    register_phase_handler(handler)
    return handler


# Static-time conformance: the real M9.2 Corroborator must satisfy the structural
# ``ClaimCorroborator`` seam the handler is typed against — so the fake-driven handler tests
# exercise the same surface the composition root wires.
_CORROBORATOR_IS_A_CLAIM_CORROBORATOR: type[ClaimCorroborator] = Corroborator
