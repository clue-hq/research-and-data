"""M8C C5 selected-contact channel acquisition, validation, replay, and privacy gates."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from pydantic import SecretStr
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection
from tests._run_lineage import assert_written_claims_are_attributable
from tests.contact_research.test_c4_exa_contact_acquisition_materialization import (
    _seed,
    _TrackedConnFactory,
)
from tests.db.conftest import run_async
from tests.profiling.conftest import migrated_db as migrated_db
from tests.profiling.conftest import require_profiling_db as require_profiling_db
from tests.profiling.conftest import rollback_conn

import clue_api.contact_channel_enrichment as contact_channel_module
from clue_api.contact_channel_enrichment import (
    ContactChannelEligibilityError,
    ContactChannelEnrichmentOutcome,
    ExaContactChannelCoordinator,
    compile_contact_channel_preflight,
)
from clue_api.storage_wiring import DurableContactResearchPrivacyStopper
from clue_config import ContactResearchPolicy, Jurisdiction
from clue_core import (
    AccountEntity,
    ChannelIdentityCorroboration,
    ChannelReachability,
    Claim,
    ClaimId,
    ClaimProvenanceKind,
    ContactChannel,
    ContactChannelAuthorization,
    ContactChannelOperationState,
    ContactChannelValidationOutcome,
    ContactChannelValidatorRequest,
    ContactChannelValidatorResult,
    ContactEntity,
    ContactResearchIntent,
    ContactResearchSelection,
    EntityType,
    ExtractionMethod,
    FieldDef,
    IdentityBinding,
    PreSpendDecision,
    PreSpendVerdict,
    ResearchMode,
    ReuseScope,
    RunId,
    TargetLock,
    UseClass,
    UseDecision,
    UseReason,
    VerificationStatus,
    new_contact_research_selection_id,
    new_entity_id,
)
from clue_research.adapters.exa_websets import (
    ExaCreateImportRequest,
    ExaCreateImportResponse,
    ExaCreateWebsetRequest,
    ExaImportExchange,
    ExaItemPageExchange,
    ExaWebset,
    ExaWebsetExchange,
)
from clue_research.claimstore import insert_claim, load_core_pack
from clue_research.compliance import DataSubjectRightsImpl, load_compliance_pack
from clue_research.durable import (
    ContactResearchSelectionApprovalAuthority,
    ContactResearchSelectionApprovalKind,
    ContactResearchSelectionNotFound,
    contact_channel_is_usable,
    get_contact_channel_operation,
    list_contact_channel_operations_for_selection,
    store_contact_research_selection,
)
from clue_research.identity import get_contact, stamp_reuse
from clue_research.sources import seed_source_manifests
from clue_research.stage0 import load_client_knowledge_pack
from clue_storage import FsStorage

pytestmark = pytest.mark.usefixtures("require_profiling_db")

_EMAIL = "alex.rivera@practice.example"


class _PassGate:
    async def check(self, request: object) -> PreSpendDecision:
        del request
        return PreSpendDecision(verdict=PreSpendVerdict.PASS)

    async def assemble_target_lock(
        self, entity: AccountEntity | ContactEntity, field: FieldDef
    ) -> TargetLock:
        del entity, field
        raise AssertionError("the channel coordinator does not assemble an LLM target lock")


class _UseGate:
    async def evaluate(self, claim: Claim) -> UseDecision:
        return UseDecision(
            claim_id=claim.id,
            usable_for_outreach=True,
            reason=UseReason.ALLOWED,
            policy_version=1,
        )


class _DenyUseGate:
    async def evaluate(self, claim: Claim) -> UseDecision:
        return UseDecision(
            claim_id=claim.id,
            usable_for_outreach=False,
            reason=UseReason.USE_CLASS_DISALLOWED_FOR_REGIME,
            policy_version=1,
        )


class _Validator:
    source_key = "channel_validator"

    def __init__(self, claim_id: ClaimId, *, conflict: bool = False) -> None:
        self.claim_id = claim_id
        self.conflict = conflict
        self.calls = 0

    async def validate(
        self, request: ContactChannelValidatorRequest
    ) -> ContactChannelValidatorResult:
        self.calls += 1
        assert request.value == _EMAIL
        return ContactChannelValidatorResult(
            outcome=ContactChannelValidationOutcome.VALIDATED,
            identity_binding=IdentityBinding.STRONG,
            corroboration=(
                ChannelIdentityCorroboration.CONFLICTED
                if self.conflict
                else ChannelIdentityCorroboration.MATCHED
            ),
            reachability=ChannelReachability.REACHABLE,
            corroborating_claim_ids=(self.claim_id,),
            provider_reference_ids=("validator:request:c5",),
            evidence={"mailbox": "reachable", "identity": "matched"},
            provider_units_charged=Decimal(1),
            provider_cost_cents_charged=Decimal("0.50"),
        )


class _CrashingValidator(_Validator):
    async def validate(
        self, request: ContactChannelValidatorRequest
    ) -> ContactChannelValidatorResult:
        self.calls += 1
        raise RuntimeError("simulated crash after possible validator dispatch")


class _WeakValidator(_Validator):
    async def validate(
        self, request: ContactChannelValidatorRequest
    ) -> ContactChannelValidatorResult:
        self.calls += 1
        assert request.value == _EMAIL
        return ContactChannelValidatorResult(
            outcome=ContactChannelValidationOutcome.VALIDATED,
            identity_binding=IdentityBinding.WEAK,
            corroboration=ChannelIdentityCorroboration.MATCHED,
            reachability=ChannelReachability.REACHABLE,
            corroborating_claim_ids=(self.claim_id,),
            provider_reference_ids=("validator:request:c5-weak",),
            evidence={"mailbox": "reachable", "identity": "weak"},
            provider_units_charged=Decimal(1),
            provider_cost_cents_charged=Decimal("0.50"),
        )


class _FailingBudget:
    async def record(self, **_: object) -> None:
        raise RuntimeError("simulated acquisition settlement failure")


class _TransactionalTrackedConnFactory(_TrackedConnFactory):
    """Mirror production transaction rollback with savepoints on the fixture connection."""

    @asynccontextmanager
    async def __call__(self) -> AsyncIterator[AsyncConnection]:
        self.active += 1
        try:
            async with self.conn.begin_nested():
                yield self.conn
        finally:
            self.active -= 1


def _import_payload(request: ExaCreateImportRequest) -> dict[str, object]:
    now = datetime.now(UTC)
    return {
        "id": "import_c5",
        "object": "import",
        "status": "pending",
        "format": "csv",
        "entity": request.entity.model_dump(mode="json"),
        "title": request.title,
        "count": request.count,
        "metadata": request.metadata,
        "failedReason": None,
        "failedAt": None,
        "failedMessage": None,
        "createdAt": now.isoformat(),
        "updatedAt": now.isoformat(),
        "uploadUrl": "https://uploads.example.invalid/c5?credential=redacted",
        "uploadValidUntil": (now + timedelta(hours=1)).isoformat(),
    }


def _webset_payload(
    request: ExaCreateWebsetRequest, *, status: str, import_status: str
) -> dict[str, object]:
    now = datetime.now(UTC).isoformat()
    enrichment_format = request.enrichments[0].format
    assert enrichment_format is not None
    definitions = [
        {
            "id": "enrichment_c5",
            "object": "webset_enrichment",
            "status": "completed" if status == "idle" else "pending",
            "websetId": "webset_c5",
            "title": request.enrichments[0].description,
            "description": request.enrichments[0].description,
            "format": enrichment_format.value,
            "options": None,
            "instructions": None,
            "metadata": request.enrichments[0].metadata,
            "createdAt": now,
            "updatedAt": now,
        }
    ]
    imported = {
        "id": request.imports[0].id,
        "object": "import",
        "status": import_status,
        "format": "csv",
        "entity": {"type": "person"},
        "title": "C5 selected contact import",
        "count": 1,
        "metadata": {},
        "failedReason": None,
        "failedAt": None,
        "failedMessage": None,
        "createdAt": now,
        "updatedAt": now,
    }
    return {
        "id": "webset_c5",
        "object": "webset",
        "status": status,
        "externalId": request.external_id,
        "title": request.title,
        "searches": [],
        "imports": [imported],
        "enrichments": definitions,
        "monitors": [],
        "excludes": [],
        "metadata": request.metadata,
        "dashboardUrl": "https://websets.exa.ai/websets/webset_c5",
        "createdAt": now,
        "updatedAt": now,
    }


def _exchange(payload: dict[str, object], status_code: int) -> ExaWebsetExchange:
    body = json.dumps(payload, sort_keys=True).encode()
    return ExaWebsetExchange(
        status_code=status_code,
        request_id="request_c5",
        response_body=body,
        webset=ExaWebset.model_validate(payload),
    )


class _Transport:
    def __init__(self, profile_url: str) -> None:
        self.profile_url = profile_url
        self.import_calls = 0
        self.upload_calls = 0
        self.create_calls = 0
        self.lookup_calls = 0
        self.poll_calls = 0
        self.item_calls = 0
        self.request: ExaCreateWebsetRequest | None = None

    async def create_import(self, request: ExaCreateImportRequest) -> ExaImportExchange:
        self.import_calls += 1
        return ExaImportExchange(
            status_code=201,
            request_id="request_c5_import",
            response=ExaCreateImportResponse.model_validate(_import_payload(request)),
        )

    async def upload_import_csv(self, *, upload_url: SecretStr, content: bytes) -> None:
        self.upload_calls += 1
        assert "credential=redacted" in upload_url.get_secret_value()
        assert self.profile_url.encode() in content

    async def create_webset(self, request: ExaCreateWebsetRequest) -> ExaWebsetExchange:
        self.create_calls += 1
        self.request = request
        return _exchange(
            _webset_payload(request, status="running", import_status="processing"), 201
        )

    async def get_webset(self, webset_id_or_external_id: str) -> ExaWebsetExchange:
        self.lookup_calls += 1
        assert self.request is not None
        assert webset_id_or_external_id in {self.request.external_id, "webset_c5"}
        return _exchange(
            _webset_payload(self.request, status="running", import_status="processing"), 200
        )

    async def poll_webset(self, webset_id: str) -> ExaWebsetExchange:
        self.poll_calls += 1
        assert webset_id == "webset_c5" and self.request is not None
        return _exchange(
            _webset_payload(self.request, status="idle", import_status="completed"), 200
        )

    async def list_items(
        self, webset_id: str, *, cursor: str | None = None, limit: int = 100
    ) -> ExaItemPageExchange:
        self.item_calls += 1
        assert webset_id == "webset_c5" and cursor is None and limit == 100
        now = datetime.now(UTC).isoformat()
        item = {
            "id": "item_c5",
            "object": "webset_item",
            "source": "import",
            "sourceId": "import_c5",
            "sourceEntityId": self.profile_url,
            "scopeId": None,
            "websetId": "webset_c5",
            "properties": {"type": "person", "url": self.profile_url},
            "evaluations": [],
            "enrichments": [
                {
                    "object": "enrichment_result",
                    "status": "completed",
                    "format": "email",
                    "result": [_EMAIL],
                    "reasoning": "Professional source matched the exact imported profile.",
                    "references": [
                        {
                            "title": "Professional profile",
                            "snippet": "Alex Rivera at the selected practice",
                            "url": self.profile_url,
                        }
                    ],
                    "enrichmentId": "enrichment_c5",
                }
            ],
            "createdAt": now,
            "updatedAt": now,
        }
        body = json.dumps({"data": [item], "hasMore": False, "nextCursor": None}).encode()
        return ExaItemPageExchange(
            status_code=200,
            request_id="request_c5_items",
            response_body=body,
            page=json.loads(body),
        )


async def _channel_intent(
    conn: AsyncConnection,
    storage: FsStorage,
    *,
    suffix: str,
    directive_reveals_allowed: bool = True,
) -> tuple[ContactResearchIntent, ContactResearchPolicy, ClaimId]:
    base = await _seed(
        conn,
        storage,
        suffix=f"c5-{suffix}",
        contact_reveals_allowed=directive_reveals_allowed,
    )
    await load_core_pack(conn)
    await load_compliance_pack(conn)
    await load_client_knowledge_pack(conn)
    await seed_source_manifests(conn)
    jurisdiction = stamp_reuse(
        Claim(
            entity_id=base.intent.contact_entity_id,
            entity_type=EntityType.CONTACT,
            field_key="contact.jurisdiction",
            value_json={
                "regime": Jurisdiction.US_STATE.value,
                "region": "US",
                "confidence": 1.0,
                "derived_from": "exact_region",
                "jurisdiction_unknown": False,
            },
            source_tier=1,
            extraction_method=ExtractionMethod.HUMAN,
            confidence=1,
            run_id=RunId(base.intent.project_run_id),
            research_mode=ResearchMode.CONTACT_PROFILING,
            reuse_scope=ReuseScope.TENANT_PRIVATE,
            workspace_id=base.intent.workspace_id,
        ),
        workspace_id=base.intent.workspace_id,
    )
    await insert_claim(conn, jurisdiction)
    policy = ContactResearchPolicy(
        contact_reveals_enabled=True,
        channel_reveal_source_plan=("exa_websets",),
        channel_validation_source_plan=("channel_validator",),
        exa_websets_contract_ref="exa-websets-v0-entitled-canary-accepted",
        channel_validation_contract_ref="channel-validator-v1-accepted",
        email_reveal_native_unit_cap=7,
        email_reveal_budget_cents=10,
        email_validation_native_unit_cap=1,
        email_validation_budget_cents=1,
        email_identity_promotion_allowed=True,
    )
    target = base.intent.selection.body.targets[0].model_copy(
        update={
            "field_keys": ("core.work_email",),
            "directional_question_ids": (),
            "email": ContactChannelAuthorization(
                channel=ContactChannel.EMAIL,
                allowed=True,
                provider_source_keys=("exa_websets",),
                provider_native_unit_cap=7,
                budget_cap_cents=10,
                validation_source_keys=("channel_validator",),
                validation_native_unit_cap=1,
                validation_budget_cap_cents=1,
                independent_validation_required=True,
            ),
        }
    )
    body = base.intent.selection.body.model_copy(
        update={
            "targets": (target,),
            "policy": policy.pin(),
            "budget_reservation_ref": f"budget:c5:{suffix}",
            "approved_by": "human:c5-test",
            "approved_at": datetime.now(UTC),
        }
    )
    selection = ContactResearchSelection.from_body(body, effective_policy=body.policy)
    account_run_id = (
        await conn.execute(
            text(
                "SELECT account_run_id FROM contact_research_selection "
                "WHERE workspace_id=:workspace_id AND id=:selection_id"
            ),
            {
                "workspace_id": base.intent.workspace_id,
                "selection_id": base.intent.selection_id,
            },
        )
    ).scalar_one()
    selection = await store_contact_research_selection(
        conn,
        selection,
        account_run_id=account_run_id,
        predecessor_id=base.intent.selection_id,
        approval=ContactResearchSelectionApprovalAuthority(
            kind=ContactResearchSelectionApprovalKind.HUMAN_SUCCESSOR,
            operation_id=uuid4(),
            approved_by=body.approved_by,
            action_ref=f"human-action:c5:{suffix}",
            approved_at=body.approved_at,
        ),
    )
    intent = ContactResearchIntent.from_selection(
        selection, contact_entity_id=base.intent.contact_entity_id
    )
    corroborating = Claim(
        entity_id=intent.contact_entity_id,
        entity_type=EntityType.CONTACT,
        field_key="core.work_email",
        # D4-b decision 6: a work-email claim is the address with the verdict that grades it. This
        # independent directory binds the address to the person; it probes no mailbox, so the
        # verdict it can honestly carry is ``unverified``. The corroboration compares addresses.
        value_json={"address": _EMAIL, "status": "unverified"},
        source_url="https://validator.example.invalid/evidence/c5",
        source_key="channel_validator",
        source_tier=1,
        extraction_method=ExtractionMethod.API,
        evidence_span="Independent professional directory binds this email to Alex Rivera.",
        confidence=1,
        run_id=RunId(intent.project_run_id),
        research_mode=ResearchMode.CONTACT_PROFILING,
        identity_binding=IdentityBinding.STRONG,
        use_class=UseClass.PROFESSIONAL_PUBLIC,
        provenance_kind=ClaimProvenanceKind.PROVIDER_RETURNED,
        verification_status=VerificationStatus.VERIFIED,
        reuse_scope=ReuseScope.TENANT_PRIVATE,
        workspace_id=intent.workspace_id,
    )
    claim_id = await insert_claim(conn, corroborating)
    return intent, policy, claim_id


def test_c5_disabled_or_wrong_channel_causes_zero_provider_traffic(tmp_path: Path) -> None:
    async def scenario() -> None:
        storage = FsStorage(tmp_path / "artifacts")
        async with rollback_conn() as conn:
            base = await _seed(conn, storage, suffix="c5-disabled")
            factory = _TrackedConnFactory(conn)
            transport = _Transport("https://www.linkedin.com/in/never-called")
            validator = _Validator(
                base.intent.selection.body.targets[0].strong_identity_claim_ids[0]
            )
            coordinator = ExaContactChannelCoordinator(
                transport=transport,
                validator=validator,
                use_gate=_UseGate(),
                pre_spend_gate=_PassGate(),
                storage=storage,
                conn_factory=factory,
            )
            with pytest.raises(ContactChannelEligibilityError, match="disables contact reveals"):
                await coordinator.start(
                    intent=base.intent,
                    effective_policy=base.policy,
                    channel=ContactChannel.EMAIL,
                    observation_window="c5-disabled",
                )
            assert transport.import_calls == transport.create_calls == validator.calls == 0

        async with rollback_conn() as conn:
            intent, policy, claim_id = await _channel_intent(
                conn,
                storage,
                suffix="directive-denied",
                directive_reveals_allowed=False,
            )
            contact = await get_contact(conn, intent.contact_entity_id)
            assert contact is not None and contact.linkedin_url is not None
            transport = _Transport(contact.linkedin_url)
            validator = _Validator(claim_id)
            coordinator = ExaContactChannelCoordinator(
                transport=transport,
                validator=validator,
                use_gate=_UseGate(),
                pre_spend_gate=_PassGate(),
                storage=storage,
                conn_factory=_TrackedConnFactory(conn),
            )
            with pytest.raises(
                ContactChannelEligibilityError,
                match="directive does not authorize selected-contact reveals",
            ):
                await coordinator.start(
                    intent=intent,
                    effective_policy=policy.pin(),
                    channel=ContactChannel.EMAIL,
                    observation_window="c5-directive-denied",
                )
            assert transport.import_calls == transport.create_calls == validator.calls == 0

        async with rollback_conn() as conn:
            intent, policy, claim_id = await _channel_intent(conn, storage, suffix="wrong-channel")
            factory = _TrackedConnFactory(conn)
            transport = _Transport("https://www.linkedin.com/in/never-called")
            validator = _Validator(claim_id)
            coordinator = ExaContactChannelCoordinator(
                transport=transport,
                validator=validator,
                use_gate=_UseGate(),
                pre_spend_gate=_PassGate(),
                storage=storage,
                conn_factory=factory,
            )
            with pytest.raises(ContactChannelEligibilityError, match="does not authorize phone"):
                await coordinator.start(
                    intent=intent,
                    effective_policy=policy.pin(),
                    channel=ContactChannel.PHONE,
                    observation_window="c5-wrong-channel",
                )
            unselected = intent.model_copy(update={"contact_entity_id": new_entity_id()})
            with pytest.raises(ContactChannelEligibilityError, match="absent from the immutable"):
                await coordinator.start(
                    intent=unselected,
                    effective_policy=policy.pin(),
                    channel=ContactChannel.EMAIL,
                    observation_window="c5-unselected",
                )
            assert transport.import_calls == transport.create_calls == validator.calls == 0

    run_async(scenario())


@pytest.mark.parametrize("authority", ["forged", "predecessor"])
def test_c5_requires_the_database_current_selection_before_provider_traffic(
    tmp_path: Path,
    authority: str,
) -> None:
    async def scenario() -> None:
        storage = FsStorage(tmp_path / "artifacts")
        async with rollback_conn() as conn:
            intent, policy, claim_id = await _channel_intent(
                conn, storage, suffix=f"selection-{authority}"
            )
            contact = await get_contact(conn, intent.contact_entity_id)
            assert contact is not None and contact.linkedin_url is not None
            transport = _Transport(contact.linkedin_url)
            validator = _Validator(claim_id)
            coordinator = ExaContactChannelCoordinator(
                transport=transport,
                validator=validator,
                use_gate=_UseGate(),
                pre_spend_gate=_PassGate(),
                storage=storage,
                conn_factory=_TrackedConnFactory(conn),
            )
            if authority == "forged":
                invalid_selection_id = new_contact_research_selection_id()
            else:
                invalid_selection_id = (
                    await conn.execute(
                        text(
                            "SELECT predecessor_id FROM contact_research_selection "
                            "WHERE id=:selection_id"
                        ),
                        {"selection_id": intent.selection_id},
                    )
                ).scalar_one()
            invalid_intent = intent.model_copy(update={"selection_id": invalid_selection_id})

            with pytest.raises(
                (ContactChannelEligibilityError, ContactResearchSelectionNotFound),
            ):
                await coordinator.start(
                    intent=invalid_intent,
                    effective_policy=policy.pin(),
                    channel=ContactChannel.EMAIL,
                    observation_window=f"c5-selection-{authority}",
                )
            assert transport.import_calls == transport.create_calls == validator.calls == 0

    run_async(scenario())


def test_c5_email_validates_promotes_replays_and_objection_suppresses(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        storage = FsStorage(tmp_path / "artifacts")
        async with rollback_conn() as conn:
            intent, policy, claim_id = await _channel_intent(conn, storage, suffix="success")
            contact = await get_contact(conn, intent.contact_entity_id)
            assert contact is not None and contact.linkedin_url is not None
            factory = _TrackedConnFactory(conn)
            transport = _Transport(contact.linkedin_url)
            validator = _Validator(claim_id)
            coordinator = ExaContactChannelCoordinator(
                transport=transport,
                validator=validator,
                use_gate=_UseGate(),
                pre_spend_gate=_PassGate(),
                storage=storage,
                conn_factory=factory,
                poll_after_seconds=1,
            )
            spent_before = Decimal(
                (
                    await conn.execute(
                        text("SELECT spent_cents FROM project_run WHERE id=:run_id"),
                        {"run_id": intent.project_run_id},
                    )
                ).scalar_one()
            )
            started = await coordinator.start(
                intent=intent,
                effective_policy=policy.pin(),
                channel=ContactChannel.EMAIL,
                observation_window="c5-success",
            )
            assert started.outcome is ContactChannelEnrichmentOutcome.CREATED
            before = await get_contact(conn, intent.contact_entity_id)
            assert before is not None and before.verified_email is None
            completed = await coordinator.drive_once(
                workspace_id=intent.workspace_id,
                operation_id=started.operation.operation_id,
                effective_policy=policy.pin(),
            )
            assert completed.outcome is ContactChannelEnrichmentOutcome.SUCCEEDED
            assert completed.operation.validation is not None
            assert completed.operation.validation.delivery_eligible
            assert completed.operation.acquisition_units_charged == Decimal(7)
            assert completed.operation.validation_units_charged == Decimal(1)
            direct_authority = await list_contact_channel_operations_for_selection(
                conn,
                workspace_id=intent.workspace_id,
                project_run_id=intent.project_run_id,
                account_id=intent.account_entity_id,
                contact_id=intent.contact_entity_id,
                selection_id=intent.selection_id,
                selection_sha256=intent.selection_sha256,
            )
            assert len(direct_authority) == 1
            assert direct_authority[0].authorization_ref == (
                f"contact-channel-operation:{completed.operation.operation_id}"
            )
            spent_after = Decimal(
                (
                    await conn.execute(
                        text("SELECT spent_cents FROM project_run WHERE id=:run_id"),
                        {"run_id": intent.project_run_id},
                    )
                ).scalar_one()
            )
            assert spent_after - spent_before == (
                completed.operation.acquisition_cost_cents_charged
                + completed.operation.validation_cost_cents_charged
            )
            promoted = await get_contact(conn, intent.contact_entity_id)
            assert promoted is not None and promoted.verified_email == _EMAIL
            # FI-2 P2: the observed channel claim carries the project run as its run_id, and that
            # run is registered so the project lens can back-join it.
            assert completed.operation.observed_claim_id is not None
            await assert_written_claims_are_attributable(
                conn,
                intent.project_run_id,
                kind="enrichment",
                workspace_id=intent.workspace_id,
                project_id=intent.project_id,
                project_run_id=intent.project_run_id,
            )

            replay = await coordinator.start(
                intent=intent,
                effective_policy=policy.pin(),
                channel=ContactChannel.EMAIL,
                observation_window="c5-success",
            )
            assert replay.outcome is ContactChannelEnrichmentOutcome.REPLAYED
            fresh_window_reuse = await coordinator.start(
                intent=intent,
                effective_policy=policy.pin(),
                channel=ContactChannel.EMAIL,
                observation_window="c5-success-fresh-window",
            )
            assert fresh_window_reuse.outcome is ContactChannelEnrichmentOutcome.REPLAYED
            exact_selection_authority = await list_contact_channel_operations_for_selection(
                conn,
                workspace_id=intent.workspace_id,
                project_run_id=intent.project_run_id,
                account_id=intent.account_entity_id,
                contact_id=intent.contact_entity_id,
                selection_id=intent.selection_id,
                selection_sha256=intent.selection_sha256,
            )
            assert len(exact_selection_authority) == 1
            assert exact_selection_authority[0].reused
            assert exact_selection_authority[0].authorization_ref.startswith(
                "contact-channel-reuse:"
            )
            assert (
                await list_contact_channel_operations_for_selection(
                    conn,
                    workspace_id=intent.workspace_id,
                    project_run_id=intent.project_run_id,
                    account_id=intent.account_entity_id,
                    contact_id=intent.contact_entity_id,
                    selection_id=new_contact_research_selection_id(),
                    selection_sha256=intent.selection_sha256,
                )
                == ()
            )
            assert transport.import_calls == transport.create_calls == transport.poll_calls == 1
            assert validator.calls == 1
            spent_after_replay = Decimal(
                (
                    await conn.execute(
                        text("SELECT spent_cents FROM project_run WHERE id=:run_id"),
                        {"run_id": intent.project_run_id},
                    )
                ).scalar_one()
            )
            assert spent_after_replay == spent_after
            assert (
                await conn.execute(
                    text(
                        "SELECT count(*) FROM contact_channel_reuse "
                        "WHERE source_operation_id=:operation_id"
                    ),
                    {"operation_id": completed.operation.operation_id},
                )
            ).scalar_one() == 2

            assert await contact_channel_is_usable(
                conn,
                workspace_id=intent.workspace_id,
                contact_id=intent.contact_entity_id,
                channel=ContactChannel.EMAIL,
                now=datetime.now(UTC),
            )
            channel_artifact_keys = tuple(
                (
                    await conn.execute(
                        text(
                            "SELECT artifact_key FROM discovery_artifact_subject "
                            "WHERE workspace_id=:workspace_id AND subject_kind='contact' "
                            "AND subject_entity_id=:contact_id "
                            "AND reference_id=:operation_id ORDER BY artifact_key"
                        ),
                        {
                            "workspace_id": intent.workspace_id,
                            "contact_id": intent.contact_entity_id,
                            "operation_id": str(completed.operation.operation_id),
                        },
                    )
                ).scalars()
            )
            assert len(channel_artifact_keys) >= 7
            assert all([await storage.exists(key) for key in channel_artifact_keys])
            rights = DataSubjectRightsImpl(
                intent.workspace_id,
                conn_factory=factory,
                storage=storage,
                contact_research_stopper=DurableContactResearchPrivacyStopper(),
            )
            objected = await rights.record_objection(intent.contact_entity_id)
            assert objected.tombstoned_claim_ids
            assert not await contact_channel_is_usable(
                conn,
                workspace_id=intent.workspace_id,
                contact_id=intent.contact_entity_id,
                channel=ContactChannel.EMAIL,
                now=datetime.now(UTC),
            )
            assert completed.operation.observation_artifact_key is not None
            assert all([not await storage.exists(key) for key in channel_artifact_keys])
            assert (
                await conn.execute(
                    text(
                        "SELECT count(*) FROM discovery_artifact_subject "
                        "WHERE workspace_id=:workspace_id AND subject_kind='contact' "
                        "AND subject_entity_id=:contact_id AND reference_id=:operation_id "
                        "AND tombstoned_at IS NULL"
                    ),
                    {
                        "workspace_id": intent.workspace_id,
                        "contact_id": intent.contact_entity_id,
                        "operation_id": str(completed.operation.operation_id),
                    },
                )
            ).scalar_one() == 0
            await rights.erase(intent.contact_entity_id)
            erased = await get_contact(conn, intent.contact_entity_id)
            assert erased is not None and erased.verified_email is None

    run_async(scenario())


@pytest.mark.parametrize("stop_kind", ("objection", "erasure"))
def test_c5_privacy_stop_cancels_planned_operation_before_any_provider_call(
    tmp_path: Path,
    stop_kind: str,
) -> None:
    async def scenario() -> None:
        storage = FsStorage(tmp_path / stop_kind / "artifacts")
        async with rollback_conn() as conn:
            intent, policy, claim_id = await _channel_intent(
                conn,
                storage,
                suffix=f"active-{stop_kind}",
            )
            contact = await get_contact(conn, intent.contact_entity_id)
            assert contact is not None and contact.linkedin_url is not None
            factory = _TrackedConnFactory(conn)
            transport = _Transport(contact.linkedin_url)
            coordinator = ExaContactChannelCoordinator(
                transport=transport,
                validator=_Validator(claim_id),
                use_gate=_UseGate(),
                pre_spend_gate=_PassGate(),
                storage=storage,
                conn_factory=factory,
            )
            preflight = await compile_contact_channel_preflight(
                conn,
                intent=intent,
                effective_policy=policy.pin(),
                channel=ContactChannel.EMAIL,
                observation_window=f"c5-active-{stop_kind}",
            )
            operation, created = await coordinator._reserve(preflight)
            assert created
            assert operation.state is ContactChannelOperationState.PLANNED

            rights = DataSubjectRightsImpl(
                intent.workspace_id,
                conn_factory=factory,
                storage=storage,
                contact_research_stopper=DurableContactResearchPrivacyStopper(),
            )
            if stop_kind == "objection":
                await rights.record_objection(intent.contact_entity_id)
            else:
                await rights.erase(intent.contact_entity_id)

            stopped = await get_contact_channel_operation(
                conn,
                workspace_id=intent.workspace_id,
                operation_id=operation.operation_id,
            )
            assert stopped is not None
            assert stopped.state is ContactChannelOperationState.CANCELLED
            assert (
                await conn.execute(
                    text(
                        "SELECT count(*) FROM contact_channel_operation_stop "
                        "WHERE operation_id=:operation_id"
                    ),
                    {"operation_id": operation.operation_id},
                )
            ).scalar_one() == 1
            with pytest.raises(ContactChannelEligibilityError):
                await coordinator.start(
                    intent=intent,
                    effective_policy=policy.pin(),
                    channel=ContactChannel.EMAIL,
                    observation_window=f"c5-active-{stop_kind}",
                )
            assert transport.import_calls == transport.create_calls == transport.poll_calls == 0

    run_async(scenario())


def test_c5_privacy_stop_between_reservation_and_dispatch_causes_zero_provider_calls(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def scenario() -> None:
        storage = FsStorage(tmp_path / "artifacts")
        async with rollback_conn() as conn:
            intent, policy, claim_id = await _channel_intent(
                conn,
                storage,
                suffix="stop-before-submit-claim",
            )
            contact = await get_contact(conn, intent.contact_entity_id)
            assert contact is not None and contact.linkedin_url is not None
            factory = _TrackedConnFactory(conn)
            transport = _Transport(contact.linkedin_url)
            coordinator = ExaContactChannelCoordinator(
                transport=transport,
                validator=_Validator(claim_id),
                use_gate=_UseGate(),
                pre_spend_gate=_PassGate(),
                storage=storage,
                conn_factory=factory,
            )
            original_claim = contact_channel_module.claim_contact_channel_submit

            async def object_then_claim(*args: Any, **kwargs: Any) -> object:
                await DataSubjectRightsImpl(
                    intent.workspace_id,
                    conn_factory=factory,
                    storage=storage,
                    contact_research_stopper=DurableContactResearchPrivacyStopper(),
                ).record_objection(intent.contact_entity_id)
                return await original_claim(*args, **kwargs)

            monkeypatch.setattr(
                contact_channel_module,
                "claim_contact_channel_submit",
                object_then_claim,
            )
            result = await coordinator.start(
                intent=intent,
                effective_policy=policy.pin(),
                channel=ContactChannel.EMAIL,
                observation_window="c5-stop-before-submit-claim",
            )

            assert result.outcome is ContactChannelEnrichmentOutcome.FAILED_TERMINAL
            assert result.operation.state is ContactChannelOperationState.CANCELLED
            assert (
                transport.import_calls
                == transport.upload_calls
                == transport.create_calls
                == transport.lookup_calls
                == transport.poll_calls
                == transport.item_calls
                == 0
            )

    run_async(scenario())


def test_c5_objection_after_acquisition_dispatch_settles_without_channel_resurrection(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def scenario() -> None:
        storage = FsStorage(tmp_path / "artifacts")
        async with rollback_conn() as conn:
            intent, policy, claim_id = await _channel_intent(
                conn, storage, suffix="objection-after-dispatch"
            )
            contact = await get_contact(conn, intent.contact_entity_id)
            assert contact is not None and contact.linkedin_url is not None
            factory = _TrackedConnFactory(conn)
            transport = _Transport(contact.linkedin_url)
            validator = _Validator(claim_id)
            coordinator = ExaContactChannelCoordinator(
                transport=transport,
                validator=validator,
                use_gate=_UseGate(),
                pre_spend_gate=_PassGate(),
                storage=storage,
                conn_factory=factory,
                poll_after_seconds=1,
            )
            started = await coordinator.start(
                intent=intent,
                effective_policy=policy.pin(),
                channel=ContactChannel.EMAIL,
                observation_window="c5-objection-after-dispatch",
            )
            assert started.outcome is ContactChannelEnrichmentOutcome.CREATED
            original_record_active = coordinator._record_active

            async def object_before_person_retention(
                operation: object,
                kind: str,
                body: bytes,
                source_url: str | None,
                request_id: str | None,
                *,
                source_key: str | None = None,
            ) -> object:
                if kind == "person_item":
                    await DataSubjectRightsImpl(
                        intent.workspace_id,
                        conn_factory=factory,
                        storage=storage,
                        contact_research_stopper=DurableContactResearchPrivacyStopper(),
                    ).record_objection(intent.contact_entity_id)
                return await original_record_active(
                    operation,  # type: ignore[arg-type]
                    kind,
                    body,
                    source_url,
                    request_id,
                    source_key=source_key,
                )

            monkeypatch.setattr(
                coordinator,
                "_record_active",
                object_before_person_retention,
            )
            completed = await coordinator.drive_once(
                workspace_id=intent.workspace_id,
                operation_id=started.operation.operation_id,
                effective_policy=policy.pin(),
            )

            assert completed.outcome is ContactChannelEnrichmentOutcome.FAILED_TERMINAL
            assert completed.operation.state is ContactChannelOperationState.CANCELLED
            assert completed.operation.observed_claim_id is None
            assert completed.operation.acquisition_spend_outcome.value == "charged"
            assert validator.calls == 0
            assert (
                await conn.execute(
                    text(
                        "SELECT count(*) FROM contact_channel_artifact "
                        "WHERE operation_id=:operation_id AND artifact_kind='person_item'"
                    ),
                    {"operation_id": completed.operation.operation_id},
                )
            ).scalar_one() == 0
            assert not await contact_channel_is_usable(
                conn,
                workspace_id=intent.workspace_id,
                contact_id=intent.contact_entity_id,
                channel=ContactChannel.EMAIL,
                now=datetime.now(UTC),
            )

    run_async(scenario())


@pytest.mark.parametrize("failure_mode", ["weak", "conflict", "use_denied"])
def test_c5_failed_validation_never_promotes_identity(
    tmp_path: Path,
    *,
    failure_mode: str,
) -> None:
    async def scenario() -> None:
        storage = FsStorage(tmp_path / failure_mode)
        async with rollback_conn() as conn:
            intent, policy, claim_id = await _channel_intent(
                conn,
                storage,
                suffix=failure_mode,
            )
            contact = await get_contact(conn, intent.contact_entity_id)
            assert contact is not None and contact.linkedin_url is not None
            validator = (
                _WeakValidator(claim_id)
                if failure_mode == "weak"
                else _Validator(claim_id, conflict=failure_mode == "conflict")
            )
            coordinator = ExaContactChannelCoordinator(
                transport=_Transport(contact.linkedin_url),
                validator=validator,
                use_gate=_DenyUseGate() if failure_mode == "use_denied" else _UseGate(),
                pre_spend_gate=_PassGate(),
                storage=storage,
                conn_factory=_TrackedConnFactory(conn),
            )
            started = await coordinator.start(
                intent=intent,
                effective_policy=policy.pin(),
                channel=ContactChannel.EMAIL,
                observation_window=f"c5-{failure_mode}",
            )
            completed = await coordinator.drive_once(
                workspace_id=intent.workspace_id,
                operation_id=started.operation.operation_id,
                effective_policy=policy.pin(),
            )
            assert completed.outcome is ContactChannelEnrichmentOutcome.REJECTED
            assert completed.operation.validation is not None
            assert not completed.operation.validation.delivery_eligible
            assert validator.calls == (0 if failure_mode == "use_denied" else 1)
            after = await get_contact(conn, intent.contact_entity_id)
            assert after is not None and after.verified_email is None
            assert not await contact_channel_is_usable(
                conn,
                workspace_id=intent.workspace_id,
                contact_id=intent.contact_entity_id,
                channel=ContactChannel.EMAIL,
                now=datetime.now(UTC),
            )

    run_async(scenario())


def test_c5_observed_claim_link_and_acquisition_settlement_are_atomic(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        storage = FsStorage(tmp_path / "atomic")
        async with rollback_conn() as conn:
            intent, policy, claim_id = await _channel_intent(conn, storage, suffix="atomic")
            contact = await get_contact(conn, intent.contact_entity_id)
            assert contact is not None and contact.linkedin_url is not None
            factory = _TransactionalTrackedConnFactory(conn)
            coordinator = ExaContactChannelCoordinator(
                transport=_Transport(contact.linkedin_url),
                validator=_Validator(claim_id),
                use_gate=_UseGate(),
                pre_spend_gate=_PassGate(),
                storage=storage,
                conn_factory=factory,
                budget=_FailingBudget(),  # type: ignore[arg-type]
            )
            started = await coordinator.start(
                intent=intent,
                effective_policy=policy.pin(),
                channel=ContactChannel.EMAIL,
                observation_window="c5-atomic",
            )
            with pytest.raises(RuntimeError, match="settlement failure"):
                await coordinator.drive_once(
                    workspace_id=intent.workspace_id,
                    operation_id=started.operation.operation_id,
                    effective_policy=policy.pin(),
                )
            row = (
                await conn.execute(
                    text(
                        "SELECT state::text, observed_claim_id, acquisition_units_charged "
                        "FROM contact_channel_operation WHERE id=:operation_id"
                    ),
                    {"operation_id": started.operation.operation_id},
                )
            ).one()
            assert tuple(row) == ("waiting_external", None, Decimal(0))
            detached = (
                await conn.execute(
                    text("SELECT count(*) FROM claim WHERE source_operation_ref=:operation_ref"),
                    {"operation_ref": str(started.operation.operation_id)},
                )
            ).scalar_one()
            assert detached == 0

    run_async(scenario())


def test_c5_validator_crash_is_quarantined_without_second_validation_call(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        storage = FsStorage(tmp_path / "artifacts")
        async with rollback_conn() as conn:
            intent, policy, claim_id = await _channel_intent(conn, storage, suffix="crash")
            contact = await get_contact(conn, intent.contact_entity_id)
            assert contact is not None and contact.linkedin_url is not None
            factory = _TrackedConnFactory(conn)
            transport = _Transport(contact.linkedin_url)
            validator = _CrashingValidator(claim_id)
            coordinator = ExaContactChannelCoordinator(
                transport=transport,
                validator=validator,
                use_gate=_UseGate(),
                pre_spend_gate=_PassGate(),
                storage=storage,
                conn_factory=factory,
                validation_lease_seconds=1,
            )
            started = await coordinator.start(
                intent=intent,
                effective_policy=policy.pin(),
                channel=ContactChannel.EMAIL,
                observation_window="c5-crash",
            )
            with pytest.raises(RuntimeError, match="simulated crash"):
                await coordinator.drive_once(
                    workspace_id=intent.workspace_id,
                    operation_id=started.operation.operation_id,
                    effective_policy=policy.pin(),
                )
            await conn.execute(
                text(
                    "UPDATE contact_channel_operation SET next_poll_at=:expired "
                    "WHERE id=:operation_id"
                ),
                {
                    "operation_id": started.operation.operation_id,
                    "expired": datetime.now(UTC) - timedelta(seconds=1),
                },
            )
            replay = await coordinator.drive_once(
                workspace_id=intent.workspace_id,
                operation_id=started.operation.operation_id,
                effective_policy=policy.pin(),
            )
            assert replay.outcome is ContactChannelEnrichmentOutcome.SPEND_OUTCOME_UNKNOWN
            assert validator.calls == 1
            quarantined_contact = await get_contact(conn, intent.contact_entity_id)
            assert quarantined_contact is not None
            assert quarantined_contact.verified_email is None

    run_async(scenario())
