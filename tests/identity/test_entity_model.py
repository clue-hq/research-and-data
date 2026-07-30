"""M2.1 (ENG-100) — the account_entity / contact_entity tables + the entity store.

Every §M2.1 acceptance criterion has a dedicated test here, exercised against a live Postgres
(skips without one). Negative cases use ``begin_nested`` savepoints so the rolled-back outer
transaction survives a constraint violation (mirrors the claim-store harness).
"""

from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from clue_core import (
    AccountStatus,
    EntityType,
    ExtractionMethod,
    ResearchMode,
    account_claim,
    new_entity_id,
    new_run_id,
)
from clue_research.claimstore import insert_claim
from clue_research.identity import (
    MergeCycleError,
    canonical_member_ids,
    get_account,
    get_contact,
    get_entity,
    insert_account_entity,
    insert_contact_entity,
    mark_merged,
    resolve_alias,
    surviving_id,
)
from tests._workspace import seed_workspace

from .conftest import rollback_conn, run_async

pytestmark = pytest.mark.usefixtures("require_identity_db")


def test_tables_present_at_head_with_contract_columns() -> None:
    """Migrating up created account_entity and contact_entity with every §4 column."""

    async def _run() -> None:
        async with rollback_conn() as conn:
            for table, expected in (
                (
                    "account_entity",
                    {
                        "id",
                        "canonical_name",
                        "primary_domain",
                        "aliases",
                        "hq_geo",
                        "registry_ids",
                        "status",
                        "merged_into",
                        "canonical_version",
                        "workspace_id",
                        "created_at",
                        "updated_at",
                    },
                ),
                (
                    "contact_entity",
                    {
                        "id",
                        "account_entity_id",
                        "full_name",
                        "linkedin_url",
                        "verified_email",
                        "aliases",
                        "geo",
                        "jurisdiction",
                        "status",
                        "merged_into",
                        "canonical_version",
                        "workspace_id",
                        "created_at",
                        "updated_at",
                    },
                ),
            ):
                cols = {
                    r[0]
                    for r in (
                        await conn.execute(
                            text(
                                "SELECT column_name FROM information_schema.columns "
                                "WHERE table_name = :t"
                            ),
                            {"t": table},
                        )
                    ).all()
                }
                assert expected <= cols, f"{table} missing columns: {expected - cols}"
                if table == "account_entity":
                    assert "brand_id" not in cols

            account_constraints = {
                row[0]
                for row in (
                    await conn.execute(
                        text(
                            "SELECT conname FROM pg_constraint "
                            "WHERE conrelid = 'account_entity'::regclass"
                        )
                    )
                ).all()
            }
            assert "account_entity_brand_fk" not in account_constraints
            assert "account_entity_brand_needs_workspace" not in account_constraints

    run_async(_run())


def test_db_enum_matches_core_account_status() -> None:
    """The migration's entity_status labels stay in lock-step with core.AccountStatus (drift)."""

    async def _run() -> None:
        async with rollback_conn() as conn:
            labels = {
                r[0]
                for r in (
                    await conn.execute(
                        text(
                            "SELECT e.enumlabel FROM pg_type t JOIN pg_enum e "
                            "ON e.enumtypid = t.oid WHERE t.typname = 'entity_status'"
                        )
                    )
                ).all()
            }
            assert labels == {m.value for m in AccountStatus}

    run_async(_run())


def test_duplicate_normalized_primary_domain_violates_unique() -> None:
    """Two accounts with the same normalized primary_domain collide; the second insert raises."""

    async def _run() -> None:
        async with rollback_conn() as conn:
            ws = await seed_workspace(conn)
            await insert_account_entity(
                conn, canonical_name="Acme", primary_domain="https://www.acme.com/", workspace_id=ws
            )
            trans = await conn.begin_nested()
            with pytest.raises(IntegrityError):
                # Different surface form, same registrable domain → same normalized key.
                await insert_account_entity(
                    conn, canonical_name="Acme Corp", primary_domain="ACME.COM", workspace_id=ws
                )
            await trans.rollback()

    run_async(_run())


def test_duplicate_registry_duns_violates_unique() -> None:
    """Two accounts sharing a normalized registry_ids.DUNS collide (per-namespace uniqueness)."""

    async def _run() -> None:
        async with rollback_conn() as conn:
            ws = await seed_workspace(conn)
            await insert_account_entity(
                conn, canonical_name="Acme", registry_ids={"DUNS": "12-345-6789"}, workspace_id=ws
            )
            trans = await conn.begin_nested()
            with pytest.raises(IntegrityError):
                await insert_account_entity(
                    conn,
                    canonical_name="Other",
                    registry_ids={"duns": "123456789"},
                    workspace_id=ws,
                )
            await trans.rollback()

    run_async(_run())


def test_null_strong_keys_allowed_for_candidates() -> None:
    """Two candidate accounts with NULL primary_domain / empty registry_ids both insert."""

    async def _run() -> None:
        async with rollback_conn() as conn:
            ws = await seed_workspace(conn)
            a = await insert_account_entity(conn, canonical_name="Candidate One", workspace_id=ws)
            b = await insert_account_entity(conn, canonical_name="Candidate Two", workspace_id=ws)
            assert a != b
            assert (await get_account(conn, a)) is not None
            assert (await get_account(conn, b)) is not None

    run_async(_run())


