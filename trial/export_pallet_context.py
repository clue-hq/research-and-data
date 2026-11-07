"""Read-only export of Pallet's research context from production (runs inside a prod worker container).

Writes JSON to stdout: rows of the spine tables for the Pallet workspace, the chosen accounts,
and the document blobs (base64). Nothing is written to production.
"""
import os, sys, json, base64, asyncio
from datetime import datetime, date
from decimal import Decimal
from uuid import UUID
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from clue_storage import storage_from_settings

# Pallet by default; another seller's workspace and project as the 2nd and 3rd arguments.
WS = sys.argv[2] if len(sys.argv) > 2 else "ws_98f69f42a7e54391aafadfc602446119"
PROJECT = sys.argv[3] if len(sys.argv) > 3 else "prj_bcbca9a562a15149875c552222ee7c8f"
DOMAINS = sys.argv[1].split(",")

def enc(v):
    if isinstance(v, (datetime, date)): return {"__dt__": v.isoformat()}
    if isinstance(v, Decimal): return {"__dec__": str(v)}
    if isinstance(v, UUID): return str(v)
    if isinstance(v, (bytes, memoryview)): return {"__b64__": base64.b64encode(bytes(v)).decode()}
    return v

async def rows(c, sql, **p):
    r = await c.execute(text(sql), p)
    return [{k: enc(v) for k, v in m.items()} for m in r.mappings().all()]

async def main():
    eng = create_async_engine(os.environ["CLUE_DATABASE_URL"]); st = storage_from_settings()
    out = {}
    async with eng.connect() as c:
        await c.execute(text("SET TRANSACTION READ ONLY"))
        out["workspace"] = await rows(c, "select * from workspace where workspace_id=:ws", ws=WS)
        out["brand"] = await rows(c, "select * from brand where workspace_id=:ws", ws=WS)
        out["product"] = await rows(c, "select * from product where workspace_id=:ws", ws=WS)
        out["project"] = await rows(c, "select * from project where project_id=:p", p=PROJECT)
        out["project_product"] = await rows(c, "select * from project_product where project_id=:p", p=PROJECT)
        out["brand_knowledge_document"] = await rows(c, "select * from brand_knowledge_document where workspace_id=:ws", ws=WS)
        out["project_icp_pin"] = await rows(c, "select * from project_icp_pin where project_id=:p", p=PROJECT)
        out["account_entity"] = await rows(c, "select * from account_entity where workspace_id=:ws and primary_domain = any(:d)", ws=WS, d=DOMAINS)
        ids = [r["id"] for r in out["account_entity"]]
        out["project_account"] = await rows(c, "select * from project_account where project_id=:p and account_entity_id::text = any(:ids)", p=PROJECT, ids=ids)
        users = set()
        for t in out.values():
            for r in t:
                for k, v in r.items():
                    if k.endswith("user_id") and isinstance(v, str): users.add(v)
        out["platform_user"] = await rows(c, "select * from platform_user where user_id = any(:u)", u=sorted(users))
        keys = sorted({r["artifact_key"] for r in out["brand_knowledge_document"] if r.get("artifact_key")})
        out["artifact"] = await rows(c, "select * from artifact where storage_key = any(:k)", k=keys)
        blobs = {}
        for k in keys:
            try: blobs[k] = base64.b64encode(await st.get(k)).decode()
            except Exception as e: blobs[k] = {"error": repr(e)}
        out["__blobs__"] = blobs
    print(json.dumps(out))
asyncio.run(main())
