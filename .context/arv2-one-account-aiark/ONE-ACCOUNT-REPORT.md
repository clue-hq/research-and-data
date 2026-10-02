# ONE ACCOUNT, END TO END — Zafran Security (zafran.io)

**Run:** `arv2-one-account-aiark` · **Date:** 2026-09-02 · **Account:** Zafran Security Ltd.
**Providers used:** AI Ark (all structured data) · Exa (search, page reads, one deep call) ·
Google Gemini (the media layer) · Ashby posting API (free) · OpenRouter gpt-5-mini (structuring only).
**Money:** **$0.1659 cash** and **11.6 AI Ark credits**, against ceilings of $3.00 and 25 credits.
**Everything below is measured.** Every number comes from a real API response saved in `raw/`
before it was parsed. Where something was not found, it says so.

---

## 0. Was Apollo used? No. Zero calls.

The founder's ruling was that AI Ark is the database and Apollo is not used. That held, and it is
checkable, not just asserted:

- `z_lib.py` — the only module in this run that can make an HTTP call — **has no Apollo helper at
  all.** There is no function that could have called it.
- The cost ledger (`cost_ledger.json`) contains 65 calls. The complete list of providers in it is
  `ai_ark, exa, gemini, live_http, openrouter`. There is no `apollo` row, and no request to
  `api.apollo.io`.
- The word "Apollo" appears in exactly three places in this folder: the Exa research prompt (where
  we *asked* whether Zafran uses Apollo as a vendor — the answer was NOT FOUND), a comment in
  `z_lib.py` saying no Apollo helper exists by design, and this report.

### The stack, in the order it actually ran

| # | Step | Provider | Calls | Cost | What it was for |
|---|---|---|---|---|---|
| 1 | Company lookup | AI Ark | 1 | 0.1 cr | The firmographic + funding + tech spine |
| 2 | People roster, domain-scoped | AI Ark | 1 | 6.0 cr | 12 of the 163 people AI Ark holds for zafran.io |
| 3 | People, name-scoped ×3 | AI Ark | 3 | 1.5 cr | Vari Kaur, Nick Fisher, Ben Seri — because the title filter is broken |
| 4 | Email export ×4 | AI Ark | 4 | 4.0 cr | The committee's work emails |
| 5 | Ashby posting API | free ATS | 2 | $0.00 | 27 live reqs **with full job descriptions** |
| 6 | Podcast RSS | free | 1 | $0.00 | The MP3 enclosure + exact duration for the media layer |
| 7 | Own-site reads | Exa `/contents` | 2 | $0.006 | zafran.io homepage, platform, about, funding release |
| 8 | Gap + media searches | Exa `/search` | 8 | $0.056 | Reputation, customers, competitors, media discovery |
| 9 | Deep research | Exa deep-reasoning | 1 | $0.025 | One call: product, funding, GTM, hiring, **negatives** |
| 10 | Media transcription | Gemini | 4 | $0.0348 | 1 podcast (42:49) + 2 YouTube videos (+1 discarded) |
| 11 | Media repair + quote mining | Gemini | 2 | $0.0199 | Re-ran the podcast on a proper ASR model after a quality failure |
| 12 | Embedding retrieval demo | Gemini embedding-2 | 32 | $0.0028 | 29 transcript chunks + 3 real questions |
| 13 | Structuring into claims | OpenRouter gpt-5-mini | 1 | $0.0214 | Prose → typed claims with verbatim spans |

Output: **174 claims** in `claims_zafran.json` (95 read straight out of a provider response,
21 from media, 54 synthesised from prose, 3 proposed new fields, 1 recorded exclusion).
No `birth_date` was written anywhere — it is dropped at parse time and scrubbed from `raw/`.

---

## 1. What exactly do we get back from AI Ark? The field inventory.

**Credits spent: 11.6 of the 25 allowed.** No 402 and no exhaustion — the only non-200 was
`GET /v1/credit`, which returned **401 with an empty body**, so there is no readable balance
endpoint on this key and credits here are counted by arithmetic (results returned × unit price).

#### A. `POST /v1/companies` — 0.1 credit per company returned (http 200, 1.99s, totalElements=1)

Request body: `{"account": {"domain": {"any": {"include": ["zafran.io"]}}}, "page": 0, "size": 3}`

Envelope fields: `content, empty, first, last, number, numberOfElements, pageable, size, sort, totalElements, totalPages` — the company object sits in `content[0]`.

