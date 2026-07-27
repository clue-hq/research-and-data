"""C7.4 reference-only snapshots and current-policy evidence access."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_api.evidence_access import (
    EphemeralEvidenceCapabilityBroker,
    EvidenceAccessServiceImpl,
)
from clue_core import (
    DisplayDecision,
    EvidenceAccessDecision,
    EvidenceAccessRequest,
    EvidenceActionDescriptor,
    EvidenceActionKind,
    OutreachDecision,
    ResearchAvailability,
    ResearchOwnedReference,
    ResearchPersonalizationItem,
    ResearchStatement,
    ResearchSubjectRef,
    ResearchView,
    ResearchViewReadRequest,
    new_operation_id,
)
from clue_research.narrative import (
    ResearchViewSnapshotCommand,
    ResearchViewSnapshotConflict,
    ResearchViewSnapshotService,
    reference_composition_sha256,
)
from clue_spine import create_brand, create_product, create_project, create_workspace
from clue_storage import StorageBackend, mark_erased, record_artifact

from .conftest import rollback_conn, run_async
from .test_research_views import _compose_account_fixture

_MIGRATION = (
    Path(__file__).resolve().parents[2]
    / "alembic/versions/a69a1769d4bc_c7_4_reference_only_research_view_.py"
)


class _Composer:
    def __init__(self, view: ResearchView) -> None:
        self.view = view
        self.calls = 0

    async def compose(self, request: ResearchViewReadRequest) -> ResearchView:
        self.calls += 1
        assert request.workspace_id == self.view.workspace_id
        assert request.project_id == self.view.project_id
        assert request.project_run_id == self.view.project_run_id
        assert request.subject_entity_id == self.view.subject.entity_id
        return self.view


class _Reachability:
    def __init__(self, view: ResearchView) -> None:
        subjects = {view.subject.entity_id: view.subject}
        for section in view.sections:
            for item in section.items:
                if isinstance(item, ResearchOwnedReference):
                    subjects[item.subject.entity_id] = item.subject
        self.subjects = tuple(subjects.values())

    async def subjects_for_claims(
        self, *, workspace_id: str, claim_ids: tuple[UUID, ...]
    ) -> tuple[ResearchSubjectRef, ...]:
        del workspace_id, claim_ids
        return self.subjects


class _Allow:
    async def authorize(self, request: EvidenceAccessRequest) -> EvidenceAccessDecision:
        return EvidenceAccessDecision(
            allowed=True,
            action_kind=request.desired_action,
            claim_id=request.claim_id,
            reason_codes=("actor_scope_allowed",),
        )


class _Storage(StorageBackend):
    def __init__(self) -> None:
        self.presign_expiries: list[int] = []

    async def put(self, key: str, data: bytes, *, media_type: str) -> None:
        del key, data, media_type

    async def get(self, key: str) -> bytes:
        raise AssertionError(f"unexpected get: {key}")

    async def delete(self, key: str) -> None:
        del key

    async def exists(self, key: str) -> bool:
        del key
        return True

    async def presign(self, key: str, *, expires_in: int = 3600) -> str:
        self.presign_expiries.append(expires_in)
        return f"https://signed.invalid/{key}"

    async def _empty(self) -> AsyncIterator[tuple[str, datetime]]:
        if False:
            yield "", datetime.now(UTC)

    def list_blobs(self) -> AsyncIterator[tuple[str, datetime]]:
        return self._empty()


@asynccontextmanager
async def _fixed(conn: AsyncConnection) -> AsyncIterator[AsyncConnection]:
    yield conn


async def _seed_scope(conn: AsyncConnection, view: ResearchView) -> None:
    workspace = await create_workspace(conn, workspace_id=view.workspace_id, name="C7 workspace")
    brand = await create_brand(
        conn,
        workspace_id=workspace.workspace_id,
        brand_id="brand-c7",
        name="C7 brand",
    )
    product = await create_product(
        conn,
        workspace_id=workspace.workspace_id,
        brand_id=brand.brand_id,
        product_id=view.product_id,
        name="C7 product",
    )
    await create_project(
        conn,
        workspace_id=workspace.workspace_id,
        brand_id=brand.brand_id,
        product_id=product.product_id,
        project_id=view.project_id,
        name="C7 project",
    )
    await conn.execute(
        text(
            """
            INSERT INTO project_run (
                id, project_id, brand_id, workspace_id, icp_key, icp_version
            ) VALUES (
                :id, :project_id, :brand_id, :workspace_id, 'default', 1
            )
            """
        ),
        {
            "id": str(view.project_run_id),
            "project_id": view.project_id,
            "brand_id": brand.brand_id,
            "workspace_id": view.workspace_id,
        },
    )
    await conn.execute(
        text(
            """
            INSERT INTO account_entity (id, canonical_name, status, workspace_id)
            VALUES (:id, 'C7 account', 'active', :workspace_id)
            """
        ),
        {"id": str(view.subject.entity_id), "workspace_id": view.workspace_id},
    )


def _first_statement(view: ResearchView) -> ResearchStatement:
    for section in view.sections:
        for item in section.items:
            if isinstance(item, ResearchStatement):
                return item
            if isinstance(item, ResearchPersonalizationItem):
                return item.statement
    raise AssertionError("fixture has no statement")


def test_snapshot_schema_declares_no_body_or_locator_columns() -> None:
    source = _MIGRATION.read_text(encoding="utf-8").lower()
    receipt_ddl = source[
        source.index("create table research_view_snapshot (") : source.index(
            "# legacy compatibility"
        )
    ]
    forbidden = (
        "value_json",
        "evidence_span",
        "source_url",
        "storage_key",
        "signed_url",
        "rendered_body",
        "markdown",
        "html_body",
        "rationale",
        "payload jsonb",
    )
    assert all(token not in receipt_ddl for token in forbidden)
    assert "reason_codes" in receipt_ddl
    assert "composition_sha256" in receipt_ddl


def test_reference_composition_hash_is_deterministic() -> None:
    view, _request, _composer_value, _candidates = run_async(_compose_account_fixture())
    assert reference_composition_sha256(view) == reference_composition_sha256(view)
    assert len(reference_composition_sha256(view)) == 64


@pytest.mark.usefixtures("require_narrative_db")
def test_snapshot_is_atomic_idempotent_body_free_and_replayed_live() -> None:
    sentinel = "C7_SNAPSHOT_BODY_SENTINEL_b112f9"

    async def scenario() -> None:
        view, request, _fixture_composer, _candidates = await _compose_account_fixture()
        statement = _first_statement(view)
        sections = tuple(
            section.model_copy(
                update={
                    "items": tuple(
                        item.model_copy(
                            update={"value_json": sentinel}
                            if isinstance(item, ResearchStatement)
                            and item.statement_id == statement.statement_id
                            else {}
                        )
                        for item in section.items
                    )
                }
            )
            for section in view.sections
        )
        view = view.model_copy(update={"sections": sections})
        composer = _Composer(view)

        async with rollback_conn() as conn:
            await _seed_scope(conn, view)
            service = ResearchViewSnapshotService(
                composer,
                _Reachability(view),  # type: ignore[arg-type]
                conn_factory=lambda: _fixed(conn),
            )
            operation_id = new_operation_id()
            command = ResearchViewSnapshotCommand(
                operation_id=operation_id,
                request=request,
            )
            first = await service.compose_and_save(command)
            second = await service.compose_and_save(command)
            assert first == second
            assert composer.calls == 1
            with pytest.raises(ResearchViewSnapshotConflict, match="different research-view"):
                await service.compose_and_save(
                    command.model_copy(
                        update={
                            "request": request.model_copy(
                                update={"project_id": "different-project"}
                            )
                        }
                    )
                )

            serialized = (
                await conn.execute(
                    text(
                        """
                        SELECT concat_ws(' ',
                            coalesce(jsonb_agg(to_jsonb(s))::text, ''),
                            coalesce((
                                SELECT jsonb_agg(to_jsonb(i))::text
                                FROM research_view_snapshot_item i
                                WHERE i.snapshot_id = :snapshot_id
                            ), ''),
                            coalesce((
                                SELECT jsonb_agg(to_jsonb(a))::text
                                FROM research_view_snapshot_evidence_action a
                                WHERE a.snapshot_id = :snapshot_id
                            ), '')
                        )
                        FROM research_view_snapshot s
                        WHERE s.snapshot_id = :snapshot_id
                        """
                    ),
                    {"snapshot_id": str(first.snapshot_id)},
                )
            ).scalar_one()
            assert sentinel not in serialized
            assert "synthetic evidence" not in serialized
            assert "synthetic.invalid" not in serialized

            reached = (
                await conn.execute(
                    text(
                        "SELECT subject_entity_id FROM research_view_snapshot_subject "
                        "WHERE snapshot_id = :snapshot_id"
                    ),
                    {"snapshot_id": str(first.snapshot_id)},
                )
            ).scalars()
            assert view.subject.entity_id in set(reached)

            hidden_state = statement.state.model_copy(
                update={
                    "availability": ResearchAvailability.REDACTED,
                    "display_decision": DisplayDecision.DENIED,
                    "outreach_decision": OutreachDecision.NOT_APPLICABLE,
                    "reason_codes": ("claim_erased",),
                }
            )
            current_sections = tuple(
                section.model_copy(
                    update={
                        "items": tuple(
                            item.model_copy(
                                update={
                                    "value_json": None,
                                    "state": hidden_state,
                                    "evidence_actions": (),
                                }
                            )
                            if isinstance(item, ResearchStatement)
                            and item.statement_id == statement.statement_id
                            else item
                            for item in section.items
                        )
                    }
                )
                for section in view.sections
            )
            composer.view = view.model_copy(update={"sections": current_sections})
            replayed = await service.resolve(
                workspace_id=view.workspace_id,
                snapshot_id=first.snapshot_id,
            )
            assert replayed is not None
            assert replayed.snapshot_id == first.snapshot_id
            assert composer.calls == 2
            replayed_statement = _first_statement(replayed)
            assert replayed_statement.value_json is None
            assert replayed_statement.state.availability is ResearchAvailability.REDACTED
            assert (
                await service.resolve(
                    workspace_id="wrong-workspace",
                    snapshot_id=first.snapshot_id,
                )
                is None
            )

    run_async(scenario())


@pytest.mark.usefixtures("require_narrative_db")
def test_evidence_access_requires_exact_scope_and_returns_only_opaque_capability() -> None:
    async def scenario() -> None:
        view, request, _fixture_composer, candidates = await _compose_account_fixture()
        statement = _first_statement(view)
        candidate = next(value for value in candidates if value.claim.id == statement.claim_id)
        assert statement.evidence_actions
        action = statement.evidence_actions[0]
        assert action.action_id is not None
        public_action = EvidenceActionDescriptor(
            kind=EvidenceActionKind.OPEN_PUBLIC_SOURCE,
            claim_id=statement.claim_id,
            action_id=uuid4(),
        )
        artifact_action = EvidenceActionDescriptor(
            kind=EvidenceActionKind.REQUEST_ARTIFACT_PREVIEW,
            claim_id=statement.claim_id,
            action_id=uuid4(),
            media_type="application/pdf",
        )
        sections = tuple(
            section.model_copy(
                update={
                    "items": tuple(
                        item.model_copy(
                            update={
                                "evidence_actions": (
                                    *statement.evidence_actions,
                                    public_action,
                                    artifact_action,
                                )
                            }
                            if isinstance(item, ResearchStatement)
                            and item.statement_id == statement.statement_id
                            else {}
                        )
                        for item in section.items
                    )
                }
            )
            for section in view.sections
        )
        view = view.model_copy(update={"sections": sections})

        async with rollback_conn() as conn:
            await _seed_scope(conn, view)
            claim = candidate.claim
            artifact_key = "public/" + ("a" * 64)
            await record_artifact(
                conn,
                storage_key=artifact_key,
                workspace_id=None,
                content_sha256="a" * 64,
                media_type="application/pdf",
                size_bytes=42,
            )
            await conn.execute(
                text(
                    """
                    INSERT INTO claim (
                        id, entity_id, entity_type, field_key, value_json, source_url,
                        artifact_key, source_tier, extraction_method, evidence_span,
                        confidence, run_id,
                        research_mode, verification_status, claim_flavor, reuse_scope,
                        workspace_id, product_id
                    ) VALUES (
                        :id, :entity_id, CAST(:entity_type AS entity_type), :field_key,
                        CAST(:value_json AS jsonb), :source_url, :artifact_key, :source_tier,
                        CAST(:extraction_method AS extraction_method), :evidence_span,
                        :confidence, :run_id, CAST(:research_mode AS research_mode),
                        CAST(:verification_status AS verification_status),
                        CAST(:claim_flavor AS claim_flavor), CAST(:reuse_scope AS reuse_scope),
                        :workspace_id, :product_id
                    )
                    """
                ),
                {
                    "id": str(claim.id),
                    "entity_id": str(claim.entity_id),
                    "entity_type": claim.entity_type.value,
                    "field_key": str(claim.field_key),
                    "value_json": json.dumps(claim.value_json),
                    "source_url": claim.source_url,
                    "artifact_key": artifact_key,
                    "source_tier": claim.source_tier,
                    "extraction_method": claim.extraction_method.value,
                    "evidence_span": claim.evidence_span,
                    "confidence": claim.confidence,
                    "run_id": str(claim.run_id),
                    "research_mode": claim.research_mode.value,
                    "verification_status": claim.verification_status.value,
                    "claim_flavor": claim.claim_flavor.value,
                    "reuse_scope": claim.reuse_scope.value,
                    "workspace_id": claim.workspace_id,
                    "product_id": claim.product_id,
                },
            )
            snapshot_service = ResearchViewSnapshotService(
                _Composer(view),
                _Reachability(view),  # type: ignore[arg-type]
                conn_factory=lambda: _fixed(conn),
            )
            await snapshot_service.compose_and_save(
                ResearchViewSnapshotCommand(
                    operation_id=new_operation_id(),
                    request=request,
                )
            )
            other = await create_project(
                conn,
                workspace_id=view.workspace_id,
                brand_id="brand-c7",
                product_id=view.product_id,
                project_id="project-c7-other",
                name="Other C7 project",
            )
            broker = EphemeralEvidenceCapabilityBroker()
            storage = _Storage()
            service = EvidenceAccessServiceImpl(
                _Allow(),
                storage,
                broker,
                conn_factory=lambda: _fixed(conn),
                preview_ttl_seconds=9999,
            )
            access_request = EvidenceAccessRequest(
                workspace_id=view.workspace_id,
                project_id=view.project_id,
                actor_id="actor-c7",
                subject_entity_id=view.subject.entity_id,
                statement_id=statement.statement_id,
                claim_id=statement.claim_id,
                action_id=action.action_id,
                desired_action=action.kind,
            )
            result = await service.request_access(access_request)
            assert result.action_kind is EvidenceActionKind.VIEW_API_PROVENANCE
            assert result.access_ref is not None
            assert "://" not in result.access_ref
            assert broker.resolve(result.access_ref) == f"api-provenance:{statement.claim_id}"

            public_result = await service.request_access(
                access_request.model_copy(
                    update={
                        "action_id": public_action.action_id,
                        "desired_action": public_action.kind,
                    }
                )
            )
            assert public_result.action_kind is EvidenceActionKind.OPEN_PUBLIC_SOURCE
            assert public_result.access_ref is not None
            assert broker.resolve(public_result.access_ref) == candidate.claim.source_url

            artifact_result = await service.request_access(
                access_request.model_copy(
                    update={
                        "action_id": artifact_action.action_id,
                        "desired_action": artifact_action.kind,
                    }
                )
            )
            assert artifact_result.action_kind is EvidenceActionKind.REQUEST_ARTIFACT_PREVIEW
            assert artifact_result.access_ref is not None
            assert "signed.invalid" not in artifact_result.access_ref
            assert storage.presign_expiries == [300]

            await mark_erased(conn, artifact_key)
            erased_artifact = await service.request_access(
                access_request.model_copy(
                    update={
                        "action_id": artifact_action.action_id,
                        "desired_action": artifact_action.kind,
                    }
                )
            )
            assert erased_artifact.action_kind is EvidenceActionKind.REDACTED
            assert erased_artifact.access_ref is None

            crossed = await service.request_access(
                access_request.model_copy(update={"project_id": other.project_id})
            )
            assert crossed.action_kind is EvidenceActionKind.UNAVAILABLE
            assert crossed.access_ref is None

            audits = (
                await conn.execute(
                    text(
                        "SELECT allowed, reason_codes FROM evidence_access_audit "
                        "WHERE actor_id = 'actor-c7' ORDER BY created_at"
                    )
                )
            ).all()
            assert [row[0] for row in audits] == [True, True, True, False, False]
            assert "api-provenance:" not in str(audits)
            assert "https://" not in str(audits)

    run_async(scenario())
