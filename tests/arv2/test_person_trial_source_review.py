"""Source-review handoff checks without live providers or benchmark-specific hints."""

import asyncio
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

from pydantic import SecretStr

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
import person_trial_source_review as review  # noqa: E402

from clue_api.arv2.calls import ProviderCaller  # noqa: E402
from clue_api.arv2.exa_client import ExaClient  # noqa: E402
from clue_api.arv2.sinks import FileRawSink, JsonlLedger  # noqa: E402
from clue_api.arv2.transport import HttpResponse, ScriptedTransport  # noqa: E402


def test_new_highlights_on_same_url_reach_tool_result_and_replay(tmp_path):
    first = {"url": "https://example.test/person", "text": "Original profile"}
    second = {**first, "highlights": ["Created a community project"], "future_field": "Retain me"}
    payloads = [
        {"requestId": "first", "results": [first]},
        {
            "requestId": "second",
            "costDollars": {"total": 0.05},
            "output": {"content": "Detailed research with source references. " * 100},
            "results": [second],
        },
    ]
    transport = ScriptedTransport([HttpResponse(200, {}, json.dumps(p).encode()) for p in payloads])
    caller = ProviderCaller(
        transport=transport,
        raw_sink=FileRawSink(tmp_path / "raw"),
        ledger=JsonlLedger(tmp_path / "ledger.jsonl"),
        now=lambda: datetime.now(UTC),
    )
    instructions = tmp_path / "instructions"
    instructions.mkdir()
    (instructions / "exa-system.md").write_text("Research the selected person.")
    acquisitions = review.FreshSourceAcquisitions(
        tmp_path, ExaClient(caller, SecretStr("offline")), None
    )

    async def calls():
        initial = await acquisitions.acquire_research_evidence(
            "search_web", {"query": "Dana profile"}, "Initial discovery"
        )
        deeper = await acquisitions.acquire_research_evidence(
            "research_deep", {"charter": "Investigate Dana"}, "Deeper research"
        )
        replay = await acquisitions.acquire_research_evidence(
            "research_deep", {"charter": "Investigate Dana"}, "Reuse"
        )
        return [json.loads(s) for s in (initial, deeper, replay)]

    initial, deeper, replay = asyncio.run(calls())
    assert len(transport.requests) == 2
    assert initial["source_review"]["sources"][0]["highlights"] == []
    row = deeper["source_review"]["sources"][0]
    assert row["previous_capture_in_this_trial"] is True
    assert row["added_fields"] == ["future_field", "highlights"]
    assert row["highlights"] == second["highlights"]
    assert row["changed_fields"] == []
    assert (tmp_path / "inputs" / row["full_source_path"].lstrip("/")).exists()
    assert replay["replayed"] is True
    assert replay["source_review"] == deeper["source_review"]
    assert any(json.loads(f.read_text()) == payloads[1] for f in (tmp_path / "responses").glob("*"))


def test_changed_fields_and_unknown_fields_are_visible_without_url_dedup():
    first = {"url": "https://example.test/person", "text": "Old", "highlights": ["Old excerpt"]}
    second = {**first, "text": "New", "highlights": ["New excerpt"], "entities": [{"name": "X"}]}
    history = {}
    nav = {"sources": [{"origin_locator": "results/0", "path": "/evidence/version/0.json"}]}
    review.source_overviews({"results": [first]}, nav, history)
    row = review.source_overviews({"results": [second]}, nav, history)[0]
    assert row["changed_fields"] == ["highlights", "text"]
    assert row["added_fields"] == ["entities"]
    assert row["highlights"] == ["New excerpt"]
    assert "entities" in row["available_fields"]


def test_overview_pagination_retains_every_highlight(tmp_path):
    payload = {
        "requestId": "pages",
        "results": [
            {"url": f"https://example.test/{i}", "highlights": [f"Distinct finding {i}"]}
            for i in range(24)
        ],
    }
    transport = ScriptedTransport([HttpResponse(200, {}, json.dumps(payload).encode())])
    caller = ProviderCaller(
        transport=transport,
        raw_sink=FileRawSink(tmp_path / "raw"),
        ledger=JsonlLedger(tmp_path / "ledger.jsonl"),
        now=lambda: datetime.now(UTC),
    )
    acquisitions = review.FreshSourceAcquisitions(
        tmp_path, ExaClient(caller, SecretStr("offline")), None
    )
    reply = json.loads(
        asyncio.run(acquisitions.acquire_research_evidence("search_web", {"query": "Dana"}, "x"))
    )
    page = reply["source_review"]
    rows = []
    while True:
        rows.extend(page["sources"])
        if page["next_path"] is None:
            break
        page = json.loads((tmp_path / "inputs" / page["next_path"].lstrip("/")).read_text())
    assert len(rows) == 24
    assert [r["highlights"] for r in rows] == [r["highlights"] for r in payload["results"]]


def test_media_candidates_are_inline_actionable_and_preserved_on_replay(tmp_path):
    raw = {
        "state": "ambiguous",
        "transcription_attempted": False,
        "resolution": {
            "gaps": ["multiple_explicit_recordings"],
            "candidates": [
                {
                    "url": "https://example.test/one.mp3",
                    "family": "audio",
                    "identity_evidence": ["explicit_embed:https://example.test/episode"],
                },
            ],
        },
    }
    calls = []

    def media(args):
        calls.append(args.url)
        return raw

    acquisitions = review.FreshSourceAcquisitions(tmp_path, None, media)

    async def run():
        return [
            json.loads(
                await acquisitions.acquire_research_evidence(
                    "read_media", {"url": "https://example.test/episode"}, "Interview"
                )
            )
            for _ in range(2)
        ]

    first, replay = asyncio.run(run())
    assert calls == ["https://example.test/episode"]
    assert first["media_review"] == replay["media_review"]
    candidate = first["media_review"]["candidates"][0]
    assert candidate["type"] == "audio" and candidate["origin"]
    assert candidate["status"] == "candidate_not_yet_attempted"
    assert "operation='read_media'" in first["media_review"]["next_action"]
    assert json.loads(next((tmp_path / "responses").glob("*.json")).read_text()) == raw


def test_media_outcomes_distinguish_missing_unattempted_failed_and_available():
    missing = review.media_overview({"state": "unsupported", "resolution": {"candidates": []}})
    assert missing["transcription_attempted"] is False
    assert "does not establish" in missing["next_action"]
    failed = review.media_overview(
        {"state": "transcription_failed", "transcription_attempted": True}
    )
    assert failed["transcription_attempted"] and not failed["transcript_available"]
    assert "before any paid retry" in failed["next_action"]
    available = review.media_overview({"state": "resolved", "resolution": {"transcript": "Speech"}})
    assert available["transcript_available"] and not available["transcription_attempted"]
