"""A preview must keep the identity of the scene actually sent to the renderer."""

from __future__ import annotations

import copy
import hashlib
import json
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from agent_fixtures import prepare_acceptance_evidence, runtime_config
from lumen_agent.tools import substrate
from lumen_api import core as core_module


ROOT = Path(__file__).resolve().parents[3]
HELPER = ROOT / "target" / "release" / "lumen-api-helper"
pytestmark = pytest.mark.skipif(not HELPER.exists(), reason="release helper not built")


class ContentionObservedLock:
    def __init__(self, contender_reached):
        self.lock = threading.RLock()
        self.contender_reached = contender_reached

    def __enter__(self):
        if not self.lock.acquire(blocking=False):
            self.contender_reached.set()
            self.lock.acquire()

    def __exit__(self, *_):
        self.lock.release()


def _panel_tools(tmp_path, monkeypatch, *, checkpoint=None):
    monkeypatch.setattr(core_module.settings, "lumen_core_helper", str(HELPER))
    core = core_module.CoreClient(repo_root=ROOT)
    monkeypatch.setattr(substrate, "CoreClient", lambda **_: core)
    tools = substrate.LumenDesignTools(
        runtime_config(tmp_path), "Color panel", scene_checkpoint=checkpoint
    )
    assert json.loads(tools.compile_dsl_block("""page square size(1080,1080,px)
  hero fr p(100,100) s(800,800) fill(#ff0000)
"""))["compile"]["status"] == "ok"
    return tools


def test_mutation_during_export_cannot_stamp_old_preview_as_current(tmp_path, monkeypatch):
    """Delay a real red-rectangle SVG while a blue-rectangle edit completes."""
    monkeypatch.setattr(core_module.settings, "lumen_core_helper", str(HELPER))
    core = core_module.CoreClient(repo_root=ROOT)
    rendered = threading.Event()
    contender_reached = threading.Event()
    release_render = threading.Event()
    rendered_scenes = []

    class PausedExportCore:
        def __getattr__(self, name):
            return getattr(core, name)

        def export_preview(self, scene, *args, **kwargs):
            rendered_scenes.append(copy.deepcopy(scene))
            response = core.export_preview(scene, *args, **kwargs)
            rendered.set()
            assert release_render.wait(timeout=5)
            return response

    class ObservedRLock:
        def __init__(self):
            self.lock = threading.RLock()

        def __enter__(self):
            if not self.lock.acquire(blocking=False):
                # A guarded export may defer the edit until its receipt exists.
                # Without that guard, wait for the actual edit to finish below.
                contender_reached.set()
                self.lock.acquire()

        def __exit__(self, *_):
            self.lock.release()

    monkeypatch.setattr(substrate, "CoreClient", lambda **_: PausedExportCore())
    tools = substrate.LumenDesignTools(runtime_config(tmp_path), "Color panel")
    assert json.loads(tools.compile_dsl_block("""page square size(1080,1080,px)
  hero fr p(100,100) s(800,800) fill(#ff0000)
"""))["compile"]["status"] == "ok"
    assert json.loads(tools.preflight_design())["preflight"]["has_errors"] is False
    tools._scene_mutation_lock = ObservedRLock()

    def mutate():
        try:
            assert json.loads(tools.compile_dsl_block("#hero fill(#0000ff)"))["compile"]["status"] == "ok"
            assert json.loads(tools.preflight_design())["preflight"]["has_errors"] is False
        finally:
            contender_reached.set()

    with ThreadPoolExecutor(max_workers=2) as pool:
        preview = pool.submit(tools.export_preview, "svg")
        try:
            assert rendered.wait(timeout=5)
            mutation = pool.submit(mutate)
            assert contender_reached.wait(timeout=5)
        finally:
            release_render.set()
        assert json.loads(preview.result(timeout=5))["export"]["status"] == "ok"
        mutation.result(timeout=5)

    assert rendered_scenes[0]["nodes"]["hero"] != tools.scene["nodes"]["hero"]
    # The bytes are from the old scene. They must either be invalidated or keep
    # the old scene identity, making them stale after the completed blue edit.
    assert tools._preview_receipt is None or tools._current_preview_receipt() != tools._preview_receipt


