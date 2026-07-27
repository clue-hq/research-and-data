"""C7.2 API-root derived-claim orchestration against live Postgres."""

from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy import text

from clue_api.research_derivations import (
    DerivedClaimPolicy,
    DerivedClaimProposal,
    DerivedClaimService,
)
from clue_core import (
    Claim,
    ClaimFlavor,
    Completion,
    EmbeddingResult,
    EntityId,
    EntityType,
    ExtractionMethod,
    Message,
    OperationId,
    ResearchMode,
    ResearchSubjectRef,
    ResearchSupportRef,
    ResearchSupportRole,
    VerificationStatus,
    new_entity_id,
    new_operation_id,
    new_run_id,
)
from clue_research.claimstore import (
    DerivationDependencyResolver,
    DerivationDependencyState,
    WorkspaceScope,
    claims_by_ids,
    current_value,
    insert_claim,
    supersede_claim,
)
from clue_research.verification import EntailmentJudgeImpl
from tests._workspace import seed_workspace
from tests.profiling.conftest import conn_session_factory, rollback_conn

from .conftest import run_async

pytestmark = pytest.mark.usefixtures("require_profiling_db")

WORKSPACE = "c7-derivations"


class FakeGateway:
    def __init__(self, reply: str, *, raises: bool = False) -> None:
        self.reply = reply
        self.raises = raises
        self.calls: list[tuple[str, list[Message]]] = []

    def complete(self, *, model: str, messages: list[Message], **opts: object) -> Completion:
        self.calls.append((model, messages))
        if self.raises:
            raise RuntimeError("judge unavailable")
        return Completion(
            model="fallback/entailment",
            text=self.reply,
            cost_cents=Decimal("0.6"),
        )

    def embed(self, *, model: str, inputs: list[str]) -> EmbeddingResult:  # pragma: no cover
        raise NotImplementedError


def _support(
    entity_id: EntityId,
    *,
    confidence: float = 0.62,
    amount: int = 25_000_000,
    status: VerificationStatus = VerificationStatus.VERIFIED,
) -> Claim:
    return Claim(
        entity_id=entity_id,
        entity_type=EntityType.ACCOUNT,
        field_key="account.recent_funding",
        value_json={"amount_usd": amount, "round": "B"},
        source_tier=1,
        extraction_method=ExtractionMethod.API,
        source_url="https://registry.example/funding",
        confidence=confidence,
        run_id=new_run_id(),
        research_mode=ResearchMode.ACCOUNT_PROFILING,
        verification_status=status,
    )


def _derived(entity_id: EntityId) -> Claim:
    return Claim(
        entity_id=entity_id,
        entity_type=EntityType.ACCOUNT,
        field_key="account.strategic_moves",
        value_json="the new funding creates a near-term transformation window",
        source_tier=4,
        extraction_method=ExtractionMethod.LLM_SYNTHESIS,
        confidence=1.0,  # proposal value is ignored; the engine propagates conservative confidence
        run_id=new_run_id(),
        research_mode=ResearchMode.ACCOUNT_PROFILING,
        claim_flavor=ClaimFlavor.DERIVED,
    )


def _pain_support(entity_id: EntityId, *, confidence: float = 0.55) -> Claim:
    return Claim(
        entity_id=entity_id,
        entity_type=EntityType.ACCOUNT,
        field_key="account.operational_pain",
        value_json="manual campaign research delays launch",
        source_tier=2,
        extraction_method=ExtractionMethod.SCRAPE,
        source_url="https://official.example/operations",
        evidence_span="The research team spends weeks assembling each campaign brief.",
        confidence=confidence,
        run_id=new_run_id(),
        research_mode=ResearchMode.ACCOUNT_PROFILING,
        verification_status=VerificationStatus.VERIFIED,
    )


