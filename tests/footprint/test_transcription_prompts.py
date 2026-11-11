"""The Gemini transcription prompts (founder-approved wording, 2026-11-12).

Gemini is no longer told the person is in the recording, nor shown their name on a speaker label:
on a wrong or namesake recording that invites it to put the name on someone (in r44a it put a Google
Cloud panelist's lines under Ann). It names a speaker only when the recording says or shows who they
are. The QUOTES and BUYING_AND_VENDOR_SIGNALS sections are gone: nothing used them as evidence.
"""

from __future__ import annotations

from clue_api.footprint.gemini_media_client import (
    SpeakerContext,
    long_transcription_prompt,
    short_transcription_prompt,
)

ANN = SpeakerContext(
    person_name="Ann Barron-DiCamillo", person_role="EVP, Global CISO", organisation="U.S. Bank"
)


def test_the_short_prompt_asks_for_the_speakers_and_the_whole_transcript_only():
    prompt = short_transcription_prompt(ANN)
    assert "## META" in prompt and "## TRANSCRIPT" in prompt
    assert "## QUOTES" not in prompt and "BUYING_AND_VENDOR_SIGNALS" not in prompt
    assert "A full transcript of the WHOLE recording" in prompt


def test_the_short_prompt_does_not_say_the_person_is_there():
    prompt = short_transcription_prompt(ANN)
    assert (
        "We are researching Ann Barron-DiCamillo, EVP, Global CISO at U.S. Bank. "
        "They may or may not speak in this recording." in prompt
    )
    assert "add a name only when the recording says or shows who they are" in prompt
    assert "[03:41] S2 (Jane Doe): <verbatim words>" in prompt
    assert "S2 (Ann Barron-DiCamillo)" not in prompt and "The subject is" not in prompt


def test_the_identity_evidence_line_stays_for_verify_speaker():
    assert (
        "guest_identity_evidence: <verbatim words in the audio, or text on screen, that identify "
        "Ann Barron-DiCamillo; else NOT STATED>" in short_transcription_prompt(ANN)
    )


def test_the_long_prompt_does_not_say_the_person_is_there():
    prompt = long_transcription_prompt(ANN)
    assert "they may or may not speak in it" in prompt
    assert "Add a name only when the recording says who the speaker is" in prompt
    assert "[03:41] S2 (Jane Doe): <verbatim words>" in prompt
    assert "Ann Barron-DiCamillo:" not in prompt and "main subject" not in prompt


def test_an_account_job_names_the_company_not_a_person():
    account = SpeakerContext(person_name="", organisation="U.S. Bank")
    for prompt in (short_transcription_prompt(account), long_transcription_prompt(account)):
        assert "We are researching U.S. Bank." in prompt
        assert "may or may not speak" not in prompt and "researching the speaker" not in prompt
