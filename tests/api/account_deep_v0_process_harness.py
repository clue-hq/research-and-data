"""Child-process harness for M8B V0 durable replay and inspection acceptance."""

from __future__ import annotations

import argparse
import asyncio
import json
from collections.abc import AsyncIterator, Mapping
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_api.committee_eligibility import CommitteeEligibilityService
from clue_api.sumble_committee_acquisition import (
    SumbleCommitteeAcquisitionCoordinator,
    SumbleCommitteeOutcome,
    compile_sumble_committee_preflight,
)
from clue_api.sumble_committee_launch import GatedSumbleCommitteeLauncher
from clue_api.sumble_committee_source import SumbleCommitteeSource
from clue_core import CommitteeAcquisitionOperationId, RunId, new_operation_id
from clue_db import db_lifespan, transaction
from clue_research.durable import (
    AccountRunStatus,
    AccountRunSubPhase,
    create_account_deep_launch,
    fold_references,
    get_account_run,
    get_committee_acquisition_operation,
    list_committee_acquisition_attempts,
    list_committee_acquisition_snapshots,
    set_account_sub_phase,
)
from clue_research.identity import get_account
from clue_research.profiling.committee import discover_committee
from clue_research.verification import PreSpendGateImpl
from clue_storage import FsStorage, read_verified_artifact
from tests.api.test_sumble_committee_acquisition_s2b import _CommitteeTransport, _setup
from tests.api.test_sumble_committee_eligibility_s2d import _authorization, _sources
from tests.profiling.conftest import FakeGateway, seed_packs


class _ForbiddenTransport:
    def search_teams(self, _body: Mapping[str, Any], *, maximum_credits: int) -> tuple[Any, Any]:
        del maximum_credits
        raise AssertionError("fresh-process replay attempted a Sumble Teams call")

    def submit_people(self, _body: Mapping[str, Any], *, maximum_credits: int) -> tuple[Any, Any]:
        del maximum_credits
        raise AssertionError("fresh-process replay attempted a Sumble People submit")

    def poll_people(self, _request_id: str, *, maximum_credits: int) -> tuple[Any, Any]:
        del maximum_credits
        raise AssertionError("fresh-process replay attempted a Sumble People poll")


@asynccontextmanager
async def _same_connection(conn: AsyncConnection) -> AsyncIterator[AsyncConnection]:
    yield conn


async def _inspect(
    conn: AsyncConnection,
    *,
    storage: FsStorage,
    workspace_id: str,
    project_run_id: UUID,
    account_id: UUID,
    operation_id: CommitteeAcquisitionOperationId,
) -> dict[str, Any]:
    operation = await get_committee_acquisition_operation(
        conn,
        workspace_id=workspace_id,
        operation_id=operation_id,
    )
    if operation is None:
        raise RuntimeError("V0 operation is absent in the fresh process")
    snapshots = await list_committee_acquisition_snapshots(
        conn,
        workspace_id=workspace_id,
        operation_id=operation.operation_id,
    )
    attempts = await list_committee_acquisition_attempts(
        conn,
        workspace_id=workspace_id,
        operation_id=operation.operation_id,
    )
    artifact_rows = (
        (
            await conn.execute(
                text(
                    "SELECT DISTINCT artifact.storage_key FROM artifact "
                    "JOIN discovery_artifact_subject subject "
                    "ON subject.workspace_id=artifact.workspace_id "
                    "AND subject.artifact_key=artifact.storage_key "
                    "WHERE subject.workspace_id=:workspace_id "
                    "AND subject.subject_kind='account' "
                    "AND subject.subject_entity_id=:account_id "
                    "AND subject.tombstoned_at IS NULL "
                    "AND artifact.erased_at IS NULL AND artifact.purged_at IS NULL "
                    "ORDER BY artifact.storage_key"
                ),
                {"workspace_id": workspace_id, "account_id": account_id},
            )
        )
        .scalars()
        .all()
    )
    verified_artifacts = 0
    for key in artifact_rows:
        await read_verified_artifact(
            conn,
            storage,
            storage_key=str(key),
            workspace_id=workspace_id,
        )
        verified_artifacts += 1
    claim_count = int(
        (
            await conn.execute(
                text(
                    "SELECT count(*) FROM claim WHERE workspace_id=:workspace_id "
                    "AND run_id=:run_id AND superseded_by IS NULL"
                ),
                {"workspace_id": workspace_id, "run_id": project_run_id},
            )
        ).scalar_one()
    )
    gate_count = int(
        (
            await conn.execute(
                text("SELECT count(*) FROM gate_decision WHERE run_id=:run_id"),
                {"run_id": project_run_id},
            )
        ).scalar_one()
    )
    eligibility_count = int(
        (
            await conn.execute(
                text(
                    "SELECT count(*) FROM committee_eligibility_decision "
                    "WHERE workspace_id=:workspace_id AND project_run_id=:run_id"
                ),
                {"workspace_id": workspace_id, "run_id": project_run_id},
            )
        ).scalar_one()
    )
    account_run = await get_account_run(conn, RunId(project_run_id))
    if account_run is None:
        raise RuntimeError("V0 account-run projection is absent")
    launch_rows = (
        (
            await conn.execute(
                text(
                    "SELECT id, request_sha256 FROM account_deep_launch "
                    "WHERE workspace_id=:workspace_id AND project_run_id=:project_run_id"
                ),
                {"workspace_id": workspace_id, "project_run_id": project_run_id},
            )
        )
        .mappings()
        .all()
    )
    if len(launch_rows) != 1:
        raise RuntimeError("V0 expected exactly one immutable account-deep launch")
    return {
        "workspace_id": workspace_id,
        "project_run_id": str(project_run_id),
        "account_id": str(account_id),
        "operation_id": str(operation.operation_id),
        "operation_state": operation.state.value,
        "receipt_ref": operation.receipt_manifest_key,
        "provider_units_charged": str(operation.provider_units_charged),
        "cost_cents_charged": str(operation.cost_cents_charged),
        "snapshot_refs": [f"{item.source_key}:{item.request_fingerprint}" for item in snapshots],
        "attempt_count": len(attempts),
        "claim_count": claim_count,
        "gate_count": gate_count,
        "eligibility_count": eligibility_count,
        "verified_artifact_count": verified_artifacts,
        "account_run_status": account_run.status.value,
        "account_run_sub_phase": (
            account_run.sub_phase.value if account_run.sub_phase is not None else None
        ),
        "account_run_refs": account_run.references_index,
        "launch_id": str(launch_rows[0]["id"]),
        "launch_request_sha256": str(launch_rows[0]["request_sha256"]),
    }


