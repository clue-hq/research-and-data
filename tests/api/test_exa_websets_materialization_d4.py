"""D4 database acceptance over immutable, current-schema Exa Webset artifacts."""

from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_api.exa_websets_lifecycle import ExaDiscoveryWakeWorker
from clue_api.exa_websets_materialization import (
    ExaD4Outcome,
    ExaWebsetsD4Materializer,
    _candidate_record,
    _RetainedItem,
)
from clue_core import (
    DiscoveryBatchId,
    DiscoveryBatchState,
    DiscoveryCandidateAdmissionState,
    DiscoveryCriterionPlan,
    DiscoveryEnrichmentFormat,
    DiscoveryEnrichmentPlan,
    DiscoveryEntityKind,
    DiscoveryFieldResolutionState,
    DiscoveryItemSnapshot,
    DiscoveryItemSnapshotId,
    DiscoveryOperation,
    DiscoveryOperationState,
    DiscoveryPageReceipt,
    DiscoveryPageResource,
    DiscoveryPlan,
    DiscoverySearchPlan,
    DiscoverySpendOutcome,
    DiscoveryWakeReason,
    DiscoveryWakeRequest,
    EntityType,
    ICPCreatedFrom,
    ProjectPhase,
    ProjectRunId,
    discovery_provider_external_id,
    new_discovery_batch_id,
    new_discovery_item_snapshot_id,
    new_discovery_operation_id,
    new_discovery_plan_id,
    new_project_run_id,
)
from clue_research.adapters.exa_websets import (
    ExaResponseEnrichment,
    ExaWebsetItem,
    normalize_exa_discovery_company_item,
)
from clue_research.claimstore import ALL_WORKSPACES, claims_for
from clue_research.discovery_scoring import DISCOVERY_ENVELOPE_POLICY_V1
from clue_research.discovery_scoring.gate import DISCOVERY_PROVENANCE_FIELD
from clue_research.durable import (
    DiscoveryReplayConflict,
    capture_discovery_artifact,
    create_discovery_batch,
    discovery_manifest_members,
    ensure_project_run,
    enumerate_discovery_subject_artifacts,
    get_discovery_candidate_link,
    get_discovery_field_resolution,
    get_discovery_item,
    mark_discovery_operation_reconciled,
    put_discovery_candidate_link,
    put_discovery_item,
    put_discovery_operation,
    put_discovery_page,
    put_discovery_plan,
    read_discovery_seal_readiness,
    schedule_discovery_wake,
    update_discovery_batch_state,
    update_discovery_operation,
)
from clue_research.durable.enums import ProjectRunStatus
from clue_research.icp import create_icp_spec
from clue_research.identity import (
    auto_merge,
    embed_account,
    insert_account_entity,
    list_open_tasks,
    resolve_create_new_entity,
)
from clue_research.membership import accounts_for_project, projects_for_accounts
from clue_storage import FsStorage, content_address
from tests._workspace import seed_project
from tests.db.conftest import run_async
from tests.profiling.conftest import conn_session_factory, rollback_conn

pytestmark = pytest.mark.usefixtures("require_profiling_db")

_NOW = datetime(2026, 8, 3, 12, 0, tzinfo=UTC)


def _definition(
    enrichment_id: str,
    field_key: str,
    *,
    format_: str,
) -> dict[str, object]:
    return {
        "id": enrichment_id,
        "object": "webset_enrichment",
        "status": "completed",
        "websetId": "ws_d4_acceptance",
        "title": field_key,
        "description": f"Find {field_key}",
        "format": format_,
        "options": None,
        "instructions": None,
        "metadata": {"clueFieldKey": field_key},
        "createdAt": "2026-08-03T11:00:00Z",
        "updatedAt": "2026-08-03T12:00:00Z",
    }


def _company_item(
    item_id: str,
    *,
    city: str,
    criterion_state: str,
) -> dict[str, object]:
    return {
        "id": item_id,
        "object": "webset_item",
        "source": "search",
        "sourceId": "search_d4_acceptance",
        "sourceEntityId": None,
        "scopeId": None,
        "websetId": "ws_d4_acceptance",
        "properties": {
            "type": "company",
            "url": "https://www.example-neuro.com/",
            "description": "Independent neurosurgery practice",
            "content": None,
            "company": {
                "name": "Example Neuro",
                "location": f"{city}, Texas, United States",
                "employees": 42,
                "industry": None,
                "about": "A physician-owned neurosurgery practice.",
                "logoUrl": None,
                "foundedYear": 1999,
                "headquarters": {
                    "address": None,
                    "city": city,
                    "state": "Texas",
                    "postalCode": None,
                    "country": "United States",
                    "countryCode": "US",
                },
                "financials": {
                    "revenueAnnual": 12_500_000,
                    "fundingTotal": 2_000_000,
                    "fundingLatestRound": {
                        "name": "Seed",
                        "date": "2025-01-02",
                        "amount": 2_000_000,
                    },
                },
                "webTraffic": {"visitsMonthly": 100_000, "uniqueVisitors": 60_000},
            },
        },
        "evaluations": [
            {
                "criterion": "Is an independent specialty practice",
                "reasoning": f"Provider evaluation for {item_id}.",
                "satisfied": criterion_state,
                "references": [
                    {
                        "title": "About Example Neuro",
                        "snippet": "Physician-owned neurosurgery practice",
                        "url": "https://www.example-neuro.com/about",
                    }
                ],
            }
        ],
        "enrichments": [
            {
                "object": "enrichment_result",
                "status": "completed",
                "format": "url",
                "result": ["https://www.linkedin.com/company/example-neuro"],
                "reasoning": "Canonical company page.",
                "references": [
                    {
                        "title": "Example Neuro | LinkedIn",
                        "snippet": None,
                        "url": "https://www.linkedin.com/company/example-neuro",
                    }
                ],
                "enrichmentId": "enr_linkedin",
            },
            {
                "object": "enrichment_result",
                "status": "completed",
                "format": "email",
                "result": None,
                "reasoning": "No public company email could be confirmed.",
                "references": [
                    {
                        "title": "Contact",
                        "snippet": "No public email listed",
                        "url": "https://www.example-neuro.com/contact",
                    }
                ],
                "enrichmentId": "enr_email",
            },
        ],
        "createdAt": "2026-08-03T11:00:00Z",
        "updatedAt": "2026-08-03T12:00:00Z",
    }


