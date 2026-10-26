"""Part-I acceptance tests for tenant-local dynamic Client-KB fields."""

from __future__ import annotations

import hashlib
from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import cast

import pytest
from pydantic import JsonValue
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_api.dynamic_client_kb import DynamicClientKbMaterializer
from clue_api.dynamic_client_kb_erasure import DynamicClientKbWorkspaceEraser
from clue_api.proposal_tools import (
    DecideFieldProposalInput,
    DecideFieldProposalTool,
    ProposalScopeInput,
    ProposeFieldInput,
    ProposeFieldTool,
)
from clue_config.proposals import ClientFieldPromotionMode, ProposalPolicy
from clue_core import (
    AccountStatus,
    EntityId,
    FieldDef,
    OnboardingInputKind,
    PassKind,
    ReuseScope,
    VolunteeredStatementId,
    new_operation_id,
)
from clue_core.proposals import FieldProposalId, ProposalAuthority, ProposalStatus
from clue_db import ConnFactory
from clue_projections.stage0 import (
    ExcludedEvidence,
    ExcludedEvidenceReason,
    ResolvedQuote,
    Stage0CardOmissionKind,
    compile_stage0_project_card,
)
from clue_research.claimstore import (
    FieldFilters,
    FieldRegistryOrigin,
    FieldRegistryScope,
    UnknownFieldError,
    ValueSchemaError,
    WorkspaceDynamicClientKbErasedError,
    entailment_judgment_id,
    get_effective_field,
    list_effective_fields,
    retire_workspace_field,
    validate_effective_value,
)
from clue_research.identity import insert_account_entity
from clue_research.proposals import (
    ClientKbFieldSpec,
    FieldProposal,
    FieldProposalPayload,
    ProposalDecision,
    ProposalScope,
    client_field_semantic_contract_hash,
    decide_field_proposal,
    propose_field,
)
from clue_research.stage0 import (
    SOURCE_CLIENT_INTERVIEW_JUDGED,
    ClaimEntailment,
    InterviewEvidenceRefused,
    StatementRoute,
    VolunteeredStatementRow,
    client_kb_readiness_metrics,
    compile_product_context,
    current_kb_version,
    read_client_kb,
    read_client_kb_claims,
    record_statement,
    set_workspace_client_kb_readiness_policy,
    submit_onboarding_input,
    workspace_required_field_metrics,
)
from clue_research.stage0.client_kb import client_kb_write_target_for_materialization
from clue_research.stage0.dynamic_client_kb import (
    FieldMaterializationStatus,
    materialize_approved_field,
    prepare_field_materialization,
)
from clue_spine import create_brand, create_product, create_project
from clue_storage import ArtifactNotFound, record_artifact
from clue_storage import artifact_key as make_artifact_key
from clue_toolbelt import ToolContext
from tests.stage0.conftest import rollback_conn, run_async

pytestmark = pytest.mark.usefixtures("require_stage0_db")


def _factory(conn: AsyncConnection) -> ConnFactory:
    @asynccontextmanager
    async def factory() -> AsyncIterator[AsyncConnection]:
        yield conn

    return factory


class _NoProjectStateEvidence:
    async def resolve_quote(
        self, *, workspace_id: str, statement: VolunteeredStatementRow
    ) -> ResolvedQuote | ExcludedEvidence:
        del workspace_id, statement
        raise AssertionError("the fixture has no project-state statement to resolve")

    async def resolve_quotes(
        self, *, workspace_id: str, statements: Sequence[VolunteeredStatementRow]
    ) -> tuple[ResolvedQuote, ...]:
        del workspace_id
        assert statements == ()
        return ()


class _StatementEvidence:
    def __init__(self, quotes: dict[str, str]) -> None:
        self._quotes = quotes

    async def resolve_quote(
        self, *, workspace_id: str, statement: VolunteeredStatementRow
    ) -> ResolvedQuote | ExcludedEvidence:
        del workspace_id
        return ResolvedQuote(statement_id=statement.id, quote=self._quotes[str(statement.id)])

    async def resolve_quotes(
        self, *, workspace_id: str, statements: Sequence[VolunteeredStatementRow]
    ) -> tuple[ResolvedQuote | ExcludedEvidence, ...]:
        return tuple(
            [
                await self.resolve_quote(workspace_id=workspace_id, statement=statement)
                for statement in statements
            ]
        )


class _ErasedStatementEvidence:
    async def resolve_quote(
        self, *, workspace_id: str, statement: VolunteeredStatementRow
    ) -> ResolvedQuote | ExcludedEvidence:
        del workspace_id
        return ExcludedEvidence(
            statement_id=statement.id,
            reason=ExcludedEvidenceReason.ARTIFACT_MISSING,
        )

    async def resolve_quotes(
        self, *, workspace_id: str, statements: Sequence[VolunteeredStatementRow]
    ) -> tuple[ResolvedQuote | ExcludedEvidence, ...]:
        return tuple(
            [
                await self.resolve_quote(workspace_id=workspace_id, statement=statement)
                for statement in statements
            ]
        )


class _SupportingJudge:
    async def entails(
        self,
        *,
        workspace_id: str,
        entity_id: EntityId,
        field_key: str,
        value: JsonValue,
        quote: str,
    ) -> ClaimEntailment:
        del workspace_id, entity_id, field_key, value, quote
        return ClaimEntailment(supported=True, verdict="supported", score=0.99)


