"""The ``ProjectPhase.VERIFICATION`` handler (integration keystone) — driven entirely by fakes (no
DB). These prove the handler *policy*: it drives the frozen ``VERIFICATION_GATE_ORDER`` over each
high-tier account's claims in order — corroboration (per ``(entity, field)``) → faithfulness
(direct tier-4 claims; C7 derivations use entailment) → use-gate (``contact.facet.*`` claims)
**last** — records per-field
verification-health, isolates a single failing account so the batch survives, and is a clean no-op
on an empty set. The end-to-end "a judge-rejected tier-4 claim is absent from ``current_value``"
proof is a DB-gated integration test (the merge enforces it via ``require_verified_tier4``); here we
prove the handler routes every direct tier-4 claim through the faithfulness judge without
double-judging derived claims.
"""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from decimal import Decimal

import pytest

from clue_api.verification import (
    VerificationPhaseHandler,
    build_verification_phase_handler,
)
from clue_api.verification.handler import (
    ClaimLoader,
    ContactResolver,
    UseGateProvider,
    VerificationAccountResolver,
)
from clue_core import (
    Claim,
    ClaimFlavor,
    EntityId,
    EntityType,
    ExtractionMethod,
    IdentityBinding,
    PhaseContext,
    PhaseHandler,
    PhaseStatus,
    ProjectPhase,
    ResearchMode,
    UseClass,
    account_claim,
    contact_claim,
    new_entity_id,
    new_project_run_id,
    new_run_id,
)
from clue_core.compliance import UseDecision
from clue_core.enums import JudgeVerdict, UseReason
from clue_core.gateway import Completion, Message
from clue_core.verification import JudgeResult
from clue_obs.otel.metrics import METRIC_TIER4_TOTAL, InMemorySink
from clue_research.claimstore import WorkspaceScope
from clue_research.durable import AccountSpec, PhaseHandlerRegistry

_PAIN = "account.operational_pain"
_MOVES = "account.strategic_moves"
_FACET = "contact.facet.marathon"
_CLIENT = "client-acme"

# --- fakes (record call order + args) ---------------------------------------


class _Recorder:
    def __init__(self) -> None:
        self.log: list[tuple[str, str]] = []

    def steps(self, kind: str) -> list[int]:
        return [i for i, (k, _) in enumerate(self.log) if k == kind]


class FakeCorroborator:
    """Satisfies the handler's ``ClaimCorroborator`` seam (M9.2)."""

    def __init__(self, rec: _Recorder) -> None:
        self._rec = rec
        self.calls: list[tuple[EntityId, str]] = []

    async def evaluate(
        self,
        entity_id: EntityId,
        field_key: object,
        *,
        scope: WorkspaceScope,
        entity_type: object = None,
    ) -> object:
        self._rec.log.append(("corroborate", str(field_key)))
        self.calls.append((entity_id, str(field_key)))
        return None


class FakeJudge:
    """Satisfies ``core.verification.FaithfulnessJudge`` (M9.3). A spanned claim is SUPPORTED, a
    span-less one UNSUPPORTED (the structural rule), each at a fixed cost so the handler aggregates
    spend."""

    def __init__(self, rec: _Recorder, *, cost: Decimal = Decimal("2")) -> None:
        self._rec = rec
        self._cost = cost
        self.judged: list[str] = []

    async def judge(self, claim: Claim) -> JudgeResult:
        self._rec.log.append(("judge", str(claim.field_key)))
        self.judged.append(str(claim.field_key))
        supported = bool(claim.evidence_span)
        return JudgeResult(
            claim_id=claim.id,
            verdict=JudgeVerdict.SUPPORTED if supported else JudgeVerdict.UNSUPPORTED,
            score=1.0 if supported else 0.0,
            cost_cents=self._cost,
        )


class FakeUseGate:
    """Satisfies ``core.compliance.UseGate`` (M10.3)."""

    def __init__(self, rec: _Recorder) -> None:
        self._rec = rec
        self.evaluated: list[str] = []

    async def evaluate(self, claim: Claim) -> UseDecision:
        self._rec.log.append(("use_gate", str(claim.field_key)))
        self.evaluated.append(str(claim.field_key))
        return UseDecision(
            claim_id=claim.id,
            usable_for_outreach=True,
            reason=UseReason.ALLOWED,
            policy_version=1,
        )