async def _capture_json(
    conn: AsyncConnection,
    storage: FsStorage,
    *,
    workspace_id: str,
    payload: object,
    source_url: str,
) -> tuple[str, bytes]:
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    key = await capture_discovery_artifact(
        conn,
        storage,
        workspace_id=workspace_id,
        content=raw,
        media_type="application/json",
        source_key="exa_websets",
        source_url=source_url,
    )
    return key, raw


async def _seed_terminal_batch(
    conn: AsyncConnection,
    storage: FsStorage,
    workspace_id: str,
    *,
    item_payloads: list[dict[str, object]] | None = None,
    provider_operation_id: str = "ws_d4_acceptance",
) -> tuple[DiscoveryBatchId, tuple[DiscoveryItemSnapshotId, ...], tuple[str, ...]]:
    project = await seed_project(conn, workspace_id, name="D4 Exa materialization")
    icp = await create_icp_spec(
        conn,
        workspace_id=workspace_id,
        icp_key="independent-specialty-practices",
        created_from=ICPCreatedFrom.SYNTHESIS,
        field_keys=("core.primary_domain", "core.employee_count"),
        activate=True,
    )
    run_id = new_project_run_id()
    await ensure_project_run(
        conn,
        project_run_id=run_id,
        project_id=project.project_id,
        workspace_id=workspace_id,
        icp_key=icp.icp_key,
        icp_version=icp.version,
        phase=ProjectPhase.DISCOVERY,
        status=ProjectRunStatus.ACTIVE,
    )
    items = item_payloads or [
        _company_item("item_d4_a", city="Austin", criterion_state="yes"),
        _company_item("item_d4_b", city="Dallas", criterion_state="unclear"),
    ]
    search = DiscoverySearchPlan(
        search_key="search-d4",
        channel_key="exa_websets",
        normalized_query="Independent neurosurgery practices in the United States",
        entity_type=DiscoveryEntityKind.COMPANY,
        requested_count=len(items),
        criteria=(DiscoveryCriterionPlan(description="Is an independent specialty practice"),),
        enrichments=(
            DiscoveryEnrichmentPlan(
                field_key="core.company_linkedin_url",
                description="Find the canonical LinkedIn company page",
                format=DiscoveryEnrichmentFormat.URL,
            ),
            DiscoveryEnrichmentPlan(
                field_key="core.company_email",
                description="Find a public general company email",
                format=DiscoveryEnrichmentFormat.EMAIL,
            ),
        ),
    )
    plan = DiscoveryPlan(
        discovery_plan_id=new_discovery_plan_id(),
        plan_version=1,
        workspace_id=workspace_id,
        project_id=project.project_id,
        project_run_id=run_id,
        icp_key=icp.icp_key,
        icp_version=icp.version,
        provider_policy_version="exa-websets-company-v1",
        field_policy_version=DISCOVERY_ENVELOPE_POLICY_V1.version,
        provider_contract_version="exa-websets-v0-openapi-2026-08-03",
        channels=("exa_websets",),
        searches=(search,),
        required_account_fields=DISCOVERY_ENVELOPE_POLICY_V1.required_fields,
        optional_account_fields=DISCOVERY_ENVELOPE_POLICY_V1.optional_fields,
        provider_credit_cap=50,
        money_budget_cap_cents=Decimal("500"),
        stopping_policy={"requested_count": len(items)},
        snapshot_reuse_policy="same_observation_window",
    )
    await put_discovery_plan(conn, workspace_id=workspace_id, plan=plan)
    batch_id = new_discovery_batch_id()
    await create_discovery_batch(
        conn,
        workspace_id=workspace_id,
        batch_id=batch_id,
        plan_id=plan.discovery_plan_id,
        generation=1,
    )
    fingerprint = hashlib.sha256(f"{workspace_id}:d4".encode()).hexdigest()
    operation_id = new_discovery_operation_id()
    planned = DiscoveryOperation(
        operation_id=operation_id,
        batch_id=batch_id,
        workspace_id=workspace_id,
        source_key="exa_websets",
        provider_api_version="v0",
        request_fingerprint=fingerprint,
        observation_window="2026-08",
        provider_external_id=discovery_provider_external_id(fingerprint),
        state=DiscoveryOperationState.PLANNED,
        spend_outcome=DiscoverySpendOutcome.NOT_DISPATCHED,
        provider_units_reserved=Decimal(24),
    )
    await put_discovery_operation(conn, workspace_id=workspace_id, operation=planned)

    definitions = [
        _definition("enr_linkedin", "core.company_linkedin_url", format_="url"),
        _definition("enr_email", "core.company_email", format_="text"),
    ]
    definitions_key, definitions_raw = await _capture_json(
        conn,
        storage,
        workspace_id=workspace_id,
        payload=definitions,
        source_url="https://api.exa.ai/websets/v0/websets/ws_d4_acceptance/enrichments",
    )
    await put_discovery_page(
        conn,
        workspace_id=workspace_id,
        page=DiscoveryPageReceipt(
            operation_id=operation_id,
            resource_kind=DiscoveryPageResource.ENRICHMENTS,
            has_more=False,
            payload_artifact_key=definitions_key,
            payload_sha256=content_address(definitions_raw),
            item_count=len(items),
            fetched_at=_NOW,
        ),
    )
    page_key, page_raw = await _capture_json(
        conn,
        storage,
        workspace_id=workspace_id,
        payload={"data": items, "hasMore": False, "nextCursor": None},
        source_url="https://api.exa.ai/websets/v0/websets/ws_d4_acceptance/items",
    )
    await put_discovery_page(
        conn,
        workspace_id=workspace_id,
        page=DiscoveryPageReceipt(
            operation_id=operation_id,
            resource_kind=DiscoveryPageResource.ITEMS,
            has_more=False,
            payload_artifact_key=page_key,
            payload_sha256=content_address(page_raw),
            item_count=len(items),
            fetched_at=_NOW,
        ),
    )
    item_keys: list[str] = []
    item_snapshot_ids = []
    for payload in items:
        item_key, item_raw = await _capture_json(
            conn,
            storage,
            workspace_id=workspace_id,
            payload=payload,
            source_url="https://api.exa.ai/websets/v0/websets/ws_d4_acceptance/items",
        )
        item_id = new_discovery_item_snapshot_id()
        await put_discovery_item(
            conn,
            workspace_id=workspace_id,
            item=DiscoveryItemSnapshot(
                item_snapshot_id=item_id,
                operation_id=operation_id,
                provider_item_id=str(payload["id"]),
                source_kind="webset_item",
                source_id="search_d4_acceptance",
                raw_artifact_key=item_key,
                item_sha256=content_address(item_raw),
                observed_at=_NOW,
            ),
        )
        item_keys.append(item_key)
        item_snapshot_ids.append(item_id)

    receipt_key, _ = await _capture_json(
        conn,
        storage,
        workspace_id=workspace_id,
        payload={"provider": "exa", "operation": "ws_d4_acceptance"},
        source_url="https://api.exa.ai/websets/v0/websets/ws_d4_acceptance",
    )
    terminal = planned.model_copy(
        update={
            "provider_operation_id": provider_operation_id,
            "state": DiscoveryOperationState.SUCCEEDED,
            "spend_outcome": DiscoverySpendOutcome.CHARGED,
            "submitted_receipt_ref": receipt_key,
            "final_receipt_ref": receipt_key,
            "raw_request_artifact_key": receipt_key,
            "raw_response_manifest_key": receipt_key,
            "provider_units_charged": Decimal(24),
            "started_at": _NOW,
            "terminal_at": _NOW,
        }
    )
    await update_discovery_operation(conn, workspace_id=workspace_id, operation=terminal)
    await mark_discovery_operation_reconciled(
        conn,
        workspace_id=workspace_id,
        operation_id=operation_id,
        final_reconciliation=True,
        pagination_exhausted=True,
    )
    await update_discovery_batch_state(
        conn,
        workspace_id=workspace_id,
        batch_id=batch_id,
        state=DiscoveryBatchState.IDENTITY_RESOLUTION,
    )
    return batch_id, tuple(item_snapshot_ids), tuple(item_keys)


