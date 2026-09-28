"""Concurrent author tools must leave a scene that its ordered ledger can replay."""

from __future__ import annotations

import base64
import json
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path

import pytest
from agent_fixtures import runtime_config
from lumen_agent.tools import substrate
from lumen_api import core as core_module


SUBSYSTEM_ROOT = Path(__file__).resolve().parents[3]
HELPER = SUBSYSTEM_ROOT / "target" / "release" / "lumen-api-helper"
pytestmark = pytest.mark.skipif(not HELPER.exists(), reason="release helper not built")
HERO_DSL = """reconcile(hero_photo)
  hero_img image asset(asset_fixture) p(0,0) s(fill,fill)
"""


def test_brand_asset_registration_cannot_erase_concurrent_reconcile_or_break_replay(
    tmp_path, monkeypatch
):
    """Google's actual interleaving: old logo upsert returns after hero compile.

    Only helper timing is controlled; ingestion, DSL reconcile, placement, and
    durable-ledger replay all use the real engine. With atomic mutations the
    contender waits for the upsert; without them it finishes before the stale
    upsert response, dropping hero_img and making the next reconcile insert it
    twice in the ledger.
    """
    monkeypatch.setattr(core_module.settings, "lumen_core_helper", str(HELPER))
    core = core_module.CoreClient(repo_root=SUBSYSTEM_ROOT)
    record = core.ingest_asset(
        store_root=str(tmp_path / "assets"),
        bytes_base64=base64.b64encode(
            b'<svg xmlns="http://www.w3.org/2000/svg" width="64" height="64">'
            b'<rect width="64" height="64" fill="#000000"/></svg>'
        ).decode(),
        asset_id="asset_fixture",
        label="Fixture logo",
        declared_mime_type="image/svg+xml",
        filename="fixture.svg",
    )["asset"]["record"]
    initial = core.new_scene("doc_concurrent", "Scene mutation replay")
    initial["assets"]["asset_fixture"] = record
    seeded = core.compile_dsl_into_scene(initial, """page square size(1080,1080,px)
  hero_photo fr p(0,0) s(800,600)
  logo image asset(asset_fixture) p(900,900) s(64,64)
""")
    assert seeded["dsl"].get("operation_error") is None
    initial = seeded["scene"]
    first_helper_waiting = threading.Event()
    contender_reached = threading.Event()
    contender_finished = threading.Event()
    release_first_helper = threading.Event()

    class PausedCore:
        def __getattr__(self, name):
            return getattr(core, name)

        def apply_operations(self, scene, operations, **kwargs):
            response = core.apply_operations(scene, operations, **kwargs)
            if operations[0]["kind"] == "upsert_asset":
                first_helper_waiting.set()
                assert release_first_helper.wait(timeout=5)
            return response

    class ObservedRLock:
        """Observe a contender without requiring unsafe overlap to complete."""

        def __init__(self):
            self.lock = threading.RLock()
            self.local = threading.local()
            self.first_owner = None
            self.first_released = False

        def __enter__(self):
            if first_helper_waiting.is_set():
                contender_reached.set()
            self.lock.acquire()
            if self.first_owner is None:
                self.first_owner = threading.get_ident()
            self.local.depth = getattr(self.local, "depth", 0) + 1

        def __exit__(self, *_):
            self.local.depth -= 1
            self.lock.release()
            if (not self.local.depth and not self.first_released
                    and self.first_owner == threading.get_ident()):
                self.first_released = True
                # Force B to finish before A runs anything outside its lock.
                # A lock around only the helper, excluding response/ledger
                # replacement, still loses the hero under this schedule.
                assert contender_finished.wait(timeout=5)

    monkeypatch.setattr(substrate, "CoreClient", lambda **_: PausedCore())
    config = replace(
        runtime_config(tmp_path), brand_kit_assets={"asset_fixture": {"record": record}}
    )
    tools = substrate.LumenDesignTools(config, "Add hero image and logo", initial_scene=initial)
    tools._scene_mutation_lock = ObservedRLock()

    def reconcile():
        try:
            return json.loads(tools.compile_dsl_block(HERO_DSL))
        finally:
            # The old implementation has no scene lock: let it finish its
            # compile before releasing the stale upsert, matching the live run.
            contender_reached.set()
            contender_finished.set()

    with ThreadPoolExecutor(max_workers=2) as pool:
        logo = pool.submit(tools.use_brand_asset, "asset_fixture", node_id="logo")
        try:
            assert first_helper_waiting.wait(timeout=5)
            hero = pool.submit(reconcile)
            assert contender_reached.wait(timeout=5)
        finally:
            release_first_helper.set()
        assert json.loads(logo.result(timeout=5))["placement"]["status"] == "ok"
        assert hero.result(timeout=5)["compile"]["status"] == "ok"

    # An ordinary author repair repeats the intended subtree. It must update
    # the existing hero, never add a second insert to a diverged ledger.
    assert json.loads(tools.compile_dsl_block(HERO_DSL))["compile"]["status"] == "ok"
    operations = [entry["operation"] for entry in tools.operations_ledger]
    replayed = core.apply_operations(initial, operations)["scene"]
    assert "hero_img" in tools.scene["nodes"]
    assert replayed == tools.scene
    assert tools.scene["nodes"]["logo"]["kind"]["asset_id"] == "asset_fixture"
    assert sum(op["kind"] == "insert_node" and op["node"]["id"] == "hero_img"
               for op in operations) == 1


def test_separate_runtimes_can_compile_concurrently(tmp_path, monkeypatch):
    """Scene transactions belong to one run, never a global worker lock."""
    monkeypatch.setattr(core_module.settings, "lumen_core_helper", str(HELPER))
    core = core_module.CoreClient(repo_root=SUBSYSTEM_ROOT)
    entered = threading.Barrier(2)

    class ConcurrentCore:
        def __getattr__(self, name):
            return getattr(core, name)

        def compile_dsl_into_scene(self, *args, **kwargs):
            entered.wait(timeout=5)
            return core.compile_dsl_into_scene(*args, **kwargs)

    monkeypatch.setattr(substrate, "CoreClient", lambda **_: ConcurrentCore())
    tools = [substrate.LumenDesignTools(runtime_config(tmp_path / str(i)), "New design")
             for i in range(2)]
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(tool.compile_dsl_block, """page square size(1080,1080,px)
  headline text "Independent run" s(800,100) font_size(48)
""") for tool in tools]
        assert all(json.loads(future.result(timeout=5))["compile"]["status"] == "ok"
                   for future in futures)
    assert all("headline" in tool.scene["nodes"] for tool in tools)
