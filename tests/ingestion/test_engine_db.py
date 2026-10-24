from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import text

from clue_core import (
    AccountStatus,
    ClaimDraft,
    Entity,
    EntityType,
    FieldDef,
    IdentityBinding,
    NormalizedText,
    RawArtifact,
    ReuseScope,
    UseClass,
    revalidate_with,
)
from clue_core.ingestion import IngestionStatus
from clue_projections.ingestion import ingestion_status
from clue_research.adapters.documents import (
    ExtractedDocument,
    TextDocumentAdapter,
)
from clue_research.claimstore import WorkspaceScope, claims_by_ids
from clue_research.identity import insert_account_entity, insert_contact_entity
from clue_research.ingestion import (
    DeclaredMaterialContext,
    DocumentAdapterRegistry,
    IngestionEngine,
    IngestionTarget,
    MaterialContext,
    default_document_adapters,
)
from clue_research.ingestion.adapters import paid_ocr_manifest
from clue_research.ingestion.models import IngestionFailureCode
from clue_storage import FsStorage, SnapshotSink, flush_snapshots, get_artifact
from tests._run_lineage import assert_written_claims_are_attributable
from tests._workspace import seed_project, seed_workspace
from tests.db.conftest import run_async
from tests.profiling.conftest import (
    conn_session_factory,
    rollback_conn,
)
from tests.profiling.conftest import (
    require_profiling_db as require_profiling_db,
)

pytestmark = pytest.mark.usefixtures("require_profiling_db")


class _Extractor:
    def __init__(self, *, fail_once: bool = False) -> None:
        self._fail_once = fail_once
        self.calls = 0

    def extract(
        self, normalized: NormalizedText, entity: Entity, field: FieldDef
    ) -> list[ClaimDraft]:
        self.calls += 1
        if self._fail_once:
            self._fail_once = False
            raise RuntimeError("transient extractor failure with private body")
        needle = "acme.example"
        assert needle in normalized.text
        return [
            ClaimDraft(
                field_key=field.field_key,
                value=needle,
                evidence_span=needle,
                confidence=0.95,
            )
        ]


class _CountingText:
    adapter_key = "counting_text"

    def __init__(self, gate_state: list[str] | None = None) -> None:
        self.calls = 0
        self._gate_state = gate_state

    def extract(self, artifact: RawArtifact) -> ExtractedDocument:
        if self._gate_state is not None:
            assert self._gate_state == ["gate"]
        self.calls += 1
        return TextDocumentAdapter().extract(artifact)


class _ProposalSink:
    def __init__(self) -> None:
        self.calls = 0

    async def preserve_unmapped(self, **kwargs) -> str:
        self.calls += 1
        return "field-proposal-1"


class _MemoryRoute:
    async def write_from_segments(self, **kwargs) -> tuple[str, ...]:
        return ("memory-1",)


async def _artifact(conn, storage: FsStorage, workspace_id: str, body: bytes, media: str) -> str:
    sink = SnapshotSink(workspace_id=workspace_id)
    key = sink.capture(RawArtifact(ref="upload", media_type=media, content=body))
    await flush_snapshots(conn, storage, sink)
    return key


async def _text_artifact(conn, storage: FsStorage, workspace_id: str) -> str:
    return await _artifact(conn, storage, workspace_id, b"Site: acme.example", "text/plain")


async def _scope(conn, workspace_id: str):
    await seed_workspace(conn, workspace_id)
    project = await seed_project(conn, workspace_id)
    account = await insert_account_entity(
        conn,
        canonical_name="Acme",
        primary_domain="acme.example",
        status=AccountStatus.ACTIVE,
        workspace_id=workspace_id,
    )
    return project, account


def _context(project, account, kind: MaterialContext) -> DeclaredMaterialContext:
    return DeclaredMaterialContext(
        brand_id=project.brand_id,
        project_id=project.project_id,
        targets=(
            IngestionTarget(
                entity_id=account,
                entity_type=EntityType.ACCOUNT,
                field_key="core.primary_domain",
                material_context=kind,
            ),
        ),
        document_context=kind,
    )