async def _workspace_table_counts(conn: AsyncConnection, workspace_id: str) -> tuple[int, ...]:
    counts: list[int] = []
    for table in (
        "account_entity",
        "claim",
        "discovery_candidate_link",
        "discovery_field_resolution",
        "discovery_artifact_subject",
        # FI-2 P1: membership is written by the same materialization, so a replay that writes
        # nothing must not grow it either.
        "project_account",
    ):
        counts.append(
            int(
                (
                    await conn.execute(
                        text(f"SELECT count(*) FROM {table} WHERE workspace_id = :workspace"),
                        {"workspace": workspace_id},
                    )
                ).scalar_one()
            )
        )
    return tuple(counts)


def test_d4_candidate_handles_do_not_collapse_same_provider_item_across_searches() -> None:
    payload = _company_item("item_shared_across_searches", city="Austin", criterion_state="yes")
    retained = _RetainedItem(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode())
    provider_item = ExaWebsetItem.model_validate(payload)
    definitions = tuple(
        ExaResponseEnrichment.model_validate(payload)
        for payload in (
            _definition("enr_linkedin", "core.company_linkedin_url", format_="url"),
            _definition("enr_email", "core.company_email", format_="text"),
        )
    )
    company = normalize_exa_discovery_company_item(provider_item, definitions)
    snapshots = (
        DiscoveryItemSnapshot(
            item_snapshot_id=new_discovery_item_snapshot_id(),
            operation_id=new_discovery_operation_id(),
            provider_item_id=provider_item.id,
            source_kind="webset_item",
            source_id="search_one",
            raw_artifact_key="workspace/" + "a" * 64,
            item_sha256="a" * 64,
            observed_at=_NOW,
        ),
        DiscoveryItemSnapshot(
            item_snapshot_id=new_discovery_item_snapshot_id(),
            operation_id=new_discovery_operation_id(),
            provider_item_id=provider_item.id,
            source_kind="webset_item",
            source_id="search_two",
            raw_artifact_key="workspace/" + "b" * 64,
            item_sha256="b" * 64,
            observed_at=_NOW,
        ),
    )
    records = tuple(_candidate_record(snapshot, company, retained) for snapshot in snapshots)

    assert records[0].source_record_ref != records[1].source_record_ref
    assert records[0].discovery_evidence["provider_item_id"] == provider_item.id
    assert records[1].discovery_evidence["provider_item_id"] == provider_item.id


