"""The Jev speaker check on a person job's transcripts: shown to the agent, paid once per job."""

from __future__ import annotations

from dataclasses import replace

import pytest

from clue_api.arv2 import media_store as store
from clue_api.arv2.media_speaker import saved_speaker_check, speaker_check
from clue_api.arv2.media_tools import ReadMediaArgs, read_media
from clue_api.footprint.jev_client import SpeakerCheck
from clue_api.footprint.media_types import Quality, Segment
from clue_research.identity import insert_contact_entity
from tests.arv2.test_media_store_db import MediaClients, recording, seeded
from tests.claimstore.conftest import (  # noqa: F401
    migrated_db,
    require_claimstore_db,
    rollback_conn,
)
from tests.db.conftest import run_async

pytestmark = pytest.mark.usefixtures("require_claimstore_db")

ANSWER = SpeakerCheck(
    state="answered",
    presence="speaking",
    presence_probabilities={"speaking": 0.97},
    is_speaking=0.94,
    label="Speaker 1",
    label_probabilities={"Speaker 0": 0.0, "Speaker 1": 0.89, "none": 0.11},
    windows=1,
    model="typesafe/jev-1.14-20261014",
    cost_usd=0.0005,
)


class SpeakerClients(MediaClients):
    def __init__(self, answer: SpeakerCheck = ANSWER) -> None:
        self.calls: list[dict] = []
        self.answer = answer

    def speaker_check(self, caller, *, person, recording, lines):
        self.calls.append({"person": person, "recording": recording, "lines": lines})
        return self.answer


async def person_runtime(conn, *, name="Ada Example"):
    rt = await seeded(conn)
    contact = await insert_contact_entity(
        conn, account_entity_id=rt.scope.account_id, full_name=name
    )
    rt.scope = replace(
        rt.scope,
        subject_kind="person",
        contact_id=contact,
        person_name=name,
        person_title="CISO",
        employment_history=("CISO, Acme (2021-)",),
    )
    rt.clients = SpeakerClients()
    return rt


async def saved_transcript(rt, conn):
    item, op, _ = await recording(rt, conn)
    text = "Welcome to the show.Thanks, I run security at Acme."
    version = await store.save_transcript(
        rt,
        conn,
        item_id=item["item_id"],
        value=text,
        segments=[
            Segment(start=0, end=20, speaker="Speaker 0", time_s=0.0, timing="source_supplied"),
            Segment(
                start=20, end=len(text), speaker="Speaker 1", time_s=5.0, timing="source_supplied"
            ),
        ],
        quality=Quality(coverage="full"),
        method="deepgram",
        operation_id=op["operation_id"],
    )
    return item, version


def test_person_job_speaker_check_built_from_the_transcript():
    async def scenario():
        async with rollback_conn() as conn:
            rt = await person_runtime(conn)
            _, version = await saved_transcript(rt, conn)
            check = await speaker_check(rt, version)
            assert check is not None and check.label == "Speaker 1"
            call = rt.clients.calls[0]
            assert call["lines"] == [
                "[00:00] Speaker 0: Welcome to the show.",
                "[00:05] Speaker 1: Thanks, I run security at Acme.",
            ]
            assert call["person"]["name"] == "Ada Example"
            assert call["person"]["employment_history"] == ["CISO, Acme (2021-)"]
            assert call["recording"]["source_url"] == "https://example.com/episode/1"
            saved = await saved_speaker_check(
                conn, workspace_id=rt.scope.workspace_id, job_id=rt.scope.job_id, version_id=version
            )
            assert saved and saved["label"] == "Speaker 1"

    run_async(scenario())


def test_the_agents_identity_note_reaches_jev_with_the_person():
    """Founder-approved 2026-11-12: the agent writes what identifies the person (past roles,
    schools, businesses, awards) and Jev reads it as part of person_we_research."""
    note = "Head of Cyber Operations at Citi (2021-2026); chairs the FS-ISAC board"

    async def scenario():
        async with rollback_conn() as conn:
            rt = await person_runtime(conn)
            _, version = await saved_transcript(rt, conn)
            await speaker_check(rt, version, identity_note=note)
            assert rt.clients.calls[0]["person"]["identity_note"] == note
        async with rollback_conn() as conn:
            rt = await person_runtime(conn)
            _, version = await saved_transcript(rt, conn)
            await speaker_check(rt, version)
            assert "identity_note" not in rt.clients.calls[0]["person"]

    run_async(scenario())


