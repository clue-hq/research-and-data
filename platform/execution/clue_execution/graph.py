"""Closed recipe-graph language and promotion-time validator.

The language is deliberately data-only. Bindings can name a literal, a recipe parameter, or a
field in a prior typed tool result; they cannot evaluate code, templates, JSONPath, or callables.
"""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict, deque
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Annotated, Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field, model_validator

from clue_execution.models import ExecutionNodeKind, PinRequest
from clue_toolbelt import ToolDescriptor


class _FrozenModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)


class LiteralBinding(_FrozenModel):
    kind: Literal["literal"]
    value: str | int | float | bool | None

    @model_validator(mode="after")
    def _display_safe_scalar(self) -> LiteralBinding:
        if isinstance(self.value, str) and (
            len(self.value) > 256 or "\n" in self.value or "\r" in self.value
        ):
            raise ValueError(
                "literal strings must be short single-line scalars; bodies belong in artifacts"
            )
        return self


class ParameterBinding(_FrozenModel):
    kind: Literal["parameter"]
    name: str = Field(min_length=1, pattern=r"^[A-Za-z_][A-Za-z0-9_]*$")


class NodeReferenceBinding(_FrozenModel):
    kind: Literal["node_reference"]
    node_key: str = Field(min_length=1, pattern=r"^[A-Za-z_][A-Za-z0-9_.-]*$")
    reference_path: tuple[
        Annotated[str, Field(min_length=1, pattern=r"^[A-Za-z_][A-Za-z0-9_]*$")], ...
    ] = Field(min_length=1)


type Binding = Annotated[
    LiteralBinding | ParameterBinding | NodeReferenceBinding,
    Field(discriminator="kind"),
]


class ToolNode(_FrozenModel):
    kind: Literal[ExecutionNodeKind.TOOL] = ExecutionNodeKind.TOOL
    node_key: str = Field(min_length=1, pattern=r"^[A-Za-z_][A-Za-z0-9_.-]*$")
    ordinal: int = Field(ge=0)
    dependencies: tuple[str, ...] = ()
    tool_name: str = Field(min_length=1)
    tool_version: str = Field(min_length=1)
    input_schema_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    output_schema_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    bindings: dict[str, Binding] = Field(default_factory=dict)
    requirements: tuple[PinRequest, ...] = ()

    @property
    def tool_address(self) -> str:
        return f"{self.tool_name}@{self.tool_version}"


class GateResumeCondition(StrEnum):
    HUMAN_DECISION = "human_decision"
    DETERMINISTIC_DECISION = "deterministic_decision"
    EXTERNAL_EVENT = "external_event"
    INPUT_AVAILABLE = "input_available"


class GateNode(_FrozenModel):
    kind: Literal[ExecutionNodeKind.GATE] = ExecutionNodeKind.GATE
    node_key: str = Field(min_length=1, pattern=r"^[A-Za-z_][A-Za-z0-9_.-]*$")
    ordinal: int = Field(ge=0)
    dependencies: tuple[str, ...] = ()
    authority: str = Field(min_length=1)
    resume_condition: GateResumeCondition
    dynamic_tool_allowlist: tuple[str, ...] = ()
    dynamic_pin_kinds: tuple[str, ...] = ()
    max_children: int = Field(default=0, ge=0)
    requirements: tuple[PinRequest, ...] = ()

    @model_validator(mode="after")
    def _dynamic_slot_shape(self) -> GateNode:
        values = self.dynamic_tool_allowlist
        if len(values) != len(set(values)):
            raise ValueError("dynamic tool allowlist entries must be unique")
        if len(self.dynamic_pin_kinds) != len(set(self.dynamic_pin_kinds)):
            raise ValueError("dynamic pin kinds must be unique")
        if values and self.resume_condition is not GateResumeCondition.INPUT_AVAILABLE:
            raise ValueError("dynamic tool children require an input_available gate")
        if bool(values) != bool(self.max_children):
            raise ValueError(
                "dynamic tool allowlist and a positive max_children must be declared together"
            )
        return self


