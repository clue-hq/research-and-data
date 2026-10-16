"""Recording acquisition stages with durable ownership and replayable provider receipts."""

from __future__ import annotations

import asyncio
import base64
import json
import math
import shutil
import tempfile
from dataclasses import asdict, replace
from pathlib import Path
from typing import Any, cast
from uuid import UUID

from sqlalchemy import text

from clue_api.arv2 import media_operations as ops
from clue_api.arv2 import media_store as store
from clue_api.arv2.deepgram_media_client import (
    REMOTE_CONTENT_ERROR,
    DeepgramMediaError,
    DeepgramTranscript,
    parameters,
    parse_response,
)
from clue_api.arv2.gemini_media_client import (
    GeminiMediaClient,
    SpeakerContext,
    Transcript,
    detect_loops,
    join_windows,
    sentence_lines,
    youtube_windows,
)
from clue_api.arv2.media_recording import prepare_audio
from clue_api.arv2.media_resolution import Resolution, fetch, resolve, with_feed_transcript
from clue_api.arv2.media_sources import media_keys_of
from clue_api.arv2.media_types import Candidate, Quality, Segment, canonical_text
from clue_storage import read_verified_artifact


def assess_transcript(
    transcript: Transcript | DeepgramTranscript,
) -> tuple[str, list[Segment], Quality]:
    if isinstance(transcript, DeepgramTranscript):
        return transcript.text, list(transcript.segments), transcript.quality
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
        try:
            envelope = json.loads(raw)
        except (ValueError, UnicodeDecodeError):
            continue
        if not isinstance(envelope, dict):
            continue
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


async def resolve_url(runtime: Any, url: str, hint: str | None) -> Resolution:
    """Resolve one link. A page that could not be read (blocked, refused, malformed) is an
    unavailable resolution carrying the reason and the saved responses as its evidence."""
    raw_keys: list[str] = []
    token = ops.active_resolution.set(raw_keys)
    media_keys = media_keys_of(runtime)
    try:
        result = cast(
            Resolution,
            await runtime.call_provider(
                "media_public", lambda caller: resolve(caller, url, hint=hint, keys=media_keys)
            ),
        )
        return replace(result, raw_keys=tuple(raw_keys))
    except ValueError as exc:
        return Resolution("unavailable", gaps=(str(exc),), raw_keys=tuple(raw_keys))
    finally:
        ops.active_resolution.reset(token)


#: The cautious bitrate a recording's size is read at when no feed states its length: few podcasts
#: are encoded below it, so the estimate errs long and the allowance is checked before paying.
ESTIMATE_BITS_PER_SECOND = 64_000