def _proposal(
    derived: Claim,
    support: Claim,
    *,
    additional_supports: tuple[Claim, ...] = (),
    operation_id: OperationId | None = None,
) -> DerivedClaimProposal:
    support_refs = [
        ResearchSupportRef(
            claim_id=support.id,
            role=ResearchSupportRole.DIRECT_EVIDENCE,
            ordinal=0,
        )
    ]
    support_refs.extend(
        ResearchSupportRef(
            claim_id=additional.id,
            role=ResearchSupportRole.CORROBORATION,
            ordinal=ordinal,
        )
        for ordinal, additional in enumerate(additional_supports, start=1)
    )
    return DerivedClaimProposal(
        workspace_id=WORKSPACE,
        operation_id=operation_id or new_operation_id(),
        target=ResearchSubjectRef(
            entity_id=derived.entity_id,
            entity_type=EntityType.ACCOUNT,
            canonical_entity_version=1,
        ),
        derived_claim=derived,
        supports=tuple(support_refs),
    )


def test_supported_derivation_is_atomic_idempotent_and_not_current_truth() -> None:
    async def _run() -> None:
        async with rollback_conn() as conn:
            await seed_workspace(conn, WORKSPACE)
            entity_id = new_entity_id()
            support = _support(entity_id)
            pain = _pain_support(entity_id)
            await insert_claim(conn, support)
            await insert_claim(conn, pain)
            derived = _derived(entity_id)
            proposal = _proposal(derived, support, additional_supports=(pain,))
            gateway = FakeGateway(
                '{"verdict":"supported","confidence":0.91,"reason_codes":["entailed"]}'
            )
            factory = conn_session_factory(conn)
            service = DerivedClaimService(
                judge=EntailmentJudgeImpl(gateway=gateway, conn_factory=factory),
                policy=DerivedClaimPolicy(
                    version=3,
                    entailment_threshold=0.7,
                    confidence_ceiling=0.85,
                ),
                conn_factory=factory,
            )

            result = await service.derive(proposal)
            assert result.accepted
            assert result.confidence == pytest.approx(0.55)
            assert result.derived_claim_id == derived.id
            assert len(gateway.calls) == 1

            # Retry resolves the original operation and makes no second model call or row.
            assert await service.derive(proposal) == result
            assert len(gateway.calls) == 1
            counts = (
                await conn.execute(
                    text(
                        """
                        SELECT
                            (SELECT count(*) FROM claim_derivation
                             WHERE derived_claim_id = :derived_id),
                            (SELECT count(*) FROM entailment_verdict
                             WHERE derived_claim_id = :derived_id)
                        """
                    ),
                    {"derived_id": derived.id},
                )
            ).one()
            assert counts == (2, 1)

            stored = (
                await claims_by_ids(
                    conn,
                    [derived.id],
                    scope=WorkspaceScope.for_workspace(WORKSPACE),
                )
            )[derived.id]
            assert stored.claim_flavor is ClaimFlavor.DERIVED
            assert stored.verification_status is VerificationStatus.VERIFIED
            assert stored.confidence == pytest.approx(0.55)
            # The factual merge still chooses the direct support, never the interpretation.
            merged = await current_value(
                conn,
                entity_id,
                "account.recent_funding",
                scope=WorkspaceScope.for_workspace(WORKSPACE),
            )
            assert merged is not None
            assert merged.provenance.claim_id == support.id
            assert (
                await current_value(
                    conn,
                    entity_id,
                    "account.strategic_moves",
                    scope=WorkspaceScope.for_workspace(WORKSPACE),
                )
                is None
            )

            resolver = DerivationDependencyResolver()
            live = await resolver.resolve(
                conn,
                derived.id,
                scope=WorkspaceScope.for_workspace(WORKSPACE),
            )
            assert live.state is DerivationDependencyState.ELIGIBLE_FRESH

            await conn.execute(
                text(
                    "UPDATE field_definition SET freshness_ttl = interval '0 seconds' "
                    "WHERE field_key = 'account.recent_funding'"
                )
            )
            stale = await resolver.resolve(
                conn,
                derived.id,
                scope=WorkspaceScope.for_workspace(WORKSPACE),
            )
            assert stale.state is DerivationDependencyState.STALE_RECHECK_REQUIRED
            await conn.execute(
                text(
                    "UPDATE field_definition SET freshness_ttl = interval '90 days' "
                    "WHERE field_key = 'account.recent_funding'"
                )
            )

            conflicting = _support(entity_id, amount=1_000_000)
            await insert_claim(conn, conflicting)
            review = await resolver.resolve(
                conn,
                derived.id,
                scope=WorkspaceScope.for_workspace(WORKSPACE),
            )
            assert review.state is DerivationDependencyState.REVIEW_REQUIRED
            await supersede_claim(
                conn,
                conflicting.id,
                _support(
                    entity_id,
                    amount=1_000_000,
                    status=VerificationStatus.REJECTED,
                ),
            )

            await conn.execute(
                text(
                    """
                    INSERT INTO lawful_basis_record
                        (claim_id, lawful_basis, regime, retention_until)
                    VALUES (:claim_id, 'legitimate_interest', 'gdpr', now() - interval '1 second')
                    """
                ),
                {"claim_id": support.id},
            )
            expired = await resolver.resolve(
                conn,
                derived.id,
                scope=WorkspaceScope.for_workspace(WORKSPACE),
            )
            assert expired.state is DerivationDependencyState.UNAVAILABLE
            assert any("superseded_or_expired" in reason for reason in expired.reason_codes)
            await conn.execute(
                text("DELETE FROM lawful_basis_record WHERE claim_id = :claim_id"),
                {"claim_id": support.id},
            )

            replacement = _support(entity_id, confidence=0.9)
            await supersede_claim(conn, support.id, replacement)
            invalidated = await resolver.resolve(
                conn,
                derived.id,
                scope=WorkspaceScope.for_workspace(WORKSPACE),
            )
            assert invalidated.state is DerivationDependencyState.UNAVAILABLE
            assert any("superseded_or_expired" in reason for reason in invalidated.reason_codes)

            # Force the deferred DB proof now: claim + edge + verdict are transaction-complete.
            await conn.execute(text("SET CONSTRAINTS derived_claim_has_lineage IMMEDIATE"))

    run_async(_run())


