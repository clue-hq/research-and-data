"""Offline delivery boundaries: first-read critique contract and preflight volume."""

import asyncio
import copy
import json
import re
from dataclasses import replace

import pytest
from agent_fixtures import FakeCoreClient, runtime_config
from lumen_agent import materialize, prompts
from lumen_agent.fs_backend import AgentWorkspaceBackend
from lumen_agent.models.schemas import SceneVisualCritique
from lumen_agent.tools import substrate
from lumen_api.core import CoreError
from test_scene_direction_review import review, validate
from test_scene_guidance_reads import sdk_reader
from test_scene_skill_family import direction


def unnumber(content):
    return "\n".join(line.split("\t", 1)[1] for line in content.splitlines() if "\t" in line)


def test_materialized_first_read_contains_complete_parseable_candidate_contract(tmp_path):
    config = replace(runtime_config(tmp_path), scene_skill_bundle="candidate")
    materialize.materialize_agent_workspace(config, knowledge_view="scene")
    _, result = sdk_reader(config.workspace_root)(
        {"file_path": "/knowledge_docs/knowledge/scene/review.md"}
    )
    assert result.additional_kwargs["guidance_read"]["end_line"] == 100
    window = unnumber(result.content)
    examples = re.findall(r"```json\n(.*?)\n```", window, re.S)
    assert examples, "The first normal read must include a complete JSON review example"
    critique = SceneVisualCritique.model_validate_json(examples[0])
    assert critique.accepted is False
    assert critique.direction_review.checks[0].status == "unverified"
    occurrence = critique.direction_review.copy_occurrences[0]
    assert occurrence.support.status == occurrence.readability.status == "unverified"
    assert occurrence.support.source_gaps is not None

    # Guard all actual nested enum values, without maintaining a second schema.
    def check_enums(schema):
        if isinstance(schema, dict):
            for value in schema.get("enum", []):
                assert str(value) in window, f"Missing enum value in first read: {value!r}"
            for child in schema.values():
                check_enums(child)
        elif isinstance(schema, list):
            for child in schema:
                check_enums(child)

    check_enums(SceneVisualCritique.model_json_schema())
    for binding in ("page_id", "node_id", "text", "join_before", "source_gaps"):
        assert binding in window
    assert "every declared copy ID" in window and "every nonempty native text node" in window
    assert "rejected" in window and "scoped_edit" in window


@pytest.mark.parametrize("has_references", [False, True])
def test_candidate_prompts_reference_single_contract_instead_of_legacy_envelope(has_references):
    for prompt in (
        prompts.build_scene_solo_prompt("/run_test/workspace", has_references=has_references),
        prompts.build_author_prompt(
            "/run_test/workspace",
            fast_loop=True,
            scene_skill_bundle="candidate",
            has_references=has_references,
        ),
        prompts.build_reviewer_prompt(
            "/run_test/workspace",
            scene_skill_bundle="candidate",
            has_references=has_references,
        ),
    ):
        assert "/knowledge_docs/knowledge/scene/review.md" in prompt
        assert "schema below" not in prompt
        assert prompts._AUTHOR_SELF_AUDIT_CONTRACT not in prompt
        assert prompts._AUTHOR_SELF_AUDIT_FIDELITY not in prompt
        assert "full VisualCritique JSON" not in prompt
    reviewer = prompts.build_reviewer_prompt(
        "/run_test/workspace", scene_skill_bundle="candidate", has_references=has_references
    )
    assert "SceneVisualCritique" in reviewer


@pytest.fixture
def offline_tools(tmp_path, monkeypatch):
    monkeypatch.setattr(substrate, "CoreClient", FakeCoreClient)
    config = replace(runtime_config(tmp_path), scene_skill_bundle="candidate")
    materialize.materialize_agent_workspace(config, knowledge_view="scene")
    runtime = substrate.LumenDesignTools(config, "Review this creative")
    assert json.loads(runtime.compile_dsl_block("page fixture"))["compile"]["status"] == "ok"
    runtime.preflight_design()
    runtime.export_preview("svg")
    return runtime


