# Clue sample run — one full account-research pass, live

**Run date:** 2026-08-26 · **Executor:** ARV2 sample harness (python3 stdlib, `.context/arv2-clue-sample/`)
**Account researched:** Charleston GI Specialists — `charlestongi.com` — Charleston, South Carolina
**Primary contact researched:** Wanda W. Punteney, Chief Executive Officer

| | |
|---|---|
| **Total cash spent** | **$0.2819** (Exa $0.1590 + OpenRouter $0.1229) |
| **Apollo credits spent** | **3** of the 12 authorised |
| **Budget ceiling** | $2.00 / 12 credits — came in at **14% of the cash ceiling** |
| **Deep-research calls** | 2 (one for the account, one for the contact) |
| **Claim rows produced** | **126**, every one carrying a source URL and a verbatim evidence span |
| **Headline** | The account is **disqualified**. It runs gGastro. A **$0.007** search found what the **$0.029** deep call had reported as "NOT FOUND". |

---

## 0. The context the agent ingested

This is the simulated Clue workspace state the run was given before it made a single call — the
client knowledge base and the ICP, exactly as the real agent would read them from the claim store.

**Client:** Insight Health.
**Products:** *Fax & Referral Agent* (flagship — automates manual fax/portal referral intake into
the EHR); *Direct Access Colonoscopy* (secondary — only monetisable where the practice owns
endoscopy capacity); *Colonoscopy Recall* (future).

**ICP:** independent, physician-owned GI/gastroenterology practices in the US Southeast, roughly
5–50 physicians, running an EHR Insight Health integrates with (Epic, eClinicalWorks, etc.).
**Hard disqualifier: gGastro / Modernizing Medicine.**

**Priority signals:** manual fax-based referral intake · prior-authorisation workload · owned
ASCs/endoscopy centres · expansion or new facility · EHR go-live · leadership change · no
automated recall programme.

**Account priorities, in order:** independence (no PE/MSO/hospital owner) > EHR fit > owned
capacity > referral-heavy operations > timing signals.

**Depth bar:** the two hand-built dossiers (`digestive-healthcare-of-georgia-p-c.md`,
`eagle-physicians-associates-p-a.md`). Both of their domains were **excluded from discovery** so
this run could not cheat off the answer key.

---

## 1. Discovery and prioritisation

Two Exa searches, $0.007 each, `numResults: 10`, with `digestivehealthcare.net` and `eaglemds.com`
excluded. Twenty results, of which these were the real candidate accounts. This is the list that
becomes approvable account cards in the product — no deep money is spent before this gate.

