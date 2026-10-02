"""Gemini media understanding — the one ARV2 call that bypasses OpenRouter, and its neighbours.

Appendix A law 11's two-model recipe, ported from the proof-of-concept's ``z4a``/``z4b``/``z4d``/
``z4e``/``z6`` scripts. What the proof-of-concept actually measured is what this module is shaped
around:

* A **short** item (≤ ``short_max_seconds``) is transcribed in one cheap chat completion through
  OpenRouter, asking for the ``META`` / ``TRANSCRIPT`` / ``QUOTES`` /
  ``BUYING_AND_VENDOR_SIGNALS`` structure. Timestamps and speaker labels survive that path.
* A **long** item is not. One-shot transcription of the 42:49 podcast on the cheap model produced
  329 timestamped lines of which only 120 were unique — it re-emitted earlier dialogue under new
  timestamps from [12:41] onward. So a long item goes to the dedicated transcription model, and
  the *founder ruling* is that this one call leaves OpenRouter: OpenRouter serves neither
  ``gemini-3.5-transcribe`` nor a file upload, so the native endpoint
  ``https://generativelanguage.googleapis.com/v1beta`` is used with an ``x-goog-api-key`` header
  (never the ``?key=`` query parameter, which would land the key in every raw record's URL).
* Because the loop is a real and *silent* failure — a looped transcript reads perfectly well —
  :func:`detect_loops` runs over every transcript and every quote taken from one is verbatim-
  checked against the transcript body it claims to come from.

:func:`detect_loops` and :func:`verify_speaker` are module-level functions rather than client
methods: neither touches a provider, both are pure over a :class:`Transcript`, and a supervisor
must be able to re-measure a stored transcript without constructing a client or a transport.

Everything that does touch a provider goes through :class:`~clue_api.arv2.calls.ProviderCaller`,
so laws 1 and 2 (raw before parse, estimate before the wire) hold for the native endpoint exactly
as they do for OpenRouter.
"""

from __future__ import annotations

import base64
import json
import re
import time
import uuid
from collections.abc import Callable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from pydantic import SecretStr

from clue_api.arv2.calls import (
    CallCost,
    CallResult,
    CallSpec,
    CostReader,
    CostReading,
    ProviderCaller,
    SpendEstimate,
)
from clue_api.arv2.errors import Arv2Error
from clue_api.arv2.media_feeds_client import AudioFile as EnclosureAudioFile
from clue_api.arv2.openrouter import (
    openrouter_chat_request,
    openrouter_cost_reader,
    openrouter_embeddings_request,
    openrouter_halt_rule,
    openrouter_message_text,
)
from clue_api.arv2.sinks import LedgerRow, LedgerSink
from clue_api.arv2.text import MatchVerdict, substring_verdict
from clue_api.arv2.transport import HttpRequest, HttpResponse, json_request

#: The native Gemini API. Used **only** for the transcription leg (founder ruling); every other
#: model call in this module goes through OpenRouter.
GEMINI_BASE = "https://generativelanguage.googleapis.com/v1beta"

#: The resumable-upload entry point of the Files API. Note the ``/upload`` prefix — it is a
#: different host path from :data:`GEMINI_BASE`, not a suffix of it.
GEMINI_UPLOAD_URL = "https://generativelanguage.googleapis.com/upload/v1beta/files"

# -- the price sheet (``z_lib.PRICE``) --------------------------------------------------------
# The native endpoint reports tokens, never money, so cost for a native call is *computed*. These
# are the constants the proof-of-concept's ledger was built from; they reproduce its recorded
# $0.019284 for the 42:49 transcription exactly.
AUDIO_INPUT_USD_PER_1M = Decimal("0.30")
TEXT_INPUT_USD_PER_1M = Decimal("0.10")
TEXT_OUTPUT_USD_PER_1M = Decimal("0.40")
EMBED_USD_PER_1M = Decimal("0.20")
#: Gemini bills roughly 32 audio tokens per second of audio — the basis of the pre-spend estimate.
AUDIO_TOKENS_PER_SECOND = 32
#: Transcript output runs ~2.7 words/s of speech; four tokens per second is the estimate's headroom.
OUTPUT_TOKENS_PER_MEDIA_SECOND = 4
_PER_MILLION = Decimal(1_000_000)

# -- loop-detector thresholds (the ``z4b`` measurement) ---------------------------------------
#: Three identical lines in a row is a stuck decoder, whatever the rest of the transcript says.
LOOP_MAX_CONSECUTIVE_REPEAT = 3
#: Below this share of unique lines the transcript is re-emitting itself (z4b: 120/329 = 0.36).
LOOP_MIN_UNIQUE_RATIO = 0.6
#: The ratio rule needs enough lines to mean anything; a 6-line clip with a repeated "Yeah" is not
#: a loop.
LOOP_MIN_LINES_FOR_RATIO = 40
#: A local rule that catches a loop the whole-transcript ratio would dilute: a 30-line window with
#: fewer than 15 distinct lines is looping *there*, even if the transcript overall looks varied.
LOOP_WINDOW = 30
LOOP_WINDOW_MIN_UNIQUE = 15

# -- the identity evidence keys the two prompts emit ------------------------------------------
IDENTITY_META_KEYS = ("guest_identity_evidence", "narrator_identity_evidence")
#: What the prompts are told to write when the audio never names the person. Anything starting
#: with this is *absence of evidence*, and must never verify a speaker.
NOT_STATED = "NOT STATED"
#: The evidence a verdict cites when the item's own feed/page metadata named the person, rather
#: than the audio. Weaker than a spoken self-identification, and labelled as such.
METADATA_EVIDENCE = "named in the source metadata"

# -- upload/poll/timeout budgets --------------------------------------------------------------
MAX_FILE_POLLS = 60
FILE_POLL_INTERVAL_S = 5.0
UPLOAD_START_TIMEOUT_S = 120.0
UPLOAD_TIMEOUT_S = 1200.0
FILE_POLL_TIMEOUT_S = 60.0
#: The 42:49 transcription took 30 s, but a long item on a busy day does not; the native call is
#: given room to finish rather than be retried, because a retry pays for the audio twice.
GENERATE_TIMEOUT_S = 3000.0
SHORT_TIMEOUT_S = 1800.0
TEXT_CALL_TIMEOUT_S = 600.0
EMBEDDINGS_TIMEOUT_S = 300.0
LONG_MAX_OUTPUT_TOKENS = 32000
SHORT_MAX_OUTPUT_TOKENS = 32000
QUOTE_MAX_OUTPUT_TOKENS = 4000
#: A 41 MB upload is re-sent on a retry, so it gets two attempts rather than law 2's four.
UPLOAD_MAX_ATTEMPTS = 2
#: The transcription call pays for the whole audio again on every attempt and is given 3000 s to
#: finish, so law 2's default of four attempts is a worst case of ~3.3 hours and four charges for
#: one item. Two attempts still survives a single transient failure without that tail.
GENERATE_MAX_ATTEMPTS = 2

_SECTION_RE = re.compile(r"^##\s+([A-Za-z_]+)\s*$")
_TS_LINE_RE = re.compile(r"^\[(\d{1,2}:\d{2}(?::\d{2})?)\]\s*(.*)$")
_SPEAKER_SPLIT_RE = re.compile(r"^([^:]{1,60}):\s*(.*)$")
#: A speaker *label*, as opposed to a sentence that merely contains a colon. Either the prompt's
#: ``S2``/``S2 (Sanaz Yashar)`` form or one to four capitalised name words. Without this check
#: "So here is the thing: we bought it" would be split into speaker "So here is the thing" and
#: the words before the colon would be dropped from the transcript.
_SPEAKER_LABEL_RE = re.compile(
    r"^(?:S\d+(?:\s*\([^)]*\))?|[A-Z][\w.'\-]*(?:\s+[A-Z][\w.'\-]*){0,3})$"
)
_META_LINE_RE = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)\s*:\s*(.*)$")
_QUOTE_LINE_RE = re.compile(r'^-\s*"?\[?(\d{1,2}:\d{2}(?::\d{2})?)\]?"?\s*"(.+?)"\s*->\s*(.*)$')
_WHY_PREFIX_RE = re.compile(r"^why[^:]{0,40}:\s*", re.IGNORECASE)
_SENTENCE_RE = re.compile(r"(?<=[.!?])\s+")
_JSON_OBJECT_RE = re.compile(r"\{.*\}", re.DOTALL)


