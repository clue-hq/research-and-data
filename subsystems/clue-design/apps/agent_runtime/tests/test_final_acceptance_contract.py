"""Full acceptance requires a passing review of current, exportable pixels."""

from __future__ import annotations

import json
from io import BytesIO
from pathlib import Path

import pytest
from agent_fixtures import FakeCoreClient, runtime_config
from lumen_agent.tools.substrate import LumenDesignTools
from lumen_api.core import CoreError
from PIL import Image


def _critique(*, accepted=True, severity=None):
    return {
        "accepted": accepted,
        "summary": "Inspected the complete creative against its direction.",
        "issues": []
        if severity is None
        else [
            {
                "severity": severity,
                "category": "brand_fit",
                "message": "The source identity was replaced with an invented mark.",
                "suggested_repair": "Use the authentic authorized identity asset.",
            }
        ],
    }


@pytest.fixture
def tools(tmp_path, monkeypatch):
    monkeypatch.setattr("lumen_agent.tools.substrate.CoreClient", FakeCoreClient)
    return LumenDesignTools(runtime_config(tmp_path), "Create a square awareness ad.")


def _compile(tools):
    if tools.scene.get("pages"):
        # A repair must use the checked op path, not recreate an existing page.
        tools.apply_operations(
            json.dumps([{"kind": "set_node_name", "node_id": "headline", "name": "Revised"}])
        )
    else:
        result = json.loads(tools.compile_dsl_block("page page_test size(1080,1080,px)"))
        assert result["compile"]["status"] == "ok"


def _prepare(tools, critique=None, *, preflight=True, preview=True):
    _compile(tools)
    if preflight:
        assert json.loads(tools.preflight_design())["preflight"]["status"] == "ok"
    if preview:
        assert json.loads(tools.export_preview("svg"))["export"]["status"] == "ok"
    body = critique if critique is not None else _critique()
    assert json.loads(tools.submit_visual_critique(json.dumps(body)))["status"] == "ok"
    return body


def _finalize(tools, critique, status="accepted"):
    return tools.finalize_run(status, "review_complete", "Creative ready.", json.dumps(critique))


@pytest.mark.parametrize(
    "critique",
    [
        _critique(accepted=False),
        _critique(severity="blocker"),
        _critique(severity="error"),
    ],
)
def test_failed_or_blocking_review_cannot_be_overridden_by_accepted_status(tools, critique):
    _prepare(tools, critique)
    result = _finalize(tools, critique)
    assert result.startswith("REFUSED"), result
    assert not (tools.trace_dir / "final.json").exists()


@pytest.mark.parametrize("missing", ["preflight", "preview"])
def test_full_acceptance_requires_preflight_and_preview(tools, missing):
    critique = _prepare(tools, preflight=missing != "preflight", preview=missing != "preview")
    assert _finalize(tools, critique).startswith("REFUSED")
    assert not (tools.trace_dir / "final.json").exists()


def test_review_of_an_earlier_scene_cannot_approve_a_new_render(tools):
    critique = _prepare(tools)
    _compile(tools)
    tools.preflight_design()
    tools.export_preview("svg")
    assert _finalize(tools, critique).startswith("REFUSED")


def test_preflight_of_an_earlier_scene_cannot_approve_newly_reviewed_scene(tools):
    critique = _prepare(tools)
    _compile(tools)
    tools.export_preview("svg")
    tools.submit_visual_critique(json.dumps(critique))
    assert _finalize(tools, critique).startswith("REFUSED")


def test_finalizer_cannot_substitute_a_passing_review_for_the_recorded_rejection(tools):
    _prepare(tools, _critique(accepted=False))
    assert _finalize(tools, _critique()).startswith("REFUSED")


def test_deleted_preview_cannot_be_accepted_from_a_cached_export_summary(tools):
    critique = _prepare(tools)
    for artifact in tools.latest_export_summary["artifacts"]:
        Path(artifact["path"]).unlink()
    assert _finalize(tools, critique).startswith("REFUSED")


