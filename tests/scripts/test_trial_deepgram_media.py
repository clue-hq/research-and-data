"""Offline checks for the isolated adapter; no synthetic provider-quality claims."""

import json

import pytest
from scripts.trial_deepgram_media import (
    parameters,
    read_cost,
    render,
    save,
    speaker_segments,
    transcribe,
)

from clue_spend.transport import HttpResponse


def test_batch_configuration_and_language_modes():
    defaults = parameters()
    assert defaults["diarize_model"] == "v2"
    assert "diarize" not in defaults  # Deepgram rejects both options together.
    assert defaults["utterances"] == "true"
    assert defaults["filler_words"] == "true"
    assert defaults["smart_format"] == "false"
    assert defaults["language"] == "en"
    auto = parameters("auto")
    assert auto["detect_language"] == "true" and "language" not in auto
    assert parameters("multi")["language"] == "multi"


def test_render_keeps_speaker_zero_exact_words_and_does_not_invent_missing_fields(tmp_path):
    word = {"word": "hello", "start": 0.1, "end": 0.4, "speaker": 0, "confidence": 0.99}
    save(tmp_path / "source.json", {"source": "https://example.org/episode", "duration_seconds": 2})
    response = {
        "metadata": {"diarize_info": {"model_uuid": "example"}},
        "results": {
            "channels": [{"alternatives": [{"words": [word, {"word": "hmm"}]}]}],
            "utterances": [
                {"start": 0.1, "end": 0.4, "speaker": 0, "transcript": "Hello <there>."},
                {"transcript": "Hmm."},
            ],
        },
    }
    save(tmp_path / "deepgram-response.json", response)
    original = (tmp_path / "deepgram-response.json").read_bytes()
    quality = render(tmp_path)
    assert quality["words_without_speaker"] == quality["words_without_timing"] == 1
    assert quality["speaker_labels"] == [0]
    assert quality["accuracy_assessed"] is False
    report = (tmp_path / "transcript.md").read_text()
    assert "00:00:00.100 – 00:00:00.400] Speaker 0" in report
    assert "Hello <there>." in report
    assert "time unknown" in report and "Speaker unknown" in report
    assert "Hello &lt;there&gt;." in (tmp_path / "transcript.vtt").read_text()
    assert json.loads((tmp_path / "words.json").read_text())[0] == word
    assert (tmp_path / "deepgram-response.json").read_bytes() == original


def test_plain_text_is_preserved_when_diarization_and_utterances_are_missing(tmp_path):
    save(tmp_path / "source.json", {"source": "local.wav", "duration_seconds": 100})
    save(
        tmp_path / "deepgram-response.json",
        {
            "results": {"channels": [{"alternatives": [{"transcript": "Actual words."}]}]},
        },
    )
    quality = render(tmp_path)
    assert "Actual words." in (tmp_path / "transcript.md").read_text()
    assert quality["warnings"]
    assert not quality["speaker_labels"]
    assert quality["last_word_end_seconds"] is None


def test_existing_submission_cannot_repurchase_even_if_result_is_missing(tmp_path):
    save(tmp_path / "submission.json", {"submitted_at": "prior attempt"})
    with pytest.raises(ValueError, match="attempt already exists"):
        transcribe(tmp_path)


def test_error_request_identity_is_retained_without_claiming_zero_cost():
    reading = read_cost(
        HttpResponse(
            408,
            body=json.dumps(
                {
                    "err_code": "SLOW_UPLOAD",
                    "request_id": "rejected-upload",
                }
            ).encode(),
        )
    )
    assert reading.provider_request_id == "rejected-upload"
    assert reading.cost_usd is None


def test_remote_file_mismatch_is_visible(tmp_path):
    save(
        tmp_path / "source.json",
        {
            "source": "https://example.org/audio",
            "duration_seconds": 10,
            "original_sha256": "expected",
            "audio_sha256": "converted",
        },
    )
    save(tmp_path / "request.json", {"delivery": "url"})
    save(tmp_path / "deepgram-response.json", {"metadata": {"sha256": "different"}})
    quality = render(tmp_path)
    assert quality["provider_file_checksum_matches"] is False
    assert any("checksum differs" in w for w in quality["warnings"])


def test_utterance_majority_label_does_not_relabel_short_interjections():
    words = [
        {"speaker": 0, "start": 1, "end": 2, "punctuated_word": "Welcome."},
        {"speaker": 1, "start": 2.1, "end": 3, "punctuated_word": "Thanks."},
        {"speaker": 0, "start": 3.2, "end": 4, "punctuated_word": "So,"},
    ]
    original = {"speaker": 0, "transcript": "Welcome. Thanks. So,", "words": words}
    segments = speaker_segments([original])
    assert [s["speaker"] for s in segments] == [0, 1, 0]
    assert segments[1]["start"] == 2.1 and segments[1]["end"] == 3
    assert " ".join(s["transcript"] for s in segments) == original["transcript"]
    assert original["words"] == words
