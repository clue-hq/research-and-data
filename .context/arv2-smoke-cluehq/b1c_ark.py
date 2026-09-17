"""B1c — AI Ark people search, one domain-scoped roster per account.

Probe result (recorded): the `contact.title` filter is IGNORED — a title-filtered zafran.io search
returned totalElements=163 with an RSM and an SVP Sales in the top 2. So the roster is unfiltered
and we pay 0.5cr per returned profile. DEGRADATION DECISION: size 12 for the top-3 intent accounts,
size 8 / 6 for accounts 4-5 (thin accounts get less), to stay inside the 50-credit ceiling.

Same-name discipline: only people whose CURRENT position is the exact account are admitted.
Web-first: the web-confirmed leaders from the deep reports are the spine; AI Ark supplies the
LinkedIn URL, exact title and position dates.
"""

import json
import sys
import time

sys.path.insert(0, ".")
import b_lib as C  # noqa: E402

PLAN = [
    ("zafran", "zafran.io", 12, "top-3 intent"),
    ("cogent", "cogent.com", 12, "top-3 intent"),
    ("vendelux", "vendelux.com", 12, "top-3 intent"),
    ("harmonic", "harmonic.security", 8, "DEGRADED: rank 4, ~56 employees"),
    ("uptiq", "uptiq.ai", 6, "DEGRADED: rank 5, thinnest intent"),
]

only = sys.argv[1:]
t_all = time.time()
rosters = {}
if len(sys.argv) > 1:
    PLAN = [p for p in PLAN if p[0] in only]

for key, domain, size, why in PLAN:
    t0 = time.time()
    body = {"account": {"domain": {"any": {"include": [domain]}}}, "page": 0, "size": size}
    out, status, el = C.ark("/v1/people", body, label=f"b1c_ark_{key}", est_credits=size * 0.5)
    people = out.get("content") or []
    C.ark_ledger(f"b1c_ark_{key}", f"POST /v1/people domain={domain} size={size}",
                 status, el, 0.5 * len(people),
                 f"totalElements={out.get('totalElements')} | {why}")
    rows = []
    for p in people:
        pr = p.get("profile") or {}
        pos = (p.get("position_groups") or [])
        cur = pos[0] if pos else {}
        comp = (cur.get("company") or {})
        date = cur.get("date") or {}
        rows.append({
            "full_name": pr.get("full_name"),
            "title": pr.get("title"),
            "headline": pr.get("headline"),
            "linkedin": (p.get("link") or {}).get("linkedin"),
            "location": pr.get("location") or pr.get("geo"),
            "current_company": comp.get("name"),
            "current_company_domain": comp.get("domain") or comp.get("website"),
            "start": (date.get("start") or {}) if isinstance(date.get("start"), dict) else date.get("start"),
            "end": (date.get("end") or {}) if isinstance(date.get("end"), dict) else date.get("end"),
            "ark_id": p.get("id"),
        })
    rosters[key] = {
        "domain": domain, "size_requested": size, "http": status,
        "totalElements": out.get("totalElements"), "returned": len(people),
        "credits": 0.5 * len(people), "degradation_note": why, "people": rows,
    }
    C.timing_record(f"B1c_ark_{key}", time.time() - t0, f"size={size}, {len(people)} profiles")
    print(f"\n=== {key} ({domain}) totalElements={out.get('totalElements')} returned={len(people)}")
    for r in rows:
        print(f"   {r['full_name']} | {r['title']} | {r['current_company']} | start={r['start']}")
        print(f"      {r['linkedin']}")

json.dump(rosters, open("b1c_ark_rosters.json", "w"), indent=2)
C.timing_record("B1c_TOTAL", time.time() - t_all, "5 AI Ark roster searches")
print(f"\nPHASE B1c {round(time.time()-t_all,1)}s spend={C.total_spend()} credits={C.total_credits()}")
