"""C2 contract tests for proposal staging, decisions, live promotion, and isolation."""

from __future__ import annotations

import asyncio
from decimal import Decimal
from uuid import uuid4

import pytest
from pydantic import ValidationError
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_config.proposals import ProposalPolicy
from clue_core import (
    EntityScope,
    FieldDef,
    Modality,
    PassKind,
    ReuseScope,
)
from clue_core.proposals import ProposalAuthority, ProposalStatus
from clue_db import db_lifespan
from clue_research.claimstore import get_field
from clue_research.proposals import (
    SENSITIVE_OUTREACH_DISABLED_GATE,
    FieldProposalPayload,
    ProposalDecision,
    ProposalScope,
    SourceManifestDraft,
    SourceProposalPayload,
    decide_field_proposal,
    decide_source_proposal,
    evaluate_source_demotion,
    get_field_proposal,
    get_source_proposal,
    propose_field,
    propose_source,
)
from clue_research.proposals.service import (
    ComplianceApprovalRequired,
    CredentialSetupRequired,
    InsufficientProposalAuthority,
)
from clue_research.proposals.store import (
    ProposalAlreadyDecided,
    ProposalNotFound,
    ProposalScopeError,
)
from clue_research.sources import get_source, sources_for
from clue_research.sources.source_yield import record_source_yield
from clue_spine import create_brand
from tests._workspace import seed_workspace
from tests.proposals.conftest import rollback_conn, run_async

pytestmark = pytest.mark.usefixtures("require_proposals_db")


async def _scope(conn: AsyncConnection, workspace_id: str = "proposal-ws") -> ProposalScope:
    await seed_workspace(conn, workspace_id)
    brand = await create_brand(conn, workspace_id=workspace_id, name=f"{workspace_id} brand")
    return ProposalScope(workspace_id=workspace_id, brand_id=brand.brand_id)


def _field_payload(key: str = "account.market_motion") -> FieldProposalPayload:
    return FieldProposalPayload(
        field_def=FieldDef(field_key=key, value_type="str", pass_kind=PassKind.DEEP),
        rationale="The current registry does not represent this account signal.",
        evidence_refs=("claim:source-gap",),
    )


def _source_payload(key: str = "industry_registry") -> SourceProposalPayload:
    return SourceProposalPayload(
        manifest=SourceManifestDraft(
            source_key=key,
            modality=Modality.TEXT,
            entity_scope=EntityScope.ACCOUNT,
            yields=("core",),
            cost_cents=Decimal("1.25"),
            provider="public_web",
            requires_adapter="generic_web_html",
        ),
        discovery_url="https://registry.example/company/acme",
        discovery_domain="registry.example",
        capability_description="Public industry registry company pages.",
        rationale="The registry covers a deterministic field gap.",
        evidence_refs=("url:https://registry.example/company/acme",),
    )


def test_propose_is_idempotent_and_scoped() -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            scope = await _scope(conn)
            first = await propose_field(
                conn,
                scope=scope,
                payload=_field_payload(),
                proposed_by_actor="agent",
                proposed_by_ref="thread:one",
            )
            second = await propose_field(
                conn,
                scope=scope,
                payload=_field_payload(),
                proposed_by_actor="agent",
                proposed_by_ref="thread:two",
            )
            assert second.id == first.id
            assert second.payload_hash == first.payload_hash
            assert second.status is ProposalStatus.PROPOSED

            assert (
                await get_field_proposal(conn, first.id, workspace_id=scope.workspace_id)
            ) == first
            assert await get_field_proposal(conn, first.id, workspace_id="other-workspace") is None

    run_async(scenario())


def test_payload_is_database_immutable_and_enums_match_core() -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            scope = await _scope(conn)
            proposed = await propose_field(
                conn,
                scope=scope,
                payload=_field_payload(),
                proposed_by_actor="agent",
            )
            with pytest.raises(DBAPIError, match="payload and scope are immutable"):
                async with conn.begin_nested():
                    await conn.execute(
                        text(
                            "UPDATE field_definition_revision "
                            "SET payload_json = '{\"tampered\": true}'::jsonb WHERE id = :id"
                        ),
                        {"id": proposed.id},
                    )
            stored = await get_field_proposal(conn, proposed.id, workspace_id=scope.workspace_id)
            assert stored == proposed

            status_labels = (
                await conn.execute(
                    text(
                        "SELECT enumlabel FROM pg_enum "
                        "JOIN pg_type ON pg_type.oid = pg_enum.enumtypid "
                        "WHERE typname = 'proposal_status' ORDER BY enumsortorder"
                    )
                )
            ).scalars()
            authority_labels = (
                await conn.execute(
                    text(
                        "SELECT enumlabel FROM pg_enum "
                        "JOIN pg_type ON pg_type.oid = pg_enum.enumtypid "
                        "WHERE typname = 'proposal_authority' ORDER BY enumsortorder"
                    )
                )
            ).scalars()
            assert tuple(status_labels) == tuple(item.value for item in ProposalStatus)
            assert tuple(authority_labels) == tuple(item.value for item in ProposalAuthority)

    run_async(scenario())


