"""The Jev speaker check: the three agreed questions, an answer per piece, never an exception."""

from __future__ import annotations

import json
from datetime import UTC, datetime

from pydantic import SecretStr

from clue_api.footprint.jev_client import (
    IS_SPEAKING_INSTRUCTIONS,
    PRESENCE_INSTRUCTIONS,
    SPEAKER_LABEL_INSTRUCTIONS,
    SpeakerCheck,
    check_speaker,
)
from clue_config.settings import Settings
from clue_spend.calls import ProviderCaller
from clue_spend.sinks import MemoryLedger, MemoryRawSink
from clue_spend.transport import HttpResponse, ScriptedTransport, TransportFailure

KEY = SecretStr("or-key")
MODEL = "typesafe/jev-1.14"
PERSON = {"name": "Ada Example", "employer": "Acme", "roles": ["CISO, Acme (2021-)"]}
RECORDING = {"show": "The Cyber World", "title": "Zero trust", "description": "Ada Example joins"}
LINES = ["[00:00] Speaker 0: Welcome.", "[00:05] Speaker 1: Thanks, I run security at Acme."]


def wire(*responses):
    transport = ScriptedTransport(list(responses))
    ledger = MemoryLedger()
    caller = ProviderCaller(
        transport=transport,
        raw_sink=MemoryRawSink(),
        ledger=ledger,
        now=lambda: datetime.now(UTC),
        sleep=lambda _: None,
    )
    return caller, transport, ledger


def answer(label="Speaker 1", p_label=0.89, presence="speaking", is_speaking=0.94, labels=None):
    labels = labels or ["Speaker 0", "Speaker 1"]
    probs = {lab: (p_label if lab == label else 0.0) for lab in labels}
    probs["none"] = round(1 - p_label, 2) if label != "none" else 1.0
    return HttpResponse(
        200,
        {"content-type": "application/json"},
        json.dumps(
            {
                "model": "typesafe/jev-1.14-20261014",
                "answers": {
                    "presence": {
                        "type": "choice",
                        "choice": presence,
                        "probabilities": {
                            "speaking": 0.97 if presence == "speaking" else 0.02,
                            "only_mentioned": 0.01,
                            "different_person": 0.02 if presence == "speaking" else 0.97,
                            "unclear": 0.0,
                        },
                    },
                    "is_speaking": {"type": "noul", "noul": is_speaking},
                    "speaker_label": {"type": "choice", "choice": label, "probabilities": probs},
                },
                "usage": {
                    "input_tokens": 12714,
                    "output_tokens": 131,
                    "cost": 0.000534,
                    "cost_details": {"upstream_inference_cost": 0.000534},
                },
                "id": "gen-dec-1",
            }
        ).encode(),
    )


def run(caller, lines=LINES, max_chars=120_000):
    return check_speaker(
        caller, KEY, MODEL, person=PERSON, recording=RECORDING, lines=lines, max_chars=max_chars
    )


def test_request_carries_the_agreed_questions():
    caller, transport, _ = wire(answer())
    run(caller)
    request = transport.requests[0]
    assert request.url == "https://openrouter.ai/api/alpha/decisions"
    body = json.loads(request.body)
    assert body["model"] == MODEL
    assert body["state"]["person_we_research"] == PERSON
    assert body["state"]["what_we_know_about_the_recording"] == RECORDING
    assert body["state"]["transcript_diarised"] == "\n".join(LINES)
    questions = body["questions"]
    assert questions["presence"]["instructions"] == PRESENCE_INSTRUCTIONS
    assert questions["is_speaking"]["instructions"] == IS_SPEAKING_INSTRUCTIONS
    assert questions["speaker_label"]["instructions"] == SPEAKER_LABEL_INSTRUCTIONS
    assert set(questions["speaker_label"]["criteria"]) == {"Speaker 0", "Speaker 1", "none"}
    assert PRESENCE_INSTRUCTIONS == (
        "Is the person we research (person_we_research) in this recording?"
    )
    assert SPEAKER_LABEL_INSTRUCTIONS.startswith(
        "Using the facts in person_we_research (their employer, roles and career), which speaker "
        "label is that exact person?"
    )


