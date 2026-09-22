"""Recording acquisition stages with durable ownership and replayable provider receipts."""

from __future__ import annotations

import base64
import json
import math
import subprocess
import tempfile
from dataclasses import asdict, replace
from pathlib import Path
from typing import Any, cast
from uuid import UUID

from sqlalchemy import text

from clue_api.arv2 import media_operations as ops
from clue_api.arv2 import media_store as store
from clue_api.arv2.gemini_media_client import (
    AudioFile,
    GeminiMediaClient,
    SpeakerContext,
    Transcript,
    detect_loops,
    sentence_lines,
)
from clue_api.arv2.media_resolution import Resolution, fetch, resolve
from clue_api.arv2.media_types import Quality, Segment, canonical_text
from clue_storage import read_verified_artifact


def assess_transcript(transcript: Transcript) -> tuple[str, list[Segment], Quality]:
    value = canonical_text(transcript.text)
    loops = detect_loops(
        transcript
        if transcript.lines
        else Transcript(model=transcript.model, text=value, lines=sentence_lines(value))
    )
    warnings = []
    if loops.tripped:
        warnings.append("repetition_detected")
    if not value.strip():
        warnings.append("empty_transcript")
    truncated = transcript.finish_reason not in {None, "STOP", "stop"}
    if truncated:
        warnings.append("provider_incomplete")
    segments = []
    cursor = 0
    for line in transcript.lines:
        found = value.find(line.text, cursor)
        if found < 0:
            continue
        if found > cursor:
            segments.append(Segment(start=cursor, end=found))
        end = found + len(line.text)
        if end > found:
            segments.append(
                Segment(
                    start=found,
                    end=end,
                    speaker=line.speaker or None,
                    attribution="model_inferred" if line.speaker else "unknown",
                    time_s=line.ts_s,
                    timing="model_estimated" if line.ts_s is not None else "unavailable",
                )
            )
        cursor = end
    if cursor < len(value):
        segments.append(Segment(start=cursor, end=len(value)))
    # A clean loop test and a normal provider finish do not prove ASR completeness.
    return (
        value,
        segments,
        Quality(
            coverage="partial" if truncated else "unknown",
            warnings=warnings,
            finish_reason=transcript.finish_reason,
            loop_report=asdict(loops),
        ),
    )


async def raw_responses(runtime: Any, conn: Any, operation: dict[str, Any]) -> list[dict[str, Any]]:
    row = (
        await conn.execute(
            text(
                "SELECT artifact_keys FROM arv2_media_operation WHERE workspace_id=:ws "
                "AND operation_id=:id"
            ),
            {"ws": runtime.scope.workspace_id, "id": operation["operation_id"]},
        )
    ).one()
    responses = []
    for key in row.artifact_keys:
        _, raw = await read_verified_artifact(
            conn, runtime.storage, storage_key=key, workspace_id=runtime.scope.workspace_id
        )
        envelope = json.loads(raw)
        record = envelope.get("record", {})
        status = record.get("response", {}).get("status")
        if status and 200 <= status < 300:
            data = envelope.get("body_utf8")
            if data is None:
                data = base64.b64decode(envelope.get("body_base64") or "").decode(
                    "utf-8", errors="replace"
                )
            try:
                body = json.loads(data)
            except ValueError:
                continue
            if isinstance(body, dict):
                responses.append(body)
    return responses


def duration_of(path: Path) -> int | None:
    try:
        result = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "json",
                str(path),
            ],
            capture_output=True,
            text=True,
            timeout=20,
            check=True,
        )
        duration = float(json.loads(result.stdout)["format"]["duration"])
        return math.ceil(duration) if math.isfinite(duration) and duration > 0 else None
    except (OSError, ValueError, KeyError, subprocess.SubprocessError):
        return None


async def recover_upload(runtime: Any, operation: dict[str, Any]) -> str | None:
    async with runtime._conn_factory() as conn:
        bodies = await raw_responses(runtime, conn, operation)
    for body in reversed(bodies):
        file = body.get("file", body)
        if not isinstance(file, dict) or not file.get("name"):
            continue
        if file.get("state") == "ACTIVE" and isinstance(file.get("uri"), str):
            uri = file["uri"]
        else:
            async with runtime._conn_factory() as conn:
                poll, won = await ops.begin(
                    runtime,
                    conn,
                    item_id=operation["item_id"],
                    stage="upload_readiness",
                    request={"file_name": file["name"]},
                )
            if won:
                uri = await ops.call(
                    runtime,
                    poll,
                    "gemini",
                    lambda caller, name=file["name"]: runtime.clients.media(
                        caller, runtime.ledger_of(caller)
                    ).resume_uploaded_file(name),
                )
                async with runtime._conn_factory() as conn:
                    await ops.finish(runtime, conn, poll, result={"uri": uri})
            elif poll["state"] == "succeeded":
                uri = poll["result"]["uri"]
            else:
                return None
        async with runtime._conn_factory() as conn:
            await ops.finish(runtime, conn, operation, result={"uri": uri})
        return str(uri)
    return None


