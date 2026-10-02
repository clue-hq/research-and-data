"""B3 — the reputation / negatives pass, one cheap criticism-aimed search per top-3 account,
plus Agent A's requested falsification probe on the alternate (Arintra).

"None found" is a real, reportable answer. The point is not to find dirt; it is to know what NOT
to say, and to spot the negative that is actually an OPENER (a bad review of the tooling they use
today is an invitation; a layoff is a landmine).
"""

import json
import sys
import time

sys.path.insert(0, ".")
import b_lib as C  # noqa: E402

SEARCHES = [
    ("n_zafran", "Zafran Security criticism complaints layoffs employee reviews Glassdoor "
     "acquisition rumors churn negative customer feedback exposure management competitors"),
    ("n_cogent", "Cogent Security cogent.com criticism complaints negative reviews AI "
     "vulnerability management skepticism agentic AI security concerns customer churn"),
    ("n_harmonic", "Harmonic Security criticism complaints layoffs employee reviews negative "
     "feedback AI data security DLP competitors skepticism"),
    ("t_arintra", "Arintra hiring marketing GTM jobs 2026 Series B Define Ventures marketing "
     "team leadership autonomous medical coding go-to-market"),
]

t_all = time.time()
res = {}
for label, q in SEARCHES:
    t0 = time.time()
    out = C.exa({"query": q, "type": "auto", "numResults": 8,
                 "contents": {"text": {"maxCharacters": 1800}}},
                label=f"b3_{label}", est_usd=0.01)
    rows = [{"title": r.get("title"), "url": r.get("url"), "published": r.get("publishedDate"),
             "text": (r.get("text") or "")[:1500]} for r in (out.get("results") or [])]
    res[label] = {"query": q, "n": len(rows), "results": rows}
    C.timing_record(f"B3_{label}", time.time() - t0, "cheap negatives/probe search")
    print(f"\n=== {label} ({len(rows)})")
    for r in rows:
        print(f"   {r['title']}  [{r['published']}]\n      {r['url']}")
    time.sleep(1.1)

json.dump(res, open("b3_negatives.json", "w"), indent=2)
C.timing_record("B3_TOTAL", time.time() - t_all, "3 negatives + 1 arintra probe")
print(f"\nPHASE B3 {round(time.time()-t_all,1)}s spend={C.total_spend()} credits={C.total_credits()}")
