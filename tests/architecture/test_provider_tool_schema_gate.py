"""Fail-closed gate: every model-bound tool schema must fit the provider JSON-schema subset.

All bound tool schemas are sent together in every agent request, so one incompatible schema
returns HTTP 400 before the model runs and blocks every turn for that role. The gate therefore
runs over every active role profile, not just the tool that last regressed.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

from langchain_core.utils.function_calling import convert_to_openai_tool

from clue_api.agent_registry_wiring import C6_ACTIVE_PROFILE_VERSIONS, build_agent_profile_registry
from clue_api.toolbelt_wiring import build_toolbelt
from clue_config import Settings
from clue_gateway.agent_model import (
    provider_compatible_tool_schema,
    unsupported_schema_pattern,
)


def _bound_tool_schemas() -> list[tuple[str, str, dict[str, Any]]]:
    registry = build_toolbelt(storage=None, gateway=None, settings=Settings(_env_file=None))
    profiles = build_agent_profile_registry(registry)
    return [
        (
            role.value,
            pin.address,
            provider_compatible_tool_schema(
                convert_to_openai_tool(registry.descriptor(pin.name, pin.version).input_model)
            ),
        )
        for role in C6_ACTIVE_PROFILE_VERSIONS
        for pin in profiles.resolve(role).profile.tools
    ]


def _patterns(node: Any) -> Iterator[str]:
    if isinstance(node, dict):
        for key, value in node.items():
            if key == "pattern" and isinstance(value, str):
                yield value
            else:
                yield from _patterns(value)
    elif isinstance(node, list):
        for item in node:
            yield from _patterns(item)


def test_every_active_profile_tool_schema_fits_the_provider_regex_subset() -> None:
    schemas = _bound_tool_schemas()
    assert schemas, "no active profile bound any tool"

    offenders = [
        (role, address, pattern)
        for role, address, schema in schemas
        for pattern in _patterns(schema)
        if unsupported_schema_pattern(pattern)
    ]

    assert offenders == []


def test_every_active_profile_tool_exposes_an_object_parameter_schema() -> None:
    for role, address, schema in _bound_tool_schemas():
        parameters = schema["function"]["parameters"]
        assert parameters["type"] == "object", f"{role}:{address}"
