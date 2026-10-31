"""Build the project's research context in the lane (rolled back, nothing kept) and diff it
against a production context manifest."""
import asyncio, json, os, sys
from clue_api.arv2.quality_context import build_context
from clue_config import Settings
from clue_storage.fs import FsStorage
from sqlalchemy.ext.asyncio import create_async_engine

async def main(prod_path):
    eng = create_async_engine(os.environ["CLUE_DATABASE_URL"])
    storage = FsStorage(os.environ["CLUE_STORAGE_FS_ROOT"])
    async with eng.connect() as conn:
        tx = await conn.begin()
        ctx = await build_context(conn, storage, workspace_id="ws_98f69f42a7e54391aafadfc602446119",
                                  project_id="prj_bcbca9a562a15149875c552222ee7c8f",
                                  product_selection_version=1)
        await tx.rollback()
    lane = json.loads(ctx.model_dump_json())
    prod = json.load(open(prod_path))
    for key in sorted(set(lane) | set(prod)):
        a, b = lane.get(key), prod.get(key)
        same = json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)
        print(f"{'same' if same else 'DIFF'}  {key}")
        if not same and key != "field_catalog":
            print("   lane:", json.dumps(a, sort_keys=True)[:400]); print("   prod:", json.dumps(b, sort_keys=True)[:400])
        if not same and key == "field_catalog":
            la = {f['field_key'] for f in a or []}; pb = {f['field_key'] for f in b or []}
            print(f"   lane {len(la)} fields, prod {len(pb)}; only lane: {sorted(la-pb)[:8]}; only prod: {sorted(pb-la)[:8]}")
asyncio.run(main(sys.argv[1]))
