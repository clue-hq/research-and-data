"""The ``CampaignPhase.VERIFICATION`` phase handler (integration) — runs the gate chain live.

This is the keystone the three-way integration (M10 + M11 + M12) adds: the live call site that
drives the frozen :data:`~clue_api.composition.VERIFICATION_GATE_ORDER` over the claims the
``DEEP`` phase produced and left ``unverified``. Until it runs, the M1.2 merge
(:class:`~clue_research.claimstore.MergePolicy` ``require_verified_tier4=True``) leaves
``current_value`` **empty** for every tier-4 synthesis field — so M11's Output-2
(``operational_pain`` / ``strategic_moves`` / ``account.resonance.*``) and the M12 value narrative
come out blank. That
silent blanking, not a crash, is the failure mode the integration plan flags
(``_memory/2026-06-25-m10-m11-m12-integration-plan.md``); this handler is what closes it.

Per account, in the frozen order (Doc D §7 — "is it true / is it this person?" before "may we use
it?"):

1. **corroboration** (M9.2) per ``(entity, field)`` — promotes a tier≤3 value to ``verified`` once
   enough independent sources agree (a no-op for a tier-4-only field);
2. **faithfulness** (M9.3) per live tier-4 claim — the judge entails ``value_json`` from the claim's
   ``evidence_span`` and drives the tier-4 ``verification_status`` to ``verified`` / ``rejected`` (a
   no-span tier-4 claim is auto-``unsupported`` — structural and free);
3. **identity-binding** (M9.4) — *not a runtime step here*: it is stamped immutably at claim
   construction (the born-binding) and enforced structurally by the merge's weak-binding exclusion;
4. **use gate** (M10.3) **last** — for each ``contact.facet.*`` claim, writes the ``use_decision``
   appropriateness verdict; the "clears both gates" composite (``is_outreach_promotable``) is read
   downstream by M12, never re-derived here.

then records the per-field tier-4 verification-health (Doc C §6,
``synthesis.record_synthesis_health``). Per-account **isolated** — one account's fault marks it
failed and the batch continues (coverage-confidence, not all-or-nothing), like the DEEP handler.
The result is references-only (counts + cost). Construct and register at the api composition root.

**Coverage:** each account is verified together with its committee *contact* entities (resolved via
the injected ``contact_resolver`` → ``identity.contact_ids_for_account``), so the account-level
synthesis claims **and** the contacts' ``contact.facet.*`` hooks are governed in one pass — the
account fields make ``current_value`` non-empty for Output-2, and the facet hooks clear the use-gate
before M12 reads them. With no ``contact_resolver``/``use_gate_provider`` wired the pass is
account-only (e.g. a no-committee run); both are defaulted on at the composition root.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from decimal import Decimal
from typing import Protocol, runtime_checkable

from clue_core import (
    CampaignPhase,
    Claim,
    CostCents,
    EntityId,
    EntityType,
    FieldKey,
    PhaseContext,
    PhaseHandler,
    PhaseResult,
    PhaseStatus,
)
from clue_core.compliance import UseGate
from clue_core.verification import FaithfulnessJudge
from clue_obs.otel import MetricSink
from clue_research.claimstore import WorkspaceScope
from clue_research.durable import AccountSpec
from clue_research.synthesis import record_synthesis_health

# Personal-hook field-class prefix (conventions §3): the use gate (M10.3) governs exactly these.
_FACET_PREFIX = "contact.facet."

# --- injected seams ----------------------------------------------------------

# Resolve the accounts to verify for this run — the SAME high-tier set the DEEP phase processed. The
# api root passes the very ``HighTierResolver`` it built for ``DeepPhaseHandler`` (one source of the
# account set); a fake is injected in tests.
VerificationAccountResolver = Callable[[PhaseContext], Awaitable[Sequence[AccountSpec]]]

# Load an entity's **live** claims across all fields (``claims_for(field_key=None)``), scoped.
# Injected so the handler imports no claim store and stays unit-testable; the concrete is wired at
# the composition root.
ClaimLoader = Callable[[EntityId, WorkspaceScope], Awaitable[Sequence[Claim]]]

# Resolve the committee *contact* entity ids under an account so their ``contact.facet.*`` claims
# are verified + use-gated alongside the account. ``None`` (the resolver unset) keeps verification
# account-only. Production reads ``identity.contact_ids_for_account``.
ContactResolver = Callable[[EntityId], Awaitable[Sequence[EntityId]]]

# Build the per-client M10.3 :class:`~clue_core.compliance.UseGate` for a run (the gate is
# parameterized by the client's posture policy, so it is resolved from ``ctx.workspace_id`` at run
# time, not at handler-construction). ``None`` (the provider unset, or returning ``None``) skips the
# use-gate leg. Production loads ``WorkspacePolicy`` and constructs ``compliance.UseGateImpl``.
UseGateProvider = Callable[[str], Awaitable[UseGate | None]]


@runtime_checkable
class ClaimCorroborator(Protocol):
    """The slice of M9.2 :class:`~clue_research.verification.Corroborator` this handler drives —
    typed structurally (conventions §2) so the handler is fake-testable without a DB. The real
    corroborator satisfies it (asserted at the composition root)."""

    async def evaluate(
        self,
        entity_id: EntityId,
        field_key: FieldKey | str,
        *,
        scope: WorkspaceScope,
        entity_type: EntityType | None = None,
    ) -> object: ...


@dataclass(frozen=True, slots=True)
class _AccountVerification:
    """One account's contribution to the phase result — the judge spend it incurred and whether it
    completed without faulting. Internal aggregation unit."""

    cost_cents: CostCents
    succeeded: bool


class VerificationPhaseHandler:
    """The ``CampaignPhase.VERIFICATION`` :class:`~clue_core.PhaseHandler`.

    Drives corroboration → faithfulness → (use-gate last) → verification-health over each high-tier
    account's deep claims, isolated per account. Construct once per campaign with the injected
    collaborators and register it at the api composition root (mirrors the DEEP handler)."""

    phase = CampaignPhase.VERIFICATION

    def __init__(
        self,
        *,
        account_resolver: VerificationAccountResolver,
        load_claims: ClaimLoader,
        corroborator: ClaimCorroborator,
        judge: FaithfulnessJudge,
        contact_resolver: ContactResolver | None = None,
        use_gate_provider: UseGateProvider | None = None,
        health_sink: MetricSink | None = None,
    ) -> None:
        self._account_resolver = account_resolver
        self._load_claims = load_claims
        self._corroborator = corroborator
        self._judge = judge
        self._contact_resolver = contact_resolver
        self._use_gate_provider = use_gate_provider
        self._health_sink = health_sink

    async def run(self, ctx: PhaseContext) -> PhaseResult:
        """Verify every high-tier account's deep claims, isolated per account, then aggregate.

        COMPLETED with a references-only count payload; a high-tier set of zero is a clean COMPLETED
        no-op. The phase never PAUSEs — verification is idempotent (corroboration UPDATEs in place,
        the judge caches on ``(claim, model, prompt)``), so a re-entry after a crash simply
        re-affirms the same verdicts."""
        accounts = tuple(await self._account_resolver(ctx))
        if not accounts:
            return PhaseResult(
                status=PhaseStatus.COMPLETED,
                accounts_processed=0,
                cost_cents=Decimal(0),
                payload={"verified_accounts": 0, "accounts_failed": 0},
            )

        scope = WorkspaceScope.for_workspace(ctx.workspace_id)
        # The use-gate is per-client (its posture policy is the client's), so resolve it once for
        # the whole run from ``ctx.workspace_id`` — not at handler construction (one handler serves
        # every campaign).
        use_gate = (
            await self._use_gate_provider(ctx.workspace_id)
            if self._use_gate_provider is not None
            else None
        )
        outcomes = [
            await self._verify_isolated(spec.entity_id, scope, use_gate) for spec in accounts
        ]

        processed = sum(1 for o in outcomes if o.succeeded)
        failed = sum(1 for o in outcomes if not o.succeeded)
        cost = sum((o.cost_cents for o in outcomes), Decimal(0))
        return PhaseResult(
            status=PhaseStatus.COMPLETED,
            accounts_processed=processed,
            cost_cents=cost,
            payload={"verified_accounts": processed, "accounts_failed": failed},
        )

    async def _verify_isolated(
        self, account_entity_id: EntityId, scope: WorkspaceScope, use_gate: UseGate | None
    ) -> _AccountVerification:
        # The per-account isolation boundary: one account's fault must not sink the batch (the same
        # coverage-confidence policy the DEEP handler owns).
        try:
            cost = await self._verify_account(account_entity_id, scope, use_gate)
        except Exception:  # noqa: BLE001 — isolate one account; record failed and continue
            return _AccountVerification(cost_cents=Decimal(0), succeeded=False)
        return _AccountVerification(cost_cents=cost, succeeded=True)

    async def _entities_for(self, account_entity_id: EntityId) -> list[EntityId]:
        """The account plus its committee contacts (when a contact resolver is wired) — the entities
        whose claims this account's verification covers."""
        entity_ids = [account_entity_id]
        if self._contact_resolver is not None:
            entity_ids.extend(await self._contact_resolver(account_entity_id))
        return entity_ids

    async def _load_all(self, entity_ids: Sequence[EntityId], scope: WorkspaceScope) -> list[Claim]:
        claims: list[Claim] = []
        for entity_id in entity_ids:
            claims.extend(await self._load_claims(entity_id, scope))
        return claims

    async def _verify_account(
        self, account_entity_id: EntityId, scope: WorkspaceScope, use_gate: UseGate | None
    ) -> CostCents:
        """Run the gate chain over an account + its committee contacts' live claims; return judge
        spend."""
        entity_ids = await self._entities_for(account_entity_id)
        claims = await self._load_all(entity_ids, scope)

        # 1. corroboration (M9.2) — once per distinct (entity, field); promotes tier≤3.
        corroborated: set[tuple[EntityId, str]] = set()
        for claim in claims:
            key = (claim.entity_id, str(claim.field_key))
            if key in corroborated:
                continue
            corroborated.add(key)
            await self._corroborator.evaluate(
                claim.entity_id, claim.field_key, scope=scope, entity_type=claim.entity_type
            )

        # 2. faithfulness (M9.3) — every live tier-4 claim; the judge drives verification_status.
        cost = Decimal(0)
        for claim in claims:
            if claim.source_tier == 4:
                result = await self._judge.judge(claim)
                cost += result.cost_cents

        # 3. identity-binding (M9.4) is structural (born immutable at insert) — no runtime step.

        # 4. use gate (M10.3) LAST — appropriateness verdict on each personal-hook claim.
        if use_gate is not None:
            for claim in claims:
                if str(claim.field_key).startswith(_FACET_PREFIX):
                    await use_gate.evaluate(claim)

        # 5. verification-health (Doc C §6) — per-field tier-4 pass-rate over the POST-judge claims
        #    (reload so the status reflects the verdicts just written).
        fresh = await self._load_all(entity_ids, scope)
        record_synthesis_health([c for c in fresh if c.source_tier == 4], sink=self._health_sink)
        return cost


# Static-time conformance (mirrors the DEEP handler): the registered handler must satisfy
# ``core.PhaseHandler``. The real Corroborator's conformance to ``ClaimCorroborator`` is asserted at
# the composition root, where the concrete is imported.
_HANDLER_IS_A_PHASE_HANDLER: type[PhaseHandler] = VerificationPhaseHandler
