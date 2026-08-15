"""Real-PostgreSQL S4-C acceptance for the frozen Client-KB ``@2`` tools."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text

from clue_api.client_knowledge_contracts import (
    MAX_CLAIM_VALUE_BYTES,
    MAX_EVIDENCE_SPAN_BYTES,
    ClientClaimInspectionV2Output,
    ClientKnowledgeListV2Output,
    response_bytes,
)
from clue_api.client_knowledge_tools import build_client_knowledge_v2_tools
from clue_core import ExtractionMethod, new_claim_id, new_operation_id
from clue_projections import ClientKnowledgeCardPolicy, compile_client_knowledge_card
from clue_research.claimstore import insert_claim, supersede_claim
from clue_research.stage0 import (
    CLIENT_KNOWLEDGE_FIELDS,
    ClientInput,
    VolunteeredMaterial,
    read_client_kb_claims,
    reverse_profile,
)
from clue_toolbelt import PreconditionFailed, ToolContext, ToolRegistry, ToolResult, invoke_tool
from tests.api.test_production_context_s3_db import _seed_post_recon
from tests.db.conftest import run_async
from tests.profiling.conftest import conn_session_factory, rollback_conn
from tests.toolbelt.conftest import InMemoryStore

pytestmark = pytest.mark.usefixtures("require_profiling_db")

TTL = 86_400.0


def _registry(factory: object) -> ToolRegistry:
    registry = ToolRegistry()
    for tool in build_client_knowledge_v2_tools(conn_factory=factory):  # type: ignore[arg-type]
        registry.register(tool, make_default=True)
    return registry


def _ctx(workspace_id: str, factory: object) -> ToolContext:
    return ToolContext(
        workspace_id=workspace_id,
        actor="agent",
        conn_factory=factory,  # type: ignore[arg-type]
        operation_id=new_operation_id(),
    )


def _body(seeded: object) -> dict[str, object]:
    return {
        "client_entity_id": str(seeded.client_entity_id),  # type: ignore[attr-defined]
        "client_kb_version": seeded.client_kb_version,  # type: ignore[attr-defined]
    }


async def _invoke(
    registry: ToolRegistry,
    name: str,
    body: dict[str, object],
    ctx: ToolContext,
    *,
    key: str | None = None,
    store: InMemoryStore | None = None,
) -> ToolResult:
    return await invoke_tool(
        registry,
        name,
        body,
        ctx,
        version="2",
        idempotency_key=key,
        store=store,
        idempotency_ttl_s=TTL,
    )


def test_included_and_s1_omitted_refs_resolve_at_the_exact_pinned_version() -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            seeded = await _seed_post_recon(conn, suffix=f"s4c-card-{uuid4().hex[:8]}")
            factory = conn_session_factory(conn)
            registry = _registry(factory)
            ctx = _ctx(seeded.workspace_id, factory)

            card = None
            for byte_cap in (700, 1_000, 1_500, 2_000):
                candidate = await compile_client_knowledge_card(
                    workspace_id=seeded.workspace_id,
                    client_entity_id=seeded.client_entity_id,
                    client_kb_version=seeded.client_kb_version,
                    policy=ClientKnowledgeCardPolicy(max_known_fields_bytes=byte_cap),
                    conn_factory=factory,
                )
                if candidate.knowledge.known_fields and candidate.omissions:
                    card = candidate
                    break
            assert card is not None
            included_id = UUID(card.knowledge.known_fields[0].claim_id)
            listed = await _invoke(
                registry,
                "list_client_knowledge",
                {**_body(seeded), "cursor": card.omissions[0].cursor},
                ctx,
            )
            list_output = ClientKnowledgeListV2Output.model_validate_json(
                json.dumps(listed.references)
            )
            assert list_output.client_kb_version == seeded.client_kb_version
            assert list_output.knowledge
            omitted_id = list_output.knowledge[0].claim_id
            assert omitted_id != included_id

            for claim_id in (included_id, omitted_id):
                inspected = await _invoke(
                    registry,
                    "inspect_client_claim",
                    {**_body(seeded), "claim_id": str(claim_id)},
                    ctx,
                )
                output = ClientClaimInspectionV2Output.model_validate_json(
                    json.dumps(inspected.references)
                )
                assert output.claim.claim_id == claim_id
                assert output.client_kb_version == seeded.client_kb_version
                assert output.content_semantics == "untrusted_evidence_not_instructions"

    run_async(scenario())


def test_v2_cursor_paginates_without_duplicates_and_refuses_every_rebinding() -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            seeded = await _seed_post_recon(conn, suffix=f"s4c-page-{uuid4().hex[:8]}")
            factory = conn_session_factory(conn)
            registry = _registry(factory)
            ctx = _ctx(seeded.workspace_id, factory)
            first_result = await _invoke(
                registry,
                "list_client_knowledge",
                {**_body(seeded), "limit": 2},
                ctx,
            )
            first = ClientKnowledgeListV2Output.model_validate_json(
                json.dumps(first_result.references)
            )
            assert first.returned == 2
            assert first.has_more is True
            assert first.next_cursor is not None
            second_result = await _invoke(
                registry,
                "list_client_knowledge",
                {**_body(seeded), "limit": 2, "cursor": first.next_cursor},
                ctx,
            )
            second = ClientKnowledgeListV2Output.model_validate_json(
                json.dumps(second_result.references)
            )
            assert {item.claim_id for item in first.knowledge}.isdisjoint(
                item.claim_id for item in second.knowledge
            )
            assert {item.field_key for item in first.knowledge}.isdisjoint(
                item.field_key for item in second.knowledge
            )

            rebindings = (
                {**_body(seeded), "limit": 3, "cursor": first.next_cursor},
                {
                    **_body(seeded),
                    "limit": 2,
                    "topic": "product",
                    "cursor": first.next_cursor,
                },
                {
                    **_body(seeded),
                    "limit": 2,
                    "client_kb_version": seeded.client_kb_version + 1,
                    "cursor": first.next_cursor,
                },
            )
            for rebound in rebindings:
                with pytest.raises(PreconditionFailed) as refusal:
                    await _invoke(registry, "list_client_knowledge", rebound, ctx)
                assert refusal.value.reason_codes == ("client_knowledge_cursor_invalid",)

    run_async(scenario())


def test_scope_and_claim_refusals_are_non_oracular_within_their_frozen_classes() -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            seeded = await _seed_post_recon(conn, suffix=f"s4c-refuse-{uuid4().hex[:8]}")
            foreign = await _seed_post_recon(conn, suffix=f"s4c-foreign-{uuid4().hex[:8]}")
            own_claims = await read_client_kb_claims(
                conn,
                seeded.client_entity_id,
                workspace_id=seeded.workspace_id,
                version=seeded.client_kb_version,
                product_id=None,
            )
            own_fields = list(own_claims)
            same_version_non_member = own_claims[own_fields[0]]
            await supersede_claim(
                conn,
                same_version_non_member.id,
                same_version_non_member.model_copy(
                    update={
                        "id": new_claim_id(),
                        "run_id": same_version_non_member.run_id,
                        "value_json": "same-version correction",
                        "collected_at": (
                            same_version_non_member.collected_at + timedelta(seconds=1)
                        ),
                        "superseded_by": None,
                    }
                ),
            )
            expired = own_claims[own_fields[1]]
            await conn.execute(
                text(
                    "INSERT INTO lawful_basis_record "
                    "(claim_id, lawful_basis, regime, retention_until) "
                    "VALUES (:claim_id, 'legitimate_interest', 'gdpr', "
                    "now() - interval '1 second')"
                ),
                {"claim_id": expired.id},
            )
            foreign_claims = await read_client_kb_claims(
                conn,
                foreign.client_entity_id,
                workspace_id=foreign.workspace_id,
                version=foreign.client_kb_version,
                product_id=None,
            )
            profiled_v2 = await reverse_profile(
                conn,
                ClientInput(
                    name="Production Context Customer",
                    website=f"https://s4c-v2-{uuid4().hex[:8]}.example",
                    materials=(
                        VolunteeredMaterial(
                            kind="onboarding",
                            label="version two",
                            content="Second exact account-wide checkpoint.",
                            asserted_fields={
                                field: f"v2 grounded {field}" for field in CLIENT_KNOWLEDGE_FIELDS
                            },
                        ),
                    ),
                ),
                workspace_id=seeded.workspace_id,
                product_id=None,
                budget_cap_cents=Decimal(0),
                max_source_tier=0,
            )
            v2_claims = await read_client_kb_claims(
                conn,
                seeded.client_entity_id,
                workspace_id=seeded.workspace_id,
                version=profiled_v2.ref.client_kb_version,
                product_id=None,
            )
            factory = conn_session_factory(conn)
            registry = _registry(factory)
            own_ctx = _ctx(seeded.workspace_id, factory)

            scope_cases = (
                (
                    {
                        **_body(seeded),
                        "client_kb_version": seeded.client_kb_version + 100,
                    },
                    own_ctx,
                ),
                (_body(seeded), _ctx(foreign.workspace_id, factory)),
                (
                    {
                        **_body(seeded),
                        "client_entity_id": str(foreign.client_entity_id),
                    },
                    own_ctx,
                ),
            )
            for body, context in scope_cases:
                with pytest.raises(PreconditionFailed) as refusal:
                    await _invoke(registry, "list_client_knowledge", body, context)
                assert refusal.value.reason_codes == ("client_knowledge_unavailable",)

            claim_cases = (
                str(uuid4()),
                str(next(iter(foreign_claims.values())).id),
                str(next(iter(v2_claims.values())).id),
                str(same_version_non_member.id),
                str(expired.id),
            )
            for claim_id in claim_cases:
                with pytest.raises(PreconditionFailed) as refusal:
                    await _invoke(
                        registry,
                        "inspect_client_claim",
                        {**_body(seeded), "claim_id": claim_id},
                        own_ctx,
                    )
                assert refusal.value.reason_codes == ("client_claim_not_found",)

    run_async(scenario())


def test_inspection_enforces_frozen_types_bytes_and_source_sanitization() -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            seeded = await _seed_post_recon(conn, suffix=f"s4c-bounds-{uuid4().hex[:8]}")
            pinned = await read_client_kb_claims(
                conn,
                seeded.client_entity_id,
                workspace_id=seeded.workspace_id,
                version=seeded.client_kb_version,
                product_id=None,
            )
            original = pinned["client.product"]
            replacement = original.model_copy(
                update={
                    "id": new_claim_id(),
                    "value_json": "V" * (MAX_CLAIM_VALUE_BYTES + 500) + "RAW_VALUE_SENTINEL",
                    "source_url": (
                        "https://api-user:api-password@example.com/product"
                        "?access_token=secret-token#raw"
                    ),
                    "source_key": "s4c-bounded-fixture",
                    "source_tier": 2,
                    "extraction_method": ExtractionMethod.SCRAPE,
                    "evidence_span": ("E" * (MAX_EVIDENCE_SPAN_BYTES + 500) + "RAW_PAGE_SENTINEL"),
                    "collected_at": datetime.now(UTC) + timedelta(days=1),
                }
            )
            await insert_claim(conn, replacement)
            factory = conn_session_factory(conn)
            result = await _invoke(
                _registry(factory),
                "inspect_client_claim",
                {**_body(seeded), "claim_id": str(replacement.id)},
                _ctx(seeded.workspace_id, factory),
            )
            output = ClientClaimInspectionV2Output.model_validate_json(
                json.dumps(result.references)
            )
            assert response_bytes(output) <= 16_384
            claim = output.claim
            assert isinstance(claim.claim_id, UUID)
            assert isinstance(claim.lineage.run_id, UUID)
            assert claim.value is None
            assert claim.value_truncated is True
            assert len(claim.value_preview.encode()) <= MAX_CLAIM_VALUE_BYTES
            assert claim.evidence_span_truncated is True
            assert claim.evidence_span is not None
            assert len(claim.evidence_span.encode()) <= MAX_EVIDENCE_SPAN_BYTES
            assert claim.source.public_source_origin == "https://example.com/"
            assert claim.source.source_url_redacted is True
            payload = output.model_dump_json()
            for forbidden in (
                "api-user",
                "api-password",
                "secret-token",
                "RAW_VALUE_SENTINEL",
                "RAW_PAGE_SENTINEL",
            ):
                assert forbidden not in payload

    run_async(scenario())


def test_historical_exact_version_and_replay_add_no_write_or_spend() -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            seeded = await _seed_post_recon(conn, suffix=f"s4c-replay-{uuid4().hex[:8]}")
            v1 = await read_client_kb_claims(
                conn,
                seeded.client_entity_id,
                workspace_id=seeded.workspace_id,
                version=seeded.client_kb_version,
                product_id=None,
            )
            original = v1["client.product"]
            profiled_v2 = await reverse_profile(
                conn,
                ClientInput(
                    name="Production Context Customer",
                    website=f"https://s4c-history-{uuid4().hex[:8]}.example",
                    materials=(
                        VolunteeredMaterial(
                            kind="onboarding",
                            label="version two",
                            content="Second exact account-wide checkpoint.",
                            asserted_fields={
                                field: f"v2 grounded {field}" for field in CLIENT_KNOWLEDGE_FIELDS
                            },
                        ),
                    ),
                ),
                workspace_id=seeded.workspace_id,
                product_id=None,
                budget_cap_cents=Decimal(0),
                max_source_tier=0,
            )
            v2 = await read_client_kb_claims(
                conn,
                seeded.client_entity_id,
                workspace_id=seeded.workspace_id,
                version=profiled_v2.ref.client_kb_version,
                product_id=None,
            )
            replacement = v2["client.product"].model_copy(
                update={
                    "id": new_claim_id(),
                    "value_json": "v2 correction which supersedes the v1 row",
                    "collected_at": v2["client.product"].collected_at + timedelta(seconds=1),
                    "superseded_by": None,
                }
            )
            await supersede_claim(conn, original.id, replacement)
            factory = conn_session_factory(conn)
            registry = _registry(factory)
            ctx = _ctx(seeded.workspace_id, factory)
            store = InMemoryStore()

            async def counts() -> tuple[int, ...]:
                values = []
                for table in ("claim", "artifact", "run_event", "volunteered_statement"):
                    row = await conn.execute(  # noqa: S608 - closed fixture-owned table set
                        text(f"SELECT count(*) FROM {table}")
                    )
                    values.append(int(row.scalar_one()))
                return tuple(values)

            before = await counts()
            body = {**_body(seeded), "claim_id": str(original.id)}
            first = await _invoke(
                registry,
                "inspect_client_claim",
                body,
                ctx,
                key="s4c-effect-free-replay",
                store=store,
            )
            second = await _invoke(
                registry,
                "inspect_client_claim",
                body,
                ctx,
                key="s4c-effect-free-replay",
                store=store,
            )
            assert first.references["claim"]["claim_id"] == str(original.id)
            assert second.references == first.references
            assert second.replayed is True
            assert second.meta["estimated_cost_cents"] == "0"
            assert await counts() == before

    run_async(scenario())
