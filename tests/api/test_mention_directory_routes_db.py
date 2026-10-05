"""The @-mention directory over HTTP: ETag revalidation, project ordering, and server search."""

from __future__ import annotations

import pytest

from clue_core import AccountStatus
from clue_research.identity import insert_account_entity
from clue_research.membership import ensure_project_account
from clue_spine import create_project
from tests.api.test_home_project_bootstrap_db import (  # noqa: F401
    _app,
    _client,
    _seed,
    require_chat_db,
)
from tests.claimstore.conftest import migrated_db, rollback_conn  # noqa: F401
from tests.db.conftest import run_async

WS = "ws-mention-dir"
HEADERS = {"X-Workspace-Id": WS}


async def _account(conn, name: str, domain: str):
    return await insert_account_entity(
        conn,
        canonical_name=name,
        primary_domain=domain,
        status=AccountStatus.ACTIVE,
        workspace_id=WS,
    )


@pytest.mark.usefixtures("require_chat_db")
def test_the_directory_is_served_with_an_etag_and_revalidates_to_304() -> None:

    async def scenario() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            await _seed(conn, WS)
            northstar = await _account(conn, "Northstar Labs", "northstar.example")
            app, _storage = _app(conn)
            async with _client(app) as client:
                first = await client.get("/api/v1/mention-directory", headers=HEADERS)
                assert first.status_code == 200, first.text
                etag = first.headers["etag"]
                body = first.json()["data"]
                assert body["complete"] is True
                assert [e["object_id"] for e in body["entities"]] == [str(northstar)]
                assert "private" in first.headers["cache-control"]

                again = await client.get(
                    "/api/v1/mention-directory", headers={**HEADERS, "If-None-Match": etag}
                )
                assert again.status_code == 304
                assert again.content == b""
                assert again.headers["etag"] == etag

                await _account(conn, "Atrium Hospitality", "atrium.example")
                changed = await client.get(
                    "/api/v1/mention-directory", headers={**HEADERS, "If-None-Match": etag}
                )
                assert changed.status_code == 200
                assert changed.headers["etag"] != etag
                assert len(changed.json()["data"]["entities"]) == 2

    run_async(scenario())


@pytest.mark.usefixtures("require_chat_db")
def test_the_directory_lists_the_projects_accounts_first_and_refuses_a_foreign_project() -> None:

    async def scenario() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            brand = await _seed(conn, WS)
            older = await _account(conn, "Atrium Hospitality", "atrium.example")
            await _account(conn, "Northstar Labs", "northstar.example")
            project = await create_project(
                conn, workspace_id=WS, brand_id=brand.brand_id, name="Hotels"
            )
            await ensure_project_account(
                conn,
                workspace_id=WS,
                project_id=project.project_id,
                account_entity_id=older,
                added_via="manual",
            )
            app, _storage = _app(conn)
            async with _client(app) as client:
                response = await client.get(
                    "/api/v1/mention-directory",
                    params={"project_id": project.project_id},
                    headers=HEADERS,
                )
                assert response.status_code == 200, response.text
                assert response.json()["data"]["entities"][0]["object_id"] == str(older)
                foreign = await client.get(
                    "/api/v1/mention-directory",
                    params={"project_id": "prj_not_in_this_workspace"},
                    headers=HEADERS,
                )
                assert foreign.status_code == 404

    run_async(scenario())


@pytest.mark.usefixtures("require_chat_db")
def test_server_search_matches_by_name_and_domain_and_needs_two_characters() -> None:

    async def scenario() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            await _seed(conn, WS)
            atrium = await _account(conn, "Atrium Hospitality", "atrium.example")
            app, _storage = _app(conn)
            async with _client(app) as client:
                by_name = await client.get(
                    "/api/v1/mention-directory/search", params={"q": "atri"}, headers=HEADERS
                )
                assert by_name.status_code == 200, by_name.text
                assert [e["object_id"] for e in by_name.json()["data"]["entities"]] == [str(atrium)]
                by_domain = await client.get(
                    "/api/v1/mention-directory/search",
                    params={"q": "atrium.ex"},
                    headers=HEADERS,
                )
                assert [e["object_id"] for e in by_domain.json()["data"]["entities"]] == [
                    str(atrium)
                ]
                too_short = await client.get(
                    "/api/v1/mention-directory/search", params={"q": "a"}, headers=HEADERS
                )
                assert too_short.status_code == 422

    run_async(scenario())
