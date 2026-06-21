"""DB-backed tests for M5.3 — the import entry scenario (``import_accounts``).

Covers every acceptance criterion: duplicate variants (shared strong key) collapse to one entity;
two genuinely-different same-name companies route to review (never silently merged); unresolvable
rows surface with a reason (never dropped); every resolved account carries discovery-provenance and
a decomposed back-score; non-fit accounts are flagged but kept; CRM enrichment writes tier-1 claims
and detects "already a customer"; imported contacts carry ``identity_binding`` / ``use_class`` /
lawful basis at write time; and the resolved set is shape-identical to discovery — it flows through
the same Pass A scoring + tiering path (a mock checkpoint).
"""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_research.claimstore import TenantScope, claims_for
from clue_research.core import AccountStatus, EntityId, IdentityBinding, ReuseScope, UseClass
from clue_research.icp import assign_tier, get_rubric_version, score_entity
from clue_research.identity import (
    DispositionPolicy,
    embed_account,
    get_account,
    insert_account_entity,
)
from clue_research.sources import bind_resolver
from clue_research.stage0 import (
    CONTACT_IMPORT_RECORD,
    DISCOVERY_PROVENANCE,
    IMPORT_BATCH,
    FitFlag,
    ImportContactRow,
    ImportRow,
    import_accounts,
)
from tests.stage0._fakes import FakeCrmResolver, build_confirmed_icp
from tests.stage0.conftest import rollback_conn, run_async

pytestmark = pytest.mark.usefixtures("require_stage0_db", "resolver_bindings")

_CLIENT = "tenant-import"


async def _client_entity(conn: AsyncConnection, suffix: str) -> EntityId:
    """A resolved client ``account_entity`` to anchor the import-batch marker on."""
    return await insert_account_entity(
        conn,
        canonical_name=f"Import Client {suffix}",
        primary_domain=f"client-{suffix}.example",
        status=AccountStatus.ACTIVE,
    )


def _scope() -> TenantScope:
    return TenantScope.for_tenant(_CLIENT)


def test_duplicate_variants_collapse_to_one_entity() -> None:
    """Exact-duplicate variants sharing a strong key (domain) collapse to one account_entity."""

    async def _run() -> None:
        async with rollback_conn() as conn:
            client = await _client_entity(conn, "dup")
            icp = await build_confirmed_icp(conn, client_id=_CLIENT)
            rows = [
                ImportRow(row_index=1, name="IBM", domain="ibm.com"),
                ImportRow(row_index=2, name="I.B.M.", domain="ibm.com"),
                ImportRow(
                    row_index=3, name="International Business Machines Corp.", domain="ibm.com"
                ),
            ]
            result = await import_accounts(
                conn, rows, icp, client_id=_CLIENT, client_entity_id=client
            )
            assert len(result.resolved) == 3
            assert len({r.account_entity_id for r in result.resolved}) == 1
            assert not result.needs_review
            assert not result.unresolved
            # the second + third rows collapse via the intra-batch strong-key index
            assert {r.resolution_method for r in result.resolved} == {"new_entity", "intra_batch"}

    run_async(_run())


def test_registry_only_variants_collapse_to_one_entity() -> None:
    """Two registry-only rows for the same company in different textual form (a co-equal strong key
    with domain) collapse to a single account_entity via the canonicalized intra-batch index."""

    async def _run() -> None:
        async with rollback_conn() as conn:
            client = await _client_entity(conn, "reg")
            icp = await build_confirmed_icp(conn, client_id=_CLIENT)
            rows = [
                ImportRow(row_index=1, name="Initech", registry_ids={"DUNS": "12-345-6789"}),
                ImportRow(row_index=2, name="Initech Corp", registry_ids={"duns": "123 456 789"}),
            ]
            result = await import_accounts(
                conn, rows, icp, client_id=_CLIENT, client_entity_id=client
            )
            assert len(result.resolved) == 2
            assert len({r.account_entity_id for r in result.resolved}) == 1
            assert not result.needs_review
            # row 1 admits the entity, row 2 collapses onto it via the registry strong key
            assert {r.resolution_method for r in result.resolved} == {"new_entity", "intra_batch"}
            collapsed = next(r for r in result.resolved if r.resolution_method == "intra_batch")
            assert collapsed.matched_signal == "registry"

    run_async(_run())