class _UnavailableJudge:
    async def entails(
        self,
        *,
        workspace_id: str,
        entity_id: EntityId,
        field_key: str,
        value: JsonValue,
        quote: str,
    ) -> ClaimEntailment:
        del workspace_id, entity_id, field_key, value, quote
        return ClaimEntailment(supported=False, verdict="unavailable", score=0.0)


class _MemoryStorage:
    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}

    async def put(self, key: str, data: bytes, *, media_type: str) -> None:
        del media_type
        self.objects[key] = data

    async def get(self, key: str) -> bytes:
        try:
            return self.objects[key]
        except KeyError as exc:
            raise ArtifactNotFound(key) from exc

    async def delete(self, key: str) -> None:
        self.objects.pop(key, None)

    async def exists(self, key: str) -> bool:
        return key in self.objects

    async def presign(self, key: str, *, expires_in: int = 3600) -> str:
        del expires_in
        return f"memory://{key}"

    async def list_blobs(self) -> AsyncIterator[tuple[str, datetime]]:
        for key in sorted(self.objects):
            yield key, datetime.now(UTC)


@dataclass(frozen=True)
class _Scope:
    workspace_id: str
    brand_id: str
    product_id: str
    project_id: str
    client_entity_id: EntityId


async def _scope(conn: AsyncConnection, workspace_id: str) -> _Scope:
    brand = await create_brand(conn, workspace_id=workspace_id, name=f"{workspace_id} brand")
    product = await create_product(
        conn, workspace_id=workspace_id, brand_id=brand.brand_id, name="Dynamic KB product"
    )
    project = await create_project(
        conn,
        workspace_id=workspace_id,
        brand_id=brand.brand_id,
        product_id=product.product_id,
        name="Dynamic KB project",
    )
    client = await insert_account_entity(
        conn,
        canonical_name=f"{workspace_id} client",
        primary_domain=f"{workspace_id}.example",
        workspace_id=workspace_id,
        status=AccountStatus.ACTIVE,
    )
    return _Scope(
        workspace_id=workspace_id,
        brand_id=brand.brand_id,
        product_id=product.product_id,
        project_id=project.project_id,
        client_entity_id=client,
    )


async def _statement(
    conn: AsyncConnection, scope: _Scope, quote: str, *, route_key: str
) -> VolunteeredStatementId:
    body = quote.encode()
    digest = hashlib.sha256(body).hexdigest()
    key = make_artifact_key(scope.workspace_id, digest)
    await record_artifact(
        conn,
        storage_key=key,
        workspace_id=scope.workspace_id,
        content_sha256=digest,
        media_type="text/plain",
        size_bytes=len(body),
    )
    captured = await submit_onboarding_input(
        conn,
        workspace_id=scope.workspace_id,
        brand_id=scope.brand_id,
        product_id=scope.product_id,
        project_id=scope.project_id,
        client_entity_id=scope.client_entity_id,
        kind=OnboardingInputKind.USER_TURN,
        artifact_key=key,
        content_sha256=digest,
        actor="human",
    )
    return await record_statement(
        conn,
        onboarding_input_id=captured.onboarding_input_id,
        workspace_id=scope.workspace_id,
        brand_id=scope.brand_id,
        product_id=scope.product_id,
        project_id=scope.project_id,
        client_entity_id=scope.client_entity_id,
        entity_id=scope.client_entity_id,
        route_kind=StatementRoute.FIELD_PROPOSAL,
        route_key=route_key,
        quote=quote,
        quote_start=0,
        quote_end=len(quote),
        created_by_actor="agent",
    )


def _payload(
    *,
    field_key: str,
    statement_id: VolunteeredStatementId,
    candidate: JsonValue,
    schema: dict[str, JsonValue],
    **detail_updates: object,
) -> FieldProposalPayload:
    details = ClientKbFieldSpec(
        candidate_value=candidate,
        source_statement_id=statement_id,
        intended_use="Supplemental Client-KB context.",
        non_expiring_rationale="The client owns this stable operating fact.",
    ).model_copy(update=detail_updates)
    return FieldProposalPayload(
        field_def=FieldDef(
            field_key=field_key,
            value_type=schema["type"],  # type: ignore[arg-type]
            pass_kind=PassKind.DEEP,
            reuse_scope=ReuseScope.TENANT_PRIVATE,
        ),
        value_schema=schema,
        description=f"Tenant-local meaning for {field_key}.",
        pack="client",
        rationale="The exact client statement contains a reusable material fact.",
        evidence_refs=(f"volunteered_statement:{statement_id}",),
        client_kb=details,
    )


async def _propose(
    conn: AsyncConnection,
    scope: _Scope,
    payload: FieldProposalPayload,
    *,
    policy: ProposalPolicy | None = None,
) -> FieldProposal:
    return await propose_field(
        conn,
        scope=ProposalScope(
            workspace_id=scope.workspace_id,
            brand_id=scope.brand_id,
            product_id=scope.product_id,
            project_id=scope.project_id,
        ),
        payload=payload,
        proposed_by_actor="agent",
        policy=policy or ProposalPolicy(),
    )


async def _human_promote(
    conn: AsyncConnection, scope: _Scope, proposal_id: FieldProposalId
) -> FieldProposal:
    return await decide_field_proposal(
        conn,
        proposal_id=proposal_id,
        workspace_id=scope.workspace_id,
        decision=ProposalDecision.PROMOTE,
        reason="Human approved the bounded supplemental field and its evidence.",
        authority=ProposalAuthority.HUMAN,
        decided_by=f"human:{scope.workspace_id}",
    )


