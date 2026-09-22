"""Real Postgres media evidence/replay/privacy contracts. All provider inputs are offline."""

from dataclasses import replace
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text

from clue_api.arv2 import media_operations as ops
from clue_api.arv2 import media_store as store
from clue_api.arv2.account_research_refusals import RefusalError
from clue_api.arv2.media_types import Candidate, Quality, Segment
from clue_api.arv2.transport import HttpResponse, ScriptedTransport
from tests.api.test_stage0_setup_db import _MemoryStorage
from tests.arv2.test_committee_discovery_v2_db import runtime
from tests.arv2.test_committee_step_db import _scope, _seed
from tests.claimstore.conftest import (  # noqa: F401
    migrated_db,
    require_claimstore_db,
    rollback_conn,
)
from tests.db.conftest import run_async

pytestmark = pytest.mark.usefixtures("require_claimstore_db")


async def seeded(conn):
    run, account, job_id = await _seed(conn)
    scope = replace(_scope(run, account), job_id=job_id, catalog_version="v3")
    return runtime(conn, scope, _MemoryStorage(), ScriptedTransport([]))


async def recording(rt, conn):
    item = await store.item_for(
        rt, conn, Candidate(url="https://example.com/episode/1", canonical_key="test:one")
    )
    await store.bind_item(rt, conn, item["item_id"], "test evidence")
    op, won = await ops.begin(
        rt,
        conn,
        item_id=item["item_id"],
        stage="transcribe",
        request={"recipe": "test"},
        seconds=60,
    )
    return item, op, won


def test_immutable_unicode_offsets_repair_and_binding():
    async def scenario():
        async with rollback_conn() as conn:
            rt = await seeded(conn)
            item, op, won = await recording(rt, conn)
            assert won
            value = "Host: Café 🙂\nGuest: We need better attribution."
            version = await store.save_transcript(
                rt,
                conn,
                item_id=item["item_id"],
                value=value,
                segments=[Segment(start=0, end=len(value))],
                quality=Quality(),
                method="fixture",
                operation_id=op["operation_id"],
            )
            saved = await store.load_transcript(rt, conn, version)
            assert saved["text"] == value
            other = replace(rt.scope, job_id=uuid4())
            rt.scope = other
            with pytest.raises(RefusalError):
                await store.load_transcript(rt, conn, version)

    run_async(scenario())


def test_committed_source_ownership_across_independent_connections(monkeypatch):
    import asyncio

    from clue_db import db_lifespan
    from clue_research.claimstore import load_core_pack
    from tests.arv2 import test_committee_step_db as fixtures

    # Committed rows are required for real cross-connection visibility. This unique test
    # workspace lives only in the dedicated throwaway DB; no shared/customer rows are used.
    monkeypatch.setattr(fixtures, "WORKSPACE", "ws_media_concurrency_" + uuid4().hex)

    async def scenario():
        async with db_lifespan() as engine:
            async with engine.begin() as conn:
                await load_core_pack(conn)
                rt = await seeded(conn)
                item = await store.item_for(
                    rt,
                    conn,
                    Candidate(
                        url="https://example.com/concurrent", canonical_key="concurrency:one"
                    ),
                )
            barrier = asyncio.Event()

            async def worker():
                await barrier.wait()
                async with engine.begin() as conn:
                    return await ops.begin(
                        rt,
                        conn,
                        item_id=item["item_id"],
                        stage="transcribe",
                        request={"recipe": "final-behavior"},
                        seconds=60,
                    )

            workers = [asyncio.create_task(worker()), asyncio.create_task(worker())]
            barrier.set()
            results = await asyncio.gather(*workers)
            assert sum(won for _, won in results) == 1
            assert results[0][0]["operation_id"] == results[1][0]["operation_id"]
            original = next(op for op, won in results if won)
            async with engine.begin() as conn:
                await conn.execute(
                    text("""UPDATE arv2_media_operation
                    SET lease_until=now()-interval '1 second' WHERE operation_id=:id"""),
                    {"id": original["operation_id"]},
                )
            async with engine.begin() as conn:
                recovered, won = await ops.begin(
                    rt,
                    conn,
                    item_id=item["item_id"],
                    stage="transcribe",
                    request={"recipe": "final-behavior"},
                    seconds=60,
                )
                assert won and recovered["owner_token"] != original["owner_token"]
                with pytest.raises(RefusalError, match="ownership"):
                    await ops.dispatch(rt, conn, original)
                await ops.dispatch(rt, conn, recovered)
                await conn.execute(
                    text("""UPDATE arv2_media_operation
                    SET lease_until=now()-interval '1 second' WHERE operation_id=:id"""),
                    {"id": recovered["operation_id"]},
                )
            async with engine.begin() as conn:
                unknown, won = await ops.begin(
                    rt,
                    conn,
                    item_id=item["item_id"],
                    stage="transcribe",
                    request={"recipe": "final-behavior"},
                    seconds=60,
                )
                assert not won and unknown["state"] == "unknown"
                assert unknown["seconds"] == 60

    async def cleanup():
        async with db_lifespan() as engine, engine.begin() as conn:
            for table in ("arv2_media_operation", "arv2_media_alias", "arv2_media_item"):
                await conn.execute(
                    text(f"DELETE FROM {table} WHERE workspace_id=:ws"), {"ws": fixtures.WORKSPACE}
                )

    try:
        run_async(scenario())
    finally:
        run_async(cleanup())


