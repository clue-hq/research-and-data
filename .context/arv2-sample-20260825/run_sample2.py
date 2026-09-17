"""ARV2 sandbox sample v2 — schema-budget-compliant (10 properties, depth 2), parallel deep calls."""
import json, os, time, urllib.request, urllib.error
from concurrent.futures import ThreadPoolExecutor

HERE = os.path.dirname(os.path.abspath(__file__))
def env_key(name):
    with open(os.path.join(HERE, "..", "..", ".env")) as f:
        for line in f:
            if line.startswith(name + "="):
                return line.strip().split("=", 1)[1]
    return ""
EXA_KEY = env_key("CLUE_EXA_API_KEY")

def exa(payload, timeout=460):
    req = urllib.request.Request("https://api.exa.ai/search", data=json.dumps(payload).encode(),
        headers={"x-api-key": EXA_KEY, "Content-Type": "application/json"}, method="POST")
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            out = json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        return {"_error": e.code, "_body": e.read().decode()[:800], "_elapsed_s": round(time.time()-t0,1)}
    out["_elapsed_s"] = round(time.time() - t0, 1)
    return out

def G(desc):  # grounded object: 1 + 3 children = 4 schema properties
    return {"type": "object", "description": desc, "properties": {
        "value": {"type": "string"}, "verbatim_quote": {"type": "string"}, "source_url": {"type": "string"}},
        "required": ["value", "source_url"]}

SYS_ACCT = ("Research the exact account Digestive Healthcare of Georgia, P.C. (digestivehealthcare.net), the Atlanta "
            "gastroenterology group — never a similarly named company. Ground every value in a public page: copy a "
            "verbatim quote and its source url. If a fact cannot be found, leave the field null rather than guessing.")
SYS_PERSON = ("Research the exact person Gaye Pennington at her exact employer Digestive Healthcare of Georgia, P.C. "
              "(Atlanta GI practice), where she is CEO/Executive Director — never a same-named different person. Ground "
              "every fact with a verbatim quote and source url from a public page; if unsure, leave the field null. "
              "Exclude sensitive categories (health, faith, politics).")
CONTENTS = {"text": {"maxCharacters": 10000}, "highlights": {"query": "digestive healthcare of georgia", "maxCharacters": 2000}}

def deep(query, sysprompt, schema, kind="deep"):
    return exa({"query": query, "type": kind, "numResults": 20, "systemPrompt": sysprompt,
                "outputSchema": {"type": "object", "properties": schema}, "contents": CONTENTS, "stream": False})

CALLS = {
  "A1_ehr_ownership": ("Digestive Healthcare of Georgia EHR electronic health record system MyChart Epic; ownership independent physician owned vs private equity", SYS_ACCT,
    {"ehr_system": G("EHR vendor + hosting (e.g. hospital-hosted instance); state explicitly if any evidence of gGastro/Modernizing Medicine"),
     "ownership_structure": G("independent physician-owned vs PE/MSO/hospital-owned; name affiliations; disambiguate similarly named Atlanta GI groups")}, "deep-reasoning"),
  "A2_size_facilities": ("Digestive Healthcare of Georgia locations providers count owned endoscopy centers ambulatory surgery centers", SYS_ACCT,
    {"size_and_locations": G("number of physicians/providers and offices, naming the office locations"),
     "owned_procedure_facilities": G("endoscopy centers / ASCs the practice OWNS, with names and opening dates")}),
  "A3_referral_priorauth": ("Digestive Healthcare of Georgia referral fax number referring physician form prior authorization precertification", SYS_ACCT,
    {"referral_intake_evidence": G("evidence inbound referrals arrive by fax / manual entry: fax numbers, referral form pages"),
     "prior_auth_evidence": G("evidence of prior-authorization / pre-certification workload")}),
  "A4_timing_committee": ("Digestive Healthcare of Georgia news new endoscopy center opening leadership CEO practice administrator", SYS_ACCT,
    {"timing_signals": {"type": "array", "maxItems": 4, "description": "recent expansion / technology go-live / new facility signals with dates",
        "items": {"type": "object", "properties": {"value": {"type": "string"}, "verbatim_quote": {"type": "string"}, "source_url": {"type": "string"}}, "required": ["value", "source_url"]}},
     "leadership_and_admins": {"type": "array", "maxItems": 8, "description": "named decision-makers: physician officers, CEO/executive director, practice administrators, revenue-cycle leaders",
        "items": {"type": "object", "properties": {"name": {"type": "string"}, "title": {"type": "string"}, "source_url": {"type": "string"}}, "required": ["name", "title", "source_url"]}}}),
  "P1_identity_career": ("Gaye Pennington CEO Digestive Healthcare of Georgia career history", SYS_PERSON,
    {"identity_confirmation": G("proof this person holds this role at this practice"),
     "career_history": {"type": "array", "maxItems": 5, "description": "roles with organization and years",
        "items": {"type": "object", "properties": {"role": {"type": "string"}, "verbatim_quote": {"type": "string"}, "source_url": {"type": "string"}}, "required": ["role", "source_url"]}}}),
  "P2_edu_awards": ("Gaye Pennington Digestive Healthcare of Georgia education degree university awards recognition 25 years", SYS_PERSON,
    {"education": {"type": "array", "maxItems": 4, "description": "degrees with institution",
        "items": {"type": "object", "properties": {"value": {"type": "string"}, "verbatim_quote": {"type": "string"}, "source_url": {"type": "string"}}, "required": ["value", "source_url"]}},
     "awards_recognition": {"type": "array", "maxItems": 4, "description": "awards, milestones, public recognitions",
        "items": {"type": "object", "properties": {"value": {"type": "string"}, "verbatim_quote": {"type": "string"}, "source_url": {"type": "string"}}, "required": ["value", "source_url"]}}}),
  "P3_hooks_openers": ("Gaye Pennington Digestive Healthcare of Georgia LinkedIn alma mater hometown community anniversary celebration", SYS_PERSON,
    {"personal_hooks": {"type": "array", "maxItems": 5, "description": "publicly sourced non-sensitive personalization hooks (hometown, alma mater, tenure milestone, community, recent post)",
        "items": {"type": "object", "properties": {"category": {"type": "string"}, "fact": {"type": "string"}, "verbatim_quote": {"type": "string"}, "source_url": {"type": "string"}}, "required": ["category", "fact", "source_url"]}},
     "suggested_openers": {"type": "array", "maxItems": 3, "description": "warm founders-letter openers grounded ONLY in the hooks above",
        "items": {"type": "object", "properties": {"opener": {"type": "string"}, "grounded_in_url": {"type": "string"}}, "required": ["opener"]}}}),
}

