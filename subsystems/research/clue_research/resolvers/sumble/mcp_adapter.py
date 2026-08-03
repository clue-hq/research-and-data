"""Governed Sumble MCP acquisition and data-driven snapshot resolver.

The MCP catalog makes new provider capabilities discoverable, but discovery is not authorization.
This module keeps those concerns separate:

* a versioned policy allowlists exact read-only tools and sensitive capability classes;
* an immutable plan pins the catalog, arguments, field bindings, expected value, and maximum spend;
* a durable journal must claim a reservation before the single paid ``tools/call`` attempt;
* the exact response or an unknown-spend disposition is durably recorded; and
* claims are normalized later from a durable snapshot through data-driven JSON-pointer bindings.

No free-form MCP text is promoted to a field.  The client admits only ``structuredContent`` or an
exact JSON text block, and the resolver still requires a registered platform ``FieldDef``.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections.abc import Mapping, Sequence
from decimal import Decimal
from enum import StrEnum
from typing import Any, Protocol, cast

from pydantic import BaseModel, ConfigDict, Field, JsonValue, model_validator

from clue_core import (
    Claim,
    CostCents,
    Entity,
    EntityId,
    EntityType,
    FieldDef,
    FieldKey,
    ProjectRunId,
    ResolverError,
    UseClass,
    revalidate_with,
)
from clue_research.resolvers.base import ResolvedField, build_claim, resolved_field
from clue_research.resolvers.sumble.mcp_client import (
    SUMBLE_MCP_ENDPOINT,
    SumbleMcpToolCatalog,
    SumbleMcpToolDescriptor,
    SumbleMcpToolExchange,
)


class SumbleMcpGovernanceError(ResolverError):
    """The proposed MCP invocation is not covered by an explicit authorization."""


class SumbleMcpSchemaError(SumbleMcpGovernanceError):
    """Arguments or a field binding do not satisfy the pinned tool contract."""


class SumbleMcpSpendOutcomeUnknown(ResolverError):
    """A tools/call may have consumed credits and must not be automatically replayed."""


class SumbleMcpToolClass(StrEnum):
    ORGANIZATION = "organization"
    JOBS = "jobs"
    TECHNOLOGY = "technology"
    SIGNALS = "signals"
    PEOPLE = "people"
    CONTACT_REVEAL = "contact_reveal"
    ACCOUNT_METADATA = "account_metadata"
    AI_BRIEF = "ai_brief"
    DATABASE = "database"
    MUTATION = "mutation"
    UNKNOWN = "unknown"


_TOOL_CLASSES: dict[str, SumbleMcpToolClass] = {
    "GetAccountInformation": SumbleMcpToolClass.ACCOUNT_METADATA,
    "GetMyCompanyProfile": SumbleMcpToolClass.ACCOUNT_METADATA,
    "FindMatchAndEnrichOrganizations": SumbleMcpToolClass.ORGANIZATION,
    "GetOrganizationTechStack": SumbleMcpToolClass.TECHNOLOGY,
    "SearchTechnologies": SumbleMcpToolClass.TECHNOLOGY,
    "LookupTechnologies": SumbleMcpToolClass.TECHNOLOGY,
    "LookupTechnologyCategories": SumbleMcpToolClass.TECHNOLOGY,
    "FindMatchAndEnrichJobs": SumbleMcpToolClass.JOBS,
    "LookupJobTitles": SumbleMcpToolClass.JOBS,
    "GetOrganizationSignals": SumbleMcpToolClass.SIGNALS,
    "SearchSignals": SumbleMcpToolClass.SIGNALS,
    "SearchPrioritySignals": SumbleMcpToolClass.SIGNALS,
    "FindMatchAndEnrichPeople": SumbleMcpToolClass.PEOPLE,
    "GetIntelligenceBrief": SumbleMcpToolClass.AI_BRIEF,
    "RunSqlQuery": SumbleMcpToolClass.DATABASE,
    "ListTables": SumbleMcpToolClass.DATABASE,
}

_MUTATION_MARKERS = (
    "add",
    "create",
    "delete",
    "report",
    "remove",
    "set",
    "submit",
    "update",
    "write",
)


def classify_sumble_mcp_tool(name: str) -> SumbleMcpToolClass:
    exact = _TOOL_CLASSES.get(name)
    if exact is not None:
        return exact
    lower = name.lower()
    if any(lower.startswith(marker) for marker in _MUTATION_MARKERS):
        return SumbleMcpToolClass.MUTATION
    if "organization" in lower or "company" in lower:
        return SumbleMcpToolClass.ORGANIZATION
    if "job" in lower:
        return SumbleMcpToolClass.JOBS
    if "tech" in lower:
        return SumbleMcpToolClass.TECHNOLOGY
    if "signal" in lower:
        return SumbleMcpToolClass.SIGNALS
    if "people" in lower or "person" in lower:
        return SumbleMcpToolClass.PEOPLE
    return SumbleMcpToolClass.UNKNOWN


def _contains_contact_reveal(value: JsonValue) -> bool:
    reveal_tokens = {
        "email",
        "emails",
        "email_address",
        "email_addresses",
        "mobile",
        "mobile_phone",
        "phone",
        "phone_number",
        "phone_numbers",
        "personal_email",
        "work_email",
    }
    if isinstance(value, dict):
        for key, child in value.items():
            normalized = key.lower().replace("-", "_")
            if normalized in reveal_tokens:
                return True
            if normalized in {"attribute", "attributes", "fields", "select"}:
                serialized = json.dumps(child, sort_keys=True).lower()
                if serialized == '"all"' or any(token in serialized for token in reveal_tokens):
                    return True
            if _contains_contact_reveal(child):
                return True
    elif isinstance(value, list):
        return any(_contains_contact_reveal(item) for item in value)
    return False


class SumbleMcpPolicy(BaseModel):
    """Versioned fail-closed capability policy; tool discovery never expands authority."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    version: str = "sumble-mcp-governance-v1"
    allowed_tool_names: frozenset[str] = frozenset(
        {
            "FindMatchAndEnrichOrganizations",
            "FindMatchAndEnrichJobs",
            "GetOrganizationTechStack",
            "LookupJobTitles",
            "SearchTechnologies",
            "LookupTechnologies",
            "LookupTechnologyCategories",
        }
    )
    allowed_tool_classes: frozenset[SumbleMcpToolClass] = frozenset(
        {
            SumbleMcpToolClass.ORGANIZATION,
            SumbleMcpToolClass.JOBS,
            SumbleMcpToolClass.TECHNOLOGY,
        }
    )
    custom_tool_classes: dict[str, SumbleMcpToolClass] = Field(default_factory=dict)
    allow_contact_reveal: bool = False
    allow_signals: bool = False

    def tool_class(self, name: str) -> SumbleMcpToolClass:
        return self.custom_tool_classes.get(name, classify_sumble_mcp_tool(name))

    def authorize(self, *, tool_name: str, contact_reveal: bool) -> None:
        base_class = classify_sumble_mcp_tool(tool_name)
        if base_class in {
            SumbleMcpToolClass.MUTATION,
            SumbleMcpToolClass.DATABASE,
            SumbleMcpToolClass.AI_BRIEF,
        }:
            raise SumbleMcpGovernanceError(
                f"Sumble MCP capability class {base_class.value!r} is prohibited"
            )
        tool_class = self.tool_class(tool_name)
        if tool_class in {
            SumbleMcpToolClass.MUTATION,
            SumbleMcpToolClass.DATABASE,
            SumbleMcpToolClass.AI_BRIEF,
        }:
            raise SumbleMcpGovernanceError(
                f"Sumble MCP capability class {tool_class.value!r} is prohibited"
            )
        if tool_name not in self.allowed_tool_names or tool_class not in self.allowed_tool_classes:
            raise SumbleMcpGovernanceError(
                f"Sumble MCP tool {tool_name!r} is not in the versioned allowlist"
            )
        if tool_class is SumbleMcpToolClass.SIGNALS and not self.allow_signals:
            raise SumbleMcpGovernanceError("Sumble MCP signals remain disabled by policy")
        if contact_reveal and not self.allow_contact_reveal:
            raise SumbleMcpGovernanceError(
                "Sumble MCP contact reveal requires separate personal-data authorization"
            )


