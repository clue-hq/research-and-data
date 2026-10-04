# WVI-4 / 05: Building Clue's own person-level identity graph (no reseller)

**Status:** research note, 2026-10-03, branch `feature/website-deanonymization` at `e1e80a2e9`. Read-only
research; no code changed. Companions: `docs/specs/WVI-website-visitor-identification.md` (WVI-1),
`WVI-2-research-register-and-90pct-blueprint.md` (WVI-2), `WVI-3-implementation-plan.md` (WVI-3).

**Question.** The founder accepts the deterministic layer (Clue snippet + tracked link / UTM token) as
built. How does a company build its *own* browser/IP-to-person bindings from scratch, without reselling
RB2B-style vendors, and what can Clue specifically do?

**Evidence labels.** `[FETCHED]` read from the live page this session. `[SNIPPET]` search-result text
only, page not read. `[INFERRED]` my reasoning or arithmetic, shown so it can be checked. `[REPO]`
verified in this worktree. `[VENDOR]` a vendor's claim about itself (treat as marketing). "Not found"
means I looked and did not find it; it is never a guess.

---

## 0. The answer in one page

An identity graph is nothing more than a pile of **binding events**: moments where a browser (cookie,
device, IP at a time) and a person (email, hashed email, login) are observed together. Every vendor's
graph is built by owning or buying binding events at scale. RB2B, Retention.com, Warmly and Leadpipe all
get theirs from *other people's* consumer sign-ups (newsletters, publishers, retail sites) and cookie
aggregators; that is why their matches are US-only, consumer-email-first, and need a second B2B lookup.

Clue cannot buy scale cheaply, but it owns the one thing those vendors lack: **a short list of the exact
people it wants to recognise** (the buying committee per target account) and **the outbound channel
that sends those people links**. So Clue's own graph should be small, deterministic, and committee-shaped,
not a consumer graph.

Ranked in-house acquisition paths (detail and arithmetic in sections 2 to 8):

