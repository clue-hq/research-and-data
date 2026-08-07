"""Typed rows and immutable payloads for Phase-C field/source proposals."""

from __future__ import annotations

import re
from decimal import Decimal
from enum import StrEnum
from typing import Literal
from urllib.parse import urlsplit

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    ValidationInfo,
    field_validator,
    model_validator,
)

from clue_core import (
    CostCents,
    EntityScope,
    EqualityMode,
    FieldClass,
    FieldDef,
    IdentityBinding,
    Modality,
    ReuseScope,
    UtcDatetime,
    VolunteeredStatementId,
    classify_field_key,
    field_namespace,
    is_field_key_or_class,
    normalize_host,
)
from clue_core.proposals import (
    FieldProposalId,
    ProposalAuthority,
    ProposalStatus,
    SourceProposalId,
)

_SOURCE_KEY_RE = re.compile(r"^[a-z][a-z0-9_]*$")
_AUTH_REF_RE = re.compile(r"^CLUE_[A-Z][A-Z0-9_]*$")
SENSITIVE_OUTREACH_DISABLED_GATE = "outreach-disabled"


class ClientKbFieldSpec(BaseModel):
    """Immutable materialization value and downstream-authority declarations."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    candidate_value: JsonValue
    source_statement_id: VolunteeredStatementId
    intended_use: str = Field(min_length=1, max_length=1_000)
    client_kb_role: Literal["extended"] = "extended"
    non_expiring_rationale: str | None = Field(default=None, max_length=1_000)
    readiness_requested: bool = False
    scoring_authoritative: bool = False
    qualification_authoritative: bool = False
    outreach_authoritative: bool = False
    compliance_authoritative: bool = False
    contains_personal_data: bool = False
    introduces_new_source: bool = False
    elevates_source_trust: bool = False


class ProposalDecision(StrEnum):
    PROMOTE = "promote"
    REJECT = "reject"
    WITHDRAW = "withdraw"


class ProposalScope(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    workspace_id: str
    brand_id: str
    product_id: str | None = None
    project_id: str | None = None
    icp_key: str | None = None
    icp_spec_version: int | None = Field(default=None, ge=1)

    @model_validator(mode="after")
    def _check_icp_pair(self) -> ProposalScope:
        if (self.icp_key is None) != (self.icp_spec_version is None):
            raise ValueError("icp_key and icp_spec_version must be supplied together")
        return self


class FieldProposalPayload(BaseModel):
    """The complete field-registry write, staged immutably before promotion."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    field_def: FieldDef
    value_schema: dict[str, JsonValue] | None = None
    corroboration_min: int = Field(default=1, ge=1)
    single_source_sufficient: bool = False
    equality_mode: EqualityMode = EqualityMode.EXACT
    description: str | None = None
    pack: str | None = None
    version: int = Field(default=1, ge=1)
    sensitive: bool = False
    rationale: str
    evidence_refs: tuple[str, ...] = ()
    client_kb: ClientKbFieldSpec | None = None

    @model_validator(mode="after")
    def _check_namespace_and_reuse(self, info: ValidationInfo) -> FieldProposalPayload:
        field_class = classify_field_key(self.field_def.field_key)
        namespace = field_namespace(self.field_def.field_key)
        if field_class is FieldClass.PACK:
            if self.pack != namespace:
                raise ValueError(
                    f"pack field {self.field_def.field_key!r} must declare pack={namespace!r}"
                )
            if self.field_def.reuse_scope is None:
                raise ValueError(
                    f"pack field {self.field_def.field_key!r} must explicitly declare reuse_scope"
                )
            # Species has no ratified default for a vertical pack either (FI-2 P3), and
            # ``register_field`` refuses one at promotion — so refuse it here, before a proposal is
            # durably staged with a frozen payload and approved by a human it can never satisfy.
            # ``client.*`` (the tenant-local dynamic Client-KB namespace) is exempt: it is
            # workspace-scoped by construction and ratified project_neutral (FI-2 §5.2).
            if self.field_def.research_scope is None and namespace != "client":
                raise ValueError(
                    f"pack field {self.field_def.field_key!r} must explicitly declare "
                    "research_scope"
                )
        elif self.pack is not None:
            raise ValueError("canonical field namespaces must not declare a pack")
        if self.sensitive and self.field_def.gate != SENSITIVE_OUTREACH_DISABLED_GATE:
            raise ValueError("sensitive fields must declare gate='outreach-disabled'")
        if self.field_def.field_key.startswith("client."):
            if self.field_def.field_key == "client.kb_version":
                raise ValueError("client.kb_version is platform-owned internal vocabulary")
            if self.pack != "client":
                raise ValueError("dynamic Client-KB fields must declare pack='client'")
            if self.field_def.reuse_scope is not ReuseScope.TENANT_PRIVATE:
                raise ValueError("dynamic Client-KB fields must declare reuse_scope=tenant_private")
            if self.client_kb is None:
                if info.context and info.context.get("allow_legacy_promoted_client_field"):
                    return self
                raise ValueError("dynamic Client-KB fields require client_kb proposal details")
            if not self.description:
                raise ValueError("dynamic Client-KB fields require a semantic description")
            if not self.evidence_refs:
                raise ValueError("dynamic Client-KB fields require durable evidence_refs")
            statement_ref = f"volunteered_statement:{self.client_kb.source_statement_id}"
            if statement_ref not in self.evidence_refs:
                raise ValueError(
                    "dynamic Client-KB evidence_refs must include the canonical "
                    "volunteered_statement:<source_statement_id> ref"
                )
            if self.field_def.freshness_ttl is None and not self.client_kb.non_expiring_rationale:
                raise ValueError(
                    "a non-expiring dynamic Client-KB field requires non_expiring_rationale"
                )
        elif self.client_kb is not None:
            raise ValueError("client_kb proposal details are valid only for client.* fields")
        return self


