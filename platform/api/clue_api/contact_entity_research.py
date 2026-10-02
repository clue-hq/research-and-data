"""M8D R8 exact-contact state, identity lock, tools, coverage, and finalization."""

from __future__ import annotations

import functools
from collections.abc import Awaitable, Callable, Mapping, Sequence
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Annotated, Literal, Protocol, cast
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

from langchain_core.tools import StructuredTool, ToolException
from pydantic import BaseModel, ConfigDict, Field, JsonValue, ValidationError
from sqlalchemy import text
from sqlalchemy.engine import RowMapping
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_agents.contact_entity_research import (
    AssessContactCoverageInput,
    ContactChannelProjection,
    ContactChannelToolInput,
    ContactCoverageProjection,
    ContactExistingClaimProjection,
    ContactFacetProjection,
    ContactIdentityProjection,
    ContactResearchStateProjection,
    DelegateContactFacetInput,
    FinalizeContactResearchInput,
    InspectContactEvidenceInput,
    ReadContactResearchStateInput,
)
from clue_agents.entity_research_contracts import (
    EntityResearchRuntimeContext,
    EntityResearchToolBinding,
    EntityResearchToolCall,
    canonical_sha256,
)
from clue_agents.entity_research_runtime import (
    ActiveEntityResearchToolExecution,
    EntityResearchExecutionGuard,
    EntityResearchFinalizationEngine,
    EntityResearchFinalizationRejected,
    EntityResearchGovernedToolRefusal,
    current_entity_research_tool_execution,
)
from clue_api.entity_research_tools import (
    EntityResearchGovernedRejection,
    convert_engine_authority_rejections,
    semantic_validation_error,
)
from clue_core import EntityId, serialize_value_json
from clue_core.entity_research import (
    ContactChannel,
    FinalizationVerification,
    ResearchFinalizationOutcome,
    ResearchFinalizationProposal,
    ResearchFinalizationReceipt,
    ResearchSubjectType,
)
from clue_research.claimstore import WorkspaceScope, current_values

ConnFactory = Callable[[], AbstractAsyncContextManager[AsyncConnection]]
NonEmptyStr = Annotated[str, Field(min_length=1)]
_PROPOSAL_NAMESPACE = uuid5(NAMESPACE_URL, "clue:m8d:r8:contact-finalization-proposal")
_RECEIPT_NAMESPACE = uuid5(NAMESPACE_URL, "clue:m8d:r8:contact-finalization-receipt")
_ACCOUNT_TOOL_PREFIXES = (
    "research_account",
    "enrich_account",
    "discover_buying_committee",
    "assess_account",
    "finalize_account",
)
_PROVIDER_TOOLS = {"research_contact_deep", "enrich_contact"}
#: Contact tools that buy nothing (see the account lane's identical note): repeating one in a
#: single model round is reading, never duplicated provider work.
_READ_ONLY_TOOL_NAMES = frozenset(
    {
        "read_contact_research_state",
        "inspect_contact_evidence",
        "read_research_result",
        "read_evidence",
    }
)
_TERMINAL_CHANNEL_STATES = {"succeeded", "rejected", "failed_terminal", "cancelled"}
_PENDING_CHANNEL_STATES = {
    "planned",
    "submitting",
    "waiting_external",
    "ready_to_validate",
    "validating",
}


class ContactResearchAuthorityError(EntityResearchGovernedToolRefusal):
    """Model-repairable contact guard/engine refusal (returned to the agent, never fatal)."""


