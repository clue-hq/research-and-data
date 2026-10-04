# WVI-4. How anonymous visitor identification really works, and how Clue builds it

**Written 2026-10-03** on branch `feature/website-deanonymization`. Synthesis of five parallel research briefs in
`docs/specs/_research/wvi-4/` (01 Ploy/Userled teardown, 02 vendor landscape and supply chain, 03 tracking-script
teardown, 04 research papers, 05 building our own graph). Every fact below is sourced in those files with
[FETCHED] / [SNIPPET] / [INFERRED] labels. This document **supersedes WVI-1/2/3 wherever they disagree** on how
person-level identification is sourced.

Founder brief: Clue builds its own identification capability, not a resold vendor UI; the deterministic layer
(snippet + tracked link / UTM match) is accepted and buildable; the question is identifying the **anonymous**
visitor (never clicked a Clue link, never filled a form), and what Ploy and others actually do.

## 1. What Ploy actually does

- Ploy's trust center subprocessor list names **"GetEmails · Identify Your Website Visitors · rb2b.com"**.
  GetEmails LLC does business as Retention.com and RB2B (California data broker registry). Ploy rents person-level
  identification from RB2B; its own pages never say so (01).
- Ploy's site script (`/_p/v1.js`, "ploy-analytics") only sets a first-party `ploy_anon_id`, posts events to its
  own `/_ploy/ingest`, and contains no identity-graph calls and no fingerprinting (checked on four Ploy-hosted sites).
  Resolution therefore happens server-side from IP (+ user agent). RB2B sells exactly that: `POST /ip_to_hem`
  (IP to ranked hashed emails with confidence), `/hem_to_business_profile`, `/hem_to_best_linkedin` (01).
- Userled has no person graph of its own: tracked links (`?ul_e=`), HubSpot cookie stitching, and **Vector** for
  anonymous US visitors (01).

## 2. The real mechanism, end to end

1. **Capture upstream.** A person logs in to, or subscribes to a newsletter on, a consumer publisher site
   (DuckDuckGo tracker data shows the relevant containers on Screen Rant, Snopes, Townhall, How-To Geek and others).
   An identity network's tag on that site binds **browser cookie + IP to a hashed email**, usually a personal email.
2. **Lookup on the B2B site.** The vendor's script, running in the visitor's browser, calls the identity networks
   with the network's own **third-party cookie**. The networks found in decoded code (03):
   - **LiveIntent** (`b-code.liadm.com`): RB2B, Vector, Warmly, Customers.ai and Apollo each hold their own
     LiveIntent distributor id. This is the backbone.
   - **`a.usbrowserspeed.com/cs`** ("FXF" in Warmly's code; associated with Delivr.ai): RB2B, Vector, Warmly,
     Customers.ai. Returns the hash via redirect placeholders.
   - **TowerData / AtData** (`alocdn.com`): RB2B.
   - **Sovrn** (`pxdrop.lijit.com`), injected by the Delivr script that Leadpipe and AudienceLab both serve byte-identical.
3. **Add form and URL signals.** Most scripts also capture form emails (some before submit), email-tool cookies
   (`hubspotutk`, Klaviyo, Marketo), and email parameters in links.
4. **Turn the hash into a B2B person.** Server-side: hashed email to name, employer, title, LinkedIn via a B2B
   database. RB2B's own API shows this two-step chain.
5. **Gate and fall back.** US only, proxies/hosting IPs skipped (RB2B checks via ip-api client-side), company-level
   reverse IP when no hash resolves.

**Consequences.** It only works where third-party cookies survive (Chrome; not Safari/Firefox by default), which is
why every vendor is US-only and quotes desktop match rates. Fingerprinting is rare and never the identity source (03).

## 3. Who owns the data (the market is a few graphs, many brands)

- Upstream identity networks: LiveIntent, AtData (TowerData), the usbrowserspeed/Delivr sync, Sovrn; beneath them
  registered data brokers (LiveRamp, Throtle, Audience Acuity, BIGDBM, Epsilon, Acxiom, etc.) (02, 03).
- Wholesale visitor-ID suppliers: GetEmails (RB2B/Retention), Leadpipe, AudienceLab, Vector, Delivr.ai, 5x5 (02).
- Brands on top: Ploy (RB2B), Userled and Common Room (Vector), Factors.ai (RB2B), Warmly (chains RB2B + Vector +
  others), Avina's Mesh SDK (RB2B with Vector fallback), white-label resellers of Leadpipe/AudienceLab/Delivr (01, 02, 03).
- Company-level only (the "millions" claim is true only here): Demandbase, 6sense, Clearbit/HubSpot, Dealfront,
  Snitcher, Leadinfo, Lusha, Albacross, Lead Forensics; Apify's only found actor wraps 6sense (02).

## 4. How accurate it is (independent evidence)

| Link | Measured accuracy | Source (04) |
|---|---|---|
| IP to person email | **16%** correct (7% to 30% by provider) | Truthset / CIMM / Go Addressable vs ISP ground truth, Nov 2025 |
| IP to postal address | **13%** correct (4% to 18%) | same |
| Agreement between providers | 2.8% to 6.4% | same |
| Hashed email to postal | 51% (32% to 69%) | Truthset / CIMM |
| Data-broker attributes | at least 40% "not at all accurate" | Venkatadri et al., WWW 2019 |
| Vendor person-level positives | 52% to 87% correct in audits | WVI-2 1.J |
| Fixed broadband IP stability | 87% keep an IP > 1 month | Mishra et al., WWW 2020 |
| Mobile | CGNAT in > 90% of cellular networks | Richter et al., IMC 2016 |

No peer-reviewed measurement of B2B reverse-IP accuracy exists. Company-level vendors' own patents (6sense,
Demandbase, BitSight) build IP-to-company maps from **form fills, logins and email activity**, with published
scoring rules (recency, frequency, dominance on an IP, business-hours weighting).