def test_d4_materializes_dedup_conflict_missing_evidence_and_exact_replay(
    tmp_path: Path,
) -> None:
    async def _run() -> None:
        async with rollback_conn() as conn:
            workspace_id = "d4-acceptance"
            storage = FsStorage(tmp_path)
            batch_id, item_ids, item_keys = await _seed_terminal_batch(conn, storage, workspace_id)
            service = ExaWebsetsD4Materializer(
                storage=storage,
                conn_factory=conn_session_factory(conn),
            )
            before_accounts = int(
                (
                    await conn.execute(
                        text("SELECT count(*) FROM account_entity WHERE workspace_id = :workspace"),
                        {"workspace": workspace_id},
                    )
                ).scalar_one()
            )
            first = await service.materialize(workspace_id=workspace_id, batch_id=batch_id)

            assert first.outcome is ExaD4Outcome.MATERIALIZED
            assert first.batch_state is DiscoveryBatchState.SEAL_PENDING
            assert first.item_count == 2
            assert len(first.account_ids) == 1
            assert first.excluded_item_count == first.review_item_count == 0
            assert first.claims_created == 18
            assert len(first.claim_ids) == 20  # 18 typed fields + 2 item-specific provenance claims
            manifest_accounts, manifest_claims, _ = await discovery_manifest_members(
                conn,
                workspace_id=workspace_id,
                batch_id=batch_id,
            )
            assert manifest_accounts == first.account_ids
            assert set(manifest_claims) == set(first.claim_ids)
            assert first.field_resolution_count == 8
            account_id = first.account_ids[0]
            assert (
                int(
                    (
                        await conn.execute(
                            text(
                                "SELECT count(*) FROM account_entity "
                                "WHERE workspace_id = :workspace"
                            ),
                            {"workspace": workspace_id},
                        )
                    ).scalar_one()
                )
                == before_accounts + 1
            )

            links = [
                await get_discovery_candidate_link(
                    conn,
                    workspace_id=workspace_id,
                    batch_id=batch_id,
                    item_snapshot_id=item_id,
                )
                for item_id in item_ids
            ]
            assert all(link is not None and link.survivor_entity_id == account_id for link in links)
            for item_id in item_ids:
                snapshot = await get_discovery_item(
                    conn,
                    workspace_id=workspace_id,
                    item_snapshot_id=item_id,
                )
                assert snapshot is not None and snapshot.normalized_at is not None

            hq = await get_discovery_field_resolution(
                conn,
                workspace_id=workspace_id,
                batch_id=batch_id,
                account_entity_id=account_id,
                logical_field_key="discovery.headquarters",
            )
            industry = await get_discovery_field_resolution(
                conn,
                workspace_id=workspace_id,
                batch_id=batch_id,
                account_entity_id=account_id,
                logical_field_key="discovery.industry",
            )
            email = await get_discovery_field_resolution(
                conn,
                workspace_id=workspace_id,
                batch_id=batch_id,
                account_entity_id=account_id,
                logical_field_key="discovery.company_email",
            )
            assert hq is not None and hq.state is DiscoveryFieldResolutionState.CONFLICT
            assert len(hq.claim_ids) == 2 and set(hq.source_item_ids) == set(item_ids)
            assert industry is not None and industry.state is (
                DiscoveryFieldResolutionState.PENDING
            )
            assert industry.reason_code is None
            assert email is not None and email.state is (
                DiscoveryFieldResolutionState.CONFIRMED_MISSING
            )
            assert email.reason_code == "exa_terminal_attempt_returned_null"

            provenance = await claims_for(
                conn, account_id, DISCOVERY_PROVENANCE_FIELD, scope=ALL_WORKSPACES
            )
            assert len(provenance) == 2
            assert {claim.artifact_key for claim in provenance} == set(item_keys)
            evaluation_states: set[str] = set()
            for claim in provenance:
                assert isinstance(claim.value_json, dict)
                evidence = claim.value_json["evidence"]
                assert isinstance(evidence, dict)
                evaluations = evidence["evaluations"]
                assert isinstance(evaluations, list)
                first_evaluation = evaluations[0]
                assert isinstance(first_evaluation, dict)
                state = first_evaluation["satisfied"]
                assert isinstance(state, str)
                evaluation_states.add(state)
            assert evaluation_states == {"yes", "unclear"}

            artifacts = await enumerate_discovery_subject_artifacts(
                conn,
                workspace_id=workspace_id,
                subject_kind="account",
                subject_entity_id=account_id,
            )
            assert set(item_keys).issubset({artifact.artifact_key for artifact in artifacts})
            field_keys = set(
                (
                    await conn.execute(
                        text("SELECT field_key FROM claim WHERE entity_id = :entity_id"),
                        {"entity_id": account_id},
                    )
                ).scalars()
            )
            assert "core.company_about" in field_keys
            assert "account.total_funding" in field_keys
            assert "account.recent_funding" in field_keys
            assert "core.founded_year" not in field_keys
            assert "account.web_traffic" not in field_keys

            # FI-2 P1 (spec §2): a materialized candidate joins the batch's project as a target,
            # via the shared admission gate (added_via='discovered').
            batch_project_id = str(
                (
                    await conn.execute(
                        text("SELECT project_id FROM discovery_batch WHERE id = :batch_id"),
                        {"batch_id": batch_id},
                    )
                ).scalar_one()
            )
            assert await accounts_for_project(
                conn, workspace_id=workspace_id, project_id=batch_project_id
            ) == (account_id,)
            assert await projects_for_accounts(
                conn, workspace_id=workspace_id, account_ids=[account_id]
            ) == {account_id: (batch_project_id,)}

            counts_before_replay = await _workspace_table_counts(conn, workspace_id)
            batch_updated_before_replay = (
                await conn.execute(
                    text("SELECT updated_at FROM discovery_batch WHERE id = :batch_id"),
                    {"batch_id": batch_id},
                )
            ).scalar_one()
            replay = await ExaWebsetsD4Materializer(
                storage=storage,
                conn_factory=conn_session_factory(conn),
            ).materialize(workspace_id=workspace_id, batch_id=batch_id)
            counts_after_replay = await _workspace_table_counts(conn, workspace_id)
            assert replay.outcome is ExaD4Outcome.REPLAYED
            assert replay.claims_created == 0
            assert replay.claims_reused == 18
            assert replay.claim_ids == first.claim_ids
            assert counts_after_replay == counts_before_replay
            assert (
                await conn.execute(
                    text("SELECT updated_at FROM discovery_batch WHERE id = :batch_id"),
                    {"batch_id": batch_id},
                )
            ).scalar_one() == batch_updated_before_replay

    run_async(_run())


