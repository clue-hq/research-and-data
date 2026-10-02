"""Step 8 — the cheap structuring pass: free-form reports -> platform claim rows.

Runs the SAME prompt through two cheap models so the report can compare them on measured cost:
  1. z-ai/glm-4.7      (the founder's question)
  2. openai/gpt-5-mini (the fallback / baseline)
Both usages are recorded; claims.json is written from whichever produced valid rows first.

The stamping matrix is ARV2-schema-impact-audit.md §3 and is applied HERE in code, never left to
the model — the model only maps facts to field keys and carries the quote/URL across.
"""

import json
import os
import re

from clue_lib import HERE, openrouter, save_raw

# ---------------------------------------------------------------- field catalog (schema authority)
# Verbatim from origin/platform/comprehensive-account-contact-research:
#   subsystems/research/clue_research/claimstore/packs.py            (CORE_PACK)
#   subsystems/research/clue_research/profiling/fields.py            (RESONANCE_PACK, FACET_PACK)
#   subsystems/research/clue_research/icp/packs.py                   (HEALTHCARE_PRACTICE)
#   subsystems/research/clue_research/profiling/committee/fields.py  (committee fields)
FIELD_CATALOG = """
ACCOUNT-ENTITY FIELDS (registered today):
  core.account_name            str            Canonical account name observation.
  core.primary_domain          str            Primary web domain.
  core.company_about           str            Public company description/about text.
  core.industry                str            Primary industry classification.
  core.employee_count          int            Total headcount.
  core.employee_range          object{label,min,max}
  core.hq_location             object{raw,city,region,country,country_code}
  core.company_linkedin_url    str
  core.company_email           str            General company email (NOT a person's).
  core.company_phone           str            General company phone (NOT a person's direct line).
  core.annual_revenue          object         Revenue figure.
  core.revenue_band            object
  core.primary_tech_stack      list[str]      Detected primary technologies.
  account.recent_funding       object{amount_usd,round}
  account.total_funding        object{amount_usd,estimate_kind}
  account.crm_relationship_status str         enum customer|open_opportunity|prospect|former_customer|none
  account.hiring_velocity_eng  number
  account.operational_pain     str            Synthesized operational pain.
  account.strategic_moves      str            Strategic moves / initiatives.
  account.resonance.culture            str
  account.resonance.employee_sentiment object{label,polarity,summary}
  account.resonance.attrition_signal   object{signal_type,direction,summary}
  account.resonance.eng_blog_tone      object{tone_label,summary}
  account.resonance.public_frustrations list[object{frustration,summary}]
  account.resonance.buying_culture     object{culture_label,summary}
  healthcare.npi               str            National Provider Identifier (registry id).

CONTACT-ENTITY FIELDS (registered today):
  core.work_email              str            Selected contact's observed work email.
  core.direct_phone            str            Selected contact's observed direct phone.
  contact.current_title        str
  contact.job_function         str
  contact.job_level            str
  contact.current_location     object{raw,country}
  contact.organization_relationship object{relationship,basis,organization_id}
  contact.team_membership      list[object]
  contact.persona              str            enum champion|economic_buyer|technical_evaluator|blocker
  contact.role_on_committee    object{role(enum as above),confidence,plausible,rationale}
  contact.class                str            workspace-defined grouping e.g. clinical|business
  contact.facet.nickname            str
  contact.facet.stated_interests    list[str]
  contact.facet.communication_style object{style_label,summary}
  contact.facet.public_appearances  list[object{title,venue,url,date}]
  contact.facet.publications        list[object{title,venue,url,date}]
  contact.facet.causes              list[object{cause,context}]     (use_class hint: sensitive)
  contact.facet.alma_mater          list[str]
  contact.facet.career_history      list[object{org,role,start,end}]
  contact.facet.recent_post         str
"""

STAMPING = """
STAMPING (applied in code after you answer — you do NOT emit these):
  Apollo-normalized value          -> source_key=apollo,       tier 1, extraction_method=api
  Anything derived from an Exa report/page -> source_key=exa_research (deep report) or
                                     exa_search (cheap search/contents), tier 4,
                                     extraction_method=llm_synthesis
  All claims: verification_status=unverified, reuse_scope=tenant_private.
  contact.facet.* additionally require identity_binding + use_class.
"""

