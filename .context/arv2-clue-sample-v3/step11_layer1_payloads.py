"""Step 11 — LAYER 1: render this run's claims AS the real production payloads.

Deterministic Python, no model. Every shape below is read off the as-built contract, not invented:

  * `apps/frontend/src/features/accounts/model/account.ts`          -> AccountSchema (list row)
  * `apps/frontend/src/features/accounts/model/account-detail.ts`   -> AccountDetailSchema
  * `apps/frontend/src/features/accounts/model/account-contact.ts`  -> AccountContactSummary/Detail
  * `apps/frontend/src/features/accounts/model/vocabulary.ts`       -> Persona/Freshness enums
  * `platform/api/clue_api/frontend_read/accounts_list.py`          -> WireModel (camelCase alias)
  * `platform/api/clue_api/frontend_read/account_detail.py`         -> NeutralFact/RelativeFact/
                                                                      CommitteeMemberRow/Coverage
  * `platform/api/clue_api/frontend_read/contacts.py`               -> ContactRow/GovernedFact/
                                                                      EvidenceChip/ContactSignals
  * `libs/clue-core/clue_core/contact_research.py`                  -> CONTACT_PROFESSIONAL_FIELD_KEYS
  * `apps/frontend/docs/api-contracts/accounts.md` §"As-built ... (FI-2 slice 1)"

Anything this run produced that the contract has NO slot for is emitted into a parallel
`_PROPOSED_SLOTS` block, never silently folded into a real field.
"""

import json
import uuid
from collections import defaultdict

RUN_AT = "2026-08-26T21:40:00Z"
WORKSPACE = "ws_clue_sample"
PROJECT_ID = "prj_clue_seriesa_verticalai"
PROJECT_NAME = "Series A vertical-AI — fragmented SMB"

# --- the closed vocabularies, quoted from the real modules ------------------------------------
# libs/clue-core/clue_core/contact_research.py::CONTACT_PROFESSIONAL_FIELD_KEYS (frozen order)
CONTACT_PROFESSIONAL_FIELD_KEYS = (
    "contact.current_title",
    "contact.job_function",
    "contact.job_level",
    "contact.team_membership",
    "contact.current_location",
    "contact.organization_relationship",
)
# platform/api/clue_api/frontend_read/contacts.py:108
CONTACT_SIGNAL_FIELD_KEYS = ("contact.facet.recent_post", "contact.facet.public_appearances")

# account_detail.py:411-419 — the FI-1-era "insight" families are all project_NEUTRAL under the
# ratified §5.2 species table, so they belong in neutralFacts. `insights[]` means "a relative field
# that is neither a score nor the narrative" — today ONLY a pack field that declares itself
# relative. This run registered no pack, so `insights` is legitimately empty; the PROPOSED
# vertical_saas.* pack is what would fill it (shown in the proposed variant below).
NARRATIVE_FIELD_KEY = "account.value_narrative"
SCORE_FIELD_KEYS = ("account.scoring.fit", "account.scoring.intent")

# stable synthetic ids so the payloads are copy-pasteable
NS = uuid.UUID("11111111-2222-3333-4444-555555555555")
ACCOUNT_UUID = str(uuid.uuid5(NS, "account:probook"))
CONTACT_UUID = {
    e: str(uuid.uuid5(NS, e))
    for e in (
        "contact:george-eliadis",
        "contact:mark-hoffman",
        "contact:kate-blumberg",
        "contact:aaron-churba",
        "contact:lewis-zhang",
    )
}

claims = json.load(open("claims.json"))
committee = json.load(open("committee.json"))
ENTITY_OF = {
    "eliadis": "contact:george-eliadis",
    "hoffman": "contact:mark-hoffman",
    "blumberg": "contact:kate-blumberg",
    "churba": "contact:aaron-churba",
    "zhang": "contact:lewis-zhang",
}

by_entity = defaultdict(list)
for c in claims:
    by_entity[c["entity"]].append(c)


