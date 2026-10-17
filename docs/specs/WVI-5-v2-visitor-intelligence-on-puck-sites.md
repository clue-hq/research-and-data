# WVI-5 v2. Visitor intelligence on the Puck website engine: architecture and build plan

**Written 2026-10-18** by Aryan with Claude, from Shashank's WVI-5 (branch `feature/visitor-intelligence`,
commit `814636ffc`). WVI-5 was written on a tree that has none of the Puck site layer
(`subsystems/clue-design/apps/api/lumen_api/site_publish.py`, `lumen_api/site_live.py` and
`apps/frontend/packages/site-kit/src/live-page.tsx` are absent there), so everything it says about pages,
page policies and publishing describes the old WebDoc pages. **This document supersedes WVI-5 wherever they
differ.** WVI-5's founder model (§0 below, amended), its data model, alerts, screens, privacy and accuracy
work carry over except where a section here says otherwise. WVI-4's research still stands.

**Checked 2026-10-18.** Every code reference here, including the ones taken from WVI-5, was re-checked on
`site/publish-durability @ 1df6a1757`; where WVI-5's reference was wrong on this tree, this document gives the
right one. **Build branch:** the Puck site layer exists only on `site/publish-durability` and
`puck/integration-wave1`. It is not on `research-streaming` or `main`, where WVI-5 was checked. The build
starts from the Puck line, or waits until it has merged into `research-streaming`.

