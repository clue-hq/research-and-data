"""Compatibility exports for the shared production memory composition."""

from clue_api.memory_wiring import (
    TransactionalMemoryAssembly,
    memory_assembly_factory,
    memory_write_factory_builder,
)

__all__ = [
    "TransactionalMemoryAssembly",
    "memory_assembly_factory",
    "memory_write_factory_builder",
]
