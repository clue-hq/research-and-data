"""A director verification must persist the round without re-exporting current pixels."""

import io
import json
from pathlib import Path

import pytest
from agent_fixtures import FakeCoreClient, runtime_config
from lumen_agent.tools.render import _render_preview_text
from lumen_agent.tools.substrate import LumenDesignTools
from PIL import Image


class _RenderCore(FakeCoreClient):
    def __init__(self, repo_root):
        super().__init__(repo_root)
        self.exports = []

    def export_preview(self, scene, export_format="svg", **kwargs):
        self.exports.append(export_format)
        response = super().export_preview(scene, export_format, **kwargs)
        if export_format == "png":
            output = io.BytesIO()
            Image.new("RGB", (32, 32), "white").save(output, format="PNG")
            response["export"]["artifacts"][0]["bytes"] = list(output.getvalue())
        return response


def _authored_preview(tmp_path, monkeypatch):
    monkeypatch.setattr("lumen_agent.tools.substrate.CoreClient", _RenderCore)
    persisted = tmp_path / "persisted-round.json"

    def checkpoint(operations, metadata):
        # Exercise the real runtime checkpoint hook, including its ledger/version guard.
        prior = json.loads(persisted.read_text()) if persisted.exists() else []
        persisted.write_text(json.dumps(prior + [{"operations": operations, "meta": metadata}]))

    tools = LumenDesignTools(runtime_config(tmp_path), "Square ad", scene_checkpoint=checkpoint)
    tools.compile_dsl_block("page page_test size(1080,1080,px)")
    tools.preflight_design()
    round_dir = tools.trace_dir / "workspace" / "rounds" / "round_1"
    round_dir.mkdir(parents=True)
    result = _render_preview_text(tools, checkpoint=False)
    assert "status=ok" in result
    assert not persisted.exists()
    return tools, persisted, round_dir


def test_director_reuses_author_pixels_and_checkpoints_once(tmp_path, monkeypatch):
    tools, persisted, round_one = _authored_preview(tmp_path, monkeypatch)
    original = (round_one / "preview.png").read_bytes()
    receipt = tools._preview_receipt
    critique = {"accepted": True, "summary": "Viewed current authored pixels.", "issues": []}
    assert json.loads(tools.submit_visual_critique(json.dumps(critique)))["status"] == "ok"
    # A no-op preflight and a new round directory do not change the scene or pixels.
    tools.preflight_design()
    round_two = round_one.parent / "round_2"
    round_two.mkdir()

    result = _render_preview_text(tools)
    _render_preview_text(tools)

    assert tools.core.exports == ["svg", "png"]
    assert (round_two / "preview.png").read_bytes() == original
    assert tools._preview_receipt == receipt
    assert tools._acceptance_error(critique) is None
    commits = json.loads(persisted.read_text())
    assert len(commits) == 1
    assert [op["kind"] for op in commits[0]["operations"]] == ["add_page", "insert_node"]
    assert commits[0]["meta"]["reason"] == "render_preview"
    assert commits[0]["meta"]["preflight_clean"] is True
    assert "reused" in result


@pytest.mark.parametrize("change", [
    "scene", "changed_png", "missing_png", "debug", "missing_bundle",
    "changed_manifest", "malformed_bundle", "invalid_artifact", "missing_preflight",
    "dirty_preflight", "single_format_export",
])
def test_reuse_never_hides_changed_or_unvalidated_evidence(tmp_path, monkeypatch, change):
    tools, _, _ = _authored_preview(tmp_path, monkeypatch)
    bundle_path = tools.trace_dir / "iterations" / "001" / "preview_bundle.json"
    bundle = json.loads(bundle_path.read_text())
    png = Path(next(a["path"] for a in bundle["reviewer"]["artifacts"] if a["format"] == "png"))
    if change == "scene":
        tools.scene["nodes"]["headline"]["kind"]["content"] = "Changed"
        tools.preflight_design()
    elif change == "changed_png":
        png.write_bytes(png.read_bytes() + b"changed")
    elif change == "missing_png":
        png.unlink()
    elif change == "debug":
        tools.export_preview_bundle(critic_format="png", debug_only=True)
    elif change == "missing_bundle":
        bundle_path.unlink()
    elif change == "changed_manifest":
        bundle["canonical"]["artifacts"] = []
        bundle_path.write_text(json.dumps(bundle))
    elif change == "malformed_bundle":
        bundle_path.write_text("[]")
    elif change == "invalid_artifact":
        tools.latest_export_summary["artifacts"][0]["valid"] = False
    elif change == "missing_preflight":
        tools._preflight_scene_stamp = None
    elif change == "dirty_preflight":
        tools.latest_preflight_has_errors = True
    elif change == "single_format_export":
        tools.export_preview("svg")
    before = len(tools.core.exports)

    result = _render_preview_text(tools)

    assert tools.core.exports[before:] == ["svg", "png"]
    assert "reused" not in result
