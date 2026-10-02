"""The recall measurement against the real answer key and the real R2 run — reads only.

The Zafran answer key is a loaded fixture (66 account claims under one run) and the R2 live run is
the thing being graded, so both tests read rows that already exist and assert *shape*, never the
measurement itself: the numbers are the output, and pinning them here would turn a measurement
into a fixture.
"""

from __future__ import annotations

from uuid import UUID

import pytest
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_api.arv2.answer_key_recall import match_claims, people_keys, zafran_keys
from clue_core import EntityId, EntityType, RunId
from clue_research.claimstore import WorkspaceScope, claims_for_runs

# The claim-store harness lives in a sibling test package; a fixture is only visible to a module
# that imports it, so re-export both (``require_claimstore_db`` depends on ``migrated_db``).
from tests.claimstore.conftest import (  # noqa: F401
    migrated_db,
    require_claimstore_db,
    rollback_conn,
)
from tests.db.conftest import run_async

pytestmark = pytest.mark.usefixtures("require_claimstore_db")

WORKSPACE = "ws_arv2_answer_key"
#: The R2 live run whose claims are the thing being graded, and its Zafran account.
R2_RUN_ID = RunId(UUID("a0021ecf-8396-5f41-b4aa-eb8de755839a"))
ZAFRAN_ACCOUNT_ID = EntityId(UUID("74d83176-f407-4d35-a9c2-25ad0a8bbf91"))


async def _skip_unless_loaded(conn: AsyncConnection) -> list:  # type: ignore[type-arg]
    keys = await zafran_keys(conn, workspace_id=WORKSPACE)
    if not keys:
        pytest.skip(
            "this database has no loaded Zafran answer key; "
            "run scripts/load_arv2_answer_key.py against it first"
        )
    return keys


def test_the_loaded_zafran_answer_key_is_66_account_keys() -> None:
    async def scenario() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            keys = await _skip_unless_loaded(conn)
            assert len(keys) == 66
            assert all(key.source_row_id is not None for key in keys)
            assert all(key.field_key.startswith(("core.", "account.")) for key in keys)
            # A pipe-joined key would have been loaded as two claims sharing one source row; the
            # alternatives are read back off the marker the loader stamped, never invented.
            assert all("|" not in alternative for key in keys for alternative in key.alternatives)

    run_async(scenario())


def test_the_r2_run_is_graded_against_all_66_zafran_keys() -> None:
    async def scenario() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            keys = await _skip_unless_loaded(conn)
            run_claims = [
                claim
                for claim in await claims_for_runs(
                    conn, [R2_RUN_ID], scope=WorkspaceScope.for_workspace(WORKSPACE)
                )
                if claim.entity_id == ZAFRAN_ACCOUNT_ID and claim.entity_type is EntityType.ACCOUNT
            ]
            if not run_claims:
                pytest.skip("this database has no R2 run a0021ecf… to grade")
            report = match_claims(keys, run_claims, account="zafran")
            assert report.keys == 66
            assert report.exact + report.partial + report.field_only + report.missing == 66
            assert 0.0 <= report.recall() <= 1.0
            assert sum(hits for hits, _ in report.by_section().values()) == (
                report.exact + report.partial
            )

    run_async(scenario())


def test_the_loaded_people_answer_key_is_122_keys_over_the_ten_people() -> None:
    """The person-depth key is read back per contact — one bundle each, in row order."""

    async def scenario() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            grouped = await people_keys(conn, workspace_id=WORKSPACE)
            if not grouped:
                pytest.skip(
                    "this database has no loaded person-depth answer key; "
                    "run scripts/load_arv2_answer_key.py against it first"
                )
            assert len(grouped) == 10
            assert sum(len(keys) for keys in grouped.values()) == 122
            for keys in grouped.values():
                assert all(key.field_key.startswith("contact.") for key in keys)
                assert all(key.source_row_id is not None for key in keys)
                # Grouped per contact, and each bundle ordered by the answer key's own row ids so
                # two runs of the measurement read alike.
                assert [key.source_row_id for key in keys] == sorted(
                    str(key.source_row_id) for key in keys
                )
                assert all("|" not in alt for key in keys for alt in key.alternatives)
            # Every row id is prefixed with its own person, so no bundle carries another's rows.
            assert all(
                len({str(key.source_row_id).rsplit("-", 1)[0] for key in keys}) == 1
                for keys in grouped.values()
            )

    run_async(scenario())
