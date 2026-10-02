"""Step 8c — chunked structuring with the winning model (GLM-4.7, reasoning off).

Round-2 finding: GLM-4.7 mapped fields materially better than gpt-5-mini (48 vs 28 claims; mini
invented the non-key `providers_staff_and_locations` and filed three fax numbers under
`core.company_phone`), but a single call still under-covers a 34k-char bundle. Round 3 splits the
same bundle into an account call and a contacts call and names the coverage checklist explicitly,
which is the shape the production agent would use anyway (one structuring call per entity).
"""

import json
import os

from clue_lib import HERE, openrouter, save_raw
from step8_structure import FIELD_CATALOG, STAMPING, build_bundle, parse_json_content

BUNDLE = build_bundle()

BASE = f"""You convert finished research into structured claim rows for a claim store.

{FIELD_CATALOG}
{STAMPING}

OUTPUT: ONE JSON object {{"claims": [...], "proposed_fields": [...]}}.

claims[] item shape:
{{"entity": "<entity id>", "field_key": "<existing catalog key, else a proposed key you invent>",
  "is_proposed_field": true|false, "value_json": <value matching the field's declared type>,
  "evidence_span": "<verbatim quotation from the bundle, <=400 chars, '' if not quote-backed>",
  "source_url": "<full URL, REQUIRED>", "origin": "apollo"|"exa_deep"|"exa_cheap",
  "identity_binding": "strong"|"weak", "use_class": "professional-public"|
  "personal-public-non-sensitive"|"sensitive"}}
(the last two only on contact.facet.* rows)

proposed_fields[] item shape:
{{"field_key","entity_type","value_type","value_schema","description","reuse_scope","why_needed"}}
— one entry for every key you marked is_proposed_field. `why_needed` is one paragraph explaining
what decision the field drives that no existing field can.

RULES
1. Prefer an EXISTING catalog key whenever one genuinely fits. A section heading is NOT a field
   key. A fax number is NOT `core.company_phone`. Invent a key only when nothing fits, under a
   sensible namespace (`account.*`, `healthcare.*`, `contact.facet.*`).
2. NEVER invent a fact, quote, or URL. Everything must be traceable to the bundle. Where the
   bundle says NOT FOUND, emit no claim.
3. evidence_span must be text that literally appears in the bundle — never a paraphrase.
4. source_url mandatory on every claim.
5. ONE FACT PER ROW. Split every enumeration — each office location, each fax number, each
   endoscopy centre, each staff role, each timing signal, each person — into its own row, unless
   the field's declared value type is itself a list.
Return ONLY the JSON object, starting with '{{'. No prose, no markdown fence, no thinking aloud.
"""

ACCOUNT_TASK = """
SCOPE: emit claims for the ACCOUNT entity only — entity id "account:charleston-gi-specialists".
Ignore contact-level personal facts in this pass.

COVERAGE CHECKLIST — work through every one of these and emit a row wherever the bundle supports
it. Do not stop early; 55-80 account rows is the expected range.
 - Canonical name, domain, about text, industry, LinkedIn, founded year, employee count,
   annual revenue, HQ location, main phone, practice-wide fax number.
 - The EHR / practice-management system, its vendor, the year it went live, and the fact that the
   vendor relationship is current in 2025. THE gGastro / Modernizing Medicine determination is the
   single most important claim in this bundle — emit it explicitly and quote the evidence.
 - Every other named technology: the patient-communication platform, the speech-recognition
   product, the patient portal name, the online bill-pay / text-to-pay capability, and Apollo's
   detected stack.
 - Ownership and independence: the self-description, the dated independence statement, the absence
   of any PE/MSO acquisition evidence.
 - EACH office location as its own row (4 of them) with its address.
 - EACH endoscopy centre / ASC as its own row (3 of them) with address, plus their accreditation
   and licensure status, procedure-room count where stated, and the legal entities named in the SC
   regulatory filings.
 - Provider counts (note the two conflicting figures and emit both, each with its own source).
 - Daily patient volume.
 - Referral intake: the referring-physician page, what the referral form does, EACH published fax
   number as its own row with its purpose, and the "no referral needed" open-access policy.
 - Prior-authorization and referral workload evidenced by STAFF ROLES in the Apollo roster —
   the Prior Authorization Specialist, the Referral Coordinator, the Recall Specialist, the two
   Medical Records Clerks, the Team Scheduler, the Front Office Specialist. Each is its own row and
   is strong evidence of a manual workload.
 - The recall programme situation (a human Recall Specialist rather than an automated programme).
 - EACH dated timing signal as its own row: the Certificate of Need filings and their dates, the
   Carnes Crossroads / Windmill Station development, the Lowcountry Endoscopy Center build, the
   December 2025 independence article, the 2025 ModMed case study, headcount trend.
 - Operational pain and strategic posture syntheses.
 - Resonance: buying culture / procurement posture where the evidence supports it.
"""