def test_claim_write_audit_repair_and_erasure_preserve_pinned_evidence():
    from clue_api.arv2.account_research_claims import ClaimInput, agent_claims
    from clue_api.arv2.media_claims import attach, audit
    from clue_api.arv2.media_retrieval import ensure_index, search
    from clue_api.arv2.media_types import TranscriptSource
    from clue_research.claimstore import WorkspaceScope, claims_for

    async def scenario():
        async with rollback_conn() as conn:
            rt = await seeded(conn)
            item, op, _ = await recording(rt, conn)
            speech = "The committee needs reliable evidence."
            version = await store.save_transcript(
                rt,
                conn,
                item_id=item["item_id"],
                value=speech,
                segments=[Segment(start=0, end=len(speech))],
                quality=Quality(),
                method="fixture",
                operation_id=op["operation_id"],
            )
            saved = await store.load_transcript(rt, conn, version)
            await ensure_index(rt, version)
            found = await search(rt, "reliable evidence")
            source = TranscriptSource(version_ref=version, start=0, end=len(speech))
            drafts = agent_claims(
                [
                    ClaimInput(
                        field_key="account.strategy",
                        value="Needs evidence",
                        evidence_span=speech,
                        priority=1,
                    ),
                    ClaimInput(
                        field_key="account.strategy",
                        value="Bad quote",
                        evidence_span="Invented vendor preference.",
                        priority=1,
                    ),
                ],
                rt.scope,
                catalog=rt.catalog,
            )
            for draft in drafts:
                await rt._writer.write(conn, attach(draft, source, saved, rt))
            claims = await claims_for(
                conn, rt.scope.account_id, scope=WorkspaceScope.for_workspace(rt.scope.workspace_id)
            )
            media_claims = [c for c in claims if c.write_markers.get("media")]
            assert len(media_claims) == 2
            assert {(await audit(rt, c))[0] for c in media_claims} == {"EXACT", "NOT_FOUND"}
            invalid = next(c for c in media_claims if c.evidence_span != speech)
            assert not invalid.outreach_safe
            replacement = await store.save_transcript(
                rt,
                conn,
                item_id=item["item_id"],
                value="Corrected committee discussion.",
                segments=[],
                quality=Quality(),
                method="repair",
                operation_id=uuid4(),
                supersedes=version,
            )
            annotation_count = (
                await conn.execute(
                    text("""SELECT count(*)
                FROM arv2_claim_annotation WHERE detail_json->>'previous_version'=:version"""),
                    {"version": str(version)},
                )
            ).scalar_one()
            assert annotation_count == 2
            assert all(
                [
                    (await audit(rt, c))[1] == "superseded_transcript_needs_recheck"
                    for c in media_claims
                ]
            )
            assert all(
                c.write_markers["media"]["version_ref"] == str(version) for c in media_claims
            )
            await ensure_index(rt, replacement)
            with pytest.raises(RefusalError, match="generation"):
                await search(rt, "reliable evidence", search_ref=UUID(found["search_ref"]))
            await conn.execute(
                text("""UPDATE artifact SET erased_at=now(),privacy_erased=true,
                erasure_reason='privacy' WHERE storage_key=:key"""),
                {"key": saved["text_key"]},
            )
            assert all([(await audit(rt, c))[0] == "fetch_failed" for c in media_claims])
            assert (await search(rt, "committee"))["results"] == []
            count = (
                await conn.execute(text("SELECT count(*) FROM arv2_media_passage"))
            ).scalar_one()
            assert count == 0

    run_async(scenario())


