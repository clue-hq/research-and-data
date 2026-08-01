from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from clue_agents.contracts import (
    AgentConstitution,
    AgentResourceRef,
    AgentRole,
    ArtifactRef,
    DomainObjectRef,
    ResourceKind,
)
from clue_core import ExecutionId

SHA_A = "a" * 64
SHA_B = "b" * 64
SHA_C = "c" * 64
NOW = datetime(2026, 7, 26, 12, tzinfo=UTC)
EXECUTION_ID = ExecutionId(UUID("00000000-0000-0000-0000-000000000601"))


def artifact(name: str, *, sha256: str = SHA_A, workspace_id: str = "ws-1") -> ArtifactRef:
    return ArtifactRef(
        workspace_id=workspace_id,
        artifact_key=f"agent-artifacts/{name}",
        sha256=sha256,
        media_type="application/json",
        byte_count=12,
    )


def resource(
    kind: ResourceKind,
    name: str,
    *,
    version: str = "1.0.0",
    sha256: str = SHA_A,
) -> AgentResourceRef:
    return AgentResourceRef(kind=kind, name=name, version=version, sha256=sha256)


def domain_ref(name: str, *, workspace_id: str = "ws-1") -> DomainObjectRef:
    return DomainObjectRef(
        workspace_id=workspace_id,
        object_type="account",
        object_id=name,
        version=1,
    )


def constitution(**overrides: Any) -> AgentConstitution:
    values: dict[str, Any] = {
        "workspace_id": "ws-1",
        "project_id": "project-1",
        "execution_id": EXECUTION_ID,
        "actor_id": "user-1",
        "role": AgentRole.HEAD_OF_ABM,
        "brand_id": "brand-1",
        "product_id": "product-1",
        "client_entity_id": "client-1",
        "workspace_root_id": "agent-root-opaque-1",
        "project_card_ref": artifact("project-card.json"),
        "budget_envelope_ref": artifact("budget.json"),
        "profile_ref": resource(ResourceKind.PROFILE, "head-of-abm"),
        "resource_manifest_ref": artifact("resource-manifest.json"),
        "resource_manifest_sha256": SHA_B,
        "focus_refs": (domain_ref("account-1"),),
    }
    values.update(overrides)
    return AgentConstitution(**values)
