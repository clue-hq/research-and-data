"""Real Postgres media evidence/replay/privacy contracts. All provider inputs are offline."""

import json
from dataclasses import replace
from uuid import UUID, uuid4

import pytest
from pydantic import SecretStr
from sqlalchemy import text

from clue_api.arv2 import media_operations as ops
from clue_api.arv2 import media_store as store
from clue_api.arv2.account_research_refusals import RefusalError
from clue_api.arv2.gemini_media_client import MediaBudget
from clue_api.arv2.media_sources import MediaSourceKeys
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


def test_media_trace_ledger_logs_fallback_and_reuse_agree():
    import json

    from clue_api.arv2.account_research_tools import build_account_tools
    from clue_api.langfuse_callbacks import ClueLangfuseHandler
    from clue_obs import capture_events
    from clue_obs.langfuse import LangfuseRunRegistry, observation, propagate_trace
    from clue_projections.cost import CostFilters, cost_report
    from tests._langfuse import finished_spans, langfuse_installed

    async def scenario():
        async with rollback_conn() as conn:
            rt = await seeded(conn)
            rt.clients = MediaClients()
            speech = "UNIQUE_TRANSCRIPT_MARKER must stay out of structured logs."
            wire = ScriptedTransport(
                [
                    offline_audio(),
                    offline_audio(),
                    deepgram_speech(speech),
                    HttpResponse(500, body=b'{"error":"embedding unavailable"}'),
                ]
            )
            rt._transport_factory = lambda: wire
            tool = next(t for t in build_account_tools(rt) if t.name == "read_media")
            with langfuse_installed() as (exporter, _), capture_events() as captured:
                with (
                    observation("arv2.account_research", as_type="agent"),
                    propagate_trace(trace_name="arv2.account_research"),
                ):
                    config = {"callbacks": [ClueLangfuseHandler(LangfuseRunRegistry())]}
                    args = {"url": "https://example.com/talk.mp3", "purpose": "Study priorities"}
                    first = json.loads(await tool.ainvoke(args, config=config))
                    assert first["state"] == "available" and first["index"]["state"] == "lexical"
                    replay = json.loads(await tool.ainvoke(args, config=config))
                    assert replay["reused"] and len(wire.requests) == 4
                spans = finished_spans(exporter)
            generations = [
                s for s in spans if s.attributes.get("langfuse.observation.type") == "generation"
            ]
            assert len(generations) == 1
            generation = generations[0]
            parents = {s.context.span_id: s for s in spans}
            stage = parents[generation.parent.span_id]
            assert stage.name == "arv2.media.provider_stage"
            assert parents[stage.parent.span_id].name == "read_media"
            assert len({s.context.trace_id for s in spans}) == 1
            assert len([s for s in spans if s.name == "read_media"]) == 2
            assert (
                len(
                    [
                        s
                        for s in spans
                        if s.attributes.get("langfuse.observation.type") == "embedding"
                    ]
                )
                == 1
            )
            assert generation.attributes["langfuse.observation.metadata.cost_source"] == "estimate"
            assert (
                json.loads(generation.attributes["langfuse.observation.cost_details"])["total"]
                == 0.0043
            )

            ledger = (
                (
                    await conn.execute(
                        text(
                            "SELECT * FROM provider_call_ledger WHERE entity_research_job_id=:job "
                            "AND phase='result' AND provider='deepgram'"
                        ),
                        {"job": rt.scope.job_id},
                    )
                )
                .mappings()
                .one()
            )
            assert float(ledger["cost_usd"]) == 0.0043 and ledger["media_seconds"] == 60
            assert ledger["extras_json"]["cost_source"] == "estimate"
            assert ledger["extras_json"]["langfuse_trace_id"] == format(
                generation.context.trace_id, "032x"
            )
            assert ledger["extras_json"]["langfuse_observation_id"] == format(
                generation.context.span_id, "016x"
            )
            operation_id = stage.attributes["langfuse.observation.metadata.operation_id"]
            op = (
                (
                    await conn.execute(
                        text("SELECT * FROM arv2_media_operation WHERE operation_id=:id"),
                        {"id": UUID(operation_id)},
                    )
                )
                .mappings()
                .one()
            )
            assert op["state"] == "succeeded" and op["ledger_ids"] and op["artifact_keys"]
            report = await cost_report(
                workspace_id=rt.scope.workspace_id,
                filters=CostFilters(job_id=rt.scope.job_id),
                conn_factory=rt._conn_factory,
            )
            video_line = next(p for p in report.providers if p.provider == "deepgram")
            assert video_line.estimated_calls == 1 and video_line.unpriced_calls == 0
            assert video_line.free_calls == 0
            logs = [
                e for e in captured.entries if str(e.get("event", "")).startswith("arv2.media.")
            ]
            assert all(e["job_id"] == str(rt.scope.job_id) for e in logs)
            assert speech not in json.dumps(logs, default=str)
            assert "https://" not in json.dumps(logs, default=str)
            assert any(e["event"] == "arv2.media.embedding_fallback" for e in logs)
            assert any(e["event"] == "arv2.media.tool_completed" and e.get("reused") for e in logs)
            assert any(
                e.get("state") == "unknown" and e.get("decision") == "reuse_or_wait" for e in logs
            )
            assert any(e.get("operation_id") == operation_id and e.get("ledger_ids") for e in logs)
            assert ops.active_operation.get() is None

    run_async(scenario())


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

    from clue_api.arv2 import account_research_store as jobs
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
                first_run = await jobs.read_run(conn, run_id=rt.scope.run_id)
                second_run = replace(first_run, run_id=uuid4(), request_sha256="e" * 64)
                assert await jobs.create_run(conn, second_run)
                second_job = uuid4()
                assert await jobs.create_job(
                    conn,
                    job_id=second_job,
                    run_id=second_run.run_id,
                    workspace_id=rt.scope.workspace_id,
                    account_entity_id=rt.scope.account_id,
                    profile_sha256=second_run.profile_sha256,
                )
                other = runtime(
                    conn,
                    replace(rt.scope, job_id=second_job, run_id=second_run.run_id),
                    rt.storage,
                    ScriptedTransport([]),
                )
            barrier = asyncio.Event()

            async def worker(consumer):
                await barrier.wait()
                async with engine.begin() as conn:
                    return await ops.begin(
                        consumer,
                        conn,
                        item_id=item["item_id"],
                        stage="transcribe",
                        request={"recipe": "final-behavior"},
                        seconds=60,
                    )

            workers = [asyncio.create_task(worker(rt)), asyncio.create_task(worker(other))]
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
                    # Scoped to this test's item: DB tests that commit leave other rows behind.
                    text(
                        "SELECT title,metadata,privacy_erased FROM arv2_media_item "
                        "WHERE item_id=:id"
                    ),
                    {"id": item["item_id"]},
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
            assert found["mode"] == "lexical" and found["results"]
            # A rich segment/quality receipt can be paginated before its matching phrase.
            # Follow the returned range to assert the entire ranked passage remains readable.
            passages = []
            for hit in found["results"]:
                body = hit["text"]
                while hit["end"] < hit["requested_end"]:
                    hit = await open_passage(
                        rt, version_id=version, start=hit["end"], end=hit["requested_end"]
                    )
                    body += hit["text"]
                passages.append(body)
            assert any("durable provenance" in body for body in passages)
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
    media_source_keys = MediaSourceKeys(youtube_api_key=SecretStr("yt-key"))
    transcription_ready = True

    def transcription(self, caller):
        from pydantic import SecretStr

        from clue_api.arv2.deepgram_media_client import DeepgramMediaClient

        return DeepgramMediaClient(caller, SecretStr("fixture"))

    def exa(self, caller):
        from clue_api.arv2.exa_client import ExaClient

        return ExaClient(caller, SecretStr("fixture"))

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


