"""Production context cards that split account knowledge from project Stage-0 state.

The combined :mod:`clue_projections.stage0` card predates the production conversation envelope and
remains a compatibility source for the trial.  Production composes the two projections here:

* :class:`ClientKnowledgeCard` is reusable across every project in one customer workspace;
* :class:`Stage0ProjectStateCard` contains only the active project's interview/readiness state.

Both are deterministic, hard-bounded read projections.  They authorize nothing: the production
constitution and tool invocation seam retain the trusted workspace/client/project bindings.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue, model_validator

from clue_core import EntityId
from clue_db import ConnFactory, transaction
from clue_research.claimstore import (
    FieldFilters,
    FieldRegistryScope,
    WorkspaceScope,
    claims_for,
    list_effective_fields,
)
from clue_research.identity import get_account
from clue_research.stage0 import (
    CLIENT_BASELINE_FIELDS,
    CLIENT_KB_VERSION,
    read_client_kb_claims,
)

from .stage0 import (
    STAGE0_CARD_POLICY_V1,
    Stage0CardIcp,
    Stage0CardIcpRef,
    Stage0CardInterview,
    Stage0CardOmission,
    Stage0CardOmissionKind,
    Stage0CardPolicy,
    Stage0CardReadiness,
    Stage0CardTooLarge,
    StatementEvidenceReader,
    compile_stage0_project_card,
    encode_card_cursor,
)

CLIENT_KNOWLEDGE_CARD_MEDIA_TYPE = "application/vnd.clue.client-knowledge-card+json"
STAGE0_PROJECT_STATE_CARD_MEDIA_TYPE = "application/vnd.clue.stage0-project-state-card+json"
CLIENT_KNOWLEDGE_CARD_SCHEMA_VERSION: Literal["1"] = "1"
STAGE0_PROJECT_STATE_CARD_SCHEMA_VERSION: Literal["1"] = "1"
STAGE0_PROJECT_STATE_POLICY_VERSION = "stage0-project-state-policy-v1"
PROJECT_CONVERSATION_CARD_MEDIA_TYPE = "application/vnd.clue.project-conversation-card+json"


def _canonical_json(value: object) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode()


def _truncate_utf8(value: str, limit: int) -> tuple[str, bool]:
    raw = value.encode()
    if len(raw) <= limit:
        return value, False
    cut = raw[:limit]
    while cut:
        try:
            return cut.decode(), True
        except UnicodeDecodeError:
            cut = cut[:-1]
    return "", True


def _brief(value: JsonValue) -> str:
    if isinstance(value, str):
        return value
    return _canonical_json(value).decode()


class ClientKnowledgeTopic(StrEnum):
    PRODUCT = "product"
    POSITIONING = "positioning"
    PRICING_AND_PROOF = "pricing_and_proof"
    CUSTOMERS_AND_BUYERS = "customers_and_buyers"
    OTHER = "other"


_FIELD_TOPICS: dict[str, ClientKnowledgeTopic] = {
    "client.product": ClientKnowledgeTopic.PRODUCT,
    "client.value_prop": ClientKnowledgeTopic.PRODUCT,
    "client.differentiator": ClientKnowledgeTopic.POSITIONING,
    "client.competitor": ClientKnowledgeTopic.POSITIONING,
    "client.market_reputation": ClientKnowledgeTopic.POSITIONING,
    "client.pricing_posture": ClientKnowledgeTopic.PRICING_AND_PROOF,
    "client.proof_point": ClientKnowledgeTopic.PRICING_AND_PROOF,
    "client.delivered_value": ClientKnowledgeTopic.PRICING_AND_PROOF,
    "client.customer": ClientKnowledgeTopic.CUSTOMERS_AND_BUYERS,
    "client.icp_evidence": ClientKnowledgeTopic.CUSTOMERS_AND_BUYERS,
    "client.buyer_profile": ClientKnowledgeTopic.CUSTOMERS_AND_BUYERS,
}


class ClientKnowledgeCardPolicy(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    version: str = "client-knowledge-card-policy-v1"
    max_brief_bytes: int = Field(default=256, ge=1)
    max_description_bytes: int = Field(default=320, ge=1)
    max_known_fields_bytes: int = Field(default=8_000, ge=1)
    max_card_bytes: int = Field(default=16_000, ge=1)


CLIENT_KNOWLEDGE_CARD_POLICY_V1 = ClientKnowledgeCardPolicy()


class ContextAvailability(StrEnum):
    AVAILABLE = "available"
    UNAVAILABLE = "unavailable"


class BrandProfileAvailability(StrEnum):
    AVAILABLE = "available"
    MINIMAL = "minimal"
    UNAVAILABLE = "unavailable"


class ProjectConversationProject(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    project_id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    status: str = Field(min_length=1)
    workspace_id: str = Field(min_length=1)
    brand_id: str = Field(min_length=1)
    confirmed_product_id: str | None = None


class ProjectConversationThread(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    thread_id: str = Field(min_length=1)


class ProjectConversationContextAvailability(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    client_knowledge: ContextAvailability
    stage0_project_state: ContextAvailability
    brand_profile: BrandProfileAvailability
    product_profile: ContextAvailability

    @model_validator(mode="after")
    def project_state_requires_client_knowledge(self) -> ProjectConversationContextAvailability:
        if (
            self.stage0_project_state is ContextAvailability.AVAILABLE
            and self.client_knowledge is not ContextAvailability.AVAILABLE
        ):
            raise ValueError("Stage-0 project state cannot be available without Client-KB context")
        return self


class ProjectConversationCard(BaseModel):
    """Always-present L3 envelope: where this conversation is, never what the client knows."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal["2"] = "2"
    card_kind: Literal["project_conversation"] = "project_conversation"
    surface: Literal["project_conversation"] = "project_conversation"
    project: ProjectConversationProject
    thread: ProjectConversationThread
    context_availability: ProjectConversationContextAvailability

    @model_validator(mode="after")
    def product_profile_matches_confirmed_product(self) -> ProjectConversationCard:
        expected = (
            ContextAvailability.AVAILABLE
            if self.project.confirmed_product_id is not None
            else ContextAvailability.UNAVAILABLE
        )
        if self.context_availability.product_profile is not expected:
            raise ValueError("product profile availability must match confirmed product state")
        return self

    def canonical_bytes(self) -> bytes:
        # ``confirmed_product_id: null`` is an intentional, typed unselected state in the frozen
        # v2 contract, so unlike the other cards this canonical form retains null fields.
        return _canonical_json(self.model_dump(mode="json", exclude_none=False))

    def content_sha256(self) -> str:
        return f"sha256:{hashlib.sha256(self.canonical_bytes()).hexdigest()}"


