"""DB-backed S1 acceptance for the split production context compilers."""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal
from uuid import NAMESPACE_URL, uuid4, uuid5

import pytest
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_core import EntityId, OnboardingInputId, OnboardingInputKind
from clue_projections.production_context import (
    CLIENT_KNOWLEDGE_CARD_POLICY_V1,
    ClientKnowledgeScopeError,
    ProjectProductSelectionStatus,
    compile_client_knowledge_card,
    compile_stage0_project_state_card,
)
from clue_projections.stage0 import (
    STAGE0_CARD_POLICY_V1,
    ExcludedEvidence,
    ExcludedEvidenceReason,
    ResolvedQuote,
    Stage0CardOmissionKind,
    decode_card_cursor,
)
from clue_research.stage0 import (
    CLIENT_KNOWLEDGE_FIELDS,
    ClientInput,
    StatementRoute,
    VolunteeredMaterial,
    VolunteeredStatementRow,
    record_statement,
    reverse_profile,
    submit_onboarding_input,
)
from clue_spine import create_brand, create_product, create_project
from clue_storage import record_artifact
from tests._workspace import seed_workspace
from tests.db.conftest import run_async
from tests.profiling.conftest import conn_session_factory, rollback_conn

pytestmark = pytest.mark.usefixtures("require_profiling_db")


class _Evidence:
    def __init__(self, *, missing: frozenset[str] = frozenset()) -> None:
        self._missing = missing

    async def resolve_quote(
        self, *, workspace_id: str, statement: VolunteeredStatementRow
    ) -> ResolvedQuote | ExcludedEvidence:
        return (await self.resolve_quotes(workspace_id=workspace_id, statements=(statement,)))[0]

    async def resolve_quotes(
        self, *, workspace_id: str, statements: Sequence[VolunteeredStatementRow]
    ) -> tuple[ResolvedQuote | ExcludedEvidence, ...]:
        del workspace_id
        return tuple(
            ExcludedEvidence(
                statement_id=row.id,
                reason=ExcludedEvidenceReason.ARTIFACT_MISSING,
            )
            if str(row.id) in self._missing
            else ResolvedQuote(statement_id=row.id, quote=f"evidence for {row.route_key}")
            for row in statements
        )


@dataclass(frozen=True)
class _Scope:
    workspace_id: str
    brand_id: str
    product_id: str
    project_a: str
    project_b: str
    client_entity_id: EntityId
    client_kb_version: int


async def _seed(conn: AsyncConnection, *, suffix: str) -> _Scope:
    workspace_id = f"production-context-{suffix}"
    await seed_workspace(conn, workspace_id)
    brand = await create_brand(conn, workspace_id=workspace_id, name="Context Brand")
    product = await create_product(
        conn, workspace_id=workspace_id, brand_id=brand.brand_id, name="Product One"
    )
    project_a = await create_project(
        conn,
        workspace_id=workspace_id,
        brand_id=brand.brand_id,
        product_id=product.product_id,
        name="Project A",
    )
    project_b = await create_project(
        conn,
        workspace_id=workspace_id,
        brand_id=brand.brand_id,
        name="Project B",
    )
    profiled = await reverse_profile(
        conn,
        ClientInput(
            name="Context Customer",
            website=f"https://{suffix}.invalid",
            materials=(
                VolunteeredMaterial(
                    kind="onboarding",
                    label="onboarding facts",
                    content="Human-supplied, provenance-backed client facts.",
                    asserted_fields={
                        field: (
                            "a" * 255 + "éé" if field == "client.product" else f"grounded {field}"
                        )
                        for field in CLIENT_KNOWLEDGE_FIELDS
                    },
                ),
            ),
        ),
        workspace_id=workspace_id,
        # The production onboarding KB is account-wide. Project product confirmation must not
        # narrow this marker or make the shared customer knowledge disappear.
        product_id=None,
        budget_cap_cents=Decimal(0),
        max_source_tier=0,
    )
    return _Scope(
        workspace_id=workspace_id,
        brand_id=brand.brand_id,
        product_id=product.product_id,
        project_a=project_a.project_id,
        project_b=project_b.project_id,
        client_entity_id=profiled.ref.client_entity_id,
        client_kb_version=profiled.ref.client_kb_version,
    )