def test_scope_validation_fails_closed() -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            scope = await _scope(conn)
            invalid = scope.model_copy(update={"workspace_id": "other-workspace"})
            with pytest.raises(ProposalScopeError, match="scope not found"):
                await propose_field(
                    conn,
                    scope=invalid,
                    payload=_field_payload(),
                    proposed_by_actor="agent",
                )

    run_async(scenario())


def test_field_promotion_is_immediately_visible_in_live_registry() -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            scope = await _scope(conn)
            proposed = await propose_field(
                conn,
                scope=scope,
                payload=_field_payload("account.expansion_program"),
                proposed_by_actor="agent",
            )
            promoted = await decide_field_proposal(
                conn,
                proposal_id=proposed.id,
                workspace_id=scope.workspace_id,
                decision=ProposalDecision.PROMOTE,
                reason="Approved as a reusable public account field.",
                authority=ProposalAuthority.POLICY,
                decided_by="policy:test",
            )
            live = await get_field(conn, "account.expansion_program")
            assert promoted.status is ProposalStatus.PROMOTED
            assert live is not None
            assert live == proposed.payload.field_def

    run_async(scenario())


def test_contact_field_requires_human_authority() -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            scope = await _scope(conn)
            proposed = await propose_field(
                conn,
                scope=scope,
                payload=_field_payload("contact.facet.community_comment"),
                proposed_by_actor="agent",
            )
            assert proposed.required_authority is ProposalAuthority.HUMAN
            with pytest.raises(InsufficientProposalAuthority, match="requires human"):
                await decide_field_proposal(
                    conn,
                    proposal_id=proposed.id,
                    workspace_id=scope.workspace_id,
                    decision=ProposalDecision.PROMOTE,
                    reason="Policy must not promote personal fields.",
                    authority=ProposalAuthority.POLICY,
                    decided_by="policy:test",
                )
            promoted = await decide_field_proposal(
                conn,
                proposal_id=proposed.id,
                workspace_id=scope.workspace_id,
                decision=ProposalDecision.PROMOTE,
                reason="Human approved the governed field.",
                authority=ProposalAuthority.HUMAN,
                decided_by="human:test",
            )
            assert promoted.status is ProposalStatus.PROMOTED

    run_async(scenario())


def test_sensitive_field_requires_disabled_outreach_gate() -> None:
    with pytest.raises(ValidationError, match="outreach-disabled"):
        FieldProposalPayload(
            field_def=FieldDef(
                field_key="account.sensitive_signal",
                value_type="str",
                pass_kind=PassKind.DEEP,
            ),
            sensitive=True,
            rationale="Special-category data must never default into outreach.",
        )
    guarded = FieldProposalPayload(
        field_def=FieldDef(
            field_key="account.sensitive_signal",
            value_type="str",
            pass_kind=PassKind.DEEP,
            gate=SENSITIVE_OUTREACH_DISABLED_GATE,
        ),
        sensitive=True,
        rationale="Human-reviewed special-category field, disabled for outreach.",
    )
    assert guarded.field_def.gate == SENSITIVE_OUTREACH_DISABLED_GATE


def test_source_tier_is_decision_owned_and_live_after_promotion() -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            scope = await _scope(conn)
            proposed = await propose_source(
                conn,
                scope=scope,
                payload=_source_payload(),
                proposed_by_actor="agent",
            )
            assert proposed.assigned_tier is None
            with pytest.raises(InsufficientProposalAuthority, match="requires human"):
                await decide_source_proposal(
                    conn,
                    proposal_id=proposed.id,
                    workspace_id=scope.workspace_id,
                    decision=ProposalDecision.PROMOTE,
                    reason="Policy cannot award authoritative trust.",
                    authority=ProposalAuthority.POLICY,
                    decided_by="policy:test",
                    assigned_tier=2,
                )
            with pytest.raises(InsufficientProposalAuthority, match="requires human"):
                await decide_source_proposal(
                    conn,
                    proposal_id=proposed.id,
                    workspace_id=scope.workspace_id,
                    decision=ProposalDecision.PROMOTE,
                    reason="Policy may promote only the governed tier-3 path.",
                    authority=ProposalAuthority.POLICY,
                    decided_by="policy:test",
                    assigned_tier=4,
                )
            promoted = await decide_source_proposal(
                conn,
                proposal_id=proposed.id,
                workspace_id=scope.workspace_id,
                decision=ProposalDecision.PROMOTE,
                reason="Human reviewed provenance and assigned trust.",
                authority=ProposalAuthority.HUMAN,
                decided_by="human:test",
                assigned_tier=2,
            )
            live = await get_source(conn, proposed.payload.manifest.source_key)
            assert promoted.assigned_tier == 2
            assert live is not None and live.tier == 2

    run_async(scenario())