def test_owner_replay_unknown_and_durable_seconds():
    async def scenario():
        async with rollback_conn() as conn:
            rt = await seeded(conn)
            item, op, won = await recording(rt, conn)
            same, won2 = await ops.begin(
                rt,
                conn,
                item_id=item["item_id"],
                stage="transcribe",
                request={"recipe": "test"},
                seconds=60,
            )
            assert won and not won2 and same["operation_id"] == op["operation_id"]
            await ops.dispatch(rt, conn, op)
            await conn.execute(
                text("UPDATE arv2_media_operation SET lease_until=now()-interval '1 second'")
            )
            unknown, won3 = await ops.begin(
                rt,
                conn,
                item_id=item["item_id"],
                stage="transcribe",
                request={"recipe": "test"},
                seconds=60,
            )
            assert unknown["state"] == "unknown" and not won3
            rt.settings = rt.settings.model_copy(update={"arv2_media_seconds_ceiling": 60})
            with pytest.raises(RefusalError, match="allowance"):
                await ops.begin(
                    rt, conn, item_id=item["item_id"], stage="repair", request={}, seconds=1
                )

    run_async(scenario())


def test_artifact_erasure_clears_derived_evidence_and_tombstones_source():
    async def scenario():
        async with rollback_conn() as conn:
            rt = await seeded(conn)
            item, op, _ = await recording(rt, conn)
            version = await store.save_transcript(
                rt,
                conn,
                item_id=item["item_id"],
                value="Real evidence.",
                segments=[],
                quality=Quality(),
                method="fixture",
                operation_id=op["operation_id"],
            )
            saved = await store.load_transcript(rt, conn, version)
            await conn.execute(
                text(
                    "UPDATE artifact SET erased_at=now(),privacy_erased=true WHERE storage_key=:key"
                ),
                {"key": saved["text_key"]},
            )
            with pytest.raises(RefusalError):
                await store.load_transcript(rt, conn, version)
            with pytest.raises(RefusalError, match="privacy-erased"):
                await store.item_for(
                    rt,
                    conn,
                    Candidate(url="https://example.com/alternate", canonical_key="test:one"),
                )
            row = (
                await conn.execute(
                    text("SELECT title,metadata,privacy_erased FROM arv2_media_item")
                )
            ).one()
            assert row.title == "" and row.metadata == {} and row.privacy_erased

    run_async(scenario())