def test_same_private_key_can_have_different_tenant_schemas_without_leakage() -> None:
    async def scenario() -> None:
        async with rollback_conn(workspace_id="dynamic-a") as conn:
            await conn.execute(
                text("INSERT INTO workspace (workspace_id, name) VALUES ('dynamic-b', 'dynamic-b')")
            )
            scope_a = await _scope(conn, "dynamic-a")
            scope_b = await _scope(conn, "dynamic-b")
            statement_a = await _statement(
                conn, scope_a, "We are fully HIPAA compliant.", route_key="hipaa"
            )
            statement_b = await _statement(
                conn,
                scope_b,
                "We support SOAP, APSO, and H&P notes.",
                route_key="note_formats",
            )
            key = "client.integration.note_formats"
            proposal_a = await _propose(
                conn,
                scope_a,
                _payload(
                    field_key=key,
                    statement_id=statement_a,
                    candidate=True,
                    schema={"type": "boolean"},
                ),
            )
            proposal_b = await _propose(
                conn,
                scope_b,
                _payload(
                    field_key=key,
                    statement_id=statement_b,
                    candidate=["SOAP", "APSO", "H&P"],
                    schema={
                        "type": "array",
                        "maxItems": 8,
                        "items": {"type": "string", "maxLength": 32},
                    },
                ),
            )
            await _human_promote(conn, scope_a, proposal_a.id)
            await _human_promote(conn, scope_b, proposal_b.id)

            resolved_a = await get_effective_field(
                conn, scope=FieldRegistryScope.for_workspace(scope_a.workspace_id), field_key=key
            )
            resolved_b = await get_effective_field(
                conn, scope=FieldRegistryScope.for_workspace(scope_b.workspace_id), field_key=key
            )
            assert resolved_a is not None and resolved_a.origin is FieldRegistryOrigin.WORKSPACE
            assert resolved_b is not None and resolved_b.origin is FieldRegistryOrigin.WORKSPACE
            assert resolved_a.value_schema == {"type": "boolean"}
            assert resolved_b.value_schema == {
                "type": "array",
                "maxItems": 8,
                "items": {"type": "string", "maxLength": 32},
            }
            assert (
                await get_effective_field(
                    conn, scope=FieldRegistryScope.global_only(), field_key=key
                )
                is None
            )
            await validate_effective_value(
                conn,
                scope=FieldRegistryScope.for_workspace(scope_a.workspace_id),
                field_key=key,
                value_json=True,
            )
            with pytest.raises(ValueSchemaError):
                await validate_effective_value(
                    conn,
                    scope=FieldRegistryScope.for_workspace(scope_b.workspace_id),
                    field_key=key,
                    value_json=True,
                )
            with pytest.raises(UnknownFieldError):
                await validate_effective_value(
                    conn,
                    scope=FieldRegistryScope.for_workspace("dynamic-unknown"),
                    field_key=key,
                    value_json=True,
                )

            baseline = await get_effective_field(
                conn,
                scope=FieldRegistryScope.for_workspace(scope_b.workspace_id),
                field_key="client.value_prop",
            )
            assert baseline is not None and baseline.origin is FieldRegistryOrigin.GLOBAL

    run_async(scenario())


def test_default_human_and_safe_auto_modes_share_one_governed_path() -> None:
    async def scenario() -> None:
        async with rollback_conn(workspace_id="dynamic-policy") as conn:
            scope = await _scope(conn, "dynamic-policy")
            human_statement = await _statement(
                conn, scope, "We are fully HIPAA compliant.", route_key="human-hipaa"
            )
            human = await _propose(
                conn,
                scope,
                _payload(
                    field_key="client.hipaa_compliant",
                    statement_id=human_statement,
                    candidate=True,
                    schema={"type": "boolean"},
                ),
            )
            assert human.status is ProposalStatus.PROPOSED
            assert human.required_authority is ProposalAuthority.HUMAN
            promoted = await _human_promote(conn, scope, human.id)
            assert promoted.status is ProposalStatus.PROMOTED

            auto_statement = await _statement(
                conn, scope, "Our BAA is standard.", route_key="auto-baa"
            )
            auto_payload = _payload(
                field_key="client.baa_standard",
                statement_id=auto_statement,
                candidate=True,
                schema={"type": "boolean"},
            )
            safe_policy = ProposalPolicy(
                client_field_mode=ClientFieldPromotionMode.SAFE_AUTO_PROMOTE,
                client_field_policy_version="dynamic-client-kb-test-v2",
                safe_auto_client_field_contract_hashes=frozenset(
                    {client_field_semantic_contract_hash(auto_payload)}
                ),
            )
            automatic = await _propose(
                conn,
                scope,
                auto_payload,
                policy=safe_policy,
            )
            assert automatic.status is ProposalStatus.PROMOTED
            assert automatic.decision_authority is ProposalAuthority.POLICY
            definition = await get_effective_field(
                conn,
                scope=FieldRegistryScope.for_workspace(scope.workspace_id),
                field_key="client.baa_standard",
            )
            assert definition is not None
            assert definition.promotion_policy_version == "dynamic-client-kb-test-v2"
            assert definition.promoted_by == "policy:dynamic_client_kb"

            blocked_statement = await _statement(
                conn, scope, "We require SOC 2 evidence.", route_key="required-soc2"
            )
            blocked = await _propose(
                conn,
                scope,
                _payload(
                    field_key="client.soc2_required",
                    statement_id=blocked_statement,
                    candidate=True,
                    schema={"type": "boolean"},
                    readiness_requested=True,
                ),
                policy=safe_policy,
            )
            assert blocked.status is ProposalStatus.PROPOSED
            assert blocked.required_authority is ProposalAuthority.HUMAN
            assert (
                await get_effective_field(
                    conn,
                    scope=FieldRegistryScope.for_workspace(scope.workspace_id),
                    field_key="client.soc2_required",
                )
                is None
            )

    run_async(scenario())