def youtube_data(duration="PT1M"):
    return json_response(
        {
            "items": [
                {
                    "id": "abcdefghijk",
                    "snippet": {
                        "publishedAt": "2026-04-08T15:00:00Z",
                        "title": "Research interview",
                        "channelTitle": "Interview channel",
                        "description": "",
                        "liveBroadcastContent": "none",
                    },
                    "contentDetails": {"duration": duration},
                    "status": {"privacyStatus": "public"},
                }
            ]
        }
    )


def no_shows():
    return json_response({"results": []})


def gemini_window(text):
    return json_response(
        {
            "responseId": "native-1",
            "usageMetadata": {"promptTokenCount": 6000, "candidatesTokenCount": 200},
            "candidates": [
                {"finishReason": "STOP", "content": {"parts": [{"text": "## TRANSCRIPT\n" + text}]}}
            ],
        }
    )


@pytest.fixture(autouse=True)
def prepared_offline_recording(monkeypatch):
    import hashlib
    import json

    from clue_api.arv2 import media_acquisition

    def prepare(path):
        data = path.read_bytes()
        return path, {
            "mime": "audio/mpeg",
            "duration_s": json.loads(data)["duration"],
            "preparation": "original_audio_bytes",
            "audio_sha256": hashlib.sha256(data).hexdigest(),
        }

    monkeypatch.setattr(media_acquisition, "prepare_audio", prepare)


