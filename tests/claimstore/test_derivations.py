"""C7.2 claimstore support-edge validation and database invariants."""

from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from clue_core import (
    Claim,
    ClaimFlavor,
    ClaimId,
    EntailmentReasonCode,
    EntailmentVerdictKind,
    EntityId,
    EntityType,
    ExtractionMethod,
    IdentityBinding,
    ResearchMode,
    ResearchSubjectRef,
    ResearchSupportRef,
    ResearchSupportRole,
    ReuseScope,
    UseClass,
    VerificationStatus,
    new_entity_id,
    new_operation_id,
    new_run_id,
)
from clue_research.claimstore import (
    DerivationStore,
    DerivationValidationError,
    WorkspaceScope,
    insert_claim,
    support_set_sha256,
)
from clue_spine import create_brand, create_product
from tests._workspace import seed_workspace

from .conftest import rollback_conn, run_async

pytestmark = pytest.mark.usefixtures("require_claimstore_db")

WORKSPACE = "c7-claimstore"


def _support(
    entity_id: EntityId,
    *,
    status: VerificationStatus = VerificationStatus.VERIFIED,
) -> Claim:
    return Claim(
        entity_id=entity_id,
        entity_type=EntityType.ACCOUNT,
        field_key="account.recent_funding",
        value_json={"amount_usd": 10_000_000},
        source_tier=1,
        extraction_method=ExtractionMethod.API,
        source_url="https://registry.example/funding",
        confidence=0.8,
        run_id=new_run_id(),
        research_mode=ResearchMode.ACCOUNT_PROFILING,
        verification_status=status,
    )


def _derived(entity_id: EntityId) -> Claim:
    return Claim(
        entity_id=entity_id,
        entity_type=EntityType.ACCOUNT,
        field_key="account.strategic_moves",
        value_json="funding increases transformation capacity",
        source_tier=4,
        extraction_method=ExtractionMethod.LLM_SYNTHESIS,
        confidence=0.7,
        run_id=new_run_id(),
        research_mode=ResearchMode.ACCOUNT_PROFILING,
        claim_flavor=ClaimFlavor.DERIVED,
    )


def _target(entity_id: EntityId) -> ResearchSubjectRef:
    return ResearchSubjectRef(
        entity_id=entity_id,
        entity_type=EntityType.ACCOUNT,
        canonical_entity_version=1,
    )


def _ref(
    claim_id: ClaimId,
    *,
    ordinal: int = 0,
    role: ResearchSupportRole = ResearchSupportRole.DIRECT_EVIDENCE,
) -> ResearchSupportRef:
    return ResearchSupportRef(
        claim_id=claim_id,
        role=role,
        ordinal=ordinal,
    )


def test_support_hash_is_order_role_and_required_sensitive() -> None:
    first = _ref(_support(new_entity_id()).id)
    second = _ref(
        _support(new_entity_id()).id,
        ordinal=1,
        role=ResearchSupportRole.CORROBORATION,
    )
    baseline = support_set_sha256((first, second))
    assert baseline == support_set_sha256((first, second))
    assert baseline != support_set_sha256(
        (
            first,
            second.model_copy(update={"role": ResearchSupportRole.ACCOUNT_SIGNAL}),
        )
    )
    assert baseline != support_set_sha256((first, second.model_copy(update={"required": False})))


def test_derivation_database_enums_match_core_and_verdict_has_no_rationale() -> None:
    async def _run() -> None:
        async with rollback_conn() as conn:
            rows = (
                await conn.execute(
                    text(
                        """
                        SELECT t.typname, e.enumlabel
                        FROM pg_type t
                        JOIN pg_enum e ON e.enumtypid = t.oid
                        WHERE t.typname IN (
                            'research_support_role',
                            'entailment_verdict_kind',
                            'entailment_reason_code'
                        )
                        """
                    )
                )
            ).all()
            by_type: dict[str, set[str]] = {}
            for type_name, label in rows:
                by_type.setdefault(str(type_name), set()).add(str(label))
            assert by_type["research_support_role"] == {role.value for role in ResearchSupportRole}
            assert by_type["entailment_verdict_kind"] == {
                verdict.value for verdict in EntailmentVerdictKind
            }
            assert by_type["entailment_reason_code"] == {
                reason.value for reason in EntailmentReasonCode
            }
            columns = set(
                (
                    await conn.execute(
                        text(
                            "SELECT column_name FROM information_schema.columns "
                            "WHERE table_name = 'entailment_verdict'"
                        )
                    )
                ).scalars()
            )
            assert "rationale" not in columns

    run_async(_run())


