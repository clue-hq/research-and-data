"""W4 — the Brand Ad Assets lane at TURN time (spec §5 W4).

Two halves, matching the two things a scene turn takes out of the lane:

* **Selection** — pure, no database and no model call. `select_reference_asset_ids` takes its
  group-picker as a seam, so both branches (the match and the deterministic fallback) are
  driven directly.
* **Composition** — a real scene turn through `run_agent_turn_preview`, with the lane's STORE
  faked and everything downstream real: the flag check, the manifest build against real
  uploaded assets, and the config the runtime is handed. Faking the store rather than
  `read_ad_lane` is deliberate — it keeps the flag gate live, which is the only way the
  flag-off red case means anything.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Optional
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from conftest import make_client
from lumen_api import ad_runtime
from lumen_api.main import REFERENCE_ASSETS_MAX, create_app, repo_root, run_agent_turn_preview
from lumen_api.models import AgentTurnPreviewRequest
from py_lumen_config import settings

REPO_ROOT = Path(__file__).resolve().parents[3]
MINIMAL_SCENE_PATH = REPO_ROOT / "crates/lumen-core/fixtures/minimal_scene.json"
LOGO_PNG_PATH = REPO_ROOT / "crates/lumen-export/fixtures/assets/acme-logo-8x8-red.png"


@pytest.fixture()
def client(tmp_path: Path) -> TestClient:
    return make_client(create_app(tmp_path / "engine-cache"))


def minimal_scene() -> dict:
    return json.loads(MINIMAL_SCENE_PATH.read_text())


def upload_logo(client: TestClient, *, label: str) -> Any:
    return client.post(
        "/assets",
        files={"file": ("acme-logo.png", LOGO_PNG_PATH.read_bytes(), "image/png")},
        data={"label": label, "kind": "logo", "uploaded_by": "designer"},
    )


PROSE = (
    "These ads are one flat deep-green field with a heavy headline on the left. "
    "A lime accent shows up once, on the button."
)


def _lane(groups: list[dict] | None, creatives: dict[str, str]) -> ad_runtime.AdLane:
    card = {"schema_version": 2, "prose": PROSE, "style_groups": groups or []}
    return ad_runtime.AdLane(card=card, creative_assets=creatives)


class _FakeStore:
    """The lane's store, as `read_ad_lane` uses it. Records that it was consulted at all."""

    def __init__(
        self,
        creatives: list[dict],
        card: Optional[dict] = None,
        pregenerated: Optional[list[dict]] = None,
    ) -> None:
        self._creatives = creatives
        self._card = card
        self._pregenerated = pregenerated or []
        self.calls: list[str] = []

    def list_creatives(self, *, limit: int = 50) -> list[dict]:
        del limit
        self.calls.append("list_creatives")
        return list(self._creatives)

    def latest_card(self, **_kwargs: Any) -> Optional[dict]:
        self.calls.append("latest_card")
        return self._card

    def list_pregenerated(self, *, card_id: str, card_version: int) -> list[dict]:
        # Recorded WITH its arguments: W5/R2-D pins the listing to the ACTIVE card version, and
        # a read that silently widened to the lineage would serve imagery generated from a
        # description the brand has since replaced.
        self.calls.append(f"list_pregenerated:{card_id}:{card_version}")
        return list(self._pregenerated)


# --- the cap ----------------------------------------------------------------------------------


def test_the_auto_cap_is_the_same_four_as_the_manual_cap() -> None:
    """Founder ruling 2026-08-24: the reference cap is FOUR, and it is one number. Two
    constants exist only because `main` imports `ad_runtime` and not the reverse."""
    assert ad_runtime.AUTO_REFERENCE_MAX == REFERENCE_ASSETS_MAX == 4


# --- reading the lane -------------------------------------------------------------------------