def test_d4_persists_identity_review_lineage_and_blocks_batch(tmp_path: Path) -> None:
    async def _run() -> None:
        async with rollback_conn() as conn:
            workspace_id = "d4-review"
            storage = FsStorage(tmp_path)
            batch_id, item_ids, _ = await _seed_terminal_batch(
                conn,
                storage,
                workspace_id,
                item_payloads=[
                    _company_item("item_d4_review", city="Austin", criterion_state="yes")
                ],
            )
            possible_duplicate = await insert_account_entity(
                conn,
                workspace_id=workspace_id,
                canonical_name="Example Neuro",
                hq_geo={"country": "United States", "country_code": "US"},
            )
            assert await embed_account(conn, possible_duplicate)
            service = ExaWebsetsD4Materializer(
                storage=storage,
                conn_factory=conn_session_factory(conn),
            )
            first = await service.materialize(workspace_id=workspace_id, batch_id=batch_id)

            assert first.outcome is ExaD4Outcome.REVIEW_REQUIRED
            assert first.batch_state is DiscoveryBatchState.FIELD_MATERIALIZATION
            assert first.review_item_count == 1
            assert first.account_ids == ()
            assert first.claim_ids == ()
            links = [
                await get_discovery_candidate_link(
                    conn,
                    workspace_id=workspace_id,
                    batch_id=batch_id,
                    item_snapshot_id=item_id,
                )
                for item_id in item_ids
            ]
            assert all(
                link is not None
                and link.admission_status is DiscoveryCandidateAdmissionState.REVIEW_REQUIRED
                and link.review_task_id is not None
                for link in links
            )
            tasks = await list_open_tasks(conn, workspace_id=workspace_id)
            assert {link.review_task_id for link in links if link is not None}.issubset(
                {task.id for task in tasks}
            )
            task_count = len(tasks)

            foreign_workspace = "d4-review-foreign-workspace"
            foreign_batch, (foreign_item,), _ = await _seed_terminal_batch(
                conn,
                storage,
                foreign_workspace,
                item_payloads=[
                    _company_item("item_d4_foreign_review", city="Boston", criterion_state="yes")
                ],
                provider_operation_id="ws_d4_foreign_review",
            )
            link = links[0]
            assert link is not None and link.review_task_id is not None
            with pytest.raises(IntegrityError):
                async with conn.begin_nested():
                    await put_discovery_candidate_link(
                        conn,
                        workspace_id=foreign_workspace,
                        batch_id=foreign_batch,
                        item_snapshot_id=foreign_item,
                        admission_status=DiscoveryCandidateAdmissionState.REVIEW_REQUIRED,
                        raw_name="Example Neuro",
                        candidate_domain="example-neuro.com",
                        source_url="https://example-neuro.com",
                        review_task_id=link.review_task_id,
                    )

            replay = await ExaWebsetsD4Materializer(
                storage=storage,
                conn_factory=conn_session_factory(conn),
            ).materialize(workspace_id=workspace_id, batch_id=batch_id)
            assert replay.outcome is ExaD4Outcome.REVIEW_REQUIRED
            assert replay.review_item_count == 1
            assert len(await list_open_tasks(conn, workspace_id=workspace_id)) == task_count

            # FI-2 P1 (spec §2): a review-banded candidate has no entity, so it joins no project.
            batch_project_id = str(
                (
                    await conn.execute(
                        text("SELECT project_id FROM discovery_batch WHERE id = :batch_id"),
                        {"batch_id": batch_id},
                    )
                ).scalar_one()
            )
            assert (
                await accounts_for_project(
                    conn, workspace_id=workspace_id, project_id=batch_project_id
                )
                == ()
            )

            admitted_id = await resolve_create_new_entity(
                conn, link.review_task_id, resolved_by="d4-test-reviewer"
            )
            # The admission stamped the batch's project on the review task (FI-2 P1), so the human
            # resolution joins the entity it created — membership lands here, before the resume.
            assert await accounts_for_project(
                conn, workspace_id=workspace_id, project_id=batch_project_id
            ) == (admitted_id,)
            membership_after_resolution = (
                await conn.execute(
                    text(
                        "SELECT added_via, added_at FROM project_account WHERE workspace_id = :ws "
                        "AND project_id = :project AND account_entity_id = :account"
                    ),
                    {
                        "ws": workspace_id,
                        "project": batch_project_id,
                        "account": admitted_id,
                    },
                )
            ).one()
            resumed = await ExaWebsetsD4Materializer(
                storage=storage,
                conn_factory=conn_session_factory(conn),
            ).materialize(workspace_id=workspace_id, batch_id=batch_id)
            assert resumed.outcome is ExaD4Outcome.MATERIALIZED
            assert resumed.batch_state is DiscoveryBatchState.SEAL_PENDING
            assert resumed.review_item_count == 0
            assert resumed.account_ids == (admitted_id,)
            assert resumed.claims_created > 0
            terminal_link = await get_discovery_candidate_link(
                conn,
                workspace_id=workspace_id,
                batch_id=batch_id,
                item_snapshot_id=item_ids[0],
            )
            assert terminal_link is not None
            assert terminal_link.admission_status is DiscoveryCandidateAdmissionState.ADMITTED
            assert terminal_link.account_entity_id == admitted_id
            assert terminal_link.survivor_entity_id == admitted_id
            assert terminal_link.review_task_id == link.review_task_id
            # The resumed materialization runs its own ensure over the same account. Two
            # independent paths, one membership: first-add-wins makes the second a no-op, so the
            # row keeps the resolution's channel and added_at rather than being re-added later.
            assert await accounts_for_project(
                conn, workspace_id=workspace_id, project_id=batch_project_id
            ) == (admitted_id,)
            assert (
                await conn.execute(
                    text(
                        "SELECT added_via, added_at FROM project_account WHERE workspace_id = :ws "
                        "AND project_id = :project AND account_entity_id = :account"
                    ),
                    {
                        "ws": workspace_id,
                        "project": batch_project_id,
                        "account": admitted_id,
                    },
                )
            ).one() == membership_after_resolution
            counts_before_terminal_replay = await _workspace_table_counts(conn, workspace_id)
            terminal_replay = await service.materialize(
                workspace_id=workspace_id, batch_id=batch_id
            )
            assert terminal_replay.outcome is ExaD4Outcome.REPLAYED
            assert terminal_replay.claims_created == 0
            assert terminal_replay.claim_ids == resumed.claim_ids
            assert await _workspace_table_counts(conn, workspace_id) == (
                counts_before_terminal_replay
            )

    run_async(_run())


