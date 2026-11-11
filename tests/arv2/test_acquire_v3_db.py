"""Version 3 runs the footprint jobs through the wrapper: saved result, ledger, no double pay."""

from __future__ import annotations

import json
from contextlib import asynccontextmanager
from dataclasses import replace
from uuid import uuid4

import pytest
from deepagents.backends.protocol import BackendProtocol
from pydantic import SecretStr
from sqlalchemy import text

from clue_api.arv2.quality_execution import Allowance, bind_execution
from clue_api.arv2.quality_provider_tools import AcquireResearchInputV3, AcquireResearchToolV3
from clue_api.arv2.quality_views import research_backend
from clue_api.arv2.transport import HttpResponse, ScriptedTransport
from clue_core import ExecutionId, OperationId
from clue_storage.fs import FsStorage
from clue_toolbelt import ToolContext
from tests.arv2.test_committee_discovery_v2_db import Clients, runtime
from tests.arv2.test_quality_claims_db import setup
from tests.arv2.test_quality_execution_db import execution
from tests.claimstore.conftest import (  # noqa: F401
    migrated_db,
    require_claimstore_db,
    rollback_conn,
    run_async,
)

pytestmark = pytest.mark.usefixtures("require_claimstore_db")


class TregClients(Clients):
    treg_token = SecretStr("treg-test-token")
    pdl_key = None


def li_page():
    body = {
        "posts": [
            {
                "id": "urn:li:activity:1",
                "content": "We moved our SOC to a hunt-first model.",
                "date": "2026-10-01T10:00:00Z",
                "shareUrl": "https://www.linkedin.com/posts/ada_1",
                "author": {"name": "Ada Example"},
            }
        ],
        "hasMore": False,
    }
    return HttpResponse(
        200,
        {"content-type": "application/json", "X-Treg-Cost-Micro": "1500"},
        json.dumps(body).encode(),
    )


async def bound(conn, tmp_path, *, clients=None, wire=None):
    storage = FsStorage(tmp_path)
    op, scope, cid = await setup(conn, storage)
    scope = replace(scope, catalog_version="v4", input_refs={"quality_recipe_version": 43})
    parent = await execution(conn, op, scope.project_id)
    await bind_execution(
        conn,
        op,
        execution_id=parent,
        context_id=cid,
        role="account_research",
        limits=Allowance(20, 40, 4),
    )
    rt = runtime(conn, scope, storage, wire or ScriptedTransport([]))
    rt.clients = clients if clients is not None else TregClients()

    @asynccontextmanager
    async def connections():
        yield conn

    ctx = ToolContext(
        workspace_id=scope.workspace_id,
        actor="agent",
        conn_factory=connections,
        execution_id=ExecutionId(parent),
        operation_id=OperationId(uuid4()),
    )
    return rt, ctx, storage, scope, parent, connections


def test_v3_lists_new_jobs_not_discover_media(tmp_path):
    async def case():
        async with rollback_conn() as conn:
            rt, *_ = await bound(conn, tmp_path)
            names = {c["operation"] for c in AcquireResearchToolV3(rt).capabilities()}
            assert {"linkedin_activity", "company_linkedin_posts", "find_podcasts"} <= names
            assert "discover_media" not in names and "read_media" in names

    run_async(case())


def test_v3_runs_linkedin_activity_and_saves_result(tmp_path):
    async def case():
        async with rollback_conn() as conn:
            wire = ScriptedTransport([li_page()])
            rt, ctx, storage, scope, parent, connections = await bound(conn, tmp_path, wire=wire)
            tool = AcquireResearchToolV3(rt)
            inputs = AcquireResearchInputV3(
                operation="linkedin_activity",
                arguments={"profile": "https://www.linkedin.com/in/ada", "kind": "posts"},
            )
            result = await tool.invoke(inputs, ctx)
            assert result.references["status"] == "completed", result
            assert "fetchinio.linkedin.user.posts" in wire.requests[0].url
            backend = research_backend(BackendProtocol(), connections, storage, scope, parent)
            view = await backend.aread(result.references["result_path"])
            assert view.error is None
            # Recipe 43's file view is a one-line header, then the saved JSON.
            saved = json.loads(view.file_data["content"].split("\n", 1)[1])
            assert saved["state"] == "complete" and saved["n_results"] == 1
            assert saved["posts"][0]["text"] == "We moved our SOC to a hunt-first model."
            cost = (
                await conn.execute(
                    text(
                        "SELECT sum(cost_usd) FROM provider_call_ledger WHERE provider='treg' "
                        "AND phase='result' AND entity_research_job_id=:job"
                    ),
                    {"job": scope.job_id},
                )
            ).scalar_one()
            assert float(cost) == 0.0015
            # The raw page is a provider record the agent can cite with a JSON pointer.
            body = (
                await conn.execute(
                    text(
                        "SELECT count(*) FROM arv2_evidence_source WHERE workspace_id=:ws "
                        "AND job_id=:job AND kind='provider_record'"
                    ),
                    {"ws": scope.workspace_id, "job": scope.job_id},
                )
            ).scalar_one()
            assert body >= 1
            replay = await tool.invoke(inputs, ctx)
            assert replay.references["replayed"] is True and len(wire.requests) == 1

    run_async(case())


def test_missing_treg_key_is_a_gap(tmp_path):
    class NoKey(TregClients):
        treg_token = None

    async def case():
        async with rollback_conn() as conn:
            rt, ctx, *_ = await bound(conn, tmp_path, clients=NoKey())
            result = await AcquireResearchToolV3(rt).invoke(
                AcquireResearchInputV3(operation="x_posts", arguments={"handle": "ada"}), ctx
            )
            assert result.references["status"] == "refused"
            assert result.references["error_code"] == "treg_key_missing"

    run_async(case())