async def _statement(
    conn: AsyncConnection,
    scope: _Scope,
    *,
    project_id: str,
    route_key: str,
) -> str:
    body = f"captured interview for {project_id}: {route_key}".encode()
    digest = hashlib.sha256(body).hexdigest()
    artifact_key = f"{scope.workspace_id}/{digest}"
    await record_artifact(
        conn,
        storage_key=artifact_key,
        workspace_id=scope.workspace_id,
        content_sha256=digest,
        media_type="text/plain",
        size_bytes=len(body),
    )
    captured = await submit_onboarding_input(
        conn,
        workspace_id=scope.workspace_id,
        brand_id=scope.brand_id,
        product_id=scope.product_id if project_id == scope.project_a else None,
        project_id=project_id,
        client_entity_id=scope.client_entity_id,
        kind=OnboardingInputKind.USER_TURN,
        artifact_key=artifact_key,
        content_sha256=digest,
        actor="human",
        onboarding_input_id=OnboardingInputId(
            uuid5(NAMESPACE_URL, f"production-context:{project_id}:{route_key}")
        ),
    )
    statement_id = await record_statement(
        conn,
        onboarding_input_id=captured.onboarding_input_id,
        workspace_id=scope.workspace_id,
        brand_id=scope.brand_id,
        product_id=scope.product_id if project_id == scope.project_a else None,
        project_id=project_id,
        client_entity_id=scope.client_entity_id,
        entity_id=scope.client_entity_id,
        route_kind=StatementRoute.PROJECT_STATE,
        route_key=route_key,
        quote=body.decode(),
        quote_start=0,
        quote_end=len(body.decode()),
        created_by_actor="agent",
    )
    return str(statement_id)


def test_client_card_is_account_wide_exact_bounded_and_deterministic() -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            scope = await _seed(conn, suffix=uuid4().hex[:8])
            factory = conn_session_factory(conn)
            first = await compile_client_knowledge_card(
                workspace_id=scope.workspace_id,
                client_entity_id=scope.client_entity_id,
                client_kb_version=scope.client_kb_version,
                conn_factory=factory,
            )
            second = await compile_client_knowledge_card(
                workspace_id=scope.workspace_id,
                client_entity_id=scope.client_entity_id,
                client_kb_version=scope.client_kb_version,
                conn_factory=factory,
            )
            assert first.canonical_bytes() == second.canonical_bytes()
            assert first.content_sha256() == second.content_sha256()
            by_field = {entry.field_key: entry for entry in first.knowledge.known_fields}
            product = by_field["client.product"]
            assert product.brief_truncated is True
            assert product.brief_value == "a" * 255
            assert len(product.brief_value.encode()) <= 256
            assert all(
                entry.label and entry.description and entry.topic and entry.claim_id
                for entry in first.knowledge.known_fields
            )

            changed_policy = CLIENT_KNOWLEDGE_CARD_POLICY_V1.model_copy(
                update={"version": "client-knowledge-card-policy-v2-test"}
            )
            changed = await compile_client_knowledge_card(
                workspace_id=scope.workspace_id,
                client_entity_id=scope.client_entity_id,
                client_kb_version=scope.client_kb_version,
                policy=changed_policy,
                conn_factory=factory,
            )
            assert changed.content_sha256() != first.content_sha256()

            with pytest.raises(ClientKnowledgeScopeError):
                await compile_client_knowledge_card(
                    workspace_id=scope.workspace_id,
                    client_entity_id=scope.client_entity_id,
                    client_kb_version=scope.client_kb_version + 999,
                    conn_factory=factory,
                )
            await seed_workspace(conn, f"foreign-{scope.workspace_id}")
            with pytest.raises(ClientKnowledgeScopeError):
                await compile_client_knowledge_card(
                    workspace_id=f"foreign-{scope.workspace_id}",
                    client_entity_id=scope.client_entity_id,
                    client_kb_version=scope.client_kb_version,
                    conn_factory=factory,
                )

    run_async(scenario())


