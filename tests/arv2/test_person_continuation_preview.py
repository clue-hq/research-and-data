"""Offline isolation/retention checks; these do not simulate research quality."""

import asyncio
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest
from pydantic import SecretStr

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
import continue_person_research as preview  # noqa: E402

from clue_api.arv2.calls import ProviderCaller  # noqa: E402
from clue_api.arv2.exa_client import ExaClient  # noqa: E402
from clue_api.arv2.sinks import FileRawSink, JsonlLedger  # noqa: E402
from clue_api.arv2.transport import HttpResponse, ScriptedTransport  # noqa: E402


def read_source(inputs, path):
    pieces = []
    while path:
        body = json.loads((inputs / path.lstrip("/")).read_text())
        pieces.extend(segment["text"] for segment in body["text_segments"])
        path = body["next_path"]
    return "".join(pieces)


def test_complete_result_fields_and_pagination_survive(tmp_path):
    evidence = preview.EvidenceFiles(tmp_path)
    hit = {
        "url": "https://example.test/profile",
        "text": "Long source " * 3000,
        "highlights": ["Small excerpt"],
        "entities": [{"name": "A project"}],
        "extras": {"links": ["https://example.test/project"]},
        "future_field": "retained",
    }
    raw = {"output": {"content": "A dossier"}, "results": [hit] * 35}
    rows = evidence.response("saved", raw)
    evidence.index()
    assert json.loads(read_source(tmp_path, f"/evidence/{rows[2]['source_id']}/0.json")) == hit
    assert json.loads(read_source(tmp_path, f"/evidence/{rows[0]['source_id']}/0.json")) == raw
    first = json.loads((tmp_path / "evidence/index/0.json").read_text())
    last = json.loads((tmp_path / first["next_path"].lstrip("/")).read_text())
    assert len(first["sources"]) + len(last["sources"]) == 37
    assert last["next_path"] is None


def test_prepare_copies_context_not_comparison_answers(tmp_path):
    source, out = tmp_path / "prior", tmp_path / "trial"
    preview.save(
        source / "inputs/research/context.json",
        {
            "person_assignment": {"name": "Dana"},
            "target": {"name": "Acme"},
            "seller_name": "Seller",
            "run_date": "2026-09-24",
        },
    )
    preview.save(source / "baseline/secret-answer.json", {"answer": "DO NOT EXPOSE"})
    response = tmp_path / "response.json"
    preview.save(response, {"requestId": "initial", "output": {"content": "Original"}})
    preview.prepare(source, response, out)
    assert (out / "initial-response.original.json").read_bytes() == response.read_bytes()
    assert "DO NOT EXPOSE" not in "".join(
        p.read_text() for p in (out / "inputs").rglob("*") if p.is_file()
    )
    with pytest.raises(ValueError, match="fresh output"):
        preview.prepare(source, response, out)


def test_provider_receipt_raw_and_dedup_with_changed_purpose(tmp_path):
    raw = {
        "requestId": "test-request",
        "costDollars": {"total": 0.005},
        "results": [
            {
                "url": "https://example.test/page",
                "text": "Original passage",
                "entities": [{"name": "Extra field"}],
            }
        ],
    }
    transport = ScriptedTransport([HttpResponse(200, {}, json.dumps(raw).encode())])
    caller = ProviderCaller(
        transport=transport,
        raw_sink=FileRawSink(tmp_path / "raw"),
        ledger=JsonlLedger(tmp_path / "ledger.jsonl"),
        now=lambda: datetime.now(UTC),
    )
    acquisitions = preview.Acquisitions(tmp_path, ExaClient(caller, SecretStr("offline")), None)

    async def calls():
        return await asyncio.gather(
            acquisitions.acquire_research_evidence("search_web", {"query": "Dana project"}, "one"),
            acquisitions.acquire_research_evidence("search_web", {"query": "Dana project"}, "two"),
        )

    receipts = [json.loads(value) for value in asyncio.run(calls())]
    assert len(transport.requests) == 1
    assert receipts[0]["result_path"] == receipts[1]["result_path"]
    assert receipts[1]["replayed"]
    receipt = json.loads((tmp_path / "inputs" / receipts[0]["result_path"].lstrip("/")).read_text())
    assert receipt["request_id"] == "test-request"
    assert receipt["ledger_row_id"]
    assert Path(receipt["raw_ref"]).is_file()
    assert json.loads(next((tmp_path / "responses").glob("*.json")).read_text()) == raw