def test_changed_preview_bytes_invalidate_the_recorded_review(tools):
    critique = _prepare(tools)
    Path(tools.latest_export_summary["artifacts"][0]["path"]).write_text(
        '<svg xmlns="http://www.w3.org/2000/svg"><text>Changed after review</text></svg>'
    )
    assert _finalize(tools, critique).startswith("REFUSED")


def test_complete_current_evidence_can_be_accepted(tools):
    critique = _prepare(tools)
    result = json.loads(_finalize(tools, critique))
    assert result["status"] == "accepted"
    assert (tools.trace_dir / "final_scene.json").exists()


@pytest.mark.parametrize(
    "submitted",
    [
        "{",
        "[]",
        '{"accepted": true}',
        json.dumps({**_critique(), "summary": "Director rewrote the author's review."}),
    ],
)
def test_payload_only_refusal_reuses_current_review_without_render_or_repair(tools, submitted):
    _prepare(tools)
    receipt = tools._review_receipt
    scene_before = json.dumps(tools.scene, sort_keys=True)
    pixels_before = {
        item["path"]: Path(item["path"]).read_bytes()
        for item in tools.latest_export_summary["artifacts"]
    }

    refusal = tools.finalize_run("accepted", "review_complete", "Ready", submitted)
    assert refusal.startswith("REFUSED")
    assert "Retry finalize_run without critique_json" in refusal
    assert not (tools.trace_dir / "final.json").exists()

    # Retry the documented default; no new author, render, preflight or review.
    final = json.loads(tools.finalize_run("accepted", "review_complete", "Ready"))
    assert final["status"] == "accepted"
    assert final["acceptance_receipt"] == receipt
    assert json.dumps(tools.scene, sort_keys=True) == scene_before
    assert all(Path(path).read_bytes() == data for path, data in pixels_before.items())


@pytest.mark.parametrize("defect", ["stale_scene", "failed_review", "missing_review"])
def test_omitting_critique_never_bypasses_invalid_registered_evidence(tools, defect):
    _prepare(tools, _critique(accepted=defect != "failed_review"))
    if defect == "stale_scene":
        _compile(tools)
    elif defect == "missing_review":
        tools.submit_visual_critique('{"accepted": true}')

    refusal = tools.finalize_run("accepted", "review_complete", "Ready")
    assert refusal.startswith("REFUSED")
    assert "Retry finalize_run without critique_json" not in refusal
    assert not (tools.trace_dir / "final.json").exists()


@pytest.mark.parametrize("score", [1, 2])
@pytest.mark.parametrize("submitted", ["{", '{"accepted": true}'])
def test_reuse_advice_obeys_the_same_reference_fidelity_gate(tools, score, submitted):
    tools._selected_reference_ids.add("source-reference")
    _prepare(
        tools,
        {
            **_critique(),
            "reference_fidelity": {
                "score": score,
                "reasons": "Compared the selected source and current preview.",
                "regressed_to_house_style": False,
            },
        },
    )
    refusal = tools.finalize_run("accepted", "review_complete", "Ready", submitted)
    assert refusal.startswith("REFUSED")
    assert ("Retry finalize_run without critique_json" in refusal) == (score >= 2)
    assert not (tools.trace_dir / "final.json").exists()
    retried = tools.finalize_run("accepted", "review_complete", "Ready")
    if score >= 2:
        assert json.loads(retried)["status"] == "accepted"
    else:
        assert retried.startswith("REFUSED")