def test_policy_can_auto_promote_public_tier3_source() -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            scope = await _scope(conn)
            policy = ProposalPolicy(auto_promote_tier3_sources=True)
            promoted = await propose_source(
                conn,
                scope=scope,
                payload=_source_payload("audited_public_registry"),
                proposed_by_actor="agent",
                policy=policy,
            )
            assert promoted.status is ProposalStatus.PROMOTED
            assert promoted.decision_authority is ProposalAuthority.POLICY
            assert promoted.assigned_tier == 3

    run_async(scenario())


def test_credentialed_source_requires_confirmed_admin_setup() -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            scope = await _scope(conn)
            base = _source_payload("credentialed_source")
            payload = base.model_copy(
                update={
                    "manifest": base.manifest.model_copy(
                        update={"auth_ref": "CLUE_CREDENTIALED_SOURCE_TOKEN"}
                    )
                }
            )
            proposed = await propose_source(
                conn,
                scope=scope,
                payload=payload,
                proposed_by_actor="agent",
            )
            with pytest.raises(CredentialSetupRequired, match="not confirmed"):
                await decide_source_proposal(
                    conn,
                    proposal_id=proposed.id,
                    workspace_id=scope.workspace_id,
                    decision=ProposalDecision.PROMOTE,
                    reason="Human review without completed credential setup.",
                    authority=ProposalAuthority.HUMAN,
                    decided_by="human:test",
                    assigned_tier=3,
                )
            assert await get_source(conn, "credentialed_source") is None

            promoted = await decide_source_proposal(
                conn,
                proposal_id=proposed.id,
                workspace_id=scope.workspace_id,
                decision=ProposalDecision.PROMOTE,
                reason="Admin confirmed the credential is configured.",
                authority=ProposalAuthority.HUMAN,
                decided_by="human:test",
                assigned_tier=3,
                credential_ready=lambda auth_ref: auth_ref == "CLUE_CREDENTIALED_SOURCE_TOKEN",
            )
            assert promoted.status is ProposalStatus.PROMOTED

    run_async(scenario())


def test_personal_data_source_requires_compliance_approval() -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            scope = await _scope(conn)
            base = _source_payload("personal_public_source")
            payload = base.model_copy(
                update={
                    "manifest": base.manifest.model_copy(
                        update={
                            "entity_scope": EntityScope.CONTACT,
                            "yields": ("contact.facet",),
                        }
                    )
                }
            )
            proposed = await propose_source(
                conn,
                scope=scope,
                payload=payload,
                proposed_by_actor="agent",
            )
            assert proposed.required_authority is ProposalAuthority.HUMAN
            with pytest.raises(ComplianceApprovalRequired, match="compliance-policy"):
                await decide_source_proposal(
                    conn,
                    proposal_id=proposed.id,
                    workspace_id=scope.workspace_id,
                    decision=ProposalDecision.PROMOTE,
                    reason="Human review without compliance approval.",
                    authority=ProposalAuthority.HUMAN,
                    decided_by="human:test",
                    assigned_tier=3,
                )
            promoted = await decide_source_proposal(
                conn,
                proposal_id=proposed.id,
                workspace_id=scope.workspace_id,
                decision=ProposalDecision.PROMOTE,
                reason="Human and compliance policy approved.",
                authority=ProposalAuthority.HUMAN,
                decided_by="human:test",
                assigned_tier=3,
                personal_source_allowed=lambda candidate: candidate == payload,
            )
            assert promoted.status is ProposalStatus.PROMOTED

    run_async(scenario())


def test_cross_workspace_decision_does_not_reveal_proposal() -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            scope = await _scope(conn)
            proposed = await propose_field(
                conn,
                scope=scope,
                payload=_field_payload(),
                proposed_by_actor="agent",
            )
            with pytest.raises(ProposalNotFound):
                await decide_field_proposal(
                    conn,
                    proposal_id=proposed.id,
                    workspace_id="other-workspace",
                    decision=ProposalDecision.REJECT,
                    reason="Must be invisible.",
                    authority=ProposalAuthority.HUMAN,
                    decided_by="human:other",
                )

    run_async(scenario())


