# WVI-4 / 02: Vendor landscape and identity supply chain for anonymous-visitor identification

**Date:** 2026-10-03. **Method:** read-only public web research (vendor docs, privacy policies, help centres,
pricing pages, the California CPPA data broker registry CSVs, FTC and CPPA press releases). No sign-ups, no
forms, no credentials.

**Evidence labels.** `[FETCHED]` = the page was retrieved in this session and the quote comes from it (quotes
were extracted by a page-reading model, so wording is near-verbatim; treat exact punctuation as best effort).
`[SNIPPET]` = text from a search-engine result summary, page not retrieved (or retrieval failed); lower
confidence. `[INFERRED]` = my reasoning from the evidence, not a vendor statement. `[PRIOR]` = already
established in `docs/specs/WVI-website-visitor-identification.md` or `WVI-2-...md` in this repo.

**Limits of this pass (read before relying on a negative).**
- The session hit its web-search budget part way through; remaining work used direct page fetches only. Some
  vendors (Qualified, Signals, Primis, Smartlead, 6sense internals) got thin coverage and are marked "not found".
- The CPPA registry CSVs are large and the page reader truncated them. A positive match (a row quoted verbatim)
  is reliable. A **negative** ("not in the registry") is **not** reliable: e.g. ZoomInfo appeared in the 2024 CSV
  read but not in the 2025 CSV read, which is almost certainly truncation. Vermont, Texas and Oregon registries
  could not be read (Texas returned HTTP 403; the others are search UIs). Vendor self-claims of registration are
  quoted as claims.

---

## 0. Bottom line

1. "Millions of companies do this" is true only at **company level** (reverse IP). **Person-level**
   identification of a visitor who never clicked, logged in or filled a form is done by a few dozen branded
   tools, which sit on a **small number of identity graphs** (roughly 6 to 10 upstream suppliers).
2. Every person-level vendor that discloses a mechanism describes the same core trick: **a cookie, device
   fingerprint, MAID or household IP was earlier bound to a (hashed) email somewhere else**, on a "publisher
   network", "partner" site, co-registration flow, email newsletter or ad auction. When that browser later lands
   on your site, the vendor's script looks the identifier up in a **pre-matched table**. AudienceLab says it
   plainest: "we have a pre-matched table of all the cookies, which is all the browser sessions you might have
   attached to HEMS" `[FETCHED]`.
3. The binding is acquired by: (a) co-registration and "partner marketing" opt-ins on consumer sites,
   (b) data co-ops where members contribute hashed emails, device data and **email engagement**, (c) email-open
   pixels in newsletters (LiveIntent model) and in the vendors' own customers' sends, (d) the ad **bidstream**,
   (e) household-IP-to-email scoring. All of it is **US-only** in practice, consent is "implied" or
   "partner marketing" grade, and the vendors push compliance onto the site owner.
4. **RB2B is a DBA of GetEmails LLC, the same legal entity as Retention.com** (CPPA 2025 registry row, quoted
   below `[FETCHED]`). RB2B's privacy policy calls its data a "contributor database" `[FETCHED]`. Its company-level
   fallback is rented from Demandbase `[FETCHED]`. Factors.ai's person-level feature is RB2B `[FETCHED]`;
   Common Room's is Vector `[FETCHED]`.
5. A new entrant can build company-level (IP-to-company), first-party identify-events, a cross-customer
   cookie co-op over its own customers' sites, and a waterfall over vendors. It **cannot** build the US
   consumer cookie/MAID/IP-to-email binding at useful coverage without either (i) years of publisher /
   co-registration supply deals or (ii) buying it. It must rent that layer.

---

## 1. Landscape table

Legend: **Co** = company-level, **Per** = person-level. "Source" = the person-level data source as stated or
evidenced. Rates are vendor claims unless marked.

