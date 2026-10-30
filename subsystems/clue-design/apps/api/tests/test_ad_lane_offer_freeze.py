"""W4 offer-time freeze (Wave-C fix #1): the offer is the truth, the claim consumes it.

The pinned red case is the Wave-B W-B2 failure: a flag-off worker process claims a turn that
a flag-on deployment queued, and the turn silently loses its ad-lane references. Under the
freeze that outcome is impossible — the lane rides the envelope by value — and the one place
the old behaviour survives (a legacy envelope with no ``ad_lane`` key) is no longer allowed
to be silent about it.
"""

from __future__ import annotations

from typing import Any, Optional

import pytest

from lumen_api import ad_runtime
from py_lumen_config import settings

FROZEN = {
    "card": {"prose": "bold, yellow, direct", "style_groups": []},
    "creative_assets": {"cr_1": "asset_1", "cr_2": "asset_2"},
    "pregenerated": [{"asset_id": "gen_1", "shape": "wide background"}],
    "creatives": [
        {"creative_id": "cr_1", "asset_id": "asset_1", "headline": "Spend less",
         "commentary": "Ramp cuts costs.", "created_at": "2026-10-02T00:00:00+00:00"},
        {"creative_id": "cr_2", "asset_id": "asset_2", "headline": None,
         "commentary": None, "created_at": "2026-10-01T00:00:00+00:00"},
    ],
}