def _utcnow() -> datetime:
    return datetime.now(UTC)


# ---------------------------------------------------------------------------------- failures --


class GeminiMediaError(Arv2Error):
    """The provider answered, but not with something this client can use.

    Carries the ``raw_ref`` of the record law 1 already wrote, so the failure is replayable from
    disk rather than reconstructed from a log line.
    """

    def __init__(
        self, message: str, *, raw_ref: str | None = None, http_status: int | None = None
    ) -> None:
        super().__init__(f"{message} (raw_ref={raw_ref}, http_status={http_status})")
        self.raw_ref = raw_ref
        self.http_status = http_status


class MediaUploadFailed(GeminiMediaError):
    """The Files API never produced an ``ACTIVE`` file to transcribe."""


class MediaCeilingExceeded(Arv2Error):
    """The media-seconds ceiling would be exceeded — money *truth*, so it blocks (§2 item 3).

    Unlike the wrapper's record-only spend ceilings, this one is enforced: it is raised **before**
    any wire call, so the audio is never sent and never paid for. The client records the refusal
    on the ledger itself, because no provider call happened for the wrapper to write a row about.
    """

    def __init__(self, *, ceiling_s: int, used_s: int, requested_s: int) -> None:
        super().__init__(
            f"media ceiling exceeded: {used_s}s used + {requested_s}s requested > {ceiling_s}s"
        )
        self.ceiling_s = ceiling_s
        self.used_s = used_s
        self.requested_s = requested_s


# ------------------------------------------------------------------------------- value types --


@dataclass(frozen=True)
class AudioFile:
    """One media file on disk, with the duration the feed or the probe reported.

    ``duration_s`` is an input, never a guess made here: it decides the short/long route, the
    ceiling reservation and the pre-spend estimate, so it comes from whoever resolved the item.
    """

    path: Path
    duration_s: int
    mime_type: str = "audio/mpeg"
    #: OpenRouter's ``input_audio.format`` — the container name, not the MIME type.
    audio_format: str = "mp3"
    display_name: str = "arv2-media"


#: Content type as a feed or host serves it → the canonical ``(mime_type, audio_format)`` pair.
#: Two names are needed because they are different vocabularies: the native Gemini endpoint wants
#: a MIME type, and OpenRouter's ``input_audio.format`` wants the *container* name.
_CONTENT_TYPE_TO_AUDIO: Mapping[str, tuple[str, str]] = {
    "audio/mpeg": ("audio/mpeg", "mp3"),
    "audio/mp3": ("audio/mpeg", "mp3"),
    "audio/mp4": ("audio/mp4", "m4a"),
    "audio/x-m4a": ("audio/mp4", "m4a"),
    "audio/m4a": ("audio/mp4", "m4a"),
    "audio/wav": ("audio/wav", "wav"),
    "audio/x-wav": ("audio/wav", "wav"),
    "audio/ogg": ("audio/ogg", "ogg"),
    "audio/flac": ("audio/flac", "flac"),
    "audio/x-flac": ("audio/flac", "flac"),
}


def transcription_input_from_enclosure(
    audio: EnclosureAudioFile, *, display_name: str
) -> AudioFile:
    """Convert a downloaded enclosure into a transcription input — the lane's one cross-client seam.

    :class:`clue_api.arv2.media_feeds_client.AudioFile` describes *what was downloaded*, so its
    duration and content type are both optional: a feed that publishes no ``itunes:duration`` and
    a host that sends no ``Content-Type`` are ordinary. This module's :class:`AudioFile` describes
    *what will be paid for*, so both are required. The conversion is where those two facts meet,
    and it ships here rather than being left to a caller because both directions of sloppiness
    cost money or truth:

    * An unknown duration must **raise**, never default to ``0``. A zero reservation passes
      :meth:`MediaBudget.reserve` unconditionally and estimates the call at ``$0``, so the lane's
      one *enforced* money control would silently stop enforcing for exactly the items whose
      length nobody could read.
    * An unknown content type must **raise**, never default to ``mp3``. Sending an m4a to
      OpenRouter labelled ``mp3`` is a decode failure at best and a wrong transcript at worst.

    Refusing is cheap: the caller probes the file's real duration and retries, or skips the item
    and says so. Guessing is not.
    """
    if audio.duration_s is None:
        raise ValueError(
            f"{audio.path} has no known duration; transcription reserves and prices media "
            "seconds, so the duration must be resolved (probe the file) before it is sent"
        )
    declared = (audio.content_type or "").split(";")[0].strip().lower()
    mapped = _CONTENT_TYPE_TO_AUDIO.get(declared)
    if mapped is None:
        raise ValueError(
            f"{audio.path} declares content type {audio.content_type!r}, which is not a "
            f"transcribable audio container (known: {', '.join(sorted(_CONTENT_TYPE_TO_AUDIO))})"
        )
    mime_type, audio_format = mapped
    return AudioFile(
        path=audio.path,
        duration_s=audio.duration_s,
        mime_type=mime_type,
        audio_format=audio_format,
        display_name=display_name,
    )


@dataclass(frozen=True)
class SpeakerContext:
    """Who the research subject is, and whether anything outside the audio already named them."""

    person_name: str
    person_role: str = ""
    organisation: str = ""
    #: True when the feed entry, video title or page already named this person. Weaker evidence
    #: than a spoken self-identification, but it is evidence, and it is what a podcast guest
    #: usually has.
    named_in_metadata: bool = False

    @property
    def surname(self) -> str:
        """The last name token — what a spoken self-identification is checked against."""
        parts = self.person_name.split()
        return parts[-1] if parts else ""

    @property
    def description(self) -> str:
        """The subject as a prompt says it, skipping the parts nobody told us."""
        head = self.person_name or "the speaker"
        if self.person_role and self.organisation:
            return f"{head}, {self.person_role} at {self.organisation}"
        if self.person_role:
            return f"{head}, {self.person_role}"
        if self.organisation:
            return f"{head} of {self.organisation}"
        return head


@dataclass(frozen=True)
class TranscriptLine:
    """One line of a transcript. ``ts_s`` is ``None`` when the model emitted no timestamp."""

    ts_s: int | None
    speaker: str
    text: str


@dataclass(frozen=True)
class QuoteCandidate:
    """A quote the model attributed to the subject, with its verbatim verdict attached.

    Appendix A law 6: the check is an **annotation**, never a filter. A ``NOT_FOUND`` quote is
    kept and flagged, because "the model invented this" is a finding worth keeping.
    """

    text: str
    ts_s: int | None = None
    why: str = ""
    topic: str | None = None
    verdict: MatchVerdict | None = None
    #: Verbatim in the transcript **and** the speaker is verified. Both gates, or it is not usable.
    usable: bool = False


@dataclass(frozen=True)
class Transcript:
    """A transcript and everything read off the same response.

    ``text`` is the transcript **body only** — never the surrounding ``META``/``QUOTES`` sections.
    That is deliberate: a quote is verbatim-checked against this string, and if the model's own
    quote block were part of it, every quote would match itself and the check would be theatre.

    ``cost`` is the money view of the *one* call that produced the words: the OpenRouter
    completion on the short path, the native ``generateContent`` on the long one (which is where
    the media seconds are billed, so ``cost.media_seconds`` is the clip's length). It is ``None``
    only on a :class:`Transcript` built by :func:`parse_structured_transcript` directly, which
    parses text somebody else paid for.

    ``upload_costs`` are the long path's Files API legs — ``files.start``, ``files.upload`` and
    every ``files.get`` poll. They are free, and they are kept **separate** rather than summed
    into ``cost`` because they are separate ledger rows: three or four requests were made, and a
    caller reconciling this transcript against the ledger has to be able to find all of them. It
    is empty on the short path, which uploads nothing.
    """

    model: str
    text: str
    lines: tuple[TranscriptLine, ...] = ()
    meta: Mapping[str, str] = field(default_factory=dict)
    quotes: tuple[QuoteCandidate, ...] = ()
    has_timestamps: bool = False
    cost: CallCost | None = None
    upload_costs: tuple[CallCost, ...] = ()
    finish_reason: str | None = None