def test_validation_rejects_missing_rejected_wrong_subject_and_duplicate() -> None:
    async def _run() -> None:
        async with rollback_conn() as conn:
            await seed_workspace(conn, WORKSPACE)
            entity_id = new_entity_id()
            derived = _derived(entity_id)
            store = DerivationStore()
            scope = WorkspaceScope.for_workspace(WORKSPACE)

            with pytest.raises(DerivationValidationError, match="missing"):
                await store.validate(
                    conn,
                    derived,
                    _target(entity_id),
                    (_ref(_support(entity_id).id),),
                    workspace_id=WORKSPACE,
                    scope=scope,
                )

            rejected = _support(entity_id, status=VerificationStatus.REJECTED)
            await insert_claim(conn, rejected)
            with pytest.raises(DerivationValidationError, match="not eligible"):
                await store.validate(
                    conn,
                    derived,
                    _target(entity_id),
                    (_ref(rejected.id),),
                    workspace_id=WORKSPACE,
                    scope=scope,
                )

            other = _support(new_entity_id())
            await insert_claim(conn, other)
            with pytest.raises(DerivationValidationError, match="cross-subject"):
                await store.validate(
                    conn,
                    derived,
                    _target(entity_id),
                    (_ref(other.id),),
                    workspace_id=WORKSPACE,
                    scope=scope,
                )

            valid = _support(entity_id)
            await insert_claim(conn, valid)
            duplicate = _ref(valid.id, ordinal=1)
            with pytest.raises(DerivationValidationError, match="duplicate"):
                await store.validate(
                    conn,
                    derived,
                    _target(entity_id),
                    (_ref(valid.id), duplicate),
                    workspace_id=WORKSPACE,
                    scope=scope,
                )
            with pytest.raises(DerivationValidationError, match="employer_context"):
                await store.validate(
                    conn,
                    derived,
                    _target(entity_id),
                    (
                        _ref(
                            valid.id,
                            role=ResearchSupportRole.EMPLOYER_CONTEXT,
                        ),
                    ),
                    workspace_id=WORKSPACE,
                    scope=scope,
                )

    run_async(_run())


def test_validation_enforces_private_product_and_contact_binding_scope() -> None:
    async def _run() -> None:
        async with rollback_conn() as conn:
            await seed_workspace(conn, WORKSPACE)
            entity_id = new_entity_id()
            brand = await create_brand(conn, workspace_id=WORKSPACE, name="C7 brand")
            product_a = await create_product(
                conn,
                brand_id=brand.brand_id,
                workspace_id=WORKSPACE,
                name="Product A",
            )
            product_b = await create_product(
                conn,
                brand_id=brand.brand_id,
                workspace_id=WORKSPACE,
                name="Product B",
            )
            product_support = Claim(
                entity_id=entity_id,
                entity_type=EntityType.ACCOUNT,
                field_key="account.recent_funding",
                value_json={"amount_usd": 10_000_000},
                source_tier=1,
                extraction_method=ExtractionMethod.API,
                source_url="https://registry.example/funding",
                confidence=0.8,
                run_id=new_run_id(),
                research_mode=ResearchMode.ACCOUNT_PROFILING,
                verification_status=VerificationStatus.VERIFIED,
                reuse_scope=ReuseScope.TENANT_PRIVATE,
                workspace_id=WORKSPACE,
                product_id=product_a.product_id,
            )
            await insert_claim(conn, product_support)
            product_derived = Claim(
                entity_id=entity_id,
                entity_type=EntityType.ACCOUNT,
                field_key="account.recent_funding",
                value_json="product-scoped interpretation",
                source_tier=4,
                extraction_method=ExtractionMethod.LLM_SYNTHESIS,
                confidence=0.7,
                run_id=new_run_id(),
                research_mode=ResearchMode.ACCOUNT_PROFILING,
                claim_flavor=ClaimFlavor.DERIVED,
                reuse_scope=ReuseScope.TENANT_PRIVATE,
                workspace_id=WORKSPACE,
                product_id=product_b.product_id,
            )
            with pytest.raises(DerivationValidationError, match="product mismatch"):
                await DerivationStore().validate(
                    conn,
                    product_derived,
                    _target(entity_id),
                    (_ref(product_support.id),),
                    workspace_id=WORKSPACE,
                    scope=WorkspaceScope.for_workspace(WORKSPACE),
                )

            public_derived = _derived(entity_id)
            with pytest.raises(DerivationValidationError, match="public derivation"):
                await DerivationStore().validate(
                    conn,
                    public_derived,
                    _target(entity_id),
                    (_ref(product_support.id),),
                    workspace_id=WORKSPACE,
                    scope=WorkspaceScope.for_workspace(WORKSPACE),
                )

            await seed_workspace(conn, "c7-foreign-workspace")
            foreign_support = product_support.model_copy(
                update={
                    "id": _support(entity_id).id,
                    "workspace_id": "c7-foreign-workspace",
                    "product_id": None,
                }
            )
            await insert_claim(conn, foreign_support)
            private_derived = _derived(entity_id).model_copy(
                update={
                    "reuse_scope": ReuseScope.TENANT_PRIVATE,
                    "workspace_id": WORKSPACE,
                }
            )
            with pytest.raises(DerivationValidationError, match="missing"):
                await DerivationStore().validate(
                    conn,
                    private_derived,
                    _target(entity_id),
                    (_ref(foreign_support.id),),
                    workspace_id=WORKSPACE,
                    scope=WorkspaceScope.for_workspace(WORKSPACE),
                )

            contact_id = new_entity_id()
            weak_support = Claim(
                entity_id=contact_id,
                entity_type=EntityType.CONTACT,
                field_key="contact.facet.recent_post",
                value_json="same-name search result",
                source_url="https://social.example/wrong-person",
                source_tier=2,
                extraction_method=ExtractionMethod.SCRAPE,
                confidence=0.5,
                run_id=new_run_id(),
                research_mode=ResearchMode.CONTACT_PROFILING,
                identity_binding=IdentityBinding.WEAK,
                use_class=UseClass.PROFESSIONAL_PUBLIC,
                reuse_scope=ReuseScope.TENANT_PRIVATE,
                workspace_id=WORKSPACE,
            )
            await insert_claim(conn, weak_support)
            contact_derived = Claim(
                entity_id=contact_id,
                entity_type=EntityType.CONTACT,
                field_key="contact.facet.recent_post",
                value_json="personalized interpretation",
                source_tier=4,
                extraction_method=ExtractionMethod.LLM_SYNTHESIS,
                confidence=0.5,
                run_id=new_run_id(),
                research_mode=ResearchMode.CONTACT_PROFILING,
                identity_binding=IdentityBinding.STRONG,
                use_class=UseClass.PROFESSIONAL_PUBLIC,
                claim_flavor=ClaimFlavor.DERIVED,
                reuse_scope=ReuseScope.TENANT_PRIVATE,
                workspace_id=WORKSPACE,
            )
            with pytest.raises(DerivationValidationError, match="strongly identity-bound"):
                await DerivationStore().validate(
                    conn,
                    contact_derived,
                    ResearchSubjectRef(
                        entity_id=contact_id,
                        entity_type=EntityType.CONTACT,
                        canonical_entity_version=1,
                        parent_account_id=new_entity_id(),
                    ),
                    (_ref(weak_support.id),),
                    workspace_id=WORKSPACE,
                    scope=WorkspaceScope.for_workspace(WORKSPACE),
                )

    run_async(_run())


