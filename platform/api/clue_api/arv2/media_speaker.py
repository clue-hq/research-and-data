"""The speaker check on a person job's transcript, saved once per (job, transcript version).

After a recording is transcribed for a person job, Jev is asked which speaker label is the person
(``clue_api.footprint.jev_client``). The answer is saved as an ``arv2_media_attempt`` row of kind
``speaker_check`` so the job pays for it once, and is shown to the agent at the top of the
transcript. It is a model's judgement for the agent to weigh: nothing in code gates on it
(founder rulings 2026-11-09). A failed check is not saved, so a later read asks again.
"""

from __future__ import annotations

import json
import re
from typing import Any
from uuid import UUID

from sqlalchemy import text

from clue_api.arv2 import media_store as store
from clue_api.arv2.account_research_refusals import RefusalError
from clue_api.footprint.jev_client import SpeakerCheck

SPEAKER_CHECK_KIND = "speaker_check"
#: The item metadata worth giving Jev as "what we know about the recording".
#: The text between two transcript lines: the next line's ``[mm:ss] Label:`` prefix and nothing
#: spoken. Sent as its own line it became ``[00:00] Unlabelled: [00:27] S2 (Ann …):`` (r44a).
_LINE_PREFIX_ONLY = re.compile(r"^\[\d{1,2}:\d{2}(?::\d{2})?\][^\n]{0,64}:$")
_RECORDING_KEYS = ("show", "channel", "description", "published_at", "duration_s", "family")


async def saved_speaker_check(
    conn: Any, *, workspace_id: str, job_id: UUID, version_id: UUID
) -> dict[str, Any] | None:
    row = (
        await conn.execute(
            text("""SELECT data FROM arv2_media_attempt
        WHERE workspace_id=:ws AND job_id=:job AND version_id=:version AND kind=:kind
        ORDER BY created_at DESC LIMIT 1"""),
            {"ws": workspace_id, "job": job_id, "version": version_id, "kind": SPEAKER_CHECK_KIND},
        )
    ).scalar_one_or_none()
    if row is None:
        return None
    return row if isinstance(row, dict) else json.loads(row)


def _clock(seconds: float | None) -> str:
    total = int(seconds or 0)
    return (
        f"{total // 3600:d}:{total % 3600 // 60:02d}:{total % 60:02d}"
        if total >= 3600
        else (f"{total // 60:02d}:{total % 60:02d}")
    )


def diarised_lines(saved: dict[str, Any]) -> list[str]:
    value = saved["text"]
    lines = []
    for segment in saved["segments"]:
        words = value[segment.start : segment.end].strip()
        if not words or (segment.speaker is None and _LINE_PREFIX_ONLY.match(words)):
            continue
        lines.append(f"[{_clock(segment.time_s)}] {segment.speaker or 'Unlabelled'}: {words}")
    return lines


def _person(scope: Any, identity_note: str | None = None) -> dict[str, Any]:
    person: dict[str, Any] = {
        "name": scope.person_name,
        "title": scope.person_title,
        "employer": scope.account_name,
        "linkedin_url": scope.person_linkedin_url or None,
        "employment_history": list(scope.employment_history),
    }
    if identity_note:
        # What the agent's research found identifies them: past roles, schools, businesses,
        # awards (founder-approved 2026-11-12). Without it a recording from an earlier job read
        # as a namesake in r44a.
        person["identity_note"] = identity_note
    return person


async def _recording(conn: Any, workspace_id: str, saved: dict[str, Any]) -> dict[str, Any]:
    metadata = (
        await conn.execute(
            text("SELECT metadata FROM arv2_media_item WHERE workspace_id=:ws AND item_id=:item"),
            {"ws": workspace_id, "item": saved["item_id"]},
        )
    ).scalar_one_or_none() or {}
    if isinstance(metadata, str):
        metadata = json.loads(metadata)
    return {
        "title": saved.get("title"),
        "source_url": saved.get("source_url"),
        **{k: metadata[k] for k in _RECORDING_KEYS if isinstance(metadata, dict) and k in metadata},
    }


async def speaker_check(
    runtime: Any, version_ref: UUID, *, identity_note: str | None = None
) -> SpeakerCheck | None:
    """The saved or freshly asked check for a person job; ``None`` on an account job."""
    scope = runtime.scope
    if scope.person_subject_id is None:
        return None
    async with runtime._conn_factory() as conn:
        saved_check = await saved_speaker_check(
            conn, workspace_id=scope.workspace_id, job_id=scope.job_id, version_id=version_ref
        )
        if saved_check is not None:
            return SpeakerCheck.model_validate(saved_check)
        ask = getattr(runtime.clients, "speaker_check", None)
        if ask is None:
            return SpeakerCheck(state="unavailable", reason="speaker_check_not_configured")
        saved = await store.load_transcript(runtime, conn, version_ref)
        recording = await _recording(conn, scope.workspace_id, saved)
    lines = diarised_lines(saved)
    person = _person(scope, identity_note)
    try:
        check: SpeakerCheck = await runtime.call_provider(
            "openrouter",
            lambda caller: ask(caller, person=person, recording=recording, lines=lines),
        )
    except RefusalError as exc:
        return SpeakerCheck(state="unavailable", reason=f"provider_halted: {exc}"[:300])
    if check.state == "answered":
        async with runtime._conn_factory() as conn:
            await store.attempt(
                runtime,
                conn,
                kind=SPEAKER_CHECK_KIND,
                outcome="answered",
                purpose="speaker check",
                item_id=saved["item_id"],
                version_id=version_ref,
                data=check.model_dump(mode="json"),
            )
    return check