@dataclass(frozen=True)
class MinedQuotes:
    """The quotes one mining call returned, and what that call cost.

    One completion produces the whole set, so the cost belongs to the set: charging it to each
    quote would multiply the run's real spend by however many quotes the model happened to emit.

    It iterates and measures like the list it replaces, so ``for quote in quotes`` and
    ``len(quotes)`` keep meaning what they meant before the cost was carried.
    """

    quotes: tuple[QuoteCandidate, ...]
    cost: CallCost

    def __iter__(self) -> Iterator[QuoteCandidate]:
        return iter(self.quotes)

    def __len__(self) -> int:
        return len(self.quotes)

    def __getitem__(self, index: int) -> QuoteCandidate:
        return self.quotes[index]


@dataclass(frozen=True)
class LoopReport:
    """How much of a transcript is the model repeating itself.

    ``first_loop_ts_s`` is the timestamp of the first line that repeats a line already emitted —
    the proof-of-concept's ``first_duplicate_ts``, which for the looped run was also the point
    sustained repetition began. When ``tripped``, that is where the transcript stops being
    evidence and everything after it must be treated as unverified.
    """

    total_lines: int
    unique_lines: int
    unique_ratio: float
    max_consecutive_repeat: int
    first_loop_ts_s: int | None
    tripped: bool


@dataclass(frozen=True)
class SpeakerVerdict:
    """Is the person we researched actually the person speaking? ``evidence`` says why."""

    verified: bool
    evidence: str


@dataclass(frozen=True)
class EmbeddedChunk:
    """One retrieval chunk and its vector. Text only — Appendix A law 11 embeds no raw audio."""

    text: str
    start_ts_s: int | None
    vector: tuple[float, ...]


@dataclass(frozen=True)
class EmbeddedTranscript:
    """Every chunk of one transcript embedded in a single call, with that call's cost.

    ``dimensions`` is the width the provider actually **served**, read off the returned vectors —
    not the width that was asked for. The embeddings call retries without ``dimensions`` when the
    model rejects the Matryoshka truncation, so the two can differ, and reporting the request
    instead of the answer would mislabel every vector in the index.

    ``cost`` is ``None`` in exactly one case: a transcript with no lines to chunk, where no call
    is made at all. There is no ledger row to point at, and inventing a zero-cost one would put a
    request in the money trail that never happened.

    It iterates and measures like the list it replaces.
    """

    chunks: tuple[EmbeddedChunk, ...]
    cost: CallCost | None
    dimensions: int

    def __iter__(self) -> Iterator[EmbeddedChunk]:
        return iter(self.chunks)

    def __len__(self) -> int:
        return len(self.chunks)

    def __getitem__(self, index: int) -> EmbeddedChunk:
        return self.chunks[index]


# ------------------------------------------------------------------------------- the ceiling --


class MediaBudget:
    """The enforced media-seconds ceiling for one research run.

    Master plan §2 item 3 splits spend controls in two: money *caps* only record, money *truth*
    blocks. Media seconds are the latter here, because the audio is the spend — once it is on the
    wire it is paid for, so the refusal has to happen before the reservation is used.
    """

    def __init__(self, ceiling_s: int) -> None:
        self._ceiling_s = int(ceiling_s)
        self._used_s = 0

    @property
    def ceiling_s(self) -> int:
        return self._ceiling_s

    @property
    def used_s(self) -> int:
        """Seconds already committed by successful reservations in this run."""
        return self._used_s

    def reserve(self, seconds: int) -> None:
        """Commit ``seconds`` of media, or refuse the whole run's next call.

        Refusal raises :class:`MediaCeilingExceeded` and leaves ``used_s`` untouched: a refused
        call never happened, so it must not consume budget either.
        """
        requested = int(seconds)
        if self._used_s + requested > self._ceiling_s:
            raise MediaCeilingExceeded(
                ceiling_s=self._ceiling_s, used_s=self._used_s, requested_s=requested
            )
        self._used_s += requested

    def release(self, seconds: int) -> None:
        """Give back a reservation whose call never reached the wire.

        The reservation has to be taken *before* the request — that is what makes the ceiling
        enforced rather than advisory — but a call that failed before the audio was ever sent was
        not paid for, and budget it did not spend must not stay committed. Three failed uploads of
        a 43-minute episode would otherwise consume a third of the default ceiling and the run
        would refuse later work for spend that never happened.

        Never drops below zero: a double release is a caller defect, not a licence to invent
        budget.
        """
        self._used_s = max(0, self._used_s - int(seconds))


# ----------------------------------------------------------------------------------- prompts --


def short_transcription_prompt(context: SpeakerContext) -> str:
    """The ``z4b`` structured-transcription prompt, addressed to this subject.

    The four sections are load-bearing and parsed by name: ``META`` carries the identity evidence
    :func:`verify_speaker` reads, ``TRANSCRIPT`` is the only text a quote may be checked against,
    and the last two are what the research lane is actually looking for.
    """
    subject = context.description
    name = context.person_name or "the subject"
    return f"""You are transcribing a public recording for a business-research record.
The subject is {subject}.

Return ONLY this structure, in plain text:

## META
speakers: <label every distinct speaker S1/S2/... with your best identification and the evidence>
guest_identity_evidence: <verbatim words in the audio that identify the subject; else NOT STATED>
duration_mmss: <total duration you observed>

## TRANSCRIPT
A full transcript of the WHOLE recording. Every line MUST start with an [MM:SS] timestamp and a
speaker label, like:
[03:41] S2 ({name}): <verbatim words>
Do not summarise, do not skip, do not stop early. Use the real spoken words.

## QUOTES
Exactly 5 verbatim quotes from {name} that reveal how they think, what they value, how they
buy/evaluate tools or vendors, what they are proud of, or what frustrates them. Format:
- "[MM:SS]" "<verbatim quote>" -> why it matters: <one line>

## BUYING_AND_VENDOR_SIGNALS
Any moment where {name} talks about buying, evaluating, choosing, or being sold to by
vendors/tools, or about how they run go-to-market/marketing. Each as: [MM:SS] verbatim + one line.
If none exist, write: NONE IN THIS RECORDING.

Never invent words. If audio is unintelligible write [inaudible]."""


def long_transcription_prompt(context: SpeakerContext) -> str:
    """The ``z4d`` prompt for the dedicated transcription model.

    "Never repeat a passage you have already emitted" is the whole reason this prompt exists: the
    cheap model looped without it, and this model is what the re-run proved does not.
    """
    name = context.person_name or "the subject"
    return f"""Transcribe this entire recording. The main subject is {context.description}.

Output ONLY transcript lines, each starting with an [MM:SS] timestamp and a speaker label:
[03:41] {name}: <verbatim words>
Cover the WHOLE recording from 00:00 to the end. Never repeat a passage you have already emitted.
Never invent words. Mark unintelligible audio [inaudible]."""


def quote_mining_prompt(context: SpeakerContext, n: int, transcript_text: str) -> str:
    """The ``z4e`` STRICT-JSON quote-mining prompt over an already-faithful transcript.

    "EXACT substring" is asked for and then *checked* — the prompt is a hint, the check is the
    guarantee.
    """
    return (
        f"Below is the verbatim transcript of a recording. The subject is {context.description}."
        '\n\nReturn STRICT JSON: {"quotes":[{"quote":"<EXACT substring copied '
        'character-for-character from the text>","topic":"buying_or_vendors|leadership|hiring|'
        'competition|product_belief|personal","why":"one line"}]}\n'
        f"Give {n} quotes, each 12-45 words, each an EXACT substring. Prefer moments about how "
        "they buy/evaluate vendors, how they build and run the company, what they believe, and "
        "what they are proud of. Never paraphrase.\n\nTEXT:\n" + transcript_text
    )


# ------------------------------------------------------------------------------- cost & halts --


def estimate_media_usd(seconds: int) -> Decimal:
    """Law 2's pre-spend estimate for a transcription, from the price sheet above."""
    audio = Decimal(seconds * AUDIO_TOKENS_PER_SECOND) / _PER_MILLION * AUDIO_INPUT_USD_PER_1M
    output = (
        Decimal(seconds * OUTPUT_TOKENS_PER_MEDIA_SECOND) / _PER_MILLION * TEXT_OUTPUT_USD_PER_1M
    )
    return audio + output