INSTRUCTIONS = f"""You convert finished research into structured claim rows for a claim store.

{FIELD_CATALOG}
{STAMPING}

TASK. Read the RESEARCH BUNDLE below and emit ONE JSON object:

{{
  "claims": [
    {{
      "entity": "account:charleston-gi-specialists" | "contact:wanda-punteney" | "contact:thomas-punteney",
      "field_key": "<an EXISTING key from the catalog above, or a PROPOSED key you invent>",
      "is_proposed_field": true|false,
      "value_json": <a value matching the field's value type; string/int/object/array as declared>,
      "evidence_span": "<the verbatim quotation from the source, <=400 chars, or '' if the fact is
                        not quote-backed>",
      "source_url": "<the single best full URL for this fact; REQUIRED, never empty>",
      "origin": "apollo" | "exa_deep" | "exa_cheap",
      "identity_binding": "strong"|"weak",     // contact.facet.* only
      "use_class": "professional-public"|"personal-public-non-sensitive"|"sensitive"  // facet only
    }}
  ],
  "proposed_fields": [
    {{
      "field_key": "...", "entity_type": "account"|"contact", "value_type": "str|int|object|list[str]|list[object]",
      "value_schema": {{...JSON Schema...}},
      "description": "<agent-facing description, one or two sentences>",
      "reuse_scope": "tenant_private"|"public_footprint",
      "why_needed": "<one paragraph: what decision this field drives that no existing field can>"
    }}
  ]
}}

RULES
1. Prefer an EXISTING field key whenever one genuinely fits. Only invent a key when nothing fits;
   invented keys go under a sensible namespace (`account.*`, `healthcare.*`, `contact.facet.*`)
   and MUST also appear in proposed_fields.
2. NEVER invent a fact, a quote, or a URL. Every claim must be traceable to the bundle. If a
   report says NOT FOUND, emit no claim for it.
3. evidence_span must be text that literally appears in the bundle. Do not paraphrase into it.
4. source_url is mandatory on every claim.
5. One fact per claim row. Split enumerations (locations, fax numbers, facilities, people) into
   separate rows rather than cramming a list into one string, EXCEPT where the field's declared
   value type is a list.
6. Emit claims for BOTH entities: the account and the two contacts.
7. For a `contact.facet.*` claim, set identity_binding=strong only when the bundle contains
   explicit identity confirmation for that person; otherwise weak. Set use_class per the category:
   career/role/professional -> professional-public; alma mater/hometown/hobby/tenure milestone ->
   personal-public-non-sensitive; anything faith/health/politics/family -> sensitive (and prefer
   simply not emitting it).
8. Be thorough: aim to capture every distinct researched fact in the bundle. 60-110 claims is a
   reasonable target for this bundle.

Return ONLY the JSON object. No prose, no markdown fence.
"""


