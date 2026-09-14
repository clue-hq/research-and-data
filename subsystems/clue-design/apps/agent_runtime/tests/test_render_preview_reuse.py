"""A director verification must persist the round without re-exporting current pixels."""

import io
import json
from dataclasses import replace
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


def _authored_preview(tmp_path, monkeypatch, *, bundle="legacy"):
    monkeypatch.setattr("lumen_agent.tools.substrate.CoreClient", _RenderCore)
    persisted = tmp_path / "persisted-round.json"

    def checkpoint(operations, metadata):
        # Exercise the real runtime checkpoint hook, including its ledger/version guard.
        prior = json.loads(persisted.read_text()) if persisted.exists() else []
        persisted.write_text(json.dumps(prior + [{"operations": operations, "meta": metadata}]))

    config = replace(runtime_config(tmp_path), scene_skill_bundle=bundle)
    tools = LumenDesignTools(config, "Square ad", scene_checkpoint=checkpoint)
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


def _register_candidate_review(tools, *, accepted=True):
    from test_scene_direction_review import review
    from test_scene_skill_family import direction

    path = tools.trace_dir / "workspace" / "creative-direction.json"
    planned = direction()
    planned["copy"][0]["text"] = "Plan"  # The actual FakeCore fixture's native text.
    path.write_text(json.dumps(planned))
    validated = json.loads(tools.validate_creative_direction())
    assert validated["status"] == "ok"
    critique = review(validated, page_id="page_test", node_id="headline", text="Plan")
    critique["accepted"] = accepted
    assert json.loads(tools.submit_visual_critique(json.dumps(critique)))["status"] == "ok"
    return tools._latest_visual_critique


def _freshness(summary):
    line = next((line for line in summary.splitlines() if line.startswith("freshness: ")), None)
    assert line is not None, "render summary hides authoritative review/preflight freshness"
    return json.loads(line.removeprefix("freshness: "))


def test_candidate_reuse_exposes_current_accepted_review_without_renewing_it(tmp_path, monkeypatch):
    tools, _, _ = _authored_preview(tmp_path, monkeypatch, bundle="candidate")
    critique = _register_candidate_review(tools)
    original_receipt = json.dumps(tools._review_receipt, sort_keys=True)

    result = _render_preview_text(tools)

    assert _freshness(result) == {
        "preflight_current": True, "preview_current": True,
        "registered_review_current": True, "review_error": None,
    }
    assert "reused" in result
    assert tools.core.exports == ["svg", "png"]
    assert json.dumps(tools._review_receipt, sort_keys=True) == original_receipt
    assert tools._acceptance_error(critique) is None


@pytest.mark.parametrize("change", ["scene", "pixels", "direction"])
def test_candidate_summary_exposes_stale_review_and_keeps_final_guard(tmp_path, monkeypatch, change):
    tools, _, _ = _authored_preview(tmp_path, monkeypatch, bundle="candidate")
    critique = _register_candidate_review(tools)
    original_receipt = json.dumps(tools._review_receipt, sort_keys=True)
    if change == "scene":
        tools.scene["nodes"]["headline"]["kind"]["line_height"] = 1.0
        tools.preflight_design()
    elif change == "pixels":
        # Same scene, genuinely different valid PNG from the export boundary.
        prior_export = tools.core.export_preview

        def changed_export(scene, export_format="svg", **kwargs):
            response = prior_export(scene, export_format, **kwargs)
            if export_format == "png":
                output = io.BytesIO()
                Image.new("RGB", (32, 32), "navy").save(output, format="PNG")
                response["export"]["artifacts"][0]["bytes"] = list(output.getvalue())
            return response

        monkeypatch.setattr(tools.core, "export_preview", changed_export)
        tools.export_preview_bundle(critic_format="png")
    else:
        path = tools.trace_dir / "workspace" / "creative-direction.json"
        direction = json.loads(path.read_text())
        direction["preserve"].append("Keep the newly requested hierarchy")
        path.write_text(json.dumps(direction))
        assert json.loads(tools.validate_creative_direction(revision_reason="Updated direction"))["status"] == "ok"

    result = _render_preview_text(tools)
    status = _freshness(result)

    assert status["preflight_current"] is True
    assert status["preview_current"] is True
    assert status["registered_review_current"] is False
    assert status["review_error"] == tools._acceptance_error(critique)
    assert status["review_error"]
    assert str(tools.trace_dir) not in result
    assert json.dumps(tools._review_receipt, sort_keys=True) == original_receipt
    final = tools.finalize_run("completed", "accepted", "Reviewed")
    assert final.startswith("REFUSED:")
    assert status["review_error"] in final


@pytest.mark.parametrize("state", [
    "missing_review", "rejected_review", "stale_preflight",
    "blocked_preflight", "blocking_diagnostic",
])
def test_candidate_summary_distinguishes_missing_or_unacceptable_review(tmp_path, monkeypatch, state):
    tools, _, _ = _authored_preview(tmp_path, monkeypatch, bundle="candidate")
    if state != "missing_review":
        _register_candidate_review(tools, accepted=state != "rejected_review")
    if state == "stale_preflight":
        tools._preflight_scene_stamp = None
    elif state == "blocked_preflight":
        tools.latest_preflight_has_errors = True
        tools._latest_preflight_diagnostics = [{"severity": "error", "code": "TEST", "message": "Blocked"}]
    elif state == "blocking_diagnostic":
        tools._latest_preflight_diagnostics = [{"severity": "error", "code": "TEST", "message": "Blocked"}]

    status = _freshness(_render_preview_text(tools))

    assert status["preflight_current"] is (state not in {"stale_preflight", "blocked_preflight", "blocking_diagnostic"})
    assert status["preview_current"] is True
    assert status["registered_review_current"] is False
    assert status["review_error"]


def test_legacy_render_summary_does_not_add_candidate_freshness(tmp_path, monkeypatch):
    tools, _, _ = _authored_preview(tmp_path, monkeypatch)
    assert "freshness:" not in _render_preview_text(tools)


def test_candidate_summary_does_not_promote_unjudged_reference_fidelity(tmp_path, monkeypatch):
    tools, _, _ = _authored_preview(tmp_path, monkeypatch, bundle="candidate")
    tools._selected_reference_ids = ["asset_source"]
    _register_candidate_review(tools)

    status = _freshness(_render_preview_text(tools))

    assert status["registered_review_current"] is False
    assert "fidelity" in status["review_error"]
    assert tools.finalize_run("completed", "accepted", "Reviewed").startswith("REFUSED:")


def test_candidate_summary_preserves_the_existing_advisory_preflight_exception(tmp_path, monkeypatch):
    tools, _, _ = _authored_preview(tmp_path, monkeypatch, bundle="candidate")
    critique = _register_candidate_review(tools)
    tools.latest_preflight_has_errors = True
    tools._latest_preflight_diagnostics = [{"severity": "error", "code": "LUMV0820", "message": "Image slot policy"}]
    assert tools._acceptance_error(critique) is None

    status = _freshness(_render_preview_text(tools))

    assert status["preflight_current"] is True
    assert status["registered_review_current"] is True
