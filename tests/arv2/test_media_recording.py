"""Local synthetic recordings and mocked downloader commands; no provider/network access."""

import json
import shutil
import wave

import pytest

from clue_api.arv2 import media_recording as recording


def test_a_downloaded_recording_becomes_small_mono_speech_audio(tmp_path):
    """Founder ruling 2026-10-16: whatever was downloaded (stereo, studio quality, a video), only
    small mono speech audio is sent: one channel, 16 kHz, 64 kbit/s MP3."""
    if not (shutil.which("ffprobe") and shutil.which("ffmpeg")):
        pytest.skip("ffmpeg/ffprobe not installed")
    source = tmp_path / "source.wav"
    with wave.open(str(source), "wb") as writer:
        writer.setnchannels(2)
        writer.setsampwidth(2)
        writer.setframerate(44100)
        writer.writeframes(b"\0" * 44100 * 4 * 3)
    audio, metadata = recording.prepare_audio(source)
    probed = json.loads(
        recording.command(["ffprobe", "-v", "error", "-show_streams", "-of", "json", str(audio)])
    )["streams"]
    assert [(s["codec_name"], s["channels"], s["sample_rate"]) for s in probed] == [
        ("mp3", 1, "16000")
    ]
    assert metadata["mime"] == "audio/mpeg" and metadata["preparation"] == "mono_speech_mp3"
    assert metadata["duration_s"] == 3
    assert audio.stat().st_size < source.stat().st_size / 10


def test_cover_art_or_video_does_not_change_how_the_speech_is_cut(tmp_path, monkeypatch):
    """An MP3 with its cover art is two streams; it was once converted to lossless FLAC (hundreds
    of MB for an hour) and uploaded. Only the first audio track is kept, cut down like any other."""
    source = tmp_path / "episode.mp3"
    source.write_bytes(b"audio with cover art")
    calls = []

    def command(args):
        calls.append(args)
        if args[0] == "ffprobe":
            return json.dumps(
                {
                    "format": {"duration": "3039.3", "format_name": "mp3"},
                    "streams": [
                        {"codec_type": "audio", "channels": 2, "sample_rate": "44100"},
                        {"codec_type": "video", "disposition": {"attached_pic": 1}},
                    ],
                }
            )
        (tmp_path / "speech.mp3").write_bytes(b"small speech")
        return ""

    monkeypatch.setattr(recording, "command", command)
    audio, metadata = recording.prepare_audio(source)
    assert audio.name == "speech.mp3" and metadata["duration_s"] == 3040
    ffmpeg = calls[1]
    assert ffmpeg[ffmpeg.index("-map") + 1] == "0:a:0" and "-vn" in ffmpeg
    assert ffmpeg[ffmpeg.index("-ac") + 1] == "1" and ffmpeg[ffmpeg.index("-ar") + 1] == "16000"
    assert ffmpeg[ffmpeg.index("-b:a") + 1] == "64k"
    assert "flac" not in ffmpeg


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
