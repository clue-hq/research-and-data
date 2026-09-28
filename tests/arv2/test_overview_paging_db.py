"""The new overview path over real, tenant-scoped blocks and an unchanged strict claim gate."""

from __future__ import annotations

import json
from uuid import uuid4

import pytest
from sqlalchemy import text

from clue_api.arv2.read_tools import Arv2ReadRefused, read_account_overview, read_account_research
from clue_core import ExtractionMethod
from tests._workspace import seed_project
from tests.arv2.test_read_tools_db import VERIFYING, _seed_account, _seed_block, _seed_claim
from tests.claimstore.conftest import (  # noqa: F401
    migrated_db,
    require_claimstore_db,
    rollback_conn,
)
from tests.db.conftest import run_async

pytestmark = pytest.mark.usefixtures("require_claimstore_db")


def test_full_overview_traversal_keeps_source_labels_without_promoting_imported_claims() -> None:
    async def scenario() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            project = await seed_project(conn, "ws_overview_pages", name="Overview pages")
            account = await _seed_account(conn, project, "Account")
            claims: dict[str, str] = {}
            imported = await _seed_claim(
                conn,
                claims,
                project,
                account,
                label="import",
                field_key="account.strategic_moves",
                value="Imported plan",
                extraction_method=ExtractionMethod.LLM_SYNTHESIS,
            )
            await conn.execute(
                text("UPDATE claim SET verification_status = 'unverified' WHERE id=:id"),
                {"id": imported},
            )
            for index in range(6):
                await _seed_block(
                    conn,
                    project,
                    account,
                    section_key=f"section-{index}",
                    cited=(imported,),
                    body={
                        "intro": [f"Imported item {index}. " * 400],
                        "status": "unverified",
                        "source_scope": "workspace_private",
                    },
                )
            chunks = []
            offset = 0
            while True:
                page = await read_account_overview(
                    conn,
                    workspace_id=project.workspace_id,
                    account_entity_id=str(account),
                    offset=offset,
                    limit=2,
                )
                chunks.extend(page.overview)
                if page.next_offset is None:
                    break
                assert page.next_offset > offset
                offset = page.next_offset
            assert len({chunk.section_key for chunk in chunks}) == 6
            for index in range(6):
                body = json.loads(
                    "".join(
                        chunk.section_json
                        for chunk in chunks
                        if chunk.section_key == f"section-{index}"
                    )
                )
                assert body["body_json"]["status"] == "unverified"
                assert body["body_json"]["source_scope"] == "workspace_private"
                assert body["cited_claim_ids"] == [str(imported)]
            gated = await read_account_research(
                conn,
                workspace_id=project.workspace_id,
                account_entity_id=str(account),
                section="claims",
                settings=VERIFYING,
            )
            assert gated.claims == () and gated.excluded["unverified"] == 1
            status = await conn.scalar(
                text("SELECT verification_status FROM claim WHERE id=:id"), {"id": imported}
            )
            assert status == "unverified"

    run_async(scenario())


def test_overview_pages_refuse_foreign_missing_and_merged_accounts() -> None:
    async def scenario() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            local = await seed_project(conn, "ws_overview_pages", name="Local")
            foreign = await seed_project(conn, "ws_overview_pages_foreign", name="Foreign")
            foreign_account = await _seed_account(conn, foreign, "Foreign account")
            await _seed_block(
                conn, foreign, foreign_account, section_key="private", body={"secret": "foreign"}
            )
            survivor = await _seed_account(conn, local, "Survivor")
            merged = await _seed_account(conn, local, "Merged")
            await conn.execute(
                text(
                    "UPDATE account_entity SET merged_into=:survivor, status='merged' WHERE id=:merged"
                ),
                {"survivor": survivor, "merged": merged},
            )
            for account in (str(foreign_account), str(merged), str(uuid4()), "bad-id"):
                with pytest.raises(Arv2ReadRefused) as refused:
                    await read_account_overview(
                        conn,
                        workspace_id=local.workspace_id,
                        account_entity_id=account,
                        offset=1,
                        limit=1,
                    )
                assert refused.value.code == "account_not_found"
            with pytest.raises(Arv2ReadRefused) as empty:
                await read_account_overview(
                    conn, workspace_id=local.workspace_id, account_entity_id=str(survivor)
                )
            assert empty.value.code == "overview_not_written"

    run_async(scenario())