def offline_audio(duration=60):
    import json

    return HttpResponse(
        200, {"content-type": "audio/mpeg"}, json.dumps({"duration": duration}).encode()
    )


def deepgram_speech(value):
    return json_response(
        {
            "metadata": {"request_id": "fixture-asr", "duration": 60},
            "results": {
                "channels": [{"alternatives": [{"transcript": value}]}],
                "utterances": [{"start": 1.25, "end": 5.75, "speaker": 0, "transcript": value}],
            },
        }
    )


def embeddings(count=1):
    return json_response(
        {"data": [{"index": i, "embedding": [1.0] + [0.0] * 767} for i in range(count)]}
    )


@pytest.mark.parametrize("duration", [60, 601])
def test_feed_enclosure_deepgram_whole_recording_and_reuse(duration):
    import json

    from clue_api.arv2.media_tools import ReadMediaArgs, read_media

    async def scenario():
        async with rollback_conn() as conn:
            rt = await seeded(conn)
            rt.clients = MediaClients()
            feed = f"""<rss xmlns:itunes="http://www.itunes.com/dtds/podcast-1.0.dtd">
              <channel><title>Source show</title><item><guid>ep-1</guid><title>Evidence</title>
              <link>https://example.com/episode-1</link><itunes:duration>{duration}</itunes:duration>
              <enclosure url="https://example.com/source.mp3" type="audio/mpeg"/>
              </item></channel></rss>"""
            wire = ScriptedTransport(
                [
                    HttpResponse(200, {"content-type": "application/rss+xml"}, feed.encode()),
                    offline_audio(duration),
                    deepgram_speech("We require reliable evidence."),
                    embeddings(),
                ]
            )
            rt._transport_factory = lambda: wire
            result = await read_media(
                rt,
                ReadMediaArgs(
                    url="https://example.com/feed", episode_hint="ep-1", purpose="Find requirements"
                ),
            )
            assert result["state"] == "available" and result["index"]["state"] == "ready"
            count = len(wire.requests)
            reused = await read_media(
                rt, ReadMediaArgs(url="https://example.com/episode-1", purpose="Reuse speech")
            )
            assert reused["reused"] and len(wire.requests) == count
            requests = [r for r in wire.requests if "/v1/listen?" in r.url]
            assert len(requests) == 1
            assert json.loads(requests[0].body) == {"url": "https://example.com/source.mp3"}
            seconds = (
                await conn.execute(
                    text(
                        "SELECT sum(seconds) FROM arv2_media_operation "
                        "WHERE workspace_id=:ws AND owner_job=:job"
                    ),
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
                    youtube_data(),
                    no_shows(),
                    no_shows(),
                    gemini_window("[00:05] Guest: We evaluate vendors by evidence quality."),
                    embeddings(),
                    embeddings(),
                ]
            )
            rt._transport_factory = lambda: wire
            result = await read_media(
                rt, ReadMediaArgs(url="https://youtu.be/abcdefghijk", purpose="Buying behavior")
            )
            assert result["index"]["state"] == "ready"
            # Nothing was downloaded and no YouTube page was read: the Data API, two directory
            # searches and one Gemini window over the public link.
            assert not any("youtube.com/watch" in r.url for r in wire.requests[:3])
            assert ":generateContent" in wire.requests[3].url
            method = (
                await conn.execute(
                    text("SELECT source_method FROM arv2_media_transcript WHERE version_id=:v"),
                    {"v": UUID(result["version_ref"])},
                )
            ).scalar_one()
            assert method == "gemini_youtube"
            found = await search(rt, "criteria for evaluating suppliers")
            assert found["mode"] == "hybrid" and found["results"]
            assert found["results"][0]["rank_components"]["semantic"] == 1
            assert len(wire.requests) == 6
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
            assert reused["reused"] and len(wire.requests) == 6
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
                    offline_audio(),
                    offline_audio(),
                    deepgram_speech("Our buying process needs reliable evidence."),
                    embeddings(),
                ]
            )
            rt._transport_factory = lambda: wire
            original = store.save_transcript

            async def fail_once(*args, **kwargs):
                monkeypatch.setattr(store, "save_transcript", original)
                raise RuntimeError("simulated persistence failure after paid response drain")

            monkeypatch.setattr(store, "save_transcript", fail_once)
            args = ReadMediaArgs(url="https://example.com/talk.mp3", purpose="Recover evidence")
            with pytest.raises(RuntimeError):
                await read_media(rt, args)
            recovered = await read_media(rt, args)
            assert recovered["state"] == "available" and len(wire.requests) == 4
            assert sum("/v1/listen?" in r.url for r in wire.requests) == 1

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


