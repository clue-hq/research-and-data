"""M8B O3 composition of current account-deep state into Head-of-ABM L3 artifacts."""

from __future__ import annotations

import json
from collections.abc import Mapping
from uuid import UUID

from clue_agents import DomainObjectRef, ProjectContextArtifact
from clue_api.agent_turn_wiring import DurableAgentArtifactStore
from clue_core import EntityId, ProjectPhase, ProjectRunId, ResearchDirective
from clue_db import ConnFactory, transaction
from clue_projections import (
    ACCOUNT_DEEP_STEERING_CARD_MEDIA_TYPE,
    AccountDeepSteeringAccount,
    AccountDeepSteeringCard,
    AccountDeepSteeringLaunch,
    project_research_directive_preview,
)
from clue_research.directives import (
    get_latest_research_directive,
    list_research_directive_overrides,
    research_directive_account_ids,
)
from clue_research.durable import (
    account_deep_launch_accounts,
    get_account_deep_launch,
    get_checkpoint,
    get_project_run,
    list_account_runs,
)
from clue_research.identity import get_account

__all__ = [
    "compile_account_deep_steering_context",
    "prepare_account_deep_steering_context",
]

_DIRECTIVE_MEDIA_TYPE = "application/vnd.clue.account-research-directive+json"


def _canonical_json(value: object) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode()


def _entity_ids(value: object) -> tuple[EntityId, ...]:
    if not isinstance(value, list):
        return ()
    parsed: list[EntityId] = []
    for item in value:
        if not isinstance(item, str):
            continue
        try:
            parsed.append(EntityId(UUID(item)))
        except ValueError:
            continue
    return tuple(dict.fromkeys(parsed))


def _approved_tiers(checkpoint_payload: Mapping[str, object]) -> dict[EntityId, str]:
    """Resolve both criteria-mode and numeric-score checkpoint approval shapes."""

    approved: dict[EntityId, str] = {}
    approved_tier = checkpoint_payload.get("approved_tier")
    if isinstance(approved_tier, str):
        approved.update(
            dict.fromkeys(
                _entity_ids(checkpoint_payload.get("approved_account_ids")), approved_tier
            )
        )
    review = checkpoint_payload.get("review")
    if not isinstance(review, dict):
        return approved
    accounts = review.get("accounts")
    if not isinstance(accounts, list):
        return approved
    for item in accounts:
        if not isinstance(item, dict):
            continue
        account_id_value = item.get("account_id")
        tier = item.get("tier")
        if not isinstance(account_id_value, str) or not isinstance(tier, str):
            continue
        try:
            approved[EntityId(UUID(account_id_value))] = tier
        except ValueError:
            continue
    return approved