def test_same_name_different_company_routes_to_review() -> None:
    """A fuzzy name match (no shared strong key) never auto-merges — it goes to the review queue."""

    async def _run() -> None:
        async with rollback_conn() as conn:
            client = await _client_entity(conn, "review")
            icp = await build_confirmed_icp(conn, client_id=_CLIENT)
            existing = await insert_account_entity(
                conn,
                canonical_name="Globex Industries",
                primary_domain="globex-existing.example",
                status=AccountStatus.ACTIVE,
            )
            await embed_account(conn, existing)
            # a name-only row (no domain → no strong key) that fuzzy-matches the existing entity
            rows = [ImportRow(row_index=1, name="Globex Industries")]
            policy = DispositionPolicy(auto_merge_threshold=0.95, review_low_threshold=0.05)
            result = await import_accounts(
                conn,
                rows,
                icp,
                client_id=_CLIENT,
                client_entity_id=client,
                disposition_policy=policy,
            )
            assert not result.resolved  # never silently merged onto the existing entity
            assert len(result.needs_review) == 1
            assert result.needs_review[0].row_index == 1
            assert existing in result.needs_review[0].candidate_entity_ids

    run_async(_run())


def test_unresolvable_row_surfaced_with_reason() -> None:
    """A row with no usable identity lands in unresolved[] with a reason — not silently dropped."""

    async def _run() -> None:
        async with rollback_conn() as conn:
            client = await _client_entity(conn, "unres")
            icp = await build_confirmed_icp(conn, client_id=_CLIENT)
            rows = [
                ImportRow(row_index=1, name="Acme Co", domain="acme-unres.example"),
                ImportRow(row_index=2),  # no name, domain, or registry id
            ]
            result = await import_accounts(
                conn, rows, icp, client_id=_CLIENT, client_entity_id=client
            )
            assert len(result.resolved) == 1
            assert len(result.unresolved) == 1
            assert result.unresolved[0].row_index == 2
            assert "identity" in result.unresolved[0].reason
            # the no-silent-drop invariant: every input row is accounted for exactly once
            assert result.row_count == 2

    run_async(_run())


def test_resolved_account_has_provenance_and_decomposed_backscore() -> None:
    """Every resolved account carries a matched_channel='import' provenance claim + a decomposed
    fit/intent score (each linking its evidence claims — no score without evidence)."""

    async def _run() -> None:
        async with rollback_conn() as conn:
            client = await _client_entity(conn, "prov")
            icp = await build_confirmed_icp(conn, client_id=_CLIENT)
            bind_resolver("crm", FakeCrmResolver(relationship="customer"))
            rows = [ImportRow(row_index=1, name="Provence SAS", domain="provence.example")]
            result = await import_accounts(
                conn, rows, icp, client_id=_CLIENT, client_entity_id=client, crm_enrich=True
            )
            (acct,) = result.resolved
            assert acct.provenance_claim_id is not None
            prov = await claims_for(
                conn, acct.account_entity_id, field_key=DISCOVERY_PROVENANCE, scope=_scope()
            )
            assert prov and prov[0].value_json["matched_channel"] == "import"
            assert prov[0].discovery_provenance is not None
            # "which accounts this client imported" is tenant-private (not a public footprint)
            assert prov[0].reuse_scope is ReuseScope.TENANT_PRIVATE
            assert prov[0].tenant_id == _CLIENT
            # the back-score is decomposed and the fit component links the CRM evidence claim
            assert acct.fit_score.value == pytest.approx(1.0)
            fit_components = acct.fit_score.components
            assert fit_components and fit_components[0].evidence_claim_ids

    run_async(_run())


