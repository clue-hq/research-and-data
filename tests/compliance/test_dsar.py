"""M10.5 — DSAR / erasure (tombstone) + retention sweep (Doc D §4): tests, one per AC.

Pure tests (no DB) cover the tombstone shape, the erasure scope, the migration CHECK drift guard,
and the seam conformance; DB-gated tests cover the four rights and the sweeps against a real
migrated schema: erase excludes from ``current_value`` (append-only audit preserved), scoped erase,
objection blocks hooks + re-suppresses, retention age-out, access export, and rectify. DB tests
``pytest.skip`` without a reachable database (``make check`` stays green without one).
"""

from __future__ import annotations

import importlib.util
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_core import (
    AccountStatus,
    AgeOutCandidate,
    Claim,
    ClaimFlavor,
    ClaimId,
    EntityId,
    EntityType,
    ExtractionMethod,
    FieldKey,
    FreshnessState,
    IdentityBinding,
    ReResearchCandidate,
    ResearchMode,
    ReuseScope,
    Staleness,
    UseClass,
    UtcDatetime,
    VerificationStatus,
    new_operation_id,
    new_run_id,
)
from clue_research.claimstore import (
    ALL_WORKSPACES,
    SOURCE_CLIENT_INTERVIEW_JUDGED,
    DerivationDependencyResolver,
    DerivationDependencyState,
    WorkspaceScope,
    claims_by_ids,
    claims_for,
    current_value,
    current_values,
    entailment_judgment_id,
    faithfulness_redaction_subject_ids,
    insert_claim,
    provenance_index,
)
from clue_research.compliance import (
    DataSubjectRights,
    DataSubjectRightsImpl,
    ErasureScope,
    RetentionSweep,
    TombstoneReason,
    build_tombstone,
)
from clue_research.identity import insert_account_entity, insert_contact_entity, stamp_reuse
from tests._workspace import seed_workspace

from .conftest import rollback_conn, run_async

_CLIENT = "client-dsar"
_FACET = "contact.facet.test_hook"
_PRO = UseClass.PROFESSIONAL_PUBLIC
_SENSITIVE = UseClass.SENSITIVE
_SCOPE = WorkspaceScope.for_workspace(_CLIENT)


# --- a minimal Freshness stub (the M9.5 engine is injected as the core.Freshness seam) --------


class _StubFreshness:
    """Returns preset age-out candidates — stands in for the M9.5 ``FreshnessImpl`` so the retention
    sweep is exercised without importing ``verification`` (the independence contract)."""

    def __init__(self, candidates: tuple[AgeOutCandidate, ...]) -> None:
        self._candidates = candidates

    def evaluate(
        self, claim: Claim, *, now: UtcDatetime, ttl: timedelta | None = None
    ) -> Staleness:  # pragma: no cover — not used by the sweep
        raise NotImplementedError

    async def due_for_refresh(
        self,
        *,
        entity_ids: tuple[EntityId, ...] | None = None,
        field_keys: tuple[FieldKey, ...] | None = None,
    ) -> tuple[ReResearchCandidate, ...]:
        return ()

    async def due_for_age_out(
        self,
        *,
        entity_ids: tuple[EntityId, ...] | None = None,
        field_keys: tuple[FieldKey, ...] | None = None,
    ) -> tuple[AgeOutCandidate, ...]:
        return self._candidates


# --- pure tests -------------------------------------------------------------


def test_build_tombstone_facet_is_rejected_and_weak() -> None:
    """A facet tombstone is REJECTED (merge-ineligible), WEAK-bound, HUMAN, tier-1, redacted, and
    inherits the target's field/entity/use_class/tenancy."""
    target = _facet_claim(_eid("aa"), use_class=_PRO)
    target = target.model_copy(update={"reuse_scope": target.reuse_scope, "workspace_id": _CLIENT})
    target = stamp_reuse(target, workspace_id=_CLIENT)
    tomb = build_tombstone(target, run_id=new_run_id())
    assert tomb.verification_status.value == "rejected"
    assert tomb.identity_binding is IdentityBinding.WEAK
    assert tomb.extraction_method is ExtractionMethod.HUMAN
    assert tomb.source_tier == 1
    assert tomb.field_key == target.field_key
    assert tomb.entity_id == target.entity_id
    assert tomb.use_class is _PRO  # copied (facet requires governance provenance)
    assert tomb.value_json == {"__erased__": True}
    assert tomb.workspace_id == _CLIENT
    assert not tomb.is_promotable  # WEAK contact claim is structurally non-promotable


