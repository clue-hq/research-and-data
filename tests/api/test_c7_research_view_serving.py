"""C7.7 tool/API/projection/event and legacy-alias integration contract."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from datetime import datetime

import httpx
import pytest
from httpx import ASGITransport
from sqlalchemy import text

from clue_api import build_tool_invoker, build_toolbelt, create_projections_app
from clue_config import Settings, load_settings
from clue_core import (
    EvidenceAccessRequest,
    EvidenceAccessResult,
    EvidenceActionKind,
    ProjectRunId,
    ResearchSectionKind,
    ResearchStatement,
    new_operation_id,
    new_run_id,
)
from clue_execution.run_events import list_run_events
from clue_research.durable import AccountRunStatus, insert_account_run
from clue_research.narrative import (
    ResearchViewRecheckService,
    ResearchViewSnapshotService,
    project_nine_blocks,
)
from clue_spine import create_brand, create_project, create_workspace
from clue_toolbelt import DbIdempotencyStore, ToolContext
from tests.narrative.conftest import require_narrative_db as require_narrative_db  # noqa: F401
from tests.narrative.test_research_view_snapshots import (
    _Composer,
    _Reachability,
    _seed_scope,
)
from tests.narrative.test_research_views import (
    _compose_account_fixture,
    _compose_contact_fixture,
)
from tests.profiling.conftest import conn_session_factory, rollback_conn
from tests.projections._helpers import build_surface

pytestmark = pytest.mark.usefixtures("require_narrative_db")


class _MemoryStorage:
    def __init__(self) -> None:
        self.blobs: dict[str, bytes] = {}

    async def put(self, key: str, data: bytes, *, media_type: str) -> None:
        del media_type
        self.blobs[key] = data

    async def get(self, key: str) -> bytes:
        return self.blobs[key]

    async def delete(self, key: str) -> None:
        self.blobs.pop(key, None)

    async def exists(self, key: str) -> bool:
        return key in self.blobs

    async def presign(self, key: str, *, expires_in: int = 3600) -> str:
        return f"memory-capability:{key}:{expires_in}"

    async def list_blobs(self) -> AsyncIterator[tuple[str, datetime]]:
        if False:
            yield "", datetime.min


class _UnavailableEvidence:
    async def request_access(self, request: EvidenceAccessRequest) -> EvidenceAccessResult:
        return EvidenceAccessResult(
            action_kind=EvidenceActionKind.UNAVAILABLE,
            claim_id=request.claim_id,
            reason_codes=("current_policy_denied",),
        )


class _EmptyOwnerReferences:
    async def resolve(self, *_args: object) -> tuple[()]:
        return ()


def _client(app) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://c7")


def _c7_settings() -> Settings:
    return load_settings(
        c7_research_view_read_enabled=True,
        c7_snapshot_compose_enabled=True,
        c7_evidence_actions_enabled=True,
        c7_recheck_enabled=True,
        c7_legacy_dossier_alias_enabled=True,
        _env_file=None,
    )


def test_c7_serving_is_scoped_replay_safe_body_free_and_alias_exact() -> None:
    async def scenario() -> None:
        view, request, _fixture_composer, _candidates = await _compose_account_fixture()
        composer = _Composer(view)
        connection_context = rollback_conn()
        conn = await connection_context.__aenter__()
        await _seed_scope(conn, view)
        await insert_account_run(
            conn,
            account_run_id=new_run_id(),
            project_run_id=ProjectRunId(view.project_run_id),
            entity_id=view.subject.entity_id,
            tier="top",
            status=AccountRunStatus.DONE,
        )
        cf = conn_session_factory(conn)
        snapshots = ResearchViewSnapshotService(
            composer,
            _Reachability(view),
            conn_factory=cf,
        )
        recheck = ResearchViewRecheckService(
            snapshots=snapshots,
            conn_factory=cf,
        )
        registry = build_toolbelt(
            storage=None,
            settings=_c7_settings(),
            gateway=None,
            conn_factory=cf,
            research_view_composer=composer,
            research_view_snapshots=snapshots,
            research_view_recheck=recheck,
        )
        storage = _MemoryStorage()
        invoker = build_tool_invoker(
            registry=registry,
            idempotency_store=DbIdempotencyStore(conn_factory=cf),
            storage=storage,
            settings=_c7_settings(),
            conn_factory=cf,
        )
        app = create_projections_app(
            surface=build_surface(conn),
            tool_invoker=invoker,
            settings=_c7_settings(),
            conn_factory=cf,
            manage_db_lifespan=False,
            sse_live_tail=False,
            research_view_composer=composer,
            research_view_snapshots=snapshots,
            research_view_evidence_access=_UnavailableEvidence(),
            research_view_owner_references=_EmptyOwnerReferences(),  # type: ignore[arg-type]
        )
        headers = {"X-Workspace-Id": view.workspace_id}
        canonical_path = (
            f"/v1/projects/{view.project_id}/accounts/{view.subject.entity_id}/research-view"
        )
        legacy_path = f"/v1/projects/{view.project_id}/accounts/{view.subject.entity_id}/dossier"
        async with _client(app) as client:
            canonical = await client.get(canonical_path, headers=headers)
            legacy = await client.get(legacy_path, headers=headers)
            assert canonical.status_code == legacy.status_code == 200
            assert canonical.json() == legacy.json()
            assert canonical.headers["etag"] == legacy.headers["etag"]
            assert legacy.headers["deprecation"] == "true"
            assert legacy.headers["x-clue-canonical-resource"] == "research-view"

            paged = await client.get(
                canonical_path,
                headers=headers,
                params={
                    "section_kind": ResearchSectionKind.SUMMARY.value,
                    "limit": 1,
                },
            )
            assert paged.status_code == 200
            assert paged.json()["view_ref"]["source_state_sha256"] == view.source_state_sha256
            assert len(paged.json()["section"]["items"]) <= 1
            assert paged.headers["etag"] == canonical.headers["etag"]

            denied = await client.get(
                canonical_path,
                headers={"X-Workspace-Id": "wrong-workspace"},
            )
            assert denied.status_code == 404

            compose_body = {
                "project_id": view.project_id,
                "project_run_id": str(view.project_run_id),
                "subject_entity_id": str(view.subject.entity_id),
                "product_id": view.product_id,
            }
            mutation_headers = {**headers, "Idempotency-Key": "compose-1"}
            first = await client.post(
                "/v1/research-view-snapshots",
                json=compose_body,
                headers=mutation_headers,
            )
            replay = await client.post(
                "/v1/research-view-snapshots",
                json=compose_body,
                headers=mutation_headers,
            )
            alias = await client.post(
                "/v1/dossier",
                json=compose_body,
                headers=mutation_headers,
            )
            assert first.status_code == replay.status_code == alias.status_code == 200
            assert first.json()["replayed"] is False
            assert replay.json()["replayed"] is True
            assert alias.json()["replayed"] is True
            assert first.json()["result"] == replay.json()["result"] == alias.json()["result"]
            assert alias.headers["deprecation"] == "true"
            snapshot_id = first.json()["result"]["snapshot_id"]

            saved = await client.get(
                f"/v1/research-view-snapshots/{snapshot_id}",
                headers=headers,
            )
            assert saved.status_code == 200
            assert saved.json()["view"]["snapshot_id"] == snapshot_id
            assert saved.headers["etag"] == canonical.headers["etag"]

            status = await client.get(
                f"/v1/projects/{view.project_id}/research-view-status",
                headers=headers,
            )
            assert status.status_code == 200
            status_item = status.json()["status"]["items"][0]
            assert status_item["latest_snapshot_id"] == snapshot_id
            assert status_item["source_state_sha256"] == view.source_state_sha256

            recheck_headers = {**headers, "Idempotency-Key": "recheck-1"}
            rechecked = await client.post(
                f"/v1/research-view-snapshots/{snapshot_id}/recheck",
                headers=recheck_headers,
                json={
                    "project_id": view.project_id,
                    "subject_entity_id": str(view.subject.entity_id),
                },
            )
            rechecked_replay = await client.post(
                f"/v1/research-view-snapshots/{snapshot_id}/recheck",
                headers=recheck_headers,
                json={
                    "project_id": view.project_id,
                    "subject_entity_id": str(view.subject.entity_id),
                },
            )
            assert rechecked.status_code == rechecked_replay.status_code == 200
            assert rechecked.json()["result"] == rechecked_replay.json()["result"]
            assert rechecked_replay.json()["replayed"] is True

            statement = next(
                item
                for section in view.sections
                for item in section.items
                if isinstance(item, ResearchStatement)
            )
            action = statement.evidence_actions[0]
            evidence = await client.post(
                f"/v1/research-statements/{statement.statement_id}/evidence-action",
                headers=headers,
                json={
                    "project_id": view.project_id,
                    "subject_entity_id": str(view.subject.entity_id),
                    "claim_id": str(statement.claim_id),
                    "action_id": str(action.action_id),
                    "desired_action": action.kind.value,
                },
            )
            assert evidence.status_code == 200
            assert evidence.json()["result"]["action_kind"] == "unavailable"
            assert evidence.json()["result"]["access_ref"] is None

        get_result = await invoker.invoke(
            "get_research_view",
            {
                "project_id": request.project_id,
                "project_run_id": str(request.project_run_id),
                "subject_entity_id": str(request.subject_entity_id),
                "product_id": request.product_id,
            },
            ToolContext(
                workspace_id=request.workspace_id,
                actor="agent",
                conn_factory=cf,
                operation_id=new_operation_id(),
            ),
            version="1",
        )
        serialized_ref = json.dumps(get_result.references, sort_keys=True)
        assert get_result.references["fetch_ref"].startswith("research-view:")
        assert "value_json" not in serialized_ref
        assert "evidence_span" not in serialized_ref

        events = await list_run_events(
            conn,
            workspace_id=view.workspace_id,
            run_id=ProjectRunId(view.project_run_id),
        )
        topics = [event.topic for event in events]
        assert topics.count("research_view.updated") == 1
        assert topics.count("dossier.updated") == 1
        assert topics.count("research_view.recheck_completed") == 1
        canonical_event = next(event for event in events if event.topic == "research_view.updated")
        alias_event = next(event for event in events if event.topic == "dossier.updated")
        assert alias_event.payload["source_event_id"] == canonical_event.payload["source_event_id"]
        event_json = json.dumps([event.model_dump(mode="json") for event in events])
        for forbidden in (
            "value_json",
            "evidence_span",
            "source_url",
            "rendered_markdown",
            "document_body",
        ):
            assert forbidden not in event_json
        async with _client(app) as client:
            token_response = await client.post(
                f"/project_runs/{view.project_run_id}/stream_token",
                headers=headers,
            )
            assert token_response.status_code == 200
            stream = await client.get(
                f"/project_runs/{view.project_run_id}/events",
                headers={**headers, "Last-Event-ID": str(canonical_event.seq)},
                params={"stream_token": token_response.json()["stream_token"]},
            )
            assert stream.status_code == 200
            assert "event: dossier.updated" in stream.text
            assert "event: research_view.recheck_completed" in stream.text
            assert f"id: {canonical_event.seq}\n" not in stream.text
            assert "value_json" not in stream.text
            assert "evidence_span" not in stream.text

        block_projection = project_nine_blocks(view)
        block_json = block_projection.model_dump_json()
        assert view.source_state_sha256 in block_json
        assert "value_json" not in block_json
        assert "evidence_span" not in block_json
        await connection_context.__aexit__(None, None, None)

    from tests.db.conftest import run_async

    run_async(scenario())


def test_contact_live_and_legacy_routes_share_scope_payload_and_hash() -> None:
    async def scenario() -> None:
        view = await _compose_contact_fixture()
        assert view.subject.parent_account_id is not None
        composer = _Composer(view)
        async with rollback_conn() as conn:
            workspace = await create_workspace(
                conn,
                workspace_id=view.workspace_id,
                name="C7 contact workspace",
            )
            brand = await create_brand(
                conn,
                workspace_id=workspace.workspace_id,
                brand_id="brand-c7-contact",
                name="C7 contact brand",
            )
            await create_project(
                conn,
                workspace_id=workspace.workspace_id,
                brand_id=brand.brand_id,
                product_id=None,
                project_id=view.project_id,
                name="C7 contact project",
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
                    INSERT INTO account_entity (
                        id, canonical_name, status, workspace_id
                    ) VALUES (
                        CAST(:id AS uuid), 'C7 contact parent', 'active', :workspace_id
                    )
                    """
                ),
                {
                    "id": view.subject.parent_account_id,
                    "workspace_id": view.workspace_id,
                },
            )
            await conn.execute(
                text(
                    """
                    INSERT INTO contact_entity (
                        id, account_entity_id, full_name, status, workspace_id
                    ) VALUES (
                        CAST(:id AS uuid), CAST(:account_id AS uuid),
                        'C7 governed contact', 'active', :workspace_id
                    )
                    """
                ),
                {
                    "id": view.subject.entity_id,
                    "account_id": view.subject.parent_account_id,
                    "workspace_id": view.workspace_id,
                },
            )
            await insert_account_run(
                conn,
                account_run_id=new_run_id(),
                project_run_id=ProjectRunId(view.project_run_id),
                entity_id=view.subject.parent_account_id,
                tier="top",
                status=AccountRunStatus.DONE,
            )
            cf = conn_session_factory(conn)
            snapshots = ResearchViewSnapshotService(
                composer,
                _Reachability(view),
                conn_factory=cf,
            )
            registry = build_toolbelt(
                storage=None,
                settings=_c7_settings(),
                gateway=None,
                conn_factory=cf,
                research_view_composer=composer,
                research_view_snapshots=snapshots,
                research_view_recheck=ResearchViewRecheckService(
                    snapshots=snapshots,
                    conn_factory=cf,
                ),
            )
            app = create_projections_app(
                surface=build_surface(conn),
                tool_invoker=build_tool_invoker(
                    registry=registry,
                    idempotency_store=DbIdempotencyStore(conn_factory=cf),
                    storage=_MemoryStorage(),
                    settings=_c7_settings(),
                    conn_factory=cf,
                ),
                settings=_c7_settings(),
                conn_factory=cf,
                manage_db_lifespan=False,
                sse_live_tail=False,
                research_view_composer=composer,
                research_view_snapshots=snapshots,
                research_view_evidence_access=_UnavailableEvidence(),
                research_view_owner_references=_EmptyOwnerReferences(),  # type: ignore[arg-type]
            )
            headers = {"X-Workspace-Id": view.workspace_id}
            canonical_path = (
                f"/v1/projects/{view.project_id}/contacts/{view.subject.entity_id}/research-view"
            )
            legacy_path = (
                f"/v1/projects/{view.project_id}/contacts/{view.subject.entity_id}/dossier"
            )
            async with _client(app) as client:
                canonical = await client.get(canonical_path, headers=headers)
                legacy = await client.get(legacy_path, headers=headers)
                assert canonical.status_code == legacy.status_code == 200
                assert canonical.json() == legacy.json()
                assert canonical.headers["etag"] == legacy.headers["etag"]
                assert canonical.json()["view"]["view_kind"] == "contact"
                assert legacy.headers["deprecation"] == "true"

                account_shape = await client.get(
                    (
                        f"/v1/projects/{view.project_id}/accounts/"
                        f"{view.subject.entity_id}/research-view"
                    ),
                    headers=headers,
                )
                assert account_shape.status_code == 404

                foreign = await client.get(
                    canonical_path,
                    headers={"X-Workspace-Id": "foreign-workspace"},
                )
                assert foreign.status_code == 404

    from tests.db.conftest import run_async

    run_async(scenario())
