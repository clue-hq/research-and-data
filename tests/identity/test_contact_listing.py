"""M2 — ``contact_ids_for_account`` (the committee-membership reader the VERIFICATION pass and the
M12 handoff iterate). DB-gated, rollback-isolated like the rest of the identity harness.

Proves it returns the **live** contacts under an account, ordered, and excludes (a) contacts of
*other* accounts and (b) merged-loser contacts (whose claims re-key to the survivor).
"""

from __future__ import annotations

import pytest

from clue_research.core import EntityType
from clue_research.identity import (
    contact_ids_for_account,
    insert_account_entity,
    insert_contact_entity,
    mark_merged,
)

from .conftest import rollback_conn, run_async

pytestmark = pytest.mark.usefixtures("require_identity_db")


def test_returns_live_contacts_under_the_account_only() -> None:
    async def _run() -> None:
        async with rollback_conn() as conn:
            acct = await insert_account_entity(
                conn, canonical_name="Acme", primary_domain="acme.com"
            )
            other = await insert_account_entity(
                conn, canonical_name="Globex", primary_domain="globex.com"
            )
            c1 = await insert_contact_entity(conn, account_entity_id=acct, full_name="Ada")
            c2 = await insert_contact_entity(conn, account_entity_id=acct, full_name="Grace")
            # a contact under a DIFFERENT account — must not appear
            await insert_contact_entity(conn, account_entity_id=other, full_name="Linus")

            ids = await contact_ids_for_account(conn, acct)
            assert set(ids) == {c1, c2}
            assert list(ids) == sorted(ids)  # deterministic order

    run_async(_run())


def test_excludes_merged_loser_contacts() -> None:
    async def _run() -> None:
        async with rollback_conn() as conn:
            acct = await insert_account_entity(
                conn, canonical_name="Acme", primary_domain="acme.com"
            )
            survivor = await insert_contact_entity(conn, account_entity_id=acct, full_name="Ada L.")
            loser = await insert_contact_entity(
                conn, account_entity_id=acct, full_name="Ada Lovelace"
            )
            await mark_merged(conn, EntityType.CONTACT, loser, survivor)

            ids = await contact_ids_for_account(conn, acct)
            assert survivor in ids
            assert loser not in ids  # the merged loser is excluded (its claims re-key to survivor)

    run_async(_run())


def test_empty_when_no_contacts() -> None:
    async def _run() -> None:
        async with rollback_conn() as conn:
            acct = await insert_account_entity(
                conn, canonical_name="Solo", primary_domain="solo.com"
            )
            assert await contact_ids_for_account(conn, acct) == ()

    run_async(_run())
