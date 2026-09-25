# WVI — Website visitor identification and attribution: how RB2B / Ploy / Userled do it, and how Clue does it cheaper

**Status:** research study + feature proposal, 2026-09-24. Awaiting founder ratification (§8).
**Scope:** identify the *person* (and failing that the *company*) behind a visit to the client's
website or to a Clue-generated landing page; find them on LinkedIn; attribute the visit to the
account, contact, project, artifact and channel that caused it; hand the result to the CRM later.
**Method tags:** `[FETCHED]` read from the vendor's live page or docs this session · `[SNIPPET]`
search-result text only · `[VENDOR]` a vendor's own claim, unaudited · `[REPO]` verified in this
worktree at `9ae1b211b` (paths are repo-relative). "Not published" beats a guess.
**Companions:** `WVI-2-research-register-and-90pct-blueprint.md` (papers, repos, open data, the ≥90%-precision principles, the RB2B caveat, the quality blueprint), `ARV2-MASTER-PLAN.md` (authoritative for the research lane and the accounts
screens), `pricing-strategy/08-ploy-pricing-teardown.md`, `pricing-strategy/_scratch/groupC-data-signals.md`.

---

## 0. The answer in one page

**How the vendors do it.** Every "who is on my website" product is the same three-layer stack:

1. **Deterministic first-party** — the visitor arrived through a link *you* sent them (tokenised
   email link, per-account page, QR on a mailer) or filled a form. 100% accurate, coverage limited
   to people you reached. Userled ranks this first, above everything else `[FETCHED]`.
2. **Company-level by IP** — reverse-IP lookup against curated corporate IP ranges. Works
   worldwide, no cookies, ~30% of B2B traffic on a good day, kills nothing legally if you stop at
   the company. Warmly runs a waterfall of 20+ such providers; RB2B rents Demandbase's `[SNIPPET]`.
3. **Person-level by identity graph** — a script on the site reads a first-party cookie plus
   device/IP signals and queries a rented *identity graph* built from an "opted-in partner network"
   of consumer sites where people typed an email that was hashed and bound to their browser. A hit
   returns a (hashed) email; a **second** lookup against a B2B database turns that email into
   name, title, company and **LinkedIn URL**. US-only by geofence; realistic 15–40% of US traffic;
   accuracy is the whole fight (§2.3). Nobody finds anyone *on LinkedIn*; LinkedIn is a column in
   the B2B database keyed by email.

RB2B, Vector, Warmly, Ploy, Apollo Inbound and Leadpipe are all layer 2 + layer 3 resellers with
different graphs, different B2B enrichment waterfalls, and different honesty. Ploy does not name
its graph; its own copy ("opted-in partner network… no LinkedIn fingerprinting… no SDK… US-located…
verifiable consent record") `[FETCHED]` is the standard white-label language of the graph vendors.

**How Clue should do it — the identification ladder, cheapest rung first.**

| Rung | Mechanism | Cost | Coverage | Accuracy | Where it works |
|---|---|---|---|---|---|
| 0 | **Clue links**: a signed token on every artifact Clue generates (per-account ABM page, email copy, LinkedIn DM, direct-mail QR) | $0 | everyone we reached | 100% | worldwide |
| 1 | **Reverse IP** on Clue-hosted pages (server-side, no script) and on the client's site (script) | $0.3–0.7 per 1,000 lookups `[FETCHED]` | ~25–35% of B2B traffic to a company `[SNIPPET]` | good for large companies, weak for SMB/remote | worldwide (legitimate interest) |
| 2 | **Identity-graph reveal**, gated to US visitors from accounts already in a project (or on a high-intent page), then **AI Ark reverse lookup by email → LinkedIn URL** | $0.10–0.30 per identified person `[FETCHED]` + 0.5 AI Ark credit (≈$0.002–0.01) `[FETCHED]` | 15–40% of *gated* US visitors | vendor-dependent; measure on our own site first | US only |

The cheapest useful product is **rung 0 + rung 1 with no vendor at all**: Clue already hosts the
per-account pages it generates (`/w/{workspace}/p/abm-<account>`), so the page server *is* the
collector — it sees the token, the IP, the referrer and the user agent on every request. That is
one migration, one fleet handler, and one cheap IP API. Rung 2 is added as a swappable resolver
later and only fires for visitors worth $0.30 — the same "cheap pass for everyone, expensive pass
for the few" rule the platform already lives by.

**What has to be built (the full list is §6):** a token minting + link table; a collector (server
log on hosted pages, a ≤2 KB first-party script for client sites); a jurisdiction/consent gate;
a `visitor_resolve` fleet handler with three resolvers behind the existing `Resolver` protocol;
web-engagement claims and an activity kind; a pre-spend policy for rung 2; the Activity-tab and
contact-chip rendering (no new components); a Head-of-ABM read tool; a CRM outbox event.

---

## 1. The anatomy of website de-anonymization

### 1.1 Layer 1 — deterministic first-party (the one everybody under-uses)

- **Tokenised outbound links.** Userled's Identity Layer ranks its methods "by accuracy: 1.
  Contact-level tracking links, 2. Account-level tracking links, 3. IP reveal" and reports that
  adding identification to email templates "often leads to a boost of 20~30% net new identities"
  `[FETCHED]` <https://intercom.help/userled/en/articles/9515210-identity-layer>. Its mechanism is
  a URL parameter: `?ul_e={{email}}` appended in HubSpot, Salesforce, Outreach, Apollo, Salesloft
  and Amplemarket templates (`ko_e` for Amplemarket) — the **email address in plain text in the
  URL** `[FETCHED]` <https://intercom.help/userled/en/articles/9984428-identify-email-recipients>.
  Clue must not copy the plaintext part (§4.1): an opaque signed token that resolves server-side
  gives the same identification with no PII in logs, referrers or analytics.
- **Per-account and per-contact pages.** Userled's product is 1:1 microsites; Mutiny and Ploy
  build "a personalized landing page per target account" and Ploy accepts a Clay webhook to do it
  `[FETCHED]` <https://ploy.ai/faq>. A unique URL per account is itself an identifier: a visit to
  `/p/abm-hotel-equities` from an unknown IP is still an account-level identification.
- **Form fills and logins** ("identify" calls). Table stakes; out of scope here except that a
  visitor id cookie must be stitched to the contact when it happens.
- **Offline.** A QR on a direct-mail piece is a tokenised link. Vector's "match rates up to 90% on
  LinkedIn" `[FETCHED]` <https://coldiq.com/tools/vector> is *ad-audience matching* (uploading
  identified contacts to LinkedIn Matched Audiences), not identification — but it is a real
  "attribute other things" use: identified visitors become a retargeting audience.