@pytest.mark.parametrize(
    "defect,reason",
    [
        ("invalid_enum", "unverified"),
        ("misplaced_gaps", "Extra inputs are not permitted"),
        ("misplaced_direction_gaps", "Extra inputs are not permitted"),
        ("incomplete_copy", "every declared copy ID"),
    ],
)
@pytest.mark.parametrize("operation", ["write", "edit", "awrite", "aedit"])
def test_file_observer_rejects_pilot_defects_and_registers_explicit_correction(
    offline_tools,
    defect,
    reason,
    operation,
):
    tools = offline_tools
    planned = direction()
    planned["copy"][0]["text"] = "Plan"
    valid = review(validate(tools, planned), page_id="page_test", node_id="headline", text="Plan")
    broken = copy.deepcopy(valid)
    if defect == "invalid_enum":
        broken["accepted"] = False
        broken["direction_review"]["checks"][0]["status"] = "unresolved"
    elif defect == "misplaced_gaps":
        occurrence = broken["direction_review"]["copy_occurrences"][0]
        occurrence["source_gaps"] = occurrence["support"].pop("source_gaps")
    elif defect == "misplaced_direction_gaps":
        occurrence = broken["direction_review"]["copy_occurrences"][0]
        broken["direction_review"]["source_gaps"] = occurrence["support"].pop("source_gaps")
    else:
        broken["direction_review"]["copy_occurrences"] = []
        SceneVisualCritique.model_validate(broken)  # semantic refusal, not a schema error
    backend = AgentWorkspaceBackend(
        tools.config.workspace_root,
        active_run_id=tools.run_id,
        critique_observer=tools.observe_written_critique,
    )
    key = f"/{tools.run_id}/workspace/critique.json"
    if operation in {"edit", "aedit"}:
        assert backend.write(key, json.dumps(valid)).error is None
        args = (key, json.dumps(valid), json.dumps(broken))
    else:
        args = (key, json.dumps(broken))
    result = getattr(backend, operation)(*args)
    if operation.startswith("a"):
        result = asyncio.run(result)
    assert result.error and reason in result.error
    assert json.loads((tools.trace_dir / "workspace/critique.json").read_text()) == broken
    assert tools._latest_visual_critique is None
    assert tools._review_receipt is None
    assert tools.finalize_run("accepted", "review_complete", "Invalid review").startswith("REFUSED")
    correction = backend.aedit if operation.startswith("a") else backend.edit
    corrected = correction(key, json.dumps(broken), json.dumps(valid))
    if operation.startswith("a"):
        corrected = asyncio.run(corrected)
    assert corrected.error is None
    assert tools._latest_visual_critique["direction_review"] == valid["direction_review"]
    assert (
        json.loads(tools.finalize_run("accepted", "review_complete", "Corrected"))["status"]
        == "accepted"
    )


class VerbosePreflightCore(FakeCoreClient):
    def preflight_scene(self, scene, brand_kit, brand_fonts=None):
        response = super().preflight_scene(scene, brand_kit, brand_fonts)
        response["preflight"].update(
            {
                "token_operations": [
                    {"kind": "update_node", "node_id": f"token_{i}", "patch": {"fill": "#abcdee"}}
                    for i in range(90)
                ],
                "layout_operations": [
                    {"kind": "update_node", "node_id": f"layout_{i}", "patch": {"x": i, "y": i}}
                    for i in range(70)
                ],
                "diagnostics": [{"message": f"Raw finding {i}"} for i in range(55)],
                "unknown_status": "preserve-me",
            }
        )
        response["diagnostics"] = [
            {
                "code": f"TEST{i}",
                "severity": "warning",
                "phase": "validation",
                "message": f"Finding {i}",
            }
            for i in range(55)
        ]
        return response


