"""Write a recipe-32 job's published markdown dossier, its index and its commit history to markdown.

    uv run python trial/render_dossier.py <job_id[,job_id]> <out_dir>
"""
import asyncio, json, os, sys
from pathlib import Path
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from clue_storage.fs import FsStorage

async def main():
    eng = create_async_engine(os.environ["CLUE_DATABASE_URL"]); st = FsStorage(os.environ["CLUE_STORAGE_FS_ROOT"])
    out = Path(sys.argv[2]); out.mkdir(parents=True, exist_ok=True)
    async with eng.connect() as c:
        for jid in sys.argv[1].split(","):
            j = (await c.execute(text("""select job_id::text, workspace_id, status, started_at, finished_at,
                model_rounds, tool_calls, cost_usd, finalization_json->>'summary'
                from arv2_research_job where job_id::text like :p"""), {"p": jid + "%"})).first()
            rows = (await c.execute(text("""select reference_id, storage_key from artifact_reference
                where workspace_id=:ws and reference_kind='research_md_dossier' and reference_id like :p
                order by reference_id"""), {"ws": j[1], "p": j[0] + ":%"})).all()
            published = (await c.execute(text("""select reference_id from artifact_reference
                where workspace_id=:ws and reference_kind='research_md_dossier_published' and reference_id like :p"""),
                {"ws": j[1], "p": j[0] + ":%"})).scalars().all()
            commits = [json.loads(await st.get(k)) for _, k in rows]
            lines = [f"# Job {j[0][:8]}", "",
                     f"status {j[2]} · {(j[4]-j[3]).total_seconds()/60:.1f} min · {j[5]} model rounds · "
                     f"{j[6]} tool calls · ${float(j[7] or 0):.2f}", "", f"Summary: {j[8]}", "",
                     "## Commits", ""]
            for cm in commits:
                mark = " (published)" if f"{j[0]}:{cm['version']:010d}" in published else ""
                lines.append(f"- v{cm['version']}{mark} · {cm['committed_at'][11:19]} · "
                             f"{len(cm['findings'])} findings · {len(cm['dossier'].split())} words — {cm['message']}")
            if commits:
                last = commits[-1]
                lines += ["", "## Index", "", "```json", json.dumps(json.loads(last["index_raw"] or "{}"), indent=2), "```",
                          "", "---", "", last["dossier"]]
            (out / f"dossier_{j[0][:8]}.md").write_text("\n".join(lines))
            print(out / f"dossier_{j[0][:8]}.md", len(commits), "commits")

asyncio.run(main())