class FakeGateway:
    """A never-called ``LLMGateway`` (the production judge needs one; fakes replace the judge)."""

    def complete(self, *, model: str, messages: Sequence[Message], **opts: object) -> Completion:
        raise NotImplementedError

    def embed(self, *, model: str, inputs: Sequence[str]) -> object:
        raise NotImplementedError


# --- builders ----------------------------------------------------------------


def _resolver(specs: Sequence[AccountSpec]) -> VerificationAccountResolver:
    async def _r(ctx: PhaseContext) -> Sequence[AccountSpec]:
        return specs

    return _r


def _loader(
    by_entity: dict[EntityId, list[Claim]], *, raise_for: EntityId | None = None
) -> ClaimLoader:
    async def _l(entity_id: EntityId, scope: WorkspaceScope) -> Sequence[Claim]:
        if raise_for is not None and entity_id == raise_for:
            raise RuntimeError("boom — claim load failed for this account")
        return by_entity.get(entity_id, [])

    return _l


def _spec(entity_id: EntityId) -> AccountSpec:
    return AccountSpec(entity_id=entity_id, tier="top", workspace_id=_CLIENT)


def _ctx(campaign: object | None = None) -> PhaseContext:
    return PhaseContext(
        project_run_id=campaign or new_project_run_id(),
        project_id="prj-test",
        brand_id="brd-test",
        phase=ProjectPhase.VERIFICATION,
        workspace_id=_CLIENT,
        icp_key="icp-1",
        icp_version=1,
    )


def _acct(field_key: str, tier: int, entity_id: EntityId, *, span: str | None = "ev") -> Claim:
    return account_claim(
        entity_id=entity_id,
        field_key=field_key,
        value_json="a synthesized value about Acme Corp",
        source_tier=tier,
        extraction_method=ExtractionMethod.LLM_SYNTHESIS if tier == 4 else ExtractionMethod.SCRAPE,
        confidence=0.9,
        run_id=new_run_id(),
        research_mode=ResearchMode.ACCOUNT_PROFILING,
        source_url="https://acme.com/eng",
        evidence_span=span,
    )


def _facet(entity_id: EntityId, *, field_key: str = _FACET) -> Claim:
    return contact_claim(
        entity_id=entity_id,
        field_key=field_key,
        value_json="ran the Boston marathon",
        source_tier=4,
        extraction_method=ExtractionMethod.LLM_SYNTHESIS,
        confidence=0.9,
        run_id=new_run_id(),
        research_mode=ResearchMode.ACCOUNT_PROFILING,
        identity_binding=IdentityBinding.STRONG,
        use_class=UseClass.PERSONAL_PUBLIC_NON_SENSITIVE,
        source_url="https://linkedin.com/in/x",
        evidence_span="ran the Boston marathon",
    )


def _derived(entity_id: EntityId) -> Claim:
    return Claim(
        entity_id=entity_id,
        entity_type=EntityType.ACCOUNT,
        field_key=_MOVES,
        value_json="a supported interpretation about Acme Corp",
        source_tier=4,
        extraction_method=ExtractionMethod.LLM_SYNTHESIS,
        confidence=0.8,
        run_id=new_run_id(),
        research_mode=ResearchMode.ACCOUNT_PROFILING,
        claim_flavor=ClaimFlavor.DERIVED,
    )


def _use_gate_provider(use_gate: FakeUseGate | None) -> UseGateProvider | None:
    if use_gate is None:
        return None

    async def _provide(workspace_id: str) -> FakeUseGate:
        return use_gate

    return _provide


def _contact_resolver(
    contacts: dict[EntityId, list[EntityId]],
) -> ContactResolver:
    async def _resolve(account_entity_id: EntityId) -> Sequence[EntityId]:
        return contacts.get(account_entity_id, [])

    return _resolve