**Relation to the live-sites spec.** `docs/superpowers/specs/2026-10-15-publishing-live-sites-design.md`
already designs tracking for live Puck pages as its phase 2: `kit.track`, a `page_view` from the site
runtime, `POST /_clue/events/{slug}`, a `site_event` table and a visitor id kept in `localStorage` (its §4.2,
§4.7, §4.8, §7). Phase 2 is "designed here but built in a later round" (its §16), and none of it is built:
there is no `kit.track`, no `site_event` and no POST route. This document replaces that tracking design
(ruling V9, §6). Forms and the lead email stay in the live-sites spec's phase 2.

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
  Which workspaces publish live is `LUMEN_SITE_LIVE_WORKSPACES` (`.env.example:836`, default empty; `*`
  means every workspace, `site_live.py:35-41`). It is read when a site is published
  (`lumen_api/toolbelt/publishes.py:259`) and for previews (`lumen_api/main.py:12409`). The founder ruled on
  2026-10-15 that every workspace publishes live by default. The only record of `*` in production is the
  pages-hosting runbook (`docs/specs/pages-hosting-runbook.md:549,554`, the worker VM's `/srv/clue/env`): no
  committed env file has it and `deploy/check_prod_env.py` does not check it. Before step 1, confirm it is
  set in every process that publishes. Ruling V1.
- **`cluehq.page` is not on the Public Suffix List.** The live-sites spec (§12) required the listing before
  customers publish live pages; the founder decided on 2026-10-15 to file it only once it can honestly claim
  thousands of users, and the same day ruled live pages on for every workspace (record:
  `_memory/2026-10-15-publishing-live-sites.md`). So live pages are public while browsers still treat all of
  `cluehq.page` as one site. The cookie design takes that into account (§2.6).
- **Old WebDoc publishes** (`delivery: "web"`) keep their policy (`connect-src 'none'`); if any are still
  served they get page hits and image-request beacons as WVI-5 designed.
- **The editor and the preview are never tracked.** Both are drawn by the site-editor server (the preview is
  the same editor in preview mode: `apps/frontend/packages/site-editor/src/server/app.ts:82`,
  `apps/frontend/src/features/site-editor/model/site-frame-sync.ts:38`),
  on its own origin, never by the page origin; injection exists only in the page origin's page routes.
- Publish packages stay free of trackers: the snippet is added at serve time, the way the live-sites spec
  adds a workspace's snippets (§9 there) and the way the custom-domain spec keeps a package independent of
  the host it is served on (rule 9 there, which is about hosts, not trackers).

### 2.2 Edge: `infra/cloudflare/pages-edge/`

- In `routing.js` `decide()`, next to the existing `x-clue-public-host` / `x-clue-edge-auth` strip-and-stamp (:35-38):
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
- **Methods:** today every non-GET/HEAD request on our hosts is answered `method_not_allowed`
  (`routing.js:25,33`). GET/HEAD stay the only methods forwarded, **except POST on `/_clue/e`** (the beacon),
  with a payload size cap; when forms land, the live-sites spec's `POST /_clue/forms/…` joins it. A
  Cloudflare rate-limit rule on `/_clue/*` and `/r/*`. Nothing in `wrangler.toml` or the repo configures a
  cache today, and `page-origin.cluehq.ai` is DNS-only (`docs/deploy/runbook.md:152`).

### 2.3 Page origin: `platform/page_origin/clue_page_origin/`

- **Serve-time injection** in `page()` and `route_page()` (`routes.py:150-189`): when the workspace has
  tracking on **and the publish is live** (`delivery == "site_live"`), insert
  `<script src="/_clue/v.js" defer></script>` before `</head>`. Today both routes build the ETag from the stored
  `html_digest` (`_page_headers(...)`), so the ETag must also cover the injection (as the live-sites spec §4.7
  plans for snippets: digest plus snippet version). The live policy allows the tag with no change: it is
  `'self'`, in both the header and the meta tag stored in the page. The tag sits in the head, outside
  `#clue-site` (`site-kit/src/render-core.tsx:93`), so React's takeover of the server-drawn page is not
  disturbed. When the live-sites spec's snippets are built, this tag goes in through the same injection step.
- **The workspace lookup** (`routes.py:69-70`, `reads.workspace_for_hostname`) returns only the workspace id today. It must also return the
  kind of host (Clue address or custom domain) for the cookie rules (§2.6); the hostname record has it
  (`libs/clue-spine/clue_spine/hostnames.py:332-361`, `resolve_active_hostname`).
- **New routes**, declared before the slug routes (`r` and `_clue` cannot collide with publish slugs: a slug
  is 3-64 characters of `[a-z0-9-]`, `lumen_api/toolbelt/publishes.py:59`):
  - `GET /r/{token}` (§2.5): look the token up, record `link_click`, set `clue_vid` if absent, 302 to the target
    page with UTMs, `Cache-Control: no-store`.
  - `GET /_clue/v.js`: the snippet, `public, max-age=300`.
  - `POST /_clue/e`: beacon events (§2.4), `no-store`, may set `clue_vid`. Returns 204.
  - `GET /_clue/b.gif`: the same events as an image request (fallback), `no-store`.
  - `POST /_clue/hit`: internal, edge-authenticated page hits.
- **Cookies.** Page HTML stays `public, max-age=60, must-revalidate` and never sets cookies; only `/r/`,
  `/_clue/e` and `/_clue/b.gif` set `clue_vid` (§2.6).
- **Writes** through a `VisitSink` injected next to `reads` in `create_page_origin_app` (`app.py:19-21`), faked
  in tests next to `FakePageReads` (`tests/page_origin/conftest.py:23-110`); insert in a background task. The
  page origin's database role (`clue_worker`) already has INSERT (`docs/deploy/runbook.md:74,79`).
- **Logs (new work, not a setting):** uvicorn's access log is on by default (`main.py:77-83`) and would write
  every `/r/{token}` path, and the edge-refusal log writes the client IP (`edge.py:49-53`). The log redaction
  in `libs/clue-obs/clue_obs/redact.py` masks only secret-shaped keys. Step 1 turns the access log off or
  replaces it with one that redacts `/r/…` paths, and removes the IP from the refusal log.

### 2.4 The snippet `/_clue/v.js` (one file, ≤ 4 KB)

- **Session:** a 30-minute session id kept in the tab (`sessionStorage`). It does **not** read `clue_vid`
  (the cookie is `HttpOnly`; the browser sends it with every beacon).
- **Real interaction (the human gate, §2.7):** scroll, pointer or touch movement, a key press, tab focus, and
  the time the page is visible. Sent as flags and counts, never as recordings of what was typed.
- **Page facts:** route, title, referrer host, UTMs. Moving between pages of a site is a full page load today
  (site-kit links are plain `basePath` links, `config.tsx:152-155`), so each page reports itself on load;
  the tab's session id ties them together.
- **Puck section engagement:** an `IntersectionObserver` on `[data-clue-section]` reports which sections were
  seen and for how long. Every page section is wrapped in `<div data-clue-section={id}>`
  (`site-kit/src/config.tsx:375`), where the id is the section's own `id` prop, chosen per site (`proof`,
  `hero`); the header and footer carry `shell-header` / `shell-footer` (`edits.ts:20`, `shell.tsx:68,109`).
  The wrapper does not say what kind of section it is, so the resolver looks up the section's type and
  heading in the publish's stored page data by id. A delegated click listener reports clicks on links and on
  `[data-clue-el]` elements, with the element key and whether the link leaves the site. What carries a key
  today:
  - our sections' buttons (`data-clue-el` on the `<a class="brand-btn">`, `site-kit/src/sections.tsx:79,82`)
    and the header button (`cta`, `shell.tsx:98`): keyed since plan 3 of the site element inspector;
  - in clones, inline links and buttons (`clone.ts:172`), but not a link that wraps a block;
  - in agent sections, a `kit.Button` only when the agent gave it a key (`agent-kit.tsx:61-62`); a
    `kit.Card`'s link has none.

  An unkeyed link is still reported by its address and section. Ruling V2.
