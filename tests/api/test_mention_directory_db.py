"""The composer's @-mention directory: every account and committee contact, light and cached.

2026-10-05: the @ tagger only offered the workspace's 50 newest accounts (and their committees),
filtered in the browser, so older accounts — Atrium, the 66th newest of 75 — could not be tagged
whatever was typed. The directory now carries every account and committee contact (names and ids
only), project accounts first, with an ETag so the browser re-checks cheaply; very large
workspaces fall back to server search.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import event

from clue_api.arv2.display.gather import committee_members, committee_members_for_accounts
from clue_api.chat.composer_context import list_composer_context_entities
from clue_api.chat.mention_directory import build_mention_directory, search_mention_directory
from clue_api.client_context_binding import bind_workspace_client
from clue_research.identity import insert_account_entity
from clue_research.membership import ensure_project_account
from tests._workspace import seed_project
from tests.arv2.display._seed import seed_display_fixture
from tests.claimstore.conftest import (  # noqa: F401
    migrated_db,
    require_claimstore_db,
    rollback_conn,
)
from tests.db.conftest import run_async


class _Statements:
    """Counts the SQL statements a block issues on one connection."""

    def __init__(self, conn: Any) -> None:
        self._conn, self.count = conn, 0

    def _hit(self, *_args: Any) -> None:
        self.count += 1

    def __enter__(self) -> _Statements:
        event.listen(self._conn.sync_connection, "before_cursor_execute", self._hit)
        return self

    def __exit__(self, *_exc: Any) -> None:
        event.remove(self._conn.sync_connection, "before_cursor_execute", self._hit)


def _ids(entities: Any, kind: str) -> list[str]:
    return [entity.object_id for entity in entities if entity.object_type == kind]


def test_the_batched_committee_matches_the_per_account_committee() -> None:
    async def _run() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            seeded = await seed_display_fixture(conn)
            accounts = [str(seeded.account), str(seeded.other_account)]
            batched = await committee_members_for_accounts(
                conn, workspace_id=seeded.workspace_id, account_ids=accounts
            )
            for account in accounts:
                single = await committee_members(
                    conn, workspace_id=seeded.workspace_id, account_id=account
                )
                assert batched.get(account, []) == single
            everyone = await committee_members_for_accounts(
                conn, workspace_id=seeded.workspace_id, account_ids=None
            )
            assert everyone == batched

    run_async(_run())


def test_the_batched_committee_costs_the_same_statements_for_any_number_of_accounts() -> None:
    async def _run() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            seeded = await seed_display_fixture(conn)
            with _Statements(conn) as one:
                await committee_members_for_accounts(
                    conn, workspace_id=seeded.workspace_id, account_ids=[str(seeded.account)]
                )
            for i in range(10):
                await insert_account_entity(
                    conn,
                    canonical_name=f"Extra {i}",
                    primary_domain=f"extra{i}.example",
                    workspace_id=seeded.workspace_id,
                )
            with _Statements(conn) as many:
                await committee_members_for_accounts(
                    conn, workspace_id=seeded.workspace_id, account_ids=None
                )
            assert many.count == one.count
            # The composer's bounded list no longer runs one committee query per account.
            with _Statements(conn) as listing:
                await list_composer_context_entities(conn, workspace_id=seeded.workspace_id)
            assert listing.count <= one.count + 4

    run_async(_run())


def test_the_directory_carries_every_account_and_committee_contact_beyond_fifty() -> None:
    async def _run() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            seeded = await seed_display_fixture(conn)
            for i in range(55):
                await insert_account_entity(
                    conn,
                    canonical_name=f"Older {i:02d}",
                    primary_domain=f"older{i}.example",
                    workspace_id=seeded.workspace_id,
                )
            directory = await build_mention_directory(
                conn, workspace_id=seeded.workspace_id, project_id=None
            )
            assert directory.complete
            accounts = _ids(directory.entities, "account")
            assert len(accounts) == 57
            assert {str(seeded.account), str(seeded.other_account)} <= set(accounts)
            contacts = set(_ids(directory.entities, "contact"))
            assert contacts == {str(seeded.nick), str(seeded.vari), str(seeded.outsider)}
            by_id = {entity.object_id: entity for entity in directory.entities}
            nick = by_id[str(seeded.nick)]
            assert nick.label == "Nick Fisher"
            assert nick.account_id == str(seeded.account)
            assert nick.account_name == "Zafran Security"
            assert by_id[str(seeded.account)].secondary_label == "zafran.io"

    run_async(_run())


def test_the_projects_own_accounts_come_first_and_the_workspace_client_never_appears() -> None:
    async def _run() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            seeded = await seed_display_fixture(conn)
            project = await seed_project(conn, seeded.workspace_id, name="Mentions")
            # Zafran is the OLDER account; as the project's target it still leads.
            await ensure_project_account(
                conn,
                workspace_id=seeded.workspace_id,
                project_id=project.project_id,
                account_entity_id=seeded.account,
                added_via="manual",
            )
            client = await insert_account_entity(
                conn,
                canonical_name="Clue Itself",
                primary_domain="cluehq.ai",
                workspace_id=seeded.workspace_id,
            )
            await bind_workspace_client(
                conn, workspace_id=seeded.workspace_id, client_entity_id=client
            )
            directory = await build_mention_directory(
                conn, workspace_id=seeded.workspace_id, project_id=project.project_id
            )
            accounts = _ids(directory.entities, "account")
            assert accounts[0] == str(seeded.account)
            assert str(client) not in accounts

    run_async(_run())


def test_the_etag_is_stable_until_the_directory_changes() -> None:
    async def _run() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            seeded = await seed_display_fixture(conn)
            first = await build_mention_directory(
                conn, workspace_id=seeded.workspace_id, project_id=None
            )
            again = await build_mention_directory(
                conn, workspace_id=seeded.workspace_id, project_id=None
            )
            assert first.etag == again.etag
            await insert_account_entity(
                conn,
                canonical_name="Newcomer",
                primary_domain="newcomer.example",
                workspace_id=seeded.workspace_id,
            )
            changed = await build_mention_directory(
                conn, workspace_id=seeded.workspace_id, project_id=None
            )
            assert changed.etag != first.etag

    run_async(_run())


def test_a_directory_over_the_threshold_is_marked_incomplete_and_keeps_project_accounts() -> None:
    async def _run() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            seeded = await seed_display_fixture(conn)
            project = await seed_project(conn, seeded.workspace_id, name="Huge")
            await ensure_project_account(
                conn,
                workspace_id=seeded.workspace_id,
                project_id=project.project_id,
                account_entity_id=seeded.account,
                added_via="manual",
            )
            for i in range(10):
                await insert_account_entity(
                    conn,
                    canonical_name=f"Bulk {i}",
                    primary_domain=f"bulk{i}.example",
                    workspace_id=seeded.workspace_id,
                )
            directory = await build_mention_directory(
                conn,
                workspace_id=seeded.workspace_id,
                project_id=project.project_id,
                max_entries=4,
            )
            assert not directory.complete
            assert len(directory.entities) <= 4
            assert _ids(directory.entities, "account")[0] == str(seeded.account)

    run_async(_run())


def test_server_search_finds_accounts_by_name_or_domain_and_committee_contacts_by_name() -> None:
    async def _run() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            seeded = await seed_display_fixture(conn)
            ws = seeded.workspace_id

            async def search(query: str) -> list[str]:
                found = await search_mention_directory(conn, workspace_id=ws, query=query)
                return [entity.object_id for entity in found]

            assert str(seeded.account) in await search("zafr")
            assert str(seeded.other_account) in await search("probook.ex")
            assert str(seeded.nick) in await search("nick f")
            # The committee rule holds in search too: no claims, merged, or another workspace.
            assert str(seeded.silent) not in await search("withoutclaims")
            assert str(seeded.merged) not in await search("duplicate")
            assert await search("zz-no-such-thing") == []

    run_async(_run())