| Vendor | Level | Geography (person) | Claimed rate | Person-level data source (evidence) | Reseller / upstream relationship | Price signal |
|---|---|---|---|---|---|---|
| **RB2B** | Per + Co | US only | 30-40% person + 30-40% company (=70-80%) `[FETCHED]` | "publisher network" cookies, device IDs, IP; "contributor database"; same entity as Retention.com `[FETCHED]` | Owns graph (GetEmails LLC). Company-level = **Demandbase** `[FETCHED]`. Powers **Factors.ai** person-level `[FETCHED]` | Starter $79/300 credits; Pro $149/600; ~$0.10/credit at volume `[PRIOR]` |
| **Retention.com** (GetEmails LLC) | Per (B2C) | US | 16-35% `[SNIPPET]` | "Data compilers and consumer data resellers, informational and retail websites"; tracks "opening emails or browsing websites" `[FETCHED]` | **Upstream wholesaler**: sells "Deanonymize Website Visitors", "MAID from IP", "Email Activity" APIs `[FETCHED]` | Not published |
| **Leadpipe** | Per + Co | US only (EU/UK -> company) | B2B 30-40%+, B2C 30-50%+ `[FETCHED]` | "5.3B emails and 444M+ profiles from opted-in publishers, retail sites, apps, and data networks" `[FETCHED]` | **Upstream + white-label**: Agency (unlimited clients, custom pixel), Platforms (API, 3-month POC) `[FETCHED]` | $147/500 ($0.294) to $1,879/20k ($0.094) per ID `[FETCHED]` |
| **AudienceLab** | Per (B2C+B2B) | US | not stated; "95 percent accuracy" `[SNIPPET]` | 40 data sources; cookie->HEM pre-matched table; IP and MAID ties; "financial institutions, credit bureaus, telecom companies" for phone verification `[FETCHED]` | **Upstream + white-label**: whole platform and pixel white-labelable; "gray-labeled" pixel domain `[FETCHED]`/`[SNIPPET]` | Not published |
| **Vector** (vector.co) | Per + Co | US only, "geofence" | ~35% contact-level `[FETCHED]` | "proprietary network of publishers who [...] share their 1st party data; namely, hashed emails (HEMs) and associated Device Fingerprint information" `[FETCHED]` | **Powers Common Room** person-level `[FETCHED]` | $36k / $60k / $96k per year `[FETCHED]` |
| **Common Room** | Per + Co | US (enhanced) | "up to 50%" US `[FETCHED]` | Vector (fingerprinting + publisher network) `[FETCHED]` | Reseller of **Vector**; absorbed Koala customers `[SNIPPET]` | Included on all plans `[FETCHED]` |
| **Warmly** | Per + Co | US person | ~65% co / ~15% person `[FETCHED]` | "extensive partner network of publishers and data providers"; 20+ providers incl. "2 other leading website de-anonymization providers" `[FETCHED]` | **Aggregator / waterfall** of unnamed vendors; CA registry row + "registered data broker in Texas" `[FETCHED]` | Not fetched |
| **Customers.ai** | Per (mostly B2C) | US `[INFERRED]` | "2-18x higher True Match Rate" (relative) `[FETCHED]` | "hashed email addresses), associated IP addresses, and event timestamps that we receive from business partners under contractual data sharing arrangements" `[FETCHED]` | Upstream not named; registers "to the extent" it is a broker (CA/TX/OR/VT) `[FETCHED]` | Priced on Klaviyo profile count `[FETCHED]` |
| **Opensend** | Per (B2C) | US | "73% USA shoppers match rate" `[FETCHED]` | "thousands of sites with millions of registered users who consent to partner marketing"; "we see the traffic for 100k+ US-based sites" `[FETCHED]` | Own network (co-reg + customer-site co-op `[INFERRED]`); CA registry row `[FETCHED]` | $1 trial `[FETCHED]` |
| **Identity Matrix** | Per + Co | US only | 50-70% of US traffic `[SNIPPET]` | "device IDs, hashed emails, and MAIDs"; "partner-marketing opt-ins" `[SNIPPET]` | Upstream not disclosed | $149/mo, 1,500 visitors, 75 Reveal credits `[SNIPPET]` |
| **5x5 Data Co-Op** | Per + Co | US-centric | "5% [...] or you might resolve 70%" `[FETCHED]` | Members contribute "email engagement, digital interactions, behavioral signals, and offline datasets"; pay less by sharing "encrypted emails and device data" `[FETCHED]` | **Upstream co-op**; partners incl. RocketReach `[FETCHED]` | Not published |
| **Delivr.ai** | Per + Co | US | "50%+ of US web traffic" `[FETCHED]` | "publisher co-ops, the bid-stream, and content consumption"; "licensed supply-side data plus first-party pixel events" `[FETCHED]` | **Upstream + white-label**: "Embed the full stack via API, white-labeled, non-compete"; LiveRamp partner listing `[SNIPPET]` | Pay per record, $0 minimum `[FETCHED]` |
| **BIGDBM** | Per (graph/API) | US | HEM match 80%+ `[SNIPPET]` | "We're not a reseller. We're the source." Sources not disclosed `[FETCHED]` | **Upstream** (WeVi visitor ID pixel + APIs) `[SNIPPET]` | Not published |
| **Datazapp** | Per (B2C) | US | not stated | IP matched to "300 million consumers"; filters to "static wifi sources in single family homes" `[SNIPPET]` | Upstream-ish (reverse IP append) | Not fetched |
| **Kwanzoo** | Per | US only | up to 40% `[FETCHED]` | "identity grid of 110MM+ cookies and device IDs" `[FETCHED]`; multi-vendor per its blog `[FETCHED]` | **Aggregator** of 3+ unnamed vendors `[FETCHED]` | Not published |
| **Happierleads** | Per + Co | claims 174+ countries | 25-35% person `[SNIPPET]` | "permissioned publisher network" `[SNIPPET]`; "matches visitor IP addresses against their 175M+ contact database" `[FETCHED]` | **White-label** reseller program, "50-200% on top of wholesale pricing" `[FETCHED]`; upstream not disclosed | from $99/mo `[FETCHED]` |
| **Apollo** (Website Visitors / Inbound) | Co free; Per add-on | US person | not stated | Matches against Apollo's "240M+ contacts"; person-graph source not disclosed `[FETCHED]` | Not found | Inbound add-on ~$119-149/mo `[SNIPPET]` |
| **Instantly** (Website Visitors) | Per + Co | US only | 22-35% (third-party test) `[SNIPPET]` | "does not come from your existing campaigns or lists" `[FETCHED]`; source not disclosed | Not found | 3 credits per resolved profile `[FETCHED]` |
| **ZoomInfo WebSights / Buyer ID** | Co + Per | US (Buyer ID) | not stated | "IP-lookup and identity graph tracking" against "500M verified contacts" `[FETCHED]` | Own | Enterprise `[SNIPPET]` |
| **HubSpot Breeze Intelligence** (ex Clearbit Reveal) | Co only | global | 20-40% co `[SNIPPET]` | n/a (reverse IP) | Clearbit is a provider inside Clay and Unify waterfalls `[FETCHED]`/`[SNIPPET]` | HubSpot credits |
| **6sense** | Co | global | varies | n/a | Called by Apify actor `[FETCHED]`; in Unify waterfall `[SNIPPET]` | $25k+/yr `[FETCHED]` (Leadpipe table) |
| **Demandbase** | Co (+cookie co-op) | global | not stated | "3.7 billion IP addresses"; "hundreds of millions of active cookies" `[FETCHED]` | **Upstream company-level for RB2B** and Clay `[FETCHED]` | Enterprise |
| **Dealfront / Leadfeeder** | Co | global | up to 45% co `[FETCHED]` | n/a; "IP-to-company database every day" `[FETCHED]` | Dealfront is a Clay provider `[FETCHED]` | Free tier + tiers `[FETCHED]` |
| **Snitcher** | Co (+ first-party identify) | global | 20-35% `[SNIPPET]` | n/a; persons only via email provided in forms/links `[FETCHED]` | Clay/Unify provider `[FETCHED]`/`[SNIPPET]` | from $49/mo `[SNIPPET]` |
| **Albacross** | Co | EU focus | "1.7X higher" `[FETCHED]` | n/a | Not found | Not on page |
| **Lead Forensics** | Co | UK/global | 1.4B IPs `[SNIPPET]` | n/a; contacts appended, not identified `[SNIPPET]` | Not found | Not published |
| **Leadinfo** (+ Visitor Queue) | Co | 195 countries | ~30% `[FETCHED]` | n/a | visitorqueue.com **301-redirects to leadinfo.com** `[FETCHED]` | EUR 49-599/mo `[FETCHED]` |
| **Lusha** | Co | global | not stated | n/a; "company-level data only" `[SNIPPET]` | Not found | n/a |
| **Seamless.AI** | none | n/a | n/a | "does not include a website visitor identification tool" `[SNIPPET]` | n/a | n/a |
| **Clay** | Co (Web Intent) | global | n/a | Waterfall: "Snitcher, Demandbase, Dealfront, Warmly, Clearbit, PDL, Versium"; "company-level denanonymization only" `[FETCHED]` | **Aggregator**; person-level via RB2B/Leadpipe integrations `[PRIOR]` | 1 action + provider credits per IP `[FETCHED]` |
| **Unify** | Co + first-party Per | n/a | 75%+ co `[SNIPPET]` | Person only after "form submission, login, or email interaction" `[FETCHED]` | Aggregator (6sense, Clearbit, Demandbase, Snitcher) `[SNIPPET]` | n/a |
| **Default** | Co | n/a | n/a | "passes your site's visitor pings through to verified partners" `[SNIPPET]` | Aggregator, partners unnamed | n/a |
| **Factors.ai** | Co + Per add-on | US person | up to 75% co `[SNIPPET]` | **RB2B** `[FETCHED]` | Reseller of RB2B (person) + waterfall (company) | add-on, credits on success `[FETCHED]` |
| **Koala** | was Co | n/a | n/a | n/a | Acqui-hired by Cursor July 2025, shut down Sept 2025 `[SNIPPET]` | defunct |
| **Apify** | Co (one actor found) | n/a | n/a | Actor `nabeelbaghoor/website-visitor-identification-api` "integrates with 6sense"; needs your 6sense token `[FETCHED]` | Thin wrapper over 6sense | $15 / 1,000 company results `[FETCHED]` |
| **Qualified, Signals (getsignals), Primis, Trigify, Smartlead** | see §2.9 | | | **Not found** | | |