- **Everything a page reports can be forged by code on the page.** Live agent sections may call `fetch`
  (`site-kit/src/check-section.ts:188-193` refuses `document.cookie`, not `fetch`), and the live-sites spec's
  snippets will run the customer's own scripts. So identity never comes from a beacon's contents, only from
  the cookie the origin set and the link token the origin looked up; beacon facts (sections, clicks,
  interaction) count towards a tier but never name anyone.
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
  forms (§5).
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
- **Token:** 96+ random bits, base62, stored as a SHA-256 digest (house pattern: `hash_invitation_token`,
  `platform/auth/clue_auth/provisioning.py:64-68`). URL on the active hostname
  (custom if connected): `https://go.conduit.ai/r/x7k2Q9…`.
- **UTMs** per channel set by Clue: `utm_source`, `utm_medium`, `utm_campaign` = project, `utm_content` =
  artifact or creative; ad URLs use the ad platforms' dynamic parameters.
- **Message id** (new): when Clue composes the outreach, every link in one message shares a `message_id`, so
  "several links of one message hit within ~2 s" is detectable as a scanner. Links copied by hand carry none.
- **Expiry and revoking:** 180 days, or revoked by the user. An expired or revoked token **still redirects to
  its target page** but identifies no one (WVI-5 sent it to the workspace fallback; old mailers should not land
  somewhere unexpected). An unknown token goes to the workspace fallback as before.
- **QR on print and direct mail:** unchanged from WVI-5 §2.4 (fill `BindingSet.links.*.url` per
  `BindingAudience(account_id, contact_id)`, `crates/lumen-core/src/binding.rs:37-42`; each copy renders its
  own QR, `binding.rs:592-612` and `crates/lumen-assets/src/qr.rs:109`; print the short URL under it). Binding
  sets are created at `lumen_api/main.py:6712-6767` (validation :6730, per-copy derivation
  `_derive_and_persist_instance` :6578). This is the scene-ad binding pipeline; Puck sites use no binding
  sets, and the Puck change does not touch it.
- **Dropped:** WVI-5's `account.tracked_url` page value. It lived in the WebDoc account values
  (`lumen_api/main.py:12888-12938`, WebDoc documents only); Puck sites are written by the agent and do not
  need the link inside the page.
- **Where people copy links** (all new UI):
  - the account header menu (`account-workspace-shell.tsx:206-236` has a menu today; the item is added);
  - the contact preview and contact rows: neither has a menu today (`contact-preview.tsx:80-86` is a plain
    button, `contact-row.tsx:147` is the email-lookup button), so a menu is built;
  - the **site editor's Share menu** (`artifact-share-menu.tsx`, today: publish, address, Copy link,
    advanced). For a site made for an account it lists that account's committee members with "Copy personal
    link" each. The account is `design_document.account_id` → `design_account.account_entity_id`
    (nullable: a 1:few or 1:many site has none, and offers a campaign link only); the committee is
    `committee_members` (`platform/api/clue_api/arv2/display/gather.py:342`).
  - There is no shared copy-to-clipboard helper (`use-copy-feedback.ts` has none); one is added.
  - These screens need designed frames from the co-founder before step 2's UI (the standing rule: wiring
    never invents UI).

### 2.6 The visitor cookie `clue_vid`

A random id (UUID) meaning "this browser"; it never contains anything about the person. This document calls it
`clue_vid`; on Clue addresses its name carries the `__Host-` prefix (table below).

| Setting | Value | Why |
|---|---|---|
| `HttpOnly` | on (new) | Page scripts, agent-written sections included, cannot read it |
| `Secure`, `SameSite=Lax` | on | HTTPS only; sent on link clicks into the site |
| Lifetime | 400 days | Returning visitors |
| On `<label>.cluehq.page` | named `__Host-clue_vid`: host only, `Path=/` | `cluehq.page` is not on the Public Suffix List (§2.1), so a script on another workspace's page could set a `cluehq.page`-wide `clue_vid` that our origin would receive. The `__Host-` prefix makes the browser refuse any such cookie under that name |
| On a custom host | `clue_vid` with `Domain=` its registrable domain (`clue_spine/hostnames.py:189-197`; an apex is never a custom host, `:233-238`) | The customer's own site shares it |