class BarrierNode(_FrozenModel):
    kind: Literal[ExecutionNodeKind.BARRIER] = ExecutionNodeKind.BARRIER
    node_key: str = Field(min_length=1, pattern=r"^[A-Za-z_][A-Za-z0-9_.-]*$")
    ordinal: int = Field(ge=0)
    dependencies: tuple[str, ...] = ()
    requirements: tuple[PinRequest, ...] = ()


class ActivityNode(_FrozenModel):
    kind: Literal[ExecutionNodeKind.ACTIVITY] = ExecutionNodeKind.ACTIVITY
    node_key: str = Field(min_length=1, pattern=r"^[A-Za-z_][A-Za-z0-9_.-]*$")
    ordinal: int = Field(ge=0)
    dependencies: tuple[str, ...] = ()
    activity_name: str = Field(min_length=1)
    activity_version: str = Field(min_length=1)
    bindings: dict[str, Binding] = Field(default_factory=dict)
    requirements: tuple[PinRequest, ...] = ()

    @property
    def activity_address(self) -> str:
        return f"{self.activity_name}@{self.activity_version}"


type MapTemplateNode = Annotated[
    ToolNode | GateNode | BarrierNode | ActivityNode,
    Field(discriminator="kind"),
]


class MapNode(_FrozenModel):
    kind: Literal[ExecutionNodeKind.MAP] = ExecutionNodeKind.MAP
    node_key: str = Field(min_length=1, pattern=r"^[A-Za-z_][A-Za-z0-9_.-]*$")
    ordinal: int = Field(ge=0)
    dependencies: tuple[str, ...] = ()
    source: Binding
    item_parameter: str = Field(min_length=1, pattern=r"^[A-Za-z_][A-Za-z0-9_]*$")
    max_items: int = Field(ge=1)
    template: tuple[MapTemplateNode, ...] = Field(min_length=1)
    requirements: tuple[PinRequest, ...] = ()


type GraphNode = Annotated[
    ToolNode | GateNode | MapNode | BarrierNode | ActivityNode,
    Field(discriminator="kind"),
]


class RecipeGraph(_FrozenModel):
    nodes: tuple[GraphNode, ...] = ()
    tool_allowlist: tuple[str, ...] = ()
    authority_allowlist: tuple[str, ...] = ()
    activity_allowlist: tuple[str, ...] = ()
    migration_state: Literal["placeholder", "executable"] = "executable"

    @model_validator(mode="after")
    def _unique_allowlists(self) -> RecipeGraph:
        for label, values in (
            ("tool", self.tool_allowlist),
            ("authority", self.authority_allowlist),
            ("activity", self.activity_allowlist),
        ):
            if len(values) != len(set(values)):
                raise ValueError(f"{label} allowlist entries must be unique")
        if self.migration_state == "placeholder" and any(
            isinstance(node, (ToolNode, GateNode, MapNode, ActivityNode)) for node in self.nodes
        ):
            raise ValueError("a placeholder recipe may contain only barrier nodes")
        return self


class ToolDescriptorCatalog(Protocol):
    def descriptor(self, name: str, version: str | None = None) -> ToolDescriptor: ...


@dataclass(frozen=True, slots=True)
class GraphIssue:
    code: str
    location: str
    message: str


@dataclass(frozen=True, slots=True)
class GraphValidation:
    graph_sha256: str
    issues: tuple[GraphIssue, ...]

    @property
    def valid(self) -> bool:
        return not self.issues


_RAW_BODY_KEYS = frozenset(
    {
        "body",
        "content",
        "interview_answer",
        "messages",
        "prompt",
        "prompt_body",
        "raw",
        "raw_body",
        "text",
        "upload",
        "uploaded_text",
    }
)


def canonical_sha256(value: BaseModel | Mapping[str, object] | Sequence[object]) -> str:
    if isinstance(value, BaseModel):
        payload: object = value.model_dump(mode="json", exclude_none=False)
    else:
        payload = value
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(encoded.encode()).hexdigest()