def merge_current(rows):
    """The M1.2 merge, as the read layer sees it: one winner per field_key.
    Ranking mirrors the substrate — lower source_tier wins, then higher confidence."""
    best = {}
    for c in rows:
        k = c["field_key"]
        cur = best.get(k)
        if cur is None or (c["source_tier"], -c["confidence"]) < (
            cur["source_tier"],
            -cur["confidence"],
        ):
            best[k] = c
    return best


# ================================================================= VIEW 1: the accounts-list row
emp = merge_current(by_entity["account:probook"]).get("core.employee_count")
revenue_band = merge_current(by_entity["account:probook"]).get("core.revenue_band")
list_row = {
    "id": ACCOUNT_UUID,
    "name": "Probook",
    "domain": "probook.ai",
    "employeeCount": emp["value_json"] if emp else None,
    # no core.revenue_band claim exists — absence is a legitimate answer (vocabulary.ts rule 1)
    "revenueBand": revenue_band["value_json"] if revenue_band else None,
    "logoUrl": None,  # account.ts:68 — always null today, no logo pipeline exists
    "projects": [
        {
            "projectId": PROJECT_ID,
            "name": PROJECT_NAME,
            "addedVia": "discovered",
            "addedAt": RUN_AT,
        }
    ],
    "primaryProjectId": PROJECT_ID,
    # No `account.scoring.*` claim was written: scoring is a rubric pass over claims, not a
    # research output, and no ICP spec version existed to score against. `fit`/`intent` are
    # independently nullable precisely so this is reportable rather than fabricated as 0.
    "scores": [],
    "researchStatus": [{"projectId": PROJECT_ID, "status": "needs_review"}],
    "updatedAt": RUN_AT,
}
accounts_list_response = {"data": [list_row], "meta": {"total": 1, "nextCursor": None}}

# ================================================================== VIEW 2: the account detail
account_current = merge_current(by_entity["account:probook"])
neutral_facts = [
    {
        "fieldKey": k,
        "value": c["value_json"],
        "freshness": "fresh",
        "observedAt": RUN_AT,
        "provider": c["source_key"],
    }
    for k, c in sorted(account_current.items())
]

committee_rows = []
for m in committee:
    ent = ENTITY_OF[m["key"]]
    committee_rows.append(
        {
            "contactId": CONTACT_UUID[ent],
            "name": m["name"],
            "persona": m["persona"],
            # account-detail.ts:70 — "An open string on the wire, not the persona enum."
            "roleOnCommittee": m["persona"],
            "projectIds": [PROJECT_ID],
        }
    )

# coverage.researchedFieldCount = distinct fields holding >=1 live non-rejected claim for the
# ACCOUNT entity (account_detail.py:193). unresolvedFieldKeys = fields research asked for and
# could not answer — here, the registered account fields the deep charter covered and the report
# returned NOT FOUND for.
unresolved = [
    "account.resonance.attrition_signal",
    "account.resonance.employee_sentiment",
    "account.resonance.eng_blog_tone",
    "account.resonance.public_frustrations",
    "core.annual_revenue",
    "core.company_email",
    "core.company_phone",
    "core.revenue_band",
]
account_detail = {
    "id": ACCOUNT_UUID,
    "name": "Probook",
    "domain": "probook.ai",
    "aliases": ["Probook AI"],
    "registryIds": {},
    "hqGeo": {"city": "New York", "region": "New York", "country": "US", "postalCode": "10022"},
    "redirectedFrom": None,
    "neutralFacts": neutral_facts,
    "projectSections": [
        {
            "projectId": PROJECT_ID,
            "name": PROJECT_NAME,
            "addedVia": "discovered",
            "addedAt": RUN_AT,
            "scores": [],
            # account.value_narrative is the M12 output; this run stops at verified claims, and
            # B4 residual (a) means no composed run emits a narrative today.
            "narratives": [],
            # EMPTY as-built: see the module note above. The proposed-pack variant is below.
            "insights": [],
        }
    ],
    "committee": committee_rows,
    "coverage": {
        "researchedFieldCount": len(account_current),
        "unresolvedFieldKeys": unresolved,
    },
}

