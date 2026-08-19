"""M8C C3 exact-contact Exa Search Deep compiler.

This module is deliberately transport-free.  It resolves the selected-contact receipt against the
current canonical account/contact, confirmed directive, effective field registry, ICP source
profile, and exact ``exa_deep`` authorization.  It emits durable contact-subject preflights that C4
may acquire later; it cannot call Exa, reserve an operation, write a claim, or reveal a channel.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, JsonValue, model_validator
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_core import (
    AccountEntity,
    ContactEntity,
    ContactResearchIntent,
    ContactResearchPolicyPin,
    ContactResearchSelectionId,
    EffectiveFieldSourcePlan,
    EntityScope,
    ExternalResearchAcquisitionRequest,
    ExternalResearchSubjectKind,
    FieldClass,
    ResearchMode,
    classify_field_key,
    normalize_host,
)
from clue_research.claimstore import (
    FieldRegistryScope,
    WorkspaceScope,
    current_values,
    get_effective_field,
)
from clue_research.directives import effective_account_research_directive
from clue_research.durable import get_project_run
from clue_research.icp import get_icp_version
from clue_research.identity import get_account, get_contact
from clue_research.resolvers.exa import (
    DEFAULT_EXA_CONFIG,
    SOURCE_KEY,
    ExaDeepConfig,
    ExaDeepContactSearchRequest,
    ExaDeepContactTargetLock,
    ExaDeepFieldSpec,
    compile_exa_contact_deep_request,
    validate_exa_contact_request_target,
)
from clue_research.sources import get_source, plan_sources

_KNOWN_DISAMBIGUATOR_FIELDS = (
    "contact.current_title",
    "contact.job_function",
    "contact.current_location",
)


class ExaDeepContactAdmittedField(BaseModel):
    """One registry field plus the exact content-addressed source authority that admitted it."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    spec: ExaDeepFieldSpec
    effective_source_plan: EffectiveFieldSourcePlan
    freshness_seconds: int = Field(ge=1)

    @model_validator(mode="after")
    def _field_is_exactly_exa_authorized(self) -> ExaDeepContactAdmittedField:
        if self.effective_source_plan.field_key != self.spec.field_key:
            raise ValueError("contact Exa field source plan belongs to another field")
        if self.effective_source_plan.authorization_for(SOURCE_KEY) is None:
            raise ValueError("contact Exa field source plan does not admit exact exa_deep")
        return self


class ExaDeepContactAcquisitionPreflight(BaseModel):
    """Transport-free C3 output for one provider-safe schema bundle."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    request: ExternalResearchAcquisitionRequest
    selection_id: ContactResearchSelectionId
    selection_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    intent_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    exa_request: ExaDeepContactSearchRequest
    target_lock: ExaDeepContactTargetLock
    field_source_plans: tuple[EffectiveFieldSourcePlan, ...] = Field(min_length=1)
    exa_config: ExaDeepConfig = DEFAULT_EXA_CONFIG

    @model_validator(mode="after")
    def _lineage_matches_wire(self) -> ExaDeepContactAcquisitionPreflight:
        request = self.request
        if (
            request.subject_kind is not ExternalResearchSubjectKind.CONTACT
            or request.contact_id != self.target_lock.contact_entity_id
            or request.account_id != self.target_lock.employer_account_id
        ):
            raise ValueError("contact Exa preflight subject differs from its target lock")
        payload = self.exa_request.model_dump(mode="json", by_alias=True, exclude_none=True)
        if request.request_payload != payload:
            raise ValueError("contact Exa durable payload differs from the compiled wire request")
        validate_exa_contact_request_target(self.exa_request, self.target_lock)
        if (
            self.exa_request.search_type != self.exa_config.search_type
            or self.exa_request.num_results != self.exa_config.num_results
            or len(self.exa_request.additional_queries or ())
            > self.exa_config.max_additional_queries
            or self.exa_request.contents.text.max_characters != self.exa_config.text_max_characters
            or self.exa_request.contents.highlights.max_characters
            != self.exa_config.highlight_max_characters
        ):
            raise ValueError("contact Exa wire request differs from its effective compiler policy")
        emitted = set(self.exa_request.field_key_by_alias.values())
        planned_keys = tuple(plan.field_key for plan in self.field_source_plans)
        if len(planned_keys) != len(set(planned_keys)):
            raise ValueError("contact Exa preflight source plans must be unique by field")
        if any(
            plan.workspace_id != request.workspace_id
            or plan.icp_key != request.icp_key
            or plan.icp_version != request.icp_version
            for plan in self.field_source_plans
        ):
            raise ValueError("contact Exa source plan scope differs from the durable request")
        planned = set(planned_keys)
        if emitted != planned:
            raise ValueError("contact Exa wire fields differ from effective source plans")
        if any(plan.authorization_for(SOURCE_KEY) is None for plan in self.field_source_plans):
            raise ValueError("every contact Exa wire field must admit exact exa_deep")
        if request.wire_request_sha256 != _sha256(_json_bytes(payload)):
            raise ValueError("contact Exa wire digest differs from the durable request")
        return self


class ExaDeepContactAcquisitionPlan(BaseModel):
    """One exact selected contact, split only when Exa's schema-property budget requires it."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    intent_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    bundles: tuple[ExaDeepContactAcquisitionPreflight, ...] = Field(min_length=1)

    @property
    def field_count(self) -> int:
        return sum(len(bundle.field_source_plans) for bundle in self.bundles)


