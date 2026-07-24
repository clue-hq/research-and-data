"""End-to-end DB governance proof (the M10×M11×M12 integration's negative assertions).

These run the **real** governance components — the M9.3 faithfulness judge, the M9.4 weak-binding
merge exclusion, the M10.3 use-gate, and the M10.5 retention sweep over the M9.5 freshness engine —
against a live Postgres and assert what the M12 handoff actually reads (``current_value`` and the
``is_outreach_promotable`` composite) **excludes** the ungoverned claim. Each is a cross-milestone
assertion no single isolated branch could make: it needs the producer, the gate, and the reader
composed on one database. Skips without a DB (like the rest of the compliance suite).

The architecture's core bet, proven on a real DB: a fabricated / misattributed / inappropriate /
expired / objected personal claim cannot reach the subsystem's output boundary.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_core import (
    AccountStatus,
    Claim,
    Completion,
    EntityId,
    ExtractionMethod,
    IdentityBinding,
    Message,
    ResearchMode,
    UseClass,
    UseReason,
    account_claim,
    contact_claim,
    new_run_id,
)
from clue_core.compliance import is_outreach_promotable
from clue_research.claimstore import WorkspaceScope, current_value, insert_claim
from clue_research.compliance import DataSubjectRightsImpl, RetentionSweep, UseGateImpl
from clue_research.identity import insert_account_entity, insert_contact_entity, stamp_reuse
from clue_research.verification import FaithfulnessJudgeImpl, FreshnessImpl
from tests._workspace import seed_workspace

from .conftest import rollback_conn, run_async

pytestmark = pytest.mark.usefixtures("require_compliance_db")

_CLIENT = "client-acme"
_SCOPE = WorkspaceScope.for_workspace(_CLIENT)
_PAIN = "account.operational_pain"  # tier-4 synthesis field (core pack)
_FACET = "contact.facet.test_hook"  # governed personal hook (compliance test pack, 90d freshness)

_SUPPORTED = '{"verdict": "supported", "score": 0.92, "rationale": "the span states the value"}'
_UNSUPPORTED = (
    '{"verdict": "unsupported", "score": 0.06, "rationale": "the span does not state it"}'
)


# --- a deterministic fake gateway for the judge (records calls; canned JSON) -------


class FakeGateway:
    def __init__(self, response_text: str) -> None:
        self._response = response_text
        self.calls: list[str] = []

    def complete(self, *, model: str, messages: list[Message], **opts: object) -> Completion:
        self.calls.append(model)
        return Completion(
            model=model, text=self._response, cost_cents=Decimal("0.5"), finish_reason="stop"
        )

    def embed(self, *, model: str, inputs: list[str]) -> object:  # pragma: no cover — unused
        raise NotImplementedError


def _factory(conn: AsyncConnection) -> Callable[[], AbstractAsyncContextManager[AsyncConnection]]:
    @asynccontextmanager
    async def factory() -> AsyncIterator[AsyncConnection]:
        yield conn

    return factory


def _judge(conn: AsyncConnection, gateway: FakeGateway) -> FaithfulnessJudgeImpl:
    return FaithfulnessJudgeImpl(gateway=gateway, conn_factory=_factory(conn))


def _use_gate(conn: AsyncConnection) -> UseGateImpl:
    return UseGateImpl(_CLIENT, conn_factory=_factory(conn))


def _sweep(conn: AsyncConnection) -> RetentionSweep:
    return RetentionSweep(FreshnessImpl(conn_factory=_factory(conn)), conn_factory=_factory(conn))


def _rights(conn: AsyncConnection) -> DataSubjectRightsImpl:
    return DataSubjectRightsImpl(_CLIENT, conn_factory=_factory(conn))


async def _account(conn: AsyncConnection) -> EntityId:
    await seed_workspace(conn, _CLIENT)
    return await insert_account_entity(
        conn,
        canonical_name="Acme",
        primary_domain="acme.com",
        status=AccountStatus.ACTIVE,
        workspace_id=_CLIENT,
    )


async def _contact(conn: AsyncConnection, account_id: EntityId) -> EntityId:
    return await insert_contact_entity(
        conn, account_entity_id=account_id, full_name="Jana Doe", status=AccountStatus.ACTIVE
    )


def _synth(entity: EntityId, *, value: str = "Acme is buckling under on-call burnout") -> Claim:
    return account_claim(
        entity_id=entity,
        field_key=_PAIN,
        value_json=value,
        source_tier=4,
        extraction_method=ExtractionMethod.LLM_SYNTHESIS,
        confidence=0.9,
        run_id=new_run_id(),
        research_mode=ResearchMode.ACCOUNT_PROFILING,
        source_url="https://news.example/acme",
        evidence_span="engineers describe relentless on-call burnout",
    )


def _facet(
    contact: EntityId,
    *,
    use_class: UseClass,
    binding: IdentityBinding = IdentityBinding.STRONG,
    observed_at: datetime | None = None,
) -> Claim:
    claim = contact_claim(
        entity_id=contact,
        field_key=_FACET,
        value_json="ran the Berlin marathon",
        source_tier=2,
        extraction_method=ExtractionMethod.SCRAPE,
        confidence=0.9,
        run_id=new_run_id(),
        research_mode=ResearchMode.CONTACT_PROFILING,
        identity_binding=binding,
        use_class=use_class,
        source_url="https://www.linkedin.com/in/jana",
        evidence_span="Jana Doe ran the Berlin marathon in 2025.",
        observed_at=observed_at,
    )
    return stamp_reuse(claim, workspace_id=_CLIENT)


# --- A. M9.3 × M1.2: a fabricated tier-4 synthesis claim never reaches current_value -------


def test_supported_tier4_synthesis_is_promoted_to_current_value() -> None:
    async def _run() -> None:
        async with rollback_conn() as conn:
            entity = await _account(conn)
            claim = _synth(entity)
            await insert_claim(conn, claim)
            # unverified tier-4 is excluded by the merge until the judge clears it …
            assert await current_value(conn, entity, _PAIN, scope=_SCOPE) is None
            await _judge(conn, FakeGateway(_SUPPORTED)).judge(claim)
            cv = await current_value(conn, entity, _PAIN, scope=_SCOPE)
            assert cv is not None and cv.value_json == claim.value_json

    run_async(_run())


def test_fabricated_tier4_synthesis_is_absent_from_current_value() -> None:
    async def _run() -> None:
        async with rollback_conn() as conn:
            entity = await _account(conn)
            claim = _synth(entity, value="Acme just IPO'd at a $9B valuation")  # not in the span
            await insert_claim(conn, claim)
            verdict = await _judge(conn, FakeGateway(_UNSUPPORTED)).judge(claim)
            assert verdict.verdict.value == "unsupported"
            # rejected by the judge → never surfaced as current truth.
            assert await current_value(conn, entity, _PAIN, scope=_SCOPE) is None

    run_async(_run())


def test_no_span_tier4_synthesis_is_absent_without_an_llm_call() -> None:
    async def _run() -> None:
        async with rollback_conn() as conn:
            entity = await _account(conn)
            claim = account_claim(
                entity_id=entity,
                field_key=_PAIN,
                value_json="unsupported guess",
                source_tier=4,
                extraction_method=ExtractionMethod.LLM_SYNTHESIS,
                confidence=0.9,
                run_id=new_run_id(),
                research_mode=ResearchMode.ACCOUNT_PROFILING,
                source_url="https://news.example/acme",
                evidence_span=None,  # no span — the structural kill switch
            )
            await insert_claim(conn, claim)
            gateway = FakeGateway(_SUPPORTED)  # would say supported IF ever called
            await _judge(conn, gateway).judge(claim)
            assert gateway.calls == []  # auto-unsupported, no spend
            assert await current_value(conn, entity, _PAIN, scope=_SCOPE) is None

    run_async(_run())


# --- B. M9.4 × M1.2: a weak-identity-binding contact claim never reaches current_value -----


def test_weak_binding_contact_claim_is_absent_from_current_value() -> None:
    async def _run() -> None:
        async with rollback_conn() as conn:
            account = await _account(conn)
            weak_c, strong_c = await _contact(conn, account), await _contact(conn, account)
            await insert_claim(
                conn,
                _facet(
                    weak_c, use_class=UseClass.PROFESSIONAL_PUBLIC, binding=IdentityBinding.WEAK
                ),
            )
            await insert_claim(
                conn,
                _facet(
                    strong_c, use_class=UseClass.PROFESSIONAL_PUBLIC, binding=IdentityBinding.STRONG
                ),
            )
            # the same-name trap: a weak-binding claim is excluded; the strong one is served.
            assert await current_value(conn, weak_c, _FACET, scope=_SCOPE) is None
            assert await current_value(conn, strong_c, _FACET, scope=_SCOPE) is not None

    run_async(_run())


# --- C. M10.3: a `sensitive` hook is never outreach-promotable under the default posture ----


def test_sensitive_facet_is_not_outreach_promotable() -> None:
    async def _run() -> None:
        async with rollback_conn() as conn:
            account = await _account(conn)
            contact = await _contact(conn, account)
            sensitive = _facet(contact, use_class=UseClass.SENSITIVE)
            await insert_claim(conn, sensitive)
            decision = await _use_gate(conn).evaluate(sensitive)
            # the hard floor: sensitive is locked regardless of jurisdiction/posture …
            assert decision.usable_for_outreach is False
            assert decision.reason is UseReason.SENSITIVE_LOCKED
            # … so the "clears both gates" composite is False even though the binding is strong.
            assert is_outreach_promotable(sensitive, decision) is False

    run_async(_run())


def test_professional_public_facet_is_outreach_promotable() -> None:
    async def _run() -> None:
        async with rollback_conn() as conn:
            account = await _account(conn)
            contact = await _contact(conn, account)
            pro = _facet(contact, use_class=UseClass.PROFESSIONAL_PUBLIC)
            await insert_claim(conn, pro)
            decision = await _use_gate(conn).evaluate(pro)
            assert decision.usable_for_outreach is True
            assert is_outreach_promotable(pro, decision) is True

    run_async(_run())


# --- D. M9.5 × M10.5 × M1.2: the tombstone-before-merge-read ordering invariant ------------


def test_retention_expired_sensitive_claim_is_tombstoned_before_the_handoff_read() -> None:
    # The documented [M9.5×M1.2/M10.5] gap, end-to-end: a 40-day sensitive facet is EXPIRED to its
    # 30-day retention horizon yet FRESH to the merge's 90-day field TTL — so it WOULD cross the
    # handoff until the M10.5 sweep tombstones it. Uses the REAL FreshnessImpl.due_for_age_out.
    async def _run() -> None:
        async with rollback_conn() as conn:
            account = await _account(conn)
            contact = await _contact(conn, account)
            aged = _facet(
                contact,
                use_class=UseClass.SENSITIVE,
                observed_at=datetime.now(UTC) - timedelta(days=40),
            )
            await insert_claim(conn, aged)
            # BEFORE the sweep: still fresh to the merge (40d < 90d field TTL) → it would be served.
            assert await current_value(conn, contact, _FACET, scope=_SCOPE) is not None
            # the sweep ages it out past the 30d sensitive retention horizon, scoped to the contact.
            result = await _sweep(conn).sweep_expired(entity_ids=(contact,))
            assert len(result.tombstoned_claim_ids) == 1
            # AFTER the sweep: tombstoned → the merge (and the M12 handoff) no longer serve it.
            assert await current_value(conn, contact, _FACET, scope=_SCOPE) is None

    run_async(_run())


# --- E. Art. 21 objection: an objected contact's hooks are tombstoned before the read ------


def test_objected_contact_hooks_are_tombstoned_before_the_handoff_read() -> None:
    async def _run() -> None:
        async with rollback_conn() as conn:
            account = await _account(conn)
            contact = await _contact(conn, account)
            await insert_claim(conn, _facet(contact, use_class=UseClass.PROFESSIONAL_PUBLIC))
            await _rights(conn).record_objection(contact)
            # a hook collected AFTER the objection was registered …
            await insert_claim(conn, _facet(contact, use_class=UseClass.PROFESSIONAL_PUBLIC))
            # … is re-suppressed by the objection sweep before the handoff reads the merge.
            await _sweep(conn).sweep_objections()
            assert await current_value(conn, contact, _FACET, scope=_SCOPE) is None

    run_async(_run())