# The same payload IF the PROPOSED `vertical_saas.*` pack existed and declared itself
# project_relative — this is where every P1 buying-intent signal would actually live.
proposed_insights = [
    {
        "fieldKey": "vertical_saas.open_gtm_roles",
        "value": [
            {"title": "Sales Development Representative", "department": "GTM",
             "location": "Manhattan", "url": "https://jobs.ashbyhq.com/probook/81d50bde-0d98-48f0-a3c1-d8eee6d4a3c0",
             "posted_at": "2026-04-23"},
            {"title": "Enterprise Account Executive", "department": "GTM",
             "location": "Manhattan", "url": "https://jobs.ashbyhq.com/probook/a54815d3-1062-4d02-9d87-ebc6feb892e2",
             "posted_at": "2026-06-03"},
            {"title": "Strategic Account Executive", "department": "GTM",
             "location": "Manhattan", "url": "https://jobs.ashbyhq.com/probook/672b7090-68f9-4951-8af3-482e289d7af7",
             "posted_at": "2026-06-23"},
            {"title": "Solutions Consultant", "department": "GTM",
             "location": "Manhattan", "url": "https://jobs.ashbyhq.com/probook/d4bf0942-9da6-4157-802e-8e5991973841",
             "posted_at": "2026-06-22"},
            {"title": "Senior Product Marketing Manager", "department": "GTM",
             "location": "Manhattan", "url": "https://jobs.ashbyhq.com/probook/b49b1bdc-3834-4b37-8216-6cc58c005991",
             "posted_at": "2026-07-16"},
            {"title": "Events Marketing Specialist", "department": "GTM",
             "location": "Manhattan", "url": "https://jobs.ashbyhq.com/probook/c195de0a-605b-4bfa-840f-f6ff5f7e24f1",
             "posted_at": "2026-07-16"},
        ],
        "observedAt": RUN_AT,
        "provider": "ashby_public",
    },
    {
        "fieldKey": "vertical_saas.gtm_stack",
        "value": {
            "as_of": "2026-08-26",
            "crm": [],
            "outbound": [],
            "abm": [],
            "paid": ["LinkedIn Ads"],
            "absent": ["Salesforce", "HubSpot", "Outreach", "Salesloft", "Apollo.io", "Clay",
                       "6sense", "Demandbase"],
        },
        "observedAt": RUN_AT,
        "provider": "apollo",
    },
    {
        "fieldKey": "vertical_saas.gtm_team_shape",
        "value": {
            "as_of": "2026-08-26",
            "sales_headcount": 7,
            "marketing_headcount": 1,
            "open_gtm_roles": 6,
            "first_sales_hire_made": True,
        },
        "observedAt": RUN_AT,
        "provider": "apollo",
    },
    {
        "fieldKey": "vertical_saas.target_vertical",
        "value": {
            "vertical": "US home-services contractors (plumbing, HVAC, electrical)",
            "fragmentation": "fragmented_smb",
            "basis": "the AI Operating System for home services, built around dispatch",
        },
        "observedAt": RUN_AT,
        "provider": "exa_research",
    },
    {
        "fieldKey": "vertical_saas.funding_runway_signal",
        "value": {
            "latest_round_date": "2026-06-23",
            "latest_round_stage": "Series A",
            "months_since_round": 2,
            "stated_growth_target": "scale its go-to-market team against surging demand",
        },
        "observedAt": RUN_AT,
        "provider": "exa_research",
    },
]

# ================================================================= VIEW 3: the contacts table
def display_title(ent):
    cur = merge_current(by_entity[ent])
    t = cur.get("contact.current_title")
    return t["value_json"] if t and isinstance(t["value_json"], str) else None


contact_rows = []
for m in committee:
    ent = ENTITY_OF[m["key"]]
    cur = merge_current(by_entity[ent])
    contact_rows.append(
        {
            "id": CONTACT_UUID[ent],
            "name": m["name"],
            "title": display_title(ent),
            "titleRestricted": False,
            "persona": m["persona"],
            "roleOnCommittee": {"value": m["persona"], "confidence": 0.9},
            "linkedinUrl": m["web_linkedin_url"],
            "projectIds": [PROJECT_ID],
            # contacts.py::_signal_type_count — how many SIGNAL TYPES hold a display-eligible
            # statement, bounded by a two-family whitelist. A person with four public posts
            # still counts 1.
            "signals": {
                "typeCount": sum(1 for f in CONTACT_SIGNAL_FIELD_KEYS if f in cur)
            },
        }
    )