def test_identical_upload_dedupes_job_segments_and_claims(tmp_path: Path) -> None:
    async def scenario() -> None:
        async with rollback_conn(seed_pack=True) as conn:
            storage = FsStorage(str(tmp_path))
            project, account = await _scope(conn, "ws-ingestion-dedupe")
            key = await _text_artifact(conn, storage, project.workspace_id)
            extractor = _Extractor()
            engine = IngestionEngine(
                storage=storage,
                extractor=extractor,
                conn_factory=conn_session_factory(conn),
            )
            context = _context(project, account, MaterialContext.CLIENT_ABOUT_SELF)

            first = await engine.submit(
                workspace_id=project.workspace_id,
                artifact_key=key,
                context=context,
                actor="human",
            )
            second = await engine.submit(
                workspace_id=project.workspace_id,
                artifact_key=key,
                context=context,
                actor="human",
            )

            assert first == second
            assert first.status is IngestionStatus.COMPLETED
            assert extractor.calls == 1
            job = await engine.status(
                workspace_id=project.workspace_id, job_id=first.ingestion_job_id
            )
            assert job is not None and job.segment_count == 1
            assert len(job.result_refs.claims) == 1
            claims = await claims_by_ids(
                conn,
                job.result_refs.claims,
                scope=WorkspaceScope.private_for_workspace(project.workspace_id),
            )
            claim = next(iter(claims.values()))
            assert claim.source_tier == 1
            assert claim.reuse_scope is ReuseScope.TENANT_PRIVATE
            assert claim.artifact_key is not None
            segment = next(iter(await _segments(conn, job)))
            assert claim.source_url == f"ingestion://{job.id}/{segment.id}"
            # FI-2 P2 (spec §3): an ingested claim back-joins to the run that wrote it. Ingestion
            # is workspace-level human-supplied material, so the run carries no ``project_id``.
            await assert_written_claims_are_attributable(
                conn,
                claim.run_id,
                kind="manual",
                workspace_id=project.workspace_id,
            )

    run_async(scenario())


async def _segments(conn, job):
    from clue_research.ingestion import list_segments

    return await list_segments(conn, job.id, workspace_id=job.workspace_id)


