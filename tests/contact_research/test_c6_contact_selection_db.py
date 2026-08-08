"""M8C C6 durable selection, steering, and independent-contact database acceptance."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncConnection
from tests.contact_research.test_c4_exa_contact_acquisition_materialization import _seed
from tests.db.conftest import run_async
from tests.profiling.conftest import conn_session_factory, rollback_conn
from tests.profiling.conftest import migrated_db as migrated_db
from tests.profiling.conftest import require_profiling_db as require_profiling_db

from clue_api.contact_research_preparation import (
    ContactPreparationAdapterResult,
    ContactResearchBatchPreparer,
    RegisteredContactResearchPreparer,
)
from clue_api.contact_research_selection import ContactResearchSelectionMaterializer
from clue_api.deep.orchestrator import deep_account_run_id
from clue_api.independent_contact_research import IndependentContactResearchService
from clue_api.toolbelt_wiring import build_toolbelt
from clue_api.trial.discovery_fixture import WORKSPACE_ID
from clue_core import (
    ClaimId,
    ContactPreparationStatus,
    ContactResearchIntent,
    ContactResearchPreparation,
    ContactResearchSelection,
    EntityId,
    EntityType,
    ExtractionMethod,
    IdentityBinding,
    Persona,
    PreSpendDecision,
    PreSpendVerdict,
    ProjectRunId,
    ResearchMode,
    RunId,
    UseClass,
    contact_claim,
    discovery_claim,
    new_contact_research_selection_id,
    new_operation_id,
    new_run_id,
    revalidate_with,
)
from clue_research.claimstore import insert_claim
from clue_research.durable import (
    AccountRunStatus,
    AccountRunSubPhase,
    ContactResearchSelectionApprovalAuthority,
    ContactResearchSelectionApprovalKind,
    ContactResearchSelectionRepositoryError,
    cancel_contact_research_selection,
    ensure_account_run,
    get_contact_research_selection,
    latest_contact_research_selection,
    pin_account_run_research_directive,
    save_references,
    set_account_sub_phase,
    store_contact_research_selection,
)
from clue_research.identity import insert_account_entity, stamp_reuse
from clue_research.profiling import ContactProfileResult
from clue_research.profiling.committee import (
    PERSONA,
    ROLE_ON_COMMITTEE,
    load_committee_pack,
)
from clue_research.profiling.committee.admission import DISCOVERY_PROVENANCE_FIELD
from clue_storage import FsStorage
from clue_toolbelt import PreconditionFailed, ToolContext, invoke_tool

pytestmark = pytest.mark.usefixtures("require_profiling_db")


@dataclass(frozen=True)
class _SelectionSeed:
    materializer: ContactResearchSelectionMaterializer
    account_run_id: RunId
    account_id: EntityId
    contact_id: EntityId
    project_run_id: ProjectRunId
    committee_claim_ids: tuple[ClaimId, ...]


async def _selection_seed(
    conn: AsyncConnection,
    storage: FsStorage,
    *,
    suffix: str,
) -> _SelectionSeed:
    seeded = await _seed(conn, storage, suffix=suffix, persist_selection=False)
    intent = seeded.intent
    account_run_id = deep_account_run_id(
        intent.project_run_id,
        intent.account_entity_id,
    )
    await ensure_account_run(
        conn,
        account_run_id=account_run_id,
        project_run_id=intent.project_run_id,
        entity_id=intent.account_entity_id,
        tier="high",
    )
    await pin_account_run_research_directive(
        conn,
        account_run_id=account_run_id,
        pin=intent.research_directive,
    )
    await load_committee_pack(conn)

    discovery = stamp_reuse(
        discovery_claim(
            entity_id=intent.contact_entity_id,
            entity_type=EntityType.CONTACT,
            field_key=DISCOVERY_PROVENANCE_FIELD,
            value_json={
                "matched_channel": "sumble_people",
                "matched_signal": "exact linkedin identity",
                "discovery_confidence": 0.99,
            },
            source_tier=1,
            extraction_method=ExtractionMethod.API,
            confidence=0.99,
            run_id=account_run_id,
            research_mode=ResearchMode.COMMITTEE_DISCOVERY,
            found_via="sumble_people",
            matched_signal="exact linkedin identity",
            discovery_confidence=0.99,
            source_url="https://www.linkedin.com/in/alex-rivera-c6",
        ),
        workspace_id=intent.workspace_id,
    )
    discovery_id = await insert_claim(conn, discovery)

    async def _committee_claim(field_key: str, value: object) -> ClaimId:
        claim = stamp_reuse(
            contact_claim(
                entity_id=intent.contact_entity_id,
                field_key=field_key,
                value_json=value,  # type: ignore[arg-type]
                source_tier=2,
                extraction_method=ExtractionMethod.API,
                confidence=0.95,
                run_id=account_run_id,
                research_mode=ResearchMode.COMMITTEE_DISCOVERY,
                identity_binding=IdentityBinding.STRONG,
                use_class=UseClass.PROFESSIONAL_PUBLIC,
                source_url="https://sumble.com/people/alex-rivera-c6",
                evidence_span=f"Sumble returned {field_key} for the exact person",
            ),
            workspace_id=intent.workspace_id,
        )
        return await insert_claim(
            conn,
            revalidate_with(
                claim,
                source_key="sumble_people",
            ),
        )

    role_id = await _committee_claim(
        ROLE_ON_COMMITTEE,
        {
            "role": Persona.CHAMPION.value,
            "confidence": 0.95,
            "plausible": True,
            "rationale": "operations owner",
        },
    )
    persona_id = await _committee_claim(PERSONA, Persona.CHAMPION.value)
    return _SelectionSeed(
        materializer=ContactResearchSelectionMaterializer(conn_factory=conn_session_factory(conn)),
        account_run_id=account_run_id,
        account_id=intent.account_entity_id,
        contact_id=intent.contact_entity_id,
        project_run_id=intent.project_run_id,
        committee_claim_ids=(discovery_id, role_id, persona_id),
    )


async def _materialize(seed: _SelectionSeed) -> ContactResearchSelection:
    selection = await seed.materializer.materialize(
        workspace_id=WORKSPACE_ID,
        project_run_id=seed.project_run_id,
        account_run_id=seed.account_run_id,
        account_entity_id=seed.account_id,
        contact_entity_ids=(seed.contact_id,),
        committee_claim_ids=seed.committee_claim_ids,
    )
    assert selection is not None
    return selection


def test_selection_is_content_elected_and_cancelled_authority_cannot_auto_resurrect(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            seed = await _selection_seed(conn, FsStorage(tmp_path / "artifacts"), suffix="c6-db")
            first = await _materialize(seed)
            replay_candidate = ContactResearchSelection.from_body(
                first.body,
                effective_policy=first.body.policy,
                selection_id=new_contact_research_selection_id(),
            )
            replayed = await store_contact_research_selection(
                conn,
                replay_candidate,
                account_run_id=seed.account_run_id,
            )
            assert replayed.selection_id == first.selection_id

            cancelled = await cancel_contact_research_selection(
                conn,
                workspace_id=first.body.workspace_id,
                selection_id=first.selection_id,
                cancelled_by="human:c6",
                reason_code="steering_changed",
            )
            assert cancelled.selection_id == first.selection_id
            blocked = await _materialize(seed)
            assert blocked.selection_id == first.selection_id
            count = int(
                (
                    await conn.execute(
                        text(
                            "SELECT count(*) FROM contact_research_selection "
                            "WHERE project_run_id=:project_run_id AND account_id=:account_id"
                        ),
                        {
                            "project_run_id": seed.project_run_id,
                            "account_id": seed.account_id,
                        },
                    )
                ).scalar_one()
            )
            assert count == 1

    run_async(scenario())


def test_selection_requires_db_approval_and_successors_form_one_current_linear_head(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            seed = await _selection_seed(
                conn,
                FsStorage(tmp_path / "artifacts"),
                suffix="c6-linear-authority",
            )
            initial = await _materialize(seed)
            approved_at = datetime.now(UTC)
            successor_body = initial.body.model_copy(
                update={
                    "budget_reservation_ref": "budget:c6:approved-successor",
                    "approved_by": "human:c6-successor",
                    "approved_at": approved_at,
                }
            )
            successor = ContactResearchSelection.from_body(
                successor_body,
                effective_policy=successor_body.policy,
                selection_id=new_contact_research_selection_id(),
            )
            with pytest.raises(
                ContactResearchSelectionRepositoryError,
                match="requires trusted approval authority",
            ):
                await store_contact_research_selection(
                    conn,
                    successor,
                    account_run_id=seed.account_run_id,
                    predecessor_id=initial.selection_id,
                )

            registry = build_toolbelt(
                storage=None,
                gateway=None,
                conn_factory=conn_session_factory(conn),
            )
            tool_inputs = {
                "selection": successor.model_dump(mode="json"),
                "account_run_id": str(seed.account_run_id),
                "predecessor_selection_id": str(initial.selection_id),
            }
            successor_id = successor.selection_id
            with pytest.raises(PreconditionFailed) as agent_denial:
                await invoke_tool(
                    registry,
                    "approve_contact_research_selection",
                    tool_inputs,
                    ToolContext(
                        workspace_id=successor.body.workspace_id,
                        actor="agent",
                        actor_id="agent:research",
                        action_ref="agent-action:c6-forbidden",
                        conn_factory=conn_session_factory(conn),
                        operation_id=new_operation_id(),
                    ),
                    # M8D R10 promotes the R7 entity-research approver as the name default;
                    # this M8C acceptance pins its exact historical tool version.
                    version="1",
                    idempotency_ttl_s=86_400,
                )
            assert agent_denial.value.reason_codes == ("human_required",)

            approval_operation_id = new_operation_id()
            approved = await invoke_tool(
                registry,
                "approve_contact_research_selection",
                tool_inputs,
                ToolContext(
                    workspace_id=successor.body.workspace_id,
                    actor="human",
                    principal_kind="human",
                    actor_id=successor_body.approved_by,
                    membership_id="wsm_c6_successor",
                    action_ref="human-action:c6-successor",
                    conn_factory=conn_session_factory(conn),
                    operation_id=approval_operation_id,
                ),
                version="1",
                idempotency_ttl_s=86_400,
            )
            successor = await get_contact_research_selection(
                conn,
                workspace_id=successor.body.workspace_id,
                selection_id=successor_id,
            )
            assert approved.references["selection_id"] == str(successor.selection_id)
            assert approved.references["approval_ref"] == (
                f"contact-research-selection-approval:{approval_operation_id}"
            )
            assert (
                await latest_contact_research_selection(
                    conn,
                    workspace_id=successor.body.workspace_id,
                    project_run_id=successor.body.project_run_id,
                    account_id=successor.body.account_entity_id,
                    include_cancelled=True,
                )
            ) == successor

            fork_body = initial.body.model_copy(
                update={
                    "budget_reservation_ref": "budget:c6:invalid-fork",
                    "approved_by": "human:c6-successor",
                    "approved_at": approved_at + timedelta(seconds=1),
                }
            )
            fork = ContactResearchSelection.from_body(
                fork_body,
                effective_policy=fork_body.policy,
                selection_id=new_contact_research_selection_id(),
            )
            with pytest.raises(DBAPIError, match="current selection head"):
                async with conn.begin_nested():
                    await store_contact_research_selection(
                        conn,
                        fork,
                        account_run_id=seed.account_run_id,
                        predecessor_id=initial.selection_id,
                        approval=ContactResearchSelectionApprovalAuthority(
                            kind=ContactResearchSelectionApprovalKind.HUMAN_SUCCESSOR,
                            operation_id=uuid4(),
                            approved_by=fork_body.approved_by,
                            action_ref="human-action:c6-invalid-fork",
                            approved_at=fork_body.approved_at,
                        ),
                    )
            approval_kinds = tuple(
                (
                    await conn.execute(
                        text(
                            "SELECT authority_kind FROM contact_research_selection_approval "
                            "WHERE workspace_id=:workspace_id AND account_id=:account_id "
                            "ORDER BY approved_at, authority_kind"
                        ),
                        {
                            "workspace_id": successor.body.workspace_id,
                            "account_id": successor.body.account_entity_id,
                        },
                    )
                ).scalars()
            )
            assert sorted(approval_kinds) == ["directive_confirmation", "human_successor"]

    run_async(scenario())


def test_one_directive_confirmation_can_approve_selections_for_multiple_accounts(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            seed = await _selection_seed(
                conn,
                FsStorage(tmp_path / "artifacts"),
                suffix="c6-multi-account-approval",
            )
            first = await _materialize(seed)
            directive = first.body.research_directive
            second_account_id = await insert_account_entity(
                conn,
                workspace_id=first.body.workspace_id,
                canonical_name="Second Directive Account",
                primary_domain="second-directive-account.example",
            )
            await conn.execute(
                text(
                    "INSERT INTO account_research_directive_account "
                    "(directive_id, workspace_id, account_id, scope_kind) VALUES "
                    "(:directive_id, :workspace_id, :account_id, 'explicit')"
                ),
                {
                    "directive_id": directive.directive_id,
                    "workspace_id": first.body.workspace_id,
                    "account_id": second_account_id,
                },
            )
            second_account_run_id = new_run_id()
            await ensure_account_run(
                conn,
                account_run_id=second_account_run_id,
                project_run_id=first.body.project_run_id,
                entity_id=second_account_id,
                tier="high",
            )
            await pin_account_run_research_directive(
                conn,
                account_run_id=second_account_run_id,
                pin=directive.model_copy(update={"account_id": second_account_id}),
            )
            confirmation = (
                await conn.execute(
                    text(
                        "SELECT confirmation_operation_id, confirmed_by, "
                        "confirming_turn_ref, confirmed_at FROM account_research_directive "
                        "WHERE directive_id=:directive_id"
                    ),
                    {"directive_id": directive.directive_id},
                )
            ).one()
            await conn.execute(
                text(
                    "INSERT INTO contact_research_selection_approval "
                    "(id, workspace_id, project_id, project_run_id, account_run_id, "
                    "account_id, directive_id, directive_version, directive_sha256, "
                    "selection_sha256, predecessor_id, authority_kind, approval_operation_id, "
                    "approved_by, action_ref, approved_at) VALUES "
                    "(:id, :workspace_id, :project_id, :project_run_id, :account_run_id, "
                    ":account_id, :directive_id, :directive_version, :directive_sha256, "
                    ":selection_sha256, NULL, 'directive_confirmation', "
                    ":approval_operation_id, :approved_by, :action_ref, :approved_at)"
                ),
                {
                    "id": uuid4(),
                    "workspace_id": first.body.workspace_id,
                    "project_id": first.body.project_id,
                    "project_run_id": first.body.project_run_id,
                    "account_run_id": second_account_run_id,
                    "account_id": second_account_id,
                    "directive_id": directive.directive_id,
                    "directive_version": directive.version,
                    "directive_sha256": directive.canonical_json_sha256,
                    "selection_sha256": "a" * 64,
                    "approval_operation_id": confirmation.confirmation_operation_id,
                    "approved_by": confirmation.confirmed_by,
                    "action_ref": confirmation.confirming_turn_ref,
                    "approved_at": confirmation.confirmed_at,
                },
            )
            approval_count = (
                await conn.execute(
                    text(
                        "SELECT count(*) FROM contact_research_selection_approval "
                        "WHERE workspace_id=:workspace_id "
                        "AND approval_operation_id=:approval_operation_id"
                    ),
                    {
                        "workspace_id": first.body.workspace_id,
                        "approval_operation_id": confirmation.confirmation_operation_id,
                    },
                )
            ).scalar_one()
            assert approval_count == 2

    run_async(scenario())


class _ReadyAdapter:
    def __init__(self, claim_ref: ClaimId) -> None:
        self.claim_ref = claim_ref
        self.calls = 0

    def claimed_source_keys(self, intent: ContactResearchIntent) -> frozenset[str]:
        return frozenset(intent.source_plan)

    async def prepare(self, **_kwargs: object) -> ContactPreparationAdapterResult:
        self.calls += 1
        return ContactPreparationAdapterResult(
            preparation=ContactResearchPreparation(
                status=ContactPreparationStatus.READY,
                snapshot_reference_ids=("contact-snapshot:c6-independent",),
                operation_reference_ids=("contact-operation:c6-independent",),
                spend_settlement_reference_ids=("contact-settlement:c6-independent",),
            ),
            claim_refs=(self.claim_ref,),
        )


class _PassGate:
    async def check(self, request: object) -> PreSpendDecision:
        del request
        return PreSpendDecision(verdict=PreSpendVerdict.PASS)


def test_independent_contact_uses_same_selection_and_preparation_seam(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            seed = await _selection_seed(
                conn,
                FsStorage(tmp_path / "independent-artifacts"),
                suffix="c6-independent",
            )
            await save_references(
                conn,
                seed.account_run_id,
                references_index={
                    "committee_contacts": [str(seed.contact_id)],
                    "committee": [str(claim_id) for claim_id in seed.committee_claim_ids],
                },
                cost_cents=Decimal(0),
                status=AccountRunStatus.RUNNING,
            )
            await set_account_sub_phase(
                conn,
                seed.account_run_id,
                AccountRunSubPhase.COMMITTEE_DISCOVERED,
            )
            adapter = _ReadyAdapter(seed.committee_claim_ids[1])
            factory = conn_session_factory(conn)
            batch = ContactResearchBatchPreparer(
                selections=seed.materializer,
                preparer=RegisteredContactResearchPreparer(
                    adapters=(adapter,),
                    conn_factory=factory,
                ),
            )
            observed_fields: list[tuple[str, ...]] = []

            async def _profile(
                _conn: AsyncConnection,
                *,
                contact_entity_id: EntityId,
                account_entity_id: EntityId,
                field_keys: tuple[str, ...],
                **_kwargs: object,
            ) -> ContactProfileResult:
                observed_fields.append(field_keys)
                return ContactProfileResult(
                    contact_entity_id=contact_entity_id,
                    account_entity_id=account_entity_id,
                    fields_filled=1,
                )

            service = IndependentContactResearchService(
                preparer=batch,
                pre_spend_gate=_PassGate(),  # type: ignore[arg-type]
                conn_factory=factory,
                profile_contact_fn=_profile,
            )
            result = await service.run(
                workspace_id=WORKSPACE_ID,
                project_run_id=seed.project_run_id,
                account_entity_id=seed.account_id,
                contact_entity_id=seed.contact_id,
            )
            assert result.preparation.status is ContactPreparationStatus.READY
            assert result.selection_ref is not None
            assert result.fields_filled == 1
            assert seed.committee_claim_ids[1] in result.claim_refs
            assert observed_fields == [("contact.facet.publications",)]
            assert adapter.calls == 1

    run_async(scenario())
