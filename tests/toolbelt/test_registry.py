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
    reg.register(echo)
    reg.register(other)
    assert reg.get("echo") is echo
    assert reg.names() == ("echo", "other")  # sorted
    assert "echo" in reg
    assert len(reg) == 2


def test_duplicate_registration_fails_loud() -> None:
    reg = ToolRegistry()
    reg.register(EchoTool())
    with pytest.raises(ValueError, match="already registered"):
        reg.register(EchoTool())  # same name -> loud, never last-write-wins


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
    reg.register(_New())
    assert "brand_new" in reg.names()