---

## 2. Vendor evidence

### 2.1 RB2B and Retention.com (one company)

- **Same legal entity.** CPPA 2025 registry row `[FETCHED]` (https://cppa.ca.gov/data_broker_registry/registry2025.csv):
  `GetEmails LLC,"Retention.com, RB2B",https://www.retention.com,support@retention.com,,"1401 Lavaca St, #298",Austin,TX,78701,USA,...`
  The same row reports 632 opt-out requests received and complied with in 2023. The 2024 CSV read also showed
  "GetEmails LLC | Retention.com" `[FETCHED]`.
- RB2B privacy policy `[FETCHED]` https://www.rb2b.com/privacy-policy : legal entity "GetEmails, LLC d/b/a R! B2B";
  "For data subjects whose personal information is included in R! B2B's contributor database, this Privacy Policy
  is intended to provide you with information on who R! B2B is, how you can opt-out of our database, and the
  potential outcomes of remaining in our database." Also: "We and third-party vendors may use first-party cookies
  and third-party cookies together, and other automated technologies."
- RB2B mechanism `[FETCHED]` https://support.rb2b.com/en/articles/11155068-contact-level-identification :
  "Using first- and third-party cookies, device identifiers, and IP address analysis, RB2B cross-references visitor
  data across a large network." Enrichment "using verified professional sources like LinkedIn and other
  career-related databases."
- RB2B cookie doc `[FETCHED]` https://support.rb2b.com/en/articles/9910029-rb2b-cookie-information : ten cookies,
  e.g. `_reb2buid` (360 days), `_reb2btd` "Identity resolution", `_reb2bli` "Session-to-identity linking";
  "All RB2B cookies are first-party cookies, set under your website's own domain". `[INFERRED]` The help
  centre contradicts itself (contact-level page says "first- and third-party cookies"); the cross-site join is
  therefore done by the script's network calls to RB2B's servers, not by cookies stored on your domain.
- What the RB2B script collects `[FETCHED]` https://support.rb2b.com/en/articles/14827019-profile-data-faqs :
  "IP address, user agent, MD5s, current page URL, referring page URL, and the timestamp of their visit." Without
  "network cookies on the visitor's device" from its publisher network, identification is "significantly reduced".
  `[INFERRED]` "MD5s" = hashed emails read in the browser; this is the HEM that keys the graph.
- Data acquisition `[FETCHED]` https://support.rb2b.com/en/articles/8795524-how-does-rb2b-collect-or-use-our-data :
  "Our technology is designed with a unique capability to recognize anonymous web traffic by aligning it with
  profiles from our extensive partner network."
- Demandbase `[FETCHED]` https://www.rb2b.com/rb2b-demandbase : "RB2B has formed a deep partnership with Demandbase
  to bring you the powerful combination of RB2B's Person-Level Identity and Demandbase's industry-leading
  Company-Level ID." "Our customers are seeing 30-40% Person-Level ID rates, and an additional 30-40% at the
  Company-Level." "RB2B's Person-Level ID remains US-only."
- Retention.com privacy policy `[FETCHED]` https://www.retention.com/privacy-policy/ (entity "GetEmails, LLC dba
  Retention.com"):
  - Sources: "Data compilers and consumer data resellers, informational and retail websites ("Commercial Source
    Categories")".
  - "Notwithstanding anything else in this policy, we and/or our partners may use pixels and pixel tags, and place,
    read or use cookies that collect information from your device and/or Internet browser."
  - "We and/or our partners use cookies, pixels and other tracking technology to associate certain
    Internet-related information about you, such as your Internet Protocol address and what Web browser you are
    using, with certain of your online behaviors, such as opening emails or browsing websites."
  - "By using our Service, you agree that us and our third-party partners may store, sell, port, combine with other
    data, monetize, utilize and otherwise use [...] the personally identifiable information they discover and/or
    identify as described above."
  - It answers "Yes" to having "sold" identifiers and browsing data; recipients include "Advertising networks and
    media platforms, political campaigns, internet service providers."
- Retention.com founder, Practical Ecommerce `[FETCHED]` https://www.practicalecommerce.com/retention-com-founder-on-email-laundering :
  "We partnered with publisher networks for the identity info, which we capture and transfer to our customers."
  "We're the middleman." "You could think about it as email laundering."
- Retention.com as wholesaler `[FETCHED]` https://retention.com/apis : endpoints including "Deanonymize Website
  Visitors", "Email Resolution", "Business Profile from IP", "MAID from Email", "MAID from IP", "Email Activity",
  "Mobile Phone from LinkedIn"; delivery as "Real-time APIs to bulk flat files" (https://retention.com/about-r).
  Its Resolution Tag honours "TCF, GPC and your own consent state by default" `[FETCHED]` https://www.retention.com/how-it-works.
- Reseller: Factors.ai `[FETCHED]` https://help.factors.ai/en/articles/14885484-visitor-identity-enrichment :
  "RB2B identifies a subset of US-based B2B visitors whose digital identity can be resolved." Fields carry an
  "RB2B" prefix.

### 2.2 Leadpipe

- Graph claim `[FETCHED]` https://www.leadpipe.com/product/identification/ : "The largest independent identity graph
  on earth: 5.3B emails and 444M+ profiles from opted-in publishers, retail sites, apps, and data networks."
  B2B "30-40%+ on US traffic"; EU/UK "defaults to company-level data only".
- Registration claim `[FETCHED]` https://www.leadpipe.com/pricing/ : "registered as a data broker in California,
  Texas, Vermont, and Oregon." "Person-level identification is US-only by design." (Not confirmed in the
  truncated CPPA reads; see Limits.)
- Entity `[FETCHED]` https://www.leadpipe.com/privacy-policy/ : "Leadpipe LLC, a limited liability company formed in
  the State of Wyoming". Policy does not say whether customer-pixel data feeds the graph for other customers;
  "A list of key subprocessors is available to Customers on request."
- A search summary claimed Leadpipe sources via "direct publisher partnerships (such as Bloomberg, CNN &
  Affiliates)" `[SNIPPET]`; I could not find this on any fetched Leadpipe page. **Unverified; do not repeat.**
