"""S4 acceptance for governed Client-KB discovery and exact claim inspection.

These tests use the real versioned claim store and production workspace/client/project binding.
They prove the card-to-tool continuation, exact version membership, indistinguishable fail-closed
refusals, bounded provenance, and effect-free replay contracts rather than only schema shape.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import text

from clue_api.client_knowledge_tools import (
    MAX_CLAIM_VALUE_BYTES,
    MAX_CLIENT_KNOWLEDGE_PAGE,
    MAX_EVIDENCE_SPAN_BYTES,
    build_client_knowledge_tools,
)
from clue_core import ExtractionMethod, new_claim_id, new_operation_id, new_run_id
from clue_projections import ClientKnowledgeCardPolicy, compile_client_knowledge_card
from clue_research.claimstore import insert_claim, supersede_claim
from clue_research.stage0 import (
    CLIENT_KNOWLEDGE_FIELDS,
    ClientInput,
    VolunteeredMaterial,
    read_client_kb_claims,
    reverse_profile,
)
from clue_toolbelt import PreconditionFailed, ToolContext, ToolRegistry, invoke_tool
from tests.api.test_production_context_s3_db import _seed_post_recon
from tests.db.conftest import run_async
from tests.profiling.conftest import conn_session_factory, rollback_conn
from tests.toolbelt.conftest import InMemoryStore

pytestmark = pytest.mark.usefixtures("require_profiling_db")

TTL = 86_400.0


def _registry(factory: object) -> ToolRegistry:
    registry = ToolRegistry()
    for tool in build_client_knowledge_tools(conn_factory=factory):  # type: ignore[arg-type]
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
        "project_id": seeded.project_a.project_id,  # type: ignore[attr-defined]
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
):
    return await invoke_tool(
        registry,
        name,
        body,
        ctx,
        idempotency_key=key,
        store=store,
        idempotency_ttl_s=TTL,
    )


def test_card_refs_and_the_omission_cursor_resolve_at_the_exact_pinned_version() -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            seeded = await _seed_post_recon(conn, suffix=f"s4-card-{uuid4().hex[:8]}")
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
            assert card is not None, "fixture did not create both an included and omitted ref"
            omission = card.omissions[0]
            listed = await _invoke(
                registry,
                "list_client_knowledge",
                {**_body(seeded), "cursor": omission.cursor},
                ctx,
            )
            assert listed.references["client_kb_version"] == seeded.client_kb_version
            assert listed.references["returned"] <= MAX_CLIENT_KNOWLEDGE_PAGE
            shown_ids = {entry.claim_id for entry in card.knowledge.known_fields}
            omitted_ids = {entry["claim_id"] for entry in listed.references["knowledge"]}
            assert omitted_ids
            assert shown_ids.isdisjoint(omitted_ids)

            for claim_id in (next(iter(shown_ids)), next(iter(omitted_ids))):
                inspected = await _invoke(
                    registry,
                    "inspect_client_claim",
                    {**_body(seeded), "claim_id": claim_id},
                    ctx,
                )
                assert inspected.references["client_kb_version"] == seeded.client_kb_version
                assert inspected.references["claim"]["claim_id"] == claim_id

            product_only = await _invoke(
                registry,
                "list_client_knowledge",
                {**_body(seeded), "topic": "product", "field_key": "client.product"},
                ctx,
            )
            assert [entry["field_key"] for entry in product_only.references["knowledge"]] == [
                "client.product"
            ]

    run_async(scenario())


def test_inspection_bounds_values_evidence_and_credential_bearing_urls() -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            seeded = await _seed_post_recon(conn, suffix=f"s4-bounds-{uuid4().hex[:8]}")
            pinned = await read_client_kb_claims(
                conn,
                seeded.client_entity_id,
                workspace_id=seeded.workspace_id,
                version=seeded.client_kb_version,
                product_id=None,
            )
            original = pinned["client.product"]
            long_value = "V" * (MAX_CLAIM_VALUE_BYTES + 500) + "RAW_VALUE_SENTINEL"
            long_evidence = "E" * (MAX_EVIDENCE_SPAN_BYTES + 500) + "RAW_PAGE_SENTINEL"
            replacement = original.model_copy(
                update={
                    "id": new_claim_id(),
                    "value_json": long_value,
                    "source_url": (
                        "https://api-user:api-password@example.com/product"
                        "?access_token=secret-token#raw"
                    ),
                    "source_key": "s4-bounded-fixture",
                    "source_tier": 2,
                    "extraction_method": ExtractionMethod.SCRAPE,
                    "evidence_span": long_evidence,
                    "collected_at": datetime.now(UTC) + timedelta(days=1),
                }
            )
            await insert_claim(conn, replacement)

            factory = conn_session_factory(conn)
            registry = _registry(factory)
            result = await _invoke(
                registry,
                "inspect_client_claim",
                {**_body(seeded), "claim_id": str(replacement.id)},
                _ctx(seeded.workspace_id, factory),
            )
            claim = result.references["claim"]
            payload = str(claim)
            assert claim["value"] is None
            assert claim["value_truncated"] is True
            assert len(claim["value_preview"].encode()) <= MAX_CLAIM_VALUE_BYTES
            assert claim["evidence_span_truncated"] is True
            assert len(claim["evidence_span"].encode()) <= MAX_EVIDENCE_SPAN_BYTES
            assert claim["source"]["source_url"] == "https://example.com/"
            assert claim["source"]["source_url_redacted"] is True
            for forbidden in (
                "api-user",
                "api-password",
                "secret-token",
                "RAW_VALUE_SENTINEL",
                "RAW_PAGE_SENTINEL",
            ):
                assert forbidden not in payload

    run_async(scenario())


def test_foreign_unknown_wrong_version_superseded_and_expired_refs_refuse_identically() -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            suffix = f"s4-refusal-{uuid4().hex[:8]}"
            seeded = await _seed_post_recon(conn, suffix=suffix)
            pinned = await read_client_kb_claims(
                conn,
                seeded.client_entity_id,
                workspace_id=seeded.workspace_id,
                version=seeded.client_kb_version,
                product_id=None,
            )
            fields = list(pinned)

            profiled_v2 = await reverse_profile(
                conn,
                ClientInput(
                    name="Production Context Customer",
                    website=f"https://{suffix}.example",
                    materials=(
                        VolunteeredMaterial(
                            kind="onboarding",
                            label="version two",
                            content="Second exact account-wide checkpoint.",
                            asserted_fields={
                                key: f"v2 grounded {key}" for key in CLIENT_KNOWLEDGE_FIELDS
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
            foreign = await _seed_post_recon(conn, suffix=f"foreign-{uuid4().hex[:8]}")
            foreign_claims = await read_client_kb_claims(
                conn,
                foreign.client_entity_id,
                workspace_id=foreign.workspace_id,
                version=foreign.client_kb_version,
                product_id=None,
            )

            superseded = pinned[fields[0]]
            await supersede_claim(
                conn,
                superseded.id,
                superseded.model_copy(
                    update={
                        "id": new_claim_id(),
                        "run_id": new_run_id(),
                        "value_json": "explicit correction outside the pinned checkpoint",
                        "superseded_by": None,
                    }
                ),
            )
            expired = pinned[fields[1]]
            await conn.execute(
                text(
                    "INSERT INTO lawful_basis_record "
                    "(claim_id, lawful_basis, regime, retention_until) "
                    "VALUES (:claim_id, 'legitimate_interest', 'gdpr', "
                    "now() - interval '1 second')"
                ),
                {"claim_id": expired.id},
            )

            refs = {
                "unknown": str(uuid4()),
                "foreign": str(next(iter(foreign_claims.values())).id),
                "wrong_version": str(next(iter(v2.values())).id),
                "superseded": str(superseded.id),
                "expired": str(expired.id),
            }
            factory = conn_session_factory(conn)
            registry = _registry(factory)
            ctx = _ctx(seeded.workspace_id, factory)
            observed: dict[str, tuple[str, ...]] = {}
            for label, claim_id in refs.items():
                with pytest.raises(PreconditionFailed) as refusal:
                    await _invoke(
                        registry,
                        "inspect_client_claim",
                        {**_body(seeded), "claim_id": claim_id},
                        ctx,
                    )
                observed[label] = refusal.value.reason_codes
            assert set(observed.values()) == {("client_claim_not_found",)}

    run_async(scenario())


def test_replay_is_zero_write_zero_spend_and_returns_the_same_reference_set() -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            seeded = await _seed_post_recon(conn, suffix=f"s4-replay-{uuid4().hex[:8]}")
            factory = conn_session_factory(conn)
            registry = _registry(factory)
            ctx = _ctx(seeded.workspace_id, factory)
            store = InMemoryStore()

            async def counts() -> tuple[int, ...]:
                values: list[int] = []
                for table in ("claim", "artifact", "run_event", "volunteered_statement"):
                    result = await conn.execute(  # noqa: S608 - closed fixture-owned table set
                        text(f"SELECT count(*) FROM {table}")
                    )
                    values.append(int(result.scalar_one()))
                return tuple(values)

            before = await counts()
            first = await _invoke(
                registry,
                "list_client_knowledge",
                _body(seeded),
                ctx,
                key="s4-effect-free-replay",
                store=store,
            )
            second = await _invoke(
                registry,
                "list_client_knowledge",
                _body(seeded),
                ctx,
                key="s4-effect-free-replay",
                store=store,
            )
            assert second.replayed is True
            assert second.references == first.references
            assert second.meta["estimated_cost_cents"] == "0"
            assert await counts() == before
            for descriptor in registry.descriptors():
                assert descriptor.effect_class.value == "read"
                assert descriptor.replay.policy.value == "effect_free"
                assert descriptor.replay.external_boundary.value == "none"

    run_async(scenario())
