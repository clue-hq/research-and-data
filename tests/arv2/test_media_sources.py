"""Official and public media sources (spec 2026-10-13-legitimate-media-sources-design). Offline."""

from __future__ import annotations

from clue_config.secrets import Secrets
from clue_spend import redact_headers


def test_media_source_keys_load_from_the_environment(monkeypatch):
    monkeypatch.setenv("CLUE_YOUTUBE_DATA_API_KEY", "yt-key")
    monkeypatch.setenv("CLUE_PODCAST_INDEX_API_KEY", "pi-key")
    monkeypatch.setenv("CLUE_PODCAST_INDEX_API_SECRET", "pi-secret")
    secrets = Secrets(_env_file=None)
    assert secrets.youtube_data_api_key.get_secret_value() == "yt-key"
    assert secrets.podcast_index_api_key.get_secret_value() == "pi-key"
    assert secrets.podcast_index_api_secret.get_secret_value() == "pi-secret"


def test_podcast_index_key_header_is_redacted_in_raw_records():
    headers = redact_headers(
        {"X-Auth-Key": "pi-key", "Authorization": "digest", "X-Auth-Date": "1700000000"}
    )
    assert headers["X-Auth-Key"] == "***" and headers["Authorization"] == "***"
    assert headers["X-Auth-Date"] == "1700000000"
