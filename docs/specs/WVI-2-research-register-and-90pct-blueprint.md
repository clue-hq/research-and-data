# WVI-2 — Research register, the principles behind ≥90% identification precision, and the implementation blueprint

**Status:** research register + engineering blueprint, 2026-09-24. Companion to
`WVI-website-visitor-identification.md` (WVI-1: vendors, the three-rung ladder, seams, costs, rulings
W1–W9). This document answers three questions: *what has been published and open-sourced on every
layer of visitor identification*, *what principles a ≥90%-precision system must follow*, and *how
Clue implements them on the WVI-1 seams*. It also states the RB2B caveat precisely (§3).
**Tags:** `[PAPER]` peer-reviewed or arXiv · `[OSS]` open-source repo or open dataset · `[VENDOR]`
vendor claim · `[FETCHED]`/`[SNIPPET]` as in WVI-1 · `[REPO]` verified in this worktree.

---

## 0. First fix what "90%" means

Vendors quote **match rate** (share of visitors they name). Nielsen's device-graph audits quote
**accuracy including true negatives** (Tapad 91.2%, Drawbridge 97.3% `[SNIPPET]`
<https://www.adexchanger.com/data-exchanges/2016-edition-marketers-guide-to-cross-device-identity/>).
Fingerprint defines accuracy as "how many returning visitors to a site we successfully identify as a
returning visitor and not as a new visitor" `[FETCHED]`
<https://fingerprint.com/blog/fingerprintjs-fingerprint-pro-device-identification-accuracy-explained/>.
These are three different numbers and none of them is what a rep needs.

**Clue's definition.** For every identification Clue *asserts* (a visit bound to a named contact or
a named account), the asserted binding is correct ≥ 90% of the time, measured on a labelled set the
system did not use to make the assertion. **Coverage** (share of visits with any assertion) is
reported separately, per rung, as an estimate — the platform's existing "coverage confidence, not a
completeness guarantee" rule. "Unknown" is a first-class, correct outcome; a wrong name is the only
failure (the claim-store law, `CLAUDE.md`). Leadpipe's own RB2B review says the same to buyers:
"record unknown identity outcome rather than treating a plausible profile as proof" `[FETCHED]`
<https://www.leadpipe.com/blog/rb2b-review/>.

**Where the labels come from — the ladder benchmarks itself.** Every rung-0 identification (a
tracked-link click, a form fill, a login) is a free, exact label for the same visitor's IP-layer and
graph-layer guesses. That turns the deterministic path from "just coverage" into the calibration set
for everything probabilistic (§2 P8). No vendor has this, because no vendor also owns the outbound.

---

## 1. The research register — what exists, by layer, and what each source gives Clue

### 1.A Device recognition (is this the same browser that came before?)

| Source | What it establishes | Use for Clue |
|---|---|---|
| Laperdrix, Bielova, Baudry, Avoine, *Browser Fingerprinting: A Survey*, ACM TWEB 2020 `[PAPER]` <https://arxiv.org/abs/1905.01051> | The full attribute catalogue (canvas, WebGL, audio, fonts, UA, screen…), entropy per attribute, defences, the state of uniqueness | The signal list for `clue.js`; which signals are stable vs noisy |
| Vastel, Laperdrix, Rudametkin, Rouvoy, *FP-Stalker*, IEEE S&P 2018 `[PAPER]` <https://www.semanticscholar.org/paper/8d6fd3522bc80cb512c3bb1f93ce52643fb976a1> | Fingerprints change fast — 50% of browsers change within 5 days, 80% within 10 `[SNIPPET]` — yet a rule-based + ML **linking** algorithm keeps tracking across changes | Fingerprints are for *linking* returning visitors with tolerance, never a static id; the linking rules (same OS/browser family, monotone version bumps, ≤k attribute changes) are the ones to port |
| Andriamilanto et al., *A Large-scale Empirical Analysis of Browser Fingerprints Properties for Web Authentication* `[PAPER]` <https://arxiv.org/pdf/2006.09511> | Stability and distinctiveness measured on a large population for an authentication use-case | Which attributes to weight in the linking score |
| FingerprintJS (open-source, BSL since v4) `[OSS]` <https://github.com/fingerprintjs/fingerprintjs>; vendor comparison: OSS "40%–60%" vs Pro "99.5%", Pro "98% accuracy at month four" `[VENDOR]` `[FETCHED]` <https://fingerprint.com/blog/fingerprintjs-fingerprint-pro-device-identification-accuracy-explained/> | Client-only fingerprinting tops out around 60%; the rest is server-side signals + ML + fuzzy matching | Do the linking server-side; client hash alone is a hint |
| ThumbmarkJS (MIT) `[OSS]` <https://github.com/thumbmarkjs/thumbmarkjs> — "~80% uniqueness" client-side; its API adds TLS/HTTP-header signals for "over 99% uniqueness" `[VENDOR]` | A commercially usable client library, and the pattern (client hash + server TLS/header hash) | The client component of `clue.js`; add a server-side TLS/header hash (JA4-class) on `/v1/collect` |
| CreepJS `[OSS]` <https://github.com/abrahamjuliot/creepjs> | Lie detection: whether fingerprint signals are mutually consistent (anti-detect browsers, spoofing) | A test page for our own script; a "tampered" flag that lowers confidence |

