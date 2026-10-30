"""W4 — the Brand Ad Assets lane at TURN time (spec §5 W4).

Two halves, matching the two things a scene turn takes out of the lane:

* **No selection** (founder ruling 2026-10-30, reference ads spec §5.4): the platform no longer
  picks ads for a turn. The agent gets the whole list and opens what it wants; only the person's
  own attachments ride as references.
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
        {"asset_id": "asset_gen_aaaa1111", "shape": "wide background"},
        {"asset_id": "asset_gen_bbbb2222", "shape": "square background"},
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


def test_a_scene_turn_with_no_attachments_carries_no_references(
    client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Founder ruling 2026-10-30: nothing is auto-attached. The agent sees every ad in its list
    and opens the ones it wants; the brand's ad description still rides."""
    monkeypatch.setattr(settings, "lumen_asset_store_root", tmp_path / "engine-cache")
    monkeypatch.setattr(settings, "lumen_brand_ad_assets", True, raising=False)
    _harvested(client, monkeypatch)
    captured = _stub_scene_turn_runtime(monkeypatch)

    run_agent_turn_preview(
        _turn(), repo_root(), workspace_id=os.environ["LUMEN_DEV_WORKSPACE_ID"]
    )

    config = captured["config"]
    assert not config.reference_assets
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


