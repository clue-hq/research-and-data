"""A4e — emit the verbatim query/result appendix for discovery.md from the raw responses."""

import json
import time

import clue_lib as L

t0 = time.time()
lines = []


def block(title, rec, qkey="query_verbatim"):
    lines.append(f"### {title}")
    lines.append("")
    lines.append("```")
    lines.append(f"POST https://api.exa.ai/search")
    payload = rec.get("payload") or {}
    if payload:
        lines.append(json.dumps(payload, indent=2))
    else:
        lines.append(json.dumps({"query": rec[qkey], "type": "auto", "numResults": 5}, indent=2))
    lines.append("```")
    lines.append("")
    lines.append(
        f"`HTTP {rec['http']}` · **{rec['elapsed_s']}s** · **${rec['cost_usd']}** · "
        f"{len(rec['results'])} results returned"
    )
    lines.append("")
    lines.append("| # | URL (verbatim) | Title (verbatim) | publishedDate |")
    lines.append("|---|---|---|---|")
    for i, r in enumerate(rec["results"], 1):
        t = (r["title"] or "").replace("|", "\\|")
        lines.append(f"| {i} | `{r['url']}` | {t} | {r['publishedDate'] or '—'} |")
    lines.append("")


disc = json.load(open("discovery_raw.json"))
lines.append("## Appendix A — the 8 discovery queries, verbatim")
lines.append("")
for rec in disc:
    block(f"`{rec['label']}` — angle: *{rec['angle']}*", rec)

ver = json.load(open("verify_raw.json"))
lines.append("## Appendix B — the 10 gate-verification queries (H1 US / H2 Series A+), verbatim")
lines.append("")
for slug, rec in ver.items():
    rec = dict(rec)
    rec["payload"] = {
        "query": rec["query_verbatim"],
        "type": "auto",
        "numResults": 5,
        "contents": {"text": {"maxCharacters": 1500}},
    }
    block(f"`v_{slug}`", rec)

tb = json.load(open("tiebreak_raw.json"))
lines.append("## Appendix C — the 5 tie-break queries, verbatim")
lines.append("")
for label, rec in tb.items():
    block(f"`{label}`", rec)

open("discovery_appendix.md", "w").write("\n".join(lines))
print("wrote discovery_appendix.md", len("\n".join(lines)), "chars")
L.timing_record("A4e_discovery_doc", time.time() - t0, "verbatim appendix generation")