- Pricing `[FETCHED]`: Pro $147/500 IDs ($0.294) ... Pro 20K $1,879 ($0.094); Agency 10K $1,279 to 200K $5,500,
  "Unlimited client accounts", "Custom tracking pixel"; Platforms: "Build with Leadpipe identity data. Try a
  3-month POC with high limits."
- Leadpipe's own claim about the market `[FETCHED]` https://www.leadpipe.com/blog/visitor-identification-api-complete-developer-guide/ :
  "most competitors don't build their own identity graphs, they resell the same third-party data sources".

### 2.3 AudienceLab

- FAQ `[FETCHED]` https://audiencelab.io/faqs/ : "We have our own audience graph that we've built across three
  years. We have 40 data sets or 40 data sources that contribute to this audience graph." "we take that cookie and
  we have a pre-matched table of all the cookies, which is all the browser sessions you might have attached to
  HEMS, which are hashed emails". "we have this tied to IPs. We have this tied to maids." "we work with financial
  institutions, credit bureaus, telecom companies where we verify the phone number". On consent: "every time you
  go into a browser, you are essentially giving consent and giving them your cookie"; "We do not provide proof of
  opt-in". White label: "The whole platform can be white-labeled as your own software."
- XactMatch press release (Audience Lab Corp, Aug 2023) `[FETCHED]`
  https://finance.yahoo.com/news/adtech-platform-audiencelab-launches-household-050000760.html : it "measures the
  household IP usage of over 280m Americans, then ties this to a separate user database of emails"; "we are able
  to know exactly how many emails are tied to which IP addresses".
- Privacy policy `[FETCHED]` https://audiencelab.io/privacy-policy : sources include "websites and apps that collect
  the information, public sources, and other data"; "we license the Information in various ways to our customers";
  opt-out at audiencelab.io/optout. No registration statement found.
- `[SNIPPET]` (search summary of the FAQ): sources include "online co-registration networks and partner websites,
  publicly available databases like real estate and financial records".

### 2.4 Vector and Common Room

- Vector security page `[FETCHED]` https://www.vector.co/security : "Vector has a proprietary network of publishers
  who properly disclose, collect, and share their 1st party data; namely, hashed emails (HEMs) and associated
  Device Fingerprint information." "When a visitor lands on your site, we only look at Device Fingerprints to
  determine if an identity can be found in our pre-existing compliantly-sourced identity graph." "You do not become
  a contributing member of the data co-op." It "geofence[s] our technology to jurisdictions with implied opt-in";
  "Vector will only fire in the United States"; "we don't collect or purchase any non-US data."
- Vector blog `[FETCHED]` https://www.vector.co/blog/enhanced-visitor-identity-is-here : "Reputable solution providers
  ensure compliance by using legitimate data sources like opt-in networks or bidstream data."
- Common Room `[FETCHED]` https://www.commonroom.io/blog/enhanced-website-visitor-identification/ : partner is Vector,
  "a combination of digital fingerprinting technology and a proprietary publisher network"; "Vector boasts a 35%
  contact-level match rate for US-based web traffic"; "comes out of the box for every Common Room customer on every
  plan level at no extra cost." Common Room's own non-Vector person ID is first-party: forms, login, and "Tracking
  links in emails" `[FETCHED]` https://www.commonroom.io/docs/signals/website-visitor-tracking/faqs/.

### 2.5 Warmly

- Privacy policy `[FETCHED]` https://www.warmly.ai/p/privacy-policy : "the technology used by our Services collects an
  online identifier (such as an IP address) from you. We will then try to match that online identifier to personal
  information records held by our data providers (e.g., name, job title, contact information, and LinkedIn
  profile)." "We are a registered data broker in Texas."
- CPPA 2025 row `[FETCHED]`: `Warmly, Inc,,https://www.warmly.ai/,vendors@warmly.ai,...` with "collects consumers'
  precise geolocation: Yes".
- Help centre `[FETCHED]` https://help.warmly.ai/articles/3568026273-contact-level-identification : it
  "cross-references it with an extensive partner network of publishers and data providers"; for emails it
  "waterfall[s] through five different data providers".
- Blog `[FETCHED]` https://www.warmly.ai/p/blog/visitor-identification-software-top-11 : "multiple data providers
  (20+), including 2 other leading website de-anonymization providers". Names not disclosed (**not found**).

### 2.6 Customers.ai, Opensend, Identity Matrix (B2C-origin "partner marketing" tier)

- Customers.ai privacy `[FETCHED]` https://customers.ai/privacy-policy : receives "Pseudonymized identifiers (such as
  hashed email addresses), associated IP addresses, and event timestamps that we receive from business partners
  under contractual data sharing arrangements"; "we may combine information collected from different sources,
  including pseudonymized identifiers received from partners, to recognize a person or device across websites and
  over time"; "Some of the disclosures described above may constitute a 'sale' of personal information"; registers
  "To the extent Customers.ai qualifies as a 'data broker'".
- Opensend homepage `[FETCHED]` https://www.opensend.com/ : "We comply with all laws by partnering with thousands of
  sites with millions of registered users who consent to partner marketing." "In our network, we see the traffic
  for 100k+ US-based sites". "180M US Shoppers in Network". CPPA 2025 row present (Opensend Inc, Las Vegas NV)
  `[FETCHED]`.
