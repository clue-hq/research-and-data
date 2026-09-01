"""Pure R6 composition guards: run-scoped factories only, never static production maps."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence
from typing import Any, cast
from uuid import UUID, uuid4

import pytest

from clue_agents import AgentModelProvider
from clue_agents.contracts import ModelPolicy
from clue_api.account_entity_research_composition import StaticAccountResearchProviderActions
from clue_api.account_research_fleet_composition import (
    RunScopedAccountResearchProviderActions,
    build_account_research_fleet_composition,
)
from clue_api.entity_research_tools import (
    ProviderActionBinding,
    ProviderOperationObservation,
    ProviderOperationReservation,
    ProviderResearchProjectionDraft,
)
from clue_core.entity_research import GovernedResearchToolRequest
from clue_fleet import EntityResearchJobRow
from clue_storage import FsStorage
from tests.db.conftest import run_async


class _Action:
    async def execute(
        self,
        request: GovernedResearchToolRequest,
        *,
        before_dispatch: Callable[
            [ProviderOperationReservation], Awaitable[ProviderOperationObservation]
        ],
        settle_terminal: Callable[
            [ProviderOperationReservation], Awaitable[ProviderOperationObservation]
        ],
    ) -> Sequence[ProviderResearchProjectionDraft]:
        del request, before_dispatch, settle_terminal
        return ()


class _Factory:
    def __init__(self) -> None:
        self.calls: list[tuple[EntityResearchJobRow, UUID]] = []

    async def __call__(
        self,
        job: EntityResearchJobRow,
        *,
        account_run_id: UUID,
    ) -> ProviderActionBinding:
        self.calls.append((job, account_run_id))
        return ProviderActionBinding(action=_Action(), version=1)


class _Context:
    def __init__(self, account_run_id: UUID) -> None:
        self.value = account_run_id

    async def account_run_id(self, job: EntityResearchJobRow) -> UUID:
        del job
        return self.value


def test_run_scoped_provider_resolver_rebuilds_every_action_from_the_exact_job() -> None:
    async def scenario() -> None:
        deep = _Factory()
        enrichment = _Factory()
        committee = _Factory()
        account_run_id = uuid4()
        resolver = RunScopedAccountResearchProviderActions(
            deep=deep,
            enrichment=enrichment,
            committee=committee,
            contexts=_Context(account_run_id),
        )
        job = cast(EntityResearchJobRow, object())
        bindings = await resolver.resolve(job)
        assert set(bindings) == {
            "research_account_deep",
            "enrich_account",
            "discover_buying_committee",
        }
        assert deep.calls == enrichment.calls == committee.calls == [(job, account_run_id)]

    run_async(scenario())


def test_production_composition_rejects_the_r5_static_fixture_shortcut(tmp_path: Any) -> None:
    with pytest.raises(TypeError, match="cannot use static provider action bindings"):
        build_account_research_fleet_composition(
            storage=FsStorage(tmp_path / "r6-composition"),
            models=cast(AgentModelProvider, object()),
            provider_actions=StaticAccountResearchProviderActions({}),
            model_policy=ModelPolicy(
                model_id="r6-construction-only",
                timeout_s=1,
                max_retries=0,
                max_output_tokens=128,
                temperature=0,
            ),
        )