### 1.2 Layer 2 — company-level by reverse IP

- **Mechanism.** IP → autonomous system / registrant organisation (WHOIS/RDAP, reverse DNS) →
  curated corporate ranges. The registrant data is free and public; the *curation* — which ranges
  are a company's offices rather than an ISP, a cloud region, a VPN egress or a mobile carrier, and
  which company actually sits behind a shared range — is the vendors' moat, built from observed
  logins and form fills across their customer base. Remote work has eroded it: most SMB visitors
  now arrive from residential ISPs and resolve to "Comcast".
- **Realistic rates.** "Match rates typically fall between 25-35% of website traffic" (industry);
  "Company-level identification matches 30–65% of B2B visitors" (vendor-authored guide) `[SNIPPET]`.
  RB2B's own doc: "30–35%" company-level on US traffic `[FETCHED]`
  <https://support.rb2b.com/en/articles/8891294-what-is-rb2b-and-how-does-it-work>.
- **Price ladder (2026).**

| Provider | What you get | Price | Tag |
|---|---|---|---|
| ipregistry | geolocation + **ASN and company data** + VPN/proxy flags on every plan; 20,000 free credits | $10/15k → $500/1.75M credits = **$0.67 → $0.29 per 1,000** | `[FETCHED]` <https://ipregistry.co/pricing/> |
| ipapi.is | API $0 (1k/day) → $200/mo (2M/day) = $0.001 → $0.0001 per 1,000; **IP-to-Company database download $89/mo** | cheapest bulk option | `[FETCHED]` <https://ipapi.is/pricing.html> |
| IPinfo | "Company name, domain, route and type" only on **Enterprise (custom)**; Core $26/mo, Max $163/mo are geo/ASN | company data is not self-serve | `[FETCHED]` <https://ipinfo.io/pricing> |
| Snitcher IP-to-Company API | `POST /company/find?ip=` → name, domain, industry, employee range, LinkedIn/Crunchbase, a `fuzzy` confidence flag, `type: isp` → 404; 600 req/min | "standalone offering… not included with our standard product plans"; contact sales | `[FETCHED]` <https://docs.snitcher.com/powered-by-snitcher/ip2company/quickstart> |
| Dealfront (Leadfeeder), Demandbase, 6sense, Clearbit→HubSpot Breeze | the curated-range incumbents; tools, not APIs, except enterprise contracts | Dealfront from ~€99/mo; 6sense/Demandbase $10k–$200k+/yr | `[SNIPPET]` |

  The gap between ipregistry-class data (registrant org) and Snitcher/Demandbase-class data
  (curated visitor ranges) is real: expect the cheap tier to name mostly large companies with their
  own address space, and the curated tier to add mid-market offices. Start cheap, upgrade the
  resolver when the miss rate on known target accounts says so — the resolver seam (§4.4) makes
  that a config change.

### 1.3 Layer 3 — person-level by identity graph (the part everyone is vague about)

**The plumbing, stated plainly.**

1. A consumer enters an email on a *partner* site — newsletter, sweepstakes, coupon, e-commerce
   checkout. The partner runs the graph vendor's pixel. The email is hashed (SHA-256/MD5) and bound
   to that browser's cookie, device fingerprint and IP. "That email gets hashed and associated with
   the user's browser fingerprint and cookie. The hash enters an identity graph" `[SNIPPET]`
   <https://www.geysera.com/blog/visitor-identification/website-visitor-identification-for-ecommerce-how-identity-graphs-and-server-side-tracking-actually-work-2026>.
2. Later the same browser lands on your site. The reseller's script (RB2B, Ploy, Leadpipe…)
   collects a first-party visitor id plus device and IP signals and queries the graph. RB2B: "In
   cases where a user's device has not been previously cookied by RB2B's publisher network, the
   ability to identify that user is significantly reduced" `[SNIPPET]`; all ten of RB2B's cookies
   (`_reb2buid` 360 days, `_reb2butk` 1 year, `_reb2btd`, `_reb2bli`, `_reb2bresolve`…) are
   **first-party, on the customer's domain** `[FETCHED]`
   <https://support.rb2b.com/en/articles/9910029-rb2b-cookie-information> — the cross-site link is
   made server-side from IP + device signals + whatever third-party cookie the graph still holds.
3. A hit returns the graph's record: hashed/plain email, name, sometimes postal address. Graph
   wholesalers are **consumer** databases: BIGDBM claims "280M+ U.S. Consumer Identities", "700M+
   Email Records", "80%+ Hashed Email Match Rate", real-time API at "100–300ms", and lists no
   LinkedIn or B2B coverage at all `[FETCHED]` <https://bigdbm.com/identity-data-statistics/>;
   Audience Acuity is "built on deterministic resolution and a scaled referential data graph" over
   "mobile device IDs, hashed emails, CTV IDs, IP addresses" `[FETCHED]` <https://audienceacuity.com/>.
4. **A second lookup makes it B2B.** The email is run through a professional database to get
   title, employer and LinkedIn URL. RB2B: "Profile enrichment using verified professional data
   sources — including LinkedIn and other publicly available professional databases" `[FETCHED]`;
   its Pro+ tier "adds premium resolution through a waterfall of trusted external data sources,
   roughly doubling the contact-level match rate to 35-45% compared to Pro's 15-20%" `[SNIPPET]`.
   This step is exactly what Clue already pays for: **AI Ark `POST /v1/people/reverse-lookup`,
   input "the email address… the only request field", "0.5 credits per request", returns
   `full_name`, `title`, `linkedin`, company** `[FETCHED]`
   <https://docs.ai-ark.com/reference/people-reverse-lookup.md>; Apollo `POST /people/match`
   accepts `email` **or `hashed_email`** `[REPO]` `docs/specs/ARV2-apollo-api-contract.md:80-82`;
   People Data Labs accepts `email_hash` (SHA-256 or MD5) and charges "per match" (~$0.28 at the
   $98/mo tier) `[FETCHED]` <https://docs.peopledatalabs.com/docs/reference-person-enrichment-api>.
5. **Geofence and consent theatre.** Every vendor restricts person-level to the US. Ploy:
   resolution is "US-located" only, "enforced via geofencing on the resolution endpoint", each
   contact carries "a verifiable consent record — timestamp, source, and IP", visitors who decline
   cookies or send Do Not Track "are suppressed at the resolution layer" `[FETCHED]`
   <https://ploy.ai/features/visitor-identification>. RB2B: "Only visitors verified as US-based are
   eligible for person-level identification" `[FETCHED]`. Leadpipe: "Person-level identification
   is US-only; EU and UK traffic defaults to company-level under GDPR" `[FETCHED]`
   <https://www.leadpipe.com/pricing/>.