DEFAULT_SUMBLE_MCP_POLICY = SumbleMcpPolicy()


class SumbleMcpFieldBinding(BaseModel):
    """Versioned mapping from one tool result to one registered platform field."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    field_key: FieldKey
    value_pointer: str = Field(pattern=r"^(|/.*)$")
    source_url_pointer: str | None = Field(default=None, pattern=r"^(|/.*)$")
    evidence_pointer: str | None = Field(default=None, pattern=r"^(|/.*)$")
    confidence_pointer: str | None = Field(default=None, pattern=r"^(|/.*)$")
    default_confidence: float = Field(default=0.85, ge=0, le=1)
    use_class: UseClass = UseClass.PROFESSIONAL_PUBLIC


class SumbleMcpSettlementMode(StrEnum):
    PROVIDER_RECEIPT = "provider_receipt"
    FIXED = "fixed"


class SumbleMcpSettlementRule(BaseModel):
    """How one pinned tool contract proves the realized provider-unit charge."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    mode: SumbleMcpSettlementMode
    credits_used_pointer: str | None = Field(default=None, pattern=r"^(|/.*)$")
    credits_remaining_pointer: str | None = Field(default=None, pattern=r"^(|/.*)$")
    provider_request_id_pointer: str | None = Field(default=None, pattern=r"^(|/.*)$")
    fixed_provider_units: Decimal | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def _coherent(self) -> SumbleMcpSettlementRule:
        if self.mode is SumbleMcpSettlementMode.PROVIDER_RECEIPT:
            if self.credits_used_pointer is None:
                raise ValueError("provider-receipt settlement requires credits_used_pointer")
            if self.fixed_provider_units is not None:
                raise ValueError("provider-receipt settlement cannot carry fixed units")
        elif self.fixed_provider_units is None:
            raise ValueError("fixed settlement requires fixed_provider_units")
        return self


