"""The speaker check: ask Jev which speaker label in a diarised transcript is the person.

Jev (TypeSafe) writes no text; it answers typed questions with probabilities through OpenRouter's
Decisions API, ``POST /api/alpha/decisions`` with ``{model, state, questions}``. The three
questions and their wording were agreed with the founder on 2026-11-09 (ledger section 4.1;
15 of 15 right on the test recordings, runs agreeing within about 0.04).

The answer is a model's judgement for the research agent to weigh. Nothing here turns it into a
rule: no threshold, no refusal. Any failure returns ``state="unavailable"`` with a reason and the
transcript is still used.
"""

from __future__ import annotations

import json
import re
from typing import Any, Literal

from pydantic import BaseModel, Field, SecretStr

from clue_api.footprint.openrouter import OPENROUTER_REFERER, OPENROUTER_TITLE
from clue_spend.calls import CallSpec, ProviderCaller
from clue_spend.errors import ProviderTransportError
from clue_spend.openrouter import openrouter_cost_reader
from clue_spend.transport import json_request

DECISIONS_URL = "https://openrouter.ai/api/alpha/decisions"

STATE_NOTE = (
    "Speaker labels come from automatic diarisation and can be wrong; names may be misspelled "
    "by transcription."
)
PRESENCE_INSTRUCTIONS = "Is the person we research (person_we_research) in this recording?"
PRESENCE_CRITERIA = {
    "speaking": "The person we research speaks in the recording",
    "only_mentioned": "The person is talked about but does not speak",
    "different_person": "The speaker with this name is a different person (a namesake)",
    "unclear": "The transcript does not let us tell",
}
IS_SPEAKING_INSTRUCTIONS = "Does the person we research speak in this recording?"
IS_SPEAKING_CRITERIA = {
    "true": "The person we research is one of the voices in the transcript",
    "false": "They do not speak here, or the speaker is someone else with the same name",
}
SPEAKER_LABEL_INSTRUCTIONS = (
    "Using the facts in person_we_research (their employer, roles and career), which speaker "
    "label is that exact person? If the speaker who shares the name is someone else (a "
    "namesake), the answer is none."
)
NONE_CRITERION = (
    "No label is the person described in person_we_research: they do not speak, or the voice "
    "with that name belongs to a namesake"
)

_LABEL = re.compile(r"^\[[^\]]*\]\s*([^:]+):")


_STAMP = re.compile(r"^\[([^\]]*)\]")


class SpeakerPiece(BaseModel):
    """Jev's answer for one piece of a transcript too long to send whole, with the times the piece
    covers (its first and last line's timestamps)."""

    start: str | None = None
    end: str | None = None
    presence: str
    presence_probabilities: dict[str, float]
    is_speaking: float
    label: str
    label_probabilities: dict[str, float]


class SpeakerCheck(BaseModel):
    state: Literal["answered", "unavailable"]
    presence: str | None = None
    presence_probabilities: dict[str, float] = Field(default_factory=dict)
    is_speaking: float | None = None
    label: str | None = None
    label_probabilities: dict[str, float] = Field(default_factory=dict)
    windows: int = 0
    #: Each piece's own answer when the transcript was asked about in pieces (review I11): a person
    #: often speaks in one part of a long recording only.
    pieces: list[SpeakerPiece] = Field(default_factory=list)
    model: str | None = None
    cost_usd: float = 0.0
    reason: str | None = None


def _labels(lines: list[str]) -> list[str]:
    found: list[str] = []
    for line in lines:
        match = _LABEL.match(line)
        if match and match.group(1).strip() not in found:
            found.append(match.group(1).strip())
    return found


def _windows(lines: list[str], max_chars: int) -> list[list[str]]:
    windows: list[list[str]] = [[]]
    size = 0
    for line in lines:
        if windows[-1] and size + len(line) + 1 > max_chars:
            windows.append([])
            size = 0
        windows[-1].append(line)
        size += len(line) + 1
    return [w for w in windows if w]


