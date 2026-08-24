# ARV2 — Melissa contract: what it can and cannot do for buying-committee addresses

**Status:** review document, 2026-08-23. Companions: `ARV2-apollo-api-contract.md`,
`ARV2-deep-agent-build-runbook.md`, `ARV2-schema-impact-audit.md`.

**Verification basis (important).** `developer.melissa.com` and `docs.melissa.com` **block our
fetcher**, so the doc pages (including the Contact Search page the founder linked, and every
result-code table) could not be read directly. Everything below is instead pinned from Melissa's
**official OpenAPI specifications** published in their own GitHub org —
`MelissaData/MelissaCloudAPI-OpenAPI-Specifications`, files `openapi/apis/{people-business-search,
global-address-verification,us-business-coder,personator-consumer,personator-search}.yaml` — which
are the machine-readable source of the portal's own reference pages, including the example
responses. Items that live only on the blocked pages (result-code semantics, credit pricing) are
marked **[BLOCKED-DOC]** and must be read from the founder's logged-in portal.

---

## 1. The founder's question, answered directly

> *Once Apollo has given us the buying committee, how much can Melissa find the address for that
> specific person?*

**For a business contact, Melissa cannot reliably give you "that person's office address," and its
person-level products would hand you their *home* address instead.** Three verified reasons:

1. **Contact Search has no person→employer→address join.** A returned record's `Consumer` block is
   `{FullName, FirstName, MiddleName, LastName, Suffix, OtherFullNames, MelissaIdentityKey}` —
   **no job title, no employer field, no email**. `CompanyName` is a *sibling* block describing the
   company associated with that record, not a filter proving this person works there. The documented
   input combinations are address-led, phone-led, or `(full | last | anyname | comp) + adminarea`
   (or `+ postal`) — i.e. company name is an **alternative** search key to a person name, not a
   qualifier that selects the person's work address.
2. **Contact Search returns no address *type*.** Its `Address` block carries no
   `DeliveryIndicator`, so nothing in the response says whether the address is a residence or a
   business. (Global Address Verification *does* carry it — see §3.)
3. **Its sibling, Personator Search, is explicitly a skip-tracing product.** Melissa's own spec
   describes it as searching "an individual's Current Address / Previous Address / Phone Numbers /
   Email Addresses / Individuals living at an address / Date of Birth and/or Date of Death." That is
   consumer identity data, not B2B contact data.

