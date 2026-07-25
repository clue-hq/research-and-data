"""C5.3 execution-control descriptor and registration contracts."""

from __future__ import annotations

from dataclasses import replace
from typing import Any, cast

from clue_api.execution_tools import (
    ExecutionControlServices,
    execution_control_tools,
    register_execution_control_tools,
)
from clue_toolbelt import ToolEffectClass, ToolRegistry


def _services(registry: ToolRegistry) -> ExecutionControlServices:
    unavailable = cast(Any, None)
    return ExecutionControlServices(
        starter=unavailable,
        executor=unavailable,
        parameters=unavailable,
        recipes=unavailable,
        run_machine=unavailable,
        queue=unavailable,
        conn_factory=unavailable,
        registry=registry,
    )


def test_execution_controls_are_typed_recipe_safe_and_audited_when_steering() -> None:
    tools = execution_control_tools(_services(ToolRegistry()))
    assert {tool.name for tool in tools} == {
        "start_recipe_execution",
        "pause_recipe_execution",
        "resume_recipe_execution",
        "decide_recipe_gate",
        "pin_execution_as_recipe",
        "advance_project_phase",
    }
    for tool in tools:
        descriptor = tool.descriptor
        assert descriptor.has_typed_output
        assert descriptor.recipe_safe
        if descriptor.effect_class is ToolEffectClass.STEERING:
            assert descriptor.has_steering_snapshot


def test_execution_controls_register_as_exact_default_versions() -> None:
    registry = ToolRegistry()
    services = _services(registry)
    register_execution_control_tools(services)
    for tool in execution_control_tools(services):
        assert registry.get(tool.name, tool.version) is not None
        assert registry.get(tool.name) is not None


def test_c5_5_control_tools_have_typed_outputs_operation_identity_and_steering_audits() -> None:
    registry = ToolRegistry()
    services = replace(_services(registry), controls=cast(Any, object()))
    tools = {tool.name: tool for tool in execution_control_tools(services)}
    assert {
        "apply_run_control",
        "release_run_control",
        "acknowledge_run_escalation",
    } <= tools.keys()
    for name in (
        "apply_run_control",
        "release_run_control",
        "acknowledge_run_escalation",
    ):
        descriptor = tools[name].descriptor
        assert descriptor.has_typed_output
        assert descriptor.has_steering_snapshot
        assert descriptor.replay.operation_id_required