async def _seed(storage_root: Path, state_path: Path, workspace_id: str) -> None:
    storage = FsStorage(storage_root)
    async with db_lifespan(), transaction() as conn:
        await seed_packs(conn)
        request = await _setup(
            conn,
            storage,
            workspace_id=workspace_id,
            strict_s2d=True,
        )
        created_launch = await create_account_deep_launch(
            conn,
            workspace_id=request.workspace_id,
            project_run_id=request.project_run_id,
            directive_id=request.research_directive.directive_id,
            account_entity_ids=(request.account_id,),
            approved_budget_cap_cents=Decimal(14),
            expected_estimated_cost_cents=Decimal(14),
            created_by="human:v0-fresh-process",
            source_operation_id=new_operation_id(),
            source_action_ref="turn:v0-launch-confirmed",
        )
        if created_launch.replayed:
            raise RuntimeError("V0 seed unexpectedly replayed its first launch")

        def factory() -> AbstractAsyncContextManager[AsyncConnection]:
            return _same_connection(conn)

        transport = _CommitteeTransport()
        coordinator = SumbleCommitteeAcquisitionCoordinator(
            transport=transport,
            storage=storage,
            cents_per_credit=Decimal("0.5"),
            conn_factory=factory,
            poll_after_seconds=30,
        )
        launcher = GatedSumbleCommitteeLauncher(
            eligibility=CommitteeEligibilityService(
                storage=storage,
                pre_spend_gate=PreSpendGateImpl(conn_factory=factory),
                sources=_sources(),
                conn_factory=factory,
            ),
            starter=coordinator,
        )
        preflight = compile_sumble_committee_preflight(request, cents_per_credit=Decimal("0.5"))
        launched = await launcher.start(preflight, authorization=_authorization(request))
        if launched.acquisition is None:
            raise RuntimeError("V0 seed did not create the committee acquisition")
        acquisition = launched.acquisition
        for _ in range(2):
            await conn.execute(
                text(
                    "UPDATE committee_acquisition_operation SET next_poll_at=:past "
                    "WHERE id=:operation_id"
                ),
                {
                    "operation_id": acquisition.operation.operation_id,
                    "past": datetime.now(UTC) - timedelta(seconds=1),
                },
            )
            resumed = await launcher.start(preflight, authorization=_authorization(request))
            if resumed.acquisition is None:
                raise RuntimeError("V0 seed lost its acquisition while polling")
            acquisition = resumed.acquisition
        if acquisition.outcome is not SumbleCommitteeOutcome.READY:
            raise RuntimeError("V0 seed did not reach a ready committee snapshot")
        account = await get_account(conn, request.account_id)
        if account is None:
            raise RuntimeError("V0 seed account disappeared")
        source = SumbleCommitteeSource(
            operation_ids={request.account_id: acquisition.operation.operation_id},
            storage=storage,
            conn_factory=factory,
        )
        committee = await discover_committee(
            conn,
            account_entity_id=request.account_id,
            run_id=RunId(request.project_run_id),
            workspace_id=request.workspace_id,
            sources=(source,),
            gateway=FakeGateway(),
            role_model="v0-recorded-role-model",
        )
        refs = {
            "committee_claims": [str(item) for item in committee.claim_refs],
            "external:committee:operation": [str(acquisition.operation.operation_id)],
            "external:committee:snapshots": [
                f"{item.source_key}:{item.request_fingerprint}"
                for item in await list_committee_acquisition_snapshots(
                    conn,
                    workspace_id=request.workspace_id,
                    operation_id=acquisition.operation.operation_id,
                )
            ],
            "external:committee:receipt": [str(acquisition.operation.receipt_manifest_key)],
        }
        await fold_references(
            conn,
            RunId(request.project_run_id),
            references_index=refs,
            status=AccountRunStatus.RUNNING,
        )
        await set_account_sub_phase(
            conn,
            RunId(request.project_run_id),
            AccountRunSubPhase.COMMITTEE_DISCOVERED,
        )
        report = await _inspect(
            conn,
            storage=storage,
            workspace_id=request.workspace_id,
            project_run_id=UUID(str(request.project_run_id)),
            account_id=UUID(str(request.account_id)),
            operation_id=acquisition.operation.operation_id,
        )
        if transport.calls != [
            "teams",
            "people_submit",
            "people_poll",
            "people_poll",
        ]:
            raise RuntimeError(f"unexpected V0 provider fixture calls: {transport.calls}")
    state_path.write_text(json.dumps(report, sort_keys=True), encoding="utf-8")
    print(json.dumps({**report, "provider_calls_this_process": len(transport.calls)}))


