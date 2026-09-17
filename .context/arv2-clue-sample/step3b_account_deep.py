"""Step 3b — THE account deep call, take 2.

WIRE FINDING (step 3a, $0.03 burned proving it): Exa `/search` only returns an `output` object when
the request carries an `outputSchema`. With NO `outputSchema` a `type:"deep-reasoning"` request
returns *only* `results[]` — no report, no `output` key at all. The brief's "no schema => free-form
markdown report" premise does not hold on this endpoint.

Nearest faithful implementation of the same cost bet (ONE deep call carrying a whole dossier):
a FLAT outputSchema whose every property is a free-form markdown section. Nine depth-1 string
properties — inside Exa's 10-property / depth-2 budget — so the model still writes prose with
quotes and URLs (structuring is still done afterwards by the cheap model), while each named
critical (fax numbers, the gGastro verdict, the committee) gets a guaranteed slot instead of
being silently dropped from a free-running essay.
"""

from clue_lib import exa, exa_output_text

ACCOUNT = "Charleston GI Specialists"
DOMAIN = "charlestongi.com"

SYSTEM = f"""You are a B2B account researcher producing an evidence-grade practice dossier for a
healthcare-workflow software vendor. Your subject is EXACTLY ONE entity:

  {ACCOUNT} — the independent gastroenterology group in Charleston, South Carolina, whose website
  is https://{DOMAIN} (also styled "Charleston Gastroenterology Specialists" / "Charleston GI").
  Apollo firmographics for it: 76 employees, founded 2002, HQ 1962 Charlie Hall Blvd, Charleston
  SC 29414, phone +1 843-722-8000, LinkedIn linkedin.com/company/charleston-gastroenterology,
  self-described as "the first and largest independent group of GI specialists in Charleston" with
  "eleven outstanding board-certified gastroenterologists", "four convenient locations and two
  state-of-the-art endoscopy centers".

TARGET LOCK. Research only this practice. Do NOT attribute to it facts about any similarly named
entity — in particular NOT: MUSC Health / Medical University of South Carolina GI, Roper St Francis,
Lowcountry Gastroenterology, Trident/Summerville hospital GI, or any national GI platform
(GI Alliance, United Digestive, One GI, Gastro Health, PE-backed MSOs). If a source is about a
different entity, exclude it and say why. Where confusion is likely, write a DISAMBIGUATION note.

EVIDENCE RULES (non-negotiable, they are the product):
* Every factual assertion carries (a) a verbatim quotation from its source, in quotation marks,
  reproduced exactly, and (b) the full source URL immediately after it.
* If a fact cannot be found on a public page, write "NOT FOUND" for it. Never guess, never infer a
  plausible-sounding value, never substitute an industry generality. An honest "NOT FOUND" is a
  correct answer; a fabricated one is the only real failure.
* Anything you are reasoning to rather than reading, prefix "INFERENCE:" and state its basis.
* Prefer: the practice's own site and its PDFs (new-patient packets, referral forms, notices of
  privacy practices, price transparency files), official registries (NPI/CMS, SC Secretary of
  State, state ASC licensure), the practice's social accounts, local business press, named staff
  LinkedIn profiles, and job postings.

Each field of your answer is free-form Markdown. Be exhaustive: full names, exact titles, numbers,
dates, street addresses, phone AND fax numbers, URLs. Length is not a constraint — citation density
and completeness are what matter. Never return an empty string; if a whole section is unfindable,
return "NOT FOUND" plus what you searched."""

QUERY = (
    f"{ACCOUNT} {DOMAIN} Charleston South Carolina independent gastroenterology practice: "
    "physician ownership and independence, private equity or MSO affiliation, electronic health "
    "record and patient portal vendor, gGastro or Modernizing Medicine, physicians and advanced "
    "practice providers, office locations addresses phone and fax numbers, owned endoscopy center "
    "ambulatory surgery center accreditation, referring physician referral form and referral fax "
    "number, prior authorization precertification, open access direct access colonoscopy "
    "screening recall, new location opening leadership change news, practice administrator CEO "
    "billing revenue cycle manager privacy officer leadership team"
)


def S(desc):
    return {"type": "string", "description": desc}


