"""Typed execution contract for user-confirmed account-research direction (M8B A2).

A directive is neither memory nor factual evidence.  It is the immutable, versioned execution
input compiled from project context and user instructions.  Scoped memory preserves the advisory
preference for future conversations; a :class:`ResearchDirectivePin` authorizes exactly one frozen
directive version for a run or provider request.
"""

from __future__ import annotations

import hashlib
import json
from decimal import Decimal
from enum import StrEnum
from typing import Annotated, NewType
from uuid import UUID, uuid4

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    model_validator,
)

from clue_core.discovery import Sha256Hex
from clue_core.enums import UseClass
from clue_core.primitives import EntityId, UtcDatetime

ResearchDirectiveId = NewType("ResearchDirectiveId", UUID)
ResearchDirectiveOverrideId = NewType("ResearchDirectiveOverrideId", UUID)
RESEARCH_DIRECTIVE_BODY_MAX_BYTES = 48_000
EFFECTIVE_RESEARCH_DIRECTIVE_MAX_BYTES = 64_000
USER_RESEARCH_INSTRUCTION_MAX_BYTES = 8_000
NonEmptyStr = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=2_000),
]
StableKey = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=255),
]


def _canonical_json_size(value: object) -> int:
    return len(
        json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
    )


class ResearchSealedSelectionRef(BaseModel):
    """An immutable discovery seal, never an opaque caller-authored selection label."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    discovery_batch_id: UUID
    discovery_seal_sha256: Sha256Hex

    @property
    def ref(self) -> str:
        return f"discovery-seal:{self.discovery_batch_id}:{self.discovery_seal_sha256}"

    @classmethod
    def parse(cls, value: str) -> ResearchSealedSelectionRef:
        prefix, separator, remainder = value.partition(":")
        batch, second_separator, digest = remainder.partition(":")
        if prefix != "discovery-seal" or not separator or not second_separator:
            raise ValueError(
                "sealed research selection must be discovery-seal:<batch_uuid>:<seal_sha256>"
            )
        return cls(discovery_batch_id=UUID(batch), discovery_seal_sha256=digest)


def new_research_directive_id() -> ResearchDirectiveId:
    return ResearchDirectiveId(uuid4())


def new_research_directive_override_id() -> ResearchDirectiveOverrideId:
    return ResearchDirectiveOverrideId(uuid4())


class ResearchDirectiveStatus(StrEnum):
    DRAFT = "draft"
    CONFIRMED = "confirmed"
    SUPERSEDED = "superseded"


class ResearchQuestion(BaseModel):
    """A search question, never an assertion that its hoped-for answer is true."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    question_id: StableKey
    text: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2_000)]
    target_field_key: StableKey | None = None
    target_facet: StableKey | None = None
    priority: int = Field(default=3, ge=1, le=5)
    source_family_hints: tuple[StableKey, ...] = Field(default=(), max_length=16)
    stop_rule: Annotated[
        str,
        StringConstraints(strip_whitespace=True, min_length=1, max_length=1_000),
    ] = "stop when grounded or terminally unsupported"

    @model_validator(mode="after")
    def _target_and_hints_are_bounded(self) -> ResearchQuestion:
        if not (self.target_field_key or self.target_facet):
            raise ValueError("research question requires a target field or facet")
        if len(set(self.source_family_hints)) != len(self.source_family_hints):
            raise ValueError("research question source-family hints must be unique")
        return self


