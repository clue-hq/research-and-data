"""Speech audio preparation for batch ASR: a downloaded recording is cut to small mono audio.

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

#: What a downloaded recording is cut down to before it is sent for transcription.
SPEECH_AUDIO_ARGS = ("-ac", "1", "-ar", "16000", "-c:a", "libmp3lame", "-b:a", "64k")


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
    # Founder ruling 2026-10-16: a downloaded recording is only transcription input, so only
    # small mono speech audio is sent, whatever was downloaded: the first audio track, one
    # channel, 16 kHz, 64 kbit/s MP3 (about 0.5 MB a minute). Cover art and video are dropped. The
    # old lossless FLAC of an hour's podcast was hundreds of MB and stalled the upload.
    audio = path.with_name("speech.mp3")
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
            *SPEECH_AUDIO_ARGS,
            str(audio),
        ]
    )
    if not 0 < audio.stat().st_size <= 2_000_000_000:
        raise ValueError("Prepared recording is empty or exceeds Deepgram upload limit")
    return audio, {
        "mime": "audio/mpeg",
        "duration_s": math.ceil(duration),
        "audio_stream_count": len(audio_streams),
        "preparation": "mono_speech_mp3",
        "original_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "audio_sha256": hashlib.sha256(audio.read_bytes()).hexdigest(),
        "source_channels": audio_streams[0].get("channels"),
        "source_sample_rate": audio_streams[0].get("sample_rate"),
    }
