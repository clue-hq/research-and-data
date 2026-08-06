"""M8D R5 engine-owned account-agent state, coverage, review, guard, and finalization."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from contextlib import AbstractAsyncContextManager
from datetime import UTC, datetime
from decimal import Decimal
from typing import Annotated, Any, cast
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, ConfigDict, Field, JsonValue
from sqlalchemy import text
from sqlalchemy.engine import RowMapping
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_agents.account_entity_research import (
    AccountCoverageProjection,
    AccountResearchStateProjection,
    AssessAccountCoverageInput,
    FinalizeAccountResearchInput,
    InspectAccountEvidenceInput,
    ReadAccountResearchStateInput,
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
    current_entity_research_tool_execution,
)
from clue_core import serialize_value_json
from clue_core.entity_research import (
    FinalizationVerification,
    ResearchFinalizationOutcome,
    ResearchFinalizationProposal,
    ResearchFinalizationReceipt,
    ResearchSubjectType,
)

ConnFactory = Callable[[], AbstractAsyncContextManager[AsyncConnection]]
NonEmptyStr = Annotated[str, Field(min_length=1)]
_PROPOSAL_NAMESPACE = uuid5(NAMESPACE_URL, "clue:m8d:r5:account-finalization-proposal")
_RECEIPT_NAMESPACE = uuid5(NAMESPACE_URL, "clue:m8d:r5:account-finalization-receipt")
_QUALITATIVE_SOURCE = "exa_deep"
_CONTACT_TOOL_PREFIXES = (
    "research_contact",
    "enrich_contact",
    "reveal_contact",
    "validate_contact",
)


class AccountResearchAuthorityError(RuntimeError):
    pass


class _EmptyInput(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class AccountResearchStateStore:
    """Derive account coverage from persisted R4 results; model prose is never authority."""

    def __init__(self, *, conn_factory: ConnFactory) -> None:
        self._conn_factory = conn_factory

    @staticmethod
    def _active_account() -> ActiveEntityResearchToolExecution:
        active = current_entity_research_tool_execution()
        if active.context.authorization.subject_type is not ResearchSubjectType.ACCOUNT:
            raise AccountResearchAuthorityError("account engine tool used by a non-account job")
        return active

    async def state(
        self, active: ActiveEntityResearchToolExecution | None = None
    ) -> AccountResearchStateProjection:
        active = active or self._active_account()
        authorization = active.context.authorization
        async with self._conn_factory() as conn:
            job = (
                (
                    await conn.execute(
                        text(
                            "SELECT current_state_sha256, spent_cents FROM entity_research_job "
                            "WHERE job_id=:job_id AND research_run_id=:run_id "
                            "AND workspace_id=:workspace_id AND subject_type='account' "
                            "AND subject_entity_id=:account_id"
                        ),
                        {
                            "job_id": authorization.job_id,
                            "run_id": authorization.research_run_id,
                            "workspace_id": authorization.workspace_id,
                            "account_id": authorization.subject_entity_id,
                        },
                    )
                )
                .mappings()
                .first()
            )
            if job is None:
                raise AccountResearchAuthorityError(
                    "account research job is absent or out of scope"
                )
            results = await self._result_rows(conn, authorization.job_id)
            fields = await self._field_rows(conn, authorization.job_id)
            pending = await self._pending_refs(conn, authorization.job_id)
            contact_count = int(
                (
                    await conn.execute(
                        text(
                            "SELECT count(*) FROM entity_research_tool_request "
                            "WHERE research_run_id=:run_id AND subject_type='contact'"
                        ),
                        {"run_id": authorization.research_run_id},
                    )
                ).scalar_one()
            )
        latest: dict[str, Mapping[str, object]] = {}
        committee_refs: list[str] = []
        member_ids: list[UUID] = []
        for row in results:
            if str(row["tool_name"]) == "discover_buying_committee":
                committee_refs.append(f"research-result:{row['result_id']}")
        for row in fields:
            if str(row["subject_type"]) == ResearchSubjectType.ACCOUNT.value:
                latest.setdefault(str(row["field_key"]), cast(Mapping[str, object], row))
            else:
                value = cast(UUID, row["target_entity_id"])
                if value not in member_ids:
                    member_ids.append(value)
        admitted = authorization.selection.admitted_field_keys
        completed = tuple(
            key for key in admitted if key in latest and str(latest[key]["outcome"]) == "found"
        )
        unresolved = tuple(key for key in admitted if key not in set(completed))
        return AccountResearchStateProjection(
            job_id=authorization.job_id,
            account_entity_id=authorization.subject_entity_id,
            current_state_sha256=str(job["current_state_sha256"]),
            admitted_field_keys=admitted,
            admitted_source_keys=authorization.selection.admitted_source_keys,
            committee_source_keys=authorization.selection.committee_source_keys,
            result_refs=tuple(f"research-result:{row['result_id']}" for row in results),
            completed_field_keys=completed,
            unresolved_field_keys=unresolved,
            committee_result_refs=tuple(committee_refs),
            committee_member_ids=tuple(member_ids),
            pending_operation_refs=tuple(pending),
            spent_cents=str(Decimal(job["spent_cents"])),
            contact_research_request_count=contact_count,
        )

    async def evidence(self, inputs: InspectAccountEvidenceInput) -> dict[str, JsonValue]:
        active = self._active_account()
        expected = set(inputs.result_refs)
        state = await self.state(active)
        if not expected.issubset(state.result_refs):
            raise AccountResearchAuthorityError(
                "evidence request cites a result outside the exact job"
            )
        ids = [UUID(ref.removeprefix("research-result:")) for ref in inputs.result_refs]
        async with self._conn_factory() as conn:
            rows = (
                (
                    await conn.execute(
                        text(
                            """
                            SELECT result.result_id, field.field_key, field.outcome,
                                   field.verification_status, evidence.evidence_id,
                                   evidence.source_key, evidence.source_url,
                                   evidence.provider_source_id,
                                   'artifact:' || evidence.artifact_key AS artifact_ref
                            FROM entity_research_result result
                            JOIN entity_research_tool_request request_row
                              ON request_row.tool_request_id=result.tool_request_id
                            JOIN entity_research_result_field field
                              ON field.result_id=result.result_id
                            LEFT JOIN entity_research_result_evidence evidence
                              ON evidence.result_id=field.result_id
                             AND evidence.field_ordinal=field.ordinal
                            WHERE result.result_id=ANY(:result_ids)
                              AND request_row.job_id=:job_id
                            ORDER BY result.created_at, field.ordinal, evidence.evidence_ordinal
                            """
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

    async def assess(self, inputs: AssessAccountCoverageInput) -> AccountCoverageProjection:
        active = self._active_account()
        authorization = active.context.authorization
        state = await self.state(active)
        if set(inputs.result_refs) != set(state.result_refs):
            raise AccountResearchAuthorityError(
                "coverage must inspect the complete current result set without omission"
            )
        if state.pending_operation_refs:
            raise AccountResearchAuthorityError("coverage cannot close over pending provider work")
        if state.contact_research_request_count:
            raise AccountResearchAuthorityError(
                "account coverage observed forbidden contact research"
            )
        coverage_id = uuid4()
        unresolved_reasons: list[str] = []
        async with self._conn_factory() as conn:
            field_rows = await self._field_rows(conn, authorization.job_id)
            latest_account: dict[str, Mapping[str, object]] = {}
            for row in field_rows:
                if str(row["subject_type"]) == "account":
                    latest_account.setdefault(
                        str(row["field_key"]), cast(Mapping[str, object], row)
                    )
            for field_key in state.unresolved_field_keys:
                selected_row = latest_account.get(field_key)
                reason = (
                    "not_researched"
                    if selected_row is None
                    else f"{selected_row['outcome']}:{selected_row['verification_status']}"
                )
                unresolved_reasons.append(f"{field_key}:{reason}")

            scope_count = int(
                (
                    await conn.execute(
                        text(
                            "SELECT count(*) FROM entity_research_account_committee_scope "
                            "WHERE job_id=:job_id"
                        ),
                        {"job_id": authorization.job_id},
                    )
                ).scalar_one()
            )
            ambiguous_count = int(
                (
                    await conn.execute(
                        text(
                            """
                            SELECT COALESCE(sum(
                                (projection.metadata_json->>'ambiguous_candidate_count')::integer
                            ), 0)
                            FROM entity_research_result result
                            JOIN entity_research_tool_request request_row
                              ON request_row.tool_request_id=result.tool_request_id
                            JOIN entity_research_sumble_projection projection
                              ON projection.provider_operation_ref=result.provider_operation_ref
                            WHERE request_row.job_id=:job_id
                              AND request_row.tool_name='discover_buying_committee'
                            """
                        ),
                        {"job_id": authorization.job_id},
                    )
                ).scalar_one()
            )
            confirmed_empty_count = int(
                (
                    await conn.execute(
                        text(
                            """
                            SELECT count(*)
                            FROM entity_research_result result
                            JOIN entity_research_tool_request request_row
                              ON request_row.tool_request_id=result.tool_request_id
                            WHERE request_row.job_id=:job_id
                              AND request_row.tool_name='discover_buying_committee'
                              AND result.confirmed_empty_discovery IS TRUE
                            """
                        ),
                        {"job_id": authorization.job_id},
                    )
                ).scalar_one()
            )
            committee_status, committee_flags = self._committee_coverage_status(
                result_count=len(state.committee_result_refs),
                member_count=len(state.committee_member_ids),
                scope_count=scope_count,
                ambiguous_count=ambiguous_count,
                confirmed_empty_count=confirmed_empty_count,
            )
            review_flags = list(committee_flags)
            if state.unresolved_field_keys:
                review_flags.append("account_fields_unresolved")

            result_ids = [UUID(ref.removeprefix("research-result:")) for ref in state.result_refs]
            claim_ids = tuple(
                str(value)
                for value in (
                    (
                        await conn.execute(
                            text(
                                "SELECT DISTINCT unnest(claim_refs) "
                                "FROM entity_research_result_field "
                                "WHERE result_id=ANY(:result_ids) ORDER BY 1"
                            ),
                            {"result_ids": result_ids},
                        )
                    )
                    .scalars()
                    .all()
                )
            )
            evidence_ids = tuple(
                str(value)
                for value in (
                    (
                        await conn.execute(
                            text(
                                "SELECT DISTINCT evidence_id FROM entity_research_result_evidence "
                                "WHERE result_id=ANY(:result_ids) ORDER BY 1"
                            ),
                            {"result_ids": result_ids},
                        )
                    )
                    .scalars()
                    .all()
                )
            )
            projection = AccountCoverageProjection(
                coverage_id=coverage_id,
                coverage_ledger_ref=f"account-coverage:{coverage_id}",
                current_state_sha256=state.current_state_sha256,
                completed_field_keys=state.completed_field_keys,
                unresolved_field_keys=state.unresolved_field_keys,
                unresolved_reasons=tuple(unresolved_reasons),
                committee_result_refs=state.committee_result_refs,
                committee_member_ids=state.committee_member_ids,
                committee_status=cast(Any, committee_status),
                claim_refs=tuple(f"claim:{value}" for value in claim_ids),
                evidence_refs=tuple(f"research-evidence:{value}" for value in evidence_ids),
                review_flags=tuple(dict.fromkeys(review_flags)),
                review_item_refs=(),
                assessment_note=inputs.assessment_note,
            )
            await conn.execute(
                text(
                    """
                    INSERT INTO entity_research_account_coverage
                        (coverage_id, research_run_id, job_id, workspace_id, account_entity_id,
                         result_refs, completed_field_keys, unresolved_field_keys,
                         unresolved_reasons, committee_result_refs, committee_member_ids,
                         committee_status, review_flags, claim_refs, evidence_refs,
                         coverage_json, coverage_sha256)
                    VALUES
                        (:coverage_id, :research_run_id, :job_id, :workspace_id, :account_id,
                         :result_refs, :completed, :unresolved, :reasons, :committee_refs,
                         :member_ids, :committee_status, :review_flags, :claim_refs,
                         :evidence_refs, CAST(:coverage_json AS jsonb), :coverage_sha256)
                    """
                ),
                {
                    "coverage_id": coverage_id,
                    "research_run_id": authorization.research_run_id,
                    "job_id": authorization.job_id,
                    "workspace_id": authorization.workspace_id,
                    "account_id": authorization.subject_entity_id,
                    "result_refs": list(state.result_refs),
                    "completed": list(state.completed_field_keys),
                    "unresolved": list(state.unresolved_field_keys),
                    "reasons": unresolved_reasons,
                    "committee_refs": list(state.committee_result_refs),
                    "member_ids": list(state.committee_member_ids),
                    "committee_status": committee_status,
                    "review_flags": review_flags,
                    "claim_refs": list(projection.claim_refs),
                    "evidence_refs": list(projection.evidence_refs),
                    "coverage_json": serialize_value_json(projection.model_dump(mode="json")),
                    "coverage_sha256": canonical_sha256(projection),
                },
            )
            review_refs: list[str] = []
            for flag in projection.review_flags:
                review_id = uuid4()
                await conn.execute(
                    text(
                        """
                        INSERT INTO entity_research_account_review_item
                            (review_item_id, coverage_id, research_run_id, job_id, workspace_id,
                             account_entity_id, reason_code, details_json)
                        VALUES (:review_id, :coverage_id, :run_id, :job_id, :workspace_id,
                                :account_id, :reason, CAST(:details AS jsonb))
                        """
                    ),
                    {
                        "review_id": review_id,
                        "coverage_id": coverage_id,
                        "run_id": authorization.research_run_id,
                        "job_id": authorization.job_id,
                        "workspace_id": authorization.workspace_id,
                        "account_id": authorization.subject_entity_id,
                        "reason": flag,
                        "details": serialize_value_json(
                            {"coverage_ref": projection.coverage_ledger_ref, "reason": flag}
                        ),
                    },
                )
                review_refs.append(f"account-review:{review_id}")
            digest = await self._refresh_account_state(conn, authorization.job_id)
        return projection.model_copy(
            update={"current_state_sha256": digest, "review_item_refs": tuple(review_refs)}
        )

    async def propose(self, inputs: FinalizeAccountResearchInput) -> ResearchFinalizationProposal:
        active = self._active_account()
        authorization = active.context.authorization
        coverage_id = self._ref_uuid(inputs.coverage_ledger_ref, "account-coverage:")
        async with self._conn_factory() as conn:
            row = (
                (
                    await conn.execute(
                        text(
                            """
                            SELECT coverage_id, completed_field_keys, unresolved_field_keys,
                                   unresolved_reasons, committee_status, review_flags,
                                   claim_refs, evidence_refs, result_refs
                            FROM entity_research_account_coverage
                            WHERE coverage_id=:coverage_id AND job_id=:job_id
                              AND research_run_id=:run_id AND workspace_id=:workspace_id
                              AND account_entity_id=:account_id
                            """
                        ),
                        {
                            "coverage_id": coverage_id,
                            "job_id": authorization.job_id,
                            "run_id": authorization.research_run_id,
                            "workspace_id": authorization.workspace_id,
                            "account_id": authorization.subject_entity_id,
                        },
                    )
                )
                .mappings()
                .first()
            )
            if row is None:
                raise AccountResearchAuthorityError("finalization cites foreign coverage")
            pending = await self._pending_refs(conn, authorization.job_id)
            if pending:
                raise AccountResearchAuthorityError("finalization cannot retain pending operations")
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
            expected_outcome = (
                ResearchFinalizationOutcome.NEEDS_REVIEW
                if review_flags or unresolved or str(row["committee_status"]) != "complete"
                else ResearchFinalizationOutcome.COMPLETED
            )
            if inputs.requested_outcome is not expected_outcome:
                raise AccountResearchAuthorityError(
                    f"requested outcome must be {expected_outcome.value} for persisted coverage"
                )
            proposal_id = uuid5(
                _PROPOSAL_NAMESPACE,
                f"{authorization.job_id}:{coverage_id}:{state_sha}:{expected_outcome.value}",
            )
            proposal = ResearchFinalizationProposal(
                proposal_id=proposal_id,
                subject_type=ResearchSubjectType.ACCOUNT,
                target_entity_id=authorization.subject_entity_id,
                outcome=expected_outcome,
                current_state_sha256=state_sha,
                coverage_ledger_ref=inputs.coverage_ledger_ref,
                claim_delta_ledger_ref=f"account-claim-delta-ledger:{coverage_id}",
                spend_reconciliation_ref=f"account-spend-reconciliation:{coverage_id}",
                identity_use_verification_ref=f"account-identity-use-verification:{coverage_id}",
                completed_field_keys=tuple(str(value) for value in row["completed_field_keys"]),
                unresolved_field_keys=unresolved,
                claim_refs=tuple(str(value) for value in row["claim_refs"]),
                evidence_refs=tuple(str(value) for value in row["evidence_refs"]),
                result_refs=tuple(str(value) for value in row["result_refs"]),
                unresolved_reasons=tuple(str(value) for value in row["unresolved_reasons"]),
                review_flags=review_flags,
            )
            values = {
                "proposal_id": proposal_id,
                "coverage_id": coverage_id,
                "run_id": authorization.research_run_id,
                "job_id": authorization.job_id,
                "workspace_id": authorization.workspace_id,
                "account_id": authorization.subject_entity_id,
                "state_sha": state_sha,
                "proposal_json": serialize_value_json(proposal.model_dump(mode="json")),
                "proposal_sha": canonical_sha256(proposal),
            }
            await conn.execute(
                text(
                    """
                    INSERT INTO entity_research_account_finalization_intent
                        (proposal_id, coverage_id, research_run_id, job_id, workspace_id,
                         account_entity_id, current_state_sha256, proposal_json, proposal_sha256)
                    VALUES (:proposal_id, :coverage_id, :run_id, :job_id, :workspace_id,
                            :account_id, :state_sha, CAST(:proposal_json AS jsonb), :proposal_sha)
                    ON CONFLICT (proposal_id) DO NOTHING
                    """
                ),
                values,
            )
            stored = (
                (
                    await conn.execute(
                        text(
                            "SELECT proposal_json, proposal_sha256 FROM "
                            "entity_research_account_finalization_intent "
                            "WHERE proposal_id=:proposal_id"
                        ),
                        {"proposal_id": proposal_id},
                    )
                )
                .mappings()
                .one()
            )
            if str(stored["proposal_sha256"]) != canonical_sha256(proposal):
                raise AccountResearchAuthorityError("finalization proposal replay changed")
        return ResearchFinalizationProposal.model_validate(stored["proposal_json"])

    async def _refresh_account_state(self, conn: AsyncConnection, job_id: UUID) -> str:
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
        request_rows = (
            (
                await conn.execute(
                    text(
                        "SELECT tool_request_id, tool_input_sha256, idempotency_key, "
                        "parent_operation_ref, parent_observation_ref, prior_result_sha256 "
                        "FROM entity_research_tool_request WHERE job_id=:job_id "
                        "ORDER BY created_at, tool_request_id"
                    ),
                    {"job_id": job_id},
                )
            )
            .mappings()
            .all()
        )
        observation_rows = (
            (
                await conn.execute(
                    text(
                        """
                        SELECT observation.tool_request_id, observation.provider_operation_ref,
                               observation.disposition, operation.provider_kind,
                               operation.source_key, operation.field_keys,
                               operation.request_artifact_ref, operation.reserved_at,
                               operation.dispatched_at
                        FROM entity_research_provider_observation observation
                        JOIN entity_research_tool_request request_row
                          ON request_row.tool_request_id=observation.tool_request_id
                        JOIN entity_research_provider_operation operation
                          ON operation.operation_ref=observation.provider_operation_ref
                        WHERE request_row.job_id=:job_id
                        ORDER BY observation.created_at, observation.observation_id
                        """
                    ),
                    {"job_id": job_id},
                )
            )
            .mappings()
            .all()
        )
        result_rows = await self._result_rows(conn, job_id)
        scope_rows = (
            (
                await conn.execute(
                    text(
                        "SELECT tool_request_id, scope_sha256 FROM "
                        "entity_research_account_committee_scope WHERE job_id=:job_id "
                        "ORDER BY created_at, scope_id"
                    ),
                    {"job_id": job_id},
                )
            )
            .mappings()
            .all()
        )
        coverage_rows = (
            (
                await conn.execute(
                    text(
                        "SELECT coverage_id, coverage_sha256 FROM entity_research_account_coverage "
                        "WHERE job_id=:job_id ORDER BY created_at, coverage_id"
                    ),
                    {"job_id": job_id},
                )
            )
            .mappings()
            .all()
        )
        digest = canonical_sha256(
            {
                "contract": "m8d-account-research-state-r5-v1",
                "initial_state_sha256": initial,
                "requests": [self._json_row(row) for row in request_rows],
                "observations": [self._json_row(row) for row in observation_rows],
                "results": [self._json_row(row) for row in result_rows],
                "committee_scopes": [self._json_row(row) for row in scope_rows],
                "coverage": [self._json_row(row) for row in coverage_rows],
            }
        )
        await conn.execute(
            text(
                "UPDATE entity_research_job SET current_state_sha256=:digest, "
                "updated_at=now() WHERE job_id=:job_id"
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
                        """
                        SELECT result.result_id, result.tool_request_id,
                               result.provider_operation_ref, result.provider_snapshot_ref,
                               result.result_sha256, result.delivery, request_row.tool_name
                        FROM entity_research_result result
                        JOIN entity_research_tool_request request_row
                          ON request_row.tool_request_id=result.tool_request_id
                        WHERE request_row.job_id=:job_id
                        ORDER BY result.created_at DESC, result.result_id DESC
                        """
                    ),
                    {"job_id": job_id},
                )
            )
            .mappings()
            .all()
        )

    @staticmethod
    def _committee_coverage_status(
        *,
        result_count: int,
        member_count: int,
        scope_count: int,
        ambiguous_count: int,
        confirmed_empty_count: int,
    ) -> tuple[str, tuple[str, ...]]:
        if result_count == 0:
            return "needs_review", ("committee_not_researched",)
        if scope_count != result_count:
            return "needs_review", ("committee_scope_missing_or_ambiguous",)
        if ambiguous_count:
            return "needs_review", ("committee_office_candidates_ambiguous",)
        if member_count:
            return "complete", ()
        if confirmed_empty_count == result_count:
            return "complete", ()
        return "partial", ("committee_no_identity_admitted_member",)

    @staticmethod
    async def _field_rows(conn: AsyncConnection, job_id: UUID) -> Sequence[RowMapping]:
        return (
            (
                await conn.execute(
                    text(
                        """
                        SELECT field.field_key, field.outcome, field.verification_status,
                               field.subject_type, field.target_entity_id,
                               result.created_at, result.result_id
                        FROM entity_research_result_field field
                        JOIN entity_research_result result ON result.result_id=field.result_id
                        JOIN entity_research_tool_request request_row
                          ON request_row.tool_request_id=result.tool_request_id
                        WHERE request_row.job_id=:job_id
                        ORDER BY result.created_at DESC, result.result_id DESC, field.ordinal
                        """
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
                (
                    await conn.execute(
                        text(
                            """
                            SELECT DISTINCT observation.provider_operation_ref
                            FROM entity_research_provider_observation observation
                            JOIN entity_research_tool_request request_row
                              ON request_row.tool_request_id=observation.tool_request_id
                            LEFT JOIN entity_research_result result
                              ON result.provider_operation_ref=observation.provider_operation_ref
                             AND result.tool_request_id=observation.tool_request_id
                            WHERE request_row.job_id=:job_id AND result.result_id IS NULL
                            ORDER BY observation.provider_operation_ref
                            """
                        ),
                        {"job_id": job_id},
                    )
                )
                .scalars()
                .all()
            )
        )

    @staticmethod
    def _json_row(row: Mapping[str, object] | RowMapping) -> dict[str, JsonValue]:
        return cast(
            dict[str, JsonValue],
            {
                key: str(value) if isinstance(value, (UUID, Decimal, datetime)) else value
                for key, value in row.items()
            },
        )

    @staticmethod
    def _ref_uuid(reference: str, prefix: str) -> UUID:
        if not reference.startswith(prefix):
            raise AccountResearchAuthorityError("reference uses the wrong account-research scheme")
        try:
            return UUID(reference.removeprefix(prefix))
        except ValueError as exc:
            raise AccountResearchAuthorityError("account-research reference is malformed") from exc


class AccountResearchExecutionGuard(EntityResearchExecutionGuard):
    """R5 purpose/source/bundle/order guard; R9 owns atomic parallel budget hardening."""

    def __init__(self, *, conn_factory: ConnFactory) -> None:
        self._conn_factory = conn_factory

    async def authorize_parallel(
        self, *, context: EntityResearchRuntimeContext, calls: Sequence[EntityResearchToolCall]
    ) -> None:
        if context.authorization.subject_type is not ResearchSubjectType.ACCOUNT:
            raise AccountResearchAuthorityError("account guard received another subject type")
        names = [call.tool_name for call in calls]
        if len(names) != len(set(names)):
            raise AccountResearchAuthorityError("one model round cannot duplicate an account tool")
        if "assess_account_coverage" in names and len(names) > 1:
            raise AccountResearchAuthorityError("coverage must follow settled provider results")
        if "finalize_account_research" in names and len(names) > 1:
            raise AccountResearchAuthorityError("finalization is a dependent terminal decision")

    async def authorize_tool(
        self,
        *,
        context: EntityResearchRuntimeContext,
        call: EntityResearchToolCall,
        journal_event_ref: str,
    ) -> None:
        del journal_event_ref
        if any(call.tool_name.startswith(prefix) for prefix in _CONTACT_TOOL_PREFIXES):
            raise AccountResearchAuthorityError("account agent cannot perform contact research")
        sources = set(cast(Sequence[str], call.arguments.get("source_keys", ())))
        fields = set(cast(Sequence[str], call.arguments.get("field_keys", ())))
        if call.tool_name == "research_account_deep":
            if sources != {_QUALITATIVE_SOURCE}:
                raise AccountResearchAuthorityError("qualitative account research uses Exa Deep")
            exa_authority = {
                item.field_key: item.source_keys
                for item in context.authorization.selection.field_source_authority
                if _QUALITATIVE_SOURCE in item.source_keys
            }
            primary = {
                field_key
                for field_key, source_keys in exa_authority.items()
                if source_keys[0] == _QUALITATIVE_SOURCE
            }
            async with self._conn_factory() as conn:
                prior = int(
                    (
                        await conn.execute(
                            text(
                                "SELECT count(*) FROM entity_research_tool_request "
                                "WHERE job_id=:job_id AND tool_name='research_account_deep'"
                            ),
                            {"job_id": context.authorization.job_id},
                        )
                    ).scalar_one()
                )
                prior_structured_fields = set(
                    (
                        await conn.execute(
                            text(
                                "SELECT DISTINCT unnest(field_keys) FROM "
                                "entity_research_tool_request WHERE job_id=:job_id "
                                "AND NOT (:exa = ANY(source_keys))"
                            ),
                            {
                                "job_id": context.authorization.job_id,
                                "exa": _QUALITATIVE_SOURCE,
                            },
                        )
                    ).scalars()
                )
            fallback = fields - primary
            if fallback - prior_structured_fields:
                raise AccountResearchAuthorityError(
                    "Exa fallback fields require a preceding structured-source attempt"
                )
            if prior == 0 and primary - fields:
                raise AccountResearchAuthorityError(
                    "first Exa account call must include every primary Exa field"
                )
        elif call.tool_name == "enrich_account" and _QUALITATIVE_SOURCE in sources:
            raise AccountResearchAuthorityError("structured enrichment is independent of Exa Deep")
        elif call.tool_name == "discover_buying_committee":
            scope = call.arguments.get("buying_unit_scope")
            if not isinstance(scope, dict) or str(scope.get("account_entity_id")) != str(
                context.authorization.subject_entity_id
            ):
                raise AccountResearchAuthorityError(
                    "committee discovery requires the exact account buying-unit scope"
                )
        elif call.tool_name in {"assess_account_coverage", "finalize_account_research"}:
            async with self._conn_factory() as conn:
                pending = await AccountResearchStateStore._pending_refs(
                    conn, context.authorization.job_id
                )
            if pending:
                raise AccountResearchAuthorityError("dependent account decision has pending work")
        async with self._conn_factory() as conn:
            closed = int(
                (
                    await conn.execute(
                        text(
                            "SELECT count(*) FROM entity_research_account_coverage "
                            "WHERE job_id=:job_id"
                        ),
                        {"job_id": context.authorization.job_id},
                    )
                ).scalar_one()
            )
        if closed and call.tool_name in {
            "research_account_deep",
            "enrich_account",
            "discover_buying_committee",
        }:
            raise AccountResearchAuthorityError(
                "provider research cannot resume after coverage close"
            )

    async def observe_tool_result(
        self,
        *,
        context: EntityResearchRuntimeContext,
        call: EntityResearchToolCall,
        result: object,
    ) -> None:
        del context, call, result


class AccountResearchFinalizationEngine(EntityResearchFinalizationEngine):
    def __init__(self, *, conn_factory: ConnFactory) -> None:
        self._conn_factory = conn_factory

    async def accept(
        self, *, context: EntityResearchRuntimeContext, proposal: ResearchFinalizationProposal
    ) -> ResearchFinalizationReceipt:
        authorization = context.authorization
        if (
            authorization.subject_type is not ResearchSubjectType.ACCOUNT
            or proposal.subject_type is not ResearchSubjectType.ACCOUNT
            or proposal.target_entity_id != authorization.subject_entity_id
        ):
            raise EntityResearchFinalizationRejected(
                "account finalization widens subject authority"
            )
        async with self._conn_factory() as conn:
            row = (
                (
                    await conn.execute(
                        text(
                            """
                            SELECT intent.proposal_json, intent.proposal_sha256,
                                   intent.current_state_sha256, coverage.committee_status,
                                   job.current_state_sha256 AS job_state,
                                   job.spent_cents AS job_spent_cents,
                                   run.spent_cents AS run_spent_cents,
                                   (SELECT COALESCE(sum(fold.settled_cost_cents), 0)
                                    FROM entity_research_provider_settlement_fold fold
                                    WHERE fold.job_id=intent.job_id
                                   ) AS result_spent_cents,
                                   (SELECT COALESCE(sum(run_job.spent_cents), 0)
                                    FROM entity_research_job run_job
                                    WHERE run_job.research_run_id=intent.research_run_id
                                   ) AS run_job_spent_cents,
                                   (SELECT count(*) FROM entity_research_account_review_item review
                                    WHERE review.coverage_id=coverage.coverage_id
                                      AND review.state='open') AS open_reviews,
                                   (SELECT count(*) FROM entity_research_tool_request request_row
                                    WHERE request_row.research_run_id=intent.research_run_id
                                      AND request_row.subject_type='contact') AS contact_requests,
                                   (SELECT count(*)
                                    FROM entity_research_provider_observation observation
                                    JOIN entity_research_tool_request request_row
                                      ON request_row.tool_request_id=observation.tool_request_id
                                    LEFT JOIN entity_research_result result
                                      ON result.provider_operation_ref=
                                         observation.provider_operation_ref
                                     AND result.tool_request_id=observation.tool_request_id
                                    WHERE request_row.job_id=intent.job_id
                                      AND result.result_id IS NULL) AS pending_operations
                                   ,(SELECT count(*)
                                     FROM unnest(coverage.completed_field_keys) completed(field_key)
                                     WHERE NOT EXISTS (
                                         SELECT 1
                                         FROM entity_research_result_field result_field
                                         JOIN entity_research_result result
                                           ON result.result_id=result_field.result_id
                                         JOIN entity_research_result_evidence evidence
                                           ON evidence.result_id=result_field.result_id
                                          AND evidence.field_ordinal=result_field.ordinal
                                         WHERE 'research-result:' || result.result_id::text =
                                               ANY(coverage.result_refs)
                                           AND result_field.subject_type='account'
                                           AND result_field.target_entity_id=
                                               intent.account_entity_id
                                           AND result_field.field_key=completed.field_key
                                           AND result_field.outcome='found'
                                     )) AS missing_completed_evidence
                            FROM entity_research_account_finalization_intent intent
                            JOIN entity_research_account_coverage coverage
                              ON coverage.coverage_id=intent.coverage_id
                            JOIN entity_research_job job ON job.job_id=intent.job_id
                            JOIN entity_research_run run
                              ON run.research_run_id=intent.research_run_id
                            WHERE intent.proposal_id=:proposal_id AND intent.job_id=:job_id
                              AND intent.research_run_id=:run_id
                              AND intent.workspace_id=:workspace_id
                              AND intent.account_entity_id=:account_id
                            """
                        ),
                        {
                            "proposal_id": proposal.proposal_id,
                            "job_id": authorization.job_id,
                            "run_id": authorization.research_run_id,
                            "workspace_id": authorization.workspace_id,
                            "account_id": authorization.subject_entity_id,
                        },
                    )
                )
                .mappings()
                .first()
            )
        if (
            row is None
            or ResearchFinalizationProposal.model_validate(row["proposal_json"]) != proposal
        ):
            raise EntityResearchFinalizationRejected(
                "model finalization lacks the exact engine-tool proposal intent"
            )
        no_pending = int(row["pending_operations"]) == 0
        state_matches = (
            str(row["job_state"])
            == proposal.current_state_sha256
            == str(row["current_state_sha256"])
        )
        coverage_matches = set(
            proposal.completed_field_keys + proposal.unresolved_field_keys
        ) == set(authorization.selection.admitted_field_keys)
        review_shape = (
            proposal.outcome is ResearchFinalizationOutcome.NEEDS_REVIEW
            and int(row["open_reviews"]) > 0
        ) or (
            proposal.outcome is ResearchFinalizationOutcome.COMPLETED
            and int(row["open_reviews"]) == 0
        )
        verification = FinalizationVerification(
            no_pending_operations=no_pending,
            evidence_complete=int(row["missing_completed_evidence"]) == 0,
            coverage_matches=coverage_matches and review_shape,
            spend_reconciled=(
                no_pending
                and Decimal(row["job_spent_cents"]) == Decimal(row["result_spent_cents"])
                and Decimal(row["run_spent_cents"]) == Decimal(row["run_job_spent_cents"])
            ),
            identity_use_verification_complete=(
                bool(proposal.identity_use_verification_ref)
                and str(row["committee_status"]) in {"complete", "partial", "needs_review"}
            ),
            policy_scope_respected=int(row["contact_requests"]) == 0,
            current_state_matches=state_matches,
        )
        if not verification.all_passed():
            raise EntityResearchFinalizationRejected(
                f"account finalization verification failed: {verification.model_dump()}"
            )
        receipt_id = uuid5(_RECEIPT_NAMESPACE, str(proposal.proposal_id))
        return ResearchFinalizationReceipt(
            receipt_id=receipt_id,
            proposal=proposal,
            proposal_ref=f"account-finalization-proposal:{proposal.proposal_id}",
            engine_actor="account-research-finalization-engine@1",
            accepted_at=datetime.now(UTC),
            accepted_state_sha256=proposal.current_state_sha256,
            verification=verification,
        )


def account_engine_tool_bindings(
    store: AccountResearchStateStore,
) -> Mapping[str, EntityResearchToolBinding]:
    async def read_state(include_result_index: bool = True) -> dict[str, JsonValue]:
        value = await store.state()
        payload = value.model_dump(mode="json")
        if not include_result_index:
            payload["result_refs"] = []
        return cast(dict[str, JsonValue], payload)

    async def inspect(**values: object) -> dict[str, JsonValue]:
        return await store.evidence(InspectAccountEvidenceInput.model_validate(values))

    async def assess(**values: object) -> dict[str, JsonValue]:
        coverage = await store.assess(AssessAccountCoverageInput.model_validate(values))
        return cast(dict[str, JsonValue], coverage.model_dump(mode="json"))

    async def finalize(**values: object) -> dict[str, JsonValue]:
        proposal = await store.propose(FinalizeAccountResearchInput.model_validate(values))
        return cast(dict[str, JsonValue], proposal.model_dump(mode="json"))

    tools = {
        "read_account_research_state": StructuredTool.from_function(
            coroutine=read_state,
            name="read_account_research_state",
            description=(
                "Read exact persisted account results, gaps, committee, pending work, and spend."
            ),
            args_schema=ReadAccountResearchStateInput,
        ),
        "inspect_account_evidence": StructuredTool.from_function(
            coroutine=inspect,
            name="inspect_account_evidence",
            description="Inspect the complete evidence index for exact persisted account results.",
            args_schema=InspectAccountEvidenceInput,
        ),
        "assess_account_coverage": StructuredTool.from_function(
            coroutine=assess,
            name="assess_account_coverage",
            description="Derive durable account-field and office-coherent committee coverage.",
            args_schema=AssessAccountCoverageInput,
        ),
        "finalize_account_research": StructuredTool.from_function(
            coroutine=finalize,
            name="finalize_account_research",
            description=(
                "Ask the engine to produce the only admissible typed finalization proposal."
            ),
            args_schema=FinalizeAccountResearchInput,
        ),
    }
    return {name: EntityResearchToolBinding(tool=tool, version=1) for name, tool in tools.items()}


__all__ = [
    "AccountResearchAuthorityError",
    "AccountResearchExecutionGuard",
    "AccountResearchFinalizationEngine",
    "AccountResearchStateStore",
    "account_engine_tool_bindings",
]