def compile_project_conversation_card(
    *,
    workspace_id: str,
    project_id: str,
    project_name: str,
    project_status: str,
    brand_id: str,
    confirmed_product_id: str | None,
    thread_id: str,
    client_knowledge_available: bool,
    stage0_project_state_available: bool,
    brand_profile: BrandProfileAvailability = BrandProfileAvailability.MINIMAL,
) -> ProjectConversationCard:
    """Compile the v2 envelope from trusted scope plus honest composition availability."""

    return ProjectConversationCard(
        project=ProjectConversationProject(
            project_id=project_id,
            name=project_name,
            status=project_status,
            workspace_id=workspace_id,
            brand_id=brand_id,
            confirmed_product_id=confirmed_product_id,
        ),
        thread=ProjectConversationThread(thread_id=thread_id),
        context_availability=ProjectConversationContextAvailability(
            client_knowledge=(
                ContextAvailability.AVAILABLE
                if client_knowledge_available
                else ContextAvailability.UNAVAILABLE
            ),
            stage0_project_state=(
                ContextAvailability.AVAILABLE
                if stage0_project_state_available
                else ContextAvailability.UNAVAILABLE
            ),
            brand_profile=brand_profile,
            product_profile=(
                ContextAvailability.AVAILABLE
                if confirmed_product_id is not None
                else ContextAvailability.UNAVAILABLE
            ),
        ),
    )