def test_integrated_publisher_read_index_search_open_and_reuse():
    import json
    from types import SimpleNamespace

    from clue_api.arv2.account_research_claims import ClaimInput, agent_claims
    from clue_api.arv2.media_claims import attach, audit, guard_draft, resolve_source
    from clue_api.arv2.media_retrieval import open_passage, search
    from clue_api.arv2.media_tools import (
        DiscoverMediaArgs,
        ReadMediaArgs,
        discover_media,
        read_media,
    )
    from clue_api.arv2.media_types import TranscriptSource

    async def scenario():
        async with rollback_conn() as conn:
            rt = await seeded(conn)
            speech = (
                "Beginning evidence.\n"
                + ("Ordinary discussion. " * 300)
                + "\nThe buying committee needs durable provenance.\nEnd of recording."
            )
            html = (
                '<script type="application/ld+json">'
                + json.dumps(
                    {"@type": "PodcastEpisode", "name": "Test recording", "transcript": speech}
                )
                + "</script>"
            )
            wire = ScriptedTransport(
                [
                    json_response(
                        {
                            "results": [
                                {
                                    "url": "https://example.com/episode",
                                    "title": "Research interview",
                                    "text": "A candidate source",
                                }
                            ],
                            "costDollars": {"total": 0.001},
                        }
                    ),
                    HttpResponse(200, {"content-type": "text/html"}, html.encode()),
                ]
            )
            rt._transport_factory = lambda: wire
            discovery_args = DiscoverMediaArgs(
                query="Company buying priorities interview", purpose="Find buying priorities"
            )
            discovery = await discover_media(rt, discovery_args)
            replay = await discover_media(
                rt,
                discovery_args.model_copy(
                    update={"discovery_ref": UUID(discovery["discovery_ref"])}
                ),
            )
            assert discovery["candidates"] == replay["candidates"] and len(wire.requests) == 1
            result = await read_media(
                rt,
                ReadMediaArgs(
                    candidate_ref=UUID(discovery["candidates"][0]["candidate_ref"]),
                    purpose="Find buying priorities",
                ),
            )
            assert result["state"] == "available" and result["index"]["state"] == "lexical"
            version = UUID(result["version_ref"])
            reconstructed = ""
            offset = 0
            while True:
                opened = await open_passage(rt, version_id=version, start=offset)
                reconstructed += opened["text"]
                if opened["next_offset"] is None:
                    break
                offset = opened["next_offset"]
            assert reconstructed == speech
            found = await search(rt, "durable provenance")
            assert found["mode"] == "lexical" and any(
                "durable provenance" in r["text"] for r in found["results"]
            )
            again = await read_media(
                rt, ReadMediaArgs(url="https://example.com/episode", purpose="Different question")
            )
            assert again["reused"] and len(wire.requests) == 2
            source = TranscriptSource(version_ref=version, start=0, end=len(speech))
            block, saved = await resolve_source(rt, source)
            rt.remember_sources([block])
            draft = agent_claims(
                [
                    ClaimInput(
                        field_key="account.strategy",
                        value="Needs evidence",
                        evidence_span="invented quote",
                        priority=1,
                    )
                ],
                rt.scope,
                catalog=rt.catalog,
            )[0]
            stamped = attach(draft, source, saved, rt)
            followup = replace(
                draft, source_url=saved["source_url"], evidence_span="Beginning evidence."
            )
            guarded = await guard_draft(rt, conn, followup)
            assert guarded.markers["media"]["version_ref"] == str(version)
            assert (
                stamped.markers["media"]["quote_verdict"] == "NOT_FOUND"
                and not stamped.outreach_safe
            )
            verdict, reason, _ = await audit(
                rt,
                SimpleNamespace(write_markers=stamped.markers, evidence_span=stamped.evidence_span),
            )
            assert verdict == "NOT_FOUND" and reason == "transcript_not_found"

    run_async(scenario())


class MediaClients:
    def media(self, caller, ledger):
        from pydantic import SecretStr

        from clue_api.arv2.gemini_media_client import GeminiMediaClient, MediaBudget

        return GeminiMediaClient(
            caller,
            openrouter_api_key=SecretStr("fixture"),
            openrouter_base_url="https://openrouter.ai/api/v1",
            gemini_api_key=SecretStr("fixture"),
            short_model="fixture/short",
            transcribe_model="fixture-long",
            embedding_model="fixture/embedding",
            media_budget=MediaBudget(9000),
            short_max_seconds=600,
            ledger=ledger,
            sleep=lambda _: None,
        )


def json_response(value):
    import json

    return HttpResponse(200, {"content-type": "application/json"}, json.dumps(value).encode())


def video_metadata():
    import json

    value = {
        "playabilityStatus": {"status": "OK"},
        "videoDetails": {
            "videoId": "abcdefghijk",
            "title": "Research interview",
            "lengthSeconds": "60",
        },
    }
    return HttpResponse(
        200,
        {"content-type": "text/html"},
        ("var ytInitialPlayerResponse = " + json.dumps(value) + ";").encode(),
    )


def native_speech(value):
    return json_response(
        {
            "candidates": [
                {
                    "finishReason": "STOP",
                    "content": {"parts": [{"text": "## TRANSCRIPT\n[00:01] Guest: " + value}]},
                }
            ]
        }
    )


def embeddings(count=1):
    return json_response(
        {"data": [{"index": i, "embedding": [1.0] + [0.0] * 767} for i in range(count)]}
    )


