"""Trusted provider-neutral discovery planning and immutable run receipts.

Stage-0's approved ICP is knowledge.  This module turns the parts that are already concrete into
an execution configuration without asking a provider adapter to reinterpret that knowledge.  If
the ICP is too vague, the caller receives the exact missing fields and may ask the Deep Agent to
propose them through a human confirmation gate.

The final configuration is persisted against the project run.  It is separate from the product-
context receipt and from spend authority: it answers only what to discover, never whether money
may be spent or which knowledge resources constitute the project context.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_api.stage0_project_contracts import (
    DISCOVERY_CONFIGURATION_SCHEMA_V1,
    DiscoveryConfigurationContract,
)
from clue_core import ICPSpec, ProjectRunId, decode_jsonb, serialize_value_json

__all__ = [
    "DEFAULT_DISCOVERY_PLANNING_POLICY",
    "DiscoveryConfigurationReceipt",
    "DiscoveryPlanningPolicy",
    "DiscoveryPlanningResult",
    "discovery_configuration_sha256",
    "derive_discovery_configuration",
    "get_discovery_configuration_receipt",
    "parse_discovery_configuration_json",
    "put_discovery_configuration_receipt",
]


class DiscoveryPlanningPolicy(BaseModel):
    """Versioned defaults and bounds used before any provider-specific compilation."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    version: Literal["stage0-discovery-planning-policy@1"] = "stage0-discovery-planning-policy@1"
    default_requested_account_count: int = Field(default=10, ge=1, le=50)
    maximum_requested_account_count: int = Field(default=50, ge=1, le=100)

    @model_validator(mode="after")
    def default_stays_inside_the_policy_maximum(self) -> DiscoveryPlanningPolicy:
        if self.default_requested_account_count > self.maximum_requested_account_count:
            raise ValueError("default discovery count cannot exceed the policy maximum")
        return self


DEFAULT_DISCOVERY_PLANNING_POLICY = DiscoveryPlanningPolicy()


@dataclass(frozen=True, slots=True)
class DiscoveryPlanningResult:
    configuration: DiscoveryConfigurationContract | None
    missing_fields: tuple[str, ...]

    @property
    def requires_confirmation(self) -> bool:
        return self.configuration is None


class DiscoveryConfigurationReceipt(BaseModel):
    """The immutable discovery configuration pinned to one project run."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    project_run_id: ProjectRunId
    workspace_id: str
    project_id: str
    icp_key: str
    icp_version: int = Field(ge=1)
    planning_policy_version: str
    configuration: DiscoveryConfigurationContract
    configuration_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_gate_id: UUID | None = None


def discovery_configuration_sha256(configuration: DiscoveryConfigurationContract) -> str:
    payload = configuration.model_dump(mode="json")
    canonical = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def parse_discovery_configuration_json(value: object) -> DiscoveryConfigurationContract:
    """Validate durable JSON in JSON mode while retaining the contract's strict scalar types."""

    return DiscoveryConfigurationContract.model_validate_json(
        serialize_value_json(decode_jsonb(value))
    )


def _clean_text(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    cleaned = " ".join(value.split())
    return cleaned or None


def _clean_texts(value: object) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)):
        return ()
    values = tuple(cleaned for item in value if (cleaned := _clean_text(item)) is not None)
    return tuple(dict.fromkeys(values))


def _firmographic_criteria(strategy: dict[str, Any]) -> tuple[str, ...]:
    firmographic = strategy.get("firmographic")
    if not isinstance(firmographic, dict):
        return ()
    labels = {
        "industry": "Industry",
        "industries": "Industry",
        "size_band": "Company size",
        "employee_band": "Company size",
        "geo": "Geography",
        "geography": "Geography",
        "revenue_band": "Revenue",
        "business_model": "Business model",
        "company_type": "Company type",
    }
    criteria: list[str] = []
    for key in sorted(firmographic):
        raw = firmographic[key]
        value = ", ".join(_clean_texts(raw)) if isinstance(raw, (list, tuple)) else _clean_text(raw)
        if not value:
            continue
        label = labels.get(key, key.replace("_", " ").title())
        criteria.append(f"{label}: {value}")
    return tuple(criteria)