def test_real_db_refuses_self_attested_sensitive_semantics_and_out_of_range_candidates() -> None:
    async def scenario() -> None:
        async with rollback_conn(workspace_id="dynamic-adversarial-policy") as conn:
            scope = await _scope(conn, "dynamic-adversarial-policy")
            address_statement = await _statement(
                conn,
                scope,
                "The founder receives mail at 123 Private Lane.",
                route_key="founder-address",
            )
            malicious = _payload(
                field_key="client.founder_home_address",
                statement_id=address_statement,
                candidate="123 Private Lane",
                schema={"type": "string", "maxLength": 120},
                intended_use="Use this private address for tailored outreach.",
                contains_personal_data=False,
                outreach_authoritative=False,
            )
            self_attested = await _propose(
                conn,
                scope,
                malicious,
                policy=ProposalPolicy(client_field_mode=ClientFieldPromotionMode.SAFE_AUTO_PROMOTE),
            )
            assert self_attested.status is ProposalStatus.PROPOSED
            assert self_attested.required_authority is ProposalAuthority.HUMAN
            assert (
                await get_effective_field(
                    conn,
                    scope=FieldRegistryScope.for_workspace(scope.workspace_id),
                    field_key=malicious.field_def.field_key,
                )
            ) is None

            retention_statement = await _statement(
                conn,
                scope,
                "Support retention is not yet configured.",
                route_key="invalid-retention",
            )
            invalid_value = await _propose(
                conn,
                scope,
                _payload(
                    field_key="client.invalid_retention_days",
                    statement_id=retention_statement,
                    candidate=-1,
                    schema={"type": "integer", "minimum": 0, "maximum": 3650},
                ),
            )
            with pytest.raises(ValueSchemaError, match="at least 0"):
                await _human_promote(conn, scope, invalid_value.id)
            assert (
                await get_effective_field(
                    conn,
                    scope=FieldRegistryScope.for_workspace(scope.workspace_id),
                    field_key="client.invalid_retention_days",
                )
            ) is None

    run_async(scenario())


def test_materialization_is_typed_replay_safe_open_to_reads_and_version_safe() -> None:
    async def scenario() -> None:
        async with rollback_conn(workspace_id="dynamic-materialize") as conn:
            scope = await _scope(conn, "dynamic-materialize")
            seed_target = await client_kb_write_target_for_materialization(
                conn,
                workspace_id=scope.workspace_id,
                client_entity_id=scope.client_entity_id,
                product_id=None,
                operation_key="seed-version",
            )
            assert seed_target.version == 1
            await compile_product_context(
                conn,
                workspace_id=scope.workspace_id,
                brand_id=scope.brand_id,
                product_id=scope.product_id,
                client_entity_id=scope.client_entity_id,
                client_kb_version=1,
                claim_refs=(),
            )
            quote = "We support SOAP, APSO, and H&P formats out of the box."
            statement = await _statement(conn, scope, quote, route_key="document-formats")
            payload = _payload(
                field_key="client.document_formats",
                statement_id=statement,
                candidate=["SOAP", "APSO", "H&P"],
                schema={
                    "type": "array",
                    "maxItems": 8,
                    "items": {"type": "string", "maxLength": 32},
                },
            )
            proposed = await _propose(conn, scope, payload)
            await _human_promote(conn, scope, proposed.id)
            plan, existing = await prepare_field_materialization(
                conn,
                workspace_id=scope.workspace_id,
                proposal_id=proposed.id,
                statement_id=statement,
            )
            assert existing is None
            first = await materialize_approved_field(conn, plan=plan, quote=quote, judged=True)
            second = await materialize_approved_field(conn, plan=plan, quote=quote, judged=True)

            assert first == second
            assert first.status is FieldMaterializationStatus.MATERIALIZED
            assert first.client_kb_version == 2
            assert (
                await current_kb_version(
                    conn,
                    scope.client_entity_id,
                    workspace_id=scope.workspace_id,
                    product_id=None,
                )
                == 2
            )
            assert "client.document_formats" not in await read_client_kb(
                conn,
                scope.client_entity_id,
                workspace_id=scope.workspace_id,
                version=1,
                product_id=None,
            )
            assert (
                await read_client_kb(
                    conn,
                    scope.client_entity_id,
                    workspace_id=scope.workspace_id,
                    version=2,
                    product_id=None,
                )
            )["client.document_formats"] == ["SOAP", "APSO", "H&P"]
            claims = await read_client_kb_claims(
                conn,
                scope.client_entity_id,
                workspace_id=scope.workspace_id,
                version=2,
                product_id=None,
            )
            claim = claims["client.document_formats"]
            assert claim.id == first.claim_id
            assert claim.source_key == SOURCE_CLIENT_INTERVIEW_JUDGED
            assert claim.evidence_span == quote
            assert claim.reuse_scope is ReuseScope.TENANT_PRIVATE
            assert claim.workspace_id == scope.workspace_id
            assert (
                await conn.execute(
                    text("SELECT count(*) FROM claim WHERE id = :claim_id"),
                    {"claim_id": first.claim_id},
                )
            ).scalar_one() == 1

            baseline_metrics = client_kb_readiness_metrics(claims)
            available = cast(list[JsonValue], baseline_metrics["available_field_keys"])
            assert "client.document_formats" not in available
            assert baseline_metrics["coverage_ratio"] == 0.0

            effective_metrics = client_kb_readiness_metrics(
                claims,
                required_field_keys=("client.document_formats",),
            )
            assert effective_metrics["available_field_keys"] == ["client.document_formats"]
            # The generic company-knowledge helper defaults to all 12 account-wide fields (the
            # eleven onboarding fields plus catalog navigation). One workspace-local extension
            # therefore makes this one filled field out of 13. ICP callers pass the stable
            # nine-field gate baseline explicitly; onboarding progress uses its explicit eleven.
            assert effective_metrics["coverage_ratio"] == pytest.approx(1 / 13)

            with pytest.raises(PermissionError, match="human authority"):
                await set_workspace_client_kb_readiness_policy(
                    conn,
                    workspace_id=scope.workspace_id,
                    required_field_keys=("client.document_formats",),
                    decided_by="policy:test",
                    decision_reason="Policy must not change readiness.",
                )
            policy = await set_workspace_client_kb_readiness_policy(
                conn,
                workspace_id=scope.workspace_id,
                required_field_keys=("client.document_formats",),
                decided_by="human:test",
                decision_reason="Client explicitly requested this local readiness extension.",
            )
            local_metrics = workspace_required_field_metrics(claims, policy)
            assert local_metrics["workspace_required_filled"] == 1
            assert local_metrics["workspace_readiness_policy_version"] == 1

            await retire_workspace_field(
                conn,
                workspace_id=scope.workspace_id,
                field_key="client.document_formats",
                retired_by="human:test",
                reason="Replaced by a newer semantic field.",
            )
            assert (
                await get_effective_field(
                    conn,
                    scope=FieldRegistryScope.for_workspace(scope.workspace_id),
                    field_key="client.document_formats",
                )
                is None
            )
            historical = await list_effective_fields(
                conn,
                scope=FieldRegistryScope.for_workspace(scope.workspace_id),
                filters=FieldFilters(pack="client", active=None),
                include_retired=True,
            )
            retired = next(
                item for item in historical if item.field_def.field_key == "client.document_formats"
            )
            assert not retired.active

    run_async(scenario())