class ClientKnowledgeField(BaseModel):
    """A model-readable index entry, not the full claim."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    field_key: str = Field(min_length=1)
    label: str = Field(min_length=1)
    description: str = Field(min_length=1)
    topic: ClientKnowledgeTopic
    brief_value: str = Field(min_length=1)
    claim_id: str = Field(min_length=1)
    brief_truncated: bool = False
    description_truncated: bool = False
    retired: bool = False


class ClientKnowledgeCoverage(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    baseline_required: int = Field(ge=0)
    baseline_filled: int = Field(ge=0)
    extended_registered: int = Field(ge=0)
    extended_filled: int = Field(ge=0)

    @model_validator(mode="after")
    def filled_counts_do_not_exceed_registered_counts(self) -> ClientKnowledgeCoverage:
        if self.baseline_filled > self.baseline_required:
            raise ValueError("baseline filled count exceeds the required field count")
        if self.extended_filled > self.extended_registered:
            raise ValueError("extended filled count exceeds the registered field count")
        return self


class ClientKnowledgeOmission(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: Literal["client_knowledge_over_cap"]
    count: int = Field(ge=1)
    cursor: str = Field(min_length=1)


class ClientKnowledgeLineage(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    client_kb_version: int = Field(ge=1)
    field_definition_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    compiler_policy_version: str = Field(min_length=1)


class ClientKnowledgeIdentity(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    client_entity_id: str = Field(min_length=1)
    client_kb_version: int = Field(ge=1)


class ClientKnowledgeBody(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    known_fields: tuple[ClientKnowledgeField, ...]
    open_gaps: tuple[str, ...]
    coverage: ClientKnowledgeCoverage


class ClientKnowledgeCard(BaseModel):
    """The reusable, hard-bounded index of one exact account-wide Client-KB version."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal["1"] = CLIENT_KNOWLEDGE_CARD_SCHEMA_VERSION
    card_kind: Literal["client_knowledge"] = "client_knowledge"
    content_semantics: Literal["reference_metadata_is_untrusted_data"] = (
        "reference_metadata_is_untrusted_data"
    )
    compiler_policy_version: str = Field(min_length=1)
    client: ClientKnowledgeIdentity
    knowledge: ClientKnowledgeBody
    omissions: tuple[ClientKnowledgeOmission, ...]
    compiled_from: ClientKnowledgeLineage

    @model_validator(mode="after")
    def lineage_matches_identity_and_policy(self) -> ClientKnowledgeCard:
        if self.client.client_kb_version != self.compiled_from.client_kb_version:
            raise ValueError("Client-KB lineage version must match the client identity pin")
        if self.compiler_policy_version != self.compiled_from.compiler_policy_version:
            raise ValueError("Client-KB lineage policy must match the card policy")
        return self

    def canonical_bytes(self) -> bytes:
        return _canonical_json(self.model_dump(mode="json", exclude_none=True))

    def content_sha256(self) -> str:
        return f"sha256:{hashlib.sha256(self.canonical_bytes()).hexdigest()}"


class Stage0ProjectFieldProposals(BaseModel):
    """Project-originated proposals stay with project state, not the shared Client-KB card."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    pending: int = Field(default=0, ge=0)
    refs: tuple[str, ...] = ()

    @model_validator(mode="after")
    def refs_are_bounded_by_pending_count(self) -> Stage0ProjectFieldProposals:
        if len(self.refs) > self.pending:
            raise ValueError("field proposal refs cannot exceed the pending proposal count")
        return self


class ProjectProductSelectionStatus(StrEnum):
    UNSELECTED = "unselected"
    CONFIRMED = "confirmed"


class Stage0ProductSelection(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    status: ProjectProductSelectionStatus


class Stage0ProjectStateLineage(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    client_knowledge_sha256: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    statement_selection_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    readiness_decision_ids: tuple[str, ...]
    confirmed_icps: tuple[Stage0CardIcpRef, ...]
    compiler_policy_version: str = Field(min_length=1)
    source_policy_version: str = Field(min_length=1)


class Stage0ProjectStateCard(BaseModel):
    """One project's Stage-0 state with no duplicated conversation/client identity payload."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal["1"] = STAGE0_PROJECT_STATE_CARD_SCHEMA_VERSION
    card_kind: Literal["stage0_project_state"] = "stage0_project_state"
    compiler_policy_version: str = Field(min_length=1)
    product_selection: Stage0ProductSelection
    field_proposals: Stage0ProjectFieldProposals
    interview: Stage0CardInterview
    readiness: Stage0CardReadiness
    icp: Stage0CardIcp
    omissions: tuple[Stage0CardOmission, ...]
    compiled_from: Stage0ProjectStateLineage

    @model_validator(mode="after")
    def lineage_policy_matches_card_policy(self) -> Stage0ProjectStateCard:
        if self.compiler_policy_version != self.compiled_from.compiler_policy_version:
            raise ValueError("project-state lineage policy must match the card policy")
        return self

    def canonical_bytes(self) -> bytes:
        return _canonical_json(self.model_dump(mode="json", exclude_none=True))

    def content_sha256(self) -> str:
        return f"sha256:{hashlib.sha256(self.canonical_bytes()).hexdigest()}"


def _field_label(field_key: str) -> str:
    tail = field_key.removeprefix("client.").replace("_", " ").strip()
    return tail.title() if tail else "Client knowledge"


