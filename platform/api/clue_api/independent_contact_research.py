"""Independently invoke selected-contact research through the same C6 preparation seam."""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable
from typing import Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict

from clue_api.contact_research_preparation import ContactResearchBatchPreparer
from clue_api.deep.orchestrator import deep_account_run_id
from clue_config import OverlayStore
from clue_core import (
    ClaimId,
    ContactPreparationStatus,
    ContactResearchPreparation,
    EntityId,
    PreSpendGate,
    ProjectRunId,
)
from clue_db import ConnFactory, transaction
from clue_research.durable import AccountRunSubPhase, get_account_run, get_project_run
from clue_research.icp import get_icp_version
from clue_research.profiling import ContactProfileResult, profile_contact

ProfileContactFn = Callable[..., Awaitable[ContactProfileResult]]


class IndependentContactResearchResult(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    contact_entity_id: EntityId
    account_entity_id: EntityId
    project_run_id: ProjectRunId
    preparation: ContactResearchPreparation
    selection_ref: str | None = None
    claim_refs: tuple[ClaimId, ...] = ()
    fields_filled: int = 0


@runtime_checkable
class IndependentContactResearchRunner(Protocol):
    async def run(
        self,
        *,
        workspace_id: str,
        project_run_id: ProjectRunId,
        account_entity_id: EntityId,
        contact_entity_id: EntityId,
    ) -> IndependentContactResearchResult: ...


class IndependentContactResearchService:
    """Require local committee/directive state, prepare externally, then write in a short tx."""

    def __init__(
        self,
        *,
        preparer: ContactResearchBatchPreparer,
        pre_spend_gate: PreSpendGate,
        conn_factory: ConnFactory = transaction,
        profile_contact_fn: ProfileContactFn = profile_contact,
        config_store: OverlayStore | None = None,
    ) -> None:
        self._preparer = preparer
        self._gate = pre_spend_gate
        self._conn_factory = conn_factory
        self._profile_contact = profile_contact_fn
        self._config_store = config_store

    async def run(
        self,
        *,
        workspace_id: str,
        project_run_id: ProjectRunId,
        account_entity_id: EntityId,
        contact_entity_id: EntityId,
    ) -> IndependentContactResearchResult:
        account_run_id = deep_account_run_id(project_run_id, account_entity_id)
        async with self._conn_factory() as conn:
            account_run = await get_account_run(conn, account_run_id)
            project_run = await get_project_run(conn, project_run_id)
        if (
            account_run is None
            or project_run is None
            or project_run.workspace_id != workspace_id
            or account_run.project_run_id != project_run_id
            or account_run.entity_id != account_entity_id
            or account_run.sub_phase
            not in {
                AccountRunSubPhase.COMMITTEE_DISCOVERED,
                AccountRunSubPhase.CONTACTS_COMPLETE,
            }
            or account_run.research_directive is None
        ):
            raise ValueError(
                "independent contact research requires the exact directive-pinned committee run"
            )
        committee_contacts = tuple(
            EntityId(uuid.UUID(value))
            for value in account_run.references_index.get("committee_contacts", ())
        )
        committee_claims = tuple(
            ClaimId(uuid.UUID(value)) for value in account_run.references_index.get("committee", ())
        )
        if contact_entity_id not in committee_contacts:
            raise ValueError("independent contact does not belong to the materialized committee")

        # No connection or claim transaction is open while preparation may call/poll providers.
        prepared = await self._preparer.prepare_independent(
            workspace_id=workspace_id,
            project_run_id=project_run_id,
            account_run_id=account_run_id,
            account_entity_id=account_entity_id,
            contact_entity_id=contact_entity_id,
            committee_contact_entity_ids=committee_contacts,
            committee_claim_ids=committee_claims,
        )
        selection_ref = (
            None
            if prepared.selection is None
            else (
                f"contact-selection:{prepared.selection.selection_id}:"
                f"{prepared.selection.selection_sha256}"
            )
        )
        if prepared.preparation.status is not ContactPreparationStatus.READY:
            return IndependentContactResearchResult(
                contact_entity_id=contact_entity_id,
                account_entity_id=account_entity_id,
                project_run_id=project_run_id,
                preparation=prepared.preparation,
                selection_ref=selection_ref,
                claim_refs=tuple(
                    dict.fromkeys(
                        claim for target in prepared.targets for claim in target.claim_refs
                    )
                ),
            )
        target = prepared.targets[0]
        async with self._conn_factory() as conn:
            spec = await get_icp_version(
                conn,
                workspace_id,
                project_run.icp_key,
                project_run.icp_version,
            )
            if spec is None:
                raise ValueError("independent contact run's pinned ICP is missing")
            profiled = await self._profile_contact(
                conn,
                contact_entity_id=contact_entity_id,
                account_entity_id=account_entity_id,
                run_id=account_run_id,
                workspace_id=workspace_id,
                tier=account_run.tier,
                spec=spec,
                field_keys=tuple(str(field_key) for field_key in target.field_keys),
                prepared_claim_refs=target.claim_refs,
                pre_spend_gate=self._gate,
                icp_key=project_run.icp_key,
                config_store=self._config_store,
            )
        return IndependentContactResearchResult(
            contact_entity_id=contact_entity_id,
            account_entity_id=account_entity_id,
            project_run_id=project_run_id,
            preparation=prepared.preparation,
            selection_ref=selection_ref,
            claim_refs=tuple(dict.fromkeys((*target.claim_refs, *profiled.claim_refs))),
            fields_filled=profiled.fields_filled,
        )


__all__ = [
    "IndependentContactResearchResult",
    "IndependentContactResearchRunner",
    "IndependentContactResearchService",
]