def test_build_tombstone_non_facet_keeps_none_binding() -> None:
    """A plain contact.* tombstone (no governance requirement) is still REJECTED, no binding."""
    target = stamp_reuse(
        Claim(
            entity_id=_eid("bb"),
            entity_type=EntityType.CONTACT,
            field_key="contact.jurisdiction",
            value_json={"regime": "gdpr"},
            source_tier=1,
            extraction_method=ExtractionMethod.HUMAN,
            confidence=0.9,
            run_id=new_run_id(),
            research_mode=ResearchMode.CONTACT_PROFILING,
        ),
        workspace_id=_CLIENT,
    )
    tomb = build_tombstone(target, run_id=new_run_id())
    assert tomb.verification_status.value == "rejected"
    assert tomb.identity_binding is None  # not a facet → no binding required, copied as-is
    assert tomb.use_class is None


def test_erasure_scope_matches() -> None:
    """Scope narrows by use-class and field-key (intersection); the default matches everything."""
    claim = _facet_claim(_eid("cc"), use_class=_SENSITIVE)
    assert ErasureScope().matches(claim)  # default = all
    assert ErasureScope(use_classes=frozenset({_SENSITIVE})).matches(claim)
    assert not ErasureScope(use_classes=frozenset({_PRO})).matches(claim)
    assert ErasureScope(field_keys=frozenset({_FACET})).matches(claim)
    assert not ErasureScope(field_keys=frozenset({"contact.facet.other"})).matches(claim)
    # both axes must match (intersection)
    assert not ErasureScope(
        use_classes=frozenset({_SENSITIVE}), field_keys=frozenset({"contact.facet.other"})
    ).matches(claim)


def test_tombstone_reason_check_matches_enum() -> None:
    """Pure no-DB drift guard: the migration CHECK value set equals the TombstoneReason enum."""
    module = _load_migration()
    assert tuple(r.value for r in TombstoneReason) == module._TOMBSTONE_REASON


def test_dsar_impl_satisfies_protocol() -> None:
    """The impl is hot-swappable behind the DataSubjectRights seam (runtime-checkable)."""
    impl = DataSubjectRightsImpl(_CLIENT)
    assert isinstance(impl, DataSubjectRights)


# --- DB-gated tests ---------------------------------------------------------


@pytest.mark.usefixtures("require_compliance_db")
def test_erase_excludes_from_current_value() -> None:  # AC3
    async def _run() -> None:
        async with rollback_conn() as conn:
            contact = await _contact(conn)
            claim = await _insert_facet(conn, contact, use_class=_PRO)
            # before: the claim is the current value
            assert await current_value(conn, contact, _FACET, scope=_SCOPE) is not None

            result = await _rights(conn).erase(contact)
            assert len(result.tombstoned_claim_ids) == 1
            assert result.reason is TombstoneReason.ERASURE

            # after: current_value returns none of the erased values, AND the field is absent from
            # the handoff-facing surface (provenance_index is the in-repo proxy for account_handoff,
            # which is M12) — the AC names both current_value and account_handoff
            assert await current_value(conn, contact, _FACET, scope=_SCOPE) is None
            assert _FACET not in await provenance_index(conn, contact, scope=_SCOPE)
            # append-only: the original row still exists (superseded), no destructive delete
            history = await claims_for(
                conn, contact, _FACET, include_superseded=True, scope=ALL_WORKSPACES
            )
            assert any(c.id == claim.id for c in history)
            original = next(c for c in history if c.id == claim.id)
            assert original.superseded_by is not None
            assert original.value_json == "runs the Berlin marathon"  # value untouched in history
            # audit row recorded; tombstone is a HUMAN claim (PF-5)
            audit = await _tombstone_rows(conn, claim.id)
            assert len(audit) == 1 and audit[0] == TombstoneReason.ERASURE.value
            tomb = next(c for c in history if c.id != claim.id and c.superseded_by is None)
            assert tomb.extraction_method is ExtractionMethod.HUMAN

    run_async(_run())


