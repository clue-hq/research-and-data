"""Materialize immutable contact-research authority after committee identity exists (M8C C6)."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncConnection

from clue_config import OverlayStore, get_config
from clue_core import (
    CONTACT_CHANNEL_FIELD_KEYS,
    CONTACT_PROFESSIONAL_FIELD_KEYS,
    Claim,
    ClaimId,
    ContactChannel,
    ContactChannelAuthorization,
    ContactResearchSelection,
    ContactResearchSelectionBody,
    ContactResearchTarget,
    EntityId,
    FieldClass,
    FieldKey,
    IdentityBinding,
    ProjectRunId,
    ResearchMode,
    RunId,
    classify_field_key,
)
from clue_core.entity_research import FieldSourceAuthority, ResearchSelectionBasis
from clue_db import ConnFactory, transaction
from clue_research.claimstore import WorkspaceScope, claims_by_ids
from clue_research.directives import (
    effective_account_research_directive,
    get_research_directive,
)
from clue_research.durable import (
    contact_research_selection_cancellation,
    directive_confirmation_selection_approval,
    get_account_run,
    latest_contact_research_selection,
    store_contact_research_selection,
)
from clue_research.identity import get_contact
from clue_research.profiling.committee import PERSONA, ROLE_ON_COMMITTEE
from clue_research.profiling.committee.admission import DISCOVERY_PROVENANCE_FIELD


class ContactResearchSelectionError(RuntimeError):
    pass


def committee_claim_runs(account_run_id: RunId, project_run_id: ProjectRunId) -> frozenset[RunId]:
    """The two exact run identities a committee-discovery claim may legitimately carry.

    M8D stamps the whole committee claim set with the *project run* — the M8C C1 lineage trigger
    requires a Sumble professional claim's ``run_id`` to equal its ready operation's
    ``project_run_id``, and ``discover_committee`` stamps role/persona/discovery claims uniformly
    with the same run. Historical M8C rows rode the per-account deep run instead. Both are exact,
    non-widening identities for this account's committee; cross-account protection remains the
    contact-ownership and entity-binding checks, never this run comparison alone.
    """

    return frozenset({account_run_id, RunId(UUID(str(project_run_id)))})


def _content_ref(prefix: str, value: object) -> str:
    payload = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        default=str,
    ).encode()
    return f"{prefix}:{hashlib.sha256(payload).hexdigest()}"


def _contact_fields(field_keys: Sequence[str]) -> tuple[FieldKey, ...]:
    channels = set(CONTACT_CHANNEL_FIELD_KEYS.values())
    admitted: list[FieldKey] = []
    for raw in field_keys:
        if raw in channels:
            # A coarse directive can permit reveals, but only an explicitly persisted successor
            # selection may authorize a named contact/channel. Automatic materialization never
            # turns the coarse switch into reveal authority.
            continue
        if raw in CONTACT_PROFESSIONAL_FIELD_KEYS or (
            classify_field_key(raw) is FieldClass.CONTACT_FACET
        ):
            admitted.append(FieldKey(raw))
    return tuple(dict.fromkeys(admitted))


def _claims_for_contact(claims: Sequence[Claim], contact_id: EntityId) -> tuple[Claim, ...]:
    return tuple(claim for claim in claims if claim.entity_id == contact_id)


def _first_claim(claims: Sequence[Claim], field_key: str) -> Claim | None:
    return next((claim for claim in claims if str(claim.field_key) == field_key), None)


def _role_is_plausible(claim: Claim | None) -> bool:
    return bool(
        claim is not None
        and isinstance(claim.value_json, dict)
        and claim.value_json.get("plausible") is True
        and claim.identity_binding is IdentityBinding.STRONG
    )


class ContactResearchSelectionMaterializer:
    """Resolve committee refs plus current policy to one durable no-widening selection.

    A previously persisted active selection wins, including an explicitly approved reveal
    successor.  Automatic materialization is deliberately no-reveal and only selects plausible,
    strongly admitted members and directive-named contact fields.
    """

    def __init__(
        self,
        *,
        conn_factory: ConnFactory = transaction,
        config_store: OverlayStore | None = None,
    ) -> None:
        self._conn_factory = conn_factory
        self._config_store = config_store

    async def materialize(
        self,
        *,
        workspace_id: str,
        project_run_id: ProjectRunId,
        account_run_id: RunId,
        account_entity_id: EntityId,
        contact_entity_ids: Sequence[EntityId],
        committee_claim_ids: Sequence[ClaimId],
    ) -> ContactResearchSelection | None:
        if not contact_entity_ids or not committee_claim_ids:
            return None
        async with self._conn_factory() as conn:
            # A cancellation is durable steering authority.  Read the latest receipt including a
            # cancelled one so automatic re-entry cannot silently mint a replacement from the
            # same old directive.  A separately approved successor is a newer persisted row.
            existing = await latest_contact_research_selection(
                conn,
                workspace_id=workspace_id,
                project_run_id=project_run_id,
                account_id=account_entity_id,
                include_cancelled=True,
            )
            if existing is not None:
                cancellation = await contact_research_selection_cancellation(
                    conn,
                    workspace_id=workspace_id,
                    selection_id=existing.selection_id,
                )
                if cancellation is not None:
                    return existing
                await self._validate_existing(
                    conn,
                    selection=existing,
                    account_run_id=account_run_id,
                    contact_entity_ids=contact_entity_ids,
                    committee_claim_ids=committee_claim_ids,
                )
                return existing

            recorded_claims = await claims_by_ids(
                conn,
                committee_claim_ids,
                scope=WorkspaceScope.for_workspace(workspace_id),
                include_superseded=True,
            )
            if len(recorded_claims) != len(set(committee_claim_ids)):
                raise ContactResearchSelectionError(
                    "committee selection contains missing or foreign claim refs"
                )
            allowed_committee_runs = committee_claim_runs(account_run_id, project_run_id)
            if any(
                claim.run_id not in allowed_committee_runs
                or claim.research_mode is not ResearchMode.COMMITTEE_DISCOVERY
                for claim in recorded_claims.values()
            ):
                raise ContactResearchSelectionError(
                    "committee selection claims cross their exact account run"
                )
            # Expired professional facts are acquisition gaps, not lost committee identity.
            # Work only from current rows below: role/persona/discovery must still be current for
            # admission, while an expired C1 fact is simply omitted and may be reacquired later.
            live_claims = await claims_by_ids(
                conn,
                committee_claim_ids,
                scope=WorkspaceScope.for_workspace(workspace_id),
            )
            claims = tuple(live_claims.values())
            if any(
                claim.field_key in {ROLE_ON_COMMITTEE, PERSONA, DISCOVERY_PROVENANCE_FIELD}
                and claim.id not in live_claims
                for claim in recorded_claims.values()
            ):
                raise ContactResearchSelectionError(
                    "committee identity authority is expired or superseded"
                )
            # The account_run pins the directive. Read it directly rather than accepting a caller
            # copy; the selection is authority and therefore must originate at the database seam.
            account_run = await get_account_run(conn, account_run_id)
            if account_run is None or account_run.research_directive is None:
                raise ContactResearchSelectionError(
                    "contact selection requires a directive-pinned account run"
                )
            if (
                account_run.project_run_id != project_run_id
                or account_run.entity_id != account_entity_id
            ):
                raise ContactResearchSelectionError(
                    "contact selection crosses its account-run subject"
                )
            directive_pin = account_run.research_directive
            effective = await effective_account_research_directive(
                conn,
                workspace_id=workspace_id,
                directive_id=directive_pin.directive_id,
                account_id=account_entity_id,
                expected_pin=directive_pin,
            )
            directive = await get_research_directive(
                conn,
                directive_pin.directive_id,
                workspace_id=workspace_id,
            )
            if (
                directive is None
                or directive.confirmed_by is None
                or directive.confirming_turn_ref is None
                or directive.confirmed_at is None
                or effective.project_id != directive.project_id
                or not effective.privacy_policy.contact_profiling_allowed
            ):
                return None

            policy = get_config(
                workspace_id,
                effective.icp_key,
                store=self._config_store,
            ).contact_research_policy.pin()
            fields = _contact_fields(effective.field_keys)
            if not fields:
                return None
            field_tokens = {str(field_key) for field_key in fields}
            question_ids = tuple(
                item.question_id
                for item in sorted(
                    effective.questions,
                    key=lambda item: (item.priority, item.question_id),
                )
                if (item.target_field_key in field_tokens)
                or (item.target_facet in field_tokens)
                or (
                    item.target_facet is not None
                    and f"contact.facet.{item.target_facet}" in field_tokens
                )
            )[: policy.exa_max_additional_queries]
            persona_filter = set(effective.committee_plan.personas)
            targets: list[ContactResearchTarget] = []
            for contact_id in tuple(dict.fromkeys(contact_entity_ids)):
                if len(targets) >= policy.max_selected_contacts:
                    break
                contact = await get_contact(conn, contact_id)
                if (
                    contact is None
                    or contact.workspace_id != workspace_id
                    or contact.account_entity_id != account_entity_id
                    or contact.merged_into is not None
                    or not contact.linkedin_url
                ):
                    continue
                member_claims = _claims_for_contact(claims, contact_id)
                role = _first_claim(member_claims, ROLE_ON_COMMITTEE)
                persona = _first_claim(member_claims, PERSONA)
                identity = _first_claim(member_claims, DISCOVERY_PROVENANCE_FIELD)
                if not _role_is_plausible(role) or persona is None or identity is None:
                    continue
                assert role is not None
                if persona.identity_binding is not IdentityBinding.STRONG:
                    continue
                if persona_filter and str(persona.value_json) not in persona_filter:
                    continue
                target_fields = tuple(
                    field_key
                    for field_key in fields
                    if classify_field_key(field_key) is FieldClass.CONTACT_FACET
                    or _first_claim(member_claims, str(field_key)) is not None
                )[: policy.max_fields_per_contact]
                if not target_fields:
                    continue
                target_source_authority = tuple(
                    FieldSourceAuthority(
                        field_key=str(field_key),
                        source_keys=(
                            policy.personal_facet_source_plan
                            if classify_field_key(field_key) is FieldClass.CONTACT_FACET
                            else policy.professional_source_plan
                        ),
                    )
                    for field_key in target_fields
                )
                targets.append(
                    ContactResearchTarget(
                        contact_entity_id=contact_id,
                        selection_basis=ResearchSelectionBasis.COMMITTEE_MEMBER,
                        committee_claim_ids=(role.id, persona.id),
                        strong_identity_claim_ids=(identity.id,),
                        association_evidence_claim_ids=(identity.id,),
                        field_keys=target_fields,
                        field_source_authority=target_source_authority,
                        directional_question_ids=question_ids,
                        facet_keys=tuple(
                            field_key
                            for field_key in target_fields
                            if classify_field_key(field_key) is FieldClass.CONTACT_FACET
                        ),
                        exa_max_results=policy.exa_max_results,
                        email=ContactChannelAuthorization(channel=ContactChannel.EMAIL),
                        phone=ContactChannelAuthorization(channel=ContactChannel.PHONE),
                    )
                )
            if not targets:
                return None
            body = ContactResearchSelectionBody(
                workspace_id=workspace_id,
                project_id=effective.project_id,
                project_run_id=project_run_id,
                account_entity_id=account_entity_id,
                research_directive=directive_pin,
                targets=tuple(targets),
                policy=policy,
                source_profile_ref=_content_ref(
                    "contact-source-policy", effective.source_policy.model_dump(mode="json")
                ),
                jurisdiction_policy_ref=_content_ref(
                    "jurisdiction-policy",
                    get_config(
                        workspace_id, effective.icp_key, store=self._config_store
                    ).policy.model_dump(mode="json"),
                ),
                use_policy_ref=_content_ref(
                    "contact-use-policy",
                    tuple(value.value for value in effective.privacy_policy.allowed_use_classes),
                ),
                retention_policy_ref=(
                    f"contact-retention:{policy.channel_retention_days}d:{policy.sha256()}"
                ),
                budget_reservation_ref=(
                    f"contact-budget:{project_run_id}:{account_entity_id}:"
                    f"{effective.effort_policy.budget_cap_cents}"
                ),
                approved_by=directive.confirmed_by,
                approved_at=directive.confirmed_at,
            )
            selection = ContactResearchSelection.from_body(body, effective_policy=policy)
            approval = await directive_confirmation_selection_approval(
                conn,
                workspace_id=workspace_id,
                directive_id=directive.directive_id,
            )
            return await store_contact_research_selection(
                conn,
                selection,
                account_run_id=account_run_id,
                approval=approval,
            )

    async def _validate_existing(
        self,
        conn: AsyncConnection,
        *,
        selection: ContactResearchSelection,
        account_run_id: RunId,
        contact_entity_ids: Sequence[EntityId],
        committee_claim_ids: Sequence[ClaimId],
    ) -> None:
        body = selection.body
        allowed_contacts = set(contact_entity_ids)
        allowed_claims = set(committee_claim_ids)
        for target in body.targets:
            if target.selection_basis is not ResearchSelectionBasis.COMMITTEE_MEMBER:
                continue
            target_claims = {*target.committee_claim_ids, *target.strong_identity_claim_ids}
            if target.contact_entity_id not in allowed_contacts or not target_claims.issubset(
                allowed_claims
            ):
                raise ContactResearchSelectionError(
                    "persisted contact selection widens the materialized committee"
                )
        claims = await claims_by_ids(
            conn,
            (
                *(
                    claim_id
                    for target in body.targets
                    for claim_id in (
                        *target.committee_claim_ids,
                        *target.strong_identity_claim_ids,
                        *target.effective_association_evidence_claim_ids,
                    )
                ),
            ),
            scope=WorkspaceScope.for_workspace(body.workspace_id),
        )
        expected_claim_ids = {
            claim_id
            for target in body.targets
            for claim_id in (
                *target.committee_claim_ids,
                *target.strong_identity_claim_ids,
                *target.effective_association_evidence_claim_ids,
            )
        }
        committee_claim_set = {
            claim_id for target in body.targets for claim_id in target.committee_claim_ids
        }
        allowed_committee_runs = committee_claim_runs(account_run_id, body.project_run_id)
        if len(claims) != len(expected_claim_ids) or any(
            claim.id in committee_claim_set and claim.run_id not in allowed_committee_runs
            for claim in claims.values()
        ):
            raise ContactResearchSelectionError(
                "persisted contact selection claim lineage is no longer valid"
            )
        account_run = await get_account_run(conn, account_run_id)
        if (
            account_run is None
            or account_run.project_run_id != body.project_run_id
            or account_run.entity_id != body.account_entity_id
            or account_run.research_directive != body.research_directive
        ):
            raise ContactResearchSelectionError(
                "persisted contact selection differs from its account-run authority"
            )
        effective = await effective_account_research_directive(
            conn,
            workspace_id=body.workspace_id,
            directive_id=body.research_directive.directive_id,
            account_id=body.account_entity_id,
            expected_pin=body.research_directive,
        )
        policy = get_config(
            body.workspace_id,
            effective.icp_key,
            store=self._config_store,
        ).contact_research_policy.pin()
        selection.require_effective_policy(policy)


__all__ = ["ContactResearchSelectionError", "ContactResearchSelectionMaterializer"]