def test_target_assertion_is_capped_at_tier_three_and_cross_workspace_is_hidden(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        async with rollback_conn(seed_pack=True) as conn:
            storage = FsStorage(str(tmp_path))
            project, account = await _scope(conn, "ws-ingestion-target")
            key = await _text_artifact(conn, storage, project.workspace_id)
            engine = IngestionEngine(
                storage=storage,
                extractor=_Extractor(),
                conn_factory=conn_session_factory(conn),
            )
            ref = await engine.submit(
                workspace_id=project.workspace_id,
                artifact_key=key,
                context=_context(project, account, MaterialContext.CLIENT_ABOUT_TARGET),
                actor="agent",
            )
            job = await engine.status(
                workspace_id=project.workspace_id, job_id=ref.ingestion_job_id
            )
            assert job is not None
            claims = await claims_by_ids(
                conn,
                job.result_refs.claims,
                scope=WorkspaceScope.private_for_workspace(project.workspace_id),
            )
            assert {claim.source_tier for claim in claims.values()} == {3}
            assert (
                await engine.status(workspace_id="ws-foreign", job_id=ref.ingestion_job_id) is None
            )

    run_async(scenario())


def test_retry_reuses_committed_segments_without_reextracting_document(tmp_path: Path) -> None:
    async def scenario() -> None:
        async with rollback_conn(seed_pack=True) as conn:
            storage = FsStorage(str(tmp_path))
            project, account = await _scope(conn, "ws-ingestion-retry")
            key = await _text_artifact(conn, storage, project.workspace_id)
            adapter = _CountingText()
            registry = DocumentAdapterRegistry()
            registry.register(("text/plain",), adapter)
            extractor = _Extractor(fail_once=True)
            engine = IngestionEngine(
                storage=storage,
                extractor=extractor,
                adapters=registry,
                conn_factory=conn_session_factory(conn),
            )
            failed = await engine.submit(
                workspace_id=project.workspace_id,
                artifact_key=key,
                context=_context(project, account, MaterialContext.CLIENT_ABOUT_SELF),
                actor="human",
            )
            assert failed.status is IngestionStatus.FAILED
            failed_job = await engine.status(
                workspace_id=project.workspace_id, job_id=failed.ingestion_job_id
            )
            assert failed_job is not None
            assert failed_job.failure_code is IngestionFailureCode.EXTRACTION_FAILED
            assert "private body" not in (failed_job.failure_detail or "")
            assert failed_job.segment_count == 1
            failed_view = await ingestion_status(
                conn_factory=conn_session_factory(conn),
                workspace_id=project.workspace_id,
                ingestion_job_id=failed.ingestion_job_id,
            )
            assert failed_view is not None and failed_view.progress == 0.5

            completed = await engine.retry(
                workspace_id=project.workspace_id, job_id=failed.ingestion_job_id
            )
            assert completed is not None and completed.status is IngestionStatus.COMPLETED
            assert adapter.calls == 1
            assert extractor.calls == 2

    run_async(scenario())


def test_paid_adapter_observes_gate_before_call(tmp_path: Path) -> None:
    async def scenario() -> None:
        async with rollback_conn(seed_pack=True) as conn:
            storage = FsStorage(str(tmp_path))
            project, account = await _scope(conn, "ws-ingestion-gate")
            key = await _text_artifact(conn, storage, project.workspace_id)
            order: list[str] = []

            async def gate(manifest) -> bool:
                assert manifest.source_key == "hosted_ocr"
                order.append("gate")
                return True

            adapter = _CountingText(order)
            registry = DocumentAdapterRegistry()
            registry.register(
                ("text/plain",),
                adapter,
                paid=True,
                gate_manifest=paid_ocr_manifest(source_key="hosted_ocr", cost_cents=Decimal("1")),
            )
            engine = IngestionEngine(
                storage=storage,
                extractor=_Extractor(),
                adapters=registry,
                conn_factory=conn_session_factory(conn),
                source_gate=gate,
            )
            result = await engine.submit(
                workspace_id=project.workspace_id,
                artifact_key=key,
                context=_context(project, account, MaterialContext.CLIENT_ABOUT_SELF),
                actor="agent",
            )
            assert result.status is IngestionStatus.COMPLETED
            assert order == ["gate"]
            assert adapter.calls == 1

    run_async(scenario())


def test_corrupt_input_records_durable_failure(tmp_path: Path) -> None:
    async def scenario() -> None:
        async with rollback_conn(seed_pack=True) as conn:
            storage = FsStorage(str(tmp_path))
            project, account = await _scope(conn, "ws-ingestion-corrupt")
            key = await _artifact(
                conn, storage, project.workspace_id, b"not a pdf", "application/pdf"
            )
            engine = IngestionEngine(
                storage=storage,
                extractor=_Extractor(),
                adapters=default_document_adapters(engine_policy()),
                conn_factory=conn_session_factory(conn),
            )
            result = await engine.submit(
                workspace_id=project.workspace_id,
                artifact_key=key,
                context=_context(project, account, MaterialContext.CLIENT_ABOUT_SELF),
                actor="human",
            )
            assert result.status is IngestionStatus.FAILED
            job = await engine.status(
                workspace_id=project.workspace_id, job_id=result.ingestion_job_id
            )
            assert job is not None
            assert job.failure_code is IngestionFailureCode.ADAPTER_FAILED
            assert "not a pdf" not in (job.failure_detail or "")

    run_async(scenario())


def test_unregistered_allowed_media_records_durable_failure(tmp_path: Path) -> None:
    async def scenario() -> None:
        async with rollback_conn(seed_pack=True) as conn:
            storage = FsStorage(str(tmp_path))
            project, account = await _scope(conn, "ws-ingestion-unsupported")
            key = await _artifact(
                conn, storage, project.workspace_id, b"captured bytes", "application/pdf"
            )
            registry = DocumentAdapterRegistry()
            registry.register(("text/plain",), TextDocumentAdapter())
            engine = IngestionEngine(
                storage=storage,
                extractor=_Extractor(),
                adapters=registry,
                conn_factory=conn_session_factory(conn),
            )
            result = await engine.submit(
                workspace_id=project.workspace_id,
                artifact_key=key,
                context=_context(project, account, MaterialContext.CLIENT_ABOUT_SELF),
                actor="human",
            )
            assert result.status is IngestionStatus.FAILED
            job = await engine.status(
                workspace_id=project.workspace_id, job_id=result.ingestion_job_id
            )
            assert job is not None
            assert job.failure_code is IngestionFailureCode.UNSUPPORTED_MEDIA_TYPE

    run_async(scenario())


def test_contact_facet_is_born_governed_before_insert(tmp_path: Path) -> None:
    async def scenario() -> None:
        async with rollback_conn(seed_pack=True) as conn:
            storage = FsStorage(str(tmp_path))
            project, account = await _scope(conn, "ws-ingestion-contact")
            contact = await insert_contact_entity(
                conn, account_entity_id=account, full_name="Ada Example"
            )
            key = await _text_artifact(conn, storage, project.workspace_id)
            observed: list[tuple[IdentityBinding | None, UseClass | None]] = []

            def tagger(claim):
                observed.append((claim.identity_binding, claim.use_class))
                return revalidate_with(claim, identity_binding=IdentityBinding.STRONG)

            engine = IngestionEngine(
                storage=storage,
                extractor=_Extractor(),
                conn_factory=conn_session_factory(conn),
                claim_tagger=tagger,
            )
            missing_use = DeclaredMaterialContext(
                brand_id=project.brand_id,
                project_id=project.project_id,
                targets=(
                    IngestionTarget(
                        entity_id=contact,
                        entity_type=EntityType.CONTACT,
                        field_key="contact.facet.recent_post",
                        material_context=MaterialContext.CLIENT_ABOUT_TARGET,
                    ),
                ),
                document_context=MaterialContext.CLIENT_ABOUT_TARGET,
            )
            failed = await engine.submit(
                workspace_id=project.workspace_id,
                artifact_key=key,
                context=missing_use,
                actor="human",
            )
            assert failed.status is IngestionStatus.FAILED
            failed_job = await engine.status(
                workspace_id=project.workspace_id, job_id=failed.ingestion_job_id
            )
            assert failed_job is not None
            assert failed_job.failure_code is IngestionFailureCode.INVALID_CONTEXT
            assert observed == []

            governed = missing_use.model_copy(
                update={
                    "targets": (
                        missing_use.targets[0].model_copy(
                            update={"use_class": UseClass.PROFESSIONAL_PUBLIC}
                        ),
                    )
                }
            )
            completed = await engine.submit(
                workspace_id=project.workspace_id,
                artifact_key=key,
                context=governed,
                actor="human",
            )
            assert completed.status is IngestionStatus.COMPLETED
            completed_job = await engine.status(
                workspace_id=project.workspace_id, job_id=completed.ingestion_job_id
            )
            assert completed_job is not None
            claims = await claims_by_ids(
                conn,
                completed_job.result_refs.claims,
                scope=WorkspaceScope.private_for_workspace(project.workspace_id),
            )
            claim = next(iter(claims.values()))
            assert observed == [(IdentityBinding.WEAK, UseClass.PROFESSIONAL_PUBLIC)]
            assert claim.identity_binding is IdentityBinding.STRONG
            assert claim.use_class is UseClass.PROFESSIONAL_PUBLIC

    run_async(scenario())


def engine_policy():
    from clue_config.ingestion import DEFAULT_INGESTION_POLICY

    return DEFAULT_INGESTION_POLICY


def test_preferences_and_unmapped_fields_route_without_claims(tmp_path: Path) -> None:
    async def scenario() -> None:
        async with rollback_conn(seed_pack=True) as conn:
            storage = FsStorage(str(tmp_path))
            project, account = await _scope(conn, "ws-ingestion-routing")
            key = await _text_artifact(conn, storage, project.workspace_id)
            proposal = _ProposalSink()
            engine = IngestionEngine(
                storage=storage,
                extractor=_Extractor(),
                conn_factory=conn_session_factory(conn),
                proposal_sink=proposal,
                memory_route=_MemoryRoute(),
            )
            preference = await engine.submit(
                workspace_id=project.workspace_id,
                artifact_key=key,
                context=DeclaredMaterialContext(
                    brand_id=project.brand_id,
                    project_id=project.project_id,
                    document_context=MaterialContext.CLIENT_PREFERENCE,
                ),
                actor="human",
            )
            preference_job = await engine.status(
                workspace_id=project.workspace_id, job_id=preference.ingestion_job_id
            )
            assert preference_job is not None
            assert preference_job.result_refs.claims == ()
            assert preference_job.result_refs.memory == ("memory-1",)

            unknown = await engine.submit(
                workspace_id=project.workspace_id,
                artifact_key=key,
                context=DeclaredMaterialContext(
                    brand_id=project.brand_id,
                    project_id=project.project_id,
                    targets=(
                        IngestionTarget(
                            entity_id=account,
                            entity_type=EntityType.ACCOUNT,
                            field_key="account.unregistered_client_concept",
                            material_context=MaterialContext.CLIENT_ABOUT_SELF,
                        ),
                    ),
                    document_context=MaterialContext.CLIENT_ABOUT_SELF,
                ),
                actor="agent",
            )
            unknown_job = await engine.status(
                workspace_id=project.workspace_id, job_id=unknown.ingestion_job_id
            )
            assert unknown_job is not None
            assert unknown_job.result_refs.claims == ()
            assert unknown_job.result_refs.proposals == ("field-proposal-1",)
            assert proposal.calls == 1

    run_async(scenario())


def test_erasure_removes_projection_segment_and_blob_reach(tmp_path: Path) -> None:
    async def scenario() -> None:
        async with rollback_conn(seed_pack=True) as conn:
            storage = FsStorage(str(tmp_path))
            project, _account = await _scope(conn, "ws-ingestion-erasure")
            key = await _text_artifact(conn, storage, project.workspace_id)
            engine = IngestionEngine(
                storage=storage,
                extractor=_Extractor(),
                conn_factory=conn_session_factory(conn),
                memory_route=_MemoryRoute(),
            )
            ref = await engine.submit(
                workspace_id=project.workspace_id,
                artifact_key=key,
                context=DeclaredMaterialContext(
                    brand_id=project.brand_id,
                    project_id=project.project_id,
                    document_context=MaterialContext.CLIENT_PREFERENCE,
                ),
                actor="human",
            )
            job = await engine.status(
                workspace_id=project.workspace_id, job_id=ref.ingestion_job_id
            )
            assert job is not None
            segments = await _segments(conn, job)
            canonical_key = segments[0].canonical_artifact_key
            cf = conn_session_factory(conn)
            assert (
                await ingestion_status(
                    conn_factory=cf,
                    workspace_id=project.workspace_id,
                    ingestion_job_id=job.id,
                )
                is not None
            )

            # Review of F3 Phase 2: an erasure purges the keys it just marked, and does no
            # fleet-wide work. ``purge_erased_artifacts`` opens with an unfiltered
            # ``UPDATE artifact … WHERE expires_at <= now()`` plus a sequential scan — the
            # keyless maintenance sweep's job, converged on its own schedule, not one
            # ingestion job's to do on another owner's rows.
            expiring = f"{project.workspace_id}/{'e' * 64}"
            await storage.put(expiring, b"another owner's bytes", media_type="text/plain")
            await conn.execute(
                text(
                    "INSERT INTO artifact (storage_key, workspace_id, content_sha256, "
                    "media_type, size_bytes, expires_at) VALUES (:key, :ws, :sha, "
                    "'text/plain', 21, now() - interval '1 second')"
                ),
                {"key": expiring, "ws": project.workspace_id, "sha": "e" * 64},
            )

            assert await engine.erase(workspace_id=project.workspace_id, job_id=job.id)

            untouched = await get_artifact(conn, expiring)
            assert untouched is not None
            assert (untouched.erased_at, untouched.purged_at, untouched.privacy_erased) == (
                None,
                None,
                False,
            )
            assert await storage.exists(expiring)

            assert (
                await ingestion_status(
                    conn_factory=cf,
                    workspace_id=project.workspace_id,
                    ingestion_job_id=job.id,
                )
                is None
            )
            assert await _segments(conn, job) == ()
            assert not await storage.exists(key)
            assert not await storage.exists(canonical_key)

            replacement_key = await _text_artifact(conn, storage, project.workspace_id)
            replacement = await engine.submit(
                workspace_id=project.workspace_id,
                artifact_key=replacement_key,
                context=job.declared_context,
                actor="human",
            )
            assert replacement.status is IngestionStatus.COMPLETED
            assert replacement.ingestion_job_id != job.id
            assert await storage.exists(replacement_key)
            assert not await engine.erase(workspace_id=project.workspace_id, job_id=job.id)
            assert await storage.exists(replacement_key)

    run_async(scenario())


def test_shared_artifact_survives_until_every_ingestion_is_erased(tmp_path: Path) -> None:
    async def scenario() -> None:
        async with rollback_conn(seed_pack=True) as conn:
            storage = FsStorage(str(tmp_path))
            project, _account = await _scope(conn, "ws-ingestion-shared-erasure")
            key = await _text_artifact(conn, storage, project.workspace_id)
            engine = IngestionEngine(
                storage=storage,
                extractor=_Extractor(),
                conn_factory=conn_session_factory(conn),
                memory_route=_MemoryRoute(),
            )
            preference = await engine.submit(
                workspace_id=project.workspace_id,
                artifact_key=key,
                context=DeclaredMaterialContext(
                    brand_id=project.brand_id,
                    project_id=project.project_id,
                    document_context=MaterialContext.CLIENT_PREFERENCE,
                ),
                actor="human",
            )
            instruction = await engine.submit(
                workspace_id=project.workspace_id,
                artifact_key=key,
                context=DeclaredMaterialContext(
                    brand_id=project.brand_id,
                    project_id=project.project_id,
                    document_context=MaterialContext.PROJECT_INSTRUCTION,
                ),
                actor="human",
            )
            assert preference.ingestion_job_id != instruction.ingestion_job_id
            assert preference.artifact_key == instruction.artifact_key == key

            assert await engine.erase(
                workspace_id=project.workspace_id, job_id=preference.ingestion_job_id
            )
            assert await storage.exists(key)

            assert await engine.erase(
                workspace_id=project.workspace_id, job_id=instruction.ingestion_job_id
            )
            assert not await storage.exists(key)

    run_async(scenario())