def _body_locations(value: object, *, path: str = "$") -> list[str]:
    locations: list[str] = []
    if isinstance(value, Mapping):
        for key, child in value.items():
            key_text = str(key)
            child_path = f"{path}.{key_text}"
            if key_text.lower() in _RAW_BODY_KEYS:
                locations.append(child_path)
            locations.extend(_body_locations(child, path=child_path))
    elif isinstance(value, list | tuple):
        for index, child in enumerate(value):
            locations.extend(_body_locations(child, path=f"{path}[{index}]"))
    return locations


def _schema_types(schema: Mapping[str, object], root: Mapping[str, object]) -> set[str]:
    resolved = _resolve_ref(schema, root)
    raw_type = resolved.get("type")
    if isinstance(raw_type, str):
        return {raw_type}
    if isinstance(raw_type, list):
        return {item for item in raw_type if isinstance(item, str)}
    types: set[str] = set()
    for key in ("anyOf", "oneOf"):
        variants = resolved.get(key)
        if isinstance(variants, list):
            for variant in variants:
                if isinstance(variant, Mapping):
                    types.update(_schema_types(variant, root))
    if "enum" in resolved:
        enum_values = resolved["enum"]
        if isinstance(enum_values, list):
            types.update(_literal_types(item) for item in enum_values)
    return types


def _literal_types(value: object) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, list):
        return "array"
    return "object"


def _resolve_ref(
    schema: Mapping[str, object],
    root: Mapping[str, object],
) -> Mapping[str, object]:
    ref = schema.get("$ref")
    if not isinstance(ref, str):
        return schema
    if not ref.startswith("#/$defs/"):
        return schema
    target: object = root
    for part in ref[2:].split("/"):
        if not isinstance(target, Mapping) or part not in target:
            return schema
        target = target[part]
    return target if isinstance(target, Mapping) else schema


def _schema_at_path(
    root: Mapping[str, object],
    path: Sequence[str],
) -> Mapping[str, object] | None:
    current: Mapping[str, object] = root
    for part in path:
        resolved = _resolve_ref(current, root)
        properties = resolved.get("properties")
        if not isinstance(properties, Mapping):
            return None
        child = properties.get(part)
        if not isinstance(child, Mapping):
            return None
        current = child
    return _resolve_ref(current, root)


def _schemas_compatible(
    source: Mapping[str, object],
    source_root: Mapping[str, object],
    destination: Mapping[str, object],
    destination_root: Mapping[str, object],
) -> bool:
    # Pydantic's JsonValue emits an empty schema. It admits any JSON value, including
    # another JsonValue binding, but cannot prove compatibility with a narrower target.
    resolved_source = _resolve_ref(source, source_root)
    resolved_destination = _resolve_ref(destination, destination_root)
    if not resolved_destination:
        return True
    if not resolved_source:
        return False
    source_types = _schema_types(source, source_root)
    destination_types = _schema_types(destination, destination_root)
    if not source_types or not destination_types:
        return False
    widened_source = source_types | ({"number"} if "integer" in source_types else set())
    if not widened_source & destination_types:
        return False
    source_enum = resolved_source.get("enum")
    destination_enum = resolved_destination.get("enum")
    if (
        isinstance(source_enum, list)
        and isinstance(destination_enum, list)
        and any(item not in destination_enum for item in source_enum)
    ):
        return False
    if "array" in source_types and "array" in destination_types:
        source_items = resolved_source.get("items")
        destination_items = resolved_destination.get("items")
        if isinstance(source_items, Mapping) and isinstance(destination_items, Mapping):
            return _schemas_compatible(
                source_items,
                source_root,
                destination_items,
                destination_root,
            )
    if "object" in source_types and "object" in destination_types:
        source_properties = resolved_source.get("properties")
        destination_properties = resolved_destination.get("properties")
        required = resolved_destination.get("required")
        if (
            isinstance(source_properties, Mapping)
            and isinstance(destination_properties, Mapping)
            and isinstance(required, list)
        ):
            for name in required:
                source_property = source_properties.get(name)
                destination_property = destination_properties.get(name)
                if not isinstance(source_property, Mapping) or not isinstance(
                    destination_property, Mapping
                ):
                    return False
                if not _schemas_compatible(
                    source_property,
                    source_root,
                    destination_property,
                    destination_root,
                ):
                    return False
    return True