| Rank | Path | Coverage of target-account visitors (est.) | Precision | Time to value | Cost | Legal risk |
|---|---|---|---|---|---|---|
| 1 | Own deterministic events, widened: opaque path tokens on every Clue link, `clue.identify` on forms, logins | all link-driven visits; ~1.7 to 2.4% of other traffic via forms | ~1.0 | weeks (WVI-3 V0/V1) | engineering only | low (first party, processor) |
| 2 | Import the customer's existing bindings: HubSpot `hubspotutk`, Marketo `_mkto_trk`/`mkt_tok`, Mailchimp `mc_eid`, plus CRM contact sync | every past form-filler / email-clicker still holding the ESP cookie on that customer's domain | ~0.95 (it is the customer's own record) | 2 to 6 weeks per connector | engineering + OAuth review | low (same controller, same domain) |
| 3 | Click-IP ledger from Clue's own tracked clicks (opens mostly useless) to link a second device on the same home IP | small: only contacts who clicked, then return on another device from the same residential IP | 0.70 to 0.90 as a *candidate* [INFERRED] | 1 to 2 months after V0 | negligible | low to medium (needs disclosure; EU consent) |
| 4 | Committee narrowing ("which of the 6 known people is this?") from title-level behaviour, geo, time, device | every visit already bound to a target account | 0.20 to 0.45 for a named person; usable only as role-level hint [INFERRED] | 1 month | negligible | low if shown as a hint |
| 5 | Licensed raw identity data as an input to Clue's own resolver | the 15 to 45% person-level band vendors quote for US traffic [VENDOR] | vendor positives audited at 52 to 87% (WVI-2 1.J) before Clue's gates | 1 to 3 months to contract | ~$1.5k/mo to $500k/yr; minimums | medium to high (you inherit their consent chain; data-broker adjacency) |
| 6 | Cross-customer pixel co-op ("Clue Network") | ~0.5 to 3% at 100 customer sites [INFERRED]; vendors needed millions of sites for 30 to 45% | high per match (deterministic seeds) | years to matter | low cash, very high legal/ops | high (CCPA third party / sale, data-broker registration, CIPA s.631 capability test, EU near-impossible) |
| 7 | Publisher / newsletter partnerships passing subscriber identity | narrow and vertical-specific | high (email-keyed) | months per deal | CPM $50 to $100+ for B2B, plus a data deal most small publishers cannot legally make | medium to high for the publisher and Clue |

**Recommended phase order:** 1 and 2 now (they are V0/V1 additions), 3 and 4 as calibrated *candidate*
features in V2, 5 only behind WVI-3's gates if the founder still wants unknown-visitor naming, 6 and 7
deferred until a measured overlap test (section 9) shows they would pay, and only with a written legal
opinion.

---

## 1. How the incumbents actually got their bindings (so we know what "building" means)

| Vendor | Where the bindings come from | Scale claimed | Evidence |
|---|---|---|---|
| RB2B | "securely correlat[ing] ... first- and third-party cookies, device identifiers, and IP data" against a "permissioned publisher network"; US-only person level; claims "approximately 40-45% of qualified US-based traffic" at person level | not published | `[FETCHED]` <https://support.rb2b.com/en/articles/8891294-what-is-rb2b-and-how-does-it-work> |
| RB2B's network is Retention.com's | RB2B's recommended privacy-policy text sends visitors to opt out at `app.retention.com/optout`, the same URL Retention.com gives its own customers | n/a | `[FETCHED]` <https://support.rb2b.com/en/articles/8795972-updating-your-privacy-policy>, <https://support.retention.com/en/articles/8826172-do-i-need-to-update-my-privacy-policy> |
| Retention.com (ex GetEmails) | founder: "partnered with publisher networks for the identity info, which we capture and transfer to our customers"; Retention is "the middleman"; consent shown as "the date in the URL of where they opted into the publisher network" | 500M+ records `[SNIPPET]` | `[FETCHED]` <https://www.practicalecommerce.com/retention-com-founder-on-email-laundering> |
| Leadpipe | "partnerships with publishers, apps, and platforms that produce first-party identity data with consent", own "Orbit" pixel on 5M sites, customer batch uploads; deterministic by default ("We do not guess"); 24-hour refresh; "30-40%+ on US B2B traffic" | 280M verified profiles, 60B signals | `[FETCHED][VENDOR]` <https://www.leadpipe.com/blog/how-we-built-the-leadpipe-identity-graph/> |
| Warmly | 1st-party cookies are 93% of its dataset, bought via "cookie aggregators" ("the New York Times is one of the data sources who sells 1st party cookies to our cookie aggregators"); 3rd-party cookies 7%; fingerprinting it calls "80% accurate"; plus customer UTMs, form fills, and "Historical cookies" pulled from the customer's HubSpot | "Contact identification rate around 45%" [VENDOR] | `[FETCHED]` <https://help.warmly.ai/articles/5643444357-overview-of-warmly-s-data-data-quality>; waterfall "through five different data providers" `[FETCHED]` <https://help.warmly.ai/articles/3568026273-contact-level-identification> |
| Customers.ai | matches "browser fingerprint, device signals, and behavioral patterns against networks of shoppers with opt-in consent" | n/a | `[SNIPPET]` <https://customers.ai/contact-data-enrichment> |
| Vector | maps work emails to personal hashed emails (HEMs) and mobile ad IDs; its pixel "lives on Forbes, Wall Street Journal, and 400k+ other top publisher sites"; 15 to 30% of US traffic at contact level | n/a | `[SNIPPET]` <https://www.vector.co/websiteid>, <https://www.docket.io/resources/research/vector-review> |
| Userled | tracked links (contact and account level), Clearbit/6sense IP, outreach email clicks ("often leads to a boost of 20~30% net new identities"), CRM, HubSpot pixel co-load; no cross-customer network | n/a | `[FETCHED]` <https://intercom.help/userled/en/articles/9515210-identity-layer> |
| Common Room | standard ID plus "enhanced" ID "powered by Vector" for US traffic; identity calls and link tracking each said to lift de-anonymisation "by over 50%" | n/a | `[FETCHED]` <https://www.commonroom.io/playbooks/make-anonymous-web-visits-actionable-with-enhanced-website-visitor-identification/>; lift figure `[SNIPPET]` <https://www.commonroom.io/blog/best-website-visitor-identification-tool/> |
| Bombora (B2B co-op, account level, not person) | members "deploy Bombora's proprietary JavaScript tag" and get co-op insights back; "86% of data within the Co-op is shared exclusively with Bombora"; 1,765+ sites added in two years; about 5,000 sites `[SNIPPET]` | account-level intent only | `[FETCHED]` <https://bombora.com/co-op/> |
| Apollo / ZoomInfo (contributory networks for *contact data*, not browsers) | Apollo: 2M+ users contribute via inbox connections and CRM syncs; ZoomInfo Community Edition: 200,000+ members let it analyse email signatures in exchange for free access | n/a | `[SNIPPET]` <https://www.apollo.io/product/b2b-data>, <https://pipeline.zoominfo.com/sales/how-does-zoominfo-get-data> |
| LiveIntent / Zeta (newsletter identity) | ad tags inside publishers' newsletters carry the subscriber's email or hash; "235 million unique hashed email addresses per month" across "2,000 premium global newsletters" | acquired by Zeta for ~$250M (2024) | `[SNIPPET]` <https://ppc.land/zeta-global-to-acquire-liveintent/>, <https://pulse2.com/zeta-global-to-buy-liveintent-in-250-million-deal/> |

**What this says.** Nobody "built" a person-level B2B graph from their own customers' sites alone.
Every network is a consumer identity supply (newsletters, retail, publisher log-ins) plus a B2B
enrichment step. The ones that are honest about their own capture (Userled, Warmly's UTM/HubSpot path,
Common Room's "identity calls") describe exactly the deterministic layer the founder already accepted.
Leadpipe's own build-vs-buy page (a vendor arguing against building) puts a from-scratch graph at
"$500K-$2M+" year one, "12-18 months to MVP", data licensing "$200K-$500K/yr", and "5-10%" initial match
rates `[FETCHED][VENDOR]` <https://www.leadpipe.com/blog/identity-resolution-for-platforms-build-vs-buy-vs-embed/>.
I found no independent figure to check those numbers against (Not found).

---

## 2. Path: own deterministic events, widened (baseline the founder accepted)

Already specified in WVI-3 (tracked `?cl=` token, `clue.identify({email})`, server-side capture on
Clue-hosted pages). Three findings from this round change *how* it should be built:

1. **Query-parameter tokens get stripped.** Firefox strips `mc_eid`, `_hsenc`, `mkt_tok` and others in
   its tracking-protection modes; Brave removes `mkt_tok` except on unsubscribe URLs `[SNIPPET]`
   <https://www.bleepingcomputer.com/news/security/new-firefox-privacy-feature-strips-urls-of-tracking-parameters/>,
   <https://github.com/brave/brave-browser/wiki/Query-String-Filter>. Apple's Link Tracking Protection
   strips known parameters in Mail, Messages and Safari Private Browsing; the list is unpublished, `mc_eid`
   is "reliably reported", UTMs survive `[SNIPPET]`
   <https://www.terminusapp.com/blog/ios-17-link-tracking-protection-what-survives/>. Clue's `cl=` is not on
   any list today, but these lists are curated remotely. **Implication [INFERRED]:** mint the token in the
   *path* of a Clue redirect (`t.cluehq.ai/c/<token>` → 302 to the destination, setting the cookie on the
   way) rather than only as a query parameter. Salesloft does the same (`slft.co/abc123` redirect, plus an
   `sbrc` parameter for its Live Website Tracking cookie, a "Persistent/1000days" `site_identity` cookie)
   `[SNIPPET]` <https://support.salesloft.com/hc/en-us/articles/115005958843-Live-Website-Tracking->.
2. **Security scanners click first.** Microsoft Defender Safe Links, Proofpoint URL Defense, Mimecast and
   Barracuda rewrite and pre-visit links; one practitioner source puts non-human B2B clicks at "20-80%"
   `[SNIPPET]` <https://emailcalculator.com/blog/bot-clicks-are-lying-to-you>,
   <https://mailtester.com/blog/filter-microsoft-defender-bot-clicks-email-analytics/>. A token must not
   bind on a request from a datacenter/security-vendor ASN or with no JS execution; bind on the first
   *human* hit (JS beacon from the landing page), as WVI-3 already does for `LinkedInBot`.
3. **Safari caps script-set cookies at 7 days of inactivity**, and caps cookies on CNAME-cloaked
   subdomains the same way `[SNIPPET]` <https://webkit.org/tracking-prevention/>,
   <https://stape.io/blog/safari-itp>. A binding made by JS on a Safari visitor decays in a week unless
   re-established; a server-set first-party cookie from the customer's *own* origin (not a CNAME to Clue)
   lasts longer. This sets the realistic half-life of every first-party binding Clue owns.

Coverage: all link-driven visits (precision ~1.0 after bot filtering); for untracked traffic, form fills
are the only deterministic source, and B2B form conversion medians are about 1.7% (forms) to 2.4%
(contact forms) `[SNIPPET]` <https://www.flint.com/articles/b2b-website-traffic-lead-conversion-statistics>,
<https://www.wearetg.com/blog/b2b-website-conversion-rates/>.

---

## 3. Path: hashed-email capture and importing the customer's existing bindings (item 3)

This is the cheapest large lift and it is not a "graph" at all: the customer already has thousands of
browser-to-person bindings sitting in its marketing tools, on its own domain.

| Source | What it is | How Clue turns it into a binding | Evidence |
|---|---|---|---|
| HubSpot `_hsenc` / `_hsmi` | `_hsenc` is per-recipient ("identity-bound"), `_hsmi` per-message, on every link in HubSpot-sent marketing email | Clue cannot decode `_hsenc` itself (Not found: no public decode). The usable path is the cookie HubSpot sets after the click (below) | `[SNIPPET]` <https://linkclean.app/trackers/hsenc/>, <https://community.hubspot.com/t5/Reporting-Analytics/Need-definitions-for-HubSpot-parameters/td-p/634937> |
| HubSpot `hubspotutk` | HubSpot's visitor token cookie; HubSpot links it to a contact on form submit or tracked-email click | `clue.js` reads `hubspotutk` on the customer's domain, the backend calls HubSpot's contacts-by-user-token endpoint with the customer's OAuth grant and gets the contact's email. The endpoint is **legacy v1** (`GET /contacts/v1/contact/byUtk/batch/`, scopes `crm.objects.contacts.read` + `.write` + `content`), so it may be retired | `[FETCHED]` <https://developers.hubspot.com/docs/api-reference/legacy/crm/objects/contacts/v1/get-contacts-v1-contactbyUtk-batch>; cookie names `[SNIPPET]` <https://developers.hubspot.com/docs/api-reference/legacy/tracking-code-v1/overview>. Whether `hubspotutk` is JS-readable on every portal: [INFERRED] yes (HubSpot's forms integrations pass it as `hutk`), verify on a live portal |
| Marketo `mkt_tok` + Munchkin `_mkto_trk` | "Each mkt_tok is specific to an email send + lead combo"; Munchkin uses it to "associate a previously anonymous Munchkin cookie with the known lead" | read `_mkto_trk` on the customer's domain and query Marketo's REST lead API by cookie [INFERRED from the Leads API page appearing in results; filter by cookie not verified] | `[SNIPPET]` <https://experienceleaguecommunities.adobe.com/adobe-marketo-engage-general-27/question-around-pre-fill-data-in-forms-and-mkt-tok-189393>, <https://experienceleague.adobe.com/en/docs/marketo-developer/marketo/rest/lead-database/leads> |
| Mailchimp `mc_eid` / `mc_cid` | `mc_eid` is "the unique, MailChimp-generated ID for the list member"; added automatically when link tracking is on | capture `mc_eid` on landing, look the member up in the customer's audience via the Mailchimp API [INFERRED: lookup by unique email id not verified] | `[SNIPPET]` <https://linkclean.app/trackers/mc-eid/>; LiveIntent uses the same `*\|EMAIL_UID\|*` merge tag to identify subscribers `[FETCHED]` <https://knowledgebase.zetaglobal.com/liveintent/esp-event-configuration-instructions-mailchimp> |
| Salesloft / Outreach | Salesloft: `slft.co` redirect + `sbrc` parameter + `site_identity` cookie when Live Website Tracking is on; Mutiny reads its own `mtl=<token>` the same way | Clue can recognise the parameter's presence and channel; mapping `sbrc` to a person via a Salesloft API: Not found | `[SNIPPET]` <https://support.salesloft.com/hc/en-us/articles/115005958843-Live-Website-Tracking->, <https://help.mutinyhq.com/hc/en-us/articles/26571961919899-Integrating-with-Salesloft> |
| Form fills on the customer's site | the classic identify call | `clue.identify({email})` (WVI-3), normalise and SHA-256 per UID2 (WVI-2 1.E) | WVI-3 0.3 |
| CRM / MAP historical cookies | Warmly: "By syncing Hubspot, we can pull in our customers' Historical cookies already assigned in past years" | one-time backfill: every `hubspotutk` HubSpot already holds for the customer's contacts becomes a Clue binding on that customer's domain | `[FETCHED]` <https://help.warmly.ai/articles/5643444357-overview-of-warmly-s-data-data-quality> |

**Why this ranks second.** Precision is the customer's own record (~0.95; the residual is shared
computers and forwarded emails [INFERRED]). Coverage is every past form-filler and email-clicker who still
holds the cookie, which for an established HubSpot customer is plausibly thousands of contacts
[INFERRED; no published figure, Not found]. Legally it is the cleanest path after the token: same
domain, same controller, Clue acting as the customer's processor/service provider, nothing crosses to
another customer. The work is OAuth app review per MAP and handling the legacy HubSpot endpoint.