@pytest.mark.parametrize("bundle", ["candidate", "legacy"])
def test_preflight_model_projection_preserves_full_saved_and_trace_report(
    tmp_path, monkeypatch, bundle
):
    monkeypatch.setattr(substrate, "CoreClient", VerbosePreflightCore)
    config = replace(runtime_config(tmp_path), scene_skill_bundle=bundle, fast_loop=True)
    tools = substrate.LumenDesignTools(config, "Preflight report")
    # Autofix/collision calculations are separate contracts. Supply their real
    # return shapes to prove presentation never filters the findings.
    from lumen_agent.autofix import AutofixRecord, AutofixResult

    autofix = AutofixResult(
        scene=tools.scene,
        diagnostics=[],
        rolled_back=[
            AutofixRecord(
                klass="text",
                codes=("TEST",),
                subject="headline",
                detail="Tried repair",
                operations=({"kind": "update_node"},),
                accepted=False,
                reason="Still blocked",
            )
        ],
    )
    monkeypatch.setattr(tools, "_run_autofix", lambda *_: autofix)
    collision = {"pairs": [{"node_id": f"overlap_{i}"} for i in range(55)]}
    monkeypatch.setattr(substrate, "collision_advisory", lambda _: collision)
    # A second iteration must point to the current iteration, not a cached path.
    for iteration in (1, 2):
        tools.iteration = iteration
        returned = tools.preflight_design()
        result = json.loads(returned)
        path = tools.trace_dir / f"iterations/{iteration:03d}/preflight.json"
        saved = json.loads(path.read_text())
        event = [
            json.loads(line) for line in (tools.trace_dir / "trace.jsonl").read_text().splitlines()
        ][-1]
        assert event["event"] == "preflight_completed"
        assert event["payload"] == saved
        assert len(saved["raw_preflight"]["token_operations"]) == 90
        assert len(saved["raw_preflight"]["layout_operations"]) == 70
        assert len(saved["raw_preflight"]["diagnostics"]) == 55
        for key in ("preflight", "effective_brand", "autofix", "text_collisions"):
            assert result[key] == saved[key]
        assert len(result["preflight"]["diagnostics"]) == 55
        if bundle == "legacy":
            assert returned == json.dumps(saved, indent=2)
            assert set(result) == {
                "preflight",
                "raw_preflight",
                "effective_brand",
                "autofix",
                "text_collisions",
            }
            continue
        assert "token_operations" not in result["raw_preflight"]
        assert "layout_operations" not in result["raw_preflight"]
        assert result["raw_preflight"]["operation_counts"] == {
            "token_operations": 90,
            "layout_operations": 70,
        }
        assert result["raw_preflight"]["diagnostics"] == saved["raw_preflight"]["diagnostics"]
        assert result["raw_preflight"]["unknown_status"] == "preserve-me"
        assert len(returned.encode()) < len(json.dumps(saved, indent=2).encode()) - 15000
        assert (
            result["full_report_path"]
            == f"/{tools.run_id}/iterations/{iteration:03d}/preflight.json"
        )
        backend = AgentWorkspaceBackend(config.workspace_root, active_run_id=tools.run_id)
        read = backend.read(result["full_report_path"], limit=10000)
        assert read.error is None
        assert json.loads(read.file_data["content"]) == saved
        other = AgentWorkspaceBackend(config.workspace_root, active_run_id="run_other")
        assert other.read(result["full_report_path"]).error


@pytest.mark.parametrize("bundle", ["candidate", "legacy"])
def test_failed_preflight_preserves_diagnostics_and_scoped_report(tmp_path, monkeypatch, bundle):
    class FailingCore(FakeCoreClient):
        def preflight_scene(self, *args, **kwargs):
            raise CoreError(
                "test.failure",
                "Cannot preflight",
                diagnostics=[
                    {
                        "code": "TEST",
                        "severity": "error",
                        "phase": "validation",
                        "message": "Exact failure",
                    }
                ],
            )

    monkeypatch.setattr(substrate, "CoreClient", FailingCore)
    tools = substrate.LumenDesignTools(
        replace(runtime_config(tmp_path), scene_skill_bundle=bundle), "Failure"
    )
    returned = tools.preflight_design()
    result = json.loads(returned)
    saved = json.loads((tools.trace_dir / "iterations/001/preflight.json").read_text())
    assert result["preflight"] == saved["preflight"]
    assert result["preflight"]["has_errors"] is True
    if bundle == "legacy":
        assert returned == json.dumps(saved, indent=2)
    else:
        assert result["full_report_path"] == f"/{tools.run_id}/iterations/001/preflight.json"
        backend = AgentWorkspaceBackend(tools.config.workspace_root, active_run_id=tools.run_id)
        read = backend.read(result["full_report_path"])
        assert read.error is None
        assert json.loads(read.file_data["content"]) == saved
        event = json.loads((tools.trace_dir / "trace.jsonl").read_text().splitlines()[-1])
        assert event["event"] == "preflight_failed"
        assert event["payload"] == saved
