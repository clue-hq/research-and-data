"""M8C C7 contact-research handoff composed from existing governed authorities.

This is a read projection.  It neither calls a provider nor persists a second handoff payload.
Research claim bodies remain in the research view/claim store; channel values remain behind the C5
delivery ledger.  The returned contract contains only the references a content consumer needs.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncConnection

from clue_api.contact_eligibility import ContactEligibilityResolver, GovernedCommitteeContact
from clue_api.research_view_runtime import ProductionResearchViewComposer
from clue_core import (
    CONTACT_CHANNEL_FIELD_KEYS,
    CONTACT_PROFESSIONAL_FIELD_KEYS,
    ContactChannel,
    ContactChannelCoverage,
    ContactChannelCoverageState,
    ContactChannelOperationState,
    ContactContentBundle,
    ContactContentHandoff,
    ContactDeliveryChannelRef,
    ContactDraftingContextRef,
    ContactDraftingFallback,
    ContactHandoffClaimKind,
    ContactHandoffClaimRef,
    ContactHandoffCoverage,
    ContactHandoffExclusion,
    ContactResearchSelection,
    ContactResearchTarget,
    DisplayDecision,
    EntityId,
    EntityType,
    OutreachDecision,
    Persona,
    ProjectRunId,
    ResearchAvailability,
    ResearchConflictState,
    ResearchPersonalizationItem,
    ResearchStatement,
    ResearchView,
    ResearchViewReadRequest,
    UseDecision,
)
from clue_db import ConnFactory, repeatable_read_transaction
from clue_research.durable import (
    ContactChannelAuthorizedOperation,
    contact_channel_operation_is_usable,
    contact_research_selection_cancellation,
    find_account_runs_for_entity,
    get_project_run,
    latest_contact_research_selection,
    list_contact_channel_operations_for_selection,
    list_contact_external_research_operations,
)
from clue_research.identity import get_account


@asynccontextmanager
async def _borrowed_connection(conn: AsyncConnection) -> AsyncIterator[AsyncConnection]:
    yield conn


def _statements(view: ResearchView) -> tuple[ResearchStatement, ...]:
    by_id: dict[object, ResearchStatement] = {}
    for section in view.sections:
        for item in section.items:
            if isinstance(item, ResearchStatement):
                by_id[item.statement_id] = item
            elif isinstance(item, ResearchPersonalizationItem):
                by_id[item.statement.statement_id] = item.statement
    return tuple(by_id.values())


def _available(statement: ResearchStatement) -> bool:
    return (
        statement.state.availability is ResearchAvailability.AVAILABLE
        and statement.state.display_decision is DisplayDecision.ALLOWED
        and statement.state.conflict is ResearchConflictState.NONE
    )


def _ref(
    statement: ResearchStatement,
    kind: ContactHandoffClaimKind,
    *,
    use_decision: UseDecision | None = None,
) -> ContactHandoffClaimRef:
    return ContactHandoffClaimRef(
        claim_id=statement.claim_id,
        field_key=statement.field_key,
        kind=kind,
        support_claim_ids=tuple(item.claim_id for item in statement.supports),
        identity_binding=statement.identity_binding,
        use_class=statement.use_class,
        use_decision=use_decision,
        conflict=statement.state.conflict,
    )


def _expected_sources(
    selection: ContactResearchSelection,
    target: ContactResearchTarget,
) -> tuple[str, ...]:
    policy = selection.body.policy
    fields = {str(value) for value in target.field_keys}
    values: list[str] = []
    if fields.intersection(CONTACT_PROFESSIONAL_FIELD_KEYS):
        values.extend(policy.professional_source_plan)
    if any(value.startswith("contact.facet.") for value in fields):
        values.extend(policy.personal_facet_source_plan)
    for authorization in (target.email, target.phone):
        if authorization.allowed:
            values.extend(authorization.provider_source_keys)
            values.extend(authorization.validation_source_keys)
    return tuple(dict.fromkeys(values))


def _account_context_refs(
    account_view: ResearchView,
) -> tuple[ContactHandoffClaimRef, ...]:
    allowed_exact = {"account.operational_pain", "account.strategic_moves"}
    result = []
    for statement in _statements(account_view):
        field = str(statement.field_key)
        if not _available(statement):
            continue
        if field in allowed_exact or field.startswith("account.resonance."):
            result.append(_ref(statement, ContactHandoffClaimKind.ACCOUNT_CONTEXT))
    return tuple(sorted(result, key=lambda item: (str(item.field_key), str(item.claim_id))))


def _value_narrative_refs(
    account_view: ResearchView,
    *,
    persona: Persona,
) -> tuple[ContactHandoffClaimRef, ...]:
    result = []
    for statement in _statements(account_view):
        if str(statement.field_key) != "account.value_narrative" or not _available(statement):
            continue
        value = statement.value_json
        if not isinstance(value, dict) or value.get("persona") != persona.value:
            continue
        result.append(_ref(statement, ContactHandoffClaimKind.VALUE_NARRATIVE))
    return tuple(sorted(result, key=lambda item: str(item.claim_id)))


def _role_and_persona_refs(
    contact: GovernedCommitteeContact,
) -> tuple[ContactHandoffClaimRef, ContactHandoffClaimRef]:
    by_id = {item.claim.id: item for item in contact.claims}
    role = by_id[contact.role_claim_id]
    persona = by_id[contact.persona_claim_id]
    return (
        ContactHandoffClaimRef(
            claim_id=role.claim.id,
            field_key=role.claim.field_key,
            kind=ContactHandoffClaimKind.ROLE,
            identity_binding=role.claim.identity_binding,
            use_class=role.claim.use_class,
            use_decision=role.use_decision,
        ),
        ContactHandoffClaimRef(
            claim_id=persona.claim.id,
            field_key=persona.claim.field_key,
            kind=ContactHandoffClaimKind.PERSONA,
            identity_binding=persona.claim.identity_binding,
            use_class=persona.claim.use_class,
            use_decision=persona.use_decision,
        ),
    )


async def _channel_projection(
    conn: AsyncConnection,
    *,
    selection: ContactResearchSelection,
    target: ContactResearchTarget,
    operations: tuple[ContactChannelAuthorizedOperation, ...],
    now: datetime,
) -> tuple[tuple[ContactDeliveryChannelRef, ...], tuple[ContactChannelCoverage, ...]]:
    deliveries: list[ContactDeliveryChannelRef] = []
    coverage: list[ContactChannelCoverage] = []
    for channel, authorization in (
        (ContactChannel.EMAIL, target.email),
        (ContactChannel.PHONE, target.phone),
    ):
        requested = authorization.allowed and (
            CONTACT_CHANNEL_FIELD_KEYS[channel] in {str(value) for value in target.field_keys}
        )
        relevant = tuple(item for item in operations if item.operation.request.channel is channel)
        if not requested or not relevant:
            coverage.append(
                ContactChannelCoverage(
                    channel=channel,
                    state=ContactChannelCoverageState.NOT_REQUESTED,
                    reason_codes=(
                        "channel_not_selected" if not requested else "channel_not_dispatched",
                    ),
                )
            )
            continue

        usable: ContactChannelAuthorizedOperation | None = None
        for authorized in relevant:
            operation = authorized.operation
            if operation.state is not ContactChannelOperationState.SUCCEEDED:
                continue
            if await contact_channel_operation_is_usable(
                conn,
                workspace_id=selection.body.workspace_id,
                operation_id=operation.operation_id,
                now=now,
            ):
                usable = authorized
                break
        if usable is not None:
            operation = usable.operation
            assert operation.validation is not None
            assert operation.observed_claim_id is not None
            assert operation.terminal_at is not None
            request = operation.request
            deliveries.append(
                ContactDeliveryChannelRef(
                    channel=channel,
                    operation_id=operation.operation_id,
                    operation_ref=usable.authorization_ref,
                    observed_claim_id=operation.observed_claim_id,
                    corroborating_claim_ids=operation.validation.corroborating_claim_ids,
                    validation_reference_ids=operation.validation.validation_reference_ids,
                    freshness_expires_at=operation.terminal_at
                    + timedelta(seconds=request.freshness_seconds),
                    retention_expires_at=operation.terminal_at
                    + timedelta(seconds=request.retention_seconds),
                    retention_policy_ref=request.retention_policy_ref,
                )
            )
            coverage.append(
                ContactChannelCoverage(
                    channel=channel,
                    state=ContactChannelCoverageState.DELIVERY_ELIGIBLE,
                    operation_ref=usable.authorization_ref,
                )
            )
            continue

        latest = relevant[0]
        operation = latest.operation
        failed_validation = operation.state is ContactChannelOperationState.REJECTED or (
            operation.validation is not None and not operation.validation.delivery_eligible
        )
        coverage.append(
            ContactChannelCoverage(
                channel=channel,
                state=(
                    ContactChannelCoverageState.FAILED_VALIDATION
                    if failed_validation
                    else ContactChannelCoverageState.EXCLUDED
                ),
                operation_ref=latest.authorization_ref,
                reason_codes=(
                    operation.failure_code
                    or (
                        "independent_validation_failed"
                        if failed_validation
                        else f"channel_{operation.state.value}"
                    ),
                ),
            )
        )
    return tuple(deliveries), tuple(coverage)


class ContactContentHandoffService:
    """Compose C7 bundles without provider, model, write, or artifact access."""

    def __init__(
        self,
        *,
        conn_factory: ConnFactory = repeatable_read_transaction,
        research_views: ProductionResearchViewComposer | None = None,
    ) -> None:
        self._conn_factory = conn_factory
        self._research_views = research_views or ProductionResearchViewComposer(
            conn_factory=conn_factory
        )

    async def compose(
        self,
        *,
        workspace_id: str,
        project_id: str,
        project_run_id: ProjectRunId,
        account_entity_id: EntityId,
        product_id: str | None,
    ) -> ContactContentHandoff:
        composed_at = datetime.now(UTC)
        async with self._conn_factory() as conn:
            return await self._compose_on_connection(
                conn,
                workspace_id=workspace_id,
                project_id=project_id,
                project_run_id=project_run_id,
                account_entity_id=account_entity_id,
                product_id=product_id,
                composed_at=composed_at,
            )

    async def _compose_on_connection(
        self,
        conn: AsyncConnection,
        *,
        workspace_id: str,
        project_id: str,
        project_run_id: ProjectRunId,
        account_entity_id: EntityId,
        product_id: str | None,
        composed_at: datetime,
    ) -> ContactContentHandoff:
        # Validate the complete caller scope before reading account-run references.  In
        # particular, the empty/cancelled-selection paths below include committee contact ids as
        # useful same-scope exclusions, so resolving those ids before this guard would create a
        # cross-workspace/project/product existence oracle.
        project_run = await get_project_run(conn, project_run_id)
        account = await get_account(conn, account_entity_id)
        if (
            project_run is None
            or project_run.workspace_id != workspace_id
            or project_run.project_id != project_id
            or project_run.product_id != product_id
            or account is None
            or account.workspace_id != workspace_id
            or account.merged_into is not None
        ):
            return self._empty(
                workspace_id=workspace_id,
                project_id=project_id,
                project_run_id=project_run_id,
                account_entity_id=account_entity_id,
                product_id=product_id,
                composed_at=composed_at,
                reason="contact_handoff_scope_not_found",
            )
        account_runs = await find_account_runs_for_entity(
            conn, project_run_id=project_run_id, entity_id=account_entity_id
        )
        if len(account_runs) != 1:
            return self._empty(
                workspace_id=workspace_id,
                project_id=project_id,
                project_run_id=project_run_id,
                account_entity_id=account_entity_id,
                product_id=product_id,
                composed_at=composed_at,
                reason="account_run_not_found",
            )
        account_run = account_runs[0]
        committee_ids = tuple(
            EntityId(UUID(value))
            for value in account_run.references_index.get("committee_contacts", ())
        )
        selection = await latest_contact_research_selection(
            conn,
            workspace_id=workspace_id,
            project_run_id=project_run_id,
            account_id=account_entity_id,
            include_cancelled=True,
        )
        if selection is None:
            return ContactContentHandoff(
                workspace_id=workspace_id,
                project_id=project_id,
                project_run_id=project_run_id,
                product_id=product_id,
                account_entity_id=account_entity_id,
                exclusions=tuple(
                    ContactHandoffExclusion(
                        contact_entity_id=value,
                        selected=False,
                        reason_codes=("no_active_contact_research_selection",),
                    )
                    for value in committee_ids
                ),
                reason_codes=("no_active_contact_research_selection",),
                composed_at=composed_at,
            )
        cancellation = await contact_research_selection_cancellation(
            conn,
            workspace_id=workspace_id,
            selection_id=selection.selection_id,
        )
        if cancellation is not None:
            return ContactContentHandoff(
                workspace_id=workspace_id,
                project_id=project_id,
                project_run_id=project_run_id,
                product_id=product_id,
                account_entity_id=account_entity_id,
                exclusions=tuple(
                    ContactHandoffExclusion(
                        contact_entity_id=value,
                        selected=False,
                        reason_codes=("contact_research_selection_cancelled",),
                    )
                    for value in committee_ids
                ),
                reason_codes=("contact_research_selection_cancelled",),
                composed_at=composed_at,
            )
        body = selection.body
        if (
            body.workspace_id != workspace_id
            or body.project_id != project_id
            or body.project_run_id != project_run_id
            or body.account_entity_id != account_entity_id
        ):
            return self._empty(
                workspace_id=workspace_id,
                project_id=project_id,
                project_run_id=project_run_id,
                account_entity_id=account_entity_id,
                product_id=product_id,
                composed_at=composed_at,
                reason="contact_selection_scope_mismatch",
            )

        resolver = ContactEligibilityResolver(
            project_run_id=project_run_id,
            product_id=product_id,
            conn_factory=lambda: _borrowed_connection(conn),
        )
        eligible = {
            item.contact_entity_id: item
            for item in await resolver.resolve_account(
                account_entity_id=account_entity_id,
                workspace_id=workspace_id,
            )
        }
        selected = {target.contact_entity_id for target in body.targets}
        exclusions = [
            ContactHandoffExclusion(
                contact_entity_id=value,
                selected=False,
                reason_codes=("not_selected_for_contact_research",),
            )
            for value in committee_ids
            if value not in selected
        ]

        account_request = ResearchViewReadRequest(
            workspace_id=workspace_id,
            project_id=project_id,
            project_run_id=project_run_id,
            subject_entity_id=account_entity_id,
            subject_entity_type=EntityType.ACCOUNT,
            product_id=product_id,
        )
        account_view = await self._research_views.compose_on_connection(conn, account_request)
        account_context = _account_context_refs(account_view)
        bundles: list[ContactContentBundle] = []
        for target in body.targets:
            contact = eligible.get(target.contact_entity_id)
            if contact is None:
                exclusions.append(
                    ContactHandoffExclusion(
                        contact_entity_id=target.contact_entity_id,
                        selected=True,
                        reason_codes=("contact_no_longer_handoff_eligible",),
                    )
                )
                continue
            contact_request = ResearchViewReadRequest(
                workspace_id=workspace_id,
                project_id=project_id,
                project_run_id=project_run_id,
                subject_entity_id=target.contact_entity_id,
                subject_entity_type=EntityType.CONTACT,
                product_id=product_id,
            )
            contact_view = await self._research_views.compose_on_connection(conn, contact_request)
            statements = _statements(contact_view)
            target_fields = {str(value) for value in target.field_keys}
            professional = tuple(
                sorted(
                    (
                        _ref(item, ContactHandoffClaimKind.PROFESSIONAL)
                        for item in statements
                        if str(item.field_key) in CONTACT_PROFESSIONAL_FIELD_KEYS
                        and str(item.field_key) in target_fields
                        and _available(item)
                    ),
                    key=lambda item: (str(item.field_key), str(item.claim_id)),
                )
            )
            governed_by_id = {item.claim.id: item for item in contact.claims}
            facets = tuple(
                sorted(
                    (
                        _ref(
                            item,
                            ContactHandoffClaimKind.PERSONAL_FACET,
                            use_decision=governed_by_id[item.claim_id].use_decision,
                        )
                        for item in statements
                        if str(item.field_key).startswith("contact.facet.")
                        and str(item.field_key) in target_fields
                        and _available(item)
                        and item.state.outreach_decision is OutreachDecision.ALLOWED
                        and item.claim_id in governed_by_id
                        and governed_by_id[item.claim_id].personalization_eligible
                    ),
                    key=lambda item: (str(item.field_key), str(item.claim_id)),
                )
            )
            narratives = _value_narrative_refs(account_view, persona=contact.persona)
            fallback = (
                ContactDraftingFallback.CONTACT_PERSONALIZED
                if facets
                else (
                    ContactDraftingFallback.ACCOUNT_LEVEL
                    if account_context or narratives
                    else ContactDraftingFallback.GENERIC_REVIEW
                )
            )
            reasons = (
                ()
                if fallback is ContactDraftingFallback.CONTACT_PERSONALIZED
                else (
                    ("personal_evidence_missing_use_account_context",)
                    if fallback is ContactDraftingFallback.ACCOUNT_LEVEL
                    else ("contact_and_account_evidence_missing_review",)
                )
            )
            drafting = ContactDraftingContextRef(
                professional_claims=professional,
                account_context_claims=account_context,
                value_narrative_claims=narratives,
                personal_facet_claims=facets,
                fallback=fallback,
                reason_codes=reasons,
            )

            channel_ops = await list_contact_channel_operations_for_selection(
                conn,
                workspace_id=workspace_id,
                project_run_id=project_run_id,
                account_id=account_entity_id,
                contact_id=target.contact_entity_id,
                selection_id=selection.selection_id,
                selection_sha256=selection.selection_sha256,
            )
            deliveries, channel_coverage = await _channel_projection(
                conn,
                selection=selection,
                target=target,
                operations=channel_ops,
                now=composed_at,
            )
            external_ops = await list_contact_external_research_operations(
                conn,
                workspace_id=workspace_id,
                project_run_id=project_run_id,
                account_id=account_entity_id,
                contact_id=target.contact_entity_id,
            )
            searched = {
                item.claim.source_key
                for item in contact.claims
                if str(item.claim.field_key) in target_fields and item.claim.source_key is not None
            }
            searched.update(item.source_key for item in external_ops)
            searched.update(item.operation.request.acquisition_source_key for item in channel_ops)
            searched.update(item.operation.request.validation_source_key for item in channel_ops)
            expected = set(_expected_sources(selection, target))

            statement_by_field = {
                str(item.field_key): item
                for item in statements
                if str(item.field_key) in target_fields
            }
            projected_fields = {str(item.field_key) for item in (*professional, *facets)}
            projected_fields.update(CONTACT_CHANNEL_FIELD_KEYS[item.channel] for item in deliveries)
            conflicted = {
                field
                for field, statement in statement_by_field.items()
                if statement.state.conflict is ResearchConflictState.REVIEW_REQUIRED
            }
            blocked = {
                field
                for field, statement in statement_by_field.items()
                if field not in projected_fields and field not in conflicted
            }
            for channel_item in channel_coverage:
                field = CONTACT_CHANNEL_FIELD_KEYS[channel_item.channel]
                if field not in target_fields or field in projected_fields:
                    continue
                if channel_item.state in {
                    ContactChannelCoverageState.EXCLUDED,
                    ContactChannelCoverageState.FAILED_VALIDATION,
                }:
                    blocked.add(field)
            empty = target_fields - projected_fields - conflicted - blocked
            stop_reasons = tuple(
                sorted(
                    {
                        value
                        for value in account_run.references_index.get("external:contact:audit", ())
                        if "budget" in value or "policy" in value or "cancel" in value
                    }
                )
            )
            role_ref, persona_ref = _role_and_persona_refs(contact)
            selection_ref = (
                f"contact-selection:{selection.selection_id}:{selection.selection_sha256}"
            )
            coverage_refs = tuple(
                dict.fromkeys(
                    (
                        selection_ref,
                        *(
                            f"external-research-operation:{item.operation_id}"
                            for item in external_ops
                        ),
                        *(item.authorization_ref for item in channel_ops),
                    )
                )
            )
            coverage = ContactHandoffCoverage(
                attempted_field_keys=tuple(sorted(target_fields)),
                filled_field_keys=tuple(sorted(projected_fields)),
                empty_field_keys=tuple(sorted(empty)),
                conflicted_field_keys=tuple(sorted(conflicted)),
                blocked_field_keys=tuple(sorted(blocked)),
                searched_source_keys=tuple(sorted(searched.intersection(expected))),
                unsearched_source_keys=tuple(sorted(expected - searched)),
                channels=channel_coverage,
                coverage_reason_codes=("committee_coverage_not_durable",),
                coverage_ref_ids=coverage_refs,
                stop_reason_codes=stop_reasons,
            )
            bundles.append(
                ContactContentBundle(
                    workspace_id=workspace_id,
                    project_id=project_id,
                    project_run_id=project_run_id,
                    product_id=product_id,
                    account_entity_id=account_entity_id,
                    contact_entity_id=target.contact_entity_id,
                    persona=contact.persona,
                    account_identity_ref=(
                        f"identity:account:{account_entity_id}:"
                        f"v{account_view.subject.canonical_entity_version}"
                    ),
                    contact_identity_ref=(
                        f"identity:contact:{target.contact_entity_id}:"
                        f"v{contact_view.subject.canonical_entity_version}"
                    ),
                    selection_id=selection.selection_id,
                    selection_sha256=selection.selection_sha256,
                    selection_ref=selection_ref,
                    account_view_id=account_view.view_id,
                    contact_view_id=contact_view.view_id,
                    account_view_state_sha256=account_view.source_state_sha256,
                    contact_view_state_sha256=contact_view.source_state_sha256,
                    role_claim=role_ref,
                    persona_claim=persona_ref,
                    drafting_context=drafting,
                    delivery_channels=deliveries,
                    coverage=coverage,
                    use_policy_ref=body.use_policy_ref,
                    retention_policy_ref=body.retention_policy_ref,
                    composed_at=composed_at,
                )
            )
        return ContactContentHandoff(
            workspace_id=workspace_id,
            project_id=project_id,
            project_run_id=project_run_id,
            product_id=product_id,
            account_entity_id=account_entity_id,
            bundles=tuple(
                sorted(
                    bundles,
                    key=lambda item: (item.persona.value, str(item.contact_entity_id)),
                )
            ),
            exclusions=tuple(sorted(exclusions, key=lambda item: str(item.contact_entity_id))),
            reason_codes=(() if bundles else ("no_contact_content_bundle_eligible",)),
            composed_at=composed_at,
        )

    @staticmethod
    def _empty(
        *,
        workspace_id: str,
        project_id: str,
        project_run_id: ProjectRunId,
        account_entity_id: EntityId,
        product_id: str | None,
        composed_at: datetime,
        reason: str,
    ) -> ContactContentHandoff:
        return ContactContentHandoff(
            workspace_id=workspace_id,
            project_id=project_id,
            project_run_id=project_run_id,
            product_id=product_id,
            account_entity_id=account_entity_id,
            reason_codes=(reason,),
            composed_at=composed_at,
        )


def build_contact_content_handoff_service(
    *,
    conn_factory: ConnFactory = repeatable_read_transaction,
) -> ContactContentHandoffService:
    return ContactContentHandoffService(conn_factory=conn_factory)


__all__ = ["ContactContentHandoffService", "build_contact_content_handoff_service"]