def test_non_fit_flagged_but_not_excluded() -> None:
    """An account below the ICP fit floor is flagged NON_FIT yet stays in resolved[] (D6)."""

    async def _run() -> None:
        async with rollback_conn() as conn:
            client = await _client_entity(conn, "nonfit")
            icp = await build_confirmed_icp(conn, client_id=_CLIENT, fit_threshold=0.5)
            # no CRM enrichment → the rubric's only fit field is absent → fit 0.0 < 0.5
            rows = [ImportRow(row_index=1, name="Misfit Ltd", domain="misfit.example")]
            result = await import_accounts(
                conn, rows, icp, client_id=_CLIENT, client_entity_id=client, crm_enrich=False
            )
            assert len(result.resolved) == 1  # flagged, not excluded
            assert result.resolved[0].fit_flag is FitFlag.NON_FIT
            assert result.non_fit_count == 1

    run_async(_run())


def test_crm_enrich_detects_already_customer() -> None:
    """A CRM-pulled relationship enters as a tier-1 claim and "already a customer" is detectable."""

    async def _run() -> None:
        async with rollback_conn() as conn:
            client = await _client_entity(conn, "crm")
            icp = await build_confirmed_icp(conn, client_id=_CLIENT)
            bind_resolver("crm", FakeCrmResolver(relationship="customer"))
            rows = [ImportRow(row_index=1, name="Loyal Corp", domain="loyal.example")]
            result = await import_accounts(
                conn, rows, icp, client_id=_CLIENT, client_entity_id=client, crm_enrich=True
            )
            (acct,) = result.resolved
            assert acct.already_customer is True
            assert acct.crm_relationship == "customer"
            assert acct.fit_flag is FitFlag.FIT  # CRM relationship present → fit 1.0
            crm = await claims_for(
                conn,
                acct.account_entity_id,
                field_key="account.crm_relationship_status",
                scope=_scope(),
            )
            assert crm and crm[0].source_tier == 1

    run_async(_run())


def test_imported_contact_carries_governance_tags() -> None:
    """An imported contact resolves under its account and its claim carries identity_binding,
    use_class, and a recorded lawful basis at write time (Doc D §2/§4)."""

    async def _run() -> None:
        async with rollback_conn() as conn:
            client = await _client_entity(conn, "contact")
            icp = await build_confirmed_icp(conn, client_id=_CLIENT)
            rows = [
                ImportRow(
                    row_index=1,
                    name="Buyer Inc",
                    domain="buyer.example",
                    contacts=(
                        ImportContactRow(
                            name="Jane Doe", email="jane@buyer.example", title="VP Engineering"
                        ),
                        ImportContactRow(name="Anon Only"),  # name-only → weak binding
                        ImportContactRow(
                            name="Pat Sensitive",
                            email="pat@buyer.example",
                            use_class=UseClass.SENSITIVE,
                        ),
                    ),
                ),
            ]
            result = await import_accounts(
                conn, rows, icp, client_id=_CLIENT, client_entity_id=client
            )
            assert len(result.contacts) == 3
            by_uc = {c.use_class: c for c in result.contacts}
            strong = next(
                c
                for c in result.contacts
                if c.identity_binding == "strong"
                and c.use_class == UseClass.PROFESSIONAL_PUBLIC.value
            )
            weak = next(c for c in result.contacts if c.identity_binding == "weak")
            sensitive = by_uc[UseClass.SENSITIVE.value]
            assert strong.lawful_basis == "legitimate_interest"
            # a weak (name-only) binding still records a lawful basis at write time
            assert weak.identity_binding == IdentityBinding.WEAK.value
            assert weak.lawful_basis == "legitimate_interest"
            # SENSITIVE (special-category) data has no outreach basis (Doc D §4; M10 keeps it out)
            assert sensitive.lawful_basis == "none"
            # the persisted professional-public claim carries the governance tags
            rec = await claims_for(
                conn, strong.contact_entity_id, field_key=CONTACT_IMPORT_RECORD, scope=_scope()
            )
            assert rec
            assert rec[0].identity_binding is IdentityBinding.STRONG
            assert rec[0].use_class is UseClass.PROFESSIONAL_PUBLIC
            assert rec[0].value_json["lawful_basis"] == "legitimate_interest"
            assert "lia_ref" in rec[0].value_json  # legitimate_interest → LIA reference recorded
            # the persisted sensitive claim is tagged sensitive with no outreach basis / no LIA ref
            srec = await claims_for(
                conn, sensitive.contact_entity_id, field_key=CONTACT_IMPORT_RECORD, scope=_scope()
            )
            assert srec
            assert srec[0].use_class is UseClass.SENSITIVE
            assert srec[0].value_json["lawful_basis"] == "none"
            assert "lia_ref" not in srec[0].value_json

    run_async(_run())


