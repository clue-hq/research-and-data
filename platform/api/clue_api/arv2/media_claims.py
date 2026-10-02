"""Server-resolved transcript provenance; annotations never pretend ASR labels prove identity."""

from __future__ import annotations

from dataclasses import replace
from typing import Any
from uuid import UUID

from sqlalchemy import text

from clue_api.arv2 import media_store as store
from clue_api.arv2.media_types import TranscriptSource
from clue_api.arv2.structuring_client import SourceBlock
from clue_api.arv2.text import substring_verdict


async def resolve_source(
    runtime: Any, source: TranscriptSource
) -> tuple[SourceBlock, dict[str, Any]]:
    async with runtime._conn_factory() as conn:
        saved = await store.load_transcript(runtime, conn, source.version_ref)
    if source.end > len(saved["text"]):
        raise store.unavailable("source offset exceeds transcript")
    return SourceBlock(
        url=saved["source_url"],
        kind="transcript",
        text=saved["text"][source.start : source.end],
        title=saved["title"],
        annotations={
            "version_ref": str(source.version_ref),
            "start": source.start,
            "end": source.end,
            "quality": saved["quality"],
            "quotes": saved["quotes"],
            "superseded": saved["superseded"],
            "segments": [
                s.model_dump(mode="json")
                for s in saved["segments"]
                if s.start < source.end and s.end > source.start
            ],
        },
    ), saved


def attach(draft: Any, source: TranscriptSource, saved: dict[str, Any], runtime: Any) -> Any:
    value = saved["text"][source.start : source.end]
    quote = draft.evidence_span or ""
    verdict = substring_verdict(quote, value)
    relative = value.find(quote) if quote else -1
    start = source.start + relative if relative >= 0 else source.start
    end = start + len(quote) if relative >= 0 else source.end
    segments = [s for s in saved["segments"] if s.start < end and s.end > start]
    mined = [q for q in saved.get("quotes", []) if q.get("text") == quote]
    mining_unsafe = any(q.get("verdict") == "NOT_FOUND" or q.get("usable") is False for q in mined)
    strong = bool(segments) and all(
        s.attribution == "evidence_backed" and str(s.entity_id) == str(runtime.scope.contact_id)
        for s in segments
    )
    media = {
        "schema_version": 1,
        "version_ref": str(source.version_ref),
        "start": start,
        "end": end,
        "quote_verdict": verdict,
        "mined_quote_qualifications": [
            {"verdict": q.get("verdict"), "usable": q.get("usable")} for q in mined
        ],
        "attribution": "evidence_backed" if strong else "unverified",
        "segments": [s.model_dump(mode="json") for s in segments],
        "quality": saved["quality"],
        "superseded": saved["superseded"],
        "timing": "unavailable" if not any(s.time_s is not None for s in segments) else "qualified",
    }
    return replace(
        draft,
        artifact_key=saved["text_key"],
        source_url=saved["source_url"],
        outreach_safe=draft.outreach_safe
        and not mining_unsafe
        and (runtime.scope.subject_kind != "person" or strong)
        and verdict == "EXACT",
        markers={
            **draft.markers,
            "media": media,
            "source_kind_block": "transcript",
            "media_timestamp": None,
        },
    )


async def annotate_drafts(
    runtime: Any, drafts: list[Any], sources: list[tuple[TranscriptSource, dict[str, Any]]]
) -> list[Any]:
    output = []
    for draft in drafts:
        matches = [
            (source, saved) for source, saved in sources if draft.source_url == saved["source_url"]
        ]
        if len(matches) > 1:
            exact = [
                (s, v)
                for s, v in matches
                if draft.evidence_span and draft.evidence_span in v["text"][s.start : s.end]
            ]
            matches = exact if len(exact) == 1 else []
        if len(matches) == 1:
            draft = attach(draft, *matches[0], runtime)
        elif draft.markers.get("source_kind_block") == "transcript":
            draft = replace(
                draft, outreach_safe=False, markers={**draft.markers, "media_reference_gap": True}
            )
        output.append(draft)
    return output