**Takeaway:** device recognition supports *returning-visitor* continuity (identify once via a link,
recognise later for free) and is never the identity anchor.

### 1.B Cross-device and IP-plus-time linking (which browsers belong to one person?)

| Source | Result | Use |
|---|---|---|
| Zimmeck, Li, Kim, Bellovin, Jebara, *A Privacy Analysis of Cross-device Tracking*, USENIX Security 2017 `[PAPER]` <https://sebastianzimmeck.de/zimmeckEtAlCross2017.pdf>; data+code `[OSS]` <https://github.com/privacy-tech-lab/cross-device-tracking> | IP similarity + browsing history links mobile to desktop at "precision, recall, and F-1 scores of 0.88, 0.95, and 0.91" on a small test set (37 TP / 5 FP / 2 FN) `[SNIPPET]` | The ceiling for IP-co-occurrence linking; the feature set (shared IPs by time-of-day, domain overlap) |
| ICDM 2015 Drawbridge Cross-Device Connections (Kaggle, 340 teams) `[OSS]` <https://www.kaggle.com/c/icdm-2015-drawbridge-cross-device-connections>; 3rd-place code `[OSS]` <https://github.com/bikash/ICDM2015> (F0.5 = 0.88); Díaz-Morales, *Cross-Device Tracking: Matching Devices and Cookies* `[PAPER]` <https://arxiv.org/abs/1510.01175>; Multi-layer classification paper `[PAPER]` <https://www.semanticscholar.org/paper/24cfe9b5681b9d31a11c8b51f7c1c26e2ce11f6c> (F0.5 = 0.855, 10th) | With IP co-occurrence and timing features, the field converges on F0.5 ≈ 0.85–0.88 | The realistic accuracy of probabilistic linking *with* IP anchors |
| CIKM Cup 2016 Cross-Device Entity Linking (DCA, browse logs only) `[OSS]` <https://competitions.codalab.org/competitions/11171>; runner-up paper `[PAPER]` <https://arxiv.org/pdf/1610.03928>; solutions `[OSS]` <https://github.com/alexeygrigorev/cikm-cup-2016-cross-device> | Without IP/time anchors, F1 ≈ 0.40–0.42 | Behaviour alone cannot carry identity — the number to quote when someone proposes "AI will figure out who it is" |
| GraphTrack, 2022 `[PAPER]` <https://arxiv.org/abs/2203.06833> | IPs, domains and devices as a graph; random walk with restart for device similarity; 154K-user dataset | The graph formulation if Clue ever links across the client's site and Clue pages at scale |
| Nielsen-validated device graphs: Tapad 91.2%, Drawbridge 97.3% `[SNIPPET]` | Commercial probabilistic graphs reach ~91–97% *accuracy incl. true negatives* with deterministic seeds | Sets expectations for a bought graph; ask the vendor for precision on positives only |

**Takeaway:** ~0.88–0.91 is the published ceiling for probabilistic linking *with* deterministic
seeds and IP anchors; ~0.4 without. 90% precision is reachable only by keeping deterministic seeds in
the loop and refusing to assert when anchors are absent.

### 1.C De-anonymization from behaviour (what pages reveal)

| Source | Result | Use |
|---|---|---|
| Su, Shukla, Goel, Narayanan, *De-anonymizing Web Browsing Data with Social Networks*, WWW 2017 `[PAPER]` <https://dl.acm.org/doi/10.1145/3038912.3052714> | "given a history with 30 links originating from Twitter, we can deduce the corresponding Twitter profile more than 50% of the time"; "nearly 400 people … correctly identify more than 70% of them" `[FETCHED]` | Page choice is identifying. Within a *known account*, the pages read (pricing vs docs vs careers) discriminate committee roles — usable as a tie-breaker between candidate contacts, never as an assertion |
| Narayanan, Shmatikov, *Robust De-anonymization of Large Sparse Datasets*, IEEE S&P 2008 `[PAPER]` <https://www.cs.utexas.edu/~shmat/shmat_oak08netflix.pdf> | Sparse behavioural records re-identify with few data points | Same lesson; also why behavioural data must be minimised and TTL'd |

### 1.D IP → organisation (the free part and the not-free part)