async def resolve_url(runtime: Any, url: str, hint: str | None) -> Resolution:
    keys: list[str] = []
    token = ops.active_resolution.set(keys)
    try:
        result = cast(
            Resolution,
            await runtime.call_provider(
                "media_public", lambda caller: resolve(caller, url, hint=hint)
            ),
        )
        return replace(result, raw_keys=tuple(keys))
    finally:
        ops.active_resolution.reset(token)


async def acquire(
    runtime: Any, resolution: Resolution, *, purpose: str, repair_version: UUID | None = None
) -> dict[str, Any]:
    candidate = resolution.candidates[0]
    async with runtime._conn_factory() as conn:
        item = await store.item_for(runtime, conn, candidate)
        await store.link_aliases(
            runtime,
            conn,
            item["item_id"],
            tuple(
                dict.fromkeys(
                    url
                    for url in (
                        *resolution.aliases,
                        candidate.url,
                        candidate.media_url,
                        candidate.transcript_url,
                    )
                    if url
                )
            ),
            evidence_key=resolution.raw_keys[0] if resolution.raw_keys else None,
        )
        if resolution.raw_keys:
            source_op, source_won = await ops.begin(
                runtime,
                conn,
                item_id=item["item_id"],
                stage="resolution",
                request={"source": candidate.url},
            )
            await conn.execute(
                text("""UPDATE arv2_media_operation SET artifact_keys=
              artifact_keys || CAST(:keys AS text[]) WHERE workspace_id=:ws AND
        operation_id=:id"""),
                {
                    "ws": runtime.scope.workspace_id,
                    "id": source_op["operation_id"],
                    "keys": list(resolution.raw_keys),
                },
            )
            for key in resolution.raw_keys:
                await store.subjects(
                    runtime,
                    conn,
                    key,
                    [("linkedin:" + url, url) for url in candidate.recognized_subject_urls],
                )
            if source_won:
                await ops.finish(runtime, conn, source_op, result={"resolved": True})

        await store.bind_item(runtime, conn, item["item_id"], purpose)
        if item["current_version"] and repair_version is None:
            await store.consume_reused_item(runtime, conn, item["item_id"])
            saved = await store.load_transcript(runtime, conn, item["current_version"])
            await store.attempt(
                runtime,
                conn,
                kind="read",
                outcome="reused",
                purpose=purpose,
                item_id=item["item_id"],
                version_id=item["current_version"],
            )
            return receipt(saved, reused=True)
        if repair_version:
            previous = await store.load_transcript(runtime, conn, repair_version)
            if previous["item_id"] != item["item_id"] or previous["superseded"]:
                raise store.unavailable(
                    "repair reference must be the current version of this recording"
                )
    context = SpeakerContext(
        person_name=runtime.scope.person_name,
        person_role=runtime.scope.person_title,
        organisation=runtime.scope.account_name,
    )
    request = {
        "recipe": "transcript-v1",
        "repair": str(repair_version) if repair_version else None,
        "model": runtime.settings.arv2_media_video_model
        if candidate.family in {"youtube", "video"}
        else runtime.settings.arv2_media_transcribe_model,
    }
    duration = candidate.duration_s
    audio = None
    with tempfile.TemporaryDirectory(prefix="arv2-media-") as directory:
        if candidate.media_url and not resolution.transcript:
            # Download is independently journalled and retained as an artifact for repairs.
            async with runtime._conn_factory() as conn:
                download, won = await ops.begin(
                    runtime,
                    conn,
                    item_id=item["item_id"],
                    stage="download",
                    request={"url": candidate.media_url},
                )
            if won:
                response = await ops.call(
                    runtime,
                    download,
                    "media_public",
                    lambda caller: fetch(caller, candidate.media_url, binary=True),
                )
                mime = response.headers.get("content-type", "").split(";")[0].lower()
                if not mime.startswith(("audio/", "video/")):
                    async with runtime._conn_factory() as conn:
                        await ops.finish(
                            runtime,
                            conn,
                            download,
                            error="unsupported_media_mime",
                            known_failure=True,
                        )
                        await store.release_item(runtime, conn, item["item_id"])
                    return {"state": "unavailable", "gap": "unsupported_media_mime"}
                blob = await runtime._artifacts.persist_body(
                    workspace_id=runtime.scope.workspace_id, data=response.body, media_type=mime
                )
                async with runtime._conn_factory() as conn:
                    await store.subjects(runtime, conn, blob.artifact_key, [])
                    await conn.execute(
                        text(
                            "UPDATE arv2_media_operation SET "
                            "artifact_keys=array_append(artifact_keys,:key) WHERE workspace_id=:ws "
                            "AND operation_id=:id"
                        ),
                        {
                            "ws": runtime.scope.workspace_id,
                            "id": download["operation_id"],
                            "key": blob.artifact_key,
                        },
                    )
                    await ops.finish(
                        runtime, conn, download, result={"blob": blob.artifact_key, "mime": mime}
                    )
                download["result"] = {"blob": blob.artifact_key, "mime": mime}
                download["state"] = "succeeded"
            if download["state"] != "succeeded":
                return {
                    "state": download["state"],
                    "operation_ref": str(download["operation_id"]),
                    "gap": "download_not_ready",
                }
            async with runtime._conn_factory() as conn:
                _, data = await read_verified_artifact(
                    conn,
                    runtime.storage,
                    workspace_id=runtime.scope.workspace_id,
                    storage_key=download["result"]["blob"],
                )
            path = Path(directory) / "recording"
            path.write_bytes(data)
            duration = duration or duration_of(path)
            mime = download["result"]["mime"]
            if duration:
                audio = AudioFile(
                    path=path,
                    duration_s=duration,
                    mime_type=mime,
                    audio_format={
                        "audio/mpeg": "mp3",
                        "audio/mp4": "m4a",
                        "audio/wav": "wav",
                        "audio/ogg": "ogg",
                        "audio/flac": "flac",
                    }.get(mime, ""),
                    display_name="research-recording",
                )
        if not resolution.transcript and not duration:
            async with runtime._conn_factory() as conn:
                await store.release_item(runtime, conn, item["item_id"])
                await store.attempt(
                    runtime,
                    conn,
                    kind="read",
                    outcome="duration_unknown",
                    item_id=item["item_id"],
                    purpose=purpose,
                )
            return {"state": "unavailable", "gap": "duration_unknown"}
        short_audio = bool(
            audio
            and audio.mime_type.startswith("audio/")
            and duration <= runtime.settings.arv2_media_short_max_seconds
            and not repair_version
            and audio.audio_format
        )
        uri = None
        if short_audio:
            request["model"] = runtime.settings.arv2_media_short_model
        if audio is not None and not short_audio:
            async with runtime._conn_factory() as conn:
                upload, upload_won = await ops.begin(
                    runtime,
                    conn,
                    item_id=item["item_id"],
                    stage="upload",
                    request={"blob": download["result"]["blob"]},
                )
            if upload_won:
                uri = await ops.call(
                    runtime,
                    upload,
                    "gemini",
                    lambda caller: runtime.clients.media(
                        caller, runtime.ledger_of(caller)
                    ).upload_recording(audio),
                )
                async with runtime._conn_factory() as conn:
                    await ops.finish(runtime, conn, upload, result={"uri": uri})
            elif upload["state"] == "succeeded":
                uri = upload["result"]["uri"]
            else:
                uri = await recover_upload(runtime, upload)
                if uri is None:
                    return {
                        "state": upload["state"],
                        "gap": "upload_not_ready",
                        "operation_ref": str(upload["operation_id"]),
                    }
        async with runtime._conn_factory() as conn:
            op, won = await ops.begin(
                runtime,
                conn,
                item_id=item["item_id"],
                stage="transcribe",
                request=request,
                seconds=0 if resolution.transcript else duration or 0,
            )
        transcript = None
        if not won:
            if op["result"].get("empty_transcript"):
                async with runtime._conn_factory() as conn:
                    await store.release_item(runtime, conn, item["item_id"])
                return {"state": "empty", "gap": "empty_transcript"}
            if op["state"] == "succeeded" and op["result"].get("version_ref"):
                async with runtime._conn_factory() as conn:
                    await store.consume_reused_item(runtime, conn, item["item_id"])
                    saved = await store.load_transcript(
                        runtime, conn, UUID(op["result"]["version_ref"])
                    )
                return receipt(saved, reused=True)
            # Recover a saved paid response; never repeat ambiguous dispatch to obtain one.
            async with runtime._conn_factory() as conn:
                bodies = await raw_responses(runtime, conn, op)
            for body in reversed(bodies):
                if "candidates" in body:
                    transcript = GeminiMediaClient.parse_native_recording(
                        body,
                        model=request["model"],
                        structured=candidate.family == "youtube" or candidate.family == "video",
                    )
                    break
                if "choices" in body:
                    transcript = GeminiMediaClient.parse_openrouter_recording(
                        body,
                        model=runtime.settings.arv2_media_short_model,
                    )
                    break
            if transcript is None:
                return {
                    "state": op["state"],
                    "operation_ref": str(op["operation_id"]),
                    "gap": "acquisition_not_ready_no_automatic_repurchase",
                }
        elif resolution.transcript:
            transcript = Transcript(
                model="publisher",
                text=resolution.transcript,
                lines=sentence_lines(resolution.transcript),
            )
        elif candidate.family == "youtube":
            transcript = await ops.call(
                runtime,
                op,
                "gemini",
                lambda caller: runtime.clients.media(
                    caller, runtime.ledger_of(caller)
                ).transcribe_video(candidate.url, duration_s=duration, context=context),
            )
        elif audio is not None:
            if short_audio:
                transcript = await ops.call(
                    runtime,
                    op,
                    "openrouter",
                    lambda caller: runtime.clients.media(
                        caller, runtime.ledger_of(caller)
                    ).transcribe_short(
                        audio, context=context, max_attempts=1, require_transcript_section=True
                    ),
                )
            else:
                transcript = await ops.call(
                    runtime,
                    op,
                    "gemini",
                    lambda caller: runtime.clients.media(
                        caller, runtime.ledger_of(caller)
                    ).transcribe_uploaded(
                        uri,
                        mime_type=audio.mime_type,
                        duration_s=duration,
                        context=context,
                        video=audio.mime_type.startswith("video/"),
                    ),
                )
        if transcript is None:
            raise store.unavailable("unsupported acquisition route")
        value, segments, quality = assess_transcript(transcript)
        if resolution.transcript:
            # Only actual publisher caption cues carry source-supplied timing.
            segments = list(resolution.segments) or segments
        async with runtime._conn_factory() as conn:
            if not value.strip():
                # Paid processing still consumed seconds even when no speech was returned.
                await ops.finish(runtime, conn, op, result={"empty_transcript": True})
                await store.release_item(runtime, conn, item["item_id"])
                await store.attempt(
                    runtime,
                    conn,
                    kind="read",
                    outcome="empty_transcript",
                    item_id=item["item_id"],
                    purpose=purpose,
                )
                return {"state": "empty", "gap": "empty_transcript"}
            version = await store.save_transcript(
                runtime,
                conn,
                item_id=item["item_id"],
                value=value,
                segments=segments,
                quality=quality,
                method="publisher_transcript" if resolution.transcript else candidate.family,
                operation_id=op["operation_id"],
                supersedes=repair_version,
                recognized=[("linkedin:" + url, url) for url in candidate.recognized_subject_urls],
            )
            await ops.finish(
                runtime,
                conn,
                op,
                result={
                    "version_ref": str(version),
                    "quotes": [{**asdict(q), "usable": False} for q in transcript.quotes],
                },
            )
            await store.attempt(
                runtime,
                conn,
                kind="read",
                outcome="acquired",
                item_id=item["item_id"],
                version_id=version,
                purpose=purpose,
            )
            saved = await store.load_transcript(runtime, conn, version)
        return receipt(
            saved, reused=False, quotes=[{**asdict(q), "usable": False} for q in transcript.quotes]
        )


