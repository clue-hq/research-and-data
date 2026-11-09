"""The downloadable video file behind a social post, for transcription by file link.

LinkedIn, Instagram and Facebook post readers already return their posts' video file links. An X
post link needs one lookup (ScrapeCreators' tweet tool through treg); the best MP4 it lists is the
file Deepgram transcribes.
"""

from __future__ import annotations

from typing import Any

from pydantic import SecretStr

from clue_api.footprint.treg_client import TREG_BASE_URL, treg_call
from clue_spend.calls import ProviderCaller
from clue_spend.errors import ProviderTransportError

X_TWEET = "scrapecreators.x.v1-twitter-tweet"


def _variants(body: Any) -> list[dict[str, Any]]:
    legacy = body.get("legacy") if isinstance(body, dict) else None
    if not isinstance(legacy, dict):
        return []
    entities = legacy.get("extended_entities") or legacy.get("entities") or {}
    found: list[dict[str, Any]] = []
    for media in entities.get("media") or []:
        found += (media.get("video_info") or {}).get("variants") or []
    return found


def x_video_file(
    caller: ProviderCaller, token: SecretStr, post_url: str, *, base_url: str = TREG_BASE_URL
) -> str | None:
    """The highest-bitrate MP4 of an X post's video, or ``None`` when it has none."""
    try:
        reply = treg_call(
            caller, token, X_TWEET, {"url": post_url, "trim": "false"}, base_url=base_url
        )
    except ProviderTransportError:
        return None
    mp4s = [
        v
        for v in _variants(reply.body)
        if v.get("content_type") == "video/mp4" and isinstance(v.get("url"), str)
    ]
    return max(mp4s, key=lambda v: v.get("bitrate") or 0)["url"] if mp4s else None