| Source | Result | Use |
|---|---|---|
| Gouda, Dainotti, Testart, *Prefix2Org: Mapping BGP Prefixes to Organizations*, IMC 2025 `[PAPER]` <https://deepakgouda.github.io/assets/pdf/IMC-2025-Prefix2Org.pdf> | A taxonomy of address *holders* (operational rights, not just registrants); public dataset covering "99.96% (99.99%) of IPv4 (IPv6) prefixes"; "99% recall" on the 9.3% of IPv4 space they could validate; no false positives on two large orgs with exhaustive ground truth; RPKI certificates used to unify names `[SNIPPET]` | The state of the art and it is public. The base layer of Clue's local resolver |
| Ziv, Izhikevich, Ruth, Izhikevich, Durumeric, *ASdb*, IMC 2021 `[PAPER]` <https://lizizhikevich.github.io/assets/papers/ASDB.pdf>; data <https://asdb.stanford.edu> `[OSS]` | "96% coverage of ASes, and 93% and 75% accuracy on 17 industry categories and 95 sub-categories" | Classify the AS behind an IP: ISP / hosting / education / enterprise. Only *enterprise-category* ASes are candidate accounts; ISP/carrier/hosting are excluded before any lookup |
| *Linnaeus: A Hierarchical, Multi-Label Framework for AS Classification*, 2026 `[PAPER]` <https://arxiv.org/abs/2603.13649> | "precision and recall of 0.83 and 0.76" on ~2,000 annotated ASes; multi-label, LLM-assisted | Newer taxonomy; use if ASdb coverage is stale |
| CAIDA AS2Org (quarterly since 2009, WHOIS-derived) `[OSS]` <https://catalog.caida.org/dataset/as_organizations>; Rust reader <https://github.com/bgpkit/as2org-rs>; Georgia Tech IIL-AS2Org <https://github.com/InetIntel/Dataset-AS-to-Organization-Mapping> | AS → organisation name, with sibling-AS grouping | Org names and siblings for enterprise ASes |
| Huston, *IP address to organization name map*, ISP Column / APNIC blog, Jan 2026 `[FETCHED]` <https://ispcol.potaroo.net/2026-01/ip2org.html>; Virginia Tech NANOG 95 system <https://asint.netsecurelab.org> | Two methods: (a) RIR *extended delegated stats* `reg-id` → one whois per holder; (b) IRR + PeeringDB + whois candidates, filtered via ASdb/PeeringDB/search, unified with an LLM | Method (a) is a weekend of code and gives holder names for every allocation; (b) is how to de-duplicate names |
| Open data feeds `[OSS]`: RIR delegated-extended files; RDAP; RIPEstat Data API (no key; `prefix-overview`, `whois`, `network-info`) <https://stat.ripe.net/docs/02.data-api/>; PeeringDB API; IRR; RouteViews/RIS; **IPinfo Lite** (free, unlimited, daily, ASN+org+country, MMDB) <https://ipinfo.io/lite>; iptoasn.com (hourly TSV) <https://iptoasn.com/>; MaxMind GeoLite2-ASN; aggregators <https://github.com/sapics/ip-location-db>, <https://github.com/O-X-L/geoip-asn>; libraries `ipwhois` <https://ipwhois.readthedocs.io/>, `pyasn` | Everything needed for holder-level mapping at $0 | The local resolver's inputs |
| Exclusion lists `[OSS]`: cloud ranges, daily, 60+ providers <https://github.com/rezmoss/cloud-provider-ip-addresses>; <https://github.com/painlessanalytics/datacenter-cloud-ip-lists>; VPN/datacenter <https://github.com/X4BNet/lists_vpn>, <https://github.com/tn3w/IPSet>; FireHOL proxies/abusers <https://iplists.firehol.org/>; **Apple iCloud Private Relay egress CSV** (authoritative, ~284k lines, with city) <https://mask-api.icloud.com/egress-ip-ranges.csv>; Tor exit list; bot UA: `isbot` <https://github.com/omrilotan/isbot>, Matomo device-detector <https://github.com/matomo-org/device-detector>, `ua-parser` | Private Relay "hides a user's true IP address" behind Apple + partner egress `[SNIPPET]` — every Safari-with-iCloud+ visitor resolves to Apple/Cloudflare/Akamai unless excluded | Exclude *before* resolving; a Private Relay hit is "unknown", not "Akamai" |
| Curated commercial ranges `[VENDOR]`: Snitcher IP-to-Company API (`fuzzy` flag, `type: isp`) `[FETCHED]`; IPinfo Enterprise; Demandbase; 6sense; Dealfront; Lead Forensics "1.4 billion IP addresses" `[SNIPPET]` | What money buys: the mapping from *ISP/shared* ranges to the business actually behind them, learned from observed logins | The upgrade path when local says "ISP" on a visit that matters |
| Poese et al. and the 2026 *Lost in the Prefix* geolocation study `[PAPER]` <https://arxiv.org/pdf/2605.21937> | Geo databases are unreliable at city level | Use geo only for jurisdiction (country) and coarse consistency checks |