So the match you would get for "Gaye Pennington, GA" is a **name-plus-geography** hit with a
`MatchLevel` percentage (Melissa's own guidance: "anything less than 80% is questionable"),
pointing at a residential record. In our own vocabulary that is a **WEAK identity binding** — the
exact same-name failure mode the platform's identity model exists to refuse — and mailing a
physician executive at home is a separate product/appropriateness decision, not a data upgrade.

**What Melissa is genuinely excellent at, and what ARV2 should buy it for:** taking the *office*
address we already determined and turning it into a **verified, USPS-deliverable, suite-level,
ZIP+4 mailing address**, with a machine-checkable "safe to mail" signal and a stable address key.
That is the real gap — Apollo returns `street_address/city/state/postal_code` as *reference data*,
not CASS/DPV-verified mailing data, and `core.hq_location` in our claim store is city-level only.

**Division of labour:** Apollo/Exa decide *who* and *which site*; Melissa decides *is this address
real, complete, and deliverable*. Melissa is a verifier, not a locator.

---

## 2. Contact Search — the endpoint the founder linked (verified contract)

- **Server:** `https://search.melissadata.net/V5/WEB/contactsearch`
- **Operations:** `GET /docontactSearch` (`docontactSearchGET`) and `POST /docontactSearch`
  (`docontactSearchPOST`)
- **Auth:** `id` query parameter = the Melissa **License Key** (no header auth, no OAuth)
- **Required input — at least one documented set:**
  - **Set A:** `a1`, `loc`, `adminarea`, `postal` (address-led)
  - **Set B:** `phone`
  - **Set C:** (`full` | `last` | `anyname` | `comp`) + `adminarea`
  - **Set C′:** (`full` | `last` | `anyname` | `comp`) + `postal`
- **Other params:** `matchlevel` (0–100; "anything less than 80% is questionable"), `maxrecords`,
  `t` (transmission reference), `first`, `premnum`, `subpremnum`, `tname`, `predir`, `postdir`,
  `trailingtype`, `ctry`, `subuser`; headers `Accept` / `Content-Type`.
- **Response:** `{TransmissionReference, Version, ResultCode, TotalRecords, Results[]}` — `Results`
  holds **max 100** items, each:
  - `MatchLevel`, `RecordID`
  - `Address{Address1, DependentLocality, Locality, LocalityAlternates, AdministrativeArea,
    CountryCode, CountryName, Thoroughfare, ThoroughfarePreDirection, ThoroughfareName,
    ThoroughfareTrailingType, ThoroughfarePostDirection, Premises, PremiseType, PremiseNumber,
    SubPremises, SubPremiseType, SubPremiseNumber, PostalCode, PostalCodeSecondary,
    MelissaAddressKey, MelissaAddressKeyBase}`
  - `Consumer{FullName, FirstName, MiddleName, LastName, Suffix, OtherFullNames,
    MelissaIdentityKey}`
  - `CompanyName{CompanyName, OtherCompanyNames, MelissaEnterpriseKey}`
  - `Phone{Phone, OtherPhones}`
- **Absent by design:** job title, email, residential/business indicator, DPV/CASS codes.
- `ResultCode` example value `US01`; the code table is **[BLOCKED-DOC]**
  (`docs.melissa.com/cloud-api/people-business-search/result-codes.html`).
- **Verdict for ARV2: do not use.** It cannot answer our question, and it puts consumer identity
  data in the pipeline for no product gain. (It would be the right tool for a *consumer*-facing
  product, which we are not building.)

---

## 3. Global Address Verification — the product ARV2 should use

- **Server:** `https://address.melissadata.net/V3/WEB/GlobalAddress`;
  `GET|POST /doGlobalAddress`; auth `id` = License Key; **POST batch `maxItems: 100`** records.
- **Inputs:** `a1`–`a8` (address lines), `loc` (city, required), `admarea` (state, required),
  `postal` (required), `ctry`, **`org`** (organization name associated with the address),
  **`last`** (*US only* — "for addresses missing a secondary like a suite or apartment, we can use
  the last name and append that information **for residential addresses**"), `opt`, `format`, `t`.
- **Response `Records[]` fields (verbatim from the official example):** `RecordID`,
  **`Results`** (e.g. `"AC16,AV24,GS05"`), **`FormattedAddress`** (mail-ready, line-separated —
  `LineSeparator` option), `Organization`, `AddressLine1`–`AddressLine8`, **`SubPremises`**,
  `DoubleDependentLocality`, `DependentLocality`, `Locality`, `SubAdministrativeArea`,
  `AdministrativeArea`, **`PostalCode`** ("in U.S. plus 4 is not required but will be appended if
  address is verified"), `PostalCodeType`, `AddressType`, `AddressKey`, `SubNationalArea`,
  `CountryName`, `CountryISO3166_1_Alpha2/Alpha3/Numeric`, `CountrySubdivisionCode`,
  `Thoroughfare*` (7 parsed parts), `DependentThoroughfare*`, `Building`, `PremisesType`,
  `PremisesNumber`, `SubPremisesType`, `SubPremisesNumber`, `PostBox`, `Latitude`, `Longitude`,
  **`DeliveryIndicator`** — *"a one character code that indicates if the address is a residence
  (R), business (B), or unknown (U)"* — **`MelissaAddressKey`**, `MelissaAddressKeyBase`,
  `PostOfficeLocation`, `SubPremiseLevel*`, `SubBuilding*`, `UTC`, `DST`, `DeliveryPointSuffix`,
  `CensusKey`, `Extras`, and `Suggestions[]` (BETA, single-record only, via `Suggestion:ON`).
- **Useful `opt` values (verified):** `DeliveryLines:ON|OFF`, `LineSeparator:…`,
  `USStandardizationType:Auto|Short|Long`, `USPreferredCityNames:ON|OFF`, `USExtras:ON|OFF`,
  `OutputGeo`, `Suggestion:ON|OFF`, `DetailedResults:ON|OFF`, `AreaDetails`, `MelissaCityKeys`.
- **`Results` code semantics are [BLOCKED-DOC]**
  (`…/global-address-verification/result-codes.html`). What is verified: the field is a
  comma-delimited set of status/error/change codes, the example shows `AV24` (an address-verified
  level), `AC16` (an address-corrected code) and `GS05` (a geocode status). **Action for the
  founder:** read that table in the portal so we can pin the exact "safe to mail" AV set in code;
  until then the adapter records the raw code string and treats only an explicitly allow-listed AV
  set as mailable.

### Why this is the right tool for us
It confirms the address exists and is deliverable, appends **ZIP+4** and **suite**
(`SubPremises`/`SubPremisesNumber`), produces a **mail-ready `FormattedAddress`**, tells us via
**`DeliveryIndicator=B`** that we are mailing an office rather than a home, and hands back
**`MelissaAddressKey`** — a stable address identity we can key claims and dedupe mailings on.
Personator Consumer (`https://personator.melissadata.net/v3/WEB/ContactVerify`,
`/doContactVerify`, required `act` ∈ `Check|Verify|Move|Append`) is the CASS/DPV **consumer**
sibling that adds name-to-address verification and move update; ARV2 does not need it unless we
ever mail individuals at home.

---

## 4. US Business Coder — the useful second Melissa call

- **Server:** `https://businesscoder.melissadata.net/WEB/BusinessCoder`;
  `GET|POST /doBusinessCoderUS`; auth `id`.
- **Inputs (locators):** `comp` (company name), **`web` (domain — which Apollo already gives us)**,
  `phone`, `a1`, `a2`, `suite`, `city`, `state`, `postal`, `ctry`, `mak` (Melissa Address Key),
  `mek` (Melissa Enterprise Key), `stock`, `ff` (free form), `rec`, plus `cols` and `opt`.
- **`opt`:** `CentricHint:company|address|phone`, `MaxContacts:1|5|10`,
  `ReturnDominantBusiness:yes|no`, `SICNAICSConfidence:strict|loose`.
- **Default `cols`:** `AddressLine1, City, CompanyName, CurrentCompanyName, MelissaEnterpriseKey,
  PostalCode, RecordID, State, Suite, TotalContacts, TransmissionReference, TransmissionResults`.
  Individually requestable: `Contacts, EmployeesEstimate, LocationType, Phone, SalesEstimate,
  StockTicker, WebAddress`. Groups: `GrpAddressDetails` (`CountryCode, CountryName,
  DeliveryIndicator, MelissaAddressKey, MelissaAddressKeyBase, Plus4`), `GrpBusinessCodes`
  (`EIN, NAICSCode1-3, SICCode1-3`), `GrpBusinessDescription`, `GrpGeoCode`, `GrpCensus`.
- **High-value fields for us:** `Suite` + `Plus4` (the mailing precision Apollo lacks),
  `CurrentCompanyName` (*"the company name in our reference data — use this to easily compare your
  input company name against Melissa records for that address"* — a free identity cross-check),
  **`LocationType`** (`0` Headquarters, `1` Branches, `2` Subsidiary Headquarters, `3` Single
  Location — directly answers "is this site the HQ?", which the dossiers care about),
  `MelissaEnterpriseKey`, `EmployeesEstimate` / `SalesEstimate` / `SIC` / `NAICS` / `EIN` as
  independent cross-checks on Apollo's firmographics.
- **`Contacts[]` = `{NameFirst, NameLast, Gender, Title, ContactPhone, Email}`** (up to 10 via
  `MaxContacts`), with `TotalContacts` counting Melissa's employee contacts for the business.
  **ARV2 deliberately does not use this for committee discovery** — per the founder's instruction
  and because Apollo's title/seniority filtering is better — but it is available as an optional
  *cross-check* that a title we found is corroborated, and it is worth knowing it exists before
  anyone pays for a redundant capability.
- Example `Results`: `"AS01,DA20,DA30,DA40,DA50,FS01,FS04,GS05"`; code table **[BLOCKED-DOC]**.
- **`Gender` must never be written to the claim store** — inferred demographic data with no
  outreach use, and squarely the kind of field the use-class model exists to keep out.

---

## 5. The ARV2 address pipeline (what actually runs)

Per contact selected for direct mail:

1. **Which site?** Determined by research, not Melissa: the account's Apollo record
   (`street_address, city, state, postal_code`, `owned_by_organization_id`) plus the Exa site
   research that identifies where the person actually sits. (For Digestive Healthcare of Georgia,
   the dossier's own answer — "land directly with central administration at the Atlanta / Howell
   Mill HQ" — is a *research* conclusion.) A multi-site practice makes this a real decision; the
   agent must state which site it chose and why.
2. **Confirm the business at that site** — `doBusinessCoderUS` with `web` = the account domain
   (optionally `comp` + `city`/`state`), `cols` including `GrpAddressDetails, LocationType`.
   Take `Suite`, `Plus4`, `LocationType`, `MelissaEnterpriseKey`; compare `CurrentCompanyName`
   against our account name as an identity check.
3. **Verify and standardize for mail** — `doGlobalAddress` with `org` = practice name, `a1` =
   street (+ suite), `loc`/`admarea`/`postal`, `opt=DeliveryLines:ON,USStandardizationType:Short`.
   Keep `FormattedAddress`, `SubPremises`, `PostalCode` (+4), `DeliveryIndicator`,
   `MelissaAddressKey`, and the raw `Results` code string.
4. **Gate:** mail only when the AV code is in the allow-list **and** `DeliveryIndicator` is `B`
   (or `U` with a human's explicit acceptance). `R` on a business mailing is a research error worth
   surfacing, not silently mailing.
5. **Batch economics:** GAV accepts **100 records per POST**, so a whole campaign's addresses
   verify in one call — do this at export time, not per-contact during research.

**Recipient line:** the person is the `Attn:`/name line on an envelope addressed to the verified
*business* address. Melissa verifies the address; Apollo/Exa supply the person and title. Nothing
needs a person-level Melissa lookup.

---

## 6. Claim-store integration (still zero schema change)

Consistent with `ARV2-schema-impact-audit.md`: **no migration.** New registered field rows only,
following the existing `_seed(...)` pattern in `claimstore/packs.py` (the `core.work_email` /
`core.direct_phone` seeds are the precedent — both `reuse_scope=TENANT_PRIVATE`, 30-day freshness,
described as *delivery data*):

- `core.mailing_address` (object) — `{formatted, address_line1, suite, city, state, postal_code,
  plus4, delivery_indicator, melissa_address_key, av_result_codes[], site_role}` where `site_role`
  carries Business Coder's `LocationType`. `reuse_scope=TENANT_PRIVATE`,
  `freshness_ttl≈180d`, description states it is USPS-verified delivery data.
- `account.site_locations` (array) — the multi-site list the dossiers enumerate, each entry
  optionally verified.
- Optional cross-check rows: `core.employee_count_estimate_alt`, `core.sic_code`, `core.naics_code`
  — only if we decide to record Melissa's firmographics as independent corroboration.

**Stamping** (per the matrix in the schema audit): `source_key="melissa"` (a new seed manifest
entry, tier 1, `extraction_method=api`, `auth_ref=CLUE_MELISSA_LICENSE_KEY`), born `UNVERIFIED`,
`tenant_private` + workspace-stamped, `source_url` = the account's own site/Apollo record (Melissa
returns no citable URL — do **not** fabricate one; the provenance is the persisted response
snapshot + `MelissaAddressKey`). The verification substance lives in the recorded AV codes, not in
`verification_status`.

**Address of a *person's home* — the rule:** if we ever record one, it is
`use_class=personal-public-non-sensitive` at best, `identity_binding=WEAK` unless independently
confirmed, and it is **not** eligible for outreach without an explicit founder ruling. ARV2's
default is that no residential address enters the claim store at all.

---

## 7. Honest gaps and what the founder should check in their portal

1. **Pricing / credit consumption per endpoint — [BLOCKED-DOC], and the founder now has an
   account.** Please read: credits per `doGlobalAddress` record, per `doBusinessCoderUS` record,
   whether the free developer tier's 1,000 credits/month applies to these, and whether
   People/Business Search (Contact Search, Personator Search) is **separately contracted** — those
   products usually carry permissible-use terms that address verification does not.
2. **Result-code tables — [BLOCKED-DOC].** We need the AV/AC ladder for GAV and AS/DA/FS for
   Business Coder to pin the mailable allow-list. Until then the adapter stores codes and mails
   nothing automatically.
3. **Suite-level append for *businesses*.** GAV's `last` param is documented for **residential**
   suite append; the business equivalent (SuiteLink / AddressPlus behaviour) is on blocked pages —
   Business Coder's `Suite` output is our verified path meanwhile. **[UNVERIFIED]**
4. **Nothing consumes a verified address yet.** `direct_mail` exists as a design *medium*, but
   there is **no recipient-address slot** anywhere in the design or content schema and no
   mail-merge/export path. Melissa output would be stored and displayed on the contact profile
   only. **Recommendation: buy/build Melissa when the direct-mail export epic starts, not during
   the ARV2 research build** — it is a Phase-5 item, and doing it earlier ships a field nobody
   reads.
5. **Terms of use.** Skip-trace/consumer products (Contact Search, Personator Search) commonly
   carry permissible-purpose restrictions; ARV2 avoids them entirely, which also keeps this
   question off the table.