def test_a_long_video_is_read_in_windows_and_joined():
    from clue_api.arv2.media_tools import (
        OpenTranscriptArgs,
        ReadMediaArgs,
        open_transcript,
        read_media,
    )

    async def scenario():
        async with rollback_conn() as conn:
            rt = await seeded(conn)
            rt.clients = MediaClients()
            rt.settings = rt.settings.model_copy(update={"arv2_media_gemini_window_seconds": 2400})
            # The shared test runtime allows 100 media seconds; a run's real ceiling is 9000.
            rt.media_budget = MediaBudget(9000)
            wire = ScriptedTransport(
                [
                    youtube_data("PT1H10M"),
                    no_shows(),
                    no_shows(),
                    gemini_window("[00:10] Guest: First part."),
                    gemini_window("[00:20] Guest: Second part."),
                    embeddings(),
                ]
            )
            rt._transport_factory = lambda: wire
            result = await read_media(
                rt, ReadMediaArgs(url="https://youtu.be/abcdefghijk", purpose="Long talk")
            )
            assert result["state"] == "available"
            bodies = [json.loads(r.body) for r in wire.requests if ":generateContent" in r.url]
            metadata = [b["contents"][0]["parts"][0]["videoMetadata"] for b in bodies]
            assert [(m["startOffset"], m["endOffset"]) for m in metadata] == [
                ("0s", "2400s"),
                ("2400s", "4200s"),
            ]
            opened = await open_transcript(
                rt, OpenTranscriptArgs(version_ref=UUID(result["version_ref"]))
            )
            text_value = json.dumps(opened)
            assert "First part." in text_value and "Second part." in text_value

    run_async(scenario())


def test_a_video_over_the_remaining_budget_is_refused_before_any_window():
    from clue_api.arv2.media_tools import ReadMediaArgs, read_media

    async def scenario():
        async with rollback_conn() as conn:
            rt = await seeded(conn)
            rt.clients = MediaClients()
            rt.media_budget.reserve(rt.media_budget.ceiling_s - 60)
            wire = ScriptedTransport([youtube_data("PT10M"), no_shows(), no_shows()])
            rt._transport_factory = lambda: wire
            result = await read_media(
                rt, ReadMediaArgs(url="https://youtu.be/abcdefghijk", purpose="Over budget")
            )
            assert result["state"] == "unavailable"
            assert "media_budget_exhausted" in json.dumps(result)
            assert not any(":generateContent" in r.url for r in wire.requests)

    run_async(scenario())