@pytest.mark.usefixtures("require_compliance_db")
def test_erase_purges_legacy_handoff_body_via_reachable_subject_index() -> None:
    """C7.4 DSAR sentinel: old copied dossier bodies are purged; receipts need no body rewrite."""

    sentinel = "C7_LEGACY_HANDOFF_PERSONAL_SENTINEL_38ce2b"

    async def _run() -> None:
        async with rollback_conn() as conn:
            contact = await _contact(conn)
            await _insert_facet(conn, contact, use_class=_PRO, value=sentinel)
            account_id = (
                await conn.execute(
                    text("SELECT account_entity_id FROM contact_entity WHERE id = :contact_id"),
                    {"contact_id": str(contact)},
                )
            ).scalar_one()
            handoff_id = (
                await conn.execute(
                    text(
                        """
                        INSERT INTO account_handoff (
                            workspace_id, account_entity_id, icp_spec_version, icp_key,
                            assembled_at, payload
                        ) VALUES (
                            :workspace_id, :account_entity_id, 1, '', now(),
                                jsonb_build_object('personal_copy', CAST(:sentinel AS text))
                        )
                        RETURNING id
                        """
                    ),
                    {
                        "workspace_id": _CLIENT,
                        "account_entity_id": str(account_id),
                        "sentinel": sentinel,
                    },
                )
            ).scalar_one()
            await conn.execute(
                text(
                    """
                    INSERT INTO account_handoff_subject (
                        account_handoff_id, subject_entity_id, subject_entity_type,
                        parent_account_entity_id, relation
                    ) VALUES (
                        :handoff_id, :contact_id, 'contact', :account_id, 'committee_member'
                    )
                    """
                ),
                {
                    "handoff_id": str(handoff_id),
                    "contact_id": str(contact),
                    "account_id": str(account_id),
                },
            )

            await _rights(conn).erase(contact)

            row = (
                await conn.execute(
                    text(
                        "SELECT payload, legacy_payload_purged_at "
                        "FROM account_handoff WHERE id = :handoff_id"
                    ),
                    {"handoff_id": str(handoff_id)},
                )
            ).one()
            assert row[0] is None
            assert row[1] is not None
            serialized = (
                await conn.execute(
                    text(
                        "SELECT concat_ws(' ', coalesce(payload::text, ''), "
                        "coalesce(research_view_snapshot_id::text, '')) "
                        "FROM account_handoff WHERE id = :handoff_id"
                    ),
                    {"handoff_id": str(handoff_id)},
                )
            ).scalar_one()
            assert sentinel not in serialized

    run_async(_run())


@pytest.mark.usefixtures("require_compliance_db")
def test_erase_is_idempotent() -> None:
    async def _run() -> None:
        async with rollback_conn() as conn:
            contact = await _contact(conn)
            await _insert_facet(conn, contact, use_class=_PRO)
            first = await _rights(conn).erase(contact)
            assert len(first.tombstoned_claim_ids) == 1
            # re-erase: no live claims remain → a no-op
            second = await _rights(conn).erase(contact)
            assert second.tombstoned_claim_ids == ()

    run_async(_run())


@pytest.mark.usefixtures("require_compliance_db")
def test_erase_scoped_by_use_class() -> None:  # AC3 (scope)
    async def _run() -> None:
        async with rollback_conn() as conn:
            contact = await _contact(conn)
            await _insert_facet(conn, contact, use_class=_SENSITIVE)
            # scope to PROFESSIONAL only → the sensitive claim is out of scope, untouched
            scoped = await _rights(conn).erase(contact, ErasureScope(use_classes=frozenset({_PRO})))
            assert scoped.tombstoned_claim_ids == ()
            assert await current_value(conn, contact, _FACET, scope=_SCOPE) is not None
            # scope to SENSITIVE → now it is erased
            hit = await _rights(conn).erase(
                contact, ErasureScope(use_classes=frozenset({_SENSITIVE}))
            )
            assert len(hit.tombstoned_claim_ids) == 1
            assert await current_value(conn, contact, _FACET, scope=_SCOPE) is None

    run_async(_run())


