"""Durable production context scope for one ``AGENT_TURN`` (FI S3.1).

The fleet may attempt the same submitted turn more than once after a worker crash.  Resolving the
current project/client/Client-KB tuple independently in every attempt would let background recon
publish vN+1 between attempts and silently mix vN and vN+1 inside one logical turn.  This module
turns that tuple into an immutable receipt, written before cards, tools, or model execution.

The receipt also pins the *meaning* of Client-KB scope. Historical
``company-account-wide-v1`` rows admit only the account-wide marker, while V2 receipts preserve
the earlier honest selected-without-knowledge state. New turns use
``company-and-selected-product-required-v3``: the company marker plus an independently current
Product-KB version for every human-confirmed project product. A missing Product-KB is repaired to
an honest empty baseline before the immutable receipt is inserted.
"""

from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, ConfigDict
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_api.agent_turn_submission import AgentTurnSubmissionRow
from clue_api.conversation_capture import project_client_entity_id
from clue_api.product_knowledge_decision import (
    COMPANY_AND_SELECTED_PRODUCT_SCOPE_POLICY_V2,
    COMPANY_AND_SELECTED_PRODUCT_SCOPE_POLICY_V3,
)
from clue_core import EntityId, UtcDatetime
from clue_research.stage0 import ensure_product_kb_baseline
from clue_spine import get_project

__all__ = [
    "COMPANY_ACCOUNT_WIDE_KNOWLEDGE_SCOPE_V1",
    "COMPANY_AND_SELECTED_PRODUCT_SCOPE_POLICY_V2",
    "COMPANY_AND_SELECTED_PRODUCT_SCOPE_POLICY_V3",
    "AgentTurnScopePinRow",
    "AgentTurnScopePinConflict",
    "get_agent_turn_scope_pin",
    "load_or_create_agent_turn_scope_pin",
]

COMPANY_ACCOUNT_WIDE_KNOWLEDGE_SCOPE_V1 = "company-account-wide-v1"

_COLUMNS = (
    "turn_id, workspace_id, project_id, project_name, project_status, brand_id, product_id, "
    "client_entity_id, client_kb_version, product_kb_version, "
    "knowledge_scope_policy_version, pinned_at"
)


class AgentTurnScopePinConflict(ValueError):
    """The submitted turn cannot be pinned to a coherent trusted project scope."""