def test_project_card_bounds_hundreds_of_dynamic_fields_and_pending_refs_honestly() -> None:
    async def scenario() -> None:
        async with rollback_conn(workspace_id="dynamic-card") as conn:
            scope = await _scope(conn, "dynamic-card")
            target = await client_kb_write_target_for_materialization(
                conn,
                workspace_id=scope.workspace_id,
                client_entity_id=scope.client_entity_id,
                product_id=None,
                operation_key="card-base",
            )
            quote = "This fixture supplies bounded supplemental boolean facts."
            statement = await _statement(conn, scope, quote, route_key="dynamic-card-source")

            for index in range(200):
                proposal = await _propose(
                    conn,
                    scope,
                    _payload(
                        field_key=f"client.card_fact_{index:03d}",
                        statement_id=statement,
                        candidate=bool(index % 2),
                        schema={"type": "boolean"},
                    ),
                )
                await _human_promote(conn, scope, proposal.id)
                plan, existing = await prepare_field_materialization(
                    conn,
                    workspace_id=scope.workspace_id,
                    proposal_id=proposal.id,
                    statement_id=statement,
                )
                assert existing is None
                await materialize_approved_field(conn, plan=plan, quote=quote, judged=True)

            for index in range(12):
                pending_statement = await _statement(
                    conn,
                    scope,
                    f"Pending supplemental fact {index}.",
                    route_key=f"pending-{index}",
                )
                pending = await _propose(
                    conn,
                    scope,
                    _payload(
                        field_key=f"client.pending_fact_{index:03d}",
                        statement_id=pending_statement,
                        candidate=True,
                        schema={"type": "boolean"},
                    ),
                )
                assert pending.status is ProposalStatus.PROPOSED

            card = await compile_stage0_project_card(
                project_id=scope.project_id,
                workspace_id=scope.workspace_id,
                client_entity_id=scope.client_entity_id,
                client_kb_version=target.version,
                product_id=scope.product_id,
                evidence=_NoProjectStateEvidence(),
                conn_factory=_factory(conn),
            )
            assert card.client_knowledge.extended_registered == 200
            assert card.client_knowledge.extended_filled == 200
            assert card.client_knowledge.pending_field_proposals == 12
            assert len(card.client_knowledge.pending_field_proposal_refs) == 8
            assert len(card.client_knowledge.known_fields) < 200
            overflow = next(
                item
                for item in card.omissions
                if item.kind is Stage0CardOmissionKind.CLIENT_KNOWLEDGE_OVER_CAP
            )
            assert overflow.count == 200 - len(card.client_knowledge.known_fields)
            assert overflow.cursor is not None
            assert len(card.canonical_bytes()) <= 24_000

    run_async(scenario())


