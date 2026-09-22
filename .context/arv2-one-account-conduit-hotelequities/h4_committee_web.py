"""H4 — committee ground truth from the OPEN WEB FIRST (v3 protocol step 1).

AI Ark never sources a person. This script builds the candidate committee from: the merger and
appointment press, Hospitality Net / hotel-trade appointment notices, LinkedIn profiles surfaced
via Exa, and any executive interviews. Everything is target-locked to Hotel Equities
(hotelequities.com, Atlanta/Alpharetta GA) — same-name strangers are recorded and excluded.
"""
import json
import re
import sys
import time

sys.path.insert(0, ".")
import z_lib as C  # noqa: E402

QUERIES = [
    ("leadership", "Hotel Equities executive leadership team Atlanta Alpharetta CEO COO president "
                   "chief officer 2025 2026", 10),
    ("merger", "Hotel Equities Springboard Hospitality merger 2025 Ben Rafter chief executive "
               "announcement", 10),
    ("appointments_nov", "Hotel Equities November 2025 executive appointments division presidents "
                         "full service focused service lifestyle", 10),
    ("ops_leader", "\"Hotel Equities\" senior vice president operations OR \"vice president of "
                   "operations\" OR \"guest experience\" leader appointed", 10),
    ("tech_leader", "\"Hotel Equities\" chief information officer OR \"vice president of "
                    "technology\" OR \"information technology\" leader hotel systems", 10),
    ("commercial", "\"Hotel Equities\" chief commercial officer OR chief revenue officer OR "
                   "senior vice president sales marketing appointed", 10),
    ("li_profiles", "site:linkedin.com/in Hotel Equities Atlanta operations technology executive", 10),
    ("rafter_voice", "Ben Rafter Hotel Equities OR Springboard Hospitality interview podcast "
                     "technology hotels AI", 10),
]

t_all = time.time()
res = {}
for label, q, n in QUERIES:
    out = C.exa({"query": q, "type": "auto", "numResults": n,
                 "contents": {"text": {"maxCharacters": 2500}}}, label=f"h4_search_{label}")
    rows = [{"url": x.get("url"), "title": x.get("title"), "author": x.get("author"),
             "published": x.get("publishedDate"), "text_head": (x.get("text") or "")[:900]}
            for x in (out.get("results") or [])]
    res[label] = {"query": q, "cost_usd": (out.get("costDollars") or {}).get("total"),
                  "n": len(rows), "results": rows}
    print(f"\n[{label}] {len(rows)} results  cost={(out.get('costDollars') or {}).get('total')}")
    for x in rows:
        print(f"   - {x['published'] or '?':10.10s} {(x['title'] or '')[:95]}")
        print(f"     {x['url']}")

# ---- name/title harvest across everything returned (evidence, not conclusions) ----
NAME_TITLE = re.compile(
    r"([A-Z][a-z]+(?:\s+[A-Z]\.)?\s+[A-Z][a-zA-Z'\-]+)\s*,?\s*(?:as|the|has been named|was named|"
    r"named|appointed|promoted to)?\s*"
    r"((?:Co-)?Chairman|Chief [A-Z][a-z]+(?: [A-Z][a-z]+)? Officer|President[^,.\n]{0,40}|"
    r"(?:Executive |Senior |)Vice President[^,.\n]{0,45}|SVP[^,.\n]{0,40}|VP[^,.\n]{0,40}|"
    r"Chief Operating Officer|Chief Executive Officer|General Counsel|Managing Director)")
hits = {}
for label, blk in res.items():
    for x in blk["results"]:
        blob = f"{x['title'] or ''}. {x['text_head'] or ''}"
        if "hotel equities" not in blob.lower() and "springboard" not in blob.lower():
            continue
        for nm, ti in NAME_TITLE.findall(blob):
            nm = nm.strip()
            ti = re.sub(r"\s+", " ", ti).strip(" ,.")
            hits.setdefault(nm, {})
            hits[nm].setdefault(ti, [])
            if x["url"] not in hits[nm][ti]:
                hits[nm][ti].append(x["url"])

print("\n=== name/title candidates seen in the returned text (RAW, unverified) ===")
for nm, tis in sorted(hits.items(), key=lambda kv: -sum(len(v) for v in kv[1].values())):
    for ti, urls in tis.items():
        print(f"   {nm:28s} | {ti[:58]:58s} | {len(urls)} url(s)")

json.dump({"searches": res, "name_title_candidates": hits},
          open("h4_committee_web.json", "w"), indent=2)
C.timing_record("H4_committee_web", time.time() - t_all, f"{len(QUERIES)} exa searches")
print(f"\nH4 {round(time.time()-t_all,1)}s spend={C.total_spend()}")
