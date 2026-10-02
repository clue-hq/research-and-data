import json, os, time, urllib.request, urllib.error, importlib.util
HERE = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location("s2", os.path.join(HERE, "run_sample2.py.lib"))
# inline instead: copy needed bits
def env_key(name):
    with open(os.path.join(HERE, "..", "..", ".env")) as f:
        for line in f:
            if line.startswith(name + "="): return line.strip().split("=", 1)[1]
    return ""
EXA_KEY = env_key("CLUE_EXA_API_KEY")
def exa(payload, timeout=460, retries=4):
    for attempt in range(retries):
        req = urllib.request.Request("https://api.exa.ai/search", data=json.dumps(payload).encode(),
            headers={"x-api-key": EXA_KEY, "Content-Type": "application/json"}, method="POST")
        t0 = time.time()
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                out = json.loads(r.read().decode()); out["_elapsed_s"] = round(time.time()-t0,1); return out
        except urllib.error.HTTPError as e:
            body = e.read().decode()[:400]
            if e.code == 429 and attempt < retries-1:
                time.sleep(3*(attempt+1)); continue
            return {"_error": e.code, "_body": body}
def G(desc):
    return {"type":"object","description":desc,"properties":{"value":{"type":"string"},"verbatim_quote":{"type":"string"},"source_url":{"type":"string"}},"required":["value","source_url"]}
SYS_ACCT = ("Research the exact account Digestive Healthcare of Georgia, P.C. (digestivehealthcare.net), the Atlanta "
            "gastroenterology group — never a similarly named company. Ground every value in a public page: copy a "
            "verbatim quote and its source url. If a fact cannot be found, leave the field null rather than guessing.")
CONTENTS = {"text":{"maxCharacters":10000},"highlights":{"query":"digestive healthcare of georgia","maxCharacters":2000}}
missing = {
  "A1_ehr_ownership": ("Digestive Healthcare of Georgia EHR electronic health record MyChart Epic Piedmont; ownership independent physician owned private equity", "deep-reasoning",
    {"ehr_system": G("EHR vendor + hosting (e.g. hospital-hosted instance); state explicitly if any evidence of gGastro/Modernizing Medicine"),
     "ownership_structure": G("independent physician-owned vs PE/MSO/hospital-owned; name affiliations; disambiguate similarly named Atlanta GI groups")}),
  "A3_referral_priorauth": ("Digestive Healthcare of Georgia referral fax number referring physician form prior authorization precertification", "deep",
    {"referral_intake_evidence": G("evidence inbound referrals arrive by fax / manual entry: fax numbers, referral form pages"),
     "prior_auth_evidence": G("evidence of prior-authorization / pre-certification workload")}),
}
for name, (q, kind, schema) in missing.items():
    print("refetch", name, flush=True)
    r = exa({"query": q, "type": kind, "numResults": 20, "systemPrompt": SYS_ACCT,
             "outputSchema": {"type":"object","properties":schema}, "contents": CONTENTS, "stream": False})
    json.dump(r, open(os.path.join(HERE, f"deep_{name}.json"), "w"), indent=2)
    print(" ", name, "elapsed", r.get("_elapsed_s"), "cost", (r.get("costDollars") or {}).get("total"), "err", r.get("_error"), flush=True)
    time.sleep(1.5)

def out_of(r):
    o = r.get("output")
    if isinstance(o, dict):
        c = o.get("content")
        if isinstance(c, dict): return c
        if isinstance(c, str):
            try: return json.loads(c)
            except Exception: return {}
        return o
    return {}
ACCT="account:digestive-healthcare-of-georgia"; PERSON="contact:gaye-pennington"
FIELD={"ehr_system":("gi.ehr_vendor",ACCT),"ownership_structure":("account.ownership_structure",ACCT),
 "size_and_locations":("account.locations",ACCT),"owned_procedure_facilities":("gi.owned_endoscopy_centers",ACCT),
 "referral_intake_evidence":("gi.referral_intake_mode",ACCT),"prior_auth_evidence":("gi.prior_auth_workload",ACCT),
 "timing_signals":("account.timing_signals",ACCT),"leadership_and_admins":("committee.member",ACCT),
 "identity_confirmation":("contact.identity_confirmation",PERSON),"career_history":("contact.facet.career_history",PERSON),
 "education":("contact.facet.alma_mater",PERSON),"awards_recognition":("contact.facet.awards",PERSON),
 "personal_hooks":("contact.facet.stated_interests",PERSON),"suggested_openers":("contact.facet.openers",PERSON)}
claims=[]; total=0.0
for fn in sorted(os.listdir(HERE)):
    if not fn.startswith("deep_"): continue
    r=json.load(open(os.path.join(HERE,fn))); total += ((r.get("costDollars") or {}).get("total") or 0)
    for key,payload in out_of(r).items():
        if key not in FIELD or payload in (None,"",[]): continue
        fk,ent=FIELD[key]; items=payload if isinstance(payload,list) else [payload]
        for it in items:
            if not isinstance(it,dict): continue
            val = it.get("value") or it.get("fact") or it.get("role") or it.get("opener") or ({"name":it.get("name"),"title":it.get("title")} if it.get("name") else None)
            if not val: continue
            row={"entity":ent,"field_key":fk,"value_json":val,"evidence_span":(it.get("verbatim_quote") or "")[:400],
                 "source_url":it.get("source_url") or it.get("grounded_in_url") or "","source_key":"exa_research",
                 "source_tier":4,"extraction_method":"llm_synthesis","verification_status":"unverified","reuse_scope":"tenant_private"}
            if fk.startswith("contact."):
                row["identity_binding"]="strong"; row["use_class"]="personal-public-non-sensitive" if fk.startswith("contact.facet") else "professional-public"
            if it.get("category"): row["value_json"]={"category":it["category"],"fact":val}
            claims.append(row)
json.dump(claims, open(os.path.join(HERE,"step5_claims.json"),"w"), indent=2)
from collections import Counter
print("TOTAL COST all calls: $"+str(round(total,3)), flush=True)
print("CLAIMS:", len(claims), dict(Counter(c["field_key"] for c in claims)), flush=True)