- Identity Matrix `[SNIPPET]` (identitymatrix.ai pages; direct fetches returned 404): "device IDs, hashed emails, and
  MAIDs"; "data points are captured or compared to databases of partner-marketing opt-ins"; "every lead has opted
  in to partner marketing and they only de-anonymize US traffic".
- `[INFERRED]` "Consent to partner marketing" is co-registration language: a consumer signs up on a sweepstakes,
  coupon, survey or content site and ticks (or is pre-ticked into) sharing with "marketing partners". That sign-up
  binds email to the browser cookie / device on that site; the binding is then pooled.

### 2.7 Upstream graph and co-op suppliers (not end-user tools)

- **5x5 Data Co-Op** `[FETCHED]` https://5x5data.com/faqs/ : "Members contribute diverse first-party data assets,
  including email engagement, digital interactions, behavioral signals, and offline datasets. These contributions
  enhance the co-op's identity graph and benefit all members." Visitor resolution page `[FETCHED]`
  https://5x5data.com/solutions/website-visitor-resolution/ : members "pay less by sharing anonymized signals like
  encrypted emails and device data"; "You could resolve 5% of website traffic or you might resolve 70%".
- **Delivr.ai** `[FETCHED]` https://www.delivr.ai/api : "~1 trillion daily impressions across publisher co-ops, the
  bid-stream, and content consumption"; "Embed the full stack via API, white-labeled, non-compete". `[FETCHED]`
  https://www.delivr.ai/resources/delivr-vs-rb2b : "licensed supply-side data plus first-party pixel events".
  `[FETCHED]` https://docs.delivr.ai/docs/how-identity-resolution-works : "The graph stores anonymized mappings
  (cookie ID to hashed email)"; "Individual customer site data is never shared."
- **BIGDBM** `[FETCHED]` https://bigdbm.com/about/ : "We're not a reseller. We're the source." `[SNIPPET]`: WeVi
  website visitor product, "200M+ identity nodes".
- **LiveIntent** (email-newsletter identity) `[FETCHED]` https://www.liveintent.com/services-privacy-policy/ : collects
  "whether an email sent by one of our business partners has been opened, or whether a link has been clicked",
  plus "IP address, unique digital identifiers (such as mobile advertising IDs)" and "an encrypted version of your
  email address"; recipients include "Data aggregators that provide information, including identifiers and
  inferences, about individuals" and "companies who perform cookie matching services, real-time bidding
  exchanges". No direct link to any named visitor-ID vendor found (**not found**).
- Registry rows found in the truncated CSV reads (positive matches only) `[FETCHED]`: People Data Labs, LiveRamp,
  Throtle, Intent IQ, Audience Acuity, Stirista (DBAs incl. "Ameribase Digital", "List Builder 360"), Fideo
  Intelligence ("formerly FullContact"), Versium, Clay Labs ("Purchases a small number of datasets each year"),
  Epsilon, Acxiom, Verisk Marketing Solutions, Taboola; 2024 read also: ZoomInfo, Apollo ("Zenleads Inc."), Lusha,
  6Sense, Demandbase. These are the identity/marketing-data brokers that sit one level above the visitor tools.
  Which of them supply which visitor tool is **not disclosed** anywhere I could read.

### 2.8 Company-level and aggregator vendors

- Demandbase `[FETCHED]` https://www.demandbase.com/blog/your-target-accounts-are-working-from-home-demandbase-has-the-answer/ :
  "around 3.7 billion IP addresses that are mapped to a company"; "hundreds of millions of active cookies that
  supplement the identification"; the system "first looks for our cookie ID. If present, we identify the company
  from this cookie alone"; "if the same IP address is used by the same Microsoft cookie, the IP address would
  eventually be officially mapped to Microsoft.com". This is a **cross-customer cookie co-op at company level**.
- Leadfeeder/Dealfront `[FETCHED]` https://www.leadfeeder.com/web-visitors/ : "Individual visitors are not shown by
  default." IP-to-company built from "our proprietary data [...] millions of external signals and public IP
  registration databases."
- Snitcher `[FETCHED]` https://docs.snitcher.com/product/how-snitcher-works : "a proprietary database of business IP
  ranges"; people only when "visitors provide their email address" via forms, logins, tracked links, API.
- ZoomInfo `[FETCHED]` https://pipeline.zoominfo.com/marketing/websight-buyer-id-website-visitor-tracking : Buyer ID
  "matching IP address data against a continuously verified B2B database"; "currently limited to identifying U.S.
  website visitors". 210M IP-to-org pairings `[SNIPPET]`.
- Apollo `[FETCHED]` https://www.apollo.io/product/website-visitor-identification : company "available globally";
  contact-level "Currently available for US-based visitors"; requires the Inbound add-on.
- Instantly `[FETCHED]` https://help.instantly.ai/en/articles/9502519-getting-started-with-the-website-visitors-feature :
  "Visitor tracking is currently only available for website traffic from the US"; "3 Credits = 1 Resolved Visitor
  Profile"; "The visitor information does not come from your existing campaigns or lists".
- Clay `[FETCHED]` https://www.clay.com/blog/web-intent : providers "Snitcher," "Demandbase," "Dealfront," "Warmly,"
  "Clearbit," "PDL," and "Versium"; "currently supports company-level denanonymization only." Docs `[FETCHED]`
  https://university.clay.com/docs/website-tracking : "Waterfall stops after the first provider match, while Best
  Match tests all providers and can cost 5-10 times more."
- Unify `[FETCHED]` https://www.unifygtm.com/explore/website-visitor-identification-how-it-works : "A durable
  first-party identifier such as a form submission, login, or email-linked event can connect activity to a known
  person."
- Happierleads `[FETCHED]` https://happierleads.com/gdpr-compliant-website-visitor-tracking : "matches visitor IP
  addresses against their 175M+ contact database", person-level in "174+ countries". `[INFERRED]` Person-level from
  IP alone outside the US, with no consumer graph, is most likely "company from IP, then a guessed contact at that
  company"; treat as low precision.
- Apify `[FETCHED]` https://apify.com/nabeelbaghoor/website-visitor-identification-api : "This Actor integrates with
  6sense's company identification service", needs "An API token from your 6sense account", "$15.00 / 1,000 company
  results". A Store search for "website visitor identification" returned no person-level visitor-ID actor; the
  person-data actors returned are LinkedIn/contact scrapers `[FETCHED]` https://apify.com/store?search=website%20visitor%20identification.