def compile_exa_contact_acquisition_plan(
    *,
    intent: ContactResearchIntent,
    target_lock: ExaDeepContactTargetLock,
    icp_key: str,
    icp_version: int,
    fields: Sequence[ExaDeepContactAdmittedField],
    directional_questions: Sequence[str],
    observation_window: str,
    cost_cents_reserved_per_bundle: Decimal,
    entity_research_job_id: UUID | None = None,
    config: ExaDeepConfig = DEFAULT_EXA_CONFIG,
    reuse_context_ref: str | None = None,
    prior_research_context: str | None = None,
) -> ExaDeepContactAcquisitionPlan:
    """Compile deterministic contact preflights without credential lookup or provider traffic."""

    if target_lock.contact_entity_id != intent.contact_entity_id:
        raise ValueError("contact target lock belongs to another selected contact")
    if target_lock.employer_account_id != intent.account_entity_id:
        raise ValueError("contact target employer differs from the selected account")
    ordered = sorted(fields, key=lambda item: str(item.spec.field_key))
    if not ordered:
        raise ValueError("contact Exa compilation requires at least one admitted facet field")
    if len({item.spec.field_key for item in ordered}) != len(ordered):
        raise ValueError("contact Exa admitted fields must be unique")
    grouped: list[list[ExaDeepContactAdmittedField]] = []
    current: list[ExaDeepContactAdmittedField] = []
    for field in ordered:
        candidate = [*current, field]
        try:
            compile_exa_contact_deep_request(
                target_lock,
                [item.spec for item in candidate],
                directional_questions=directional_questions,
                prior_research_context=prior_research_context,
                config=config,
            )
        except ValueError:
            if not current:
                raise
            grouped.append(current)
            current = [field]
            compile_exa_contact_deep_request(
                target_lock,
                [field.spec],
                directional_questions=directional_questions,
                prior_research_context=prior_research_context,
                config=config,
            )
        else:
            current = candidate
    grouped.append(current)

    intent_sha = intent.sha256()
    preflights: list[ExaDeepContactAcquisitionPreflight] = []
    for index, bundle in enumerate(grouped):
        wire = compile_exa_contact_deep_request(
            target_lock,
            [item.spec for item in bundle],
            directional_questions=directional_questions,
            prior_research_context=prior_research_context,
            config=config,
        )
        payload = wire.model_dump(mode="json", by_alias=True, exclude_none=True)
        wire_sha = _sha256(_json_bytes(payload))
        source_plans = tuple(item.effective_source_plan for item in bundle)
        reuse_payload = {
            "contract": "exa-search-contact-deep-c3-semantic-v1",
            "workspace_id": intent.workspace_id,
            "project_id": intent.project_id,
            "subject_kind": ExternalResearchSubjectKind.CONTACT.value,
            "account_id": str(intent.account_entity_id),
            "contact_id": str(intent.contact_entity_id),
            "icp_key": icp_key,
            "icp_version": icp_version,
            "directive": intent.research_directive.model_dump(mode="json"),
            "selection_id": str(intent.selection_id),
            "selection_sha256": intent.selection_sha256,
            "intent_sha256": intent_sha,
            "target_lock": target_lock.model_dump(mode="json"),
            "source_key": SOURCE_KEY,
            "source_plan_sha256": [plan.plan_sha256 for plan in source_plans],
            "freshness_policy_ref": intent.freshness_policy_ref,
            "wire_request_sha256": wire_sha,
        }
        if reuse_context_ref is not None:
            reuse_payload["follow_up_context_ref"] = reuse_context_ref
        reuse_fingerprint = _sha256(_json_bytes(reuse_payload))
        request_fingerprint = _sha256(
            _json_bytes(
                {
                    "contract": "exa-search-contact-deep-c3-operation-v1",
                    "reuse_fingerprint": reuse_fingerprint,
                    "project_run_id": str(intent.project_run_id),
                    "entity_research_job_id": (
                        str(entity_research_job_id) if entity_research_job_id is not None else None
                    ),
                    "observation_window": observation_window,
                    "bundle_index": index,
                }
            )
        )
        durable = ExternalResearchAcquisitionRequest(
            workspace_id=intent.workspace_id,
            project_id=intent.project_id,
            project_run_id=intent.project_run_id,
            entity_research_job_id=entity_research_job_id,
            subject_kind=ExternalResearchSubjectKind.CONTACT,
            account_id=intent.account_entity_id,
            contact_id=intent.contact_entity_id,
            icp_key=icp_key,
            icp_version=icp_version,
            research_directive=intent.research_directive,
            source_key=SOURCE_KEY,
            observation_window=f"{observation_window}:contact:{intent.contact_entity_id}:bundle:{index}",
            freshness_policy_ref=intent.freshness_policy_ref,
            freshness_seconds=min(item.freshness_seconds for item in bundle),
            reuse_fingerprint=reuse_fingerprint,
            request_fingerprint=request_fingerprint,
            wire_request_sha256=wire_sha,
            request_payload=payload,
            cost_cents_reserved=cost_cents_reserved_per_bundle,
        )
        preflights.append(
            ExaDeepContactAcquisitionPreflight(
                request=durable,
                selection_id=intent.selection_id,
                selection_sha256=intent.selection_sha256,
                intent_sha256=intent_sha,
                exa_request=wire,
                target_lock=target_lock,
                field_source_plans=source_plans,
                exa_config=config,
            )
        )
    return ExaDeepContactAcquisitionPlan(intent_sha256=intent_sha, bundles=tuple(preflights))