def test_answer_parsed():
    caller, _, ledger = wire(answer())
    check = run(caller)
    assert isinstance(check, SpeakerCheck) and check.state == "answered"
    assert check.presence == "speaking" and check.label == "Speaker 1"
    assert check.label_probabilities["Speaker 1"] == 0.89 and check.is_speaking == 0.94
    assert check.windows == 1 and check.model == "typesafe/jev-1.14-20261014"
    assert check.cost_usd == 0.000534
    assert [r for r in ledger.rows if r.phase == "result"][0].provider == "openrouter"


def test_namesake_answer_is_none():
    caller, *_ = wire(
        answer(label="none", p_label=0.0, presence="different_person", is_speaking=0.1)
    )
    check = run(caller)
    assert check.label == "none" and check.presence == "different_person"


def test_a_person_heard_in_one_piece_of_a_long_recording_is_reported_as_speaking():
    """Review I11, approved 2026-11-12. A long transcript is asked about in pieces. Averaging them
    reported Ann as a different person when she spoke only in the last of three pieces; now the
    headline is the piece where she most likely speaks, and every piece is listed with its time."""
    lines = [
        "[00:00] Speaker 0: " + "a" * 40,
        "[1:10:00] Speaker 0: " + "b" * 40,
        "[2:20:00] Speaker 1: " + "c" * 10,
        "[2:59:00] Speaker 1: " + "d" * 10,
    ]
    absent = answer(label="none", p_label=0.0, presence="different_person", is_speaking=0.05)
    caller, transport, _ = wire(absent, absent, answer(p_label=0.95, is_speaking=0.95))
    check = run(caller, lines=lines, max_chars=70)
    assert len(transport.requests) == 3 and check.windows == 3
    assert check.presence == "speaking" and check.label == "Speaker 1"
    assert check.is_speaking == 0.95 and check.label_probabilities["Speaker 1"] == 0.95
    assert [(p.start, p.end, p.presence, p.label) for p in check.pieces] == [
        ("00:00", "00:00", "different_person", "none"),
        ("1:10:00", "1:10:00", "different_person", "none"),
        ("2:20:00", "2:59:00", "speaking", "Speaker 1"),
    ]
    assert check.pieces[2].is_speaking == 0.95
    assert round(check.cost_usd, 6) == round(3 * 0.000534, 6)


def test_when_several_pieces_hear_them_the_headline_is_the_most_certain():
    lines = ["[00:00] Speaker 1: " + "a" * 40, "[00:10] Speaker 1: " + "b" * 40]
    caller, *_ = wire(answer(p_label=0.7, is_speaking=0.8), answer(p_label=0.9, is_speaking=0.96))
    check = run(caller, lines=lines, max_chars=70)
    assert check.is_speaking == 0.96 and check.label_probabilities["Speaker 1"] == 0.9
    assert [p.is_speaking for p in check.pieces] == [0.8, 0.96]


def test_a_recording_asked_about_in_one_go_lists_no_pieces():
    caller, *_ = wire(answer())
    assert run(caller).pieces == []


def test_error_returns_unavailable():
    caller, *_ = wire(*[TransportFailure("reset")] * 4)
    check = run(caller)
    assert check.state == "unavailable" and check.reason and check.label is None


def test_unparseable_answer_is_unavailable():
    caller, *_ = wire(HttpResponse(200, {"content-type": "application/json"}, b'{"oops": 1}'))
    assert run(caller).state == "unavailable"


def test_settings_defaults():
    settings = Settings(_env_file=None)
    assert settings.arv2_speaker_check_model.count("/") == 1
    assert settings.arv2_speaker_check_max_chars == 120_000