**What it does not do:** recognise someone the customer has never captured. That is the gap every
"graph" is trying to fill, and the remaining paths show how expensive it is.

---

## 4. Path: email open and click IP mapping (item 2)

**Precondition from the repo.** Clue does **not** send email today: no SMTP/ESP client, no
`send_email`, no sequencing code in `platform/`, `libs/`, `subsystems/research/` or the design API at
`e1e80a2e9` `[REPO]` (searched for sendgrid/smtp/postmark/mailgun/send_email/gmail). WVI-3 already plans
outbound links as "the rep copies a tracked link" (V0) to automatic minting (V3). So open tracking is not
available unless Clue becomes the sender; click IPs are available through Clue's own redirect.

**Opens are mostly proxied, so their IP is not the reader's.**

- Apple Mail Privacy Protection pre-fetches images through Apple proxies at delivery time; the IP is an
  Apple relay "in the user's general region", sometimes a different state `[SNIPPET]`
  <https://bird.com/en-us/guides/apple-mail-privacy-protection-s-impact-on-email>.
- Gmail fetches images through Google's proxy (`googleusercontent.com`, UA "via ggpht.com
  GoogleImageProxy"), hiding the reader's IP `[SNIPPET]`
  <https://www.suped.com/learn/email-deliverability/how-does-gmails-image-proxy-affect-email-open-tracking-and-what-could-cause-very-fast-opens>.