def estimate_embedding_usd(texts: Sequence[str]) -> Decimal:
    """Law 2's estimate for an embeddings call, at the usual four characters per token."""
    tokens = sum(len(text) for text in texts) // 4
    return Decimal(tokens) / _PER_MILLION * EMBED_USD_PER_1M


def gemini_usage_cost(usage: Mapping[str, object]) -> Decimal:
    """Cost of a native call from its ``usageMetadata``, audio-modality tokens priced as audio.

    A faithful port of ``z_lib.gemini_cost``: the native endpoint reports tokens by modality and
    never reports money, so this is the only place a native call's spend comes from.

    The modality breakdown is preferred whenever it exists, because the fallback prices the whole
    prompt as text at a third of the audio rate — an honest last resort when the provider tells us
    nothing, but an understatement of a call that was mostly audio, so it must never be the
    default.
    """
    audio_tokens = 0
    text_tokens = 0
    details = usage.get("promptTokensDetails")
    if isinstance(details, list):
        for detail in details:
            if not isinstance(detail, dict):
                continue
            count = detail.get("tokenCount")
            count = count if isinstance(count, int) else 0
            if detail.get("modality") == "AUDIO":
                audio_tokens += count
            else:
                text_tokens += count
    if audio_tokens == 0 and text_tokens == 0:
        prompt_total = usage.get("promptTokenCount")
        text_tokens = prompt_total if isinstance(prompt_total, int) else 0
    output_tokens = 0
    for key in ("candidatesTokenCount", "thoughtsTokenCount"):
        value = usage.get(key)
        output_tokens += value if isinstance(value, int) else 0
    return (
        Decimal(audio_tokens) / _PER_MILLION * AUDIO_INPUT_USD_PER_1M
        + Decimal(text_tokens) / _PER_MILLION * TEXT_INPUT_USD_PER_1M
        + Decimal(output_tokens) / _PER_MILLION * TEXT_OUTPUT_USD_PER_1M
    )


def gemini_cost_reader(
    media_seconds: int, *, model: str | None = None, video: bool = False
) -> CostReader:
    """A cost reader for a native ``generateContent`` response, stamping the media seconds."""

    def read(response: HttpResponse) -> CostReading:
        body = json.loads(response.body)
        usage = body.get("usageMetadata") if isinstance(body, dict) else None
        usage = usage if isinstance(usage, dict) else {}
        request_id = body.get("responseId") if isinstance(body, dict) else None
        extras: dict[str, object] = {"usage": usage}
        if model:
            extras["model"] = model
        if video:
            extras["usd_unpriced"] = True
        for source, target in (
            ("promptTokenCount", "prompt_tokens"),
            ("candidatesTokenCount", "completion_tokens"),
            ("cachedContentTokenCount", "cached_prompt_tokens"),
        ):
            value = usage.get(source)
            if isinstance(value, int) and value >= 0:
                extras[target] = value
        return CostReading(
            cost_usd=None if video else gemini_usage_cost(usage),
            provider_request_id=request_id if isinstance(request_id, str) else None,
            media_seconds=media_seconds,
            extras=extras,
        )

    return read


def with_media_seconds(reader: CostReader, media_seconds: int) -> CostReader:
    """Wrap a cost reader so its reading also carries the seconds of audio the call consumed.

    Media seconds are the ARV2 lane's third currency (master plan §4); a transcription row that
    records dollars but not seconds cannot answer "how much audio did this account cost us".
    """

    def read(response: HttpResponse) -> CostReading:
        return replace(reader(response), media_seconds=media_seconds)

    return read


def gemini_native_halt_rule(response: HttpResponse) -> str | None:
    """Global Constraint 2: a 402/403 or a body naming credit is money truth, so it blocks.

    Returning a reason latches the provider in the wrapper — every later call to it raises without
    touching the wire, which is the point: a lane that keeps calling a provider that will not sell
    burns the run's time discovering the same refusal N more times.

    This rule belongs to the **native Gemini** endpoints only (``files.start``, ``files.upload``,
    ``files.get``, ``generateContent``), which latch under the provider key ``gemini``. The
    client's OpenRouter calls — short transcription, quote mining, embeddings — latch under
    ``openrouter``, the same key the structuring client uses, so they share
    :func:`~clue_api.arv2.openrouter.openrouter_halt_rule`: one latch key must have exactly one
    definition of when its provider is dead, or the lane disagrees with itself about it.
    """
    if response.status == 402:
        return "payment_required"
    if response.status == 403:
        return "forbidden"
    if response.status >= 400 and "credit" in response.body.decode("utf-8", "replace").lower():
        return "credit_exhausted"
    return None


def drop_download_uri(body: object) -> object:
    """Appendix A law 3: the Files API's ``downloadUri`` is a pre-authorised fetch URL for our
    uploaded audio, so it is dropped inside the client and never reaches a raw record."""
    if isinstance(body, dict):
        return {
            key: drop_download_uri(value) for key, value in body.items() if key != "downloadUri"
        }
    if isinstance(body, list):
        return [drop_download_uri(item) for item in body]
    return body


# ------------------------------------------------------------------------------------ parsing --


def parse_timestamp(text: str) -> int | None:
    """``MM:SS`` or ``HH:MM:SS`` to seconds; anything else is ``None``, never zero."""
    parts = text.split(":")
    if not 2 <= len(parts) <= 3:
        return None
    try:
        numbers = [int(part) for part in parts]
    except ValueError:
        return None
    seconds = 0
    for number in numbers:
        seconds = seconds * 60 + number
    return seconds


def _split_sections(text: str) -> dict[str, str]:
    """Split the ``## SECTION`` structure the short prompt asks for into named blocks."""
    sections: dict[str, list[str]] = {}
    current: str | None = None
    for line in text.splitlines():
        heading = _SECTION_RE.match(line.strip())
        if heading is not None:
            current = heading.group(1).upper()
            sections.setdefault(current, [])
            continue
        if current is not None:
            sections[current].append(line)
    return {name: "\n".join(body).strip() for name, body in sections.items()}


def _parse_meta(block: str) -> dict[str, str]:
    meta: dict[str, str] = {}
    for line in block.splitlines():
        match = _META_LINE_RE.match(line.strip())
        if match is not None:
            meta[match.group(1).lower()] = match.group(2).strip()
    return meta


def parse_transcript_lines(block: str) -> tuple[TranscriptLine, ...]:
    """Read ``[MM:SS] Speaker: words`` lines, keeping the lines that match neither shape.

    A line without a timestamp or without a speaker label is still transcript, and still counts
    for the loop detector — dropping it would let a model hide a loop by omitting timestamps.
    A prefix is only taken as a speaker when it *looks* like a label
    (:data:`_SPEAKER_LABEL_RE`), so a sentence containing a colon keeps all of its words.
    """
    lines: list[TranscriptLine] = []
    for raw in block.splitlines():
        stripped = raw.strip()
        if not stripped:
            continue
        ts_s: int | None = None
        remainder = stripped
        timestamped = _TS_LINE_RE.match(stripped)
        if timestamped is not None:
            ts_s = parse_timestamp(timestamped.group(1))
            remainder = timestamped.group(2).strip()
        speaker = ""
        split = _SPEAKER_SPLIT_RE.match(remainder)
        if split is not None and _SPEAKER_LABEL_RE.match(split.group(1).strip()):
            speaker = split.group(1).strip()
            remainder = split.group(2).strip()
        lines.append(TranscriptLine(ts_s=ts_s, speaker=speaker, text=remainder))
    return tuple(lines)


def sentence_lines(text: str) -> tuple[TranscriptLine, ...]:
    """Split timestamp-free prose into sentence-sized lines.

    The dedicated transcription model returns one unbroken block of prose — no newlines, no
    timestamps, no speaker labels. The loop detector needs *units* to compare, so the sentence is
    the unit for that path. Without this a 37 000-character blob would be one line and every loop
    rule would pass vacuously.
    """
    lines: list[TranscriptLine] = []
    for block in text.splitlines():
        for sentence in _SENTENCE_RE.split(block):
            cleaned = sentence.strip()
            if cleaned:
                lines.append(TranscriptLine(ts_s=None, speaker="", text=cleaned))
    return tuple(lines)