def test_surviving_id_follows_three_hop_chain() -> None:
    """A→B→C resolves to C in one call; surviving_id of the survivor is itself."""

    async def _run() -> None:
        async with rollback_conn() as conn:
            ws = await seed_workspace(conn)
            a = await insert_account_entity(conn, canonical_name="A", workspace_id=ws)
            b = await insert_account_entity(conn, canonical_name="B", workspace_id=ws)
            c = await insert_account_entity(conn, canonical_name="C", workspace_id=ws)
            await mark_merged(conn, EntityType.ACCOUNT, a, b)
            await mark_merged(conn, EntityType.ACCOUNT, b, c)
            assert await surviving_id(conn, a, EntityType.ACCOUNT) == c
            assert await surviving_id(conn, b, EntityType.ACCOUNT) == c
            assert await surviving_id(conn, c, EntityType.ACCOUNT) == c

    run_async(_run())


def test_surviving_id_rejects_a_cycle() -> None:
    """A two-row cycle A→B→A is detected and errored (never infinite-looped)."""

    async def _run() -> None:
        async with rollback_conn() as conn:
            ws = await seed_workspace(conn)
            a = await insert_account_entity(conn, canonical_name="A", workspace_id=ws)
            b = await insert_account_entity(conn, canonical_name="B", workspace_id=ws)
            await mark_merged(conn, EntityType.ACCOUNT, a, b)
            await mark_merged(conn, EntityType.ACCOUNT, b, a)  # closes the cycle
            with pytest.raises(MergeCycleError):
                await surviving_id(conn, a, EntityType.ACCOUNT)

    run_async(_run())


def test_self_merge_rejected_at_write_time() -> None:
    """The no-self-merge CHECK blocks a 1-hop A→A cycle at the database."""

    async def _run() -> None:
        async with rollback_conn() as conn:
            ws = await seed_workspace(conn)
            a = await insert_account_entity(conn, canonical_name="A", workspace_id=ws)
            trans = await conn.begin_nested()
            with pytest.raises(IntegrityError):
                await conn.execute(
                    text(
                        "UPDATE account_entity SET status='merged', merged_into = id WHERE id = :id"
                    ),
                    {"id": a},
                )
            await trans.rollback()

    run_async(_run())


def test_contact_requires_valid_account_fk() -> None:
    """A contact_entity cannot be inserted under a non-existent account (FK enforced)."""

    async def _run() -> None:
        async with rollback_conn() as conn:
            ghost_account = new_entity_id()
            trans = await conn.begin_nested()
            with pytest.raises(IntegrityError):
                await insert_contact_entity(
                    conn, account_entity_id=ghost_account, full_name="Jane Doe"
                )
            await trans.rollback()

    run_async(_run())


def test_contact_strong_keys_unique_when_present() -> None:
    """linkedin_url / verified_email are partial-unique; NULLs are allowed."""

    async def _run() -> None:
        async with rollback_conn() as conn:
            ws = await seed_workspace(conn)
            account = await insert_account_entity(conn, canonical_name="Acme", workspace_id=ws)
            await insert_contact_entity(
                conn,
                account_entity_id=account,
                full_name="Jane",
                linkedin_url="https://www.linkedin.com/in/jane/",
                verified_email="JANE@acme.com",
            )
            trans = await conn.begin_nested()
            with pytest.raises(IntegrityError):
                # Same linkedin URL (trailing slash + case folded) → collision.
                await insert_contact_entity(
                    conn,
                    account_entity_id=account,
                    full_name="Jane (dup)",
                    linkedin_url="https://www.linkedin.com/in/jane",
                )
            await trans.rollback()
            # Two contacts with NULL strong keys both insert (candidates).
            c1 = await insert_contact_entity(conn, account_entity_id=account, full_name="A")
            c2 = await insert_contact_entity(conn, account_entity_id=account, full_name="B")
            assert c1 != c2

    run_async(_run())


def test_resolve_alias_by_domain_name_and_unknown() -> None:
    """resolve_alias hits on normalized domain and on a name-key alias; misses return None."""

    async def _run() -> None:
        async with rollback_conn() as conn:
            ws = await seed_workspace(conn)
            account = await insert_account_entity(
                conn,
                canonical_name="Acme Incorporated",
                primary_domain="acme.com",
                aliases=["Acme Labs"],
                workspace_id=ws,
            )
            acct = EntityType.ACCOUNT
            # Domain hit (different surface form).
            assert (
                await resolve_alias(conn, "https://acme.com/contact", acct, workspace_id=ws)
                == account
            )
            # Name-key hit on the canonical name (legal suffix stripped).
            assert await resolve_alias(conn, "ACME inc", acct, workspace_id=ws) == account
            # Alias hit.
            assert await resolve_alias(conn, "Acme Labs", acct, workspace_id=ws) == account
            # Unknown → None (no fuzzy fallback at this issue).
            assert await resolve_alias(conn, "Globex", acct, workspace_id=ws) is None
            assert await resolve_alias(conn, "unknown.example", acct, workspace_id=ws) is None

    run_async(_run())


