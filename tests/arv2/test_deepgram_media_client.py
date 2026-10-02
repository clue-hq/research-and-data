"""Offline protocol, faithful segmentation and no-repurchase checks."""

import json
from decimal import Decimal
from urllib.parse import parse_qs, urlsplit

import pytest
from pydantic import SecretStr

from clue_api.arv2.deepgram_media_client import DeepgramMediaClient, parse_response
from clue_api.arv2.media_acquisition import assess_transcript
from clue_api.arv2.sinks import MemoryLedger, MemoryRawSink
from clue_api.arv2.transport import HttpResponse, ScriptedTransport
from clue_config import Secrets
from tests.arv2.test_media_research import caller


def speech():
    words = [
        {"word": "hello", "punctuated_word": "Hello,", "speaker": 0, "start": 0.125, "end": 0.3},
        {"word": "yes", "punctuated_word": "yes.", "speaker": 1, "start": 0.4, "end": 0.6},
    ]
    return {
        "metadata": {"duration": 2, "request_id": "fixture", "sha256": "expected"},
        "results": {
            "channels": [{"alternatives": [{"words": words}]}],
            "utterances": [
                {
                    "speaker": 0,
                    "start": 0.125,
                    "end": 0.6,
                    "transcript": "Hello, yes.",
                    "words": words,
                }
            ],
        },
    }


def test_word_speaker_changes_and_fractional_alignment_survive():
    result = parse_response(speech(), expected_hash="expected")
    text, segments, quality = assess_transcript(result)
    assert text == "Hello,\nyes."
    assert [s.speaker for s in segments] == ["Speaker 0", "Speaker 1"]
    assert [(s.time_s, s.end_time_s) for s in segments] == [(0.125, 0.3), (0.4, 0.6)]
    assert all(s.timing == "aligned" and s.entity_id is None for s in segments)
    assert [text[s.start : s.end] for s in segments] == ["Hello,", "yes."]
    assert quality.coverage == "unknown"
    assert quality.diagnostics["provider_file_checksum_matches"] is True


@pytest.mark.parametrize("url", [None, "https://example.com/audio.mp3"])
def test_native_wire_ledger_and_saved_raw_response(url):
    wire = ScriptedTransport([HttpResponse(200, body=json.dumps(speech()).encode())])
    from datetime import UTC, datetime

    from clue_spend.calls import ProviderCaller

    ledger, raw = MemoryLedger(), MemoryRawSink()
    client = DeepgramMediaClient(
        ProviderCaller(transport=wire, raw_sink=raw, ledger=ledger, now=lambda: datetime.now(UTC)),
        SecretStr("secret"),
    )
    result = client.transcribe(
        audio=b"audio", mime="audio/mpeg", duration_s=2, expected_hash="expected", media_url=url
    )
    assert result.text == "Hello,\nyes."
    request = wire.requests[0]
    params = parse_qs(urlsplit(request.url).query)
    assert params["diarize_model"] == ["v2"] and "diarize" not in params
    assert params["filler_words"] == ["true"] and params["smart_format"] == ["false"]
    assert request.body == (json.dumps({"url": url}).encode() if url else b"audio")
    row = next(r for r in ledger.rows if r.phase == "result")
    assert row.provider_request_id == "fixture" and row.media_seconds == 2
    assert row.cost_usd == Decimal(2) * Decimal("0.0043") / 60
    assert row.extras["cost_source"] == "estimate"
    assert row.extras["invoice_verified"] is False
    record, body = raw.records[0]
    assert json.loads(body) == speech()
    assert record.request.headers["Authorization"] != "Token secret"


@pytest.mark.parametrize("duration", [0, 2.125, 2570])
def test_cost_uses_provider_duration_and_configured_rate(duration):
    from clue_api.arv2.deepgram_media_client import read_cost

    result = read_cost(
        HttpResponse(
            200,
            body=json.dumps(
                {"metadata": {"duration": duration, "request_id": "cost-fixture"}}
            ).encode(),
        ),
        usd_per_minute=Decimal("0.0052"),
    )
    assert result.cost_usd == Decimal(str(duration)) * Decimal("0.0052") / 60
    assert result.inferred and result.provider_request_id == "cost-fixture"


@pytest.mark.parametrize(
    "status,metadata", [(200, {}), (503, {"duration": 10}), (200, {"duration": -1})]
)
def test_missing_or_failed_metering_stays_unknown(status, metadata):
    from clue_api.arv2.deepgram_media_client import read_cost

    assert (
        read_cost(
            HttpResponse(status, body=json.dumps({"metadata": metadata}).encode()),
            usd_per_minute=Decimal("0.0043"),
        ).cost_usd
        is None
    )


def test_no_automatic_retry_after_failed_paid_attempt():
    wire = ScriptedTransport([HttpResponse(503, body=b'{"err_msg":"busy"}')])
    client = DeepgramMediaClient(caller(wire), SecretStr("secret"))
    with pytest.raises(ValueError, match="HTTP 503"):
        client.transcribe(audio=b"audio", mime="audio/wav", duration_s=2, expected_hash="x")
    assert len(wire.requests) == 1


def test_sparse_transcript_and_checksum_warning_are_visible():
    data = {
        "metadata": {"sha256": "other"},
        "results": {"channels": [{"alternatives": [{"transcript": "Actual speech."}]}]},
    }
    result = parse_response(data, expected_hash="expected")
    assert result.text == "Actual speech."
    assert result.segments[0].time_s is None and result.segments[0].speaker is None
    assert "provider_file_checksum_mismatch" in result.quality.warnings


def test_trial_key_alias_and_production_precedence(monkeypatch):
    monkeypatch.setenv("DEEPGRAM_API_KEY", "trial")
    monkeypatch.delenv("CLUE_DEEPGRAM_API_KEY", raising=False)
    assert Secrets(_env_file=None).deepgram_api_key.get_secret_value() == "trial"
    monkeypatch.setenv("CLUE_DEEPGRAM_API_KEY", "production")
    assert Secrets(_env_file=None).deepgram_api_key.get_secret_value() == "production"


def test_missing_utterances_or_speakers_do_not_drop_channel_words():
    body = speech()
    body["results"]["utterances"] = []
    for word in body["results"]["channels"][0]["alternatives"][0]["words"]:
        word.pop("speaker")
    result = parse_response(body)
    assert result.text == "Hello, yes."
    assert result.segments[0].speaker is None
    assert "utterance_word_mismatch_using_complete_word_stream" in result.quality.warnings


def test_job_client_clone_keeps_transcription_credentials():
    from clue_api.arv2.account_research_driver import _LiveClients
    from clue_api.arv2.gemini_media_client import MediaBudget
    from clue_config import Settings

    clients = _LiveClients(
        settings=Settings(_env_file=None),
        exa_api_key=SecretStr("fixture"),
        ai_ark_api_key=SecretStr("fixture"),
        gemini_api_key=SecretStr("fixture"),
        openrouter_api_key=SecretStr("fixture"),
        openrouter_base_url="https://fixture.test",
        deepgram_api_key=SecretStr("transcription"),
    )
    clone = clients.for_job(media_budget=MediaBudget(9000))
    client = clone.transcription(caller(ScriptedTransport([])))
    assert client.api_key.get_secret_value() == "transcription"