def _parse_quotes(
    block: str, *, haystack: str, speaker_verified: bool
) -> tuple[QuoteCandidate, ...]:
    """Read the ``QUOTES`` block, scoring each quote against the transcript body."""
    quotes: list[QuoteCandidate] = []
    for raw in block.splitlines():
        match = _QUOTE_LINE_RE.match(raw.strip())
        if match is None:
            continue
        text = match.group(2).strip()
        verdict = substring_verdict(text, haystack)
        quotes.append(
            QuoteCandidate(
                text=text,
                ts_s=parse_timestamp(match.group(1)),
                why=_WHY_PREFIX_RE.sub("", match.group(3).strip()),
                verdict=verdict,
                usable=verdict == "EXACT" and speaker_verified,
            )
        )
    return tuple(quotes)


def parse_structured_transcript(output: str, *, model: str, context: SpeakerContext) -> Transcript:
    """Turn the short prompt's four-section output into a :class:`Transcript`.

    A model that ignores the structure and simply transcribes is not a failure: the whole output
    becomes the transcript body, and the empty ``META``/``QUOTES`` say honestly that it gave none.
    """
    sections = _split_sections(output)
    body = sections.get("TRANSCRIPT", "").strip() or output.strip()
    lines = parse_transcript_lines(body)
    meta = _parse_meta(sections.get("META", ""))
    quotes = _parse_quotes(
        sections.get("QUOTES", ""),
        haystack=body,
        speaker_verified=context.named_in_metadata,
    )
    return Transcript(
        model=model,
        text=body,
        lines=lines,
        meta=meta,
        quotes=quotes,
        has_timestamps=any(line.ts_s is not None for line in lines),
    )


def native_transcript_text(body: object) -> str:
    """The text of a native ``generateContent`` response.

    ``candidates[0].content.parts[].audioTranscription.text`` is where the dedicated transcription
    model puts it — **not** ``parts[].text``, which is where every other Gemini model puts it and
    where the proof-of-concept first looked and found nothing. Both are read, transcription first.
    """
    if not isinstance(body, dict):
        return ""
    candidates = body.get("candidates")
    if not isinstance(candidates, list) or not candidates:
        return ""
    first = candidates[0]
    content = first.get("content") if isinstance(first, dict) else None
    parts = content.get("parts") if isinstance(content, dict) else None
    if not isinstance(parts, list):
        return ""
    transcription: list[str] = []
    plain: list[str] = []
    for part in parts:
        if not isinstance(part, dict):
            continue
        audio = part.get("audioTranscription")
        if isinstance(audio, dict) and isinstance(audio.get("text"), str):
            transcription.append(audio["text"])
        if isinstance(part.get("text"), str):
            plain.append(part["text"])
    return "".join(transcription) or "".join(plain)


def _first_json_object(text: str) -> dict[str, object] | None:
    """The first ``{...}`` block in a model's answer, parsed — fences and prose tolerated."""
    match = _JSON_OBJECT_RE.search(text)
    if match is None:
        return None
    try:
        parsed = json.loads(match.group(0))
    except ValueError:
        return None
    return parsed if isinstance(parsed, dict) else None


# ------------------------------------------------------------------------ pure measurements --


def detect_loops(transcript: Transcript) -> LoopReport:
    """Is this transcript re-emitting itself? The three rules the ``z4b`` run taught us.

    Tripped when any line repeats three or more times consecutively (a stuck decoder), or fewer
    than 60% of at least 40 lines are unique (the whole-transcript view: 120 unique of 329), or
    any 30-line window holds fewer than 15 distinct lines (the local view, which catches a loop
    that a long faithful opening would otherwise dilute below the ratio rule).
    """
    pairs = [(line.ts_s, line.text.strip()) for line in transcript.lines if line.text.strip()]
    total = len(pairs)
    if total == 0:
        return LoopReport(0, 0, 1.0, 0, None, False)

    texts = [text for _, text in pairs]
    unique = len(set(texts))
    ratio = unique / total

    max_run = 1
    run = 1
    for index in range(1, total):
        run = run + 1 if texts[index] == texts[index - 1] else 1
        max_run = max(max_run, run)

    first_loop_ts_s: int | None = None
    seen: set[str] = set()
    for ts_s, text in pairs:
        if text in seen:
            first_loop_ts_s = ts_s
            break
        seen.add(text)

    windowed = False
    if total >= LOOP_WINDOW:
        for start in range(total - LOOP_WINDOW + 1):
            if len(set(texts[start : start + LOOP_WINDOW])) < LOOP_WINDOW_MIN_UNIQUE:
                windowed = True
                break

    tripped = (
        max_run >= LOOP_MAX_CONSECUTIVE_REPEAT
        or (ratio < LOOP_MIN_UNIQUE_RATIO and total >= LOOP_MIN_LINES_FOR_RATIO)
        or windowed
    )
    return LoopReport(
        total_lines=total,
        unique_lines=unique,
        unique_ratio=ratio,
        max_consecutive_repeat=max_run,
        first_loop_ts_s=first_loop_ts_s,
        tripped=tripped,
    )


def verify_speaker(transcript: Transcript, context: SpeakerContext) -> SpeakerVerdict:
    """Is the subject actually the person on this recording?

    Spoken self-identification wins: a ``META`` identity-evidence line that is not ``NOT STATED``
    and names the subject's surname verifies them, and the verbatim words become the evidence.
    Failing that, the item's own metadata naming them verifies them more weakly, and says so.
    Otherwise unverified — which is the correct answer, not a defect.
    """
    surname = context.surname.lower()
    stated = ""
    for key in IDENTITY_META_KEYS:
        value = (transcript.meta.get(key) or "").strip()
        if not value:
            continue
        stated = stated or value
        if value.upper().startswith(NOT_STATED):
            continue
        if surname and surname in value.lower():
            return SpeakerVerdict(verified=True, evidence=value)
    if context.named_in_metadata:
        return SpeakerVerdict(verified=True, evidence=METADATA_EVIDENCE)
    return SpeakerVerdict(verified=False, evidence=stated)


def chunk_lines(
    lines: Sequence[TranscriptLine], window_lines: int
) -> tuple[tuple[str, int | None], ...]:
    """Group transcript lines into retrieval chunks, keeping each chunk's opening timestamp.

    Ported from ``z6``: a fixed line window rather than a token window, so a chunk stays a
    contiguous stretch of dialogue and a retrieval hit can be cited at a timestamp.
    """
    chunks: list[tuple[str, int | None]] = []
    buffer: list[TranscriptLine] = []
    for line in lines:
        if not line.text.strip():
            continue
        buffer.append(line)
        if len(buffer) >= window_lines:
            chunks.append((" ".join(item.text.strip() for item in buffer), buffer[0].ts_s))
            buffer = []
    if buffer:
        chunks.append((" ".join(item.text.strip() for item in buffer), buffer[0].ts_s))
    return tuple(chunks)


# ------------------------------------------------------------------------------- the client --