**Takeaway:** holder-level IP→org is a solved, free problem (Prefix2Org-class recall ≈ 99% on what
can be validated). The unsolved, paid part is *who is behind an ISP or cloud range* — and remote
work caps every vendor there. Company precision ≥ 90% is reachable by (1) excluding what should not
be resolved and (2) asserting only enterprise-category holders; the price is coverage.

### 1.E Identity graphs and hashed-email standards

| Source | Result | Use |
|---|---|---|
| UID2 normalisation and encoding `[OSS]` <https://github.com/IABTechLab/uid2docs/blob/main/docs/getting-started/gs-normalization-encoding.md> | lowercase, trim, Gmail dot-removal, SHA-256, Base64; salt buckets rotate ~yearly `[SNIPPET]` | Normalise exactly this way so any provider hash matches ours; store only the normalised SHA-256 |
| Prebid SharedId / UID2 operator `[OSS]` <https://github.com/IABTechLab> | Open reference implementations of first-party id + hashed-email token flows | Pattern for the `clue_vid` ↔ hashed-email binding |
| Truthset accuracy scoring `[VENDOR]` <https://truthset.com/data-accuracy/data-accuracy/>; email↔postal match "32% to as high as 69%" across providers `[SNIPPET]` <https://www.adweek.com/adweek-wire/massive-study-on-matching-households-and-email-addresses-finds-range-of-inaccuracies/> | Provider identity data varies 2× in accuracy; only scored data is safe to act on | Score every provider (§2 P11); ask graph vendors for Truthset-style scores |
| Graph wholesalers BIGDBM, Audience Acuity (WVI-1 §1.3) `[FETCHED]` | Consumer graphs: hashed-email ↔ device/IP/MAID, no LinkedIn | The email comes from here; the *employer* does not |
| Reseller pixels RB2B / Leadpipe / Bullseye (WVI-1 §2) | Cookies, install, payloads, prices | The rung-2 provider seam |

### 1.F Entity resolution (binding a revealed person or company to Clue's entities)

| Source | Result | Use |
|---|---|---|
| Fellegi & Sunter, *A Theory for Record Linkage*, JASA 1969 `[PAPER]` | Match/non-match weights per field, decision thresholds with explicit error rates | The scoring model for name+company+title binding |
| Splink (MoJ) `[OSS]` <https://github.com/moj-analytical-services/splink> — F1 0.998 on PII-style data, 0.73 on DBLP-ACM `[SNIPPET]` | Scalable Fellegi–Sunter with EM training, SQL/DuckDB backends | The binding engine when there are no strong keys |
| dedupe `[OSS]` <https://github.com/dedupeio/dedupe>; Zingg `[OSS]` <https://github.com/zinggAI/zingg>; Awesome list `[OSS]` <https://github.com/OlivierBinette/Awesome-Entity-Resolution> | Active-learning alternatives; dedupe struggles past ~10k rows `[SNIPPET]` | Labelling UI ideas; not the engine |
| Ditto, VLDB 2020 `[PAPER]` <https://www.vldb.org/pvldb/vol14/p50-li.pdf>; code `[OSS]` <https://github.com/megagonlabs/ditto> — "matching two company datasets consisting of 789K and 412K records, Ditto achieves a high F1 score of 96.5%" `[SNIPPET]` | LM-based matching on company records | Company-name reconciliation (IP holder name ↔ `account_entity.canonical_name`) |
| LLM entity matching 2025–26: Peeters & Bizer <https://openproceedings.org/2025/conf/edbt/paper-81.pdf>; ComEM <https://aclanthology.org/2025.coling-main.8.pdf>; AnyMatch <https://arxiv.org/pdf/2409.04073>; fine-tuning <https://arxiv.org/pdf/2409.08185> `[PAPER]` | Zero-shot LLM matching is strong but costs and drifts; batch/verify patterns cut cost | LLM adjudication only for the ambiguous residue, logged as tier-4 |

### 1.G Identity-stitching semantics to copy from open-source analytics

| Source | Pattern | Use |
|---|---|---|
| PostHog identity resolution `[OSS]` <https://posthog.com/docs/product-analytics/identity-resolution> | `identify` merges the anonymous person *into* the identified one; `alias` merges two ids; merges are one-way; events are immutable `[SNIPPET]` | `clue_vid` ↔ contact merge semantics |
| Snowplow identifiers, IP-lookup enrichment, PII pseudonymisation (`anonymousOnly`: keep ids only for consented users) `[OSS]` <https://docs.snowplow.io/docs/pipeline/enrichments/available-enrichments/pii-pseudonymization-enrichment/> | Collector → enrich → warehouse with `network_userid` / `domain_userid` / session ids and consent-aware hashing | The event pipeline shape and the consent-aware pseudonymisation step |
| Plausible / Umami cookieless counting (daily-rotating salted hash of IP+UA) `[OSS]` | Consentless unique counting that cannot re-identify next day | The EU no-consent mode for Clue pages (counts only, no identity) |

