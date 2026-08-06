"""M8D R7 exact contact selection and separately confirmed fleet launch.

The older M8C receipt remains the provider/channel authority.  R7 generalizes its target shape to
committee and explicitly user-selected associated contacts, validates every identity/association
claim against current Postgres state, and projects each target into the R0/R2 shared-fleet
contract without granting one contact another contact's fields, sources, facets, channels, or
budget.

Selection and launch are distinct durable human actions.  This module performs no provider call
and constructs no contact agent; R8 owns the contact ``create_agent()`` composition.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Annotated, Self
from uuid import NAMESPACE_URL, UUID, uuid5

from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_config import OverlayStore, get_config
from clue_core import (
    ClaimId,
    ContactChannelAuthorization,
    ContactResearchIntent,
    ContactResearchPolicyPin,
    ContactResearchSelection,
    ContactResearchSelectionBody,
    ContactResearchSelectionId,
    ContactResearchTarget,
    EntityId,
    FieldClass,
    FieldKey,
    IdentityBinding,
    ProjectRunId,
    ResearchDirectiveStatus,
    RunId,
    classify_field_key,
)
from clue_core.contact_research import ContactChannel as SelectionContactChannel
from clue_core.entity_research import (
    ContactChannel as EntityContactChannel,
)
from clue_core.entity_research import (
    EntityResearchJobAuthorization,
    EntityResearchSelection,
    FieldSourceAuthority,
    ResearchOperationKind,
    ResearchRunKind,
    ResearchRunLifecycleContract,
    ResearchSelectionBasis,
    ResearchSubjectType,
    SelectedContactResearchAuthority,
    SelectedResearchSubject,
)
from clue_db import ConnFactory, transaction
from clue_fleet import (
    EntityResearchJobEnvelope,
    EntityResearchRunEnvelope,
    launch_entity_research_run,
)
from clue_research.claimstore import WorkspaceScope, claims_by_ids
from clue_research.directives import effective_account_research_directive, get_research_directive
from clue_research.durable import (
    ContactResearchSelectionApprovalAuthority,
    ContactResearchSelectionApprovalKind,
    ContactResearchSelectionAuthorityRecord,
    ContactResearchSelectionNotFound,
    contact_research_selection_authority,
    get_account_run,
    get_project_run,
    latest_contact_research_selection,
    store_contact_research_selection,
)
from clue_research.durable.enums import ProjectRunStatus
from clue_research.identity import get_account, get_contact
from clue_research.profiling.committee import (
    ORGANIZATION_RELATIONSHIP,
    PERSONA,
    ROLE_ON_COMMITTEE,
)
from clue_research.profiling.committee.admission import DISCOVERY_PROVENANCE_FIELD

Money = Annotated[Decimal, Field(ge=0)]

_SELECTION_NAMESPACE = uuid5(NAMESPACE_URL, "clue:m8d:r7:contact-selection")
_RUN_NAMESPACE = uuid5(NAMESPACE_URL, "clue:m8d:r7:contact-research-run")
_JOB_NAMESPACE = uuid5(NAMESPACE_URL, "clue:m8d:r7:contact-research-job")
_ATTEMPT_NAMESPACE = uuid5(NAMESPACE_URL, "clue:m8d:r7:contact-research-attempt")
_LEASE_NAMESPACE = uuid5(NAMESPACE_URL, "clue:m8d:r7:contact-research-lease")
_CONTACT_PROFILE_REF = "agent-profile:contact-research:v1"


class ContactResearchSelectionApprovalError(RuntimeError):
    pass


class ContactResearchFleetLaunchError(RuntimeError):
    pass


def _sha(value: object) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
            default=str,
        ).encode()
    ).hexdigest()


def _content_ref(prefix: str, value: object) -> str:
    return f"{prefix}:{_sha(value)}"


def _unique[ValueT](values: Iterable[ValueT]) -> tuple[ValueT, ...]:
    return tuple(dict.fromkeys(values))


def contact_research_profile_sha256(catalog_root: Path | None = None) -> str:
    root = catalog_root or (
        Path(__file__).parents[2] / "agents" / "catalog" / "entity-research" / "contact" / "v1"
    )
    return hashlib.sha256((root / "profile.md").read_bytes()).hexdigest()


class ContactResearchTargetApproval(BaseModel):
    """One user-chosen exact contact and its target-local execution authority."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    contact_entity_id: UUID
    selection_basis: ResearchSelectionBasis
    strong_identity_claim_ids: tuple[UUID, ...] = Field(min_length=1)
    association_evidence_claim_ids: tuple[UUID, ...] = Field(min_length=1)
    committee_claim_ids: tuple[UUID, ...] = ()
    field_keys: tuple[str, ...] = Field(min_length=1, max_length=32)
    field_source_authority: tuple[FieldSourceAuthority, ...] = Field(
        min_length=1,
        max_length=32,
    )
    directional_question_ids: tuple[str, ...] = Field(min_length=1, max_length=32)
    facet_keys: tuple[str, ...] = Field(default=(), max_length=32)
    exa_max_results: int = Field(default=50, ge=1, le=50)
    budget_cap_cents: Money
    email: ContactChannelAuthorization = Field(
        default_factory=lambda: ContactChannelAuthorization(channel=SelectionContactChannel.EMAIL)
    )
    phone: ContactChannelAuthorization = Field(
        default_factory=lambda: ContactChannelAuthorization(channel=SelectionContactChannel.PHONE)
    )

    @model_validator(mode="after")
    def _request_is_exact(self) -> Self:
        if self.selection_basis is ResearchSelectionBasis.ACCOUNT_SELECTION:
            raise ValueError("contact selection requires a contact selection basis")
        for values, message in (
            (self.strong_identity_claim_ids, "strong identity claims must be unique"),
            (self.association_evidence_claim_ids, "association claims must be unique"),
            (self.committee_claim_ids, "committee claims must be unique"),
            (self.field_keys, "contact fields must be unique"),
            (
                tuple(item.field_key for item in self.field_source_authority),
                "contact field source authority must be unique",
            ),
            (self.directional_question_ids, "contact questions must be unique"),
            (self.facet_keys, "contact facets must be unique"),
        ):
            if len(values) != len(set(values)):
                raise ValueError(message)
        if self.budget_cap_cents <= 0:
            raise ValueError("a selected contact requires a positive bounded research budget")
        research_fields = {value for value in self.field_keys if value.startswith("contact.")}
        if {item.field_key for item in self.field_source_authority} != research_fields:
            raise ValueError(
                "contact field source authority must exactly cover selected research fields"
            )
        expected_facets = {
            value
            for value in self.field_keys
            if classify_field_key(value) is FieldClass.CONTACT_FACET
        }
        if set(self.facet_keys) != expected_facets:
            raise ValueError("contact facet authority must exactly match selected facet fields")
        if (
            self.selection_basis is ResearchSelectionBasis.COMMITTEE_MEMBER
            and not self.committee_claim_ids
        ):
            raise ValueError("committee selection requires committee claims")
        if (
            self.selection_basis is ResearchSelectionBasis.USER_SELECTED_ASSOCIATED_CONTACT
            and self.committee_claim_ids
        ):
            raise ValueError("non-committee selection cannot carry committee claims")
        return self