def test_erased_statement_refuses_once_and_replay_cannot_resurrect_a_claim() -> None:
    async def scenario() -> None:
        async with rollback_conn(workspace_id="dynamic-erasure") as conn:
            scope = await _scope(conn, "dynamic-erasure")
            quote = "We retain support transcripts for 30 days."
            statement = await _statement(conn, scope, quote, route_key="support-retention")
            proposal = await _propose(
                conn,
                scope,
                _payload(
                    field_key="client.support_transcript_retention_days",
                    statement_id=statement,
                    candidate=30,
                    schema={"type": "integer", "minimum": 0, "maximum": 3650},
                ),
            )
            promoted = await _human_promote(conn, scope, proposal.id)
            factory = _factory(conn)

            erased = DynamicClientKbMaterializer(
                evidence=_ErasedStatementEvidence(), entailment_judge=_SupportingJudge()
            )
            refused = await erased.materialize(
                proposal=promoted,
                workspace_id=scope.workspace_id,
                conn_factory=factory,
            )
            assert refused.materialization_status == "refused"
            assert refused.refusal_code == "statement_evidence_missing"
            assert refused.claim_ref is None

            # Even if an artifact backend later returns bytes for the same key, the terminal
            # erasure refusal is durable. A cold replay resolves the receipt before evidence I/O
            # and cannot recreate content that was erased.
            replay = DynamicClientKbMaterializer(
                evidence=_StatementEvidence({str(statement): quote}),
                entailment_judge=_SupportingJudge(),
            )
            replayed = await replay.materialize(
                proposal=promoted,
                workspace_id=scope.workspace_id,
                conn_factory=factory,
            )
            assert replayed == refused
            assert (
                await conn.execute(
                    text(
                        "SELECT count(*) FROM claim "
                        "WHERE workspace_id = :workspace_id AND field_key = :field_key"
                    ),
                    {
                        "workspace_id": scope.workspace_id,
                        "field_key": "client.support_transcript_retention_days",
                    },
                )
            ).scalar_one() == 0
            assert (
                await conn.execute(
                    text(
                        "SELECT count(*) FROM volunteered_statement "
                        "WHERE workspace_id = :workspace_id AND id = :statement_id"
                    ),
                    {"workspace_id": scope.workspace_id, "statement_id": statement},
                )
            ).scalar_one() == 1

    run_async(scenario())


def test_temporary_judge_outage_leaves_no_terminal_receipt_and_a_healthy_retry_writes() -> None:
    async def scenario() -> None:
        async with rollback_conn(workspace_id="dynamic-judge-retry") as conn:
            scope = await _scope(conn, "dynamic-judge-retry")
            quote = "We retain support transcripts for 30 days."
            statement = await _statement(conn, scope, quote, route_key="retry-retention")
            proposal = await _propose(
                conn,
                scope,
                _payload(
                    field_key="client.retry_retention_days",
                    statement_id=statement,
                    candidate=30,
                    schema={"type": "integer", "minimum": 0, "maximum": 3650},
                ),
            )
            promoted = await _human_promote(conn, scope, proposal.id)
            factory = _factory(conn)
            evidence = _StatementEvidence({str(statement): quote})

            unavailable = DynamicClientKbMaterializer(
                evidence=evidence, entailment_judge=_UnavailableJudge()
            )
            with pytest.raises(InterviewEvidenceRefused) as caught:
                await unavailable.materialize(
                    proposal=promoted,
                    workspace_id=scope.workspace_id,
                    conn_factory=factory,
                )
            assert caught.value.reason_code == "claim_value_judge_unavailable"
            assert (
                await conn.execute(
                    text(
                        "SELECT count(*) FROM workspace_field_materialization "
                        "WHERE workspace_id = :workspace_id"
                    ),
                    {"workspace_id": scope.workspace_id},
                )
            ).scalar_one() == 0

            healthy = DynamicClientKbMaterializer(
                evidence=evidence, entailment_judge=_SupportingJudge()
            )
            materialized = await healthy.materialize(
                proposal=promoted,
                workspace_id=scope.workspace_id,
                conn_factory=factory,
            )
            assert materialized.materialization_status == "materialized"
            assert materialized.claim_ref is not None

    run_async(scenario())


