"""Local synthetic recordings and mocked downloader commands; no provider/network access."""

import json
import shutil
import wave

import pytest

from clue_api.arv2 import media_recording as recording
from clue_spend.transport import HttpRequest


def test_lossless_wav_passes_through_without_resampling(tmp_path):
    if not shutil.which("ffprobe"):
        pytest.skip("ffprobe not installed")
    source = tmp_path / "source.wav"
    with wave.open(str(source), "wb") as writer:
        writer.setnchannels(2)
        writer.setsampwidth(2)
        writer.setframerate(16000)
        writer.writeframes(b"\0" * 64000)
    before = source.read_bytes()
    audio, metadata = recording.prepare_audio(source)
    assert audio.read_bytes() == before
    assert metadata["preparation"] == "original_audio_bytes"
    assert metadata["channels"] == 2 and metadata["sample_rate"] == "16000"
    assert metadata["audio_sha256"] == metadata["original_sha256"]
    assert metadata["duration_s"] == 1


def test_video_first_audio_track_is_extracted_without_channel_or_sample_changes(
    tmp_path, monkeypatch
):
    source = tmp_path / "input.video"
    source.write_bytes(b"video")
    calls = []

    def command(args):
        calls.append(args)
        if args[0] == "ffprobe":
            return json.dumps(
                {
                    "format": {"duration": "12.4", "format_name": "mp4"},
                    "streams": [{"codec_type": "video"}, {"codec_type": "audio", "channels": 2}],
                }
            )
        (tmp_path / "prepared.flac").write_bytes(b"lossless audio")
        return ""

    monkeypatch.setattr(recording, "command", command)
    audio, metadata = recording.prepare_audio(source)
    assert audio.name == "prepared.flac" and metadata["duration_s"] == 13
    assert "0:a:0" in calls[1] and "flac" in calls[1]
    assert "-ar" not in calls[1] and "-ac" not in calls[1]


def test_youtube_acquisition_is_exact_public_single_recording(monkeypatch):
    monkeypatch.setattr(recording, "find_spec", lambda _: object())
    monkeypatch.setattr(recording.shutil, "which", lambda _: "/bin/node")
    calls = []

    def command(args):
        calls.append(args)
        if "--dump-single-json" in args:
            return json.dumps({"availability": "public", "id": "abcdefghijk"})
        from pathlib import Path

        Path(args[args.index("-o") + 1].replace("%(ext)s", "webm")).write_bytes(b"audio")
        return ""

    monkeypatch.setattr(recording, "command", command)
    response = recording.YouTubeAudioTransport().send(
        HttpRequest("GET", "https://youtu.be/abcdefghijk")
    )
    assert response.body == b"audio"
    assert all("--ignore-config" in args and "--no-playlist" in args for args in calls)
    with pytest.raises(ValueError):
        recording.YouTubeAudioTransport().send(HttpRequest("GET", "http://localhost/audio"))