def test_finalize_writes_the_scene_that_passed_its_acceptance_check(tmp_path, monkeypatch):
    tools = _panel_tools(tmp_path, monkeypatch)
    prepare_acceptance_evidence(tools)
    accepted_scene = copy.deepcopy(tools.scene)
    checked = threading.Event()
    contender_reached = threading.Event()
    release_check = threading.Event()
    real_acceptance_check = tools._acceptance_error

    def paused_acceptance_check(critique):
        result = real_acceptance_check(critique)
        assert result is None
        checked.set()
        assert release_check.wait(timeout=5)
        return result

    monkeypatch.setattr(tools, "_acceptance_error", paused_acceptance_check)
    tools._scene_mutation_lock = ContentionObservedLock(contender_reached)

    def mutate():
        try:
            assert json.loads(tools.compile_dsl_block("#hero fill(#0000ff)"))["compile"]["status"] == "ok"
        finally:
            contender_reached.set()

    with ThreadPoolExecutor(max_workers=2) as pool:
        final = pool.submit(tools.finalize_run, "accepted", "accepted", "Fixture accepted")
        try:
            assert checked.wait(timeout=5)
            mutation = pool.submit(mutate)
            assert contender_reached.wait(timeout=5)
        finally:
            release_check.set()
        payload = json.loads(final.result(timeout=5))
        mutation.result(timeout=5)

    assert payload["status"] == "accepted"
    written = json.loads((tools.trace_dir / "final_scene.json").read_text())
    assert written == accepted_scene
    written_stamp = hashlib.sha256(
        json.dumps(written, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    assert payload["acceptance_receipt"]["scene"] == written_stamp


def test_preview_bundle_renders_svg_and_png_from_one_scene(tmp_path, monkeypatch):
    tools = _panel_tools(tmp_path, monkeypatch)
    assert json.loads(tools.preflight_design())["preflight"]["has_errors"] is False
    rendered_scenes = []
    real_core_export = tools.core.export_preview

    def capture_scene(scene, *args, **kwargs):
        rendered_scenes.append(copy.deepcopy(scene))
        return real_core_export(scene, *args, **kwargs)

    monkeypatch.setattr(tools.core, "export_preview", capture_scene)
    real_export = tools.export_preview
    svg_done = threading.Event()
    contender_reached = threading.Event()
    release_svg = threading.Event()

    def pause_between_formats(fmt):
        response = real_export(fmt)
        if fmt == "svg":
            svg_done.set()
            assert release_svg.wait(timeout=5)
        return response

    monkeypatch.setattr(tools, "export_preview", pause_between_formats)
    tools._scene_mutation_lock = ContentionObservedLock(contender_reached)

    def mutate():
        try:
            assert json.loads(tools.compile_dsl_block("#hero fill(#0000ff)"))["compile"]["status"] == "ok"
            assert json.loads(tools.preflight_design())["preflight"]["has_errors"] is False
        finally:
            contender_reached.set()

    with ThreadPoolExecutor(max_workers=2) as pool:
        bundle = pool.submit(tools.export_preview_bundle, "png")
        try:
            assert svg_done.wait(timeout=5)
            mutation = pool.submit(mutate)
            assert contender_reached.wait(timeout=5)
        finally:
            release_svg.set()
        result = json.loads(bundle.result(timeout=10))
        mutation.result(timeout=5)

    assert result["reviewer"]["status"] == "ok"
    assert len(rendered_scenes) == 2
    assert rendered_scenes[0] == rendered_scenes[1]


def test_concurrent_checkpoints_do_not_rewind_the_committed_ledger_cursor(tmp_path, monkeypatch):
    first_checkpoint = threading.Event()
    contender_reached = threading.Event()
    release_checkpoint = threading.Event()
    received = []

    def checkpoint(operations, meta):
        received.append(copy.deepcopy(operations))
        if len(received) == 1:
            first_checkpoint.set()
            assert release_checkpoint.wait(timeout=5)

    tools = _panel_tools(tmp_path, monkeypatch, checkpoint=checkpoint)
    tools._scene_mutation_lock = ContentionObservedLock(contender_reached)

    def mutate_and_checkpoint():
        try:
            assert json.loads(tools.compile_dsl_block("#hero fill(#0000ff)"))["compile"]["status"] == "ok"
            tools.checkpoint_scene("later edit")
        finally:
            contender_reached.set()

    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(tools.checkpoint_scene, "first preview")
        try:
            assert first_checkpoint.wait(timeout=5)
            second = pool.submit(mutate_and_checkpoint)
            assert contender_reached.wait(timeout=5)
        finally:
            release_checkpoint.set()
        first.result(timeout=5)
        second.result(timeout=5)

    assert len(received) == 2
    assert len(received[1]) > len(received[0])
    tools.checkpoint_scene("unchanged scene")
    # No document version or duplicate persistence request for an unchanged
    # ledger: an older callback must not move its cursor behind the later one.
    assert len(received) == 2
