"""Render the result tables into REPORT.md between the TABLES markers. Re-run after --judge / --report."""
import json, re, pathlib, statistics as st
recs = [json.loads(l) for l in open("results.jsonl") if l.strip()]
recs = [r for r in recs if r["rep"] in (1, 2)]
def J(r): return ((r.get("judge") or {}).get("scores") or {})
def avg(xs):
    xs = [x for x in xs if x is not None]; return round(st.mean(xs), 2) if xs else None
def fmt(x, d=2):
    return "—" if x is None else (f"{x:.{d}f}" if isinstance(x, float) else str(x))
NAMES = {"luna": "gpt-5.6-luna", "muse-glimmer": "meta/muse-glimmer-30b", "muse-1.3c": "meta/muse-spark-1.3-contributor", "gpt-5-nano": "gpt-5-nano",
         "gpt-5-mini": "gpt-5-mini", "gemini-2.5-fl": "gemini-2.5-flash-lite", "deepseek-v4-fl": "deepseek-v4-flash", "qwen3.7-flash": "qwen3.7-flash",
         "glm-5.3-flash": "glm-5.3-flash", "mistral-small": "mistral-small-2603", "llama-4-mav": "llama-4-maverick"}
PRICE = {"luna": "0.20 / 1.20", "muse-glimmer": "0.30 / 1.10", "muse-1.3c": "0.10 / 0.20", "gpt-5-nano": "0.05 / 0.40", "gpt-5-mini": "0.25 / 2.00",
         "gemini-2.5-fl": "0.10 / 0.40", "deepseek-v4-fl": "0.089 / 0.177", "qwen3.7-flash": "0.03 / 0.13", "glm-5.3-flash": "0.075 / 0.25",
         "mistral-small": "0.15 / 0.60", "llama-4-mav": "0.20 / 0.70"}
out = []
# ---- Table A: Luna per rep
out.append("### Table A — Luna, three ways of calling it (every run)\n")
out.append("| page | mode | rep | cost | calls | latency total / longest call | prompt tok | cached tok | output tok | judge /10 | faith /5 | off-recipe cites | ids typed in prose | items |")
out.append("|---|---|---|---|---|---|---|---|---|---|---|---|---|---|")
for r in sorted([r for r in recs if r["model"] == "luna"], key=lambda r: (r["page"] != "contact", r["mode"] != "whole", r["mode"], r["rep"])):
    m = r["metrics"]; j = J(r)
    out.append(f"| {r['page']} | {r['mode']} | r{r['rep']} | ${r['cost_usd']:.4f} | {r['n_calls']} | {r['latency_sum_s']}s / {r['latency_max_s']}s | {r['prompt_tokens']:,} | {r['cached_tokens']:,} | {r['completion_tokens']:,} | {fmt(j.get('overall'))} | {fmt(j.get('faithfulness'))} | {m['off_recipe']} | {m.get('ids_in_text',0)} | {m['items']} |")
# ---- Table B: models whole-page, per page
for page in ("contact", "insights"):
    out.append(f"\n### Table B-{page} — every model, whole page in one call (mean of 2 runs)\n")
    out.append("| model | $/M in / out | cost per page | latency | usable JSON | judge /10 | faith /5 | action /5 | unsafe leaks | quotes not verbatim | numbers not in payload | off-recipe cites | ids typed in prose | items |")
    out.append("|---|---|---|---|---|---|---|---|---|---|---|---|---|---|")
    rows = []
    for mk in NAMES:
        rs = [r for r in recs if r["model"] == mk and r["mode"] == "whole" and r["page"] == page]
        if not rs: continue
        M = [r["metrics"] for r in rs]; Js = [J(r) for r in rs]
        rows.append((avg([j.get("overall") for j in Js]) or 0, mk, rs, M, Js))
    for _, mk, rs, M, Js in sorted(rows, key=lambda x: -x[0]):
        ok = sum(1 for r in rs if r["json_ok"] and r["metrics"]["items"] > 0)
        out.append(f"| {NAMES[mk]} | {PRICE[mk]} | ${avg([r['cost_usd'] for r in rs]):.4f} | {fmt(avg([r['latency_sum_s'] for r in rs]),0)}s | {ok}/{len(rs)} | {fmt(avg([j.get('overall') for j in Js]))} | {fmt(avg([j.get('faithfulness') for j in Js]))} | {fmt(avg([j.get('actionability') for j in Js]))} | {fmt(avg([m['unsafe_leaks'] for m in M]))} | {fmt(avg([m['quote_violations'] for m in M]))} / {fmt(avg([m['quotes_total'] for m in M]),0)} | {fmt(avg([m['numbers_not_in_payload'] for m in M]))} / {fmt(avg([m['numbers_total'] for m in M]),0)} | {fmt(avg([m['off_recipe'] for m in M]))} | {fmt(avg([m.get('ids_in_text',0) for m in M]))} | {fmt(avg([m['items'] for m in M]),0)} |")
# ---- Table C: judge worst problems, one line per model (contact page, r2)
out.append("\n### Table C — the judge's single worst problem per model (contact page, run 2)\n")
out.append("| model | worst problem |")
out.append("|---|---|")
for mk in NAMES:
    rs = [r for r in recs if r["model"] == mk and r["mode"] == "whole" and r["page"] == "contact" and r["rep"] == 2]
    if rs and J(rs[0]).get("worst_problem"):
        out.append(f"| {NAMES[mk]} | {J(rs[0])['worst_problem'][:260].replace('|','/')} |")
gen = sum(r["cost_usd"] for r in recs); jud = sum(((r.get("judge") or {}).get("judge_cost_usd") or 0) + ((r.get("judge_v1") or {}).get("judge_cost_usd") or 0) for r in recs)
out.append(f"\nSpend: generation ${gen:.3f} across {len(recs)} page runs; judging ${jud:.2f}.")
tables = "\n".join(out)
p = pathlib.Path("REPORT.md"); s = p.read_text()
s = re.sub(r"<!-- TABLES -->.*?<!-- /TABLES -->", "<!-- TABLES -->\n" + tables + "\n<!-- /TABLES -->", s, flags=re.S)
p.write_text(s); print("tables rendered:", len(out), "lines")