class SumbleMcpInvocationPlan(BaseModel):
    """Exact bounded intent for one account-scoped MCP tool call."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    workspace_id: str = Field(min_length=1)
    project_run_id: ProjectRunId
    account_id: EntityId
    source_key: str = Field(min_length=1)
    tool_name: str = Field(min_length=1)
    arguments: dict[str, JsonValue]
    catalog_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    provider_contract_version: str = Field(min_length=1)
    policy_version: str = Field(min_length=1)
    observation_window: str = Field(min_length=1)
    field_bindings: tuple[SumbleMcpFieldBinding, ...] = Field(min_length=1)
    maximum_provider_units: Decimal = Field(ge=0)
    expected_value_credits: Decimal = Field(ge=0)
    maximum_cost_cents: CostCents = Decimal(0)
    contact_reveal: bool = False
    settlement: SumbleMcpSettlementRule

    @model_validator(mode="after")
    def _coherent(self) -> SumbleMcpInvocationPlan:
        keys = tuple(str(binding.field_key) for binding in self.field_bindings)
        if len(keys) != len(set(keys)) or keys != tuple(sorted(keys)):
            raise ValueError("Sumble MCP field bindings must be unique and sorted")
        if self.expected_value_credits < self.maximum_provider_units:
            raise ValueError("Sumble MCP expected value does not cover maximum provider units")
        if (
            self.settlement.mode is SumbleMcpSettlementMode.FIXED
            and self.settlement.fixed_provider_units is not None
            and self.settlement.fixed_provider_units > self.maximum_provider_units
        ):
            raise ValueError("fixed Sumble MCP charge exceeds the reserved maximum")
        return self

    @property
    def request_fingerprint(self) -> str:
        payload = self.model_dump(mode="json")
        return hashlib.sha256(
            json.dumps(
                payload,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
            ).encode("utf-8")
        ).hexdigest()


class SumbleMcpDurableAuthorization(BaseModel):
    """Proof that the exact plan was durably reserved before dispatch."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    operation_id: str = Field(min_length=1)
    durable_reservation_key: str = Field(min_length=1)
    request_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    catalog_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    provider_units_reserved: Decimal = Field(ge=0)
    cost_cents_reserved: CostCents = Decimal(0)


