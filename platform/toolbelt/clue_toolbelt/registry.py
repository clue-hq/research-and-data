"""The tool registry — register / get / list, duplicate registration fails loud.

The single lookup surface the runner resolves a tool name against. Registration is **loud on
collision** (a second tool under the same name is a ``ValueError`` at composition time, not a
last-write-wins silent shadow — the same discipline the phase registry and the source registry
follow): two capabilities fighting over one name is a wiring bug, caught at the root, never in
production. The registry is populated at the ``clue_api`` composition root
(:mod:`clue_api.toolbelt_wiring`); ``clue_toolbelt`` ships only the empty container."""

from __future__ import annotations

from clue_toolbelt.envelope import Tool
from clue_toolbelt.errors import UnknownTool

__all__ = ["ToolRegistry"]


class ToolRegistry:
    """A name → :class:`~clue_toolbelt.Tool` map with loud duplicate detection."""

    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        """Register ``tool`` under its ``name``. Raises :class:`ValueError` if the name is already
        taken (duplicate registration is a composition bug — never last-write-wins)."""
        name = tool.name
        if name in self._tools:
            raise ValueError(
                f"tool {name!r} is already registered "
                f"({type(self._tools[name]).__name__}); duplicate registration is a wiring bug"
            )
        self._tools[name] = tool

    def get(self, name: str) -> Tool:
        """Resolve ``name`` to its tool, or raise :class:`~clue_toolbelt.errors.UnknownTool`."""
        try:
            return self._tools[name]
        except KeyError:
            raise UnknownTool(name) from None

    def has(self, name: str) -> bool:
        """Whether ``name`` is registered."""
        return name in self._tools

    def names(self) -> tuple[str, ...]:
        """The registered tool names, sorted — the coverage surface the out-of-order matrix test
        asserts against (a new tool without a matrix entry is caught by comparing to this)."""
        return tuple(sorted(self._tools))

    def tools(self) -> tuple[Tool, ...]:
        """The registered tools, ordered by name."""
        return tuple(self._tools[name] for name in self.names())

    def __len__(self) -> int:
        return len(self._tools)

    def __contains__(self, name: object) -> bool:
        return isinstance(name, str) and name in self._tools