class _EmptyInput(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class ContactFacetDelegate(Protocol):
    async def delegate(
        self,
        *,
        active: ActiveEntityResearchToolExecution,
        request: DelegateContactFacetInput,
    ) -> ContactFacetProjection: ...


@dataclass(frozen=True, slots=True)
class ContactChannelAdmission:
    provider_family: str
    budget_reservation_cents: Decimal
    provider_rate_limit_ref: str
    provider_concurrency_limit: int


class ContactChannelActions(Protocol):
    def admission(
        self,
        *,
        stage: Literal["acquisition", "validation"],
    ) -> ContactChannelAdmission | None: ...

    async def reveal(
        self,
        *,
        active: ActiveEntityResearchToolExecution,
        request: ContactChannelToolInput,
    ) -> ContactChannelProjection: ...

    async def validate(
        self,
        *,
        active: ActiveEntityResearchToolExecution,
        request: ContactChannelToolInput,
    ) -> ContactChannelProjection: ...


class ContactResearchStateStore:
    """Derive contact state only from the selected job and lock its canonical identity."""

    def __init__(self, *, conn_factory: ConnFactory) -> None:
        self._conn_factory = conn_factory

    @staticmethod
    def _active_contact() -> ActiveEntityResearchToolExecution:
        active = current_entity_research_tool_execution()
        if active.context.authorization.subject_type is not ResearchSubjectType.CONTACT:
            raise ContactResearchAuthorityError("contact engine tool used by a non-contact job")
        return active

    async def lock_identity(
        self,
        active: ActiveEntityResearchToolExecution | EntityResearchRuntimeContext,
    ) -> str:
        authorization = (
            active.authorization
            if isinstance(active, EntityResearchRuntimeContext)
            else active.context.authorization
        )
        selected = authorization.selected_subject
        strong_ids = self._claim_ids(selected.strong_identity_claim_refs)
        association_ids = self._claim_ids(selected.association_evidence_refs)
        async with self._conn_factory() as conn:
            contact = (
                (
                    await conn.execute(
                        text(
                            "SELECT contact.id, contact.account_entity_id, contact.workspace_id, "
                            "contact.full_name, contact.linkedin_url, contact.verified_email, "
                            "contact.status::text, contact.merged_into, account.canonical_name AS "
                            "account_name, account.primary_domain AS account_domain FROM "
                            "contact_entity contact JOIN account_entity account ON account.id="
                            "contact.account_entity_id WHERE contact.id=:contact_id AND "
                            "contact.workspace_id=:workspace_id AND account.workspace_id="
                            ":workspace_id AND account.status<>'merged' AND "
                            "account.merged_into IS NULL"
                        ),
                        {
                            "contact_id": authorization.subject_entity_id,
                            "workspace_id": authorization.workspace_id,
                        },
                    )
                )
                .mappings()
                .first()
            )
            if (
                contact is None
                or contact["account_entity_id"] != authorization.parent_account_id
                or str(contact["status"]) == "merged"
                or contact["merged_into"] is not None
                or not (contact["linkedin_url"] or contact["verified_email"])
            ):
                raise ContactResearchAuthorityError(
                    "selected contact identity is absent, merged, weak, or cross-account"
                )
            rows = (
                (
                    await conn.execute(
                        text(
                            "SELECT id, entity_id, field_key, identity_binding::text, "
                            "superseded_by FROM claim WHERE id=ANY(:claim_ids)"
                        ),
                        {"claim_ids": [*strong_ids, *association_ids]},
                    )
                )
                .mappings()
                .all()
            )
            by_id = {UUID(str(row["id"])): row for row in rows}
            if set(by_id) != set(strong_ids) | set(association_ids):
                raise ContactResearchAuthorityError("selected identity evidence is missing")
            if any(
                row["entity_id"] != authorization.subject_entity_id
                or row["superseded_by"] is not None
                for row in rows
            ):
                raise ContactResearchAuthorityError(
                    "selected identity evidence is stale or belongs to another contact"
                )
            for claim_id in strong_ids:
                row = by_id[claim_id]
                if (
                    str(row["field_key"]) != "core.discovery_provenance"
                    and str(row["identity_binding"]) != "strong"
                ):
                    raise ContactResearchAuthorityError(
                        "selected contact no longer has strong identity evidence"
                    )
            for claim_id in association_ids:
                if str(by_id[claim_id]["field_key"]) not in {
                    "core.discovery_provenance",
                    "contact.organization_relationship",
                }:
                    raise ContactResearchAuthorityError(
                        "selected contact lacks exact-account association evidence"
                    )
            lock_payload = {
                "contract": "m8d-r8-contact-identity-lock-v1",
                "job_id": str(authorization.job_id),
                "contact_id": str(authorization.subject_entity_id),
                "account_id": str(authorization.parent_account_id),
                "workspace_id": str(authorization.workspace_id),
                "full_name": contact["full_name"],
                "linkedin_url": contact["linkedin_url"],
                "verified_email_anchor": (
                    contact["verified_email"] if contact["linkedin_url"] is None else None
                ),
                "account_name": contact["account_name"],
                "account_domain": contact["account_domain"],
                "strong_claim_ids": sorted(str(value) for value in strong_ids),
                "association_claim_ids": sorted(str(value) for value in association_ids),
            }
            digest = canonical_sha256(lock_payload)
            await conn.execute(
                text(
                    "INSERT INTO entity_research_contact_identity_lock "
                    "(job_id, research_run_id, workspace_id, contact_entity_id, "
                    "parent_account_id, identity_json, identity_sha256) VALUES "
                    "(:job_id, :run_id, :workspace_id, :contact_id, :account_id, "
                    "CAST(:identity AS jsonb), :digest) ON CONFLICT (job_id) DO NOTHING"
                ),
                {
                    "job_id": authorization.job_id,
                    "run_id": authorization.research_run_id,
                    "workspace_id": authorization.workspace_id,
                    "contact_id": authorization.subject_entity_id,
                    "account_id": authorization.parent_account_id,
                    "identity": serialize_value_json(lock_payload),
                    "digest": digest,
                },
            )
            stored = (
                await conn.execute(
                    text(
                        "SELECT identity_sha256 FROM entity_research_contact_identity_lock "
                        "WHERE job_id=:job_id"
                    ),
                    {"job_id": authorization.job_id},
                )
            ).scalar_one()
        if str(stored) != digest:
            raise ContactResearchAuthorityError(
                "canonical contact identity changed after the job identity lock"
            )
        return f"contact-identity-lock:{digest}"

    async def state(
        self,
        active: ActiveEntityResearchToolExecution | None = None,
    ) -> ContactResearchStateProjection:
        active = active or self._active_contact()
        authorization = active.context.authorization
        identity_ref = await self.lock_identity(active)
        async with self._conn_factory() as conn:
            job = (
                (
                    await conn.execute(
                        text(
                            "SELECT current_state_sha256, spent_cents FROM entity_research_job "
                            "WHERE job_id=:job_id AND research_run_id=:run_id "
                            "AND workspace_id=:workspace_id AND subject_type='contact' "
                            "AND subject_entity_id=:contact_id AND parent_account_id=:account_id"
                        ),
                        {
                            "job_id": authorization.job_id,
                            "run_id": authorization.research_run_id,
                            "workspace_id": authorization.workspace_id,
                            "contact_id": authorization.subject_entity_id,
                            "account_id": authorization.parent_account_id,
                        },
                    )
                )
                .mappings()
                .first()
            )
            if job is None:
                raise ContactResearchAuthorityError(
                    "contact research job is absent or out of scope"
                )
            results = await self._result_rows(conn, authorization.job_id)
            fields = await self._field_rows(conn, authorization.job_id)
            pending = list(await self._pending_refs(conn, authorization.job_id))
            facets = await self._facet_rows(conn, authorization.job_id)
            channels = await self._channel_rows(conn, authorization.job_id)
            lock = (
                (
                    await conn.execute(
                        text(
                            "SELECT lock.identity_json, contact.verified_email FROM "
                            "entity_research_contact_identity_lock lock JOIN contact_entity "
                            "contact ON contact.id=lock.contact_entity_id AND "
                            "contact.workspace_id=lock.workspace_id WHERE lock.job_id=:job_id"
                        ),
                        {"job_id": authorization.job_id},
                    )
                )
                .mappings()
                .one()
            )
            current = await current_values(
                conn,
                [EntityId(authorization.subject_entity_id)],
                authorization.effective_admitted_field_keys,
                scope=WorkspaceScope.for_workspace(str(authorization.workspace_id)),
            )
        latest: dict[str, RowMapping] = {}
        for row in fields:
            if (
                str(row["subject_type"]) == "contact"
                and row["target_entity_id"] == authorization.subject_entity_id
            ):
                latest.setdefault(str(row["field_key"]), row)
        admitted = authorization.effective_admitted_field_keys
        existing_claims = tuple(
            ContactExistingClaimProjection(
                field_key=key,
                claim_ref=f"claim:{value.provenance.claim_id}",
                value=value.value_json,
                source_url=value.provenance.source_url,
                source_tier=int(value.provenance.source_tier),
                evidence_span=value.provenance.evidence_span,
                confidence=float(value.provenance.confidence),
                freshness_state=cast(Literal["fresh", "stale"], value.freshness_state.value),
                conflict=value.conflict,
            )
            for key in admitted
            if (value := current.get((EntityId(authorization.subject_entity_id), key))) is not None
        )
        fresh_existing = {
            item.field_key
            for item in existing_claims
            if item.freshness_state == "fresh" and item.evidence_span and not item.conflict
        }
        completed = tuple(
            key
            for key in admitted
            if key in fresh_existing or (key in latest and str(latest[key]["outcome"]) == "found")
        )
        unresolved = tuple(key for key in admitted if key not in set(completed))
        facet_projections = tuple(
            self._facet_projection(cast(Mapping[str, object], row)) for row in facets
        )
        channel_projections = tuple(
            self._channel_projection(cast(Mapping[str, object], row)) for row in channels
        )
        pending.extend(
            projection.operation_ref
            for projection in channel_projections
            if projection.state in _PENDING_CHANNEL_STATES
        )
        pending.extend(
            f"contact-facet:{projection.child_turn_id}"
            for projection in facet_projections
            if projection.state in {"started", "waiting_external"}
        )
        return ContactResearchStateProjection(
            job_id=authorization.job_id,
            contact_entity_id=authorization.subject_entity_id,
            parent_account_id=cast(UUID, authorization.parent_account_id),
            current_state_sha256=str(job["current_state_sha256"]),
            identity_lock_ref=identity_ref,
            identity=ContactIdentityProjection(
                contact_entity_id=authorization.subject_entity_id,
                parent_account_id=cast(UUID, authorization.parent_account_id),
                full_name=str(lock["identity_json"]["full_name"]),
                linkedin_url=lock["identity_json"].get("linkedin_url"),
                verified_email=lock["verified_email"],
                account_name=str(lock["identity_json"]["account_name"]),
                account_domain=lock["identity_json"].get("account_domain"),
            ),
            admitted_field_keys=admitted,
            admitted_source_keys=authorization.effective_admitted_source_keys,
            existing_claims=existing_claims,
            result_refs=tuple(f"research-result:{row['result_id']}" for row in results),
            completed_field_keys=completed,
            unresolved_field_keys=unresolved,
            facet_projections=facet_projections,
            channel_projections=channel_projections,
            pending_operation_refs=tuple(dict.fromkeys(pending)),
            spent_cents=str(Decimal(job["spent_cents"])),
        )

    async def evidence(self, inputs: InspectContactEvidenceInput) -> dict[str, JsonValue]:
        active = self._active_contact()
        state = await self.state(active)
        if not set(inputs.result_refs).issubset(state.result_refs):
            raise ContactResearchAuthorityError(
                "evidence request cites a result outside the exact contact job"
            )
        ids = [self._ref_uuid(value, "research-result:") for value in inputs.result_refs]
        async with self._conn_factory() as conn:
            rows = (
                (
                    await conn.execute(
                        text(
                            "SELECT result.result_id, field.field_key, field.outcome, "
                            "field.verification_status, evidence.evidence_id, "
                            "evidence.source_key, evidence.source_url, "
                            "evidence.provider_source_id, "
                            "'artifact:' || evidence.artifact_key AS artifact_ref "
                            "FROM entity_research_result result "
                            "JOIN entity_research_tool_request request_row ON "
                            "request_row.tool_request_id=result.tool_request_id "
                            "JOIN entity_research_result_field field ON "
                            "field.result_id=result.result_id "
                            "LEFT JOIN entity_research_result_evidence evidence ON "
                            "evidence.result_id=field.result_id AND "
                            "evidence.field_ordinal=field.ordinal "
                            "WHERE result.result_id=ANY(:result_ids) AND "
                            "request_row.job_id=:job_id ORDER BY result.created_at, "
                            "field.ordinal, evidence.evidence_ordinal"
                        ),
                        {"result_ids": ids, "job_id": active.context.authorization.job_id},
                    )
                )
                .mappings()
                .all()
            )
        return {
            "result_refs": list(inputs.result_refs),
            "evidence_index": [self._json_row(row) for row in rows],
            "current_state_sha256": state.current_state_sha256,
        }

    async def assess(self, inputs: AssessContactCoverageInput) -> ContactCoverageProjection:
        active = self._active_contact()
        authorization = active.context.authorization
        state = await self.state(active)
        if set(inputs.result_refs) != set(state.result_refs):
            raise ContactResearchAuthorityError(
                "coverage must inspect the complete current contact result set"
            )
        if state.pending_operation_refs:
            raise ContactResearchAuthorityError("coverage cannot close over pending contact work")
        unresolved_reasons: list[str] = []
        review_flags: list[str] = []
        coverage_id = uuid4()
        async with self._conn_factory() as conn:
            field_rows = await self._field_rows(conn, authorization.job_id)
            latest = {str(row["field_key"]): row for row in reversed(field_rows)}
            existing_by_field = {item.field_key: item for item in state.existing_claims}
            for key in state.unresolved_field_keys:
                row = latest.get(key)
                existing = existing_by_field.get(key)
                if row is not None:
                    reason = f"{row['outcome']}:{row['verification_status']}"
                elif existing is None:
                    reason = "not_researched"
                elif existing.conflict:
                    reason = "existing_claim_conflict"
                elif existing.freshness_state != "fresh":
                    reason = f"existing_claim_{existing.freshness_state}"
                else:
                    reason = "existing_claim_missing_evidence"
                unresolved_reasons.append(f"{key}:{reason}")
            if state.unresolved_field_keys:
                review_flags.append("contact_fields_unresolved")
            channel_by_kind = {item.channel: item for item in state.channel_projections}
            for channel in authorization.effective_channel_permissions:
                channel_projection = channel_by_kind.get(channel)
                if channel_projection is None:
                    review_flags.append(f"contact_channel_{channel.value}_not_requested")
                elif channel_projection.state != "succeeded":
                    review_flags.append(
                        f"contact_channel_{channel.value}_{channel_projection.state}"
                    )
            result_ids = [self._ref_uuid(value, "research-result:") for value in state.result_refs]
            claim_ids: tuple[str, ...] = ()
            evidence_ids: tuple[str, ...] = ()
            if result_ids:
                claim_ids = tuple(
                    str(value)
                    for value in (
                        await conn.execute(
                            text(
                                "SELECT DISTINCT unnest(claim_refs) FROM "
                                "entity_research_result_field WHERE result_id=ANY(:ids) ORDER BY 1"
                            ),
                            {"ids": result_ids},
                        )
                    ).scalars()
                )
                evidence_ids = tuple(
                    str(value)
                    for value in (
                        await conn.execute(
                            text(
                                "SELECT DISTINCT evidence_id FROM "
                                "entity_research_result_evidence WHERE result_id=ANY(:ids) "
                                "ORDER BY 1"
                            ),
                            {"ids": result_ids},
                        )
                    ).scalars()
                )
            existing_claim_ids = tuple(
                item.claim_ref.removeprefix("claim:")
                for item in state.existing_claims
                if item.field_key in state.completed_field_keys
                and item.freshness_state == "fresh"
                and item.evidence_span
                and not item.conflict
            )
            claim_ids = tuple(dict.fromkeys((*claim_ids, *existing_claim_ids)))
            facet_refs = tuple(
                f"contact-facet:{item.child_turn_id}" for item in state.facet_projections
            )
            channel_refs = tuple(item.operation_ref for item in state.channel_projections)
            projection = ContactCoverageProjection(
                coverage_id=coverage_id,
                coverage_ledger_ref=f"contact-coverage:{coverage_id}",
                current_state_sha256=state.current_state_sha256,
                identity_lock_ref=state.identity_lock_ref,
                completed_field_keys=state.completed_field_keys,
                unresolved_field_keys=state.unresolved_field_keys,
                unresolved_reasons=tuple(unresolved_reasons),
                result_refs=state.result_refs,
                facet_refs=facet_refs,
                channel_operation_refs=channel_refs,
                claim_refs=tuple(f"claim:{value}" for value in claim_ids),
                evidence_refs=tuple(f"research-evidence:{value}" for value in evidence_ids),
                review_flags=tuple(dict.fromkeys(review_flags)),
                review_item_refs=(),
                assessment_note=inputs.assessment_note,
            )
            await conn.execute(
                text(
                    "INSERT INTO entity_research_contact_coverage "
                    "(coverage_id, research_run_id, job_id, workspace_id, contact_entity_id, "
                    "parent_account_id, identity_lock_ref, result_refs, facet_refs, "
                    "channel_operation_refs, completed_field_keys, unresolved_field_keys, "
                    "unresolved_reasons, review_flags, claim_refs, evidence_refs, coverage_json, "
                    "coverage_sha256) VALUES (:coverage_id, :run_id, :job_id, :workspace_id, "
                    ":contact_id, :account_id, :identity_ref, :result_refs, :facet_refs, "
                    ":channel_refs, :completed, :unresolved, :reasons, :review_flags, "
                    ":claim_refs, :evidence_refs, CAST(:coverage AS jsonb), :digest)"
                ),
                {
                    "coverage_id": coverage_id,
                    "run_id": authorization.research_run_id,
                    "job_id": authorization.job_id,
                    "workspace_id": authorization.workspace_id,
                    "contact_id": authorization.subject_entity_id,
                    "account_id": authorization.parent_account_id,
                    "identity_ref": state.identity_lock_ref,
                    "result_refs": list(state.result_refs),
                    "facet_refs": list(facet_refs),
                    "channel_refs": list(channel_refs),
                    "completed": list(state.completed_field_keys),
                    "unresolved": list(state.unresolved_field_keys),
                    "reasons": unresolved_reasons,
                    "review_flags": review_flags,
                    "claim_refs": list(projection.claim_refs),
                    "evidence_refs": list(projection.evidence_refs),
                    "coverage": serialize_value_json(projection.model_dump(mode="json")),
                    "digest": canonical_sha256(projection),
                },
            )
            review_refs: list[str] = []
            for flag in projection.review_flags:
                review_id = uuid4()
                await conn.execute(
                    text(
                        "INSERT INTO entity_research_contact_review_item "
                        "(review_item_id, coverage_id, research_run_id, job_id, workspace_id, "
                        "contact_entity_id, reason_code, details_json) VALUES "
                        "(:review_id, :coverage_id, :run_id, :job_id, :workspace_id, "
                        ":contact_id, :reason, CAST(:details AS jsonb))"
                    ),
                    {
                        "review_id": review_id,
                        "coverage_id": coverage_id,
                        "run_id": authorization.research_run_id,
                        "job_id": authorization.job_id,
                        "workspace_id": authorization.workspace_id,
                        "contact_id": authorization.subject_entity_id,
                        "reason": flag,
                        "details": serialize_value_json(
                            {"coverage_ref": projection.coverage_ledger_ref, "reason": flag}
                        ),
                    },
                )
                review_refs.append(f"contact-review:{review_id}")
            digest = await self.refresh_state(conn, authorization.job_id)
        return projection.model_copy(
            update={"current_state_sha256": digest, "review_item_refs": tuple(review_refs)}
        )

    async def propose(self, inputs: FinalizeContactResearchInput) -> ResearchFinalizationProposal:
        active = self._active_contact()
        authorization = active.context.authorization
        coverage_id = self._ref_uuid(inputs.coverage_ledger_ref, "contact-coverage:")
        async with self._conn_factory() as conn:
            row = (
                (
                    await conn.execute(
                        text(
                            "SELECT * FROM entity_research_contact_coverage WHERE "
                            "coverage_id=:coverage_id AND job_id=:job_id AND "
                            "research_run_id=:run_id AND workspace_id=:workspace_id AND "
                            "contact_entity_id=:contact_id"
                        ),
                        {
                            "coverage_id": coverage_id,
                            "job_id": authorization.job_id,
                            "run_id": authorization.research_run_id,
                            "workspace_id": authorization.workspace_id,
                            "contact_id": authorization.subject_entity_id,
                        },
                    )
                )
                .mappings()
                .first()
            )
            if row is None:
                raise ContactResearchAuthorityError("finalization cites foreign contact coverage")
            pending = await self._pending_refs(conn, authorization.job_id)
            if pending:
                raise ContactResearchAuthorityError("finalization cannot retain pending operations")
            channel_pending = int(
                (
                    await conn.execute(
                        text(
                            "SELECT count(*) FROM entity_research_contact_channel_causation link "
                            "JOIN contact_channel_operation operation ON "
                            "operation.id=link.channel_operation_id WHERE link.job_id=:job_id "
                            "AND operation.state::text=ANY(:states)"
                        ),
                        {"job_id": authorization.job_id, "states": list(_PENDING_CHANNEL_STATES)},
                    )
                ).scalar_one()
            )
            if channel_pending:
                raise ContactResearchAuthorityError("contact channel work is still pending")
            state_sha = str(
                (
                    await conn.execute(
                        text(
                            "SELECT current_state_sha256 FROM entity_research_job "
                            "WHERE job_id=:job_id"
                        ),
                        {"job_id": authorization.job_id},
                    )
                ).scalar_one()
            )
            unresolved = tuple(str(value) for value in row["unresolved_field_keys"])
            review_flags = tuple(str(value) for value in row["review_flags"])
            expected = (
                ResearchFinalizationOutcome.NEEDS_REVIEW
                if unresolved or review_flags
                else ResearchFinalizationOutcome.COMPLETED
            )
            # Engine-derived, same normalization as the account lane: the model's requested
            # outcome never reaches the proposal, so a mismatch is corrected by the honest derived
            # value in the tool result instead of a refusal the model can wedge itself against.
            proposal_id = uuid5(
                _PROPOSAL_NAMESPACE,
                f"{authorization.job_id}:{coverage_id}:{state_sha}:{expected.value}",
            )
            proposal = ResearchFinalizationProposal(
                proposal_id=proposal_id,
                subject_type=ResearchSubjectType.CONTACT,
                target_entity_id=authorization.subject_entity_id,
                outcome=expected,
                current_state_sha256=state_sha,
                coverage_ledger_ref=inputs.coverage_ledger_ref,
                claim_delta_ledger_ref=f"contact-claim-delta-ledger:{coverage_id}",
                spend_reconciliation_ref=f"contact-spend-reconciliation:{coverage_id}",
                identity_use_verification_ref=str(row["identity_lock_ref"]),
                completed_field_keys=tuple(str(value) for value in row["completed_field_keys"]),
                unresolved_field_keys=unresolved,
                claim_refs=tuple(str(value) for value in row["claim_refs"]),
                evidence_refs=tuple(str(value) for value in row["evidence_refs"]),
                result_refs=tuple(str(value) for value in row["result_refs"]),
                unresolved_reasons=tuple(str(value) for value in row["unresolved_reasons"]),
                review_flags=review_flags,
            )
            await conn.execute(
                text(
                    "INSERT INTO entity_research_contact_finalization_intent "
                    "(proposal_id, coverage_id, research_run_id, job_id, workspace_id, "
                    "contact_entity_id, current_state_sha256, proposal_json, proposal_sha256) "
                    "VALUES (:proposal_id, :coverage_id, :run_id, :job_id, :workspace_id, "
                    ":contact_id, :state_sha, CAST(:proposal AS jsonb), :digest) "
                    "ON CONFLICT (proposal_id) DO NOTHING"
                ),
                {
                    "proposal_id": proposal_id,
                    "coverage_id": coverage_id,
                    "run_id": authorization.research_run_id,
                    "job_id": authorization.job_id,
                    "workspace_id": authorization.workspace_id,
                    "contact_id": authorization.subject_entity_id,
                    "state_sha": state_sha,
                    "proposal": serialize_value_json(proposal.model_dump(mode="json")),
                    "digest": canonical_sha256(proposal),
                },
            )
            stored = (
                (
                    await conn.execute(
                        text(
                            "SELECT proposal_json, proposal_sha256 FROM "
                            "entity_research_contact_finalization_intent "
                            "WHERE proposal_id=:proposal_id"
                        ),
                        {"proposal_id": proposal_id},
                    )
                )
                .mappings()
                .one()
            )
        if str(stored["proposal_sha256"]) != canonical_sha256(proposal):
            raise ContactResearchAuthorityError("contact finalization proposal replay changed")
        return ResearchFinalizationProposal.model_validate(stored["proposal_json"])

    async def refresh_state(self, conn: AsyncConnection, job_id: UUID) -> str:
        initial = str(
            (
                await conn.execute(
                    text(
                        "SELECT initial_state_sha256 FROM entity_research_job "
                        "WHERE job_id=:job_id FOR UPDATE"
                    ),
                    {"job_id": job_id},
                )
            ).scalar_one()
        )
        requests = (
            (
                await conn.execute(
                    text(
                        "SELECT tool_request_id, tool_input_sha256, idempotency_key FROM "
                        "entity_research_tool_request WHERE job_id=:job_id "
                        "ORDER BY created_at, tool_request_id"
                    ),
                    {"job_id": job_id},
                )
            )
            .mappings()
            .all()
        )
        results = await self._result_rows(conn, job_id)
        locks = (
            (
                await conn.execute(
                    text(
                        "SELECT identity_sha256 FROM entity_research_contact_identity_lock "
                        "WHERE job_id=:job_id"
                    ),
                    {"job_id": job_id},
                )
            )
            .scalars()
            .all()
        )
        facets = await self._facet_rows(conn, job_id)
        channels = await self._channel_rows(conn, job_id)
        coverage = (
            (
                await conn.execute(
                    text(
                        "SELECT coverage_id, coverage_sha256 FROM "
                        "entity_research_contact_coverage WHERE job_id=:job_id "
                        "ORDER BY created_at, coverage_id"
                    ),
                    {"job_id": job_id},
                )
            )
            .mappings()
            .all()
        )
        digest = canonical_sha256(
            {
                "contract": "m8d-contact-research-state-r8-v1",
                "initial": initial,
                "requests": [self._json_row(row) for row in requests],
                "results": [self._json_row(row) for row in results],
                "identity_locks": [str(value) for value in locks],
                "facets": [self._json_row(row) for row in facets],
                "channels": [self._json_row(row) for row in channels],
                "coverage": [self._json_row(row) for row in coverage],
            }
        )
        await conn.execute(
            text(
                "UPDATE entity_research_job SET current_state_sha256=:digest, updated_at=now() "
                "WHERE job_id=:job_id"
            ),
            {"digest": digest, "job_id": job_id},
        )
        return digest

    @staticmethod
    async def _result_rows(conn: AsyncConnection, job_id: UUID) -> Sequence[RowMapping]:
        return (
            (
                await conn.execute(
                    text(
                        "SELECT result.result_id, result.tool_request_id, "
                        "result.provider_operation_ref, result.provider_snapshot_ref, "
                        "result.result_sha256, result.delivery, request_row.tool_name "
                        "FROM entity_research_result result JOIN entity_research_tool_request "
                        "request_row ON request_row.tool_request_id=result.tool_request_id "
                        "WHERE request_row.job_id=:job_id ORDER BY result.created_at DESC, "
                        "result.result_id DESC"
                    ),
                    {"job_id": job_id},
                )
            )
            .mappings()
            .all()
        )

    @staticmethod
    async def _field_rows(conn: AsyncConnection, job_id: UUID) -> Sequence[RowMapping]:
        return (
            (
                await conn.execute(
                    text(
                        "SELECT field.field_key, field.outcome, field.verification_status, "
                        "field.subject_type, field.target_entity_id, result.created_at, "
                        "result.result_id FROM entity_research_result_field field JOIN "
                        "entity_research_result result ON result.result_id=field.result_id JOIN "
                        "entity_research_tool_request request_row ON "
                        "request_row.tool_request_id=result.tool_request_id WHERE "
                        "request_row.job_id=:job_id ORDER BY result.created_at DESC, "
                        "result.result_id DESC, field.ordinal"
                    ),
                    {"job_id": job_id},
                )
            )
            .mappings()
            .all()
        )

    @staticmethod
    async def _pending_refs(conn: AsyncConnection, job_id: UUID) -> Sequence[str]:
        return tuple(
            str(value)
            for value in (
                await conn.execute(
                    text(
                        "SELECT DISTINCT observation.provider_operation_ref FROM "
                        "entity_research_provider_observation observation JOIN "
                        "entity_research_tool_request request_row ON "
                        "request_row.tool_request_id=observation.tool_request_id WHERE "
                        "request_row.job_id=:job_id AND NOT EXISTS (SELECT 1 FROM "
                        "entity_research_result result JOIN entity_research_tool_request "
                        "result_request ON result_request.tool_request_id=result.tool_request_id "
                        "WHERE result.provider_operation_ref=observation.provider_operation_ref "
                        "AND result_request.job_id=request_row.job_id) "
                        # A fold without any result is a deterministic terminal rejection: never
                        # pending (live Sumble 402 livelock). It releases the operation whichever
                        # job filed it — a fold is a property of the operation, not of the asker,
                        # and the join above already scopes this to operations *this* job observed.
                        # Content-keyed operations are reused across jobs and the fold is written
                        # once, ON CONFLICT DO NOTHING, so demanding one's own job id left a
                        # replaying job waiting forever on work the provider had already finished
                        # (the live 2026-08-19 Millennium wedge). Results stay job-scoped: a
                        # cross-job result is repairable by a zero-spend replay under this job.
                        "AND NOT EXISTS (SELECT 1 FROM "
                        "entity_research_provider_settlement_fold fold WHERE "
                        "fold.provider_operation_ref=observation.provider_operation_ref AND "
                        "NOT EXISTS (SELECT 1 FROM "
                        "entity_research_result settled WHERE settled.provider_operation_ref="
                        "fold.provider_operation_ref)) ORDER BY 1"
                    ),
                    {"job_id": job_id},
                )
            ).scalars()
        )

    @staticmethod
    async def _facet_rows(conn: AsyncConnection, job_id: UUID) -> Sequence[RowMapping]:
        return (
            (
                await conn.execute(
                    text(
                        "SELECT DISTINCT ON (facet_key) facet_key, child_ordinal, state, "
                        "child_turn_id, result_refs, claim_refs, evidence_refs, wait_ref, "
                        "event_seq FROM entity_research_contact_facet_event "
                        "WHERE job_id=:job_id ORDER BY facet_key, event_seq DESC"
                    ),
                    {"job_id": job_id},
                )
            )
            .mappings()
            .all()
        )

    @staticmethod
    async def _channel_rows(conn: AsyncConnection, job_id: UUID) -> Sequence[RowMapping]:
        return (
            (
                await conn.execute(
                    text(
                        "SELECT DISTINCT ON (operation.channel) operation.channel::text AS "
                        "channel, operation.id, operation.state::text AS state, "
                        "operation.acquisition_source_key, operation.validation_source_key, "
                        "operation.observed_claim_id, operation.validation_json, "
                        "operation.acquisition_cost_cents_charged, "
                        "operation.validation_cost_cents_charged, link.stage, "
                        "COALESCE((SELECT array_agg('artifact:' || artifact_key ORDER BY ordinal) "
                        "FROM contact_channel_artifact artifact WHERE artifact.operation_id="
                        "operation.id), ARRAY[]::text[]) AS artifact_refs, "
                        "COALESCE((SELECT array_agg(provider_request_id ORDER BY ordinal) "
                        "FILTER (WHERE provider_request_id IS NOT NULL) FROM "
                        "contact_channel_artifact artifact WHERE artifact.operation_id="
                        "operation.id), ARRAY[]::text[]) AS provider_request_ids "
                        "FROM entity_research_contact_channel_causation link JOIN "
                        "contact_channel_operation operation ON operation.id="
                        "link.channel_operation_id WHERE link.job_id=:job_id "
                        "ORDER BY operation.channel, "
                        "CASE link.stage WHEN 'validation' THEN 1 ELSE 0 END DESC, "
                        "link.created_at DESC, link.causation_id DESC"
                    ),
                    {"job_id": job_id},
                )
            )
            .mappings()
            .all()
        )

    @staticmethod
    def _facet_projection(row: Mapping[str, object]) -> ContactFacetProjection:
        return ContactFacetProjection(
            facet_key=str(row["facet_key"]),
            child_ordinal=int(cast(int, row["child_ordinal"])),
            state=cast(Literal["started", "waiting_external", "completed"], row["state"]),
            child_turn_id=cast(UUID, row["child_turn_id"]),
            result_refs=tuple(str(value) for value in cast(Sequence[object], row["result_refs"])),
            claim_refs=tuple(str(value) for value in cast(Sequence[object], row["claim_refs"])),
            evidence_refs=tuple(
                str(value) for value in cast(Sequence[object], row["evidence_refs"])
            ),
            wait_ref=str(row["wait_ref"]) if row["wait_ref"] is not None else None,
        )

    @staticmethod
    def _channel_projection(row: Mapping[str, object]) -> ContactChannelProjection:
        validation = row["validation_json"] if isinstance(row["validation_json"], dict) else {}
        return ContactChannelProjection(
            channel=ContactChannel(str(row["channel"])),
            operation_ref=f"contact-channel-operation:{row['id']}",
            stage=cast(Literal["acquisition", "validation"], row["stage"]),
            state=str(row["state"]),
            acquisition_source_key=str(row["acquisition_source_key"]),
            validation_source_key=str(row["validation_source_key"]),
            observed_claim_ref=(
                f"claim:{row['observed_claim_id']}" if row["observed_claim_id"] else None
            ),
            validation_state=(str(validation.get("state")) if validation.get("state") else None),
            delivery_eligible=bool(
                str(validation.get("state")) in {"validated", "verified_identity"}
                and str(validation.get("use_decision")) == "allowed"
            ),
            artifact_refs=tuple(
                str(value) for value in cast(Sequence[object], row["artifact_refs"])
            ),
            provider_request_ids=tuple(
                str(value) for value in cast(Sequence[object], row["provider_request_ids"])
            ),
            acquisition_cost_cents=str(
                Decimal(cast(Decimal, row["acquisition_cost_cents_charged"]))
            ),
            validation_cost_cents=str(Decimal(cast(Decimal, row["validation_cost_cents_charged"]))),
        )

    @staticmethod
    def _claim_ids(references: Sequence[str]) -> tuple[UUID, ...]:
        return tuple(ContactResearchStateStore._ref_uuid(value, "claim:") for value in references)

    @staticmethod
    def _ref_uuid(reference: str, prefix: str) -> UUID:
        if not reference.startswith(prefix):
            raise ContactResearchAuthorityError("contact research reference uses the wrong scheme")
        try:
            return UUID(reference.removeprefix(prefix))
        except ValueError as exc:
            raise ContactResearchAuthorityError("contact research reference is malformed") from exc

    @staticmethod
    def _json_row(row: Mapping[str, object] | RowMapping) -> dict[str, JsonValue]:
        return cast(
            dict[str, JsonValue],
            {
                key: (str(value) if isinstance(value, (UUID, Decimal, datetime)) else value)
                for key, value in row.items()
            },
        )


class ContactResearchExecutionGuard(EntityResearchExecutionGuard):
    """Protect exact contact, source, channel, facet, and dependent-decision ordering."""

    def __init__(self, *, conn_factory: ConnFactory) -> None:
        self._conn_factory = conn_factory

    async def authorize_parallel(
        self,
        *,
        context: EntityResearchRuntimeContext,
        calls: Sequence[EntityResearchToolCall],
    ) -> None:
        if context.authorization.subject_type is not ResearchSubjectType.CONTACT:
            raise ContactResearchAuthorityError("contact guard received another subject type")
        names = [call.tool_name for call in calls]
        duplicates = {
            name for name in names if names.count(name) > 1 and name not in _READ_ONLY_TOOL_NAMES
        }
        if duplicates:
            if duplicates != {"delegate_contact_facet"}:
                raise ContactResearchAuthorityError(
                    "one model round cannot duplicate contact provider work"
                )
            facets = {
                str(call.arguments.get("facet_key", ""))
                for call in calls
                if call.tool_name == "delegate_contact_facet"
            }
            if "" in facets or len(facets) != names.count("delegate_contact_facet"):
                raise ContactResearchAuthorityError(
                    "parallel contact facet calls require distinct selected facets"
                )
        if {"reveal_contact_channel", "validate_contact_channel"}.issubset(names):
            raise ContactResearchAuthorityError("channel acquisition must precede validation")
        if "assess_contact_coverage" in names and len(names) > 1:
            raise ContactResearchAuthorityError("contact coverage is a dependent decision")
        if "finalize_contact_research" in names and len(names) > 1:
            raise ContactResearchAuthorityError("contact finalization is a terminal decision")

    async def authorize_tool(
        self,
        *,
        context: EntityResearchRuntimeContext,
        call: EntityResearchToolCall,
        journal_event_ref: str,
    ) -> None:
        del journal_event_ref
        authorization = context.authorization
        if any(call.tool_name.startswith(prefix) for prefix in _ACCOUNT_TOOL_PREFIXES):
            raise ContactResearchAuthorityError("contact agent cannot perform account research")
        fields = set(cast(Sequence[str], call.arguments.get("field_keys", ())))
        sources = set(cast(Sequence[str], call.arguments.get("source_keys", ())))
        if fields and not fields.issubset(authorization.effective_admitted_field_keys):
            raise ContactResearchAuthorityError("contact tool widened selected fields")
        if sources and not sources.issubset(authorization.effective_admitted_source_keys):
            raise ContactResearchAuthorityError("contact tool widened selected sources")
        if call.tool_name == "research_contact_deep" and sources != {"exa_deep"}:
            raise ContactResearchAuthorityError("contact deep research uses target-locked Exa")
        if call.tool_name == "enrich_contact" and "exa_deep" in sources:
            raise ContactResearchAuthorityError("structured contact enrichment is independent")
        if call.tool_name in _PROVIDER_TOOLS and not fields:
            # Parity with the account guard: ``EntityResearchSemanticToolInput.field_keys`` has no
            # minimum length and the record-time field/source pairing check is conditional on a
            # non-empty set, so a zero-field bundle reached the provider action and died there on
            # ``EntityResearchResultIntegrityError`` — the *suspending* species — for what is a
            # model argument mistake. Refuse it here as the turn the agent can act on.
            raise ContactResearchAuthorityError("contact research needs at least one field to buy")
        if call.tool_name == "delegate_contact_facet":
            facet = str(call.arguments.get("facet_key", ""))
            if facet not in authorization.effective_facet_keys:
                raise ContactResearchAuthorityError("facet delegation widened selected facets")
        if call.tool_name in {"reveal_contact_channel", "validate_contact_channel"}:
            requested = str(call.arguments.get("channel", ""))
            try:
                channel = ContactChannel(requested)
            except ValueError as invalid:
                # A channel name the model invented is not a ``ContactChannel`` member, and a raw
                # ``ValueError`` here is not an ``EntityResearchGovernedToolRefusal``, so the
                # middleware could not render it and the whole contact job failed on a typo.
                permitted = sorted(
                    value.value for value in authorization.effective_channel_permissions
                )
                raise ContactResearchAuthorityError(
                    f"channel tool named an unknown channel {requested!r}; the exact permitted "
                    f"channels are {permitted}"
                ) from invalid
            if channel not in authorization.effective_channel_permissions:
                raise ContactResearchAuthorityError("channel tool widened exact permission")
        async with self._conn_factory() as conn:
            closed = int(
                (
                    await conn.execute(
                        text(
                            "SELECT count(*) FROM entity_research_contact_coverage "
                            "WHERE job_id=:job_id"
                        ),
                        {"job_id": authorization.job_id},
                    )
                ).scalar_one()
            )
            if call.tool_name in {"assess_contact_coverage", "finalize_contact_research"}:
                pending = await ContactResearchStateStore._pending_refs(conn, authorization.job_id)
                if pending:
                    raise ContactResearchAuthorityError(
                        "dependent contact decision has pending provider work"
                    )
        if closed and call.tool_name in _PROVIDER_TOOLS | {
            "delegate_contact_facet",
            "reveal_contact_channel",
            "validate_contact_channel",
        }:
            raise ContactResearchAuthorityError(
                "contact research cannot resume after coverage close"
            )

    async def observe_tool_result(
        self,
        *,
        context: EntityResearchRuntimeContext,
        call: EntityResearchToolCall,
        result: object,
    ) -> None:
        del context, call, result


class ContactResearchFinalizationEngine(EntityResearchFinalizationEngine):
    def __init__(self, *, conn_factory: ConnFactory) -> None:
        self._conn_factory = conn_factory

    async def accept(
        self,
        *,
        context: EntityResearchRuntimeContext,
        proposal: ResearchFinalizationProposal,
    ) -> ResearchFinalizationReceipt:
        authorization = context.authorization
        if (
            authorization.subject_type is not ResearchSubjectType.CONTACT
            or proposal.subject_type is not ResearchSubjectType.CONTACT
            or proposal.target_entity_id != authorization.subject_entity_id
        ):
            raise EntityResearchFinalizationRejected(
                "contact finalization widens subject authority"
            )
        async with self._conn_factory() as conn:
            row = (
                (
                    await conn.execute(
                        text(
                            "SELECT intent.proposal_json, intent.proposal_sha256, "
                            "intent.current_state_sha256, coverage.identity_lock_ref, "
                            "coverage.completed_field_keys, coverage.unresolved_field_keys, "
                            "job.current_state_sha256 AS job_state, "
                            "job.spent_cents AS job_spent, run.spent_cents AS run_spent, "
                            "((SELECT COALESCE(sum(settled_cost_cents), 0) FROM "
                            "entity_research_provider_settlement_fold fold WHERE "
                            "fold.job_id=intent.job_id) + (SELECT COALESCE(sum(cost_cents), 0) "
                            "FROM entity_research_contact_channel_cost_fold channel_fold WHERE "
                            "channel_fold.job_id=intent.job_id)) AS folded_spend, "
                            "(SELECT COALESCE(sum(run_job.spent_cents), 0) FROM "
                            "entity_research_job run_job WHERE run_job.research_run_id="
                            "intent.research_run_id) AS run_job_spend, "
                            "(SELECT count(*) FROM entity_research_contact_review_item review "
                            "WHERE review.coverage_id=coverage.coverage_id AND "
                            "review.state='open') AS open_reviews, "
                            "(SELECT count(*) FROM entity_research_provider_observation obs JOIN "
                            "entity_research_tool_request req ON req.tool_request_id="
                            "obs.tool_request_id WHERE req.job_id=intent.job_id AND NOT EXISTS "
                            "(SELECT 1 FROM entity_research_result result JOIN "
                            "entity_research_tool_request result_request ON "
                            "result_request.tool_request_id=result.tool_request_id WHERE "
                            "result.provider_operation_ref=obs.provider_operation_ref AND "
                            "result_request.job_id=req.job_id) AND NOT EXISTS "
                            # Same predicate as ``_pending_refs``, and for the same reason: the
                            # fold releases this job's observation whichever job filed it, because
                            # a fold says the provider is done with the operation. Only the spend
                            # sum above stays job-scoped — a replaying job bought nothing.
                            "(SELECT 1 FROM entity_research_provider_settlement_fold fold "
                            "WHERE fold.provider_operation_ref=obs.provider_operation_ref "
                            "AND NOT EXISTS (SELECT 1 FROM "
                            "entity_research_result settled WHERE "
                            "settled.provider_operation_ref=fold.provider_operation_ref))) "
                            "AS pending, "
                            "ARRAY(SELECT DISTINCT field.field_key FROM "
                            "entity_research_result_field field JOIN entity_research_result "
                            "result ON result.result_id=field.result_id JOIN "
                            "entity_research_result_evidence evidence ON evidence.result_id="
                            "field.result_id AND evidence.field_ordinal=field.ordinal WHERE "
                            "'research-result:' || result.result_id::text="
                            "ANY(coverage.result_refs) AND field.subject_type='contact' AND "
                            "field.target_entity_id=intent.contact_entity_id AND "
                            "field.outcome='found') AS result_evidence_fields, "
                            "(SELECT count(*) FROM unnest(coverage.completed_field_keys) key "
                            "WHERE NOT EXISTS (SELECT 1 FROM entity_research_result_field field "
                            "JOIN entity_research_result result ON result.result_id="
                            "field.result_id JOIN entity_research_result_evidence evidence ON "
                            "evidence.result_id=field.result_id AND evidence.field_ordinal="
                            "field.ordinal WHERE 'research-result:' || result.result_id::text="
                            "ANY(coverage.result_refs) AND field.subject_type='contact' AND "
                            "field.target_entity_id=intent.contact_entity_id AND "
                            "field.field_key=key AND field.outcome='found') AND NOT EXISTS "
                            "(SELECT 1 FROM claim current_claim WHERE "
                            "'claim:' || current_claim.id::text=ANY(coverage.claim_refs) AND "
                            "current_claim.entity_id=intent.contact_entity_id AND "
                            "current_claim.field_key=key AND current_claim.superseded_by IS NULL "
                            "AND current_claim.evidence_span IS NOT NULL AND "
                            "btrim(current_claim.evidence_span)<>'' AND "
                            "(current_claim.reuse_scope='public_footprint' OR "
                            "current_claim.workspace_id=intent.workspace_id))) AS missing_evidence "
                            "FROM entity_research_contact_finalization_intent intent JOIN "
                            "entity_research_contact_coverage coverage ON coverage.coverage_id="
                            "intent.coverage_id JOIN entity_research_job job ON job.job_id="
                            "intent.job_id JOIN entity_research_run run ON run.research_run_id="
                            "intent.research_run_id WHERE intent.proposal_id=:proposal_id AND "
                            "intent.job_id=:job_id AND intent.research_run_id=:run_id AND "
                            "intent.workspace_id=:workspace_id AND "
                            "intent.contact_entity_id=:contact_id"
                        ),
                        {
                            "proposal_id": proposal.proposal_id,
                            "job_id": authorization.job_id,
                            "run_id": authorization.research_run_id,
                            "workspace_id": authorization.workspace_id,
                            "contact_id": authorization.subject_entity_id,
                        },
                    )
                )
                .mappings()
                .first()
            )
            current = (
                {}
                if row is None
                else await current_values(
                    conn,
                    [EntityId(authorization.subject_entity_id)],
                    set(row["completed_field_keys"]) - set(row["result_evidence_fields"]),
                    scope=WorkspaceScope.for_workspace(str(authorization.workspace_id)),
                )
            )
        if (
            row is None
            or ResearchFinalizationProposal.model_validate(row["proposal_json"]) != proposal
        ):
            raise EntityResearchFinalizationRejected(
                "model contact finalization lacks the exact engine proposal intent"
            )
        no_pending = int(row["pending"]) == 0
        state_matches = (
            str(row["job_state"])
            == proposal.current_state_sha256
            == str(row["current_state_sha256"])
        )
        coverage_matches = set(
            proposal.completed_field_keys + proposal.unresolved_field_keys
        ) == set(authorization.effective_admitted_field_keys)
        review_shape = (
            proposal.outcome is ResearchFinalizationOutcome.NEEDS_REVIEW
            and int(row["open_reviews"]) > 0
        ) or (
            proposal.outcome is ResearchFinalizationOutcome.COMPLETED
            and int(row["open_reviews"]) == 0
        )
        fresh_current_fields = {
            key
            for (_entity_id, key), value in current.items()
            if value.freshness_state.value == "fresh"
            and value.provenance.evidence_span
            and not value.conflict
        }
        existing_completed_fields = set(proposal.completed_field_keys) - set(
            row["result_evidence_fields"]
        )
        verification = FinalizationVerification(
            no_pending_operations=no_pending,
            evidence_complete=(
                int(row["missing_evidence"]) == 0
                and existing_completed_fields.issubset(fresh_current_fields)
            ),
            coverage_matches=coverage_matches and review_shape,
            spend_reconciled=(
                no_pending
                and Decimal(row["job_spent"]) == Decimal(row["folded_spend"])
                and Decimal(row["run_spent"]) == Decimal(row["run_job_spend"])
            ),
            identity_use_verification_complete=(
                bool(row["identity_lock_ref"])
                and proposal.identity_use_verification_ref == row["identity_lock_ref"]
            ),
            policy_scope_respected=True,
            current_state_matches=state_matches,
        )
        if not verification.all_passed():
            raise EntityResearchFinalizationRejected(
                f"contact finalization verification failed: {verification.model_dump()}"
            )
        return ResearchFinalizationReceipt(
            receipt_id=uuid5(_RECEIPT_NAMESPACE, str(proposal.proposal_id)),
            proposal=proposal,
            proposal_ref=f"contact-finalization-proposal:{proposal.proposal_id}",
            engine_actor="contact-research-finalization-engine@1",
            accepted_at=datetime.now(UTC),
            accepted_state_sha256=proposal.current_state_sha256,
            verification=verification,
        )


def contact_engine_tool_bindings(
    store: ContactResearchStateStore,
    *,
    facets: ContactFacetDelegate,
    channels: ContactChannelActions,
) -> Mapping[str, EntityResearchToolBinding]:
    def repairable(
        coroutine: Callable[..., Awaitable[dict[str, JsonValue]]],
    ) -> Callable[..., Awaitable[dict[str, JsonValue]]]:
        governed = convert_engine_authority_rejections(
            coroutine,
            error_types=(ContactResearchAuthorityError,),
        )

        @functools.wraps(governed)
        async def guarded(*args: object, **kwargs: object) -> dict[str, JsonValue]:
            try:
                return await governed(*args, **kwargs)
            except ValidationError as error:
                # Parity with the account lane: these tools re-validate their own arguments in the
                # body, so a malformed one surfaced here as a raw ``ValidationError`` and killed
                # the contact execution. A wrong-shaped argument is the model's to repair.
                raise ToolException(semantic_validation_error(error)) from error
            except EntityResearchGovernedRejection as rejection:
                # Already the repairable species (a model-typed reference of the wrong shape from
                # the shared read helpers, or a channel refusal): render it rather than let it
                # escape raw, which is exactly how the account lane lost a live job.
                raise ToolException(rejection.render()) from rejection

        return guarded

    async def read_state(include_result_index: bool = True) -> dict[str, JsonValue]:
        value = await store.state()
        payload = value.model_dump(mode="json")
        if not include_result_index:
            payload["result_refs"] = []
        return cast(dict[str, JsonValue], payload)

    async def inspect(**values: object) -> dict[str, JsonValue]:
        return await store.evidence(InspectContactEvidenceInput.model_validate(values))

    async def assess(**values: object) -> dict[str, JsonValue]:
        value = await store.assess(AssessContactCoverageInput.model_validate(values))
        return cast(dict[str, JsonValue], value.model_dump(mode="json"))

    async def delegate(**values: object) -> dict[str, JsonValue]:
        value = await facets.delegate(
            active=current_entity_research_tool_execution(),
            request=DelegateContactFacetInput.model_validate(values),
        )
        return cast(dict[str, JsonValue], value.model_dump(mode="json"))

    async def reveal(**values: object) -> dict[str, JsonValue]:
        value = await channels.reveal(
            active=current_entity_research_tool_execution(),
            request=ContactChannelToolInput.model_validate(values),
        )
        return cast(dict[str, JsonValue], value.model_dump(mode="json"))

    async def validate(**values: object) -> dict[str, JsonValue]:
        value = await channels.validate(
            active=current_entity_research_tool_execution(),
            request=ContactChannelToolInput.model_validate(values),
        )
        return cast(dict[str, JsonValue], value.model_dump(mode="json"))

    async def finalize(**values: object) -> dict[str, JsonValue]:
        value = await store.propose(FinalizeContactResearchInput.model_validate(values))
        return cast(dict[str, JsonValue], value.model_dump(mode="json"))

    tools = {
        "read_contact_research_state": StructuredTool.from_function(
            coroutine=repairable(read_state),
            name="read_contact_research_state",
            description="Read exact contact identity, results, facets, channels, gaps, and spend.",
            args_schema=ReadContactResearchStateInput,
            handle_validation_error=semantic_validation_error,
            handle_tool_error=True,
        ),
        "inspect_contact_evidence": StructuredTool.from_function(
            coroutine=repairable(inspect),
            name="inspect_contact_evidence",
            description="Inspect evidence for exact persisted contact results.",
            args_schema=InspectContactEvidenceInput,
            handle_validation_error=semantic_validation_error,
            handle_tool_error=True,
        ),
        "assess_contact_coverage": StructuredTool.from_function(
            coroutine=repairable(assess),
            name="assess_contact_coverage",
            description="Derive durable field, facet, channel, identity, and review coverage.",
            args_schema=AssessContactCoverageInput,
            handle_validation_error=semantic_validation_error,
            handle_tool_error=True,
        ),
        "delegate_contact_facet": StructuredTool.from_function(
            coroutine=repairable(delegate),
            name="delegate_contact_facet",
            description="Run one admitted depth-one contact facet child on the shared budget.",
            args_schema=DelegateContactFacetInput,
            handle_validation_error=semantic_validation_error,
            handle_tool_error=True,
        ),
        # The channel pair is popped out of this map and merged past ``compose`` by the contact
        # composition, so it never inherits the factory's rendering: without its own wrapper and
        # error handlers, every refusal it raised — a channel outside the selected permissions, a
        # validation with no acquisition — escaped raw and failed the whole contact execution.
        # ``EntityResearchExternalWait`` is not a ``ToolException`` and still suspends normally.
        "reveal_contact_channel": StructuredTool.from_function(
            coroutine=repairable(reveal),
            name="reveal_contact_channel",
            description=(
                "Acquire one explicitly approved exact-contact channel without validating it."
            ),
            args_schema=ContactChannelToolInput,
            handle_validation_error=semantic_validation_error,
            handle_tool_error=True,
        ),
        "validate_contact_channel": StructuredTool.from_function(
            coroutine=repairable(validate),
            name="validate_contact_channel",
            description="Independently validate one already acquired exact-contact channel.",
            args_schema=ContactChannelToolInput,
            handle_validation_error=semantic_validation_error,
            handle_tool_error=True,
        ),
        "finalize_contact_research": StructuredTool.from_function(
            coroutine=repairable(finalize),
            name="finalize_contact_research",
            description="Ask the engine for the only admissible contact finalization proposal.",
            args_schema=FinalizeContactResearchInput,
            handle_validation_error=semantic_validation_error,
            handle_tool_error=True,
        ),
    }
    return {name: EntityResearchToolBinding(tool=tool, version=1) for name, tool in tools.items()}


__all__ = [
    "ContactChannelAdmission",
    "ContactChannelActions",
    "ContactFacetDelegate",
    "ContactResearchAuthorityError",
    "ContactResearchExecutionGuard",
    "ContactResearchFinalizationEngine",
    "ContactResearchStateStore",
    "contact_engine_tool_bindings",
]