def test_unknown_outcome_cannot_be_repurchased(tmp_path):
    class Fails:
        count = 0

        def search(self, **kwargs):
            self.count += 1
            raise TimeoutError()

    exa = Fails()
    acquisitions = preview.Acquisitions(tmp_path, exa, None)

    async def calls():
        first = await acquisitions.acquire_research_evidence("search_web", {"query": "Dana"}, "x")
        second = await acquisitions.acquire_research_evidence("search_web", {"query": "Dana"}, "y")
        return json.loads(first), json.loads(second)

    first, second = asyncio.run(calls())
    assert first["status"] == second["status"] == "outcome_unknown"
    assert exa.count == 1
    assert len(list((tmp_path / "errors").glob("*.json"))) == 1


def test_publisher_transcript_reused_without_transcription(tmp_path, monkeypatch):
    from clue_api.arv2.media_resolution import Resolution

    monkeypatch.setattr(
        preview,
        "resolve",
        lambda *args, **kw: Resolution("resolved", transcript="Publisher transcript"),
    )
    reader = preview.media_reader(tmp_path, None, None, {})
    result = reader(preview.ReadMedia(url="https://example.test/interview"))
    assert result["resolution"]["transcript"] == "Publisher transcript"


def test_native_media_uses_configured_client_and_retains_transcript(tmp_path, monkeypatch):
    from clue_api.arv2.gemini_media_client import Transcript
    from clue_api.arv2.media_resolution import Resolution
    from clue_api.arv2.media_types import Candidate

    candidate = Candidate(
        url="https://www.youtube.com/watch?v=abcdefghijk",
        family="youtube",
        canonical_key="youtube:abcdefghijk",
        duration_s=60,
    )
    monkeypatch.setattr(
        preview, "resolve", lambda *args, **kw: Resolution("resolved", candidates=(candidate,))
    )
    calls = []

    def transcribe(url, **kwargs):
        calls.append((url, kwargs))
        return Transcript(model="configured-model", text="Original spoken words")

    reader = preview.media_reader(
        tmp_path,
        None,
        SimpleNamespace(transcribe_video=transcribe),
        {
            "person_assignment": {"name": "Dana"},
            "target": {"name": "Acme"},
        },
    )
    result = reader(preview.ReadMedia(url=candidate.url))
    assert calls[0][1]["duration_s"] == 60
    assert result["transcript"]["text"] == "Original spoken words"
    assert result["resolution"]["candidates"][0]["url"] == candidate.url


@pytest.mark.parametrize("failure", ["exception", "empty"])
def test_transcription_failure_is_distinct_and_never_blindly_retried(
    tmp_path, monkeypatch, failure
):
    from clue_api.arv2.gemini_media_client import Transcript
    from clue_api.arv2.media_resolution import Resolution
    from clue_api.arv2.media_types import Candidate

    candidate = Candidate(url="https://youtu.be/abcdefghijk", family="youtube", duration_s=60)
    monkeypatch.setattr(preview, "resolve", lambda *a, **kw: Resolution("resolved", (candidate,)))
    calls = []

    def transcribe(*args, **kwargs):
        calls.append(args)
        if failure == "exception":
            raise TimeoutError("Do not expose provider error text")
        return Transcript(model="configured-model", text="")

    reader = preview.media_reader(
        tmp_path,
        None,
        SimpleNamespace(transcribe_video=transcribe),
        {
            "person_assignment": {"name": "Dana"},
            "target": {"name": "Acme"},
        },
    )
    result = reader(preview.ReadMedia(url=candidate.url))
    assert result["state"] == "transcription_failed" and result["transcription_attempted"]
    assert len(calls) == 1
    assert "Do not expose" not in json.dumps(result)