def test_gemini_switched_off_returns_the_video_details():
    from clue_api.arv2.media_tools import ReadMediaArgs, read_media

    async def scenario():
        async with rollback_conn() as conn:
            rt = await seeded(conn)
            rt.clients = MediaClients()
            rt.settings = rt.settings.model_copy(
                update={"arv2_media_youtube_gemini_enabled": False}
            )
            wire = ScriptedTransport([youtube_data(), no_shows(), no_shows()])
            rt._transport_factory = lambda: wire
            result = await read_media(
                rt, ReadMediaArgs(url="https://youtu.be/abcdefghijk", purpose="Switched off")
            )
            assert result["state"] == "unavailable"
            assert "youtube_transcription_disabled" in result["gaps"]
            assert result["video"]["title"] == "Research interview"
            assert not any(":generateContent" in r.url for r in wire.requests)

    run_async(scenario())


def test_a_worker_without_ffprobe_reports_the_media_lane_unavailable(monkeypatch):
    import shutil

    from clue_api.arv2 import media_acquisition
    from clue_api.arv2.media_tools import ReadMediaArgs, read_media

    real_which = shutil.which

    async def scenario():
        async with rollback_conn() as conn:
            rt = await seeded(conn)
            rt.clients = MediaClients()
            monkeypatch.setattr(
                media_acquisition.shutil,
                "which",
                lambda name: None if name == "ffprobe" else real_which(name),
            )
            feed = """<rss><channel><item><guid>ep-1</guid><title>E</title>
              <enclosure url="https://example.com/a.mp3" type="audio/mpeg"/>
              </item></channel></rss>"""
            wire = ScriptedTransport(
                [HttpResponse(200, {"content-type": "application/rss+xml"}, feed.encode())]
            )
            rt._transport_factory = lambda: wire
            result = await read_media(
                rt,
                ReadMediaArgs(url="https://example.com/feed", episode_hint="ep-1", purpose="Lane"),
            )
            assert result["state"] == "unavailable"
            assert "media_lane_unavailable_on_worker: ffprobe missing" in json.dumps(result)
            assert len(wire.requests) == 1  # nothing downloaded, nothing sent to Deepgram

    run_async(scenario())


def test_a_chosen_episode_still_uses_its_feed_transcript():
    from clue_api.arv2.media_tools import ReadMediaArgs, read_media

    async def scenario():
        async with rollback_conn() as conn:
            rt = await seeded(conn)
            rt.clients = MediaClients()
            feed = """<rss xmlns:podcast="https://podcastindex.org/namespace/1.0"><channel>
              <item><guid>a</guid><title>Pricing evidence part 1</title>
              <enclosure url="https://example.com/a.mp3" type="audio/mpeg"/>
              <podcast:transcript url="https://example.com/a.vtt" type="text/vtt"/></item>
              <item><guid>b</guid><title>Pricing evidence part 2</title>
              <enclosure url="https://example.com/b.mp3" type="audio/mpeg"/></item>
              </channel></rss>"""
            vtt = "WEBVTT\n\n00:00:01.000 --> 00:00:02.000\nWe price on evidence.\n"
            wire = ScriptedTransport(
                [
                    HttpResponse(200, {"content-type": "application/rss+xml"}, feed.encode()),
                    HttpResponse(200, {"content-type": "text/vtt"}, vtt.encode()),
                    embeddings(),
                ]
            )
            rt._transport_factory = lambda: wire
            listed = await read_media(
                rt,
                ReadMediaArgs(
                    url="https://example.com/feed", episode_hint="Pricing", purpose="Pricing"
                ),
            )
            assert listed["state"] == "ambiguous"
            first = next(c for c in listed["candidates"] if c["title"].endswith("part 1"))
            result = await read_media(
                rt, ReadMediaArgs(candidate_ref=UUID(first["candidate_ref"]), purpose="Pricing")
            )
            assert result["state"] == "available"
            assert not any(r.url.endswith(".mp3") for r in wire.requests)

    run_async(scenario())