@pytest.mark.usefixtures("require_compliance_db")
def test_object_blocks_hooks() -> None:  # AC4
    async def _run() -> None:
        async with rollback_conn() as conn:
            contact = await _contact(conn)
            await _insert_facet(conn, contact, use_class=_PRO)
            result = await _rights(conn).record_objection(contact)
            assert result.newly_objected is True
            assert len(result.tombstoned_claim_ids) == 1
            # the hook is no longer surfaced (a substrate exclusion, D-OBJ)
            assert await current_value(conn, contact, _FACET, scope=_SCOPE) is None
            # the durable marker is recorded
            marker = (
                await conn.execute(
                    text(
                        "SELECT count(*) FROM outreach_objected "
                        "WHERE contact_entity_id = :c AND workspace_id = :t"
                    ),
                    {"c": str(contact), "t": _CLIENT},
                )
            ).scalar_one()
            assert marker == 1

    run_async(_run())


@pytest.mark.usefixtures("require_compliance_db")
def test_object_then_sweep_resuppresses_new_hooks() -> None:  # AC4 (re-apply)
    async def _run() -> None:
        async with rollback_conn() as conn:
            contact = await _contact(conn)
            await _insert_facet(conn, contact, use_class=_PRO)
            await _rights(conn).record_objection(contact)
            # a NEW hook is collected after the objection → re-appears as current value
            await _insert_facet(conn, contact, use_class=_PRO, value="ran another marathon")
            assert await current_value(conn, contact, _FACET, scope=_SCOPE) is not None
            # the objection sweep re-suppresses it
            swept = await _sweep(conn).sweep_objections()
            assert len(swept.tombstoned_claim_ids) == 1
            assert await current_value(conn, contact, _FACET, scope=_SCOPE) is None

    run_async(_run())


@pytest.mark.usefixtures("require_compliance_db")
def test_sweep_expired_ages_out() -> None:  # AC2
    async def _run() -> None:
        async with rollback_conn() as conn:
            contact = await _contact(conn)
            claim = await _insert_facet(conn, contact, use_class=_SENSITIVE)
            assert await current_value(conn, contact, _FACET, scope=_SCOPE) is not None
            # the M9.5 seam surfaces this claim as EXPIRED (past its retention horizon)
            candidate = AgeOutCandidate(
                claim_id=claim.id,
                entity_id=contact,
                field_key=FieldKey(_FACET),
                age_days=40.0,
                retention_days=30.0,
            )
            result = await _sweep(conn, (candidate,)).sweep_expired()
            assert result.scanned == 1
            assert len(result.tombstoned_claim_ids) == 1
            assert result.reason is TombstoneReason.RETENTION_EXPIRY
            assert await current_value(conn, contact, _FACET, scope=_SCOPE) is None
            assert _FACET not in await provenance_index(conn, contact, scope=_SCOPE)
            audit = await _tombstone_rows(conn, claim.id)
            assert audit == [TombstoneReason.RETENTION_EXPIRY.value]

    run_async(_run())


@pytest.mark.usefixtures("require_compliance_db")
def test_known_retention_expiry_is_fail_closed_before_sweep() -> None:
    """C7.1: list/detail and dependency reads exclude a recorded expiry immediately.

    The durable sweep may run later; the selector must not re-expose the value in that interval.
    """

    async def _run() -> None:
        from clue_config import Jurisdiction
        from clue_research.compliance import record_lawful_basis

        async with rollback_conn() as conn:
            contact = await _contact(conn)
            claim = await _insert_facet(conn, contact, use_class=_PRO)
            await record_lawful_basis(conn, claim, regime=Jurisdiction.GDPR)
            await conn.execute(
                text(
                    "UPDATE lawful_basis_record "
                    "SET retention_until = :expired WHERE claim_id = :claim_id"
                ),
                {
                    "expired": datetime.now(UTC) - timedelta(seconds=1),
                    "claim_id": str(claim.id),
                },
            )

            # Detail and list use the same retention-aware selector and agree before a tombstone
            # exists. The missing batch key is the honest list representation.
            assert await current_value(conn, contact, _FACET, scope=_SCOPE) is None
            assert await current_values(conn, [contact], [_FACET], scope=_SCOPE) == {}

            # The live-by-id reader is the future derivation dependency input: an expired support
            # resolves as missing/invalid, while explicit audit mode retains append-only history.
            assert await claims_by_ids(conn, [claim.id], scope=_SCOPE) == {}
            audit = await claims_by_ids(
                conn,
                [claim.id],
                scope=_SCOPE,
                include_superseded=True,
            )
            assert audit[claim.id].value_json == "runs the Berlin marathon"

    run_async(_run())