def test_workspace_erasure_removes_the_full_dynamic_kb_surface_and_blocks_resurrection() -> None:
    async def scenario() -> None:
        workspace_id = "dynamic-full-erasure"
        other_workspace = "dynamic-erasure-neighbor"
        async with rollback_conn(workspace_id=workspace_id) as conn:
            await conn.execute(
                text(
                    "INSERT INTO workspace (workspace_id, name) "
                    "VALUES (:workspace_id, :workspace_id)"
                ),
                {"workspace_id": other_workspace},
            )
            scope = await _scope(conn, workspace_id)
            neighbor = await _scope(conn, other_workspace)
            field_key = "client.capacity_limit"
            quote = "Our reviewed customer capacity limit is 50 accounts."
            statement = await _statement(conn, scope, quote, route_key="capacity")
            promoted = await _human_promote(
                conn,
                scope,
                (
                    await _propose(
                        conn,
                        scope,
                        _payload(
                            field_key=field_key,
                            statement_id=statement,
                            candidate=50,
                            schema={"type": "integer", "minimum": 0, "maximum": 1000},
                        ),
                    )
                ).id,
            )
            materializer = DynamicClientKbMaterializer(
                evidence=_StatementEvidence({str(statement): quote}),
                entailment_judge=_SupportingJudge(),
            )
            materialized = await materializer.materialize(
                proposal=promoted,
                workspace_id=workspace_id,
                conn_factory=_factory(conn),
            )
            assert materialized.claim_ref is not None
            assert materialized.client_kb_version is not None
            await set_workspace_client_kb_readiness_policy(
                conn,
                workspace_id=workspace_id,
                required_field_keys=(field_key,),
                decided_by="human:privacy-admin",
                decision_reason="Require the reviewed capacity fact.",
            )

            pending_quote = "Our escalation window is 24 hours."
            pending_statement = await _statement(
                conn, scope, pending_quote, route_key="escalation-window"
            )
            pending = await _propose(
                conn,
                scope,
                _payload(
                    field_key="client.escalation_window_hours",
                    statement_id=pending_statement,
                    candidate=24,
                    schema={"type": "integer", "minimum": 0, "maximum": 168},
                ),
            )
            assert pending.status is ProposalStatus.PROPOSED

            # The same key remains independent in a neighboring workspace and must survive.
            neighbor_statement = await _statement(
                conn,
                neighbor,
                "Capacity means 50 concurrent analyst seats here.",
                route_key="capacity",
            )
            neighbor_promoted = await _human_promote(
                conn,
                neighbor,
                (
                    await _propose(
                        conn,
                        neighbor,
                        _payload(
                            field_key=field_key,
                            statement_id=neighbor_statement,
                            candidate="50 concurrent analyst seats",
                            schema={"type": "string", "maxLength": 80},
                        ),
                    )
                ).id,
            )

            question_id = entailment_judgment_id(
                workspace_id=workspace_id,
                field_key=field_key,
                value=50,
                quote=quote,
            )
            rationale_sentinel = "PRIVATE_ERASURE_RATIONALE_SENTINEL"
            await conn.execute(
                text(
                    """
                    INSERT INTO faithfulness_verdict
                        (claim_id, verdict, score, rationale, judge_model, answering_model,
                         prompt_version, cost_cents)
                    VALUES
                        (:claim_id, 'supported', 0.99, :rationale, 'test/judge', 'test/judge',
                         'workspace-erasure-v1', 0)
                    """
                ),
                {"claim_id": question_id, "rationale": rationale_sentinel},
            )

            storage = _MemoryStorage()
            artifact_keys = {
                make_artifact_key(workspace_id, hashlib.sha256(body.encode()).hexdigest()): body
                for body in (quote, pending_quote)
            }
            for artifact_key, body in artifact_keys.items():
                await storage.put(artifact_key, body.encode(), media_type="text/plain")

            # Review of F3 Phase 2: this eraser purges the keys its own transaction marked.
            # ``purge_erased_artifacts`` opens with an unfiltered
            # ``UPDATE artifact … WHERE expires_at <= now()`` and a sequential scan, which is
            # the keyless maintenance sweep's work — not a workspace erasure's to do on rows
            # that belong to other owners.
            expiring = make_artifact_key(workspace_id, "e" * 64)
            await storage.put(expiring, b"another owner's bytes", media_type="text/plain")
            await conn.execute(
                text(
                    "INSERT INTO artifact (storage_key, workspace_id, content_sha256, "
                    "media_type, size_bytes, expires_at) VALUES (:key, :ws, :sha, "
                    "'text/plain', 21, now() - interval '1 second')"
                ),
                {"key": expiring, "ws": workspace_id, "sha": "e" * 64},
            )

            eraser = DynamicClientKbWorkspaceEraser(conn_factory=_factory(conn), storage=storage)
            erased = await eraser.erase(
                workspace_id=workspace_id,
                erased_by="human:privacy-admin",
            )
            assert erased.definition_count == 1
            assert erased.proposal_count == 2
            assert erased.materialization_count == 1
            assert erased.readiness_policy_count == 1
            assert erased.claim_count == 1
            assert erased.artifact_count == 2
            assert set(erased.marked_artifact_keys) == set(artifact_keys)
            assert set(storage.objects) == {expiring}
            untouched = (
                await conn.execute(
                    text(
                        "SELECT erased_at, purged_at, privacy_erased FROM artifact "
                        "WHERE storage_key = :key"
                    ),
                    {"key": expiring},
                )
            ).one()
            assert tuple(untouched) == (None, None, False)

            counts = (
                await conn.execute(
                    text(
                        """
                        SELECT
                          (SELECT count(*) FROM workspace_field_definition
                           WHERE workspace_id = :workspace_id),
                          (SELECT count(*) FROM field_definition_revision
                           WHERE workspace_id = :workspace_id
                             AND payload_json->'client_kb' IS NOT NULL),
                          (SELECT count(*) FROM workspace_field_materialization
                           WHERE workspace_id = :workspace_id),
                          (SELECT count(*) FROM workspace_client_kb_readiness_policy
                           WHERE workspace_id = :workspace_id)
                        """
                    ),
                    {"workspace_id": workspace_id},
                )
            ).one()
            assert tuple(counts) == (0, 0, 0, 0)
            assert (
                await get_effective_field(
                    conn,
                    scope=FieldRegistryScope.for_workspace(workspace_id),
                    field_key=field_key,
                )
            ) is None
            assert (
                await get_effective_field(
                    conn,
                    scope=FieldRegistryScope.for_workspace(other_workspace),
                    field_key=field_key,
                )
            ) is not None
            assert field_key not in await read_client_kb(
                conn,
                scope.client_entity_id,
                workspace_id=workspace_id,
                product_id=None,
            )
            assert (
                await conn.execute(
                    text("SELECT rationale FROM faithfulness_verdict WHERE claim_id = :claim_id"),
                    {"claim_id": question_id},
                )
            ).scalar_one() is None
            old_claim_state = (
                await conn.execute(
                    text("SELECT superseded_by FROM claim WHERE id = CAST(:claim_id AS uuid)"),
                    {"claim_id": materialized.claim_ref},
                )
            ).scalar_one()
            assert old_claim_state is not None

            card = await compile_stage0_project_card(
                project_id=scope.project_id,
                workspace_id=workspace_id,
                client_entity_id=scope.client_entity_id,
                client_kb_version=materialized.client_kb_version,
                product_id=scope.product_id,
                evidence=_NoProjectStateEvidence(),
                conn_factory=_factory(conn),
            )
            assert card.client_knowledge.extended_registered == 0
            assert card.client_knowledge.extended_filled == 0
            assert card.client_knowledge.pending_field_proposals == 0

            # The durable marker makes every replay/write seam fail closed, while an idempotent
            # erasure replay returns the original audit result and leaves the neighbor untouched.
            assert (
                await eraser.erase(
                    workspace_id=workspace_id,
                    erased_by="human:another-actor",
                )
                == erased
            )
            with pytest.raises(WorkspaceDynamicClientKbErasedError):
                await _propose(
                    conn,
                    scope,
                    _payload(
                        field_key="client.resurrection_attempt",
                        statement_id=pending_statement,
                        candidate=True,
                        schema={"type": "boolean"},
                    ),
                )
            with pytest.raises(WorkspaceDynamicClientKbErasedError):
                await materializer.materialize(
                    proposal=promoted,
                    workspace_id=workspace_id,
                    conn_factory=_factory(conn),
                )
            with pytest.raises(WorkspaceDynamicClientKbErasedError):
                await set_workspace_client_kb_readiness_policy(
                    conn,
                    workspace_id=workspace_id,
                    required_field_keys=(),
                    decided_by="human:privacy-admin",
                    decision_reason="Attempted replay.",
                )
            assert neighbor_promoted.status is ProposalStatus.PROMOTED

    run_async(scenario())


