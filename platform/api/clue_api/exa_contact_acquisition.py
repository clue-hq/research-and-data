"""Selected-contact Exa acquisition over the shared external-research ledger (M8C C4)."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from contextlib import AbstractAsyncContextManager
from datetime import datetime

from pydantic import BaseModel, ConfigDict
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_api.exa_contact_compiler import compile_registered_exa_contact_plan
from clue_api.exa_deep_acquisition import (
    ExaDeepAcquisitionCoordinator,
    ExaDeepAcquisitionResult,
    ExaDeepBeforeDispatch,
)
from clue_core import ContactResearchIntent, ContactResearchPolicyPin
from clue_research.resolvers.exa import DEFAULT_EXA_CONFIG, ExaDeepConfig


class ExaDeepContactAcquisitionBatchResult(BaseModel):
    """Durable outcomes for every provider-safe bundle of one exact selected contact."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    intent_sha256: str
    results: tuple[ExaDeepAcquisitionResult, ...]

    @property
    def provider_calls(self) -> int:
        return sum(result.provider_calls for result in self.results)


class ExaDeepContactAcquisitionService:
    """Compile under database authority, then dispatch only after that transaction closes."""

    def __init__(
        self,
        *,
        coordinator: ExaDeepAcquisitionCoordinator,
        conn_factory: Callable[[], AbstractAsyncContextManager[AsyncConnection]],
    ) -> None:
        self._coordinator = coordinator
        self._conn_factory = conn_factory

    async def acquire_intent(
        self,
        *,
        intent: ContactResearchIntent,
        effective_policy: ContactResearchPolicyPin,
        observation_window: str,
        start_published_date: datetime | None = None,
        end_published_date: datetime | None = None,
        config: ExaDeepConfig = DEFAULT_EXA_CONFIG,
        before_dispatch: ExaDeepBeforeDispatch | None = None,
        field_keys: Sequence[str] | None = None,
        directional_questions: Sequence[str] | None = None,
        reuse_context_ref: str | None = None,
    ) -> ExaDeepContactAcquisitionBatchResult:
        """Acquire only a database-proven selected intent; a rejected compile makes zero calls."""

        async with self._conn_factory() as conn:
            plan = await compile_registered_exa_contact_plan(
                conn,
                intent=intent,
                effective_policy=effective_policy,
                observation_window=observation_window,
                start_published_date=start_published_date,
                end_published_date=end_published_date,
                config=config,
                field_keys=field_keys,
                directional_questions=directional_questions,
                reuse_context_ref=reuse_context_ref,
            )

        # This loop is deliberately outside the compiler/claim transaction. Each coordinator call
        # uses short reserve/settlement transactions around one external HTTP request.
        results: list[ExaDeepAcquisitionResult] = []
        for bundle in plan.bundles:
            results.append(await self._coordinator.acquire(bundle, before_dispatch=before_dispatch))
        return ExaDeepContactAcquisitionBatchResult(
            intent_sha256=plan.intent_sha256,
            results=tuple(results),
        )


__all__ = [
    "ExaDeepContactAcquisitionBatchResult",
    "ExaDeepContactAcquisitionService",
]
