"""Task-scoped resolver composition for ready external snapshots."""

from __future__ import annotations

import asyncio

import pytest

from clue_core import Claim, Entity, FieldDef, Resolver
from clue_research.sources import (
    NoResolverBoundError,
    bind_resolver,
    bind_resolver_overrides,
    clear_resolver_bindings,
    get_resolver,
)


class _Resolver:
    tier = 4

    def __init__(self, name: str) -> None:
        self.name = name

    def resolve(self, entity: Entity, field: FieldDef) -> list[Claim]:
        del entity, field
        return []


class _FalseyResolver(_Resolver):
    def __bool__(self) -> bool:
        return False


def test_override_is_nested_and_restores_the_process_binding() -> None:
    global_resolver = _Resolver("global")
    # Presence by exact key wins even if a provider adapter implements falsey state.
    outer = _FalseyResolver("outer")
    inner = _Resolver("inner")
    bind_resolver("exa_deep", global_resolver)
    try:
        with bind_resolver_overrides({"exa_deep": outer}):
            assert get_resolver("exa_deep") is outer
            with bind_resolver_overrides({"exa_deep": inner}):
                assert get_resolver("exa_deep") is inner
            assert get_resolver("exa_deep") is outer
        assert get_resolver("exa_deep") is global_resolver
    finally:
        clear_resolver_bindings()


def test_parallel_tasks_do_not_see_each_others_account_snapshot() -> None:
    async def run_one(resolver: _Resolver) -> Resolver:
        with bind_resolver_overrides({"exa_deep": resolver}):
            await asyncio.sleep(0)
            return get_resolver("exa_deep")

    async def scenario() -> None:
        first = _Resolver("account-one")
        second = _Resolver("account-two")
        observed = await asyncio.gather(run_one(first), run_one(second))
        assert observed[0] is first
        assert observed[1] is second
        with pytest.raises(NoResolverBoundError):
            get_resolver("exa_deep")

    asyncio.run(scenario())