def test_human_and_safe_auto_tools_materialize_and_return_references_only() -> None:
    async def scenario() -> None:
        async with rollback_conn(workspace_id="dynamic-tools") as conn:
            scope = await _scope(conn, "dynamic-tools")
            human_quote = "We are fully HIPAA compliant."
            auto_quote = "Our BAA is standard."
            human_statement = await _statement(
                conn, scope, human_quote, route_key="tool-human-hipaa"
            )
            auto_statement = await _statement(conn, scope, auto_quote, route_key="tool-auto-baa")
            materializer = DynamicClientKbMaterializer(
                evidence=_StatementEvidence(
                    {str(human_statement): human_quote, str(auto_statement): auto_quote}
                ),
                entailment_judge=_SupportingJudge(),
            )
            factory = _factory(conn)
            agent = ToolContext(
                workspace_id=scope.workspace_id,
                actor="agent",
                conn_factory=factory,
                operation_id=new_operation_id(),
            )
            human = ToolContext(
                workspace_id=scope.workspace_id,
                actor="human",
                principal_kind="human",
                actor_id="human:client-kb-test",
                membership_id="wsm_client_kb_test",
                conn_factory=factory,
                operation_id=new_operation_id(),
            )
            scope_input = ProposalScopeInput(product_id=scope.product_id)
            human_input = ProposeFieldInput(
                brand_id=scope.brand_id,
                project_id=scope.project_id,
                scope=scope_input,
                payload=_payload(
                    field_key="client.tool_hipaa_compliant",
                    statement_id=human_statement,
                    candidate=True,
                    schema={"type": "boolean"},
                ),
            )
            propose_human = ProposeFieldTool(dynamic_client_kb_materializer=materializer)
            proposed = await propose_human.invoke(human_input, agent)
            assert proposed.references["status"] == ProposalStatus.PROPOSED.value
            assert "claim_ref" not in proposed.references

            decide = DecideFieldProposalTool(dynamic_client_kb_materializer=materializer)
            decision_input = DecideFieldProposalInput(
                field_proposal_id=str(proposed.references["field_proposal_id"]),
                decision=ProposalDecision.PROMOTE,
                reason="Human approved the bounded field and exact source statement.",
            )
            assert await decide.preconditions(decision_input, human) == ()
            materialized = await decide.invoke(decision_input, human)
            assert materialized.references["status"] == ProposalStatus.PROMOTED.value
            assert materialized.references["materialization_status"] == "materialized"
            assert "claim_ref" in materialized.references

            auto_payload = _payload(
                field_key="client.tool_baa_standard",
                statement_id=auto_statement,
                candidate=True,
                schema={"type": "boolean"},
            )
            safe_policy = ProposalPolicy(
                client_field_mode=ClientFieldPromotionMode.SAFE_AUTO_PROMOTE,
                client_field_policy_version="dynamic-client-kb-tool-v1",
                safe_auto_client_field_contract_hashes=frozenset(
                    {client_field_semantic_contract_hash(auto_payload)}
                ),
            )
            auto_tool = ProposeFieldTool(
                policy=safe_policy, dynamic_client_kb_materializer=materializer
            )
            auto_input = ProposeFieldInput(
                brand_id=scope.brand_id,
                project_id=scope.project_id,
                scope=scope_input,
                payload=auto_payload,
            )
            assert await auto_tool.preconditions(auto_input, agent) == ()
            automatic = await auto_tool.invoke(auto_input, agent)
            replay = await auto_tool.invoke(auto_input, agent)
            assert automatic.references == replay.references
            assert automatic.references["status"] == ProposalStatus.PROMOTED.value
            assert automatic.references["materialization_status"] == "materialized"
            assert "candidate_value" not in automatic.references
            assert set(automatic.references) >= {
                "field_proposal_id",
                "field_key",
                "status",
                "materialization_id",
                "materialization_status",
                "claim_ref",
                "client_kb_version",
            }

    run_async(scenario())
