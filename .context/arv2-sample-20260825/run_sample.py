"""ARV2 sandbox sample — the three-step pipeline, live against Exa.

Step 1  DISCOVER   : Exa /search (type=auto)  — ICP query finds the account
Step 2  ACCOUNT    : Exa /search (type=deep-reasoning) + outputSchema — dossier-depth account research
Step 3  COMMITTEE  : Apollo people search (key absent -> emit the exact request, skip live)
Step 4  CONTACT    : Exa /search (type=deep) + outputSchema — one person's facets
Step 5  CLAIMS     : convert outputs to claim-shaped rows (the ARV2 stamping matrix)

Writes everything into this directory as JSON; never touches the platform DB.
"""
import json, os, re, sys, time, urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ENV  = os.path.join(HERE, "..", "..", ".env")

def env_key(name):
    with open(ENV) as f:
        for line in f:
            if line.startswith(name + "="):
                return line.strip().split("=", 1)[1]
    return ""

EXA_KEY = env_key("CLUE_EXA_API_KEY")
assert EXA_KEY, "no Exa key"

def exa(payload, timeout=420):
    req = urllib.request.Request(
        "https://api.exa.ai/search",
        data=json.dumps(payload).encode(),
        headers={"x-api-key": EXA_KEY, "Content-Type": "application/json"},
        method="POST",
    )
    t0 = time.time()
    with urllib.request.urlopen(req, timeout=timeout) as r:
        out = json.loads(r.read().decode())
    out["_elapsed_s"] = round(time.time() - t0, 1)
    return out

def save(name, obj):
    with open(os.path.join(HERE, name), "w") as f:
        json.dump(obj, f, indent=2)
    print(f"saved {name}", flush=True)

GROUNDED = {
    "type": "object",
    "properties": {
        "value": {"type": "string"},
        "verbatim_quote": {"type": "string", "description": "exact words copied from the source page"},
        "source_url": {"type": "string"},
    },
    "required": ["value", "source_url"],
}

# ---------- Step 1: DISCOVER ----------
print("== step 1: discovery ==", flush=True)
disc = exa({
    "query": "independent physician-owned gastroenterology group practice in Georgia with its own endoscopy centers",
    "type": "auto",
    "numResults": 5,
}, timeout=90)
save("step1_discovery.json", disc)
for r in disc.get("results", []):
    print("  -", r.get("title"), "|", r.get("url"), flush=True)

# ---------- Step 2: ACCOUNT DEEP RESEARCH ----------
print("== step 2: account deep research (deep-reasoning) ==", flush=True)
account_schema = {
    "type": "object",
    "properties": {
        "ehr_system": {**GROUNDED, "description": "The electronic health record system the practice runs (vendor + hosting arrangement). Also state explicitly whether there is any evidence they run gGastro/Modernizing Medicine."},
        "ownership_structure": {**GROUNDED, "description": "Independent physician-owned vs private-equity/MSO/hospital owned; name any parent or affiliation and disambiguate similarly named companies."},
        "size_and_locations": {**GROUNDED, "description": "Number of physicians/providers and office locations, listing location names."},
        "owned_procedure_facilities": {**GROUNDED, "description": "Endoscopy centers / ambulatory surgery centers the practice OWNS, with names and any opening dates."},
        "referral_intake_evidence": {**GROUNDED, "description": "Evidence that inbound referrals arrive by fax / manual entry (fax numbers, referral form pages)."},
        "prior_auth_evidence": {**GROUNDED, "description": "Evidence of a prior-authorization / pre-certification workload."},
        "timing_signals": {
            "type": "array", "maxItems": 4,
            "items": {**GROUNDED, "description": "Recent expansion, technology go-live, new facility, hiring or leadership change with dates"},
        },
        "leadership_and_admins": {
            "type": "array", "maxItems": 8,
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "title": {"type": "string"},
                    "clinical_or_business": {"type": "string", "enum": ["clinical", "business"]},
                    "source_url": {"type": "string"},
                },
                "required": ["name", "title", "source_url"],
            },
            "description": "Named decision-makers: physician officers/owners, CEO/executive director, practice administrators, revenue-cycle leaders.",
        },
    },
    "required": ["ehr_system", "ownership_structure", "size_and_locations", "owned_procedure_facilities", "leadership_and_admins"],
}
acct = exa({
    "query": "Digestive Healthcare of Georgia P.C. (digestivehealthcare.net) — complete B2B account research for a healthcare-workflow vendor",
    "type": "deep-reasoning",
    "systemPrompt": ("You are researching one specific medical practice: Digestive Healthcare of Georgia, P.C. "
                     "(digestivehealthcare.net), an Atlanta gastroenterology group. Every value must be grounded in a "
                     "public page with a verbatim quote and its URL. If a fact cannot be found, say 'not found' rather "
                     "than guessing. Prefer the practice's own site, NPI registry, and reputable directories."),
    "outputSchema": account_schema,
}, timeout=420)
save("step2_account_deep.json", acct)

# ---------- Step 3: COMMITTEE (Apollo — key absent, emit request) ----------
print("== step 3: committee via Apollo (dry) ==", flush=True)
apollo_req = {
    "method": "POST",
    "url": "https://api.apollo.io/api/v1/mixed_people/api_search",
    "headers": {"x-api-key": "<CLUE_APOLLO_API_KEY — not yet purchased>"},
    "json": {
        "q_organization_domains_list": ["digestivehealthcare.net"],
        "person_seniorities": ["owner", "c_suite", "vp", "director", "manager"],
        "per_page": 25,
    },
    "note": "0 credits; returns obfuscated shortlist; round-trip ids via POST /people/match (1 cr email, +8 mobile via webhook)",
}
save("step3_apollo_request.json", apollo_req)