SCHEMA = {
    "type": "object",
    "properties": {
        "identity_and_disambiguation": S(
            "Markdown. Legal/operating name(s), entity type (P.A./LLC/P.C.), year founded, "
            "corporate-registry evidence (SC Secretary of State filing, EIN, organizational NPI) "
            "if public, main address, main phone, website, LinkedIn page. Then a DISAMBIGUATION "
            "paragraph naming every similarly named Charleston-area GI entity this must not be "
            "confused with, and the evidence separating them. Quote + URL for each fact."
        ),
        "ownership_and_independence": S(
            "Markdown. Is the practice independent and physician-owned, or owned by a hospital "
            "system, private-equity firm, or MSO? Search explicitly for acquisition/partnership "
            "announcements, GI Alliance / United Digestive / One GI / Gastro Health / any PE "
            "platform affiliation, self-descriptions such as 'independent' or 'physician-owned', "
            "Digestive Health Physicians Association (DHPA) membership (DHPA admits only "
            "independent GI practices), and any parent or management company. State plainly which "
            "it is, with verbatim quotes + URLs, and give dates for any ownership change. If no "
            "acquisition evidence exists anywhere, say so explicitly — that absence is a finding."
        ),
        "ehr_technology_and_ggastro_verdict": S(
            "Markdown. THE #1 QUALIFIER. Which EHR / practice-management system does this practice "
            "run? Evidence to hunt: patient-portal branding and the portal login URL (the vendor is "
            "usually visible in the hostname), Notice of Privacy Practices PDFs naming the EHR, job "
            "postings requiring named EHR experience, staff LinkedIn profiles naming the EHR, "
            "online bill-pay / patient-communication vendors. THEN, as its own final line, answer "
            "verbatim: 'gGastro/Modernizing Medicine: YES | NO | NOT FOUND' followed by the "
            "evidence for that answer either way. A wrong answer here is worse than no answer."
        ),
        "providers_staff_and_locations": S(
            "Markdown. Enumerate every physician (full name + credentials) and every advanced "
            "practice provider (NP/PA), and give the total provider count. Then enumerate EVERY "
            "office/clinic location as a list with street address, phone, and fax, and state the "
            "total number of locations. Quote + URL for each."
        ),
        "owned_endoscopy_capacity": S(
            "Markdown. Does the practice own and operate its own endoscopy center(s)/ASC(s)? Name "
            "each facility with address, accreditation (AAAHC/AAAASF/state licensure), number of "
            "procedure rooms if stated, and any NPI/CMS listing. Quote the ownership language "
            "('our endoscopy center', 'physician-owned', 'state-licensed'). Explicitly distinguish "
            "facilities the group OWNS from hospitals where its physicians merely hold privileges."
        ),
        "referral_intake_and_fax_numbers": S(
            "Markdown. How do inbound primary-care referrals actually arrive? List EVERY fax number "
            "published anywhere on the site or in its PDFs — referral fax, medical-records fax, "
            "prior-auth fax, per-office administrative fax — each with its purpose and source URL; "
            "fax numbers are a named critical, hunt them in contact pages, location pages, referral "
            "forms, and PDF letterheads. Give the referring-physician page URL and any downloadable "
            "referral form PDF URL, and describe exactly what the form collects. Conclude whether "
            "intake is manual (fax/phone/paper re-keyed by staff) or electronic/integrated, quoting "
            "the evidence."
        ),
        "prior_auth_recall_and_screening": S(
            "Markdown. Two parts. (a) Public evidence that staff perform prior authorization / "
            "pre-certification: patient FAQ language, new-patient packet text, job postings for "
            "prior-auth or referral coordinators, billing-office instructions — quote it. (b) Does "
            "the practice publicize open-access / direct-access colonoscopy scheduling, and is "
            "there any automated screening-recall or surveillance-reminder program? Quote what "
            "exists; say NOT FOUND explicitly if no recall program is evidenced."
        ),
        "timing_signals_dated": S(
            "Markdown bulleted list. Everything with a DATE in roughly the last 36 months: new "
            "location or endoscopy-center opening, EHR go-live or system change, leadership hire / "
            "retirement / transition, merger or affiliation, new physicians joining, hiring surges "
            "or open roles, awards, anniversaries, notable local press. Each bullet: the date, the "
            "verbatim quote, and the URL."
        ),
        "leadership_and_buying_committee": S(
            "Markdown table plus notes. Every person with a leadership, administrative, operations, "
            "billing/revenue-cycle, compliance/privacy-officer, or IT role — from the website, the "
            "Notice of Privacy Practices, PDFs, LinkedIn, job postings, org-chart sites, or local "
            "press. Columns: Full name | Exact title | Source URL | Verbatim line naming them. "
            "Include physician officers / managing partners where identifiable, and say which "
            "individuals could NOT be found. Completeness and exact titles matter more than "
            "seniority filtering."
        ),
    },
    "required": [
        "identity_and_disambiguation",
        "ownership_and_independence",
        "ehr_technology_and_ggastro_verdict",
        "providers_staff_and_locations",
        "owned_endoscopy_capacity",
        "referral_intake_and_fax_numbers",
        "prior_auth_recall_and_screening",
        "timing_signals_dated",
        "leadership_and_buying_committee",
    ],
}

r = exa(
    {
        "query": QUERY,
        "type": "deep-reasoning",
        "numResults": 25,
        "systemPrompt": SYSTEM,
        "outputSchema": SCHEMA,
        "contents": {
            "text": {"maxCharacters": 10000},
            "highlights": {
                "query": "Charleston GI Specialists endoscopy referral fax EHR ownership leadership",
                "maxCharacters": 2000,
            },
        },
        "stream": False,
    },
    label="step3b_account_deep",
    timeout=900,
)

text = exa_output_text(r)
print("REPORT CHARS:", len(text))
open("account_report.json", "w").write(text)