def test_database_rejects_indirect_cycle_and_edge_mutation() -> None:
    async def _run() -> None:
        async with rollback_conn() as conn:
            await seed_workspace(conn, WORKSPACE)
            entity_id = new_entity_id()
            direct = _support(entity_id)
            derived_a = _derived(entity_id)
            derived_b = _derived(entity_id)
            await insert_claim(conn, direct)
            await insert_claim(conn, derived_a)
            await insert_claim(conn, derived_b)

            async def edge(
                derived_id: ClaimId,
                support_id: ClaimId,
                ordinal: int,
            ) -> None:
                await conn.execute(
                    text(
                        """
                        INSERT INTO claim_derivation
                            (workspace_id, derived_claim_id, supporting_claim_id, support_role,
                             ordinal, operation_id)
                        VALUES (:workspace, :derived, :support, 'direct_evidence', :ordinal, :op)
                        """
                    ),
                    {
                        "workspace": WORKSPACE,
                        "derived": derived_id,
                        "support": support_id,
                        "ordinal": ordinal,
                        "op": new_operation_id(),
                    },
                )

            await edge(derived_a.id, direct.id, 0)
            await edge(derived_b.id, derived_a.id, 0)
            with pytest.raises(DBAPIError, match="cycle"):
                async with conn.begin_nested():
                    await edge(derived_a.id, derived_b.id, 1)

            with pytest.raises(DBAPIError, match="append-only"):
                async with conn.begin_nested():
                    await conn.execute(
                        text(
                            "UPDATE claim_derivation SET support_required = false "
                            "WHERE derived_claim_id = :derived"
                        ),
                        {"derived": derived_a.id},
                    )
            with pytest.raises(DBAPIError, match="append-only"):
                async with conn.begin_nested():
                    await conn.execute(
                        text("DELETE FROM claim_derivation WHERE derived_claim_id = :derived"),
                        {"derived": derived_a.id},
                    )

            orphan = _derived(entity_id).model_copy(
                update={"verification_status": VerificationStatus.VERIFIED}
            )
            with pytest.raises(DBAPIError, match="requires at least one support edge"):
                async with conn.begin_nested():
                    await insert_claim(conn, orphan)
                    await conn.execute(text("SET CONSTRAINTS derived_claim_has_lineage IMMEDIATE"))

    run_async(_run())