def test_x_post_link_reads_its_video_file():
    from clue_api.arv2.media_tools import ReadMediaArgs, read_media
    from tests.arv2.test_media_store_db import (
        MediaClients,
        deepgram_speech,
        embeddings,
        offline_audio,
        seeded,
    )

    class XClients(MediaClients):
        treg_token = SecretStr("treg-test-token")

    tweet = {
        "legacy": {
            "extended_entities": {
                "media": [
                    {
                        "video_info": {
                            "variants": [
                                {
                                    "content_type": "video/mp4",
                                    "bitrate": 2176000,
                                    "url": "https://video.twimg.com/ext_tw_video/1/high.mp4",
                                }
                            ]
                        }
                    }
                ]
            }
        }
    }

    async def case():
        async with rollback_conn() as conn:
            rt = await seeded(conn)
            rt.clients = XClients()
            wire = ScriptedTransport(
                [
                    HttpResponse(
                        200,
                        {"content-type": "application/json", "X-Treg-Cost-Micro": "1880"},
                        json.dumps(tweet).encode(),
                    ),
                    offline_audio(),
                    offline_audio(),
                    deepgram_speech("We hunt once, then automate."),
                    embeddings(),
                ]
            )
            rt._transport_factory = lambda: wire
            result = await read_media(
                rt, ReadMediaArgs(url="https://x.com/ada/status/123", purpose="Hear them")
            )
            assert result["state"] == "available", result
            assert "scrapecreators.x.v1-twitter-tweet" in wire.requests[0].url
            assert wire.requests[1].url.startswith("https://video.twimg.com/")

    run_async(case())


def treg_reply(value, status=200, *, treg_error=False):
    headers = {"content-type": "application/json", "X-Treg-Cost-Micro": "0"}
    if treg_error:
        headers["X-Treg-Error"] = "1"
    return HttpResponse(status, headers, json.dumps(value).encode())


LINKEDIN = AcquireResearchInputV3(
    operation="linkedin_activity",
    arguments={"profile": "https://www.linkedin.com/in/ada", "kind": "posts"},
)


def test_unreadable_history_is_refused_and_an_identical_call_reads_again(tmp_path):
    """A failure on our side is not the answer for the job: repeating the identical call runs it
    again (a new attempt), and once it has been read, repeating replays without paying."""

    async def case():
        async with rollback_conn() as conn:
            wire = ScriptedTransport([treg_reply({"error": "Upstream timeout"}), li_page()])
            rt, ctx, *_ = await bound(conn, tmp_path, wire=wire)
            tool = AcquireResearchToolV3(rt)
            first = (await tool.invoke(LINKEDIN, ctx)).references
            assert first["status"] == "refused" and first["error_code"] == "history_unavailable"
            assert "Upstream timeout" in first["preview"][0]["snippet"]
            ctx = replace(ctx, operation_id=OperationId(uuid4()))
            second = (await tool.invoke(LINKEDIN, ctx)).references
            assert second["status"] == "completed" and second["replayed"] is False
            assert second["error_code"] is None and second["result_count"] == 1
            assert second["operation_id"] != first["operation_id"]
            ctx = replace(ctx, operation_id=OperationId(uuid4()))
            third = (await tool.invoke(LINKEDIN, ctx)).references
            assert third["replayed"] is True and third["operation_id"] == second["operation_id"]
            assert len(wire.requests) == 2

    run_async(case())


def test_partial_history_is_completed_with_its_code_and_can_be_read_again(tmp_path):
    async def case():
        async with rollback_conn() as conn:
            more = {
                "posts": [
                    {
                        "id": "urn:li:activity:7",
                        "content": "Part one.",
                        "date": "2026-10-07T10:00:00Z",
                        "shareUrl": "https://www.linkedin.com/posts/ada_7",
                    }
                ],
                "paginationToken": "p2",
                "hasMore": True,
            }
            wire = ScriptedTransport(
                [treg_reply(more), treg_reply({"error": "Upstream timeout"}), li_page()]
            )
            rt, ctx, *_ = await bound(conn, tmp_path, wire=wire)
            tool = AcquireResearchToolV3(rt)
            first = (await tool.invoke(LINKEDIN, ctx)).references
            assert first["status"] == "completed" and first["error_code"] == "history_partial"
            assert "not the whole history" in first["preview"][0]["snippet"]
            ctx = replace(ctx, operation_id=OperationId(uuid4()))
            second = (await tool.invoke(LINKEDIN, ctx)).references
            assert second["status"] == "completed" and second["error_code"] is None
            assert len(wire.requests) == 3

    run_async(case())


def test_treg_out_of_credit_stops_every_later_treg_job(tmp_path):
    async def case():
        async with rollback_conn() as conn:
            wire = ScriptedTransport(
                [treg_reply({"detail": "insufficient_balance"}, 402, treg_error=True)]
            )
            rt, ctx, *_ = await bound(conn, tmp_path, wire=wire)
            tool = AcquireResearchToolV3(rt)
            first = (await tool.invoke(LINKEDIN, ctx)).references
            assert first["status"] == "refused" and first["error_code"] == "provider_halted"
            assert "out of credit" in first["preview"][0]["snippet"]
            ctx = replace(ctx, operation_id=OperationId(uuid4()))
            other = AcquireResearchInputV3(operation="x_posts", arguments={"handle": "ada"})
            second = (await tool.invoke(other, ctx)).references
            assert second["status"] == "refused"
            assert second["error_code"].startswith("provider_halted")
            assert len(wire.requests) == 1  # the X job never reached treg

    run_async(case())