def test_a_flag_off_process_never_even_asks_the_database(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """RED CASE. Flag off is OFF: not "on but empty". A query issued on every scene turn of
    every workspace that never onboarded ads is a permanent cost for a permanently absent
    feature, and the flag is what promises it is not being paid."""
    store = _FakeStore([{"creative_id": "adcre_a", "asset_id": "asset_a"}])
    monkeypatch.setattr(settings, "lumen_brand_ad_assets", False, raising=False)
    assert ad_runtime.read_ad_lane("ws_test", store=store) is None
    assert store.calls == []

    monkeypatch.setattr(settings, "lumen_brand_ad_assets", True, raising=False)
    assert ad_runtime.read_ad_lane("ws_test", store=store) is not None
    assert "list_creatives" in store.calls


# --- W5/R2-D: the pre-generated grounds leave the database ------------------------------------


PREGENERATED_ROWS = [
    {
        "asset_id": "asset_gen_aaaa1111",
        "visual_system": "Deep Field",
        "prompt": "…",
        "generation": {"aspect_ratio": "16:9"},
    },
    {
        "asset_id": "asset_gen_bbbb2222",
        "visual_system": "Deep Field",
        "prompt": "…",
        "generation": {"aspect_ratio": "1:1"},
    },
]


def test_the_lane_now_carries_the_pregenerated_grounds_for_the_active_card(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """RED CASE. Nothing at turn time read `design_ad_pregenerated_asset` at all.

    The W5 Ramp run paid for twelve grounds and its turn referenced none of them, because the
    only path out of that table was the operator's inspection route.
    """
    monkeypatch.setattr(settings, "lumen_brand_ad_assets", True, raising=False)
    store = _FakeStore(
        [{"creative_id": "adcre_a", "asset_id": "asset_a"}],
        card={
            "card_id": "adna_kit",
            "version": 3,
            "card": {"schema_version": 2, "prose": PROSE, "style_groups": []},
        },
        pregenerated=PREGENERATED_ROWS,
    )

    lane = ad_runtime.read_ad_lane("ws_test", store=store)

    assert lane is not None
    # Pinned to the ACTIVE card version, never the lineage.
    assert "list_pregenerated:adna_kit:3" in store.calls
    assert lane.pregenerated == (
        {"asset_id": "asset_gen_aaaa1111", "style_group": "Deep Field", "shape": "wide ground"},
        {"asset_id": "asset_gen_bbbb2222", "style_group": "Deep Field", "shape": "square ground"},
    )
    assert ad_runtime.context_pregenerated(lane) == [dict(e) for e in lane.pregenerated]


def test_a_flag_off_process_never_asks_for_the_grounds_either(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The listing is inside the flag's promise, not beside it."""
    monkeypatch.setattr(settings, "lumen_brand_ad_assets", False, raising=False)
    store = _FakeStore(
        [{"creative_id": "adcre_a", "asset_id": "asset_a"}], pregenerated=PREGENERATED_ROWS
    )

    assert ad_runtime.read_ad_lane("ws_test", store=store) is None
    assert store.calls == []


def test_a_lane_with_no_imagery_carries_none_rather_than_an_empty_list(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Absence, not emptiness — the rule every by-value channel here follows."""
    monkeypatch.setattr(settings, "lumen_brand_ad_assets", True, raising=False)
    store = _FakeStore(
        [{"creative_id": "adcre_a", "asset_id": "asset_a"}],
        card={"card_id": "adna_kit", "version": 1, "card": {"prose": PROSE}},
    )

    lane = ad_runtime.read_ad_lane("ws_test", store=store)
    assert lane.pregenerated == ()
    assert ad_runtime.context_pregenerated(lane) is None
    assert ad_runtime.context_pregenerated(None) is None


def test_an_unreadable_imagery_table_costs_the_listing_not_the_turn(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Advisory means advisory: this may never be the thing that fails a turn."""
    monkeypatch.setattr(settings, "lumen_brand_ad_assets", True, raising=False)

    class _Broken(_FakeStore):
        def list_pregenerated(self, **_kwargs: Any) -> list[dict]:
            raise RuntimeError("the database is unreachable")

    store = _Broken(
        [{"creative_id": "adcre_a", "asset_id": "asset_a"}],
        card={"card_id": "adna_kit", "version": 1, "card": {"prose": PROSE}},
    )

    lane = ad_runtime.read_ad_lane("ws_test", store=store)
    assert lane is not None, "the references still ride"
    assert lane.pregenerated == ()


def test_the_listing_is_bounded(monkeypatch: pytest.MonkeyPatch) -> None:
    """Pre-generation has no cap of its own, and this rides every ad turn's opening context."""
    monkeypatch.setattr(settings, "lumen_brand_ad_assets", True, raising=False)
    many = [
        {
            "asset_id": f"asset_gen_{index:08d}",
            "visual_system": f"Look {index}",
            "generation": {"aspect_ratio": "1:1"},
        }
        for index in range(ad_runtime.PREGENERATED_CONTEXT_MAX * 3)
    ]
    store = _FakeStore(
        [{"creative_id": "adcre_a", "asset_id": "asset_a"}],
        card={"card_id": "adna_kit", "version": 1, "card": {"prose": PROSE}},
        pregenerated=many,
    )

    lane = ad_runtime.read_ad_lane("ws_test", store=store)
    assert len(lane.pregenerated) == ad_runtime.PREGENERATED_CONTEXT_MAX


def test_an_unharvested_workspace_reads_as_no_lane(monkeypatch: pytest.MonkeyPatch) -> None:
    """None, not an empty lane — every caller's job is "leave the turn alone unless there is
    something real here", and an empty object makes each of them re-derive that."""
    monkeypatch.setattr(settings, "lumen_brand_ad_assets", True, raising=False)
    assert ad_runtime.read_ad_lane("ws_test", store=_FakeStore([])) is None


def test_the_lane_maps_creatives_to_their_asset_rows_and_carries_the_card(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "lumen_brand_ad_assets", True, raising=False)
    store = _FakeStore(
        [
            {"creative_id": "adcre_a", "asset_id": "asset_a"},
            {"creative_id": "adcre_orphan", "asset_id": None},
            {"creative_id": "adcre_b", "asset_id": "asset_b"},
        ],
        card={"card": {"schema_version": 2, "prose": PROSE, "style_groups": []}},
    )
    lane = ad_runtime.read_ad_lane("ws_test", store=store)
    assert lane is not None
    # Newest-first order survives (the DAL orders it), and a creative with no asset row is
    # dropped rather than becoming an unresolvable reference id.
    assert list(lane.creative_assets) == ["adcre_a", "adcre_b"]
    assert lane.card["prose"] == PROSE


def test_an_undistilled_lane_still_serves_its_creatives(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """W2 stops after a failed distillation with the harvest intact and says so. That state
    must still condition a turn — on the creatives, with no description."""
    monkeypatch.setattr(settings, "lumen_brand_ad_assets", True, raising=False)
    lane = ad_runtime.read_ad_lane(
        "ws_test", store=_FakeStore([{"creative_id": "a", "asset_id": "asset_a"}], card=None)
    )
    assert lane is not None
    assert lane.has_creatives
    assert ad_runtime.context_card(lane) is None


# --- selection --------------------------------------------------------------------------------


def test_the_matched_group_decides_which_creatives_ride() -> None:
    lane = _lane(
        [
            {"name": "Deep Field", "creative_ids": ["adcre_a", "adcre_b"]},
            {"name": "Photo Poster", "creative_ids": ["adcre_c"]},
        ],
        {"adcre_a": "asset_a", "adcre_b": "asset_b", "adcre_c": "asset_c"},
    )
    asked: list[tuple[str, list[str]]] = []

    def choose(brief: str, names: list[str]) -> str:
        asked.append((brief, names))
        return "Photo Poster"

    assert ad_runtime.select_reference_asset_ids(
        "a photographic launch ad", lane, choose=choose
    ) == ["asset_c"]
    assert asked == [("a photographic launch ad", ["Deep Field", "Photo Poster"])]


def test_a_single_group_is_not_worth_a_model_call() -> None:
    lane = _lane(
        [{"name": "Deep Field", "creative_ids": ["adcre_b", "adcre_a"]}],
        {"adcre_a": "asset_a", "adcre_b": "asset_b"},
    )

    def choose(brief: str, names: list[str]) -> str:
        raise AssertionError("nothing to choose between; the call must be skipped")

    assert ad_runtime.select_reference_asset_ids("an ad", lane, choose=choose) == [
        "asset_b",
        "asset_a",
    ]


def test_a_failed_or_nonsense_pick_falls_back_to_the_most_recent_creatives() -> None:
    """RED CASE. The fallback is not decoration: the picker is a network call, and a turn
    that loses its references to a flaky tie-break has lost the whole feature. It is also
    what refuses an INVENTED group — the answer is matched against the known names."""
    lane = _lane(
        [
            {"name": "Deep Field", "creative_ids": ["adcre_c"]},
            {"name": "Photo Poster", "creative_ids": ["adcre_b"]},
        ],
        {"adcre_a": "asset_a", "adcre_b": "asset_b", "adcre_c": "asset_c"},
    )

    def exploding(brief: str, names: list[str]) -> str:
        raise RuntimeError("the gateway is on fire")

    recency = ["asset_a", "asset_b", "asset_c"]
    assert ad_runtime.select_reference_asset_ids("an ad", lane, choose=exploding) == recency
    assert (
        ad_runtime.select_reference_asset_ids("an ad", lane, choose=lambda *_a: None) == recency
    )
    assert (
        ad_runtime.select_reference_asset_ids(
            "an ad", lane, choose=lambda *_a: "The Neon One"
        )
        == recency
    )


def test_a_quoted_or_chatty_answer_still_resolves_to_its_group() -> None:
    """The answer is free text out of a language model. It may not INVENT a group; it may
    well arrive quoted or wrapped in a sentence."""
    lane = _lane(
        [{"name": "Deep Field", "creative_ids": ["adcre_a"]}, {"name": "Photo", "ids": []}],
        {"adcre_a": "asset_a", "adcre_z": "asset_z"},
    )
    for answer in ('"Deep Field"', "Deep Field.", "I would use Deep Field"):
        assert ad_runtime.select_reference_asset_ids(
            "an ad", lane, choose=lambda *_a, _answer=answer: _answer
        ) == ["asset_a"], answer


def test_a_group_whose_creatives_no_longer_resolve_falls_back_rather_than_attaching_none() -> None:
    """A re-harvest replaces creative rows; a card version pinned to the old ones is a stale
    pointer, not a reason to send the turn in blind."""
    lane = _lane(
        [
            {"name": "Deep Field", "creative_ids": ["adcre_gone"]},
            {"name": "Photo Poster", "creative_ids": ["adcre_a"]},
        ],
        {"adcre_a": "asset_a"},
    )
    assert ad_runtime.select_reference_asset_ids(
        "an ad", lane, choose=lambda *_a: "Deep Field"
    ) == ["asset_a"]


def test_selection_is_capped_at_four_on_both_branches() -> None:
    many = {f"adcre_{n}": f"asset_{n}" for n in range(9)}
    grouped = _lane([{"name": "One", "creative_ids": list(many)}], many)
    assert len(ad_runtime.select_reference_asset_ids("an ad", grouped)) == 4

    ungrouped = ad_runtime.AdLane(card=None, creative_assets=many)
    assert ad_runtime.select_reference_asset_ids("an ad", ungrouped) == [
        "asset_0",
        "asset_1",
        "asset_2",
        "asset_3",
    ]


def test_an_undistilled_lane_selects_by_recency_without_a_model_call() -> None:
    lane = ad_runtime.AdLane(card=None, creative_assets={"adcre_a": "asset_a"})

    def choose(brief: str, names: list[str]) -> str:
        raise AssertionError("there is no card to name a group from")

    assert ad_runtime.select_reference_asset_ids("an ad", lane, choose=choose) == ["asset_a"]


# --- composition into the turn ----------------------------------------------------------------


def _stub_scene_turn_runtime(monkeypatch: pytest.MonkeyPatch) -> dict:
    """Capture the config a scene turn hands the runtime, without running one."""
    import lumen_agent.harness as harness_mod
    import lumen_agent.llm as llm_mod

    captured: dict = {}

    class _Stop(Exception):
        pass

    def fake_run(prompt, config, **kwargs):
        captured["prompt"] = prompt
        captured["config"] = config
        raise _Stop()

    monkeypatch.setattr(harness_mod, "run_deepagent_turn", fake_run)
    monkeypatch.setattr(llm_mod, "assert_model_supports_image_input", lambda *a, **k: None)
    return captured


def _harvested(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, *, groups: list[dict] | None = None
) -> list[str]:
    """Two REAL uploaded assets, presented to the lane as this brand's harvested creatives.

    The store is what is faked, not `read_ad_lane` — so the flag gate, the manifest build and
    the durable-byte read-through below are all the production ones.
    """
    first = upload_logo(client, label="Published ad one").json()["asset"]["id"]
    second = upload_logo(client, label="Published ad two").json()["asset"]["id"]
    store = _FakeStore(
        [
            {"creative_id": "adcre_one", "asset_id": first},
            {"creative_id": "adcre_two", "asset_id": second},
        ],
        card={"card": {"schema_version": 2, "prose": PROSE, "style_groups": groups or []}},
    )
    import lumen_ingestion.ad_library.store as store_mod

    monkeypatch.setattr(store_mod, "AdAssetsStore", lambda **_kwargs: store)
    return [first, second]


def _turn(prompt: str = "Design a launch ad", **overrides: Any) -> AgentTurnPreviewRequest:
    payload = {"prompt": prompt, "scene": minimal_scene()}
    payload.update(overrides)
    return AgentTurnPreviewRequest(**payload)


def test_a_scene_turn_with_no_attachments_gets_the_brands_own_published_ads(
    client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """W4's whole point: the marketer says "make me an ad" and the run is conditioned on this
    brand's real creative, with nobody hand-feeding anything (spec §5 W5's "no hand-fed")."""
    monkeypatch.setattr(settings, "lumen_asset_store_root", tmp_path / "engine-cache")
    monkeypatch.setattr(settings, "lumen_brand_ad_assets", True, raising=False)
    creatives = _harvested(client, monkeypatch)
    captured = _stub_scene_turn_runtime(monkeypatch)

    run_agent_turn_preview(
        _turn(), repo_root(), workspace_id=os.environ["LUMEN_DEV_WORKSPACE_ID"]
    )

    config = captured["config"]
    assert set(config.reference_assets or {}) == set(creatives)
    # A real by-value manifest, not a list of ids: the runtime never reads the API database.
    for entry in config.reference_assets.values():
        assert entry["preview_digest"]
        assert entry["record"]["id"] in creatives
    # And the description rides alongside.
    assert config.ad_dna_card["prose"] == PROSE


def test_the_humans_own_attachments_are_never_overridden_or_topped_up(
    client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """RED CASE. The platform suggests; the person decides. A turn that already carries
    attachments is left exactly as it was composed — auto-attach must not replace them and
    must not quietly pad them up to the cap with creatives nobody chose."""
    monkeypatch.setattr(settings, "lumen_asset_store_root", tmp_path / "engine-cache")
    monkeypatch.setattr(settings, "lumen_brand_ad_assets", True, raising=False)
    _harvested(client, monkeypatch)
    chosen = upload_logo(client, label="The one I picked").json()["asset"]["id"]
    captured = _stub_scene_turn_runtime(monkeypatch)

    run_agent_turn_preview(
        _turn(reference_asset_ids=[chosen]),
        repo_root(),
        workspace_id=os.environ["LUMEN_DEV_WORKSPACE_ID"],
    )

    assert list(captured["config"].reference_assets) == [chosen]


def test_the_flag_off_turn_is_byte_identical_to_a_pre_w4_one(
    client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """RED CASE. A POPULATED lane and the flag DOWN: nothing attaches, no card rides, and the
    config the runtime receives is the one it received before W4 existed."""
    monkeypatch.setattr(settings, "lumen_asset_store_root", tmp_path / "engine-cache")
    monkeypatch.setattr(settings, "lumen_brand_ad_assets", False, raising=False)
    _harvested(client, monkeypatch)
    captured = _stub_scene_turn_runtime(monkeypatch)

    run_agent_turn_preview(
        _turn(), repo_root(), workspace_id=os.environ["LUMEN_DEV_WORKSPACE_ID"]
    )

    config = captured["config"]
    assert config.reference_assets is None
    assert config.ad_dna_card is None
    assert config.ad_pregenerated_assets is None


def test_the_selected_group_decides_which_published_ads_reach_the_run(
    client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "lumen_asset_store_root", tmp_path / "engine-cache")
    monkeypatch.setattr(settings, "lumen_brand_ad_assets", True, raising=False)
    first, second = _harvested(
        client,
        monkeypatch,
        groups=[
            {"name": "Deep Field", "creative_ids": ["adcre_one"]},
            {"name": "Photo Poster", "creative_ids": ["adcre_two"]},
        ],
    )
    monkeypatch.setattr(ad_runtime, "choose_style_group", lambda *_a: "Photo Poster")
    captured = _stub_scene_turn_runtime(monkeypatch)

    run_agent_turn_preview(
        _turn("a photographic ad"),
        repo_root(),
        workspace_id=os.environ["LUMEN_DEV_WORKSPACE_ID"],
    )

    assert list(captured["config"].reference_assets) == [second]
    assert first not in (captured["config"].reference_assets or {})


def test_the_platform_design_leg_path_auto_attaches_too(
    client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The DEMO path, and the one that used to be silently inert.

    A platform design-leg envelope carries the leg's frozen context and NO ``reference_assets``
    key at all — the platform never assembles this worker's runtime manifest (see the leg
    runner in ``clue_api.design_leg_wiring``). The executor reads that missing key through the
    ``_REFERENCES_UNRESOLVED`` sentinel precisely so the turn resolves in-worker instead of
    reading a bare ``.get`` ``None`` as "resolved: no references" — which is exactly what made
    every accepted platform reference inert before that fix.

    W4 hangs off that same in-worker branch, so the chat-driven ad turn gets the brand's own
    published ads with nothing hand-fed. This test drives the REAL executor with a key-less
    leg envelope to prove the whole chain, rather than asserting the sentinel and hoping.
    """
    from clue_design.envelopes import DesignTurnEnvelope
    from clue_design.runs import work_id_for_run
    from lumen_api.fleet_handler import DesignTurnHost
    from lumen_api.main import execute_agent_turn_job

    monkeypatch.setattr(settings, "lumen_asset_store_root", tmp_path / "engine-cache")
    monkeypatch.setattr(settings, "lumen_brand_ad_assets", True, raising=False)
    workspace_id = os.environ["LUMEN_DEV_WORKSPACE_ID"]
    creatives = _harvested(client, monkeypatch)
    captured = _stub_scene_turn_runtime(monkeypatch)

    run_id = f"run_{uuid4().hex}"
    from lumen_api.design_store import HybridRepository
    HybridRepository(workspace_id).create_run(run_id, None)
    envelope = DesignTurnEnvelope(
        kind="agent_turn",
        work_id=work_id_for_run(run_id),
        workspace_id=workspace_id,
        run_id=run_id,
        checkpoint_thread_id=run_id,
        document_id=None,
        config={
            "request": {"prompt": "Make us a launch ad", "scene": minimal_scene()},
            "delegation_bundle": {"brief": "A launch ad for the new plan."},
            "history": [],
            "leg": {"leg_id": "leg-w4"},
            # NOTE the absence: no "reference_assets" key. That absence is the contract.
        },
    )
    assert "reference_assets" not in envelope.config

    execute_agent_turn_job(
        envelope, store=HybridRepository(workspace_id), host=DesignTurnHost(), event_sink=None
    )

    config = captured["config"]
    assert set(config.reference_assets or {}) == set(creatives)
    assert config.ad_dna_card["prose"] == PROSE
    # The leg's brief still rides the prompt — auto-attach did not displace anything.
    assert "A launch ad for the new plan." in captured.get("prompt", "")


def test_a_legs_own_attachments_survive_the_key_less_envelope_and_beat_auto_attach(
    client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """RED CASE for the leg path's real hazard, which auto-attach alone does NOT cover.

    A leg envelope freezes the human's chosen references as ``request.reference_asset_ids`` and
    carries no ``reference_assets`` manifest. Read with a bare ``.get``, the missing key comes
    back ``None``, the executor reports "resolved: no references", the in-worker resolver never
    runs, and the person's own attachments are silently dropped — the exact defect the
    ``_REFERENCES_UNRESOLVED`` sentinel exists to close. With W4 in place the failure gets
    WORSE, not louder: the dropped attachments are replaced by auto-selected ones, so the run
    looks healthy while designing from images nobody picked.
    """
    from clue_design.envelopes import DesignTurnEnvelope
    from clue_design.runs import work_id_for_run
    from lumen_api.fleet_handler import DesignTurnHost
    from lumen_api.main import execute_agent_turn_job

    monkeypatch.setattr(settings, "lumen_asset_store_root", tmp_path / "engine-cache")
    monkeypatch.setattr(settings, "lumen_brand_ad_assets", True, raising=False)
    workspace_id = os.environ["LUMEN_DEV_WORKSPACE_ID"]
    harvested = _harvested(client, monkeypatch)
    chosen = upload_logo(client, label="The one the human picked").json()["asset"]["id"]
    captured = _stub_scene_turn_runtime(monkeypatch)

    run_id = f"run_{uuid4().hex}"
    from lumen_api.design_store import HybridRepository
    HybridRepository(workspace_id).create_run(run_id, None)
    execute_agent_turn_job(
        DesignTurnEnvelope(
            kind="agent_turn",
            work_id=work_id_for_run(run_id),
            workspace_id=workspace_id,
            run_id=run_id,
            checkpoint_thread_id=run_id,
            document_id=None,
            config={
                "request": {
                    "prompt": "Use this one",
                    "scene": minimal_scene(),
                    "reference_asset_ids": [chosen],
                },
                "leg": {"leg_id": "leg-w4-manual"},
            },
        ),
        store=HybridRepository(workspace_id),
        host=DesignTurnHost(),
        event_sink=None,
    )

    assert list(captured["config"].reference_assets) == [chosen]
    for auto in harvested:
        assert auto not in captured["config"].reference_assets


def test_an_unresolvable_auto_attachment_costs_the_references_not_the_turn(
    client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """RED CASE, and the one deliberate asymmetry against the manual path: a bad attachment
    the HUMAN made is a loud 422 (explicit intent), but one the platform suggested must never
    be able to fail the turn."""
    monkeypatch.setattr(settings, "lumen_asset_store_root", tmp_path / "engine-cache")
    monkeypatch.setattr(settings, "lumen_brand_ad_assets", True, raising=False)
    store = _FakeStore(
        [{"creative_id": "adcre_ghost", "asset_id": "asset_never_uploaded"}],
        card={"card": {"schema_version": 2, "prose": PROSE, "style_groups": []}},
    )
    import lumen_ingestion.ad_library.store as store_mod

    monkeypatch.setattr(store_mod, "AdAssetsStore", lambda **_kwargs: store)
    captured = _stub_scene_turn_runtime(monkeypatch)

    run_agent_turn_preview(
        _turn(), repo_root(), workspace_id=os.environ["LUMEN_DEV_WORKSPACE_ID"]
    )

    assert captured["config"].reference_assets is None
    # The description is independent of the references and still rides.
    assert captured["config"].ad_dna_card["prose"] == PROSE