| field | type | real value for Zafran |
|---|---|---|
| `id` | str | "4d204374-9b1e-69fe-6840-539eacb7a436" |
| `summary.name` | str | "Zafran Security" |
| `summary.legal_name` | str | "Zafran Security Ltd." |
| `summary.description` | str | "Zafran is an AI-native exposure management platform that eliminates the manual toil of vulnerability management by cutting through noise, revealing what is truly exploitable, and automating mitigation and remediation using the security controls teams already have.\n\nWe are a team of practitioners  |
| `summary.overview` | str | "Zafran Security is a cybersecurity startup specializing in vulnerability prioritization and threat exposure management, aiming to identify, remediate, and mitigate risks within organizations. The AI-native exposure management platform developed by the company aims to proactively avert the exploitat |
| `summary.founded_year` | int | 2022 |
| `summary.type` | str | "PRIVATELY_HELD" |
| `summary.industry` | str | "computer and network security" |
| `summary.staff.total` | int | 167 |
| `summary.staff.range.start` | int | 51 |
| `summary.staff.range.end` | int | 200 |
| `summary.logo.source` | str | "https://images.ai-ark.com/RpiIBozJWCMNQANKs8JmoEPrgxmC-k6InHogkK2sszk/exp:1790899199/rs:fill:80:80/plain/s3://ark-company/images/4d204374-9b1e-69fe-6840-539eacb7a436.jpg" |
| `link.website` | str | "https://www.zafran.io" |
| `link.domain` | str | "zafran.io" |
| `link.domain_ltd` | str | "zafran.io" |
| `link.linkedin` | str | "https://www.linkedin.com/company/zafran-security" |
| `link.twitter` | str | "https://x.com/Zafran_io" |
| `link.crunchbase` | str | "https://www.crunchbase.com/organization/zafran" |
| `contact.email` | str | "info@zafran.io" |
| `financial.revenue.annual.start` | int | 10000000 |
| `financial.revenue.annual.end` | int | 25000000 |
| `financial.revenue.annual.amount` | str | "10000000-25000000" |
| `financial.funding.type` | str | "SERIES_C" |
| `financial.funding.total_amount` | int | 130500000 |
| `financial.funding.last_amount` | int | 60000000 |
| `financial.funding.num_investor` | int | 9 |
| `financial.funding.num_funding_rounds` | int | 4 |
| `financial.funding.rounds` | list[4] | 4 items -> fields below |
| `financial.funding.rounds[0].announced_at` | str | "2025-12-02" |
| `financial.funding.rounds[0].raised_amount` | int | 60000000 |
| `financial.funding.rounds[0].type` | str | "SERIES_C" |
| `financial.funding.rounds[0].investors` | list[7] scalar | ["Vintage Investment Partners", "Cyberstarts", "Amex Ventures", "PSP Growth", "Knollwood Investment Advisory", "Sequoia Capital", "Menlo Ventures"] |
| `financial.funding.rounds[*]` | list values | ["SERIES_C", "SERIES_B", "VENTURE_ROUND", "SEED_ROUND"] |
| `financial.funding.date` | str | "2025-12-02" |
| `location.headquarter.continent` | str | "North America" |
| `location.headquarter.country` | str | "United States" |
| `location.headquarter.city` | str | "New York, New York" |
| `location.headquarter.raw_address` | str | "New York, New York, United States, North America" |
| `location.headquarter.position.lng` | float | -73.98556 |
| `location.headquarter.position.lat` | float | 40.748295 |
| `location.locations` | list[1] | 1 items -> fields below |
| `location.locations[0].continent` | str | "North America" |
| `location.locations[0].country` | str | "United States" |
| `location.locations[0].city` | str | "New York, New York" |
| `location.locations[0].raw_address` | str | "New York, New York, United States, North America" |
| `location.locations[0].position.lng` | float | -73.98556 |
| `location.locations[0].position.lat` | float | 40.748295 |
| `technologies` | list[10] | 10 items -> fields below |
| `technologies[0].name` | str | "dnssec" |
| `technologies[0].category` | str | "ns" |
| `technologies[*]` | list values | ["dnssec", "google cloud", "amazon s3", "envoy", "floc opt-out", "cloudflare automatic challenge", "cloudflare challenge", "hubspot hosted", "amazon oregon region", "zendesk mail"] |
| `industries` | list[6] scalar | ["risk management", "cyber security", "information technology", "network security", "software", "computer and network security"] |
| `languages` | list[1] scalar | ["english"] |
| `last_updated` | str | "2026-08-22" |


#### B. `POST /v1/people` — 0.5 credit per profile returned (http 200, 0.69s). Subject: Vari Kaur (representative full person object)

Request body: `{"contact": {"fullName": {"any": {"include": {"mode": "STRICT", "content": ["Vari Kaur", "Varinder Kaur"]}}}}, "account": {"domain": {"any": {"include": ["zafran.io"]}}}, "page": 0, "size": 3}`

> **Completeness note:** the live API also returns `profile.birth_date` on the person object. It
> was `null` for all four people we pulled, and per the run rule it is dropped at parse time and
> scrubbed from `raw/`, so it does not appear in the table below or anywhere else in this folder.