def test_d4_replay_follows_identity_survivor_without_rewriting_or_duplicating_claims(
    tmp_path: Path,
) -> None:
    async def _run() -> None:
        async with rollback_conn() as conn:
            workspace_id = "d4-survivor-replay"
            storage = FsStorage(tmp_path)
            batch_id, (item_id,), _ = await _seed_terminal_batch(
                conn,
                storage,
                workspace_id,
                item_payloads=[
                    _company_item("item_d4_merge", city="Austin", criterion_state="yes")
                ],
            )
            service = ExaWebsetsD4Materializer(
                storage=storage,
                conn_factory=conn_session_factory(conn),
            )
            initial = await service.materialize(workspace_id=workspace_id, batch_id=batch_id)
            assert initial.outcome is ExaD4Outcome.MATERIALIZED
            assert len(initial.account_ids) == 1
            original_id = initial.account_ids[0]
            original_claim_ids = initial.claim_ids
            claim_count = int(
                (
                    await conn.execute(
                        text("SELECT count(*) FROM claim WHERE workspace_id = :workspace"),
                        {"workspace": workspace_id},
                    )
                ).scalar_one()
            )

            survivor_id = await insert_account_entity(
                conn,
                workspace_id=workspace_id,
                canonical_name="Example Neuro Holdings",
            )
            await auto_merge(
                conn,
                original_id,
                survivor_id,
                entity_type=EntityType.ACCOUNT,
                decided_by="d4-test-identity-merge",
                workspace_id=workspace_id,
            )
            redirected = await service.materialize(workspace_id=workspace_id, batch_id=batch_id)
            assert redirected.outcome is ExaD4Outcome.REPLAYED
            assert redirected.account_ids == (survivor_id,)
            assert redirected.claims_created == 0
            assert redirected.claim_ids == original_claim_ids
            assert (
                int(
                    (
                        await conn.execute(
                            text("SELECT count(*) FROM claim WHERE workspace_id = :workspace"),
                            {"workspace": workspace_id},
                        )
                    ).scalar_one()
                )
                == claim_count
            )
            link = await get_discovery_candidate_link(
                conn,
                workspace_id=workspace_id,
                batch_id=batch_id,
                item_snapshot_id=item_id,
            )
            assert link is not None
            assert link.admission_status is DiscoveryCandidateAdmissionState.MERGED
            assert link.account_entity_id == original_id
            assert link.survivor_entity_id == survivor_id
            redirected_link_updated_at = link.updated_at
            # FI-2 P1 (spec §2): membership follows the merge. ``mark_merged`` re-pointed the
            # original's row onto the survivor, and the replay's own ensure lands on the survivor
            # too — so the project targets exactly the survivor, once.
            batch_project_id = str(
                (
                    await conn.execute(
                        text("SELECT project_id FROM discovery_batch WHERE id = :batch_id"),
                        {"batch_id": batch_id},
                    )
                ).scalar_one()
            )
            assert await accounts_for_project(
                conn, workspace_id=workspace_id, project_id=batch_project_id
            ) == (survivor_id,)
            assert (
                await projects_for_accounts(
                    conn, workspace_id=workspace_id, account_ids=[original_id]
                )
                == {}
            )
            survivor_resolution = await get_discovery_field_resolution(
                conn,
                workspace_id=workspace_id,
                batch_id=batch_id,
                account_entity_id=survivor_id,
                logical_field_key="identity.primary_domain",
            )
            assert survivor_resolution is not None
            assert survivor_resolution.state is DiscoveryFieldResolutionState.RESOLVED
            assert survivor_resolution.winning_claim_id in original_claim_ids
            readiness = await read_discovery_seal_readiness(
                conn, workspace_id=workspace_id, batch_id=batch_id
            )
            assert readiness.survivor_links_complete
            assert readiness.hard_identities_complete
            # D4 keeps unresolved required fields open for the pre-seal provider waterfall.
            assert not readiness.required_fields_terminal
            assert readiness.claims_or_dispositions_complete

            counts_before_replay = await _workspace_table_counts(conn, workspace_id)
            replay = await service.materialize(workspace_id=workspace_id, batch_id=batch_id)
            assert replay.outcome is ExaD4Outcome.REPLAYED
            assert replay.claim_ids == original_claim_ids
            assert await _workspace_table_counts(conn, workspace_id) == counts_before_replay
            replayed_link = await get_discovery_candidate_link(
                conn,
                workspace_id=workspace_id,
                batch_id=batch_id,
                item_snapshot_id=item_id,
            )
            assert replayed_link is not None
            assert replayed_link.updated_at == redirected_link_updated_at

    run_async(_run())


