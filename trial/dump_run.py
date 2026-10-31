"""Dump trial account jobs (lane DB) to JSON in the same shape as the production dump:
jobs with their latest dossier and ledger, current claims and display blocks.

    uv run python trial/dump_run.py <job_id,job_id> > out.json
"""
import asyncio, json, os, sys
from datetime import datetime
from decimal import Decimal
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from clue_storage.fs import FsStorage

def d(v):
    if isinstance(v, datetime): return v.isoformat()
    if isinstance(v, Decimal): return float(v)
    return v if isinstance(v, (dict, list, int, float, type(None), str, bool)) else str(v)

async def rows(c, q, **p):
    return [{k: d(v) for k, v in m.items()} for m in (await c.execute(text(q), p)).mappings().all()]

async def main():
    eng = create_async_engine(os.environ["CLUE_DATABASE_URL"]); st = FsStorage(os.environ["CLUE_STORAGE_FS_ROOT"])
    out = {}
    async with eng.connect() as c:
        for jid in sys.argv[1].split(","):
            j = (await rows(c, "select job_id,run_id,workspace_id,account_entity_id,subject_type,status,started_at,finished_at,model_rounds,tool_calls,cost_usd,finalization_json from arv2_research_job where job_id=:j", j=jid))[0]
            k = (await c.execute(text("select storage_key from artifact_reference where workspace_id=:ws and reference_kind='research_json_dossier' and reference_id like :p order by reference_id desc limit 1"), {"ws": j["workspace_id"], "p": jid + ":%"})).scalar_one_or_none()
            if k: j["dossier"] = json.loads(await st.get(k))
            j["ledger"] = await rows(c, "select provider,operation,phase,cost_usd,outcome,extras_json from provider_call_ledger where entity_research_job_id::text=:j order by recorded_at", j=jid)
            a = j["account_entity_id"]
            o = {"jobs": [j], "names": []}
            o["claims"] = await rows(c, "select id,entity_id,field_key,value_json,source_url,source_tier,evidence_span,confidence,observed_at,verification_status,identity_binding,use_class,outreach_safe from claim where workspace_id=:ws and entity_id=:a and superseded_by is null order by field_key", ws=j["workspace_id"], a=a)
            o["display"] = await rows(c, "select subject_id,page,section_key,body_json,cited_claim_ids,generated_at from display_block where workspace_id=:ws and subject_id=:a and superseded_at is null order by page,section_key", ws=j["workspace_id"], a=a)
            out[a] = o
    print(json.dumps(out, default=str))
asyncio.run(main())
