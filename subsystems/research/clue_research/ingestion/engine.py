"""C3 durable upload orchestration: artifact -> segments -> governed claims."""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from dataclasses import dataclass
from decimal import Decimal

from pydantic import JsonValue
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_config.ingestion import DEFAULT_INGESTION_POLICY, IngestionPolicy
from clue_core import (
    Claim,
    ClaimDraft,
    ClaimTagger,
    ContactEntity,
    Entity,
    EntityType,
    ExtractionMethod,
    FieldClass,
    FieldDef,
    IdentityBinding,
    NormalizedText,
    RawArtifact,
    ResearchMode,
    ReuseScope,
    RunId,
    SourceGate,
    classify_field_key,
    new_run_id,
    revalidate_with,
    to_value_json,
)
from clue_core.ingestion import (
    IngestionJobId,
    IngestionJobRef,
    IngestionSegmentId,
    IngestionStatus,
)
from clue_db import ConnFactory, transaction
from clue_research.adapters.documents import DocumentSegment
from clue_research.adapters.seams import AdaptError, ClaimExtractor
from clue_research.claimstore import get_field, insert_claim, record_run_lineage
from clue_research.identity import get_entity
from clue_research.ingestion.adapters import (
    DocumentAdapterRegistry,
    RegisteredDocumentAdapter,
    default_document_adapters,
)
from clue_research.ingestion.errors import IngestionError
from clue_research.ingestion.models import (
    DeclaredMaterialContext,
    IngestionFailureCode,
    IngestionJob,
    IngestionResultRefs,
    IngestionSegment,
    IngestionTarget,
    MaterialContext,
)
from clue_research.ingestion.seams import (
    ClaimConstructionRoute,
    ClaimErasureRoute,
    ContactClaimRoute,
    MemoryRoute,
    ProjectStateRoute,
    ProposalSink,
)
from clue_research.ingestion.store import (
    artifact_has_live_ingestion_ref,
    complete_job,
    create_or_get_job,
    fail_job,
    get_job,
    increment_retry,
    list_segments,
    mark_erased,
    mark_extracting,
    replace_segments,
)
from clue_storage import (
    ArtifactRecord,
    StorageBackend,
    artifact_key,
    content_address,
    erase_if_unreferenced,
    get_artifact,
    purge_erased_artifacts,
    record_artifact,
)


@dataclass(frozen=True, slots=True)
class _CanonicalSegment:
    ordinal: int
    text: str
    locator: dict[str, JsonValue]


