"""Workspace-local source evidence. Project interpretation stays in job attempts/claims."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

from sqlalchemy import text

from clue_api.arv2.account_research_refusals import RefusalError
from clue_api.arv2.media_types import Candidate, Quality, Segment, canonical_text, content_hash
from clue_api.arv2.research_operations import job_available
from clue_research.identity.provider import register_provider_subjects
from clue_storage import artifact_key, content_address, read_verified_artifact, record_artifact

if TYPE_CHECKING:
    from clue_api.arv2.media_resolution import Resolution


def unavailable(
    message: str = "media reference unavailable in this research scope",
) -> RefusalError:
    return RefusalError("tool_error", message)


async def authority(runtime: Any, conn: Any) -> None:
    exists = (
        await conn.execute(
            text("""SELECT EXISTS(SELECT 1 FROM arv2_research_job
      WHERE workspace_id=:ws AND job_id=:job AND run_id=:run AND account_entity_id=:account)"""),
            {
                "ws": runtime.scope.workspace_id,
                "job": runtime.scope.job_id,
                "run": runtime.scope.run_id,
                "account": runtime.scope.account_id,
            },
        )
    ).scalar_one()
    if (
        not exists
        or runtime.storage is None
        or not await job_available(conn, runtime.operation_scope)
    ):
        raise unavailable("media storage or research authority unavailable")


async def item_for(runtime: Any, conn: Any, candidate: Candidate) -> dict[str, Any]:
    await authority(runtime, conn)
    ws = runtime.scope.workspace_id
    key = candidate.canonical_key or "url:" + content_hash(candidate.url)
    item_id = uuid5(NAMESPACE_URL, f"arv2-media:{ws}:{key}")
    aliases = [
        content_hash(url)
        for url in (candidate.url, candidate.media_url, candidate.transcript_url)
        if url
    ]
    existing = (
        (
            await conn.execute(
                text("""
      SELECT i.* FROM arv2_media_item i LEFT JOIN arv2_media_alias a
        USING(workspace_id,item_id)
      WHERE i.workspace_id=:ws AND (i.canonical_key=:key OR a.alias_hash=ANY(:aliases))
    """),
                {"ws": ws, "key": key, "aliases": aliases},
            )
        )
        .mappings()
        .first()
    )
    if existing:
        if existing["privacy_erased"]:
            raise unavailable("recording was privacy-erased; alternate URLs cannot reacquire it")
        if existing["erased_at"]:
            raise unavailable(
                "recording expired; deliberate reacquisition must use refresh_expired"
            )
        if not existing["metadata"]:
            await conn.execute(
                text("""UPDATE arv2_media_item SET source_url=:url,title=:title,
              metadata=CAST(:meta AS jsonb) WHERE workspace_id=:ws AND item_id=:id AND NOT
        privacy_erased"""),
                {
                    "ws": ws,
                    "id": existing["item_id"],
                    "url": candidate.url,
                    "title": candidate.title,
                    "meta": candidate.model_dump_json(),
                },
            )
            return {
                **dict(existing),
                "metadata": candidate.model_dump(mode="json"),
                "source_url": candidate.url,
                "title": candidate.title,
            }
        return dict(existing)
    await conn.execute(
        text("""
      INSERT INTO arv2_media_item(workspace_id,item_id,canonical_key,source_url,title,metadata)
      VALUES (:ws,:id,:key,:url,:title,CAST(:meta AS jsonb)) ON CONFLICT DO NOTHING
    """),
        {
            "ws": ws,
            "id": item_id,
            "key": key,
            "url": candidate.url,
            "title": candidate.title,
            "meta": candidate.model_dump_json(),
        },
    )
    await conn.execute(
        text("""
      INSERT INTO arv2_media_alias(workspace_id,alias_hash,item_id) VALUES(:ws,:alias,:id)
      ON CONFLICT DO NOTHING
    """),
        {"ws": ws, "alias": content_hash(candidate.url), "id": item_id},
    )
    return dict(
        (
            await conn.execute(
                text("SELECT * FROM arv2_media_item WHERE workspace_id=:ws AND item_id=:id"),
                {"ws": ws, "id": item_id},
            )
        )
        .mappings()
        .one()
    )


async def attempt(
    runtime: Any,
    conn: Any,
    *,
    kind: str,
    outcome: str,
    purpose: str = "",
    item_id: UUID | None = None,
    version_id: UUID | None = None,
    data: dict[str, Any] | None = None,
    attempt_id: UUID | None = None,
) -> UUID:
    await authority(runtime, conn)
    aid = attempt_id or uuid4()
    await conn.execute(
        text("""
      INSERT INTO
        arv2_media_attempt(workspace_id,attempt_id,job_id,item_id,version_id,kind,outcome,purpose,data)
      VALUES(:ws,:id,:job,:item,:version,:kind,:outcome,:purpose,CAST(:data AS jsonb))
      ON CONFLICT DO NOTHING
    """),
        {
            "ws": runtime.scope.workspace_id,
            "id": aid,
            "job": runtime.scope.job_id,
            "item": item_id,
            "version": version_id,
            "kind": kind,
            "outcome": outcome,
            "purpose": purpose,
            "data": json.dumps(data or {}, default=str),
        },
    )
    return aid


async def get_attempt(runtime: Any, conn: Any, aid: UUID) -> dict[str, Any]:
    await authority(runtime, conn)
    row = (
        (
            await conn.execute(
                text("""
      SELECT * FROM arv2_media_attempt WHERE workspace_id=:ws AND job_id=:job AND
        attempt_id=:id
        AND created_at>now()-interval '30 days' AND outcome<>'unavailable'
    """),
                {"ws": runtime.scope.workspace_id, "job": runtime.scope.job_id, "id": aid},
            )
        )
        .mappings()
        .one_or_none()
    )
    if row is None:
        raise unavailable()
    return dict(row)


async def bind_item(runtime: Any, conn: Any, item_id: UUID, purpose: str) -> None:
    """Reserve a distinct substantive person recording slot, serialized with other tools."""
    await authority(runtime, conn)
    await conn.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:key,0))"),
        {"key": f"media-job:{runtime.scope.workspace_id}:{runtime.scope.job_id}"},
    )
    params = {"ws": runtime.scope.workspace_id, "job": runtime.scope.job_id, "item": item_id}
    existing = (
        await conn.execute(
            text("""SELECT EXISTS(SELECT 1 FROM arv2_media_attempt
      WHERE workspace_id=:ws AND job_id=:job AND item_id=:item AND kind='binding' AND
        outcome<>'released')"""),
            params,
        )
    ).scalar_one()
    if existing:
        return
    if runtime.scope.subject_kind == "person":
        count = (
            await conn.execute(
                text("""SELECT count(DISTINCT item_id) FROM arv2_media_attempt
          WHERE workspace_id=:ws AND job_id=:job AND kind='binding' AND outcome<>'released'"""),
                params,
            )
        ).scalar_one()
        if count >= runtime.settings.arv2_person_media_max_items:
            raise unavailable("person media item allowance reached")
    await attempt(
        runtime, conn, kind="binding", outcome="reserved", item_id=item_id, purpose=purpose
    )


async def release_item(runtime: Any, conn: Any, item_id: UUID) -> None:
    await conn.execute(
        text("""UPDATE arv2_media_attempt SET outcome='released'
      WHERE workspace_id=:ws AND job_id=:job AND item_id=:item AND kind='binding'
        AND outcome='reserved'"""),
        {"ws": runtime.scope.workspace_id, "job": runtime.scope.job_id, "item": item_id},
    )


async def consume_reused_item(runtime: Any, conn: Any, item_id: UUID) -> None:
    """Bind every reused artifact to the known consumer for subsequent contact erasure."""
    keys = (
        (
            await conn.execute(
                text("""SELECT text_key AS key FROM arv2_media_transcript
              WHERE workspace_id=:ws AND item_id=:item
              UNION SELECT segments_key FROM arv2_media_transcript
              WHERE workspace_id=:ws AND item_id=:item
              UNION SELECT unnest(artifact_keys) FROM arv2_media_operation
              WHERE workspace_id=:ws AND item_id=:item"""),
                {"ws": runtime.scope.workspace_id, "item": item_id},
            )
        )
        .scalars()
        .all()
    )
    for key in keys:
        await subjects(runtime, conn, key, [])
    await conn.execute(
        text("""UPDATE arv2_media_attempt SET outcome='consumed'
          WHERE workspace_id=:ws AND job_id=:job AND item_id=:item AND kind='binding'
            AND outcome='reserved'"""),
        {"ws": runtime.scope.workspace_id, "job": runtime.scope.job_id, "item": item_id},
    )


async def subjects(
    runtime: Any, conn: Any, key: str, recognized: list[tuple[str, str | None]]
) -> None:
    """Unknown speaker labels never become subjects. Recognized excluded speakers do."""
    ws = runtime.scope.workspace_id
    await register_provider_subjects(
        conn, workspace_id=ws, provider="arv2-media", artifact_key=key, subjects=recognized
    )
    # The researched contact is known by canonical identity, not inferred from ASR labels.
    if runtime.scope.contact_id:
        cid = str(runtime.scope.contact_id)
        await register_provider_subjects(
            conn,
            workspace_id=ws,
            provider="arv2-contact",
            artifact_key=key,
            subjects=[(cid, runtime.scope.person_linkedin_url or None)],
        )
        await conn.execute(
            text(
                "UPDATE provider_identity SET contact_id=:cid WHERE workspace_id=:ws "
                "AND provider='arv2-contact' AND subject_id=:subject"
            ),
            {"ws": ws, "cid": runtime.scope.contact_id, "subject": cid},
        )
    await conn.execute(
        text("""UPDATE artifact SET expires_at=LEAST(COALESCE(expires_at,now()+interval
        '30 days'),now()+interval '30 days')
      WHERE workspace_id=:ws AND storage_key=:key"""),
        {"ws": ws, "key": key},
    )


async def save_transcript(
    runtime: Any,
    conn: Any,
    *,
    item_id: UUID,
    value: str,
    segments: list[Segment],
    quality: Quality,
    method: str,
    operation_id: UUID,
    supersedes: UUID | None = None,
    recognized: list[tuple[str, str | None]] | None = None,
) -> UUID:
    await authority(runtime, conn)
    value = canonical_text(value)
    if not value.strip() or any(s.end > len(value) for s in segments):
        raise ValueError("empty transcript or segment outside canonical text")
    item = (
        (
            await conn.execute(
                text(
                    (
                        "SELECT * FROM arv2_media_item WHERE workspace_id=:ws AND item_id=:id "
                        "FOR UPDATE"
                    )
                ),
                {"ws": runtime.scope.workspace_id, "id": item_id},
            )
        )
        .mappings()
        .one()
    )
    if item["privacy_erased"] or item["erased_at"]:
        raise unavailable()
    if supersedes and item["current_version"] != supersedes:
        raise unavailable("repair must refer to the current immutable version")
    version_id = uuid5(operation_id, "canonical-transcript-v1")
    existing = (
        await conn.execute(
            text(
                "SELECT version_id FROM arv2_media_transcript WHERE workspace_id=:ws "
                "AND version_id=:id"
            ),
            {"ws": runtime.scope.workspace_id, "id": version_id},
        )
    ).scalar_one_or_none()
    if existing:
        return UUID(str(existing))
    # Persist under this transaction using the existing CAS primitive; no nested sink transaction.
    txt_key = await persist(runtime, conn, value.encode(), "text/plain; charset=utf-8", item)
    segments_payload = {
        "item_ref": str(item_id),
        "segments": [s.model_dump(mode="json") for s in segments],
    }
    meta_key = await persist(
        runtime,
        conn,
        json.dumps(segments_payload, sort_keys=True).encode(),
        "application/json",
        item,
    )
    await conn.execute(
        text("""INSERT INTO arv2_media_transcript
      (workspace_id,version_id,item_id,text_key,segments_key,text_sha256,char_count,quality,recipe,source_method,supersedes)
      VALUES(:ws,:id,:item,:txt,:meta,:sha,:count,CAST(:quality AS
        jsonb),'newline-v1',:method,:previous)
    """),
        {
            "ws": runtime.scope.workspace_id,
            "id": version_id,
            "item": item_id,
            "txt": txt_key,
            "meta": meta_key,
            "sha": content_hash(value),
            "count": len(value),
            "quality": quality.model_dump_json(),
            "method": method,
            "previous": supersedes,
        },
    )
    for key in (txt_key, meta_key):
        await subjects(runtime, conn, key, recognized or [])
        await read_verified_artifact(
            conn, runtime.storage, storage_key=key, workspace_id=runtime.scope.workspace_id
        )
    await conn.execute(
        text(
            "UPDATE arv2_media_item SET current_version=:version WHERE "
            "workspace_id=:ws AND item_id=:item AND erased_at IS NULL"
        ),
        {"ws": runtime.scope.workspace_id, "item": item_id, "version": version_id},
    )
    await conn.execute(
        text(
            "UPDATE arv2_media_attempt SET outcome='consumed' WHERE "
            "workspace_id=:ws AND job_id=:job AND item_id=:item AND kind='binding'"
        ),
        {"ws": runtime.scope.workspace_id, "job": runtime.scope.job_id, "item": item_id},
    )
    if supersedes:
        from clue_api.arv2.media_claims import mark_repaired

        await mark_repaired(runtime, conn, supersedes, version_id)
    return version_id


async def load_transcript(
    runtime: Any, conn: Any, version_id: UUID, *, require_binding: bool = True
) -> dict[str, Any]:
    await authority(runtime, conn)
    row = (
        (
            await conn.execute(
                text("""SELECT t.*,i.source_url,i.title,i.current_version FROM
        arv2_media_transcript t
      JOIN arv2_media_item i USING(workspace_id,item_id)
      WHERE t.workspace_id=:ws AND t.version_id=:id AND i.erased_at IS NULL
        AND i.expires_at>now() AND t.expires_at>now()
        AND (:unbound OR EXISTS(SELECT 1 FROM arv2_media_attempt a WHERE
        a.workspace_id=t.workspace_id
          AND a.job_id=:job AND a.item_id=t.item_id AND a.kind='binding' AND
        a.outcome<>'released'))
    """),
                {
                    "ws": runtime.scope.workspace_id,
                    "id": version_id,
                    "job": runtime.scope.job_id,
                    "unbound": not require_binding,
                },
            )
        )
        .mappings()
        .one_or_none()
    )
    if row is None:
        raise unavailable()
    result = dict(row)
    _, raw = await read_verified_artifact(
        conn, runtime.storage, storage_key=row["text_key"], workspace_id=runtime.scope.workspace_id
    )
    _, raw_segments = await read_verified_artifact(
        conn,
        runtime.storage,
        storage_key=row["segments_key"],
        workspace_id=runtime.scope.workspace_id,
    )
    value = raw.decode()
    if content_hash(value) != row["text_sha256"] or len(value) != row["char_count"]:
        raise unavailable("transcript integrity mismatch")
    result["text"] = value
    result["segments"] = [Segment.model_validate(s) for s in json.loads(raw_segments)["segments"]]
    result["superseded"] = row["current_version"] != version_id
    result["quotes"] = (
        await conn.execute(
            text("""SELECT result->'quotes' FROM arv2_media_operation
              WHERE workspace_id=:ws AND item_id=:item
                AND result->>'version_ref'=:version AND state='succeeded' LIMIT 1"""),
            {"ws": runtime.scope.workspace_id, "item": row["item_id"], "version": str(version_id)},
        )
    ).scalar_one_or_none() or []
    return result


async def state(runtime: Any, conn: Any) -> dict[str, Any]:
    await authority(runtime, conn)
    rows = (
        (
            await conn.execute(
                text("""SELECT kind,outcome,count(*) AS count FROM arv2_media_attempt
      WHERE workspace_id=:ws AND job_id=:job GROUP BY kind,outcome ORDER BY kind,outcome"""),
                {"ws": runtime.scope.workspace_id, "job": runtime.scope.job_id},
            )
        )
        .mappings()
        .all()
    )
    sources = (
        (
            await conn.execute(
                text("""SELECT DISTINCT i.item_id,i.current_version AS
        version_ref,i.title,
      i.source_url,i.erased_at IS NOT NULL OR i.expires_at<=now() AS unavailable
      FROM arv2_media_item i JOIN arv2_media_attempt a USING(workspace_id,item_id)
      WHERE a.workspace_id=:ws AND a.job_id=:job AND a.kind='binding' AND
        a.outcome<>'released'"""),
                {"ws": runtime.scope.workspace_id, "job": runtime.scope.job_id},
            )
        )
        .mappings()
        .all()
    )
    return {
        "attempts": [dict(r) for r in rows],
        "recordings": [
            {
                "item_id": r["item_id"],
                "version_ref": r["version_ref"],
                "title": r["title"][:100],
                "unavailable": r["unavailable"],
            }
            for r in sources[:20]
        ],
        "recording_count": len(sources),
        "recordings_truncated": len(sources) > 20,
        "discovery": "searched" if any(r["kind"] == "discovery" for r in rows) else "unsearched",
        "coverage": "observed_only",
        "exhaustive": False,
    }


async def cached_resolution(runtime: Any, conn: Any, url: str) -> Resolution | None:
    from clue_api.arv2.media_resolution import Resolution, public_url, youtube_url

    url = public_url(url)
    yt = youtube_url(url)
    if yt:
        url = yt[0]
    await authority(runtime, conn)
    row = (
        (
            await conn.execute(
                text("""SELECT i.* FROM arv2_media_item i JOIN arv2_media_alias a
      USING(workspace_id,item_id) WHERE i.workspace_id=:ws AND a.alias_hash=:hash"""),
                {"ws": runtime.scope.workspace_id, "hash": content_hash(url)},
            )
        )
        .mappings()
        .one_or_none()
    )
    if row is None:
        return None
    if row["privacy_erased"]:
        raise unavailable("recording was privacy-erased")
    if row["erased_at"] or row["expires_at"] <= runtime.now():
        raise unavailable("recording expired")
    if row["metadata"] and (
        row["current_version"] or row["metadata"].get("family") != "transcript"
    ):
        return Resolution("resolved", (Candidate.model_validate(row["metadata"]),))
    return None


async def link_aliases(
    runtime: Any,
    conn: Any,
    item_id: UUID,
    aliases: tuple[str, ...],
    *,
    evidence_key: str | None = None,
) -> None:
    for alias in aliases:
        row = await conn.execute(
            text("""INSERT INTO
        arv2_media_alias(workspace_id,alias_hash,item_id,evidence_key)
          VALUES(:ws,:hash,:id,:key) ON CONFLICT(workspace_id,alias_hash) DO UPDATE
            SET evidence_key=COALESCE(arv2_media_alias.evidence_key,EXCLUDED.evidence_key)
            WHERE arv2_media_alias.item_id=EXCLUDED.item_id RETURNING item_id"""),
            {
                "ws": runtime.scope.workspace_id,
                "hash": content_hash(alias),
                "id": item_id,
                "key": evidence_key,
            },
        )
        if row.scalar_one_or_none() is None:
            raise unavailable("recording alias conflicts with an existing source identity")


async def refresh_expired(runtime: Any, conn: Any, url: str) -> None:
    from clue_api.arv2.media_resolution import public_url, youtube_url

    url = public_url(url)
    yt = youtube_url(url)
    if yt:
        url = yt[0]
    await authority(runtime, conn)
    row = (
        (
            await conn.execute(
                text("""SELECT i.* FROM arv2_media_item i JOIN arv2_media_alias a
      USING(workspace_id,item_id) WHERE i.workspace_id=:ws AND a.alias_hash=:hash FOR UPDATE
        OF i"""),
                {"ws": runtime.scope.workspace_id, "hash": content_hash(url)},
            )
        )
        .mappings()
        .one_or_none()
    )
    if row is None:
        return
    if row["privacy_erased"]:
        raise unavailable("privacy-erased media cannot be refreshed")
    if row["expires_at"] > runtime.now() and row["erased_at"] is None:
        return
    # A refresh is an explicit new acquisition generation; prior versions remain expired.
    await conn.execute(
        text("""UPDATE arv2_media_item SET erased_at=NULL,current_version=NULL,
      metadata='{}',acquisition_generation=acquisition_generation+1,expires_at=now()+interval
        '30 days'
      WHERE workspace_id=:ws AND item_id=:id AND NOT privacy_erased"""),
        {"ws": runtime.scope.workspace_id, "id": row["item_id"]},
    )


async def persist(runtime: Any, conn: Any, data: bytes, mime: str, item: dict[str, Any]) -> str:
    key = artifact_key(runtime.scope.workspace_id, content_address(data))
    if item.get("acquisition_generation", 0) > 0:
        # Only the explicit generation change can renew expired identical bytes. DSAR never can.
        await conn.execute(
            text("""UPDATE artifact SET privacy_erased=false,erasure_reason=NULL,
          erased_at=NULL,purged_at=NULL,expires_at=now()+interval '30 days'
          WHERE workspace_id=:ws AND storage_key=:key AND erasure_reason='retention'"""),
            {"ws": runtime.scope.workspace_id, "key": key},
        )
    await record_artifact(
        conn,
        workspace_id=runtime.scope.workspace_id,
        storage_key=key,
        content_sha256=content_address(data),
        media_type=mime,
        size_bytes=len(data),
    )
    await runtime.storage.put(key, data, media_type=mime)
    return key


async def run_media_summary(conn: Any, *, workspace_id: str, run_id: UUID) -> dict[str, Any]:
    """What one research run did with media: found, attempted, transcribed by method, and why
    the rest failed (spec 2026-10-13-legitimate-media-sources-design §4)."""
    rows = (
        (
            await conn.execute(
                text("""
        SELECT a.kind, a.outcome, a.data, t.source_method
        FROM arv2_media_attempt a
        JOIN arv2_research_job j ON j.job_id=a.job_id AND j.workspace_id=a.workspace_id
        LEFT JOIN arv2_media_transcript t
          ON t.workspace_id=a.workspace_id AND t.version_id=a.version_id
        WHERE a.workspace_id=:ws AND j.run_id=:run
    """),
                {"ws": workspace_id, "run": run_id},
            )
        )
        .mappings()
        .all()
    )
    transcribed: dict[str, int] = {}
    unavailable: dict[str, int] = {}
    discovered = attempted = 0
    for row in rows:
        if row["kind"] == "candidate" and row["outcome"] == "unverified":
            discovered += 1
        if row["kind"] != "read":
            continue
        attempted += 1
        if row["outcome"] in {"acquired", "reused"} and row["source_method"]:
            method = str(row["source_method"])
            transcribed[method] = transcribed.get(method, 0) + 1
        elif row["outcome"] == "unavailable":
            data = row["data"]
            data = json.loads(data) if isinstance(data, str | bytes) else data or {}
            for gap in data.get("gaps", []):
                key = str(gap).split(":", 1)[0]
                unavailable[key] = unavailable.get(key, 0) + 1
    return {
        "discovered": discovered,
        "attempted": attempted,
        "transcribed": transcribed,
        "unavailable": unavailable,
    }