async def compile_registered_exa_contact_plan(
    conn: AsyncConnection,
    *,
    intent: ContactResearchIntent,
    effective_policy: ContactResearchPolicyPin,
    observation_window: str,
    start_published_date: datetime | None = None,
    end_published_date: datetime | None = None,
    config: ExaDeepConfig = DEFAULT_EXA_CONFIG,
    field_keys: Sequence[str] | None = None,
    directional_questions: Sequence[str] | None = None,
    reuse_context_ref: str | None = None,
    prior_research_context: str | None = None,
    entity_research_job_id: UUID | None = None,
) -> ExaDeepContactAcquisitionPlan:
    """Resolve every C3 authority, optionally narrowing to one governed semantic tool call."""

    intent.selection.require_effective_policy(effective_policy)
    if SOURCE_KEY not in intent.source_plan:
        raise ValueError("selected contact intent does not authorize exa_deep")
    effective = await effective_account_research_directive(
        conn,
        workspace_id=intent.workspace_id,
        directive_id=intent.research_directive.directive_id,
        account_id=intent.account_entity_id,
        expected_pin=intent.research_directive,
    )
    if effective.project_id != intent.project_id:
        raise ValueError("contact intent project differs from its confirmed directive")
    if not effective.privacy_policy.contact_profiling_allowed:
        raise ValueError("confirmed directive does not authorize contact profiling")
    if SOURCE_KEY not in effective.source_policy.allowed_source_keys:
        raise ValueError("confirmed directive does not authorize exa_deep")
    icp = await get_icp_version(
        conn,
        intent.workspace_id,
        effective.icp_key,
        effective.icp_version,
    )
    if icp is None:
        raise ValueError("contact Exa compiler cannot resolve the pinned ICP")
    project_run = await get_project_run(conn, intent.project_run_id)
    if project_run is None or (
        project_run.workspace_id != intent.workspace_id
        or project_run.project_id != intent.project_id
        or project_run.icp_key != effective.icp_key
        or project_run.icp_version != effective.icp_version
    ):
        raise ValueError("contact selection run does not pin the confirmed directive ICP")
    account = await get_account(conn, intent.account_entity_id)
    contact = await get_contact(conn, intent.contact_entity_id)
    _validate_subjects(intent, account=account, contact=contact)
    assert account is not None and contact is not None

    target_receipt = next(
        target
        for target in intent.selection.body.targets
        if target.contact_entity_id == intent.contact_entity_id
    )
    if config.num_results > target_receipt.exa_max_results:
        config = config.model_copy(update={"num_results": target_receipt.exa_max_results})
    if config.num_results > effective_policy.exa_max_results:
        raise ValueError("contact Exa configuration exceeds the effective result cap")
    if config.max_additional_queries > effective_policy.exa_max_additional_queries:
        config = config.model_copy(
            update={"max_additional_queries": effective_policy.exa_max_additional_queries}
        )

    source = await get_source(conn, SOURCE_KEY)
    if source is None or not source.active:
        raise ValueError("exa_deep source manifest is absent or inactive")

    current = await current_values(
        conn,
        (contact.id,),
        _KNOWN_DISAMBIGUATOR_FIELDS,
        scope=WorkspaceScope.for_workspace(intent.workspace_id),
    )
    target_lock = ExaDeepContactTargetLock(
        contact_entity_id=contact.id,
        employer_account_id=account.id,
        canonical_full_name=contact.full_name or "",
        canonical_profile_url=contact.linkedin_url or "",
        employer_name=account.canonical_name,
        employer_domain=account.primary_domain or "",
        current_title=_display_current(current, contact.id, "contact.current_title"),
        job_function=_display_current(current, contact.id, "contact.job_function"),
        location=(
            _display_current(current, contact.id, "contact.current_location")
            or _display_json(contact.geo)
        ),
        approved_profile_hosts=effective_policy.approved_strong_profile_hosts,
        start_published_date=start_published_date,
        end_published_date=end_published_date,
    )

    question_by_id = {question.question_id: question for question in effective.questions}
    missing_questions = set(intent.directional_question_ids) - set(question_by_id)
    if missing_questions:
        raise ValueError(
            "contact selection references unknown confirmed questions: "
            + ", ".join(sorted(missing_questions))
        )
    selected_intent_questions = tuple(
        question_by_id[key].text for key in intent.directional_question_ids
    )
    questions = (
        selected_intent_questions if directional_questions is None else tuple(directional_questions)
    )
    if (
        len(questions) != len(set(questions))
        or (
            prior_research_context is None
            and not set(questions).issubset(selected_intent_questions)
        )
        or (directional_questions is not None and not questions)
    ):
        raise ValueError(
            "contact Exa questions must be unique, non-empty, and selected or follow-up scoped"
        )

    selected_field_keys = (
        tuple(str(field_key) for field_key in intent.field_keys)
        if field_keys is None
        else tuple(field_keys)
    )
    selected_intent_fields = {
        str(field_key)
        for field_key in intent.field_keys
        if classify_field_key(field_key) is FieldClass.CONTACT_FACET
    }
    if (
        not selected_field_keys
        or len(selected_field_keys) != len(set(selected_field_keys))
        or not set(selected_field_keys).issubset(selected_intent_fields)
    ):
        raise ValueError(
            "contact Exa fields must be a non-empty unique subset of selected facet fields"
        )

    admitted: list[ExaDeepContactAdmittedField] = []
    for field_key in selected_field_keys:
        definition = await get_effective_field(
            conn,
            scope=FieldRegistryScope.for_workspace(intent.workspace_id),
            field_key=str(field_key),
        )
        if definition is None or not definition.active or definition.value_schema is None:
            raise ValueError(f"contact Exa field {field_key!r} is not registered with a schema")
        planned = await plan_sources(
            conn,
            spec=icp,
            entity=contact.as_entity(),
            field=str(field_key),
            mode=ResearchMode.CONTACT_PROFILING,
            entity_tier=effective.effort_policy.tier,
            entity_scope=EntityScope.CONTACT,
            budget_envelope=effective.effort_policy.budget_cap_cents,
        )
        source_plan = planned.effective_source_plan
        if (
            source_plan is None
            or source_plan.authorization_for(SOURCE_KEY) is None
            or SOURCE_KEY not in planned.tier_plan()
        ):
            raise ValueError(
                f"effective source plan for {field_key!r} does not select exact exa_deep"
            )
        ttl = definition.field_def.freshness_ttl
        admitted.append(
            ExaDeepContactAdmittedField(
                spec=ExaDeepFieldSpec(
                    field_key=field_key,
                    value_schema=definition.value_schema,
                ),
                effective_source_plan=source_plan,
                freshness_seconds=(
                    max(1, int(ttl.total_seconds()))
                    if ttl is not None
                    else effective_policy.personal_facet_freshness_days * 86_400
                ),
            )
        )

    return compile_exa_contact_acquisition_plan(
        intent=intent,
        target_lock=target_lock,
        icp_key=effective.icp_key,
        icp_version=effective.icp_version,
        fields=admitted,
        directional_questions=questions,
        observation_window=observation_window,
        cost_cents_reserved_per_bundle=Decimal(source.cost_cents),
        config=config,
        reuse_context_ref=reuse_context_ref,
        prior_research_context=prior_research_context,
        entity_research_job_id=entity_research_job_id,
    )


