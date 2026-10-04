# WVI-4 / 01: Ploy and Userled teardown: how they identify anonymous visitors at person level

Date: 2026-10-03. Method: read-only fetches of public pages, public JS, public registries and public
package code. No accounts, no forms, no credentials. Tags: `[FETCHED]` = I read the page or file
myself; `[SNIPPET]` = search-result snippet only; `[INFERRED]` = my inference from the evidence.
Raw captures are in the session scratchpad (not committed).

---

## 0. Bottom line

1. **Ploy's person-level identification is rented from RB2B (legal entity GetEmails LLC, d/b/a
   Retention.com and RB2B).** This is not inference: Ploy's own Vanta trust center lists, among its
   25 subprocessors, **"GetEmails · Identify Your Website Visitors and Boost Your Leads · US ·
   rb2b.com"** `[FETCHED]` <https://trust.ploy.ai/subprocessors>. Ploy's marketing never names the
   vendor; the subprocessor list does.
2. Ploy does **not** run the RB2B pixel on customer sites. Every Ploy-hosted site runs only Ploy's
   own first-party engine (`/_p/v1.js`, "ploy-analytics" v1.0.28), which beacons to the same origin
   (`/_ploy/ingest`). No third-party identity script, no ID sync, no fingerprinting code. So the
   resolution is **server-side from the request IP (and probably user agent)**, which is exactly
   what RB2B's API Partner Program sells: `POST /ip_to_hem`, `POST /hem_to_business_profile`,
   `POST /hem_to_best_linkedin` on `api.rb2b.com/api/v1`, and Retention.com's "Business Profile from
   IP" (IP mandatory, UA optional) `[FETCHED]`. The API choice is `[INFERRED]` from the absence of
   any client-side resolver; the supplier is confirmed.
3. Ploy's email/contact tooling (Contact Tools) is a separate rented layer: subprocessors
   **Waterfall (waterfall.io) "Marketing Data Provider"** and **Wiza (wiza.co) "Marketing Data
   Provider"** `[FETCHED]`.
4. **The underlying graph is RB2B/Retention's**, and RB2B's own browser script shows how that graph
   is fed: it calls three identity sources in parallel in the visitor's browser: **LiveIntent**
   (`b-code.liadm.com/lc2.js`, publisherId 72731), **TowerData** (`alocdn.com/c/vn3d8u2u/a/xtarget/p.json`,
   `credentials: include`, returns `md5_email`) and **Delivr.ai** (`a.usbrowserspeed.com/cs?pid=…`,
   a cookie-sync), plus an IP geofence via `pro.ip-api.com` `[FETCHED]` (deobfuscated from RB2B's
   own site script). The same TowerData container id and the Delivr.ai sync endpoint fire on large
   consumer publisher sites (screenrant.com, howtogeek.com, heavy.com, townhall.com, snopes.com,
   tvtropes.org) per DuckDuckGo Tracker Radar `[FETCHED]`. That is the "opted-in partner network".
5. **Userled has no person graph of its own and does not pretend to.** Contact-level comes from
   tracked links (`?ul_e={{email}}`), CRM/HubSpot cookie stitching, and, for truly anonymous US
   visitors, a **Vector** partnership ("1000 free contact reveals per month", US-only geofence).
   Company-level is Clearbit Reveal, 6sense, or Demandbase `[FETCHED]` (Userled help centre).
   Vector's own pixel in turn embeds **LiveIntent's LiveConnect hub** (white-labelled through
   `api.vector.co/pixel/phoenix/*`, with `idx.liadm.com/nonId`) and the same **Delivr.ai**
   cookie-sync domain `[FETCHED]`.

Net: neither Ploy nor Userled owns the person-identity graph. Both rent it from the same small set
of consumer-identity suppliers (LiveIntent, TowerData, Delivr.ai behind RB2B/Retention and Vector).

---

## 1. Ploy: what it says publicly

### 1.1 Feature page `[FETCHED]` <https://ploy.ai/features/visitor-identification>

Verbatim (page body and its FAQPage JSON-LD):

- Step 01 "Resolve": "Anonymous IPs resolved to company in milliseconds — no SDK install, no
  JavaScript fingerprinting."