def _definition_digest(definitions: Mapping[str, tuple[str, int, bool]]) -> str:
    return f"sha256:{hashlib.sha256(_canonical_json(definitions)).hexdigest()}"


class ClientKnowledgeScopeError(LookupError):
    """The requested account/version does not belong to the trusted workspace scope."""


def _marker_version(value: JsonValue) -> int | None:
    if not isinstance(value, dict):
        return None
    version = value.get("version")
    return version if isinstance(version, int) and version >= 1 else None


async def compile_client_knowledge_card(
    *,
    workspace_id: str,
    client_entity_id: EntityId,
    client_kb_version: int,
    policy: ClientKnowledgeCardPolicy = CLIENT_KNOWLEDGE_CARD_POLICY_V1,
    conn_factory: ConnFactory = transaction,
) -> ClientKnowledgeCard:
    """Compile one exact Client-KB version without any project-specific state."""

    async with conn_factory() as conn:
        account = await get_account(conn, client_entity_id)
        markers = await claims_for(
            conn,
            client_entity_id,
            CLIENT_KB_VERSION,
            include_superseded=True,
            scope=WorkspaceScope.for_workspace(workspace_id),
        )
        if (
            account is None
            or account.workspace_id != workspace_id
            or not any(
                marker.product_id is None
                and _marker_version(marker.value_json) == client_kb_version
                for marker in markers
            )
        ):
            raise ClientKnowledgeScopeError(
                "the requested account-wide Client-KB version is unavailable in this workspace"
            )
        claims = await read_client_kb_claims(
            conn,
            client_entity_id,
            workspace_id=workspace_id,
            version=client_kb_version,
            product_id=None,
        )
        resolved = await list_effective_fields(
            conn,
            scope=FieldRegistryScope.for_workspace(workspace_id),
            filters=FieldFilters(pack="client", active=None),
            include_retired=True,
        )

    definitions = {item.field_def.field_key: item for item in resolved}
    baseline = [field for field in CLIENT_BASELINE_FIELDS if field in claims]
    extended = sorted(set(claims) - set(CLIENT_BASELINE_FIELDS))
    entries: list[ClientKnowledgeField] = []
    used_bytes = 0
    for field_key in (*baseline, *extended):
        claim = claims[field_key]
        definition = definitions.get(field_key)
        description_source = (
            definition.description
            if definition is not None and definition.description
            else f"Registered Client-KB knowledge for {field_key}."
        )
        description, description_truncated = _truncate_utf8(
            description_source, policy.max_description_bytes
        )
        brief, brief_truncated = _truncate_utf8(_brief(claim.value_json), policy.max_brief_bytes)
        entry = ClientKnowledgeField(
            field_key=field_key,
            label=_field_label(field_key),
            description=description,
            topic=_FIELD_TOPICS.get(field_key, ClientKnowledgeTopic.OTHER),
            brief_value=brief,
            claim_id=str(claim.id),
            brief_truncated=brief_truncated,
            description_truncated=description_truncated,
            retired=definition is not None and not definition.active,
        )
        entry_size = len(_canonical_json(entry.model_dump(mode="json")))
        if used_bytes + entry_size > policy.max_known_fields_bytes:
            break
        used_bytes += entry_size
        entries.append(entry)

    withheld = len(claims) - len(entries)
    omissions = (
        (
            ClientKnowledgeOmission(
                kind="client_knowledge_over_cap",
                count=withheld,
                cursor=encode_card_cursor(
                    {
                        "kind": "client_knowledge",
                        "schema_version": CLIENT_KNOWLEDGE_CARD_SCHEMA_VERSION,
                        "client_entity_id": str(client_entity_id),
                        "client_kb_version": client_kb_version,
                        "compiler_policy_version": policy.version,
                        "after_field_key": entries[-1].field_key if entries else None,
                    }
                ),
            ),
        )
        if withheld
        else ()
    )
    extended_definitions = tuple(
        item for item in resolved if item.field_def.field_key not in CLIENT_BASELINE_FIELDS
    )
    definition_shape = {
        item.field_def.field_key: (item.description or "", item.definition_version, item.active)
        for item in resolved
    }
    card = ClientKnowledgeCard(
        compiler_policy_version=policy.version,
        client=ClientKnowledgeIdentity(
            client_entity_id=str(client_entity_id),
            client_kb_version=client_kb_version,
        ),
        knowledge=ClientKnowledgeBody(
            known_fields=tuple(entries),
            open_gaps=tuple(field for field in CLIENT_BASELINE_FIELDS if field not in claims),
            coverage=ClientKnowledgeCoverage(
                baseline_required=len(CLIENT_BASELINE_FIELDS),
                baseline_filled=sum(field in claims for field in CLIENT_BASELINE_FIELDS),
                extended_registered=len(extended_definitions),
                extended_filled=sum(
                    item.field_def.field_key in claims for item in extended_definitions
                ),
            ),
        ),
        omissions=omissions,
        compiled_from=ClientKnowledgeLineage(
            client_kb_version=client_kb_version,
            field_definition_digest=_definition_digest(definition_shape),
            compiler_policy_version=policy.version,
        ),
    )
    if len(card.canonical_bytes()) > policy.max_card_bytes:
        raise Stage0CardTooLarge(
            f"Client-KB card exceeds {policy.max_card_bytes} bytes after bounded field selection"
        )
    return card