def test_resolved_set_converges_with_discovery_path() -> None:
    """The resolved set is shape-identical to discovery (admitted candidate + discovery-provenance
    claim) and flows through the same Pass A scoring + tiering path — verified with a mock
    checkpoint that cannot tell import from discovery except by matched_channel."""

    async def _run() -> None:
        async with rollback_conn() as conn:
            client = await _client_entity(conn, "converge")
            icp = await build_confirmed_icp(conn, client_id=_CLIENT)
            bind_resolver("crm", FakeCrmResolver(relationship="customer"))
            rows = [
                ImportRow(row_index=1, name="Alpha LLC", domain="alpha.example"),
                ImportRow(row_index=2, name="Beta GmbH", domain="beta.example"),
            ]
            result = await import_accounts(
                conn, rows, icp, client_id=_CLIENT, client_entity_id=client, crm_enrich=True
            )
            rubric = await get_rubric_version(conn, _CLIENT, icp.icp_key, icp.icp_version)
            assert rubric is not None
            for acct in result.resolved:
                # discovery shape: an admitted account entity (candidate) ...
                entity = await get_account(conn, acct.account_entity_id)
                assert entity is not None
                assert entity.status is AccountStatus.CANDIDATE
                # ... plus a discovery-provenance claim flavored 'import'
                prov = await claims_for(
                    conn, acct.account_entity_id, field_key=DISCOVERY_PROVENANCE, scope=_scope()
                )
                assert prov and prov[0].value_json["matched_channel"] == "import"
                # a mock M6 checkpoint scores + tiers it from the spec alone
                sr = await score_entity(conn, rubric, acct.account_entity_id, scope=_scope())
                tier = assign_tier(sr.tier_cutoffs, sr.fit_score, sr.intent_score)
                assert tier == "high"  # CRM-enriched → clears the fit band

    run_async(_run())


def test_import_batch_marker_written() -> None:
    """The import run is grouped by a claim-native import.batch marker on the client entity."""

    async def _run() -> None:
        async with rollback_conn() as conn:
            client = await _client_entity(conn, "batch")
            icp = await build_confirmed_icp(conn, client_id=_CLIENT)
            rows = [
                ImportRow(row_index=1, name="One Co", domain="one.example"),
                ImportRow(row_index=2),  # unresolved
            ]
            result = await import_accounts(
                conn,
                rows,
                icp,
                client_id=_CLIENT,
                client_entity_id=client,
                import_batch_id="batch-x",
            )
            marker = await claims_for(conn, client, field_key=IMPORT_BATCH, scope=_scope())
            assert marker
            value = marker[0].value_json
            assert value["import_batch_id"] == "batch-x"
            assert value["resolved_count"] == 1
            assert value["unresolved_count"] == 1
            assert result.import_batch_id == "batch-x"

    run_async(_run())


def test_reimport_same_batch_does_not_duplicate_entities() -> None:
    """A retried import (same rows) re-resolves to the existing entities — no duplicate accounts."""

    async def _run() -> None:
        async with rollback_conn() as conn:
            client = await _client_entity(conn, "reimport")
            icp = await build_confirmed_icp(conn, client_id=_CLIENT)
            rows = [ImportRow(row_index=1, name="Repeat Inc", domain="repeat.example")]
            first = await import_accounts(
                conn, rows, icp, client_id=_CLIENT, client_entity_id=client, import_batch_id="b1"
            )
            second = await import_accounts(
                conn, rows, icp, client_id=_CLIENT, client_entity_id=client, import_batch_id="b1"
            )
            assert first.resolved[0].account_entity_id == second.resolved[0].account_entity_id
            # the second pass auto-merges onto the existing entity (deterministic strong key)
            assert second.resolved[0].resolution_method == "deterministic"

    run_async(_run())