@pytest.mark.usefixtures("require_compliance_db")
def test_stale_nonexpired_personal_claim_remains_explicitly_stale() -> None:
    """Freshness staleness remains distinct from retention expiry."""

    async def _run() -> None:
        from clue_config import Jurisdiction
        from clue_research.compliance import record_lawful_basis

        async with rollback_conn() as conn:
            contact = await _contact(conn)
            stale_claim = _facet_claim(contact, use_class=_PRO).model_copy(
                update={"observed_at": datetime.now(UTC) - timedelta(days=100)}
            )
            stale_claim = stamp_reuse(stale_claim, workspace_id=_CLIENT)
            await insert_claim(conn, stale_claim)
            await record_lawful_basis(conn, stale_claim, regime=Jurisdiction.GDPR)

            result = await current_value(conn, contact, _FACET, scope=_SCOPE)
            assert result is not None
            assert result.provenance.claim_id == stale_claim.id
            assert result.freshness_state is FreshnessState.STALE

    run_async(_run())


@pytest.mark.usefixtures("require_compliance_db")
def test_dsar_erases_faithfulness_rationale_body_but_retains_audit_metadata() -> None:
    """C7.1 sentinel: personal rationale text disappears from raw and serialized DSAR outputs."""

    sentinel = "C7_PERSONAL_SENTINEL_7d090678"

    async def _run() -> None:
        async with rollback_conn() as conn:
            contact = await _contact(conn)
            claim = await _insert_facet(conn, contact, use_class=_PRO)
            await conn.execute(
                text(
                    """
                    INSERT INTO faithfulness_verdict
                        (claim_id, verdict, score, rationale, judge_model, answering_model,
                         prompt_version, cost_cents)
                    VALUES
                        (:claim_id, 'supported', 0.99, :rationale, 'judge-requested',
                         'judge-answered', 'c7-test-v1', 0)
                    """
                ),
                {"claim_id": str(claim.id), "rationale": sentinel},
            )

            await _rights(conn).erase(contact)
            row = (
                await conn.execute(
                    text(
                        "SELECT rationale, rationale_redacted_at, rationale_redaction_reason, "
                        "verdict, judge_model, answering_model, prompt_version "
                        "FROM faithfulness_verdict WHERE claim_id = :claim_id"
                    ),
                    {"claim_id": str(claim.id)},
                )
            ).one()
            assert row[0] is None
            assert row[1] is not None
            assert row[2] == TombstoneReason.ERASURE.value
            assert tuple(row[3:]) == (
                "supported",
                "judge-requested",
                "judge-answered",
                "c7-test-v1",
            )

            serialized = (await _rights(conn).access(contact)).model_dump_json()
            assert sentinel not in serialized
            raw = (
                await conn.execute(
                    text(
                        "SELECT coalesce(rationale, '') "
                        "FROM faithfulness_verdict WHERE claim_id = :claim_id"
                    ),
                    {"claim_id": str(claim.id)},
                )
            ).scalar_one()
            assert sentinel not in raw

    run_async(_run())