### 2.9 Not found

- **Qualified** (Piper): no evidence of native person-level identification of anonymous visitors; data partners not
  found. **Signals (getsignals.ai)**: described as ABM/conversational, data source not found. **Primis**: no visitor
  identification product found under that name. **Trigify**: a social/LinkedIn signal tool, not website visitor ID
  `[SNIPPET]`. **Smartlead**: no native website-visitor feature found; it integrates with Leadpipe et al.
  `[SNIPPET]`. **Seamless.AI**: no visitor ID `[SNIPPET]`. **Lusha**: company-level Website Visits API `[SNIPPET]`.
- Named suppliers behind Warmly, Customers.ai, Identity Matrix, Apollo Inbound, Instantly, Happierleads: **not found**.

---

## 3. The wholesale layer (upstream suppliers)

From the evidence, the person-level market resolves to these graph owners. Everything else is a brand on top.

| Upstream | What it sells | How it says it gets the browser-to-email binding |
|---|---|---|
| **GetEmails LLC** (Retention.com / RB2B) | Own SaaS (RB2B, Retention) + enrichment APIs incl. "Deanonymize Website Visitors", "MAID from IP", "Email Activity" | "partnered with publisher networks"; "Data compilers and consumer data resellers, informational and retail websites"; cookies/pixels associating IP and browser with "opening emails or browsing websites" `[FETCHED]` |
| **Leadpipe LLC** | Own SaaS + white-label Agency + Platforms API | "opted-in publishers, retail sites, apps, and data networks" `[FETCHED]` |
| **AudienceLab** (Audience Lab Corp) | White-label DaaS + SuperPixel | 40 sources; cookie->HEM pre-matched table; household IP scoring; co-registration `[FETCHED]`/`[SNIPPET]` |
| **Vector** | Own SaaS, embedded in Common Room | publisher network sharing "HEMs and associated Device Fingerprint" `[FETCHED]` |
| **5x5 Data Co-Op** | Co-op graph + visitor resolution tag | members contribute "email engagement", "encrypted emails and device data" `[FETCHED]` |
| **Delivr.ai** | Pay-per-record API, white-label | "publisher co-ops, the bid-stream" `[FETCHED]` |
| **BIGDBM**, **Datazapp** | Identity graph / reverse-IP append APIs | not disclosed; Datazapp keys on residential static IPs `[SNIPPET]` |
| Below these | LiveIntent (newsletter opens), LiveRamp, Throtle, Intent IQ, Audience Acuity, Stirista, Versium, PDL, Epsilon, Acxiom | Registered data brokers; email-open, co-registration, compiled consumer files `[FETCHED]` registry rows; supply relationships to visitor tools **not disclosed** |

Company-level upstream: **Demandbase** (supplies RB2B, Clay), **6sense** (Apify actor, Unify), **Clearbit/HubSpot**,
**Snitcher**, **Dealfront**, **PDL**, **Versium** (Clay waterfall).

---

## 4. Supply chain diagram (in words)

```
TIER 0  Consumer touchpoints where an email meets a browser/device
        co-registration & sweepstakes/coupon sites ("consent to partner marketing")
        publisher newsletters (email-open pixels: hashed email + IP + cookie/MAID)
        retail/e-commerce sites running identity pixels (Retention, Opensend, Customers.ai customers)
        ad auctions (bidstream: IP, MAID, user agent, page)
        credit bureau / telecom / compiled consumer files (phone, address verification)
            |
            v
TIER 1  Identity brokers and co-ops (registered data brokers)
        LiveIntent, LiveRamp, Throtle, Intent IQ, Audience Acuity, Stirista, Versium, PDL, Epsilon, Acxiom,
        5x5 Co-Op, BIGDBM, Datazapp   [who sells to whom below this line: not disclosed]
            |
            v
TIER 2  Visitor-identity graph owners (cookie/fingerprint/IP -> HEM -> person)
        GetEmails LLC (Retention.com + RB2B), Leadpipe, AudienceLab, Vector, Delivr.ai, Opensend,
        Customers.ai (partner HEM+IP feeds), ZoomInfo (Buyer ID), Apollo (Inbound, source undisclosed)
            |                                    |
            | white-label / API / embed          | direct SaaS
            v                                    v
TIER 3  Resellers and aggregators
        Common Room  <- Vector
        Factors.ai   <- RB2B
        RB2B         <- Demandbase (company-level fallback)
        Leadpipe Agency/Platforms white-labels; AudienceLab white-label sub-accounts;
        Happierleads white-label ("50-200% on top of wholesale"); Delivr "white-labeled, non-compete"
        Warmly (20+ providers incl. 2 de-anon vendors, unnamed); Kwanzoo (3+ unnamed);
        Clay, Unify, Default (company-level waterfalls over Snitcher/Demandbase/Dealfront/Clearbit/6sense/PDL/Versium)
            |
            v
TIER 4  End customers' websites (each pixel also feeds TIER 2 where terms allow: Opensend "we see the
        traffic for 100k+ US-based sites"; Demandbase cookie network; 5x5 members contribute)
```

---

## 5. Distinct mechanisms in use