class IngestionEngine:
    """Resumable C3 engine.

    Normalization and claim insertion are separate committed stages. A retry after the segment
    checkpoint reads the canonical artifact and does not call the document adapter again.
    """

    def __init__(
        self,
        *,
        storage: StorageBackend,
        extractor: ClaimExtractor,
        policy: IngestionPolicy = DEFAULT_INGESTION_POLICY,
        adapters: DocumentAdapterRegistry | None = None,
        conn_factory: ConnFactory = transaction,
        source_gate: SourceGate | None = None,
        claim_tagger: ClaimTagger | None = None,
        proposal_sink: ProposalSink | None = None,
        memory_route: MemoryRoute | None = None,
        project_state_route: ProjectStateRoute | None = None,
        claim_construction_route: ClaimConstructionRoute | None = None,
        claim_erasure_route: ClaimErasureRoute | None = None,
        contact_claim_route: ContactClaimRoute | None = None,
        run_id_factory: Callable[[], RunId] = new_run_id,
    ) -> None:
        self._storage = storage
        self._extractor = extractor
        self._policy = policy
        self._adapters = adapters or default_document_adapters(policy)
        self._conn_factory = conn_factory
        self._source_gate = source_gate
        self._claim_tagger = claim_tagger
        self._proposal_sink = proposal_sink
        self._memory_route = memory_route
        self._project_state_route = project_state_route
        self._claim_construction_route = claim_construction_route
        self._claim_erasure_route = claim_erasure_route
        self._contact_claim_route = contact_claim_route
        self._run_id_factory = run_id_factory

    async def submit(
        self,
        *,
        workspace_id: str,
        artifact_key: str,
        context: DeclaredMaterialContext,
        actor: str,
    ) -> IngestionJobRef:
        async with self._conn_factory() as conn:
            artifact = await get_artifact(conn, artifact_key)
            if artifact is None:
                raise IngestionError(
                    IngestionFailureCode.ARTIFACT_NOT_FOUND, "captured artifact does not exist"
                )
            self._validate_artifact(artifact, workspace_id)
            registered = self._adapters.get(artifact.media_type)
            await self._validate_context(conn, workspace_id, context)
            job = await create_or_get_job(
                conn,
                workspace_id=workspace_id,
                artifact=artifact,
                context=context,
                adapter_key=(
                    registered.adapter.adapter_key if registered is not None else "unsupported"
                ),
                actor=actor,
            )
            # The job insert's artifact FK key-lock serializes against DSAR's artifact lock.
            # Re-read afterward so an erasure that won the race causes this transaction to roll
            # back instead of creating a job over erased bytes.
            current_artifact = await get_artifact(conn, artifact_key)
            if current_artifact is None:
                raise IngestionError(
                    IngestionFailureCode.ARTIFACT_NOT_FOUND,
                    "captured artifact does not exist",
                )
            self._validate_artifact(current_artifact, workspace_id)
        if job.status in {
            IngestionStatus.COMPLETED,
            IngestionStatus.ERASED,
            IngestionStatus.FAILED,
        }:
            return _ref(job)
        if registered is None:
            code = (
                IngestionFailureCode.OCR_DISABLED
                if artifact.media_type.startswith("image/") and not self._policy.ocr_enabled
                else IngestionFailureCode.UNSUPPORTED_MEDIA_TYPE
            )
            async with self._conn_factory() as conn:
                await fail_job(
                    conn,
                    job.id,
                    code=code,
                    detail="no document adapter is registered for this media type",
                )
                failed = await get_job(conn, job.id, workspace_id=workspace_id)
            if failed is None:
                raise IngestionError(
                    IngestionFailureCode.INVALID_CONTEXT, "ingestion job disappeared"
                )
            return _ref(failed)
        return _ref(await self._drive(job))

    async def retry(self, *, workspace_id: str, job_id: IngestionJobId) -> IngestionJobRef | None:
        async with self._conn_factory() as conn:
            job = await get_job(conn, job_id, workspace_id=workspace_id)
            if job is None:
                return None
            if job.status is IngestionStatus.COMPLETED:
                return _ref(job)
            if job.status is IngestionStatus.ERASED:
                raise IngestionError(
                    IngestionFailureCode.ARTIFACT_ERASED,
                    "an erased ingestion cannot be retried; submit a new authorized upload",
                )
            if job.status is IngestionStatus.FAILED:
                if job.retry_count >= self._policy.max_retries:
                    raise IngestionError(
                        IngestionFailureCode.RETRY_LIMIT_EXCEEDED,
                        "configured ingestion retry limit reached",
                    )
                resumed = await increment_retry(conn, job_id, workspace_id=workspace_id)
                if resumed is None:
                    return None
                job = resumed
        return _ref(await self._drive(job))

    async def status(self, *, workspace_id: str, job_id: IngestionJobId) -> IngestionJob | None:
        async with self._conn_factory() as conn:
            return await get_job(conn, job_id, workspace_id=workspace_id)

    async def erase(self, *, workspace_id: str, job_id: IngestionJobId) -> bool:
        """Remove C3 serving/projection reach and delegate claim tombstoning to DSAR."""
        async with self._conn_factory() as conn:
            job = await get_job(conn, job_id, workspace_id=workspace_id)
            if job is None:
                return False
            if job.status is IngestionStatus.ERASED:
                return False
        if job.result_refs.claims and self._claim_erasure_route is None:
            raise IngestionError(
                IngestionFailureCode.INVALID_CONTEXT,
                "claim-producing ingestion erasure requires the compliance/DSAR route",
            )
        if self._claim_erasure_route is not None and job.result_refs.claims:
            await self._claim_erasure_route.erase_claims(
                workspace_id=workspace_id, claim_ids=job.result_refs.claims
            )
        async with self._conn_factory() as conn:
            segments = await list_segments(conn, job_id, workspace_id=workspace_id)
            keys = {job.artifact_key, *(segment.canonical_artifact_key for segment in segments)}
            changed = await mark_erased(conn, job_id, workspace_id=workspace_id)
            if not changed:
                return False
            marked_list: list[str] = []
            for key in sorted(keys):
                if not await artifact_has_live_ingestion_ref(
                    conn, key
                ) and await erase_if_unreferenced(conn, key):
                    marked_list.append(key)
            marked = tuple(marked_list)
        if marked:
            async with self._conn_factory() as conn:
                # ``sweep_expired=False``: ``marked`` is what this erasure itself stamped.
                # Tombstoning every expired row fleet-wide is the keyless sweep's work, not
                # one ingestion job's (review I7).
                await purge_erased_artifacts(conn, self._storage, keys=marked, sweep_expired=False)
        return changed

    async def _drive(self, job: IngestionJob) -> IngestionJob:
        try:
            if job.status is IngestionStatus.QUEUED:
                await self._normalize(job)
            async with self._conn_factory() as conn:
                current = await get_job(conn, job.id, workspace_id=job.workspace_id)
            if current is None:
                raise IngestionError(
                    IngestionFailureCode.INVALID_CONTEXT, "ingestion job disappeared"
                )
            if current.status in {IngestionStatus.SNAPSHOTTED, IngestionStatus.EXTRACTING}:
                await self._extract_claims(current)
            async with self._conn_factory() as conn:
                final = await get_job(conn, job.id, workspace_id=job.workspace_id)
            if final is None:
                raise IngestionError(
                    IngestionFailureCode.INVALID_CONTEXT, "ingestion job disappeared"
                )
            return final
        except IngestionError as exc:
            async with self._conn_factory() as conn:
                await fail_job(conn, job.id, code=exc.code, detail=exc.detail)
                failed = await get_job(conn, job.id, workspace_id=job.workspace_id)
            if failed is None:
                raise
            return failed

    async def _normalize(self, job: IngestionJob) -> None:
        registered = self._registered_adapter(job.media_type)
        if registered.paid:
            if self._source_gate is None or registered.gate_manifest is None:
                raise IngestionError(
                    IngestionFailureCode.GATE_BLOCKED,
                    "paid extraction has no injected SourceGate authority",
                )
            allowed = await self._source_gate(registered.gate_manifest)
            if not allowed:
                raise IngestionError(
                    IngestionFailureCode.GATE_BLOCKED, "paid extraction was blocked by policy"
                )
        async with self._conn_factory() as conn:
            current = await get_job(conn, job.id, workspace_id=job.workspace_id, for_update=True)
            if current is None:
                raise IngestionError(
                    IngestionFailureCode.INVALID_CONTEXT, "ingestion job disappeared"
                )
            if current.status is not IngestionStatus.QUEUED:
                return
            try:
                raw = await self._storage.get(current.artifact_key)
                document = registered.adapter.extract(
                    RawArtifact(
                        ref=current.artifact_key,
                        media_type=current.media_type,
                        content=raw,
                    )
                )
            except AdaptError:
                await fail_job(
                    conn,
                    current.id,
                    code=IngestionFailureCode.ADAPTER_FAILED,
                    detail=f"{registered.adapter.adapter_key} normalization failed",
                )
                return
            if len(document.segments) > self._policy.max_segments:
                await fail_job(
                    conn,
                    current.id,
                    code=IngestionFailureCode.SEGMENT_LIMIT_EXCEEDED,
                    detail="normalized document exceeds the configured segment limit",
                )
                return
            canonical, segments = _canonicalize(document.segments)
            sha = content_address(canonical)
            canonical_key = artifact_key(current.workspace_id, sha)
            await record_artifact(
                conn,
                storage_key=canonical_key,
                workspace_id=current.workspace_id,
                content_sha256=sha,
                media_type="text/plain",
                size_bytes=len(canonical),
                source_key="client_upload_extracted",
            )
            if not await self._storage.exists(canonical_key):
                await self._storage.put(canonical_key, canonical, media_type="text/plain")
            await replace_segments(
                conn,
                job_id=current.id,
                segments=tuple(
                    (
                        segment.ordinal,
                        dict(segment.locator),
                        hashlib.sha256(segment.text.encode()).hexdigest(),
                        canonical_key,
                    )
                    for segment in segments
                ),
            )

    async def _extract_claims(self, job: IngestionJob) -> None:
        async with self._conn_factory() as conn:
            current = await get_job(conn, job.id, workspace_id=job.workspace_id, for_update=True)
            if current is None:
                raise IngestionError(
                    IngestionFailureCode.INVALID_CONTEXT, "ingestion job disappeared"
                )
            if current.status is IngestionStatus.COMPLETED:
                return
            if current.status not in {IngestionStatus.SNAPSHOTTED, IngestionStatus.EXTRACTING}:
                raise IngestionError(
                    IngestionFailureCode.INVALID_CONTEXT,
                    "ingestion job is not ready for claim extraction",
                )
            try:
                async with conn.begin_nested():
                    await self._extract_claims_locked(conn, current)
            except IngestionError as exc:
                await fail_job(conn, current.id, code=exc.code, detail=exc.detail)
            except Exception:
                await fail_job(
                    conn,
                    current.id,
                    code=IngestionFailureCode.EXTRACTION_FAILED,
                    detail="claim extraction failed",
                )

    async def _extract_claims_locked(self, conn: AsyncConnection, job: IngestionJob) -> None:
        """Run the claim stage while the caller holds the ingestion-job row lock."""
        await mark_extracting(conn, job.id)
        segments = await list_segments(conn, job.id, workspace_id=job.workspace_id)
        canonical = await _load_canonical(self._storage, segments)
        segment_bodies = _segment_bodies(canonical, segments)
        segment_ids = tuple(segment.id for segment in segments)

        memory_refs: tuple[str, ...] = ()
        project_refs: tuple[str, ...] = ()
        unmapped: list[IngestionSegmentId] = []
        if job.declared_context.document_context is MaterialContext.CLIENT_PREFERENCE:
            if self._memory_route is None:
                unmapped.extend(segment_ids)
            else:
                memory_refs = await self._memory_route.write_from_segments(
                    job_id=job.id,
                    segment_ids=segment_ids,
                    context=job.declared_context,
                )
        elif job.declared_context.document_context is MaterialContext.PROJECT_INSTRUCTION:
            if self._project_state_route is None:
                unmapped.extend(segment_ids)
            else:
                project_refs = await self._project_state_route.write_from_segments(
                    job_id=job.id,
                    segment_ids=segment_ids,
                    context=job.declared_context,
                )
        elif not job.declared_context.targets:
            unmapped.extend(segment_ids)

        pending_claims: list[Claim] = []
        proposal_refs: list[str] = []
        run_id = self._run_id_factory()
        for target in job.declared_context.targets:
            if (
                target.material_context is MaterialContext.CLIENT_ABOUT_PRODUCT
                and job.product_id is not None
                and self._claim_construction_route is None
            ):
                raise IngestionError(
                    IngestionFailureCode.INVALID_CONTEXT,
                    "product claim extraction requires the C4 claim-construction route",
                )
            field = await get_field(conn, target.field_key)
            if field is None:
                if self._proposal_sink is not None:
                    proposal_refs.append(
                        await self._proposal_sink.preserve_unmapped(
                            job=job, segment_ids=segment_ids, target=target
                        )
                    )
                else:
                    unmapped.extend(segment_ids)
                continue
            field_class = classify_field_key(target.field_key)
            if (
                field_class in {FieldClass.CONTACT, FieldClass.CONTACT_FACET}
                and target.entity_type is not EntityType.CONTACT
            ) or (
                field_class in {FieldClass.ACCOUNT, FieldClass.ACCOUNT_RESONANCE}
                and target.entity_type is not EntityType.ACCOUNT
            ):
                raise IngestionError(
                    IngestionFailureCode.INVALID_CONTEXT,
                    "declared target entity type does not match the registered field class",
                )
            entity = await get_entity(conn, target.entity_id, target.entity_type)
            if entity is None or entity.workspace_id != job.workspace_id:
                raise IngestionError(
                    IngestionFailureCode.INVALID_CONTEXT,
                    "declared target entity is absent from this workspace",
                )
            if target.material_context in {
                MaterialContext.CLIENT_PREFERENCE,
                MaterialContext.PROJECT_INSTRUCTION,
                MaterialContext.UNKNOWN,
            }:
                unmapped.extend(segment_ids)
                continue
            try:
                drafts = self._extractor.extract(
                    NormalizedText(text=canonical.decode(), media_type="text/plain"),
                    Entity(entity_id=target.entity_id, entity_type=target.entity_type),
                    field,
                )
            except Exception as exc:
                raise IngestionError(
                    IngestionFailureCode.EXTRACTION_FAILED,
                    "claim extraction failed for a declared target",
                ) from exc
            for draft in drafts:
                if draft.field_key != target.field_key:
                    raise IngestionError(
                        IngestionFailureCode.EXTRACTION_FAILED,
                        "extractor returned a field outside the declared target",
                    )
                segment = _find_segment(draft.evidence_span, segment_bodies)
                if self._claim_construction_route is None:
                    claim = _build_claim(
                        job=job,
                        target=target,
                        field=field,
                        draft=draft,
                        segment_id=str(segment[0]),
                        canonical_key=segments[segment[1]].canonical_artifact_key,
                        run_id=run_id,
                    )
                else:
                    claim = self._claim_construction_route.build(
                        job=job,
                        target=target,
                        field=field,
                        draft=draft,
                        segment_id=str(segment[0]),
                        canonical_key=segments[segment[1]].canonical_artifact_key,
                        run_id=run_id,
                    )
                if target.entity_type is EntityType.CONTACT:
                    if not isinstance(entity, ContactEntity):
                        raise IngestionError(
                            IngestionFailureCode.INVALID_CONTEXT,
                            "declared contact target did not resolve to a contact",
                        )
                    if self._contact_claim_route is not None:
                        governed_claim = await self._contact_claim_route.tag(
                            conn,
                            claim=claim,
                            contact=entity,
                            field=field,
                            target=target,
                        )
                    elif self._claim_tagger is not None:
                        governed_claim = self._claim_tagger(claim)
                    else:
                        raise IngestionError(
                            IngestionFailureCode.INVALID_CONTEXT,
                            "contact extraction requires an injected production ClaimTagger",
                        )
                    if governed_claim is None:
                        unmapped.append(segment[0])
                        continue
                    claim = governed_claim
                pending_claims.append(claim)

        if pending_claims:
            # FI-2 P2 (spec §3): register the extraction run before the claims that cite it, in
            # this same transaction — so every ingested claim's ``run_id`` back-joins to a lineage
            # row. Idempotent, and only written when the job actually produced claims, so a
            # preference/unmapped-only job registers no run that never wrote.
            #
            # Kind and project: ingestion is human-supplied *document evidence* uploaded into the
            # workspace, so it registers as ``manual`` with ``project_id=None``. Account and contact
            # targets share the one kind deliberately — the project lens dispatches on
            # ``project_id`` and ``kind`` is advisory, so splitting it per entity type would buy
            # nothing and only invite two names for one path. The declared context does carry a
            # ``project_id``, but uploaded material is workspace-scoped truth about the
            # account/contact itself (it stays true whichever project reads it), so it is
            # deliberately *not* pinned into one project's lens.
            await record_run_lineage(
                conn, run_id=run_id, workspace_id=job.workspace_id, kind="manual"
            )

        claim_ids = []
        try:
            for claim in pending_claims:
                claim_ids.append(await insert_claim(conn, claim))
        except Exception as exc:
            raise IngestionError(
                IngestionFailureCode.EXTRACTION_FAILED,
                "claim insertion failed for extracted material",
            ) from exc
        refs = IngestionResultRefs(
            claims=tuple(claim_ids),
            proposals=tuple(proposal_refs),
            memory=memory_refs,
            project_state=project_refs,
            unmapped_segments=tuple(dict.fromkeys(unmapped)),
        )
        await complete_job(conn, job.id, refs)

    def _validate_artifact(self, artifact: ArtifactRecord, workspace_id: str) -> None:
        if artifact.erased_at is not None:
            raise IngestionError(
                IngestionFailureCode.ARTIFACT_ERASED, "captured artifact has been erased"
            )
        if artifact.workspace_id != workspace_id:
            raise IngestionError(
                IngestionFailureCode.ARTIFACT_SCOPE_MISMATCH,
                "captured artifact is absent from this workspace",
            )
        if artifact.size_bytes > self._policy.max_bytes:
            raise IngestionError(
                IngestionFailureCode.SIZE_LIMIT_EXCEEDED,
                "captured artifact exceeds the configured byte limit",
            )
        if artifact.media_type not in self._policy.allowed_media_types:
            raise IngestionError(
                IngestionFailureCode.UNSUPPORTED_MEDIA_TYPE,
                "captured artifact media type is not allowed",
            )

    def _registered_adapter(self, media_type: str) -> RegisteredDocumentAdapter:
        registered = self._adapters.get(media_type)
        if registered is None:
            code = (
                IngestionFailureCode.OCR_DISABLED
                if media_type.startswith("image/") and not self._policy.ocr_enabled
                else IngestionFailureCode.UNSUPPORTED_MEDIA_TYPE
            )
            raise IngestionError(code, "no document adapter is registered for this media type")
        return registered

    @staticmethod
    async def _validate_context(
        conn: AsyncConnection, workspace_id: str, context: DeclaredMaterialContext
    ) -> None:
        row = (
            await conn.execute(
                text("SELECT 1 FROM brand WHERE brand_id = :brand AND workspace_id = :workspace"),
                {"brand": context.brand_id, "workspace": workspace_id},
            )
        ).scalar_one_or_none()
        if row is None:
            raise IngestionError(
                IngestionFailureCode.INVALID_CONTEXT,
                "declared brand is absent from this workspace",
            )
        if context.product_id is not None:
            product = (
                await conn.execute(
                    text(
                        "SELECT 1 FROM product WHERE product_id = :product AND brand_id = :brand "
                        "AND workspace_id = :workspace"
                    ),
                    {
                        "product": context.product_id,
                        "brand": context.brand_id,
                        "workspace": workspace_id,
                    },
                )
            ).scalar_one_or_none()
            if product is None:
                raise IngestionError(
                    IngestionFailureCode.INVALID_CONTEXT,
                    "declared product is absent from the selected brand/workspace",
                )
        if context.project_id is not None:
            project = (
                (
                    await conn.execute(
                        text(
                            "SELECT project_id, product_id FROM project "
                            "WHERE project_id = :project "
                            "AND brand_id = :brand AND workspace_id = :workspace"
                        ),
                        {
                            "project": context.project_id,
                            "brand": context.brand_id,
                            "workspace": workspace_id,
                        },
                    )
                )
                .mappings()
                .first()
            )
            if project is None:
                raise IngestionError(
                    IngestionFailureCode.INVALID_CONTEXT,
                    "declared project is absent from the selected brand/workspace",
                )
            if project["product_id"] != context.product_id:
                raise IngestionError(
                    IngestionFailureCode.INVALID_CONTEXT,
                    "declared product does not match the project's selected product",
                )


