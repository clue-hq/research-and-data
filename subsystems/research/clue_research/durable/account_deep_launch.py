"""Immutable authorization to launch one selected account-deep fleet (M8B O2).

A confirmed research directive describes executable intent; it does not authorize spend.  This
repository creates the separate, content-addressed launch receipt consumed by the DEEP phase.  The
receipt pins one project run, one directive version/digest, one explicit account subset, and the
human-approved cost envelope.  Re-entry is idempotent only for the exact same request.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid5

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_core import (
    EntityId,
    OperationId,
    ProjectPhase,
    ProjectRunId,
    ResearchDirectiveId,
    ResearchDirectivePin,
    ResearchDirectiveStatus,
    UtcDatetime,
)
from clue_research.directives import (
    ResearchDirectiveConflict,
    ResearchDirectiveInvalid,
    effective_account_research_directive,
    get_research_directive,
)
from clue_research.durable.enums import ProjectRunStatus
from clue_research.durable.project_run import get_project_run

_LAUNCH_NAMESPACE = UUID("ae69094d-cc02-5e63-a327-a17f0d4b51e0")


class AccountDeepLaunchError(RuntimeError):
    """Base typed refusal for an invalid or conflicting launch request."""


class AccountDeepLaunchConflict(AccountDeepLaunchError):
    pass


class AccountDeepLaunchInvalid(AccountDeepLaunchError):
    pass


class AccountDeepLaunchRow(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    id: UUID
    workspace_id: str
    project_id: str
    project_run_id: ProjectRunId
    directive_id: ResearchDirectiveId
    directive_version: int
    directive_sha256: str
    request_sha256: str
    approved_budget_cap_cents: Decimal
    estimated_cost_cents: Decimal
    created_by: str
    source_operation_id: OperationId
    source_action_ref: str
    created_at: UtcDatetime


class AccountDeepLaunchPreview(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    workspace_id: str
    project_id: str
    project_run_id: ProjectRunId
    directive_id: ResearchDirectiveId
    directive_version: int
    directive_sha256: str
    account_entity_ids: tuple[EntityId, ...] = Field(min_length=1, max_length=500)
    account_pins: tuple[ResearchDirectivePin, ...] = Field(min_length=1, max_length=500)
    estimated_cost_cents: Decimal = Field(ge=0)
    request_sha256: str


@dataclass(frozen=True, slots=True)
class CreatedAccountDeepLaunch:
    launch: AccountDeepLaunchRow
    account_entity_ids: tuple[EntityId, ...]
    replayed: bool


def _request_sha256(
    *,
    project_run_id: ProjectRunId,
    directive_id: ResearchDirectiveId,
    directive_version: int,
    directive_sha256: str,
    account_entity_ids: tuple[EntityId, ...],
    approved_budget_cap_cents: Decimal,
    expected_estimated_cost_cents: Decimal,
) -> str:
    def money(value: Decimal) -> str:
        # Decimal scale is transport syntax, not launch identity: ``300``, ``300.0`` and
        # ``3.00E+2`` authorize the same cent amount and must replay the same receipt.
        normalized = value.normalize()
        return format(normalized, "f") if normalized else "0"

    payload = {
        "project_run_id": str(project_run_id),
        "directive_id": str(directive_id),
        "directive_version": directive_version,
        "directive_sha256": directive_sha256,
        "account_entity_ids": [str(value) for value in account_entity_ids],
        "approved_budget_cap_cents": money(approved_budget_cap_cents),
        "expected_estimated_cost_cents": money(expected_estimated_cost_cents),
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


async def preview_account_deep_launch(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    project_run_id: ProjectRunId,
    directive_id: ResearchDirectiveId,
    account_entity_ids: tuple[EntityId, ...],
    approved_budget_cap_cents: Decimal,
    expected_estimated_cost_cents: Decimal,
) -> AccountDeepLaunchPreview:
    """Validate current launchability and recompute the exact account-budget estimate."""

    selected = tuple(sorted(account_entity_ids, key=str))
    if not selected or len(selected) > 500 or len(set(selected)) != len(selected):
        raise AccountDeepLaunchInvalid("launch requires 1-500 unique account ids")
    if (
        not approved_budget_cap_cents.is_finite()
        or not expected_estimated_cost_cents.is_finite()
        or approved_budget_cap_cents < 0
        or expected_estimated_cost_cents < 0
    ):
        raise AccountDeepLaunchInvalid("launch budget and estimate must be nonnegative")

    # An immutable launch remains replayable even when a later human-confirmed directive
    # supersedes it or the state machine advances. Requiring mutable current state before checking
    # this receipt would break crash recovery at the enqueue boundary.
    existing = await get_account_deep_launch(conn, project_run_id, workspace_id=workspace_id)
    if existing is not None:
        digest = _request_sha256(
            project_run_id=project_run_id,
            directive_id=directive_id,
            directive_version=existing.directive_version,
            directive_sha256=existing.directive_sha256,
            account_entity_ids=selected,
            approved_budget_cap_cents=approved_budget_cap_cents,
            expected_estimated_cost_cents=expected_estimated_cost_cents,
        )
        if existing.directive_id != directive_id or existing.request_sha256 != digest:
            raise AccountDeepLaunchConflict("project run already has a different deep launch")
        replay_pins = await account_deep_launch_account_pins(conn, existing)
        return AccountDeepLaunchPreview(
            workspace_id=existing.workspace_id,
            project_id=existing.project_id,
            project_run_id=existing.project_run_id,
            directive_id=existing.directive_id,
            directive_version=existing.directive_version,
            directive_sha256=existing.directive_sha256,
            account_entity_ids=selected,
            account_pins=replay_pins,
            estimated_cost_cents=existing.estimated_cost_cents,
            request_sha256=existing.request_sha256,
        )

    run = await get_project_run(conn, project_run_id)
    if run is None or run.workspace_id != workspace_id:
        raise AccountDeepLaunchInvalid("project run is absent or cross-workspace")
    if run.phase is not ProjectPhase.DEEP or run.status is not ProjectRunStatus.ACTIVE:
        raise AccountDeepLaunchInvalid("project run must be active at the DEEP phase")

    directive = await get_research_directive(conn, directive_id, workspace_id=workspace_id)
    if directive is None:
        raise AccountDeepLaunchInvalid("research directive is absent or cross-workspace")
    if directive.status is not ResearchDirectiveStatus.CONFIRMED:
        raise AccountDeepLaunchInvalid("only the current confirmed directive can launch new work")
    if (
        directive.project_id != run.project_id
        or directive.icp_key != run.icp_key
        or directive.icp_version != run.icp_version
    ):
        raise AccountDeepLaunchInvalid("directive lineage differs from the project run")
    if not directive.body.privacy_policy.account_research_allowed:
        raise AccountDeepLaunchInvalid("directive policy does not authorize account research")
    if directive.body.privacy_policy.contact_reveals_allowed:
        raise AccountDeepLaunchInvalid("O2 does not admit contact-reveal authorization")

    estimate = Decimal(0)
    pins: list[ResearchDirectivePin] = []
    try:
        for account_id in selected:
            effective = await effective_account_research_directive(
                conn,
                workspace_id=workspace_id,
                directive_id=directive_id,
                account_id=account_id,
            )
            estimate += effective.effort_policy.budget_cap_cents
            pins.append(effective.pin)
    except (ResearchDirectiveInvalid, ResearchDirectiveConflict) as exc:
        raise AccountDeepLaunchInvalid(str(exc)) from exc
    if estimate != expected_estimated_cost_cents:
        raise AccountDeepLaunchConflict(
            "approved estimate differs from the current effective directive estimate"
        )
    if approved_budget_cap_cents < estimate:
        raise AccountDeepLaunchInvalid("approved launch budget is below the reviewed estimate")
    if run.budget_cap_cents is not None:
        remaining = max(Decimal(0), run.budget_cap_cents - run.spent_cents)
        if approved_budget_cap_cents > remaining:
            raise AccountDeepLaunchInvalid("approved launch budget exceeds remaining run headroom")

    digest = _request_sha256(
        project_run_id=project_run_id,
        directive_id=directive_id,
        directive_version=directive.version,
        directive_sha256=directive.canonical_json_sha256,
        account_entity_ids=selected,
        approved_budget_cap_cents=approved_budget_cap_cents,
        expected_estimated_cost_cents=expected_estimated_cost_cents,
    )
    return AccountDeepLaunchPreview(
        workspace_id=workspace_id,
        project_id=run.project_id,
        project_run_id=project_run_id,
        directive_id=directive_id,
        directive_version=directive.version,
        directive_sha256=directive.canonical_json_sha256,
        account_entity_ids=selected,
        account_pins=tuple(pins),
        estimated_cost_cents=estimate,
        request_sha256=digest,
    )


async def create_account_deep_launch(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    project_run_id: ProjectRunId,
    directive_id: ResearchDirectiveId,
    account_entity_ids: tuple[EntityId, ...],
    approved_budget_cap_cents: Decimal,
    expected_estimated_cost_cents: Decimal,
    created_by: str,
    source_operation_id: OperationId,
    source_action_ref: str,
) -> CreatedAccountDeepLaunch:
    """Create or exactly replay the immutable launch receipt under a run-scoped lock."""

    await conn.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:scope, 0))"),
        {"scope": f"account-deep-launch:{workspace_id}:{project_run_id}"},
    )
    preview = await preview_account_deep_launch(
        conn,
        workspace_id=workspace_id,
        project_run_id=project_run_id,
        directive_id=directive_id,
        account_entity_ids=account_entity_ids,
        approved_budget_cap_cents=approved_budget_cap_cents,
        expected_estimated_cost_cents=expected_estimated_cost_cents,
    )
    existing = await get_account_deep_launch(conn, project_run_id, workspace_id=workspace_id)
    if existing is not None:
        if existing.request_sha256 != preview.request_sha256:
            raise AccountDeepLaunchConflict("project run already has a different deep launch")
        accounts = await account_deep_launch_accounts(conn, existing.id, workspace_id=workspace_id)
        return CreatedAccountDeepLaunch(existing, accounts, replayed=True)

    launch_id = uuid5(_LAUNCH_NAMESPACE, f"{workspace_id}:{project_run_id}")
    row = (
        (
            await conn.execute(
                text(
                    "INSERT INTO account_deep_launch "
                    "(id, workspace_id, project_id, project_run_id, directive_id, "
                    "directive_version, directive_sha256, request_sha256, "
                    "approved_budget_cap_cents, estimated_cost_cents, created_by, "
                    "source_operation_id, source_action_ref) VALUES "
                    "(:id, :workspace_id, :project_id, :project_run_id, :directive_id, "
                    ":directive_version, :directive_sha256, :request_sha256, :budget, :estimate, "
                    ":created_by, :source_operation_id, :source_action_ref) RETURNING *"
                ),
                {
                    "id": launch_id,
                    "workspace_id": workspace_id,
                    "project_id": preview.project_id,
                    "project_run_id": project_run_id,
                    "directive_id": directive_id,
                    "directive_version": preview.directive_version,
                    "directive_sha256": preview.directive_sha256,
                    "request_sha256": preview.request_sha256,
                    "budget": approved_budget_cap_cents,
                    "estimate": preview.estimated_cost_cents,
                    "created_by": created_by,
                    "source_operation_id": source_operation_id,
                    "source_action_ref": source_action_ref,
                },
            )
        )
        .mappings()
        .one()
    )
    for pin in preview.account_pins:
        await conn.execute(
            text(
                "INSERT INTO account_deep_launch_account "
                "(launch_id, workspace_id, directive_id, account_id, directive_ref, "
                "override_id, override_ref, override_sha256) VALUES "
                "(:launch_id, :workspace_id, :directive_id, :account_id, :directive_ref, "
                ":override_id, :override_ref, :override_sha256)"
            ),
            {
                "launch_id": launch_id,
                "workspace_id": workspace_id,
                "directive_id": directive_id,
                "account_id": pin.account_id,
                "directive_ref": pin.directive_ref,
                "override_id": pin.override_id,
                "override_ref": pin.override_ref,
                "override_sha256": pin.override_sha256,
            },
        )
    return CreatedAccountDeepLaunch(_row(row), preview.account_entity_ids, replayed=False)


async def get_account_deep_launch(
    conn: AsyncConnection,
    project_run_id: ProjectRunId,
    *,
    workspace_id: str,
) -> AccountDeepLaunchRow | None:
    row = (
        (
            await conn.execute(
                text(
                    "SELECT * FROM account_deep_launch WHERE project_run_id=:project_run_id "
                    "AND workspace_id=:workspace_id"
                ),
                {"project_run_id": project_run_id, "workspace_id": workspace_id},
            )
        )
        .mappings()
        .first()
    )
    return _row(row) if row is not None else None


async def account_deep_launch_accounts(
    conn: AsyncConnection,
    launch_id: UUID,
    *,
    workspace_id: str,
) -> tuple[EntityId, ...]:
    values = (
        await conn.execute(
            text(
                "SELECT account_id FROM account_deep_launch_account "
                "WHERE launch_id=:launch_id AND workspace_id=:workspace_id ORDER BY account_id"
            ),
            {"launch_id": launch_id, "workspace_id": workspace_id},
        )
    ).scalars()
    return tuple(EntityId(value) for value in values)


async def account_deep_launch_account_pins(
    conn: AsyncConnection,
    launch: AccountDeepLaunchRow,
) -> tuple[ResearchDirectivePin, ...]:
    rows = (
        await conn.execute(
            text(
                "SELECT account_id, directive_ref, override_id, override_ref, override_sha256 "
                "FROM account_deep_launch_account WHERE launch_id=:launch_id "
                "AND workspace_id=:workspace_id ORDER BY account_id"
            ),
            {"launch_id": launch.id, "workspace_id": launch.workspace_id},
        )
    ).mappings()
    return tuple(
        ResearchDirectivePin(
            directive_id=launch.directive_id,
            directive_ref=str(row["directive_ref"]),
            version=launch.directive_version,
            canonical_json_sha256=launch.directive_sha256,
            account_id=EntityId(row["account_id"]),
            override_id=row["override_id"],
            override_ref=row["override_ref"],
            override_sha256=row["override_sha256"],
        )
        for row in rows
    )


def _row(row: Any) -> AccountDeepLaunchRow:
    return AccountDeepLaunchRow.model_validate(dict(row))


__all__ = [
    "AccountDeepLaunchConflict",
    "AccountDeepLaunchError",
    "AccountDeepLaunchInvalid",
    "AccountDeepLaunchPreview",
    "AccountDeepLaunchRow",
    "CreatedAccountDeepLaunch",
    "account_deep_launch_accounts",
    "account_deep_launch_account_pins",
    "create_account_deep_launch",
    "get_account_deep_launch",
    "preview_account_deep_launch",
]
