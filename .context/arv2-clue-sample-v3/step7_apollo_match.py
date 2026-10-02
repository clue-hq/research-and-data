"""Step 7 — Apollo as ENRICHMENT-ONLY on the five WEB-CONFIRMED committee members.

The v2 failure this fixes: v2 built the committee FROM Apollo's degraded free people-search, which
returned obfuscated surnames, no LinkedIn URLs, and staff of a same-name company. v3 never asks
Apollo who is on the committee. It hands Apollo five people it already confirmed on the open web
(company /company page, a16z, Sequoia, GlobeNewswire, the founders' own LinkedIn posts, the
company's own LinkedIn posts) and asks only for the verified email + employment history.

Matching key: `linkedin_url` (the strongest locator, taken from the confirming source itself) plus
`domain` for corroboration. HARD GATE: an Apollo record whose organization.primary_domain is not
probook.ai is DISCARDED, not admitted — the same-name trap that contaminated v2.

No reveal_phone_number (8 credits + an HTTPS webhook we do not have; Apollo contract 3.4).
"""

import json
import sys

sys.path.insert(0, ".")
import clue_lib as C  # noqa: E402

ACCOUNT_DOMAIN = "probook.ai"

# name, linkedin_url, clue persona, the NON-APOLLO url that confirmed them, and the confirming quote
CONFIRMED = [
    {
        "key": "eliadis",
        "name": "George Eliadis",
        "linkedin_url": "https://www.linkedin.com/in/george-eliadis",
        "persona": "economic_buyer",
        "role_on_committee": "Co-Founder & CEO — final approver on a GTM platform purchase",
        "confirm_url": "https://www.probook.ai/company",
        "confirm_quote": "George Eliadis\nCo-Founder & CEO",
    },
    {
        "key": "hoffman",
        "name": "Mark Hoffman",
        "linkedin_url": "https://www.linkedin.com/in/mark-hoffman-582a5741",
        "persona": "economic_buyer",
        "role_on_committee": "Chief Revenue Officer — owns the revenue number and the GTM budget",
        "confirm_url": "https://www.linkedin.com/posts/probook-ai_ten-years-ago-our-cro-mark-hoffman-hired-activity-7472694957506707456-MK6f",
        "confirm_quote": "Ten years ago, our CRO, Mark Hoffman, hired Aaron Churba for his first job out of college.",
    },
    {
        "key": "blumberg",
        "name": "Kate Blumberg",
        "linkedin_url": "https://www.linkedin.com/in/kibrady12",
        "persona": "champion",
        "role_on_committee": "Director of Growth — building the marketing org; the SDR req reports into her",
        "confirm_url": "https://www.linkedin.com/posts/kibrady12_im-excited-to-share-that-ive-joined-probook-activity-7475235473679077376-nv9z",
        "confirm_quote": "I’m excited to share that I’ve joined Probook to lead growth and build out the marketing organization.",
    },
    {
        "key": "churba",
        "name": "Aaron Churba",
        "linkedin_url": "https://www.linkedin.com/in/aaronloganchurba",
        "persona": "champion",
        "role_on_committee": "Director of Sales & Development — owns the outbound/SDR engine (day-to-day user)",
        "confirm_url": "https://www.linkedin.com/posts/probook-ai_ten-years-ago-our-cro-mark-hoffman-hired-activity-7472694957506707456-MK6f",
        "confirm_quote": "We’re excited to welcome Aaron to Probook as our Director of Sales &",
    },
    {
        "key": "zhang",
        "name": "Lewis Zhang",
        "linkedin_url": "https://www.linkedin.com/in/lewisfzhang",
        "persona": "technical_evaluator",
        "role_on_committee": "Co-Founder & CTO — data, integrations and security review",
        "confirm_url": "https://www.probook.ai/company",
        "confirm_quote": "Lewis Zhang\nCo-Founder & CTO",
    },
]

out = []
for m in CONFIRMED:
    resp = C.apollo(
        "/people/match",
        label=f"apollo_match_{m['key']}",
        method="POST",
        body={
            "linkedin_url": m["linkedin_url"],
            "name": m["name"],
            "domain": ACCOUNT_DOMAIN,
            "reveal_personal_emails": False,
        },
        credits=1,
    )
    p = resp.get("person") or {}
    org = p.get("organization") or {}
    org_domain = org.get("primary_domain")
    admitted = org_domain == ACCOUNT_DOMAIN
    rec = {
        **{k: m[k] for k in ("key", "name", "persona", "role_on_committee", "confirm_url", "confirm_quote")},
        "web_linkedin_url": m["linkedin_url"],
        "apollo_admitted": admitted,
        "apollo_reject_reason": None if admitted else f"organization.primary_domain={org_domain!r}",
        "apollo_id": p.get("id"),
        "apollo_name": p.get("name"),
        "apollo_title": p.get("title"),
        "apollo_headline": p.get("headline"),
        "seniority": p.get("seniority"),
        "departments": p.get("departments"),
        "subdepartments": p.get("subdepartments"),
        "functions": p.get("functions"),
        "email": p.get("email") if admitted else None,
        "email_status": p.get("email_status") if admitted else None,
        "apollo_linkedin_url": p.get("linkedin_url"),
        "city": p.get("city"),
        "state": p.get("state"),
        "country": p.get("country"),
        "employment_history": p.get("employment_history"),
        "organization_name": org.get("name"),
        "organization_domain": org_domain,
    }
    out.append(rec)
    print(
        f"  -> {m['name']}: admitted={admitted} title={p.get('title')!r} "
        f"email={rec['email']} ({rec['email_status']}) org={org.get('name')!r}/{org_domain}"
    )

C.save_raw("committee_enriched", out)
json.dump(out, open("committee.json", "w"), indent=2)
print("\ncredits spent this step: 5 | TOTAL cash:", C.total_spend())