def test_concurrent_decisions_apply_exactly_once() -> None:
    async def scenario() -> None:
        suffix = uuid4().hex
        workspace_id = f"concurrent-{suffix}"
        async with db_lifespan() as engine:
            async with engine.begin() as conn:
                scope = await _scope(conn, workspace_id)
                proposed = await propose_field(
                    conn,
                    scope=scope,
                    payload=_field_payload(f"account.concurrent_{suffix}"),
                    proposed_by_actor="agent",
                )

            async def decide(decision: ProposalDecision) -> object:
                try:
                    async with engine.begin() as conn:
                        return await decide_field_proposal(
                            conn,
                            proposal_id=proposed.id,
                            workspace_id=workspace_id,
                            decision=decision,
                            reason=f"Concurrent {decision.value}.",
                            authority=ProposalAuthority.HUMAN,
                            decided_by=f"human:{decision.value}",
                        )
                except ProposalAlreadyDecided as exc:
                    return exc

            outcomes = await asyncio.gather(
                decide(ProposalDecision.REJECT),
                decide(ProposalDecision.WITHDRAW),
            )
            winners = [item for item in outcomes if not isinstance(item, Exception)]
            losers = [item for item in outcomes if isinstance(item, ProposalAlreadyDecided)]
            assert len(winners) == 1
            assert len(losers) == 1

            async with engine.begin() as conn:
                stored = await get_field_proposal(conn, proposed.id, workspace_id=workspace_id)
                assert stored is not None
                assert stored.status in {ProposalStatus.REJECTED, ProposalStatus.WITHDRAWN}
                await conn.execute(
                    text("DELETE FROM field_definition_revision WHERE id = :id"),
                    {"id": proposed.id},
                )
                await conn.execute(
                    text("DELETE FROM brand WHERE workspace_id = :workspace_id"),
                    {"workspace_id": workspace_id},
                )
                await conn.execute(
                    text("DELETE FROM workspace WHERE workspace_id = :workspace_id"),
                    {"workspace_id": workspace_id},
                )

    run_async(scenario())


def test_low_yield_policy_source_is_disabled() -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            scope = await _scope(conn)
            policy = ProposalPolicy(
                auto_promote_tier3_sources=True,
                min_observations_for_yield=2,
                demotion_yield_floor=0.5,
            )
            promoted = await propose_source(
                conn,
                scope=scope,
                payload=_source_payload("low_yield_registry"),
                proposed_by_actor="agent",
                policy=policy,
            )
            already_compiled_plan = FieldDef(
                field_key="core.employee_count",
                value_type="int",
                tier_plan=("low_yield_registry",),
                pass_kind=PassKind.SCORING,
            )
            for _ in range(2):
                await record_source_yield(
                    conn,
                    workspace_id=scope.workspace_id,
                    icp_key="primary",
                    source_key="low_yield_registry",
                    claims_total=1,
                    fields_filled=0,
                )
            result = await evaluate_source_demotion(
                conn,
                proposal_id=promoted.id,
                workspace_id=scope.workspace_id,
                policy=policy,
            )
            live = await get_source(conn, "low_yield_registry")
            stored = await get_source_proposal(conn, promoted.id, workspace_id=scope.workspace_id)
            assert result.demoted
            assert live is not None and not live.active and live.version == 2
            assert stored is not None and stored.demoted_at is not None
            assert already_compiled_plan.tier_plan == ("low_yield_registry",)
            assert "low_yield_registry" not in await sources_for(
                conn, "core.employee_count", active=True
            )

    run_async(scenario())


def test_invalid_pack_reuse_and_source_yields_reject_loudly() -> None:
    with pytest.raises(ValidationError, match="invalid field_key"):
        FieldProposalPayload(
            field_def=FieldDef(
                field_key="Not A Field",
                value_type="str",
                pass_kind=PassKind.DEEP,
            ),
            rationale="Malformed registry key.",
        )
    with pytest.raises(ValidationError, match="explicitly declare reuse_scope"):
        FieldProposalPayload(
            field_def=FieldDef(
                field_key="new_vertical.install_base",
                value_type="str",
                pass_kind=PassKind.DEEP,
            ),
            pack="new_vertical",
            rationale="Missing reuse classification is unsafe.",
        )
    valid = FieldProposalPayload(
        field_def=FieldDef(
            field_key="new_vertical.install_base",
            value_type="str",
            pass_kind=PassKind.DEEP,
            reuse_scope=ReuseScope.PUBLIC_FOOTPRINT,
        ),
        pack="new_vertical",
        rationale="Explicit public-footprint classification.",
    )
    assert valid.field_def.reuse_scope is ReuseScope.PUBLIC_FOOTPRINT

    with pytest.raises(ValidationError, match="invalid source yields"):
        SourceManifestDraft(
            source_key="bad_yields",
            modality=Modality.TEXT,
            entity_scope=EntityScope.ACCOUNT,
            yields=("Not A Field",),
        )


def test_source_payload_cannot_self_assign_tier() -> None:
    with pytest.raises(ValidationError, match="extra"):
        SourceManifestDraft.model_validate(
            {
                "source_key": "self_trusting",
                "modality": "text",
                "entity_scope": "account",
                "yields": ["core"],
                "tier": 1,
            }
        )