| # | Mechanism | Who (evidence) | Level |
|---|---|---|---|
| M1 | Reverse IP to company from an IP-range database | Leadfeeder, Snitcher, Lead Forensics, Albacross, Leadinfo, Clearbit/HubSpot, 6sense, Demandbase, ZoomInfo | Co |
| M2 | **Cross-customer cookie co-op**: every customer site's tag sets a network cookie; a cookie seen with a known company/person on one site identifies it on another | Demandbase ("hundreds of millions of active cookies"), 5x5 (members contribute), Opensend ("we see the traffic for 100k+ US-based sites"), RB2B "contributor database" `[INFERRED as co-op]`. Vector explicitly is **not** ("You do not become a contributing member") | Co and Per |
| M3 | **Publisher / co-registration binding**: a consumer gives an email on a partner site; that site's tag binds email to cookie/fingerprint/MAID; pooled into a pre-matched table | RB2B, Retention, Leadpipe, Vector, AudienceLab, Opensend, Identity Matrix, Warmly ("partner network of publishers") | Per |
| M4 | **Email-open binding**: a tracking pixel in an email fires from the reader's browser/mail client, revealing IP (and cookie/MAID in webmail/browser contexts) next to the known recipient address; later web visits from that IP/cookie match | LiveIntent (newsletter opens), Retention.com policy ("opening emails"), 5x5 ("email engagement"), Retention "Email Activity" API. **No visitor-ID vendor openly markets "we map your own email opens to IPs"**; Instantly explicitly says its data "does not come from your existing campaigns or lists" | Per (weak: shared/NAT IPs, Apple Mail Privacy Protection proxies opens) |
| M5 | **Bidstream harvesting**: IP, MAID, user agent and page from RTB bid requests, joined to HEMs | Delivr ("bid-stream", "licensed supply-side data"); Vector names "bidstream data" as a legitimate source; FTC alleges Mobilewalla retained bid data "even when it didn't have a winning bid" | Per / household |
| M6 | **Household IP to email scoring**: count which emails are seen on which residential IP; assign a visitor from that IP to the dominant email | AudienceLab XactMatch; Datazapp reverse IP append (residential static IPs) | Per (B2C; B2B only when people work from home) |
| M7 | Device fingerprint lookup (no cookie) | Vector ("we only look at Device Fingerprints"), Identity Matrix, Kwanzoo. Delivr claims "no device, browser, or canvas fingerprinting" | Per |
| M8 | **First-party identify events**: forms, logins, tracked email links (`?utm`/hash tokens), then back-fill prior anonymous sessions | HubSpot, Common Room, Snitcher, Unify, Leadfeeder | Per (deterministic, consented) |
| M9 | **Waterfall aggregation** over the above vendors | Warmly, Clay, Unify, Factors, Default, Kwanzoo | both |
| M10 | Enrichment of a resolved HEM to a B2B profile (LinkedIn URL, title, work email) | RB2B ("LinkedIn and other career-related databases"), everyone | Per |

---

## 6. Email-open IP harvesting and cross-customer co-ops: who does it

