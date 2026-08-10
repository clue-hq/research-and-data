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
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_core import (
    AccountStatus,
    EntityId,
    EntityType,
    IdentityBinding,
    ReuseScope,
    UseClass,
)
from clue_research.claimstore import WorkspaceScope, claims_for
from clue_research.icp import assign_tier, get_rubric_version, score_entity
from clue_research.identity import (
    DispositionPolicy,
    embed_account,
    get_account,
    get_task,
    insert_account_entity,
    mark_merged,
    resolve_create_new_entity,
)
from clue_research.membership import accounts_for_project, projects_for_accounts
from clue_research.sources import bind_resolver
from clue_research.stage0 import (
    CONTACT_IMPORT_RECORD,
    DISCOVERY_PROVENANCE,
    IMPORT_BATCH,
    FitFlag,
    ImportContactRow,
    ImportProjectNotFound,
    ImportRow,
    import_accounts,
)
from clue_research.stage0.import_accounts import import_batch_run_id
from tests._run_lineage import assert_written_claims_are_attributable
from tests._workspace import seed_project
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
        workspace_id=_CLIENT,
    )


def _scope() -> WorkspaceScope:
    return WorkspaceScope.for_workspace(_CLIENT)


async def _added_via(conn: AsyncConnection, entity_id: EntityId) -> list[str]:
    """The membership channels recorded for one account — no reader exposes ``added_via``."""
    rows = await conn.execute(
        text(
            "SELECT added_via FROM project_account "
            "WHERE workspace_id = :ws AND account_entity_id = :id ORDER BY added_at"
        ),
        {"ws": _CLIENT, "id": entity_id},
    )
    return list(rows.scalars())


async def _accounts_named(conn: AsyncConnection, domain: str) -> int:
    """How many account entities exist for a domain — "the batch created nothing" made checkable."""
    rows = await conn.execute(
        text(
            "SELECT count(*) FROM account_entity WHERE primary_domain = :d AND workspace_id = :ws"
        ),
        {"d": domain, "ws": _CLIENT},
    )
    return int(rows.scalar_one())