@pytest.mark.parametrize("failure", [None, "other_svg_error", "invalid_png", "debug_only"])
def test_png_acceptance_excuses_only_the_existing_svg_font_embedding_refusal(
    tools, monkeypatch, failure
):
    from test_scene_checkpoint import FONT_EMBED_REFUSAL

    _compile(tools)
    tools.preflight_design()
    pixels = BytesIO()
    Image.new("RGB", (1080, 1080), "#224466").save(pixels, format="PNG")
    original_export = tools.core.export_preview
    message = "unrelated SVG failure" if failure == "other_svg_error" else FONT_EMBED_REFUSAL

    def export_with_svg_refusal(scene, export_format="svg", **kwargs):
        if export_format == "svg":
            raise CoreError("export.failed", message)
        response = original_export(scene, export_format, **kwargs)
        response["export"]["artifacts"][0]["bytes"] = list(
            b"" if failure == "invalid_png" else pixels.getvalue()
        )
        return response

    monkeypatch.setattr(tools.core, "export_preview", export_with_svg_refusal)
    bundle = json.loads(tools.export_preview_bundle("png", debug_only=failure == "debug_only"))
    # The unsupported SVG remains visible even when the raster can be accepted.
    assert bundle["reviewer"]["status"] == "error"
    assert any(message in error for error in bundle["reviewer"]["validation_errors"])
    critique = _critique()
    tools.submit_visual_critique(json.dumps(critique))
    result = _finalize(tools, critique)
    if failure is None:
        final = json.loads(result)
        assert final["status"] == "accepted"
        artifacts = final["acceptance_receipt"]["preview"]["artifacts"]
        assert len(artifacts) == 1 and artifacts[0]["path"].endswith(".png")
        assert Path(artifacts[0]["path"]).read_bytes() == pixels.getvalue()
    else:
        assert result.startswith("REFUSED")
        assert not (tools.trace_dir / "final.json").exists()


def test_director_can_verify_unchanged_author_work_without_invalidating_its_review(tools):
    critique = _prepare(tools)
    reviewed_scene = json.dumps(tools.scene, sort_keys=True)
    # Both fast-loop directors verify again after the author's accepted review.
    tools.preflight_design()
    tools.export_preview("svg")
    assert json.dumps(tools.scene, sort_keys=True) == reviewed_scene
    assert json.loads(_finalize(tools, critique))["status"] == "accepted"


def test_failed_run_preserves_an_honest_draft_without_acceptance_evidence(tools):
    _compile(tools)
    result = json.loads(_finalize(tools, _critique(accepted=False), status="failed"))
    assert result["status"] == "failed"
    assert (tools.trace_dir / "final_scene.json").exists()


def test_fast_loop_file_write_and_edit_register_the_actual_review(tools):
    from lumen_agent.fs_backend import AgentWorkspaceBackend

    _compile(tools)
    tools.preflight_design()
    tools.export_preview("svg")
    backend = AgentWorkspaceBackend(
        tools.config.workspace_root, critique_observer=tools.observe_written_critique
    )
    path = f"/{tools.run_id}/workspace/rounds/round_1/critique.json"
    assert not backend.write(path, json.dumps(_critique(accepted=False))).error
    assert not backend.edit(path, '"accepted": false', '"accepted": true').error
    assert (
        json.loads(tools.finalize_run("accepted", "review_complete", "Ready"))["status"]
        == "accepted"
    )


def test_previous_round_cannot_register_another_review_for_current_pixels(tools):
    _prepare(tools, _critique(accepted=False))
    workspace = tools.trace_dir / "workspace"
    (workspace / "rounds/round_2").mkdir(parents=True)
    tools.observe_written_critique(
        workspace / "rounds/round_1/critique.json", json.dumps(_critique())
    )
    assert _finalize(tools, _critique()).startswith("REFUSED")


def test_malformed_replacement_invalidates_a_previous_passing_review(tools):
    critique = _prepare(tools)
    tools.submit_visual_critique('{"accepted":true}')
    assert _finalize(tools, critique).startswith("REFUSED")


def test_valid_direction_records_only_available_sources_and_catalog_playbooks(tools):
    from test_scene_skill_family import direction

    path = tools.trace_dir / "workspace" / "creative-direction.json"
    path.parent.mkdir(exist_ok=True)
    payload = direction()
    path.write_text(json.dumps(payload))
    assert json.loads(tools.validate_creative_direction())["status"] == "ok"
    payload["source_roles"] = [{"asset_id": "other-tenant-image", "role": "treatment"}]
    path.write_text(json.dumps(payload))
    assert json.loads(tools.validate_creative_direction())["status"] == "error"
    payload["source_roles"] = []
    payload["playbook"] = "nonexistent-family"
    path.write_text(json.dumps(payload))
    assert json.loads(tools.validate_creative_direction())["status"] == "error"