@pytest.mark.usefixtures("require_compliance_db")
def test_dsar_erases_the_rationale_of_a_verdict_keyed_on_the_entailment_question() -> None:
    """PC-C8 §6c-b: a judged claim's verdict is NOT keyed on the claim id, and erasure must still
    reach it.

    A typed interview value is vouched for before its claim exists, so its verdict rides the
    content-addressed entailment-question id (field_key + value + span). Redacting only
    ``claim_id = <erased claim>`` matched zero of those rows — the claim vanished while the
    rationale went on quoting the subject's own words. This test fails loud (rationale still
    present) against the claim-id-only redaction.
    """

    sentinel = "C8_JUDGED_PERSONAL_SENTINEL_4f21ab90"

    async def _run() -> None:
        async with rollback_conn() as conn:
            contact = await _contact(conn)
            claim = await _insert_facet(
                conn,
                contact,
                use_class=_PRO,
                source_key=SOURCE_CLIENT_INTERVIEW_JUDGED,
            )
            # The key the §6c-b judge actually wrote under: recomputed from the claim's own
            # content, exactly as `dsar._tombstone` must recompute it.
            question_id = entailment_judgment_id(
                workspace_id=claim.workspace_id,
                field_key=claim.field_key,
                value=claim.value_json,
                quote=claim.evidence_span or "",
            )
            assert question_id != claim.id
            legacy_question_id = faithfulness_redaction_subject_ids(claim)[-1]
            assert legacy_question_id not in {question_id, claim.id}
            await conn.execute(
                text(
                    """
                    INSERT INTO faithfulness_verdict
                        (claim_id, verdict, score, rationale, judge_model, answering_model,
                         prompt_version, cost_cents)
                    VALUES
                        (:claim_id, 'supported', 0.98, :rationale, 'judge-requested',
                         'judge-answered', 'c8-test-v1', 0),
                        (:actual_id, 'unsupported', 0.02, :rationale, 'legacy-requested',
                         'legacy-answered', 'c8-legacy-v1', 0),
                        (:legacy_question_id, 'supported', 0.97, :rationale, 'pre-scope-requested',
                         'pre-scope-answered', 'c8-pre-scope-v1', 0)
                    """
                ),
                {
                    "claim_id": str(question_id),
                    "actual_id": str(claim.id),
                    "legacy_question_id": str(legacy_question_id),
                    "rationale": sentinel,
                },
            )

            await _rights(conn).erase(contact)

            row = (
                await conn.execute(
                    text(
                        "SELECT rationale, rationale_redacted_at, rationale_redaction_reason, "
                        "verdict, judge_model FROM faithfulness_verdict WHERE claim_id = :cid"
                    ),
                    {"cid": str(question_id)},
                )
            ).one()
            assert row[0] is None, "the judged claim's rationale survived erasure"
            assert row[1] is not None
            assert row[2] == TombstoneReason.ERASURE.value
            # The bounded audit metadata is preserved, exactly as on the claim-id path.
            assert tuple(row[3:]) == ("supported", "judge-requested")

            legacy_row = (
                await conn.execute(
                    text(
                        "SELECT rationale, rationale_redacted_at, rationale_redaction_reason "
                        "FROM faithfulness_verdict WHERE claim_id = :cid"
                    ),
                    {"cid": str(claim.id)},
                )
            ).one()
            assert legacy_row[0] is None, "the judged claim's legacy A rationale survived erasure"
            assert legacy_row[1] is not None
            assert legacy_row[2] == TombstoneReason.ERASURE.value

            legacy_question_row = (
                await conn.execute(
                    text(
                        "SELECT rationale, rationale_redacted_at, rationale_redaction_reason "
                        "FROM faithfulness_verdict WHERE claim_id = :cid"
                    ),
                    {"cid": str(legacy_question_id)},
                )
            ).one()
            assert legacy_question_row[0] is None, "the pre-scope Q rationale survived erasure"
            assert legacy_question_row[1] is not None
            assert legacy_question_row[2] == TombstoneReason.ERASURE.value

            raw = (
                (
                    await conn.execute(
                        text("SELECT coalesce(rationale, '') FROM faithfulness_verdict")
                    )
                )
                .scalars()
                .all()
            )
            assert all(sentinel not in body for body in raw)

    run_async(_run())


