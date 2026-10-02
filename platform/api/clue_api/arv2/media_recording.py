"""Public recording acquisition and lossless audio preparation for batch ASR."""

from __future__ import annotations

import hashlib
import json
import math
import shutil
import subprocess
import sys
import tempfile
from importlib.util import find_spec
from pathlib import Path
from typing import Any

from clue_api.arv2.media_resolution import MAX_MEDIA_BYTES, youtube_url
from clue_spend.calls import CallSpec, ProviderCaller
from clue_spend.transport import HttpRequest, HttpResponse


def command(args: list[str]) -> str:
    result = subprocess.run(args, capture_output=True, text=True, timeout=900, check=False)
    if result.returncode:
        # Do not echo signed URLs or provider diagnostics into the model conversation.
        raise ValueError(
            f"recording preparation failed: {Path(args[0]).name} exit {result.returncode}"
        )
    return result.stdout


def download_youtube(url: str, out: Path) -> tuple[Path, dict[str, Any]]:
    target = youtube_url(url)
    if target is None:
        raise ValueError("Exact public YouTube recording required")
    if find_spec("yt_dlp") is None:
        raise ValueError("Install the locked clue-api dependencies for YouTube audio")
    base = [sys.executable, "-m", "yt_dlp", "--ignore-config", "--no-playlist", "--no-cache-dir"]
    # Use the installed dependency, never an older global yt-dlp executable.
    for engine in ("deno", "node"):
        if executable := shutil.which(engine):
            base.extend(["--js-runtimes", f"{engine}:{executable}"])
            break
    meta = json.loads(command([*base, "--dump-single-json", "--skip-download", target[0]]))
    if meta.get("availability") not in {None, "public"} or meta.get("is_live"):
        raise ValueError("Only public, non-live recordings are supported")
    command(
        [
            *base,
            "--no-overwrites",
            "--max-filesize",
            str(MAX_MEDIA_BYTES),
            "-f",
            "bestaudio/best",
            "-o",
            str(out / "download.%(ext)s"),
            target[0],
        ]
    )
    files = [p for p in out.glob("download.*") if p.suffix not in {".part", ".ytdl"}]
    if len(files) != 1 or not 0 < files[0].stat().st_size <= MAX_MEDIA_BYTES:
        raise ValueError("Downloader did not produce one complete recording within byte limit")
    return files[0], {k: meta.get(k) for k in ("id", "title", "duration", "webpage_url")}


class YouTubeAudioTransport:
    """A journalled public download, with no cookies, shell or inherited downloader config."""

    def send(self, request: HttpRequest) -> HttpResponse:
        if request.method != "GET":
            raise ValueError("YouTube audio transport only supports reads")
        with tempfile.TemporaryDirectory(prefix="arv2-youtube-") as directory:
            path, metadata = download_youtube(request.url, Path(directory))
            return HttpResponse(
                200,
                {
                    "content-type": "audio/octet-stream",
                    "x-arv2-recording-metadata": json.dumps(metadata),
                },
                path.read_bytes(),
            )


def fetch_youtube(caller: ProviderCaller, url: str) -> HttpResponse:
    target = youtube_url(url)
    if target is None:
        raise ValueError("Exact YouTube recording required")
    return caller.call(
        CallSpec(
            provider="public_media",
            operation="youtube/audio",
            label="media.download",
            request=HttpRequest("GET", target[0], timeout_s=900),
            binary=True,
            max_attempts=1,
        )
    ).response


def prepare_audio(path: Path) -> tuple[Path, dict[str, Any]]:
    probe = json.loads(
        command(
            [
                "ffprobe",
                "-v",
                "error",
                "-show_format",
                "-show_streams",
                "-of",
                "json",
                str(path),
            ]
        )
    )
    streams = probe.get("streams", [])
    audio_streams = [s for s in streams if s.get("codec_type") == "audio"]
    if not audio_streams:
        raise ValueError("Recording has no audio stream")
    duration = float(probe["format"]["duration"])
    if not math.isfinite(duration) or duration <= 0:
        raise ValueError("Recording duration is unavailable")
    formats = {"mp3": "audio/mpeg", "flac": "audio/flac", "wav": "audio/wav"}
    original_format = probe["format"].get("format_name")
    passthrough = original_format in formats and len(streams) == 1
    audio = path if passthrough else path.with_name("prepared.flac")
    if not passthrough:
        command(
            [
                "ffmpeg",
                "-nostdin",
                "-v",
                "error",
                "-n",
                "-i",
                str(path),
                "-map",
                "0:a:0",
                "-vn",
                "-c:a",
                "flac",
                str(audio),
            ]
        )
    if not 0 < audio.stat().st_size <= 2_000_000_000:
        raise ValueError("Prepared recording is empty or exceeds Deepgram upload limit")
    return audio, {
        "mime": formats[original_format] if passthrough else "audio/flac",
        "duration_s": math.ceil(duration),
        "audio_stream_count": len(audio_streams),
        "preparation": "original_audio_bytes" if passthrough else "lossless_first_audio_track",
        "original_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "audio_sha256": hashlib.sha256(audio.read_bytes()).hexdigest(),
        "channels": audio_streams[0].get("channels"),
        "sample_rate": audio_streams[0].get("sample_rate"),
    }
