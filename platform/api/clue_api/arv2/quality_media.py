"""Transcript originals and turn evidence through the same scoped research evidence seam."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal
from uuid import UUID, uuid5

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_api.arv2 import media_store
from clue_api.arv2.account_research_claims import JobScope
from clue_api.arv2.media_types import Segment
from clue_api.arv2.quality_evidence import (
    EvidenceGrant,
    EvidenceUnavailable,
    SourceRef,
    TextSupport,
    persist_source,
    resolve_source,
    validate_support,
)
from clue_api.arv2.research_operations import OperationScope
from clue_research.claimstore.quality import assess_claim
from clue_storage import StorageBackend, read_verified_artifact, retain_artifact


class SpeakerIntroduction(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    speaker_label: str = Field(min_length=1, max_length=200)
    passage: TextSupport


class TranscriptSupport(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    kind: Literal["transcript"] = "transcript"
    source_id: UUID
    version_ref: UUID
    start: int = Field(ge=0)
    end: int = Field(gt=0)
    quote: str = Field(min_length=1, max_length=8000)
    introduction: SpeakerIntroduction | None = None


@dataclass(frozen=True)
class TranscriptReader:
    scope: OperationScope
    storage: StorageBackend

    @property
    def operation_scope(self) -> OperationScope:
        return self.scope


async def index_transcripts(
    conn: AsyncConnection, storage: StorageBackend, scope: OperationScope
) -> tuple[SourceRef, ...]:
    """Reconstruct from committed transcripts, including after acquisition receipt failure."""
    rows = (
        (
            await conn.execute(
                text("""SELECT DISTINCT t.version_id FROM arv2_media_transcript t
        JOIN arv2_media_attempt a USING(workspace_id,item_id)
        JOIN arv2_media_item i USING(workspace_id,item_id)
        WHERE t.workspace_id=:ws AND a.job_id=:job AND a.kind='binding'
          AND a.outcome<>'released' AND i.erased_at IS NULL AND i.expires_at>now()
          AND t.expires_at>now() ORDER BY t.version_id"""),
                {"ws": scope.workspace_id, "job": scope.job_id},
            )
        )
        .scalars()
        .all()
    )
    refs = []
    for version in rows:
        saved = await media_store.load_transcript(TranscriptReader(scope, storage), conn, version)
        ref = await persist_source(
            conn,
            storage,
            scope,
            kind="transcript",
            body=saved["text"],
            original_key=saved["text_key"],
            origin_locator=f"transcript:{version}",
            observed_at=saved["created_at"],
            source_url=saved["source_url"],
            metadata={
                "version_ref": str(version),
                "item_ref": str(saved["item_id"]),
                "quality": saved["quality"],
                "segments_key": saved["segments_key"],
                "transcript_view": f"/research/transcripts/{version}/0.json",
            },
        )
        await retain_artifact(
            conn,
            workspace_id=scope.workspace_id,
            storage_key=saved["segments_key"],
            reference_kind="research_source",
            reference_id=str(ref.source_id),
        )
        refs.append(ref)
    return tuple(refs)


async def read_transcript(
    conn: AsyncConnection,
    storage: StorageBackend,
    grant: EvidenceGrant,
    version: UUID,
    start: int = 0,
) -> dict[str, Any]:
    # Only a manifest source may confer access, not a guessed workspace-wide version ID.
    ids = (
        (
            await conn.execute(
                text("""SELECT source_id FROM arv2_evidence_source
        WHERE workspace_id=:ws AND run_id=:run AND account_id=:account AND kind='transcript'
          AND metadata->>'version_ref'=:version ORDER BY revision"""),
                {
                    "ws": grant.scope.workspace_id,
                    "run": grant.scope.run_id,
                    "account": grant.scope.account_id,
                    "version": str(version),
                },
            )
        )
        .scalars()
        .all()
    )
    for sid in ids:
        try:
            await resolve_source(conn, grant, sid)
        except EvidenceUnavailable:
            continue
        saved = await media_store.load_transcript(
            TranscriptReader(grant.scope, storage), conn, version, require_binding=False
        )
        if not 0 <= start <= len(saved["segments"]):
            raise EvidenceUnavailable("restart the transcript segment view at 0")
        end = len(saved["segments"])
        return {
            "source_id": str(sid),
            "version_ref": str(version),
            "current_version": str(saved["current_version"]),
            "superseded": saved["superseded"],
            "quality": saved["quality"],
            "segments": [s.model_dump(mode="json") for s in saved["segments"][start:end]],
            "next_path": f"/research/transcripts/{version}/{end}.json"
            if end < len(saved["segments"])
            else None,
        }
    raise EvidenceUnavailable(
        "invalid transcript reference; read /evidence/index.json for valid versions"
    )


async def validate_transcript(
    conn: AsyncConnection,
    storage: StorageBackend,
    grant: EvidenceGrant,
    scope: JobScope,
    support: TranscriptSupport,
) -> tuple[SourceRef, dict[str, Any], list[str]]:
    ref = await validate_support(
        conn,
        storage,
        grant,
        TextSupport(
            source_id=support.source_id, start=support.start, end=support.end, quote=support.quote
        ),
    )
    if ref.kind != "transcript" or ref.metadata.get("version_ref") != str(support.version_ref):
        raise EvidenceUnavailable("source and transcript version differ")
    saved = await media_store.load_transcript(
        TranscriptReader(grant.scope, storage), conn, support.version_ref, require_binding=False
    )
    if saved["superseded"]:
        raise EvidenceUnavailable(
            "transcript was repaired; list current versions before rechecking"
        )
    segments: list[Segment] = [
        s for s in saved["segments"] if s.start < support.end and s.end > support.start
    ]
    cursor = support.start
    for seg in sorted(segments, key=lambda s: s.start):
        if seg.start > cursor:
            break
        cursor = max(cursor, seg.end)
    if cursor < support.end:
        raise EvidenceUnavailable("the quoted range lacks complete segment support")
    bound = False
    introduction = support.introduction
    if introduction and scope.person_subject_id:
        intro = introduction.passage
        if intro.source_id != ref.source_id:
            raise EvidenceUnavailable("introduction must be a passage in this exact recording")
        await validate_support(conn, storage, grant, intro)
        intro_segments = [
            s for s in saved["segments"] if s.start < intro.end and s.end > intro.start
        ]
        # Exact name in the introduction and a consistent turn label are necessary, not a
        # declaration that every voice in an episode belongs to its named guest.
        import re

        bound = bool(scope.person_name.strip()) and bool(
            re.search(
                r"\b(?:i am|i'm|my name is)\s+" + re.escape(scope.person_name) + r"\b",
                intro.quote,
                re.IGNORECASE,
            )
        )
        bound = (
            bound
            and bool(intro_segments)
            and all(
                s.speaker == introduction.speaker_label
                and s.attribution != "conflict"
                and s.entity_id in (None, scope.person_subject_id)
                for s in [*segments, *intro_segments]
            )
        )
    warnings = list(saved["quality"].get("warnings", []))
    if saved["quality"].get("coverage") != "full":
        warnings.append("Transcript coverage is incomplete or unknown.")
    if any(v is True for v in saved["quality"].get("loop_report", {}).values()):
        warnings.append("Transcript repetition needs review.")
    if scope.person_subject_id and not bound:
        warnings.append("The quoted voice is not corroborated as this person.")
    return (
        ref,
        {
            "schema_version": 2,
            "version_ref": str(support.version_ref),
            "start": support.start,
            "end": support.end,
            "quote_verdict": "EXACT",
            "attribution": "evidence_backed" if bound else "unverified",
            "speaker_binding": introduction.model_dump(mode="json") if introduction else None,
            "segments": [s.model_dump(mode="json") for s in segments],
            "quality": saved["quality"],
            "superseded": False,
            "segments_key": saved["segments_key"],
            "timing": "unavailable"
            if not any(s.time_s is not None for s in segments)
            else "estimated"
            if any(s.timing == "model_estimated" for s in segments)
            else "source_supplied",
        },
        warnings,
    )


async def invalidate_repaired(
    conn: AsyncConnection, storage: StorageBackend, workspace_id: str, previous: UUID, current: UUID
) -> None:
    rows = (
        (
            await conn.execute(
                text("""SELECT c.id,c.entity_id,q.revision,q.context_id,
        q.assessment_id FROM claim c JOIN claim_quality_current q ON q.claim_id=c.id
        WHERE c.workspace_id=:ws AND c.superseded_by IS NULL
          AND c.write_markers->'media'->>'version_ref'=:old
        ORDER BY c.id"""),
                {"ws": workspace_id, "old": str(previous)},
            )
        )
        .mappings()
        .all()
    )
    # The new immutable transcript is the rationale, never a rewrite of the old evidence.
    key = (
        await conn.execute(
            text("""SELECT segments_key FROM arv2_media_transcript
        WHERE workspace_id=:ws AND version_id=:version"""),
            {"ws": workspace_id, "version": current},
        )
    ).scalar_one()
    await read_verified_artifact(conn, storage, workspace_id=workspace_id, storage_key=key)
    for row in rows:
        oid = uuid5(current, f"recheck:{row['id']}")
        if (
            await conn.execute(
                text("SELECT 1 FROM claim_quality_operation WHERE operation_id=:id"), {"id": oid}
            )
        ).scalar_one_or_none():
            continue
        keys = tuple(
            (
                await conn.execute(
                    text("""SELECT artifact_key FROM claim_quality_support
            WHERE assessment_id=:id ORDER BY artifact_key"""),
                    {"id": row["assessment_id"]},
                )
            ).scalars()
        )
        await assess_claim(
            conn,
            workspace_id=workspace_id,
            entity_id=row["entity_id"],
            claim_id=row["id"],
            operation_id=oid,
            expected_revision=row["revision"],
            conclusion="unresolved",
            rationale_key=key,
            actor_ref="transcript-repair:v1",
            support_artifacts=keys,
            context_id=row["context_id"],
            kind="conflict",
        )
