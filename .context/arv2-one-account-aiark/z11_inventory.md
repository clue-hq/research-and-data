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