print(f"launching {len(CALLS)} deep calls in parallel...", flush=True)
with ThreadPoolExecutor(max_workers=7) as pool:
    futs = {k: pool.submit(deep, *v) if len(v) == 3 else pool.submit(deep, v[0], v[1], v[2], v[3]) for k, v in CALLS.items()}
    results = {k: f.result() for k, f in futs.items()}

total_cost = 0.0
for k, r in results.items():
    with open(os.path.join(HERE, f"deep_{k}.json"), "w") as f:
        json.dump(r, f, indent=2)
    c = (r.get("costDollars") or {}).get("total", 0)
    total_cost += c or 0
    print(f"{k}: elapsed={r.get('_elapsed_s')}s cost=${c} error={r.get('_error','-')} {str(r.get('_body',''))[:200]}", flush=True)
print(f"TOTAL COST: ${round(total_cost, 3)}", flush=True)

def out_of(r):
    o = r.get("output")
    if isinstance(o, dict) and isinstance(o.get("content"), str):
        try: return json.loads(o["content"])
        except Exception: return {}
    return o if isinstance(o, dict) else {}

ACCT = "account:digestive-healthcare-of-georgia"; PERSON = "contact:gaye-pennington"
FIELD = {"ehr_system": ("gi.ehr_vendor", ACCT), "ownership_structure": ("account.ownership_structure", ACCT),
         "size_and_locations": ("account.locations", ACCT), "owned_procedure_facilities": ("gi.owned_endoscopy_centers", ACCT),
         "referral_intake_evidence": ("gi.referral_intake_mode", ACCT), "prior_auth_evidence": ("gi.prior_auth_workload", ACCT),
         "timing_signals": ("account.timing_signals", ACCT), "leadership_and_admins": ("committee.member", ACCT),
         "identity_confirmation": ("contact.identity_confirmation", PERSON), "career_history": ("contact.facet.career_history", PERSON),
         "education": ("contact.facet.alma_mater", PERSON), "awards_recognition": ("contact.facet.awards", PERSON),
         "personal_hooks": ("contact.facet.stated_interests", PERSON), "suggested_openers": ("contact.facet.openers", PERSON)}
claims = []
for r in results.values():
    for key, payload in out_of(r).items():
        if key not in FIELD or payload in (None, "", []): continue
        fk, ent = FIELD[key]
        items = payload if isinstance(payload, list) else [payload]
        for it in items:
            if not isinstance(it, dict): continue
            val = it.get("value") or it.get("fact") or it.get("role") or it.get("opener") or ({"name": it.get("name"), "title": it.get("title")} if it.get("name") else None)
            if not val: continue
            row = {"entity": ent, "field_key": fk, "value_json": val,
                   "evidence_span": (it.get("verbatim_quote") or "")[:400],
                   "source_url": it.get("source_url") or it.get("grounded_in_url") or "",
                   "source_key": "exa_research", "source_tier": 4, "extraction_method": "llm_synthesis",
                   "verification_status": "unverified", "reuse_scope": "tenant_private"}
            if fk.startswith("contact."):
                row["identity_binding"] = "strong"
                row["use_class"] = "personal-public-non-sensitive" if fk.startswith("contact.facet") else "professional-public"
            if it.get("category"): row["value_json"] = {"category": it["category"], "fact": val}
            claims.append(row)
with open(os.path.join(HERE, "step5_claims.json"), "w") as f:
    json.dump(claims, f, indent=2)
print(f"CLAIMS WRITTEN: {len(claims)}", flush=True)