@pytest.mark.parametrize(
    ("reply", "raises", "expected_verdict"),
    [
        (
            '{"verdict":"unsupported","confidence":0.2,"reason_codes":["not_entailed"]}',
            False,
            "unsupported",
        ),
        ("not-json", False, "unsupported"),
        ("", True, "error"),
    ],
)
def test_unsupported_malformed_and_error_never_promote(
    reply: str,
    raises: bool,
    expected_verdict: str,
) -> None:
    async def _run() -> None:
        async with rollback_conn() as conn:
            await seed_workspace(conn, WORKSPACE)
            entity_id = new_entity_id()
            support = _support(entity_id)
            await insert_claim(conn, support)
            derived = _derived(entity_id)
            gateway = FakeGateway(reply, raises=raises)
            factory = conn_session_factory(conn)
            result = await DerivedClaimService(
                judge=EntailmentJudgeImpl(gateway=gateway, conn_factory=factory),
                conn_factory=factory,
            ).derive(_proposal(derived, support))

            assert not result.accepted
            assert result.verdict.value == expected_verdict
            stored = (
                await claims_by_ids(
                    conn,
                    [derived.id],
                    scope=WorkspaceScope.for_workspace(WORKSPACE),
                )
            )[derived.id]
            assert stored.verification_status is VerificationStatus.REJECTED
            merged = await current_value(
                conn,
                entity_id,
                "account.recent_funding",
                scope=WorkspaceScope.for_workspace(WORKSPACE),
            )
            assert merged is not None
            assert merged.provenance.claim_id == support.id
            await conn.execute(text("SET CONSTRAINTS derived_claim_has_lineage IMMEDIATE"))

    run_async(_run())