def test_resolve_alias_follows_merge_to_survivor() -> None:
    """A strong-key hit on a merged loser resolves through to the live survivor."""

    async def _run() -> None:
        async with rollback_conn() as conn:
            ws = await seed_workspace(conn)
            loser = await insert_account_entity(
                conn, canonical_name="Old Acme", aliases=["oldacme"], workspace_id=ws
            )
            survivor = await insert_account_entity(
                conn, canonical_name="Acme", primary_domain="acme.com", workspace_id=ws
            )
            await mark_merged(conn, EntityType.ACCOUNT, loser, survivor)
            assert (
                await resolve_alias(conn, "oldacme", EntityType.ACCOUNT, workspace_id=ws)
                == survivor
            )

    run_async(_run())


def test_get_entity_returns_typed_record_and_surfaces_merged_into() -> None:
    """get_entity returns the typed record; a merged entity surfaces merged_into."""

    async def _run() -> None:
        async with rollback_conn() as conn:
            ws = await seed_workspace(conn)
            survivor = await insert_account_entity(conn, canonical_name="Survivor", workspace_id=ws)
            loser = await insert_account_entity(conn, canonical_name="Loser", workspace_id=ws)
            await mark_merged(conn, EntityType.ACCOUNT, loser, survivor)

            acct = await get_entity(conn, loser, EntityType.ACCOUNT)
            assert acct is not None and acct.status is AccountStatus.MERGED
            assert acct.merged_into == survivor  # the read surfaces it, does not follow it

            contact_account = await insert_account_entity(
                conn, canonical_name="Acme", workspace_id=ws
            )
            contact = await insert_contact_entity(
                conn,
                account_entity_id=contact_account,
                full_name="Jane",
                jurisdiction=None,
            )
            crec = await get_contact(conn, contact)
            assert crec is not None and crec.account_entity_id == contact_account
            assert crec.as_entity().entity_type is EntityType.CONTACT

    run_async(_run())


def test_canonical_version_tracks_visible_mutations_and_exact_merge_membership() -> None:
    """C7 identity hashes change once per canonical mutation and include only exact members."""

    async def _run() -> None:
        async with rollback_conn() as conn:
            workspace_id = await seed_workspace(conn)
            survivor = await insert_account_entity(
                conn,
                canonical_name="Canonical Target",
                primary_domain="canonical.example",
                workspace_id=workspace_id,
            )
            original = await get_account(conn, survivor)
            assert original is not None and original.canonical_version == 1

            await conn.execute(
                text("UPDATE account_entity SET updated_at = now() WHERE id = :id"),
                {"id": survivor},
            )
            bookkeeping = await get_account(conn, survivor)
            assert bookkeeping is not None and bookkeeping.canonical_version == 1

            await conn.execute(
                text(
                    "UPDATE account_entity "
                    "SET canonical_name = 'Canonical Target Incorporated' "
                    "WHERE id = :id"
                ),
                {"id": survivor},
            )
            renamed = await get_account(conn, survivor)
            assert renamed is not None and renamed.canonical_version == 2

            loser = await insert_account_entity(
                conn,
                canonical_name="Target Legacy",
                workspace_id=workspace_id,
            )
            await mark_merged(conn, EntityType.ACCOUNT, loser, survivor)
            merged = await get_account(conn, survivor)
            assert merged is not None and merged.canonical_version == 3
            assert set(
                await canonical_member_ids(
                    conn,
                    survivor,
                    EntityType.ACCOUNT,
                    workspace_id=workspace_id,
                )
            ) == {survivor, loser}

            foreign_workspace = await seed_workspace(conn, "identity-foreign-c7")
            foreign = await insert_account_entity(
                conn,
                canonical_name="Foreign Target",
                workspace_id=foreign_workspace,
            )
            assert foreign not in set(
                await canonical_member_ids(
                    conn,
                    survivor,
                    EntityType.ACCOUNT,
                    workspace_id=workspace_id,
                )
            )

    run_async(_run())


def test_claim_entity_id_stays_fk_free() -> None:
    """REGRESSION (locked decision 1): claim.entity_id has NO hard FK — a claim for an entity with
    no row inserts cleanly. A hard FK to account_entity would break this and every contact claim."""

    async def _run() -> None:
        async with rollback_conn() as conn:
            orphan_entity = new_entity_id()  # never inserted into any entity table
            claim = account_claim(
                entity_id=orphan_entity,
                field_key="account.recent_funding",
                value_json={"round": "B"},
                source_tier=1,
                extraction_method=ExtractionMethod.API,
                source_url="https://api.example.com/acme",
                confidence=0.9,
                run_id=new_run_id(),
                research_mode=ResearchMode.ACCOUNT_PROFILING,
            )
            claim_id = await insert_claim(conn, claim, validate_field=False)
            assert claim_id is not None

    run_async(_run())