def _handler(
    *,
    specs: Sequence[AccountSpec],
    by_entity: dict[EntityId, list[Claim]],
    rec: _Recorder,
    use_gate: FakeUseGate | None,
    contact_resolver: ContactResolver | None = None,
    raise_for: EntityId | None = None,
    sink: InMemorySink | None = None,
) -> VerificationPhaseHandler:
    return VerificationPhaseHandler(
        account_resolver=_resolver(specs),
        load_claims=_loader(by_entity, raise_for=raise_for),
        corroborator=FakeCorroborator(rec),
        judge=FakeJudge(rec),
        contact_resolver=contact_resolver,
        use_gate_provider=_use_gate_provider(use_gate),
        health_sink=sink,
    )


# --- tests -------------------------------------------------------------------


def test_handler_conforms_to_protocol_and_registers() -> None:
    rec = _Recorder()
    handler = _handler(specs=(), by_entity={}, rec=rec, use_gate=FakeUseGate(rec))
    assert isinstance(handler, PhaseHandler)
    assert handler.phase is ProjectPhase.VERIFICATION
    registry = PhaseHandlerRegistry()
    assert registry.get(ProjectPhase.VERIFICATION) is None
    registry.register(handler)
    assert registry.get(ProjectPhase.VERIFICATION) is handler


def test_runs_full_gate_chain_with_use_gate_last() -> None:
    rec = _Recorder()
    e1 = new_entity_id()
    use_gate = FakeUseGate(rec)
    handler = _handler(
        specs=(_spec(e1),),
        by_entity={e1: [_acct(_PAIN, 4, e1), _acct(_MOVES, 3, e1), _facet(e1)]},
        rec=rec,
        use_gate=use_gate,
    )

    async def _run() -> None:
        result = await handler.run(_ctx())
        assert result.status is PhaseStatus.COMPLETED
        assert result.accounts_processed == 1
        # corroboration of every (entity, field), then the judge, then the use-gate — strict order.
        corr, judge, gate = rec.steps("corroborate"), rec.steps("judge"), rec.steps("use_gate")
        assert corr and judge and gate
        assert max(corr) < min(judge), "corroboration must precede faithfulness"
        assert max(judge) < min(gate), "the use-gate (M10.3) must run LAST — after the judge"

    asyncio.run(_run())


def test_disabled_verification_calls_no_corroborator_or_judge_but_keeps_use_gate() -> None:
    rec = _Recorder()
    account, contact = new_entity_id(), new_entity_id()
    use_gate = FakeUseGate(rec)
    handler = VerificationPhaseHandler(
        account_resolver=_resolver((_spec(account),)),
        load_claims=_loader({account: [_acct(_PAIN, 4, account)], contact: [_facet(contact)]}),
        corroborator=None,
        judge=None,
        verification_enabled=False,
        contact_resolver=_contact_resolver({account: [contact]}),
        use_gate_provider=_use_gate_provider(use_gate),
    )

    async def _run() -> None:
        result = await handler.run(_ctx())
        assert result.status is PhaseStatus.COMPLETED
        assert result.accounts_processed == 1
        assert result.cost_cents == Decimal(0)
        assert not rec.steps("corroborate")
        assert not rec.steps("judge")
        assert use_gate.evaluated == [_FACET]
        assert result.payload == {
            "verification_enabled": False,
            "verified_accounts": 0,
            "accounts_skipped": 1,
            "accounts_failed": 0,
        }

    asyncio.run(_run())


def test_disabled_verification_without_use_gate_does_not_load_claims() -> None:
    account = new_entity_id()
    handler = VerificationPhaseHandler(
        account_resolver=_resolver((_spec(account),)),
        load_claims=_loader({}, raise_for=account),
        corroborator=None,
        judge=None,
        verification_enabled=False,
        use_gate_provider=None,
    )

    async def _run() -> None:
        result = await handler.run(_ctx())
        assert result.status is PhaseStatus.COMPLETED
        assert result.accounts_processed == 1
        assert result.payload["accounts_skipped"] == 1

    asyncio.run(_run())