# ---------- Step 4: CONTACT DEEP RESEARCH ----------
print("== step 4: contact deep research (deep) ==", flush=True)
contact_schema = {
    "type": "object",
    "properties": {
        "identity_confirmation": {**GROUNDED, "description": "Proof this person holds this role at Digestive Healthcare of Georgia (practice site, org chart, LinkedIn)."},
        "career_history": {"type": "array", "maxItems": 6, "items": GROUNDED},
        "education": {"type": "array", "maxItems": 4, "items": GROUNDED},
        "awards_and_recognition": {"type": "array", "maxItems": 4, "items": GROUNDED},
        "personal_hooks": {
            "type": "array", "maxItems": 6,
            "items": {
                "type": "object",
                "properties": {
                    "category": {"type": "string", "enum": ["hometown", "alma_mater", "hobby", "pet", "family_milestone", "community", "recent_post", "tenure_milestone", "other"]},
                    "fact": {"type": "string"},
                    "verbatim_quote": {"type": "string"},
                    "source_url": {"type": "string"},
                },
                "required": ["category", "fact", "source_url"],
            },
            "description": "Publicly sourced personalization hooks suitable for a warm founders letter. Exclude anything sensitive (health, faith, politics).",
        },
        "suggested_openers": {"type": "array", "maxItems": 3, "items": {"type": "object", "properties": {"opener": {"type": "string"}, "grounded_in_url": {"type": "string"}}, "required": ["opener"]}},
    },
    "required": ["identity_confirmation", "career_history"],
}
person = exa({
    "query": "Gaye Pennington, Chief Executive Officer of Digestive Healthcare of Georgia (Atlanta GI practice) — professional and public-personalization research",
    "type": "deep",
    "systemPrompt": ("Research one person: Gaye Pennington, CEO/Executive Director of Digestive Healthcare of Georgia, P.C., "
                     "Atlanta. Every fact needs a verbatim quote and source URL from a public page. Confirm identity against "
                     "the practice's own pages first; mark anything uncertain. Never include sensitive categories."),
    "outputSchema": contact_schema,
}, timeout=420)
save("step4_contact_deep.json", person)

# ---------- Step 5: CLAIM CONVERSION ----------
print("== step 5: claim conversion ==", flush=True)
FIELD_MAP = {
    "ehr_system": "gi.ehr_vendor", "ownership_structure": "account.ownership_structure",
    "size_and_locations": "account.locations", "owned_procedure_facilities": "gi.owned_endoscopy_centers",
    "referral_intake_evidence": "gi.referral_intake_mode", "prior_auth_evidence": "gi.prior_auth_workload",
}
def out_of(resp):
    o = resp.get("output")
    if isinstance(o, dict) and "content" in o and isinstance(o["content"], str):
        try: return json.loads(o["content"])
        except Exception: return {}
    return o if isinstance(o, dict) else {}

claims, ao = [], out_of(acct)
def claim(fk, value, quote, url, entity):
    claims.append({"entity": entity, "field_key": fk, "value_json": value,
                   "evidence_span": (quote or "")[:400], "source_url": url,
                   "source_key": "exa_research", "source_tier": 4,
                   "extraction_method": "llm_synthesis", "verification_status": "unverified",
                   "reuse_scope": "tenant_private"})
for k, fk in FIELD_MAP.items():
    v = ao.get(k)
    if isinstance(v, dict) and v.get("value"):
        claim(fk, v["value"], v.get("verbatim_quote"), v.get("source_url", ""), "account:digestive-healthcare-of-georgia")
for i, t in enumerate(ao.get("timing_signals") or []):
    if isinstance(t, dict) and t.get("value"):
        claim("account.timing_signals", t["value"], t.get("verbatim_quote"), t.get("source_url", ""), "account:digestive-healthcare-of-georgia")
for m in ao.get("leadership_and_admins") or []:
    if isinstance(m, dict) and m.get("name"):
        claim("committee.member", {"name": m["name"], "title": m.get("title"), "class": m.get("clinical_or_business")},
              None, m.get("source_url", ""), "account:digestive-healthcare-of-georgia")
po = out_of(person)
for k, fk in [("identity_confirmation", "contact.identity_confirmation"), ("career_history", "contact.facet.career_history"),
              ("education", "contact.facet.alma_mater"), ("awards_and_recognition", "contact.facet.awards"),
              ("personal_hooks", "contact.facet.stated_interests"), ("suggested_openers", "contact.facet.openers")]:
    v = po.get(k)
    items = v if isinstance(v, list) else ([v] if isinstance(v, dict) else [])
    for it in items:
        if isinstance(it, dict):
            val = it.get("value") or it.get("fact") or it.get("opener")
            if val:
                c = {"entity": "contact:gaye-pennington", "field_key": fk, "value_json": val,
                     "evidence_span": (it.get("verbatim_quote") or "")[:400],
                     "source_url": it.get("source_url") or it.get("grounded_in_url", ""),
                     "source_key": "exa_research", "source_tier": 4, "extraction_method": "llm_synthesis",
                     "verification_status": "unverified", "reuse_scope": "tenant_private",
                     "identity_binding": "strong", "use_class": "personal-public-non-sensitive" if fk.startswith("contact.facet") else "professional-public"}
                if fk.startswith("contact.facet") and it.get("category"):
                    c["value_json"] = {"category": it["category"], "fact": val}
                claims.append(c)
save("step5_claims.json", claims)
cost = (acct.get("costDollars") or {}); pcost = (person.get("costDollars") or {})
print(f"DONE  claims={len(claims)}  acct_elapsed={acct['_elapsed_s']}s person_elapsed={person['_elapsed_s']}s", flush=True)
print("acct_cost:", json.dumps(cost), " person_cost:", json.dumps(pcost), flush=True)