**Deterministic vs probabilistic.** Deterministic = the graph holds an exact prior binding of this
browser to that hashed email. Probabilistic = inferred from IP + device + timing overlap; wider
coverage, more wrong people. The independent evidence (all of it vendor-adjacent, §2.3) says the
probabilistic tools return the wrong person often enough to embarrass a rep.

**Browser reality (2026).** Chrome kept third-party cookies (Google dropped deprecation in July
2024 and dropped the choice prompt in April 2025; most Privacy Sandbox APIs were retired in
October 2025); Safari and Firefox block them by default, ~17–20% of traffic `[SNIPPET]`. Graphs
therefore lean on first-party cookies set by the reseller script plus IP/device matching — which is
why match rates are quoted on *US desktop Chrome* and quietly collapse on iPhones.

### 1.4 The legal floor (what a product built on this must do)

- **US.** CCPA/CPRA is an opt-out regime; the B2B exemption expired 1 January 2023, so business
  contact data is in scope `[SNIPPET]`. Duties: notice at collection, honour the Global Privacy
  Control signal, contract vendors as service providers, honour know/delete/correct requests
  `[FETCHED]` <https://www.leadpipe.com/blog/is-website-visitor-identification-legal/>.
  Enforcement is about missing opt-outs: Tractor Supply $1.35M (Sep 2025), PlayOn Sports $1.10M
  by the CPPA (Mar 2026) for sharing tracking data without a compliant opt-out `[SNIPPET]`.
- **CIPA (California wiretap) in 2026.** Pixel and script suits under Penal Code §638.51 (pen
  register) carry $5,000 statutory damages per visitor. **SB 690 passed the legislature on
  28 August 2026**: as passed it removes the *private* right of action for §638.51 website claims
  (only the Attorney General may sue), retroactive to claims filed on or after 1 January 2025,
  operative 1 January 2027 if signed; **§631/§632 wiretap and eavesdropping claims are untouched**
  `[SNIPPET]` <https://www.sidley.com/en/insights/newsupdates/2026/09/californias-sb-690-clears-the-legislature-what-it-means-for-cipa-website-tracking-claims>.
  Practical reading: the pen-register theory that hit visitor-ID pixels is being closed; the
  wiretap theory is not; consent before the script runs remains the defence.
- **EU/UK.** Person-level identification needs consent under GDPR, and ePrivacy/PECR needs consent
  "before you store or read anything on a visitor's device — regardless of your GDPR basis";
  company-level by IP under legitimate interest is the honest ceiling `[FETCHED]` (Leadpipe legal
  page). Every vendor geofences to company-level in the EU.
- **Vendors push the duty to the site owner.** RB2B "requires you to update your privacy policy and
  cookie banner… Compliance responsibility rests entirely with you" `[SNIPPET]`
  <https://support.rb2b.com/en/articles/8795972-updating-your-privacy-policy>. Clue must ship the
  policy text and the consent hook as part of the feature, not as a footnote.
- **Clue's own Doc D machinery already models this** `[REPO]`: `Jurisdiction` (gdpr | uk_gdpr |
  us_state | global_strict, default GDPR — `libs/clue-config/clue_config/policy.py:30-47`),
  `UseClass` and per-claim `identity_binding` (`libs/clue-core/clue_core/enums.py:90-99`,
  `claim.py:139-140`), `LawfulBasis` with `derive_lawful_basis` and `record_lawful_basis`
  (`subsystems/research/clue_research/compliance/lawful_basis.py:87-216`), the use gate
  (`compliance/use_gate.py:264`), and DSAR tombstoning (`compliance/dsar.py`). A visit becomes a
  claim, so it inherits all of it. What does not exist: cookies, consent state, GPC, ePrivacy — none
  in code; the only cookies today are auth sessions.

---

## 2. The vendors, one by one

### 2.1 Mechanism, output, price

| Vendor | Company-level | Person-level | Geography | Output | Price | API for builders | Tag |
|---|---|---|---|---|---|---|---|
| **RB2B** | Demandbase reverse-IP network; "30–35%" | own publisher-network graph + first-party cookies + device ids + IP; Pro+ adds an external B2B waterfall; claims "40–45%" of qualified US traffic | US only (person) | name, title, employer, domain, **LinkedIn URL, professional email**, pages | Free = company-level only since Jan 2026; Starter $79/300 credits; Pro $149/600 (webhooks, Zapier, HubSpot, Salesforce, Clay, Apollo); Pro+ $199/600 with the waterfall; ~$0.10/credit at $499/5,000; **Clay Agency Starter $49 per client account/mo with 1,250 credits**; 1 credit = one unique visitor identified per 30-day window | webhooks on Pro | `[FETCHED]` support docs + `[SNIPPET]` pricing pages |
| **Vector** | yes | "device fingerprinting matched against a proprietary publisher network"; "15–30% of U.S. visitors at the contact level" | US (person) | name, title, email, LinkedIn URL | Free 5 IDs; Plus $399/mo for 1,000; Growth $3,000/yr for 10,000; Enterprise unlimited | HMAC-signed webhooks (`X-Vector-Signature`) | `[FETCHED]` coldiq + `[SNIPPET]` |
| **Warmly** | waterfall of "20+ data providers", first hit wins | "extensive partner network of publishers and data providers", "five different data providers for email conversion"; admits "lower match rates" | not stated | role, email, title, company | ~$700–900/mo annual; custom from $15k/yr | integrations | `[FETCHED]` help centre |
| **Userled** | Clearbit and 6sense partner IP reveal | **none by graph** — contact-level comes from tracked links (`ul_e` param) and CRM identity; cookieless fingerprinting across the customer's domains | worldwide (links) | unified profile per account/contact | modules, "$25,000/yr entry" (pricing-strategy 06 §1.3) | n/a | `[FETCHED]` help centre |
| **Ploy** | IP → company "in milliseconds — with no SDK install or JavaScript fingerprinting" | "opted-in partner network of websites where consumers have agreed to share their information for third-party marketing"; graph vendor **not named** | US only, geofenced at the resolution endpoint | company + "likely contacts with LinkedIn profiles", intent from "page paths, dwell time, scroll depth, and repeat visits" | enrichment allowance 50/mo Starter ($50), 1,000/mo Pro ($300); pushes to Attio, HubSpot, Clay | none | `[FETCHED]` feature page + FAQ; pricing-strategy 08 |
| **Apollo Inbound add-on** | company-level free on every plan (industry, headcount, pages) | contact-level with the add-on, US only, "up to 50,000 companies" cap | US (person) | Apollo person record | $119/team/mo annual, $149 monthly | in Apollo | `[SNIPPET]` |
| **Leadpipe** | yes; EU/UK default to company-level | "deterministic matching" against "685 million verified profiles" (vendor); "30-40%+" B2B US | US (person) | `email, first_name, last_name, company_name, company_domain, job_title, linkedin_url, phone, pages_viewed, referrer…` | Pro $147/500 → $1,879/20k; **Agency $1,279/10k → $5,500/200k, unlimited clients**; **Platforms tier = API, custom price, "3-month POC with high limits"**; ~$0.30/ID list; pixel pauses at cap, no overage | webhook + API, white-label at Platforms | `[FETCHED]` pricing + payload reference |
| **Bullseye** | yes | "up to 40%" | not stated | name, work email, title, company, direct dials | not published | **"Whitelabel branded tracking pixel", "Whitelabel API integration", custom domain** for platforms/resellers | `[FETCHED]` homepage |
| **BIGDBM / Audience Acuity** (graph wholesalers) | n/a | the graph itself: hashed-email ↔ device/IP/MAID links, consumer PII | US | consumer identity, **no LinkedIn** | marketplace/enterprise; not published | real-time APIs, pixels via partners | `[FETCHED]` |

