# AI Ark field inventory — Hotel Equities (every field, with its real value)


## `POST /v1/companies`

- **request**: `{"account": {"domain": {"any": {"include": ["hotelequities.com"]}}}, "page": 0, "size": 3}`
- **http**: `200`
- **elapsed_s**: `0.97`
- **credits_billed**: `0.1`
- **totalElements**: `1`
- **envelope_fields**: `["content", "empty", "first", "last", "number", "numberOfElements", "pageable", "size", "sort", "totalElements", "totalPages"]`

| field | type | real value for Hotel Equities |
|---|---|---|
| `id` | str | "8d12a1a5-5640-2ef8-d600-a45bf43f0d49" |
| `summary.name` | str | "Hotel Equities" |
| `summary.legal_name` | str | "Hotel Equities Group, LLC." |
| `summary.description` | str | "Hotel Equities (HE) is a best-in-class hospitality management company with a diverse portfolio of premium-branded and independent hotels, resorts, and outdoor hospitality destinations throughout the United States, Canada, the Caribbean, and Latin America (CALA). We deliver proven results and drive long-term value for stakeholders through… |
| `summary.overview` | str | "Hotel Equities (HE) is an award-winning hotel development, ownership and management company.  For 30 years, our team has collaborated with premier brands and entrepreneurial owners to deliver best in class results.  HE is hyper focused on managing upper midscale and full-service hotels in the U.S and Canada.  Whether we’re executing grou… |
| `summary.seo` | str | "Choose the management team at Hotel Equities when you want to expand your hotels company brand like never before." |
| `summary.founded_year` | int | 1989 |
| `summary.type` | str | "PRIVATELY_HELD" |
| `summary.industry` | str | "hospitality" |
| `summary.staff.total` | int | 990 |
| `summary.staff.range.start` | int | 10001 |
| `summary.logo.source` | str | "https://images.ai-ark.com/icRykKwDx88zNA4EIGDgrDf7yBnb7u9YGQtkkF8pxs4/exp:1790899199/rs:fill:80:80/plain/s3://ark-company/images/8d12a1a5-5640-2ef8-d600-a45bf43f0d49.jpg" |
| `link.website` | str | "http://www.hotelequities.com" |
| `link.domain` | str | "hotelequities.com" |
| `link.domain_ltd` | str | "hotelequities.com" |
| `link.linkedin` | str | "https://www.linkedin.com/company/hotel-equities" |
| `link.facebook` | str | "https://www.facebook.com/hotelequities" |
| `link.twitter` | str | "https://x.com/HotelEquities" |
| `link.crunchbase` | str | "https://www.crunchbase.com/organization/hotel-equities" |
| `contact.phone.raw` | str | "678.578.4444" |
| `contact.phone.sanitized` | str | "6785784444" |
| `financial.revenue.annual.start` | int | 50000000 |
| `financial.revenue.annual.end` | int | 100000000 |
| `financial.revenue.annual.amount` | str | "50000000-100000000" |
| `financial.funding.type` | str | "PRIVATE_EQUITY_ROUND" |
| `financial.funding.total_amount` | int | 500000000 |
| `financial.funding.last_amount` | int | 500000000 |
| `financial.funding.num_investor` | int | 1 |
| `financial.funding.num_funding_rounds` | int | 1 |
| `financial.funding.rounds` | list[1] | 1 items -> fields below |
| `financial.funding.rounds[0].announced_at` | str | "2018-09-12" |
| `financial.funding.rounds[0].raised_amount` | int | 500000000 |
| `financial.funding.rounds[0].type` | str | "PRIVATE_EQUITY_ROUND" |
| `financial.funding.rounds[0].investors` | list[1] scalar | ["Virtua Partners"] |
| `financial.funding.date` | str | "2018-09-12" |
| `location.headquarter.continent` | str | "North America" |
| `location.headquarter.country` | str | "United States" |
| `location.headquarter.state` | str | "Georgia" |
| `location.headquarter.city` | str | "Alpharetta" |
| `location.headquarter.street` | str | "North Point Pkwy" |
| `location.headquarter.raw_address` | str | "North Point Pkwy, Alpharetta, Georgia, United States, North America" |
| `location.headquarter.position.lng` | float | -84.38857 |
| `location.headquarter.position.lat` | float | 33.74975 |
| `location.locations` | list[1] | 1 items -> fields below |
| `location.locations[0].continent` | str | "North America" |
| `location.locations[0].country` | str | "United States" |
| `location.locations[0].state` | str | "Georgia" |
| `location.locations[0].city` | str | "Alpharetta" |
| `location.locations[0].street` | str | "North Point Pkwy" |
| `location.locations[0].raw_address` | str | "North Point Pkwy, Alpharetta, Georgia, United States, North America" |
| `location.locations[0].position.lng` | float | -84.38857 |
| `location.locations[0].position.lat` | float | 33.74975 |
| `technologies` | list[36] | 36 items -> fields below |
| `technologies[0].name` | str | "viewport meta" |
| `technologies[0].category` | str | "mobile" |
| `technologies[*]` | list values | ["viewport meta", "iphone / mobile compatible", "ssl by default", "hsts", "apple mobile web clips icon", "dnssec", "google tag manager", "google font api", "content delivery network", "google analytics", "html5", "symantec email security.cloud", "godaddy premium dns", "google fonts", "google tag manager", "bootstrap", "google cloud transl |
| `industries` | list[1] scalar | ["hospitality"] |
| `keywords` | list[14] scalar | ["rooms operations", "revenue generation", "finance & accounting", "food & beverage", "human resources", "procurement", "commercial strategy", "development services", "content storytelling", "brand development", "online reputation management", "talent acquistion & development", "tech innovation", "guest experience"] |
| `hashtags` | list[3] scalar | ["hotelmanagement", "hospitalitystrong", "hoteliers"] |
| `languages` | list[1] scalar | ["english"] |
| `sic` | list[1] scalar | ["7011"] |
| `naics` | list[2] scalar | ["721110", "561499"] |
| `last_updated` | str | "2026-09-21" |

**63 field rows, 0 empty/null.**

## `POST /v1/people (person object)`

- **request**: `{"contact": {"fullName": {"any": {"include": {"mode": "STRICT", "content": ["Ben Rafter", "Benjamin Rafter"]}}}}, "account": {"domain": {"any": {"include": ["hotelequities.com"]}}}, "page": 0, "size": 3}`
- **http**: `200`
- **elapsed_s**: `0.55`
- **credits_billed**: `0.5`
- **totalElements**: `1`
- **subject**: `"Ben Rafter (representative full person object)"`
- **envelope_fields**: `["content", "empty", "first", "last", "number", "numberOfElements", "pageable", "size", "sort", "totalElements", "totalPages", "trackId"]`

| field | type | real value for Hotel Equities |
|---|---|---|
| `id` | str | "f54c7f19-7467-a9d5-8f02-fb54beb96345" |
| `identifier` | str | "ben-rafter-623a702" |
| `profile.first_name` | str | "Ben" |
| `profile.middle_name` | null (EMPTY) | null |
| `profile.last_name` | str | "Rafter" |
| `profile.full_name` | str | "Ben Rafter" |
| `profile.headline` | str | "CEO at Hotel Equities" |
| `profile.title` | str | "CEO" |
| `profile.picture.source` | str | "https://images.ai-ark.com/xad2dL6AxN5wxpNybDCPlsGKNXH0XUPfS5kpj3SnaVA/exp:1790899199/rs:fill:80:80/plain/s3://ark-person/images/f54c7f19-7467-a9d5-8f02-fb54beb96345.jpg" |
| `profile.background.source` | str | "https://media.licdn.com/dms/image/v2/D5616AQHr8esx8MOX6g/profile-displaybackgroundimage-shrink_350_1400/B56Zo1WYr3HQAY-/0/1761831652474?e=1789603200&v=beta&t=tm2sMxCgvQKVlA7v005Ac2gUwZ5Kz60j9R6ZL7eiqRE" |
| `profile.summary` | str | "Would you put your cell phone in all the hotels rooms you managed? I did and 10,000,000 guests later it was the most worthwhile thing I've done in my career. I also co-founded a company acquired by Amazon, sold a company to Marriott Vacations and spent half my career developing new technologies. I'm currently Chief Executive Officer of H… |
| `link.linkedin` | str | "https://www.linkedin.com/in/ben-rafter-623a702" |
| `link.twitter` | null (EMPTY) | null |
| `link.github` | null (EMPTY) | null |
| `link.facebook` | str | "https://www.facebook.com/bgrafter" |
| `location.default` | str | "Honolulu, Hawaii, United States, North America" |
| `location.short` | str | "Honolulu, Hawaii" |
| `location.country` | str | "United States" |
| `location.state` | str | "Hawaii" |
| `location.city` | str | "Honolulu" |
| `location.position` | null (EMPTY) | null |
| `languages.primary_locale.country` | str | "US" |
| `languages.primary_locale.language` | str | "en" |
| `languages.supported_locales` | list[1] | 1 items -> fields below |
| `languages.supported_locales[0].country` | str | "US" |
| `languages.supported_locales[0].language` | str | "en" |
| `languages.profile_languages` | null (EMPTY) | null |
| `industry` | str | "Hospitality" |
| `educations` | list[1] | 1 items -> fields below |
| `educations[0].school.id` | str | "6816c47b-c1a1-c878-0fbf-f882fd20d6e4" |
| `educations[0].school.name` | str | "University of Washington" |
| `educations[0].school.logo` | str | "https://images.ai-ark.com/8XUFl7oH2Rh0MGG1dGOO53luzBRzP4WVA-I55ANZCLc/exp:1790899199/rs:fill:80:80/plain/s3://ark-company/images/6816c47b-c1a1-c878-0fbf-f882fd20d6e4.jpg" |
| `educations[0].school.url` | str | "https://www.linkedin.com/school/university-of-washington" |
| `educations[0].degree_name` | null (EMPTY) | null |
| `educations[0].field_of_study` | null (EMPTY) | null |
| `educations[0].grade` | null (EMPTY) | null |
| `educations[0].date` | null (EMPTY) | null |
| `position_groups` | list[9] | 9 items -> fields below |
| `position_groups[0].company.id` | str | "8d12a1a5-5640-2ef8-d600-a45bf43f0d49" |
| `position_groups[0].company.name` | str | "Hotel Equities" |
| `position_groups[0].company.logo` | str | "https://images.ai-ark.com/icRykKwDx88zNA4EIGDgrDf7yBnb7u9YGQtkkF8pxs4/exp:1790899199/rs:fill:80:80/plain/s3://ark-company/images/8d12a1a5-5640-2ef8-d600-a45bf43f0d49.jpg" |
| `position_groups[0].company.url` | str | "https://www.linkedin.com/company/hotel-equities" |
| `position_groups[0].company.employees.start` | int | 10001 |
| `position_groups[0].company.employees.end` | null (EMPTY) | null |
| `position_groups[0].date.start` | str | "2025-05-01" |
| `position_groups[0].date.end` | null (EMPTY) | null |
| `position_groups[0].profile_positions` | list[1] | 1 items -> fields below |
| `position_groups[0].profile_positions[0].company` | str | "Hotel Equities" |
| `position_groups[0].profile_positions[0].description` | str | "Hotel Equities, a leading hospitality management firm with a diverse portfolio of hotels, resorts, and outdoor destinations across the United States, Canada, the Caribbean, and Latin America." |
| `position_groups[0].profile_positions[0].title` | str | "CEO" |
| `position_groups[0].profile_positions[0].employment_type` | str | "Full-time" |
| `position_groups[0].profile_positions[0].location` | str | "Atlanta, GA" |
| `position_groups[0].profile_positions[0].date.start` | str | "2025-05-01" |
| `position_groups[0].profile_positions[0].date.end` | null (EMPTY) | null |
| `position_groups[*]` | list values | [null, null, null, null, null, null, null, null, null] |
| `skills` | list[20] scalar | ["Business Development", "E-commerce", "Hospitality", "Resorts", "Hospitality Industry", "Hotels", "Start-ups", "Leadership", "Leisure", "Tourism", "Program Management", "Management", "Strategy", "Analytics", "Marketing Strategy", "Product Marketing", "Sales", "Human Resources", "Committed to Customer Satisfaction", "Mergers & Acquisition |
| `member_badges.premium` | bool | false |
| `member_badges.creator` | bool | false |
| `member_badges.open_to_work` | bool | false |
| `member_badges.hiring` | bool | false |
| `member_badges.verified` | bool | true |
| `member_badges.influencer` | bool | false |
| `statistics.network.influencer` | bool | false |
| `statistics.network.followable` | null (EMPTY) | null |
| `statistics.network.followers_count` | int | 4458 |
| `statistics.network.connections_count` | int | 4078 |
| `statistics.experience.prev_job_titles` | null (EMPTY) | null |
| `statistics.experience.tenure.company` | str | "2025-05-01" |
| `statistics.experience.tenure.start` | str | "1996-12-02" |
| `statistics.experience.tenure.title` | str | "2018-07-01" |
| `company.id` | str | "8d12a1a5-5640-2ef8-d600-a45bf43f0d49" |
| `company.summary.name` | str | "Hotel Equities" |
| `company.summary.legal_name` | str | "Hotel Equities Group, LLC." |
| `company.summary.description` | str | "Hotel Equities (HE) is a best-in-class hospitality management company with a diverse portfolio of premium-branded and independent hotels, resorts, and outdoor hospitality destinations throughout the United States, Canada, the Caribbean, and Latin America (CALA). We deliver proven results and drive long-term value for stakeholders through… |
| `company.summary.overview` | str | "Hotel Equities (HE) is an award-winning hotel development, ownership and management company.  For 30 years, our team has collaborated with premier brands and entrepreneurial owners to deliver best in class results.  HE is hyper focused on managing upper midscale and full-service hotels in the U.S and Canada.  Whether we’re executing grou… |
| `company.summary.seo` | str | "Choose the management team at Hotel Equities when you want to expand your hotels company brand like never before." |
| `company.summary.founded_year` | int | 1989 |
| `company.summary.type` | str | "PRIVATELY_HELD" |
| `company.summary.industry` | str | "hospitality" |
| `company.summary.staff.total` | int | 990 |
| `company.summary.staff.range.start` | int | 10001 |
| `company.summary.logo.source` | str | "https://images.ai-ark.com/icRykKwDx88zNA4EIGDgrDf7yBnb7u9YGQtkkF8pxs4/exp:1790899199/rs:fill:80:80/plain/s3://ark-company/images/8d12a1a5-5640-2ef8-d600-a45bf43f0d49.jpg" |
| `company.link.website` | str | "http://www.hotelequities.com" |
| `company.link.domain` | str | "hotelequities.com" |
| `company.link.domain_ltd` | str | "hotelequities.com" |
| `company.link.linkedin` | str | "https://www.linkedin.com/company/hotel-equities" |
| `company.link.facebook` | str | "https://www.facebook.com/hotelequities" |
| `company.link.twitter` | str | "https://x.com/HotelEquities" |
| `company.link.crunchbase` | str | "https://www.crunchbase.com/organization/hotel-equities" |
| `company.financial.revenue.annual.start` | int | 50000000 |
| `company.financial.revenue.annual.end` | int | 100000000 |
| `company.financial.revenue.annual.amount` | str | "50000000-100000000" |
| `company.financial.funding.type` | str | "PRIVATE_EQUITY_ROUND" |
| `company.financial.funding.total_amount` | int | 500000000 |
| `company.financial.funding.last_amount` | int | 500000000 |
| `company.financial.funding.num_investor` | int | 1 |
| `company.financial.funding.num_funding_rounds` | int | 1 |
| `company.financial.funding.rounds` | list[1] | 1 items -> fields below |
| `company.financial.funding.rounds[0].announced_at` | str | "2018-09-12" |
| `company.financial.funding.rounds[0].raised_amount` | int | 500000000 |
| `company.financial.funding.rounds[0].type` | str | "PRIVATE_EQUITY_ROUND" |
| `company.financial.funding.rounds[0].investors` | list[1] scalar | ["Virtua Partners"] |
| `company.financial.funding.date` | str | "2018-09-12" |
| `company.financial.acquisition.total` | int | 1 |
| `company.financial.acquisition.contents` | list[1] | 1 items -> fields below |
| `company.financial.acquisition.contents[0].role` | str | "acquiree" |
| `company.financial.acquisition.contents[0].announced_at` | str | "2025-05-01" |
| `company.financial.aberdeen.it_spend` | int | 8712352 |
| `company.location.headquarter.continent` | str | "North America" |
| `company.location.headquarter.country` | str | "United States" |
| `company.location.headquarter.state` | str | "Georgia" |
| `company.location.headquarter.city` | str | "Alpharetta" |
| `company.location.headquarter.street` | str | "North Point Pkwy" |
| `company.location.headquarter.raw_address` | str | "North Point Pkwy, Alpharetta, Georgia, United States, North America" |
| `company.location.headquarter.position.lng` | float | -84.38857 |
| `company.location.headquarter.position.lat` | float | 33.74975 |
| `company.location.locations` | list[1] | 1 items -> fields below |
| `company.location.locations[0].continent` | str | "North America" |
| `company.location.locations[0].country` | str | "United States" |
| `company.location.locations[0].state` | str | "Georgia" |
| `company.location.locations[0].city` | str | "Alpharetta" |
| `company.location.locations[0].street` | str | "North Point Pkwy" |
| `company.location.locations[0].raw_address` | str | "North Point Pkwy, Alpharetta, Georgia, United States, North America" |
| `company.location.locations[0].position.lng` | float | -84.38857 |
| `company.location.locations[0].position.lat` | float | 33.74975 |
| `company.technologies` | list[36] | 36 items -> fields below |
| `company.technologies[0].name` | str | "viewport meta" |
| `company.technologies[0].category` | str | "mobile" |
| `company.technologies[*]` | list values | ["viewport meta", "iphone / mobile compatible", "ssl by default", "hsts", "apple mobile web clips icon", "dnssec", "google tag manager", "google font api", "content delivery network", "google analytics", "html5", "symantec email security.cloud", "godaddy premium dns", "google fonts", "google tag manager", "bootstrap", "google cloud transl |
| `company.industries` | list[1] scalar | ["hospitality"] |
| `company.keywords` | list[14] scalar | ["rooms operations", "revenue generation", "finance & accounting", "food & beverage", "human resources", "procurement", "commercial strategy", "development services", "content storytelling", "brand development", "online reputation management", "talent acquistion & development", "tech innovation", "guest experience"] |
| `company.hashtags` | list[3] scalar | ["hotelmanagement", "hospitalitystrong", "hoteliers"] |
| `company.languages` | list[1] scalar | ["english"] |
| `company.sic` | list[1] scalar | ["7011"] |
| `company.naics` | list[2] scalar | ["721110", "561499"] |
| `company.last_updated` | str | "2026-09-21" |
| `department.departments` | list[1] scalar | ["general_management"] |
| `department.sub_departments` | list[1] scalar | ["executive_leadership_and_general_management"] |
| `department.functions` | list[1] scalar | ["general_management"] |
| `department.seniority` | str | "c_suite" |
| `last_updated` | str | "2026-09-21" |

**141 field rows, 14 empty/null.**

## `POST /v1/people/export/single (email block)`

- **request**: `{"url": "https://www.linkedin.com/in/ben-rafter-623a702"}`
- **http**: `200`
- **elapsed_s**: `1.02`
- **credits_billed**: `1.0`
- **subject**: `"Ben Rafter"`
- **note**: `"the export returns the SAME person object as /v1/people plus one extra top-level block: `email`. Only the `email` block is inventoried here."`
- **envelope_fields**: `["company", "department", "educations", "email", "id", "identifier", "industry", "languages", "last_updated", "link", "location", "member_badges", "position_groups", "profile", "skills", "statistics"]`

| field | type | real value for Hotel Equities |
|---|---|---|
| `email.state` | str | "DONE" |
| `email.output` | list[1] | 1 items -> fields below |
| `email.output[0].address` | str | "ben.rafter@hotelequities.com" |
| `email.output[0].mx.record` | str | "hotelequities-com.mail.protection.outlook.com" |
| `email.output[0].mx.google` | bool | false |
| `email.output[0].mx.found` | bool | true |
| `email.output[0].mx.provider` | str | "microsoft" |
| `email.output[0].domainType` | str | "SMTP" |
| `email.output[0].status` | str | "VALID" |
| `email.output[0].subStatus` | str | "EMPTY" |
| `email.output[0].date` | str | "2026-09-22T05:26:58.000420" |
| `email.output[0].free` | bool | false |
| `email.output[0].generic` | bool | false |
| `email.output[0].found` | bool | true |

**14 field rows, 0 empty/null.**

## `GET /v1/credit`

- **http**: `401`
- **elapsed_s**: `0.95`
- **credits_billed**: `0.0`
- **result**: `"401, empty body — no readable balance endpoint on this key; credits in this run are counted from returned-result arithmetic (carried finding, identical to the Zafran run)."`

## `POST /v1/people/export/single — the 404`

- **request**: `{"url": "https://www.linkedin.com/in/albert-smith-3aa9318"}`
- **http**: `404`
- **elapsed_s**: `0.72`
- **credits_billed**: `0.0`
- **result**: `"HTTP 404 on the exact LinkedIn URL AI Ark itself returned from /v1/people for the same person. New wire finding: the export index and the people index disagree."`

## `GET workforcenow.adp.com job-requisitions (FREE, for contrast)`

- **credits_billed**: `0.0`
- **centres**: `{"9200396175623_2": {"label": "US management & sales", "total_reported": 32, "pulled": 33, "properties_listed": 557}, "9200402480447_2": {"label": "US hourly / property", "total_reported": 97, "pulled": 98, "properties_listed": 557}, "9200585439604_2": {"label": "Canada hourly", "total_reported": 8, "pulled": 8, "properties_listed": 557}, "9200585441819_2": {"label": "Canada management", "total_reported": 6, "pulled": 6, "properties_listed": 557}}`
- **reqs_returned**: `145`
- **bonus**: `"meta.links LOCATION enumerates 552 named properties — a free portfolio roster nobody would think to ask for"`
- **no_description_text**: `"The ADP public requisition object carries NO description field; the per-requisition detail endpoint returns the same object. Titles, locations, post dates and salary ranges are the whole payload — verified by probing /job-requisitions/<itemID> and <itemID>?$expand=all, both 200 with identical bodies."`

Per-requisition field names: `additionalProperties`, `clientRequisitionID`, `customFieldGroup`, `itemID`, `links`, `organizationalUnits`, `payGradeRange`, `postDate`, `postingInstructions`, `requisitionLocations`, `requisitionTitle`, `screeningRequirements`, `sponsoredVisaTypeCodes`, `workLevelCode`