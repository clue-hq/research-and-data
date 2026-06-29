"""The canonical campaign phase sequence (M7.3) — pure, no DB.

M7.3 AC: "the phase set and ordering exactly match the conventions §3 / Doc C §4 sequence." These
lock that ordering and the ``next_phase`` walk to the single source of truth (``core.CampaignPhase``
/ ``obs.CAMPAIGN_PHASES``), so a reordering or a dropped phase fails loudly here.
"""

from __future__ import annotations

from clue_research.core import CampaignPhase
from clue_research.durable import PHASE_SEQUENCE, next_phase
from clue_research.obs import CAMPAIGN_PHASES

# conventions §3 / Doc C §4 — the exact phase list, written out so a reorder of the enum is caught
# against an independent literal (not just re-derived from the same enum).
_EXPECTED = (
    "reverse_profiling",
    "icp_confirmed",
    "discovery",
    "scoring",
    "tier_checkpoint",
    "deep",
    "verification",
    "review",
    "handoff",
)


def test_phase_sequence_matches_conventions() -> None:
    assert tuple(p.value for p in PHASE_SEQUENCE) == _EXPECTED


def test_phase_sequence_is_the_core_enum_order() -> None:
    # Single source of truth: the state machine order is exactly the core enum's definition order.
    assert tuple(CampaignPhase) == PHASE_SEQUENCE


def test_phase_sequence_matches_obs_span_tokens() -> None:
    # The obs span tokens and the state-machine order derive from the same enum — they cannot drift.
    assert tuple(p.value for p in PHASE_SEQUENCE) == CAMPAIGN_PHASES


def test_next_phase_walks_the_sequence() -> None:
    for current, expected in zip(PHASE_SEQUENCE, PHASE_SEQUENCE[1:], strict=False):
        assert next_phase(current) is expected


def test_next_phase_terminal_is_none() -> None:
    assert next_phase(CampaignPhase.HANDOFF) is None
    # tier_checkpoint resumes into deep — the human-gate transition.
    assert next_phase(CampaignPhase.TIER_CHECKPOINT) is CampaignPhase.DEEP