The page origin picks the row from the host kind its workspace lookup returns (§2.3). Known losses: one
cookie per browser (a phone and a laptop are two visitors until each clicks a personal link), private
windows, cleared cookies, and Safari limiting cookies set by a server on a different IP range from the main
site to about 7 days (a custom subdomain pointed at Clue by CNAME is exactly that).

### 2.7 Resolution: fleet `VISITOR_RESOLVE` (+ `VISITOR_ALERT_DELIVER`)

Fleet wiring, pickup (origin inserts; a fleet loop claims `resolved_at IS NULL` rows every 2-5 s) and the
`platform/api/clue_api/visitor_intel/` package as WVI-5 §2.6, at these places on this tree:

- the two kinds go after `PRODUCT_PAGE_WRITE`, today the last kind (`platform/fleet/clue_fleet/enums.py:80`),
  with an `ALTER TYPE fleet_task_kind ADD VALUE` migration like `1ecc7437e5bc`, whose test asserts the last
  label (`tests/db/test_product_page_write_kind_migration.py:27-28`) and must be updated;
- handlers are passed per kind to `build_multi_work_worker` (`platform/api/clue_api/fleet_wiring.py:383`,
  kind checks :445-484);
- the claiming loop sits beside `_orphan_sweep_loop` (`fleet_main.py:243`); the advisory-lock-plus-
  `maintenance_run` pattern is `run_orphan_blob_sweep_if_due` (`storage_wiring.py:254`).