CONTACT_TASK = """
SCOPE: emit claims for the two CONTACT entities only —
  "contact:wanda-punteney"  (Wanda W. Punteney, Chief Executive Officer / Administrator)
  "contact:thomas-punteney" (Thomas D. Punteney, Chief Operating Officer)
Ignore account-level firmographics in this pass.

COVERAGE CHECKLIST — 30-45 contact rows expected.
 - For EACH person: current title, job function, job level/seniority, current location,
   organization relationship, work email + its verification status, LinkedIn URL, committee
   persona (economic_buyer / technical_evaluator / champion / blocker) and the role_on_committee
   object with a rationale.
 - Wanda: the identity-confirmation anchors (each anchor its own row), the 1989 tenure and the
   ~37-year service milestone, the SCMGMA 2005 Governor role, the CEO-of-record roles in the SC
   DHEC Certificate of Need filings for Charleston Endoscopy Center LLC and Summerville Endoscopy
   Center LLC, the Post & Courier 2017 quote, the Cypress Engineering 2023 testimonial, and the
   personalization hooks and suggested openers grounded in those.
 - Thomas: the COO title and its source, the published operational scope (three offices, two
   surgery centers, 11 providers), his role as the person who selected and implemented gGastro/gPM
   in 2013 and later the cloud EHR, the Becker's ASC / ModMed appearance as a published
   professional appearance, and his verified work email.
 - Governance: identity_binding=strong only where the bundle explicitly confirms identity
   (Wanda has four converging anchors; Thomas is named-with-title in two independent published
   sources plus an Apollo verified email on the practice domain). use_class per category.
 - Do NOT emit health, faith, politics, family, or any special-category material, and do NOT
   speculate about any relationship between the two same-surname executives.
"""

PASSES = [
    ("step8c_account", ACCOUNT_TASK),
    ("step8c_contacts", CONTACT_TASK),
]

merged_claims = []
merged_proposed = []
for label, task in PASSES:
    resp = openrouter(
        "z-ai/glm-4.7",
        [
            {"role": "system", "content": BASE + task},
            {"role": "user", "content": "RESEARCH BUNDLE\n\n" + BUNDLE},
        ],
        label=label,
        response_format={"type": "json_object"},
        reasoning={"enabled": False},
        max_tokens=32000,
        timeout=1500,
    )
    parsed, err = parse_json_content(resp)
    if not parsed:
        print(f"  !! {label} failed: {err}")
        continue
    c = parsed.get("claims") or []
    p = parsed.get("proposed_fields") or []
    print(f"  -> {label}: claims={len(c)} proposed={len(p)}")
    merged_claims.extend(c)
    merged_proposed.extend(p)
    save_raw(label + "_parsed", parsed)

json.dump(
    {"claims": merged_claims, "proposed_fields": merged_proposed},
    open(os.path.join(HERE, "structured_raw.json"), "w"),
    indent=2,
)
print("MERGED:", len(merged_claims), "claims,", len(merged_proposed), "proposed fields")
