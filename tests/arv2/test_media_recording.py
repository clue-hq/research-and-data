"""Local synthetic recordings and mocked downloader commands; no provider/network access."""

import json
import shutil
import wave

import pytest

from clue_api.arv2 import media_recording as recording


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


def test_youtube_is_never_downloaded():
    """Spec 2026-10-13 §2: no yt-dlp anywhere; YouTube is read by Gemini from its public link."""
    assert not hasattr(recording, "download_youtube")
    assert not hasattr(recording, "YouTubeAudioTransport")
    assert not hasattr(recording, "fetch_youtube")


def test_the_deepgram_trial_script_imports_and_refuses_youtube(tmp_path):
    import importlib.util
    from pathlib import Path

    path = Path(__file__).parents[2] / "scripts" / "trial_deepgram_media.py"
    spec = importlib.util.spec_from_file_location("trial_deepgram_media", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    with pytest.raises(ValueError, match="never downloaded"):
        module.prepare("https://youtu.be/abcdefghijk", tmp_path / "out")
