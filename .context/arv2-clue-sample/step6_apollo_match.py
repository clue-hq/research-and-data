"""Step 6 — Apollo `people/match` on the two decision-makers (1 credit each, no phone reveal).

`reveal_phone_number` is deliberately NOT set: it requires an HTTPS webhook receiver we do not
have, and would cost +8 credits. Email + employment history only.
"""

import json
import sys

from clue_lib import apollo

DOMAIN = "charlestongi.com"

TARGETS = [
    ("step6a_match_tpunteney", {"first_name": "Thomas", "last_name": "Punteney", "domain": DOMAIN}),
    ("step6b_match_wpunteney", {"first_name": "Wanda", "last_name": "Punteney", "domain": DOMAIN}),
]

if len(sys.argv) > 1 and sys.argv[1] == "fallback":
    TARGETS = [
        (
            "step6c_match_fallback_priorauth",
            {"id": sys.argv[2]},
        ),
    ]

out = {}
for label, body in TARGETS:
    body = dict(body)
    body["reveal_personal_emails"] = False
    r = apollo("/people/match", label=label, method="POST", body=body, credits=1)
    person = r.get("person")
    if not person:
        print(f"  [{label}] NO PERSON MATCHED. keys={list(r.keys())}")
        print("   body:", json.dumps(r)[:400])
        continue
    out[label] = person
    print(f"  [{label}] MATCH:")
    for k in [
        "id",
        "name",
        "first_name",
        "last_name",
        "title",
        "seniority",
        "headline",
        "email",
        "email_status",
        "linkedin_url",
        "photo_url",
        "city",
        "state",
        "country",
        "departments",
        "subdepartments",
        "functions",
    ]:
        if person.get(k):
            print(f"    {k}: {person[k]}")
    org = person.get("organization") or {}
    if org:
        print(f"    organization.name: {org.get('name')} | id: {org.get('id')}")
    for job in person.get("employment_history") or []:
        print(
            "    employment:",
            job.get("title"),
            "@",
            job.get("organization_name"),
            "|",
            job.get("start_date"),
            "->",
            job.get("end_date"),
            "| current:",
            job.get("current"),
        )
    contact = person.get("contact") or {}
    if contact.get("phone_numbers"):
        print("    phones (already-known only):", json.dumps(contact["phone_numbers"])[:300])

json.dump(out, open("matched_contacts.json", "w"), indent=2)