| # | Candidate | Domain | Region | One-line fit rationale | Priority |
|---|---|---|---|---|---|
| 1 | **Charleston GI Specialists** | charlestongi.com | Charleston, SC | Hit on **both** queries — the structural ICP query *and* the referral/fax query. Self-describes as the first and largest **independent** GI group in Charleston; multiple owned endoscopy centres; dedicated referring-physician page. | **PICKED** |
| 2 | Athens Gastroenterology Center | athensgicenter.com | Athens, GA | Also a double hit (ICP query + a dedicated `/referrals` page). Smaller footprint. | 2nd |
| 3 | Asheville Gastroenterology Associates | ashevillegastro.com | Asheville, NC | Independent GI, P.A., own endoscopy centre. Single-query hit. | 3rd |
| 4 | Charleston GI (same as #1, via referral-form PDF) | charlestongi.com | — | Corroborated #1's referral-intake signal from a second angle. | — |
| 5 | Gastroenterology Associates of Gainesville | gastrogainesville.com | Gainesville, GA | Explicit "Endoscopy Centers" page — owned capacity. | 4th |
| 6 | Digestive Disease Group | digestivediseasegroup.com | Greenwood, SC | Independent GI, Southeast. | 5th |
| 7 | SC Gastroenterology | scgastro.com | SC | Surfaced via a PDF titled *"CENTRALIZED REFERRAL FAX # – 803.667.9126"* — a fax-intake signal in the search result itself. | 6th |
| 8 | Charlotte Gastroenterology & Hepatology | charlottegastro.com | Charlotte, NC | Surfaced via an "Easy Access GI Referral" PDF. Larger group. | 7th |
| 9 | Carolina Digestive Diseases | cddgastro.com | NC | Direct referral form PDF. | 8th |
| 10 | Gastroenterology Associates of Pensacola | gapgi.com | Pensacola, FL | Two referral-by-fax PDFs, one dated 2025-11. | 9th |
| 11 | Blount Gastroenterology | blountgastro.com | Maryville, TN | Small; likely under the 5-physician floor. | low |
| 12 | West Georgia Gastroenterology | westgagastro.com | Carrollton, GA | Small. | low |
| 13 | Advanced GI & Hepatology | advancedgijax.com | Jacksonville, FL | Referral form PDF only. | low |
| 14 | Tampa Gut MD | tampagutmd.com | Tampa, FL | Referring-physician page. | low |
| 15 | Southeastern Endoscopy Center | southeasternendoscopy.com | SC | A centre, not a physician group — wrong entity type. | reject |

**Why Charleston GI was picked:** it was the only candidate to surface independently in *both*
discovery queries, and its snippet asserted all three of the top ICP priorities at once —
independence, owned endoscopy capacity, and a referral-intake surface.

---

## 2. Charleston GI Specialists — the account

> Everything in this section is a **human-readable view over the 104 account claim rows** in
> `claims.json`. No dossier document is stored anywhere in the platform. Each fact below is one
> structured claim with a field key, a value, an evidence span and a source URL; the prose is
> rendered from them. Every quotation is reproduced exactly as it appears in the source.

### 2.1 Identity

Charleston GI Specialists (also styled *Charleston Gastroenterology Specialists* and *Charleston
GI*), a gastroenterology practice headquartered at **1962 Charlie Hall Blvd, Charleston, SC 29414**,
main line **843-722-8000**, fax **843-647-6066**. Apollo reports it founded in **2002** with **76
employees** and **$34.9M** annual revenue. LinkedIn:
`linkedin.com/company/charleston-gastroenterology`.

An NPI directory listing identifies the organisation and, usefully, an employee:

> "1962 Charlie Hall Blvd, Charleston, SC 29414-5837" … "Official Title BUSINESS SERVICES MANAGER"
> — https://opengovus.com/npi/1205835865

**Disambiguation.** The research was target-locked to the entity operating `charlestongi.com`, and
explicitly excluded MUSC Health GI, Roper St. Francis GI, Lowcountry Gastroenterology, Trident/
Summerville hospital GI, and every national GI platform. One trap was caught and handled correctly:
a Roper St. Francis provider directory lists Charleston Gastroenterology Specialists' locations, and
the agent refused to read that as ownership evidence —

> "A Roper page is explicitly labeled 'Roper St. Francis Healthcare' even though it lists Charleston
> Gastroenterology Specialists locations; it is not treated as ownership evidence for Charleston GI."

### 2.2 Ownership and independence — **PASSES**

The practice states its independence in its own voice, and repeated it recently and deliberately:

> "As the largest independent gastroenterology practice in the Lowcountry"
> — https://charlestongi.com/

> "At Charleston GI, we're proud to maintain a local, patient-centered focus" … "Charleston GI
> remains committed to being a trusted, independent resource."
> — https://charlestongi.com/news&events/navigating-the-changing-gi-investment-landscape-what-it-means-for-you/ (**29 December 2025**)

A third-party construction record independently describes it as "a private physicians group"
(https://www.gmka.com/charleston-gastro-specialists).

No acquisition or partnership announcement involving GI Alliance, United Digestive, One GI, Gastro
Health, or any PE/MSO parent was found. The agent was careful to label that correctly:

> "PE/MSO affiliation: NOT FOUND, not a definitive negative."

**That December 2025 article is worth reading twice.** A practice that publishes a piece titled
*"Navigating the Changing GI Investment Landscape: What It Means for You"* is a practice that has
been approached by consolidators and has chosen, publicly, to stay independent. That is both a
buying-posture signal and the sharpest possible positioning hook — for a different vendor.

### 2.3 EHR — **FAILS. This is the disqualifier.**

The deep-research call reported the EHR as **NOT FOUND**:

> "The publicly indexed evidence reviewed does not name the EHR/practice-management vendor, portal
> hostname, or an EHR go-live/change. NOT FOUND. gGastro/Modernizing Medicine: NOT FOUND — no
> reviewed public source names gGastro or Modernizing Medicine."

A **$0.007** follow-up search found the answer in the vendor's own marketing, in three independent
places.

**The finding, verbatim** (published by Modernizing Medicine, and republished by Becker's ASC):

> "Thomas D. Punteney, Chief Operating Officer of Charleston (S.C.) GI Specialists, manages
> operations for three offices and two surgery centers with 11 providers on staff. **Charleston GI
> Specialists implemented gGastro and its practice management system, gPM, in 2013.** After using
> the EHR in its endoscopy center for four years, Mr. Punteney then implemented the cloud-b[ased]…"
> — https://www.modmed.com/resources/blog/experts-share-their-thoughts-on-the-right-ehr-for-gastroenterologists (2022-10-05)
> — and independently at https://www.beckersasc.com/gastroenterology-and-endoscopy/3-experts-share-their-thoughts-on-the-right-ehr-for-gastroenterologists/ (2018-07-03)

**The relationship is current, not historical** — ModMed published a fresh customer case study in
August 2025:

> "Charleston GI increased patient payments with ModMed solutions"
> — https://www.modmed.com/resources/success-stories/charleston-gi-increased-patient-payments-with-modmed-solutions (**2025-08-12**)

**And a third, independent corroboration** — the patient-communication platform is Klara, a ModMed
product:

> "gGastro Patient Collaboration Success Story · Gastroenterology · Charleston GI improves the
> patient experience and operational efficiency with Klara"
> — https://www.modmed.com/resources/educational-guides/one-gi-practice-improves-the-patient-experience-with-klara

**Cross-provider corroboration worth noting:** Apollo's technographics — fetched *before* any of
this, from a completely different provider — independently list **"Klara"** in
`technology_names`. Two providers that share no data lineage converged on the same vendor
relationship.

Also detected: **Nuance Dragon Medical One / PowerMic** for clinician dictation, and a patient
portal branded **"My GI Patient Portal"**.

> **Verdict: `gGastro/Modernizing Medicine: YES`. Charleston GI Specialists is disqualified under
> the ICP's single hard disqualifier.** Everything below is therefore evidence about *the machine*,
> not a live opportunity — but it is exactly what a qualifying account's dossier would contain.

### 2.4 Providers, staff and locations

The roster page names them individually:

**Gastroenterologists:** Jeffrey M. Basile, MD · Theodore G. Gourdin, MD · William F. Marsteller IV,
MD · Marc D. Noble, MD · Lee M. Royall, MD · R Sidney G. Smith, MD · William Brener, MD *(Retired)* ·
John K. Corless, MD *(Retired)*
**Pathology:** Tom D. Carico, MD
**Advanced practice providers:** Renee L. Larsen, PA-C · Emily K. Brown, PA-C · Heather Harrison,
MMS, PA-C · Sandi (Beth) Engler, PA-C
**Administration/nursing:** Stephanie C. Andrews, RN, BSN · Julie Q. Dupree, LPN · Gabby Rodriguez,
BSN, RN · Hilliary Goode, BS, MSN, CRNA
— all from https://charlestongi.com/doctors-and-staff/

**A genuine conflict the run surfaced rather than smoothed over — the practice states three
different physician counts on its own website:**

| Count | Source quote | URL |
|---|---|---|
| **10** | "our medical team includes 10 outstanding board-certified gastroenterologists" | /doctors-and-staff/ |
| **11** | "eleven outstanding board-certified gastroenterologists" | / (homepage) |
| **12** | "Our team includes 12 incredible board-certified physicians." | /for-patients/faq/endoscopy-faqs/ |

All three are stored as separate claims with separate sources. In the platform this is precisely
what `conflict_flag` and the human review surface exist for — one number would have been a guess.

**Four offices** (the site footer publishes all of them):
1. **West Ashley** — 1962 Charlie Hall Boulevard, Charleston, SC 29414 *(co-located with Charleston Endoscopy Center)*
2. **Summerville** — 328 Midland Parkway, Summerville, SC 29485 *(co-located with Summerville Endoscopy Center)*
3. **Carnes Crossroads** — Windmill Station, 2001 2nd Avenue, Suite 101, Summerville, SC 29486
4. **Mount Pleasant** — 180 Wingo Way, Ste. 305, Mount Pleasant, SC 29464

### 2.5 Owned endoscopy capacity — **strong** (would have been a strong DAC fit)

> "Charleston GI also operates **three nationally certified and state licensed endoscopy centers**."
> — https://charlestongi.com/referring-physicians/

| Facility | Address | Evidence |
|---|---|---|
| Charleston Endoscopy Center | 1962 Charlie Hall Blvd, Charleston, SC 29414 | site footer; ASGE Endoscopy Unit Recognition Program (per its former medical director's profile) |
| Summerville Endoscopy Center | 328 Midland Parkway, Summerville, SC 29485 | site footer; "an office-based center with **two procedure rooms**", built for "a private physicians group" — https://www.gmka.com/charleston-gastro-specialists |
| Lowcountry Endoscopy Center | 207 McBride Ln., Summerville, SC 29486 | site footer; built by Cypress Engineering (project page dated 2023-03-07) |

**Ownership is proved at the registry level, not inferred.** South Carolina Department of Public
Health Certificate-of-Need filings name the legal entities and their CEO:

> "Summerville Endoscopy Center, LLC by Wanda W Punteney, its CEO" · "Charleston Endoscopy Center,
> LLC by Wanda W. Punteney, its CEO"
> — https://dph.sc.gov/sites/scdph/files/2025-04/2025_March_Archived_CON_Applications.pdf
> — https://dph.sc.gov/sites/scdph/files/2024-08/2024_August_Archived_CON_Applications.pdf

That single find does three jobs at once: it confirms the contact's identity, it establishes that
the practice owns the endoscopy centres through named LLCs, and — because CON filings are how new
healthcare capacity gets approved in South Carolina — it is a **live expansion signal**.

### 2.6 Referral intake and fax — the flagship product's evidence

> "For referring physicians only, this form enables you to schedule an appointment with Charleston
> GI for your patient." — https://charlestongi.com/referring-physicians/

The referring-physician page publishes **PHONE 843-722-8000** and **FAX 843-647-6066**, and offers a
set of downloadable PDFs: Appointment Request Form, Anesthesia Patient Letter, HIPAA Privacy Policy,
Endoscopy Financial Information Form, Financial Policy, Patient Information Form, Patient Rights and
Responsibilities.

**Fax numbers found:**

| Fax | Purpose | Source |
|---|---|---|
| **843-647-6066** | practice-wide; published in the footer of every page including the referring-physician page | https://charlestongi.com/referring-physicians/ |
| **843-723-7850** | listed by the Roper St. Francis directory against all four locations | Roper provider directory |

The two disagree, and the run said so rather than picking one: *"fax discrepancy requires
confirmation."*

**The referral surface is a downloadable PDF plus a fax line — the exact manual, re-keyed intake the
Fax & Referral Agent replaces.** And the practice runs **open access**:

> "Schedule an appointment 5 days a week, no referral needed!" — https://charlestongi.com/doctors-and-staff/

### 2.7 Prior authorisation and recall — found by Apollo, not by the web

The deep call could not evidence prior-auth workload from public pages:

> "A public statement explicitly assigning prior-authorization/pre-certification work to named staff
> or a job posting: NOT FOUND."

**Apollo's staff roster answered it in one 0-credit call.** These are live job titles at the
practice:

| Apollo-listed title | What it proves |
|---|---|
| **Prior Authorization Specialist** | A dedicated human FTE on prior auth — the workload is real and staffed |
| **Referral Coordinator** | A dedicated human FTE on referral intake — manual intake, staffed |
| **Recall Specialist** | **A dedicated human doing colonoscopy recall.** Not "no recall programme" — a *manual* recall programme, which is a stronger wedge for the Recall product than an absence would be |
| Medical Records Clerk ×2 | Manual records handling |
| Team Scheduler, Front Office Specialist, HR Coordinator/Carnes Office Manager, Clinical Manager | Front-office operations depth |

**This is the single most important architectural lesson of the run.** Three of the ICP's priority
signals — manual referral intake, prior-auth workload, recall programme status — were *invisible to
web research* and *trivially visible in an org chart*. Job titles are an operational X-ray. Apollo
earns its place not as a discovery tool but as the workload sensor.

### 2.8 Procedure volume — the ROI arithmetic, published by the practice itself

> **"2020 Practice Statistics — Total procedures: 16,365 · Total Colonoscopies: 11,585 · Total
> precancerous polyps: 5,107 · Total Cancer: 66"**
> — https://charlestongi.com/referring-physicians/

Plus, from a vendor case study:

> "Its 11 physicians provide the highest level of medical care in the field of gastroenterology for
> **up to 200 patients a day**."
> — Nuance Dragon Medical One case study PDF

11,585 colonoscopies a year across three owned centres is the number every ROI slide in the Insight
Health deck needs, and the practice publishes it on its own referrals page. It cost $0.004 to find.

### 2.9 Timing signals (dated)

| Date | Signal | Evidence |
|---|---|---|
| **2025-12** | Certificate of Need filing | SC DPH archived CON applications, December 2025 |
| **2025-12-29** | Publishes *"Navigating the Changing GI Investment Landscape"*, restating independence | charlestongi.com/news&events/… |
| **2025-08-12** | ModMed publishes a fresh customer case study — vendor relationship active | modmed.com/resources/success-stories/… |
| **2025-03** | Certificate of Need filing | SC DPH archived CON applications, March 2025 |
| **2025-04-18** | Publishes open-access InterStim programme page | charlestongi.com/procedures/interstim/ |
| **2024-08** | Certificate of Need filing | SC DPH archived CON applications, August 2024 |
| **2023-03-07** | Lowcountry Endoscopy Center project completed (Cypress Engineering) | cypresseng.com/project/lowcountry-endoscopy-center/ |
| **2017-04-30** | Carnes Crossroads / Windmill Station groundbreaking, CEO quoted | Post and Courier |
| trend | Apollo headcount 12-month growth **−9.4%**, 6-month **−6.5%** | Apollo org enrich |

Three Certificate-of-Need filings in eighteen months is an unusually loud expansion signal, and it
came free with the contact research.

### 2.10 Operational pain and posture (synthesis, marked as such)

> "Referral intake and prior authorization appear to be manual, labor-intensive processes, evidenced
> by dedicated roles for Referral Coordinators and Prior Authorization Specialists."

> "Expansion into Carnes Crossroads/Windmill Station and construction of Lowcountry Endoscopy Center
> to support regional growth."

Resonance: culture reads *"Independent, local, patient-centered"*; buying posture reads long-term
and partnership-oriented (a practice that has run the same specialty EHR since 2013 and publicly
defends its independence is not a fast, transactional buyer).

---

## 3. The buying committee

Every row carries where it came from and whether identity is confirmed. **Apollo and the open web
found almost entirely different people** — the executives were invisible to Apollo, and the
operational staff were invisible to the web.

| # | Name | Title | Source | Identity confirmed? |
|---|---|---|---|---|
| 1 | **Wanda W. Punteney** | Chief Executive Officer / "Administrator, CEO" | **web + apollo** | ✅ **CONFIRMED** — four converging anchors (employer bio, LinkedIn, Post & Courier, SC DPH CON filings) + Apollo verified email |
| 2 | **Thomas D. Punteney** | Chief Operating Officer | **web + apollo** | ✅ **CONFIRMED** — named with title in two independent published sources (ModMed, Becker's ASC) + Apollo verified email on the practice domain |
| 3 | Sherry M. Searson | Business Services Manager | web (NPI registry) | ⚠️ name + title on a public registry record only |
| 4 | Stephanie C. Andrews, RN, BSN | Director of Nursing — Lowcountry & Summerville Endoscopy Centers | **web + apollo** | ✅ appears on the practice's own staff page *and* in Apollo |
| 5 | Julie Q. Dupree, LPN | Clinical Manager | **web + apollo** | ✅ on the staff page *and* in Apollo |
| 6 | Jessica Ha\*\*\*y | HR Coordinator / Carnes Office Manager | apollo | ⚠️ last name obfuscated (degraded search payload) |
| 7 | **Grace Ha\*\*\*s** | **Prior Authorization Specialist** | apollo | ⚠️ obfuscated — but the *title* is the signal |
| 8 | **Katelyn Lu\*\*\*s** | **Referral Coordinator** | apollo | ⚠️ obfuscated — title is the signal |
| 9 | **Jerri Mc\*\*\*l** | **Recall Specialist** | apollo | ⚠️ obfuscated — title is the signal |
| 10 | Karen Bo\*\*\*s | Medical Records Clerk | apollo | ⚠️ obfuscated |
| 11 | Amanda Wa\*\*\*n | Medical Records Clerk | apollo | ⚠️ obfuscated |
| 12 | Chelsey Ke\*\*\*y | Team Scheduler | apollo | ⚠️ obfuscated |
| 13 | Leanna Li\*\*\*s | Front Office Specialist | apollo | ⚠️ obfuscated |
| 14 | John K. Corless, MD | Former physician partner / Medical Director (departed 6/30/18) | web | ✅ historical — correctly flagged as *not current* |
| 15–22 | Basile, Gourdin, Marsteller, Noble, Royall, Smith, Brener (ret.), Carico | Gastroenterologists / Pathology | web (practice roster) | ✅ named on the practice's own site |

### The Apollo coverage trap, observed live

The `ARV2-apollo-api-contract.md` document warned that domain-scoped people search on a small
practice can miss the org under a name variant. **It happened exactly as documented, and the
mitigation worked:**

- `people/api_search` scoped by `organization_ids` (the id from org enrich, `5500af3d…`) returned
  **3 people**. Scoped by domain it returned **25**. Union: 25.
- **Neither search returned the CEO or the COO.**
- `people/match` found Wanda Punteney anyway — attached to a **different Apollo organisation id**
  (`66e6b7de…`, "Charleston GI") than the one org-enrich returned (`5500af3d…`, "Charleston GI
  Specialists"). Apollo holds this practice under two org records, and the executives sit under the
  one that neither search query reaches.

**Operational rule this produces:** never trust a single Apollo scoping. Search by org id *and* by
domain, union the results, and then `people/match` named executives directly — the match endpoint
resolves across org records that search does not.

---

## 4. The enriched contacts

Apollo `people/match`, 1 credit each, no phone reveal (that needs an HTTPS webhook receiver we do
not have, and costs +8 credits).

| Field | Wanda W. Punteney | Thomas D. Punteney |
|---|---|---|
| **Work email** | **wanda.punteney@charlestongi.com** | **tommy.punteney@charlestongi.com** |
| **Email status** | ✅ **verified** | ✅ **verified** |
| Title (Apollo) | Administrator, CEO | *(not returned)* |
| Title (web) | Chief Executive Officer | Chief Operating Officer |
| Seniority | `c_suite` | *(not returned)* |
| LinkedIn | linkedin.com/in/wanda-punteney-5a503a6 | *(not returned)* |
| Location | Charleston, South Carolina, US | Charleston, South Carolina, US |
| Apollo person id | 66f54fcc962ce60001a2a3f3 | 6a8e800333952b00141258ca |
| Committee persona | **economic_buyer** | **technical_evaluator** |
| Credits | 1 | 1 |

Both emails came back **verified**, which is the single highest-value thing Apollo did in this run:
two named executives, deliverable addresses, 2 credits, ~1.3 seconds. Thomas Punteney's record is
sparse (email only, no title or LinkedIn) — Apollo knows the address but not the person, which is
why the web research carrying his COO title matters.

---

## 5. Wanda W. Punteney — the contact deep research

One Exa `deep-reasoning` call, $0.029, 28.4 seconds, 10,182 characters returned.

### Identity — CONFIRMED, four independent anchors

> "Chief Executive Officer Member of Charleston GI since 1989" — https://charlestongi.com/doctors&staff/wanda-w-punteney/

> "Administrator, CEO at Charleston GI", located in "Charleston, South Carolina, United States" — https://www.linkedin.com/in/wanda-punteney-5a503a6

> "Wanda Punteney, CEO of Charleston GI" — https://www.postandcourier.com/journal-scene/news/officials-break-ground-on-windmill-station/…

> "Summerville Endoscopy Center, LLC by Wanda W Punteney, its CEO" — SC DPH CON filings

> "**Identity: CONFIRMED** — the employer bio, LinkedIn role/location, independent press coverage,
> and South Carolina regulatory records converge on the Charleston GI executive. Same-name
> individuals were not used."

Note the discipline: a second executive with the same surname (Thomas D. Punteney, COO) exists at the
same practice, and the prompt explicitly forbade merging their facts or speculating about any
relationship. The report kept them separate and did not speculate.

### Tenure — the standout hook

> "Member of Charleston GI since 1989."

**Approximately 37 years at one practice**, and she is its CEO. Career progression to the top of the
organisation she joined in 1989.

### Professional leadership

> "2005 Governor SCMGMA - Wanda Punteney" — https://www.southcarolinamgma.org/about/cog

(South Carolina Medical Group Management Association Council of Governors.)

### Her own words — the highest-value personalisation material

> "With the continued growth in Berkeley County, we recognize the need to be here and we're thrilled
> to find a home in Carnes Crossroads."
> — Post and Courier / Berkeley Independent, **30 April 2017**, on the Windmill Station groundbreaking

> "Exceptional experience in every way. Professional and customer focused. Attention to details;
> rapid response time; courteous and warm. Truly can say our total experience was beyond our
> expectations from your stellar team."
> — attributed to "Wanda Punteney, CEO, Charleston GI" — https://www.cypresseng.com/project/lowcountry-endoscopy-center/ (2023-03-07)

That second quote is unusually useful: it is her, on the record, describing what she values in a
vendor — responsiveness, attention to detail, warmth. That is a positioning brief written by the
buyer.

### Suggested openers (grounded only in the hooks above)

- *"Your nearly four decades with Charleston GI — 'Member of Charleston GI since 1989' — stand out as a substantial record of continuity and leadership."*
- *"I noticed your 2005 leadership service as Governor of the South Carolina Medical Group Management Association."*
- *"Your comments on Charleston GI's Carnes Crossroads expansion — 'we recognize the need to be here' — capture a clear connection between practice growth and regional access."*

### Honest gaps (the report's own list)

Education, degrees and graduation years — **NOT FOUND**. CMPE/FACMPE certification — **NOT FOUND**.
Pre-1989 career history — **NOT FOUND**. Title-change chronology — **NOT FOUND**. Conference talks,
podcasts, bylined articles — **NOT FOUND**. Awards — **NOT FOUND**. A dated anniversary
announcement — **NOT FOUND**. Each entry names the channels searched.

**Compliance behaviour:** the prompt hard-excluded health, faith, politics, family, marital status,
children, home address, DOB, race and sexual orientation. Nothing in those categories was recorded,
and the hooks section closes with *"Excluded by policy: health, faith, politics, family, and other
sensitive personal material."* Contrast with the hand-built dossiers, which recorded a contact's
father's Holocaust survival and the family's religious community under a "faith" heading — true,
publicly sourced, correctly attributed, and exactly what the use-gate exists to keep out of
outreach.

---

## 6. Claims summary

**126 claim rows.** Every row has a `source_url`; every row has a non-empty `evidence_span`.
Full data in `claims.json`; rejections in `claims_rejected.json`; schema check in
`schema_conformance_report.json`.

| Dimension | Breakdown |
|---|---|
| **By entity** | account:charleston-gi-specialists **104** · contact:wanda-punteney **13** · contact:thomas-punteney **9** |
| **By field status** | **registered 40** (32%) · **proposed 86** (68%) |
| **Distinct field keys** | **26 registered** · **65 proposed** |
| **By source_key** | `exa_search` 59 · `exa_research` 44 · `apollo` 23 |
| **By tier** | tier 4 (llm_synthesis) **103** · tier 1 (api) **23** |
| **Born status** | 100% `unverified`, 100% `tenant_private` |
| **Rejected at the write gate** | 2 — one duplicate, and one `contact.facet.career_history` row missing `identity_binding`/`use_class` |

**Registered keys used (26):** `core.account_name`, `core.primary_domain`, `core.company_about`,
`core.industry`, `core.employee_count` ×3, `core.hq_location` ×2, `core.company_linkedin_url`,
`core.company_phone` ×2, `core.annual_revenue`, `core.primary_tech_stack`, `core.work_email` ×2,
`account.operational_pain`, `account.strategic_moves`, `account.resonance.culture`,
`account.resonance.buying_culture`, `contact.current_title` ×3, `contact.job_function` ×2,
`contact.job_level` ×2, `contact.current_location` ×2, `contact.organization_relationship` ×2,
`contact.persona` ×2, `contact.role_on_committee` ×2, `contact.facet.career_history`,
`contact.facet.stated_interests`, `contact.facet.public_appearances` ×2, `contact.facet.causes`.

Note what is *absent*: `contact.facet.alma_mater` was never populated because the contact's
education is genuinely not public (the report says so explicitly), and `core.employee_range` was
skipped in favour of three conflicting exact `core.employee_count` values.

### Two write-gate findings worth acting on

**(a) 5 of the 40 registered-field claims would be refused by `check_claim_writable`** — all of them
value-shape errors, none of them fabrications:

| Field | Problem |
|---|---|
| `account.resonance.buying_culture` | declared `object{culture_label,summary}`, model emitted a bare string |
| `contact.organization_relationship` ×2 | `relationship="employed"` not in enum `["current_employee"]`; `basis="current_employment"` not in the declared enum |
| `contact.role_on_committee` ×2 | `confidence="high"` — declared a **number** 0..1 |

The cheap structuring model reads field *names* well and field *value schemas* badly. Production
`write_claims` must validate each value against `value_schema` and return an actionable per-item
refusal — which is what the schema-impact audit already specifies. This run is the empirical
justification for that requirement.

**(b) The model invents a field key per *instance* instead of per *fact type*.** It emitted
`account.staff_jeffrey_basile`, `account.staff_theodore_gourdin`, `account.staff_marc_noble` …
(16 of them), `account.form_hipaa_privacy_policy`, `account.form_financial_policy` … (9 of them),
and `account.office_address_carnes_crossroads` alongside `account.location_address`. That is why
"65 proposed keys" is misleading — the real number of *needed* fields is about 14 (§7).

**The fix is a tool-signature change, not a prompt change:** `write_claims` should expose the
registered field keys as a **closed enum**, with a separate `propose_field` side-channel for
genuinely new fields. A free-text `field_key` parameter invites exactly this behaviour.

**(c) A mis-mapping with a governance consequence.** Her SCMGMA governorship landed on
`contact.facet.causes`, whose registry `use_class_hint` is **`sensitive`** (it is the
religion/politics-adjacent field). A professional association board role is not a "cause" — but no
`board_roles` or `memberships` field is registered, so the model reached for the nearest thing and
put a benign professional fact into a field whose default hint would exclude it from outreach. The
per-claim `use_class` was set correctly to `professional-public`, so nothing broke; but this is a
concrete argument for registering `contact.facet.board_roles` and `contact.facet.memberships`.

---

## 7. PROPOSED FIELDS

Below is the **consolidated** set — what the platform should actually register, derived from the 65
keys the structuring pass invented (raw list in `proposed_fields.json`). Each carries the value
schema, the agent-facing description, the reuse scope, and the hypothesis for why the platform
needs it.

### Account fields

---

**`account.ownership_structure`** · `str` · account · `tenant_private`
```json
{"type":"string","enum":["independent_physician_owned","private_equity","mso_affiliated","hospital_owned","publicly_traded","unknown"]}
```
*Description (agent-facing):* Who ultimately controls the account — independent/physician-owned, PE-backed, MSO-affiliated, hospital-owned, public, or unknown. Set `unknown` when no acquisition evidence exists either way; absence of evidence is not evidence of independence.

*Hypothesis.* Independence is the #1 account priority in this ICP and it has no home in the registry today, so it currently lands in free-text `account.operational_pain` or nowhere. It needs its own key because it is a **gating** attribute, not a narrative one: the tiering pass must be able to filter on it deterministically, and the closed enum forces the agent to make the "PE or not" call explicitly rather than burying "no acquisition evidence found" in prose. The `unknown` member is load-bearing — this run's account said "PE/MSO affiliation: NOT FOUND, not a definitive negative", which is a materially different state from "confirmed independent" and must not collapse into it.

---

**`healthcare.ehr_vendor`** · `object` · account · `tenant_private`
```json
{"type":"object","required":["vendor"],"properties":{"vendor":{"type":"string"},"product":{"type":"string"},"go_live_year":{"type":"integer"},"relationship_current_as_of":{"type":"string"},"hosting":{"type":"string"}}}
```
*Description:* The account's electronic health record and practice-management vendor and product, when it went live, and the date through which the relationship is evidenced as current.

*Hypothesis.* EHR fit is the #2 account priority and the whole basis of the flagship product's technical feasibility, yet the registry has no EHR field at all — only `core.primary_tech_stack`, a flat `list[str]` that cannot express "gGastro/gPM, live since 2013, still current in August 2025". The structured shape matters because *currency* is the expensive part: a 2013 go-live and a 2025 case study are two different claims that together prove the relationship is live, and a flat string list loses that. This one field would have disqualified this account before any deep spend.

---

**`healthcare.ehr_disqualifier_flag`** · `object` · account · `tenant_private`
```json
{"type":"object","required":["verdict"],"properties":{"verdict":{"type":"string","enum":["disqualified","cleared","unresolved"]},"rule":{"type":"string"},"basis":{"type":"string"}}}
```
*Description:* The explicit verdict of the client's hard EHR disqualifier rule for this account: disqualified, cleared, or unresolved. `unresolved` means the qualifier could not be settled from public evidence and requires escalation — it never silently means "cleared".

*Hypothesis.* This is the field that turns research into a **decision**. Today a disqualifier verdict exists only as prose inside a synthesized claim, so nothing downstream can act on it: the tiering pass cannot gate on it, the run cannot terminate early on it, and the account list cannot be filtered by it. Making the verdict a first-class three-valued claim is what lets the platform stop spending on an account the moment it is disqualified — the single biggest cost lever this run identified (§8). The `unresolved` member is essential: this run's deep call returned exactly that state, and treating it as `cleared` would have been the expensive mistake.

---

**`account.owned_facilities`** · `list[object]` · account · `tenant_private`
```json
{"type":"array","items":{"type":"object","required":["name"],"properties":{"name":{"type":"string"},"facility_type":{"type":"string"},"address":{"type":"string"},"legal_entity":{"type":"string"},"accreditation":{"type":"string"},"procedure_rooms":{"type":"integer"},"npi":{"type":"string"},"ownership_basis":{"type":"string"}}}}
```
*Description:* Facilities the account owns or operates itself — endoscopy centres, ASCs, labs — each with the legal entity that holds it, accreditation/licensure, room count and the evidence basis for the ownership claim. Facilities where the account's clinicians merely hold privileges do not belong here.

*Hypothesis.* Owned procedure capacity is priority #3 and is the entire precondition for the Direct Access Colonoscopy product — there is no point pitching DAC to a group that does not own the rooms. Nothing in the registry represents a facility. The `legal_entity` and `ownership_basis` properties are the interesting ones: this run distinguished "operated by" (a construction-industry page) from proven ownership (SC CON filings naming *Charleston Endoscopy Center, LLC*), and that distinction is the difference between a claim you can put in a founders letter and one you cannot.

---

**`account.locations`** · `list[object]` · account · `tenant_private`
```json
{"type":"array","items":{"type":"object","required":["address"],"properties":{"name":{"type":"string"},"address":{"type":"string"},"phone":{"type":"string"},"fax":{"type":"string"},"role":{"type":"string"}}}}
```
*Description:* Every office/clinic site the account operates, with per-site phone and fax. `core.hq_location` holds only the primary site; this holds the rest.

*Hypothesis.* Multi-site footprint is both a fit signal (more sites ⇒ more referral volume a manual process cannot absorb) and a delivery requirement (a direct-mail or per-site campaign needs the addresses). `core.hq_location` is a single object and cannot express four offices. The per-site `fax` property is what makes this a research field rather than a logistics field — in this ICP the fax line *is* the product surface.

---

**`healthcare.referral_intake_mode`** · `object` · account · `tenant_private`
```json
{"type":"object","required":["mode"],"properties":{"mode":{"type":"string","enum":["fax","phone","paper_form","web_form","portal","integrated_electronic","mixed","unknown"]},"fax_numbers":{"type":"array","items":{"type":"object","required":["number"],"properties":{"number":{"type":"string"},"purpose":{"type":"string"},"source_url":{"type":"string"}}}},"referral_form_url":{"type":"string"},"open_access":{"type":"boolean"},"evidence_summary":{"type":"string"}}}
```
*Description:* How inbound referrals actually reach the account, every published fax number with its purpose, the referral form URL, and whether the account advertises open-access (no-referral-needed) scheduling.

*Hypothesis.* This is the flagship product's qualification field and it does not exist. Fax numbers were named as a critical in the research charter and they are genuinely load-bearing — they are simultaneously the evidence that intake is manual, the operational detail that proves the research was real, and, eventually, the integration target. Bundling them with `mode` and `open_access` in one object keeps the buying story coherent: this account is `fax` + `open_access: true`, which means unscreened inbound volume landing on a fax machine — the strongest possible version of the pitch.

---

**`healthcare.workload_staffing_signal`** · `list[object]` · account · `tenant_private`
```json
{"type":"array","items":{"type":"object","required":["function","evidence_kind"],"properties":{"function":{"type":"string","enum":["prior_authorization","referral_intake","recall","medical_records","scheduling","billing_revenue_cycle","front_office","other"]},"title_observed":{"type":"string"},"headcount":{"type":"integer"},"evidence_kind":{"type":"string","enum":["staff_directory","provider_roster","job_posting","org_chart_provider","press"]},"source_url":{"type":"string"}}}}
```
*Description:* Evidence that the account staffs a named operational function with dedicated people — derived from job titles in a contact provider, job postings, or a published staff directory. A dedicated title is direct evidence that the function is performed manually at a scale worth automating.

*Hypothesis.* **This is the highest-conviction proposal in this document.** Three ICP priority signals that public web research could not evidence — prior-auth workload, manual referral intake, and recall programme status — were all settled by a single 0-credit Apollo people search returning job titles. A "Prior Authorization Specialist" on the payroll is stronger proof of prior-auth burden than any FAQ sentence, and a "Recall Specialist" inverts the ICP's assumption in a useful direction: recall is not absent, it is *manual*, which is a warmer wedge than a greenfield. The platform currently has nowhere to put this, so the strongest available evidence for the product's core value proposition is being discarded. Note the field is deliberately about the *function*, not the person — it takes obfuscated provider records (which are not identity-resolved and must never become contact claims) and extracts the one thing they can legitimately support.

---

**`healthcare.procedure_volume`** · `list[object]` · account · `tenant_private`
```json
{"type":"array","items":{"type":"object","required":["metric","value","period"],"properties":{"metric":{"type":"string"},"value":{"type":"number"},"unit":{"type":"string"},"period":{"type":"string"},"basis":{"type":"string","enum":["published_by_account","third_party_report","estimate"]}}}}
```
*Description:* Published clinical throughput figures — annual procedures, colonoscopies, daily patient volume — each with its period and whether the account published it itself.

*Hypothesis.* Every ROI claim in this client's outreach is a volume multiplication, and this account publishes its own numbers on its referrals page: 16,365 procedures and 11,585 colonoscopies in 2020, up to 200 patients a day. Without this field those figures either vanish or get flattened into a prose blob that the content layer cannot compute against. Because the downstream content plane needs to *calculate* with them, they must be typed numbers with an explicit period, not sentences. `basis` matters because a self-published figure and a third-party estimate carry very different weight in a letter.

---

**`account.timing_signals`** · `list[object]` · account · `tenant_private`
```json
{"type":"array","items":{"type":"object","required":["date","signal_type","summary"],"properties":{"date":{"type":"string"},"signal_type":{"type":"string","enum":["facility_opening","regulatory_filing","ehr_change","leadership_change","expansion","merger_or_affiliation","hiring","award","anniversary","publication","other"]},"summary":{"type":"string"},"source_url":{"type":"string"}}}}
```
*Description:* Dated events indicating the account is in a buying window — new facilities, regulatory filings, EHR changes, leadership transitions, expansion, notable press. Undated observations do not belong here.

*Hypothesis.* Timing is priority #5 and there is no registered field for it, so dated events currently dissolve into `account.strategic_moves` free text where nothing can sort or expire them. Timing signals have a property no other research fact has — **they decay** — so they need a typed date to drive freshness, recency ranking and re-research cadence. This run found nine, including three SC Certificate-of-Need filings in eighteen months, which is exactly the sort of "they are actively building capacity right now" trigger that decides *when* to send rather than *whether*.

---

**`account.vendor_relationships`** · `list[object]` · account · `tenant_private`
```json
{"type":"array","items":{"type":"object","required":["vendor","category"],"properties":{"vendor":{"type":"string"},"product":{"type":"string"},"category":{"type":"string"},"evidence_kind":{"type":"string","enum":["vendor_case_study","vendor_press_release","technographic_detection","job_posting","account_website"]},"as_of":{"type":"string"},"source_url":{"type":"string"}}}}
```
*Description:* Named third-party vendors the account uses beyond the EHR — patient communication, dictation, bill-pay, portal — with how the relationship was evidenced and as of when.

*Hypothesis.* `core.primary_tech_stack` is a `list[str]` of detected technologies with no evidence kind and no date, which conflates "a crawler saw a script tag" with "the vendor published a case study naming this customer". That distinction decided this entire run: Apollo's technographic detection of **Klara** and ModMed's published Klara case study were the two independent legs that confirmed the disqualifier. Recording `evidence_kind` is what lets the corroborator treat them as two sources rather than one, and a vendor case study naming the account is close to tier-1 evidence about a competitor's footprint — far too strong to store as an undated string in a list.

---

**`account.headcount_trend`** · `object` · account · `tenant_private`
```json
{"type":"object","required":["window_months","change_ratio"],"properties":{"window_months":{"type":"integer"},"change_ratio":{"type":"number"},"as_of":{"type":"string"}}}
```
*Description:* Provider-reported headcount growth or contraction over a stated window, as a ratio.

*Hypothesis.* `account.hiring_velocity_eng` exists but is engineering-specific and a bare number — meaningless for a medical practice. Apollo returns 6/12/24-month headcount deltas for free on the org enrich we already pay for, and direction matters for qualification: this account is **−9.4% over twelve months** while filing for new capacity, a tension worth surfacing to a human rather than averaging away.

---

### Contact fields

---

**`contact.identity_confirmation`** · `object` · contact · `tenant_private`
```json
{"type":"object","required":["verdict","anchors"],"properties":{"verdict":{"type":"string","enum":["confirmed","same_name_only","unresolved"]},"anchors":{"type":"array","items":{"type":"object","required":["anchor_kind","source_url"],"properties":{"anchor_kind":{"type":"string","enum":["employer_page","linkedin","registry","press","provider_verified_email","directory"]},"quote":{"type":"string"},"source_url":{"type":"string"}}}}}}
```
*Description:* The explicit verdict on whether researched facts belong to *this* person, and the independent anchors supporting it. `same_name_only` means the evidence matches on name alone and must never drive outreach.

*Hypothesis.* `identity_binding` is a per-claim stamp with two values and no room for *why*, so today the reasoning behind a `strong` binding is unrecoverable — an auditor can see the verdict but not the evidence, and a DSAR or a "why did you write to me" complaint needs the evidence. Making the confirmation itself a claim with enumerated anchors gives the binding stamp a citable basis, and the three-valued verdict preserves the state this run actually hit repeatedly: sources that matched on name only and were correctly discarded. It also handles the specific hazard this account presented — two executives sharing a surname at one practice, whose facts must never merge.

---

**`contact.facet.board_roles`** · `list[object]` · contact · `tenant_private` · use_class hint `professional-public`
```json
{"type":"array","items":{"type":"object","required":["organization"],"properties":{"organization":{"type":"string"},"role":{"type":"string"},"year":{"type":"string"},"source_url":{"type":"string"}}}}
```
*Description:* Board, council, governor or committee service in professional and industry bodies. Professional-public: this is a career fact, not a personal affiliation.

*Hypothesis.* This run put a South Carolina MGMA governorship into `contact.facet.causes`, because `causes` is the closest registered field — and `causes` carries a **`sensitive`** use-class hint by design, since it is the religion/politics-adjacent field. A benign professional association role therefore landed one classification step away from being excluded from outreach entirely. Board service is among the best personalisation material available (it is public, professional, flattering and verifiable), and it needs a field whose default governance does not fight it.

---

**`contact.facet.tenure_milestone`** · `object` · contact · `tenant_private` · use_class hint `personal-public-non-sensitive`
```json
{"type":"object","required":["organization","start"],"properties":{"organization":{"type":"string"},"start":{"type":"string"},"years_as_of":{"type":"integer"},"as_of_date":{"type":"string"},"publicly_celebrated":{"type":"boolean"},"source_url":{"type":"string"}}}
```
*Description:* Length of service at an organisation, and whether the organisation itself publicly celebrated the milestone.

*Hypothesis.* Tenure is the most reliably available and most warmly receivable opener in this segment — "Member of Charleston GI since 1989" is a better first line than anything else this run found about anyone. `contact.facet.career_history` can store the start date but cannot express the *milestone*, and the derived year count must be recomputed against a date to stay honest (37 years is only true as of a stated date, which is exactly the kind of drift that makes a letter look automated when it ages). `publicly_celebrated` distinguishes a fact the person's employer chose to publicise — safe and flattering to reference — from one merely inferable from a bio.

---

**`contact.facet.openers`** · `list[object]` · contact · `tenant_private` · use_class hint `professional-public`
```json
{"type":"array","items":{"type":"object","required":["text","grounded_in_source_url"],"properties":{"text":{"type":"string"},"grounded_in_source_url":{"type":"string"},"hook_field_key":{"type":"string"}}}}
```
*Description:* Suggested opening lines for outreach, each carrying the source URL and the hook field it rests on. An opener with no grounding link is not storable.

*Hypothesis.* Openers are where fabrication is most tempting and most damaging — a warm, specific, invented first line is the failure mode that destroys trust fastest. Forcing every opener to carry `grounded_in_source_url` and a pointer to the hook claim it derives from makes an ungrounded opener structurally unstorable, and gives the content layer a ready-made, already-verified starting point instead of re-deriving personalisation from raw facts. It also makes the review surface trivially auditable: a human can click each opener straight through to the page it came from.

---

**Also recommended, from the schema-impact audit's own list and confirmed as needed by this run:**
`contact.facet.memberships`, `contact.facet.awards`, `account.research_audit` / `contact.research_audit`
(the link-audit annotation — the hand-built dossiers carry a "Fabrication audit result / links opened
/ items flagged" line per contact, and there is nowhere to store it).

---

## 8. Cost analysis

### 8.1 Every call, actual

| # | Provider | Call | Type | $ | secs | Credits |
|---|---|---|---|---|---|---|
| 1 | Exa | discovery query 1 | `/search` auto, 10 results | 0.00700 | 2.1 | — |
| 2 | Exa | discovery query 2 | `/search` auto, 10 results | 0.00700 | 1.5 | — |
| 3 | Apollo | org enrich | `GET /organizations/enrich` | 0 | 0.4 | **1** |
| 4 | Exa | account deep — **no outputSchema** | `deep-reasoning`, 25 | **0.03000** | 29.3 | — |
| 5 | Exa | account deep — flat schema | `deep-reasoning`, 25 | 0.02900 | 27.9 | — |
| 6 | Exa | gap-fill: 4 own-site pages | `/contents` | 0.00400 | 1.3 | — |
| 7 | Exa | gap-fill: EHR / portal | `/search` auto | 0.00700 | 1.0 | — |
| 8 | Exa | gap-fill: jobs / prior-auth | `/search` auto | 0.00700 | 1.0 | — |
| 9 | Exa | gap-fill: leadership | `/search` auto | 0.00700 | 1.9 | — |
| 10 | Exa | ModMed page fetch (livecrawl timeout on 1 of 4 URLs) | `/contents` | 0.00300 | 10.2 | — |
| 11 | Exa | ModMed page retry (cached) | `/contents` | 0.00100 | 0.1 | — |
| 12 | Exa | ModMed corroboration | `/search` auto | 0.00700 | 2.0 | — |
| 13 | Apollo | people search by org id | `POST /mixed_people/api_search` | 0 | 0.3 | **0** |
| 14 | Apollo | people search by domain | `POST /mixed_people/api_search` | 0 | 0.2 | **0** |
| 15 | Apollo | match — T. Punteney | `POST /people/match` | 0 | 1.0 | **1** |
| 16 | Apollo | match — W. Punteney | `POST /people/match` | 0 | 0.3 | **1** |
| 17 | Exa | contact deep | `deep-reasoning`, 25 | 0.02900 | 28.4 | — |
| 18 | OpenRouter | structuring r1 — GLM-4.7 (**returned empty**) | z-ai/glm-4.7 | 0.01502 | 207.7 | — |
| 19 | OpenRouter | structuring r1 — gpt-5-mini | openai/gpt-5-mini | 0.02570 | 129.5 | — |
| 20 | OpenRouter | structuring r2 — GLM-4.7, reasoning off | z-ai/glm-4.7 | 0.01910 | 335.4 | — |
| 21 | OpenRouter | structuring r2 — gpt-5-mini, reasoning low | openai/gpt-5-mini | 0.01261 | 64.6 | — |
| 22 | OpenRouter | structuring r3 — account chunk | z-ai/glm-4.7 | 0.02297 | 214.0 | — |
| 23 | OpenRouter | structuring r3 — contacts chunk | z-ai/glm-4.7 | 0.01245 | 13.8 | — |
| 24 | OpenRouter | structuring r3 — raw pages chunk | z-ai/glm-4.7 | 0.01508 | 110.3 | — |
| 25–27 | Exa | qualifier probes, 3 other candidates | `/search` auto ×3 | 0.02100 | 4.3 | — |
| | | **TOTAL AS RUN** | | **$0.2819** | ~19 min | **3** |

### 8.2 What one account actually costs

$0.1234 of the $0.2819 was **experiment**, not production: the failed no-schema deep call, three
superseded structuring rounds, and three qualifier probes on candidates I did not research.

| Configuration | Cost | Apollo credits |
|---|---|---|
| **As run, everything** | $0.2819 | 3 |
| **Production replay** (the winning path only, full discovery pass included) | **$0.1585** | 3 |
| **Per account, discovery amortised over 20 candidates** | **$0.1452** | 3 |
| — of which Exa deep research (2 calls) | $0.058 | |
| — of which Exa cheap search + page fetches (7 calls) | $0.050 | |
| — of which OpenRouter structuring (3 calls) | $0.050 | |
| — of which discovery, amortised | $0.0007 | |
| **Disqualified account, with the qualifier gate first (§8.5)** | **$0.0077** | **0** |

### 8.3 Extrapolation

At **$0.145/account and 3 Apollo credits**, researching every account to full depth:

| Accounts | Exa + OpenRouter | Apollo credits | Wall clock, sequential | With 10× concurrency |
|---|---|---|---|---|
| 10 | $1.45 | 30 | ~1.2 h | ~7 min |
| 100 | $14.52 | 300 | ~11.5 h | ~1.2 h |
| 1,000 | $145.20 | 3,000 | ~4.8 days | ~11.5 h |

Per-account wall clock in the production path is **414 s (6.9 min)** — and **338 s of it (5.6 min,
82%) is the structuring model**, not the research. All ten Exa calls together take 74 s; the two
deep calls take 56 s of that; all five Apollo calls take 2.2 s.

**So latency is a structuring problem, not a research problem.** gpt-5-mini did the same job in
65 s against GLM's 335 s. If throughput ever matters more than mapping precision, switching the
structuring model is a **5× wall-clock win** and a 34% cost win — which is the strongest argument
for fixing GLM's mapping gap with a closed field-key enum and then re-running the bake-off.

**Apollo credit arithmetic.** 3 credits per fully-researched account (1 org enrich + 2 people/match);
people search is free. Phone reveal would add **+8 credits per person** and needs a webhook receiver,
so at 2 contacts/account phones would take an account from 3 to 19 credits — a **6.3×** increase.
Do not enable phones by default.

| Credit pool | Accounts, email only (3/acct) | Accounts with phones (19/acct) |
|---|---|---|
| 1,000 | 333 | 52 |
| 5,000 | 1,666 | 263 |
| 10,000 | 3,333 | 526 |
| 25,000 | 8,333 | 1,315 |

### 8.4 Alternatives, measured where possible

| Option | Measured cost | Evidence | Verdict |
|---|---|---|---|
| **Exa `deep-reasoning`, 25 results** | **$0.029–0.030** / call, ~28 s | this run, 3 calls | What we used. 12.1k-char account report, 10.2k-char contact report, dense citations. |
| **Exa `deep-reasoning`, 20 results** | **$0.021** / call, ~11 s | prior run (`deep_A1`) | Cost tracks `numResults` at roughly **$0.0012/result**. numResults is the cost dial. |
| **Exa `deep`, 20 results** | **$0.014** / call, ~4 s | prior run (`deep_A3`) | **~33% cheaper and ~3× faster than `deep-reasoning` at equal breadth.** Untested at 25 results with the flat schema — **the single highest-value experiment still outstanding.** |
| **Exa `/search` auto, 10 results** | **$0.007** / call, ~1.5 s | this run, 8 calls | The workhorse. Found the disqualifier that the deep call missed. |
| **Exa `/contents` page fetch** | **$0.001 / page** | this run, 3 calls | **The best value in the entire run.** One $0.004 four-page fetch of the practice's own site produced the full provider roster, the three-ASC accreditation sentence, all four addresses, the fax number, the referral form inventory, and the 2020 procedure volumes. |
| **Build-your-own research loop** (3 searches + 15 page fetches + one synthesis call) | **≈$0.021 + $0.015 + $0.020 = $0.056** | composed from this run's measured unit costs | **~2× more expensive than the $0.029 Exa deep call**, and you own the retrieval quality, the citation discipline and the failure modes. Do not build this. |
| **OpenRouter `z-ai/glm-4.7`, reasoning OFF** | **$0.0191** for 10.3k in / 8.6k out | this run | **Recommended structuring model.** Best field-key mapping of the two. |
| **OpenRouter `openai/gpt-5-mini`, reasoning LOW** | **$0.0126** for 10.1k in / 5.0k out | this run | 34% cheaper, **5× faster** (65 s vs 335 s), but mapped fields worse — invented a non-key from a section heading and filed three fax numbers under `core.company_phone`. |
| **Parallel Task API** | **not tested** | — | No measurement taken; do not plan against a guessed price. Needs a like-for-like bake-off against the $0.029 deep call. |
| **Firecrawl** | **not tested** | — | It is a crawler, not a researcher; its role is the `/contents` leg, where Exa already costs $0.001/page. Only worth testing if it beats that or handles JS-rendered pages Exa's livecrawl times out on (which happened once here). |

**The GLM question, answered with numbers.** GLM-4.7 is the better structuring model *and* the more
dangerous one:

| | GLM-4.7 | gpt-5-mini |
|---|---|---|
| Round 1, reasoning left on | **$0.0150, returned EMPTY** — burned 6,120 of 6,240 completion tokens on reasoning and never emitted JSON | $0.0257, 28 claims |
| Round 2, reasoning off/low | $0.0191, **48 claims, 20 proposed fields** | $0.0126, 28 claims, 4 proposed fields |
| Field-key mapping quality | clean, coherent namespaces | invented `providers_staff_and_locations` from a section heading; put fax numbers in `core.company_phone` |
| Latency | **335 s** | **65 s** |

> **Set `reasoning: {enabled: false}` explicitly on GLM-4.7 for extraction work.** Left at default it
> silently spent a whole call's budget thinking and returned nothing — a 100% loss that a naive
> pipeline would have logged as a success with zero claims.

### 8.5 The recommendation: qualifier-first ordering

The most expensive thing this run did was **research an account it should have disqualified in the
first ten seconds**. The deep call ($0.029) reported the EHR as NOT FOUND; a $0.007 search then
settled it definitively. That ordering is backwards.

I tested whether a cheap search alone can adjudicate the qualifier, on three untouched candidates
from the same discovery pass ($0.021). **A naive keyword probe is not sufficient** — it returns
vendor marketing pages about *other* practices (Gastro Care Partners in Colorado, Woodholme in
Baltimore, Palmetto Gastro in SC). But the rule that actually worked on Charleston GI generalises:

> **Target-lock rule:** a qualifier is settled only when a page on a *known EHR-vendor domain*
> names the *target practice* in its URL or title.

Applied to all four candidates, with no additional spend:

| Candidate | Result |
|---|---|
| **Charleston GI Specialists** | ✅ **TARGET-LOCKED HIT** → `modmed.com/resources/gi/charleston-gi-improves-revenue-cycle-with-modmed-suite-of-products` → **DISQUALIFY** |
| Asheville Gastroenterology | no target-locked vendor page in 10 results → **UNRESOLVED, escalate** |
| Athens Gastroenterology Center | no target-locked vendor page in 10 results → **UNRESOLVED, escalate** |
| Gastroenterology Associates of Gainesville | no target-locked vendor page in 10 results → **UNRESOLVED, escalate** |

One true positive, zero false positives, and an honest `unresolved` state that escalates rather than
silently clearing. **Cheapest dossier-grade configuration:**

1. **Discovery** — 1 Exa `auto` search per ~10 candidates → **$0.0007/account**
2. **Qualifier probe** — 1 Exa `auto` search + the target-lock rule → **$0.007**
   → on a hit: write `healthcare.ehr_disqualifier_flag = disqualified` and **STOP. Total: $0.0077, 0 Apollo credits.**
3. Apollo org enrich → **1 credit**
4. **Own-site `/contents` fetch, 4–6 pages** → **$0.005** ← do this *before* the deep call; it is the
   best-value call in the run and it shrinks what the deep call has to discover
5. **One Exa deep call**, flat 9-section schema, `numResults: 20` → **$0.021** (or ~$0.014 if `deep`
   matches `deep-reasoning`'s quality — test this)
6. 3 cheap gap-fill searches for named criticals → **$0.021**
7. Apollo people search ×2 (0 credits) + `people/match` ×2 → **2 credits**
8. **One Exa deep contact call**, `numResults: 20` → **$0.021**
9. Structuring — GLM-4.7, **reasoning off**, 3 chunked calls, closed field-key enum → **$0.050**

**≈ $0.125/account (≈ $0.118 with `deep`), 3 Apollo credits, and ~$0.008 for every account the
qualifier kills.**

At a 40% disqualification rate — plausible in GI, where gGastro is the category-leading specialty
EHR — 100 accounts costs **$0.32 + $7.50 = $7.82** instead of $14.52, a **46% saving**, and the
saving grows with list quality getting worse, which is exactly when you need it.

---

## 9. Verdict against the dossier bar

| Dossier section (the bar) | This run | Verdict |
|---|---|---|
| Operating name, website, tier, ownership | Found, with the December 2025 independence article as fresh evidence | ✅ |
| Size — physicians + APPs | Found, **and caught the practice contradicting itself three times (10 / 11 / 12)** rather than picking one | ✅ better than the bar |
| Locations enumerated | All 4 offices with addresses | ✅ |
| Owned endoscopy centres | All 3, **with the legal entities proved from state CON filings** | ✅ better than the bar |
| EHR + explicit gGastro check | **gGastro/gPM since 2013, still current 2025 — DISQUALIFIED** | ✅ **the run's headline** |
| Referral intake with fax numbers | Referring-physician page, form inventory, 2 fax numbers, discrepancy flagged | ✅ |
| Prior-authorisation workload | Web: NOT FOUND. **Apollo: a dedicated Prior Authorization Specialist** | ✅ via a channel the dossier never used |
| Recall programme | **A dedicated Recall Specialist** — manual, not absent | ✅ better than the bar |
| Buying-intent / timing signals, dated | 9 dated signals incl. 3 Certificate-of-Need filings | ✅ |
| Decision makers with titles | CEO + COO confirmed, 20 more named | ✅ |
| Work emails | **2 verified emails, 2 credits** (the dossiers say "pending the ZoomInfo enrichment pass") | ✅ better than the bar |
| NPIs per physician | Organisational NPI only; no per-physician NPI lookup was run | ❌ needs the NPI registry resolver |
| Per-contact education / publications / awards | Sparse for this contact — genuinely not public | ⚠️ honest miss, correctly reported |
| Personalisation hooks + openers | 4 hooks, 3 grounded openers, sensitive categories excluded by policy | ✅ |
| ROI arithmetic inputs | **16,365 procedures / 11,585 colonoscopies / 200 patients a day**, self-published | ✅ better than the bar |

### Honest gaps and failures

1. **The brief's core premise was wrong, and it cost $0.03 to find out.** Exa `/search` returns an
   `output` object **only when the request carries an `outputSchema`**. With none, a
   `deep-reasoning` request returns just `results[]` — no report, no `output` key. There is no
   free-form-report mode on this endpoint. The workaround is faithful to the intent and works well:
   a **flat schema of 9–10 depth-1 string properties**, each a free-form markdown section. That is
   still one deep call carrying a whole dossier, structuring still happens afterwards in the cheap
   model, and it has the bonus that every named critical gets a guaranteed slot instead of being
   dropped from a free-running essay.
2. **The deep call missed the single most important fact.** It reported the EHR as NOT FOUND when a
   $0.007 search found three sources. Deep research is not a superset of cheap search — it optimises
   for synthesis breadth, and vendor case studies naming a customer are a *lookup*, not a synthesis.
   Both are needed; the cheap one should go first.
3. **The structuring bundle was incomplete and I did not notice until late.** Rounds 8b/8c were fed
   the deep reports plus a hand-written digest of the gap-fills — not the raw `/contents` page text.
   The richest artifact of the run went unstructured until a fourth pass ($0.015). *The structuring
   pass can only structure what is in its bundle* — in production every persisted snapshot must be
   in it by construction.
4. **65 proposed field keys is a tool-design defect, not 65 missing fields.** With a free-text
   `field_key` the model invents a key per instance (`account.staff_jeffrey_basile`). The real need
   is ~14 fields (§7). Fix: closed enum + a `propose_field` side-channel.
5. **5 of 40 registered-field claims would be refused for value-shape errors.** The model reads
   field names well and value schemas badly. `write_claims` must validate against `value_schema`.
6. **One `livecrawl` timeout** (504 `CRAWL_LIVECRAWL_TIMEOUT`) on `modmed.com`; the cached retry
   succeeded at $0.001. Always fall back to cache.
7. **The ModMed case-study page body was never retrievable** — both live and cached fetches returned
   only the title and publication date. The disqualifier verdict therefore rests on the *other* three
   sources (the ModMed blog, Becker's ASC, and the Klara guide), which is why the corroboration search
   was worth $0.007.
8. **No NPI registry lookups** were run — no per-physician NPI, no CMS taxonomy. The hand-built
   dossiers have these and they are cheap deterministic tier-1 anchors. The NPI resolver should be in
   the production path.
9. **No `account.scoring.fit` / `.intent` / `.tier` claims** were produced — this run stopped at
   research and did not score.
10. **Apollo people search missed both executives**, under both scopings. `people/match` by name +
    domain rescued them. Never rely on search alone for the committee.

### Bottom line

The machine works, at **$0.145 per account and 3 Apollo credits** — and can work at **$0.125** with
the ordering fix. It hit the dossier bar on most sections and beat it on several: owned-facility
ownership proved from state regulatory filings, self-published procedure volumes, verified work
emails, and an operational X-ray from job titles that the hand-built dossiers never had.

It also did the most valuable thing a research agent can do, which is to **stop**: it found, for
$0.007, that this account runs the one EHR the product cannot integrate with. The hand-built process
would have spent hours reaching that conclusion, and the version of this run that skipped the cheap
search would have produced a beautiful, fully-cited, completely unusable dossier.

---

### Artifacts

| File | Contents |
|---|---|
| `CLUE-SAMPLE-RUN.md` | this report |
| `claims.json` | all 126 stamped claim rows |
| `claims_rejected.json` | the 2 rows the write gate refused, with reasons |
| `proposed_fields.json` | the raw model-proposed field definitions |
| `schema_conformance_report.json` | the 5 value-schema violations |
| `account_report.json` / `contact_report.json` | the two deep-research reports |
| `committee_shortlist.json` / `matched_contacts.json` | Apollo committee data |
| `qualifier_probe.json` | the three qualifier probes |
| `cost_ledger.json` | every call with its actual cost, latency and credits |
| `structuring_comparison*.json` | the GLM vs gpt-5-mini measurements |
| `structuring_bundle.txt` | exactly what the structuring model was fed |
| `raw/` | every raw provider response, saved before parsing |
| `clue_lib.py`, `step*.py` | the scripts, in run order |