class AgentTurnScopePinRow(BaseModel):
    """One immutable production context receipt."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    turn_id: UUID
    workspace_id: str
    project_id: str
    project_name: str
    project_status: str
    brand_id: str
    product_id: str | None
    client_entity_id: EntityId | None
    client_kb_version: int | None
    product_kb_version: int | None
    knowledge_scope_policy_version: str
    pinned_at: UtcDatetime

    def assert_supported_policy(self) -> None:
        """Fail closed rather than reinterpret a receipt written under another policy."""

        if self.knowledge_scope_policy_version not in {
            COMPANY_ACCOUNT_WIDE_KNOWLEDGE_SCOPE_V1,
            COMPANY_AND_SELECTED_PRODUCT_SCOPE_POLICY_V2,
            COMPANY_AND_SELECTED_PRODUCT_SCOPE_POLICY_V3,
        }:
            raise AgentTurnScopePinConflict(
                "this turn's Client-KB scope policy is not supported by this worker"
            )
        if (
            self.knowledge_scope_policy_version == COMPANY_ACCOUNT_WIDE_KNOWLEDGE_SCOPE_V1
            and self.product_kb_version is not None
        ):
            raise AgentTurnScopePinConflict("a historical V1 pin cannot carry Product-KB state")
        if self.product_kb_version is not None and (
            self.product_id is None
            or self.client_entity_id is None
            or self.client_kb_version is None
        ):
            raise AgentTurnScopePinConflict(
                "a Product-KB pin requires company, client, and confirmed-product authority"
            )
        if (
            self.knowledge_scope_policy_version == COMPANY_AND_SELECTED_PRODUCT_SCOPE_POLICY_V3
            and self.product_id is not None
            and self.product_kb_version is None
        ):
            raise AgentTurnScopePinConflict(
                "a V3 selected-product turn requires an exact Product-KB lineage"
            )


async def _current_kb_version_pair(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    client_entity_id: EntityId,
    product_id: str | None,
) -> tuple[int | None, int | None]:
    """Resolve company and selected-product markers in one PostgreSQL statement snapshot."""

    row = (
        (
            await conn.execute(
                text(
                    "SELECT "
                    "max((value_json->>'version')::integer) "
                    "FILTER (WHERE product_id IS NULL) AS company_version, "
                    "max((value_json->>'version')::integer) "
                    "FILTER (WHERE product_id=:product_id) AS product_version "
                    "FROM claim WHERE workspace_id=:workspace_id "
                    "AND entity_id=:client_entity_id AND field_key='client.kb_version' "
                    "AND superseded_by IS NULL "
                    "AND (product_id IS NULL OR product_id=:product_id)"
                ),
                {
                    "workspace_id": workspace_id,
                    "client_entity_id": client_entity_id,
                    "product_id": product_id,
                },
            )
        )
        .mappings()
        .one()
    )
    return row["company_version"], row["product_version"]


async def get_agent_turn_scope_pin(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    turn_id: UUID,
) -> AgentTurnScopePinRow | None:
    """Read a pin inside one workspace; a foreign pin is indistinguishable from absence."""

    row = (
        (
            await conn.execute(
                text(
                    f"SELECT {_COLUMNS} FROM agent_turn_scope_pin "
                    "WHERE turn_id=:turn_id AND workspace_id=:workspace_id"
                ),
                {"turn_id": turn_id, "workspace_id": workspace_id},
            )
        )
        .mappings()
        .one_or_none()
    )
    if row is None:
        return None
    pin = AgentTurnScopePinRow.model_validate(dict(row))
    pin.assert_supported_policy()
    return pin


async def load_or_create_agent_turn_scope_pin(
    conn: AsyncConnection,
    *,
    submission: AgentTurnSubmissionRow,
) -> tuple[AgentTurnScopePinRow, bool]:
    """Return this turn's immutable scope, atomically creating it on the first attempt.

    Concurrent attempts may both resolve current state, but only the winning ``INSERT`` owns the
    turn.  The loser reads the winner's row; it never composes from its discarded observation.
    Database ``now()`` supplies the receipt time.
    """

    existing = await get_agent_turn_scope_pin(
        conn,
        workspace_id=submission.workspace_id,
        turn_id=submission.turn_id,
    )
    if existing is not None:
        return existing, False

    project = await get_project(conn, submission.project_id)
    if project is None or project.workspace_id != submission.workspace_id:
        raise AgentTurnScopePinConflict("the submission names no project in its workspace")
    client_entity_id = await project_client_entity_id(
        conn,
        workspace_id=submission.workspace_id,
        project_id=submission.project_id,
    )
    client_kb_version, product_kb_version = (
        (None, None)
        if client_entity_id is None
        else await _current_kb_version_pair(
            conn,
            workspace_id=submission.workspace_id,
            client_entity_id=client_entity_id,
            product_id=project.product_id,
        )
    )
    if project.product_id is not None:
        if client_entity_id is None or client_kb_version is None:
            raise AgentTurnScopePinConflict(
                "a selected-product turn requires an established company Client-KB"
            )
        if product_kb_version is None:
            baseline = await ensure_product_kb_baseline(
                conn,
                workspace_id=submission.workspace_id,
                client_entity_id=client_entity_id,
                product_id=project.product_id,
                operation_key=f"turn-pin-repair:{project.project_id}:{project.product_id}",
            )
            product_kb_version = baseline.version
    inserted = (
        (
            await conn.execute(
                text(
                    "INSERT INTO agent_turn_scope_pin "
                    "(turn_id, workspace_id, project_id, project_name, project_status, brand_id, "
                    " product_id, client_entity_id, client_kb_version, product_kb_version, "
                    " knowledge_scope_policy_version) "
                    "VALUES (:turn_id, :workspace_id, :project_id, :project_name, "
                    " :project_status, :brand_id, :product_id, :client_entity_id, "
                    " :client_kb_version, :product_kb_version, :policy) "
                    "ON CONFLICT (turn_id) DO NOTHING "
                    f"RETURNING {_COLUMNS}"
                ),
                {
                    "turn_id": submission.turn_id,
                    "workspace_id": submission.workspace_id,
                    "project_id": project.project_id,
                    "project_name": project.name,
                    "project_status": project.status,
                    "brand_id": project.brand_id,
                    "product_id": project.product_id,
                    "client_entity_id": client_entity_id,
                    "client_kb_version": client_kb_version,
                    "product_kb_version": product_kb_version,
                    "policy": COMPANY_AND_SELECTED_PRODUCT_SCOPE_POLICY_V3,
                },
            )
        )
        .mappings()
        .one_or_none()
    )
    if inserted is not None:
        pin = AgentTurnScopePinRow.model_validate(dict(inserted))
        pin.assert_supported_policy()
        return pin, True

    winner = await get_agent_turn_scope_pin(
        conn,
        workspace_id=submission.workspace_id,
        turn_id=submission.turn_id,
    )
    if winner is None:
        raise AgentTurnScopePinConflict(
            "this turn's scope pin exists outside the requested workspace"
        )
    return winner, False
