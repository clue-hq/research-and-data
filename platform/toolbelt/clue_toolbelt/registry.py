"""Version-aware tool registry with an explicit default alias per name."""

from __future__ import annotations

from clue_toolbelt.envelope import Tool, ToolDescriptor
from clue_toolbelt.errors import UnknownTool

__all__ = ["ToolRegistry"]


class ToolRegistry:
    """An exact ``(name, version)`` registry plus explicitly composed default aliases.

    Exact recipe resolution never floats. Name-only HTTP callers resolve the one version that the
    composition root deliberately marks as default; registration order or lexical version sorting
    never chooses it.
    """

    def __init__(self) -> None:
        self._tools: dict[tuple[str, str], Tool] = {}
        self._defaults: dict[str, str] = {}

    def register(self, tool: Tool, *, make_default: bool) -> None:
        """Register one exact implementation and optionally claim its name-only alias."""
        descriptor = tool.descriptor
        key = (descriptor.name, descriptor.version)
        if key in self._tools:
            prior = self._tools[key]
            raise ValueError(
                f"tool {descriptor.address!r} is already registered "
                f"({type(prior).__name__}); duplicate registration is a wiring bug"
            )
        if make_default and descriptor.name in self._defaults:
            prior_version = self._defaults[descriptor.name]
            raise ValueError(
                f"tool {descriptor.name!r} already has default version {prior_version!r}; "
                "multiple default aliases are a wiring bug"
            )
        self._tools[key] = tool
        if make_default:
            self._defaults[descriptor.name] = descriptor.version

    def get(self, name: str, version: str | None = None) -> Tool:
        """Resolve an exact version or the explicitly composed default alias."""
        resolved_version = version if version is not None else self._defaults.get(name)
        if resolved_version is None:
            raise UnknownTool(name, version=version)
        try:
            return self._tools[(name, resolved_version)]
        except KeyError:
            raise UnknownTool(name, version=resolved_version) from None

    def descriptor(self, name: str, version: str | None = None) -> ToolDescriptor:
        return self.get(name, version).descriptor

    def has(self, name: str, version: str | None = None) -> bool:
        """Whether an exact version or name-only default alias is available."""
        if version is not None:
            return (name, version) in self._tools
        return name in self._defaults

    def names(self) -> tuple[str, ...]:
        """Default-addressable names, sorted."""
        return tuple(sorted(self._defaults))

    def versions(self, name: str) -> tuple[str, ...]:
        """All registered versions for ``name``, sorted for display only."""
        return tuple(sorted(version for tool_name, version in self._tools if tool_name == name))

    def tools(self) -> tuple[Tool, ...]:
        """Default tools, ordered by name."""
        return tuple(self.get(name) for name in self.names())

    def descriptors(self) -> tuple[ToolDescriptor, ...]:
        """Default descriptors, ordered by name."""
        return tuple(tool.descriptor for tool in self.tools())

    def all_descriptors(self) -> tuple[ToolDescriptor, ...]:
        """Every exact descriptor, ordered by address for deterministic inspection."""
        return tuple(
            self._tools[key].descriptor for key in sorted(self._tools, key=lambda item: item)
        )

    def __len__(self) -> int:
        return len(self._tools)

    def __contains__(self, name: object) -> bool:
        return isinstance(name, str) and name in self._defaults