The ladder per session:

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
   - relevance: project membership (`projects_for_accounts`, `subsystems/research/clue_research/membership.py:225`)
     and ARV2 committee membership (`committee_members`, `arv2/display/gather.py:342`), as WVI-5;
   - tier, from what the session did:

   | Tier | Signals | Use |
   |---|---|---|
   | Verified intent | CTA click, form or booking (later), time on pricing / security / integrations sections, a return visit, 2+ committee members of one account within 7 days | Alert when the person is known |
   | Likely human | Real interaction with scroll and dwell | Score; show in the app; no alert |
   | Unverified | A link click or page hit with no interaction (including every static page) | Log only |
   | Bot | Scanner or bot patterns | Discard |

   Which sections count as high-intent is a per-workspace setting, matched on the section's type and heading
   (looked up by id in the publish's page data, §2.4) and on element keys.
6. **Write:** `visitor_resolution` (decision, method, strength, tier, reasons), a `visit` item on
   `account_activity_event`, and evaluate alert rules.

### 2.8 Data model: one migration

House rules as WVI-5 §2.5 (raw SQL, text + named CHECKs, composite FKs on `(id, workspace_id)`, reversible,
downgrade fails loudly while `visit` rows exist). Two of WVI-5's references do not hold on this tree:

- **`down_revision`:** WVI-5 names `ddf063300a0b`, which exists only on `research-streaming`, `feat/discovery-excludes-customers`
  and `feature/visitor-intelligence`, not on the Puck branch. The head here is `6fb438905f96`. Use the build
  branch's single head at the time.
- **Templates:** WVI-5's `89791cb5949e_provider_incident.py` is a fleet-wide table with no `workspace_id` and
  no composite FK. Use `65fb2128c904_arv2_d1_display_substrate.py:259-261` for the composite FK and
  `000b9d8bb17b_arv2_onboarding_synthesis_role.py:75` for the downgrade that refuses while rows exist.

Changes against WVI-5's tables:

| Table | Change |
|---|---|
| `tracked_link` | add `scope` CHECK (person, account, campaign), `message_id` NULL, `target_route` NULL; `contact_entity_id` required when scope = person; `account_entity_id` NULL when scope = campaign |
| `visit_event` | `kind` adds `section_view`, `element_click`, `interaction`, `page_hit` (from the edge), `custom` (a `kit.track` event, with its name) and `hydration_error` (V9); add `route`, `section_id`, `element_key`, `outbound` bool, `visible_ms`, `interaction` jsonb (flags and counts); `ip_hash` becomes a **keyed hash** (HMAC; key below): there are only ~4 billion IPv4 addresses, so a plain hash can be reversed by trying them all |
| `visitor_resolution` | add `tier` CHECK (verified_intent, likely_human, unverified, bot) |
| `visitor_identity_binding` | `method` CHECK drops `account_page` |
| `account_activity_event` | `kind` CHECK (`65fb2128c904:262-263`: created, contacts, summary, artifact, updated) gains `visit`. The read side needs more than WVI-5 lists: `_ACTIVITY_SQL` does not select `ref_json` (`frontend_read/v1_shared.py:1186`), and `ActivityKind` is a closed Literal in `v1_shared.py:1193` and `contract_v1.py:451`, and in the frontend (`account-detail.ts:49`, icons in `account-activity-feed.tsx:7`) |
| others | `web_visitor`, `visit_alert_rule` / `visit_alert`, `workspace_integration`: as WVI-5 |

The keyed IP hash needs a key. There is no pattern in the repo for a secret stored in the database (§2.9), so
the simplest form is one platform key in env (`CLUE_VISITOR_IP_HASH_KEY`, in `.env.example` in the same
commit) with the workspace id mixed into the hashed value, so the same address hashes differently per
workspace. (Claude's call, for Aryan to confirm: a per-workspace stored key buys nothing more here.)

### 2.9 Alerts

As WVI-5 §2.7 (Slack app with encrypted token storage under a new `CLUE_INTEGRATION_ENCRYPTION_KEY`; in-app via
the product-notice pattern, `frontend_read/product_notices.py`). All of it is new: there is no Slack code
(only a "coming soon" placeholder in Settings, `settings-coming-soon.tsx:27`), nothing in the repo stores a
secret encrypted, and `cryptography` arrives only through other packages (`PyJWT[crypto]`), so it becomes a
direct dependency. One change in behaviour: **an alert fires only for the verified-intent tier from a known
committee member** (decision `assert`; `review` decisions appear in the app, not in Slack). Default rules:
committee member's first verified visit; a returning committee member reads a high-intent section; 2+ committee
members of one account within 7 days. Throttled per contact per day.

### 2.10 Read side, screens and agents

As WVI-5 §2.8, plus:

- **Screens need frames first.** The live-sites spec records the founders' decision to design the tracking
  screens themselves (its §18.2), and wiring never invents UI. Today: no project analytics route exists (the
  project overview's rail is `project-overview-view.tsx:29-32`); the Activity filter is by who acted, not by
  kind (`filterAccountActivity`, `account-workspace-presentation.ts:89-95`); there is no chart library, so
  charts are inline SVG (WVI-5 R7). The read routes register after `register_product_notice_routes`
  (`frontend_read/app.py:415`); tracking settings sit with the other Settings pages behind
  `workspace.manage_settings` (`settings_pages.py:469`, `clue_auth/policy.py:21`).
- **Project analytics** shows visits per page **and per section** (how many people saw each section, median time
  on it, CTA clicks), for 1:1, 1:few and 1:many sites alike. Each item says how we know (link, returning, unknown).
- **Account Activity** shows `review` visits as "probably forwarded" with a confirm/dismiss action; a confirmed
  forward to a known committee member binds that browser to them.
- **Static publishes** show page hits only, with a note that live publishing is needed for engagement.
- **Head of ABM:** `read_engagement@1` as WVI-5 (serves `assert` and `review` only; batch the profile bump with
  other catalog changes). WVI-5's version numbers are stale: the profile is at `v74` and Recipe #0 at `34`
  (`conversation_turns.py:210`, `recipe0-stage0-v34.json`), so the bump is to profile `v75` and recipe `35`
  unless another change takes them first. The tool registers like `read_artifact`
  (`artifact_read_tools.py:234-292`, `toolbelt_wiring.py:2873`) and is granted in `C6_AGENT_TOOL_AUTHORITY`
  (`agent_registry_wiring.py:308`, the `read_artifact` grant at :358).
- **Website agent:** optionally reads a short engagement summary in its `site.md` (written by `site_summary`,
  `lumen_agent/site/workspace.py:529`: "the pricing section was read by 3 committee members; nobody reached the
  FAQ"), so it can improve pages from what visitors read. Its skills (`building-with-puck`,
  `skills-e5/writing-a-section`, `skills-live/making-a-section-interactive`) say it never writes tracking or
  analytics code of its own. Ruling V3; skill text goes to the founder first.

### 2.11 Privacy, retention, DSAR

As WVI-5 §2.9 (raw `client_ip` cleared after 30 days, keeping the keyed hash; DSAR helper revoking bindings and
clearing contact references; `/_clue/optout`), plus India's DPDP Act in the consent design and privacy notice.
The DSAR helper hooks into `erase` (`subsystems/research/clue_research/compliance/dsar.py:932`, the erase-all
branch at :1032) and `record_objection` (:1064). There is no HTTP route for DSAR today; erasure runs through
`DataSubjectRightsImpl`, built in `storage_wiring.py`.

## 3. Accuracy and production quality

WVI-5's table stands, with these rows changed or added:

| Risk | Control | Proof |
|---|---|---|
| Scanners that run JavaScript in sandboxes | Real-interaction gate plus security-vendor / cloud network check; identity binds only on the first human-confirmed hit | Corporate-inbox test (Defender, Proofpoint, Mimecast): 0 bound scanner clicks |
| Cached pages | Page hits recorded at the edge, which runs on cache hits | Cache-rule test: hits counted with a forced cache |
| Beacons lost on page close | `sendBeacon` on Clue pages; image fallback | Leave-page test across browsers |
| Page code reading or forging the visitor id | `HttpOnly` cookie; `__Host-` name on Clue addresses; origin checks beacons | Tests: a page script cannot read the cookie; a `cluehq.page`-wide cookie set from another label is never read as the visitor id |
| Page code faking engagement | Beacon contents count towards a tier, never towards a name | Test: a forged beacon with no cookie and no link stays unknown |
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
| 0. Rulings | V1-V9 below; screen frames from the co-founder | 1-2 days |
| 1. Capture | migration; edge headers, bot class, page hits, POST on `/_clue/e`; origin `/r/`, `/_clue/v.js`, `/_clue/e`, `/_clue/b.gif`, `/_clue/hit`, serve-time injection on live publishes with its ETag; host kind from the workspace lookup; `VisitSink`; `kit.track` posting to `/_clue/e` (V9); access-log and refusal-log redaction | ~4-5 days |
| 2. Links | tracked-link API with scopes and message ids; Copy personal link in account, contact and Share menus; QR filling | ~2-3 days |
| 3. Resolve | ladder with the interaction gate, tiers, stitching, committee match, activity items | ~3-4 days |
| 4. Alerts | Slack app, encrypted storage, delivery, rules on verified intent; in-app | ~3 days |
| 5. Screens | Activity (incl. forward review), contact engagement, project analytics with sections, Settings, from the co-founder's frames | ~4 days |
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
- **Forms and meeting bookings on Puck pages** with `clue.identify({email})`: waits for the live-sites spec's
  phase 2 forms (`kit.Form`, `POST /_clue/forms/{slug}`), "built in a later round" (its §16); the live policy
  has `form-action 'none'` today (`publishes.py:565-575`). Booking embeds (Calendly, HubSpot meetings) come
  with that spec's phase 3, but a booking inside a provider's frame is not visible to our snippet. Forms are
  the strongest cross-device signal once they land.
- **Importing the customer's existing marketing identities** (WVI-4 path C: HubSpot `hubspotutk`, Marketo,
  Mailchimp).
- **CRM push** of visits. The founder's CRM ruling (2026-10-17) makes v1 read-only; no CRM spec is written yet,
  and the code has only the abstract read-only `CRMConnector` seam (`clue_research/resolvers/crm/__init__.py:124-147`).
- **Honeypot links:** need Clue to send the email itself; Clue does not send email today (no mail library or
  sender anywhere in the code; the lead email in the live-sites spec still waits for its email service).
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
| V9 | The live-sites spec's tracking (phase 2: `kit.track`, `POST /_clue/events/{slug}`, `site_event`, a `localStorage` visitor id) | Replaced by this design before any of it is built: one events route and one table (`visit_event`), the `HttpOnly` cookie instead of `localStorage` (page code can read `localStorage`). `kit.track` stays as the way an agent section sends a named event, posting to `/_clue/e` as an event kind; hydration reports use a reserved name as that spec planned. Its "account the site was made for" is kept as a page fact, never as identity. Once ruled, the live-sites spec §7 gets a pointer here |

Carried from WVI-5 and still recommended as written there: R2 (origin inserts, fleet claims), R4 (cookie
scope, with §2.6's `__Host-` name on Clue addresses), R5 (consent default, now with DPDP), R6 (Slack token storage), R7 (inline SVG charts). WVI-5's R1 is
replaced by V1 (injection only on live publishes); R3 is replaced by V4.