def test_judges_every_tier4_claim_and_no_lower_tier() -> None:
    rec = _Recorder()
    e1 = new_entity_id()
    judge = FakeJudge(rec)
    handler = VerificationPhaseHandler(
        account_resolver=_resolver((_spec(e1),)),
        load_claims=_loader({e1: [_acct(_PAIN, 4, e1), _acct(_MOVES, 3, e1)]}),
        corroborator=FakeCorroborator(rec),
        judge=judge,
        use_gate_provider=None,
    )

    async def _run() -> None:
        await handler.run(_ctx())
        # the tier-4 synthesis claim is judged; the tier-3 claim is NOT (corroboration's job)
        assert judge.judged == [_PAIN]

    asyncio.run(_run())


def test_faithfulness_skips_derived_claims_owned_by_entailment() -> None:
    rec = _Recorder()
    entity_id = new_entity_id()
    judge = FakeJudge(rec)
    handler = VerificationPhaseHandler(
        account_resolver=_resolver((_spec(entity_id),)),
        load_claims=_loader({entity_id: [_acct(_PAIN, 4, entity_id), _derived(entity_id)]}),
        corroborator=FakeCorroborator(rec),
        judge=judge,
        use_gate_provider=None,
    )

    async def _run() -> None:
        await handler.run(_ctx())
        assert judge.judged == [_PAIN]

    asyncio.run(_run())


def test_use_gate_runs_only_on_facet_claims() -> None:
    rec = _Recorder()
    e1 = new_entity_id()
    use_gate = FakeUseGate(rec)
    handler = _handler(
        specs=(_spec(e1),),
        by_entity={e1: [_acct(_PAIN, 4, e1), _facet(e1)]},
        rec=rec,
        use_gate=use_gate,
    )

    async def _run() -> None:
        await handler.run(_ctx())
        # only the contact.facet.* claim is use-gated; the account synthesis claim is not personal.
        assert use_gate.evaluated == [_FACET]

    asyncio.run(_run())


def test_committee_contacts_are_sourced_and_their_facets_governed() -> None:
    # The follow-on: with a contact resolver wired, the account's committee CONTACT entities are
    # pulled in and their contact.facet.* hooks go through corroboration → judge → use-gate — the
    # personal-data leg the production handler runs.
    rec = _Recorder()
    account, contact = new_entity_id(), new_entity_id()
    use_gate = FakeUseGate(rec)
    handler = _handler(
        specs=(_spec(account),),
        by_entity={account: [_acct(_PAIN, 4, account)], contact: [_facet(contact)]},
        rec=rec,
        use_gate=use_gate,
        contact_resolver=_contact_resolver({account: [contact]}),
    )

    async def _run() -> None:
        result = await handler.run(_ctx())
        assert result.accounts_processed == 1
        # the contact's facet hook went through the full chain: corroborate → judge → use-gate.
        assert ("corroborate", _FACET) in rec.log
        assert ("judge", _FACET) in rec.log  # the facet claim is tier-4 → judged
        assert use_gate.evaluated == [_FACET]
        # and the account's own field was still verified in the same pass.
        assert ("corroborate", _PAIN) in rec.log
        assert ("judge", _PAIN) in rec.log

    asyncio.run(_run())


def test_no_span_tier4_claim_is_still_routed_through_the_judge() -> None:
    # The fabrication trap: a tier-4 claim with no evidence span must reach the judge (which fails
    # it safe to unsupported) — it can never silently bypass verification into current_value.
    rec = _Recorder()
    e1 = new_entity_id()
    judge = FakeJudge(rec)
    handler = VerificationPhaseHandler(
        account_resolver=_resolver((_spec(e1),)),
        load_claims=_loader({e1: [_acct(_PAIN, 4, e1, span=None)]}),
        corroborator=FakeCorroborator(rec),
        judge=judge,
        use_gate_provider=None,
    )

    async def _run() -> None:
        await handler.run(_ctx())
        assert judge.judged == [_PAIN]

    asyncio.run(_run())


