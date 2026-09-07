"""Refusal codes the R2 driver and tools can emit, and the envelope the model receives.

A refusal spends nothing, suspends nothing and ends nothing (master plan Appendix A 12; substance
§5). The ``reaction`` sentence is the manual's row for that code, so the model reads the correct
move inside the envelope and the manual test proves the two never drift.
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
    "feed_not_found": "No podcast or YouTube for this person; media stays empty; move on.",
    "episode_not_found": "The feed has no matching episode; media stays empty for this person.",
    "media_ceiling_reached": (
        "Skip this item; the reservation was released; do not shorten and retry."
    ),
    "enclosure_too_large": "Skip this item; do not retry with another URL for the same episode.",
    "native_video_rejected": "Use the YouTube words path (page text), never a video download.",
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
        "Re-issue the refused calls in the next round; the first fifty of this round ran."
    ),
    "finalization_already_proposed": "The decision is made; stop.",
    "tool_error": (
        "The tool failed for a reason outside your control; record the gap and continue."
    ),
    "invalid_arguments": "Correct the named argument and call again.",
}

REFUSAL_CODES: frozenset[str] = frozenset(REACTIONS)


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