def build_bundle():
    parts = []
    acct = json.load(open(os.path.join(HERE, "account_report.json")))
    parts.append("=== A. ACCOUNT DEEP-RESEARCH REPORT (Exa deep-reasoning; origin=exa_deep) ===")
    for k, v in acct.items():
        parts.append(f"\n--- {k} ---\n{v}")

    contact = json.load(open(os.path.join(HERE, "contact_report.json")))
    parts.append(
        "\n\n=== B. CONTACT DEEP-RESEARCH REPORT — Wanda W. Punteney "
        "(Exa deep-reasoning; origin=exa_deep) ==="
    )
    for k, v in contact.items():
        parts.append(f"\n--- {k} ---\n{v}")

    org = (json.load(open(os.path.join(HERE, "raw", "step2_apollo_org.json"))) or {}).get(
        "organization"
    ) or {}
    keep = [
        "id", "name", "website_url", "primary_domain", "linkedin_url", "founded_year", "industry",
        "industries", "estimated_num_employees", "annual_revenue_printed", "raw_address",
        "street_address", "city", "state", "postal_code", "country", "phone",
        "retail_location_count", "short_description", "technology_names",
        "departmental_head_count", "organization_headcount_six_month_growth",
        "organization_headcount_twelve_month_growth", "keywords",
    ]
    slim = {k: org[k] for k in keep if org.get(k) not in (None, "", [], {})}
    parts.append(
        "\n\n=== C. APOLLO ORGANIZATION ENRICHMENT (origin=apollo; tier 1) ===\n"
        "Apollo record URL for provenance: "
        "http://www.linkedin.com/company/charleston-gastroenterology\n"
        + json.dumps(slim, indent=2)
    )

    shortlist = json.load(open(os.path.join(HERE, "committee_shortlist.json")))
    roster = [
        {
            "first_name": p.get("first_name"),
            "last_name_obfuscated": p.get("last_name_obfuscated") or p.get("last_name"),
            "title": p.get("title"),
            "has_email": p.get("has_email"),
        }
        for p in shortlist
    ]
    parts.append(
        "\n\n=== D. APOLLO PEOPLE SEARCH ROSTER (origin=apollo, DEGRADED shortlist: last names "
        "obfuscated, 0 credits). Treat the TITLES as evidence of staffing/workload; do NOT emit "
        "per-person contact claims from this list (the people are not identity-resolved). "
        "Apollo record URL: http://www.linkedin.com/company/charleston-gastroenterology ===\n"
        + json.dumps(roster, indent=2)
    )

    matched = json.load(open(os.path.join(HERE, "matched_contacts.json")))
    slim_matched = {}
    for label, p in matched.items():
        slim_matched[label] = {
            k: p.get(k)
            for k in [
                "id", "name", "first_name", "last_name", "title", "seniority", "headline",
                "email", "email_status", "linkedin_url", "city", "state", "country",
                "departments", "subdepartments", "functions",
            ]
            if p.get(k)
        }
        slim_matched[label]["organization_name"] = (p.get("organization") or {}).get("name")
        slim_matched[label]["employment_history"] = [
            {
                "title": j.get("title"),
                "organization_name": j.get("organization_name"),
                "start_date": j.get("start_date"),
                "end_date": j.get("end_date"),
                "current": j.get("current"),
            }
            for j in (p.get("employment_history") or [])
        ]
    parts.append(
        "\n\n=== E. APOLLO PEOPLE/MATCH — enriched contacts (origin=apollo; tier 1). "
        "Provenance URL: the person's linkedin_url when present, else "
        "https://app.apollo.io/#/people/<id> ===\n" + json.dumps(slim_matched, indent=2)
    )

    parts.append(
        "\n\n=== F. CHEAP GAP-FILL FINDINGS (origin=exa_cheap; these OVERRIDE the deep report's "
        "'NOT FOUND' where they conflict) ===\n"
        "F1. THE HARD DISQUALIFIER — the practice runs gGastro (Modernizing Medicine).\n"
        "  Quote: \"Thomas D. Punteney, Chief Operating Officer of Charleston (S.C.) GI "
        "Specialists, manages operations for three offices and two surgery centers with 11 "
        "providers on staff. Charleston GI Specialists implemented gGastro and its practice "
        "management system, gPM, in 2013.\"\n"
        "  URL: https://www.modmed.com/resources/blog/experts-share-their-thoughts-on-the-right-"
        "ehr-for-gastroenterologists  (published 2022-10-05)\n"
        "  Same passage independently at URL: https://www.beckersasc.com/gastroenterology-and-"
        "endoscopy/3-experts-share-their-thoughts-on-the-right-ehr-for-gastroenterologists/ "
        "(published 2018-07-03)\n"
        "F2. The ModMed relationship is CURRENT (2025), not historical.\n"
        "  Quote: \"Charleston GI increased patient payments with ModMed solutions\"\n"
        "  URL: https://www.modmed.com/resources/success-stories/charleston-gi-increased-patient-"
        "payments-with-modmed-solutions  (published 2025-08-12)\n"
        "F3. Klara (a ModMed product) is the patient-communication platform — and Apollo's "
        "independent technographics also list 'Klara'.\n"
        "  Quote: \"gGastro Patient Collaboration Success Story Gastroenterology Charleston GI "
        "improves the patient experience and operational efficiency with Klara\"\n"
        "  URL: https://www.modmed.com/resources/educational-guides/one-gi-practice-improves-the-"
        "patient-experience-with-klara\n"
        "F4. Facility scale, accreditation and daily patient volume.\n"
        "  Quote: \"Charleston GI, the first and largest gastroenterology practice in the "
        "Lowcountry, consists of three physician practices and two nationally certified and "
        "state-licensed endoscopy centers. Its 11 physicians provide the highest level of medical "
        "care in the field of gastroenterology for up to 200 patients a day.\"\n"
        "  URL: https://www.mindwareconnections.com/hubfs/PDF's/Case%20Studies/DMO%20Case%20"
        "Studies/cs-charleston-gi-cloud-based-speech-recognition-en-us.pdf\n"
        "F5. Speech recognition / dictation in use.\n"
        "  Quote: \"Nuance Dragon Medical One PowerMic\"\n"
        "  URL: https://www.mindwareconnections.com/hubfs/PDF's/Case%20Studies/DMO%20Case%20"
        "Studies/cs-charleston-gi-cloud-based-speech-recognition-en-us.pdf\n"
        "F6. Thomas D. Punteney is Chief Operating Officer (title source for the contact entity).\n"
        "  Quote: \"Thomas D. Punteney, Chief Operating Officer of Charleston (S.C.) GI "
        "Specialists\"\n"
        "  URL: https://www.beckersasc.com/gastroenterology-and-endoscopy/3-experts-share-their-"
        "thoughts-on-the-right-ehr-for-gastroenterologists/\n"
        "F7. Practice-wide fax and phone, from the practice's own site footer.\n"
        "  Quote: \"PHONE 843-722-8000 (8437228000) • FAX 843-647-6066 (8436476066)\"\n"
        "  URL: https://charlestongi.com/careers-portal/\n"
        "F8. Self-description on the homepage.\n"
        "  Quote: \"As the largest independent gastroenterology practice in the Lowcountry\"\n"
        "  URL: https://charlestongi.com/\n"
    )
    return "\n".join(parts)