class GeminiMediaClient:
    """Transcription, loop detection, quote verification and text embeddings for one run.

    The ``ledger`` is here for one reason: a :class:`MediaCeilingExceeded` refusal happens before
    any provider call, so the wrapper never sees it and never writes a row. A refusal that leaves
    no trace is indistinguishable from a media item nobody tried, so the client writes that one
    row itself.
    """

    def __init__(
        self,
        caller: ProviderCaller,
        *,
        openrouter_api_key: SecretStr,
        openrouter_base_url: str,
        gemini_api_key: SecretStr,
        short_model: str,
        transcribe_model: str,
        embedding_model: str,
        media_budget: MediaBudget,
        short_max_seconds: int,
        ledger: LedgerSink,
        video_model: str = "gemini-3.5-flash-lite",
        sleep: Callable[[float], None] = time.sleep,
        now: Callable[[], datetime] = _utcnow,
    ) -> None:
        self._video_model = video_model
        self._caller = caller
        self._openrouter_api_key = openrouter_api_key
        self._openrouter_base_url = openrouter_base_url
        self._gemini_api_key = gemini_api_key
        self._short_model = short_model
        self._transcribe_model = transcribe_model
        self._embedding_model = embedding_model
        self._media_budget = media_budget
        self._short_max_seconds = short_max_seconds
        self._ledger = ledger
        self._sleep = sleep
        self._now = now

    # -- transcription -------------------------------------------------------------------------

    def transcribe_short(
        self,
        audio: AudioFile,
        *,
        context: SpeakerContext,
        max_attempts: int = 4,
        require_transcript_section: bool = False,
    ) -> Transcript:
        """One cheap OpenRouter completion over a short item, returning the structured output.

        Refuses a long item outright rather than quietly routing it to the expensive path: the
        short/long decision belongs to the caller, who knows the run's budget.
        """
        if audio.duration_s > self._short_max_seconds:
            raise ValueError(
                f"{audio.duration_s}s exceeds the short-item ceiling of "
                f"{self._short_max_seconds}s — use transcribe_long"
            )
        self._reserve(
            audio.duration_s,
            provider="openrouter",
            operation="chat/completions",
            label="media.transcribe_short",
        )
        encoded = base64.b64encode(audio.path.read_bytes()).decode("ascii")
        request = openrouter_chat_request(
            base_url=self._openrouter_base_url,
            api_key=self._openrouter_api_key,
            model=self._short_model,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "input_audio",
                            "input_audio": {"data": encoded, "format": audio.audio_format},
                        },
                        {"type": "text", "text": short_transcription_prompt(context)},
                    ],
                }
            ],
            max_tokens=SHORT_MAX_OUTPUT_TOKENS,
            temperature=0.0,
            timeout_s=SHORT_TIMEOUT_S,
        )
        result = self._caller.call(
            CallSpec(
                provider="openrouter",
                operation="chat/completions",
                label="media.transcribe_short",
                request=request,
                estimate=SpendEstimate(
                    usd=estimate_media_usd(audio.duration_s), media_seconds=audio.duration_s
                ),
                halt_rule=openrouter_halt_rule,
                cost_reader=with_media_seconds(openrouter_cost_reader, audio.duration_s),
                # The whole clip is base64'd into this JSON body: it decodes as UTF-8 and would
                # otherwise be inlined into every attempt's raw record (~13 MB for a 10-minute
                # item, up to four attempts). The record keeps its sha256 and byte count instead.
                binary_request=True,
                max_attempts=max_attempts,
            )
        )
        self._require_ok(result, "short transcription")
        response_body = result.json()
        choices = response_body.get("choices") if isinstance(response_body, dict) else None
        first = choices[0] if isinstance(choices, list) and choices else {}
        finish = first.get("finish_reason") if isinstance(first, dict) else None
        value = openrouter_message_text(result.json())
        return replace(
            self.parse_openrouter_recording(response_body, model=self._short_model)
            if require_transcript_section
            else parse_structured_transcript(value, model=self._short_model, context=context),
            cost=result.call_cost,
            finish_reason=finish if isinstance(finish, str) else None,
        )

    def transcribe_long(self, audio: AudioFile, *, context: SpeakerContext) -> Transcript:
        """Upload the file and transcribe it on the dedicated model, off OpenRouter.

        The founder ruling: this is the one ARV2 call that leaves OpenRouter, because OpenRouter
        serves neither this model nor a file upload. The key travels in ``x-goog-api-key``, never
        as ``?key=``, so it is masked by the raw sink's header redaction rather than sitting in a
        URL on disk.

        The media-seconds reservation is taken before the upload (that is what makes the ceiling
        enforced) and **released again if the upload or the transcription fails** — audio that was
        never transcribed was never paid for, and budget it did not spend must not stay committed.
        """
        self._reserve(
            audio.duration_s,
            provider="gemini",
            operation=f"models/{self._transcribe_model}:generateContent",
            label="media.transcribe_long",
        )
        try:
            return self._transcribe_long_reserved(audio, context=context)
        except Exception:
            self._media_budget.release(audio.duration_s)
            raise

    def _transcribe_long_reserved(self, audio: AudioFile, *, context: SpeakerContext) -> Transcript:
        """The upload-and-generate body of :meth:`transcribe_long`, under a live reservation."""
        file_uri, upload_costs = self._upload(audio)
        request = json_request(
            "POST",
            f"{GEMINI_BASE}/models/{self._transcribe_model}:generateContent",
            headers=self._gemini_headers(),
            json_body={
                "contents": [
                    {
                        "parts": [
                            {
                                "file_data": {
                                    "file_uri": file_uri,
                                    "mime_type": audio.mime_type,
                                }
                            },
                            {"text": long_transcription_prompt(context)},
                        ]
                    }
                ],
                "generationConfig": {
                    "temperature": 0,
                    "maxOutputTokens": LONG_MAX_OUTPUT_TOKENS,
                },
            },
            timeout_s=GENERATE_TIMEOUT_S,
        )
        result = self._caller.call(
            CallSpec(
                provider="gemini",
                operation=f"models/{self._transcribe_model}:generateContent",
                label="media.transcribe_long",
                request=request,
                estimate=SpendEstimate(
                    usd=estimate_media_usd(audio.duration_s), media_seconds=audio.duration_s
                ),
                max_attempts=GENERATE_MAX_ATTEMPTS,
                halt_rule=gemini_native_halt_rule,
                cost_reader=gemini_cost_reader(audio.duration_s),
            )
        )
        self._require_ok(result, "long transcription")
        text = native_transcript_text(result.json())
        return Transcript(
            model=self._transcribe_model,
            text=text,
            lines=sentence_lines(text),
            meta={},
            quotes=(),
            has_timestamps=False,
            cost=result.call_cost,
            upload_costs=upload_costs,
        )

    # -- quotes and embeddings -----------------------------------------------------------------

    def mine_quotes(
        self,
        transcript_text: str,
        *,
        context: SpeakerContext,
        n: int = 6,
        speaker_verified: bool | None = None,
    ) -> MinedQuotes:
        """Ask for ``n`` verbatim quotes, then check every one of them against the transcript.

        Nothing is dropped: a fabricated quote comes back with ``verdict='NOT_FOUND'`` and
        ``usable=False``, because Appendix A law 6 makes the check an annotation, not a filter.
        ``speaker_verified`` defaults to whether the item's metadata named the subject — pass
        :func:`verify_speaker`'s verdict when a transcript with ``META`` evidence exists.
        """
        verified = context.named_in_metadata if speaker_verified is None else speaker_verified
        request = openrouter_chat_request(
            base_url=self._openrouter_base_url,
            api_key=self._openrouter_api_key,
            model=self._short_model,
            messages=[
                {"role": "user", "content": quote_mining_prompt(context, n, transcript_text)}
            ],
            max_tokens=QUOTE_MAX_OUTPUT_TOKENS,
            temperature=0.0,
            timeout_s=TEXT_CALL_TIMEOUT_S,
        )
        result = self._caller.call(
            CallSpec(
                provider="openrouter",
                operation="chat/completions",
                label="media.mine_quotes",
                request=request,
                estimate=SpendEstimate(usd=Decimal("0.01")),
                halt_rule=openrouter_halt_rule,
                cost_reader=openrouter_cost_reader,
            )
        )
        self._require_ok(result, "quote mining")
        payload = _first_json_object(openrouter_message_text(result.json()))
        if payload is None:
            raise GeminiMediaError("quote mining returned no JSON object", raw_ref=result.raw_ref)
        raw_quotes = payload.get("quotes")
        raw_quotes = raw_quotes if isinstance(raw_quotes, list) else []
        quotes: list[QuoteCandidate] = []
        for item in raw_quotes:
            if not isinstance(item, dict):
                continue
            text = str(item.get("quote") or "")
            topic = item.get("topic")
            verdict = substring_verdict(text, transcript_text)
            quotes.append(
                QuoteCandidate(
                    text=text,
                    ts_s=None,
                    why=str(item.get("why") or ""),
                    topic=topic if isinstance(topic, str) else None,
                    verdict=verdict,
                    usable=verdict == "EXACT" and verified,
                )
            )
        return MinedQuotes(quotes=tuple(quotes), cost=result.call_cost)

    def embed_chunks(
        self, transcript: Transcript, *, window_lines: int = 14, dimensions: int = 768
    ) -> EmbeddedTranscript:
        """Embed the transcript in timestamped chunks — text only, never the raw audio.

        Appendix A law 11: audio embedding is priced per second and buys nothing retrieval cannot
        get from the transcript we already paid to produce.

        A transcript with nothing to chunk makes **no call**, and the result says so: no chunks,
        no cost, zero dimensions. That is the one honest empty here — a fabricated zero-cost
        ledger reference would claim a request that was never sent.
        """
        chunks = chunk_lines(transcript.lines, window_lines)
        if not chunks:
            return EmbeddedTranscript(chunks=(), cost=None, dimensions=0)
        texts = [text for text, _ in chunks]
        result = self._embeddings_call(texts, dimensions)
        vectors = self._embedding_vectors(result, expected=len(texts))
        return EmbeddedTranscript(
            chunks=tuple(
                EmbeddedChunk(text=text, start_ts_s=start_ts_s, vector=vector)
                for (text, start_ts_s), vector in zip(chunks, vectors, strict=True)
            ),
            cost=result.call_cost,
            # The width the provider served, not the one requested: `_embeddings_call` retries
            # without `dimensions` when the model rejects it, so these can differ.
            dimensions=len(vectors[0]),
        )

    def embed_texts(
        self, texts: Sequence[str], *, query: bool = False, dimensions: int = 768
    ) -> EmbeddedTranscript:
        """Prepared passage/query embeddings, one compatible textual-format contract.

        OpenRouter does not promise Gemini task_type forwarding. Prefixes are explicit and
        versioned by the media index; actual dimensions are validated, never padded/truncated.
        """
        import math

        if not texts:
            return EmbeddedTranscript(chunks=(), cost=None, dimensions=0)
        inputs = [("search_query: " if query else "search_document: ") + t for t in texts]
        result = self._embeddings_call(inputs, dimensions, max_attempts=1)
        vectors = self._embedding_vectors(result, expected=len(texts))
        body = result.json()
        rows = body.get("data", []) if isinstance(body, dict) else []
        indices = [row.get("index") for row in rows]
        if sorted(indices) != list(range(len(texts))):
            raise GeminiMediaError(
                "incomplete or duplicate embedding indices", raw_ref=result.raw_ref
            )
        vectors = [vector for _, vector in sorted(zip(indices, vectors, strict=True))]
        width = len(vectors[0])
        if width not in {768, 1536, 3072}:
            raise GeminiMediaError("unsupported embedding dimensions", raw_ref=result.raw_ref)
        normalized = []
        for vector in vectors:
            if len(vector) != width or any(not math.isfinite(v) for v in vector):
                raise GeminiMediaError("invalid embedding vector contract", raw_ref=result.raw_ref)
            norm = math.sqrt(sum(v * v for v in vector))
            if norm == 0:
                raise GeminiMediaError("zero embedding vector", raw_ref=result.raw_ref)
            normalized.append(tuple(v / norm for v in vector))
        return EmbeddedTranscript(
            chunks=tuple(
                EmbeddedChunk(text=t, start_ts_s=None, vector=v)
                for t, v in zip(texts, normalized, strict=True)
            ),
            cost=result.call_cost,
            dimensions=width,
        )

    def upload_recording(self, audio: AudioFile) -> str:
        """Free Files stage, independently checkpointed by the v3 acquisition owner."""
        return self._upload(audio)[0]

    def resume_uploaded_file(self, name: str) -> str:
        """Resume the free readiness poll from a saved upload response."""
        if not re.fullmatch(r"files/[A-Za-z0-9_-]+", name):
            raise ValueError("invalid saved Gemini file name")
        return self._await_active(name, raw_ref=None)[0]

    def transcribe_uploaded(
        self,
        file_uri: str,
        *,
        mime_type: str,
        duration_s: int,
        context: SpeakerContext,
        video: bool = False,
    ) -> Transcript:
        return self.transcribe_native(
            file_uri, mime_type=mime_type, duration_s=duration_s, context=context, video=video
        )

    def transcribe_video(self, url: str, *, duration_s: int, context: SpeakerContext) -> Transcript:
        """Native public-YouTube input. The resolver proves public access and duration first."""
        from clue_api.arv2.media_resolution import youtube_url

        normalized = youtube_url(url)
        if normalized is None:
            raise ValueError("public YouTube URL required")
        return self.transcribe_native(
            normalized[0], mime_type="video/mp4", duration_s=duration_s, context=context, video=True
        )

    def transcribe_native(
        self, uri: str, *, mime_type: str, duration_s: int, context: SpeakerContext, video: bool
    ) -> Transcript:
        if duration_s <= 0:
            raise ValueError("verified media duration required")
        model = self._video_model if video else self._transcribe_model
        self._reserve(
            duration_s,
            provider="gemini",
            operation=f"models/{model}:generateContent",
            label="media.transcribe_video" if video else "media.transcribe_long",
        )
        prompt = (
            (
                short_transcription_prompt(context)
                + "\nTranscribe ALL audible speech, not a summary. Do not infer unheard words. "
                "Speaker labels and timestamps are estimates unless explicitly grounded. "
                "Report truncation or inaudible sections honestly."
            )
            if video
            else long_transcription_prompt(context)
        )
        result = self._caller.call(
            CallSpec(
                provider="gemini",
                operation=f"models/{model}:generateContent",
                label="media.transcribe_video" if video else "media.transcribe_long",
                request=json_request(
                    "POST",
                    f"{GEMINI_BASE}/models/{model}:generateContent",
                    headers=self._gemini_headers(),
                    json_body={
                        "contents": [
                            {
                                "parts": [
                                    {"fileData": {"fileUri": uri, "mimeType": mime_type}},
                                    {"text": prompt},
                                ]
                            }
                        ],
                        "generationConfig": {
                            "temperature": 0,
                            "maxOutputTokens": LONG_MAX_OUTPUT_TOKENS,
                        },
                    },
                    timeout_s=GENERATE_TIMEOUT_S,
                ),
                # Video billing must be calibrated in the founder-triggered canary. Never apply the
                # dedicated audio model's price to video. The ledger explicitly records unknown USD.
                estimate=SpendEstimate(
                    media_seconds=duration_s,
                    usd=Decimal(0) if video else estimate_media_usd(duration_s),
                ),
                # Stamp the spec too: malformed metering must not turn unknown USD into zero.
                extras={"usd_unpriced": True} if video else {},
                cost_reader=gemini_cost_reader(duration_s, model=model, video=video),
                halt_rule=gemini_native_halt_rule,
                max_attempts=1,
            )
        )
        self._require_ok(result, "native recording transcription")
        return replace(
            self.parse_native_recording(result.json(), model=model, structured=video),
            cost=result.call_cost,
        )

    @staticmethod
    def parse_openrouter_recording(body: object, *, model: str) -> Transcript:
        value = openrouter_message_text(body)
        choices = body.get("choices") if isinstance(body, dict) else None
        first = choices[0] if isinstance(choices, list) and choices else {}
        finish = first.get("finish_reason") if isinstance(first, dict) else None
        return replace(
            GeminiMediaClient.parse_recording_text(value, model=model, structured=True),
            finish_reason=finish if isinstance(finish, str) else None,
        )

    @staticmethod
    def parse_native_recording(body: object, *, model: str, structured: bool) -> Transcript:
        value = native_transcript_text(body)
        finish = None
        if isinstance(body, dict):
            candidates = body.get("candidates") or []
            if candidates:
                finish = candidates[0].get("finishReason")
        parsed = GeminiMediaClient.parse_recording_text(value, model=model, structured=structured)
        return replace(parsed, finish_reason=finish)

    @staticmethod
    def parse_recording_text(value: str, *, model: str, structured: bool) -> Transcript:
        if structured and not re.search(r"^##\s+TRANSCRIPT\s*$", value, re.M | re.I):
            # A description, META block or refusal cannot masquerade as audible speech.
            return Transcript(model=model, text="", lines=())
        return (
            parse_structured_transcript(value, model=model, context=SpeakerContext(person_name=""))
            if structured
            else Transcript(model=model, text=value, lines=sentence_lines(value))
        )

    # -- internals -----------------------------------------------------------------------------

    def _gemini_headers(self) -> dict[str, str]:
        """The native endpoint's credential. Lower-cased so the raw sink's redaction matches it."""
        return {"x-goog-api-key": self._gemini_api_key.get_secret_value()}

    def _reserve(self, seconds: int, *, provider: str, operation: str, label: str) -> None:
        """Take the media-seconds reservation, recording a refusal the wrapper cannot see."""
        try:
            self._media_budget.reserve(seconds)
        except MediaCeilingExceeded as exc:
            self._ledger.record(
                LedgerRow(
                    row_id=str(uuid.uuid4()),
                    call_id=str(uuid.uuid4()),
                    phase="result",
                    provider=provider,
                    operation=operation,
                    label=label,
                    recorded_at=self._now(),
                    estimate_usd=estimate_media_usd(seconds),
                    estimate_media_seconds=exc.requested_s,
                    cost_usd=Decimal(0),
                    credits=Decimal(0),
                    media_seconds=0,
                    over_ceiling=True,
                    outcome="halted",
                    error_code="media_ceiling",
                    extras={
                        "ceiling_s": exc.ceiling_s,
                        "used_s": exc.used_s,
                        "requested_s": exc.requested_s,
                    },
                )
            )
            raise

    def _require_ok(self, result: CallResult, what: str) -> None:
        """A non-2xx is a loud typed failure, never an empty transcript nobody notices."""
        if not 200 <= result.response.status < 300:
            raise GeminiMediaError(
                f"{what} failed", raw_ref=result.raw_ref, http_status=result.response.status
            )

    def _upload(self, audio: AudioFile) -> tuple[str, tuple[CallCost, ...]]:
        """Resumable-upload the file to the Files API and wait for it to become ``ACTIVE``.

        Returns the file URI **and every leg's cost**. The three or four requests here are free,
        but they are still requests, and a caller reconciling a transcript against the ledger has
        to be able to find all of their rows — so they are handed back rather than dropped on the
        floor for being worth nothing.
        """
        size = audio.path.stat().st_size
        start = self._caller.call(
            CallSpec(
                provider="gemini",
                operation="files.start",
                label="media.upload_start",
                request=json_request(
                    "POST",
                    GEMINI_UPLOAD_URL,
                    headers={
                        **self._gemini_headers(),
                        "X-Goog-Upload-Protocol": "resumable",
                        "X-Goog-Upload-Command": "start",
                        "X-Goog-Upload-Header-Content-Length": str(size),
                        "X-Goog-Upload-Header-Content-Type": audio.mime_type,
                    },
                    json_body={"file": {"display_name": audio.display_name}},
                    timeout_s=UPLOAD_START_TIMEOUT_S,
                ),
                halt_rule=gemini_native_halt_rule,
            )
        )
        self._require_ok(start, "files upload start")
        upload_url = start.response.headers.get("x-goog-upload-url")
        if not upload_url:
            raise MediaUploadFailed(
                "files upload start returned no X-Goog-Upload-URL", raw_ref=start.raw_ref
            )

        uploaded = self._caller.call(
            CallSpec(
                provider="gemini",
                operation="files.upload",
                label="media.upload",
                request=HttpRequest(
                    method="POST",
                    url=upload_url,
                    headers={
                        "Content-Length": str(size),
                        "X-Goog-Upload-Offset": "0",
                        "X-Goog-Upload-Command": "upload, finalize",
                    },
                    body=audio.path.read_bytes(),
                    timeout_s=UPLOAD_TIMEOUT_S,
                ),
                max_attempts=UPLOAD_MAX_ATTEMPTS,
                halt_rule=gemini_native_halt_rule,
                raw_scrubber=drop_download_uri,
                # The request body *is* the media file; only its content address belongs on disk.
                binary_request=True,
            )
        )
        self._require_ok(uploaded, "files upload")
        body = uploaded.json()
        file_object = body.get("file") if isinstance(body, dict) else None
        name = file_object.get("name") if isinstance(file_object, dict) else None
        if not isinstance(name, str) or not name:
            raise MediaUploadFailed("files upload returned no file name", raw_ref=uploaded.raw_ref)

        uri, poll_costs = self._await_active(name, raw_ref=uploaded.raw_ref)
        return uri, (start.call_cost, uploaded.call_cost, *poll_costs)

    def _await_active(self, name: str, *, raw_ref: str | None) -> tuple[str, tuple[CallCost, ...]]:
        """Poll ``GET /v1beta/files/{name}`` until the file is usable, or fail loudly.

        Returns the file URI and one free :class:`CallCost` per poll actually made — the polls
        are requests, so they are rows, so they are reported.
        """
        polls: list[CallCost] = []
        for _ in range(MAX_FILE_POLLS):
            poll = self._caller.call(
                CallSpec(
                    provider="gemini",
                    operation="files.get",
                    label="media.upload_poll",
                    request=HttpRequest(
                        method="GET",
                        url=f"{GEMINI_BASE}/{name}",
                        headers=self._gemini_headers(),
                        timeout_s=FILE_POLL_TIMEOUT_S,
                    ),
                    halt_rule=gemini_native_halt_rule,
                    raw_scrubber=drop_download_uri,
                )
            )
            polls.append(poll.call_cost)
            self._require_ok(poll, "files get")
            body = poll.json()
            state = body.get("state") if isinstance(body, dict) else None
            uri = body.get("uri") if isinstance(body, dict) else None
            if state == "ACTIVE":
                if not isinstance(uri, str) or not uri:
                    raise MediaUploadFailed("ACTIVE file has no uri", raw_ref=poll.raw_ref)
                return uri, tuple(polls)
            if state == "FAILED":
                raise MediaUploadFailed(f"file {name} entered state FAILED", raw_ref=poll.raw_ref)
            self._sleep(FILE_POLL_INTERVAL_S)
        raise MediaUploadFailed(
            f"file {name} never became ACTIVE within "
            f"{MAX_FILE_POLLS} polls {FILE_POLL_INTERVAL_S}s apart",
            raw_ref=raw_ref,
        )

    def _embeddings_spec(
        self, texts: Sequence[str], dimensions: int | None, *, max_attempts: int = 4
    ) -> CallSpec:
        return CallSpec(
            provider="openrouter",
            operation="embeddings",
            max_attempts=max_attempts,
            label="media.embed_chunks",
            request=openrouter_embeddings_request(
                base_url=self._openrouter_base_url,
                api_key=self._openrouter_api_key,
                model=self._embedding_model,
                inputs=texts,
                dimensions=dimensions,
                timeout_s=EMBEDDINGS_TIMEOUT_S,
            ),
            estimate=SpendEstimate(usd=estimate_embedding_usd(texts)),
            halt_rule=openrouter_halt_rule,
            cost_reader=openrouter_cost_reader,
        )

    def _embeddings_call(
        self, texts: Sequence[str], dimensions: int, *, max_attempts: int = 4
    ) -> CallResult:
        """One embeddings call, retried once without ``dimensions`` if that is what was rejected.

        ``dimensions`` is a Matryoshka truncation the model may or may not expose through this
        endpoint. Retrying without it and reporting the served dimension is honest; silently
        padding or truncating a vector to the dimension we asked for would not be.
        """
        result = self._caller.call(
            self._embeddings_spec(texts, dimensions, max_attempts=max_attempts)
        )
        if 400 <= result.response.status < 500 and "dimension" in result.text().lower():
            result = self._caller.call(
                self._embeddings_spec(texts, None, max_attempts=max_attempts)
            )
        self._require_ok(result, "embeddings")
        return result

    def _embedding_vectors(self, result: CallResult, *, expected: int) -> list[tuple[float, ...]]:
        body = result.json()
        data = body.get("data") if isinstance(body, dict) else None
        if not isinstance(data, list) or len(data) != expected:
            raise GeminiMediaError(
                f"embeddings returned {len(data) if isinstance(data, list) else 'no'} vectors "
                f"for {expected} chunks",
                raw_ref=result.raw_ref,
            )
        vectors: list[tuple[float, ...]] = []
        for item in data:
            values = item.get("embedding") if isinstance(item, dict) else None
            if not isinstance(values, list) or not values:
                raise GeminiMediaError("embeddings row has no vector", raw_ref=result.raw_ref)
            vectors.append(tuple(float(value) for value in values))
        return vectors
