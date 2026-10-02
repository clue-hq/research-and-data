"""B1d — the cheap gap-fills (<=2 per account, most accounts need 1) + one name-scoped AI Ark call.

Each gap-fill closes a load-bearing NOT FOUND from the deep report. Nothing speculative.
The Zafran roster slice (12 of 163) came back 100% sales — zero marketing — so the marketing org
is the one gap AI Ark could not close by roster; a name-scoped call gets the known VP Marketing.
"""

import json
import sys
import time

sys.path.insert(0, ".")
import b_lib as C  # noqa: E402

GAPS = [
    ("g_zafran_mktg", "Zafran Security marketing team Head of Growth Marketing Nick Fisher VP "
     "Marketing LinkedIn who leads demand generation zafran.io"),
    ("g_cogent_mktg", "Cogent Security Cameron Coles VP of Marketing Alexander Semien Head of "
     "Growth cogent.com marketing team who owns marketing budget"),
    ("g_harmonic_abm", "Harmonic Security Ana Corio Director of Demand Generation account based "
     "marketing manager hired harmonic.security marketing team 2026"),
    ("g_uptiq_agency", "Uptiq GrowthSpree ABM agency engagement 2026 still working together "
     "account based marketing program financial institutions"),
]

t_all = time.time()
res = {}
for label, q in GAPS:
    t0 = time.time()
    out = C.exa({"query": q, "type": "auto", "numResults": 8,
                 "contents": {"text": {"maxCharacters": 1800}}},
                label=f"b1d_{label}", est_usd=0.01)
    rows = [{"title": r.get("title"), "url": r.get("url"),
             "published": r.get("publishedDate"),
             "text": (r.get("text") or "")[:1400]}
            for r in (out.get("results") or [])]
    res[label] = {"query": q, "n": len(rows), "results": rows}
    C.timing_record(f"B1d_{label}", time.time() - t0, "cheap gap-fill search")
    print(f"\n=== {label} ({len(rows)} results)")
    for r in rows:
        print(f"   {r['title']}  [{r['published']}]\n      {r['url']}")
    time.sleep(1.1)

# name-scoped AI Ark for the one person the Zafran roster slice missed
t0 = time.time()
body = {"contact": {"fullName": {"any": {"include": {"mode": "SMART", "content": ["Nick Fisher"]}}}},
        "account": {"domain": {"any": {"include": ["zafran.io"]}}}, "page": 0, "size": 3}
out, status, el = C.ark("/v1/people", body, label="b1d_ark_nick_fisher", est_credits=1.5)
people = out.get("content") or []
C.ark_ledger("b1d_ark_nick_fisher", "POST /v1/people name-scoped zafran.io", status, el,
             0.5 * len(people), f"totalElements={out.get('totalElements')}")
fisher = []
for p in people:
    pr = p.get("profile") or {}
    pos = (p.get("position_groups") or [{}])[0]
    fisher.append({"full_name": pr.get("full_name"), "title": pr.get("title"),
                   "linkedin": (p.get("link") or {}).get("linkedin"),
                   "current_company": ((pos.get("company") or {}).get("name")),
                   "start": (pos.get("date") or {}).get("start")})
    print(f"   {fisher[-1]}")
res["ark_nick_fisher"] = {"returned": len(people), "people": fisher,
                          "totalElements": out.get("totalElements")}
C.timing_record("B1d_ark_nick_fisher", time.time() - t0, "name-scoped, size 3")

json.dump(res, open("b1d_gapfill.json", "w"), indent=2)
C.timing_record("B1d_TOTAL", time.time() - t_all, "4 exa gap-fills + 1 ark name search")
print(f"\nPHASE B1d {round(time.time()-t_all,1)}s spend={C.total_spend()} credits={C.total_credits()}")
