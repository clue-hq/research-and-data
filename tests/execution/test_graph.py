"""C5.2 closed graph/binding validation."""

from __future__ import annotations

import random

import pytest
from pydantic import JsonValue, ValidationError

from clue_execution import (
    BarrierNode,
    GateNode,
    GateResumeCondition,
    LiteralBinding,
    MapNode,
    NodeReferenceBinding,
    ParameterBinding,
    PinRequest,
    RecipeGraph,
    ToolNode,
    canonical_sha256,
    validate_graph,
)
from clue_toolbelt import (
    JournalParameterPolicy,
    ReplayPolicy,
    ReplaySafety,
    ToolEffectClass,
    ToolInput,
    ToolOutput,
    ToolRegistry,
)
from tests.toolbelt.conftest import EchoTool


class _SourceInput(ToolInput):
    seed: int


class _SourceOutput(ToolOutput):
    value: int
    values: tuple[int, ...]


class _TargetInput(ToolInput):
    value: int


class _TargetOutput(ToolOutput):
    accepted: int


class _SafeTool(EchoTool):
    replay = ReplaySafety(
        policy=ReplayPolicy.OPERATION_IDEMPOTENT,
        durable_identity="operation_id",
        operation_id_required=True,
    )
    effect_class = ToolEffectClass.WRITE
    parameter_policy = JournalParameterPolicy()
    pin_requirements = ()


class _SourceTool(_SafeTool):
    name = "source"
    input_model = _SourceInput
    output_model = _SourceOutput


class _TargetTool(_SafeTool):
    name = "target"
    input_model = _TargetInput
    output_model = _TargetOutput


def _catalog() -> ToolRegistry:
    registry = ToolRegistry()
    registry.register(_SourceTool(), make_default=True)
    registry.register(_TargetTool(), make_default=True)
    return registry


class _JsonInput(ToolInput):
    value: JsonValue


class _JsonTool(_SafeTool):
    name = "json_target"
    input_model = _JsonInput
    output_model = _TargetOutput


@pytest.mark.parametrize("unconstrained_target", [True, False])
def test_arbitrary_json_binding_accepts_json_but_not_a_narrower_type(unconstrained_target):
    registry = _catalog()
    registry.register(_JsonTool(), make_default=True)
    name = "json_target" if unconstrained_target else "target"
    node = _tool_node(
        registry,
        key="consume",
        name=name,
        ordinal=0,
        bindings={"value": ParameterBinding(kind="parameter", name="value")},
    )
    report = validate_graph(
        RecipeGraph(nodes=(node,), tool_allowlist=(f"{name}@1",)),
        parameter_schema={
            "type": "object",
            "properties": {"value": {}},
            "required": ["value"],
            "additionalProperties": False,
        },
        tool_catalog=registry,
        max_nodes=2,
        max_depth=2,
        max_fanout=1,
    )
    assert report.valid is unconstrained_target


def _tool_node(
    registry: ToolRegistry,
    *,
    key: str,
    name: str,
    ordinal: int,
    dependencies: tuple[str, ...] = (),
    bindings=None,
) -> ToolNode:
    descriptor = registry.descriptor(name, "1")
    return ToolNode(
        node_key=key,
        ordinal=ordinal,
        dependencies=dependencies,
        tool_name=name,
        tool_version="1",
        input_schema_sha256=descriptor.input_schema_sha256,
        output_schema_sha256=descriptor.output_schema_sha256,
        bindings=bindings or {},
        requirements=(PinRequest(kind="tool", key=name, version="1"),),
    )


def test_valid_typed_data_edge_and_canonical_digest() -> None:
    registry = _catalog()
    source = _tool_node(
        registry,
        key="source",
        name="source",
        ordinal=0,
        bindings={"seed": ParameterBinding(kind="parameter", name="seed")},
    )
    target = _tool_node(
        registry,
        key="target",
        name="target",
        ordinal=1,
        dependencies=("source",),
        bindings={
            "value": NodeReferenceBinding(
                kind="node_reference",
                node_key="source",
                reference_path=("value",),
            )
        },
    )
    graph = RecipeGraph(
        nodes=(source, target),
        tool_allowlist=("source@1", "target@1"),
    )
    parameter_schema = {
        "type": "object",
        "properties": {"seed": {"type": "integer"}},
        "required": ["seed"],
        "additionalProperties": False,
    }
    report = validate_graph(
        graph,
        parameter_schema=parameter_schema,
        tool_catalog=registry,
        max_nodes=4,
        max_depth=2,
        max_fanout=2,
    )
    assert report.valid
    assert report.graph_sha256 == canonical_sha256(
        RecipeGraph.model_validate(graph.model_dump(mode="python"))
    )


def test_validator_returns_graph_schema_allowlist_and_privacy_defects_together() -> None:
    registry = _catalog()
    source = _tool_node(
        registry,
        key="source",
        name="source",
        ordinal=0,
        dependencies=("target", "absent"),
        bindings={"seed": ParameterBinding(kind="parameter", name="unknown")},
    )
    target = _tool_node(
        registry,
        key="target",
        name="target",
        ordinal=1,
        dependencies=("source",),
        bindings={
            "value": NodeReferenceBinding(
                kind="node_reference",
                node_key="source",
                reference_path=("missing",),
            )
        },
    )
    # A tool input named body is structurally forbidden from the recipe JSON even when the tool
    # schema itself happened to expose it.
    graph_payload = RecipeGraph(
        nodes=(source, target),
        tool_allowlist=("source@1",),
    ).model_dump(mode="python")
    graph_payload["body"] = "not accepted"  # proves the Pydantic surface is closed
    with pytest.raises(ValidationError):
        RecipeGraph.model_validate(graph_payload)

    report = validate_graph(
        RecipeGraph(nodes=(source, target), tool_allowlist=("source@1",)),
        parameter_schema={"type": "object", "properties": {}},
        tool_catalog=registry,
        max_nodes=1,
        max_depth=1,
        max_fanout=1,
    )
    codes = {issue.code for issue in report.issues}
    assert {
        "cycle",
        "missing_dependency",
        "node_ceiling",
        "tool_not_allowed",
        "unknown_output_path",
        "unknown_parameter",
    } <= codes


