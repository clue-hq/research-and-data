"""The ``CampaignPhase.VERIFICATION`` composition root — wires the concrete M9/M10 seams.

Constructs :class:`~clue_research.api.verification.handler.VerificationPhaseHandler` with the real
M9.2 :class:`~clue_research.verification.Corroborator`, the M9.3
:class:`~clue_research.verification.FaithfulnessJudgeImpl` (over the shared
:class:`~clue_core.gateway.LLMGateway`), the live-claims loader
(:func:`clue_research.claimstore.claims_for` with ``field_key=None``), and — when
``govern_contacts`` is set — the committee-contact source
(:func:`clue_research.identity.contact_ids_for_account`) plus
the per-client use-gate provider (:func:`clue_research.compliance.load_client_policy` →
:class:`~clue_research.compliance.UseGateImpl`). It then registers the handler into the M7
phase-handler registry so ``CampaignRun.advance()`` dispatches ``VERIFICATION`` instead of raising
``NoPhaseHandlerRegistered(VERIFICATION)``.

``api`` is the import-linter-exempt seam, so this module imports the otherwise-independent
``verification`` / ``compliance`` / ``identity`` / ``claimstore`` packages directly (nothing imports
``api`` — Rule 5).

**Account set:** pass the SAME ``account_resolver`` the DEEP composition built
(:func:`clue_research.api.deep.composition.build_high_tier_resolver`), so verification runs over
exactly the accounts DEEP processed — one source of the high-tier set.

**Contacts + use-gate (M10.3):** with ``govern_contacts=True`` (the default), each account's
committee contacts are verified alongside it and every ``contact.facet.*`` claim is run through the
per-client use-gate (resolved from ``ctx.client_id`` at run time, since the posture policy is the
client's). Set ``govern_contacts=False`` for account-only verification (e.g. a no-committee run).
"""

from __future__ import annotations

from collections.abc import Sequence

from clue_core import Claim, EntityId
from clue_core.compliance import UseGate
from clue_core.gateway import LLMGateway
from clue_db import ConnFactory, transaction
from clue_obs.otel import MetricSink
from clue_research.api.verification.handler import (
    ClaimCorroborator,
    ContactResolver,
    UseGateProvider,
    VerificationAccountResolver,
    VerificationPhaseHandler,
)
from clue_research.claimstore import TenantScope, claims_for
from clue_research.compliance import UseGateImpl, load_client_policy
from clue_research.durable import register_phase_handler
from clue_research.identity import contact_ids_for_account
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
    session_factory: ConnFactory = transaction,
    judge_policy: JudgePolicy = DEFAULT_JUDGE_POLICY,
    corroboration_policy: CorroborationPolicy = DEFAULT_CORROBORATION_POLICY,
    govern_contacts: bool = True,
    health_sink: MetricSink | None = None,
) -> VerificationPhaseHandler:
    """Construct the ``CampaignPhase.VERIFICATION`` handler with the concrete M9/M10 seams.

    ``account_resolver`` is the high-tier resolver shared with DEEP. The corroborator and judge each
    manage their own committed transaction per call (``session_factory``); the live-claims loader
    reads all live fields for an entity in one tenant-scoped read. With ``govern_contacts`` set, the
    committee-contact resolver and the per-client use-gate provider are wired so personal hooks are
    governed; clear it for account-only verification."""
    corroborator = Corroborator(
        policy=corroboration_policy, conn_factory=session_factory, sink=health_sink
    )
    judge = FaithfulnessJudgeImpl(
        gateway=gateway, policy=judge_policy, conn_factory=session_factory, sink=health_sink
    )

    async def load_claims(entity_id: EntityId, scope: TenantScope) -> Sequence[Claim]:
        async with session_factory() as conn:
            return await claims_for(conn, entity_id, scope=scope)

    contact_resolver: ContactResolver | None = None
    use_gate_provider: UseGateProvider | None = None
    if govern_contacts:

        async def resolve_contacts(account_entity_id: EntityId) -> Sequence[EntityId]:
            async with session_factory() as conn:
                return await contact_ids_for_account(conn, account_entity_id)

        async def provide_use_gate(client_id: str) -> UseGate | None:
            async with session_factory() as conn:
                policy = await load_client_policy(conn, client_id=client_id)
            return UseGateImpl(
                client_id, policy=policy, conn_factory=session_factory, sink=health_sink
            )

        contact_resolver = resolve_contacts
        use_gate_provider = provide_use_gate

    return VerificationPhaseHandler(
        account_resolver=account_resolver,
        load_claims=load_claims,
        corroborator=corroborator,
        judge=judge,
        contact_resolver=contact_resolver,
        use_gate_provider=use_gate_provider,
        health_sink=health_sink,
    )


def register_verification_phase_handler(
    *,
    gateway: LLMGateway,
    account_resolver: VerificationAccountResolver,
    session_factory: ConnFactory = transaction,
    judge_policy: JudgePolicy = DEFAULT_JUDGE_POLICY,
    corroboration_policy: CorroborationPolicy = DEFAULT_CORROBORATION_POLICY,
    govern_contacts: bool = True,
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
        govern_contacts=govern_contacts,
        health_sink=health_sink,
    )
    register_phase_handler(handler)
    return handler


# Static-time conformance: the real M9.2 Corroborator must satisfy the structural
# ``ClaimCorroborator`` seam the handler is typed against, and the M10.3 ``UseGateImpl`` must meet
# the ``core.compliance.UseGate`` protocol the provider returns — so the fake-driven handler tests
# exercise the same surface the composition root wires.
_CORROBORATOR_IS_A_CLAIM_CORROBORATOR: type[ClaimCorroborator] = Corroborator
_USE_GATE_IMPL_IS_A_USE_GATE: type[UseGate] = UseGateImpl