def exa_links(*links, url="https://events.example.com/talk", text="Session page"):
    return json_response(
        {
            "requestId": "exa-links-1",
            "results": [{"url": url, "id": url, "text": text, "extras": {"links": list(links)}}],
            "statuses": [{"id": url, "status": "success"}],
            "costDollars": {"total": 0.001},
        }
    )


def test_page_recordings_keeps_only_recording_links_in_order():
    from clue_api.arv2.media_tools import page_recordings

    links = [
        "https://example.com/about",
        "https://www.youtube.com/embed/abcdefghijk",
        "https://cdn.example.com/talk.mp3",
        "https://podcasts.apple.com/us/podcast/x/id1",
        "https://www.youtube.com/watch?v=abcdefghijk",
        "https://www.youtube.com/@channel",
    ]
    assert page_recordings(links) == [
        "https://www.youtube.com/watch?v=abcdefghijk",
        "https://cdn.example.com/talk.mp3",
        "https://podcasts.apple.com/us/podcast/x/id1",
    ]


def test_a_blocked_page_is_read_through_exa_and_its_one_recording_is_used():
    from clue_api.arv2.media_tools import ReadMediaArgs, read_media

    async def scenario():
        async with rollback_conn() as conn:
            rt = await seeded(conn)
            rt.clients = MediaClients()
            wire = ScriptedTransport(
                [
                    HttpResponse(403, {"content-type": "text/html"}, b"blocked"),
                    exa_links("https://cdn.example.com/talk.mp3", "https://example.com/about"),
                    offline_audio(60),
                    offline_audio(60),
                    deepgram_speech("We hire for evidence."),
                    embeddings(),
                ]
            )
            rt._transport_factory = lambda: wire
            result = await read_media(
                rt, ReadMediaArgs(url="https://events.example.com/talk", purpose="Blocked page")
            )
            assert result["state"] == "available"
            exa = next(r for r in wire.requests if r.url.endswith("/contents"))
            assert json.loads(exa.body)["extras"] == {"links": 200}

    run_async(scenario())


def test_several_recordings_on_a_blocked_page_go_back_to_the_agent():
    from clue_api.arv2.media_tools import ReadMediaArgs, read_media

    async def scenario():
        async with rollback_conn() as conn:
            rt = await seeded(conn)
            rt.clients = MediaClients()
            wire = ScriptedTransport(
                [
                    HttpResponse(403, {"content-type": "text/html"}, b"blocked"),
                    exa_links("https://cdn.example.com/a.mp3", "https://cdn.example.com/b.mp3"),
                ]
            )
            rt._transport_factory = lambda: wire
            result = await read_media(
                rt, ReadMediaArgs(url="https://events.example.com/talk", purpose="Two talks")
            )
            assert result["state"] == "ambiguous"
            assert {c["url"] for c in result["candidates"]} == {
                "https://cdn.example.com/a.mp3",
                "https://cdn.example.com/b.mp3",
            }
            assert not any(r.url.endswith(".mp3") for r in wire.requests)

    run_async(scenario())


def test_a_page_with_no_recording_anywhere_tells_the_agent_where_else_to_look():
    from clue_api.arv2.media_tools import ReadMediaArgs, read_media

    async def scenario():
        async with rollback_conn() as conn:
            rt = await seeded(conn)
            rt.clients = MediaClients()
            wire = ScriptedTransport(
                [
                    HttpResponse(200, {"content-type": "text/html"}, b"<p>Show notes only</p>"),
                    exa_links("https://example.com/about"),
                ]
            )
            rt._transport_factory = lambda: wire
            result = await read_media(
                rt, ReadMediaArgs(url="https://events.example.com/notes", purpose="Notes page")
            )
            assert result["state"] == "unavailable"
            assert "no_recording_link_on_page_through_exa" in result["gaps"]
            assert "fetch_page" in result["next_action"]
            assert "podcast" in result["next_action"] and "LinkedIn" in result["next_action"]

    run_async(scenario())