def test_gate_and_bounded_map_envelopes_are_enforced() -> None:
    registry = _catalog()
    template = _tool_node(
        registry,
        key="one",
        name="target",
        ordinal=0,
        bindings={"value": ParameterBinding(kind="parameter", name="item")},
    )
    graph = RecipeGraph(
        nodes=(
            GateNode(
                node_key="approval",
                ordinal=0,
                authority="human:admin",
                resume_condition=GateResumeCondition.HUMAN_DECISION,
            ),
            MapNode(
                node_key="fanout",
                ordinal=1,
                dependencies=("approval",),
                source=ParameterBinding(kind="parameter", name="items"),
                item_parameter="item",
                max_items=5,
                template=(template,),
            ),
        ),
        tool_allowlist=("target@1",),
        authority_allowlist=("human:owner",),
    )
    report = validate_graph(
        graph,
        parameter_schema={
            "type": "object",
            "properties": {"items": {"type": "array", "items": {"type": "integer"}}},
        },
        tool_catalog=registry,
        max_nodes=4,
        max_depth=1,
        max_fanout=2,
    )
    codes = {issue.code for issue in report.issues}
    assert {"authority_not_allowed", "depth_ceiling", "fanout_ceiling", "node_ceiling"} <= codes


def test_bounded_interaction_slot_requires_exact_safe_tools_and_pin_envelope() -> None:
    registry = _catalog()
    unsafe = EchoTool()
    registry.register(unsafe, make_default=True)
    graph = RecipeGraph(
        nodes=(
            GateNode(
                node_key="interactions",
                ordinal=0,
                authority="human",
                resume_condition=GateResumeCondition.INPUT_AVAILABLE,
                dynamic_tool_allowlist=("source@1", "echo@1"),
                dynamic_pin_kinds=("source_profile",),
                max_children=3,
                requirements=(PinRequest(kind="tool", key="source", version="1"),),
            ),
        ),
        tool_allowlist=("source@1", "echo@1"),
        authority_allowlist=("human",),
    )
    report = validate_graph(
        graph,
        parameter_schema={"type": "object", "properties": {}},
        tool_catalog=registry,
        max_nodes=3,
        max_depth=1,
        max_fanout=1,
    )
    codes = {issue.code for issue in report.issues}
    assert {
        "node_ceiling",
        "missing_tool_pin",
        "tool_not_recipe_safe",
    } <= codes


def test_dynamic_children_require_an_input_gate_and_positive_ceiling() -> None:
    with pytest.raises(ValidationError, match="input_available"):
        GateNode(
            node_key="interactions",
            ordinal=0,
            authority="human",
            resume_condition=GateResumeCondition.HUMAN_DECISION,
            dynamic_tool_allowlist=("source@1",),
            max_children=1,
        )
    with pytest.raises(ValidationError, match="positive max_children"):
        GateNode(
            node_key="interactions",
            ordinal=0,
            authority="human",
            resume_condition=GateResumeCondition.INPUT_AVAILABLE,
            dynamic_tool_allowlist=("source@1",),
        )


def test_binding_ast_rejects_templates_callables_and_jsonpath() -> None:
    for payload in (
        {"kind": "jinja", "template": "{{ secret }}"},
        {"kind": "callable", "path": "module:function"},
        {"kind": "node_reference", "node_key": "x", "reference_path": ("$.value",)},
    ):
        with pytest.raises(ValidationError):
            if payload["kind"] == "node_reference":
                NodeReferenceBinding.model_validate(payload)
            else:
                LiteralBinding.model_validate(payload)
    with pytest.raises(ValidationError, match="bodies belong in artifacts"):
        LiteralBinding(kind="literal", value="first line\nprivate body")


def test_generated_dags_are_accepted_and_back_edges_are_rejected() -> None:
    registry = _catalog()
    rng = random.Random(20260724)
    for size in range(2, 20):
        nodes = []
        for index in range(size):
            dependencies = tuple(
                f"n{candidate}" for candidate in range(index) if rng.random() < 0.12
            )
            nodes.append(
                BarrierNode(
                    node_key=f"n{index}",
                    ordinal=index,
                    dependencies=dependencies,
                )
            )
        valid = validate_graph(
            RecipeGraph(nodes=tuple(nodes)),
            parameter_schema={"type": "object", "properties": {}},
            tool_catalog=registry,
            max_nodes=20,
            max_depth=2,
            max_fanout=2,
        )
        assert valid.valid

        cyclic_nodes = list(nodes)
        cyclic_nodes[0] = BarrierNode(
            node_key="n0",
            ordinal=0,
            dependencies=(f"n{size - 1}",),
        )
        cyclic_nodes[-1] = BarrierNode(
            node_key=f"n{size - 1}",
            ordinal=size - 1,
            dependencies=("n0",),
        )
        cyclic = validate_graph(
            RecipeGraph(nodes=tuple(cyclic_nodes)),
            parameter_schema={"type": "object", "properties": {}},
            tool_catalog=registry,
            max_nodes=20,
            max_depth=2,
            max_fanout=2,
        )
        assert any(issue.code == "cycle" for issue in cyclic.issues)