def test_project_a_and_b_share_client_card_but_never_project_state() -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            scope = await _seed(conn, suffix=uuid4().hex[:8])
            factory = conn_session_factory(conn)
            await _statement(conn, scope, project_id=scope.project_a, route_key="goal_a")
            await _statement(conn, scope, project_id=scope.project_b, route_key="goal_b")
            client = await compile_client_knowledge_card(
                workspace_id=scope.workspace_id,
                client_entity_id=scope.client_entity_id,
                client_kb_version=scope.client_kb_version,
                conn_factory=factory,
            )
            card_a = await compile_stage0_project_state_card(
                project_id=scope.project_a,
                workspace_id=scope.workspace_id,
                client_entity_id=scope.client_entity_id,
                client_kb_version=scope.client_kb_version,
                client_knowledge_sha256=client.content_sha256(),
                evidence=_Evidence(),
                conn_factory=factory,
            )
            card_b = await compile_stage0_project_state_card(
                project_id=scope.project_b,
                workspace_id=scope.workspace_id,
                client_entity_id=scope.client_entity_id,
                client_kb_version=scope.client_kb_version,
                client_knowledge_sha256=client.content_sha256(),
                evidence=_Evidence(),
                conn_factory=factory,
            )
            quotes_a = {item.quoted_text for item in card_a.interview.current_effective_statements}
            quotes_b = {item.quoted_text for item in card_b.interview.current_effective_statements}
            assert quotes_a == {"evidence for goal_a"}
            assert quotes_b == {"evidence for goal_b"}
            assert quotes_a.isdisjoint(quotes_b)
            assert card_a.product_selection.status is ProjectProductSelectionStatus.CONFIRMED
            assert card_b.product_selection.status is ProjectProductSelectionStatus.UNSELECTED
            assert card_a.compiled_from.client_knowledge_sha256 == client.content_sha256()
            assert card_b.compiled_from.client_knowledge_sha256 == client.content_sha256()

            before_b = card_b.content_sha256()
            await _statement(conn, scope, project_id=scope.project_a, route_key="audience_a")
            changed_a = await compile_stage0_project_state_card(
                project_id=scope.project_a,
                workspace_id=scope.workspace_id,
                client_entity_id=scope.client_entity_id,
                client_kb_version=scope.client_kb_version,
                client_knowledge_sha256=client.content_sha256(),
                evidence=_Evidence(),
                conn_factory=factory,
            )
            unchanged_b = await compile_stage0_project_state_card(
                project_id=scope.project_b,
                workspace_id=scope.workspace_id,
                client_entity_id=scope.client_entity_id,
                client_kb_version=scope.client_kb_version,
                client_knowledge_sha256=client.content_sha256(),
                evidence=_Evidence(),
                conn_factory=factory,
            )
            assert changed_a.content_sha256() != card_a.content_sha256()
            assert unchanged_b.content_sha256() == before_b

    run_async(scenario())


def test_omission_cursor_and_dsar_absence_are_explicit_and_deterministic() -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            scope = await _seed(conn, suffix=uuid4().hex[:8])
            factory = conn_session_factory(conn)
            statement_id = await _statement(
                conn, scope, project_id=scope.project_a, route_key="erased_answer"
            )
            tight = CLIENT_KNOWLEDGE_CARD_POLICY_V1.model_copy(
                update={"version": "tight-cursor-v1", "max_known_fields_bytes": 1}
            )
            first = await compile_client_knowledge_card(
                workspace_id=scope.workspace_id,
                client_entity_id=scope.client_entity_id,
                client_kb_version=scope.client_kb_version,
                policy=tight,
                conn_factory=factory,
            )
            second = await compile_client_knowledge_card(
                workspace_id=scope.workspace_id,
                client_entity_id=scope.client_entity_id,
                client_kb_version=scope.client_kb_version,
                policy=tight,
                conn_factory=factory,
            )
            assert first.omissions == second.omissions
            (omission,) = first.omissions
            cursor = decode_card_cursor(omission.cursor)
            assert cursor == {
                "after_field_key": None,
                "client_entity_id": str(scope.client_entity_id),
                "client_kb_version": scope.client_kb_version,
                "compiler_policy_version": "tight-cursor-v1",
                "kind": "client_knowledge",
                "schema_version": "1",
            }

            project = await compile_stage0_project_state_card(
                project_id=scope.project_a,
                workspace_id=scope.workspace_id,
                client_entity_id=scope.client_entity_id,
                client_kb_version=scope.client_kb_version,
                client_knowledge_sha256=first.content_sha256(),
                evidence=_Evidence(missing=frozenset({statement_id})),
                conn_factory=factory,
            )
            assert project.interview.current_effective_statements == ()
            assert any(
                item.kind is Stage0CardOmissionKind.EXCLUDED_STATEMENT_EVIDENCE_MISSING
                for item in project.omissions
            )

            source_policy = STAGE0_CARD_POLICY_V1.model_copy(
                update={"version": "stage0-source-policy-v2-test"}
            )
            changed = await compile_stage0_project_state_card(
                project_id=scope.project_a,
                workspace_id=scope.workspace_id,
                client_entity_id=scope.client_entity_id,
                client_kb_version=scope.client_kb_version,
                client_knowledge_sha256=first.content_sha256(),
                evidence=_Evidence(missing=frozenset({statement_id})),
                policy=source_policy,
                conn_factory=factory,
            )
            assert changed.compiled_from.source_policy_version == source_policy.version
            assert changed.content_sha256() != project.content_sha256()

    run_async(scenario())