def _validate_subjects(
    intent: ContactResearchIntent,
    *,
    account: AccountEntity | None,
    contact: ContactEntity | None,
) -> None:
    if account is None or account.workspace_id != intent.workspace_id or account.merged_into:
        raise ValueError("contact Exa employer account is absent, merged, or cross-workspace")
    if not account.primary_domain or not normalize_host(account.primary_domain):
        raise ValueError("contact Exa employer requires a canonical domain")
    if (
        contact is None
        or contact.workspace_id != intent.workspace_id
        or contact.account_entity_id != account.id
        or contact.merged_into
    ):
        raise ValueError("contact Exa subject is absent, merged, cross-account, or cross-workspace")
    if not contact.full_name or not contact.linkedin_url:
        raise ValueError("contact Exa subject requires a full name and strong profile URL")


def _display_current(
    values: dict[tuple[Any, str], Any],
    contact_id: Any,
    field_key: str,
) -> str | None:
    current = values.get((contact_id, field_key))
    return None if current is None else _display_json(current.value_json)


def _display_json(value: JsonValue | None) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        display = " ".join(value.split())
    else:
        display = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return display[:500] or None


def _json_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


__all__ = [
    "ExaDeepContactAcquisitionPlan",
    "ExaDeepContactAcquisitionPreflight",
    "ExaDeepContactAdmittedField",
    "compile_exa_contact_acquisition_plan",
    "compile_registered_exa_contact_plan",
]