@pytest.mark.usefixtures("require_compliance_db")
def test_dsar_reaches_cross_subject_derivations_through_support_edges() -> None:
    """An account inference copied from a contact signal is erased through reverse lineage."""

    async def _run() -> None:
        sentinel = "SENTINEL-C7-DERIVED-JANA-PRIVATE"
        async with rollback_conn() as conn:
            account = await _account(conn)
            contact = await insert_contact_entity(
                conn,
                account_entity_id=account,
                full_name="Jana Doe",
                status=AccountStatus.ACTIVE,
            )
            support = stamp_reuse(
                _facet_claim(
                    contact,
                    use_class=_PRO,
                    value="shared a private-to-this-controller professional signal",
                ).model_copy(update={"verification_status": VerificationStatus.VERIFIED}),
                workspace_id=_CLIENT,
            )
            await insert_claim(conn, support)
            derived = Claim(
                entity_id=account,
                entity_type=EntityType.ACCOUNT,
                field_key="account.recent_funding",
                value_json={"amount_usd": 1, "round": sentinel},
                source_tier=4,
                extraction_method=ExtractionMethod.LLM_SYNTHESIS,
                confidence=0.75,
                run_id=new_run_id(),
                research_mode=ResearchMode.ACCOUNT_PROFILING,
                claim_flavor=ClaimFlavor.DERIVED,
                verification_status=VerificationStatus.VERIFIED,
                reuse_scope=ReuseScope.TENANT_PRIVATE,
                workspace_id=_CLIENT,
            )
            await insert_claim(conn, derived)
            operation_id = new_operation_id()
            await conn.execute(
                text(
                    """
                    INSERT INTO claim_derivation
                        (workspace_id, derived_claim_id, supporting_claim_id, support_role,
                         ordinal, operation_id)
                    VALUES
                        (:workspace, :derived, :support, 'account_signal', 0, :operation)
                    """
                ),
                {
                    "workspace": _CLIENT,
                    "derived": derived.id,
                    "support": support.id,
                    "operation": operation_id,
                },
            )
            await conn.execute(
                text(
                    """
                    INSERT INTO entailment_verdict
                        (workspace_id, derived_claim_id, support_set_sha256, verdict, confidence,
                         reason_codes, requested_model, answering_model, prompt_version,
                         policy_version, trace_ref, operation_id)
                    VALUES
                        (:workspace, :derived, :support_hash, 'supported', 0.8,
                         ARRAY['entailed'::entailment_reason_code], 'judge', 'judge', 'v1',
                         1, 'trace-c7-dsar', :operation)
                    """
                ),
                {
                    "workspace": _CLIENT,
                    "derived": derived.id,
                    "support_hash": "d" * 64,
                    "operation": operation_id,
                },
            )
            await conn.execute(text("SET CONSTRAINTS derived_claim_has_lineage IMMEDIATE"))

            erased = await _rights(conn).erase(contact)
            assert len(erased.tombstoned_claim_ids) == 2
            rows = (
                await conn.execute(
                    text(
                        "SELECT erased_claim_id FROM dsar_tombstone "
                        "WHERE contact_entity_id = :contact"
                    ),
                    {"contact": contact},
                )
            ).scalars()
            assert set(rows) == {support.id, derived.id}

            visible = await claims_by_ids(
                conn,
                [support.id, derived.id],
                scope=WorkspaceScope.for_workspace(_CLIENT),
            )
            assert visible == {}
            assert sentinel not in str(visible)
            resolution = await DerivationDependencyResolver().resolve(
                conn,
                derived.id,
                scope=WorkspaceScope.for_workspace(_CLIENT),
            )
            assert resolution.state is DerivationDependencyState.REDACTED

    run_async(_run())


@pytest.mark.usefixtures("require_compliance_db")
def test_access_exports_claims_and_basis() -> None:  # AC5 (access)
    from clue_config import Jurisdiction
    from clue_research.compliance import record_lawful_basis

    async def _run() -> None:
        async with rollback_conn() as conn:
            contact = await _contact(conn)
            claim = await _insert_facet(conn, contact, use_class=_PRO)
            await record_lawful_basis(conn, claim, regime=Jurisdiction.GDPR)
            export = await _rights(conn).access(contact)
            assert export.contact_entity_id == contact
            assert export.workspace_id == _CLIENT
            assert any(c.id == claim.id for c in export.claims)
            assert len(export.lawful_bases) == 1
            assert export.lawful_bases[0].claim_id == claim.id
            # after an erasure, the export excludes the internal {"__erased__": true} tombstone rows
            # (substrate bookkeeping, not the subject's data) but still shows the held value
            await _rights(conn).erase(contact)
            after = await _rights(conn).access(contact)
            assert all(c.value_json != {"__erased__": True} for c in after.claims)
            assert any(c.value_json == "runs the Berlin marathon" for c in after.claims)

    run_async(_run())


@pytest.mark.usefixtures("require_compliance_db")
def test_rectify_supersedes_with_corrected() -> None:  # AC5 (rectify)
    async def _run() -> None:
        async with rollback_conn() as conn:
            contact = await _contact(conn)
            claim = await _insert_facet(conn, contact, use_class=_PRO)
            corrected = _facet_claim(contact, use_class=_PRO, value="ran the London marathon")
            corrected = stamp_reuse(corrected, workspace_id=_CLIENT)
            new_id = await _rights(conn).rectify(claim.id, corrected)
            cv = await current_value(conn, contact, _FACET, scope=_SCOPE)
            assert cv is not None
            assert cv.value_json == "ran the London marathon"
            assert cv.provenance.claim_id == new_id

    run_async(_run())


