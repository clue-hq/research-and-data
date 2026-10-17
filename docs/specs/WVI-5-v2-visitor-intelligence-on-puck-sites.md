# WVI-5 v2. Visitor intelligence on the Puck website engine: architecture and build plan

**Written 2026-10-18** by Aryan with Claude, from Shashank's WVI-5 (branch `feature/visitor-intelligence`,
commit `814636ffc`). WVI-5 was written on a tree that has none of the Puck site layer
(`lumen_api/site_publish.py`, `lumen_api/site_live.py` and site-kit's `live-page.tsx` are absent there), so
everything it says about pages, page policies and publishing describes the old WebDoc pages. **This
document supersedes WVI-5 wherever they differ.** WVI-5's founder model (§0 below, amended), its data model,
alerts, screens, privacy and accuracy work carry over except where a section here says otherwise. WVI-4's
research still stands.

Seams cited here were checked on `site/publish-durability` (the Puck branch). Seams this document takes
from WVI-5 without change (fleet kinds, frontend files, migration templates) were verified by Shashank on
`research-streaming @ 61f9d1bf9` and must be re-checked on the build branch, which has to contain the Puck
site layer.

## 0. Founder model

- Every landing page lives in Clue: a Puck site published at the workspace's Clue address
  (`<label>.cluehq.page/<slug>`) or, once the customer connects a custom domain, at theirs
  (`go.conduit.ai/<slug>`). Sites can be 1:1 (made for one account), 1:few or 1:many. Nothing is exported.
- Tracking is **one Clue snippet**: Clue adds it to every live page it serves; the customer pastes the same
  snippet into Google Tag Manager or their site head **only for their own website**.
- Identification is **deterministic**: a person is named only by their own personal link (or QR), or by a
  browser cookie that one of their personal links set. Scope = target accounts and their buying committees.
- **Whose page it is never says who visited.** A visit to a site made for Oliver Hotels, with no personal
  link and no known cookie, is unknown: the page may have been forwarded, and 1:few and 1:many sites are
  made for no single account. (WVI-5's "an ABM account page names the account" rung is removed.)
- After a person is identified once, their browser is recognised later on Clue pages and on the customer's
  own site (shared cookie on custom domains), and that browser's earlier anonymous visits are filled in.
- Alerts go to Slack and in-app, only for strong signals; analytics live in the app.

**Laws (carried from WVI-5, extended).** (1) Unknown is a correct answer; a wrong name is the only failure.
(2) The page origin only appends rows; it never resolves. (3) Nothing personal is ever in a URL; tokens are
opaque and stored as digests. (4) Every assertion carries its method and evidence. (5) We never try to get
past corporate security; we filter it. (6) New behaviour sits behind per-workspace switches and env flags
documented in `.env.example` in the same commit.

## 1. Architecture

```
 Personal link / QR          Clue Puck page (live publish)        Customer's own website
 (token per person,          <label>.cluehq.page/<slug>           snippet via GTM / <head>
  account or campaign)       or go.conduit.ai/<slug>
            │                           │                                    │
            └───────────────┬───────────┴────────────────┬───────────────────┘
                            ▼                            ▼
          ┌──────────── Cloudflare Worker  pages-edge ─────────────────────────┐
          │ strips + stamps x-clue-client-ip, x-clue-geo (country, asn, org),   │
          │ first-pass bot class (user agent, security-vendor / cloud networks) │
          │ records EVERY page hit (cache hits too) → background POST to origin │
          │ GET/HEAD as today; POST allowed on /_clue/e only                    │
          └──────────────────────────────┬─────────────────────────────────────┘
                                         ▼
          ┌──────────── Page origin  clue_page_origin ─────────────────────────┐
          │ /{slug}, /{slug}/{route}  serve page; live publishes get           │
          │                           <script src="/_clue/v.js" defer> in head │
          │ /r/{token}     record click, set HttpOnly clue_vid, 302 → page+UTMs │
          │ /_clue/v.js    the snippet (same file for customer sites)          │
          │ /_clue/e       sendBeacon POST (interaction, sections, clicks)      │
          │ /_clue/b.gif   image-request fallback for the same events           │
          │ /_clue/hit     internal: page hits from the edge (edge secret)     │
          │  → INSERT visit_event (append-only, no resolution)                  │
          └──────────────────────────────┬─────────────────────────────────────┘
                                         ▼  fleet loop claims unresolved rows
          ┌──────────── Fleet: VISITOR_RESOLVE (per session) ──────────────────┐
          │ 1 drop bots and scanners   2 require a real interaction            │
          │ 3 who: personal link · returning cookie · else unknown             │
          │ 4 fill in the browser's earlier visits                             │
          │ 5 relevance (target account, committee) + signal tier              │
          │ 6 visitor_resolution (assert | review | unknown), activity item,   │
          │   alert rules (verified intent from a known committee member)      │
          └───────────────┬────────────────────────────┬───────────────────────┘
                          ▼                            ▼
          VISITOR_ALERT_DELIVER                Read API /frontend/v1/...
          Slack (OAuth bot) + in-app           Activity tab · contact engagement ·
                                               project analytics (pages, sections) ·
                                               Settings · Share menu personal links ·
                                               Head of ABM read_engagement@1
```

Each session yields two separate answers: **who** (from a link or a cookie the link set) and **how strong a
signal** (the tier, §2.7). An alert needs both.

## 2. Components and what changes from WVI-5

### 2.1 Which pages are tracked

- **Live Puck publishes only.** A live publish is served under `site_live_csp`
  (`subsystems/design/clue_design/publishes.py:565-575`): `script-src 'self'` plus its import-map hash, and
  `connect-src 'self'`. The snippet at `/_clue/v.js` and same-origin beacons are allowed with **no policy
  change**.
- **Static Puck publishes cannot run the snippet.** Their policy is `script-src 'none'; connect-src 'none'`
  (`publishes.py:549-554`) and it is baked into each published version's meta tag. Static pages get the edge's
  page-hit count only (no interaction, so never "human-confirmed", never identified beyond a link click).
  Which workspaces publish live is `LUMEN_SITE_LIVE_WORKSPACES` (`.env.example:836`; production is meant to set
  `*`, the default is empty). Ruling V1.
- **Old WebDoc publishes** (`delivery: "web"`) keep their policy (`connect-src 'none'`); if any are still
  served they get page hits and image-request beacons as WVI-5 designed.
- **The editor and the preview are never tracked.** The site editor runs on its own origin and the preview is
  drawn by the design API, not the page origin; injection exists only in the page origin's page routes.
- Publish packages stay host- and tracker-free (custom-domain spec rule 9): the snippet is added at serve time.

### 2.2 Edge: `infra/cloudflare/pages-edge/`

- In `routing.js` `decide()`, next to the existing `x-clue-public-host` / `x-clue-edge-auth` strip-and-stamp:
  delete inbound `x-clue-client-ip`, `x-clue-geo`, `x-clue-bot`, then stamp them from `cf-connecting-ip` and
  `request.cf` (`country`, `asn`, `asOrganization`). `decide()` must tolerate a missing `request.cf` under
  `node --test`.
- **First-pass bot class:** user agents (LinkedInBot, Slackbot, facebookexternalhit, Googlebot, Microsoft Safe
  Links / Defender, Proofpoint, Mimecast, Barracuda, preview fetchers) and networks (published security-vendor
  ranges, cloud and hosting providers). Corporate cloud proxies (Zscaler, Netskope) carry real people and must
  be classed separately from scanners. The origin and the resolver re-check.
- **Page hits are recorded at the edge.** The Worker runs in front of Cloudflare's cache on every request, so
  it sees hits a cache would answer. `worker.js` gains the `ctx` argument and, for a page GET on an "ours"
  host, sends a small hit record to the origin's internal `/_clue/hit` with `ctx.waitUntil(...)` (the visitor's
  page is not delayed), authenticated with the existing `EDGE_SECRET`. Today the Worker forwards every request
  and Cloudflare does not cache HTML by default, so the origin does see every page GET; recording at the edge
  keeps counts right if a cache rule is ever added. In a dev stack without the Worker, a dev flag lets the origin
  record page GETs itself.
- **Methods:** GET/HEAD stay the only methods forwarded, **except POST on `/_clue/e`** (the beacon), with a
  payload size cap. A Cloudflare rate-limit rule on `/_clue/*` and `/r/*`.

### 2.3 Page origin: `platform/page_origin/clue_page_origin/`

- **Serve-time injection** in `page()` and `route_page()` (`routes.py:150-191`): when the workspace has
  tracking on **and the publish is live**, insert `<script src="/_clue/v.js" defer></script>` before `</head>`
  and compute the ETag over the served bytes. The tag sits in the head, outside `#clue-site`, so React's
  takeover of the server-drawn page is not disturbed.
- **New routes**, declared before the slug routes (`r` and `_clue` cannot collide with publish slugs):
  - `GET /r/{token}` (§2.5): look the token up, record `link_click`, set `clue_vid` if absent, 302 to the target
    page with UTMs, `Cache-Control: no-store`.
  - `GET /_clue/v.js`: the snippet, `public, max-age=300`.
  - `POST /_clue/e`: beacon events (§2.4), `no-store`, may set `clue_vid`. Returns 204.
  - `GET /_clue/b.gif`: the same events as an image request (fallback), `no-store`.
  - `POST /_clue/hit`: internal, edge-authenticated page hits.
- **Cookies.** Page HTML stays `public, max-age=60, must-revalidate` and never sets cookies; only `/r/`,
  `/_clue/e` and `/_clue/b.gif` set `clue_vid` (§2.6).
- **Writes** through a `VisitSink` injected next to `reads` in `create_page_origin_app`, faked in tests; insert
  in a background task.
- **Logs:** redact `/r/{token}` paths in access and edge-refusal logs; never log IP or email fields.

### 2.4 The snippet `/_clue/v.js` (one file, ≤ 4 KB)

- **Session:** a 30-minute session id kept in the tab (`sessionStorage`). It does **not** read `clue_vid`
  (the cookie is `HttpOnly`; the browser sends it with every beacon).
- **Real interaction (the human gate, §2.7):** scroll, pointer or touch movement, a key press, tab focus, and
  the time the page is visible. Sent as flags and counts, never as recordings of what was typed.
- **Page facts:** route, title, referrer host, UTMs; single-page route changes if a site adds any.
- **Puck section engagement:** an `IntersectionObserver` on `[data-clue-section]` (every page section and the
  header and footer, `shell-header` / `shell-footer`) reports which sections were seen and for how long; a
  delegated click listener reports clicks on `[data-clue-el]` elements and on links (call-to-action buttons,
  nav links, links in rich text), with the element key and whether the link leaves the site. Agent sections
  report element clicks only for elements the agent named. Ruling V2.
- **Transport:** `navigator.sendBeacon('/_clue/e', …)` (survives the page closing), batched, flushed on
  `visibilitychange`/`pagehide`. Fallback: `new Image().src = '/_clue/b.gif?…'` when `sendBeacon` is missing or
  blocked (customer sites whose own policy forbids it).
- **On the customer's site** it loads from the workspace's active hostname, preferably the custom one
  (`https://go.conduit.ai/_clue/v.js`), so beacons are same-site and the shared cookie flows.
- **Link tagging:** on Clue pages, outbound links to the customer's registered domains get `?cl=<link token>`
  **at the moment of the click** (not by rewriting the page up front, which redrawn sections would undo). The
  tag is a separate short-lived, non-identifying token the origin maps to the visitor; it is not `clue_vid`.
- **Consent:** honours GPC and DNT (no cookie; events marked); `consent_mode` per workspace: `auto` (track
  where the law allows, wait for consent in the EU/UK and where India's DPDP Act requires it), `wait`, `off`.
  In `wait`, a tab-only id until a consent platform grants (OneTrust, Cookiebot) or `clue.consent('granted')`.
- **Never:** fingerprinting, reading form fields, session recording. `clue.identify({email})` arrives with
  forms (§6).
- **Abuse control on customer sites:** beacons are accepted only when the page host is in the workspace's
  `allowed_hosts`; otherwise silently dropped.

### 2.5 Personal links and QR codes

- `POST /frontend/v1/tracked-links` `{accountId?, contactId?, projectId, channel, scope, target, messageId?,
  artifactRef?}` with `Idempotency-Key` → `{token, url, expiresAt}`. Copying the same person's link again for
  the same project and channel returns the same token.
- **Scope** (new): `person` (account + contact; 1:1 email, LinkedIn DM, one printed QR per copy), `account`
  (account only; a gift to an office), `campaign` (no account or contact; 1:few and 1:many pages, ads). Only
  `person` links can name anyone. Ads stay campaign-level.
- **Target:** a published site and optional route. For an account with its own published site, the default
  target is that site; for a campaign, the campaign's page.
- **Token:** 96+ random bits, base62, stored as a SHA-256 digest (house pattern). URL on the active hostname
  (custom if connected): `https://go.conduit.ai/r/x7k2Q9…`.
- **UTMs** per channel set by Clue: `utm_source`, `utm_medium`, `utm_campaign` = project, `utm_content` =
  artifact or creative; ad URLs use the ad platforms' dynamic parameters.
- **Message id** (new): when Clue composes the outreach, every link in one message shares a `message_id`, so
  "several links of one message hit within ~2 s" is detectable as a scanner. Links copied by hand carry none.
- **Expiry and revoking:** 180 days, or revoked by the user. An expired or revoked token **still redirects to
  its target page** but identifies no one (WVI-5 sent it to the workspace fallback; old mailers should not land
  somewhere unexpected). An unknown token goes to the workspace fallback as before.
- **QR on print and direct mail:** unchanged from WVI-5 §2.4 (fill `BindingSet.links.*.url` per
  `BindingAudience(account_id, contact_id)`; each copy renders its own QR; print the short URL under it). This
  is the scene-ad binding pipeline, which the Puck change does not touch.
- **Dropped:** WVI-5's `account.tracked_url` page value. It came from WebDoc templates; Puck sites are written
  by the agent and do not need the link inside the page.
- **Where people copy links:** the account header menu, the contact preview and contact rows (as WVI-5), and
  the **site editor's Share menu**, which lists the site's account's committee members with "Copy personal
  link" each.

### 2.6 The visitor cookie `clue_vid`

A random id (UUID) meaning "this browser"; it never contains anything about the person.

| Setting | Value | Why |
|---|---|---|
| `HttpOnly` | on (new) | Page scripts, agent-written sections included, cannot read or forge it |
| `Secure`, `SameSite=Lax` | on | HTTPS only; sent on link clicks into the site |
| Lifetime | 400 days | Returning visitors |
| Domain on `<label>.cluehq.page` | host only | A `cluehq.page`-wide cookie would cross workspaces |
| Domain on a custom host | its registrable domain (`clue_spine/hostnames.py`) | The customer's own site shares it |

The page-origin workspace lookup also returns the hostname kind. Known losses: one cookie per browser (a
phone and a laptop are two visitors until each clicks a personal link), private windows, cleared cookies, and
Safari shortening some cookies to about 7 days (notably where the custom subdomain points at Cloudflare).

### 2.7 Resolution: fleet `VISITOR_RESOLVE` (+ `VISITOR_ALERT_DELIVER`)

Fleet wiring, pickup (origin inserts; a fleet loop claims `resolved_at IS NULL` rows every 2-5 s) and the
`platform/api/clue_api/visitor_intel/` package as WVI-5 §2.6. The ladder per session:

1. **Drop bots and scanners:** edge class, origin re-check, scanner timing (several links of one message within
   ~2 s; a hit within seconds of sending), HEAD and prefetch requests, no cookie kept.
2. **Require a real interaction (changed).** "The snippet ran" is **not** enough: corporate scanners
   (Defender, Proofpoint, Mimecast) open links in sandbox browsers that run JavaScript. A session counts as human
   only with a real interaction (scroll, pointer or touch, key, tab focus) or several seconds of visible time, and
   not from a security-vendor or cloud-provider network. Sandboxes sometimes fake mouse movement; the network
   check catches most of them.
3. **Who it is (changed):**
   - a `person` token's **first human click** binds that browser to the contact, strong;
   - the same token in another browser afterwards → probably forwarded, decision `review`, never asserted;
   - a browser already bound by an earlier link → `returning`, same person;
   - everything else → `unknown`. The account a page was made for is never used.
4. **Fill in the past:** the browser's earlier unresolved sessions take the identity.
5. **Relevance and tier (new):**
   - relevance: `project_account` membership and ARV2 committee membership (as WVI-5);
   - tier, from what the session did:

   | Tier | Signals | Use |
   |---|---|---|
   | Verified intent | CTA click, form or booking (later), time on pricing / security / integrations sections, a return visit, 2+ committee members of one account within 7 days | Alert when the person is known |
   | Likely human | Real interaction with scroll and dwell | Score; show in the app; no alert |
   | Unverified | A link click or page hit with no interaction (including every static page) | Log only |
   | Bot | Scanner or bot patterns | Discard |

   Which sections count as high-intent is a per-workspace setting, matched on section and element names.
6. **Write:** `visitor_resolution` (decision, method, strength, tier, reasons), a `visit` item on
   `account_activity_event`, and evaluate alert rules.

### 2.8 Data model: one migration

House rules as WVI-5 §2.5 (raw SQL, text + named CHECKs, composite FKs on `(id, workspace_id)`, reversible,
downgrade fails loudly while `visit` rows exist). `down_revision` = the build branch's head at the time.
Changes against WVI-5's tables:

| Table | Change |
|---|---|
| `tracked_link` | add `scope` CHECK (person, account, campaign), `message_id` NULL, `target_route` NULL; `contact_entity_id` required when scope = person; `account_entity_id` NULL when scope = campaign |
| `visit_event` | `kind` adds `section_view`, `element_click`, `interaction`, `page_hit` (from the edge); add `route`, `section_id`, `element_key`, `outbound` bool, `visible_ms`, `interaction` jsonb (flags and counts); `ip_hash` becomes a **keyed hash** (HMAC with a workspace secret): there are only ~4 billion IPv4 addresses, so a plain hash can be reversed by trying them all |
| `visitor_resolution` | add `tier` CHECK (verified_intent, likely_human, unverified, bot) |
| `visitor_identity_binding` | `method` CHECK drops `account_page` |
| others | `web_visitor`, `visit_alert_rule` / `visit_alert`, `workspace_integration`, the `account_activity_event.kind` widening: as WVI-5 |

### 2.9 Alerts

As WVI-5 §2.7 (Slack app with encrypted token storage under a new `CLUE_INTEGRATION_ENCRYPTION_KEY`; in-app via
the product-notice pattern), with one change: **an alert fires only for the verified-intent tier from a known
committee member** (decision `assert`; `review` decisions appear in the app, not in Slack). Default rules:
committee member's first verified visit; a returning committee member reads a high-intent section; 2+ committee
members of one account within 7 days. Throttled per contact per day.

### 2.10 Read side, screens and agents

As WVI-5 §2.8, plus:

- **Project analytics** shows visits per page **and per section** (how many people saw each section, median time
  on it, CTA clicks), for 1:1, 1:few and 1:many sites alike. Each item says how we know (link, returning, unknown).
- **Account Activity** shows `review` visits as "probably forwarded" with a confirm/dismiss action; a confirmed
  forward to a known committee member binds that browser to them.
- **Static publishes** show page hits only, with a note that live publishing is needed for engagement.
- **Head of ABM:** `read_engagement@1` as WVI-5 (serves `assert` and `review` only; batch the profile bump with
  other catalog changes).
- **Website agent:** optionally reads a short engagement summary in its `site.md` ("the pricing section was read
  by 3 committee members; nobody reached the FAQ"), so it can improve pages from what visitors read. Its skills
  say it never writes tracking or analytics code of its own. Ruling V3; skill text goes to the founder first.

### 2.11 Privacy, retention, DSAR

As WVI-5 §2.9 (raw `client_ip` cleared after 30 days, keeping the keyed hash; DSAR helper revoking bindings and
clearing contact references; `/_clue/optout`), plus India's DPDP Act in the consent design and privacy notice.

## 3. Accuracy and production quality

WVI-5's table stands, with these rows changed or added:

| Risk | Control | Proof |
|---|---|---|
| Scanners that run JavaScript in sandboxes | Real-interaction gate plus security-vendor / cloud network check; identity binds only on the first human-confirmed hit | Corporate-inbox test (Defender, Proofpoint, Mimecast): 0 bound scanner clicks |
| Cached pages | Page hits recorded at the edge, which runs on cache hits | Cache-rule test: hits counted with a forced cache |
| Beacons lost on page close | `sendBeacon` on Clue pages; image fallback | Leave-page test across browsers |
| Page code reading or forging the visitor id | `HttpOnly` cookie; origin checks beacons | Test: a page script cannot read `clue_vid` |
| A page made for one account, opened by someone else | Page ownership is never identity | Forward test: unknown or `review`, never the page's account |
| Corporate proxy users dropped as bots | Zscaler / Netskope classed apart from scanners | Known visitors behind a proxy are counted |

**Known-visitor harness** as WVI-5 (about 20 known people; email, LinkedIn DM, printed QR, ads; iPhone, Android,
desktop Chrome/Safari/Firefox, in-app browsers), with sandbox-scanner inboxes and a proxy user added. Gates
before any customer sees it: named-person precision 100%, ≥ 95% of known human visits captured, 0 bot alerts,
alert p95 < 60 s, forward and back-fill cases correct, section counts within 5% of the manual sheet.

**Monitoring** as WVI-5 (metrics, tracking-health line in Settings, a canary visit every 10 minutes), plus the
share of static-page traffic.

## 4. Build order

| Step | Scope | Rough size |
|---|---|---|
| 0. Rulings | V1-V8 below | 1-2 days |
| 1. Capture | migration; edge headers, bot class, page hits, POST on `/_clue/e`; origin `/r/`, `/_clue/v.js`, `/_clue/e`, `/_clue/b.gif`, `/_clue/hit`, serve-time injection on live publishes; `VisitSink` | ~4-5 days |
| 2. Links | tracked-link API with scopes and message ids; Copy personal link in account, contact and Share menus; QR filling | ~2-3 days |
| 3. Resolve | ladder with the interaction gate, tiers, stitching, committee match, activity items | ~3-4 days |
| 4. Alerts | Slack app, encrypted storage, delivery, rules on verified intent; in-app | ~3 days |
| 5. Screens | Activity (incl. forward review), contact engagement, project analytics with sections, Settings | ~4 days |
| 6. Customer site | snippet on customer domains, allowed hosts, click-time link tagging, consent modes, install check | ~2 days |
| 7. Harden | harness run, canary, metrics, retention, DSAR hook, `read_engagement@1`, site-agent summary if V3 | ~3-4 days |

Roughly **four weeks for one engineer**; an internal demo (link → visit → Activity → Slack) after steps 1-4.

## 5. Not in this build

- **Probable company from the visitor's network** (WVI-4 path B: an IP-to-company map built from our own
  identified visits and public registries; about 25-35% of business visits, labelled "probable", never a
  person). Ruling V7.
- **The same person across devices without a link:** a "probable same person" rule from network, timing and
  device signals is to be designed separately; until then each device is named only by its own personal-link
  click.
- **Forms and meeting bookings on Puck pages** with `clue.identify({email})`: waits for forms in live publishing
  (the live policy has `form-action 'none'` today). The strongest cross-device signal once it lands.
- **Importing the customer's existing marketing identities** (WVI-4 path C: HubSpot `hubspotutk`, Marketo,
  Mailchimp).
- **CRM push** of visits (the CRM integration is read-only in v1).
- **Honeypot links:** need Clue to send the email itself; Clue does not send email today.
- Anonymous person-level identification (WVI-4 path D, rulings W18-W20).

## 6. Rulings needed (Aryan)

| # | Decision | Recommendation |
|---|---|---|
| V1 | Which pages are tracked | Live Puck publishes only; static publishes get page hits; production keeps `LUMEN_SITE_LIVE_WORKSPACES=*` |
| V2 | Section and CTA engagement | In v1: it is what makes the tiers and project analytics useful, and Puck already names sections and elements |
| V3 | Website agent reads engagement | In v1 as a short `site.md` summary, after the Head of ABM tool; skill text to the founder first |
| V4 | Beacon transport | `sendBeacon` POST to `/_clue/e` on Clue pages (POST allowed at the edge for that path only), image request as fallback |
| V5 | Where page views are recorded | At the edge, posted to the origin in the background |
| V6 | Alerts | Only verified intent from a known committee member (`assert`); `review` stays in the app |
| V7 | Probable company from network | Deferred (§5) |
| V8 | Expired links | Still redirect to the target page, identifying no one |

Carried from WVI-5 and still recommended as written there: R2 (origin inserts, fleet claims), R4 (cookie
scope), R5 (consent default, now with DPDP), R6 (Slack token storage), R7 (inline SVG charts). WVI-5's R1 is
replaced by V1 (injection only on live publishes); R3 is replaced by V4.