@pytest.mark.parametrize("long_audio", [False, True])
def test_feed_enclosure_audio_and_saved_upload_recovery(monkeypatch, long_audio):
    from clue_api.arv2.media_tools import ReadMediaArgs, read_media

    async def scenario():
        async with rollback_conn() as conn:
            rt = await seeded(conn)
            rt.clients = MediaClients()
            duration = 601 if long_audio else 60
            feed = f"""<rss xmlns:itunes="http://www.itunes.com/dtds/podcast-1.0.dtd">
              <channel><title>Source show</title><item><guid>ep-1</guid><title>Evidence</title>
              <link>https://example.com/episode-1</link><itunes:duration>{duration}</itunes:duration>
              <enclosure url="https://example.com/source.mp3" type="audio/mpeg"/>
              </item></channel></rss>"""
            responses = [
                HttpResponse(200, {"content-type": "application/rss+xml"}, feed.encode()),
                HttpResponse(200, {"content-type": "audio/mpeg"}, b"offline audio bytes"),
            ]
            if long_audio:
                responses.extend(
                    [
                        HttpResponse(
                            200, {"x-goog-upload-url": "https://upload.example.com/session"}
                        ),
                        json_response({"file": {"name": "files/offline"}}),
                        json_response(
                            {
                                "name": "files/offline",
                                "state": "ACTIVE",
                                "uri": "https://generativelanguage.googleapis.com/v1beta/files/offline",
                            }
                        ),
                        native_speech("We require reliable evidence."),
                    ]
                )
                original = ops.finish

                async def fail_once(runtime, connection, operation, **kwargs):
                    if operation["stage"] == "upload":
                        monkeypatch.setattr(ops, "finish", original)
                        raise RuntimeError("crash after saved upload receipt")
                    return await original(runtime, connection, operation, **kwargs)

                monkeypatch.setattr(ops, "finish", fail_once)
            else:
                responses.append(
                    json_response(
                        {
                            "choices": [
                                {
                                    "finish_reason": "stop",
                                    "message": {
                                        "content": "## TRANSCRIPT\n[00:01] Guest: "
                                        "We require reliable evidence."
                                    },
                                }
                            ]
                        }
                    )
                )
            responses.append(embeddings())
            wire = ScriptedTransport(responses)
            rt._transport_factory = lambda: wire
            first = ReadMediaArgs(
                url="https://example.com/feed",
                episode_hint="ep-1",
                purpose="Find buying requirements",
            )
            if long_audio:
                with pytest.raises(RuntimeError, match="saved upload"):
                    await read_media(rt, first)
                # Recovery needs only the already resolved episode alias and saved free-upload
                # responses. The paid transcription was never dispatched before the crash.
                first = first.model_copy(update={"url": "https://example.com/episode-1"})
            result = await read_media(rt, first)
            assert result["state"] == "available" and result["index"]["state"] == "ready"
            count = len(wire.requests)
            reused = await read_media(
                rt, ReadMediaArgs(url="https://example.com/episode-1", purpose="Reuse speech")
            )
            assert reused["reused"] and len(wire.requests) == count
            generation = [
                r
                for r in wire.requests
                if ":generateContent" in r.url or r.url.endswith("chat/completions")
            ]
            assert len(generation) == 1
            seconds = (
                await conn.execute(
                    text("""SELECT sum(seconds) FROM arv2_media_operation
                WHERE workspace_id=:ws AND owner_job=:job"""),
                    {"ws": rt.scope.workspace_id, "job": rt.scope.job_id},
                )
            ).scalar_one()
            assert seconds == duration

    run_async(scenario())