Sources for this table: <https://support.rb2b.com/en/articles/8891294-what-is-rb2b-and-how-does-it-work>,
<https://support.rb2b.com/en/articles/11155068-contact-level-identification>,
<https://www.rb2b.com/built-for-clay>, <https://pipeline.zoominfo.com/sales/rb2b-pricing>,
<https://coldiq.com/tools/vector>, <https://help.warmly.ai/articles/3568026273-contact-level-identification>,
<https://intercom.help/userled/en/articles/9515210-identity-layer>, <https://ploy.ai/features/visitor-identification>,
<https://www.apollo.io/product/website-visitor-identification>, <https://www.leadpipe.com/pricing/>,
<https://leadpipe.com/blog/webhook-payload-reference-every-visitor-data-field/>, <https://www.bullseye.so/>,
<https://bigdbm.com/identity-data-statistics/>, <https://audienceacuity.com/>.

### 2.2 What this says about "how RB2B / Ploy / Userled usually do it"

- **RB2B** built its own consumer-side graph (Adam Robinson's Retention.com lineage), rents
  Demandbase for company-level, and buys a B2B enrichment waterfall for Pro+. It sells per
  identified visitor and makes the site owner carry the privacy exposure.
- **Ploy** rents a graph and wraps it in the website builder; the value is that the same product
  that *builds* the page also *reads* who came. That is exactly Clue's position with the design
  subsystem — with the difference that Clue also knows *which account the page was built for*.
- **Userled** does not buy a person graph at all. It gets contact-level identity from the links it
  controls (outbound + 1:1 microsites) and buys only company-level IP reveal from partners. For an
  ABM product this is the honest, EU-safe design, and it is the one Clue should copy first.

### 2.3 Accuracy: the only evidence that exists is vendor-adjacent

- A press-released "Gartner auditor" test (26 March 2026, via ABNewswire; treat as Leadpipe-adjacent)
  sent known contacts to three live B2B sites (~25k visits/month): Leadpipe "correctly identifying
  82 percent of known visitors" (8.7/10); RB2B 5.2 overall, "consistently identified irrelevant
  contacts — wrong seniority levels, wrong departments"; Warmly 4/10 "after returning entirely
  wrong individuals from unrelated companies"; 6sense 6.5; Leadfeeder 6.2 `[SNIPPET]`
  <https://www.barchart.com/story/news/993090/gartner-auditor-tests-rb2b-leadpipe-warmly-clearbit-6sense-leadfeeder-accuracy-results-vary-widely>.
- Leadpipe's own developer guide: "Leadpipe: 30-40% match rate, 87% accuracy; RB2B: 5-20% match
  rate, 52% accuracy; Warmly: 15-25% match rate, 40% accuracy" `[FETCHED]`
  <https://www.leadpipe.com/blog/visitor-identification-api-complete-developer-guide/>.
- The vendors' own numbers: RB2B "40–45%" person-level; Vector "15–30%"; Bullseye "up to 40%";
  Ploy publishes none.

Reading: the spread between a vendor's claim and an adversarial test is 2–3× on coverage and
~2× on accuracy. **Clue must measure before it sells**: run the known-visitor test on cluehq.ai and
on one pilot client's site (§7, phase V2 exit gate) and publish the number to the client as a
coverage confidence, the way the research layer already reports estimated coverage rather than
completeness.

---

## 3. Why Clue's position is different (and cheaper)

1. **Clue hosts the pages it generates.** The design API publishes web documents at
   `/w/{workspace_id}/p/{slug}` and derives **one page per account** (`abm-<account-slug>`,
   deterministic document id `abm_derived_document_id(template_id, account_id)`, stamped `noindex`)
   `[REPO]` `subsystems/clue-design/apps/api/lumen_api/main.py:4317, 5128-5258, 5492, 7345-7352, 7461, 7479`.
   Every request to such a page already carries IP, user agent, referrer and query string to a
   server Clue controls. **Rung 0 and rung 1 need no pixel on those pages.**
2. **Clue knows the audience before the visit.** The engine's `BindingSet` carries
   `audience{account_id?, contact_id?}` and `links: InstanceLink{url}`; there is a `UrlQr` slot type
   `[REPO]` `subsystems/clue-design/crates/lumen-core/src/binding.rs:20-42, 77-79`, `slots.rs:59`.
   Doc S records that instances "already carry InstanceLink/QR hooks for landing pages +
   attribution-lite" as a v2 activation `[REPO]` `docs/architecture/clue-hq-content-and-artifact-scaling.md:179-180`.
   Nothing is wired, but the shape was designed for exactly this.
3. **Clue already has the B2B half of the graph lookup.** AI Ark reverse lookup by email is 0.5
   credit `[FETCHED]`; at the Premium tier ($49 for 5,000 credits) that is $0.005, at volume
   $0.002–0.004 `[REPO]` `docs/specs/ARV2-ai-ark-contract-notes.md:48-50`. RB2B charges $0.10–0.26
   for the whole reveal; the B2B step is a rounding error for us.
4. **Clue has a target list.** Rung 2's paid reveal fires only for visitors whose rung-1 company is
   a `project_account` (or who hit a high-intent page). A vendor pixel reveals everyone because it
   is paid per reveal; Clue reveals the few it can act on.
5. **A visit is a claim.** `insert_claim` with `extraction_method=api`, provider `source_key`,
   `identity_binding` from the method, `use_class=professional-public`, `signal_priority=1` for a
   pricing/ABM-page visit (`ARV2-MASTER-PLAN.md` §4). The use gate, DSAR and lineage are free.

What Clue cannot do: build its own consumer identity graph. That requires a publisher network of
opted-in consumer sites; RB2B's is its moat. Rent it (Leadpipe Platforms, Bullseye white-label, or
a wholesaler), behind a resolver, and be ready to swap.