- **Email-open harvesting (documented):** LiveIntent (core business: newsletter opens with hashed email + IP +
  device IDs, shared with "cookie matching services, real-time bidding exchanges") `[FETCHED]`; Retention.com
  (policy associates IP and browser with "opening emails") `[FETCHED]`; 5x5 (members contribute "email
  engagement") `[FETCHED]`. Retention sells an "Email Activity" endpoint `[FETCHED]`.
- **Email-open harvesting (not found):** no B2B visitor-ID vendor in this list publicly says it maps a customer's own
  outbound-email opens to IPs to identify later anonymous visits. Common Room, Unify and Snitcher use **click**
  tracking links (first-party, M8), not opens.
- **Cross-customer pixel co-op (documented):** Demandbase (company level), 5x5 (member contribution), Opensend
  ("we see the traffic for 100k+ US-based sites"). RB2B's "contributor database" and its policy right to use data
  "To create new products, services and tools that we may use internally or offer to others, including Customers"
  `[FETCHED]` are consistent with a co-op but do not state it outright `[INFERRED]`.
- **Explicitly not a co-op:** Vector ("You do not become a contributing member of the data co-op"); Delivr
  ("Individual customer site data is never shared") `[FETCHED]`.

---

## 7. Lawsuits and regulatory actions that reveal mechanisms

- **FTC v. Mobilewalla** (Dec 2024) `[FETCHED]`
  https://www.ftc.gov/news-events/news/press-releases/2024/12/ftc-takes-action-against-mobilewalla-collecting-selling-sensitive-location-data :
  "When Mobilewalla bid to place an ad for its clients on a real-time advertising bidding exchange, it unfairly
  collected and retained the information in the bid request, even when it didn't have a winning bid." First time
  the FTC called this unfair; order: "prohibited from collecting or retaining consumer data while participating
  in online advertising auctions for any other purpose than participating in the auction". **Direct legal risk for
  the bidstream mechanism (M5).**
- **CPPA Delete Act enforcement** `[SNIPPET]`/`[FETCHED]`: fines for failing to register, e.g. ROR Partners
  $56,600 (Dec 2025; it "created consumer profiles and custom audience lists using data points covering [...] over
  262 million Americans") `[FETCHED]` https://www.hunton.com/privacy-and-cybersecurity-law-blog/cppa-fines-nevada-marketing-firm-for-violation-of-californias-delete-act ;
  Accurate Append $55,400 (Jul 2025), National Public Data $46,000 (Feb 2025), Datamasters $45,000 and S&P Global
  $62,600 (Jan 2026) `[SNIPPET]`. DROP (one-request deletion across all registered brokers) launches 2026
  `[SNIPPET]`. Implication: a graph owner must register and honour DROP deletions.
- **CPPA v. PlayOn Sports** $1.10M (Mar 2026) for sharing tracking-tech visitor data with ad partners without a
  compliant opt-out `[SNIPPET]`.
- **CIPA wiretap / pen-register wave** `[SNIPPET]`: suits target the **site operator** that runs third-party pixels
  (e.g. Camplisson v. Adidas over TikTok/Bing pixels; LA Times $3.85M settlement June 2026), at $5,000 per
  violation. A 2026 wave also targets **email** tracking pixels. **No suit naming RB2B, Retention, Leadpipe,
  Warmly, Customers.ai or Opensend as defendant was found** (search coverage limited).

---

## 8. Build vs buy for a new entrant (Clue)

**Can build (no third-party identity data needed):**
- M1 company-level reverse IP (open IP registries + ASN/WHOIS + crawled corporate ranges; or rent Snitcher /
  ipregistry cheaply, `[PRIOR]` plan).
- M8 first-party identify events: forms, logins, and **Clue's own outbound** tracked links (per-recipient tokens),
  then retroactive stitching of prior sessions. Deterministic and consent-clean.
- M2 a **cross-customer co-op over Clue's own customers' sites**: a shared first-party-set network id is not
  possible across domains without third-party cookies, but a server-side join on (identified email from one
  customer's form/link) x (fingerprint/IP at that moment) can identify the same device on another customer's
  site. Coverage grows with customer count; it requires explicit contract terms and privacy-policy language from
  every customer, and it turns Clue into a data broker (registration in CA/TX/VT/OR) `[INFERRED]`.
- M4-lite: map opens of **Clue-sent** emails to IP for account-level scoring. Weak for person-level (Apple Mail
  Privacy Protection proxies opens; corporate NAT) `[INFERRED]`.
- M9 waterfall over vendors behind a provider seam.

**Must buy (practically):**
- M3 consumer cookie/fingerprint/MAID-to-HEM binding at US scale. Every vendor at 30%+ person-level owns years of
  publisher/co-registration supply (GetEmails since 2019, AudienceLab "three years", Leadpipe "5.3B emails").
- M5 bidstream: buy only from a licensed supplier; harvesting it yourself is the exact conduct the FTC called unfair.
- M6 household IP-to-email scoring: needs a large email-to-IP observation set you do not have.
- HEM-to-B2B-profile enrichment at scale (Apollo, PDL, ZoomInfo, Retention APIs).

**Cheapest legitimate rental paths found:** Leadpipe Platforms (API, 3-month POC) or Agency ($1,279/10k IDs);
Delivr pay-per-record white-label; RB2B Pro webhooks ($149/600). Expect US-only person-level and no proof of
opt-in ("We do not provide proof of opt-in", AudienceLab `[FETCHED]`).

---

## 9. Source list (all URLs used)

Fetched: https://cppa.ca.gov/data_broker_registry/ · https://cppa.ca.gov/data_broker_registry/registry2025.csv ·
https://cppa.ca.gov/data_broker_registry/registry2024.csv · https://support.rb2b.com/en/articles/8795524-how-does-rb2b-collect-or-use-our-data ·
https://support.rb2b.com/en/articles/14827019-profile-data-faqs · https://support.rb2b.com/en/articles/11155068-contact-level-identification ·
https://support.rb2b.com/en/articles/9910029-rb2b-cookie-information · https://www.rb2b.com/rb2b-demandbase · https://www.rb2b.com/privacy-policy ·
https://www.retention.com/privacy-policy/ · https://retention.com/about-r · https://retention.com/apis · https://www.retention.com/how-it-works ·
https://www.practicalecommerce.com/retention-com-founder-on-email-laundering · https://audiencelab.io/faqs/ · https://audiencelab.io/privacy-policy ·
https://finance.yahoo.com/news/adtech-platform-audiencelab-launches-household-050000760.html · https://www.leadpipe.com/product/identification/ ·
https://www.leadpipe.com/pricing/ · https://www.leadpipe.com/privacy-policy/ · https://www.leadpipe.com/blog/visitor-identification-api-complete-developer-guide/ ·
https://www.vector.co/security · https://www.vector.co/blog/enhanced-visitor-identity-is-here · https://www.vector.co/pricing ·
https://www.commonroom.io/blog/enhanced-website-visitor-identification/ · https://www.commonroom.io/docs/signals/website-visitor-tracking/faqs/ ·
https://www.warmly.ai/p/privacy-policy · https://help.warmly.ai/articles/3568026273-contact-level-identification · https://www.warmly.ai/p/blog/visitor-identification-software-top-11 ·
https://customers.ai/privacy-policy · https://customers.ai/identity-graph · https://customers.ai/pricing · https://www.opensend.com/ · https://www.opensend.com/privacy-policy ·
https://5x5data.com/faqs/ · https://5x5data.com/solutions/website-visitor-resolution/ · https://www.delivr.ai/api · https://www.delivr.ai/resources/delivr-vs-rb2b ·
https://docs.delivr.ai/docs/how-identity-resolution-works · https://bigdbm.com/about/ · https://www.liveintent.com/services-privacy-policy/ ·
https://www.kwanzoo.com/blog/why-one-data-vendor-isnt-enough-for-website-identity-resolution · https://www.kwanzoo.com/product/person-level-website-visitor-id ·
https://happierleads.com/blog/whitelabel-visitor-identification-software-guide · https://happierleads.com/gdpr-compliant-website-visitor-tracking ·
https://help.factors.ai/en/articles/14885484-visitor-identity-enrichment · https://www.apollo.io/product/website-visitor-identification ·
https://help.instantly.ai/en/articles/9502519-getting-started-with-the-website-visitors-feature · https://pipeline.zoominfo.com/marketing/websight-buyer-id-website-visitor-tracking ·
https://university.clay.com/docs/website-tracking · https://www.clay.com/blog/web-intent · https://www.unifygtm.com/explore/website-visitor-identification-how-it-works ·
https://www.leadfeeder.com/web-visitors/ · https://docs.snitcher.com/product/how-snitcher-works · https://www.albacross.com/ · https://www.visitorqueue.com/ (301 to leadinfo.com) ·
https://www.leadinfo.com/ · https://www.demandbase.com/blog/your-target-accounts-are-working-from-home-demandbase-has-the-answer/ ·
https://apify.com/nabeelbaghoor/website-visitor-identification-api · https://apify.com/store?search=website%20visitor%20identification ·
https://www.ftc.gov/news-events/news/press-releases/2024/12/ftc-takes-action-against-mobilewalla-collecting-selling-sensitive-location-data ·
https://www.hunton.com/privacy-and-cybersecurity-law-blog/cppa-fines-nevada-marketing-firm-for-violation-of-californias-delete-act

Snippet-only (search results, not fetched or fetch failed): https://www.identitymatrix.ai/blog/identity-matrix-1-alternative-to-rb2b ·
https://www.dimmo.ai/products/identity-matrix · https://www.opensend.com/post/retention-com-review · https://www.datazapp.com/website-visitor-identification/ ·
https://datarade.ai/data-providers/bigdbm/profile · https://partner-directory.liveramp.com/partners/delivr-ai · https://marketbetter.ai/blog/best-koala-alternatives-2026/ ·
https://www.knock2.ai/blog/apollo-website-visitor-identification · https://www.knock2.ai/blog/instantly-website-visitor-identification · https://pipeline.zoominfo.com/sales/snitcher-review ·
https://www.leadpipe.com/blog/lead-forensics-alternatives/ · https://www.amplemarket.com/blog/what-does-seamless-ai-really-do · https://docs.lusha.com/user-guide/lushas-api/signals-api ·
https://traxy.ai/blog/blog-best-trigify-alternatives-2026 · https://www.default.com/solutions/website-visitor-tracking · https://www.factors.ai/blog/anonymous-website-visitor-identification-guide ·
https://www.unifygtm.com/explore/best-website-intent-data-tools-b2b · https://btlaw.com/en/insights/alerts/2026/cipa-ecpa-website-tracking-privacy-litigation-in-2026 ·
https://www.fisherphillips.com/en/news-insights/court-allows-cipa-claim-involving-third-party-pixels-to-proceed.html · https://www.hunton.com/privacy-and-cybersecurity-law-blog/cppa-enforces-against-two-data-brokers-for-failing-to-register-under-the-delete-act ·
https://cppa.ca.gov/announcements/2025/20250729.html · https://www.gblock.app/articles/email-tracking-pixel-lawsuits-cipa-wiretapping-2026
