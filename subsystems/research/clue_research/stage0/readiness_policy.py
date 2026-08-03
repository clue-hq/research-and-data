"""Human-authorized, tenant-local Client-KB readiness extensions.

Dynamic fields are always registered as supplemental. This ledger is the separate prospective
operation that may make selected local fields required; it never mutates the platform baseline.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping, Sequence

from pydantic import BaseModel, ConfigDict, JsonValue
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_core import Claim, UtcDatetime, canonical_json, decode_jsonb, serialize_value_json
from clue_research.claimstore import (
    assert_workspace_dynamic_client_kb_active,
    get_workspace_field,
)


class WorkspaceClientKbReadinessPolicy(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    workspace_id: str
    version: int
    required_field_keys: tuple[str, ...]
    policy_hash: str
    decided_by: str
    decision_reason: str
    created_at: UtcDatetime


async def get_workspace_client_kb_readiness_policy(
    conn: AsyncConnection, *, workspace_id: str
) -> WorkspaceClientKbReadinessPolicy | None:
    row = (
        (
            await conn.execute(
                text(
                    """
                    SELECT workspace_id, version, required_field_keys, policy_hash, decided_by,
                           decision_reason, created_at
                    FROM workspace_client_kb_readiness_policy
                    WHERE workspace_id = :workspace_id
                      AND NOT EXISTS (
                          SELECT 1 FROM workspace_dynamic_client_kb_erasure e
                          WHERE e.workspace_id = workspace_client_kb_readiness_policy.workspace_id
                      )
                    ORDER BY version DESC
                    LIMIT 1
                    """
                ),
                {"workspace_id": workspace_id},
            )
        )
        .mappings()
        .one_or_none()
    )
    if row is None:
        return None
    payload = dict(row)
    payload["required_field_keys"] = tuple(decode_jsonb(payload["required_field_keys"]) or ())
    return WorkspaceClientKbReadinessPolicy.model_validate(payload)


async def set_workspace_client_kb_readiness_policy(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    required_field_keys: Sequence[str],
    decided_by: str,
    decision_reason: str,
) -> WorkspaceClientKbReadinessPolicy:
    """Append/replay one local policy revision; only a human may change the denominator."""

    if not decided_by.startswith("human:"):
        raise PermissionError("workspace Client-KB readiness policy requires human authority")
    await assert_workspace_dynamic_client_kb_active(conn, workspace_id=workspace_id)
    keys = tuple(sorted(set(required_field_keys)))
    for field_key in keys:
        definition = await get_workspace_field(conn, workspace_id=workspace_id, field_key=field_key)
        if definition is None:
            raise ValueError(
                f"required field {field_key!r} is not an active local field in this workspace"
            )
    policy_hash = hashlib.sha256(canonical_json(list(keys)).encode()).hexdigest()
    await conn.execute(
        text("SELECT workspace_id FROM workspace WHERE workspace_id = :workspace_id FOR UPDATE"),
        {"workspace_id": workspace_id},
    )
    current = await get_workspace_client_kb_readiness_policy(conn, workspace_id=workspace_id)
    if current is not None and current.policy_hash == policy_hash:
        return current
    version = current.version + 1 if current is not None else 1
    await conn.execute(
        text(
            """
            INSERT INTO workspace_client_kb_readiness_policy (
                workspace_id, version, required_field_keys, policy_hash, decided_by,
                decision_reason
            ) VALUES (
                :workspace_id, :version, CAST(:keys AS jsonb), :policy_hash, :decided_by,
                :decision_reason
            )
            """
        ),
        {
            "workspace_id": workspace_id,
            "version": version,
            "keys": serialize_value_json(list(keys)),
            "policy_hash": policy_hash,
            "decided_by": decided_by,
            "decision_reason": decision_reason,
        },
    )
    created = await get_workspace_client_kb_readiness_policy(conn, workspace_id=workspace_id)
    assert created is not None
    return created


def workspace_required_field_metrics(
    claims: Mapping[str, Claim],
    policy: WorkspaceClientKbReadinessPolicy | None,
) -> dict[str, JsonValue]:
    """Informational local-policy metrics, kept separate from baseline coverage."""

    required = policy.required_field_keys if policy is not None else ()
    filled = tuple(key for key in required if key in claims)
    return {
        "workspace_readiness_policy_version": policy.version if policy is not None else 0,
        "workspace_required_field_keys": list(required),
        "workspace_required_filled": len(filled),
        "workspace_required_missing_field_keys": [key for key in required if key not in claims],
    }


__all__ = [
    "WorkspaceClientKbReadinessPolicy",
    "get_workspace_client_kb_readiness_policy",
    "set_workspace_client_kb_readiness_policy",
    "workspace_required_field_metrics",
]
