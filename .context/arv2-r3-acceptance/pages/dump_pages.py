"""Dump the contract-v1 payloads the live frontend would read, straight from this worktree's store."""
import asyncio, json, sys, pathlib
import httpx
from httpx import ASGITransport
from clue_api.frontend_read import FRONTEND_READ_PREFIX
from clue_api.projections_app import create_projections_app
from clue_api.storage_wiring import build_storage_backend
from clue_config import load_settings
from clue_db import db_lifespan, transaction

WS = "ws_arv2_answer_key"
OUT = pathlib.Path(".context/arv2-r3-acceptance/pages")
PATHS = {
    "zafran-contacts": "/accounts/74d83176-f407-4d35-a9c2-25ad0a8bbf91/contacts?contract=v1",
    "semien-page": "/accounts/{cogent}/contacts/a9b153a0-161e-45b5-a104-904a355a5253?contract=v1",
    "nick-fisher-page": "/accounts/74d83176-f407-4d35-a9c2-25ad0a8bbf91/contacts/034de76e-06e7-48b2-8141-11aa664da79c?contract=v1",
    "cogent-contacts": "/accounts/{cogent}/contacts?contract=v1",
}

async def main() -> None:
    settings = load_settings(_env_file=None, frontend_read_enabled=True, arv2_display_generate_on_read=True, projections_auth_mode="local_header", auth_environment="local", auth_mode="local_fixture")
    storage = build_storage_backend(settings)
    async with db_lifespan(None) as engine:
        async with engine.connect() as conn:
            cogent = (await conn.execute(__import__("sqlalchemy").text("select id from account_entity where workspace_id=:w and primary_domain='cogent.com'"), {"w": WS})).scalar_one()
        app = create_projections_app(surface=None, tool_invoker=None, settings=settings, conn_factory=transaction, ingestion_storage=storage, manage_db_lifespan=False)
        async with httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://t", timeout=180) as client:
            for name, path in PATHS.items():
                url = FRONTEND_READ_PREFIX + path.replace("{cogent}", str(cogent))
                r = await client.get(url, headers={"X-Workspace-Id": WS})
                (OUT / f"{name}.json").write_text(r.text)
                print(name, r.status_code, len(r.text), "bytes")

asyncio.run(main())
