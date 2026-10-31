"""Turn a lf_watch.py dump into a readable per-account timeline: searches, page reads, people
lookups, notes written, nominations, dossier steps, and any reasoning/text the model emitted."""
import json, sys, collections

rows = [json.loads(l) for l in open(sys.argv[1])]
KEEP = {"acquire_research_evidence", "write_file", "edit_file", "nominate_web_committee_candidate",
        "nominate_committee_candidate", "save_dossier_section", "update_dossier_findings",
        "validate_dossier", "finish_dossier", "write_todos", "finalize_turn"}

def parse(x):
    if isinstance(x, str):
        try: return json.loads(x)
        except Exception: return x
    return x

by_trace = collections.defaultdict(list)
for o in rows: by_trace[o["traceId"]].append(o)
for tid, obs in by_trace.items():
    obs.sort(key=lambda o: o["startTime"])
    label = tid[:8]
    for o in obs:
        if o["name"] == "acquire_research_evidence":
            a = parse(o.get("input")) or {}
            if isinstance(a, dict) and a.get("operation") == "lookup_company":
                label += " " + json.dumps(a.get("arguments"))[:60]; break
    print(f"\n######## trace {label}  ({len(obs)} obs, {obs[0]['startTime'][11:19]}–{obs[-1]['startTime'][11:19]})")
    reads = 0
    for o in obs:
        t = o["startTime"][11:19]
        if o["type"] == "GENERATION" and o["name"] == "GovernedAgentChatModel":
            out = parse(o.get("output")) or {}
            content = out.get("content") if isinstance(out, dict) else None
            for item in content if isinstance(content, list) else []:
                if isinstance(item, dict) and item.get("type") in ("reasoning", "text", "output_text"):
                    txt = item.get("text") or " ".join(s.get("text", "") for s in item.get("summary", []) if isinstance(s, dict))
                    if txt.strip(): print(f"{t}  [{item['type']}] {txt.strip()[:600]}")
            if isinstance(content, str) and content.strip(): print(f"{t}  [text] {content.strip()[:600]}")
        elif o["type"] == "TOOL" and o["name"] == "read_file":
            reads += 1
        elif o["type"] == "TOOL" and o["name"] in KEEP:
            a = parse(o.get("input"))
            if o["name"] == "acquire_research_evidence" and isinstance(a, dict):
                s = f"{a.get('operation')}: {json.dumps(a.get('arguments'), ensure_ascii=False)[:260]}"
            elif o["name"] in ("write_file", "edit_file") and isinstance(a, dict):
                s = f"{a.get('file_path')}: {(a.get('content') or a.get('new_string') or '')[:700]}"
            else:
                s = json.dumps(a, ensure_ascii=False)[:300]
            print(f"{t}  {o['name']} | {s}")
    print(f"   (+{reads} file reads)")