def test_one_account_raising_is_isolated_and_batch_survives() -> None:
    rec = _Recorder()
    e1, e2 = new_entity_id(), new_entity_id()
    handler = _handler(
        specs=(_spec(e1), _spec(e2)),
        by_entity={e1: [_acct(_PAIN, 4, e1)], e2: [_acct(_PAIN, 4, e2)]},
        rec=rec,
        use_gate=None,
        raise_for=e1,
    )

    async def _run() -> None:
        result = await handler.run(_ctx())
        assert result.status is PhaseStatus.COMPLETED  # the batch survives
        assert result.accounts_processed == 1
        assert result.payload["accounts_failed"] == 1
        assert result.payload["verified_accounts"] == 1

    asyncio.run(_run())


def test_empty_account_set_is_a_completed_no_op() -> None:
    rec = _Recorder()
    handler = _handler(specs=(), by_entity={}, rec=rec, use_gate=None)

    async def _run() -> None:
        result = await handler.run(_ctx())
        assert result.status is PhaseStatus.COMPLETED
        assert result.accounts_processed == 0
        assert result.cost_cents == Decimal(0)
        assert not rec.log  # nothing was gated

    asyncio.run(_run())


def test_cost_aggregates_judge_spend() -> None:
    rec = _Recorder()
    e1 = new_entity_id()
    handler = _handler(
        specs=(_spec(e1),),
        by_entity={e1: [_acct(_PAIN, 4, e1), _acct(_MOVES, 4, e1)]},  # two tier-4 claims @ 2 cents
        rec=rec,
        use_gate=None,
    )

    async def _run() -> None:
        result = await handler.run(_ctx())
        assert result.cost_cents == Decimal("4")

    asyncio.run(_run())


def test_per_field_verification_health_is_emitted() -> None:
    rec = _Recorder()
    e1 = new_entity_id()
    sink = InMemorySink()
    handler = _handler(
        specs=(_spec(e1),),
        by_entity={e1: [_acct(_PAIN, 4, e1), _acct(_MOVES, 3, e1)]},
        rec=rec,
        use_gate=None,
        sink=sink,
    )

    async def _run() -> None:
        await handler.run(_ctx())
        # the tier-4 synthesis field is counted; the tier-3 field is not (judge governs tier-4).
        assert sink.counters.get((METRIC_TIER4_TOTAL, (("field_key", _PAIN),))) == 1
        assert sink.counters.get((METRIC_TIER4_TOTAL, (("field_key", _MOVES),))) is None

    asyncio.run(_run())


def test_use_gate_optional_when_unwired() -> None:
    # With no use-gate injected (the production v1 default), a facet claim is simply not use-gated —
    # the handler still completes the accuracy gates without error.
    rec = _Recorder()
    e1 = new_entity_id()
    handler = _handler(
        specs=(_spec(e1),),
        by_entity={e1: [_acct(_PAIN, 4, e1), _facet(e1)]},
        rec=rec,
        use_gate=None,
    )

    async def _run() -> None:
        result = await handler.run(_ctx())
        assert result.status is PhaseStatus.COMPLETED
        assert not rec.steps("use_gate")

    asyncio.run(_run())


def test_build_verification_phase_handler_wires_the_concrete_seams() -> None:
    # The composition smoke: build with a (never-called) gateway + a fake resolver constructs the
    # real Corroborator + FaithfulnessJudgeImpl without a DB, yielding a VERIFICATION handler.
    handler = build_verification_phase_handler(
        gateway=FakeGateway(),
        account_resolver=_resolver(()),
    )
    assert isinstance(handler, PhaseHandler)
    assert handler.phase is ProjectPhase.VERIFICATION


def test_build_disabled_verification_handler_needs_no_gateway() -> None:
    handler = build_verification_phase_handler(
        gateway=None,
        account_resolver=_resolver(()),
        verification_enabled=False,
    )
    assert isinstance(handler, PhaseHandler)
    assert handler.phase is ProjectPhase.VERIFICATION


def test_build_enabled_verification_handler_requires_gateway() -> None:
    with pytest.raises(ValueError, match="enabled verification requires an LLM gateway"):
        build_verification_phase_handler(
            gateway=None,
            account_resolver=_resolver(()),
        )