def _literal_matches(
    value: str | int | float | bool | None,
    destination: Mapping[str, object],
    root: Mapping[str, object],
) -> bool:
    destination_types = _schema_types(destination, root)
    literal_type = _literal_types(value)
    if literal_type == "integer" and "number" in destination_types:
        return True
    if literal_type not in destination_types:
        return False
    enum_values = _resolve_ref(destination, root).get("enum")
    return not isinstance(enum_values, list) or value in enum_values


def _topological_issues(nodes: Sequence[GraphNode], *, prefix: str = "graph") -> list[GraphIssue]:
    issues: list[GraphIssue] = []
    keys = [node.node_key for node in nodes]
    duplicates = sorted({key for key in keys if keys.count(key) > 1})
    if duplicates:
        issues.append(
            GraphIssue("duplicate_node", prefix, f"node keys are duplicated: {duplicates}")
        )
    known = set(keys)
    indegree: dict[str, int] = dict.fromkeys(known, 0)
    outgoing: dict[str, list[str]] = defaultdict(list)
    for node in nodes:
        for dependency in node.dependencies:
            if dependency not in known:
                issues.append(
                    GraphIssue(
                        "missing_dependency",
                        f"{prefix}.{node.node_key}",
                        f"dependency {dependency!r} does not exist",
                    )
                )
                continue
            indegree[node.node_key] += 1
            outgoing[dependency].append(node.node_key)
    queue = deque(sorted(key for key, count in indegree.items() if count == 0))
    visited = 0
    while queue:
        current = queue.popleft()
        visited += 1
        for child in sorted(outgoing[current]):
            indegree[child] -= 1
            if indegree[child] == 0:
                queue.append(child)
    if visited != len(known):
        cyclic = sorted(key for key, count in indegree.items() if count > 0)
        issues.append(GraphIssue("cycle", prefix, f"dependency cycle contains: {cyclic}"))
    return issues


def _descriptor_or_issue(
    *,
    catalog: ToolDescriptorCatalog,
    node: ToolNode,
    location: str,
    issues: list[GraphIssue],
) -> ToolDescriptor | None:
    try:
        descriptor = catalog.descriptor(node.tool_name, node.tool_version)
    except Exception as exc:
        issues.append(GraphIssue("unknown_tool", location, str(exc)))
        return None
    if not descriptor.recipe_safe:
        issues.append(
            GraphIssue("tool_not_recipe_safe", location, f"{node.tool_address} is not recipe-safe")
        )
    if descriptor.input_schema_sha256 != node.input_schema_sha256:
        issues.append(
            GraphIssue(
                "input_schema_mismatch",
                location,
                f"{node.tool_address} input schema digest does not match its descriptor",
            )
        )
    if descriptor.output_schema_sha256 != node.output_schema_sha256:
        issues.append(
            GraphIssue(
                "output_schema_mismatch",
                location,
                f"{node.tool_address} output schema digest does not match its descriptor",
            )
        )
    return descriptor