class ResearchAccountScope(BaseModel):
    """The exact account selection described by a project directive."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    explicit_account_ids: tuple[EntityId, ...] = Field(default=(), max_length=500)
    sealed_selection_ref: (
        Annotated[
            str,
            StringConstraints(strip_whitespace=True, min_length=1, max_length=1_000),
        ]
        | None
    ) = None

    @model_validator(mode="after")
    def _exactly_one_scope_kind(self) -> ResearchAccountScope:
        explicit = bool(self.explicit_account_ids)
        sealed = bool(self.sealed_selection_ref and self.sealed_selection_ref.strip())
        if explicit == sealed:
            raise ValueError(
                "research account scope requires explicit ids or one sealed selection reference"
            )
        if len(set(self.explicit_account_ids)) != len(self.explicit_account_ids):
            raise ValueError("research account scope ids must be unique")
        if self.sealed_selection_ref is not None:
            ResearchSealedSelectionRef.parse(self.sealed_selection_ref)
        return self


class ResearchCommitteePlan(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    functions: tuple[StableKey, ...] = Field(default=(), max_length=32)
    levels: tuple[StableKey, ...] = Field(default=(), max_length=32)
    teams: tuple[StableKey, ...] = Field(default=(), max_length=32)
    personas: tuple[StableKey, ...] = Field(default=(), max_length=32)
    candidate_cap: int = Field(default=20, ge=1, le=200)
    relationship_depth: int = Field(default=1, ge=0, le=2)

    @model_validator(mode="after")
    def _selectors_are_unique(self) -> ResearchCommitteePlan:
        for label, values in (
            ("functions", self.functions),
            ("levels", self.levels),
            ("teams", self.teams),
            ("personas", self.personas),
        ):
            if len(set(values)) != len(values):
                raise ValueError(f"committee {label} must be unique")
        return self


class ResearchSourcePolicy(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    allowed_source_keys: tuple[StableKey, ...] = Field(max_length=64)
    preferred_source_keys: tuple[StableKey, ...] = Field(default=(), max_length=64)
    excluded_source_keys: tuple[StableKey, ...] = Field(default=(), max_length=64)
    use_primary_source_for_contradictions: bool = True

    @model_validator(mode="after")
    def _sets_are_coherent(self) -> ResearchSourcePolicy:
        allowed = set(self.allowed_source_keys)
        preferred = set(self.preferred_source_keys)
        excluded = set(self.excluded_source_keys)
        if not allowed:
            raise ValueError("research source policy requires at least one allowed source")
        if any(
            len(set(values)) != len(values)
            for values in (
                self.allowed_source_keys,
                self.preferred_source_keys,
                self.excluded_source_keys,
            )
        ):
            raise ValueError("research source-policy lists must not contain duplicates")
        if not preferred <= allowed:
            raise ValueError("preferred research sources must also be allowed")
        if allowed & excluded:
            raise ValueError("a research source cannot be both allowed and excluded")
        return self


class ResearchPrivacyPolicy(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    account_research_allowed: bool = True
    committee_discovery_allowed: bool = True
    contact_profiling_allowed: bool = False
    contact_reveals_allowed: bool = False
    allowed_use_classes: tuple[UseClass, ...] = (UseClass.PROFESSIONAL_PUBLIC,)
    exclusions: tuple[NonEmptyStr, ...] = Field(default=(), max_length=64)

    @model_validator(mode="after")
    def _privacy_is_coherent(self) -> ResearchPrivacyPolicy:
        if len(set(self.allowed_use_classes)) != len(self.allowed_use_classes):
            raise ValueError("research privacy use classes must be unique")
        if self.contact_reveals_allowed and not self.contact_profiling_allowed:
            raise ValueError("contact reveals cannot be allowed when contact profiling is excluded")
        return self


class ResearchEffortPolicy(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    tier: StableKey
    max_depth: int = Field(ge=0, le=4)
    max_fanout: int = Field(ge=1, le=64)
    budget_cap_cents: Decimal = Field(ge=0, le=100_000_000)
    budget_envelope_ref: StableKey
    recursion_policy_ref: StableKey
    freshness_policy_ref: StableKey


class ResearchDirectiveBody(BaseModel):
    """The immutable executable content of one directive version."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    account_scope: ResearchAccountScope
    field_keys: tuple[StableKey, ...] = Field(max_length=128)
    questions: tuple[ResearchQuestion, ...] = Field(default=(), max_length=64)
    committee_plan: ResearchCommitteePlan
    source_policy: ResearchSourcePolicy
    privacy_policy: ResearchPrivacyPolicy
    effort_policy: ResearchEffortPolicy
    exclusions: tuple[NonEmptyStr, ...] = Field(default=(), max_length=64)

    @model_validator(mode="after")
    def _keys_are_unique(self) -> ResearchDirectiveBody:
        if not self.field_keys and not self.questions:
            raise ValueError("research directive requires at least one field or question")
        if len(set(self.field_keys)) != len(self.field_keys):
            raise ValueError("research directive field keys must be unique")
        question_ids = tuple(item.question_id for item in self.questions)
        if len(set(question_ids)) != len(question_ids):
            raise ValueError("research directive question ids must be unique")
        size = _canonical_json_size(self.model_dump(mode="json"))
        if size > RESEARCH_DIRECTIVE_BODY_MAX_BYTES:
            raise ValueError(
                "research directive body exceeds its "
                f"{RESEARCH_DIRECTIVE_BODY_MAX_BYTES}-byte execution-context contract"
            )
        return self


