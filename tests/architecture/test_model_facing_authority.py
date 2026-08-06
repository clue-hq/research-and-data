"""Fail-closed gate: trusted authority never appears in a model-facing tool schema, at any depth.

``MODEL_FORBIDDEN_AUTHORITY_KEYS`` names the scope authority of the execution a constitution
governs — ``workspace_id``, ``project_id``, ``brand_id``, ``client_entity_id``, the ids. The seam
that enforces it (``_with_trusted_runtime`` + ``_trusted_tool_arguments``) works on the **top
level** of a tool's input model, so before PC-C8 task 1.4 a name one level down inside a sub-model
was neither hidden from the model nor served from the constitution: ``propose_field``/
``propose_source`` exposed ``scope.brand_id``/``scope.project_id`` and ``submit_ingestion`` exposed
``declared_context.*``. Task 1.4 hoisted those fields onto the tool inputs, which is only a durable
fix if nothing can nest one again.

This is that guarantee, mechanized. The 1.3 review found the three exceptions by walking the tool
list by hand; this walks it on every build, at every depth, over the exact schema the provider is
sent (post trusted-runtime strip, post provider transform, ``$defs`` resolved).
"""

from __future__ import annotations

from collections.abc import Iterator
from copy import deepcopy
from typing import Any

from langchain_core.tools import StructuredTool
from langchain_core.utils.function_calling import convert_to_openai_tool

from clue_agents.contracts import MODEL_FORBIDDEN_AUTHORITY_KEYS
from clue_api.agent_registry_wiring import c6_roles_for_tool
from clue_api.agent_runtime_wiring import _with_trusted_runtime
from clue_api.toolbelt_wiring import build_toolbelt
from clue_config import Settings
from clue_gateway.agent_model import provider_compatible_tool_schema
from clue_toolbelt import ToolRegistry


def _model_facing_schema(registry: ToolRegistry, name: str, version: str) -> dict[str, Any]:
    """Reproduce exactly what ``agent_runtime_wiring`` binds and the provider receives."""

    descriptor = registry.descriptor(name, version)
    args_schema = _with_trusted_runtime(
        descriptor.input_model,
        name=f"{descriptor.input_model.__name__}AgentRuntime",
    )

    async def invoke(**kwargs: Any) -> str:  # pragma: no cover - never called
        raise AssertionError("schema probe")

    tool = StructuredTool.from_function(
        coroutine=invoke,
        name=descriptor.name,
        description=f"probe {descriptor.address}",
        args_schema=args_schema,
    )
    return provider_compatible_tool_schema(convert_to_openai_tool(tool))


def _property_paths(node: Any, prefix: tuple[str, ...] = ()) -> Iterator[tuple[str, ...]]:
    """Yield every property path in a JSON schema, descending through every container form.

    Deliberately structural rather than schema-aware: ``properties``/``items``/``$defs``/
    ``anyOf``/``allOf``/``oneOf``/``prefixItems``/``additionalProperties`` are all walked, so a
    forbidden name cannot hide behind a union member or a nested definition. Only ``properties``
    contributes a path segment; the rest are transparent.
    """

    if isinstance(node, dict):
        for name, child in node.get("properties", {}).items():
            path = (*prefix, name)
            yield path
            yield from _property_paths(child, path)
        for key, child in node.items():
            if key == "properties":
                continue
            yield from _property_paths(child, prefix)
    elif isinstance(node, list):
        for item in node:
            yield from _property_paths(item, prefix)


def test_no_model_facing_tool_schema_carries_trusted_authority_at_any_depth() -> None:
    registry = build_toolbelt(storage=None, gateway=None, settings=Settings(_env_file=None))
    registered_descriptors = tuple(registry.all_descriptors())
    assert registered_descriptors, "the toolbelt registered no tools"

    # The toolbelt is also the backend registry for human-only steering operations. Those
    # operations deliberately carry authenticated scope in their request bodies and are never
    # admitted to an agent role. Mirror the live agent-catalog composition here: only an address
    # with at least one admitted role can cross the model boundary. The separate exhaustive C6
    # authority audit proves that every registered address has an explicit authority decision, so
    # an unclassified tool cannot disappear from this gate by omission.
    descriptors = tuple(
        descriptor for descriptor in registered_descriptors if c6_roles_for_tool(descriptor.address)
    )
    assert descriptors, "the live authority composition admitted no model-facing tools"

    offenders = sorted(
        f"{descriptor.address}: {'.'.join(path)}"
        for descriptor in descriptors
        for path in _property_paths(
            _model_facing_schema(registry, descriptor.name, descriptor.version)
        )
        if path[-1] in MODEL_FORBIDDEN_AUTHORITY_KEYS
    )
    assert offenders == []


def test_the_walk_actually_descends_into_nested_definitions() -> None:
    """Guard the guard: a structural walk that silently stopped at depth 1 would pass forever.

    Observing that *some* nested path exists is weaker than it looks — a walk could find the paths
    it happens to reach and still miss the container form a future tool uses. So this plants a real
    forbidden name inside a `$defs` sub-model of a real tool schema and asserts the walk catches it
    exactly where it was planted. The gate above is only as good as this.
    """

    registry = build_toolbelt(storage=None, gateway=None, settings=Settings(_env_file=None))
    schema = _model_facing_schema(registry, "submit_ingestion", "1")
    paths = set(_property_paths(schema))

    assert ("declared_context",) in paths
    assert ("declared_context", "document_context") in paths

    planted = deepcopy(schema)
    nested = planted["function"]["parameters"]["properties"]["declared_context"]
    assert isinstance(nested, dict)
    # Depth 2, through `properties`.
    nested["properties"]["project_id"] = {"type": "string"}
    # Depth 3, through an `items` container — a different code path in the walk, and the one a
    # list-of-sub-models tool would use.
    nested["properties"]["targets"]["items"]["properties"]["workspace_id"] = {"type": "string"}

    caught = sorted(
        ".".join(path)
        for path in _property_paths(planted)
        if path[-1] in MODEL_FORBIDDEN_AUTHORITY_KEYS
    )
    assert caught == [
        "declared_context.project_id",
        "declared_context.targets.workspace_id",
    ]