def test_duplicate_variants_collapse_to_one_entity() -> None:
    """Exact-duplicate variants sharing a strong key (domain) collapse to one account_entity."""

    async def _run() -> None:
        async with rollback_conn(workspace_id=_CLIENT) as conn:
            client = await _client_entity(conn, "dup")
            icp = await build_confirmed_icp(conn, workspace_id=_CLIENT)
            rows = [
                ImportRow(row_index=1, name="IBM", domain="ibm.com"),
                ImportRow(row_index=2, name="I.B.M.", domain="ibm.com"),
                ImportRow(
                    row_index=3, name="International Business Machines Corp.", domain="ibm.com"
                ),
            ]
            result = await import_accounts(
                conn, rows, icp, workspace_id=_CLIENT, client_entity_id=client
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
        async with rollback_conn(workspace_id=_CLIENT) as conn:
            client = await _client_entity(conn, "reg")
            icp = await build_confirmed_icp(conn, workspace_id=_CLIENT)
            rows = [
                ImportRow(row_index=1, name="Initech", registry_ids={"DUNS": "12-345-6789"}),
                ImportRow(row_index=2, name="Initech Corp", registry_ids={"duns": "123 456 789"}),
            ]
            result = await import_accounts(
                conn, rows, icp, workspace_id=_CLIENT, client_entity_id=client
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
        async with rollback_conn(workspace_id=_CLIENT) as conn:
            client = await _client_entity(conn, "review")
            icp = await build_confirmed_icp(conn, workspace_id=_CLIENT)
            existing = await insert_account_entity(
                conn,
                canonical_name="Globex Industries",
                primary_domain="globex-existing.example",
                status=AccountStatus.ACTIVE,
                workspace_id=_CLIENT,
            )
            await embed_account(conn, existing)
            # a name-only row (no domain → no strong key) that fuzzy-matches the existing entity
            rows = [ImportRow(row_index=1, name="Globex Industries")]
            policy = DispositionPolicy(auto_merge_threshold=0.95, review_low_threshold=0.05)
            result = await import_accounts(
                conn,
                rows,
                icp,
                workspace_id=_CLIENT,
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
        async with rollback_conn(workspace_id=_CLIENT) as conn:
            client = await _client_entity(conn, "unres")
            icp = await build_confirmed_icp(conn, workspace_id=_CLIENT)
            rows = [
                ImportRow(row_index=1, name="Acme Co", domain="acme-unres.example"),
                ImportRow(row_index=2),  # no name, domain, or registry id
            ]
            result = await import_accounts(
                conn, rows, icp, workspace_id=_CLIENT, client_entity_id=client
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
        async with rollback_conn(workspace_id=_CLIENT) as conn:
            client = await _client_entity(conn, "prov")
            icp = await build_confirmed_icp(conn, workspace_id=_CLIENT)
            bind_resolver("crm", FakeCrmResolver(relationship="customer"))
            rows = [ImportRow(row_index=1, name="Provence SAS", domain="provence.example")]
            result = await import_accounts(
                conn, rows, icp, workspace_id=_CLIENT, client_entity_id=client, crm_enrich=True
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
            assert prov[0].workspace_id == _CLIENT
            # the back-score is decomposed and the fit component links the CRM evidence claim
            assert acct.fit_score.value == pytest.approx(1.0)
            fit_components = acct.fit_score.components
            assert fit_components and fit_components[0].evidence_claim_ids

    run_async(_run())


def test_non_fit_flagged_but_not_excluded() -> None:
    """An account below the ICP fit floor is flagged NON_FIT yet stays in resolved[] (D6)."""

    async def _run() -> None:
        async with rollback_conn(workspace_id=_CLIENT) as conn:
            client = await _client_entity(conn, "nonfit")
            icp = await build_confirmed_icp(conn, workspace_id=_CLIENT, fit_threshold=0.5)
            # no CRM enrichment → the rubric's only fit field is absent → fit 0.0 < 0.5
            rows = [ImportRow(row_index=1, name="Misfit Ltd", domain="misfit.example")]
            result = await import_accounts(
                conn, rows, icp, workspace_id=_CLIENT, client_entity_id=client, crm_enrich=False
            )
            assert len(result.resolved) == 1  # flagged, not excluded
            assert result.resolved[0].fit_flag is FitFlag.NON_FIT
            assert result.non_fit_count == 1

    run_async(_run())


def test_crm_enrich_detects_already_customer() -> None:
    """A CRM-pulled relationship enters as a tier-1 claim and "already a customer" is detectable."""

    async def _run() -> None:
        async with rollback_conn(workspace_id=_CLIENT) as conn:
            client = await _client_entity(conn, "crm")
            icp = await build_confirmed_icp(conn, workspace_id=_CLIENT)
            bind_resolver("crm", FakeCrmResolver(relationship="customer"))
            rows = [ImportRow(row_index=1, name="Loyal Corp", domain="loyal.example")]
            result = await import_accounts(
                conn, rows, icp, workspace_id=_CLIENT, client_entity_id=client, crm_enrich=True
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
        async with rollback_conn(workspace_id=_CLIENT) as conn:
            client = await _client_entity(conn, "contact")
            icp = await build_confirmed_icp(conn, workspace_id=_CLIENT)
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
                conn, rows, icp, workspace_id=_CLIENT, client_entity_id=client
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
        async with rollback_conn(workspace_id=_CLIENT) as conn:
            client = await _client_entity(conn, "converge")
            icp = await build_confirmed_icp(conn, workspace_id=_CLIENT)
            bind_resolver("crm", FakeCrmResolver(relationship="customer"))
            rows = [
                ImportRow(row_index=1, name="Alpha LLC", domain="alpha.example"),
                ImportRow(row_index=2, name="Beta GmbH", domain="beta.example"),
            ]
            result = await import_accounts(
                conn, rows, icp, workspace_id=_CLIENT, client_entity_id=client, crm_enrich=True
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
        async with rollback_conn(workspace_id=_CLIENT) as conn:
            client = await _client_entity(conn, "batch")
            icp = await build_confirmed_icp(conn, workspace_id=_CLIENT)
            rows = [
                ImportRow(row_index=1, name="One Co", domain="one.example"),
                ImportRow(row_index=2),  # unresolved
            ]
            result = await import_accounts(
                conn,
                rows,
                icp,
                workspace_id=_CLIENT,
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
        async with rollback_conn(workspace_id=_CLIENT) as conn:
            client = await _client_entity(conn, "reimport")
            icp = await build_confirmed_icp(conn, workspace_id=_CLIENT)
            rows = [ImportRow(row_index=1, name="Repeat Inc", domain="repeat.example")]
            first = await import_accounts(
                conn, rows, icp, workspace_id=_CLIENT, client_entity_id=client, import_batch_id="b1"
            )
            second = await import_accounts(
                conn, rows, icp, workspace_id=_CLIENT, client_entity_id=client, import_batch_id="b1"
            )
            assert first.resolved[0].account_entity_id == second.resolved[0].account_entity_id
            # the second pass auto-merges onto the existing entity (deterministic strong key)
            assert second.resolved[0].resolution_method == "deterministic"

    run_async(_run())


def test_import_batch_registers_its_run_in_run_lineage() -> None:
    """FI-2 P2: every claim an import batch writes back-joins to a registered run.

    Import carries no project context of its own yet (the caller supplies one), so an unattributed
    batch registers as a workspace-level run — and a batch handed a project registers under it.
    """

    async def _run() -> None:
        async with rollback_conn(workspace_id=_CLIENT) as conn:
            client = await _client_entity(conn, "lineage")
            icp = await build_confirmed_icp(conn, workspace_id=_CLIENT)
            rows = [ImportRow(row_index=1, name="Lineage Inc", domain="lineage.example")]

            await import_accounts(
                conn, rows, icp, workspace_id=_CLIENT, client_entity_id=client, import_batch_id="bl"
            )
            await assert_written_claims_are_attributable(
                conn,
                import_batch_run_id("bl"),
                kind="import",
                workspace_id=_CLIENT,
                project_id=None,
            )

            project = await seed_project(conn, _CLIENT, name="Import project")
            await import_accounts(
                conn,
                rows,
                icp,
                workspace_id=_CLIENT,
                client_entity_id=client,
                import_batch_id="bl-project",
                project_id=project.project_id,
            )
            await assert_written_claims_are_attributable(
                conn,
                import_batch_run_id("bl-project"),
                kind="import",
                workspace_id=_CLIENT,
                project_id=project.project_id,
            )

    run_async(_run())


def test_import_into_a_project_joins_every_account_the_batch_lands_on() -> None:
    """FI-2 H3 (spec §8.3): an import *into a project* makes every account the batch resolves to a
    target of that project — the freshly-admitted one and the one that auto-merged onto an account
    that already existed. Membership is a join, not a creation record: an account discovery already
    put in the workspace joins the importing project too."""

    async def _run() -> None:
        async with rollback_conn(workspace_id=_CLIENT) as conn:
            client = await _client_entity(conn, "join")
            icp = await build_confirmed_icp(conn, workspace_id=_CLIENT)
            project = await seed_project(conn, _CLIENT, name="Joining project")
            existing = await insert_account_entity(
                conn,
                canonical_name="Already Here Ltd",
                primary_domain="alreadyhere.example",
                status=AccountStatus.ACTIVE,
                workspace_id=_CLIENT,
            )
            await embed_account(conn, existing)
            rows = [
                ImportRow(row_index=1, name="Brand New Co", domain="brandnew-join.example"),
                ImportRow(row_index=2, name="Already Here", domain="alreadyhere.example"),
            ]
            result = await import_accounts(
                conn,
                rows,
                icp,
                workspace_id=_CLIENT,
                client_entity_id=client,
                project_id=project.project_id,
            )
            by_row = {r.row_index: r for r in result.resolved}
            assert by_row[1].resolution_method == "new_entity"
            assert by_row[2].resolution_method == "deterministic"
            assert by_row[2].account_entity_id == existing

            assert set(
                await accounts_for_project(
                    conn, workspace_id=_CLIENT, project_id=project.project_id
                )
            ) == {by_row[1].account_entity_id, existing}
            assert await projects_for_accounts(
                conn, workspace_id=_CLIENT, account_ids=[by_row[1].account_entity_id, existing]
            ) == {
                by_row[1].account_entity_id: (project.project_id,),
                existing: (project.project_id,),
            }
            # the channel is how the account joined the project, and this one joined by import
            assert await _added_via(conn, by_row[1].account_entity_id) == ["imported"]
            assert await _added_via(conn, existing) == ["imported"]

    run_async(_run())


def test_import_row_landing_on_a_merged_loser_joins_the_survivor() -> None:
    """FI-2 H3 (spec §8.3), the merge-chain leg: a row whose strong key still points at an account
    that has since been merged away joins the *survivor* to the project, never the loser.

    Membership rides the ``surviving_id`` redirect the import applies before it writes, so the join
    can never be orphaned on a merged-away entity — the same guarantee ``mark_merged`` gives
    memberships that already existed, here for one created after the merge."""

    async def _run() -> None:
        async with rollback_conn(workspace_id=_CLIENT) as conn:
            client = await _client_entity(conn, "merged")
            icp = await build_confirmed_icp(conn, workspace_id=_CLIENT)
            project = await seed_project(conn, _CLIENT, name="Survivor project")
            loser = await insert_account_entity(
                conn,
                canonical_name="Old Name Ltd",
                primary_domain="mergedloser.example",
                status=AccountStatus.ACTIVE,
                workspace_id=_CLIENT,
            )
            survivor = await insert_account_entity(
                conn,
                canonical_name="Survivor Corp",
                primary_domain="survivor-merged.example",
                status=AccountStatus.ACTIVE,
                workspace_id=_CLIENT,
            )
            await embed_account(conn, loser)
            await embed_account(conn, survivor)
            await mark_merged(conn, EntityType.ACCOUNT, loser, survivor)

            result = await import_accounts(
                conn,
                [ImportRow(row_index=1, name="Old Name", domain="mergedloser.example")],
                icp,
                workspace_id=_CLIENT,
                client_entity_id=client,
                project_id=project.project_id,
            )

            (resolved,) = result.resolved
            # the row's domain is the *loser*'s strong key, so this is a deterministic hit on the
            # merged-away entity — the survivor id below is the redirect's doing, not a fresh admit
            assert resolved.resolution_method == "deterministic"
            assert resolved.account_entity_id == survivor  # redirected off the loser
            assert await accounts_for_project(
                conn, workspace_id=_CLIENT, project_id=project.project_id
            ) == (survivor,)
            assert await projects_for_accounts(
                conn, workspace_id=_CLIENT, account_ids=[loser, survivor]
            ) == {survivor: (project.project_id,)}
            assert await _added_via(conn, survivor) == ["imported"]
            assert await _added_via(conn, loser) == []

    run_async(_run())


def test_import_without_a_project_writes_no_membership() -> None:
    """A projectless (workspace-level) import is unchanged: the accounts land workspace-global with
    no project claiming them (spec §8.3) — membership-less accounts are a supported state."""

    async def _run() -> None:
        async with rollback_conn(workspace_id=_CLIENT) as conn:
            client = await _client_entity(conn, "nomember")
            icp = await build_confirmed_icp(conn, workspace_id=_CLIENT)
            project = await seed_project(conn, _CLIENT, name="Uninvolved project")
            rows = [ImportRow(row_index=1, name="Global Co", domain="globalco-nomember.example")]
            result = await import_accounts(
                conn, rows, icp, workspace_id=_CLIENT, client_entity_id=client
            )
            (acct,) = result.resolved
            assert (
                await projects_for_accounts(
                    conn, workspace_id=_CLIENT, account_ids=[acct.account_entity_id]
                )
                == {}
            )
            assert (
                await accounts_for_project(
                    conn, workspace_id=_CLIENT, project_id=project.project_id
                )
                == ()
            )

    run_async(_run())


def test_import_into_an_unknown_project_refuses_before_creating_any_account() -> None:
    """A project that is not this workspace's is refused up front, so the batch is all-or-nothing.

    The check cannot be left to the ``project_account`` composite FK: every row's admit + write
    phase runs in its own savepoint, so an FK violation would surface as a per-row "resolution write
    failed" and the batch would report a partially-imported success instead of failing loud.
    """

    async def _run() -> None:
        async with rollback_conn(workspace_id=_CLIENT) as conn:
            client = await _client_entity(conn, "badproject")
            icp = await build_confirmed_icp(conn, workspace_id=_CLIENT)
            other = await seed_project(conn, "tenant-elsewhere", name="Another tenant's project")
            rows = [ImportRow(row_index=1, name="Never Created", domain="nevercreated.example")]

            with pytest.raises(ImportProjectNotFound):
                await import_accounts(
                    conn,
                    rows,
                    icp,
                    workspace_id=_CLIENT,
                    client_entity_id=client,
                    project_id="prj-does-not-exist",
                )
            assert await _accounts_named(conn, "nevercreated.example") == 0

            # a real project of *another* workspace is equally unknown here
            with pytest.raises(ImportProjectNotFound):
                await import_accounts(
                    conn,
                    rows,
                    icp,
                    workspace_id=_CLIENT,
                    client_entity_id=client,
                    project_id=other.project_id,
                )
            assert await _accounts_named(conn, "nevercreated.example") == 0

    run_async(_run())


def test_import_review_task_carries_the_project_and_its_resolution_joins_it() -> None:
    """An import row that lands mid-band admits no entity, so it can join no project — the project
    rides the review task instead (FI-2 P1) and the human resolution joins the account it creates.
    An imported ambiguity therefore reaches the same project a clean import row would have."""

    async def _run() -> None:
        async with rollback_conn(workspace_id=_CLIENT) as conn:
            client = await _client_entity(conn, "reviewproject")
            icp = await build_confirmed_icp(conn, workspace_id=_CLIENT)
            project = await seed_project(conn, _CLIENT, name="Review project")
            existing = await insert_account_entity(
                conn,
                canonical_name="Globex Review Industries",
                primary_domain="globex-reviewproject.example",
                status=AccountStatus.ACTIVE,
                workspace_id=_CLIENT,
            )
            await embed_account(conn, existing)
            rows = [ImportRow(row_index=1, name="Globex Review Industries")]  # name-only → mid-band
            policy = DispositionPolicy(auto_merge_threshold=0.95, review_low_threshold=0.05)
            result = await import_accounts(
                conn,
                rows,
                icp,
                workspace_id=_CLIENT,
                client_entity_id=client,
                project_id=project.project_id,
                disposition_policy=policy,
            )
            (review,) = result.needs_review
            task = await get_task(conn, review.task_id)
            assert task is not None and task.project_id == project.project_id
            assert (
                await accounts_for_project(
                    conn, workspace_id=_CLIENT, project_id=project.project_id
                )
                == ()
            )

            new_id = await resolve_create_new_entity(conn, review.task_id, resolved_by="reviewer")
            assert await accounts_for_project(
                conn, workspace_id=_CLIENT, project_id=project.project_id
            ) == (new_id,)

    run_async(_run())
