"""The registry contract: register/get/list; duplicate registration + unknown lookup fail loud."""

from __future__ import annotations

import pytest

from clue_toolbelt import ToolRegistry, UnknownTool
from tests.toolbelt.conftest import EchoInput, EchoTool, Tool, ToolResult


class _Other(EchoTool):
    name = "other"


def test_register_get_and_list() -> None:
    reg = ToolRegistry()
    echo = EchoTool()
    other = _Other()
    reg.register(echo, make_default=True)
    reg.register(other, make_default=True)
    assert reg.get("echo") is echo
    assert reg.names() == ("echo", "other")  # sorted
    assert "echo" in reg
    assert len(reg) == 2


def test_duplicate_registration_fails_loud() -> None:
    reg = ToolRegistry()
    reg.register(EchoTool(), make_default=True)
    with pytest.raises(ValueError, match="already registered"):
        reg.register(EchoTool(), make_default=False)


def test_unknown_tool_is_typed() -> None:
    reg = ToolRegistry()
    with pytest.raises(UnknownTool) as ei:
        reg.get("nope")
    assert ei.value.name == "nope"


def test_names_is_the_coverage_surface() -> None:
    """A fresh tool is visible in ``names()`` — the surface the matrix test asserts full coverage
    against, so a new tool without a matrix entry is caught."""

    class _New(Tool):
        name = "brand_new"
        input_model = EchoInput

        async def invoke(self, inputs, ctx):  # type: ignore[no-untyped-def]
            return ToolResult(tool=self.name, version=self.version)

    reg = ToolRegistry()
    reg.register(_New(), make_default=True)
    assert "brand_new" in reg.names()


def test_exact_versions_and_explicit_default_do_not_float() -> None:
    class _EchoV2(EchoTool):
        version = "2"

    reg = ToolRegistry()
    v1 = EchoTool()
    v2 = _EchoV2()
    reg.register(v1, make_default=False)
    reg.register(v2, make_default=True)

    assert reg.get("echo") is v2
    assert reg.get("echo", "1") is v1
    assert reg.get("echo", "2") is v2
    assert reg.versions("echo") == ("1", "2")
    assert tuple(item.address for item in reg.all_descriptors()) == ("echo@1", "echo@2")


def test_multiple_default_aliases_fail_loud() -> None:
    class _EchoV2(EchoTool):
        version = "2"

    reg = ToolRegistry()
    reg.register(EchoTool(), make_default=True)
    with pytest.raises(ValueError, match="already has default version"):
        reg.register(_EchoV2(), make_default=True)


def test_version_without_default_is_not_name_addressable() -> None:
    reg = ToolRegistry()
    reg.register(EchoTool(), make_default=False)
    assert reg.get("echo", "1").version == "1"
    with pytest.raises(UnknownTool):
        reg.get("echo")