def derive_discovery_configuration(
    *,
    spec: ICPSpec,
    approved_icp_ref: str,
    policy: DiscoveryPlanningPolicy = DEFAULT_DISCOVERY_PLANNING_POLICY,
) -> DiscoveryPlanningResult:
    """Derive a complete configuration when the approved ICP contains enough concrete scope.

    The compatibility branch accepts the explicit query/criteria shape used by older confirmed
    ICPs.  Current Stage-0 ICPs use the provider-neutral firmographic shape; their concrete values
    are rendered into readable criteria and a deterministic search intent.  No model or provider
    call occurs here.
    """

    strategy = dict(spec.discovery_strategy)
    explicit_query = _clean_text(strategy.get("query"))
    explicit_criteria = _clean_texts(strategy.get("must_have_criteria"))
    criteria = explicit_criteria or _firmographic_criteria(strategy)
    exclusions = _clean_texts(strategy.get("exclusion_criteria"))

    requested_raw = strategy.get("requested_count", strategy.get("requested_account_count"))
    requested_count = (
        requested_raw
        if isinstance(requested_raw, int) and not isinstance(requested_raw, bool)
        else policy.default_requested_account_count
    )
    if requested_count < 1 or requested_count > policy.maximum_requested_account_count:
        return DiscoveryPlanningResult(
            configuration=None,
            missing_fields=("requested_account_count",),
        )

    missing: list[str] = []
    if not criteria:
        missing.append("must_have_criteria")
    search_intent = explicit_query
    if search_intent is None and criteria:
        search_intent = "Find companies matching the approved ICP: " + "; ".join(criteria)
    if search_intent is None:
        missing.append("search_intent")
    if missing:
        return DiscoveryPlanningResult(configuration=None, missing_fields=tuple(missing))

    assert search_intent is not None
    configuration = DiscoveryConfigurationContract(
        schema_version=DISCOVERY_CONFIGURATION_SCHEMA_V1,
        approved_icp_ref=approved_icp_ref,
        entity_type="company",
        requested_account_count=requested_count,
        search_intent=search_intent,
        must_have_criteria=criteria,
        exclusion_criteria=exclusions,
    )
    return DiscoveryPlanningResult(configuration=configuration, missing_fields=())


async def put_discovery_configuration_receipt(
    conn: AsyncConnection,
    *,
    receipt: DiscoveryConfigurationReceipt,
) -> DiscoveryConfigurationReceipt:
    """Insert-or-return one run receipt, refusing any attempted identity drift."""

    await conn.execute(
        text(
            """
            INSERT INTO project_run_discovery_configuration (
                project_run_id, workspace_id, project_id, icp_key, icp_version,
                planning_policy_version, configuration_json, configuration_sha256,
                source_gate_id
            ) VALUES (
                :project_run_id, :workspace_id, :project_id, :icp_key, :icp_version,
                :planning_policy_version, CAST(:configuration_json AS jsonb),
                :configuration_sha256, :source_gate_id
            )
            ON CONFLICT (project_run_id) DO NOTHING
            """
        ),
        {
            "project_run_id": receipt.project_run_id,
            "workspace_id": receipt.workspace_id,
            "project_id": receipt.project_id,
            "icp_key": receipt.icp_key,
            "icp_version": receipt.icp_version,
            "planning_policy_version": receipt.planning_policy_version,
            "configuration_json": serialize_value_json(
                receipt.configuration.model_dump(mode="json")
            ),
            "configuration_sha256": receipt.configuration_sha256,
            "source_gate_id": receipt.source_gate_id,
        },
    )
    stored = await get_discovery_configuration_receipt(
        conn,
        project_run_id=receipt.project_run_id,
        workspace_id=receipt.workspace_id,
    )
    if stored is None:
        raise RuntimeError("discovery configuration vanished after insertion")
    if stored != receipt:
        raise ValueError("project run already carries a different discovery configuration")
    return stored


async def get_discovery_configuration_receipt(
    conn: AsyncConnection,
    *,
    project_run_id: ProjectRunId,
    workspace_id: str,
) -> DiscoveryConfigurationReceipt | None:
    row = (
        (
            await conn.execute(
                text(
                    """
                    SELECT project_run_id, workspace_id, project_id, icp_key, icp_version,
                           planning_policy_version, configuration_json,
                           configuration_sha256, source_gate_id
                    FROM project_run_discovery_configuration
                    WHERE project_run_id = :project_run_id
                      AND workspace_id = :workspace_id
                    """
                ),
                {"project_run_id": project_run_id, "workspace_id": workspace_id},
            )
        )
        .mappings()
        .one_or_none()
    )
    if row is None:
        return None
    configuration = parse_discovery_configuration_json(row["configuration_json"])
    receipt = DiscoveryConfigurationReceipt(
        project_run_id=ProjectRunId(row["project_run_id"]),
        workspace_id=str(row["workspace_id"]),
        project_id=str(row["project_id"]),
        icp_key=str(row["icp_key"]),
        icp_version=int(row["icp_version"]),
        planning_policy_version=str(row["planning_policy_version"]),
        configuration=configuration,
        configuration_sha256=str(row["configuration_sha256"]),
        source_gate_id=row["source_gate_id"],
    )
    if discovery_configuration_sha256(configuration) != receipt.configuration_sha256:
        raise ValueError("stored discovery configuration digest does not match its bytes")
    return receipt