- Step 02 "Enrich": "Firmographics, headcount, funding stage, and likely contacts with LinkedIn
  profiles attached to every account."
- Step 03 "Score intent": "Page paths, dwell time, scroll depth, and repeat visits feed an intent
  score so hot accounts surface first."
- "Ploy resolves visitors only when they're U.S.-located and present in an opted-in partner network
  where consumers explicitly consented to third-party marketing. Every identified contact carries a
  verifiable consent record — CAN-SPAM compliant, SOC 2 Type II, Spamhaus-aligned, CCPA opt-out
  honored."
- FAQ "Where does the identity data come from?": "From an opted-in partner network of websites where
  consumers have agreed to share their information for third-party marketing. When one of those
  consented individuals visits your site, the underlying identity graph resolves the visit to a
  person and company. No data is purchased from scraped sources, no LinkedIn fingerprinting is
  performed, and no SDK is installed on visitor devices to capture identifying information."
- FAQ compliance: "CAN-SPAM: All identity data comes from an opted-in partner network. Verifiable
  consent records — timestamp, source, and IP — are maintained for every contact, aligned with
  Spamhaus best practices to avoid spam traps." / "GDPR: Ploy does not collect or share net-new
  anonymous visitor data in GDPR-regulated regions such as the EU and UK. If your brand already has
  an existing relationship with a user … that identity can be resolved, but only when the
  relationship already exists."
- FAQ geography: "identities are only resolved when the visitor is located in the United States,
  enforced through geofencing on the resolution endpoint."
- FAQ DNT/GPC: "When a visitor declines cookies on your banner — or signals Do Not Track / Global
  Privacy Control — Ploy suppresses identification for that visitor. The signal is honored at the
  resolution layer … Your cookie banner is the gate."
- FAQ opt-out: "Identified consumers can exercise their CCPA rights … through a public opt-out form
  maintained by the data provider. Once a consumer opts out, their identity is removed from the
  network and will not be resolved on any downstream site, including yours."
- FAQ "Can Ploy identify people or only companies?": "Ploy can resolve eligible U.S. traffic to a
  company and likely contacts when the visitor matches its opted-in partner network."
- Customer duties: "(2) Update your website privacy policy with language disclosing that you use a
  third-party identity graph to recognize business visitors; Ploy provides recommended language you
  can paste in."

### 1.2 Docs `[FETCHED]`

- <https://docs.ploy.ai/visitor-identification>: fields per identified visitor are **Name ("when
  available"), Company, Job title, LinkedIn, Visit count, Pages viewed**. No email field. "Identifying
  companies and people uses visitor-enrichment credits from your organization." Privacy section:
  **"Visitor identification is privacy-conscious and does not use cookies. No additional consent
  banners are required."**
- <https://docs.ploy.ai/security>: "Ploy's visitor identification does not use cookies and does not
  require consent banners."
- <https://docs.ploy.ai/credits>: "Visitor enrichment has its own monthly allowance … Free plans do
  not include enrichment. Each enrichment counts as one credit." Pricing page: visitor enrichment
  50/mo on Starter ($50), 1,000/mo on Pro ($300), custom on Enterprise `[FETCHED]`
  <https://ploy.ai/pricing>.