def receipt(
    saved: dict[str, Any], *, reused: bool, quotes: list[dict[str, Any]] | None = None
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "state": "available",
        "item_ref": str(saved["item_id"]),
        "version_ref": str(saved["version_id"]),
        "source_url": saved["source_url"],
        "title": saved["title"][:500],
        "quality": saved["quality"],
        "char_count": saved["char_count"],
        "preview": saved["text"][:1200],
        "next_offset": 1200 if saved["char_count"] > 1200 else None,
        "reused": reused,
        "quotes": [
            {
                **q,
                "text": q["text"][:300],
                "why": q.get("why", "")[:200],
                "topic": (q.get("topic") or "")[:100],
                "quote_index": index,
                "text_truncated": len(q["text"]) > 300,
            }
            for index, q in enumerate((quotes or saved.get("quotes", []))[:6])
        ],
        "quote_count": len(quotes or saved.get("quotes", [])),
        "superseded": saved["superseded"],
        "attribution": "inspect_passage",
        "timing": "inspect_passage",
    }
    while len(json.dumps(result, ensure_ascii=False).encode()) > 11_000:
        if result["quotes"]:
            result["quotes"].pop()
        else:
            result["preview"] = result["preview"][: len(result["preview"]) // 2]
            result["next_offset"] = len(result["preview"])
            result["title"] = result["title"][:200]
            result["source_url"] = result["source_url"][:2048]
            if not result["preview"]:
                break
    result["next_quote_index"] = (
        len(result["quotes"]) if len(result["quotes"]) < result["quote_count"] else None
    )
    return result