| field | type | real value for Zafran |
|---|---|---|
| `id` | str | "02321ba9-8571-0924-a589-abef8647c8fa" |
| `identifier` | str | "varinderkaur" |
| `profile.first_name` | str | "Vari" |
| `profile.middle_name` | null (EMPTY) | null |
| `profile.last_name` | str | "Kaur" |
| `profile.full_name` | str | "Vari Kaur" |
| `profile.headline` | str | "Demand Generation & ABM Expert \| B2B SaaS Marketing Leader \| GTM Strategist \| Pipeline Acceleration, and Revenue Growth" |
| `profile.title` | str | "Head of Growth Marketing" |
| `profile.picture.source` | str | "https://images.ai-ark.com/52YGyxVQ6xPIjz1h6JSN7-w5HVq0eiF3fDN4sXOtw8g/exp:1790899199/rs:fill:80:80/plain/s3://ark-person/images/02321ba9-8571-0924-a589-abef8647c8fa.jpg" |
| `profile.background.source` | str | "https://media.licdn.com/dms/image/v2/C5616AQGBuHa7E1riYg/profile-displaybackgroundimage-shrink_350_1400/profile-displaybackgroundimage-shrink_350_1400/0/1617220225944?e=1786579200&v=beta&t=zeqEtP2NtiMWz9PaHEb4EjTZz6nS5Ccj4ZuOeo0R1jc" |
| `profile.summary` | str | "Results-driven marketing leader with expertise in building and scaling demand generation, account-based marketing (ABM), and digital marketing programs for B2B SaaS companies across industries, including cybersecurity, healthcare, enterprise software, and AI. Strong track record in aligning marketi |
| `link.linkedin` | str | "https://www.linkedin.com/in/varinderkaur" |
| `link.twitter` | null (EMPTY) | null |
| `link.github` | null (EMPTY) | null |
| `link.facebook` | null (EMPTY) | null |
| `location.default` | str | "Easton, Pennsylvania, United States, North America" |
| `location.short` | str | "Easton, Pennsylvania" |
| `location.country` | str | "United States" |
| `location.state` | str | "Pennsylvania" |
| `location.city` | str | "Easton" |
| `location.position` | null (EMPTY) | null |
| `languages.primary_locale.country` | str | "US" |
| `languages.primary_locale.language` | str | "en" |
| `languages.supported_locales` | list[1] | 1 items -> fields below |
| `languages.supported_locales[0].country` | str | "US" |
| `languages.supported_locales[0].language` | str | "en" |
| `languages.profile_languages` | null (EMPTY) | null |
| `industry` | str | "Information Technology & Services" |
| `educations` | list[2] | 2 items -> fields below |
| `educations[0].school.id` | str | "6d97d024-dcdc-ad1c-4845-8971f3a526b0" |
| `educations[0].school.name` | str | "Punjab Technical University" |
| `educations[0].school.logo` | str | "https://images.ai-ark.com/wlvi3Nowb_Qn2jpQaOUoL_OwCH9r2nK52Ih8WyAgs1U/exp:1790899199/rs:fill:80:80/plain/s3://ark-company/images/6d97d024-dcdc-ad1c-4845-8971f3a526b0.jpg" |
| `educations[0].school.url` | str | "https://www.linkedin.com/school/punjab-technical-university" |
| `educations[0].degree_name` | str | "Master of Business Administration (M.B.A)" |
| `educations[0].field_of_study` | str | "Marketing" |
| `educations[0].grade` | null (EMPTY) | null |
| `educations[0].date.start` | str | "2008-01-01" |
| `educations[0].date.end` | str | "2010-12-31" |
| `educations[*]` | list values | ["Punjab Technical University", "Punjab Technical University"] |
| `awards` | list[2] | 2 items -> fields below |
| `awards[0].title` | str | "CMO Special Mention Award" |
| `awards[0].description` | null (EMPTY) | null |
| `awards[0].issuer` | null (EMPTY) | null |
| `awards[0].date` | null (EMPTY) | null |
| `awards[*]` | list values | ["CMO Special Mention Award", "Marketing Team Player Award"] |
| `certifications` | list[8] | 8 items -> fields below |
| `certifications[0].name` | str | "Fundamentals of Next-Gen Marketing" |
| `certifications[0].authority` | str | "6sense" |
| `certifications[0].url` | str | "https://verify.skilljar.com/c/arzgsjcfpzxh" |
| `certifications[0].license_number` | str | "arzgsjcfpzxh" |
| `certifications[0].display_source` | str | "skilljar.com" |
| `certifications[0].company.id` | str | "4826043c-0a62-5a5b-67a2-c483c5f4cddf" |
| `certifications[0].company.name` | str | "6sense" |
| `certifications[0].company.logo` | str | "https://images.ai-ark.com/r53FvoChTgqks7XWxwZhHHDsWsJ-A0Oae2iMZp0RcyY/exp:1790899199/rs:fill:80:80/plain/s3://ark-company/images/4826043c-0a62-5a5b-67a2-c483c5f4cddf.jpg" |
| `certifications[0].company.url` | str | "https://www.linkedin.com/company/6sense" |
| `certifications[0].date.start` | str | "2025-03-01" |
| `certifications[0].date.end` | null (EMPTY) | null |
| `certifications[*]` | list values | ["Fundamentals of Next-Gen Marketing", "Account-Based Go-to-Market (GTM) Certification", "Conversion Funnel Optimization", "ABM Advanced Certification", "Inbound Marketing", "Advanced Google Analytics", "Google Analytics Individual Qualification (GAIQ)", "Marketo Certified Expert (MCE)"] |
| `position_groups` | list[8] | 8 items -> fields below |
| `position_groups[0].company.id` | str | "4d204374-9b1e-69fe-6840-539eacb7a436" |
| `position_groups[0].company.name` | str | "Zafran Security" |
| `position_groups[0].company.logo` | str | "https://images.ai-ark.com/RpiIBozJWCMNQANKs8JmoEPrgxmC-k6InHogkK2sszk/exp:1790899199/rs:fill:80:80/plain/s3://ark-company/images/4d204374-9b1e-69fe-6840-539eacb7a436.jpg" |
| `position_groups[0].company.url` | str | "https://www.linkedin.com/company/zafran-security" |
| `position_groups[0].company.employees.start` | int | 51 |
| `position_groups[0].company.employees.end` | int | 200 |
| `position_groups[0].date.start` | str | "2025-05-01" |
| `position_groups[0].date.end` | null (EMPTY) | null |
| `position_groups[0].profile_positions` | list[1] | 1 items -> fields below |
| `position_groups[0].profile_positions[0].company` | str | "Zafran Security" |
| `position_groups[0].profile_positions[0].description` | null (EMPTY) | null |
| `position_groups[0].profile_positions[0].title` | str | "Head of Growth Marketing" |
| `position_groups[0].profile_positions[0].employment_type` | str | "Full-time" |
| `position_groups[0].profile_positions[0].location` | str | "New York, United States" |
| `position_groups[0].profile_positions[0].date.start` | str | "2025-05-01" |
| `position_groups[0].profile_positions[0].date.end` | null (EMPTY) | null |
| `position_groups[*]` | list values | [null, null, null, null, null, null, null, null] |
| `skills` | list[20] scalar | ["Website Conversion Optimization", "A/B Testing", "Website Optimization", "Web Conversion Optimization", "Demandbase", "Target Marketing", "Inbound Marketing", "Inbound Lead Generation", "HubSpot Marketing Hub", "HubSpot", "Go-to-Market Strategy", "Funnel Optimization", "Performance Marketing", "An |
| `member_badges.premium` | bool | false |
| `member_badges.creator` | bool | false |
| `member_badges.open_to_work` | bool | false |
| `member_badges.hiring` | bool | false |
| `member_badges.verified` | bool | true |
| `member_badges.influencer` | bool | false |
| `statistics.network.influencer` | bool | false |
| `statistics.network.followable` | null (EMPTY) | null |
| `statistics.network.followers_count` | int | 2478 |
| `statistics.network.connections_count` | int | 1899 |
| `statistics.experience.prev_job_titles` | null (EMPTY) | null |
| `statistics.experience.tenure.company` | str | "2025-05-01" |
| `statistics.experience.tenure.start` | str | "2006-01-01" |
| `statistics.experience.tenure.title` | str | "2025-05-01" |
| `department.departments` | list[1] scalar | ["marketing"] |
| `department.sub_departments` | list[1] scalar | ["growth_marketing"] |
| `department.functions` | list[1] scalar | ["marketing"] |
| `department.seniority` | str | "head" |
| `last_updated` | str | "2026-08-22" |

**Plus a whole embedded company object** (54 more fields, identical to the `/v1/companies` object except as noted below):

| field | type | real value for Zafran |
|---|---|---|
| `company.summary.legal_name` | str | "Zafran Security Ltd." |
| `company.summary.staff.total` | int | 167 |
| `company.financial.funding.total_amount` | int | 130500000 |
| `company.financial.funding.num_investor` | int | 9 |
| `company.financial.aberdeen.it_spend` | int | 7626866 |
| `company.last_updated` | str | "2026-08-22" |


#### C. `POST /v1/people/export/single` — 1 credit when an address is found (http 200, 0.83s). Subject: Vari Kaur

Request body: `{"url": "https://www.linkedin.com/in/varinderkaur"}`

the export returns the SAME person object as /v1/people plus one extra top-level block: `email`. Only the `email` block is inventoried here.

| field | type | real value for Zafran |
|---|---|---|
| `email.state` | str | "DONE" |
| `email.output` | list[1] | 1 items -> fields below |
| `email.output[0].address` | str | "vari@zafran.io" |
| `email.output[0].mx.record` | str | "aspmx.l.google.com" |
| `email.output[0].mx.google` | bool | false |
| `email.output[0].mx.found` | bool | true |
| `email.output[0].mx.provider` | str | "g-suite" |
| `email.output[0].domainType` | str | "SMTP" |
| `email.output[0].status` | str | "VALID" |
| `email.output[0].subStatus` | str | "EMPTY" |
| `email.output[0].date` | str | "2026-08-31T07:51:52.000461" |
| `email.output[0].free` | bool | false |
| `email.output[0].generic` | bool | false |
| `email.output[0].found` | bool | true |

#### D. `GET /v1/credit` — 401, empty body — no readable balance endpoint on this key; credits in this run are counted from returned-result arithmetic.


#### E. For contrast — the FREE Ashby posting API (0 credits, $0.00)

Board fields: `apiVersion, jobs`. Per-job fields: `address, applyUrl, compensation, department, descriptionHtml, descriptionPlain, employmentType, id, isListed, isRemote, jobUrl, location, publishedAt, secondaryLocations, shouldDisplayCompensationOnJobPostings, team, title, workplaceType`. Jobs returned: **27**.

### Which AI Ark fields were actually valuable, and which were empty

**Genuinely valuable (would change an outreach email):**

| Field | Why it earns its credit |
|---|---|
| `summary.legal_name` = "Zafran Security Ltd." | The Aug-31 deep-research run marked legal name NOT FOUND. One 0.1-credit call answered it. |
| `financial.funding.rounds[]` | Four rounds with **exact dates, amounts and named investors** — including a **$40M Series B on 2024-09-08** that the previous deep-research run never found at all. |
| `financial.revenue.annual` = $10M–$25M | A revenue band with a provider label on it, not a guess. Consistent with the third-party "~$20M ARR" claim. |
| `summary.staff.total` = 167 | An exact number rather than a band. **Flag a conflict, do not smooth it:** the 2026-08-31 run recorded a LinkedIn-derived 141 for the same company, and AI Ark's row is stamped `last_updated: 2026-08-22` — i.e. *older* than the 141. Two providers disagree by 26 people; neither is confirmed by Zafran. |
| `technologies[]` | `hubspot hosted`, `zendesk mail`, `google cloud`, `envoy`, `cloudflare` — real marketing/support stack evidence. |
| `certifications[]` (person) | **The single best field in the whole API.** Vari Kaur holds a 6sense certification (Mar 2025), two Demandbase certifications (Feb 2025 and Feb 2021), a Marketo Certified Expert and a HubSpot Academy cert. |
| `awards[]` (person) | "CMO Special Mention Award", "Marketing Team Player Award" for Vari; "1st place - Columbia Venture Capital Investment Competition" for Nick. |
| `department` (person) | `departments` / `sub_departments` / `functions` / `seniority` — machine-usable persona routing (`marketing / growth_marketing / head`). |
| `position_groups[]` (person) | Full career history with start/end dates per company **and per title**, so tenure is computable. |
| `statistics.network` | Followers/connections — a real proxy for who has reach (Nick 6,808 followers vs Sanaz 3,655). |
| `member_badges` | `premium`, `creator`, `open_to_work`, `hiring`, `verified`, `influencer`. Nick and Sanaz are both flagged `creator`; nobody was `open_to_work` or `hiring`. |
| `email.output[0]` | Address + SMTP status + sub-status + MX record + provider + free/generic flags. Not just a string. |
| `company.financial.aberdeen.it_spend` = $7,626,866 | **Only present in the person-embedded company object, not in `/v1/companies`.** |

**Empty or near-useless for this account:**

| Field | What came back |
|---|---|
| `profile.middle_name`, `link.twitter/github/facebook` (person) | `null` for every person we pulled |
| `location.position` (person) | `null` — no lat/long on people, only on the company |
| `languages.profile_languages` | `null` |
| `statistics.experience.prev_job_titles` | `null` — despite 8 position groups being present two fields away |
| `educations[].grade` | `null` |
| `awards[].description / issuer / date` | `null` — you get the award title and nothing else |
| `certifications[].url / license_number` | Present for the 6sense and Demandbase certs, `null` for five of the eight |
| `educations`, `certifications`, `awards`, `skills` for **Ben Seri** | All four empty arrays. AI Ark is only as rich as the person's own LinkedIn. |
| SIC / NAICS codes | **Not returned at all.** The brief expected them; `/v1/companies` has `industry` + `industries[]` and no numeric codes. |
| `GET /v1/credit` | 401, empty body |
| `contact.title` filter | Broken (carried finding). A title-filtered search ignores the filter and bills you for whoever it returns. |

**Two operational findings worth pinning:**

1. **The name filter works even though the title filter does not.** `contact.fullName` with
   `mode: STRICT` plus a domain scope returned exactly 1 correct person, three times out of three,
   for 0.5 credit each. That makes a targeted committee pull **12× cheaper** than the 6-credit
   domain roster.
2. **Email verification is served from cache but still billed.** Vari's and Nick's email blocks
   came back stamped `2026-08-31T07:51`, i.e. the verification performed during a run two days
   earlier; Sanaz's and Tom's were stamped `2026-09-02T07:18`, verified live. All four cost
   1 credit. Re-asking for an address you already have is not free.

---

## 2. Database vs research — what AI Ark alone gives you, and what only Exa/Gemini give you

| What AI Ark gave us on its own (11.6 credits, $0.00 cash) | What AI Ark could not give, and only research could |
|---|---|
| Legal name, founded year, exact headcount (167), HQ city + coordinates | That the ABM req has been **open 77 days** (free Ashby) |
| Four funding rounds with dates, amounts, 9 named investors, $130.5M total | That the **Cisco acquisition story was refuted** and Cisco invested instead (Exa deep) |
| Revenue band $10–25M, Aberdeen IT spend $7.63M | The third-party **"~$20M ARR, high burn"** claim and who said it (Exa deep) |
| Website/mail technologies (HubSpot-hosted, Zendesk mail, Google Cloud) | The **actual SDR tool stack** — Salesforce, Sales Navigator, ZoomInfo, Outreach (free Ashby) |
| The 163-person employee footprint and a 12-person sample | That **BDRs sit inside the Marketing department** and work NYC 3 days/week (free Ashby) |
| Every committee member's title, department, seniority, tenure, career history | **Named customers**: Kraft Heinz, Chipotle, Netskope, with their CISOs by name (own site, $0.001) |
| Vari Kaur's 6sense and Demandbase certifications | That co-founder/CPO **Snir Havdala left for NVIDIA** (Exa deep) |
| Four verified work emails with SMTP status and MX provider | **Their own voice** — what Sanaz actually says about changing customer habits (Gemini) |
| LinkedIn follower/connection counts and creator/premium badges | That Nick Fisher is the creator of the **Cocktail Chemistry** YouTube channel and a published author (Exa + Gemini) |

**The blunt version:** AI Ark is an excellent *spine* — identity, money, org shape, contactability —
and it is the cheapest way to get those. It knows almost nothing about **timing, intent, reputation
or voice**, which is precisely the material that makes an outreach email land. And the free Ashby
API beat the $0.025 deep-research call on the one question the deep call cared most about
(what tools do they use), because a job description is a primary source and a search index is not.

---

## 3. The Gemini media layer — run for real

Three media items were processed and one was thrown away. **48.6 minutes kept**, against a
2.5-hour ceiling.

| Item | Person | Length | Modality | Media tokens | Tokens/sec | Cost | Latency | $/hour of media |
|---|---|---|---|---|---|---|---|---|
| Boardroom Club, "AI Summit: Sanaz Yashar" (MP3 via RSS) | Sanaz Yashar | 42:49 | audio | 64,243 | **25.0** | $0.024451 | 44.1s | $0.0343 |
| "Advanced Techniques – How To Make A Moscow Mule" | Nick Fisher | 04:14 | YouTube video | 23,109 | **91.0** | $0.002991 | 9.4s | $0.0424 |
| "Supporting Cocktail Chemistry" | Nick Fisher | 01:31 | YouTube video | 8,199 | **90.1** | $0.001191 | 23.2s | $0.0471 |
| "The Truth About Why I Was a Faceless Cocktail Channel" | **DISCARDED** | 09:00 | YouTube video | 49,244 | 91.2 | $0.006188 | 14.1s | — |

**Measured, not assumed:** an MP3 costs **25 audio tokens per second**; a YouTube URL costs
**~91 tokens per second**, because Gemini bills the *video* modality (frames + audio), not just the
audio. A YouTube link is therefore roughly **3.6× the price** of the same minutes as an audio file.

**The discarded item is the honest part.** A search for Nick Fisher's cocktail channel returned a
2026 video called "The Truth About Why I Was a Faceless Cocktail Channel". Transcribing it cost
$0.006188 and proved it is a *different, British* cocktail YouTuber — the narrator is "in leafy old
England out in the sticks" and is unmasking himself in 2026, whereas Nick Fisher is the American
who created Cocktail Chemistry in 2014. No claim was built from it. It is recorded in
`claims_zafran.json` as an explicit exclusion with its cost.

### The identity chain for Nick Fisher (three independent links)

1. His own LinkedIn post: *"If we've worked together you may have discovered my little side hobby
   as a cocktail YouTuber"*, announcing the book *Cocktail Chemistry*.
2. Simon & Schuster's author page for Nick Fisher: *"In 2014, he created the YouTube channel
   Cocktail Chemistry to showcase these techniques, and it quickly rose to one of the most-watched
   cocktail channels."*
3. The Gemini transcript of a Cocktail Chemistry video, where the narrator identifies himself:
   *"Hey everyone it's Nick just checking in."*

### A real quality failure, found and repaired

The 42:49 podcast was first transcribed in one shot with `gemini-3.5-flash-lite`. It produced 329
timestamped lines — but **only 120 were unique**. From `[12:41]` onwards it **looped**, re-emitting
earlier dialogue under new timestamps. Roughly 12½ minutes of a 43-minute episode were genuinely
transcribed.

The same uploaded file was re-run on **`gemini-3.5-transcribe`**, the dedicated model. It returned
the **complete episode** — 6,926 words, 162 words/minute, ending on the real sign-off — with **no
looping**, for **$0.019284** (cheaper than the flash-lite attempt). Two wire facts:

- `gemini-3.5-transcribe` returns its text at `candidates[0].content.parts[0].audioTranscription.text`,
  **not** `parts[].text`. A normal parser reads it as an empty response.
- It gives **no timestamps and no speaker labels**. Flash-lite gives both but degrades on long files.

**The rule we applied:** every quote flash-lite produced was re-checked against the faithful ASR
before being kept. Four of its five quotes fell inside the honest window and all five were found in
the ASR (one exact, four matching after filler-word cleanup). Then the half of the episode
flash-lite never actually transcribed was mined separately, and every quote from it was verified in
code as an exact substring of the ASR.

### Best timestamped quotes

**Sanaz Yashar** — *Boardroom Club, "AI Summit"*, published 2025-08-10
([source](https://podcasters.spotify.com/pod/show/boardroomclub/episodes/AI-Summit-Sanaz-Yashar--Co-Founder-and-CEO-at-Zafran-Security-e36d9ai)):

> **[09:19]** "Today, it's like kind of simple, you do scan, right? And then you say, okay, have
> like, I'm not kidding, like when I say 30 million vulnerabilities, these are the real numbers we
> are seeing."

> **[05:14]** "And the biggest pain of cybersecurity when you come from the offensive war to the
> defensive war, the biggest pain is we don't have enough operators to operate all the different
> vulnerabilities."

And from the second half, verified verbatim against the ASR (no timestamp — the ASR model does not
emit them):

> "I think it's very important to understand that no matter which technology you're bringing to the
> world, at the end you have to deal with **habits**." … "I do think this has been definitely the
> biggest challenge, understanding how you can also change habits with a very good technology but
> also make them believe that they can do it different."

> "Passion, obsession. There would be if you pick the problem you're going to solve that you believe
> that it's a problem, not because you told, you believe it and you're obsessed about solving it."

**Nick Fisher** — *"Supporting Cocktail Chemistry"*
([source](https://www.youtube.com/watch?v=8_YWBtq4eic)):

> **[00:05]** "It is a a side hobby for me and uh one that is quite expensive and time consuming."

> **[00:30]** "I basically film on my iPhone in my kitchen at home. Um but I invest a lot in top
> quality liquors that I love and want to recommend to you guys, um as well as equipment that I
> use, uh whether it's a smoking gun or immersion circulator for cool infusions and and high
> quality glassware."

> **[00:44]** "…spend a lot of time doing things uh like ice experiments…"

That is a marketing VP describing, in his own voice, that he will spend his own money and time to
get a detail right. It is the most usable personal hook in the entire run.

### The embedding retrieval demo (`gemini-embedding-2`, 768 dimensions)

29 transcript chunks embedded as `RETRIEVAL_DOCUMENT` — **13,894 tokens, $0.002779, 11.1 seconds**.
Three questions embedded as `RETRIEVAL_QUERY` — 50 tokens, $0.00001. Total **$0.002789**.

| Question | Top hit | Score |
|---|---|---|
| "What does Sanaz say about how she buys, evaluates or chooses security tools and vendors?" | Sanaz **[06:26–08:27]** — the Mandiant incident-response passage | 0.751 |
| "What is Nick most proud of, and what does he invest his own time and money in?" | Nick **[00:00–01:26]** — the "side hobby… I invest a lot in top quality liquors" passage | **0.701** |
| "What frustrates Sanaz most about how vulnerability management works today?" | Sanaz **[08:29–09:52]** — *"the surgery was successful, the patient died"* | 0.789 |

The index holds both people, and each question pulled the right person's chunk at rank 1 without
being told whose transcript to look in. Retrieval on transcript **text** is essentially free.

**For the record:** embedding the **raw audio** of the same 2,914 seconds at $0.00016/sec would
have cost **$0.4662** — **167× more** than the $0.002789 the text embeddings cost, for the same
three answers. Transcribe first, embed the text. Never embed the audio.

---

## 4. What is actually fruitful for outreach — the ranked top 15

Ranked by how much each one would change what you write in a first email. "Cost" is the marginal
cost of the call that produced it.

| # | The fact | Source | Cost | Why it moves outreach |
|---|---|---|---|---|
| 1 | **Vari Kaur is 6sense- and Demandbase-certified** — "Fundamentals of Next-Gen Marketing" (6sense, Mar 2025), "Account-Based Go-to-Market Certification" (Demandbase, Feb 2025), "ABM Advanced Certification" (Demandbase, Feb 2021), Marketo Certified Expert | AI Ark `certifications[]` | 0.5 cr | She is the buyer, she already knows what an ABM platform is, and she chose to certify on two of them. You do not need to explain the category — you need to explain why you are different from the two she trained on. Both deep-research runs marked 6sense/Demandbase **NOT FOUND**. |
| 2 | **The actual SDR stack: "Utilize tools such as Salesforce, LinkedIn Sales Navigator, ZoomInfo & Outreach"** | Ashby BDR req (2026-08-19) | **$0.00** | This is the incumbent stack you are displacing or plugging into. It is a primary source — their own job ad — and it was NOT FOUND by the $0.025 deep-research call. |
| 3 | **The ABM req has been open 77 days** (published 2026-06-17, still listed 2026-09-02) and says "Own ABM from the ground up: 1:1 programs… 1:few cluster plays… scaled 1:many motions", reporting to the Head of Growth Marketing | Ashby posting API | **$0.00** | They have been trying to hire the person who would do this work for 11 weeks and have not. That is the opening line: the work is not getting done. |
| 4 | **Four verified work emails**: `vari@`, `nick@`, `sanaz@`, `tom@zafran.io` — all SMTP `VALID`, sub-status `EMPTY`, Google Workspace MX, not free, not generic | AI Ark export | 4.0 cr | Deliverability is settled and the pattern is `firstname@zafran.io`, which generalises to the rest of the org for free. |
| 5 | **Named customers with named CISOs on their own homepage**: Ricardo Lafosse (CISO, Kraft Heinz), Dave Estlick (CISO, Chipotle), James Robinson (CISO, Netskope) | zafran.io homepage via Exa `/contents` | $0.001 | Proof-point ammunition and, more usefully, the exact shape of account they win. Both deep-research runs said named customers NOT FOUND. |
| 6 | **"You have to deal with habits"** — Sanaz's own framing that the hardest part is changing customer behaviour, not the technology | Gemini media | $0.0244 (whole episode) | The CEO has publicly named change-management as her biggest challenge. An ABM pitch framed as "how you change a buying committee's habits" speaks her language back to her. |
| 7 | **Director of Alliances req published 2026-09-01** — "Our partner ecosystem is becoming one of the fastest ways security teams discover and adopt Zafran… build that engine from scratch" | Ashby posting API | **$0.00** | Published yesterday. A brand-new GTM motion with no owner yet is the freshest timing signal available. |
| 8 | **Exact funding ladder**: seed $5.5M and a $25M venture round both on 2024-03-28, **$40M Series B on 2024-09-08**, $60M Series C on 2025-12-02, $130.5M total, 9 investors | AI Ark `financial.funding.rounds[]` | 0.1 cr | The Series B was entirely missing from the previous research run. Getting the ladder right is the difference between sounding informed and sounding scraped. |
| 9 | **The Cisco story is refuted** — Calcalist reported acquisition talks "at a steep discount"; Globes then reported "Cisco investing in, not acquiring", and Zafran's own release confirms a strategic *investment* | Exa deep-reasoning | $0.025 | **`outreach_safe: false`.** You must never mention it. Its value is defensive: it stops a rep repeating a rumour the CEO publicly denied. |
| 10 | **Nick Fisher runs the Cocktail Chemistry YouTube channel and wrote the book** — in his own voice: "It is a side hobby for me and one that is quite expensive and time consuming" | Exa `/contents` + Gemini | ~$0.004 | The most human hook in the run, and it is safe: he published it about himself, repeatedly. |
| 11 | **BDRs sit in the Marketing department** (Ashby `department: Marketing`) and work "approximately 3 days a week at our NYC office" | Ashby posting API | **$0.00** | Tells you where pipeline responsibility actually lives — Vari's org owns the top of funnel, not Sales. That changes who your champion is. |
| 12 | **Their own marketing stack**: `hubspot hosted` pages, `zendesk mail` MX, plus "Proficiency in Salesforce, HubSpot and major ABM platforms" in the ABM req | AI Ark `technologies[]` + Ashby | 0.1 cr + $0.00 | HubSpot is the system of record for campaigns; "major ABM platforms" is deliberately unnamed, which is consistent with them not having bought one yet. |
| 13 | **Zafran uses Gong** — Nick Fisher's own article: "combing through dozens of Gong calls with vuln management teams" — and names the tools their buyers own: CrowdStrike, Akamai, Rapid7, Palo Alto Networks | Nick's LinkedIn article via Exa | $0.001 | A first-person tooling admission the deep call marked NOT FOUND, plus the exact competitor landscape their buyers live in. |
| 14 | **Third-party doubt**: Calcalist reported "roughly $20 million" ARR without the acceleration investors expected, plus an unnamed executive on "cash burn remains high"; and co-founder/CPO Snir Havdala left for NVIDIA | Exa deep-reasoning | (same $0.025) | **`outreach_safe: false`.** Never say it. But it explains the 27 open reqs and the urgency, and it tells you the CEO is under pressure to show pipeline — which is what ABM is for. |
| 15 | **Aberdeen IT spend $7,626,866** and revenue band $10–25M | AI Ark (person-embedded company object) | 0.5 cr | A budget-scale anchor. Notable that it appears **only** inside the person object, never in `/v1/companies`. |

Runners-up that did not make 15 but are in `claims_zafran.json`: Vari's "CMO Special Mention Award";
Nick's "1st place – Columbia Venture Capital Investment Competition" and Vassar College undergrad;
Tom Anthony joining Nov 2024 from Okta/Fortinet and sitting in San Francisco while the company is
NY/Tel Aviv; Ben Seri coming from Armis; and the fact that **nobody** on the committee carries the
`open_to_work` or `hiring` LinkedIn badge.

---

## 5. The buying committee, with emails

All five identities were carried in from the earlier person-depth work and **re-confirmed** by AI
Ark's current-employer field in this run — nobody was admitted on name alone.

| Person | Title (AI Ark) | Persona | Email | Status | Verified at | Dept / seniority | At Zafran since | Reach |
|---|---|---|---|---|---|---|---|---|
| **Vari Kaur** (Varinder Kaur) | Head of Growth Marketing | champion | `vari@zafran.io` | **VALID / SMTP / EMPTY** → verified | 2026-08-31 (cached) | marketing / growth_marketing / head | 2025-05 | 2,478 followers |
| **Nick Fisher** | VP of Marketing | economic buyer | `nick@zafran.io` | **VALID / SMTP / EMPTY** → verified | 2026-08-31 (cached) | marketing / product_marketing / vp | 2024-04 | 6,808 followers, `creator` + `premium` |
| **Sanaz Yashar** | Co-Founder & CEO | executive sponsor | `sanaz@zafran.io` | **VALID / SMTP / EMPTY** → verified | 2026-09-02 (live) | information_technology / cybersecurity / founder | 2022-11 | 3,655 followers, `creator` |
| **Tom Anthony** | SVP, Global Sales | adjacent buyer | `tom@zafran.io` | **VALID / SMTP / EMPTY** → verified | 2026-09-02 (live) | sales / enterprise_sales / vp | 2024-11 | 6,514 followers |
| **Ben Seri** | Co-Founder & CTO | technical evaluator | not requested | — | — | information_technology / cybersecurity_operations / founder | 2022-11 | 3,517 followers |

MX for all four is `aspmx.l.google.com` (`g-suite`); none is flagged `free` or `generic`.
**4 of 4 requested emails found → 4.0 credits.** Two were served from a cache created two days
earlier and still charged full price.

**Committee read:** marketing owns this. Vari is the champion (she is hiring the ABM seat, she is
certified on the competing platforms, and she is 4 months into a Head-of-Growth-Marketing role with
an unfilled req underneath her). Nick is the economic buyer and the one with public reach. Sanaz is
the sponsor whose public language is about changing habits and being under-resourced for
operations. Tom Anthony matters because BDRs report into Marketing, not to him — so a
marketing-led ABM motion does not need his sign-off, only his cooperation.

---

## 6. What it cost

### 6a. This run, by provider — every figure from the ledger

| Provider | Calls | Cash | AI Ark credits | Time in-call | Non-200 |
|---|---|---|---|---|---|
| AI Ark | 10 | $0.00 | **11.6** | 13.1s | 1 (`GET /v1/credit` → 401) |
| Exa | 11 | **$0.0870** | — | 51.6s | 0 |
| Gemini | 39 | **$0.0575** | — | 137.9s | 0 |
| OpenRouter (gpt-5-mini) | 1 | **$0.0214** | — | 81.8s | 0 |
| Free HTTP (Ashby, RSS, MP3) | 4 | $0.00 | — | 2.0s | 1 (wrong Ashby slug → 404) |
| **Total** | **65** | **$0.1659** | **11.6** | 286.4s | 2 |

Against the ceilings: **5.5% of the $3.00 cash**, **46% of the 25 AI Ark credits**, and **38%** of the
2.5-hour media budget (57.6 minutes of media processed, including the discarded item).

### 6b. Full recipe, per account

| Line item | Unit | Quantity | Credits | Cash |
|---|---|---|---|---|
| AI Ark company search | 0.1 cr/result | 1 company | 0.1 | $0.00 |
| AI Ark people, domain-scoped roster | 0.5 cr/profile | 12 profiles | 6.0 | $0.00 |
| AI Ark people, name-scoped committee | 0.5 cr/profile | 3 × 1 hit | 1.5 | $0.00 |
| AI Ark email export | 1 cr when found | 4 of 4 found | 4.0 | $0.00 |
| Ashby posting API (27 reqs + full JDs) | free | 1 GET | 0 | $0.00 |
| Podcast RSS (MP3 + duration) | free | 1 GET | 0 | $0.00 |
| Exa `/contents`, own site | ~$0.001/page | 4 pages | 0 | $0.004 |
| Exa `/contents`, identity binding | ~$0.001/page | 2 returned | 0 | $0.002 |
| Exa `/search` | $0.007/search | 8 searches | 0 | $0.056 |
| Exa deep-reasoning | $0.025/call | 1 call | 0 | $0.025 |
| Gemini transcription, 42:49 podcast | measured | 1 | 0 | $0.0245 |
| Gemini transcription, 2 short YouTube items | measured | 2 (5:45) | 0 | $0.0042 |
| Gemini embedding-2 index + 3 queries | $0.20/1M | 29 chunks | 0 | $0.0028 |
| gpt-5-mini structuring | measured | 1 | 0 | $0.0214 |
| *Waste:* wrong-person video | measured | 1 | 0 | $0.0062 |
| *Repair:* re-transcription on `gemini-3.5-transcribe` | measured | 1 | 0 | $0.0193 |
| *Repair:* second-half quote mining | measured | 1 | 0 | $0.0006 |
| **FULL RECIPE** | | | **11.6 cr** | **$0.1659** |

### 6c. Trimmed recipe, per account — what I would actually run at scale

Cuts the 6-credit domain roster (ten of its twelve profiles were sales, account-management,
technical-account-management or finance seats — only Sanaz Yashar and Tom Anthony were on the
committee),
drops two of the four emails, drops the YouTube item, and makes the dedicated ASR model primary.

| Line item | Credits | Cash | Why keep / cut |
|---|---|---|---|
| AI Ark company search | 0.1 | $0.00 | Highest yield per credit in the entire run |
| AI Ark name-scoped lookups × 4 committee members | 2.0 | $0.00 | 12× cheaper than the roster and 100% on-target |
| AI Ark email export × 2 (champion + economic buyer) | 2.0 | $0.00 | The CEO's and SVP's emails are nice-to-have, not send targets |
| Ashby posting API | 0 | $0.00 | Free, and it out-performed the paid deep call |
| Exa `/contents`, 3 own-site pages | 0 | $0.003 | The homepage carries the named-customer testimonials |
| Exa deep-reasoning, 1 call | 0 | $0.025 | The only source of the reputation/negatives layer |
| Gemini media, 1 short item for the primary target | 0 | $0.0030 | One item per person is enough for voice |
| Gemini ASR on any long item (`gemini-3.5-transcribe`) | 0 | $0.0193 | Cheaper **and** faithful; only use flash-lite where timestamps matter |
| gpt-5-mini structuring | 0 | $0.0214 | Required |
| **TRIMMED RECIPE** | **4.1 cr** | **$0.0717** |

### 6d. What that means at different AI Ark prices

| AI Ark credit price | Full recipe / account | Trimmed recipe / account | Trimmed × 1,000 accounts |
|---|---|---|---|
| Free tier (today) | $0.166 | **$0.072** | $72 |
| $0.02 / credit | $0.398 | **$0.154** | $154 |
| $0.05 / credit | $0.746 | **$0.277** | $277 |

### 6e. Per-person media cost

| Person | Items | Media seconds | Transcription | Repair | All-in |
|---|---|---|---|---|---|
| Sanaz Yashar | 1 (42:49 audio) | 2,569 | $0.024451 | $0.019284 | **$0.043735** |
| Nick Fisher | 2 (5:45 video) | 345 | $0.004182 | — | **$0.004182** |
| *(discarded, wrong person)* | 1 (9:00 video) | 540 | $0.006188 | — | $0.006188 |
| Embedding index for all of it | 29 chunks | — | $0.002789 | — | $0.002789 |

**Blended: $0.0354 per hour of media kept.** A one-item-per-person media layer for a 4-person
committee is roughly **$0.01–0.05 per account** — the media layer is not the expensive part of
this recipe. The expensive parts are Exa search ($0.056 across 8 searches) and the structuring
call ($0.021).

---

## 7. Honest gaps, and what surprised me

### Still not found

- **Exact ARR.** The only number is Calcalist's third-party "roughly $20 million", which Zafran has
  never confirmed. AI Ark's $10–25M band is consistent with it but is a provider estimate.
- **The Cisco and Amex cheque sizes.** Both undisclosed. Calcalist called Amex "several million".
- **Which ABM platform they actually use.** The req says "major ABM platforms" and names none, and
  none of the 27 job descriptions mentions 6sense, Demandbase, Terminus, RollWorks, Mutiny, Folloze,
  Influ2, Madison Logic, Clay or Common Room. The honest read is that they have not bought one.
- **SIC/NAICS codes** — AI Ark does not return them.
- **Street address, pricing, ACV, and the rest of the marketing team below Vari.** The only two
  marketing people we can name are Nick and Vari.
- **Ben Seri's profile is nearly empty** in AI Ark — no education, certifications, awards or skills.
- **Timestamps for the second half of the podcast.** The dedicated ASR model does not emit them, so
  the six verified second-half quotes carry a "second half" marker rather than an `MM:SS`.

### What surprised me

1. **The free ATS API beat the paid deep-research call at its own job.** The $0.025 deep-reasoning
   call marked Salesforce, ZoomInfo, Outreach, Sales Navigator and Gong all NOT FOUND. A free GET
   against `api.ashbyhq.com` returned 27 reqs **with complete job descriptions**, and one of them
   lists the SDR stack by name. Primary sources beat search indexes. The only reason the first
   attempt failed is that the board slug is `zafran-security`, not `zafran`.
2. **The name filter works while the title filter is broken.** A name-scoped, domain-scoped people
   search returned exactly the right person for 0.5 credit, three times out of three. The 6-credit
   domain roster returned ten sales/CS/finance seats and only two people on the committee.
   **The roster is a trap** —
   name-scoped committee pulls are 12× cheaper and strictly better.
3. **`certifications[]` is the best field in AI Ark and nobody would think to ask for it.** Knowing
   that the champion holds a 6sense certification and two Demandbase certifications tells you more
   about how she will evaluate you than her title, her company's funding, or anything the deep
   research produced.
4. **YouTube is 3.6× more expensive than audio, per minute**, because Gemini bills video tokens
   (~91/sec) rather than audio tokens (~25/sec). Pull the MP3 when one exists.
5. **A long one-shot transcription silently degrades.** `gemini-3.5-flash-lite` looped after 12½
   minutes of a 43-minute episode and kept emitting confident, well-formatted, *fabricated*
   timestamps. It would have passed any eyeball check. The dedicated `gemini-3.5-transcribe` model
   did the whole thing faithfully **for less money** — but returns its text under a different key
   and with no timestamps. Long media needs a two-model recipe and a duplicate-line check, always.
6. **The company object hidden inside the person object is richer than the company endpoint** — it
   carries `financial.aberdeen.it_spend`, which `/v1/companies` does not return at all.
7. **Email verification is cached but still billed.** Two of the four addresses came back stamped
   with a verification timestamp from a run two days earlier, at full price.
8. **Media search will confidently hand you the wrong person.** "Cocktail Chemistry" plus "faceless
   channel" returned a British YouTuber with the same subject matter. Only transcribing it settled
   it — a $0.006 mistake, and the reason the identity chain in section 3 has three links instead of
   one.

---

## Files in this run

| File | What it is |
|---|---|
| `ONE-ACCOUNT-REPORT.md` | This report |
| `claims_zafran.json` | 174 typed claims with provenance, cost, use-class and outreach-safety |
| `cost_ledger.json` | Every one of the 65 calls with http status, latency, cost and credits |
| `timing.json` | Per-phase wall clock |
| `z9_tables.json` | The cost tables above, machine-readable |
| `z10_ark_field_inventory.json` / `z11_inventory.md` | The AI Ark field inventory |
| `transcripts/` | `sanaz_boardroom.md` (timestamped, loops after 12:38), `sanaz_boardroom_transcribe_model.md` (faithful, no timestamps), `nick_supporting_cc.md`, `nick_moscow_mule.md`, `EXCLUDED_not_nick_faceless.md` |
| `report_account_zafran_deep.md` | The raw Exa deep-reasoning dossier |
| `raw/` | Every provider response, saved before parsing, birth-date scrubbed |
| `z1a`–`z11` scripts | Every step, re-runnable, python3 stdlib only |
