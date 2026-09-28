"""Whole-recording ASR through the shared spend/raw-response seam.

Voice clusters are never mapped to the research subject's name. No LLM rewrites speech.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from decimal import Decimal
from itertools import groupby
from typing import Any
from urllib.parse import urlencode

from pydantic import SecretStr

from clue_api.arv2.media_resolution import public_url
from clue_api.arv2.media_types import Quality, Segment, canonical_text
from clue_spend.calls import CallSpec, CostReading, ProviderCaller, SpendEstimate
from clue_spend.transport import HttpRequest, HttpResponse


def parameters(language: str = "en", keyterms: tuple[str, ...] = ()) -> dict[str, Any]:
    params: dict[str, Any] = {
        "model": "nova-3",
        "diarize_model": "v2",
        "utterances": "true",
        "utt_split": "0.8",
        "punctuate": "true",
        "smart_format": "false",
        "filler_words": "true",
        "profanity_filter": "false",
        "multichannel": "false",
    }
    params["detect_language" if language == "auto" else "language"] = (
        "true" if language == "auto" else language
    )
    if keyterms:
        params["keyterm"] = list(keyterms)
    return params


def speaker_segments(utterances: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Preserve the trial's word-speaker splits instead of majority-label attribution."""
    segments = []
    for utterance in utterances:
        words = utterance.get("words") or []
        if not words or {w.get("speaker") for w in words} == {utterance.get("speaker")}:
            segments.append(utterance)
            continue
        for speaker, grouped in groupby(words, key=lambda w: w.get("speaker")):
            group = list(grouped)
            segments.append(
                {
                    "start": group[0].get("start"),
                    "end": group[-1].get("end"),
                    "speaker": speaker,
                    "words": group,
                    "transcript": " ".join(
                        w.get("punctuated_word", w.get("word", "")) for w in group
                    ),
                    "derived_from_utterance": utterance.get("id"),
                }
            )
    return segments


def time_value(value: Any) -> float | None:
    if (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
        and value >= 0
    ):
        return float(value)
    return None


def read_cost(response: HttpResponse, *, usd_per_minute: Decimal) -> CostReading:
    body = json.loads(response.body)
    metadata = body.get("metadata", {})
    duration = time_value(metadata.get("duration"))
    return CostReading(
        provider_request_id=metadata.get("request_id") or body.get("request_id"),
        media_seconds=math.ceil(duration) if duration is not None else None,
        cost_usd=(Decimal(str(duration)) * usd_per_minute / 60)
        if 200 <= response.status < 300 and duration is not None
        else None,
        inferred=True,
        extras={
            "duration_seconds": duration,
            "usd_per_minute": str(usd_per_minute),
            "pricing_basis": "configured_nova3_prerecorded_rate",
            "invoice_verified": False,
            "usd_unpriced": not (200 <= response.status < 300 and duration is not None),
        },
    )


@dataclass(frozen=True)
class DeepgramTranscript:
    text: str
    segments: tuple[Segment, ...]
    quality: Quality
    model: str = "nova-3"
    quotes: tuple[Any, ...] = ()


