"""Isolated Deepgram batch transcription; no fleet, DB, claims or model-generated prose.

See docs/experiments/deepgram-media-trial.md. Run with the repository .venv Python.
"""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import math
import os
import shutil
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from time import monotonic
from urllib.parse import urlencode

from dotenv import dotenv_values

from clue_api.arv2.deepgram_media_client import parameters, read_cost, speaker_segments
from clue_api.arv2.media_recording import prepare_audio
from clue_api.arv2.media_resolution import (
    PublicMediaTransport,
    fetch,
    public_url,
    resolve,
    youtube_url,
)
from clue_config import Secrets, load_settings
from clue_obs.langfuse import flush_langfuse, observation, propagate_trace
from clue_obs.production import install_production_langfuse, install_production_tracing
from clue_spend.calls import CallSpec, ProviderCaller, SpendEstimate
from clue_spend.sinks import FileRawSink, JsonlLedger
from clue_spend.transport import HttpRequest, HttpxTransport

ROOT = Path(__file__).resolve().parents[1]


def save(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def event(out, stage, **details):
    with (out / "events.jsonl").open("a") as stream:
        stream.write(json.dumps({"at": datetime.now(UTC).isoformat(), "stage": stage, **details}))
        stream.write("\n")
    print(stage, flush=True)


def caller(out, transport):
    return ProviderCaller(
        transport=transport,
        raw_sink=FileRawSink(out / "raw"),
        ledger=JsonlLedger(out / "provider-ledger.jsonl"),
        now=lambda: datetime.now(UTC),
    )


class CachedPublicTransport:
    """Reuse media already downloaded during shared page/feed resolution."""

    def __init__(self):
        self.media = {}

    def send(self, request):
        if request.url in self.media:
            return self.media[request.url]
        response = PublicMediaTransport().send(request)
        if response.headers.get("content-type", "").startswith(("audio/", "video/")):
            self.media[request.url] = response
            self.media[response.headers.get("x-arv2-final-url", request.url)] = response
        return response


def command(args, out, label):
    """No shell, cookies, inherited downloader config, or secrets in command arguments."""
    result = subprocess.run(args, capture_output=True, text=True, timeout=900, check=False)
    (out / f"{label}.stderr.txt").write_text(result.stderr)
    if result.returncode:
        raise ValueError(f"{label} failed; see {label}.stderr.txt")
    return result.stdout


#: YouTube is never downloaded (spec 2026-10-13-legitimate-media-sources-design §2); research
#: reads it through its podcast twin or Gemini on the public link (``read_media``).
YOUTUBE_REFUSAL = "YouTube is never downloaded; use read_media for a YouTube link"


def prepare(source, out, episode=None):
    out.mkdir(parents=True, exist_ok=False)
    event(out, "preparing")
    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        raise ValueError("Install ffmpeg (including ffprobe) first")
    info = {"source": source, "episode_hint": episode}
    local = Path(source).expanduser()
    if local.is_file():
        acquired = out / ("input" + local.suffix)
        shutil.copyfile(local, acquired)
        info["title"] = local.name
    elif source.startswith(("http://", "https://")):
        if youtube_url(source):
            raise ValueError(YOUTUBE_REFUSAL)
        else:
            transport = CachedPublicTransport()
            public = caller(out, transport)
            resolution = resolve(public, source, hint=episode)
            save(
                out / "resolution.json",
                {
                    "state": resolution.state,
                    "gaps": resolution.gaps,
                    "aliases": resolution.aliases,
                    "candidates": [c.model_dump(mode="json") for c in resolution.candidates],
                },
            )
            if resolution.state != "resolved" or len(resolution.candidates) != 1:
                raise ValueError(
                    "Select a recording using resolution.json and --episode or its URL"
                )
            candidate = resolution.candidates[0]
            info["candidate"] = candidate.model_dump(mode="json")
            info["title"] = candidate.title
            if candidate.family == "youtube":
                raise ValueError(YOUTUBE_REFUSAL)
            elif candidate.media_url:
                # A resolver may have already fetched the enclosure while following a page.
                response = transport.media.get(candidate.media_url)
                if response is None:
                    response = fetch(public, candidate.media_url, binary=True)
                acquired = out / "input.media"
                acquired.write_bytes(response.body)
            else:
                raise ValueError(
                    "Source resolved to text, not audio; supply the recording or RSS URL"
                )
    else:
        raise ValueError("Source must be a local media file or a public HTTP(S) URL")
    audio, prepared = prepare_audio(acquired)
    info.update(
        {
            **prepared,
            "audio_file": audio.name,
            "content_type": prepared["mime"],
            "original_file": acquired.name,
            "audio_bytes": audio.stat().st_size,
            "duration_seconds": prepared["duration_s"],
            "audio_track": "0:a:0",
        }
    )
    save(out / "source.json", info)
    event(out, "prepared", duration_seconds=info["duration_seconds"])


def timestamp(seconds):
    if not isinstance(seconds, (int, float)) or not math.isfinite(seconds) or seconds < 0:
        return None
    millis = round(seconds * 1000)
    hours, millis = divmod(millis, 3_600_000)
    minutes, millis = divmod(millis, 60_000)
    seconds, millis = divmod(millis, 1000)
    return f"{hours:02}:{minutes:02}:{seconds:02}.{millis:03}"


def render(out):
    data = json.loads((out / "deepgram-response.json").read_bytes())
    source = json.loads((out / "source.json").read_text())
    results = data.get("results", {})
    alternatives = [
        c["alternatives"][0] for c in results.get("channels", []) if c.get("alternatives")
    ]
    words = [w for a in alternatives for w in a.get("words", [])]
    utterances = results.get("utterances", [])
    segments = speaker_segments(utterances)
    save(out / "words.json", words)
    save(out / "utterances.json", utterances)
    save(out / "segments.json", segments)
    lines = [
        f"# {source.get('title') or 'Media transcript'}",
        "",
        f"Source: {source.get('candidate', {}).get('url') or source['source']}",
        "",
        "Machine transcript. Speaker numbers identify voice clusters, not verified names.",
        "Wording, timing and speaker assignments need listening review.",
        "",
    ]
    cues = ["WEBVTT", ""]
    warnings = []
    for u in segments:
        start, end = timestamp(u.get("start")), timestamp(u.get("end"))
        speaker = f"Speaker {u['speaker']}" if u.get("speaker") is not None else "Speaker unknown"
        text = u.get("transcript", "")
        lines += [f"**[{start or 'time unknown'} – {end or 'time unknown'}] {speaker}**", text, ""]
        if start and end and u["end"] > u["start"]:
            cues += [f"{start} --> {end}", f"<v {speaker}>{html.escape(text)}</v>", ""]
    if not utterances:
        warnings.append("No utterances returned; unsegmented transcript preserved below")
        lines += [a.get("transcript", "") for a in alternatives]
    if not data.get("metadata", {}).get("diarize_info"):
        warnings.append("Provider did not report diarizer metadata; inspect speaker coverage")
    missing_speakers = sum(w.get("speaker") is None for w in words)
    missing_times = sum(
        timestamp(w.get("start")) is None or timestamp(w.get("end")) is None for w in words
    )
    if missing_speakers or missing_times:
        warnings.append("Some words lack speaker labels or valid timing; no values were invented")
    if not words:
        warnings.append("No word-level transcription returned")
    mixed = sum(len({w.get("speaker") for w in u.get("words", [])}) > 1 for u in utterances)
    if mixed:
        warnings.append(
            f"{mixed} mixed-speaker utterances split using word-level labels for display"
        )
    if any(
        u.get("speaker") is None
        or timestamp(u.get("start")) is None
        or timestamp(u.get("end")) is None
        for u in utterances
    ):
        warnings.append("Some utterances lack speaker labels or timing")
    ends = [w["end"] for w in words if timestamp(w.get("end")) is not None]
    duration = source["duration_seconds"]
    last_end = max(ends, default=None)
    if last_end is not None and duration - last_end > 30:
        warnings.append("Last word is over 30 seconds before file end; check silence or truncation")
    request_path = out / "request.json"
    request = json.loads(request_path.read_text()) if request_path.exists() else {}
    expected_hash = (
        source.get("original_sha256")
        if request.get("delivery") == "url"
        else (source.get("audio_sha256"))
    )
    actual_hash = data.get("metadata", {}).get("sha256")
    hash_matches = actual_hash == expected_hash if actual_hash and expected_hash else None
    if hash_matches is False:
        warnings.append(
            "Provider file checksum differs from prepared input; investigate source identity"
        )
    quality = {
        "provider_file_checksum_matches": hash_matches,
        "word_count": len(words),
        "utterance_count": len(utterances),
        "rendered_segment_count": len(segments),
        "mixed_speaker_utterance_count": mixed,
        "speaker_labels": sorted({w["speaker"] for w in words if w.get("speaker") is not None}),
        "words_without_speaker": missing_speakers,
        "words_without_timing": missing_times,
        "words_confidence_below_0_8": sum(w.get("confidence", 1) < 0.8 for w in words),
        "words_speaker_confidence_below_0_8": sum(
            w.get("speaker_confidence", 1) < 0.8 for w in words
        ),
        "words_without_speaker_confidence": sum(w.get("speaker_confidence") is None for w in words),
        "audio_duration_seconds": duration,
        "last_word_end_seconds": last_end,
        "provider_metadata": data.get("metadata", {}),
        "warnings": warnings,
        "accuracy_assessed": False,
    }
    save(out / "quality.json", quality)
    (out / "transcript.md").write_text("\n".join(lines) + "\n")
    (out / "transcript.vtt").write_text("\n".join(cues) + "\n")
    return quality


def transcribe(out, language="en", keyterms=(), delivery="upload"):
    if (out / "submission.json").exists():
        raise ValueError(
            "An attempt already exists. Use render; inspect it before any new purchase"
        )
    source = json.loads((out / "source.json").read_text())
    audio = (out / source["audio_file"]).read_bytes()
    if hashlib.sha256(audio).hexdigest() != source["audio_sha256"]:
        raise ValueError("Prepared audio changed")
    content_type = source.get("content_type", "audio/flac")
    remote_url = None
    if delivery == "url":
        remote_url = source.get("candidate", {}).get("media_url")
        if not remote_url:
            raise ValueError("URL delivery requires a resolved public media enclosure")
        remote_url = public_url(remote_url)
        if source.get("audio_stream_count") != 1:
            raise ValueError("Use upload for files requiring first-track selection")
        body = json.dumps({"url": remote_url}).encode()
        content_type = "application/json"
    else:
        body = audio
    env = dotenv_values(ROOT / ".env")
    key = os.environ.get("DEEPGRAM_API_KEY") or env.get("DEEPGRAM_API_KEY")
    if not key:
        raise ValueError("Set DEEPGRAM_API_KEY in .env")
    settings = load_settings(_env_file=ROOT / ".env")
    secrets = Secrets(_env_file=ROOT / ".env")
    runtime = install_production_tracing(settings, secrets, service_name="deepgram-trial")
    traced = install_production_langfuse(
        settings, secrets, runtime=runtime, service_name="deepgram-trial"
    )
    params = parameters(language, keyterms)
    # Win exclusive ownership before writing the request manifest as well as before spending.
    # The marker remains after timeout: never silently purchase a duplicate.
    with (out / "submission.json").open("x") as stream:
        json.dump({"submitted_at": datetime.now(UTC).isoformat()}, stream)
    save(
        out / "request.json",
        {
            "endpoint": "https://api.deepgram.com/v1/listen",
            "query": params,
            "content_type": content_type,
            "delivery": delivery,
            "remote_media_url": remote_url,
            "audio_sha256": source["audio_sha256"],
            "max_attempts": 1,
            "cost_usd": None,
        },
    )
    started = monotonic()
    event(out, "submitting")
    try:
        with (
            observation("research.media.deepgram-trial") as span,
            propagate_trace(
                trace_name="research.media.deepgram-trial",
                session_id=out.name,
                tags=["standalone", "deepgram", "media-trial"],
            ),
        ):
            save(
                out / "trace-linkage.json",
                {
                    "trace_id": span.trace_id,
                    "observation_id": span.id,
                    "langfuse_installed": traced,
                },
            )
            result = caller(out, HttpxTransport()).call(
                CallSpec(
                    provider="deepgram",
                    operation="listen/pre-recorded",
                    label="media.trial",
                    request=HttpRequest(
                        "POST",
                        "https://api.deepgram.com/v1/listen?" + urlencode(params, doseq=True),
                        headers={
                            "Authorization": f"Token {key}",
                            "Content-Type": content_type,
                        },
                        body=body,
                        timeout_s=660,
                    ),
                    estimate=SpendEstimate(media_seconds=math.ceil(source["duration_seconds"])),
                    binary_request=delivery == "upload",
                    max_attempts=1,
                    cost_reader=read_cost,
                    extras={"usd_unpriced": True, "standalone": True},
                )
            )
            # Exact provider bytes, not a reformatted or LLM-rewritten transcript.
            (out / "deepgram-response.json").write_bytes(result.response.body)
            save(
                out / "receipt.json",
                {
                    "http_status": result.response.status,
                    "request_id": result.cost.provider_request_id,
                    "raw_ref": result.raw_ref,
                    "ledger_row_id": result.ledger_row_id,
                    "elapsed_seconds": round(monotonic() - started, 2),
                    "cost_usd": None,
                    "cost_note": "Check Deepgram billing; YC credits not inferred",
                },
            )
            if not 200 <= result.response.status < 300:
                raise ValueError(
                    f"Deepgram HTTP {result.response.status}; inspect retained response"
                )
            quality = render(out)
        event(out, "completed", words=quality["word_count"], speakers=quality["speaker_labels"])
    except Exception as exc:
        event(
            out,
            "failed_or_uncertain",
            error_type=type(exc).__name__,
            note="Inspect raw/ledger before retry; submission may have reached the provider",
        )
        raise
    finally:
        flush_langfuse()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stage", choices=["prepare", "transcribe", "render"])
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--source", help="Public RSS/page/media/YouTube URL or local recording")
    parser.add_argument("--episode", help="Exact RSS episode title, GUID, or episode URL")
    parser.add_argument(
        "--language", default="en", help="en, another supported code, auto or multi"
    )
    parser.add_argument("--keyterm", action="append", default=[])
    parser.add_argument(
        "--delivery",
        choices=["upload", "url"],
        default="upload",
        help="url lets Deepgram fetch a resolved public RSS/media enclosure",
    )
    args = parser.parse_args()
    out = args.out.expanduser().resolve()
    if args.stage == "prepare":
        if not args.source:
            parser.error("prepare requires --source")
        try:
            prepare(args.source, out, args.episode)
        except FileExistsError:
            raise  # Do not modify an earlier experiment's log.
        except Exception as exc:
            if out.is_dir():
                event(out, "preparation_failed", error_type=type(exc).__name__)
            raise
    elif args.stage == "transcribe":
        transcribe(out, args.language, args.keyterm, args.delivery)
    else:
        render(out)


if __name__ == "__main__":
    main()
