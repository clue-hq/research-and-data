"""Refusal codes the arv2 drivers and tools can emit, and the envelope the model receives.

A refusal spends nothing, suspends nothing and ends nothing (master plan Appendix A 12; substance
§5). The ``reaction`` sentence is the manual's row for that code, so the model reads the correct
move inside the envelope and the manual test proves the two never drift.

One table serves both agents. ``REFUSAL_CODES`` is what the account driver can emit;
``PERSON_REFUSAL_CODES`` is what the person driver can emit — the five person codes plus every
shared code whose tool the person toolbelt keeps. The person agent has no ATS board and no company
lookup, so those three codes are not in its set and its manual carries no row for them.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

from clue_api.arv2.errors import Arv2Error

#: One row per code in ``manual.md``; the reaction text there is this text, word for word.
REACTIONS: dict[str, str] = {
    "provider_halted": (
        "Continue with the other providers and note the gap; never retry that provider in this job."
    ),
    "board_not_found": (
        "Fetch the careers page itself with fetch_page; hiring is a gap only after both were read; "
        "never guess a slug."
    ),
    "board_fetch_failed": "Record hiring as an honest gap; do not re-fetch the board.",
    "page_unavailable": (
        "Record the URL as unreadable; try a different known URL, never a search for the same page."
    ),
    "company_not_found": "AI Ark has no record for this domain; continue from the web sources.",
    "feed_not_found": (
        "Every URL given failed to load (the message names each with its error). If you have not "
        "yet passed alternates — the podcast's other feed host, the YouTube upload of the same "
        "episode — call once more with them in alternate_urls; otherwise media stays empty for "
        "this person; move on."
    ),
    "episode_not_found": "The feed has no matching episode; media stays empty for this person.",
    "media_ceiling_reached": (
        "Skip this item; the reservation was released; do not shorten and retry."
    ),
    "enclosure_too_large": "Skip this item; do not retry with another URL for the same episode.",
    "native_video_rejected": (
        "Look for the same talk elsewhere (YouTube, Vimeo, the event's own page or a podcast) and "
        "read it with read_media; never a video download."
    ),
    "youtube_read_retired": (
        "Call read_media with the YouTube link: it finds the video's podcast episode or reads the "
        "public video through the official route."
    ),
    "speaker_unverified": (
        "Quote nothing from this transcript; record the item as unattributed media."
    ),
    "deep_thin_response": (
        "Both deep attempts came back thin; structure what the free sources yielded; do not call "
        "research_deep again."
    ),
    "structuring_unparseable": (
        "Resend the same material once; if it fails again record the subject as unstructured."
    ),
    "already_established": "Drop that field from the call; it is already recorded.",
    "identical_call_repeated": (
        "Change the arguments the way the earlier refusal named, make the call it named, or "
        "finalize honestly."
    ),
    "too_many_parallel_calls": (
        "Re-issue the refused calls in the next round; the calls within the per-round ceiling ran."
    ),
    "finalization_already_proposed": "The decision is made; stop.",
    "tool_error": (
        "The tool failed for a reason outside your control; record the gap and continue."
    ),
    "invalid_arguments": "Correct the named argument and call again.",
    # --- R3, the person driver ---
    "subject_lock_failed": (
        "This candidate is not the person; record the lookalike; no person job."
    ),
    "email_export_empty": "Record no email; the member is still researched.",
    "media_cap_reached": (
        "Media for this person is complete; do not call read_media_feeds again for them."
    ),
    "insight_not_found": 'Record "thin public footprint" with channels checked; move on.',
}

#: The codes only the person driver emits.
_PERSON_ONLY_CODES: frozenset[str] = frozenset(
    {
        "subject_lock_failed",
        "email_export_empty",
        "media_cap_reached",
        "insight_not_found",
    }
)

#: The codes only the account driver emits: the ATS board and the company lookup are account tools.
_ACCOUNT_ONLY_CODES: frozenset[str] = frozenset(
    {"board_not_found", "board_fetch_failed", "company_not_found"}
)

REFUSAL_CODES: frozenset[str] = frozenset(REACTIONS) - _PERSON_ONLY_CODES
PERSON_REFUSAL_CODES: frozenset[str] = frozenset(REACTIONS) - _ACCOUNT_ONLY_CODES


@dataclass(frozen=True)
class Refusal:
    """One governed refusal: the code, why it fired, and the one admissible move."""

    code: str
    detail: str

    @property
    def reaction(self) -> str:
        """The manual's reaction for this code. Suffix forms resolve on the base code."""
        return REACTIONS[self.code.split(":", 1)[0]]


class RefusalError(Arv2Error):
    """Raised inside a tool body; the tool wrapper turns it into the envelope, never a raise."""

    def __init__(self, code: str, detail: str) -> None:
        base = code.split(":", 1)[0]
        if base not in REACTIONS:
            raise ValueError(f"unknown refusal code {code!r}")
        super().__init__(f"{code}: {detail}")
        self.refusal = Refusal(code=code, detail=detail)


def refusal_json(code: str, detail: str) -> str:
    """The tool-result envelope the model reads: recoverable, with the manual's reaction inside."""
    refusal = Refusal(code=code, detail=detail)
    return json.dumps(
        {
            "error": "governed_research_rejection",
            "code": code,
            "detail": detail[:1_000],
            "recoverable": True,
            "reaction": refusal.reaction,
        },
        sort_keys=True,
        separators=(",", ":"),
    )