def test_d4_rejects_tampered_raw_artifact_before_identity_or_claim_writes(tmp_path: Path) -> None:
    async def _run() -> None:
        async with rollback_conn() as conn:
            workspace_id = "d4-tampered-artifact"
            storage = FsStorage(tmp_path)
            batch_id, _, (item_key,) = await _seed_terminal_batch(
                conn,
                storage,
                workspace_id,
                item_payloads=[
                    _company_item("item_d4_tampered", city="Austin", criterion_state="yes")
                ],
            )
            (tmp_path / item_key).write_bytes(b"{}")

            with pytest.raises(DiscoveryReplayConflict, match="raw item artifact hash mismatch"):
                async with conn.begin_nested():
                    await ExaWebsetsD4Materializer(
                        storage=storage,
                        conn_factory=conn_session_factory(conn),
                    ).materialize(workspace_id=workspace_id, batch_id=batch_id)
            assert await _workspace_table_counts(conn, workspace_id) == (0, 0, 0, 0, 0, 0)

    run_async(_run())


def test_d4_excludes_unresolvable_company_without_fabricating_account(tmp_path: Path) -> None:
    async def _run() -> None:
        async with rollback_conn() as conn:
            workspace_id = "d4-exclusion"
            storage = FsStorage(tmp_path)
            invalid = deepcopy(
                _company_item("item_d4_invalid", city="Austin", criterion_state="yes")
            )
            properties = invalid["properties"]
            assert isinstance(properties, dict)
            properties["url"] = "https://localhost/"
            batch_id, (item_id,), _ = await _seed_terminal_batch(
                conn,
                storage,
                workspace_id,
                item_payloads=[invalid],
            )
            result = await ExaWebsetsD4Materializer(
                storage=storage,
                conn_factory=conn_session_factory(conn),
            ).materialize(workspace_id=workspace_id, batch_id=batch_id)

            assert result.batch_state is DiscoveryBatchState.SEAL_PENDING
            assert result.excluded_item_count == 1
            assert result.account_ids == ()
            assert result.claim_ids == ()
            link = await get_discovery_candidate_link(
                conn,
                workspace_id=workspace_id,
                batch_id=batch_id,
                item_snapshot_id=item_id,
            )
            assert link is not None
            assert link.admission_status is DiscoveryCandidateAdmissionState.EXCLUDED
            assert link.disposition_reason == "missing_required_name_or_registrable_domain"
            assert (
                int(
                    (
                        await conn.execute(
                            text(
                                "SELECT count(*) FROM account_entity "
                                "WHERE workspace_id = :workspace"
                            ),
                            {"workspace": workspace_id},
                        )
                    ).scalar_one()
                )
                == 0
            )

    run_async(_run())


