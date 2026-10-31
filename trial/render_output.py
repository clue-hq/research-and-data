"""Write one readable markdown file per trial account job: the agent's four answers, hypotheses
and people map (from its saved workspace), the dossier findings, and the account pages as the
page writer produced them, plus what code adds to Miscellaneous at read time.

    uv run python trial/render_output.py <out-dir> <job_id> [<job_id> ...]
"""
import asyncio, json, os, sys
from pathlib import Path
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from clue_storage.fs import FsStorage

ORDER = {"overview": ["what-they-do", "why-they-fit", "why-now", "buying-committee", "how-to-approach"],
         "insights": ["buying-signals", "money-and-momentum", "tools-they-already-use", "how-they-sell",
                      "watch-outs", "context-only", "miscellaneous"]}


def lines_of(parts, indent=""):
    out = []
    for p in parts or []:
        if isinstance(p, dict) and p.get("text"):
            tag = "" if p.get("kind") in (None, "fact") else f" _({p['kind']})_"
            out.append(f"{indent}- {p['text']}{tag}")
        elif isinstance(p, str):
            out.append(f"{indent}- {p}")
    return out


def render_block(body):
    out = []
    out += lines_of(body.get("intro"))
    for it in body.get("items") or []:
        head = it.get("h2") or it.get("h3") or it.get("title") or it.get("reason")
        if head: out.append(f"\n**{head}**")
        for k in ("body", "evidence", "text"):
            if isinstance(it.get(k), list): out += lines_of(it[k], "  ")
            elif isinstance(it.get(k), str): out.append(f"  - {it[k]}")
        for k, v in it.items():
            if k in ("h2", "h3", "title", "reason", "body", "evidence", "text", "id", "claimIds"): continue
            if isinstance(v, list) and v and isinstance(v[0], dict) and "text" in v[0]:
                out.append(f"  _{k}:_"); out += lines_of(v, "    ")
    for t in ("rows", "table"):
        for r in body.get(t) or []:
            out.append("- " + " | ".join(str(x.get("text", x)) if isinstance(x, dict) else str(x) for x in (r.values() if isinstance(r, dict) else r)))
    if body.get("gaps"):
        out.append("\n_Gaps shown:_"); out += lines_of(body["gaps"], "  ")
    return out


async def main(outdir, jobs):
    eng = create_async_engine(os.environ["CLUE_DATABASE_URL"]); st = FsStorage(os.environ["CLUE_STORAGE_FS_ROOT"])
    Path(outdir).mkdir(parents=True, exist_ok=True)
    async with eng.connect() as c:
        for jid in jobs:
            j = (await c.execute(text("""select j.*, a.canonical_name, a.primary_domain from arv2_research_job j
                 join account_entity a on a.id=j.account_entity_id where j.job_id=:j"""), {"j": jid})).mappings().one()
            ws, acct = j["workspace_id"], j["account_entity_id"]
            L = [f"# {j['canonical_name']} ({j['primary_domain']}): trial research output",
                 f"Job `{jid}` · status {j['status']} · {j['model_rounds']} model rounds · {j['tool_calls']} tool calls · "
                 f"${float(j['cost_usd']):.2f} · {round((j['finished_at']-j['started_at']).total_seconds()/60)} min · "
                 f"recipe {(j['input_refs'] or {}).get('quality_recipe_version')}"]
            # Agent workspace files (the real contents, not Langfuse's truncated copies).
            snap = (await c.execute(text("""select s.manifest_artifact_key from agent_workspace_snapshot s
                 join arv2_quality_execution e on 'research-quality-' || e.execution_id::text = s.thread_id
                 where s.workspace_id=:ws and e.job_id=:job order by s.updated_at desc"""), {"ws": ws, "job": jid})).scalars().all()
            files = {}
            for key in snap:
                man = json.loads(await st.get(key))
                for e in man["entries"]:
                    if e["path"] in ("outputs/account-assessment.md", "outputs/page-brief.md", "work/hypotheses.md", "work/people-map.md"):
                        body = (await st.get(f"{ws}/agent-workspace/{e['sha256']}")).decode()
                        files.setdefault(e["path"], []).append(body)
            def pick(path):
                stem = j["primary_domain"].split(".")[0].lower()
                names = {stem, stem[:3], j["canonical_name"].split()[0].lower()}
                cands = [b for b in files.get(path, []) if any(n in b.lower()[:400] for n in names)]
                return cands[0] if cands else None
            for path, title in (("outputs/page-brief.md", "1. The researcher's page brief (verdict and per-section messages)"),
                                ("outputs/account-assessment.md", "1b. The agent's account assessment (earlier rounds)"),
                                ("work/hypotheses.md", "2. Hypotheses, learning notes and outcomes"),
                                ("work/people-map.md", "3. People map and committee reasoning")):
                L += [f"\n---\n\n## {title}\n", pick(path) or "_(file not found)_"]
            # Pages.
            blocks = (await c.execute(text("""select page, section_key, body_json, cited_claim_ids from display_block
                 where workspace_id=:ws and subject_id=:a and superseded_at is null and page in ('overview','insights')"""),
                 {"ws": ws, "a": acct})).mappings().all()
            cited = {str(x) for b in blocks for x in (b["cited_claim_ids"] or [])}
            L.append("\n---\n\n## 4. The account pages, as the page writer produced them")
            for page in ("overview", "insights"):
                L.append(f"\n### {page.title()} page")
                bs = sorted([b for b in blocks if b["page"] == page],
                            key=lambda b: ORDER[page].index(b["section_key"]) if b["section_key"] in ORDER[page] else 99)
                for b in bs:
                    L.append(f"\n#### {b['section_key']}")
                    L += render_block(b["body_json"] if isinstance(b["body_json"], dict) else json.loads(b["body_json"]))
            # Findings and what code adds to Miscellaneous.
            claims = (await c.execute(text("""select id, value_json from claim where workspace_id=:ws and entity_id=:a
                 and field_key like '%research_finding' and superseded_by is null order by collected_at"""),
                 {"ws": ws, "a": acct})).mappings().all()
            unc = [cl for cl in claims if str(cl["id"]) not in cited]
            L.append(f"\n#### miscellaneous: added by code at read time ({len(unc)} findings no section cited)")
            for cl in unc:
                v = cl["value_json"] if isinstance(cl["value_json"], dict) else json.loads(cl["value_json"])
                L.append(f"- **{v.get('topic')}**: {v.get('finding')}")
            L.append(f"\n---\n\n## 5. All dossier findings ({len(claims)})")
            for cl in claims:
                v = cl["value_json"] if isinstance(cl["value_json"], dict) else json.loads(cl["value_json"])
                L.append(f"- **{v.get('topic')}**: {v.get('finding')}"
                         + (f"  \n  _Why it matters:_ {v['agent_interpretation']}" if v.get("agent_interpretation") else "")
                         + f"  \n  _{v.get('attribution')} · {v.get('time_context')}_")
            name = j["primary_domain"].split(".")[0]
            tag = os.environ.get("TRIAL_TAG", "round2b")
            Path(outdir, f"{tag}_{name}.md").write_text("\n".join(L))
            print("wrote", Path(outdir, f"{tag}_{name}.md"), len(claims), "findings,", len(unc), "uncited")

asyncio.run(main(sys.argv[1], sys.argv[2:]))