class ResearchDirective(BaseModel):
    """One durable directive version; lifecycle fields never affect its execution digest."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    directive_id: ResearchDirectiveId
    workspace_id: NonEmptyStr
    project_id: NonEmptyStr
    product_id: NonEmptyStr
    icp_key: NonEmptyStr
    icp_version: int = Field(ge=1)
    version: int = Field(ge=1)
    status: ResearchDirectiveStatus
    body: ResearchDirectiveBody
    memory_refs: tuple[NonEmptyStr, ...] = Field(default=(), max_length=64)
    created_by: NonEmptyStr
    source_turn_ref: NonEmptyStr
    predecessor_id: ResearchDirectiveId | None = None
    canonical_json_sha256: Sha256Hex
    created_at: UtcDatetime
    confirmed_by: str | None = None
    confirming_turn_ref: str | None = None
    confirmed_at: UtcDatetime | None = None

    def execution_payload(self) -> dict[str, object]:
        return {
            "directive_id": str(self.directive_id),
            "workspace_id": self.workspace_id,
            "project_id": self.project_id,
            "product_id": self.product_id,
            "icp_key": self.icp_key,
            "icp_version": self.icp_version,
            "version": self.version,
            "body": self.body.model_dump(mode="json"),
            "memory_refs": list(self.memory_refs),
            "source_turn_ref": self.source_turn_ref,
            "predecessor_id": str(self.predecessor_id) if self.predecessor_id else None,
        }

    def expected_sha256(self) -> str:
        encoded = json.dumps(
            self.execution_payload(),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    @model_validator(mode="after")
    def _digest_and_lifecycle_are_coherent(self) -> ResearchDirective:
        if self.canonical_json_sha256 != self.expected_sha256():
            raise ValueError("research directive digest does not match its executable content")
        confirmation = (self.confirmed_by, self.confirming_turn_ref, self.confirmed_at)
        if self.status is ResearchDirectiveStatus.DRAFT and any(
            item is not None for item in confirmation
        ):
            raise ValueError("draft directive cannot carry confirmation fields")
        if self.status is not ResearchDirectiveStatus.DRAFT and any(
            item is None for item in confirmation
        ):
            raise ValueError("confirmed/superseded directive requires confirmation fields")
        if len(set(self.memory_refs)) != len(self.memory_refs):
            raise ValueError("research directive memory refs must be unique")
        return self

    @property
    def directive_ref(self) -> str:
        return f"research-directive:{self.directive_id}:v{self.version}"


class ResearchDirectiveAccountOverrideBody(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    include_field_keys: tuple[StableKey, ...] = Field(default=(), max_length=128)
    exclude_field_keys: tuple[StableKey, ...] = Field(default=(), max_length=128)
    additional_questions: tuple[ResearchQuestion, ...] = Field(default=(), max_length=64)
    exclude_question_ids: tuple[StableKey, ...] = Field(default=(), max_length=64)
    source_policy: ResearchSourcePolicy | None = None
    committee_plan: ResearchCommitteePlan | None = None
    effort_policy: ResearchEffortPolicy | None = None
    exclusions: tuple[NonEmptyStr, ...] = Field(default=(), max_length=64)

    @model_validator(mode="after")
    def _override_is_coherent(self) -> ResearchDirectiveAccountOverrideBody:
        included = set(self.include_field_keys)
        excluded = set(self.exclude_field_keys)
        if len(included) != len(self.include_field_keys):
            raise ValueError("override included field keys must be unique")
        if len(excluded) != len(self.exclude_field_keys):
            raise ValueError("override excluded field keys must be unique")
        if included & excluded:
            raise ValueError("an override field cannot be both included and excluded")
        question_ids = tuple(item.question_id for item in self.additional_questions)
        if len(set(question_ids)) != len(question_ids):
            raise ValueError("override question ids must be unique")
        if len(set(self.exclude_question_ids)) != len(self.exclude_question_ids):
            raise ValueError("override excluded question ids must be unique")
        return self


class ResearchDirectiveAccountOverride(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    override_id: ResearchDirectiveOverrideId
    directive_id: ResearchDirectiveId
    workspace_id: NonEmptyStr
    account_id: EntityId
    body: ResearchDirectiveAccountOverrideBody
    created_by: NonEmptyStr
    source_turn_ref: NonEmptyStr
    canonical_json_sha256: Sha256Hex
    created_at: UtcDatetime

    def expected_sha256(self) -> str:
        payload = {
            "override_id": str(self.override_id),
            "directive_id": str(self.directive_id),
            "workspace_id": self.workspace_id,
            "account_id": str(self.account_id),
            "body": self.body.model_dump(mode="json"),
            "source_turn_ref": self.source_turn_ref,
        }
        encoded = json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    @model_validator(mode="after")
    def _digest_is_coherent(self) -> ResearchDirectiveAccountOverride:
        if self.canonical_json_sha256 != self.expected_sha256():
            raise ValueError("research directive override digest does not match its content")
        return self

    @property
    def override_ref(self) -> str:
        return f"research-directive-override:{self.override_id}"


class ResearchDirectivePin(BaseModel):
    """The complete immutable identity stored on a run, plan, or provider request."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    directive_id: ResearchDirectiveId
    directive_ref: NonEmptyStr
    version: int = Field(ge=1)
    canonical_json_sha256: Sha256Hex
    account_id: EntityId
    override_id: ResearchDirectiveOverrideId | None = None
    override_ref: str | None = None
    override_sha256: Sha256Hex | None = None

    @model_validator(mode="after")
    def _override_pin_is_all_or_none(self) -> ResearchDirectivePin:
        expected_directive_ref = f"research-directive:{self.directive_id}:v{self.version}"
        if self.directive_ref != expected_directive_ref:
            raise ValueError("research directive ref does not match its id/version")
        values = (self.override_id, self.override_ref, self.override_sha256)
        if any(item is not None for item in values) and any(item is None for item in values):
            raise ValueError("research directive override pin must be all-or-none")
        if self.override_id is not None and self.override_ref != (
            f"research-directive-override:{self.override_id}"
        ):
            raise ValueError("research directive override ref does not match its id")
        return self

    @classmethod
    def from_records(
        cls,
        directive: ResearchDirective,
        override: ResearchDirectiveAccountOverride | None = None,
        *,
        account_id: EntityId | None = None,
        allow_superseded: bool = False,
        allow_draft: bool = False,
    ) -> ResearchDirectivePin:
        """Freeze one account's exact directive revision.

        ``allow_draft`` exists for exactly one caller (FI Lane D D4): a confirmation gate has to
        *price* the draft it is asking the human to approve, and pricing needs the same effective
        composition execution needs. It is a pricing relaxation only — a pin derived this way names
        a draft revision, so it must never be frozen onto an account run. Every path that does
        freeze one (``pin_account_run_research_directive``, through the launcher) leaves this
        ``False``, which keeps "only a confirmed directive executes" exactly as strict as it was.
        """

        allowed_statuses = {ResearchDirectiveStatus.CONFIRMED}
        if allow_superseded:
            allowed_statuses.add(ResearchDirectiveStatus.SUPERSEDED)
        if allow_draft:
            allowed_statuses.add(ResearchDirectiveStatus.DRAFT)
        if directive.status not in allowed_statuses:
            raise ValueError("only a confirmed research directive can be pinned")
        if override is not None and override.directive_id != directive.directive_id:
            raise ValueError("research directive override belongs to another directive")
        resolved_account_id = account_id or (override.account_id if override is not None else None)
        if (
            resolved_account_id is None
            and len(directive.body.account_scope.explicit_account_ids) == 1
        ):
            resolved_account_id = directive.body.account_scope.explicit_account_ids[0]
        if resolved_account_id is None:
            raise ValueError("research directive pin requires one exact account id")
        if override is not None and override.account_id != resolved_account_id:
            raise ValueError("research directive override belongs to another account")
        return cls(
            directive_id=directive.directive_id,
            directive_ref=directive.directive_ref,
            version=directive.version,
            canonical_json_sha256=directive.canonical_json_sha256,
            account_id=resolved_account_id,
            override_id=override.override_id if override else None,
            override_ref=override.override_ref if override else None,
            override_sha256=override.canonical_json_sha256 if override else None,
        )