### 1.H Email → person, and free corroborators

| Source | Result | Use |
|---|---|---|
| AI Ark `POST /v1/people/reverse-lookup` — email only, 0.5 credit, returns `full_name`, `title`, `linkedin`, company `[FETCHED]` <https://docs.ai-ark.com/reference/people-reverse-lookup.md> | The B2B step, already in Clue's stack | Primary email→LinkedIn |
| Apollo `people/match` (`email` or `hashed_email`) `[REPO]` `docs/specs/ARV2-apollo-api-contract.md:80-82`; PDL `email_hash` `[FETCHED]` | Fallbacks that accept a *hash* | When the graph returns only a hash |
| Gravatar REST v3 profile by SHA-256 email hash (free; 100/h, 1,000/h with key) `[OSS]` <https://docs.gravatar.com/rest-api/> | Verified social accounts, display name, for the fraction of people with a profile | Free corroborator of name / LinkedIn on a candidate |
| GitHub commit emails and OSINT tools (`gitrecon`, `MailAccess`) `[OSS]` | Public commit metadata links emails to profiles | **Verification only, never discovery** — out of the Doc D use-class for outreach; note for completeness |

### 1.I Free aggregate calibration

LinkedIn Insight Tag "Website Demographics" — free, aggregate job title / company / seniority /
industry of logged-in LinkedIn members who visited; minimum 300 members per report; no individuals
`[SNIPPET]` <https://business.linkedin.com/marketing-solutions/insight-tag>. Use: a monthly sanity
check that the company/seniority mix reverse-IP produces matches what LinkedIn saw.

### 1.J Accuracy audits and their method

Gartner-auditor press release (Leadpipe-adjacent; 26 March 2026): known contacts sent to three live
sites, per-vendor correctness — Leadpipe 82% correct, RB2B 5.2/10 with wrong seniority/department,
Warmly returned "entirely wrong individuals" `[SNIPPET]` (WVI-1 §2.3). The *method* is the reusable
part: send N known people, record which rung named them and whether the name was right.

### 1.K Legal and consent references

GPC specification <https://globalprivacycontrol.org/>; CPRA B2B-exemption expiry; SB 690 (Sidley,
Alston & Bird) ; ePrivacy/PECR; all in WVI-1 §1.4.

---

## 2. The principles a ≥90%-precision system follows (each tied to its evidence)

1. **Precision on assertions, coverage as an estimate, "unknown" as a valid answer.** (§0; claim-store law.)
2. **Deterministic anchors create identity; probabilistic methods only *recognise* an identity that
   already exists.** Linking with anchors reaches F ≈ 0.88–0.91; without them ≈ 0.40 (1.B). A
   fingerprint or an IP never names a person by itself.
3. **Two independent signals to assert STRONG; one signal is WEAK and goes to review.** Examples of
   independent pairs: tracked link + returning fingerprint; graph email + IP holder consistent with
   the person's employer; form fill + cookie. This is the platform's corroboration rule (M9.2)
   applied to identity.
4. **Consistency checks before assertion.** Employer(person) ∈ {IP holder, residential ISP};
   IP country vs person location; device class vs role plausibility; page/persona plausibility (1.C)
   as a tie-breaker only. Most wrong-person reveals fail one of these cheaply.
5. **Exclude before you resolve.** Cloud, VPN, Tor, datacenter, mobile carrier, Private Relay and
   bot traffic are removed first (1.D lists). A resolved "Akamai" is a false positive waiting to be
   emailed.
6. **Only enterprise-category holders become accounts.** ASdb/Linnaeus category gate; ISP/hosting
   holders are "unknown" locally and go to a curated vendor only when the visit matters (§4).
7. **Freshness is part of correctness.** Graph bindings and employers decay; require the provider's
   capture recency and re-verify the employer at assertion time (AI Ark ≤30-day refresh claim; Truthset
   variance 1.E). A person who changed jobs is the classic "wrong department" reveal.
8. **The deterministic rung labels the probabilistic rungs.** Every link click / form fill / login
   is a label; nightly, compute per-method and per-provider precision on those labels; thresholds are
   chosen for precision ≥ 0.90 on a held-out month and re-fitted monthly (Fellegi–Sunter weights via
   Splink, 1.F).
9. **Scored providers, auto-demotion.** A graph or IP vendor whose rolling precision on our labels
   falls below the floor is demoted to "suggestion" (WEAK, no assertion) without a code change.
10. **One-way merges, immutable events, append-only decisions.** PostHog semantics (1.G) plus the
    platform's C1 ledger discipline: never overwrite a resolution, supersede it.