def _validate_tool_bindings(
    *,
    node: ToolNode,
    descriptor: ToolDescriptor,
    by_key: Mapping[str, GraphNode],
    descriptors: Mapping[str, ToolDescriptor],
    parameter_schema: Mapping[str, object],
    local_parameters: Mapping[
        str,
        tuple[Mapping[str, object], Mapping[str, object]],
    ],
    issues: list[GraphIssue],
    location: str,
) -> None:
    input_schema = descriptor.input_model.model_json_schema()
    properties_raw = input_schema.get("properties")
    properties = properties_raw if isinstance(properties_raw, Mapping) else {}
    required_raw = input_schema.get("required")
    required = {str(item) for item in required_raw} if isinstance(required_raw, list) else set()
    bound = set(node.bindings)
    for missing in sorted(required - bound):
        issues.append(
            GraphIssue("missing_binding", location, f"required input {missing!r} is not bound")
        )
    for extra in sorted(bound - set(properties)):
        issues.append(
            GraphIssue("unknown_input", location, f"input {extra!r} is absent from the tool schema")
        )
    parameter_properties_raw = parameter_schema.get("properties")
    parameter_properties = (
        parameter_properties_raw if isinstance(parameter_properties_raw, Mapping) else {}
    )
    for input_name, binding in node.bindings.items():
        destination = properties.get(input_name)
        if not isinstance(destination, Mapping):
            continue
        binding_location = f"{location}.bindings.{input_name}"
        if isinstance(binding, LiteralBinding):
            if not _literal_matches(binding.value, destination, input_schema):
                issues.append(
                    GraphIssue(
                        "binding_type_mismatch",
                        binding_location,
                        "literal is incompatible with the destination input schema",
                    )
                )
            continue
        if isinstance(binding, ParameterBinding):
            local_source = local_parameters.get(binding.name)
            if local_source is None:
                candidate = parameter_properties.get(binding.name)
                source = candidate if isinstance(candidate, Mapping) else None
                source_root = parameter_schema
            else:
                source, source_root = local_source
            if source is None:
                issues.append(
                    GraphIssue(
                        "unknown_parameter",
                        binding_location,
                        f"parameter {binding.name!r} is not declared",
                    )
                )
            elif not _schemas_compatible(source, source_root, destination, input_schema):
                issues.append(
                    GraphIssue(
                        "binding_type_mismatch",
                        binding_location,
                        f"parameter {binding.name!r} is incompatible with input {input_name!r}",
                    )
                )
            continue
        source_node = by_key.get(binding.node_key)
        if source_node is None:
            issues.append(
                GraphIssue(
                    "unknown_reference_node",
                    binding_location,
                    f"reference node {binding.node_key!r} does not exist",
                )
            )
            continue
        if binding.node_key not in node.dependencies:
            issues.append(
                GraphIssue(
                    "reference_not_dependency",
                    binding_location,
                    f"reference node {binding.node_key!r} must be a direct dependency",
                )
            )
        source_descriptor = descriptors.get(binding.node_key)
        if source_descriptor is None:
            issues.append(
                GraphIssue(
                    "untyped_reference_source",
                    binding_location,
                    "node references may only read typed tool outputs",
                )
            )
            continue
        output_schema = source_descriptor.output_model.model_json_schema()
        source_schema = _schema_at_path(output_schema, binding.reference_path)
        if source_schema is None:
            issues.append(
                GraphIssue(
                    "unknown_output_path",
                    binding_location,
                    f"output path {binding.reference_path!r} does not exist",
                )
            )
        elif not _schemas_compatible(source_schema, output_schema, destination, input_schema):
            issues.append(
                GraphIssue(
                    "binding_type_mismatch",
                    binding_location,
                    f"output path {binding.reference_path!r} is incompatible with {input_name!r}",
                )
            )


