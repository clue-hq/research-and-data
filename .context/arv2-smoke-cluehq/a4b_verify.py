"""A4b — cheap Series-A+/US verification for the shortlist (H1 + H2 gates).

One Exa search per company, 5 results, 1500 chars of text each (~$0.012/company).
No deep-reasoning calls — Agent A stays cheap by contract.
"""

import json
import time

import clue_lib as L

t_phase = time.time()

SHORTLIST = [
    ("cogent_security", "Cogent Security AI autonomous cyber defense funding round investors headquarters"),
    ("oscilar", "Oscilar AI Risk Decisioning Neha Narkhede funding round Series A investors headquarters"),
    ("harmonic_security", "Harmonic Security AI governance funding Series A Series B investors headquarters"),
    ("zafran_security", "Zafran Security funding Series B investors headquarters location"),
    ("revenuecat", "RevenueCat funding Series C investors headquarters San Francisco"),
    ("arintra", "Arintra autonomous medical coding Series B funding investors headquarters"),
    ("translucent_health", "Translucent healthcare finance $27M Series A GV headquarters founders"),
    ("prosper_ai", "Prosper AI patient access automation $30M Series A a16z headquarters"),
    ("vendelux", "Vendelux event intelligence $50M funding round investors headquarters New York"),
    ("uptiq", "Uptiq AI financial AI platform for banks credit unions funding round headquarters"),
]

out = {}
for slug, q in SHORTLIST:
    t0 = time.time()
    resp = L.exa(
        {
            "query": q,
            "type": "auto",
            "numResults": 5,
            "contents": {"text": {"maxCharacters": 1500}},
        },
        label=f"v_{slug}",
    )
    out[slug] = {
        "query_verbatim": q,
        "http": resp.get("_http_status"),
        "elapsed_s": resp.get("_elapsed_s"),
        "cost_usd": (resp.get("costDollars") or {}).get("total"),
        "results": [
            {
                "url": r.get("url"),
                "title": r.get("title"),
                "publishedDate": r.get("publishedDate"),
                "text": r.get("text") or "",
            }
            for r in (resp.get("results") or [])
        ],
    }
    L.timing_record(f"A4b_verify_{slug}", time.time() - t0, "H1/H2 gate verification")
    time.sleep(1.1)

json.dump(out, open("verify_raw.json", "w"), indent=2)
el = time.time() - t_phase
L.timing_record("A4b_verification", el, f"{len(SHORTLIST)} cheap gate-verification searches")
print(f"A4b done in {el:.1f}s; total spend ${L.total_spend()}")