class _RecordingStore:
    """The lane's store seam; records whether the claim path ever consulted it."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    def list_creatives(self, *, limit: int = 50) -> list[dict]:
        self.calls.append("list_creatives")
        return [{"creative_id": "cr_9", "asset_id": "asset_9", "headline": "H9",
                 "commentary": "C9", "created_at": "2026-10-03T00:00:00+00:00"}]

    def latest_card(self, **_kwargs: Any) -> Optional[dict]:
        self.calls.append("latest_card")
        return None

    def list_pregenerated(self, **_kwargs: Any) -> list[dict]:
        self.calls.append("list_pregenerated")
        return []


@pytest.fixture
def recording_warnings(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, dict]]:
    seen: list[tuple[str, dict]] = []

    def warning(event: str, **kwargs: Any) -> None:
        seen.append((event, kwargs))

    monkeypatch.setattr(ad_runtime.logger, "warning", warning)
    return seen


def test_red_case_frozen_lane_beats_a_flag_off_claiming_process(
    monkeypatch: pytest.MonkeyPatch, recording_warnings: list
) -> None:
    """The Wave-B scenario, inverted: flag OFF in the claimant, lane still served."""
    monkeypatch.setattr(settings, "lumen_brand_ad_assets", False, raising=False)
    store = _RecordingStore()
    lane = ad_runtime.resolve_turn_ad_lane(FROZEN, workspace_id="ws_test", store=store)
    assert lane is not None and lane.creative_assets == FROZEN["creative_assets"]
    assert lane.card == FROZEN["card"]
    assert [dict(e) for e in lane.pregenerated] == FROZEN["pregenerated"]
    assert store.calls == []  # the offer decided; the claimant read nothing
    assert recording_warnings == []  # and nothing to warn about


def test_a_frozen_none_is_a_decision_not_a_fallback(
    monkeypatch: pytest.MonkeyPatch, recording_warnings: list
) -> None:
    """Offer said "no lane": even a flag-ON claimant with a full store serves none."""
    monkeypatch.setattr(settings, "lumen_brand_ad_assets", True, raising=False)
    store = _RecordingStore()
    assert ad_runtime.resolve_turn_ad_lane(None, workspace_id="ws_test", store=store) is None
    assert store.calls == []
    assert recording_warnings == []


def test_legacy_envelope_with_flag_off_is_loud_not_silent(
    monkeypatch: pytest.MonkeyPatch, recording_warnings: list
) -> None:
    """The old silent decline is dead: a legacy claim under a flag-off process says so."""
    monkeypatch.setattr(settings, "lumen_brand_ad_assets", False, raising=False)
    store = _RecordingStore()
    lane = ad_runtime.resolve_turn_ad_lane(workspace_id="ws_test", store=store)
    assert lane is None
    assert store.calls == []  # flag-off still never opens a connection
    events = [event for event, _ in recording_warnings]
    assert "ad_lane_flag_off_in_claiming_process" in events


def test_legacy_envelope_with_flag_on_composes_at_claim_time(
    monkeypatch: pytest.MonkeyPatch, recording_warnings: list
) -> None:
    monkeypatch.setattr(settings, "lumen_brand_ad_assets", True, raising=False)
    store = _RecordingStore()
    lane = ad_runtime.resolve_turn_ad_lane(workspace_id="ws_test", store=store)
    assert lane is not None and lane.creative_assets == {"cr_9": "asset_9"}
    assert "list_creatives" in store.calls
    assert recording_warnings == []


def test_frozen_lane_round_trips_through_the_envelope_shape() -> None:
    lane = ad_runtime.lane_from_frozen(FROZEN)
    assert lane is not None
    assert ad_runtime.lane_to_frozen(lane) == FROZEN
    assert ad_runtime.lane_to_frozen(None) is None


def test_a_malformed_frozen_value_never_fails_the_turn(recording_warnings: list) -> None:
    assert ad_runtime.lane_from_frozen("garbage") is None
    assert ad_runtime.lane_from_frozen({"creative_assets": []}) is None
    assert ad_runtime.lane_from_frozen({"creative_assets": {}}) is None
    events = [event for event, _ in recording_warnings]
    assert "ad_lane_frozen_malformed" in events


def test_the_offerer_freezes_what_read_ad_lane_would_serve(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """frozen_lane_payload is read_ad_lane by value: flag gate included."""
    store = _RecordingStore()
    monkeypatch.setattr(settings, "lumen_brand_ad_assets", True, raising=False)
    frozen = ad_runtime.frozen_lane_payload("ws_test", store=store)
    assert frozen is not None and frozen["creative_assets"] == {"cr_9": "asset_9"}
    monkeypatch.setattr(settings, "lumen_brand_ad_assets", False, raising=False)
    assert ad_runtime.frozen_lane_payload("ws_test", store=_RecordingStore()) is None


def test_shared_reduction_constants_still_exported() -> None:
    # main/other importers read these off ad_runtime; they now live in clue_design.ad_assets.
    from clue_design import ad_assets as shared

    assert ad_runtime.CREATIVE_SCAN == shared.CREATIVE_SCAN == 200
    assert ad_runtime.PREGENERATED_CONTEXT_MAX == shared.PREGENERATED_CONTEXT_MAX == 12


def test_the_frozen_lane_carries_each_creatives_headline_and_copy() -> None:
    lane = ad_runtime.lane_from_frozen(FROZEN)
    assert lane is not None
    assert lane.creatives[0]["headline"] == "Spend less"
    assert ad_runtime.lane_from_frozen(ad_runtime.lane_to_frozen(lane)) == lane


def test_a_legacy_frozen_lane_without_creatives_still_lists_them_blank() -> None:
    """A fleet turn offered before 2026-10-30 carries no ``creatives``; never a failed turn."""
    lane = ad_runtime.lane_from_frozen(
        {"card": None, "creative_assets": {"c1": "a1"}, "pregenerated": []}
    )
    assert lane is not None
    assert lane.creatives == (
        {"creative_id": "c1", "asset_id": "a1", "headline": None, "commentary": None,
         "created_at": None},
    )


def test_the_offerer_freezes_each_creatives_headline_and_copy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "lumen_brand_ad_assets", True, raising=False)
    frozen = ad_runtime.frozen_lane_payload("ws_test", store=_RecordingStore())
    assert frozen is not None
    assert frozen["creatives"] == [
        {"creative_id": "cr_9", "asset_id": "asset_9", "headline": "H9", "commentary": "C9",
         "created_at": "2026-10-03T00:00:00+00:00"}
    ]


def test_nothing_auto_attaches_any_more() -> None:
    for retired in ("select_reference_asset_ids", "choose_style_group", "AUTO_REFERENCE_MAX"):
        assert not hasattr(ad_runtime, retired)