---

## 4. Integration design — seam by seam

Terminology: a **visitor** is a first-party id (cookie on client sites, or a server-issued id on
Clue pages); a **visit event** is one page view; a **resolution** is the binding of a visitor to an
`account_entity` and/or `contact_entity` by one method; the **claims** are the durable, governed
facts the screens and the agent read.

### 4.1 Rung 0 — Clue links (token minting)

- New table `visitor_link` (`token` opaque 22-char url-safe id, `workspace_id`, `project_id`,
  `artifact_ref` (design document id / campaign artifact id / mailer id), `channel`
  (email | linkedin_dm | ad | direct_mail | other), `account_entity_id NULL`,
  `contact_entity_id NULL`, `created_by`, `created_at`, `expires_at NULL`). Tokens are random, not
  derived — a token must not be guessable from an account id. The URL form is `?cl=<token>`; the
  page server strips it before rendering and never echoes it (the pages already send
  `Referrer-Policy: no-referrer` `[REPO]` `main.py:5509-5520`).
- Minting happens where artifacts are scaled: the design batch derive (`POST /documents/{id}/web/batch`)
  mints an account token per derived page and writes it into the page's `InstanceLink`; the
  content layer mints a contact token per email/DM opener; the direct-mail path mints one per piece
  into the `UrlQr` slot. Until those writers exist, a `POST /frontend/v1/visitor-links` endpoint
  lets a human mint a link for an account or contact from the accounts screens (this is the
  smallest V0: a "Copy tracked link" action).
- **Why not Userled's `ul_e=email`:** an email in a URL leaks into browser history, server logs,
  referrer headers of any outbound click, and the client's analytics. The token design gives the
  same identification and is what our Doc D posture demands.

### 4.2 Collection

- **Clue-hosted pages (no script).** The `/w/{ws}/p/{slug}` handler enqueues a `web_visit_event`
  per HTML request: `visitor_id` (a first-party `clue_vid` cookie set by the page server, 13
  months; only after consent where the jurisdiction requires it — see 4.5), `link_token`,
  `page_url`, `referrer`, `utm_json`, `ip` (retained raw for 30 days for resolution, then reduced
  to country + a salted hash), `user_agent_class`, `geo_country`, `received_at`. Bot filtering by
  UA class and a known-crawler list before enqueue. This does **not** require relaxing the
  published-page CSP (`connect-src 'none'`, script sanitiser) `[REPO]` `web_export.py:1264-1287`,
  `fragments/sanitize.py:15-40` — the server logs the request itself.
- **Client's own site (script).** `clue.js` ≤2 KB, served from Clue's origin, installed via
  Webflow/HubSpot/GTM/Ploy-style header snippet with the workspace's public pixel key. It sets
  `clue_vid`, reads `?cl=`, honours `navigator.globalPrivacyControl` and DNT, waits for the CMP
  signal in consent jurisdictions, and `POST`s to `/v1/collect` (unauthenticated, keyed by the
  public pixel key, 202, enqueue-only — copy the `ExaWebhookIngestor` shape `[REPO]`
  `platform/api/clue_api/exa_websets_lifecycle.py:285, 414`, mounted like `projections_main.py:288-296`).
  Inbound rate limiting per key must be added; today there is none (`[REPO]` only the outbound
  `RateLimiter` exists).
- **Consent state travels with the event** (`consent_state: granted | denied | not_required |
  unknown`, `gpc: bool`). The resolver never sees an event it may not act on.

### 4.3 Resolution — one fleet handler, three resolvers

- `FleetTaskKind.VISITOR_RESOLVE` (append + `ALTER TYPE` migration, precedents `93113e83bf2f`,
  `be855c8f6993` `[REPO]`), enqueued with `dedup_key = f"visitor-resolve:{visitor_id}:{day}"` via
  `enqueue_task` (`platform/fleet/clue_fleet/queue.py:384`); handler registered the way
  `DbStage0ReconEnqueuer`/its handler are (`stage0_setup_fleet.py:84-114`).
