"""Transport the pinned edit context; typography semantics live in Rust tests."""

import json
from dataclasses import replace

import pytest
from agent_fixtures import FakeCoreClient, runtime_config
from lumen_agent.tools import substrate
from lumen_api.core import CoreClient


@pytest.mark.parametrize("structured", [False, True])
def test_core_client_serializes_optional_edit_context(monkeypatch, structured):
    core = CoreClient()
    monkeypatch.setattr(core, "_run", lambda request: request)
    kit, mode = {"id": "pinned", "version": 7}, {"theme": "dark"}
    if structured:
        request = core.apply_structured_edit({}, {}, brand_kit=kit, mode=mode)
        legacy = core.apply_structured_edit({}, {})
    else:
        request = core.compile_dsl_into_scene({}, "", brand_kit=kit, mode=mode)
        legacy = core.compile_dsl_into_scene({}, "")
    assert request["brand_kit"] == kit
    assert request["mode"] == mode
    assert "brand_kit" not in legacy
    assert "mode" not in legacy


def test_runtime_passes_selected_kit_and_scene_medium_to_both_edit_paths(tmp_path, monkeypatch):
    calls = []

    class RecordingCore(FakeCoreClient):
        def compile_dsl_into_scene(self, scene, source, **kwargs):
            calls.append(kwargs)
            return super().compile_dsl_into_scene(scene, source, **kwargs)

        def apply_structured_edit(self, scene, edit, **kwargs):
            calls.append(kwargs)
            return super().apply_structured_edit(scene, edit, **kwargs)

    monkeypatch.setattr(substrate, "CoreClient", RecordingCore)
    kit = {"id": "pinned", "version": 7, "name": "Pinned", "approval_status": "approved"}
    config = replace(runtime_config(tmp_path), brand_kit=kit, brand_kit_source="leg_pin")
    tools = substrate.LumenDesignTools(config, "Repair only the requested text fields.")
    tools.compile_dsl_block("page square size(1080,1080,px)")
    tools.apply_structured_edit(
        json.dumps(
            {
                "kind": "modify",
                "target": {"kind": "node", "id": "headline"},
                "patch": {"kind": "node", "value": {}},
            }
        )
    )
    assert len(calls) == 2
    assert all(call["brand_kit"] is kit for call in calls)
    assert all(call["mode"]["medium"] == "digital" for call in calls)
