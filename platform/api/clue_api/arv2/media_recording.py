"""Lossless audio preparation for batch ASR.

YouTube is never downloaded here (spec 2026-10-13-legitimate-media-sources-design §2): its
videos are read by Gemini from the public link, or replaced by the same episode's podcast feed.
"""

from __future__ import annotations

import hashlib
import json
import math
import subprocess
from pathlib import Path
from typing import Any


def command(args: list[str]) -> str:
    result = subprocess.run(args, capture_output=True, text=True, timeout=900, check=False)
    if result.returncode:
        # Do not echo signed URLs or provider diagnostics into the model conversation.
        raise ValueError(
            f"recording preparation failed: {Path(args[0]).name} exit {result.returncode}"
        )
    return result.stdout


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