contacts_response = {"data": contact_rows, "meta": {"total": len(contact_rows)}}

# ============================================================ VIEW 4: one contact profile
def contact_profile(ent, row):
    rows = by_entity[ent]
    cur = merge_current(rows)
    professional = []
    for fk in CONTACT_PROFESSIONAL_FIELD_KEYS:
        c = cur.get(fk)
        if c is None:
            continue
        professional.append(
            {
                "fieldKey": fk,
                "value": c["value_json"],
                "observedAt": RUN_AT,
                "provider": c["source_key"],
                "restricted": False,
            }
        )
    providers = sorted({c["source_key"] for c in rows})
    return {
        **row,
        "accountId": ACCOUNT_UUID,
        "accountName": "Probook",
        "professionalFacts": professional,
        # contacts.py::_evidence — one chip per distinct source, provider + time only.
        # "evidence URLs stay off this wire (G4)".
        "evidence": [{"provider": p, "observedAt": RUN_AT} for p in providers],
        "redirectedFrom": None,
    }


blumberg_row = next(r for r in contact_rows if r["name"] == "Kate Blumberg")
blumberg_profile = contact_profile("contact:kate-blumberg", blumberg_row)

# ============================================================= what the contract has NO slot for
def facets(ent):
    return [
        {
            "fieldKey": c["field_key"],
            "value": c["value_json"],
            "priority": c["priority"],
            "useClass": c.get("use_class"),
            "sourceUrl": c["source_url"],
            "evidenceSpan": c["evidence_span"],
        }
        for c in sorted(by_entity[ent], key=lambda x: (x["priority"], x["field_key"]))
        if c["field_key"].startswith("contact.facet.") or c["field_key"] == "core.work_email"
    ]


PROPOSED_SLOTS = {
    "_note": "Everything this run produced that the as-built contract has NO slot for. Marked, "
             "never silently folded into a real field.",
    "account.neutralFacts[].priority": {
        "hypothesis": "NeutralFactSchema has no rank, so the frontend can only sort by fieldKey. "
                      "The 8 P1 rows on this account are interleaved with 15 P2/P3 rows and the "
                      "'why now' story is invisible. One `priority: 1|2|3` per fact makes the "
                      "ordering server-authored and identical on every surface.",
        "example": [
            {"fieldKey": f["fieldKey"], "priority": next(
                c["priority"] for c in by_entity["account:probook"]
                if c["field_key"] == f["fieldKey"])}
            for f in neutral_facts
        ],
    },
    "account.topSignals[]": {
        "hypothesis": "The 'Why now' card. A server-selected, ordered list of the P1 facts with "
                      "the verbatim quote and the source domain behind each. Derivable from "
                      "neutralFacts+priority, but every client would re-derive it differently, "
                      "and the quote (evidence_span) is not on the wire at all today.",
        "example": [
            {
                "fieldKey": c["field_key"],
                "quote": c["evidence_span"],
                "sourceDomain": (c["source_url"] or "").split("/")[2] if c["source_url"] else None,
                "observedAt": RUN_AT,
            }
            for c in by_entity["account:probook"]
            if c["priority"] == 1
        ],
    },
    "account.summary": {
        "hypothesis": "The Lane-E `account.summary` analog: a 3-5 sentence prose paragraph. No "
                      "field on AccountDetailSchema holds prose. Layer 2 generates it; it needs "
                      "somewhere to land.",
        "example": "<generated by Layer 2 — see layer2_display.json>",
    },
    "contact.professionalFacts — missing families": {
        "hypothesis": "CONTACT_PROFESSIONAL_FIELD_KEYS is exactly six keys and includes NEITHER "
                      "core.work_email NOR any contact.facet.* field. So the verified email this "
                      "run paid an Apollo credit for, and the entire per-person deep research "
                      "(career history, awards, public posts, communication style, hooks), have "
                      "NO surface on the contact-profile payload. `signals.typeCount` is an "
                      "integer — the only hint they exist.",
        "example_missing_per_contact": {
            CONTACT_UUID[e]: {"name": n, "facts": facets(e)}
            for e, n in (
                ("contact:george-eliadis", "George Eliadis"),
                ("contact:mark-hoffman", "Mark Hoffman"),
                ("contact:kate-blumberg", "Kate Blumberg"),
                ("contact:aaron-churba", "Aaron Churba"),
                ("contact:lewis-zhang", "Lewis Zhang"),
            )
        },
    },
    "contact.openers[]": {
        "hypothesis": "Each per-person deep call produced 3 grounded openers with the exact hook "
                      "and its URL. There is no registered field and no wire slot. This is the "
                      "single most immediately actionable output of the run and it lives only in "
                      "a markdown file.",
        "example": "<generated by Layer 2 from the person reports — see layer2_display.json>",
    },
    "evidence[].url": {
        "hypothesis": "ContactEvidenceSchema is deliberately {provider, observedAt} with no URL "
                      "(G4). Every claim in this run has a source_url and most have a verbatim "
                      "evidence_span; a reviewer cannot open either from the contact profile. "
                      "REQ-07's presign path is the intended home — see the CLAUDE.md "
                      "[B2xpresign/frontend] backlog item for the scope gate that must land first.",
    },
    "projectSections[].insights[] — needs a project_relative pack": {
        "hypothesis": "As-built this array is empty for this account, because every field the run "
                      "wrote is project_neutral. The P1 buying-intent signals (open GTM roles, the "
                      "GTM stack gap, GTM team shape, funding runway) are exactly the "
                      "project-relative species, and the PROPOSED vertical_saas.* pack is what "
                      "makes them land here instead of being flattened into neutralFacts.",
        "example_if_pack_registered": proposed_insights,
    },
}