async def audit(runtime: Any, claim: Any) -> tuple[str, str, dict[str, Any]]:
    marker = (claim.write_markers or {}).get("media")
    if not isinstance(marker, dict):
        return "fetch_failed", "legacy_transcript_reference_missing", {}
    try:
        async with runtime._conn_factory() as conn:
            saved = await store.load_transcript(runtime, conn, UUID(marker["version_ref"]))
        start, end = marker["start"], marker["end"]
        if (
            not isinstance(start, int)
            or not isinstance(end, int)
            or not 0 <= start < end <= len(saved["text"])
        ):
            return "NOT_FOUND", "transcript_offset_mismatch", {}
        verdict = substring_verdict(claim.evidence_span or "", saved["text"][start:end])
        reason = (
            "superseded_transcript_needs_recheck"
            if saved["superseded"]
            else "transcript_" + verdict.lower()
        )
        return (
            verdict,
            reason,
            {"media": {**marker, "quality": saved["quality"], "superseded": saved["superseded"]}},
        )
    except Exception:
        return "fetch_failed", "transcript_unavailable", {}


async def mark_repaired(runtime: Any, conn: Any, previous: UUID, current: UUID) -> None:
    from clue_api.arv2.quality_media import invalidate_repaired

    await invalidate_repaired(conn, runtime.storage, runtime.scope.workspace_id, previous, current)
    # Append an audit finding, preserving the original claim and its pinned evidence.
    await conn.execute(
        text("""INSERT INTO
        arv2_claim_annotation(claim_id,job_id,kind,verdict,detail_json)
      SELECT id,:job,'link_audit','fetch_failed',jsonb_build_object(
        'reason','superseded_transcript_needs_recheck','previous_version',CAST(:previous AS
        text),
        'current_version',CAST(:current AS text))
      FROM claim WHERE workspace_id=:ws AND write_markers->'media'->>'version_ref'=:previous
    """),
        {
            "ws": runtime.scope.workspace_id,
            "job": runtime.scope.job_id,
            "previous": str(previous),
            "current": str(current),
        },
    )


async def guard_draft(runtime: Any, conn: Any, draft: Any) -> Any:
    """Close non-structuring paths (unique insight/final openers) over known media sources."""
    if draft.markers.get("media"):
        return draft
    matches = [
        block
        for block in runtime.person_sources
        if block.annotations
        and block.annotations.get("version_ref")
        and block.url == draft.source_url
        and draft.evidence_span
        and draft.evidence_span in block.text
    ]
    if len(matches) == 1:
        meta = matches[0].annotations
        source = TranscriptSource(
            version_ref=meta["version_ref"], start=meta["start"], end=meta["end"]
        )
        saved = await store.load_transcript(runtime, conn, source.version_ref)
        return attach(draft, source, saved, runtime)
    is_media = draft.markers.get("source_kind_block") == "transcript"
    if draft.source_url:
        from clue_api.arv2.media_types import content_hash

        is_media = (
            is_media
            or (
                await conn.execute(
                    text("""SELECT EXISTS(SELECT 1 FROM arv2_media_alias a
          JOIN arv2_media_attempt b USING(workspace_id,item_id) WHERE a.workspace_id=:ws
          AND b.job_id=:job AND a.alias_hash=:hash AND b.kind='binding')"""),
                    {
                        "ws": runtime.scope.workspace_id,
                        "job": runtime.scope.job_id,
                        "hash": content_hash(draft.source_url),
                    },
                )
            ).scalar_one()
        )
    if is_media:
        return replace(
            draft,
            outreach_safe=False,
            markers={
                **draft.markers,
                "media_reference_gap": True,
                "source_kind_block": "transcript",
            },
        )
    return draft