async def estimated_seconds(runtime: Any, url: str) -> int | None:
    """A recording's length from its size alone (one header-only request), or ``None``."""
    try:
        response = await runtime.call_provider(
            "media_public", lambda caller: fetch(caller, url, binary=True, probe=True)
        )
    except ValueError:
        return None
    size = response.headers.get("content-length", "")
    return -(-int(size) * 8 // ESTIMATE_BITS_PER_SECOND) if size.isdigit() and int(size) else None


async def acquire(
    runtime: Any,
    resolution: Resolution,
    *,
    purpose: str,
    repair_version: UUID | None = None,
    upload: bool = False,
) -> dict[str, Any]:
    """``upload`` is the fallback after Deepgram could not fetch the recording's link: fetch it
    ourselves and send the bytes."""
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
    if candidate.family == "youtube" and not resolution.transcript:
        return await _acquire_youtube(
            runtime,
            item=item,
            candidate=candidate,
            resolution=resolution,
            purpose=purpose,
            repair_version=repair_version,
        )
    if not resolution.transcript and (gap := media_lane_gap(runtime)):
        async with runtime._conn_factory() as conn:
            await store.release_item(runtime, conn, item["item_id"])
        return {"state": "unavailable", "gap": gap}
    language = runtime.settings.arv2_deepgram_language
    request = {
        "recipe": "deepgram-transcript-v1"
        if not resolution.transcript
        else "publisher-transcript-v1",
        "repair": str(repair_version) if repair_version else None,
        "parameters": parameters(language) if not resolution.transcript else {},
    }
    duration = candidate.duration_s
    audio = None
    prepared = None
    expected_hash = None
    # Founder ruling 2026-10-16: an audio file is transcribed from its own link and never
    # downloaded, when its length is known (the feed's, or estimated from its size) so the
    # allowance is checked before paying. Deepgram's checksum, request id and measured duration
    # are the proof. Video, an unknown length, or a link Deepgram cannot fetch is downloaded.
    link = None
    if (
        not (resolution.transcript or upload)
        and candidate.media_url
        and candidate.family == "audio"
    ):
        if not duration:
            # A size says little about a length (podcasts run 32 to 320 kbit/s): the cautious
            # estimate may only skip a download, never refuse a recording. One it does not
            # clearly fit is downloaded and measured exactly, as before link-first.
            estimate = await estimated_seconds(runtime, candidate.media_url)
            async with runtime._conn_factory() as conn:
                used = await ops.used_seconds(runtime, conn)
            ceiling = runtime.settings.arv2_media_seconds_ceiling
            duration = estimate if estimate and used + estimate <= ceiling else None
        if duration:
            link = candidate.media_url
            request.update(delivery="url", source_url=link)
    with tempfile.TemporaryDirectory(prefix="arv2-media-") as directory:
        if not resolution.transcript and candidate.media_url and link is None:
            # Founder ruling 2026-10-16: a download is transcription input only. It lives in this
            # temporary folder, which is deleted when this block ends, whatever happens; its raw
            # record keeps a hash and size, never the bytes; nothing of it reaches storage. A
            # retry after a failure therefore downloads it again.
            async with runtime._conn_factory() as conn:
                download, won = await ops.begin(
                    runtime,
                    conn,
                    item_id=item["item_id"],
                    stage="download",
                    request={"url": candidate.media_url or candidate.url},
                )
            if not won and download["state"] != "succeeded":
                return {
                    "state": download["state"],
                    "operation_ref": str(download["operation_id"]),
                    "gap": "download_not_ready",
                }
            media_url = candidate.media_url

            def get(caller: Any) -> Any:
                return fetch(caller, media_url, binary=True, keep_body=False)

            response = await (
                ops.call(runtime, download, "media_public", get)
                if won
                else runtime.call_provider("media_public", get)
            )
            mime = response.headers.get("content-type", "").split(";")[0].lower()
            if not mime.startswith(("audio/", "video/")):
                async with runtime._conn_factory() as conn:
                    if won:
                        await ops.finish(
                            runtime,
                            conn,
                            download,
                            error="unsupported_media_mime",
                            known_failure=True,
                        )
                    await store.release_item(runtime, conn, item["item_id"])
                return {"state": "unavailable", "gap": "unsupported_media_mime"}
            path = Path(directory) / "recording"
            path.write_bytes(response.body)
            if won:
                async with runtime._conn_factory() as conn:
                    await ops.finish(
                        runtime,
                        conn,
                        download,
                        result={"mime": mime, "bytes": len(response.body)},
                    )
            audio, prepared = await asyncio.to_thread(prepare_audio, path)
            duration = prepared["duration_s"]
            expected_hash = prepared["audio_sha256"]
            # The step is known by the downloaded file's hash: a retry re-downloads the same
            # bytes, while the speech audio cut from them need not come out byte-identical.
            request.update(
                input_sha256=prepared["original_sha256"],
                delivery="upload",
                preparation=prepared["preparation"],
            )
        if not resolution.transcript and link is None and (audio is None or not duration):
            async with runtime._conn_factory() as conn:
                await store.release_item(runtime, conn, item["item_id"])
            return {"state": "unavailable", "gap": "recording_audio_unavailable"}
        async with runtime._conn_factory() as conn:
            op, won = await ops.begin(
                runtime,
                conn,
                item_id=item["item_id"],
                stage="transcribe",
                request=request,
                seconds=0 if resolution.transcript else duration or 0,
            )
        if not won and link is not None and op["state"] == "failed":
            # An earlier read sent this link and Deepgram refused it outright (heard nothing,
            # billed nothing): fetch the recording ourselves rather than send the link again.
            return await acquire(
                runtime, resolution, purpose=purpose, repair_version=repair_version, upload=True
            )
        transcript: Transcript | DeepgramTranscript | None = None
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
                if "results" in body:
                    transcript = parse_response(body, expected_hash=expected_hash)
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
        elif link is not None or (audio is not None and prepared is not None):
            names = (runtime.scope.account_name, runtime.scope.person_name)
            keyterms = tuple(dict.fromkeys(n.strip() for n in names if n and n.strip()))
            sent = link
            try:
                transcript = await ops.call(
                    runtime,
                    op,
                    "deepgram",
                    lambda caller: runtime.clients.transcription(caller).transcribe(
                        audio=b"" if sent else audio.read_bytes(),
                        mime=prepared["mime"] if prepared else "audio/mpeg",
                        duration_s=duration,
                        expected_hash=expected_hash,
                        media_url=sent,
                        keyterms=keyterms,
                    ),
                )
            except DeepgramMediaError as exc:
                # Deepgram heard nothing (its 400, already recorded as a failed, released step);
                # fetch the recording ourselves. A server error or timeout is never retried.
                if link is None or exc.err_code != REMOTE_CONTENT_ERROR:
                    raise
                return await acquire(
                    runtime, resolution, purpose=purpose, repair_version=repair_version, upload=True
                )
            if link is not None and isinstance(transcript, DeepgramTranscript):
                measured = transcript.quality.diagnostics.get("metadata", {}).get("duration")
                if isinstance(measured, int | float) and measured > 0:
                    async with runtime._conn_factory() as conn:
                        await ops.settle_seconds(runtime, conn, op, math.ceil(measured))
        if transcript is None:
            raise store.unavailable("unsupported acquisition route")
        return await _save_transcript(
            runtime,
            op=op,
            item=item,
            candidate=candidate,
            resolution=resolution,
            transcript=transcript,
            request=request,
            purpose=purpose,
            repair_version=repair_version,
            method="publisher_transcript" if resolution.transcript else candidate.family,
        )


async def _save_transcript(
    runtime: Any,
    *,
    op: dict[str, Any],
    item: dict[str, Any],
    candidate: Candidate,
    resolution: Resolution,
    transcript: Transcript | DeepgramTranscript,
    request: dict[str, Any],
    purpose: str,
    repair_version: UUID | None,
    method: str,
) -> dict[str, Any]:
    """Assess, save and index-ready a paid or published transcript, and record the read."""
    value, segments, quality = assess_transcript(transcript)
    if resolution.transcript:
        # Only actual publisher caption cues carry source-supplied timing.
        segments = list(resolution.segments) or segments
    async with runtime._conn_factory() as conn:
        if not value.strip():
            # Paid processing still consumed seconds even when no speech was returned.
            await ops.finish(
                runtime, conn, op, result={"empty_transcript": True, "acquisition": request}
            )
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
            method=method,
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
                "acquisition": request,
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


def media_lane_gap(runtime: Any) -> str | None:
    """What this worker lacks to transcribe a recording, named, or ``None`` (spec §4)."""
    missing = [tool for tool in ("ffprobe", "ffmpeg") if shutil.which(tool) is None]
    if not getattr(runtime.clients, "transcription_ready", True):
        missing.append("Deepgram key")
    return f"media_lane_unavailable_on_worker: {', '.join(missing)} missing" if missing else None


async def attach_feed_transcript(runtime: Any, resolution: Resolution) -> Resolution:
    """A chosen feed episode still gets its publisher transcript before any audio is bought."""
    candidate = resolution.candidates[0] if resolution.candidates else None
    if candidate is None or not candidate.transcript_url or resolution.transcript:
        return resolution
    return cast(
        Resolution,
        await runtime.call_provider(
            "media_public", lambda caller: with_feed_transcript(caller, resolution)
        ),
    )


def video_details(candidate: Candidate) -> dict[str, Any]:
    """What the agent learns about a video it could not get words from."""
    return {
        "title": candidate.title,
        "published_at": candidate.published_at.isoformat() if candidate.published_at else None,
        "duration_s": candidate.duration_s,
        "description": candidate.description[:1200],
        "url": candidate.url,
    }


async def _acquire_youtube(
    runtime: Any,
    *,
    item: dict[str, Any],
    candidate: Candidate,
    resolution: Resolution,
    purpose: str,
    repair_version: UUID | None,
) -> dict[str, Any]:
    """Spec §3 step 3: Gemini reads the public link in windows; nothing is downloaded."""
    if not runtime.settings.arv2_media_youtube_gemini_enabled:
        async with runtime._conn_factory() as conn:
            await store.release_item(runtime, conn, item["item_id"])
        return {
            "state": "unavailable",
            "gap": "youtube_transcription_disabled",
            "video": video_details(candidate),
        }
    duration = candidate.duration_s or 0
    budget = runtime.media_budget
    if duration <= 0 or budget.used_s + duration > budget.ceiling_s:
        # Refused before any window is paid, never cut off after the first one.
        async with runtime._conn_factory() as conn:
            await store.release_item(runtime, conn, item["item_id"])
        return {
            "state": "unavailable",
            "gap": "media_budget_exhausted" if duration > 0 else "duration_unknown",
            "video": video_details(candidate),
        }
    windows = youtube_windows(duration, runtime.settings.arv2_media_gemini_window_seconds)
    request: dict[str, Any] = {
        "recipe": "gemini-youtube-v1",
        "model": runtime.settings.arv2_media_video_model,
        "windows": windows,
        "repair": str(repair_version) if repair_version else None,
    }
    async with runtime._conn_factory() as conn:
        op, won = await ops.begin(
            runtime,
            conn,
            item_id=item["item_id"],
            stage="transcribe",
            request=request,
            seconds=duration,
        )
    if not won:
        if op["state"] == "succeeded" and op["result"].get("version_ref"):
            async with runtime._conn_factory() as conn:
                await store.consume_reused_item(runtime, conn, item["item_id"])
                saved = await store.load_transcript(
                    runtime, conn, UUID(op["result"]["version_ref"])
                )
            return receipt(saved, reused=True)
        # Every window was paid but the transcript was never saved: rebuild it from the saved
        # responses, as the Deepgram route does. A window that was never answered is an unknown
        # outcome and is not bought again.
        async with runtime._conn_factory() as conn:
            bodies = [b for b in await raw_responses(runtime, conn, op) if "candidates" in b]
        if len(bodies) == len(windows):
            model = runtime.settings.arv2_media_video_model
            recovered = join_windows(
                [
                    (
                        start,
                        GeminiMediaClient.parse_native_recording(
                            body, model=model, structured=True
                        ),
                    )
                    for (start, _), body in zip(windows, bodies, strict=True)
                ]
            )
            return await _save_transcript(
                runtime,
                op=op,
                item=item,
                candidate=candidate,
                resolution=resolution,
                transcript=recovered,
                request=request,
                purpose=purpose,
                repair_version=repair_version,
                method="gemini_youtube",
            )
        return {
            "state": op["state"],
            "operation_ref": str(op["operation_id"]),
            "gap": "acquisition_not_ready_no_automatic_repurchase",
        }
    person = runtime.scope.person_name or ""
    context = SpeakerContext(
        person_name=person,
        person_role=runtime.scope.person_title or "",
        organisation=runtime.scope.account_name or "",
        named_in_metadata=bool(person)
        and person.casefold() in f"{candidate.title} {candidate.description}".casefold(),
    )

    def hop(caller: Any) -> Transcript:
        client = runtime.clients.media(caller, runtime.ledger_of(caller))
        return join_windows(
            [
                (
                    start,
                    client.transcribe_video(
                        candidate.url,
                        duration_s=end - start,
                        start_s=start,
                        end_s=end,
                        context=context,
                    ),
                )
                for start, end in windows
            ]
        )

    transcript = await ops.call(runtime, op, "gemini", hop)
    return await _save_transcript(
        runtime,
        op=op,
        item=item,
        candidate=candidate,
        resolution=resolution,
        transcript=transcript,
        request=request,
        purpose=purpose,
        repair_version=repair_version,
        method="gemini_youtube",
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