def test_field_materialization_wake_routes_to_d4_without_provider_lifecycle(
    tmp_path: Path,
) -> None:
    class _RecordingMaterializer:
        def __init__(self) -> None:
            self.calls: list[tuple[str, DiscoveryBatchId]] = []

        async def materialize(self, *, workspace_id: str, batch_id: DiscoveryBatchId) -> object:
            self.calls.append((workspace_id, batch_id))
            return object()

    class _ForbiddenLifecycle:
        async def run_once(self, **_: object) -> object:
            raise AssertionError("field-materialization wake must not call the Exa lifecycle")

    async def _run() -> None:
        async with rollback_conn() as conn:
            workspace_id = "d4-wake-routing"
            batch_id, _, _ = await _seed_terminal_batch(
                conn,
                FsStorage(tmp_path),
                workspace_id,
            )
            # The named local acceptance DB intentionally retains live-fixture wakes. Hide those
            # inside this rollback-only transaction so the global worker claims only this case.
            await conn.execute(
                text(
                    "UPDATE discovery_wake_outbox SET claimed_at = now(), processed_at = now() "
                    "WHERE workspace_id <> :workspace_id AND processed_at IS NULL"
                ),
                {"workspace_id": workspace_id},
            )
            operation_id, project_run_id = (
                await conn.execute(
                    text(
                        "SELECT operation.id, batch.project_run_id "
                        "FROM discovery_operation operation "
                        "JOIN discovery_batch batch ON batch.id = operation.batch_id "
                        "AND batch.workspace_id = operation.workspace_id "
                        "WHERE operation.workspace_id = :workspace_id "
                        "AND operation.batch_id = :batch_id"
                    ),
                    {"workspace_id": workspace_id, "batch_id": batch_id},
                )
            ).one()
            await schedule_discovery_wake(
                conn,
                workspace_id=workspace_id,
                request=DiscoveryWakeRequest(
                    workspace_id=workspace_id,
                    project_run_id=project_run_id,
                    discovery_batch_id=batch_id,
                    operation_id=operation_id,
                    reason=DiscoveryWakeReason.FIELD_MATERIALIZATION,
                    available_at=_NOW,
                    dedupe_key=f"d4-materialize:{batch_id}",
                ),
            )
            materializer = _RecordingMaterializer()
            woken_runs: list[ProjectRunId] = []

            async def _wake_project_run(run_id: ProjectRunId) -> object:
                woken_runs.append(run_id)
                return True

            worker = ExaDiscoveryWakeWorker(
                lifecycle=_ForbiddenLifecycle(),  # type: ignore[arg-type]
                materializer=materializer,
                project_run_waker=_wake_project_run,
                conn_factory=conn_session_factory(conn),
            )

            assert await worker.run_due(now=_NOW) == 1
            assert materializer.calls == [(workspace_id, batch_id)]
            assert woken_runs == [project_run_id]
            processed_at = (
                await conn.execute(
                    text(
                        "SELECT processed_at FROM discovery_wake_outbox "
                        "WHERE workspace_id = :workspace_id AND dedupe_key = :dedupe_key"
                    ),
                    {
                        "workspace_id": workspace_id,
                        "dedupe_key": f"d4-materialize:{batch_id}",
                    },
                )
            ).scalar_one()
            assert processed_at is not None

    run_async(_run())