- Litmus, July 2026: Apple 62.26%, Gmail 27.03%, Outlook 5.83% of opens; MPP touches "roughly 55-60%" of
  opens `[FETCHED]` <https://www.litmus.com/email-client-market-share>.
- **Arithmetic [INFERRED]:** at most ~10% of opens (Outlook plus long tail) can carry a real client IP,
  and corporate Outlook often loads images through an office egress or a cloud proxy, which names the
  company, not the person. Usable residential-IP opens are therefore low single digits of all opens.
  Open-IP mapping is not worth building.

**Clicks carry the real browser IP** (the browser hits Clue's redirect). Their marginal value over the
token is **cross-device**: contact X clicks on a phone at home, and two days later an untokenised desktop
browser on the same home Wi-Fi visits the customer's site.

How durable is that IP?

- CAIDA/Akamai DynamIPs: fixed-line addresses in ARIN "have very long and stable durations; the median
  duration is 100 days"; mobile addresses have "medians very near one day"; some ISPs renumber every
  24 h to 2 weeks (Germany, Orange, BT) `[FETCHED]` <https://www.caida.org/catalog/papers/2020_dynamips/dynamips.pdf>.
- Mishra et al. (WWW 2020): "87% of participants retain at least one IP address for more than a month";
  IP alone respawned 25.68% of deleted cookies `[SNIPPET]`
  <https://www.researchgate.net/publication/341125245_Don't_Count_Me_Out_On_the_Relevance_of_IP_Address_in_the_Tracking_Ecosystem>.
- CGNAT: "more than 90% of all cellular ASes" deploy carrier-grade NAT; 17 to 18% of eyeball networks
  overall `[SNIPPET]` <https://arxiv.org/pdf/1605.05606>. A mobile IP is shared and changes daily: useless.
- Office IPs are shared by hundreds of people, and corporate VPN / Zscaler egress names the security
  vendor, not the employer `[SNIPPET]` <https://streamkap.com/resources-and-guides/ip-to-company-enrichment>.
- About 26% of US paid full days are worked from home (WFH Research, Sept 2026) `[SNIPPET]`
  <https://wfhresearch.com/wp-content/uploads/2026/08/WFHResearch_updates_September2026.pdf>, so a
  meaningful share of B2B visits arrive from home IPs, which is exactly where this path works.
- Published ceilings for IP-anchored linking: Zimmeck et al. precision 0.88 on a small set; ICDM 2015
  winners F0.5 ≈ 0.85 to 0.88 (WVI-2 1.B).

**Rule that keeps precision near the bar [INFERRED]:** a click-IP becomes a *candidate* binding only if
the IP is residential fixed-line (not hosting, not relay, not a CGNAT/mobile ASN, not a known office
range), the later visit is within 14 days, exactly one known contact is bound to that IP in the window,
and the visit is to that contact's customer workspace. Expected precision 0.70 to 0.90 (household members
rarely browse the same B2B vendor; the failure is a spouse or housemate in the same industry, or a
re-assigned IP). Written as `identity_binding=WEAK`, `decision=review`, never asserted. Coverage is small:
only contacts who clicked and later return on a second device from home.

**Who does this commercially:** Warmly lists "email pixel correlations" among its signals `[SNIPPET]`
<https://help.warmly.ai/articles/3568026273-contact-level-identification>. No vendor documentation
describing an open-IP or click-IP to person method in detail was found (Not found).

---

## 5. Path: probabilistic matching against the known committee (item 5)

Clue's unusual asset: for a target account it already holds the buying committee (`committee_member_ids`
per research run `[REPO]` `platform/api/clue_api/account_research_coverage.py:75-84`), each contact's
`linkedin_url`, `verified_email` and `geo` (`[REPO]` `subsystems/research/clue_research/identity/entities.py:118,196-212`),
and a `contact.current_location` claim (`[REPO]` `docs/specs/ARV2-DATA-SOURCE-MAP.md:227`). So the
question shrinks from "who on earth is this" to "which of these ~6 people, if any".

The honest arithmetic [INFERRED]:

- **Prior.** Given an account-level hit (reverse IP or a per-account Clue page), the visitor is one of the
  k committee members with some probability q, and an uncommitteed employee with 1 − q. q is unknown and
  depends on outreach: for a page Clue sent to the committee, q is high; for organic traffic from a
  10,000-person company, q may be well under 0.2. Uniform over k = 6 gives 0.17 per person *times* q.
- **Geo.** MaxMind GeoIP2 City is about 66 to 68% correct within 50 km for US IPs `[SNIPPET]`
  <https://support.maxmind.com/knowledge-base/articles/maxmind-geolocation-accuracy>. Committee members of
  one company usually share a metro, so geo separates them only when someone is remote in a different
  metro. Office egress IPs geolocate to the egress, not the person.
- **Behaviour.** Behaviour-only linking reaches F1 ≈ 0.40 to 0.42 (CIKM Cup 2016, WVI-2 1.B). Pricing
  pages lean economic buyer, docs and API pages lean technical evaluator, but this is a lean, not an ID.
- **Time zone / device / time of day.** Weak; they mostly discriminate the same things geo does.
- **Result.** Even with all features, naming *one person* is right perhaps 20 to 45% of the time when the
  visitor is in the committee, and lower when q is low. That is far below the 0.90 bar.

