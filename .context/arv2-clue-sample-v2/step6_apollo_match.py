"""Step 6 — Apollo people/match on the two selected committee members (1 credit each).

Primary   : Steijn Pelle, CEO & Co-Founder  -> economic buyer (and de-facto growth owner: the open
            Head of Marketing req says the hire "partner[s] directly with Lassie's CEO, who scaled
            Robinhood's referral program as its first growth lead").
Secondary : the "Founding GTM" person surfaced by BOTH the organization_ids and the domain search
            (highest-confidence non-founder) -> champion / user.

No reveal_phone_number: it requires an HTTPS webhook we do not have (Apollo contract 3.4).
"""

import json

from clue_lib import apollo, save_raw, total_spend

shortlist = json.load(open("raw/apollo_committee_shortlist.json"))
by_title = {r["title"]: r for r in shortlist}

targets = [
    ("primary", by_title["CEO and Co-Founder"]),
    ("secondary", by_title["Founding GTM"]),
]

matched = []
for role, row in targets:
    resp = apollo(
        "/people/match",
        label=f"apollo_match_{role}",
        method="POST",
        body={"id": row["id"], "reveal_personal_emails": False},
        credits=1,
    )
    p = resp.get("person") or {}
    rec = {
        "committee_role": role,
        "apollo_id": p.get("id"),
        "name": p.get("name"),
        "first_name": p.get("first_name"),
        "last_name": p.get("last_name"),
        "title": p.get("title"),
        "headline": p.get("headline"),
        "seniority": p.get("seniority"),
        "departments": p.get("departments"),
        "subdepartments": p.get("subdepartments"),
        "functions": p.get("functions"),
        "email": p.get("email"),
        "email_status": p.get("email_status"),
        "linkedin_url": p.get("linkedin_url"),
        "twitter_url": p.get("twitter_url"),
        "github_url": p.get("github_url"),
        "photo_url": p.get("photo_url"),
        "city": p.get("city"),
        "state": p.get("state"),
        "country": p.get("country"),
        "employment_history": p.get("employment_history"),
        "organization_name": (p.get("organization") or {}).get("name"),
        "organization_domain": (p.get("organization") or {}).get("primary_domain"),
        "phone_numbers": (p.get("contact") or {}).get("phone_numbers"),
        "request_id": resp.get("request_id"),
    }
    matched.append(rec)
    print(
        f"  -> {rec['name']} | {rec['title']} | {rec['email']} ({rec['email_status']}) | "
        f"{rec['linkedin_url']}",
        flush=True,
    )
    hist = rec.get("employment_history") or []
    for h in hist[:12]:
        print(
            f"       {h.get('start_date')}..{h.get('end_date') or 'present'} "
            f"{h.get('title')} @ {h.get('organization_name')} (current={h.get('current')})"
        )

save_raw("apollo_matched_contacts", matched)
print("\ntotal spend $", total_spend())
