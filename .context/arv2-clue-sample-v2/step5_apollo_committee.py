"""Step 5 — Apollo people search (0 credits) for the Lassie buying committee.

Per the Apollo contract trap: search by organization_ids AND by domain, then union. The response is
DEGRADED (obfuscated last names, has_email booleans) - a shortlist only, never claim-store truth.
"""

import json

from clue_lib import apollo, save_raw, total_spend

ORG_ID = "63174e0badba1b00014e22fa"
SENIORITIES = ["owner", "founder", "c_suite", "partner", "vp", "head", "director", "manager"]

by_org = apollo(
    "/mixed_people/api_search",
    label="apollo_people_by_org",
    method="POST",
    body={
        "organization_ids": [ORG_ID],
        "person_seniorities": SENIORITIES,
        "per_page": 50,
        "page": 1,
    },
    credits=0,
)

by_domain = apollo(
    "/mixed_people/api_search",
    label="apollo_people_by_domain",
    method="POST",
    body={
        "q_organization_domains_list": ["lassie.ai"],
        "per_page": 50,
        "page": 1,
    },
    credits=0,
)

seen = {}
for src, resp in (("organization_ids", by_org), ("domain", by_domain)):
    for p in resp.get("people") or []:
        pid = p.get("id")
        if pid in seen:
            seen[pid]["found_via"].append(src)
            continue
        org = p.get("organization") or {}
        seen[pid] = {
            "id": pid,
            "first_name": p.get("first_name"),
            "last_name": p.get("last_name"),
            "last_name_obfuscated": p.get("last_name_obfuscated"),
            "name": p.get("name"),
            "title": p.get("title"),
            "seniority": p.get("seniority"),
            "departments": p.get("departments"),
            "linkedin_url": p.get("linkedin_url"),
            "city": p.get("city"),
            "state": p.get("state"),
            "has_email": p.get("has_email"),
            "email_status": p.get("email_status"),
            "has_direct_phone": p.get("has_direct_phone"),
            "org_name": org.get("name"),
            "org_id": org.get("id"),
            "found_via": [src],
        }

rows = sorted(seen.values(), key=lambda r: (r.get("seniority") or "zz", r.get("title") or ""))
save_raw("apollo_committee_shortlist", rows)
print(
    "\npagination org:",
    json.dumps(by_org.get("pagination")),
    "| domain:",
    json.dumps(by_domain.get("pagination")),
)
print("union size:", len(rows), "\n")
for r in rows:
    print(
        f"  {r['first_name']} {r['last_name'] or r['last_name_obfuscated']} | {r['title']} | "
        f"sen={r['seniority']} | org={r['org_name']} | email={r['has_email']} | "
        f"via={'+'.join(r['found_via'])} | {r['linkedin_url']}"
    )
print("\ntotal spend $", total_spend())