**What it is good for:** a role-level hint ("likely finance or the economic buyer, 2 of 6 committee
members fit") and a ranking of which committee member to contact next. It becomes a *named* candidate
only when a deterministic anchor exists (section 4's click-IP within days, or a returning `clue_vid`).
Calibrate on the WVI-3 known-visitor test (≥20 known people), and publish the measured precision per band
before any name is shown.

---

## 6. Path: cross-customer pixel co-op, the "Clue Network" (item 1)

**Mechanics.** Every customer site running `clue.js` contributes bindings when any visitor identifies on
any customer site; a later anonymous visit to a different customer's site is matched. Because each
customer site is a different domain, the cross-site join needs one of: a third-party cookie on a Clue
domain (works in Chrome and Edge, which still allow them by default; Safari and Firefox block them, WVI-1
1.3), link decoration between sites (rare for unrelated companies), or IP + user-agent + time heuristics
(section 4's precision problem at much larger scale).

**How big must it be? [INFERRED, arithmetic shown].**

- Identification events: 100 customer sites × 20,000 monthly visitors × 2% identify ≈ 40,000 bindings a
  month, roughly 480,000 a year before cookie decay (Safari's 7-day cap, device churn); call it 250,000
  to 480,000 live browsers.
- Relevant population: tens of millions of US B2B decision-makers' browsers (assume 50M).
- Random overlap: 250k to 480k / 50M ≈ 0.5 to 1% of a customer's visitors are already in the pool.
  Vertical concentration (customers selling to the same buyers) might multiply that by 3 to 5, giving 1.5
  to 5%.
- Cross-domain join success (third-party cookie only in Chrome/Edge, ≈78% of US *desktop* page views in
  August 2026: Chrome 65.55%, Edge 12.81% `[SNIPPET]`
  <https://gs.statcounter.com/browser-market-share/desktop/united-states-of-america>; lower overall once
  mobile Safari is included) gives roughly **0.5 to 3% person-level coverage at 100 customer sites**.
- For comparison, Leadpipe says a fresh build starts at 5 to 10% (with licensed data) and its mature
  network spans 5M sites for 30 to 40% `[FETCHED][VENDOR]`; Bombora needed thousands of sites for
  *account-level* intent `[FETCHED]`. Clue would need thousands of customer sites in overlapping verticals
  before a co-op beats the paths above. No published threshold ("network must be N sites for M% match")
  was found (Not found).

**Consent language the networks use.** RB2B and Retention.com both ask the site owner to publish: "cookies
and similar technologies may be used by our online data partners or vendors to associate these
activities with other personal information they or others have about you, including by association with
your email ... We (or service providers on our behalf) may then send communications and marketing ...",
with an opt-out link, and RB2B adds "Compliance responsibility rests entirely with you" `[FETCHED]`
<https://support.rb2b.com/en/articles/8795972-updating-your-privacy-policy>,
<https://support.retention.com/en/articles/8826172-do-i-need-to-update-my-privacy-policy>. Customers.ai
leans on CAN-SPAM and "opt-in" networks `[SNIPPET]`. Bombora requires members to "execute an agreement"
and deploy its tag `[SNIPPET]` <https://bombora.com/blog/b2b-intent-data-explained-privacy-compliance/>.

**Legal structure (why this is the expensive path).**

- **CCPA/CPRA: Clue stops being a service provider.** The regulations let a service provider use data to
  improve its service only where it "does not use the personal information to perform services on behalf
  of another person"; it "shall not combine" opted-out consumers' data received from one business with
  data from another business or its own collection; and a vendor providing cross-context behavioural
  advertising "is a third party and not a service provider" `[FETCHED]`
  <https://www.law.cornell.edu/regulations/california/11-CCR-7050> (11 CCR 7050(a)(3), (b)). A co-op uses
  customer A's visitors to serve customer B, so for that use Clue is a third party and each contributing
  site is "selling" or "sharing": every site needs a "Do Not Sell or Share" link and must honour GPC.
- **Data-broker registration.** California defines a data broker as a business that "knowingly collects
  and sells personal information about consumers with whom it does not have a direct relationship"; it
  must register annually, and since 1 August 2026 must access DROP "at least once every 45 days" and
  process deletions; penalties $200 per day per unfulfilled request `[FETCHED]`
  <https://www.coblentzlaw.com/news/navigating-californias-data-broker-requirements-in-2026/>. The 2026
  registration fee is reported as $6,000 `[SNIPPET]` <https://www.datagrail.io/glossary/what-are-the-delete-act-and-drop/>.
  Over 475,000 Californians had used DROP by August 2026, and CalPrivacy has acted against brokers for
  late registration (LocateSmarter; Cybba, Inc.) `[FETCHED]`
  <https://www.gov.ca.gov/2026/08/13/icymi-california-takes-historic-action-against-data-brokers/>.
  Vermont ($100), Texas ($300) and Oregon ($600) run their own registries `[SNIPPET]`
  <https://secureprivacy.ai/blog/data-broker-registration>. A Clue co-op that reveals people to
  customers they never dealt with fits the definition [INFERRED].
- **CIPA s.631 "capability" test.** Some California courts hold a third-party script provider liable
  when it has "the capability to use the user data to its benefit, regardless of whether or not it
  actually did so" (Javier v. Assurance IQ line) `[SNIPPET]`
  <https://www.lexology.com/library/detail.aspx?g=ddf4ee87-6946-499f-b116-24a2448fae89>. A co-op is that
  capability by design. SB 690, **signed 30 September 2026, operative 1 January 2027**, ends the private
  right of action only for s.638.51 pen-register claims and leaves s.631/632 untouched `[FETCHED]`
  <https://www.cyberadviserblog.com/2026/10/governor-newsom-signs-sb-690-ending-the-private-right-of-action-under-cipas-pen-register-and-trap-and-trace-provision/>.
  (This updates WVI-1 1.4, which recorded SB 690 as passed but unsigned.)
- **EU/UK.** ePrivacy Art. 5(3) requires consent before storing or reading anything on the device, and the
  EDPB says tracking pixels and tracking URLs are "unlikely to escape" it `[SNIPPET]`
  <https://www.bclplaw.com/en-US/events-insights-news/edpb-explains-eu-eprivacy-cookie-rules-apply-to-emerging-online-tracking-tools.html>.
  Under Fashion ID (CJEU C-40/17, 2019) a site embedding a third party's collector is joint controller for
  "the collection and transmission" `[SNIPPET]` <https://gdprhub.eu/index.php?title=CJEU_-_C%E2%80%9140/17_-_Fashion_ID>.
  Every vendor geofences person-level to the US (WVI-1 1.3). A co-op is effectively US-only.
- **Hashing is not anonymisation.** The FTC: "Hashing is just one tool used in persistent user
  identification" `[FETCHED]` <https://www.ftc.gov/policy/advocacy-research/tech-at-ftc/2024/07/no-hashing-still-doesnt-make-your-data-anonymous>.
  Pooling hashed emails does not take a co-op out of scope.

**Verdict.** Low cash cost, highest legal and operational cost, and near-zero coverage at Clue's current
scale. Defer. If ever built, make it an explicit opt-in tier with contributing customers' consent
language, US-only, GPC-honouring, with Clue registered as a data broker and integrated with DROP.

---

## 7. Path: publisher partnerships and buying first-party data (item 4)

- **The working model is LiveIntent's**: newsletter publishers place ad tags in their templates that carry
  the subscriber's email (or MD5/SHA-1/SHA-256 hash) as a parameter, or wire the ESP's per-subscriber id
  (`*|EMAIL_UID|*` in Mailchimp) into tags and links `[SNIPPET]` <https://support.liveintent.com/how-to-implement-livetag-3-0/>,
  `[FETCHED]` <https://knowledgebase.zetaglobal.com/liveintent/esp-event-configuration-instructions-mailchimp>.
  That is a publisher disclosing subscriber identity for advertising: a "sale/share" by the publisher
  under CCPA, needing its privacy policy and opt-out to cover it [INFERRED from 7050 above].
- **Self-serve newsletter platforms do not hand identity to advertisers.** beehiiv's advertiser pixel is
  for "the effectiveness of your newsletter campaign"; its docs do not say subscriber identity is shared
  `[FETCHED]` <https://www.beehiiv.com/support/article/35763267725591-implementing-the-beehiiv-pixel-for-advertisers>.
  beehiiv is "actively working on" subscriber-level targeting across 60,000 publishers `[SNIPPET]`
  <https://www.adexchanger.com/publishers/why-beehiiv-is-betting-on-programmatic-to-scale-its-ad-platform-for-newsletters/>.
  Substack and ConvertKit sponsorship identity programmes: Not found.
- **Costs.** Newsletter CPMs "$10 to $75"; specialised B2B "$50-$100+"; mid-size (5k to 50k subscribers)
  placements "$500-$3,000" `[FETCHED]` <https://www.beehiiv.com/blog/newsletter-sponsorship-cost>.
  Consented B2B leads via content syndication cost about $35 to $175 per lead depending on targeting
  `[SNIPPET]` <https://revnew.com/blog/content-syndication-pricing-models>.
- **What Clue could do legitimately [INFERRED]:** sponsor vertical newsletters with *Clue-tokenised links
  per edition* (account/channel attribution, not person), and, where a publisher has explicit consent,
  agree a per-subscriber token passed in the click (the publisher's merge tag mapped to a Clue token).
  That gives deterministic person bindings for the readers who click, at a few dollars to tens of dollars
  per click, but only with publishers whose privacy terms permit it. It is business development, not
  engineering, and it scales one deal at a time.

---

## 8. Path: licensing raw identity data as an input to Clue's own resolver (item 6)

This is what RB2B does (it rides Retention.com's network, section 1). Bought as a *resolver input* behind
WVI-2's gates, it is the only path that names never-captured visitors at vendor-like coverage.

| Supplier | What you get | Published price / minimum | Evidence |
|---|---|---|---|
| BIGDBM | consumer identity graph ("280M+ U.S. Consumer Identities", HEM ↔ device/IP), real-time API | quote-only; monthly licences "start at $1,500 / month"; annual minimums | `[SNIPPET]` <https://datarade.ai/data-providers/bigdbm/profile>, <https://tomba.io/blog/bigdbm-pricing-reviews-pros-and-cons>; graph stats `[FETCHED]` in WVI-1 |
| AtData | Website Visitor ID: pixel matches unknown users to a hashed email, deliverable email or postal address | "minimum investment of $10,000", custom; IP/UA data at a 20 to 25% premium; Email Append $0.20 to $0.05 per match | `[SNIPPET]` <https://atdata.com/pricing/> (page fetch returned contact text only) |
| FullContact | Resolve/Enrich, accepts MD5/SHA-256 email, MAIDs | "starts at $99 per month"; enterprise custom, annual | `[SNIPPET]` <https://pipeline.zoominfo.com/sales/fullcontact-pricing> |
| Leadpipe (Platforms / agency) | API, pixel minting, white label | agency/platform "$1,979/month for 20,000 IDs"; build-vs-buy page "From $23,748/year" | `[SNIPPET]` <https://www.leadpipe.com/blog/b2b-identity-resolution-api-guide/>; `[FETCHED][VENDOR]` build-vs-buy page above |
| LiveRamp, Experian, Oracle class | enterprise identity | "$300K-$500K/yr", "6-12 months from initial contact to live data" | `[FETCHED][VENDOR]` (Leadpipe's characterisation; not independently verified) |
| AWS Entity Resolution | matching service only, provider licence separate | "$0.25 per 1,000 records" rule/ML matching | `[SNIPPET]` <https://www.leadpipe.com/blog/identity-resolution-for-platforms-build-vs-buy-vs-embed/> |

**Build vs license [INFERRED].** Licensing gets you the consumer HEM ↔ device/IP layer; Clue already
owns the B2B step (AI Ark reverse lookup from email, Apollo `people/match` accepting `hashed_email`
`[REPO]` `docs/specs/ARV2-apollo-api-contract.md:80-82`). Accuracy of these consumer graphs varies two-fold
across providers (Truthset/Adweek, WVI-2 1.E), so every input must be scored against Clue's own
deterministic events. Legally Clue inherits the supplier's consent chain: get the supplier's consent
records, data-broker registrations and suppression feeds in the contract, and keep the WVI-3 gates (US,
not GPC, consented, target account, cap).

---

## 9. Legal guardrails by path (item 7, consolidated)

| Path | US (CCPA/CPRA + states) | CIPA | Data broker | EU/UK |
|---|---|---|---|---|
| 1 Own tokens, forms | Clue as service provider; notice at collection; GPC | consent banner before script in CA reduces s.631 risk; s.638.51 private suits end 1 Jan 2027 | no | consent for cookies (ePrivacy); person-level by consent only |
| 2 Customer's MAP/CRM bindings | same controller, processor contract | same as 1 | no | same as 1 |
| 3 Click IP | disclose IP collection in link context; processor | low (Clue's own redirect, not a third-party script) [INFERRED] | no | tracking URLs in Art. 5(3) scope per EDPB `[SNIPPET]`: consent or skip |
| 4 Committee hint | profiling disclosure; show as hint | n/a | no | legitimate interest arguable for company-level; person-level needs consent |
| 5 Licensed graph | Clue receives purchased PI; customer must disclose third-party enrichment; GPC suppression | vendor-script analogue; keep consent-first in CA | suppliers are brokers; Clue may become one if it resells [INFERRED] | do not use |
| 6 Co-op | third party, "sale/share" by every contributor (7050) | capability test makes Clue the paradigm defendant | very likely yes: CA $6,000 + DROP every 45 days; VT/TX/OR | effectively unavailable |
| 7 Publisher | publisher's sale/share; Clue a third party recipient | n/a | possibly | consent per subscriber |

Email open tracking itself: the Arizona "spy pixel" wave under TUCSRA failed; the Arizona Court of
Appeals held the statute does not apply to marketing-email pixels (Smith v. Target, 13 Nov 2025)
`[SNIPPET]` <https://natlawreview.com/article/arizona-court-appeals-affirms-dismissal-arizona-spy-pixel-class-action>.
In the EU, email tracking pixels need consent under Art. 5(3) `[SNIPPET]`
<https://maciejturek.com/resources/email-tracking-pixel-consent-rules.html>.

No reported lawsuit or regulator action naming RB2B, Leadpipe, Customers.ai or Retention.com
specifically was found (Not found); the GDPR "DPAs have ruled against vendors resolving EU traffic"
claim appears only in a vendor blog without a cited decision `[SNIPPET]`
<https://www.leadpipe.com/blog/visitor-identification-in-germany/> (treat as unverified).

---

## 10. What Clue already has that helps (verified in the repo)

| Asset | Where | Which path it serves |
|---|---|---|
| Per-account hosted pages `/w/{workspace_id}/p/{slug}`, slug `abm-<account>` | `subsystems/clue-design/apps/api/lumen_api/main.py:5492` (route), `:7447-7465` (CP2 account slug) `[REPO]` | 1 (server-side capture; page is account-scoped) |
| Published page CSP `connect-src 'none'` (no client beacon; capture must be server-side) | `subsystems/clue-design/apps/api/lumen_api/web_export.py:1264-1288` (per WVI-3) `[REPO]` | 1, 3 |
| Buying committee per account run (`committee_member_ids`) | `platform/api/clue_api/account_research_coverage.py:75-84` `[REPO]` | 4 |
| Contact strong keys `linkedin_url`, `verified_email`, plus `geo` | `subsystems/research/clue_research/identity/entities.py:105-136,196-212` `[REPO]` | 2, 3, 4, 8 |
| `contact.current_location` claim for display | `docs/specs/ARV2-DATA-SOURCE-MAP.md:227` `[REPO]` | 4 (geo feature) |
| Apollo resolver; `people/match` accepts `email` or `hashed_email` | `subsystems/research/clue_research/resolvers/apollo/`; `docs/specs/ARV2-apollo-api-contract.md:80-82` `[REPO]` | 2, 5, 8 (email to person/employer) |
| AI Ark reverse lookup (0.5 credit, email to LinkedIn) | contract only, `docs/specs/ARV2-ai-ark-contract-notes.md:31`; no AI Ark client in code yet (WVI-3 §5) `[REPO]` | 5, 8 |
| CRM import resolver (tier-1, vendor-agnostic connector seam) | `subsystems/research/clue_research/resolvers/crm/__init__.py` `[REPO]` | 2 (the natural home for HubSpot/Marketo binding import) |
| Jurisdiction switch, use classes, lawful basis, use gate, DSAR | `libs/clue-config/clue_config/policy.py:30`; `subsystems/research/clue_research/compliance/` `[REPO]` | all (gates and erasure) |
| Redis token bucket (`RateLimiter`) | `libs/clue-locks/clue_locks/rate_limit.py:43-69` (per WVI-3) `[REPO]` | collector abuse control |
| **Not present:** outbound email sending, open/click tracking, LinkedIn message sending | searched `platform/`, `libs/`, `subsystems/research/`, design API `[REPO]` | 3 depends on Clue's redirect, not on sending |

---

## 11. Recommended phased path

1. **Now (add to WVI-3 V0/V1).** Path-token redirect (`t.cluehq.ai/c/<token>`) in addition to `?cl=`,
   human-hit binding with scanner/ASN filtering, `clue.identify` on forms. Log the click IP into the
   `visitor_resolution` ledger as evidence only.
2. **V1.5 (2 to 6 weeks per connector).** HubSpot first: read `hubspotutk` in `clue.js`, resolve through the
   customer's OAuth grant, plus a one-time backfill of historical tokens; then Marketo `_mkto_trk`, then
   Mailchimp `mc_eid`. Build as `CRMConnector` implementations behind the existing CRM resolver seam.
   Track the HubSpot v1 deprecation risk.
3. **V2 (candidates, never assertions).** Click-IP second-device candidates under the section 4 rule;
   committee role hints under section 5. Both write `WEAK` + `review`, and both are scored against the
   known-visitor test before any name is displayed.
4. **V2, only on founder ruling.** A licensed HEM/device graph as a gated resolver input (section 8), or
   the WVI-3 Leadpipe/RB2B control, chosen by measured precision on the same test set.
5. **Deferred.** Co-op and publisher identity deals. Before spending legal money, run a **non-personal
   overlap test**: count how many target-account *domains* recur across Clue workspaces (company domains
   are not personal data). If customers' target lists barely overlap, a co-op can only ever re-identify
   people Clue already reaches by link, and the question is closed.

**Rulings to add** (continuing WVI-3's W10 to W13): W14 path-token redirect domain; W15 MAP binding import
per connector (HubSpot first) with the legacy-endpoint risk accepted; W16 click-IP candidates allowed as
`WEAK/review` (US only); W17 co-op explicitly out of scope until the overlap test and a legal opinion.

---

## 12. Not found (looked, did not find)

- An independent (non-vendor) figure for how many sites or bindings a co-op needs for a given match rate.
- Any vendor document describing open-IP or click-IP to person mapping in detail (only Warmly's "email
  pixel correlations" mention).
- A public way to decode HubSpot `_hsenc`, or a Salesloft/Outreach API that maps their tracking token to
  a person.
- Verified Marketo "leads by cookie" and Mailchimp "member by unique_email_id" lookups (both plausible,
  both need confirmation against the API references).
- Identity-sharing programmes for Substack or ConvertKit sponsors.
- Lawsuits or regulator actions naming RB2B, Leadpipe, Customers.ai or Retention.com.
- A cited EU DPA decision against person-level B2B visitor identification.

---

## 13. Sources (this document)

Vendors and networks: <https://support.rb2b.com/en/articles/8891294-what-is-rb2b-and-how-does-it-work> ·
<https://support.rb2b.com/en/articles/8795972-updating-your-privacy-policy> ·
<https://support.retention.com/en/articles/8826172-do-i-need-to-update-my-privacy-policy> ·
<https://www.practicalecommerce.com/retention-com-founder-on-email-laundering> ·
<https://www.leadpipe.com/blog/how-we-built-the-leadpipe-identity-graph/> ·
<https://www.leadpipe.com/blog/identity-resolution-for-platforms-build-vs-buy-vs-embed/> ·
<https://www.leadpipe.com/blog/b2b-identity-resolution-api-guide/> ·
<https://help.warmly.ai/articles/5643444357-overview-of-warmly-s-data-data-quality> ·
<https://help.warmly.ai/articles/3568026273-contact-level-identification> ·
<https://customers.ai/contact-data-enrichment> · <https://www.vector.co/websiteid> ·
<https://www.docket.io/resources/research/vector-review> ·
<https://intercom.help/userled/en/articles/9515210-identity-layer> ·
<https://www.commonroom.io/playbooks/make-anonymous-web-visits-actionable-with-enhanced-website-visitor-identification/> ·
<https://www.commonroom.io/blog/best-website-visitor-identification-tool/> · <https://bombora.com/co-op/> ·
<https://bombora.com/blog/b2b-intent-data-explained-privacy-compliance/> ·
<https://www.apollo.io/product/b2b-data> · <https://pipeline.zoominfo.com/sales/how-does-zoominfo-get-data> ·
<https://ppc.land/zeta-global-to-acquire-liveintent/> · <https://pulse2.com/zeta-global-to-buy-liveintent-in-250-million-deal/> ·
<https://support.liveintent.com/how-to-implement-livetag-3-0/> ·
<https://knowledgebase.zetaglobal.com/liveintent/esp-event-configuration-instructions-mailchimp>

ESP / MAP parameters: <https://linkclean.app/trackers/hsenc/> · <https://linkclean.app/trackers/mc-eid/> ·
<https://community.hubspot.com/t5/Reporting-Analytics/Need-definitions-for-HubSpot-parameters/td-p/634937> ·
<https://developers.hubspot.com/docs/api-reference/legacy/crm/objects/contacts/v1/get-contacts-v1-contactbyUtk-batch> ·
<https://developers.hubspot.com/docs/api-reference/legacy/tracking-code-v1/overview> ·
<https://experienceleaguecommunities.adobe.com/adobe-marketo-engage-general-27/question-around-pre-fill-data-in-forms-and-mkt-tok-189393> ·
<https://experienceleague.adobe.com/en/docs/marketo-developer/marketo/rest/lead-database/leads> ·
<https://support.salesloft.com/hc/en-us/articles/115005958843-Live-Website-Tracking-> ·
<https://help.mutinyhq.com/hc/en-us/articles/26571961919899-Integrating-with-Salesloft> ·
<https://www.bleepingcomputer.com/news/security/new-firefox-privacy-feature-strips-urls-of-tracking-parameters/> ·
<https://github.com/brave/brave-browser/wiki/Query-String-Filter> ·
<https://www.terminusapp.com/blog/ios-17-link-tracking-protection-what-survives/> ·
<https://webkit.org/tracking-prevention/> · <https://stape.io/blog/safari-itp>

Email and IP: <https://www.litmus.com/email-client-market-share> ·
<https://bird.com/en-us/guides/apple-mail-privacy-protection-s-impact-on-email> ·
<https://www.suped.com/learn/email-deliverability/how-does-gmails-image-proxy-affect-email-open-tracking-and-what-could-cause-very-fast-opens> ·
<https://emailcalculator.com/blog/bot-clicks-are-lying-to-you> ·
<https://mailtester.com/blog/filter-microsoft-defender-bot-clicks-email-analytics/> ·
<https://www.caida.org/catalog/papers/2020_dynamips/dynamips.pdf> ·
<https://www.researchgate.net/publication/341125245_Don't_Count_Me_Out_On_the_Relevance_of_IP_Address_in_the_Tracking_Ecosystem> ·
<https://arxiv.org/pdf/1605.05606> · <https://streamkap.com/resources-and-guides/ip-to-company-enrichment> ·
<https://wfhresearch.com/wp-content/uploads/2026/08/WFHResearch_updates_September2026.pdf> ·
<https://support.maxmind.com/knowledge-base/articles/maxmind-geolocation-accuracy> ·
<https://gs.statcounter.com/browser-market-share/desktop/united-states-of-america> ·
<https://www.flint.com/articles/b2b-website-traffic-lead-conversion-statistics> ·
<https://www.wearetg.com/blog/b2b-website-conversion-rates/>

Publishers and licensing: <https://www.beehiiv.com/support/article/35763267725591-implementing-the-beehiiv-pixel-for-advertisers> ·
<https://www.beehiiv.com/blog/newsletter-sponsorship-cost> ·
<https://www.adexchanger.com/publishers/why-beehiiv-is-betting-on-programmatic-to-scale-its-ad-platform-for-newsletters/> ·
<https://revnew.com/blog/content-syndication-pricing-models> · <https://datarade.ai/data-providers/bigdbm/profile> ·
<https://tomba.io/blog/bigdbm-pricing-reviews-pros-and-cons> · <https://atdata.com/pricing/> ·
<https://pipeline.zoominfo.com/sales/fullcontact-pricing>

Legal: <https://www.law.cornell.edu/regulations/california/11-CCR-7050> ·
<https://www.coblentzlaw.com/news/navigating-californias-data-broker-requirements-in-2026/> ·
<https://www.datagrail.io/glossary/what-are-the-delete-act-and-drop/> ·
<https://www.gov.ca.gov/2026/08/13/icymi-california-takes-historic-action-against-data-brokers/> ·
<https://secureprivacy.ai/blog/data-broker-registration> ·
<https://www.lexology.com/library/detail.aspx?g=ddf4ee87-6946-499f-b116-24a2448fae89> ·
<https://www.cyberadviserblog.com/2026/10/governor-newsom-signs-sb-690-ending-the-private-right-of-action-under-cipas-pen-register-and-trap-and-trace-provision/> ·
<https://www.bclplaw.com/en-US/events-insights-news/edpb-explains-eu-eprivacy-cookie-rules-apply-to-emerging-online-tracking-tools.html> ·
<https://gdprhub.eu/index.php?title=CJEU_-_C%E2%80%9140/17_-_Fashion_ID> ·
<https://www.ftc.gov/policy/advocacy-research/tech-at-ftc/2024/07/no-hashing-still-doesnt-make-your-data-anonymous> ·
<https://natlawreview.com/article/arizona-court-appeals-affirms-dismissal-arizona-spy-pixel-class-action> ·
<https://maciejturek.com/resources/email-tracking-pixel-consent-rules.html> ·
<https://www.leadpipe.com/blog/visitor-identification-in-germany/>
