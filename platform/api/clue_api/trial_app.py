"""Feature-gated local HTTP routes for the Sumble-only Clue Trial."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Header, HTTPException

from clue_api.trial.coordinator import (
    AccountInput,
    ClueTrialCoordinator,
    CreateTrialInput,
    ResearchInput,
    TrialIdempotencyConflict,
    TrialReadinessOverrideRequired,
    TurnInput,
)
from clue_core import ResolverError

IdempotencyKey = Annotated[str, Header(alias="Idempotency-Key", min_length=1)]


def _http_error(exc: Exception) -> HTTPException:
    if isinstance(exc, FileNotFoundError):
        return HTTPException(status_code=404, detail=str(exc))
    if isinstance(exc, TrialIdempotencyConflict):
        return HTTPException(status_code=409, detail=str(exc))
    if isinstance(exc, TrialReadinessOverrideRequired):
        return HTTPException(
            status_code=409,
            detail={
                "code": "readiness_override_required",
                "message": str(exc),
                "reason_codes": list(exc.reason_codes),
            },
        )
    if isinstance(exc, ResolverError):
        # Preserve the provider's 402 meaning even though the shared resolver taxonomy deliberately
        # abstracts most HTTP statuses. No Authorization header/body is ever included here.
        status = 402 if "HTTP 402" in str(exc) else 502
        return HTTPException(
            status_code=status,
            detail={"code": type(exc).__name__, "message": str(exc)},
        )
    if isinstance(exc, (ValueError, RuntimeError)):
        return HTTPException(status_code=422, detail=str(exc))
    return HTTPException(status_code=500, detail=type(exc).__name__)


def create_trial_router(coordinator: ClueTrialCoordinator) -> APIRouter:
    """Build the local canary router over an injected coordinator."""

    router = APIRouter(prefix="/v1", tags=["clue-trial"])

    async def mutation(
        *,
        trial_id: str,
        route: str,
        key: str,
        body: dict[str, Any],
        operation: Callable[[], Awaitable[dict[str, Any]]],
    ) -> dict[str, Any]:
        try:
            return await coordinator.execute_idempotent(
                trial_id=trial_id,
                route=route,
                key=key,
                body=body,
                operation=operation,
            )
        except Exception as exc:
            raise _http_error(exc) from exc

    @router.get("/trial/doctor")
    async def doctor() -> dict[str, Any]:
        return await coordinator.doctor()

    @router.post("/trials")
    async def create_trial(
        body: CreateTrialInput,
        idempotency_key: IdempotencyKey,
    ) -> dict[str, Any]:
        try:
            return await coordinator.create(body, key=idempotency_key)
        except Exception as exc:
            raise _http_error(exc) from exc

    @router.get("/trials/{trial_id}")
    async def get_trial(trial_id: str) -> dict[str, Any]:
        try:
            return await coordinator.get(trial_id)
        except Exception as exc:
            raise _http_error(exc) from exc

    @router.post("/trials/{trial_id}/turns")
    async def run_turn(
        trial_id: str,
        body: TurnInput,
        idempotency_key: IdempotencyKey,
    ) -> dict[str, Any]:
        return await mutation(
            trial_id=trial_id,
            route="clue_trial.turn",
            key=idempotency_key,
            body=body.model_dump(mode="json"),
            operation=lambda: coordinator.turn(trial_id, body),
        )

    @router.post("/trials/{trial_id}/product:confirm")
    async def confirm_product(
        trial_id: str,
        idempotency_key: IdempotencyKey,
    ) -> dict[str, Any]:
        return await mutation(
            trial_id=trial_id,
            route="clue_trial.product_confirm",
            key=idempotency_key,
            body={},
            operation=lambda: coordinator.confirm_product(trial_id),
        )

    @router.post("/trials/{trial_id}/icps:synthesize")
    async def synthesize_icps(
        trial_id: str,
        idempotency_key: IdempotencyKey,
    ) -> dict[str, Any]:
        return await mutation(
            trial_id=trial_id,
            route="clue_trial.icps_synthesize",
            key=idempotency_key,
            body={},
            operation=lambda: coordinator.synthesize_icps(trial_id),
        )

    @router.post("/trials/{trial_id}/icps/{proposal}:confirm")
    async def confirm_icp(
        trial_id: str,
        proposal: int,
        idempotency_key: IdempotencyKey,
    ) -> dict[str, Any]:
        return await mutation(
            trial_id=trial_id,
            route="clue_trial.icp_confirm",
            key=idempotency_key,
            body={"proposal": proposal},
            operation=lambda: coordinator.confirm_icp(trial_id, proposal),
        )

    @router.post("/trials/{trial_id}/accounts")
    async def add_account(
        trial_id: str,
        body: AccountInput,
        idempotency_key: IdempotencyKey,
    ) -> dict[str, Any]:
        return await mutation(
            trial_id=trial_id,
            route="clue_trial.account_add",
            key=idempotency_key,
            body=body.model_dump(mode="json"),
            operation=lambda: coordinator.add_account(trial_id, body),
        )

    @router.post("/trials/{trial_id}/accounts/{account_id}:research")
    async def research_account(
        trial_id: str,
        account_id: UUID,
        body: ResearchInput,
        idempotency_key: IdempotencyKey,
    ) -> dict[str, Any]:
        return await mutation(
            trial_id=trial_id,
            route="clue_trial.account_research",
            key=idempotency_key,
            body={"account_id": str(account_id), **body.model_dump(mode="json")},
            operation=lambda: coordinator.research(trial_id, account_id, body),
        )

    @router.get("/trials/{trial_id}/events")
    async def get_events(trial_id: str) -> dict[str, Any]:
        try:
            return await coordinator.events(trial_id)
        except Exception as exc:
            raise _http_error(exc) from exc

    @router.get("/trials/{trial_id}/cost")
    async def get_cost(trial_id: str) -> dict[str, Any]:
        try:
            return await coordinator.cost(trial_id)
        except Exception as exc:
            raise _http_error(exc) from exc

    @router.get("/trials/{trial_id}/report")
    async def get_report(trial_id: str) -> dict[str, Any]:
        try:
            return await coordinator.report(trial_id)
        except Exception as exc:
            raise _http_error(exc) from exc

    return router


__all__ = ["create_trial_router"]