def parse_response(body: dict[str, Any], *, expected_hash: str | None = None) -> DeepgramTranscript:
    results = body.get("results")
    if not isinstance(results, dict) or not isinstance(results.get("channels"), list):
        raise ValueError("Deepgram response has no transcription results")
    alternatives = [c["alternatives"][0] for c in results["channels"] if c.get("alternatives")]
    words = [w for alternative in alternatives for w in alternative.get("words", [])]
    utterances = results.get("utterances") or []
    warnings = [
        "machine_transcript_not_listening_verified",
        "speaker_labels_are_voice_clusters_not_names",
    ]
    utterance_words = [w for u in utterances for w in u.get("words", [])]

    # A partial utterance view must not silently discard words in the channel transcript.
    def signature(word: dict[str, Any]) -> tuple[Any, Any, Any]:
        return word.get("word"), word.get("start"), word.get("end")

    if words and [signature(w) for w in words] != [signature(w) for w in utterance_words]:
        warnings.append("utterance_word_mismatch_using_complete_word_stream")
        utterances = [
            {
                "words": words,
                "start": words[0].get("start"),
                "end": words[-1].get("end"),
                "transcript": " ".join(w.get("punctuated_word", w.get("word", "")) for w in words),
            }
        ]
    rows = speaker_segments(utterances)
    if not rows:
        rows = [{"transcript": a.get("transcript", "")} for a in alternatives]
        warnings.append("utterances_unavailable")
    text_parts: list[str] = []
    segments = []
    cursor = 0
    for row in rows:
        value = canonical_text(row.get("transcript", ""))
        if not value:
            continue
        if text_parts:
            cursor += 1
        start_time = time_value(row.get("start"))
        end_time = time_value(row.get("end"))
        if start_time is None or end_time is None:
            warnings.append("segment_timing_unavailable")
        speaker = row.get("speaker")
        segments.append(
            Segment(
                start=cursor,
                end=cursor + len(value),
                speaker=f"Speaker {speaker}" if speaker is not None else None,
                attribution="model_inferred" if speaker is not None else "unknown",
                time_s=start_time,
                end_time_s=end_time
                if start_time is not None and end_time is not None and end_time >= start_time
                else None,
                timing="aligned" if start_time is not None else "unavailable",
            )
        )
        text_parts.append(value)
        cursor += len(value)
    metadata = body.get("metadata", {})
    actual_hash = metadata.get("sha256")
    matches = actual_hash == expected_hash if actual_hash and expected_hash else None
    if matches is False:
        warnings.append("provider_file_checksum_mismatch")
    if not metadata.get("diarize_info"):
        warnings.append("diarizer_metadata_unavailable")
    if not words:
        warnings.append("word_timing_unavailable")
    last = max((time_value(w.get("end")) or 0 for w in words), default=0)
    duration = time_value(metadata.get("duration"))
    if duration and last and duration - last > 30:
        warnings.append("trailing_audio_may_be_silence_or_missing_speech")
    return DeepgramTranscript(
        text="\n".join(text_parts),
        segments=tuple(segments),
        quality=Quality(
            coverage="unknown",
            warnings=list(dict.fromkeys(warnings)),
            diagnostics={
                "provider": "deepgram",
                "metadata": metadata,
                "word_count": len(words),
                "provider_file_checksum_matches": matches,
                "accuracy_assessed": False,
                "words_without_speaker": sum(w.get("speaker") is None for w in words),
                "words_without_timing": sum(
                    time_value(w.get("start")) is None or time_value(w.get("end")) is None
                    for w in words
                ),
                "words_confidence_below_0_8": sum(w.get("confidence", 1) < 0.8 for w in words),
                "words_speaker_confidence_below_0_8": sum(
                    w.get("speaker_confidence", 1) < 0.8 for w in words
                ),
            },
        ),
    )


class DeepgramMediaError(ValueError):
    def __init__(self, message: str, http_status: int | None = None):
        super().__init__(message)
        self.http_status = http_status


class DeepgramMediaClient:
    def __init__(
        self,
        caller: ProviderCaller,
        api_key: SecretStr | None,
        *,
        language: str = "en",
        usd_per_minute: Decimal = Decimal("0.0043"),
    ):
        self.caller, self.api_key, self.language = caller, api_key, language
        if not usd_per_minute.is_finite() or usd_per_minute < 0:
            raise ValueError("Deepgram rate must be finite and nonnegative")
        self.usd_per_minute = usd_per_minute

    def transcribe(
        self,
        *,
        audio: bytes,
        mime: str,
        duration_s: int,
        expected_hash: str,
        media_url: str | None = None,
    ) -> DeepgramTranscript:
        if self.api_key is None or not self.api_key.get_secret_value():
            raise ValueError("CLUE_DEEPGRAM_API_KEY is required for recording transcription")
        body = json.dumps({"url": public_url(media_url)}).encode() if media_url else audio
        result = self.caller.call(
            CallSpec(
                provider="deepgram",
                operation="listen/pre-recorded",
                label="media.transcribe",
                request=HttpRequest(
                    "POST",
                    "https://api.deepgram.com/v1/listen?" + urlencode(parameters(self.language)),
                    headers={
                        "Authorization": f"Token {self.api_key.get_secret_value()}",
                        "Content-Type": "application/json" if media_url else mime,
                    },
                    body=body,
                    timeout_s=660,
                ),
                estimate=SpendEstimate(
                    media_seconds=duration_s, usd=Decimal(duration_s) * self.usd_per_minute / 60
                ),
                binary_request=not bool(media_url),
                max_attempts=1,
                cost_reader=lambda response: read_cost(
                    response, usd_per_minute=self.usd_per_minute
                ),
                extras={
                    "usd_unpriced": True,
                    "model": "nova-3",
                    "diarize_model": "v2",
                    "usd_per_minute": str(self.usd_per_minute),
                },
            )
        )
        if not 200 <= result.response.status < 300:
            raise DeepgramMediaError(
                f"Deepgram transcription failed with HTTP {result.response.status}",
                result.response.status,
            )
        try:
            return parse_response(json.loads(result.response.body), expected_hash=expected_hash)
        except (ValueError, KeyError, TypeError) as exc:
            raise DeepgramMediaError(
                "Deepgram response was retained but could not be parsed"
            ) from exc
