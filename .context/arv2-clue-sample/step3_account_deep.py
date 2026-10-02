"""Step 3 — THE account deep call. ONE Exa `deep-reasoning` request, NO outputSchema.

The whole cost bet: one free-form, citation-dense report per subject instead of N schema-bound
calls (Exa's outputSchema caps at 10 properties / depth 2). Structuring happens later, cheaply.
"""

from clue_lib import exa, exa_output_text

ACCOUNT = "Charleston GI Specialists"
DOMAIN = "charlestongi.com"

SYSTEM = f"""You are a B2B account researcher producing an evidence-grade practice dossier for a
healthcare-workflow software vendor. Your subject is EXACTLY ONE entity:

  {ACCOUNT} — the independent gastroenterology group in Charleston, South Carolina, whose
  website is https://{DOMAIN} (also styled "Charleston Gastroenterology Specialists" /
  "Charleston GI").

TARGET LOCK. Research only this practice. Do NOT attribute to it facts about any similarly named
entity — in particular NOT: MUSC Health / Medical University of South Carolina GI, Roper St.
Francis, Charleston Gastroenterology Associates, Lowcountry GI, Trident Medical Center GI, any
national GI platform (GI Alliance, United Digestive, One GI, Gastro Health, PE-backed MSOs), or
any non-Charleston practice. If a source is about a different entity, say so explicitly and
exclude it. When two entities could be confused, add a short DISAMBIGUATION note naming both.

EVIDENCE RULES (non-negotiable):
* Every factual assertion carries (a) a verbatim quotation from the source, in quotation marks,
  reproduced exactly, and (b) the full source URL on the same line or immediately after.
* If a fact cannot be found on a public page, write "NOT FOUND" for it. Never guess, never infer
  a plausible-sounding value, never fill a gap with an industry generality. An honest "NOT FOUND"
  is a correct answer and is far more valuable than a guess.
* Mark anything you are inferring rather than reading with "INFERENCE:" and state the basis.
* Prefer the practice's own website, its PDFs (new-patient packets, referral forms, notices of
  privacy practices), official registries (NPI/CMS, state licensure, SC Secretary of State),
  the practice's social accounts, local business press, and named staff LinkedIn profiles.

Write in Markdown with exactly the section headings given in the user's request, in that order.
Be exhaustive and specific: names, numbers, dates, addresses, phone AND fax numbers, URLs.
Length is not a constraint; completeness and citation density are what matter."""

QUERY = f"""Produce a complete account dossier on {ACCOUNT} ({DOMAIN}), the Charleston, South
Carolina independent gastroenterology practice. Use these exact section headings:

## 1. Identity & disambiguation
Legal/operating name(s), entity type (P.A./LLC/P.C.), year founded, corporate registry evidence
(SC Secretary of State / EIN / NPI organizational number if public), main address, main phone,
website, LinkedIn page. Name any similarly named Charleston-area GI entity it must not be
confused with, and cite the evidence separating them.

## 2. Ownership & independence
Is this practice independent and physician-owned, or owned by a hospital system, a private-equity
firm, or a management services organization (MSO)? Look explicitly for: acquisition/partnership
press releases, GI Alliance / United Digestive / One GI / Gastro Health / PE platform affiliation,
"physician-owned" or "independent" self-description, membership in the Digestive Health Physicians
Association (DHPA, which represents only independent GI practices), and any parent company. State
plainly which it is, with quotes. If ownership changed at any point, give dates.

## 3. EHR / practice-management technology  (THE #1 QUALIFIER)
Which electronic health record and practice-management system does this practice run? Look for:
patient-portal branding and portal login URLs (the portal vendor is usually visible in the URL or
page), Notice of Privacy Practices PDFs naming the EHR, job postings requiring named EHR
experience, staff LinkedIn profiles naming the EHR, patient-payment/billing vendor names, and the
patient-communication platform. THEN ANSWER THIS EXPLICITLY AND SEPARATELY:
  "Does this practice run gGastro (gGastro / gMed) or Modernizing Medicine (ModMed / gGastro
  successor products)?  YES / NO / NOT FOUND"  — and give the evidence for your answer either way.
This single question decides whether the account is workable, so treat a wrong answer as worse
than no answer.

## 4. Providers, staff & locations
Enumerate the physicians (full names + credentials), advanced practice providers (NP/PA), and the
total provider count. Enumerate every office/clinic location with its street address, phone, and
fax. State the total number of locations. Cite the pages.

## 5. Owned endoscopy / ambulatory surgery capacity
Does the practice own and operate its own endoscopy center(s) or ASC(s)? Name each facility, its
address, its accreditation (AAAHC/AAAASF/state licensure), the number of procedure rooms if
stated, and any NPI/CMS listing. Quote the ownership language ("our endoscopy center", "physician-
owned", "state-licensed"). Distinguish owned facilities from hospitals where physicians merely
hold privileges.

## 6. Referral intake mechanics  (fax numbers are a named critical)
How do inbound referrals from primary-care physicians actually arrive? Find and list EVERY fax
number published anywhere on the site or its PDFs — referral fax, records fax, prior-auth fax,
per-office administrative fax — with what each is for. Find the referring-physician page and any
downloadable referral form (give the PDF URL) and describe exactly what it collects. State whether
referral intake looks manual (fax/phone/paper form re-keyed by staff) or electronic/integrated,
and quote the evidence.

## 7. Prior-authorization / pre-certification workload
Any public evidence that staff perform prior authorization or pre-certification: patient FAQ
language, new-patient packet text, job postings for prior-auth or referral coordinators, billing
office instructions. Quote it.

## 8. Colonoscopy screening & recall program
Does the practice publicize open-access / direct-access colonoscopy scheduling? Is there any
automated screening-recall or reminder program for patients due for surveillance? Quote what
exists; say NOT FOUND if there is no evidence of a recall program.

## 9. Timing signals (dated)
Anything with a date in the last ~36 months: new location or endoscopy center opening, EHR
go-live or system change, leadership hire/retirement/transition, practice merger or affiliation,
new physician joining, hiring surges, awards, anniversaries, notable local press. Give the date and
the quote for each.

## 10. Leadership, administration & buying committee
Name every person with a leadership, administrative, operations, billing/revenue-cycle,
compliance/privacy-officer, or IT role you can find — from the website, the Notice of Privacy
Practices, PDFs, LinkedIn, job postings, local press, or org-chart sites. For each: full name,
exact title, the source URL, and the verbatim line naming them. Include the physician officers /
managing partners if identifiable. This list is used to route executive outreach, so completeness
and exact titles matter more than seniority filtering.

## 11. Operational pain & strategic posture
Synthesize (marked as synthesis, grounded in the quotes above) what this practice's operational
burden looks like and what it appears to be investing in.

## 12. Gaps
List every item above you could not find, explicitly, as a bulleted "NOT FOUND" list."""

r = exa(
    {
        "query": QUERY,
        "type": "deep-reasoning",
        "numResults": 25,
        "systemPrompt": SYSTEM,
        "contents": {
            "text": {"maxCharacters": 10000},
            "highlights": {
                "query": "Charleston GI Specialists endoscopy referral fax EHR ownership",
                "maxCharacters": 2000,
            },
        },
        "stream": False,
    },
    label="step3_account_deep",
    timeout=900,
)

text = exa_output_text(r)
print("REPORT CHARS:", len(text))
print(text[:1500])
open("account_report.md", "w").write(text)