def _canonicalize(
    raw_segments: tuple[DocumentSegment, ...],
) -> tuple[bytes, tuple[_CanonicalSegment, ...]]:
    bodies: list[str] = []
    segments: list[_CanonicalSegment] = []
    cursor = 0
    for raw in raw_segments:
        if not raw.text:
            continue
        if bodies:
            cursor += 1
        start = cursor
        bodies.append(raw.text)
        cursor += len(raw.text)
        locator = {
            **raw.locator,
            "canonical_char_start": start,
            "canonical_char_end": cursor,
        }
        segments.append(_CanonicalSegment(ordinal=len(segments), text=raw.text, locator=locator))
    return "\n".join(bodies).encode(), tuple(segments)


async def _load_canonical(storage: StorageBackend, segments: tuple[IngestionSegment, ...]) -> bytes:
    if not segments:
        return b""
    key = segments[0].canonical_artifact_key
    if any(segment.canonical_artifact_key != key for segment in segments):
        raise IngestionError(
            IngestionFailureCode.EXTRACTION_FAILED,
            "ingestion segments disagree on their canonical artifact",
        )
    return await storage.get(key)


def _segment_bodies(
    canonical: bytes, segments: tuple[IngestionSegment, ...]
) -> tuple[tuple[IngestionSegmentId, str], ...]:
    text_body = canonical.decode()
    result: list[tuple[IngestionSegmentId, str]] = []
    for segment in segments:
        start = segment.locator.get("canonical_char_start")
        end = segment.locator.get("canonical_char_end")
        if not isinstance(start, int) or not isinstance(end, int):
            raise IngestionError(
                IngestionFailureCode.EXTRACTION_FAILED,
                "segment lacks canonical character coordinates",
            )
        body = text_body[start:end]
        if hashlib.sha256(body.encode()).hexdigest() != segment.text_sha256:
            raise IngestionError(
                IngestionFailureCode.EXTRACTION_FAILED,
                "canonical segment checksum mismatch",
            )
        result.append((segment.id, body))
    return tuple(result)