def test_native_video_hybrid_retrieval_and_cross_job_reuse():
    from clue_api.arv2 import account_research_store as job_store
    from clue_api.arv2.media_retrieval import search
    from clue_api.arv2.media_tools import ReadMediaArgs, read_media

    async def scenario():
        async with rollback_conn() as conn:
            rt = await seeded(conn)
            rt.clients = MediaClients()
            wire = ScriptedTransport(
                [
                    video_metadata(),
                    native_speech("We evaluate vendors by evidence quality."),
                    embeddings(),
                    embeddings(),
                ]
            )
            rt._transport_factory = lambda: wire
            result = await read_media(
                rt, ReadMediaArgs(url="https://youtu.be/abcdefghijk", purpose="Buying behavior")
            )
            assert result["index"]["state"] == "ready"
            found = await search(rt, "criteria for evaluating suppliers")
            assert found["mode"] == "hybrid" and found["results"]
            assert found["results"][0]["rank_components"]["semantic"] == 1
            assert len(wire.requests) == 4
            old_job = rt.scope.job_id
            original_run = await job_store.read_run(conn, run_id=rt.scope.run_id)
            run2 = replace(original_run, run_id=uuid4(), request_sha256="d" * 64)
            assert await job_store.create_run(conn, run2)
            new_job = uuid4()
            assert await job_store.create_job(
                conn,
                job_id=new_job,
                run_id=run2.run_id,
                workspace_id=rt.scope.workspace_id,
                account_entity_id=rt.scope.account_id,
                profile_sha256=run2.profile_sha256,
            )
            rt.scope = replace(rt.scope, job_id=new_job, run_id=run2.run_id)
            # Workspace reuse requires an explicit source binding in the new job.
            assert (await search(rt, "vendors"))["results"] == []
            reused = await read_media(
                rt,
                ReadMediaArgs(
                    url="https://youtube.com/embed/abcdefghijk", purpose="Separate project question"
                ),
            )
            assert reused["reused"] and len(wire.requests) == 4
            owner = (
                await conn.execute(
                    text("SELECT owner_job FROM arv2_media_operation WHERE stage='transcribe'")
                )
            ).scalar_one()
            assert owner == old_job

    run_async(scenario())


def test_saved_paid_response_recovers_after_canonical_persistence_failure(monkeypatch):
    from clue_api.arv2.media_tools import ReadMediaArgs, read_media

    async def scenario():
        async with rollback_conn() as conn:
            rt = await seeded(conn)
            rt.clients = MediaClients()
            wire = ScriptedTransport(
                [
                    video_metadata(),
                    native_speech("Our buying process needs reliable evidence."),
                    embeddings(),
                ]
            )
            rt._transport_factory = lambda: wire
            original = store.save_transcript

            async def fail_once(*args, **kwargs):
                monkeypatch.setattr(store, "save_transcript", original)
                raise RuntimeError("simulated persistence failure after paid response drain")

            monkeypatch.setattr(store, "save_transcript", fail_once)
            args = ReadMediaArgs(url="https://youtu.be/abcdefghijk", purpose="Recover evidence")
            with pytest.raises(RuntimeError):
                await read_media(rt, args)
            recovered = await read_media(rt, args)
            assert recovered["state"] == "available" and len(wire.requests) == 3
            assert sum(":generateContent" in r.url for r in wire.requests) == 1

    run_async(scenario())


def test_expiry_is_unavailable_then_explicit_refresh_but_dsar_never_refreshes():
    import json

    from clue_api.arv2.media_tools import ReadMediaArgs, read_media
    from clue_storage import purge_erased_artifacts

    async def scenario():
        async with rollback_conn() as conn:
            rt = await seeded(conn)
            page = (
                '<script type="application/ld+json">'
                + json.dumps({"@type": "AudioObject", "transcript": "Publisher words preserved."})
                + "</script>"
            )
            wire = ScriptedTransport(
                [
                    HttpResponse(200, {"content-type": "text/html"}, page.encode()),
                    HttpResponse(200, {"content-type": "text/html"}, page.encode()),
                ]
            )
            rt._transport_factory = lambda: wire
            args = ReadMediaArgs(url="https://example.com/expiry", purpose="Retention test")
            first = await read_media(rt, args)
            await conn.execute(
                text(
                    "UPDATE artifact SET expires_at=now()-interval '1 second' WHERE "
                    "storage_key IN (SELECT text_key FROM arv2_media_transcript)"
                )
            )
            await purge_erased_artifacts(conn, rt.storage)
            with pytest.raises(RefusalError):
                await read_media(rt, args)
            refreshed = await read_media(rt, args.model_copy(update={"refresh_expired": True}))
            assert (
                refreshed.get("version_ref") != first["version_ref"] and "version_ref" in refreshed
            ), refreshed
            await conn.execute(
                text(
                    "UPDATE artifact SET "
                    "erased_at=now(),privacy_erased=true,erasure_reason='privacy' WHERE "
                    "storage_key IN (SELECT text_key FROM arv2_media_transcript)"
                )
            )
            with pytest.raises(RefusalError, match="privacy"):
                await read_media(rt, args.model_copy(update={"refresh_expired": True}))

    run_async(scenario())