async def compile_stage0_project_state_card(
    *,
    project_id: str,
    workspace_id: str,
    client_entity_id: EntityId,
    client_kb_version: int,
    client_knowledge_sha256: str,
    evidence: StatementEvidenceReader,
    proposals_pending: bool = False,
    proposals_stale: bool = False,
    readiness_spec_version: int | None = None,
    policy: Stage0CardPolicy = STAGE0_CARD_POLICY_V1,
    conn_factory: ConnFactory = transaction,
) -> Stage0ProjectStateCard:
    """Compile the active project's state and discard the compatibility card's account payload."""

    combined = await compile_stage0_project_card(
        project_id=project_id,
        workspace_id=workspace_id,
        client_entity_id=client_entity_id,
        client_kb_version=client_kb_version,
        evidence=evidence,
        # Product confirmation is project-owned durable state. The split compiler never accepts a
        # caller-supplied candidate that could disagree with the active project row.
        product_id=None,
        include_client_knowledge=False,
        proposals_pending=proposals_pending,
        proposals_stale=proposals_stale,
        readiness_spec_version=readiness_spec_version,
        policy=policy,
        conn_factory=conn_factory,
    )
    project_omissions = tuple(
        item
        for item in combined.omissions
        if item.kind is not Stage0CardOmissionKind.CLIENT_KNOWLEDGE_OVER_CAP
    )
    card = Stage0ProjectStateCard(
        compiler_policy_version=STAGE0_PROJECT_STATE_POLICY_VERSION,
        product_selection=Stage0ProductSelection(
            status=(
                ProjectProductSelectionStatus.CONFIRMED
                if combined.product.confirmed
                else ProjectProductSelectionStatus.UNSELECTED
            )
        ),
        field_proposals=Stage0ProjectFieldProposals(
            pending=combined.client_knowledge.pending_field_proposals,
            refs=combined.client_knowledge.pending_field_proposal_refs,
        ),
        interview=combined.interview,
        readiness=combined.readiness,
        icp=combined.icp,
        omissions=project_omissions,
        compiled_from=Stage0ProjectStateLineage(
            client_knowledge_sha256=client_knowledge_sha256,
            statement_selection_digest=combined.compiled_from.statement_selection_digest,
            readiness_decision_ids=combined.compiled_from.readiness_decision_ids,
            confirmed_icps=tuple(combined.compiled_from.confirmed_icps),
            compiler_policy_version=STAGE0_PROJECT_STATE_POLICY_VERSION,
            source_policy_version=policy.version,
        ),
    )
    if len(card.canonical_bytes()) > policy.max_card_bytes:
        raise Stage0CardTooLarge(
            f"Stage-0 project-state card exceeds {policy.max_card_bytes} bytes after split"
        )
    return card


__all__ = [
    "CLIENT_KNOWLEDGE_CARD_MEDIA_TYPE",
    "CLIENT_KNOWLEDGE_CARD_POLICY_V1",
    "PROJECT_CONVERSATION_CARD_MEDIA_TYPE",
    "STAGE0_PROJECT_STATE_CARD_MEDIA_TYPE",
    "BrandProfileAvailability",
    "ClientKnowledgeScopeError",
    "ClientKnowledgeCard",
    "ClientKnowledgeBody",
    "ClientKnowledgeIdentity",
    "ClientKnowledgeCardPolicy",
    "ClientKnowledgeField",
    "ClientKnowledgeTopic",
    "ContextAvailability",
    "ProjectProductSelectionStatus",
    "ProjectConversationCard",
    "Stage0ProjectStateCard",
    "Stage0ProductSelection",
    "compile_client_knowledge_card",
    "compile_project_conversation_card",
    "compile_stage0_project_state_card",
]