def _ask(
    caller: ProviderCaller,
    api_key: SecretStr,
    model: str,
    *,
    person: dict[str, Any],
    recording: dict[str, Any],
    lines: list[str],
    labels: list[str],
) -> tuple[dict[str, Any], float]:
    body = {
        "model": model,
        "state": {
            "person_we_research": person,
            "what_we_know_about_the_recording": recording,
            "transcript_diarised": "\n".join(lines),
            "note": STATE_NOTE,
        },
        "questions": {
            "presence": {
                "type": "choice",
                "instructions": PRESENCE_INSTRUCTIONS,
                "criteria": PRESENCE_CRITERIA,
            },
            "is_speaking": {
                "type": "noul",
                "instructions": IS_SPEAKING_INSTRUCTIONS,
                "criteria": IS_SPEAKING_CRITERIA,
            },
            "speaker_label": {
                "type": "choice",
                "instructions": SPEAKER_LABEL_INSTRUCTIONS,
                "criteria": {
                    **{
                        label: f"{label} is the person described in person_we_research"
                        for label in labels
                    },
                    "none": NONE_CRITERION,
                },
            },
        },
    }
    result = caller.call(
        CallSpec(
            provider="openrouter",
            operation="decisions",
            label="footprint.speaker_check",
            request=json_request(
                "POST",
                DECISIONS_URL,
                json_body=body,
                headers={
                    "Authorization": f"Bearer {api_key.get_secret_value()}",
                    "HTTP-Referer": OPENROUTER_REFERER,
                    "X-Title": OPENROUTER_TITLE,
                },
                timeout_s=300,
            ),
            max_attempts=2,
            cost_reader=openrouter_cost_reader,
        )
    )
    if result.response.status != 200:
        raise ValueError(f"jev HTTP {result.response.status}")
    answer = json.loads(result.response.body)
    answers = answer["answers"]
    usage = answer.get("usage") or {}
    cost = (usage.get("cost_details") or {}).get("upstream_inference_cost", usage.get("cost"))
    return {
        "model": answer.get("model"),
        "presence": answers["presence"]["probabilities"],
        "is_speaking": float(answers["is_speaking"]["noul"]),
        "label": answers["speaker_label"]["probabilities"],
    }, float(cost or 0)


def _stamp(line: str) -> str | None:
    found = _STAMP.match(line)
    return found.group(1) if found else None


def _piece(answer: dict[str, Any], window: list[str]) -> SpeakerPiece:
    return SpeakerPiece(
        start=_stamp(window[0]),
        end=_stamp(window[-1]),
        presence=max(answer["presence"], key=answer["presence"].__getitem__),
        presence_probabilities=answer["presence"],
        is_speaking=answer["is_speaking"],
        label=max(answer["label"], key=answer["label"].__getitem__),
        label_probabilities=answer["label"],
    )


def check_speaker(
    caller: ProviderCaller,
    api_key: SecretStr,
    model: str,
    *,
    person: dict[str, Any],
    recording: dict[str, Any],
    lines: list[str],
    max_chars: int,
) -> SpeakerCheck:
    labels = _labels(lines)
    if not lines:
        return SpeakerCheck(state="unavailable", reason="empty_transcript")
    answers: list[tuple[dict[str, Any], list[str]]] = []
    cost = 0.0
    for window in _windows(lines, max_chars):
        try:
            answer, spent = _ask(
                caller,
                api_key,
                model,
                person=person,
                recording=recording,
                lines=window,
                labels=labels,
            )
        except (ProviderTransportError, ValueError, KeyError, TypeError) as exc:
            return SpeakerCheck(
                state="unavailable",
                reason=f"{type(exc).__name__}: {exc}"[:300],
                cost_usd=cost,
                windows=len(answers),
            )
        cost += spent
        answers.append((answer, window))
    pieces = [_piece(answer, window) for answer, window in answers]
    # Never an average (review I11, approved 2026-11-12): someone who speaks in one piece speaks
    # in the recording, so the headline is the piece where they most likely speak; every piece
    # is listed for the agent to weigh.
    best = max(pieces, key=lambda piece: piece.is_speaking)
    return SpeakerCheck(
        state="answered",
        presence=best.presence,
        presence_probabilities=best.presence_probabilities,
        is_speaking=best.is_speaking,
        label=best.label,
        label_probabilities=best.label_probabilities,
        windows=len(pieces),
        pieces=pieces if len(pieces) > 1 else [],
        model=answers[0][0]["model"],
        cost_usd=cost,
    )