def test_the_platform_design_leg_path_carries_the_card_and_no_auto_references(
    client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The DEMO path, and the one that used to be silently inert.

    A platform design-leg envelope carries the leg's frozen context and NO ``reference_assets``
    key at all — the platform never assembles this worker's runtime manifest (see the leg
    runner in ``clue_api.design_leg_wiring``). The executor reads that missing key through the
    ``_REFERENCES_UNRESOLVED`` sentinel precisely so the turn resolves in-worker instead of
    reading a bare ``.get`` ``None`` as "resolved: no references" — which is exactly what made
    every accepted platform reference inert before that fix.

    The chat-driven ad turn gets the brand's ad description through that same in-worker branch,
    and — since 2026-10-30 — no auto-attached references. This test drives the REAL executor with
    a key-less leg envelope to prove the whole chain, rather than asserting the sentinel and hoping.
    """
    from clue_design.envelopes import DesignTurnEnvelope
    from clue_design.runs import work_id_for_run
    from lumen_api.fleet_handler import DesignTurnHost
    from lumen_api.main import execute_agent_turn_job

    monkeypatch.setattr(settings, "lumen_asset_store_root", tmp_path / "engine-cache")
    monkeypatch.setattr(settings, "lumen_brand_ad_assets", True, raising=False)
    workspace_id = os.environ["LUMEN_DEV_WORKSPACE_ID"]
    _harvested(client, monkeypatch)
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
    assert not config.reference_assets
    assert config.ad_dna_card["prose"] == PROSE
    # The leg's brief still rides the prompt.
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


# --- the brand's ad list (spec 2026-10-30, reference ads §5.5) -------------------------------


def _entry(asset_id: str, creative_type: Optional[str], *, created_at: str = "2026-09-01",
           title: str = "", width: int = 0, height: int = 0) -> dict:
    record: dict = {"id": asset_id, "kind": "raster_image", "status": "ready"}
    if width:
        record["raster"] = {"pixel_width": width, "pixel_height": height}
    entry: dict = {"record": record, "created_at": created_at, "title": title,
                   "description": f"About {asset_id}."}
    if creative_type is not None:
        entry["creative_type"] = creative_type
    return entry


def _ads_lane() -> ad_runtime.AdLane:
    return ad_runtime.AdLane(
        card=None,
        creative_assets={"c1": "a1", "c2": "a2"},
        creatives=(
            {"creative_id": "c1", "asset_id": "a1", "headline": "H1", "commentary": "Copy 1",
             "created_at": "2026-10-02"},
            {"creative_id": "c2", "asset_id": "a2", "headline": None, "commentary": None,
             "created_at": "2026-10-01"},
        ),
    )


def test_the_list_holds_harvested_ads_and_person_marked_ones_newest_first() -> None:
    library = {
        "a1": _entry("a1", "ad", title="T1", width=1200, height=628),
        "a2": _entry("a2", "ad"),
        "a3": _entry("a3", "ad", created_at="2026-10-03"),
        "a4": _entry("a4", "photo"),
    }
    ads = ad_runtime.context_brand_ads(_ads_lane(), library)
    assert [ad["asset_id"] for ad in ads] == ["a3", "a1", "a2"]
    assert ads[0]["from"] == "marked_by_person" and ads[1]["from"] == "linkedin_ad"
    assert ads[1]["headline"] == "H1" and ads[1]["commentary"] == "Copy 1"
    assert ads[1]["title"] == "T1" and ads[1]["description"] == "About a1."
    assert (ads[1]["width"], ads[1]["height"]) == (1200, 628)
    assert (ads[2]["width"], ads[2]["height"]) == (None, None)


def test_a_harvested_ad_the_person_retyped_leaves_the_list() -> None:
    library = {"a1": _entry("a1", "photo"), "a2": _entry("a2", "ad")}
    assert [ad["asset_id"] for ad in ad_runtime.context_brand_ads(_ads_lane(), library)] == ["a2"]


def test_a_harvested_ad_with_no_description_is_still_listed() -> None:
    library = {"a1": _entry("a1", None), "a2": _entry("a2", "ad")}
    assert [ad["asset_id"] for ad in ad_runtime.context_brand_ads(_ads_lane(), library)] == ["a1", "a2"]


def test_a_harvested_ad_missing_from_the_library_is_left_out() -> None:
    assert [ad["asset_id"] for ad in ad_runtime.context_brand_ads(_ads_lane(), {"a2": _entry("a2", "ad")})] == ["a2"]


def test_person_marked_ads_are_listed_with_no_lane() -> None:
    assert [ad["asset_id"] for ad in ad_runtime.context_brand_ads(None, {"a3": _entry("a3", "ad")})] == ["a3"]


def test_no_ads_is_none() -> None:
    assert ad_runtime.context_brand_ads(None, {"a4": _entry("a4", "photo")}) is None
    assert ad_runtime.context_brand_ads(_ads_lane(), None) is None


def test_a_turn_carries_the_list_even_with_the_lane_off(
    client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The flag gates the harvest lane, not the person's own "Ad" choice (spec §5.5)."""
    monkeypatch.setattr(settings, "lumen_asset_store_root", tmp_path / "engine-cache")
    monkeypatch.setattr(settings, "lumen_brand_ad_assets", False, raising=False)
    marked = upload_logo(client, label="Our print ad").json()["asset"]["id"]
    captured = _stub_scene_turn_runtime(monkeypatch)
    from lumen_api import main as main_module

    real = main_module.resolve_scene_turn_asset_library

    def library_with_marked_ad(*args: Any, **kwargs: Any):
        library = real(*args, **kwargs) or {}
        library[marked] = {**library.get(marked, {}), "creative_type": "ad"}
        return library

    monkeypatch.setattr(main_module, "resolve_scene_turn_asset_library", library_with_marked_ad)

    run_agent_turn_preview(
        _turn(), repo_root(), workspace_id=os.environ["LUMEN_DEV_WORKSPACE_ID"]
    )

    assert [ad["asset_id"] for ad in captured["config"].brand_ads] == [marked]


def test_a_list_that_cannot_be_built_costs_the_list_not_the_turn(
    client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Spec anti-goal: a turn never fails because the ad list can't be read."""
    monkeypatch.setattr(settings, "lumen_asset_store_root", tmp_path / "engine-cache")
    monkeypatch.setattr(settings, "lumen_brand_ad_assets", True, raising=False)
    _harvested(client, monkeypatch)
    captured = _stub_scene_turn_runtime(monkeypatch)

    def broken(*_args: Any) -> None:
        raise ValueError("a malformed library entry")

    monkeypatch.setattr(ad_runtime, "context_brand_ads", broken)

    run_agent_turn_preview(
        _turn(), repo_root(), workspace_id=os.environ["LUMEN_DEV_WORKSPACE_ID"]
    )

    assert "config" in captured, "the turn reached the runtime"
    assert captured["config"].brand_ads is None
    assert captured["config"].ad_dna_card["prose"] == PROSE