- <https://docs.ploy.ai/contact-tools>: email lookup, phone lookup, verification ("deliverable,
  risky, undeliverable, or unknown"), person/company enrichment, prospect search, job changes. "Do I
  need to connect a data provider? No." Getting an email for an identified visitor is a separate
  Contact Tools step ("Contact Tools turns those signals into verified, actionable contact details",
  <https://docs.ploy.ai/audience>).
- <https://docs.ploy.ai/cli/reference>: `ploy site visitors --type person|company --sort
  lastSeen|visits --json` "lists identified people and companies, not necessarily all site traffic".
- <https://docs.ploy.ai/integrations>: ClickHouse "Query large event and signals datasets directly
  for high-volume analytics behind visitor identification".

**Contradiction worth noting:** the marketing page says "Your cookie banner is the gate"; the docs
say identification "does not use cookies" and "No additional consent banners are required". The
engine does set a 1-year first-party `ploy_anon_id` cookie (section 2). `[FETCHED]`

### 1.3 Legal pages `[FETCHED]`

- Privacy policy (Ploy, Inc., "Last Updated: April 15, 2026") <https://ploy.ai/privacy>: "To power
  certain features, we may process firmographic data, intent signals, technographic information,
  and publicly available business information about target accounts and contacts sourced from
  third-party data providers." Ploy says it is a **processor** for "Customer End-User Information"
  including "IP addresses and device or browser identifiers" and "Pixel tag metadata, cookie
  identifiers". It says "We do not sell personal information." The cookie list names GA4/GTM,
  Google Ads, PostHog, Meta Pixel, HubSpot, Mailchimp only; **it omits Snitcher, Mesh/Avina,
  LinkedIn, TikTok, Snap and X tags that ploy.ai itself loads** (section 2.3). On DNT: "There is no
  widely adopted standard for responding to DNT signals, so we do not respond to them separately"
  (this is about ploy.ai as a site, not the product claim). No vendor named.
- Terms <https://ploy.ai/terms-of-service>: "If you require a Data Processing Agreement (“DPA”) …
  contact us". "Ploy does not obtain marketing consents on your behalf and does not verify the
  opt-in status of your contacts." No identity vendor named.
- **Trust center (Vanta, titled "runploy.com Trust Center")** <https://trust.ploy.ai/subprocessors>,
  rendered in a headless browser. All 25 subprocessors: Google Cloud, Cloudflare, OpenAI, Anthropic,
  Vercel, Composio, Code.storage, Blaxel, ClickHouse, Data for SEO, Daytona, Exa AI Search, Google
  Workspace, Merge, Meta, PartnerStack, PostHog, Pylon, Resend, Slack, Stripe, **Waterfall
  ("Marketing Data Provider", waterfall.io)**, **Wiza ("Marketing Data Provider", wiza.co)**, Zapier,
  **GetEmails ("Identify Your Website Visitors and Boost Your Leads", US, rb2b.com)**. Snitcher is
  **not** a subprocessor, so Snitcher on ploy.ai is Ploy's own marketing tool, not the product.

### 1.4 Data-broker registries

- **California (CPPA)** `[FETCHED]` <https://cppa.ca.gov/data_broker_registry/> (`registry.csv`,
  `registry2025.csv`, `complete-reg-data-brokers.csv`): **Ploy is not registered.** Registered:
  **"GETEMAILS LLC | DBA: RETENTION.COM; RB2B | www.retention.com; www.rb2b.com"**, Austin TX,
  reporting **9,482** opt-out-of-sale requests (all complied) and 13 deletion requests in the
  reported year; "GetEmails, LLC" also appears in the older complete list. Also registered:
  GetVector, Inc. (Vector), Warmly, Inc., Audience Acuity LLC, BIGDBM (PublicNSA LLC), J2 Martech
  (FullContact), Versium, 5x5 US, Opensend, ID5, 33Across, LiveRamp, Tapad, Cross Pixel Media,
  Visual Visitor. Delivr.ai Inc appears in the 2025 file. Leadpipe, AudienceLab, Userled, Snitcher:
  not found in the files I searched.
- RB2B says it is "officially registered as a data broker in California, Texas, Vermont, and
  Oregon" `[FETCHED]` <https://support.rb2b.com/en/articles/10580390-data-broker-registration>.
- Texas (Appian portal), Vermont (search form) and Oregon (report downloads are form POSTs): **not
  checked**, because each requires submitting a search form.

### 1.5 People, launch, reviews

- Founder Bryant Chou (co-founder/CTO of Webflow 2013–2025, earlier Vungle CTO); YC S26; $27M seed
  led by First Round and YC announced 17–18 June 2026 `[FETCHED]`
  <https://www.ycombinator.com/companies/ploy>, <https://www.prnewswire.com/news-releases/ploy-raises-27m-to-turn-your-companys-website-into-your-hardest-working-employee-302803231.html>.
  Neither page says anything about identification or data partners.
- Careers page and Ashby postings: no data-stack disclosure `[FETCHED]` <https://ploy.ai/careers>.
- G2/Capterra/Reddit match-rate reviews: **not found** (the session's web-search budget was
  exhausted before this pass; not read).

---

## 2. Ploy: what the code actually does

### 2.1 The engine on every Ploy-hosted site `[FETCHED]` <https://ploy.ai/_p/v1.js>

Ploy-hosted customer sites checked: leadbay.ai, volca.ai, raspire.com, tntgrowth.com (all load the
same engine via an inline `data-ploy-analytics` stub). Findings from the 53 KB bundle:

- Library `"ploy-analytics"`, version `"1.0.28"`, built on the open-source `analytics` npm package
  (error links to `lytics.dev`).
- Endpoint: **`/_ploy/ingest`** (same origin, hosted mode, sent with `navigator.sendBeacon`), or in
  "external" mode `${scriptDir}v1/b/{page|identify|track}` for non-hosted sites.
- Identity storage: first-party cookie **`ploy_anon_id`**, `Max-Age=31536000` (1 year), set on the
  registrable domain, mirrored to localStorage; `ploy_session` (30-minute window,
  `R7=1800000`), `ploy_pending_events` retry queue.
- Events: `session.started/heartbeat (15 s)/ended`, `page.scroll_depth_reached` at 25/50/75/90,
  `cta.clicked`, `link.outbound_clicked`, `form.started`, `form.submitted` (form id/name/action only;
  **no field values, no email capture**), `site_search.performed`, `experiment.exposed`.
- Context sent: URL, path, title, referrer, userAgent, locale, viewport and screen size, timezone.
- Third-party integrations it can load: only `ga4`, `meta`, `google_ads` (the `U8` map), with a
  consent object `{analytics, ads}` mapped to Google Consent Mode and `fbq('consent')`.
- **Absent:** any identity-graph domain (no rlcdn/LiveRamp, ID5, 33across, liadm/LiveIntent,
  alocdn/TowerData, usbrowserspeed/Delivr, reb2b, vector.co, leadpipe), canvas/WebGL fingerprinting,
  `doNotTrack`/`globalPrivacyControl` reads, iframes or pixel images.
- Response headers on Ploy sites: Cloudflare in front (`server: cloudflare`, `cf-ray`), cached HTML.

**Reading `[INFERRED]`:** the only identifiers Ploy's server ever sees for an anonymous visitor are
the connecting IP (Cloudflare gives it `CF-Connecting-IP` and `CF-IPCountry` for free, which is the
natural "geofencing on the resolution endpoint"), the user agent, and its own first-party anon id.
Person resolution therefore must be a server-to-server call from `/_ploy/ingest` (or a batch job)
to the supplier with the IP (+UA). The `ploy_anon_id` only lets Ploy de-duplicate repeat visits and
spend one enrichment credit per visitor.

### 2.2 The matching supplier API (RB2B / Retention.com) `[FETCHED]`

- Retention.com Enrichment API Suite <https://retention.com/apis>:
  - "Deanonymize Website Visitors — From IP & user agent. IP address (mandatory). User agent
    (optional, improves accuracy). You get MD5 and SHA256 hashed emails (HEM), with confidence
    scores. Up to 3 ranked matches."
  - "Business Profile from IP — … Resolve an anonymous visitor straight to a professional identity:
    LinkedIn profile, name, title, seniority, company, and work email in one call."
  - Also MAID from IP, Business Profile from Email/LinkedIn, Profile from Name & Company.
- RB2B API Partner Program, read from RB2B's own MCP server package `@rb2b/rb2b-apis-mcp@1.1.7`
  (`dist/api.js`, `dist/server.js`) via jsDelivr: base `https://api.rb2b.com/api/v1`, header
  `Api-Key`; `POST /ip_to_company {ip_address}` (1 credit), **`POST /ip_to_hem {ip_address}`**
  ("Returns a ranked list of MD5 and SHA256 hashes with confidence scores. Cost: 1 credit"),
  `POST /ip_to_maid`, **`POST /hem_to_business_profile {md5}`** ("employer and job title
  information. Cost: 2 credits"), **`POST /hem_to_best_linkedin {md5}`** (1 credit),
  `/linkedin_to_personal_email`, `/linkedin_to_mobile_phone`, `/linkedin_to_hashed_emails`. Rate
  limit "50 requests/second per endpoint". README: "Get your first 100 credits for just $9."
- RB2B OEM Partner Program <https://support.rb2b.com/en/articles/12579426-rb2b-s-oem-partner-program>:
  "Martech, sales tech, CRM, vertical SaaS, or data companies"; "Monthly platform fee is $5,000,
  plus $0.10 per resolution beyond 50,000 free monthly resolutions" (WebFetch summary). The OEM path
  is a nested pixel with `window.rb2bConfig = { options: { customer_id: … } }`
  (<https://support.rb2b.com/en/articles/12881892-installing-your-rb2b-oem-tracking-script>).
- rb2b.com FAQ: "Reseller (tech vendors building RB2B into their product): We can power site visitor
  resolution within your app. Contact robb@rb2b.com" and "White Label: We do NOT have a white label
  option."

**Fit with Ploy:** Ploy outputs name, company, title, LinkedIn and no email = exactly
`ip_to_hem` → `hem_to_business_profile` + `hem_to_best_linkedin`. Ploy's words "opted-in partner
network", "verifiable consent", "Spamhaus", "geofencing", "public opt-out form maintained by the
data provider" mirror RB2B/Retention's own: "Through our partner network, we ensure that every
contact on your list has opted in", "backed by verifiable consent", "We supply all the necessary
information, such as the when and where of the opt-in, at your request", Spamhaus, "We've
introduced a geofencing feature to ensure our services only activate for users in the United
States" `[FETCHED]` <https://support.rb2b.com/en/articles/8922650-staying-compliant-and-effective-a-retention-com-guide-to-email-regulations>,
and the opt-out at `https://app.retention.com/optout` / `https://app.retention.com/ccpa_details/`
`[FETCHED]` <https://www.rb2b.com>, <https://retention.com/privacy-policy>. Whether Ploy uses the
self-serve API (IP-only) or the $5,000/month OEM contract is **not determinable** from public data;
the absence of the RB2B pixel on Ploy sites points to the API `[INFERRED]`.

**Precision consequence `[INFERRED]`:** an IP-only lookup cannot use the browser-side LiveIntent /
TowerData / Delivr hashes that RB2B's own pixel collects (2.4), so Ploy gets the subset of RB2B's
graph that is keyed by recently observed IP. That is the lower-precision mode (shared office and
household IPs, CGNAT, VPN). Ploy hedges this in copy: "likely contacts".

### 2.3 What ploy.ai (Ploy's own marketing site) loads `[FETCHED]`

Not the product, but revealing:

- **Snitcher Radar** (`cdn.snitcher.com`, `apiEndpoint: radar.snitcher.com`, `profileId:
  "roH5P5S6IYz"`, `namespace: "ployTwo"`), only for visitors without the `ploy.has_session=1` cookie.
- **Mesh SDK** (`@mesh-interactive/mesh-sdk@latest`, maintainers at withmesh.com and **avina.io**),
  attributes `{useFingerprint: false, track:{session: true, forms: true}}`.
- LinkedIn Insight, Meta, TikTok, Snap, X, Google Ads, GA4, PostHog, GTM.

The Mesh/Avina SDK is a **live example of a reseller waterfall over rented graphs** `[FETCHED]`
(<https://cdn.jsdelivr.net/npm/@mesh-interactive/mesh-sdk@latest/dist/umd/index.js>, v0.4.1): it
calls `api.withmesh.com/init-sdk`, gets `rb2bEnabled`, `vectorEnabled`, `fullContactKey`,
`primaryResolverTimeoutMs` (35,000), injects **RB2B's OEM script with a hard-coded key
`46DJ4HGQ5J61`** and `window.rb2bConfig = {options:{customer_id: JSON({contact_id__mesh_web,
workspace_id})}}`, polls `contacts/{visitorId}/resolution-status`, and on timeout "waterfalling to
V…" injects `cdn.vector.co/pixel.js`. It skips the ipify IP lookup when the browser timezone starts
with "Europe", reads an `m_email` URL parameter, and can use FingerprintJS Pro when `useFingerprint`
is true. Log strings: "Attempting R resolution...", "R resolution timed out, waterfalling to V...".

### 2.4 How the RB2B graph is fed (RB2B's own script) `[FETCHED]`

RB2B's script for its own site (`ddwl4m2hdecbv.cloudfront.net/b/1VN080HQL06J/1VN080HQL06J.js.gz`,
gzip, last modified 26 June 2026), deobfuscated base64 constants:

| Constant | Decoded | What it does |
|---|---|---|
| `aHR0cHM6Ly9wcm8uaXAtYXBpLmNvbS…` | `https://pro.ip-api.com/json?key=…&fields=proxy,hosting,isp,lat,long,zip,city,region,status,country,timezone,regionName,countryCode` | client-side geofence: `countryCode === 'US'` and proxy/hosting check, cached in `_reb2bgeo` |
| `aHR0cHM6Ly9iLWNvZGUubGlhZG0uY29tL2xjMi5qcw==` | `https://b-code.liadm.com/lc2.js` | **LiveIntent LiveConnect**, `identityResolutionConfig: {publisherId: 72731}`; result `md5` stored in `_reb2bli` |
| `aHR0cHM6Ly9hbG9jZG4uY29tL2Mvdm4zZDh1MnUvYS94dGFyZ2V0L3AuanNvbg==` | `https://alocdn.com/c/vn3d8u2u/a/xtarget/p.json` | **TowerData** (DDG Tracker Radar owner "TowerData, Inc."), `fetch(…, {credentials:'include'})`, reads `md5_email`, stored ~30 days (resolver named `td`) |
| `aHR0cHM6Ly9hLnVzYnJvd3NlcnNwZWVkLmNvbS9jcz9waWQ9…` | `https://a.usbrowserspeed.com/cs?pid=3f6274bd…` | **Delivr.ai** cookie sync (Ghostery TrackerDB maps `usbrowserspeed.com` to Delivr.ai, formerly CDP Resolution LLC); cookie `fxf_md5` / `_reb2bfxf` `[INFERRED mapping of resolver name]` |
| `…execute-api.us-west-2.amazonaws.com/b2b` | API gateway | collector receiving the md5s plus `_fbp`, `_fbc`, `hubspotutk`, `utm_source=hs_email` clicks, page, referrer, session |

`collect()` runs `fxf`, `td`, `li` with `Promise.allSettled`, then posts whatever hashes came back.
Cookies: `_reb2buid`, `_reb2bsessionID`, `_reb2bgeo`, `_reb2bli`, `_reb2bsha`, `_reb2bfxf`,
`_reb2beid`, `_reb2bec`, `_reb2btd`, `_reb2butk`, `_reb2bref`. Bot filter on UA list (gptbot,
ahrefsbot, python-requests, headless, webdriver…). Config `geoFence: true`.

RB2B's own description: "we will identify visitors to your website who are known and have been
previously identified through our expansive, fully-permissioned publisher network. We use a
combination of 1st and 3rd party cookies, device IDs, and IP addresses to track and identify people
across our network. We also identify your site visitors through Demandbase's proprietary Reverse-IP
Lookup network." `[FETCHED]` <https://www.rb2b.com>.

**Where the "publisher network" lives `[FETCHED]` (DuckDuckGo Tracker Radar, US crawl):** the exact
rule `alocdn.com/c/vn3d8u2u/a/xtarget/p.json` (RB2B's TowerData container) is seen on heavy.com,
screenrant.com, townhall.com, howtogeek.com, electricbikeexplorer.com; `usbrowserspeed.com/cs` on
screenrant.com, howtogeek.com, tvtropes.org, snopes.com, dailycaller.com, globalnews.ca, polywood.com
(prevalence 0.7%, 1,048 sites in the crawl). `[INFERRED]` These are the consumer sites where a
login/newsletter/checkout binds an email hash to a browser and to an IP; RB2B's visitor scripts and
Retention.com's IP-keyed APIs then look that binding up.

---

## 3. Ploy: answers to the five questions

1. **Exact technical claims:** section 1.1–1.2. The verifiable ones are "no SDK", "no JavaScript
   fingerprinting", "US only", "per-enrichment credits". The engine confirms the first two.
2. **Legal pages / registries:** the trust-center subprocessor list names GetEmails/RB2B, Waterfall,
   Wiza. Ploy is not a registered California data broker; GetEmails LLC (Retention.com; RB2B) is.
   Ploy's privacy policy names no identity vendor and calls Ploy a processor.
3. **Script analysis:** first-party only; ingest at `/_ploy/ingest`; `ploy_anon_id` 1-year cookie; no
   third-party ID syncs. Supply chain revealed by the subprocessor list, not the script.
4. **People/interviews/jobs/reviews:** nothing public names the data stack. Reviews not read.
5. **White-label?** Yes in substance: Ploy's person layer is RB2B/Retention behind Ploy's UI and
   credits. Shared phrasing is near-verbatim with RB2B/Retention's compliance copy. No shared script
   domain, because Ploy calls the supplier server-side `[INFERRED]`.

---

## 4. Userled (brief)

All `[FETCHED]` from the Userled help centre <https://intercom.help/userled/en/>.

- **Identity layer** (<https://intercom.help/userled/en/articles/9515210-identity-layer>):
  "De-anonymisation strategies are ranked based on accuracy: Contact-level tracking links …
  Account-level tracking links … IP reveal: We enriched the visitor's IP to match them to an
  account." Company-level partners: "Clearbit Reveal" and "6Sense"; Demandbase also listed.
  "HubSpot Tracking Pixel: Userled automatically integrates with the HubSpot tracking pixel when
  both HubSpot and Userled are loaded onto the same page."
- **Email-click identification** (<https://intercom.help/userled/en/articles/9984428-identify-email-recipients>):
  append `?ul_e={{email}}` (Outreach, HubSpot `{{contact.email}}`, Salesforce
  `{{{Recipient.Email}}}`, Apollo, Salesloft; Amplemarket uses `?ko_e={{email}}`). "often leads to a
  boost of 20~30% net new identities".
- **Person-level for anonymous visitors = Vector** (<https://intercom.help/userled/en/articles/11203911-vector>):
  "Our partnership offers you 1000 free contact reveals per month"; "Vector surfaces US-based
  contacts only using geo-fencing to comply with GDPR"; "Vector sends uncovered visitor updates
  approximately one hour after the visitor visits your website"; CSP needed: `connect-src
  https://*.vector.co https://*.usbrowserspeed.com https://*.ip-api.com`. Webhook payload includes
  `contactName`, `contactEmail`, `contactTitle`, `contactLinkedinUrl`, `country`, `location`.
- **Fingerprinting** (<https://intercom.help/userled/en/articles/9496422-cookieless-fingerprinting>):
  a first-party visitor id used to link one browser across the customer's own domains; "The visitor
  ID is scoped to each Userled workspace, not the internet at large"
  (<https://intercom.help/userled/en/articles/10948476-privacy-and-compliance>).
- **Cookies** (<https://intercom.help/userled/en/articles/10948721-cookies-user-consent>):
  `userled_fingerprint_id` 7 d, `userled_user_id` 1 y, `userled_session_id` 5 min,
  `userled_consent` 1 y, `_vid_t` 1 y. Consent API: `window.Userled("revokeConsent")`,
  `requireConsent: true`; default implementation "will automatically grant consent".
- **SDK domains** (<https://intercom.help/userled/en/articles/9122732-content-security-policy-csp-directives>):
  `*.userledclient.io`, `*.userled.io`, `wss://*.userled.io`.
- Registries: Userled not found in the California registry.

**Vector's pixel** `[FETCHED]` <https://cdn.vector.co/pixel.js> (231 KB): embeds LiveIntent's
LiveConnect hub (`window.liQHub`, `hubVersion "v3.17.0"`) proxied through
`https://api.vector.co/pixel/phoenix/{rp,rpr,idex,sync-container}` with
`nonIdEndpointUrl: "https://idx.liadm.com/nonId"`, and injects
`https://a.usbrowserspeed.com/cs?pid=b910e4cf…&puid=<pixel>|<visitor>` (Delivr.ai). Consent is
recorded via `PUT api.vector.co/pixel/{pixel}/visitor/{id}/consent`. GetVector, Inc. is a registered
California data broker with opt-out at <https://www.vector.co/opt-out>.

---

## 5. What is proprietary vs rented

| Layer | Ploy | Userled |
|---|---|---|
| Visitor capture (first-party script, events, sessions) | **own** (`ploy-analytics`, `/_ploy/ingest`) | **own** (Userled SDK, fingerprint id) |
| Hosting/edge that sees every IP | **own** (Ploy hosts the site behind Cloudflare) | n/a |
| Company from IP | not named in subprocessors; RB2B `ip_to_company` (Demandbase-backed) is available under the same contract `[INFERRED]` | rented: Clearbit Reveal, 6sense, Demandbase |
| Person from anonymous visit | **rented: GetEmails/RB2B (Retention.com)** | **rented: Vector** (LiveIntent + Delivr.ai underneath) |
| Person from known traffic | first-party `identify()`; "existing relationship" exception | **own**: `ul_e` tracked links, 1:1 microsite links, HubSpot `hubspotutk` stitching |
| Email/phone for a person | rented: Waterfall, Wiza (Contact Tools) | via CRM / Vector payload |
| Intent scoring, CRM sync, agent actions | own | own |
| Consent, geofence, opt-out | geofence is trivial (Cloudflare country); opt-out is the supplier's form | delegated to customer CMP and Vector |

---

## 6. Implications for building it in-house (for Clue)

1. **"In-house" for these companies means the capture, scoring and workflow, not the graph.** The
   person graph in every case traces to the same handful of consumer-identity suppliers
   (LiveIntent, TowerData, Delivr.ai, behind RB2B/Retention and Vector). Building the graph itself
   means building what those suppliers have: an email↔browser↔IP binding harvested on large
   consumer publisher sites with login/newsletter traffic, plus a registered data-broker posture.
   Clue has no publisher footprint, so a from-scratch person graph is not buildable in the near term
   `[INFERRED]`.
2. **The Ploy architecture is copyable cheaply:** first-party script → own ingest → server-side
   `ip(+ua) → hem → business profile/LinkedIn` call to a supplier → own scoring. With RB2B's API at
   ~$0.09/credit entry (100 for $9) and 1 + 2 + 1 credits for IP→HEM→profile→LinkedIn, a resolved
   person costs roughly $0.36 at entry pricing, less at volume; or $5,000/month OEM with 50,000
   resolutions included. Retention.com sells the same as "Business Profile from IP".
3. **Precision is the supplier's, and IP-only is the weak mode.** Ploy hedges with "likely
   contacts". Clue's WVI-2 rules (employer must equal the IP holder or a residential ISP, freshness,
   corroboration) are what turn a rented guess into a claim Clue can defend.
4. **Copy Userled's honest layer first:** per-contact tracked links and 1:1 pages already give
   deterministic person identity with no graph; Clue knows which account each page was built for.
5. **Legal posture travels with the supplier:** Ploy is not a registered data broker and leans on
   GetEmails' registration and opt-out form; its own docs contradict its own banner guidance. If Clue
   rents, it should name the supplier as a subprocessor (Ploy does), pass through
   `app.retention.com/optout`-style opt-outs, and keep EU/UK to company level.

## 7. Not found / not checked

- No public statement by Ploy or its founder naming RB2B; the only naming is the trust-center
  subprocessor row.
- Which RB2B product Ploy uses (self-serve API vs OEM vs Retention.com contract): not public.
- Ploy's own match rate: not published.
- Texas, Vermont, Oregon registry entries: not checked (form submission required).
- G2/Capterra/Reddit reviews of Ploy: not read (search budget exhausted).
- Owner of `usbrowserspeed.com` per WHOIS is privacy-proxied; the Delivr.ai attribution rests on
  Ghostery TrackerDB (`db/patterns/delivrai.eno`).