def test_speaker_check_paid_once_per_job():
    async def scenario():
        async with rollback_conn() as conn:
            rt = await person_runtime(conn)
            _, version = await saved_transcript(rt, conn)
            await speaker_check(rt, version)
            again = await speaker_check(rt, version)
            assert again.label == "Speaker 1" and len(rt.clients.calls) == 1

    run_async(scenario())


def test_account_job_has_no_speaker_check():
    async def scenario():
        async with rollback_conn() as conn:
            rt = await seeded(conn)
            rt.clients = SpeakerClients()
            _, version = await saved_transcript(rt, conn)
            assert await speaker_check(rt, version) is None and rt.clients.calls == []

    run_async(scenario())


class FlakyClients(SpeakerClients):
    """Jev fails the first ``failures`` times it is asked, then answers."""

    def __init__(self, failures: int) -> None:
        super().__init__()
        self.failures = failures

    def speaker_check(self, caller, *, person, recording, lines):
        self.calls.append({"person": person})
        if len(self.calls) <= self.failures:
            return SpeakerCheck(state="unavailable", reason="ReadTimeout: jev timed out")
        return self.answer


def test_a_failed_check_is_saved_retried_once_then_not_asked_again():
    """Review I13. A failed check used to be asked again on every transcript page, each ask waiting
    up to 300 s twice. It is now saved with its reason; the next read retries once; after that the
    saved failure is shown straight away."""

    async def scenario():
        async with rollback_conn() as conn:
            rt = await person_runtime(conn)
            rt.clients = FlakyClients(failures=99)
            _, version = await saved_transcript(rt, conn)
            first = await speaker_check(rt, version)
            assert first.state == "unavailable" and "timed out" in first.reason
            await speaker_check(rt, version)
            third = await speaker_check(rt, version)
            fourth = await speaker_check(rt, version)
            assert len(rt.clients.calls) == 2
            assert third.state == fourth.state == "unavailable"
            assert "timed out" in fourth.reason

    run_async(scenario())


def test_a_retry_that_answers_is_kept():
    async def scenario():
        async with rollback_conn() as conn:
            rt = await person_runtime(conn)
            rt.clients = FlakyClients(failures=1)
            _, version = await saved_transcript(rt, conn)
            assert (await speaker_check(rt, version)).state == "unavailable"
            assert (await speaker_check(rt, version)).label == "Speaker 1"
            assert (await speaker_check(rt, version)).label == "Speaker 1"
            assert len(rt.clients.calls) == 2

    run_async(scenario())


def test_worker_without_speaker_check_reports_it():
    async def scenario():
        async with rollback_conn() as conn:
            rt = await person_runtime(conn)
            rt.clients = MediaClients()
            _, version = await saved_transcript(rt, conn)
            check = await speaker_check(rt, version)
            assert check.state == "unavailable" and check.reason == "speaker_check_not_configured"

    run_async(scenario())


def test_person_read_media_carries_speaker_check():
    async def scenario():
        import json

        from clue_spend.transport import ScriptedTransport
        from tests.arv2.test_media_store_db import deepgram_speech, embeddings, offline_audio

        async with rollback_conn() as conn:
            rt = await person_runtime(conn)
            wire = ScriptedTransport(
                [offline_audio(), offline_audio(), deepgram_speech("I run security."), embeddings()]
            )
            rt._transport_factory = lambda: wire
            result = await read_media(
                rt,
                ReadMediaArgs(
                    url="https://example.com/talk.mp3",
                    purpose="Hear them",
                    identity_note="CISO at Acme since 2021",
                ),
            )
            assert result["state"] == "available"
            assert result["speaker_check"]["label"] == "Speaker 1"
            assert rt.clients.calls[0]["person"]["identity_note"] == "CISO at Acme since 2021"
            assert list(result).index("speaker_check") < list(result).index("preview")
            assert "speaker check" in result["next_action"].lower()
            assert json.dumps(result)

    run_async(scenario())
