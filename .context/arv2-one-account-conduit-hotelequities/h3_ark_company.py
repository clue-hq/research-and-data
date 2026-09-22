"""H3 — AI Ark company object for hotelequities.com (0.1 cr/result). FIELD INVENTORY source.

Only the company call runs here. People/email calls wait until the committee is confirmed from
the open web (the v3 protocol: AI Ark is enrichment-only, never the source of a person).
AI Ark calls are paced >=10.5s by z_lib and halt on 402/exhaustion.
"""
import json
import sys
import time

sys.path.insert(0, ".")
import z_lib as C  # noqa: E402

BIRTH = {"birth_date", "birthDate", "birthday"}


def scrub(o):
    if isinstance(o, dict):
        return {k: scrub(v) for k, v in o.items() if k not in BIRTH}
    if isinstance(o, list):
        return [scrub(v) for v in o]
    return o


t_all = time.time()

print("== GET /v1/credit (balance probe) ==")
r0 = C.ark("/v1/credit", None, label="h3_credit_before", method="GET", est_credits=0.0)
print("   ", r0["_http_status"], json.dumps(r0["_body"])[:300])

print("\n== POST /v1/companies domain=hotelequities.com size=3 ==")
body = {"account": {"domain": {"any": {"include": ["hotelequities.com"]}}}, "page": 0, "size": 3}
r = C.ark("/v1/companies", body, label="h3_companies_hotelequities", est_credits=0.3)
out = scrub(r["_body"]) if isinstance(r["_body"], dict) else {}
C.save_raw("h3_companies_hotelequities", {"_http_status": r["_http_status"],
                                          "_elapsed_s": r["_elapsed_s"],
                                          "_request_body": body, "_body": out})
comps = out.get("content") or []
print("   totalElements:", out.get("totalElements"), "returned:", len(comps))
for c in comps:
    s = c.get("summary") or {}
    lk = c.get("link") or {}
    fin = c.get("financial") or {}
    loc = (c.get("location") or {}).get("headquarter") or {}
    print(f"   -> {s.get('name')} | legal={s.get('legal_name')} | staff={(s.get('staff') or {}).get('total')} "
          f"| founded={s.get('founded_year')} | {loc.get('city')} | {lk.get('domain')}")
    print(f"      revenue={(fin.get('revenue') or {}).get('annual')}")
    print(f"      technologies={[t.get('name') for t in (c.get('technologies') or [])]}")
    print(f"      industries={c.get('industries')}")

json.dump({"totalElements": out.get("totalElements"), "companies": comps},
          open("h3_company.json", "w"), indent=2)
C.timing_record("H3_ark_company", time.time() - t_all, "credit probe + company search")
print(f"\nH3 {round(time.time()-t_all,1)}s credits={C.total_credits()} spend={C.total_spend()}")