async def compile_account_deep_steering_context(
    *,
    workspace_id: str,
    project_run_id: ProjectRunId,
    conn_factory: ConnFactory = transaction,
) -> tuple[AccountDeepSteeringCard, ResearchDirective | None] | None:
    """Read one exact current card plus the newest directive body, without writing."""

    async with conn_factory() as conn:
        run = await get_project_run(conn, project_run_id)
        if run is None or run.workspace_id != workspace_id:
            return None

        checkpoint = await get_checkpoint(conn, project_run_id, ProjectPhase.TIER_CHECKPOINT)
        checkpoint_payload = checkpoint.payload if checkpoint is not None else {}
        approved_tier_by_account = (
            _approved_tiers(checkpoint_payload)
            if checkpoint is not None and checkpoint.status.value == "committed"
            else {}
        )
        approved_ids = tuple(approved_tier_by_account)
        distinct_approved_tiers = set(approved_tier_by_account.values())
        approved_tier = (
            next(iter(distinct_approved_tiers)) if len(distinct_approved_tiers) == 1 else None
        )

        directive = (
            await get_latest_research_directive(
                conn,
                workspace_id=workspace_id,
                project_id=run.project_id,
                product_id=run.product_id,
                icp_key=run.icp_key,
                icp_version=run.icp_version,
            )
            if run.product_id is not None
            else None
        )
        directive_ids: tuple[EntityId, ...] = ()
        directive_preview = None
        if directive is not None:
            directive_ids = await research_directive_account_ids(
                conn,
                workspace_id=workspace_id,
                directive_id=directive.directive_id,
            )
            overrides = await list_research_directive_overrides(
                conn,
                workspace_id=workspace_id,
                directive_id=directive.directive_id,
            )
            directive_preview = project_research_directive_preview(
                directive,
                overrides,
                resolved_account_ids=directive_ids,
                memory_outcome=("persisted" if directive.memory_refs else "memory_disabled"),
            )

        launch = await get_account_deep_launch(
            conn,
            project_run_id,
            workspace_id=workspace_id,
        )
        launch_ids = (
            await account_deep_launch_accounts(
                conn,
                launch.id,
                workspace_id=workspace_id,
            )
            if launch is not None
            else ()
        )
        account_runs = {row.entity_id: row for row in await list_account_runs(conn, project_run_id)}
        all_ids = tuple(sorted({*approved_ids, *directive_ids, *launch_ids}, key=str))
        account_rows: list[AccountDeepSteeringAccount] = []
        for account_id in all_ids:
            account = await get_account(conn, account_id)
            if account is None or account.workspace_id != workspace_id:
                continue
            account_run = account_runs.get(account_id)
            account_rows.append(
                AccountDeepSteeringAccount(
                    account_entity_id=account_id,
                    canonical_name=account.canonical_name,
                    primary_domain=account.primary_domain,
                    tier_approved=account_id in approved_ids,
                    approved_tier=approved_tier_by_account.get(account_id),
                    in_latest_directive=account_id in directive_ids,
                    in_launch=account_id in launch_ids,
                    account_run_id=str(account_run.id) if account_run is not None else None,
                    account_run_status=(
                        account_run.status.value if account_run is not None else None
                    ),
                    account_run_sub_phase=(
                        account_run.sub_phase.value
                        if account_run is not None and account_run.sub_phase is not None
                        else None
                    ),
                    account_run_cost_cents=(
                        account_run.cost_cents if account_run is not None else None
                    ),
                )
            )

    launch_projection = (
        AccountDeepSteeringLaunch(
            launch_ref=f"account-deep-launch:{launch.id}",
            launch_id=str(launch.id),
            directive_id=str(launch.directive_id),
            directive_version=launch.directive_version,
            directive_sha256=launch.directive_sha256,
            account_entity_ids=launch_ids,
            estimated_cost_cents=launch.estimated_cost_cents,
            approved_budget_cap_cents=launch.approved_budget_cap_cents,
            created_at=launch.created_at.isoformat(),
        )
        if launch is not None
        else None
    )
    return (
        AccountDeepSteeringCard(
            workspace_id=workspace_id,
            project_id=run.project_id,
            project_run_id=run.id,
            project_run_phase=run.phase.value,
            project_run_status=run.status.value,
            icp_key=run.icp_key,
            icp_version=run.icp_version,
            run_budget_cap_cents=run.budget_cap_cents,
            run_spent_cents=run.spent_cents,
            tier_checkpoint_status=(checkpoint.status.value if checkpoint is not None else None),
            approved_tier=approved_tier,
            approved_account_count=len(approved_ids),
            accounts=tuple(account_rows),
            latest_directive=directive_preview,
            latest_directive_sha256=(
                directive.canonical_json_sha256 if directive is not None else None
            ),
            launch_state="receipt_created" if launch is not None else "not_launched",
            launch=launch_projection,
        ),
        directive,
    )


async def prepare_account_deep_steering_context(
    *,
    artifacts: DurableAgentArtifactStore,
    workspace_id: str,
    project_run_id: ProjectRunId,
    conn_factory: ConnFactory = transaction,
) -> tuple[ProjectContextArtifact, ...]:
    """Persist the bounded current card and newest directive for one full Head turn.

    The returned artifacts are ordinary constitution inputs. They create no phase transition,
    confirmation, provider call, launch, or agent-owned state. A caller can therefore assemble
    them on every conversational turn, including while the independently durable fleet is waiting
    or running.
    """

    compiled = await compile_account_deep_steering_context(
        workspace_id=workspace_id,
        project_run_id=project_run_id,
        conn_factory=conn_factory,
    )
    if compiled is None:
        raise ValueError("account-deep steering context run is absent or cross-workspace")
    card, directive = compiled

    card_subject_bindings = tuple(
        (UUID(str(account.account_entity_id)), "context") for account in card.accounts
    )
    directive_subject_bindings = tuple(
        (UUID(str(account.account_entity_id)), "context")
        for account in card.accounts
        if account.in_latest_directive
    )
    project_bindings = ((card.project_id, "account_deep_steering_context"),)
    card_ref = await artifacts.persist_body(
        workspace_id=workspace_id,
        data=card.canonical_bytes(),
        media_type=ACCOUNT_DEEP_STEERING_CARD_MEDIA_TYPE,
        subject_bindings=card_subject_bindings,
        project_bindings=project_bindings,
    )
    materialized: list[ProjectContextArtifact] = [
        ProjectContextArtifact(
            name="account-deep-steering",
            artifact_ref=card_ref,
            domain_ref=DomainObjectRef(
                workspace_id=workspace_id,
                object_type="project_run",
                object_id=str(project_run_id),
                version=None,
            ),
        )
    ]

    if directive is not None:
        directive_ref = await artifacts.persist_body(
            workspace_id=workspace_id,
            data=_canonical_json(directive.model_dump(mode="json")),
            media_type=_DIRECTIVE_MEDIA_TYPE,
            subject_bindings=directive_subject_bindings,
            project_bindings=project_bindings,
        )
        materialized.append(
            ProjectContextArtifact(
                name="research-directive",
                artifact_ref=directive_ref,
                domain_ref=DomainObjectRef(
                    workspace_id=workspace_id,
                    object_type="research_directive",
                    object_id=str(directive.directive_id),
                    version=directive.version,
                ),
            )
        )
    return tuple(materialized)