def _find_segment(
    span: str, segment_bodies: tuple[tuple[IngestionSegmentId, str], ...]
) -> tuple[IngestionSegmentId, int]:
    for index, (segment_id, body) in enumerate(segment_bodies):
        if span and span in body:
            return segment_id, index
    raise IngestionError(
        IngestionFailureCode.EXTRACTION_FAILED,
        "claim evidence span does not resolve to a durable segment",
    )


def _build_claim(
    *,
    job: IngestionJob,
    target: IngestionTarget,
    field: FieldDef,
    draft: ClaimDraft,
    segment_id: str,
    canonical_key: str,
    run_id: RunId,
) -> Claim:
    del field
    tier = 3 if target.material_context is MaterialContext.CLIENT_ABOUT_TARGET else 1
    research_mode = (
        ResearchMode.CONTACT_PROFILING
        if target.entity_type is EntityType.CONTACT
        else ResearchMode.ACCOUNT_PROFILING
    )
    use_class = draft.use_class or target.use_class
    if (
        target.entity_type is EntityType.CONTACT
        and classify_field_key(target.field_key) is FieldClass.CONTACT_FACET
        and use_class is None
    ):
        raise IngestionError(
            IngestionFailureCode.INVALID_CONTEXT,
            "contact.facet extraction requires an explicit governed use_class",
        )
    claim = Claim(
        entity_id=target.entity_id,
        entity_type=target.entity_type,
        field_key=target.field_key,
        value_json=to_value_json(draft.value),
        source_url=f"ingestion://{job.id}/{segment_id}",
        source_key="client_upload",
        artifact_key=canonical_key,
        source_tier=tier,
        extraction_method=ExtractionMethod.HUMAN,
        evidence_span=draft.evidence_span,
        confidence=draft.confidence,
        observed_at=draft.observed_at,
        cost_cents=Decimal(0),
        run_id=run_id,
        research_mode=research_mode,
        identity_binding=(
            target.manifest_identity_binding or IdentityBinding.WEAK
            if target.entity_type is EntityType.CONTACT
            else None
        ),
        use_class=use_class if target.entity_type is EntityType.CONTACT else None,
        reuse_scope=ReuseScope.TENANT_PRIVATE,
        workspace_id=job.workspace_id,
    )
    # Product scope is C4-owned. The injected ClaimConstructionRoute builds the C4 shape
    # before insertion; C3 never mutates a stored claim afterward.
    return revalidate_with(claim)


def build_ingestion_claim(
    *,
    job: IngestionJob,
    target: IngestionTarget,
    field: FieldDef,
    draft: ClaimDraft,
    segment_id: str,
    canonical_key: str,
    run_id: RunId,
) -> Claim:
    """The public C3 claim factory used by C4's additive product-scope route."""
    return _build_claim(
        job=job,
        target=target,
        field=field,
        draft=draft,
        segment_id=segment_id,
        canonical_key=canonical_key,
        run_id=run_id,
    )


def _ref(job: IngestionJob) -> IngestionJobRef:
    return IngestionJobRef(
        ingestion_job_id=job.id, artifact_key=job.artifact_key, status=job.status
    )
