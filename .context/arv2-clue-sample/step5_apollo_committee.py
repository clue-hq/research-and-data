"""Step 5 — the buying committee: Apollo people search (0 credits) + people/match (1 credit each).

Known trap from the contract doc: domain-only people search on a small practice can miss the org,
so search BOTH by `organization_ids` (from the step-2 enrich) and by domain, then union.
`api_search` output is a DEGRADED shortlist (obfuscated last names) and is never claim-store truth.
"""

import json

from clue_lib import apollo

ORG_ID = "5500af3d7369642de9450100"
DOMAIN = "charlestongi.com"

SENIORITIES = ["owner", "founder", "c_suite", "partner", "vp", "head", "director", "manager"]


def show(tag, resp):
    people = resp.get("people") or []
    contacts = resp.get("contacts") or []
    print(f"  [{tag}] people={len(people)} contacts={len(contacts)} "
          f"pagination={json.dumps(resp.get('pagination') or {})}")
    for p in people + contacts:
        org = (p.get("organization") or {}).get("name") or p.get("organization_name")
        print(
            "   -",
            p.get("first_name"),
            p.get("last_name") or p.get("last_name_obfuscated"),
            "|",
            p.get("title"),
            "| org:",
            org,
            "| has_email:",
            p.get("has_email"),
            "| id:",
            p.get("id"),
        )
    return people + contacts


# --- 5a. by organization_ids (0 credits) ---
a = apollo(
    "/mixed_people/api_search",
    label="step5a_people_by_orgid",
    method="POST",
    body={
        "organization_ids": [ORG_ID],
        "person_seniorities": SENIORITIES,
        "per_page": 25,
        "page": 1,
    },
    credits=0,
)
by_org = show("by_org_id", a)

# --- 5b. by domain (0 credits) — union, per the known name-variant trap ---
b = apollo(
    "/mixed_people/api_search",
    label="step5b_people_by_domain",
    method="POST",
    body={
        "q_organization_domains_list": [DOMAIN],
        "per_page": 25,
        "page": 1,
    },
    credits=0,
)
by_domain = show("by_domain", b)

seen = {}
for p in by_org + by_domain:
    if p.get("id"):
        seen[p["id"]] = p
print(f"  UNION unique people: {len(seen)}")
json.dump(list(seen.values()), open("committee_shortlist.json", "w"), indent=2)