class ContactResearchSelectionApprovalRequest(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    workspace_id: str = Field(min_length=1)
    project_run_id: UUID
    account_run_id: UUID
    account_entity_id: UUID
    targets: tuple[ContactResearchTargetApproval, ...] = Field(min_length=1, max_length=20)

    @model_validator(mode="after")
    def _contacts_are_unique(self) -> Self:
        ids = tuple(target.contact_entity_id for target in self.targets)
        if len(ids) != len(set(ids)):
            raise ValueError("contact selection cannot repeat a canonical contact")
        return self


class ContactResearchFleetLaunchRequest(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    workspace_id: str = Field(min_length=1)
    selection_id: UUID
    selection_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    approved_budget_cap_cents: Annotated[Decimal, Field(gt=0)]
    expected_estimated_cost_cents: Annotated[Decimal, Field(gt=0)]
    concurrency_limit: int = Field(default=8, ge=1, le=32)


class ContactResearchJobLaunchProjection(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    job_id: UUID
    contact_entity_id: UUID
    parent_account_id: UUID
    selection_basis: ResearchSelectionBasis
    contact_intent_ref: str
    contact_intent_sha256: str
    field_keys: tuple[str, ...]
    research_questions: tuple[str, ...]
    source_keys: tuple[str, ...]
    field_source_authority: tuple[FieldSourceAuthority, ...]
    facet_keys: tuple[str, ...]
    channel_permissions: tuple[EntityContactChannel, ...]
    channel_source_keys: tuple[str, ...]
    policy_refs: tuple[str, ...]
    approval_refs: tuple[str, ...]
    budget_cap_cents: Decimal
    state: str


class ContactResearchFleetLaunchProjection(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    research_run_id: UUID
    workspace_id: str
    project_id: str
    product_id: str
    project_run_id: UUID
    account_entity_id: UUID
    contact_selection_id: UUID
    contact_selection_sha256: str
    run_state: str
    budget_cap_cents: Decimal
    concurrency_limit: int
    jobs: tuple[ContactResearchJobLaunchProjection, ...]


class ContactResearchSelectionApprover:
    """Compile current database authority into one immutable M8C selection receipt."""

    def __init__(
        self,
        *,
        conn_factory: ConnFactory = transaction,
        config_store: OverlayStore | None = None,
    ) -> None:
        self._conn_factory = conn_factory
        self._config_store = config_store

    async def approve(
        self,
        request: ContactResearchSelectionApprovalRequest,
        *,
        approved_by: str,
        action_ref: str,
        approval_operation_id: UUID,
        approved_at: datetime,
    ) -> ContactResearchSelection:
        if not approved_by.strip() or not action_ref.strip() or approved_at.utcoffset() is None:
            raise ContactResearchSelectionApprovalError(
                "contact selection requires attributable timezone-aware human approval"
            )
        async with self._conn_factory() as conn:
            await conn.execute(
                text("SELECT pg_advisory_xact_lock(hashtextextended(:scope, 0))"),
                {
                    "scope": (
                        f"contact-selection-approval:{request.workspace_id}:{approval_operation_id}"
                    )
                },
            )
            replay = (
                await conn.execute(
                    text(
                        "SELECT selection.id FROM contact_research_selection_approval approval "
                        "JOIN contact_research_selection selection "
                        "ON selection.approval_id=approval.id "
                        "WHERE approval.workspace_id=:workspace_id "
                        "AND approval.account_id=:account_id "
                        "AND approval.approval_operation_id=:operation_id"
                    ),
                    {
                        "workspace_id": request.workspace_id,
                        "account_id": request.account_entity_id,
                        "operation_id": approval_operation_id,
                    },
                )
            ).scalar_one_or_none()
            body, policy = await self._compile_body(
                conn,
                request=request,
                approved_by=approved_by,
                approved_at=approved_at,
                approval_operation_id=approval_operation_id,
            )
            if replay is not None:
                authority = await contact_research_selection_authority(
                    conn,
                    workspace_id=request.workspace_id,
                    selection_id=ContactResearchSelectionId(replay),
                )
                if authority.selection.body != body or authority.action_ref != action_ref:
                    raise ContactResearchSelectionApprovalError(
                        "contact selection approval operation was replayed with changed authority"
                    )
                return authority.selection

            head = await latest_contact_research_selection(
                conn,
                workspace_id=request.workspace_id,
                project_run_id=ProjectRunId(request.project_run_id),
                account_id=EntityId(request.account_entity_id),
                include_cancelled=True,
            )
            if head is not None and bool(
                (
                    await conn.execute(
                        text(
                            "SELECT EXISTS (SELECT 1 FROM entity_research_run run "
                            "JOIN entity_research_job job USING (research_run_id) "
                            "WHERE run.workspace_id=:workspace_id "
                            "AND run.contact_selection_id=:selection_id "
                            "AND job.state <> 'terminal')"
                        ),
                        {
                            "workspace_id": request.workspace_id,
                            "selection_id": head.selection_id,
                        },
                    )
                ).scalar_one()
            ):
                raise ContactResearchSelectionApprovalError(
                    "active contact research must be cancelled or terminal before selecting "
                    "a successor"
                )
            selection_id = ContactResearchSelectionId(
                uuid5(
                    _SELECTION_NAMESPACE,
                    f"{approval_operation_id}:{body.sha256()}",
                )
            )
            selection = ContactResearchSelection.from_body(
                body,
                effective_policy=policy,
                selection_id=selection_id,
            )
            return await store_contact_research_selection(
                conn,
                selection,
                account_run_id=RunId(request.account_run_id),
                predecessor_id=(head.selection_id if head is not None else None),
                approval=ContactResearchSelectionApprovalAuthority(
                    kind=(
                        ContactResearchSelectionApprovalKind.HUMAN_SUCCESSOR
                        if head is not None
                        else ContactResearchSelectionApprovalKind.HUMAN_INITIAL
                    ),
                    operation_id=approval_operation_id,
                    approved_by=approved_by,
                    action_ref=action_ref,
                    approved_at=approved_at,
                ),
            )

    async def _compile_body(
        self,
        conn: AsyncConnection,
        *,
        request: ContactResearchSelectionApprovalRequest,
        approved_by: str,
        approved_at: datetime,
        approval_operation_id: UUID,
    ) -> tuple[ContactResearchSelectionBody, ContactResearchPolicyPin]:
        account_run = await get_account_run(conn, RunId(request.account_run_id))
        project_run = await get_project_run(conn, ProjectRunId(request.project_run_id))
        account = await get_account(conn, EntityId(request.account_entity_id))
        if (
            account_run is None
            or project_run is None
            or account is None
            or project_run.workspace_id != request.workspace_id
            or project_run.product_id is None
            or project_run.status is ProjectRunStatus.FAILED
            or account.workspace_id != request.workspace_id
            or account.merged_into is not None
            or account_run.project_run_id != request.project_run_id
            or account_run.entity_id != request.account_entity_id
            or account_run.research_directive is None
        ):
            raise ContactResearchSelectionApprovalError(
                "contact selection lacks one exact live account/project/directive scope"
            )
        pin = account_run.research_directive
        directive = await get_research_directive(
            conn,
            pin.directive_id,
            workspace_id=request.workspace_id,
        )
        if (
            directive is None
            or directive.status is ResearchDirectiveStatus.DRAFT
            or directive.project_id != project_run.project_id
            or directive.product_id != project_run.product_id
        ):
            raise ContactResearchSelectionApprovalError(
                "contact selection requires a confirmed directive pinned to the project run"
            )
        effective = await effective_account_research_directive(
            conn,
            workspace_id=request.workspace_id,
            directive_id=pin.directive_id,
            account_id=EntityId(request.account_entity_id),
            expected_pin=pin,
        )
        if not effective.privacy_policy.contact_profiling_allowed:
            raise ContactResearchSelectionApprovalError(
                "the exact directive does not authorize contact profiling"
            )
        config = get_config(
            request.workspace_id,
            effective.icp_key,
            store=self._config_store,
        )
        policy = config.contact_research_policy.pin()
        allowed_fields = {str(value) for value in effective.field_keys}
        questions = {item.question_id: item for item in effective.questions}
        allowed_sources = set(effective.source_policy.allowed_source_keys)
        targets: list[ContactResearchTarget] = []
        for requested in request.targets:
            contact = await get_contact(conn, EntityId(requested.contact_entity_id))
            if (
                contact is None
                or contact.workspace_id != request.workspace_id
                or contact.account_entity_id != request.account_entity_id
                or contact.merged_into is not None
                or not (contact.linkedin_url or contact.verified_email)
            ):
                raise ContactResearchSelectionApprovalError(
                    f"contact {requested.contact_entity_id} is not strongly resolved "
                    "under the account"
                )
            if not set(requested.field_keys).issubset(allowed_fields):
                raise ContactResearchSelectionApprovalError(
                    f"contact {requested.contact_entity_id} widens the directive field plan"
                )
            if any(
                str(value) not in set(requested.field_keys)
                for value in (
                    question.target_field_key
                    or (
                        question.target_facet
                        if str(question.target_facet).startswith("contact.")
                        else f"contact.facet.{question.target_facet}"
                    )
                    for question_id in requested.directional_question_ids
                    for question in (questions.get(question_id),)
                    if question is not None
                )
            ) or any(
                question_id not in questions for question_id in requested.directional_question_ids
            ):
                raise ContactResearchSelectionApprovalError(
                    f"contact {requested.contact_entity_id} has an unknown or cross-field question"
                )
            if requested.exa_max_results > policy.exa_max_results:
                raise ContactResearchSelectionApprovalError(
                    "contact selection exceeds the effective Exa result cap"
                )
            if (requested.email.allowed or requested.phone.allowed) and not (
                effective.privacy_policy.contact_reveals_allowed and policy.contact_reveals_enabled
            ):
                raise ContactResearchSelectionApprovalError(
                    "contact selection requested a policy-disabled channel reveal"
                )
            claim_ids = {
                ClaimId(value)
                for value in (
                    *requested.strong_identity_claim_ids,
                    *requested.association_evidence_claim_ids,
                    *requested.committee_claim_ids,
                )
            }
            claims = await claims_by_ids(
                conn,
                tuple(claim_ids),
                scope=WorkspaceScope.for_workspace(request.workspace_id),
            )
            if len(claims) != len(claim_ids) or any(
                claim.entity_id != requested.contact_entity_id for claim in claims.values()
            ):
                raise ContactResearchSelectionApprovalError(
                    f"contact {requested.contact_entity_id} evidence is missing, stale, or foreign"
                )
            strong = {ClaimId(value) for value in requested.strong_identity_claim_ids}
            if any(
                claim.id in strong
                and claim.field_key != DISCOVERY_PROVENANCE_FIELD
                and claim.identity_binding is not IdentityBinding.STRONG
                for claim in claims.values()
            ):
                raise ContactResearchSelectionApprovalError(
                    f"contact {requested.contact_entity_id} lacks strong identity evidence"
                )
            association = {ClaimId(value) for value in requested.association_evidence_claim_ids}
            if any(
                claim.id in association
                and str(claim.field_key)
                not in {DISCOVERY_PROVENANCE_FIELD, ORGANIZATION_RELATIONSHIP}
                for claim in claims.values()
            ):
                raise ContactResearchSelectionApprovalError(
                    f"contact {requested.contact_entity_id} lacks current-employer evidence"
                )
            committee = {ClaimId(value) for value in requested.committee_claim_ids}
            committee_fields = {
                str(claim.field_key) for claim in claims.values() if claim.id in committee
            }
            if requested.selection_basis is ResearchSelectionBasis.COMMITTEE_MEMBER and (
                not {ROLE_ON_COMMITTEE, PERSONA}.issubset(committee_fields)
                or any(
                    claim.id in committee and claim.run_id != request.account_run_id
                    for claim in claims.values()
                )
            ):
                raise ContactResearchSelectionApprovalError(
                    f"contact {requested.contact_entity_id} lacks exact committee authority"
                )
            budget_ref = _content_ref(
                "contact-target-budget",
                {
                    "approval_operation_id": str(approval_operation_id),
                    "contact_id": str(requested.contact_entity_id),
                    "budget_cap_cents": requested.budget_cap_cents,
                },
            )
            target = ContactResearchTarget(
                contact_entity_id=EntityId(requested.contact_entity_id),
                selection_basis=requested.selection_basis,
                committee_claim_ids=tuple(
                    ClaimId(value) for value in requested.committee_claim_ids
                ),
                strong_identity_claim_ids=tuple(
                    ClaimId(value) for value in requested.strong_identity_claim_ids
                ),
                association_evidence_claim_ids=tuple(
                    ClaimId(value) for value in requested.association_evidence_claim_ids
                ),
                field_keys=tuple(FieldKey(value) for value in requested.field_keys),
                field_source_authority=requested.field_source_authority,
                directional_question_ids=requested.directional_question_ids,
                facet_keys=tuple(FieldKey(value) for value in requested.facet_keys),
                exa_max_results=requested.exa_max_results,
                research_budget_envelope_ref=budget_ref,
                research_budget_cap_cents=requested.budget_cap_cents,
                email=requested.email,
                phone=requested.phone,
            )
            intent_sources = self._target_source_keys(target, policy)
            if not intent_sources or not set(intent_sources).issubset(allowed_sources):
                raise ContactResearchSelectionApprovalError(
                    f"contact {requested.contact_entity_id} source plan exceeds the directive"
                )
            targets.append(target)
        total_budget = sum((target.research_budget_cap_cents for target in targets), Decimal(0))
        body = ContactResearchSelectionBody(
            workspace_id=request.workspace_id,
            project_id=effective.project_id,
            project_run_id=ProjectRunId(request.project_run_id),
            account_entity_id=EntityId(request.account_entity_id),
            research_directive=pin,
            targets=tuple(targets),
            policy=policy,
            source_profile_ref=_content_ref(
                "contact-source-policy", effective.source_policy.model_dump(mode="json")
            ),
            jurisdiction_policy_ref=_content_ref(
                "jurisdiction-policy", config.policy.model_dump(mode="json")
            ),
            use_policy_ref=_content_ref(
                "contact-use-policy",
                tuple(value.value for value in effective.privacy_policy.allowed_use_classes),
            ),
            retention_policy_ref=(
                f"contact-retention:{policy.channel_retention_days}d:{policy.sha256()}"
            ),
            budget_reservation_ref=_content_ref(
                "contact-selection-budget",
                {
                    "approval_operation_id": str(approval_operation_id),
                    "total_budget_cents": total_budget,
                },
            ),
            budget_cap_cents=total_budget,
            approved_by=approved_by,
            approved_at=approved_at,
        )
        return body, policy

    @staticmethod
    def _target_source_keys(
        target: ContactResearchTarget, policy: ContactResearchPolicyPin
    ) -> tuple[str, ...]:
        # Constructing the intent is circular until the selection exists.  This is the same closed
        # mapping enforced again by ContactResearchIntent after the receipt is built.
        field_tokens = {str(value) for value in target.field_keys}
        values: list[str] = []
        if target.field_source_authority:
            values.extend(
                source
                for authority in target.field_source_authority
                for source in authority.source_keys
            )
        elif field_tokens.intersection(
            {
                "contact.current_title",
                "contact.job_function",
                "contact.job_level",
                "contact.team_membership",
                "contact.current_location",
                "contact.organization_relationship",
            }
        ):
            values.extend(policy.professional_source_plan)
        if not target.field_source_authority and any(
            classify_field_key(value) is FieldClass.CONTACT_FACET for value in target.field_keys
        ):
            values.extend(policy.personal_facet_source_plan)
        for authorization in (target.email, target.phone):
            if authorization.allowed:
                values.extend(authorization.provider_source_keys)
                values.extend(authorization.validation_source_keys)
        return tuple(dict.fromkeys(values))


class ContactResearchFleetLauncher:
    """Project one active approved selection into a separately launched R2 contact run."""

    def __init__(self, *, conn_factory: ConnFactory = transaction) -> None:
        self._conn_factory = conn_factory

    async def launch(
        self,
        request: ContactResearchFleetLaunchRequest,
        *,
        actor: str,
        source_action_ref: str,
        source_operation_id: UUID,
        confirmed_at: datetime,
    ) -> ContactResearchFleetLaunchProjection:
        if not actor.strip() or not source_action_ref.strip() or confirmed_at.utcoffset() is None:
            raise ContactResearchFleetLaunchError(
                "contact launch requires attributable timezone-aware human confirmation"
            )
        async with self._conn_factory() as conn:
            await conn.execute(
                text("SELECT pg_advisory_xact_lock(hashtextextended(:scope, 0))"),
                {
                    "scope": (
                        f"contact-research-launch:{request.workspace_id}:{source_operation_id}"
                    )
                },
            )
            try:
                authority = await contact_research_selection_authority(
                    conn,
                    workspace_id=request.workspace_id,
                    selection_id=ContactResearchSelectionId(request.selection_id),
                )
            except ContactResearchSelectionNotFound as error:
                raise ContactResearchFleetLaunchError(
                    "contact launch has no durable selection authority"
                ) from error
            selection = authority.selection
            body = selection.body
            # Serialize launch against selection cancellation and successor approval. All three
            # paths use this exact scope key, so a cancellation cannot commit between the active
            # authority check and the deferred contact-run completeness check.
            await conn.execute(
                text("SELECT pg_advisory_xact_lock(hashtextextended(:scope, 0))"),
                {
                    "scope": (
                        f"{request.workspace_id}:{body.project_run_id}:{body.account_entity_id}"
                    )
                },
            )
            request_sha = _sha(
                {
                    "request": request.model_dump(mode="json"),
                    "actor": actor,
                    "source_action_ref": source_action_ref,
                    "source_operation_id": str(source_operation_id),
                    "confirmed_at": confirmed_at,
                    "selection_approval_id": str(authority.approval_id),
                }
            )
            operation_replay = (
                (
                    await conn.execute(
                        text(
                            "SELECT research_run_id, request_sha256 FROM "
                            "entity_research_contact_launch WHERE workspace_id=:workspace_id "
                            "AND source_operation_id=:operation_id"
                        ),
                        {
                            "workspace_id": request.workspace_id,
                            "operation_id": source_operation_id,
                        },
                    )
                )
                .mappings()
                .one_or_none()
            )
            if operation_replay is not None:
                if operation_replay["request_sha256"] != request_sha:
                    raise ContactResearchFleetLaunchError(
                        "contact launch operation was replayed with changed authority"
                    )
                return await self._projection(conn, operation_replay["research_run_id"])
            if (
                selection.selection_sha256 != request.selection_sha256
                or authority.cancelled
                or not authority.current_head
            ):
                raise ContactResearchFleetLaunchError(
                    "contact launch requires the exact active current selection"
                )
            if (
                authority.approval_kind
                is ContactResearchSelectionApprovalKind.DIRECTIVE_CONFIRMATION
            ):
                raise ContactResearchFleetLaunchError(
                    "contact launch requires an explicit human contact-selection approval"
                )
            if any(
                not target.field_source_authority
                or not target.directional_question_ids
                or target.research_budget_envelope_ref is None
                or target.research_budget_cap_cents <= 0
                or set(target.facet_keys) != set(target.effective_facet_keys)
                for target in body.targets
            ):
                raise ContactResearchFleetLaunchError(
                    "contact launch selection lacks complete exact target authority"
                )
            project_run = await get_project_run(conn, body.project_run_id)
            account_run = await get_account_run(conn, authority.account_run_id)
            if (
                project_run is None
                or account_run is None
                or project_run.workspace_id != request.workspace_id
                or project_run.product_id is None
                or project_run.status is ProjectRunStatus.FAILED
                or account_run.project_run_id != body.project_run_id
                or account_run.entity_id != body.account_entity_id
                or account_run.research_directive != body.research_directive
            ):
                raise ContactResearchFleetLaunchError(
                    "contact launch selection is outside its account/project authority"
                )
            estimated = body.execution_budget_cap_cents
            if (
                request.expected_estimated_cost_cents != estimated
                or request.approved_budget_cap_cents != estimated
            ):
                raise ContactResearchFleetLaunchError(
                    "contact launch budget must equal the reviewed exact target budget sum"
                )
            if project_run.budget_cap_cents is not None and request.approved_budget_cap_cents > max(
                Decimal(0), project_run.budget_cap_cents - project_run.spent_cents
            ):
                raise ContactResearchFleetLaunchError(
                    "contact launch exceeds remaining project budget headroom"
                )
            research_run_id = uuid5(_RUN_NAMESPACE, request_sha)
            subjects: list[SelectedResearchSubject] = []
            jobs: list[EntityResearchJobEnvelope] = []
            intents: dict[UUID, ContactResearchIntent] = {}
            target_authorities: dict[UUID, SelectedContactResearchAuthority] = {}
            for target in body.targets:
                intent = ContactResearchIntent.from_selection(
                    selection,
                    contact_entity_id=target.contact_entity_id,
                )
                contact_id = UUID(str(target.contact_entity_id))
                intents[contact_id] = intent
                questions_by_id = {
                    item.question_id: item.text
                    for item in (
                        await effective_account_research_directive(
                            conn,
                            workspace_id=request.workspace_id,
                            directive_id=body.research_directive.directive_id,
                            account_id=body.account_entity_id,
                            expected_pin=body.research_directive,
                        )
                    ).questions
                }
                question_texts = tuple(
                    questions_by_id[value] for value in target.directional_question_ids
                )
                field_authority = self._field_source_authority(target, body)
                research_fields = tuple(
                    str(value) for value in target.field_keys if str(value).startswith("contact.")
                )
                facets = tuple(str(value) for value in target.effective_facet_keys)
                channels = tuple(
                    channel
                    for channel, allowed in (
                        (EntityContactChannel.EMAIL, target.email.allowed),
                        (EntityContactChannel.PHONE, target.phone.allowed),
                    )
                    if allowed
                )
                approval_refs = (
                    f"contact-selection-approval:{authority.approval_id}",
                    f"contact-launch-operation:{source_operation_id}",
                    authority.action_ref,
                    source_action_ref,
                )
                policy_refs = (
                    body.source_profile_ref,
                    body.jurisdiction_policy_ref,
                    body.use_policy_ref,
                    body.retention_policy_ref,
                    body.policy.freshness_policy_ref,
                    f"contact-policy:{body.policy.sha256()}",
                )
                target_authority = SelectedContactResearchAuthority(
                    contact_selection_ref=(f"contact-selection:{selection.selection_id}"),
                    contact_selection_sha256=selection.selection_sha256,
                    contact_intent_ref=f"contact-intent:{intent.sha256()}",
                    contact_intent_sha256=intent.sha256(),
                    field_plan_ref=_content_ref("contact-field-plan", research_fields),
                    source_plan_ref=_content_ref(
                        "contact-source-plan",
                        tuple(item.model_dump(mode="json") for item in field_authority),
                    ),
                    admitted_field_keys=research_fields,
                    admitted_source_keys=tuple(
                        dict.fromkeys(
                            source for item in field_authority for source in item.source_keys
                        )
                    ),
                    field_source_authority=field_authority,
                    research_questions=question_texts,
                    facet_keys=facets,
                    channel_permissions=channels,
                    channel_source_keys=tuple(
                        dict.fromkeys(
                            source
                            for authorization in (target.email, target.phone)
                            if authorization.allowed
                            for source in (
                                *authorization.provider_source_keys,
                                *authorization.validation_source_keys,
                            )
                        )
                    ),
                    policy_refs=policy_refs,
                    budget_envelope_ref=intent.budget_reservation_ref,
                    budget_cap_cents=target.execution_budget_cap_cents,
                    approval_refs=approval_refs,
                )
                target_authorities[contact_id] = target_authority
                subjects.append(
                    SelectedResearchSubject(
                        subject_entity_id=contact_id,
                        basis=target.selection_basis,
                        strong_identity_claim_refs=tuple(
                            f"claim:{value}" for value in target.strong_identity_claim_ids
                        ),
                        association_evidence_refs=tuple(
                            f"claim:{value}"
                            for value in target.effective_association_evidence_claim_ids
                        ),
                        committee_claim_refs=tuple(
                            f"claim:{value}" for value in target.committee_claim_ids
                        ),
                        contact_authority=target_authority,
                    )
                )
            global_fields = _unique(
                value
                for authority in target_authorities.values()
                for value in authority.admitted_field_keys
            )
            global_sources = _unique(
                value
                for authority in target_authorities.values()
                for value in authority.admitted_source_keys
            )
            global_questions = _unique(
                value
                for authority in target_authorities.values()
                for value in authority.research_questions
            )
            global_facets = _unique(
                value for authority in target_authorities.values() for value in authority.facet_keys
            )
            global_channels = _unique(
                value
                for authority in target_authorities.values()
                for value in authority.channel_permissions
            )
            global_policies = _unique(
                value
                for authority in target_authorities.values()
                for value in authority.policy_refs
            )
            global_approvals = _unique(
                value
                for authority in target_authorities.values()
                for value in authority.approval_refs
            )
            global_field_authority = self._union_field_authority(target_authorities)
            entity_selection = EntityResearchSelection(
                selection_id=UUID(str(selection.selection_id)),
                workspace_id=request.workspace_id,
                project_id=body.project_id,
                product_id=project_run.product_id,
                project_run_id=UUID(str(body.project_run_id)),
                subject_type=ResearchSubjectType.CONTACT,
                account_entity_id=UUID(str(body.account_entity_id)),
                subjects=tuple(subjects),
                directive_ref=(
                    f"research-directive:{body.research_directive.directive_id}:"
                    f"v{body.research_directive.version}"
                ),
                directive_sha256=body.research_directive.canonical_json_sha256,
                field_plan_ref=_content_ref("contact-run-field-plan", global_fields),
                source_plan_ref=_content_ref(
                    "contact-run-source-plan",
                    tuple(value.model_dump(mode="json") for value in global_field_authority),
                ),
                admitted_field_keys=global_fields,
                admitted_source_keys=global_sources,
                field_source_authority=global_field_authority,
                research_questions=global_questions,
                facet_keys=global_facets,
                channel_permissions=global_channels,
                policy_refs=global_policies,
                budget_envelope_ref=body.budget_reservation_ref,
                approval_refs=global_approvals,
                confirmed_by=actor,
                confirmed_at=confirmed_at,
            )
            lifecycle = ResearchRunLifecycleContract(
                run_id=research_run_id,
                run_kind=ResearchRunKind.CONTACT_RESEARCH,
                selection=entity_selection,
                user_confirmed_launch=True,
                operations=(ResearchOperationKind.CONTACT_RESEARCH,),
                automatic_successor_run=False,
            )
            profile_sha = contact_research_profile_sha256()
            for priority, subject in enumerate(subjects):
                contact_id = subject.subject_entity_id
                target_authority = target_authorities[contact_id]
                job_id = uuid5(_JOB_NAMESPACE, f"{research_run_id}:{contact_id}")
                authorization = EntityResearchJobAuthorization(
                    job_id=job_id,
                    research_run_id=research_run_id,
                    subject_type=ResearchSubjectType.CONTACT,
                    subject_entity_id=contact_id,
                    parent_account_id=UUID(str(body.account_entity_id)),
                    workspace_id=request.workspace_id,
                    project_id=body.project_id,
                    product_id=project_run.product_id,
                    project_run_id=UUID(str(body.project_run_id)),
                    selection=entity_selection,
                    agent_profile_ref=_CONTACT_PROFILE_REF,
                    agent_profile_sha256=profile_sha,
                    checkpoint_thread_id=f"entity-research:{job_id}",
                    attempt_id=uuid5(_ATTEMPT_NAMESPACE, str(job_id)),
                    lease_id=uuid5(_LEASE_NAMESPACE, str(job_id)),
                )
                jobs.append(
                    EntityResearchJobEnvelope(
                        authorization=authorization,
                        priority=priority,
                        budget_envelope_ref=target_authority.budget_envelope_ref,
                        budget_cap_cents=target_authority.budget_cap_cents,
                    )
                )
            envelope = EntityResearchRunEnvelope(
                lifecycle=lifecycle,
                jobs=tuple(jobs),
                budget_cap_cents=request.approved_budget_cap_cents,
                concurrency_limit=request.concurrency_limit,
            )
            await launch_entity_research_run(conn, envelope)
            await self._persist_launch(
                conn,
                envelope=envelope,
                authority=authority,
                intents=intents,
                request=request,
                request_sha=request_sha,
                actor=actor,
                source_action_ref=source_action_ref,
                source_operation_id=source_operation_id,
                confirmed_at=confirmed_at,
            )
            await conn.execute(
                text("SET CONSTRAINTS entity_research_contact_run_complete IMMEDIATE")
            )
            await conn.execute(
                text("SET CONSTRAINTS entity_research_contact_run_complete DEFERRED")
            )
            return await self._projection(conn, research_run_id)

    @staticmethod
    def _field_source_authority(
        target: ContactResearchTarget,
        body: ContactResearchSelectionBody,
    ) -> tuple[FieldSourceAuthority, ...]:
        if target.field_source_authority:
            return target.field_source_authority
        values: list[FieldSourceAuthority] = []
        for field in target.field_keys:
            token = str(field)
            if token in {
                "contact.current_title",
                "contact.job_function",
                "contact.job_level",
                "contact.team_membership",
                "contact.current_location",
                "contact.organization_relationship",
            }:
                sources = body.policy.professional_source_plan
            elif classify_field_key(field) is FieldClass.CONTACT_FACET:
                sources = body.policy.personal_facet_source_plan
            elif token in {"core.work_email", "core.direct_phone"}:
                continue
            else:
                sources = ()
            if not sources:
                raise ContactResearchFleetLaunchError(
                    f"contact field {token!r} has no exact executable source authority"
                )
            values.append(FieldSourceAuthority(field_key=token, source_keys=tuple(sources)))
        return tuple(values)

    @staticmethod
    def _union_field_authority(
        authorities: dict[UUID, SelectedContactResearchAuthority],
    ) -> tuple[FieldSourceAuthority, ...]:
        values: dict[str, list[str]] = {}
        for authority in authorities.values():
            for item in authority.field_source_authority:
                sources = values.setdefault(item.field_key, [])
                sources.extend(source for source in item.source_keys if source not in sources)
        return tuple(
            FieldSourceAuthority(field_key=field, source_keys=tuple(sources))
            for field, sources in values.items()
        )

    async def _persist_launch(
        self,
        conn: AsyncConnection,
        *,
        envelope: EntityResearchRunEnvelope,
        authority: ContactResearchSelectionAuthorityRecord,
        intents: dict[UUID, ContactResearchIntent],
        request: ContactResearchFleetLaunchRequest,
        request_sha: str,
        actor: str,
        source_action_ref: str,
        source_operation_id: UUID,
        confirmed_at: datetime,
    ) -> None:
        inserted = await conn.execute(
            text(
                "INSERT INTO entity_research_contact_launch "
                "(research_run_id, workspace_id, project_id, product_id, project_run_id, "
                "account_run_id, account_entity_id, contact_selection_id, "
                "contact_selection_sha256, selection_approval_id, source_operation_id, "
                "source_action_ref, launched_by, confirmed_at, request_json, request_sha256) "
                "VALUES (:run_id, :workspace_id, :project_id, :product_id, :project_run_id, "
                ":account_run_id, :account_id, :selection_id, :selection_sha, :approval_id, "
                ":operation_id, :action_ref, :actor, :confirmed_at, CAST(:request AS jsonb), "
                ":request_sha) ON CONFLICT (research_run_id) DO NOTHING"
            ),
            {
                "run_id": envelope.lifecycle.run_id,
                "workspace_id": request.workspace_id,
                "project_id": envelope.lifecycle.selection.project_id,
                "product_id": envelope.lifecycle.selection.product_id,
                "project_run_id": envelope.lifecycle.selection.project_run_id,
                "account_run_id": authority.account_run_id,
                "account_id": envelope.lifecycle.selection.account_entity_id,
                "selection_id": authority.selection.selection_id,
                "selection_sha": authority.selection.selection_sha256,
                "approval_id": authority.approval_id,
                "operation_id": source_operation_id,
                "action_ref": source_action_ref,
                "actor": actor,
                "confirmed_at": confirmed_at,
                "request": json.dumps(request.model_dump(mode="json"), default=str),
                "request_sha": request_sha,
            },
        )
        stored = (
            await conn.execute(
                text(
                    "SELECT request_sha256, source_operation_id FROM "
                    "entity_research_contact_launch WHERE research_run_id=:run_id"
                ),
                {"run_id": envelope.lifecycle.run_id},
            )
        ).one()
        if (
            stored.request_sha256 != request_sha
            or stored.source_operation_id != source_operation_id
        ):
            raise ContactResearchFleetLaunchError(
                "contact research launch replay changed immutable authority"
            )
        for job in envelope.jobs:
            authorization = job.authorization
            intent = intents[authorization.subject_entity_id]
            target = next(
                value
                for value in intent.selection.body.targets
                if value.contact_entity_id == intent.contact_entity_id
            )
            await conn.execute(
                text(
                    "INSERT INTO entity_research_contact_job_authority "
                    "(job_id, research_run_id, workspace_id, contact_selection_id, contact_id, "
                    "account_id, selection_basis, contact_intent_json, contact_intent_sha256, "
                    "target_json, budget_cap_cents) VALUES "
                    "(:job_id, :run_id, :workspace_id, :selection_id, :contact_id, :account_id, "
                    ":basis, CAST(:intent AS jsonb), :intent_sha, CAST(:target AS jsonb), "
                    ":budget_cap) ON CONFLICT (job_id) DO NOTHING"
                ),
                {
                    "job_id": authorization.job_id,
                    "run_id": authorization.research_run_id,
                    "workspace_id": authorization.workspace_id,
                    "selection_id": intent.selection_id,
                    "contact_id": intent.contact_entity_id,
                    "account_id": intent.account_entity_id,
                    "basis": target.selection_basis.value,
                    "intent": intent.model_dump_json(),
                    "intent_sha": intent.sha256(),
                    "target": target.model_dump_json(),
                    "budget_cap": target.execution_budget_cap_cents,
                },
            )
        if inserted.rowcount == 0:
            count = (
                await conn.execute(
                    text(
                        "SELECT count(*) FROM entity_research_contact_job_authority "
                        "WHERE research_run_id=:run_id"
                    ),
                    {"run_id": envelope.lifecycle.run_id},
                )
            ).scalar_one()
            if int(count) != len(envelope.jobs):
                raise ContactResearchFleetLaunchError(
                    "contact research launch replay has a different exact job set"
                )

    async def _projection(
        self, conn: AsyncConnection, research_run_id: UUID
    ) -> ContactResearchFleetLaunchProjection:
        launch = (
            (
                await conn.execute(
                    text(
                        "SELECT launch.*, run.state AS run_state, run.budget_cap_cents, "
                        "run.concurrency_limit FROM entity_research_contact_launch launch "
                        "JOIN entity_research_run run USING (research_run_id) "
                        "WHERE launch.research_run_id=:run_id"
                    ),
                    {"run_id": research_run_id},
                )
            )
            .mappings()
            .one()
        )
        rows = (
            (
                await conn.execute(
                    text(
                        "SELECT authority.job_id, authority.contact_id, authority.account_id, "
                        "authority.selection_basis, authority.contact_intent_sha256, "
                        "authority.contact_intent_json, job.state, job.budget_cap_cents, "
                        "job.authorization_json FROM entity_research_contact_job_authority "
                        "authority JOIN entity_research_job job USING (job_id) "
                        "WHERE authority.research_run_id=:run_id ORDER BY job.priority, job.job_id"
                    ),
                    {"run_id": research_run_id},
                )
            )
            .mappings()
            .all()
        )
        jobs: list[ContactResearchJobLaunchProjection] = []
        for row in rows:
            intent = ContactResearchIntent.model_validate(row["contact_intent_json"])
            authorization = EntityResearchJobAuthorization.model_validate(row["authorization_json"])
            target = authorization.effective_contact_authority
            if target is None:
                raise ContactResearchFleetLaunchError(
                    "persisted contact job lacks exact target authority"
                )
            jobs.append(
                ContactResearchJobLaunchProjection(
                    job_id=row["job_id"],
                    contact_entity_id=row["contact_id"],
                    parent_account_id=row["account_id"],
                    selection_basis=ResearchSelectionBasis(row["selection_basis"]),
                    contact_intent_ref=target.contact_intent_ref,
                    contact_intent_sha256=intent.sha256(),
                    field_keys=target.admitted_field_keys,
                    research_questions=target.research_questions,
                    source_keys=target.admitted_source_keys,
                    field_source_authority=target.field_source_authority,
                    facet_keys=target.facet_keys,
                    channel_permissions=target.channel_permissions,
                    channel_source_keys=target.channel_source_keys,
                    policy_refs=target.policy_refs,
                    approval_refs=target.approval_refs,
                    budget_cap_cents=row["budget_cap_cents"],
                    state=str(row["state"]),
                )
            )
        return ContactResearchFleetLaunchProjection(
            research_run_id=research_run_id,
            workspace_id=str(launch["workspace_id"]),
            project_id=str(launch["project_id"]),
            product_id=str(launch["product_id"]),
            project_run_id=launch["project_run_id"],
            account_entity_id=launch["account_entity_id"],
            contact_selection_id=launch["contact_selection_id"],
            contact_selection_sha256=str(launch["contact_selection_sha256"]),
            run_state=str(launch["run_state"]),
            budget_cap_cents=launch["budget_cap_cents"],
            concurrency_limit=int(launch["concurrency_limit"]),
            jobs=tuple(jobs),
        )


__all__ = [
    "ContactResearchFleetLaunchError",
    "ContactResearchFleetLaunchProjection",
    "ContactResearchFleetLaunchRequest",
    "ContactResearchFleetLauncher",
    "ContactResearchSelectionApprovalError",
    "ContactResearchSelectionApprovalRequest",
    "ContactResearchSelectionApprover",
    "ContactResearchTargetApproval",
    "contact_research_profile_sha256",
]