async def _replay(storage_root: Path, state_path: Path) -> None:
    state = json.loads(state_path.read_text(encoding="utf-8"))
    storage = FsStorage(storage_root)
    async with db_lifespan(), transaction() as conn:
        operation = await get_committee_acquisition_operation(
            conn,
            workspace_id=state["workspace_id"],
            operation_id=CommitteeAcquisitionOperationId(UUID(state["operation_id"])),
        )
        if operation is None:
            raise RuntimeError("fresh-process replay cannot find the original operation")
        coordinator = SumbleCommitteeAcquisitionCoordinator(
            transport=_ForbiddenTransport(),
            storage=storage,
            cents_per_credit=Decimal("0.5"),
            conn_factory=lambda: _same_connection(conn),
        )
        replay = await coordinator.start(
            compile_sumble_committee_preflight(operation.request, cents_per_credit=Decimal("0.5"))
        )
        if replay.outcome is not SumbleCommitteeOutcome.REPLAYED:
            raise RuntimeError(f"fresh-process replay returned {replay.outcome.value}")
        report = await _inspect(
            conn,
            storage=storage,
            workspace_id=state["workspace_id"],
            project_run_id=UUID(state["project_run_id"]),
            account_id=UUID(state["account_id"]),
            operation_id=CommitteeAcquisitionOperationId(UUID(state["operation_id"])),
        )
    print(json.dumps({**report, "provider_calls_this_process": replay.provider_calls}))


async def _launch(state_path: Path) -> None:
    state = json.loads(state_path.read_text(encoding="utf-8"))
    async with db_lifespan(), transaction() as conn:
        operation = await get_committee_acquisition_operation(
            conn,
            workspace_id=state["workspace_id"],
            operation_id=CommitteeAcquisitionOperationId(UUID(state["operation_id"])),
        )
        if operation is None:
            raise RuntimeError("concurrent launch cannot find the durable V0 operation")
        launched = await create_account_deep_launch(
            conn,
            workspace_id=operation.request.workspace_id,
            project_run_id=operation.request.project_run_id,
            directive_id=operation.request.research_directive.directive_id,
            account_entity_ids=(operation.request.account_id,),
            approved_budget_cap_cents=Decimal(14),
            expected_estimated_cost_cents=Decimal(14),
            created_by="human:v0-concurrent-replay",
            source_operation_id=new_operation_id(),
            source_action_ref="turn:v0-concurrent-launch",
        )
    print(
        json.dumps(
            {
                "launch_id": str(launched.launch.id),
                "request_sha256": launched.launch.request_sha256,
                "replayed": launched.replayed,
            }
        )
    )


def _args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("seed", "launch", "replay"))
    parser.add_argument("--storage-root", type=Path)
    parser.add_argument("--state", type=Path, required=True)
    parser.add_argument("--workspace-id")
    return parser.parse_args()


def main() -> None:
    args = _args()
    if args.mode == "seed":
        if not args.workspace_id or args.storage_root is None:
            raise SystemExit("seed mode requires --workspace-id and --storage-root")
        asyncio.run(_seed(args.storage_root, args.state, args.workspace_id))
    elif args.mode == "replay":
        if args.storage_root is None:
            raise SystemExit("replay mode requires --storage-root")
        asyncio.run(_replay(args.storage_root, args.state))
    else:
        asyncio.run(_launch(args.state))


if __name__ == "__main__":
    main()