- The handler runs the ladder and stops at the first binding that the policy allows:
  1. **token** → `visitor_link` row → account/contact. `identity_binding=STRONG`, method `link`.
  2. **reverse IP** → `Resolver` for source `reverse_ip` (provider config: ipregistry → ipapi.is →
     Snitcher) → domain → `identity.resolve(Observation(domain=…))` in the workspace `[REPO]`
     `subsystems/research/clue_research/identity/resolve.py:217-243, 420` (or
     `resolve_account_entity_id` `subsystems/design/clue_design/joins.py:115`). ISP/cloud/VPN/mobile
     types are discarded, `fuzzy` matches are `WEAK`. A domain with no `account_entity` is written
     as a `visiting_company` suggestion (a discovery seed, not an account — accounts are created by
     discovery/import only, master plan §5.1 D7).
  3. **identity graph** (rung 2) — only if `geo_country == US`, `consent_state != denied`,
     `gpc == false`, and (account ∈ `project_account` for an active project **or** page ∈ the
     workspace's high-intent list) **and** the workspace's monthly reveal cap has room. Provider
     returns email (plain or hash) + name; then AI Ark `reverse-lookup(email)` → LinkedIn URL,
     title, company (Apollo `people/match(hashed_email)` as the configured fallback). Bind to
     `contact_entity` by the strong keys `verified_email` / `linkedin_url` `[REPO]`
     `identity/resolve.py:246-265`; if none, insert a contact under the resolved account via
     `insert_contact_entity` with `identity_binding=WEAK` and a `needs_review` marker. Employer
     mismatch (graph says acme.com, IP says other.com) → WEAK and review, never silent.
- Every paid call writes the cost ledger row (ARV2 rule) and is preceded by the pre-spend check
  against a per-workspace `CLUE_WVI_MONTHLY_REVEAL_CAP` (record-only until budget controls are on,
  like the other caps).
- Writes, in one transaction: `visitor_resolution` row; claims `account.web_engagement`
  (object: `last_visit_at`, `visits_30d`, `pages[]`, `high_intent_pages[]`, `channels[]`,
  `identified_contacts`) and `contact.web_engagement` (same shape plus `link_token_channel`);
  `account_activity_event` kind `visit` (the ARV2 D1 table, `ARV2-DATA-SOURCE-MAP.md:106` — add
  the kind to its CHECK); lineage via the project's `run_lineage` so the claim is visible on the
  project's pages. `run_event` is **not** extended: its subject kinds are a closed CHECK
  (`project_run`/`design_run`) `[REPO]` `libs/clue-core/clue_core/run_event.py:42-87`.

### 4.4 Source manifests and the resolver seam

Register three sources in `sources/seeds.py` with the `_entry(...)` helper, copying the `crm`
entry's shape (tier 1, `IdentityBinding.STRONG`, `freshness_profile="realtime"`) `[REPO]`
`subsystems/research/clue_research/sources/seeds.py:30-64, 292-302`:

| source_key | modality | entity_scope | tier | identity_binding prior | yields |
|---|---|---|---|---|---|
| `visitor_link` | api | contact/account | 1 | STRONG | `contact.web_engagement`, `account.web_engagement` |
| `reverse_ip` | api | account | 2 | WEAK (MEDIUM only when the provider's non-fuzzy flag is set) | `account.web_engagement` |
| `identity_graph` | api | contact | 3 | WEAK (provider "deterministic" flag does not upgrade it until our own accuracy test says so) | `contact.web_engagement` |

Each is a `Resolver` (`resolve(entity, field) -> list[Claim]`, `libs/clue-core/clue_core/resolver.py:41-52`)
bound with `bind_resolver`; provider SDK imports stay inside the provider package (the static
import guards — note they currently scan an empty path, CLAUDE.md `[tooling]` bullet). Swapping
ipregistry for Snitcher, or Leadpipe for Bullseye, is a registry/config change.

### 4.5 Compliance, in code

- Jurisdiction from `geo_country` on the event → `Jurisdiction` policy: `gdpr`/`uk_gdpr` →
  rung 2 never; `clue_vid` set only after `consent_state == granted`; rung 1 under
  `legitimate_interest` (recorded with `record_lawful_basis`, `lia_ref` = the WVI LIA document).
  `us_state` → rung 2 allowed, `consent` basis carried from the provider's consent record
  (timestamp/source), GPC honoured as opt-out, suppression list checked.
- A person-level visit claim is `use_class=professional-public`; nothing about a visit is ever
  `sensitive`. The use gate (`decide_use`) governs whether the claim may drive outreach; the display
  predicate for the accounts screens is the ARV2 S10 read-time relaxation.
- DSAR: `compliance/dsar.py` tombstones claims by contact; add `web_visit_event` /
  `visitor_resolution` rows keyed to that contact to its selector (same pattern as the durable
  email-enrichment commit `c3b34494f` which touched `dsar.py`).
- Retention: raw IP 30 days; events 13 months; resolutions follow the contact's retention.
- Product assets that ship with the feature: privacy-policy paragraph for clients (US and EU
  variants), the CMP hook contract, a per-workspace "person-level reveal: on/off/US-only" switch
  defaulting to **off**.

### 4.6 Read side and screens (no new components)

- **Account Activity tab**: add `visit` to the closed kinds. Today the tab reads
  `research_subject_activity` with a 3-value enum (`platform/api/clue_api/frontend_read/account_activity.py:37-43`,
  `apps/frontend/src/features/accounts/model/account-activity.ts:6-10`) and ARV2 D3 replaces it
  with `account_activity_event` — the `visit` kind rides that replacement.
  Text is served: "Nick Fisher opened the ABM page from the September mailer (2 min, pricing)".
- **Account detail**: `account.web_engagement` renders through the generic field-key rendering
  the frontend already has (`[REPO]` audit note: "Frontend renders new research fields with zero
  change"); a "Visited 3× this week" chip is a QUESTION for the dummy frontend, not a component.
- **Contact profile**: the "Recent signals" chip is fed by `CONTACT_SIGNAL_FIELD_KEYS`
  (`frontend_read/contacts.py:129`); add `contact.web_engagement`.
- **Project-level "Who's on the site" list** (the RB2B feed): a later screen; QUESTION for the
  dummy frontend.

### 4.7 Scoring and the agent

- `account.scoring.intent` is a computed Pass A object written by `score_account` from
  "scoring-tagged deterministic proxies" `[REPO]` `discovery_scoring/scoring/engine.py:142-374`,
  `icp/rubric.py:65-69`. Doc C's intent proxies are job-count delta, funding and headcount growth —
  no first-party engagement row `[REPO]` `docs/architecture/clue-hq-signal-execution-cost.md:9-26`.
  Register `account.web_engagement` with `signal_class="intent"` so the compiler's
  `_build_signal_links` picks it up (`icp/compiler.py:118`) and the rubric can weight it. This is
  the first *first-party* intent proxy the platform has had.
- Head-of-ABM: a read tool `list_recent_visits(project_id, since)` registered through
  `build_toolbelt` (`toolbelt_wiring.py:2605, 2945`), returning identified and company-level
  visitors with their pages and channels. The 2026-09-19 behavioural audit found the agent "never
  acts or plans proactively" and has "no signal-scan tools"; this is the first signal worth
  scanning. A daily system-authored digest turn does not exist (`AGENT_TURN` is human-submitted
  only `[REPO]` `agent_turn_submission.py:1-35`) — propose it as a separate ruling.

### 4.8 CRM (later, but shaped now)

CRM write-back is forbidden in the resolver layer ("Postgres is the only write path",
`resolvers/crm/__init__.py:125-155` `[REPO]`). The correct seam is the **outbox**: emit a
`visitor.identified` / `account.visited` event the way `emit_handoff_event` does
(`narrative/handoff_events.py:135`) and let a publisher push a HubSpot timeline event, an Attio
note or a Salesforce task. Read-back (is this contact already a CRM lead?) comes through the
existing read-only `CrmResolver` when a connector exists. Nothing in rungs 0–2 depends on this.

---

## 5. What "attribute other things" means here

| Question | Answered by | Rung |
|---|---|---|
| Which contact came back to the ABM page after the mailer / the LinkedIn DM / the email? | token channel + contact binding | 0 |
| Which channel and artifact drove the visit? | token `channel` + `artifact_ref`; UTM/referrer as fallback | 0/1 |
| Which target accounts are on the client's site this week, unprompted? | reverse IP ∩ `project_account` | 1 |
| Which new companies (not yet accounts) keep showing up? | `visiting_company` suggestions → discovery seeds | 1 |
| Who, by name, at a target account is researching pricing? | identity graph + AI Ark → contact | 2 |
| Multi-touch across artifacts | `clue_vid` stitching across Clue pages + client site | 0–2 |
| Offline: did the direct-mail piece get scanned? | `UrlQr` token | 0 |
| Retargeting | identified contacts → LinkedIn/Meta Matched Audiences (Vector's "syncs to LinkedIn, Google, Meta, and Reddit" `[FETCHED]`) | 2, later |
| Intent score with a first-party input | `account.web_engagement` as a `signal_class=intent` proxy | 1–2 |

---

## 6. What must be built — the checklist

**Migration (one, Aryan):** `visitor_link`, `web_visit_event`, `visitor_resolution`,
`ALTER TYPE fleet_task_kind ADD VALUE 'visitor_resolve'`, `account_activity_event.kind += 'visit'`,
field registry rows `account.web_engagement` / `contact.web_engagement` / `account.visiting_company`,
three source manifests. Hash revision id, single head, `make db-smoke`.

**Collector:** the `/w/{ws}/p/{slug}` request hook (design API); `POST /v1/collect` + public pixel
key + inbound rate limit (projections app); `clue.js` (static asset, own origin); bot filter.

**Token minting:** `visitor_link` writer; `POST /frontend/v1/visitor-links` for humans; hooks into
the design batch derive (`InstanceLink`) and the content scaler (openers) when those writers exist.

**Resolution:** `visitor_resolve` handler; `reverse_ip` resolver (ipregistry client, Snitcher
client behind the same interface); `identity_graph` resolver (Leadpipe Platforms webhook/API
client, Bullseye as the alternate); AI Ark `reverse-lookup` client (leaf code, `arv2/ai_ark_client.py`
gains one method); contact bind/create with review marker; claim + activity writers; cost ledger;
the reveal cap.

**Compliance:** jurisdiction + consent + GPC gate; lawful-basis record; DSAR selector extension;
retention job; privacy-policy text (US/EU); per-workspace reveal switch (default off).

**Read side:** activity kind, two field keys on existing chips, the Head-of-ABM read tool.

**Flags in `.env.example`, same commit as the code:** `CLUE_WVI_ENABLED=false`,
`CLUE_WVI_PERSON_LEVEL=off` (`off | us_only`), `CLUE_WVI_REVERSE_IP_PROVIDER=ipregistry`,
`CLUE_WVI_IDENTITY_GRAPH_PROVIDER=none`, `CLUE_WVI_MONTHLY_REVEAL_CAP=500`,
`CLUE_WVI_RAW_IP_RETENTION_DAYS=30`; keys `CLUE_IPREGISTRY_API_KEY`, `CLUE_LEADPIPE_API_KEY` in
`Secrets`.

**Measurement before selling:** the known-visitor test (§2.3) on cluehq.ai and one pilot site;
the numbers go on the client's cost/coverage surface as "estimated identification coverage".

---

## 7. Build order and cost

| Phase | What | Vendor spend | Exit gate |
|---|---|---|---|
| **V0** (rungs 0+1 on Clue pages) | migration; page-server collector; token minting + "Copy tracked link"; `visitor_resolve` with link + ipregistry; claims + activity | ipregistry free tier (20k) | Open an account's ABM page from a tracked link in an email → the contact's Activity shows the visit with channel and pages within 60 s; an untracked visit from a corporate IP shows as the account |
| **V1** (client sites) | `clue.js`, `/v1/collect`, pixel key, consent/GPC/jurisdiction gate, privacy text, retention | same | Pixel on cluehq.ai; EU visits produce company-level only; GPC visitor produces nothing; DSAR erases a contact's visits |
| **V2** (rung 2) | identity-graph resolver via Leadpipe Platforms POC (or RB2B Pro webhooks as a 30-day bridge), AI Ark reverse lookup, contact bind/review, reveal cap | POC free for 3 months (Leadpipe `[FETCHED]`) or RB2B Pro $149/mo | Known-visitor test: published coverage and accuracy numbers; zero person-level rows outside the US; every reveal has a ledger row |
| **V3** | intent weighting, Head-of-ABM tool, CRM outbox, Matched-Audience export | — | agent answers "who from our target list visited this week" from the tool |

**Running cost per 10,000 monthly visits** (a typical mid-market B2B site):

| Item | Assumption | Monthly |
|---|---|---|
| Reverse IP | 10,000 lookups at $0.29–0.67/1k | **$3–7** |
| Person-level, ungated (the RB2B way) | 35% US × 30% match = 1,050 IDs × $0.10–0.30 | $105–315 |
| Person-level, **gated to target accounts / intent pages** | ~20% of the above pass the gate = 210 IDs × $0.10–0.30 | **$21–63** |
| AI Ark reverse lookups | 210 × 0.5 credit | **≈$1** |
| Compare: RB2B Pro / Pro+ | 600 credits, no gating | $149 / $199 |
| Compare: Vector Plus | 1,000 IDs | $399 |

With the gate, a workspace's person-level bill is tens of dollars, and it is spent only on people
the project can act on. Under the credit model in `pricing-strategy/07-credit-system-design.md`
the natural unit is "one identified person at a target account = 1 credit ($1 list)" with
company-level and tracked-link identification free — the same shape RB2B uses (1 credit per unique
identified visitor per 30 days), priced above our ~$0.10–0.30 COGS.

---

## 8. Open decisions (founder rulings)

| # | Decision | Recommendation |
|---|---|---|
| W1 | Rung 2 provider for the POC | Leadpipe Platforms tier: published price, `linkedin_url` in the payload, 3-month POC, US-only/EU-company-level built in. RB2B Pro webhooks as a bridge if the POC stalls. Bullseye white-label as the alternate. Going straight to a wholesaler (BIGDBM / Audience Acuity) only after the POC proves demand. |
| W2 | Person-level in the EU/UK | Never. Company-level + tracked links only. |
| W3 | Token in URL vs cookie-only for Clue links | Token in URL (`?cl=`), opaque, stripped on render; never an email or an entity id. |
| W4 | Widen the published-page CSP for a script, or server-side only | Server-side only for Clue pages; the script exists for client sites. |
| W5 | Ownership | Migration, collector, handler, wiring = Aryan; spec, `clue.js`, privacy text, provider clients as leaf code, frontend chips = Shashank via agents; recipes/prompts unaffected. |
| W6 | Default posture | `CLUE_WVI_PERSON_LEVEL=off` per workspace; a client turns it on after accepting the privacy-policy text. |
| W7 | Pricing unit | 1 credit per identified person at a target account; company-level and tracked-link identification free. |
| W8 | A daily system-authored Head-of-ABM digest turn | Yes, as its own ruling; until then the read tool. |
| W9 | Where V0 sits in the ARV2 roadmap | After D3 (the `account_activity_event` table and `/frontend/v1` payloads exist) and independent of Track R. |

---

## Appendix A — what exists in the repo today (verified)

- **No tracking of any kind:** no pixel, script, beacon, UTM capture, visitor/session/page-view
  model, reverse-IP lookup or cookie/consent code. `utm_` appears only as a prefix to strip from
  crawled URLs (`subsystems/research/clue_research/official_site/url_policy.py:34`). Vendors are
  named only in `head-of-abm-agent-refinements/*.md` research notes.
- **Publishing:** `POST /documents/{id}/web/publish` → `/w/{ws}/p/{slug}`; batch derive per
  account; `design_account.account_entity_id` nullable FK; `design_web_publish` has no
  account/contact column. No CDN, custom domain or hosting layer (Part IV item 5,
  `docs/specs/design-integration-master-plan.md:225`).
- **Inbound webhook pattern:** `ExaWebhookIngestor` (HMAC, 300 s tolerance, enqueue-only, 202).
- **Sales-outcome ingest contract exists but has no HTTP route:** `review/disposition.py`
  (`DispositionOrigin.WEBHOOK`, `MEETING_BOOKED`, `CLOSED_WON`…), `disposition_store.py:346, 425`.
- **Signals:** no `signal` field class and no `account.signal.*` namespace; `FieldDef.signal_class`
  links proxies to narratives; `account.scoring.intent` is computed in Pass A.
- **Contact strong keys:** `linkedin_url`, `verified_email`, workspace-scoped partial-unique
  indexes; no email-hash key. `linkedin_url` is an entity column, not a claim.
- **Person lookup by email:** none in any resolver; Sumble had LinkedIn → email only. AI Ark
  reverse lookup (email → profile) is documented but not yet a client method.
- **CRM:** read-only `CRMConnector` duck-type, no concrete connector, not wired.
- **Fleet:** closed `FleetTaskKind` enum; `enqueue_task` with `(kind, work_id, dedup_key)` dedup;
  `run_event` subject kinds closed to `project_run`/`design_run`.
- **Frontend:** Activity tab with a 3-value kind enum over `research_subject_activity`; contact
  "Recent signals" chip over `CONTACT_SIGNAL_FIELD_KEYS`; Artifacts tab hard-coded
  `capability_unavailable`.
- **Agent:** `AGENT_TURN` human-submitted only; no notification/inbox surface.

## Appendix B — source list

RB2B: <https://support.rb2b.com/en/articles/8891294-what-is-rb2b-and-how-does-it-work> ·
<https://support.rb2b.com/en/articles/11155068-contact-level-identification> ·
<https://support.rb2b.com/en/articles/9910029-rb2b-cookie-information> ·
<https://support.rb2b.com/en/articles/8795972-updating-your-privacy-policy> ·
<https://www.rb2b.com/built-for-clay> · <https://pipeline.zoominfo.com/sales/rb2b-pricing> ·
<https://www.factors.ai/blog/identify-anonymous-website-visitor>
Vector: <https://www.vector.co/blog/how-to-identify-website-visitors> · <https://coldiq.com/tools/vector> ·
<https://builtfast.dev/docs/vector-pro/webhooks/webhook-overview/>
Warmly: <https://help.warmly.ai/articles/3568026273-contact-level-identification> ·
<https://www.warmly.ai/p/article/what-is-visitor-intelligence-how-to-identify-website-visitors>
Userled: <https://intercom.help/userled/en/articles/9515210-identity-layer> ·
<https://intercom.help/userled/en/articles/9984428-identify-email-recipients> ·
<https://intercom.help/userled/en/articles/9477665-6sense>
Ploy: <https://ploy.ai/features/visitor-identification> · <https://ploy.ai/faq> · <https://ploy.ai/pricing>
Apollo: <https://www.apollo.io/product/website-visitor-identification> ·
<https://knowledge.apollo.io/hc/en-us/articles/20544185285389-Track-Website-Visitors-to-Prioritize-Prospects> ·
<https://docs.apollo.io/docs/enrich-people-data>
Leadpipe: <https://www.leadpipe.com/pricing/> ·
<https://www.leadpipe.com/blog/visitor-identification-api-complete-developer-guide/> ·
<https://leadpipe.com/blog/webhook-payload-reference-every-visitor-data-field/> ·
<https://www.leadpipe.com/blog/is-website-visitor-identification-legal/>
Bullseye: <https://www.bullseye.so/>
Graphs: <https://bigdbm.com/identity-data-statistics/> · <https://audienceacuity.com/> ·
<https://www.geysera.com/blog/visitor-identification/website-visitor-identification-for-ecommerce-how-identity-graphs-and-server-side-tracking-actually-work-2026>
Reverse IP: <https://ipregistry.co/pricing/> · <https://ipapi.is/pricing.html> · <https://ipinfo.io/pricing> ·
<https://docs.snitcher.com/powered-by-snitcher/ip2company/quickstart> · <https://www.snitcher.com/ip-to-company-api/>
B2B enrichment: <https://docs.ai-ark.com/reference/people-reverse-lookup.md> ·
<https://docs.peopledatalabs.com/docs/reference-person-enrichment-api>
Accuracy: <https://www.barchart.com/story/news/993090/gartner-auditor-tests-rb2b-leadpipe-warmly-clearbit-6sense-leadfeeder-accuracy-results-vary-widely>
Legal: <https://www.sidley.com/en/insights/newsupdates/2026/09/californias-sb-690-clears-the-legislature-what-it-means-for-cipa-website-tracking-claims> ·
<https://www.alston.com/en/insights/publications/2026/07/california-sb-690-reform-cipa-claims> ·
<https://cookie-script.com/privacy-laws/cipa-lawsuit-tracker> · <https://www.cookieyes.com/blog/cpra-exemptions/> ·
<https://mojoauth.com/blog/anonymous-website-visitor-identification-gdpr-ccpa-tools>
Cookies: <https://www.consenteo.com/knowledge-hub/cookies/third_party_cookies_2026_after_google_reversal> ·
<https://www.onetrust.com/blog/google-drops-plans-for-third-party-cookie-choice-prompt-in-chrome/>