class EffectiveAccountResearchDirective(BaseModel):
    """The deterministic project directive plus one separately pinned account override."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    workspace_id: NonEmptyStr
    project_id: NonEmptyStr
    product_id: NonEmptyStr
    account_id: EntityId
    icp_key: NonEmptyStr
    icp_version: int = Field(ge=1)
    pin: ResearchDirectivePin
    field_keys: tuple[StableKey, ...] = Field(max_length=128)
    questions: tuple[ResearchQuestion, ...] = Field(max_length=128)
    committee_plan: ResearchCommitteePlan
    source_policy: ResearchSourcePolicy
    privacy_policy: ResearchPrivacyPolicy
    effort_policy: ResearchEffortPolicy
    exclusions: tuple[NonEmptyStr, ...] = Field(default=(), max_length=128)

    @model_validator(mode="after")
    def _effective_work_is_non_empty(self) -> EffectiveAccountResearchDirective:
        if not self.field_keys and not self.questions:
            raise ValueError("effective account research directive cannot be empty")
        if self.pin.account_id != self.account_id:
            raise ValueError("effective directive pin belongs to another account")
        size = _canonical_json_size(self.model_dump(mode="json"))
        if size > EFFECTIVE_RESEARCH_DIRECTIVE_MAX_BYTES:
            raise ValueError(
                "effective account research directive exceeds its "
                f"{EFFECTIVE_RESEARCH_DIRECTIVE_MAX_BYTES}-byte execution-context contract"
            )
        return self


def compose_account_research_directive(
    directive: ResearchDirective,
    *,
    account_id: EntityId,
    override: ResearchDirectiveAccountOverride | None = None,
    allow_superseded: bool = False,
    allow_draft: bool = False,
) -> EffectiveAccountResearchDirective:
    """Layer one immutable account override without mutating the project directive.

    ``allow_draft`` is the FI Lane D D4 pricing relaxation described on
    :meth:`ResearchDirectivePin.from_records`: a directive-confirmation gate must compute its
    maximum spend from the *draft* it is presenting, and it must compute it with this composition
    rather than a second one, or the number on the gate and the number the launcher verifies could
    drift. Composing is not authorizing — every execution path keeps this ``False``.
    """

    allowed_statuses = {ResearchDirectiveStatus.CONFIRMED}
    if allow_superseded:
        allowed_statuses.add(ResearchDirectiveStatus.SUPERSEDED)
    if allow_draft:
        allowed_statuses.add(ResearchDirectiveStatus.DRAFT)
    if directive.status not in allowed_statuses:
        raise ValueError("effective account direction requires a confirmed directive")
    if directive.body.account_scope.explicit_account_ids and (
        account_id not in directive.body.account_scope.explicit_account_ids
    ):
        raise ValueError("account is outside the directive's explicit scope")
    if override is not None and (
        override.directive_id != directive.directive_id or override.account_id != account_id
    ):
        raise ValueError("account override does not belong to this directive/account")

    body = directive.body
    override_body = override.body if override else ResearchDirectiveAccountOverrideBody()
    if override_body.source_policy is not None:
        project_allowed = set(body.source_policy.allowed_source_keys)
        override_allowed = set(override_body.source_policy.allowed_source_keys)
        if not override_allowed <= project_allowed:
            raise ValueError("account source-policy override may only narrow project sources")
    excluded_fields = set(override_body.exclude_field_keys)
    fields = tuple(
        dict.fromkeys(
            field
            for field in (*body.field_keys, *override_body.include_field_keys)
            if field not in excluded_fields
        )
    )
    excluded_questions = set(override_body.exclude_question_ids)
    questions = tuple(
        item
        for item in (*body.questions, *override_body.additional_questions)
        if item.question_id not in excluded_questions
    )
    if len({item.question_id for item in questions}) != len(questions):
        raise ValueError("project and account directive question ids collide")
    return EffectiveAccountResearchDirective(
        workspace_id=directive.workspace_id,
        project_id=directive.project_id,
        product_id=directive.product_id,
        account_id=account_id,
        icp_key=directive.icp_key,
        icp_version=directive.icp_version,
        pin=ResearchDirectivePin.from_records(
            directive,
            override,
            account_id=account_id,
            allow_superseded=allow_superseded,
            allow_draft=allow_draft,
        ),
        field_keys=fields,
        questions=questions,
        committee_plan=override_body.committee_plan or body.committee_plan,
        source_policy=override_body.source_policy or body.source_policy,
        privacy_policy=body.privacy_policy,
        effort_policy=override_body.effort_policy or body.effort_policy,
        exclusions=tuple(dict.fromkeys((*body.exclusions, *override_body.exclusions))),
    )


def research_directive_digest(
    *,
    directive_id: ResearchDirectiveId,
    workspace_id: str,
    project_id: str,
    product_id: str,
    icp_key: str,
    icp_version: int,
    version: int,
    body: ResearchDirectiveBody,
    memory_refs: tuple[str, ...],
    source_turn_ref: str,
    predecessor_id: ResearchDirectiveId | None,
) -> str:
    """Compute the digest before constructing the self-validating durable model."""

    payload = {
        "directive_id": str(directive_id),
        "workspace_id": workspace_id,
        "project_id": project_id,
        "product_id": product_id,
        "icp_key": icp_key,
        "icp_version": icp_version,
        "version": version,
        "body": body.model_dump(mode="json"),
        "memory_refs": list(memory_refs),
        "source_turn_ref": source_turn_ref,
        "predecessor_id": str(predecessor_id) if predecessor_id else None,
    }
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def research_directive_override_digest(
    *,
    override_id: ResearchDirectiveOverrideId,
    directive_id: ResearchDirectiveId,
    workspace_id: str,
    account_id: EntityId,
    body: ResearchDirectiveAccountOverrideBody,
    source_turn_ref: str,
) -> str:
    payload = {
        "override_id": str(override_id),
        "directive_id": str(directive_id),
        "workspace_id": workspace_id,
        "account_id": str(account_id),
        "body": body.model_dump(mode="json"),
        "source_turn_ref": source_turn_ref,
    }
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


__all__ = [
    "EFFECTIVE_RESEARCH_DIRECTIVE_MAX_BYTES",
    "RESEARCH_DIRECTIVE_BODY_MAX_BYTES",
    "USER_RESEARCH_INSTRUCTION_MAX_BYTES",
    "EffectiveAccountResearchDirective",
    "ResearchAccountScope",
    "ResearchCommitteePlan",
    "ResearchDirective",
    "ResearchDirectiveAccountOverride",
    "ResearchDirectiveAccountOverrideBody",
    "ResearchDirectiveBody",
    "ResearchDirectiveId",
    "ResearchDirectiveOverrideId",
    "ResearchDirectivePin",
    "ResearchDirectiveStatus",
    "ResearchEffortPolicy",
    "ResearchPrivacyPolicy",
    "ResearchQuestion",
    "ResearchSealedSelectionRef",
    "ResearchSourcePolicy",
    "compose_account_research_directive",
    "new_research_directive_id",
    "new_research_directive_override_id",
    "research_directive_digest",
    "research_directive_override_digest",
]