11. **Behavioural inference never drives outreach.** Persona tie-breaking (1.C) is WEAK by
    construction and is stopped by the Doc D use gate; it may reorder a review queue, not send a mail.
12. **Privacy is a quality property.** UID2-normalised SHA-256 only; raw IP TTL 30 days; consent and
    GPC gates; person-level US-only and off by default; a wrong identification is also a compliance
    incident, so the same ledger serves both audits.
13. **Coverage is bought with reach, not with resolution.** Tokens on every outbound (Userled's
    +20–30% net-new identities), per-account pages, QR on mail, LinkedIn Matched Audiences pointed at
    per-account pages. Every extra deterministic touch raises coverage *and* the label set.
14. **Audit before enabling.** The known-visitor test (1.J) runs per site before person-level is
    switched on, and its numbers are shown to the client.

---

## 3. The RB2B caveat, stated precisely (and how the same theory works for us)

The founder's framing is right: person-level identification is *also* deterministic in theory. RB2B's
graph binding — this browser ↔ that hashed email — was **deterministic at capture** (the person typed
the email on a partner site). What makes it fail is everything between capture and your site:

1. **Transfer depends on browser continuity, not on your link.** The binding is carried by cookies,
   device signals and IP. Safari/Firefox third-party blocking, ITP cookie ageing, private mode, a new
   device, or iCloud Private Relay break the chain (1.A, 1.D). RB2B's own doc: a device "not been
   previously cookied by RB2B's publisher network" is largely unidentifiable `[SNIPPET]`.
2. **The captured email is usually personal.** Sweepstakes, coupons and newsletters collect
   `gmail.com`, so *person → employer* is a **second, probabilistic** lookup against a B2B database
   (common names, stale positions). That is where "wrong seniority levels, wrong departments" comes
   from (1.J), not from the graph.
3. **Shared devices and households** bind one browser to several people.
4. **US-only**, and the reveal is charged whether or not it is right (1 credit per identified visitor
   per 30 days `[FETCHED]`).
5. **It names anyone**, not people you can act on; relevance is left to the buyer.

**Clue's version of the same theory:** make *our own* capture events the binding. A tracked-link
click, a form fill or a login binds `clue_vid` ↔ contact deterministically, on our terms, with
consent state recorded (P2). After that the browser is recognised on return for free (1.A linking),
so the expensive graph is queried only for visitors who are (a) unresolved, (b) US, (c) consented /
not GPC, and (d) from a target account or on an intent page. A graph reveal is a *candidate* that must
pass P3–P7 before it is asserted; its email is normalised (1.E), hashed, and taken to AI Ark for the
employer step (1.H), which is then cross-checked against the IP holder (P4).

**Efficiency, in one line:** identify once with a link, recognise for free thereafter, buy a reveal
only for the few who matter, and let every free identification calibrate the paid ones.

---

## 4. Implementation blueprint (extends WVI-1 §4 with the quality machinery)

### 4.1 Components

| # | Component | Inputs | Open-source / open-data base | Output |
|---|---|---|---|---|
| C1 | **Collector** — server hook on `/w/{ws}/p/{slug}` (no script) and `clue.js` + `POST /v1/collect` on client sites | token, `clue_vid`, IP, UA, accept-language, timezone/screen (ThumbmarkJS-class client hash, MIT), server TLS/header hash, referrer, UTM, page, dwell/scroll, consent state, GPC | ThumbmarkJS; Snowplow tracker/collector semantics | `web_visit_event` |
| C2 | **Exclusion service** — nightly refresh of cloud/VPN/Tor/datacenter/Private Relay/bot lists; ASdb category per AS | IP, UA | rezmoss, X4BNet, tn3w/IPSet, FireHOL, Apple egress CSV, isbot, device-detector, ASdb | `traffic_class` ∈ {enterprise, isp, hosting, vpn, relay, bot, unknown} |
| C3 | **Local IP→holder resolver** | IP | IPinfo Lite MMDB + Prefix2Org dataset + CAIDA AS2Org + RIR delegated-extended `reg-id` → RDAP/RIPEstat cache + PeeringDB names | holder org name, AS, category, confidence |
| C4 | **Curated IP vendor** (gated) | IP where C3 says isp/unknown **and** the visit matters | Snitcher API (later IPinfo Enterprise / Demandbase) | company + domain + `fuzzy` |
| C5 | **Company binding** | holder/company name, domain | `identity.resolve(Observation(domain))` `[REPO]`; Ditto/Splink for name-only matches; RPKI/AS2Org siblings | `account_entity_id` or `visiting_company` suggestion |
| C6 | **Visitor recognition** | `clue_vid`, client hash, server hash, IP, UA | FP-Stalker linking rules (server-side, tolerance-based) | `visitor_id` continuity across cookie loss |
| C7 | **Person resolution** | token → form/login → (gated) graph vendor → UID2-normalised hash → AI Ark reverse lookup → candidate | Leadpipe/Bullseye/RB2B webhook client; AI Ark client; Apollo/PDL hash fallback | candidate person + provenance |
| C8 | **Person binding** | candidate vs `contact_entity` (email, LinkedIn URL strong keys; then name+company+title) | Splink Fellegi–Sunter; Gravatar corroboration; LLM adjudication for the residue | STRONG / WEAK / unknown + score |
| C9 | **Consistency + policy gate** | candidate, IP holder, geo, consent, jurisdiction, cap | Doc D use gate, lawful basis, reveal cap ledger | assert / review / refuse |
| C10 | **Labels + calibration** | deterministic identifications ↔ probabilistic guesses for the same visitor | Splink EM, nightly job | per-method/provider precision, thresholds, demotions |
| C11 | **Audit harness** | a list of known people and a site | the Gartner-auditor method as a script | coverage + precision per rung, per site |
| C12 | **Writers** | everything above | `insert_claim`, `account_activity_event`, cost ledger, DSAR selectors `[REPO]` | claims, activity, ledger |

