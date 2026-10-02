"""Z1b — AI Ark people: domain-scoped roster (size 12) + name-scoped committee lookups.

The title filter is broken (smoke-test G2), so the committee is fetched by name+domain.
NEVER persists profile.birth_date: it is dropped at parse time and stripped from raw/.
"""
import json, sys, time
sys.path.insert(0, ".")
import z_lib as C  # noqa: E402

BIRTH_KEYS = {"birth_date", "birthDate", "birthday"}


def scrub(obj):
    """Recursively drop any birth-date field. Applied before anything is written."""
    if isinstance(obj, dict):
        return {k: scrub(v) for k, v in obj.items() if k not in BIRTH_KEYS}
    if isinstance(obj, list):
        return [scrub(v) for v in obj]
    return obj


def row(p):
    pr = p.get("profile") or {}
    pos = p.get("position_groups") or []
    cur = pos[0] if pos else {}
    comp = cur.get("company") or {}
    return {
        "full_name": pr.get("full_name"), "title": pr.get("title"),
        "headline": pr.get("headline"),
        "linkedin": (p.get("link") or {}).get("linkedin"),
        "location": p.get("location"),
        "current_company": comp.get("name"),
        "current_company_domain": comp.get("domain") or comp.get("website"),
        "date": cur.get("date"), "ark_id": p.get("id"),
        "department": p.get("department"),
        "top_keys": sorted(p.keys()),
    }


t_all = time.time()
result = {}

print("== POST /v1/people  domain=zafran.io size=12 ==")
body = {"account": {"domain": {"any": {"include": ["zafran.io"]}}}, "page": 0, "size": 12}
r = C.ark("/v1/people", body, label="z1b_people_domain", est_credits=6.0)
out = scrub(r["_body"])
people = out.get("content") or []
result["domain_search"] = {"totalElements": out.get("totalElements"), "returned": len(people),
                           "credits": 0.5 * len(people), "rows": [row(p) for p in people]}
for rr in result["domain_search"]["rows"]:
    print(f"   {rr['full_name']} | {rr['title']} | {rr['current_company']} | {rr['linkedin']}")

NAMES = [("Vari Kaur", ["Vari Kaur", "Varinder Kaur"]),
         ("Nick Fisher", ["Nick Fisher", "Nicholas Fisher"]),
         ("Ben Seri", ["Ben Seri"])]
result["name_scoped"] = {}
for key, variants in NAMES:
    print(f"\n== POST /v1/people  fullName={variants} + domain=zafran.io size=3 ==")
    b = {"contact": {"fullName": {"any": {"include": {"mode": "STRICT", "content": variants}}}},
         "account": {"domain": {"any": {"include": ["zafran.io"]}}}, "page": 0, "size": 3}
    rr = C.ark("/v1/people", b, label=f"z1b_people_name_{key.replace(' ', '_').lower()}",
               est_credits=1.5)
    o = scrub(rr["_body"])
    ps = o.get("content") or []
    result["name_scoped"][key] = {"variants": variants, "http": rr["_http_status"],
                                  "totalElements": o.get("totalElements"),
                                  "returned": len(ps), "credits": 0.5 * len(ps),
                                  "rows": [row(p) for p in ps]}
    for x in result["name_scoped"][key]["rows"]:
        print(f"   {x['full_name']} | {x['title']} | {x['current_company']} | {x['linkedin']}")

json.dump(result, open("z1b_people.json", "w"), indent=2)
C.timing_record("Z1b_ark_people", time.time() - t_all, "domain roster + 3 name-scoped")
print(f"\nZ1b {round(time.time()-t_all,1)}s credits={C.total_credits()} spend={C.total_spend()}")