## 5. The options for Clue, honestly ranked

| # | Path | Anonymous person coverage | Precision | Time | Cost | Legal |
|---|---|---|---|---|---|---|
| A | **Own first-party layer**: script, ingest, path-token redirect links on everything Clue sends, form identify on submit, email-tool params/cookies (`hubspotutk`, `mkt_tok`, `mc_eid`), returning-visitor stitching | none for true strangers; all Clue-driven traffic | ~1.0 | weeks | engineering | low |
| B | **Own IP-to-company database** built the 6sense/BitSight way from Clue's own identify events + registries (Prefix2Org, ASdb) | company only, ~25-35% of business visits | >= 0.90 when asserted | 1-2 months | engineering | low |
| C | **Import the customer's existing bindings** (HubSpot `hubspotutk` byUtk, Marketo, Mailchimp) | people the customer already knows, now recognised on any visit | ~0.95 | 2-6 weeks per connector | engineering | low |
| D | **Direct contracts with upstream identity networks** (LiveIntent, AtData, the Delivr/usbrowserspeed sync, Sovrn) feeding **Clue's own** resolver: multiple hashes, agreement scoring, hash to B2B person via Apollo `people/match` (accepts `hashed_email`) or PDL, employer cross-checked against the IP's company and against the target account's known buying committee | vendor-like: 15-45% of US Chrome visitors (vendor claims) | raw sources weak; **Clue's committee and employer checks are what make it defensible** | 2-4 months incl. contracts | contract minimums (AtData from ~$10K; RB2B OEM ~$5K/mo for 50K as a reference) | medium: Clue registers as a data broker (CA ~$6K/yr, plus VT/TX/OR), US only, opt-out passthrough |
| E | Cross-customer co-op ("Clue Network") | ~0.5-3% at 100 customer sites | ~1.0 for its matches | years | engineering | highest; reverses the 2026-07-22 workspace-isolation ruling; data broker; not EU |
| F | Publisher / newsletter deals of our own | grows one deal at a time | ~1.0 | slow | B2B newsletter CPMs $50-100+ | medium |

**Do not build:** pre-submit form sniffing (flagged by Senol et al., USENIX Security 2022; CIPA risk), bidstream
harvesting (FTC Mobilewalla order, Dec 2024), cross-site leak / XS-Leak or ad-platform oracle tricks (attacks).

## 6. Recommendation

1. **Build A + B + C now.** All owned, accurate, and they produce the labelled ground truth needed to measure
   everything probabilistic.
2. **Path D is the honest answer to "how do Ploy and RB2B find strangers".** It is the RB2B model itself, not
   reselling RB2B: Clue contracts the same upstream networks RB2B uses and owns resolution, scoring and the B2B
   step. Clue's edge over RB2B is the committee check: a revealed person is only asserted if they match (or
   plausibly join) a target account's known committee and the IP's company, which is how Clue reaches >= 90%
   precision on inputs that are 15-50% accurate raw.
3. **Gate D on three founder rulings**: (W18) Clue becomes a registered data broker and US-only person-level is
   acceptable; (W19) upstream contracts are a "data input", not a "vendor feature" (the founder's no-external-service
   line); (W20) the precision bar: no name shown below 0.90 on the held-out known-visitor test.
4. **Defer E and F.** Run the non-personal overlap test first (how many target-account domains recur across Clue
   workspaces) before any co-op discussion.

## 7. Corrections to earlier documents

- WVI-1 described Ploy's graph vendor as "not named": it is RB2B (GetEmails), per Ploy's subprocessor list.
- WVI-1 recorded California SB 690 as unsigned: it was signed 2026-09-30, operative 2027-01-01, and ends only
  private pen-register (s. 638.51) suits (05).
- Clue does not send email today (no ESP/SMTP client in the repo), so open-IP mapping needs Clue to become the
  sender; click IPs need only Clue's own redirect (05). Apple Mail and Gmail proxy most opens anyway.
- Koala shut down in September 2025 (acqui-hired by Cursor) (02).