### 4.2 Schema deltas beyond WVI-1 §4.3

`visitor_fingerprint (visitor_id, client_hash, server_hash, components_json, first_seen, last_seen)` ·
`identification_label (visitor_id, contact_entity_id, account_entity_id, method, observed_at)` ·
`resolution_decision` append-only ledger `(event_id, method, provider, candidate_json, checks_json,
score, decision, decided_at)` · `provider_score (provider, window, n, precision, demoted)` ·
`ip_exclusion (cidr, class, source, refreshed_at)` · `ip_holder_cache (prefix, holder, as, category,
source, refreshed_at)`. All hash revision ids, one head, `make db-smoke`.

### 4.3 Decision procedure per visit (the ladder with the gates)

```
event → C2 exclude (bot/vpn/relay/hosting → class only, stop)
      → rung 0: token / form / login → STRONG contact (+account); write label
      → C6 recognise returning visitor → inherit prior STRONG binding if < 90 days and consistent
      → rung 1: C3 local holder → category gate → C5 bind account
                 if isp/unknown and (target page or high value) → C4 vendor → C5
      → rung 2 (only if US, consent ok, no GPC, account ∈ project or intent page, cap ok):
                 graph reveal → normalise+hash → AI Ark → candidate
                 → C8 score vs contacts → C9 checks (employer∈{holder,residential}, geo, freshness)
                 → ≥ threshold & two signals → STRONG; one signal → WEAK+review; else unknown
      → C12 write; C10 compares this decision to any label for the visitor
```

### 4.4 Expected numbers, honestly

| Rung | Precision target | Evidence it is reachable | Coverage (estimate) |
|---|---|---|---|
| 0 | ≈ 1.0 | deterministic | all outbound-driven visits |
| 1 (account) | ≥ 0.90 after exclusion + category gate | Prefix2Org 99% recall on validated space; ASdb 93% category accuracy; the loss is coverage on ISP ranges | 25–35% of B2B visits locally; more with a curated vendor |
| 2 (person) | ≥ 0.90 **only** with P3 corroboration | Zimmeck/ICDM ceilings 0.88–0.91 with anchors; vendor positives audited at 52–87% (1.J) → the corroboration step is what closes the gap | 10–25% of *gated* US visitors (vs vendor 15–45% claims) |

### 4.5 Phases (supersede WVI-1 §7 where they differ)

- **V0** — C1 (server hook), C2, C3, C5, rung 0 tokens, C10 labels, C12. No vendor. Gate: tracked
  visit shows on the contact within 60 s; a corporate-IP visit binds the account; a Private Relay
  visit is "unknown", not "Cloudflare".
- **V1** — `clue.js`, `/v1/collect`, consent/GPC/jurisdiction, C6 fingerprint linking, C11 harness,
  nightly calibration report. Gate: harness run on cluehq.ai with ≥20 known visitors; rung-1 precision
  ≥ 0.90 on labelled visits.
- **V2** — C4 (Snitcher) gated, C7 graph vendor POC (Leadpipe Platforms / RB2B webhooks), AI Ark
  reverse lookup, C8 Splink binding, C9 gate, provider scores. Gate: person-level precision ≥ 0.90 on
  the harness before `CLUE_WVI_PERSON_LEVEL=us_only` may be set for any workspace.
- **V3** — persona tie-breaker, intent weighting, Head-of-ABM tool, CRM outbox, Matched-Audience export.

### 4.6 What stays cheap

Local IP resolution, exclusion lists, fingerprint linking, Splink, labels and the audit harness are
all $0 and open-source. Paid calls are two, both gated: a curated IP lookup for visits that matter,
and a graph reveal + AI Ark lookup for US target-account visitors. WVI-1 §7's $21–63 per 10k visits
stands; V0–V1 cost nothing but compute.

---