out = {
    "_contracts_read": [
        "apps/frontend/src/features/accounts/model/account.ts",
        "apps/frontend/src/features/accounts/model/account-detail.ts",
        "apps/frontend/src/features/accounts/model/account-contact.ts",
        "apps/frontend/src/features/accounts/model/vocabulary.ts",
        "apps/frontend/docs/api-contracts/accounts.md",
        "platform/api/clue_api/frontend_read/accounts_list.py",
        "platform/api/clue_api/frontend_read/account_detail.py",
        "platform/api/clue_api/frontend_read/contacts.py",
        "platform/api/clue_api/frontend_read/committee.py",
        "libs/clue-core/clue_core/contact_research.py",
    ],
    "GET /frontend/v1/accounts": accounts_list_response,
    "GET /frontend/v1/accounts/{accountId}": account_detail,
    "GET /frontend/v1/accounts/{accountId}/contacts": contacts_response,
    "GET /frontend/v1/accounts/{accountId}/contacts/{contactId}": blumberg_profile,
    "_PROPOSED_SLOTS": PROPOSED_SLOTS,
}
json.dump(out, open("layer1_payloads.json", "w"), indent=2)

print("layer1_payloads.json written")
print(f"  neutralFacts: {len(neutral_facts)}   committee: {len(committee_rows)}   "
      f"contacts: {len(contact_rows)}")
print(f"  coverage.researchedFieldCount = {len(account_current)}  "
      f"unresolvedFieldKeys = {len(unresolved)}")
print(f"  projectSections[0].insights = {len(account_detail['projectSections'][0]['insights'])} "
      f"(as-built)  vs {len(proposed_insights)} if the proposed pack existed")
print(f"  contact profile professionalFacts = {len(blumberg_profile['professionalFacts'])} of "
      f"{len(CONTACT_PROFESSIONAL_FIELD_KEYS)} registered keys; "
      f"{len(facets('contact:kate-blumberg'))} researched facts have NO slot")
print(f"  PROPOSED-SLOTS: {len([k for k in PROPOSED_SLOTS if not k.startswith('_')])}")