@pytest.mark.usefixtures("require_compliance_db")
def test_rectify_rejects_cross_controller_claim() -> None:  # controller-scoped, fail-closed
    async def _run() -> None:
        async with rollback_conn() as conn:
            contact = await _contact(conn)
            # the target belongs to ANOTHER controller (tenant)
            foreign = _facet_claim(contact, use_class=_PRO)
            await insert_claim(conn, stamp_reuse(foreign, workspace_id="other-controller"))
            corrected = stamp_reuse(
                _facet_claim(contact, use_class=_PRO, value="ran the London marathon"),
                workspace_id=_CLIENT,
            )
            with pytest.raises(ValueError, match="not one of this controller"):
                await _rights(conn).rectify(foreign.id, corrected)
            # the foreign claim is untouched (still live, original value)
            cv = await current_value(
                conn, contact, _FACET, scope=WorkspaceScope.for_workspace("other-controller")
            )
            assert cv is not None and cv.value_json == "runs the Berlin marathon"

    run_async(_run())


# --- helpers ----------------------------------------------------------------


def _eid(suffix: str) -> EntityId:
    return EntityId(f"00000000-0000-0000-0000-0000000000{suffix}")


def _load_migration() -> object:
    path = (
        Path(__file__).resolve().parents[2]
        / "alembic/versions/b56207f907f2_m10_5_lawful_basis_record_dsar_.py"
    )
    spec = importlib.util.spec_from_file_location("_m105_migration_dsar", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@asynccontextmanager
async def _yield(conn: AsyncConnection) -> AsyncIterator[AsyncConnection]:
    yield conn


def _rights(conn: AsyncConnection) -> DataSubjectRightsImpl:
    return DataSubjectRightsImpl(_CLIENT, conn_factory=lambda: _yield(conn))


def _sweep(conn: AsyncConnection, candidates: tuple[AgeOutCandidate, ...] = ()) -> RetentionSweep:
    return RetentionSweep(_StubFreshness(candidates), conn_factory=lambda: _yield(conn))


def _facet_claim(
    contact: EntityId,
    *,
    use_class: UseClass,
    value: str = "runs the Berlin marathon",
    source_key: str | None = None,
) -> Claim:
    return Claim(
        entity_id=contact,
        entity_type=EntityType.CONTACT,
        field_key=_FACET,
        value_json=value,
        source_url="https://www.linkedin.com/in/jana",
        evidence_span=f"Jana Doe {value}.",
        source_key=source_key,
        source_tier=2,
        extraction_method=ExtractionMethod.SCRAPE,
        identity_binding=IdentityBinding.STRONG,
        use_class=use_class,
        confidence=0.9,
        run_id=new_run_id(),
        research_mode=ResearchMode.CONTACT_PROFILING,
    )


async def _account(conn: AsyncConnection) -> EntityId:
    await seed_workspace(conn, _CLIENT)
    return await insert_account_entity(
        conn,
        canonical_name="Acme GmbH",
        primary_domain="acme.de",
        status=AccountStatus.ACTIVE,
        workspace_id=_CLIENT,
    )


async def _contact(conn: AsyncConnection) -> EntityId:
    account = await _account(conn)
    return await insert_contact_entity(
        conn, account_entity_id=account, full_name="Jana Doe", status=AccountStatus.ACTIVE
    )


async def _insert_facet(
    conn: AsyncConnection,
    contact: EntityId,
    *,
    use_class: UseClass,
    value: str = "runs the Berlin marathon",
    source_key: str | None = None,
) -> Claim:
    claim = _facet_claim(
        contact,
        use_class=use_class,
        value=value,
        source_key=source_key,
    )
    stored = stamp_reuse(claim, workspace_id=_CLIENT)
    await insert_claim(conn, stored)
    return stored


async def _tombstone_rows(conn: AsyncConnection, erased_claim_id: ClaimId) -> list[str]:
    rows = (
        await conn.execute(
            text("SELECT reason FROM dsar_tombstone WHERE erased_claim_id = :c"),
            {"c": str(erased_claim_id)},
        )
    ).all()
    return [str(r[0]) for r in rows]