class SourceManifestDraft(BaseModel):
    """A source manifest without an assigned trust tier.

    The proposer describes capability. The decision service supplies ``tier`` under the authority
    matrix, so an agent-controlled payload can never award itself trust.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    source_key: str
    modality: Modality
    entity_scope: EntityScope
    yields: tuple[str, ...] = ()
    cost_cents: CostCents = Decimal(0)
    latency_ms: int | None = Field(default=None, ge=0)
    geo_coverage: tuple[str, ...] = ()
    freshness_profile: str | None = None
    identity_binding_strength: IdentityBinding | None = None
    active: bool = True
    provider: str | None = None
    auth_ref: str | None = None
    rate_limit: dict[str, JsonValue] | None = None
    requires_adapter: str | None = None
    version: int = Field(default=1, ge=1)

    @field_validator("source_key")
    @classmethod
    def _source_key_shape(cls, value: str) -> str:
        if not _SOURCE_KEY_RE.fullmatch(value):
            raise ValueError("source_key must be a lowercase identifier")
        return value

    @field_validator("yields")
    @classmethod
    def _yield_shapes(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        invalid = tuple(value for value in values if not is_field_key_or_class(value))
        if invalid:
            raise ValueError(f"invalid source yields: {invalid}")
        return values

    @field_validator("auth_ref")
    @classmethod
    def _auth_ref_shape(cls, value: str | None) -> str | None:
        if value is not None and not _AUTH_REF_RE.fullmatch(value):
            raise ValueError("auth_ref must be a CLUE_* credential reference, never a secret")
        return value


class SourceProposalPayload(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    manifest: SourceManifestDraft
    discovery_url: str
    discovery_domain: str
    capability_description: str
    rationale: str
    evidence_refs: tuple[str, ...] = ()

    @model_validator(mode="after")
    def _check_discovery_target(self) -> SourceProposalPayload:
        parsed = urlsplit(self.discovery_url)
        if parsed.username is not None or parsed.password is not None:
            raise ValueError("discovery_url must not contain credentials")
        url_host = normalize_host(self.discovery_url)
        declared_host = normalize_host(self.discovery_domain)
        if not url_host or not declared_host or url_host != declared_host:
            raise ValueError("discovery_url must match discovery_domain")
        return self


class FieldProposal(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    id: FieldProposalId
    scope: ProposalScope
    payload: FieldProposalPayload
    payload_hash: str
    status: ProposalStatus
    proposed_by_actor: str
    proposed_by_ref: str | None = None
    proposed_at: UtcDatetime
    required_authority: ProposalAuthority
    decided_by: str | None = None
    decision_authority: ProposalAuthority | None = None
    decided_at: UtcDatetime | None = None
    decision_reason: str | None = None
    applied_field_key: str | None = None
    applied_version: int | None = None


class SourceProposal(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    id: SourceProposalId
    scope: ProposalScope
    payload: SourceProposalPayload
    payload_hash: str
    status: ProposalStatus
    proposed_by_actor: str
    proposed_by_ref: str | None = None
    proposed_at: UtcDatetime
    required_authority: ProposalAuthority
    decided_by: str | None = None
    decision_authority: ProposalAuthority | None = None
    decided_at: UtcDatetime | None = None
    decision_reason: str | None = None
    assigned_tier: int | None = None
    applied_source_key: str | None = None
    applied_version: int | None = None
    yield_observations: int = 0
    yield_rate: float | None = None
    demoted_at: UtcDatetime | None = None
    demoted_by: str | None = None
    demotion_reason: str | None = None
    demoted_version: int | None = None


class SourceDemotionResult(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    proposal_id: SourceProposalId
    source_key: str
    observations: int
    yield_rate: float | None = None
    demoted: bool = False
    applied_version: int | None = None


def source_yields_personal_data(payload: SourceProposalPayload) -> bool:
    for token in payload.manifest.yields:
        if token == FieldClass.CONTACT.value or token == FieldClass.CONTACT_FACET.value:
            return True
        if token.startswith("contact."):
            return True
    return False


__all__ = [
    "ClientKbFieldSpec",
    "FieldProposal",
    "FieldProposalPayload",
    "ProposalDecision",
    "ProposalScope",
    "SourceDemotionResult",
    "SourceManifestDraft",
    "SourceProposal",
    "SourceProposalPayload",
    "SENSITIVE_OUTREACH_DISABLED_GATE",
    "source_yields_personal_data",
]