def validate_graph(
    graph: RecipeGraph,
    *,
    parameter_schema: Mapping[str, object],
    tool_catalog: ToolDescriptorCatalog,
    max_nodes: int,
    max_depth: int,
    max_fanout: int,
    execution_requirements: Sequence[PinRequest] = (),
) -> GraphValidation:
    """Return every graph defect in one deterministic report."""
    issues = _topological_issues(graph.nodes)
    graph_payload = graph.model_dump(mode="json", exclude_none=False)
    for location in _body_locations(graph_payload):
        issues.append(GraphIssue("raw_body_key", location, "raw body content is forbidden"))
    if parameter_schema.get("type") != "object":
        issues.append(
            GraphIssue("parameter_schema", "parameter_schema", "parameter schema must be an object")
        )
    if len(graph.nodes) > max_nodes:
        issues.append(
            GraphIssue(
                "node_ceiling",
                "graph",
                f"declared nodes {len(graph.nodes)} exceed max_nodes {max_nodes}",
            )
        )

    by_key = {node.node_key: node for node in graph.nodes}
    descriptors: dict[str, ToolDescriptor] = {}
    expanded_nodes = (
        len(graph.nodes)
        + sum(
            node.max_items * len(node.template) for node in graph.nodes if isinstance(node, MapNode)
        )
        + sum(node.max_children for node in graph.nodes if isinstance(node, GateNode))
    )
    if expanded_nodes > max_nodes:
        issues.append(
            GraphIssue(
                "node_ceiling",
                "graph",
                f"bounded expansion {expanded_nodes} exceeds max_nodes {max_nodes}",
            )
        )

    execution_pin_kinds = {item.kind for item in execution_requirements}
    execution_tool_pins = {
        (item.key, item.version) for item in execution_requirements if item.kind == "tool"
    }
    for node in graph.nodes:
        location = f"graph.{node.node_key}"
        if isinstance(node, ToolNode):
            if node.tool_address not in graph.tool_allowlist:
                issues.append(
                    GraphIssue(
                        "tool_not_allowed",
                        location,
                        f"{node.tool_address} is absent from the tool allowlist",
                    )
                )
            descriptor = _descriptor_or_issue(
                catalog=tool_catalog, node=node, location=location, issues=issues
            )
            if descriptor is not None:
                descriptors[node.node_key] = descriptor
                node_pin_kinds = execution_pin_kinds | {item.kind for item in node.requirements}
                node_tool_pins = execution_tool_pins | {
                    (item.key, item.version) for item in node.requirements if item.kind == "tool"
                }
                if (node.tool_name, node.tool_version) not in node_tool_pins:
                    issues.append(
                        GraphIssue(
                            "missing_tool_pin",
                            location,
                            f"{node.tool_address} has no exact compatibility pin",
                        )
                    )
                for pin_kind in sorted(set(descriptor.pin_requirements) - node_pin_kinds):
                    issues.append(
                        GraphIssue(
                            "missing_tool_requirement",
                            location,
                            f"{node.tool_address} requires pin kind {pin_kind!r}",
                        )
                    )
        elif isinstance(node, GateNode):
            if node.authority not in graph.authority_allowlist:
                issues.append(
                    GraphIssue(
                        "authority_not_allowed",
                        location,
                        f"authority {node.authority!r} is absent from the authority allowlist",
                    )
                )
            node_pin_kinds = execution_pin_kinds | {item.kind for item in node.requirements}
            node_tool_pins = execution_tool_pins | {
                (item.key, item.version) for item in node.requirements if item.kind == "tool"
            }
            for address in node.dynamic_tool_allowlist:
                if address not in graph.tool_allowlist:
                    issues.append(
                        GraphIssue(
                            "tool_not_allowed",
                            location,
                            f"{address} is absent from the tool allowlist",
                        )
                    )
                    continue
                name, separator, version = address.rpartition("@")
                if not separator or not name or not version:
                    issues.append(
                        GraphIssue(
                            "invalid_tool_address",
                            location,
                            f"{address!r} is not an exact tool address",
                        )
                    )
                    continue
                try:
                    descriptor = tool_catalog.descriptor(name, version)
                except Exception as exc:
                    issues.append(GraphIssue("unknown_tool", location, str(exc)))
                    continue
                if not descriptor.recipe_safe:
                    issues.append(
                        GraphIssue(
                            "tool_not_recipe_safe",
                            location,
                            f"{address} is not recipe-safe",
                        )
                    )
                if (name, version) not in node_tool_pins:
                    issues.append(
                        GraphIssue(
                            "missing_tool_pin",
                            location,
                            f"{address} has no exact compatibility pin",
                        )
                    )
                available_pin_kinds = node_pin_kinds | set(node.dynamic_pin_kinds)
                for pin_kind in sorted(set(descriptor.pin_requirements) - available_pin_kinds):
                    issues.append(
                        GraphIssue(
                            "missing_tool_requirement",
                            location,
                            f"{address} requires pin kind {pin_kind!r}",
                        )
                    )
        elif isinstance(node, ActivityNode):
            if node.activity_address not in graph.activity_allowlist:
                issues.append(
                    GraphIssue(
                        "activity_not_allowed",
                        location,
                        f"{node.activity_address} is absent from the activity allowlist",
                    )
                )
        elif isinstance(node, MapNode):
            if node.max_items > max_fanout:
                issues.append(
                    GraphIssue(
                        "fanout_ceiling",
                        location,
                        f"map max_items {node.max_items} exceeds max_fanout {max_fanout}",
                    )
                )
            if max_depth < 2:
                issues.append(
                    GraphIssue(
                        "depth_ceiling",
                        location,
                        "a map template requires max_depth of at least 2",
                    )
                )
            issues.extend(_topological_issues(node.template, prefix=f"{location}.template"))

    for node in graph.nodes:
        if isinstance(node, ToolNode) and node.node_key in descriptors:
            _validate_tool_bindings(
                node=node,
                descriptor=descriptors[node.node_key],
                by_key=by_key,
                descriptors=descriptors,
                parameter_schema=parameter_schema,
                local_parameters={},
                issues=issues,
                location=f"graph.{node.node_key}",
            )
        elif isinstance(node, MapNode):
            source_schema: Mapping[str, object] | None = None
            source_root: Mapping[str, object] = parameter_schema
            if isinstance(node.source, ParameterBinding):
                properties = parameter_schema.get("properties")
                if isinstance(properties, Mapping):
                    candidate = properties.get(node.source.name)
                    source_schema = candidate if isinstance(candidate, Mapping) else None
                if source_schema is None:
                    issues.append(
                        GraphIssue(
                            "unknown_parameter",
                            f"graph.{node.node_key}.source",
                            f"parameter {node.source.name!r} is not declared",
                        )
                    )
            elif isinstance(node.source, NodeReferenceBinding):
                source_node = by_key.get(node.source.node_key)
                if source_node is None:
                    issues.append(
                        GraphIssue(
                            "unknown_reference_node",
                            f"graph.{node.node_key}.source",
                            f"reference node {node.source.node_key!r} does not exist",
                        )
                    )
                if node.source.node_key not in node.dependencies:
                    issues.append(
                        GraphIssue(
                            "reference_not_dependency",
                            f"graph.{node.node_key}.source",
                            f"reference node {node.source.node_key!r} must be a direct dependency",
                        )
                    )
                source_descriptor = descriptors.get(node.source.node_key)
                if source_descriptor is not None:
                    output_schema = source_descriptor.output_model.model_json_schema()
                    source_schema = _schema_at_path(output_schema, node.source.reference_path)
                    source_root = output_schema
                    if source_schema is None:
                        issues.append(
                            GraphIssue(
                                "unknown_output_path",
                                f"graph.{node.node_key}.source",
                                f"output path {node.source.reference_path!r} does not exist",
                            )
                        )
                elif source_node is not None:
                    issues.append(
                        GraphIssue(
                            "untyped_reference_source",
                            f"graph.{node.node_key}.source",
                            "map references may only read typed tool outputs",
                        )
                    )
            elif isinstance(node.source, LiteralBinding):
                source_schema = {"type": _literal_types(node.source.value)}
                source_root = source_schema
            if source_schema is None or "array" not in _schema_types(source_schema, source_root):
                issues.append(
                    GraphIssue(
                        "map_source_not_array",
                        f"graph.{node.node_key}.source",
                        "map source must resolve to a typed array",
                    )
                )
                continue
            resolved_source = _resolve_ref(source_schema, source_root)
            items = resolved_source.get("items")
            item_schema = items if isinstance(items, Mapping) else {}
            template_by_key = {item.node_key: item for item in node.template}
            template_descriptors: dict[str, ToolDescriptor] = {}
            for template_node in node.template:
                template_location = f"graph.{node.node_key}.template.{template_node.node_key}"
                if isinstance(template_node, ToolNode):
                    if template_node.tool_address not in graph.tool_allowlist:
                        issues.append(
                            GraphIssue(
                                "tool_not_allowed",
                                template_location,
                                f"{template_node.tool_address} is absent from the tool allowlist",
                            )
                        )
                    descriptor = _descriptor_or_issue(
                        catalog=tool_catalog,
                        node=template_node,
                        location=template_location,
                        issues=issues,
                    )
                    if descriptor is not None:
                        template_descriptors[template_node.node_key] = descriptor
                        template_pin_kinds = execution_pin_kinds | {
                            item.kind for item in node.requirements + template_node.requirements
                        }
                        template_tool_pins = execution_tool_pins | {
                            (item.key, item.version)
                            for item in node.requirements + template_node.requirements
                            if item.kind == "tool"
                        }
                        if (
                            template_node.tool_name,
                            template_node.tool_version,
                        ) not in template_tool_pins:
                            issues.append(
                                GraphIssue(
                                    "missing_tool_pin",
                                    template_location,
                                    f"{template_node.tool_address} has no exact compatibility pin",
                                )
                            )
                        for pin_kind in sorted(
                            set(descriptor.pin_requirements) - template_pin_kinds
                        ):
                            issues.append(
                                GraphIssue(
                                    "missing_tool_requirement",
                                    template_location,
                                    f"{template_node.tool_address} requires pin kind {pin_kind!r}",
                                )
                            )
                elif isinstance(template_node, GateNode):
                    if template_node.authority not in graph.authority_allowlist:
                        issues.append(
                            GraphIssue(
                                "authority_not_allowed",
                                template_location,
                                f"authority {template_node.authority!r} is not allowed",
                            )
                        )
                elif isinstance(template_node, ActivityNode):
                    if template_node.activity_address not in graph.activity_allowlist:
                        issues.append(
                            GraphIssue(
                                "activity_not_allowed",
                                template_location,
                                f"{template_node.activity_address} is not allowed",
                            )
                        )
            for template_node in node.template:
                if (
                    isinstance(template_node, ToolNode)
                    and template_node.node_key in template_descriptors
                ):
                    _validate_tool_bindings(
                        node=template_node,
                        descriptor=template_descriptors[template_node.node_key],
                        by_key=template_by_key,
                        descriptors=template_descriptors,
                        parameter_schema=parameter_schema,
                        local_parameters={node.item_parameter: (item_schema, source_root)},
                        issues=issues,
                        location=f"graph.{node.node_key}.template.{template_node.node_key}",
                    )

    ordered_issues = tuple(
        sorted(issues, key=lambda item: (item.location, item.code, item.message))
    )
    return GraphValidation(
        graph_sha256=canonical_sha256(graph),
        issues=ordered_issues,
    )


def node_requirements(graph: RecipeGraph) -> dict[str, tuple[PinRequest, ...]]:
    result: dict[str, tuple[PinRequest, ...]] = {}
    for node in graph.nodes:
        requirements = list(node.requirements)
        if isinstance(node, MapNode):
            for template_node in node.template:
                requirements.extend(template_node.requirements)
        if requirements:
            result[node.node_key] = tuple(requirements)
    return result


__all__ = [
    "ActivityNode",
    "BarrierNode",
    "Binding",
    "GateNode",
    "GateResumeCondition",
    "GraphIssue",
    "GraphNode",
    "GraphValidation",
    "LiteralBinding",
    "MapNode",
    "NodeReferenceBinding",
    "ParameterBinding",
    "RecipeGraph",
    "ToolDescriptorCatalog",
    "ToolNode",
    "canonical_sha256",
    "node_requirements",
    "validate_graph",
]