BUNDLE = build_bundle()
print("BUNDLE CHARS:", len(BUNDLE))
open(os.path.join(HERE, "structuring_bundle.txt"), "w").write(BUNDLE)

MESSAGES = [
    {"role": "system", "content": INSTRUCTIONS},
    {"role": "user", "content": "RESEARCH BUNDLE\n\n" + BUNDLE},
]


def parse_json_content(resp):
    try:
        content = resp["choices"][0]["message"]["content"]
    except Exception:
        return None, "no choices"
    if not content:
        return None, "empty content"
    text = content.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        text = text[start : end + 1]
    try:
        return json.loads(text), None
    except Exception as e:  # noqa: BLE001
        return None, f"json parse error: {e}"


RESULTS = {}
for model in ["z-ai/glm-4.7", "openai/gpt-5-mini"] if __name__ == "__main__" else []:
    label = "step8_structure_" + model.replace("/", "_").replace(".", "")
    resp = openrouter(
        model,
        MESSAGES,
        label=label,
        response_format={"type": "json_object"},
        timeout=900,
    )
    parsed, err = parse_json_content(resp)
    n = len(parsed.get("claims") or []) if parsed else 0
    npf = len(parsed.get("proposed_fields") or []) if parsed else 0
    print(f"  -> {model}: claims={n} proposed_fields={npf} err={err}")
    RESULTS[model] = {"parsed": parsed, "err": err, "usage": resp.get("usage")}
    if parsed:
        save_raw(label + "_parsed", parsed)

if __name__ == "__main__":
  json.dump(
    {m: {"err": r["err"], "usage": r["usage"],
         "n_claims": len(r["parsed"].get("claims") or []) if r["parsed"] else 0,
         "n_proposed": len(r["parsed"].get("proposed_fields") or []) if r["parsed"] else 0}
     for m, r in RESULTS.items()},
    open(os.path.join(HERE, "structuring_comparison.json"), "w"),
    indent=2,
)