## 5. Source list (this document; WVI-1 Appendix B covers the vendor pages)

Papers: <https://arxiv.org/abs/1905.01051> · <https://www.semanticscholar.org/paper/8d6fd3522bc80cb512c3bb1f93ce52643fb976a1> ·
<https://arxiv.org/pdf/2006.09511> · <https://sebastianzimmeck.de/zimmeckEtAlCross2017.pdf> ·
<https://arxiv.org/abs/1510.01175> · <https://www.semanticscholar.org/paper/24cfe9b5681b9d31a11c8b51f7c1c26e2ce11f6c> ·
<https://arxiv.org/pdf/1610.03928> · <https://arxiv.org/pdf/1612.07117> · <https://arxiv.org/abs/2203.06833> ·
<https://dl.acm.org/doi/10.1145/3038912.3052714> · <https://collaborate.princeton.edu/en/publications/de-anonymizing-web-browsing-data-with-social-networks/> ·
<https://deepakgouda.github.io/assets/pdf/IMC-2025-Prefix2Org.pdf> · <https://lizizhikevich.github.io/assets/papers/ASDB.pdf> ·
<https://arxiv.org/abs/2603.13649> · <https://ispcol.potaroo.net/2026-01/ip2org.html> · <https://arxiv.org/pdf/2605.21937> ·
<https://www.vldb.org/pvldb/vol14/p50-li.pdf> · <https://openproceedings.org/2025/conf/edbt/paper-81.pdf> ·
<https://aclanthology.org/2025.coling-main.8.pdf> · <https://arxiv.org/pdf/2409.04073> · <https://arxiv.org/pdf/2409.08185> ·
<https://arxiv.org/pdf/2506.14057> (SoK web tracking 2025)
Repos and open data: <https://github.com/fingerprintjs/fingerprintjs> · <https://github.com/thumbmarkjs/thumbmarkjs> ·
<https://github.com/abrahamjuliot/creepjs> · <https://github.com/privacy-tech-lab/cross-device-tracking> ·
<https://github.com/bikash/ICDM2015> · <https://github.com/alexeygrigorev/cikm-cup-2016-cross-device> ·
<https://catalog.caida.org/dataset/as_organizations> · <https://github.com/bgpkit/as2org-rs> ·
<https://github.com/InetIntel/Dataset-AS-to-Organization-Mapping> · <https://asdb.stanford.edu> ·
<https://asint.netsecurelab.org> · <https://stat.ripe.net/docs/02.data-api/> · <https://ipinfo.io/lite> · <https://iptoasn.com/> ·
<https://github.com/sapics/ip-location-db> · <https://github.com/O-X-L/geoip-asn> · <https://ipwhois.readthedocs.io/> ·
<https://github.com/rezmoss/cloud-provider-ip-addresses> · <https://github.com/painlessanalytics/datacenter-cloud-ip-lists> ·
<https://github.com/X4BNet/lists_vpn> · <https://github.com/tn3w/IPSet> · <https://iplists.firehol.org/> ·
<https://mask-api.icloud.com/egress-ip-ranges.csv> · <https://github.com/nlink-jp/icloud-relay-lookup> ·
<https://github.com/omrilotan/isbot> · <https://github.com/matomo-org/device-detector> ·
<https://github.com/IABTechLab/uid2docs/blob/main/docs/getting-started/gs-normalization-encoding.md> ·
<https://github.com/moj-analytical-services/splink> · <https://github.com/dedupeio/dedupe> · <https://github.com/zinggAI/zingg> ·
<https://github.com/megagonlabs/ditto> · <https://github.com/OlivierBinette/Awesome-Entity-Resolution> ·
<https://posthog.com/docs/product-analytics/identity-resolution> ·
<https://docs.snowplow.io/docs/pipeline/enrichments/available-enrichments/pii-pseudonymization-enrichment/> ·
<https://docs.gravatar.com/rest-api/> · <https://docs.ai-ark.com/reference/people-reverse-lookup.md> ·
<https://business.linkedin.com/marketing-solutions/insight-tag> · <https://globalprivacycontrol.org/>
Vendor claims and audits: <https://fingerprint.com/blog/fingerprintjs-fingerprint-pro-device-identification-accuracy-explained/> ·
<https://www.adexchanger.com/data-exchanges/2016-edition-marketers-guide-to-cross-device-identity/> ·
<https://truthset.com/data-accuracy/data-accuracy/> · <https://www.adweek.com/adweek-wire/massive-study-on-matching-households-and-email-addresses-finds-range-of-inaccuracies/> ·
<https://www.leadpipe.com/blog/rb2b-review/> · <https://www.barchart.com/story/news/993090/gartner-auditor-tests-rb2b-leadpipe-warmly-clearbit-6sense-leadfeeder-accuracy-results-vary-widely> ·
<https://fingerprint.com/blog/icloud-private-relay-detection/>