class SumbleMcpSnapshot(BaseModel):
    """Artifact-backed, replayable result of one governed MCP tool call."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    source_key: str = Field(min_length=1)
    tool_name: str = Field(min_length=1)
    request_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    catalog_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    provider_request_id: str = Field(min_length=1)
    provider_units_charged: Decimal = Field(ge=0)
    credits_remaining: int | None = Field(default=None, ge=0)
    payload: JsonValue
    response_artifact_key: str = Field(min_length=1)
    cost_cents_charged: CostCents = Decimal(0)


class SumbleMcpAcquireState(StrEnum):
    DISPATCH = "dispatch"
    REPLAY = "replay"
    IN_FLIGHT = "in_flight"
    SPEND_OUTCOME_UNKNOWN = "spend_outcome_unknown"


class SumbleMcpAcquireResult(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    state: SumbleMcpAcquireState
    lease_key: str = Field(min_length=1)
    snapshot: SumbleMcpSnapshot | None = None

    @model_validator(mode="after")
    def _shape(self) -> SumbleMcpAcquireResult:
        if (self.state is SumbleMcpAcquireState.REPLAY) != (self.snapshot is not None):
            raise ValueError("only an MCP replay acquire result may carry a snapshot")
        return self


class SumbleMcpInvocationJournal(Protocol):
    """Durable reserve/claim/receipt boundary implemented by the composition root."""

    async def acquire(
        self,
        *,
        plan: SumbleMcpInvocationPlan,
        authorization: SumbleMcpDurableAuthorization,
    ) -> SumbleMcpAcquireResult: ...

    async def commit(
        self,
        *,
        plan: SumbleMcpInvocationPlan,
        authorization: SumbleMcpDurableAuthorization,
        lease_key: str,
        exchange: SumbleMcpToolExchange,
        provider_request_id: str,
        provider_units_charged: Decimal,
        credits_remaining: int | None,
    ) -> SumbleMcpSnapshot: ...

    async def mark_spend_unknown(
        self,
        *,
        plan: SumbleMcpInvocationPlan,
        authorization: SumbleMcpDurableAuthorization,
        lease_key: str,
        failure_code: str,
        exchange: SumbleMcpToolExchange | None,
    ) -> None: ...


class SumbleMcpInvocationClient(Protocol):
    """Narrow client seam used by the governed adapter and provider test doubles."""

    async def initialize(self) -> object: ...

    async def call_tool(
        self,
        name: str,
        arguments: Mapping[str, JsonValue],
    ) -> SumbleMcpToolExchange: ...


class SumbleMcpInvocationOutcome(StrEnum):
    COMPLETED = "completed"
    REPLAYED = "replayed"
    JOINED_IN_FLIGHT = "joined_in_flight"


class SumbleMcpInvocationResult(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    outcome: SumbleMcpInvocationOutcome
    snapshot: SumbleMcpSnapshot | None = None
    provider_calls: int = Field(default=0, ge=0, le=1)


def _json_pointer(document: JsonValue, pointer: str) -> JsonValue:
    if pointer == "":
        return document
    current: Any = document
    for raw in pointer[1:].split("/"):
        token = raw.replace("~1", "/").replace("~0", "~")
        if isinstance(current, dict):
            if token not in current:
                raise KeyError(pointer)
            current = current[token]
        elif isinstance(current, list):
            try:
                index = int(token)
            except ValueError as exc:
                raise KeyError(pointer) from exc
            if index < 0 or index >= len(current):
                raise KeyError(pointer)
            current = current[index]
        else:
            raise KeyError(pointer)
    return cast(JsonValue, current)


def _optional_pointer(document: JsonValue, pointer: str | None) -> JsonValue | None:
    if pointer is None:
        return None
    try:
        return _json_pointer(document, pointer)
    except KeyError:
        return None


def _resolve_local_schema(
    schema: Mapping[str, Any], root_schema: Mapping[str, Any]
) -> Mapping[str, Any]:
    reference = schema.get("$ref")
    if not isinstance(reference, str):
        return schema
    if not reference.startswith("#/"):
        raise SumbleMcpSchemaError("external MCP argument-schema references are unsupported")
    current: Any = root_schema
    for token in reference[2:].split("/"):
        key = token.replace("~1", "/").replace("~0", "~")
        if not isinstance(current, dict) or key not in current:
            raise SumbleMcpSchemaError("MCP argument schema has an unresolved local reference")
        current = current[key]
    if not isinstance(current, dict):
        raise SumbleMcpSchemaError("MCP argument schema reference is not an object")
    return current


def _validate_schema_value(
    value: JsonValue,
    schema: Mapping[str, Any],
    *,
    path: str,
    root_schema: Mapping[str, Any],
) -> None:
    """Conservative local validation for the argument constraints we can enforce exactly.

    Full JSON-Schema evaluation remains the server's responsibility.  We enforce the security-
    relevant object boundary (required keys, declared properties, additionalProperties=false),
    primitive types, arrays, enums, and local allOf/anyOf branches before any paid dispatch.
    """

    schema = _resolve_local_schema(schema, root_schema)
    if "const" in schema and value != schema["const"]:
        raise SumbleMcpSchemaError(f"MCP argument {path} differs from the advertised constant")
    if "enum" in schema and value not in schema["enum"]:
        raise SumbleMcpSchemaError(f"MCP argument {path} is outside the advertised enum")
    if "allOf" in schema:
        for branch in schema["allOf"]:
            if isinstance(branch, dict):
                _validate_schema_value(value, branch, path=path, root_schema=root_schema)
    if "anyOf" in schema:
        errors = 0
        for branch in schema["anyOf"]:
            if not isinstance(branch, dict):
                continue
            try:
                _validate_schema_value(value, branch, path=path, root_schema=root_schema)
                break
            except SumbleMcpSchemaError:
                errors += 1
        else:
            if errors:
                raise SumbleMcpSchemaError(f"MCP argument {path} matches no advertised branch")
    expected = schema.get("type")
    if isinstance(expected, list):
        if value is None and "null" in expected:
            return
        non_null = [item for item in expected if item != "null"]
        if len(non_null) == 1:
            expected = non_null[0]
    if expected == "object":
        if not isinstance(value, dict):
            raise SumbleMcpSchemaError(f"MCP argument {path} must be an object")
        properties = schema.get("properties", {})
        properties = properties if isinstance(properties, dict) else {}
        required = schema.get("required", [])
        if isinstance(required, list):
            missing = [key for key in required if key not in value]
            if missing:
                raise SumbleMcpSchemaError(
                    f"MCP argument {path} omits required keys {sorted(missing)!r}"
                )
        if schema.get("additionalProperties") is False:
            unknown = sorted(set(value) - set(properties))
            if unknown:
                raise SumbleMcpSchemaError(f"MCP argument {path} has undeclared keys {unknown!r}")
        minimum_properties = schema.get("minProperties")
        maximum_properties = schema.get("maxProperties")
        if isinstance(minimum_properties, int) and len(value) < minimum_properties:
            raise SumbleMcpSchemaError(f"MCP argument {path} has too few properties")
        if isinstance(maximum_properties, int) and len(value) > maximum_properties:
            raise SumbleMcpSchemaError(f"MCP argument {path} has too many properties")
        for key, child in value.items():
            child_schema = properties.get(key)
            if isinstance(child_schema, dict):
                _validate_schema_value(
                    child,
                    child_schema,
                    path=f"{path}/{key}",
                    root_schema=root_schema,
                )
    elif expected == "array":
        if not isinstance(value, list):
            raise SumbleMcpSchemaError(f"MCP argument {path} must be an array")
        minimum_items = schema.get("minItems")
        maximum_items = schema.get("maxItems")
        if isinstance(minimum_items, int) and len(value) < minimum_items:
            raise SumbleMcpSchemaError(f"MCP argument {path} has too few items")
        if isinstance(maximum_items, int) and len(value) > maximum_items:
            raise SumbleMcpSchemaError(f"MCP argument {path} has too many items")
        items = schema.get("items")
        if isinstance(items, dict):
            for index, item in enumerate(value):
                _validate_schema_value(
                    item,
                    items,
                    path=f"{path}/{index}",
                    root_schema=root_schema,
                )
    elif expected == "string":
        if not isinstance(value, str):
            raise SumbleMcpSchemaError(f"MCP argument {path} must be a string")
        minimum_length = schema.get("minLength")
        maximum_length = schema.get("maxLength")
        if isinstance(minimum_length, int) and len(value) < minimum_length:
            raise SumbleMcpSchemaError(f"MCP argument {path} is too short")
        if isinstance(maximum_length, int) and len(value) > maximum_length:
            raise SumbleMcpSchemaError(f"MCP argument {path} is too long")
        pattern = schema.get("pattern")
        if isinstance(pattern, str) and re.search(pattern, value) is None:
            raise SumbleMcpSchemaError(f"MCP argument {path} does not match its pattern")
    elif expected == "integer" and (not isinstance(value, int) or isinstance(value, bool)):
        raise SumbleMcpSchemaError(f"MCP argument {path} must be an integer")
    elif expected == "number" and (not isinstance(value, (int, float)) or isinstance(value, bool)):
        raise SumbleMcpSchemaError(f"MCP argument {path} must be numeric")
    elif expected == "boolean" and not isinstance(value, bool):
        raise SumbleMcpSchemaError(f"MCP argument {path} must be boolean")
    elif expected == "null" and value is not None:
        raise SumbleMcpSchemaError(f"MCP argument {path} must be null")
    if expected in {"integer", "number"} and isinstance(value, (int, float)):
        minimum = schema.get("minimum")
        maximum = schema.get("maximum")
        exclusive_minimum = schema.get("exclusiveMinimum")
        exclusive_maximum = schema.get("exclusiveMaximum")
        if isinstance(minimum, (int, float)) and value < minimum:
            raise SumbleMcpSchemaError(f"MCP argument {path} is below its minimum")
        if isinstance(maximum, (int, float)) and value > maximum:
            raise SumbleMcpSchemaError(f"MCP argument {path} exceeds its maximum")
        if isinstance(exclusive_minimum, (int, float)) and value <= exclusive_minimum:
            raise SumbleMcpSchemaError(f"MCP argument {path} is below its exclusive minimum")
        if isinstance(exclusive_maximum, (int, float)) and value >= exclusive_maximum:
            raise SumbleMcpSchemaError(f"MCP argument {path} exceeds its exclusive maximum")


def validate_sumble_mcp_arguments(
    arguments: Mapping[str, JsonValue], descriptor: SumbleMcpToolDescriptor
) -> None:
    _validate_schema_value(
        dict(arguments),
        descriptor.inputSchema,
        path="",
        root_schema=descriptor.inputSchema,
    )


def _settle(
    plan: SumbleMcpInvocationPlan,
    exchange: SumbleMcpToolExchange,
) -> tuple[str, Decimal, int | None]:
    rule = plan.settlement
    if rule.mode is SumbleMcpSettlementMode.FIXED:
        assert rule.fixed_provider_units is not None
        charged = rule.fixed_provider_units
    else:
        try:
            raw = _json_pointer(exchange.payload, rule.credits_used_pointer or "")
            charged = Decimal(str(raw))
        except (KeyError, ValueError, ArithmeticError) as exc:
            raise SumbleMcpSpendOutcomeUnknown(
                "Sumble MCP result lacks its pinned credit receipt"
            ) from exc
    if not charged.is_finite() or charged < 0 or charged > plan.maximum_provider_units:
        raise SumbleMcpSpendOutcomeUnknown(
            "Sumble MCP realized charge is invalid or exceeds the durable reservation"
        )
    remaining: int | None = None
    raw_remaining = _optional_pointer(exchange.payload, rule.credits_remaining_pointer)
    if raw_remaining is not None:
        try:
            if not isinstance(raw_remaining, (str, int, float)) or isinstance(raw_remaining, bool):
                raise TypeError("credits remaining is not scalar")
            remaining = int(raw_remaining)
        except (TypeError, ValueError) as exc:
            raise SumbleMcpSpendOutcomeUnknown(
                "Sumble MCP credits-remaining receipt is not an integer"
            ) from exc
        if remaining < 0:
            raise SumbleMcpSpendOutcomeUnknown("Sumble MCP credits-remaining receipt is negative")
    raw_request_id = _optional_pointer(exchange.payload, rule.provider_request_id_pointer)
    if isinstance(raw_request_id, (str, int, float)) and not isinstance(raw_request_id, bool):
        request_id = (
            str(raw_request_id)
            if str(raw_request_id)
            else (f"mcp:{exchange.session_id or 'stateless'}:{exchange.jsonrpc_request_id}")
        )
    elif raw_request_id is None:
        request_id = f"mcp:{exchange.session_id or 'stateless'}:{exchange.jsonrpc_request_id}"
    else:
        raise SumbleMcpSpendOutcomeUnknown("Sumble MCP provider request id receipt is not scalar")
    return request_id, charged, remaining


class GovernedSumbleMcpAdapter:
    """Single-attempt MCP acquisition guarded by exact policy and durable authorization."""

    def __init__(
        self,
        *,
        client: SumbleMcpInvocationClient,
        journal: SumbleMcpInvocationJournal,
        policy: SumbleMcpPolicy = DEFAULT_SUMBLE_MCP_POLICY,
    ) -> None:
        self._client = client
        self._journal = journal
        self._policy = policy

    async def invoke(
        self,
        *,
        plan: SumbleMcpInvocationPlan,
        authorization: SumbleMcpDurableAuthorization,
        catalog: SumbleMcpToolCatalog,
    ) -> SumbleMcpInvocationResult:
        self._policy.authorize(
            tool_name=plan.tool_name,
            contact_reveal=plan.contact_reveal,
        )
        if plan.policy_version != self._policy.version:
            raise SumbleMcpGovernanceError("Sumble MCP plan uses a different policy version")
        if catalog.fingerprint != plan.catalog_fingerprint:
            raise SumbleMcpGovernanceError("Sumble MCP catalog changed after planning")
        descriptor = catalog.require(plan.tool_name)
        annotations = descriptor.annotations or {}
        if (
            annotations.get("readOnlyHint") is not True
            or annotations.get("destructiveHint") is not False
        ):
            raise SumbleMcpGovernanceError(
                "Sumble MCP paid tool lacks the pinned read-only/non-destructive annotation"
            )
        validate_sumble_mcp_arguments(plan.arguments, descriptor)
        if (
            authorization.request_fingerprint != plan.request_fingerprint
            or authorization.catalog_fingerprint != plan.catalog_fingerprint
            or authorization.provider_units_reserved != plan.maximum_provider_units
            or authorization.cost_cents_reserved != plan.maximum_cost_cents
        ):
            raise SumbleMcpGovernanceError(
                "Sumble MCP durable authorization does not cover the exact plan"
            )
        if _contains_contact_reveal(plan.arguments) and not plan.contact_reveal:
            raise SumbleMcpGovernanceError(
                "Sumble MCP contact-reveal arguments were not declared in the plan"
            )
        # Authentication/session negotiation and catalog discovery are non-paid MCP operations.
        # Complete initialization before taking the durable paid-dispatch lease so an expired
        # OAuth token cannot poison the operation as an unknown spend.
        await self._client.initialize()
        acquire = await self._journal.acquire(plan=plan, authorization=authorization)
        if acquire.state is SumbleMcpAcquireState.REPLAY:
            return SumbleMcpInvocationResult(
                outcome=SumbleMcpInvocationOutcome.REPLAYED,
                snapshot=acquire.snapshot,
                provider_calls=0,
            )
        if acquire.state is SumbleMcpAcquireState.IN_FLIGHT:
            return SumbleMcpInvocationResult(
                outcome=SumbleMcpInvocationOutcome.JOINED_IN_FLIGHT,
                provider_calls=0,
            )
        if acquire.state is SumbleMcpAcquireState.SPEND_OUTCOME_UNKNOWN:
            raise SumbleMcpSpendOutcomeUnknown(
                "Sumble MCP operation already has an unresolved spend outcome"
            )

        exchange: SumbleMcpToolExchange | None = None
        try:
            # There is deliberately no retry here.  Any failure after the journal hands out a
            # dispatch lease can represent a charged call whose response was lost.
            exchange = await self._client.call_tool(plan.tool_name, plan.arguments)
            request_id, charged, remaining = _settle(plan, exchange)
            snapshot = await self._journal.commit(
                plan=plan,
                authorization=authorization,
                lease_key=acquire.lease_key,
                exchange=exchange,
                provider_request_id=request_id,
                provider_units_charged=charged,
                credits_remaining=remaining,
            )
        except Exception as exc:
            await self._journal.mark_spend_unknown(
                plan=plan,
                authorization=authorization,
                lease_key=acquire.lease_key,
                failure_code="sumble_mcp_dispatch_or_receipt_unknown",
                exchange=exchange,
            )
            if isinstance(exc, SumbleMcpSpendOutcomeUnknown):
                raise
            raise SumbleMcpSpendOutcomeUnknown(
                "Sumble MCP call may have consumed credits; automatic retry is disabled"
            ) from exc
        return SumbleMcpInvocationResult(
            outcome=SumbleMcpInvocationOutcome.COMPLETED,
            snapshot=snapshot,
            provider_calls=1,
        )


class SumbleMcpSnapshotLookup(Protocol):
    def snapshot_for(self, entity_id: EntityId, source_key: str) -> SumbleMcpSnapshot | None: ...


class MappingSumbleMcpSnapshotLookup:
    def __init__(self, values: Mapping[tuple[EntityId, str], SumbleMcpSnapshot]) -> None:
        self._values = dict(values)

    def snapshot_for(self, entity_id: EntityId, source_key: str) -> SumbleMcpSnapshot | None:
        return self._values.get((entity_id, source_key))


def normalize_sumble_mcp_snapshot(
    snapshot: SumbleMcpSnapshot,
    field: FieldDef,
    bindings: Mapping[str, SumbleMcpFieldBinding],
) -> list[ResolvedField]:
    binding = bindings.get(str(field.field_key))
    if binding is None:
        return []
    try:
        value = _json_pointer(snapshot.payload, binding.value_pointer)
    except KeyError:
        return []
    if value is None or value == "" or value == []:
        return []
    source_raw = _optional_pointer(snapshot.payload, binding.source_url_pointer)
    source_url = source_raw if isinstance(source_raw, str) and source_raw else SUMBLE_MCP_ENDPOINT
    evidence_raw = _optional_pointer(snapshot.payload, binding.evidence_pointer)
    confidence_raw = _optional_pointer(snapshot.payload, binding.confidence_pointer)
    try:
        if confidence_raw is None:
            confidence = binding.default_confidence
        elif isinstance(confidence_raw, (str, int, float)) and not isinstance(confidence_raw, bool):
            confidence = float(confidence_raw)
        else:
            raise TypeError("confidence is not scalar")
    except (TypeError, ValueError):
        confidence = binding.default_confidence
    if not math.isfinite(confidence):
        confidence = binding.default_confidence
    confidence = min(1.0, max(0.0, confidence))
    item = resolved_field(
        str(field.field_key),
        value,
        source_url=source_url,
        confidence=confidence,
        use_class=binding.use_class,
    )
    if evidence_raw is not None and evidence_raw != "":
        item = item.model_copy(update={"evidence_span": str(evidence_raw)})
    return [item]


class SumbleMcpSnapshotResolver:
    """Tier-1 resolver over a durable MCP snapshot and data-driven field bindings."""

    tier = 1

    def __init__(
        self,
        *,
        source_key: str,
        snapshots: SumbleMcpSnapshotLookup,
        bindings: Sequence[SumbleMcpFieldBinding],
        charge_field: FieldKey,
    ) -> None:
        self._source_key = source_key
        self._snapshots = snapshots
        self._bindings = {str(item.field_key): item for item in bindings}
        if len(self._bindings) != len(bindings):
            raise ValueError("Sumble MCP resolver bindings must be unique")
        self._charge_field = charge_field

    def resolve(self, entity: Entity, field: FieldDef) -> list[Claim]:
        if entity.entity_type is not EntityType.ACCOUNT:
            return []
        snapshot = self._snapshots.snapshot_for(entity.entity_id, self._source_key)
        if snapshot is None:
            return []
        normalized = normalize_sumble_mcp_snapshot(snapshot, field, self._bindings)
        claims = [
            build_claim(
                entity,
                item,
                cost_cents=(
                    snapshot.cost_cents_charged
                    if field.field_key == self._charge_field and index == 0
                    else Decimal(0)
                ),
            )
            for index, item in enumerate(normalized)
        ]
        return [
            revalidate_with(claim, artifact_key=snapshot.response_artifact_key) for claim in claims
        ]


__all__ = [
    "DEFAULT_SUMBLE_MCP_POLICY",
    "GovernedSumbleMcpAdapter",
    "MappingSumbleMcpSnapshotLookup",
    "SumbleMcpAcquireResult",
    "SumbleMcpAcquireState",
    "SumbleMcpDurableAuthorization",
    "SumbleMcpFieldBinding",
    "SumbleMcpGovernanceError",
    "SumbleMcpInvocationJournal",
    "SumbleMcpInvocationClient",
    "SumbleMcpInvocationOutcome",
    "SumbleMcpInvocationPlan",
    "SumbleMcpInvocationResult",
    "SumbleMcpPolicy",
    "SumbleMcpSchemaError",
    "SumbleMcpSettlementMode",
    "SumbleMcpSettlementRule",
    "SumbleMcpSnapshot",
    "SumbleMcpSnapshotLookup",
    "SumbleMcpSnapshotResolver",
    "SumbleMcpSpendOutcomeUnknown",
    "SumbleMcpToolClass",
    "classify_sumble_mcp_tool",
    "normalize_sumble_mcp_snapshot",
    "validate_sumble_mcp_arguments",
]
