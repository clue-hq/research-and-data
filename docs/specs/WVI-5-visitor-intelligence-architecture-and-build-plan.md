# WVI-5. Visitor intelligence: architecture and build plan

**Written 2026-10-17** on branch `feature/visitor-intelligence`, cut from `origin/research-streaming @ 61f9d1bf9`
(alembic head `ddf063300a0b`). Seams verified against this tree by three read-only code maps (page serving,
backend data/fleet, frontend/agent). **This document supersedes WVI-3 §1, §2's `down_revision`, and §3.B/§3.E**:
the design API `/w/{ws}/p/{slug}` routes WVI-3 hooks were removed (`lumen_api/main.py:1122-1123`), and the
frontend files WVI-3 §3.E cites do not exist. WVI-3's product answers (§0) and WVI-4's research still stand.

## 0. Founder model (ratified in chat 2026-10-16)

- Every landing page lives in Clue. By default it is served at the workspace's Clue address
  (`<label>.pages.cluehq.ai/<slug>`); once the customer connects a custom domain in Settings, the same pages
  serve at their address (`pages.google.com/<slug>`). Nothing is exported. (v1 custom domains are subdomain-only,
  `clue_spine/hostnames.py:185-208`.)
- Tracking is **one Clue snippet**: Clue injects it into every page it serves; the customer pastes the same
  snippet into Google Tag Manager or their site head **only for their own website**.
- Identification is **deterministic**: the snippet fires and a personal tracked link / QR (plus UTMs) says who
  and from which campaign. Scope = target accounts and their buying committees.
- After a person is identified once, the browser is recognised later on Clue pages and on the customer's own
  site (parent-domain cookie on custom domains), and earlier anonymous visits from that browser are back-filled.
- Alerts go to Slack and in-app; analytics live in the app.

## 1. Architecture

```
 Personal link / QR / ad ─┐                         Customer's own site (google.com)
 (Clue-minted, UTMs)      │                         └─ Clue snippet via GTM / <head>
                          ▼                                      │ image beacon (GET)
          ┌──────────── Cloudflare Worker  pages-edge ───────────┴──┐
          │  stamps x-clue-client-ip, x-clue-geo (country/asn/org),  │
          │  first-pass bot class; GET/HEAD only (unchanged)        │
          └──────────────────────────┬──────────────────────────────┘
                                     ▼
          ┌──────────── Page origin  clue_page_origin ──────────────┐
          │ /{slug}        serve page + inject <script src=/_clue/v.js>
          │                 + server-side page_view capture (no JS)  │
          │ /r/{token}     record click, set clue_vid, 302 → page+UTMs│
          │ /_clue/v.js    the snippet (same file for customer sites) │
          │ /_clue/b.gif   beacon: human confirm, dwell, scroll, nav  │
          │  → INSERT visit_event (append-only, fast, no resolution)  │
          └──────────────────────────┬──────────────────────────────┘
                                     ▼  (fleet sweep / enqueue)
          ┌──────────── Fleet: VISITOR_RESOLVE ─────────────────────┐
          │ bot/scanner filter → human confirm → identity            │
          │ (token first human click / bound cookie / account page)  │
          │ → stitch & back-fill → committee + target-account match  │
          │ → visitor_resolution (assert | review | unknown)         │
          │ → account_activity_event(kind='visit') → alert rules     │
          └───────────────┬──────────────────────────┬──────────────┘
                          ▼                          ▼
          Fleet: VISITOR_ALERT_DELIVER       Read API /frontend/v1/...
          Slack (OAuth bot) + in-app         Activity tab · contact engagement ·
                                             project analytics · settings ·
                                             Head of ABM read_engagement@1
```

**Design laws.** (1) Unknown is a correct answer; a wrong name is the only failure. (2) The page origin only
appends rows; it never resolves, so page latency and the 256 MB origin are unaffected. (3) Nothing personal is
ever in a URL: tokens are opaque and stored as digests. (4) Every assertion carries its method and evidence
(`link`, `returning`, `account_page`; later `form`, `reverse_ip`). (5) All new behaviour sits behind
per-workspace switches and env flags documented in `.env.example` in the same commit.

## 2. Components and exact seams

### 2.1 Edge: `infra/cloudflare/pages-edge/`
- In `routing.js:11-15` (same pattern as the public-host strip at `:12-13`): delete inbound `x-clue-client-ip`,
  `x-clue-geo`, `x-clue-bot`, then stamp them from `cf-connecting-ip` and `request.cf` (`country`, `asn`,
  `asOrganization`). `decide()` must tolerate missing `request.cf` under `node --test`.
- First-pass bot class from user agent (LinkedInBot, Slackbot, facebookexternalhit, Googlebot, Microsoft Safe
  Links / Defender, Proofpoint, Mimecast, Barracuda, preview fetchers). The origin re-checks.
- No routing change needed: every path on an "ours" host is already forwarded (`routing.js:3-18`). GET/HEAD-only
  stays. Add a Cloudflare rate-limit rule on `/_clue/*` and `/r/*`.

### 2.2 Page origin: `platform/page_origin/clue_page_origin/`
- **Serve-time injection** in `page()` / `route_page()` (`routes.py:150-152`, `168-170`): insert
  `<script src="/_clue/v.js" defer></script>` before `</head>` when the workspace has tracking on; compute the
  ETag over the served bytes. Covers every existing page on both hostnames with no republish and keeps publish
  packages host- and tracker-free (custom-domain spec rule 9). Root-relative src satisfies the CSP
  (`script-src 'self'`) and the no-absolute-URL-in-head pin.
- **Server-side capture** on the page GET itself (works without JavaScript; HEAD not logged).
- **New routes** declared before `routes.py:130` (`r` and `_clue` cannot collide with publish slugs, which are
  3-64 chars, `toolbelt/publishes.py:57`):
  - `GET /r/{token}`: workspace-scoped token lookup, record `link_click`, set `clue_vid`, 302 to the target page
    with UTMs, `Cache-Control: no-store`. Unknown/expired token → workspace fallback URL (`_miss`, `:72-76`).
  - `GET /_clue/v.js`: the snippet (§2.3), `public, max-age=300`.
  - `GET /_clue/b.gif`: 1×1 GIF beacon, `no-store`, may set/refresh `clue_vid`.
- **Beacons are image GETs.** The published CSP has `connect-src 'none'` and `form-action 'none'`, pinned
  byte-exact (`tests/design/test_publish_delivery.py:17-30`, `subsystems/clue-design/apps/api/tests/test_web_export.py:936-967`)
  and baked into immutable revisions' meta tags. `img-src 'self'` already allows `new Image().src='/_clue/b.gif?…'`,
  so **no CSP change is required**.
- **Cookies.** Page HTML responses stay `public, max-age=60` and never set cookies; only `/r/` and `/_clue/b.gif`
  (both `no-store`) set `clue_vid`. On a **custom** hostname set `Domain=<registrable_domain(host)>`
  (`clue_spine/hostnames.py:174-182`) so the customer's whole site shares it; on the **system** hostname use a
  host-only cookie (a `Domain=pages.cluehq.ai` cookie would cross tenants). The workspace lookup at
  `routes.py:69-70` must also return the hostname kind. `Secure; SameSite=Lax; Max-Age=400 days`.
- **Writes.** A `VisitSink` protocol injected next to `reads` in `create_page_origin_app` (`app.py:17-19`),
  faked in tests (`tests/page_origin/conftest.py:98-104`). Insert via a background task; `clue_worker` already has
  INSERT (`docs/deploy/runbook.md:70-78`).
- **Logs.** Redact `/r/{token}` paths in the uvicorn access log (`main.py:64-72`) and edge-refusal logs
  (`edge.py:49-53`). Never log IP or email fields (`clue_obs/redact.py`).
- **Tests to update:** `tests/page_origin/test_routes.py` body/header pins (:18, :20-24, :40, :131-135).

### 2.3 The snippet `/_clue/v.js` (≤ 3 KB, one file for both surfaces)
- Reads/sets first-party `clue_vid`; 30-minute session id; reads `?cl=` (link decoration) and strips it with
  `history.replaceState`; captures path, title, referrer host, UTMs; SPA route changes; dwell and max scroll on
  `pagehide`/`visibilitychange`; sends via image beacon to the same origin it loaded from.
- **On the customer's site** it loads from the workspace's active hostname, preferably the custom one
  (`https://pages.google.com/_clue/v.js`), so the beacon is same-site and the parent-domain cookie flows. Without
  a custom domain it loads from `<label>.pages.cluehq.ai` and cross-page recognition relies on link decoration.
- **Link decoration:** on Clue pages, outbound links to the customer's registered domains get `?cl=<visitor
  token>` (like Google Analytics cross-domain `_gl`), so a click-through is recognised even without a custom domain.
- **Consent:** honours `navigator.globalPrivacyControl` and DNT (never sets the cookie; event marked `gpc`);
  `consent_mode` per workspace: `auto` (US track, EU wait), `wait`, `off`. In `wait`, sessionStorage-only id until
  a CMP grant (OneTrust `OneTrustGroupsUpdated`, Cookiebot `CookiebotOnAccept`) or `clue.consent('granted')`.
- No fingerprinting, no form-field sniffing. `clue.identify({email})` only on an explicit customer call (later).
- **Abuse control on customer sites:** the beacon is accepted only when the `Referer`/page host is in the
  workspace's `allowed_hosts`; otherwise a silent 204-equivalent (still returns the GIF).

### 2.4 Tracked links and QR (platform API + design API)
- `POST /frontend/v1/tracked-links` `{accountId, contactId?, projectId, channel, targetSlug?, artifactRef?}`
  with `Idempotency-Key` → `{token, url, expiresAt}`. Token: 96+ random bits, base62, stored as SHA-256 digest
  (the house pattern, `clue_auth/provisioning.py:66-70`). URL uses the workspace's active hostname
  (custom if active, else system): `https://pages.google.com/r/x7k2Q9…`.
- UTMs are set by Clue per channel: `utm_source` (email, linkedin, direct_mail, ads), `utm_medium`,
  `utm_campaign` = project, `utm_content` = artifact/creative. Ad URLs use platform dynamic parameters for
  campaign/creative ids. Ads stay account- or campaign-level; only 1:1 channels name a person.
- **QR on print/direct mail:** fill `BindingSet.links.*.url` server-side at `POST /binding-sets`
  (`lumen_api/main.py:6398-6453`, before validation at `:6416`) or in `_derive_and_persist_instance`
  (`:6264-6290`), keyed by `BindingAudience(account_id, contact_id)` (`binding.rs:37-42`). The existing
  `generated.qr.url_from` chain (`binding.rs:564-625`, `qr.rs:109`) then renders a different QR per copy; re-derive
  stays idempotent per `binding_set_id`. Print the short URL under the QR.
- **ABM web pages:** add `account.tracked_url` to `account_values` (`main.py:11865-11905`). Page → account join is
  `design_web_publish.document_id → design_document.account_id → design_account.account_entity_id`.

### 2.5 Data model: one migration, `down_revision = "ddf063300a0b"`
Raw SQL in `op.execute`, text + named CHECKs (no new DB enums), composite FKs on `(id, workspace_id)`, UTC
timestamptz, reversible; template `89791cb5949e_provider_incident.py`.

| Table | Purpose and key columns |
|---|---|
| `tracked_link` | `link_id`, `workspace_id`, `token_digest` UNIQUE, `project_id`, `account_entity_id`, `contact_entity_id` NULL, `channel` CHECK, `utm` jsonb, `artifact_ref` jsonb, `target_slug`, `created_by_user_id`, `created_at`, `expires_at` (180 d), `revoked_at`, `first_human_click_at`, `bound_visitor_id` |
| `web_visitor` | `visitor_id` uuid, `workspace_id`, `cookie_scope` CHECK host/parent, `first_seen_at`, `last_seen_at` |
| `visit_event` | append-only: `event_id`, `workspace_id`, `visitor_id`, `session_id`, `occurred_at`, `kind` CHECK (page_view, link_click, beacon, leave), `hostname`, `host_kind`, `surface` CHECK (clue_page, customer_site), `path`, `slug`, `document_id`, `referrer_host`, `utm` jsonb, `link_id`, `user_agent`, `client_ip` (nulled after retention), `ip_hash`, `country`, `asn`, `as_org`, `bot_class` CHECK, `consent_state`, `gpc`, `dwell_ms`, `max_scroll`, `resolved_at`; index `(workspace_id, occurred_at DESC)` and partial on `resolved_at IS NULL` |
| `visitor_identity_binding` | `workspace_id`, `visitor_id`, `contact_entity_id` NULL, `account_entity_id`, `method` CHECK (link, returning, account_page, form, import), `strength` CHECK (strong, weak), `evidence` jsonb (link_id, event_id), `created_at`, `revoked_at` |
| `visitor_resolution` | per session: `account_entity_id`, `contact_entity_id`, `method`, `strength`, `decision` CHECK (assert, review, unknown), `reasons` jsonb, `committee_member` bool, `target_account` bool |
| `visit_alert_rule` / `visit_alert` | rules (trigger, scope, thresholds, destination) and fired alerts with UNIQUE `dedupe_key` |
| `workspace_integration` | Slack: `team_id`, `channel_id`, `bot_token_ciphertext` bytea, `key_id`, `status` |

Also widen `account_activity_event.kind` CHECK (`65fb2128c904:262-263`) to include `visit` and write summaries
there (detail in `ref_json`), so the existing feed path (`frontend_read/v1_shared.py:1180-1244`) serves visits.
Downgrade fails loudly while `visit` rows exist (house pattern, `ddf063300a0b:84-96`).

### 2.6 Resolution: fleet `VISITOR_RESOLVE` (+ `VISITOR_ALERT_DELIVER`)
- Append both kinds after `PRODUCT_PAGE_WRITE` (`clue_fleet/enums.py:80`; migration on `1ecc7437e5bc`'s pattern;
  relax `tests/db/test_product_page_write_kind_migration.py:27`). Handlers in a new
  `platform/api/clue_api/visitor_intel/` package, registered in `build_multi_work_worker` (`fleet_wiring.py:383`),
  priority ≈ -50, `work_id` uuid5, dedup `visitor-resolve:{session}`.
- Pickup: the origin only inserts; a fleet loop (maintenance-run pattern, `fleet_main.py:238`,
  `storage_wiring.py:246-300`) claims `resolved_at IS NULL` rows every 2-5 s. (Alternative: give page_origin a
  `clue-fleet` dependency and enqueue in the insert transaction; decision R2.)
- **Ladder per session:** (1) drop bots and scanners (§3); (2) require a human signal (beacon from executed JS, or
  a second request within the session); (3) identity: token on its **first human** click binds `visitor ↔
  contact` STRONG; the same token from another browser = WEAK "forwarded", decision `review`; a bound cookie =
  `returning`; an ABM account page = account only; (4) stitch: back-fill the visitor's earlier unresolved
  sessions; (5) relevance: `project_account` membership (`clue_research/membership.py:238`) and committee via
  ARV2 `committee_members` (`arv2/display/gather.py:342`); (6) write `visitor_resolution`, the activity summary,
  and evaluate alert rules.

### 2.7 Alerts
- Default rules: committee member first visit; returning committee member viewed a high-intent page (pricing,
  security, integrations, configured per workspace); account with 2+ committee visitors in 7 days. Throttle per
  contact per day (`dedupe_key`), quiet hours optional.
- **Slack:** a Clue Slack app (OAuth, `chat:write`, channel picker). No token-storage pattern exists today: add
  `CLUE_INTEGRATION_ENCRYPTION_KEY` (Secrets, `secrets.py:59`), a direct `cryptography` dependency, AES-GCM
  ciphertext with key id. `VISITOR_ALERT_DELIVER` retries with `requeue_after`.
- **In-app:** the product-notice pattern (`frontend_read/product_notices.py`, dismissal table); later a nudge
  into the Head of ABM conversation and the "Today" queue from the email follow-up work.

### 2.8 Read side and screens
- Backend: new `frontend_read/visitor_intel.py` with `register_visitor_intel_routes`, registered after
  `frontend_read/app.py:415`; template `product_notices.py`; Settings routes on the `settings_pages.py:466-560`
  pattern with `workspace.manage_settings`.
  - `GET /accounts/{id}/visits`, `GET /contacts/{id}/engagement`, `GET /projects/{id}/engagement?range=30d`,
    `GET /visitors/live` (poll 10-15 s; no workspace push channel exists), `GET|PATCH /settings/website-tracking`,
    `POST /tracked-links`, Slack connect/disconnect.
- Frontend (repository seam: Zod model → repository with fixture + HTTP adapters → hook → component):
  - **Activity tab:** add `visit` to `AccountActivitySchema` (`model/account-detail.ts:47-59`), the icon map
    (`account-activity-feed.tsx:7`, `public/icons/detail/globe.svg`), a "Visits" filter
    (`account-library-screens.tsx:139-163`, `account-workspace-presentation.ts:72-88`). Each item shows how we know.
  - **Copy tracked link:** account header menu (`account-workspace-shell.tsx:206-236`), contact preview menu
    (`contacts/components/contact-preview.tsx:80-86`), contact row (`contact-row.tsx:147`); add
    `copyText(value)` to `hooks/use-copy-feedback.ts`.
  - **Contact engagement:** `webEngagement` on `AccountContactDetailSchema` (`model/account-contact.ts:59-91`),
    rendered in `contact-profile-content.tsx:256-328`.
  - **Project analytics:** new route `app/(protected)/projects/[projectId]/analytics/page.tsx`, linked from
    `project-overview-view.tsx:19`, plus an "Engagement" rail block with three stat tiles. No chart library exists:
    use token-driven inline SVG (the design-token test resolves every `var(--clue-…)`).
  - **Settings → Website tracking:** new section via `model/settings.ts:4-14`, `config/settings-navigation.ts`,
    `settings-screen.tsx:8-18`, `settings-read.ts:10-32`, settings `page.tsx:47-104`; reuse `CustomDomainCard`,
    `DnsRecordTable`, `StatusStepper`, `SettingsToggle`. Shows: snippet with copy, install status ("last seen on
    google.com 4 min ago"), allowed hosts, consent mode, alert rules, Slack connect.
  - Update `apps/frontend/docs/api-contracts/*.md` per the contract-gap rule.
- **Agent:** `read_engagement@1` (template `artifact_read_tools.py:234-293`), registered in
  `toolbelt_wiring.py:2853-2870`, authority in `agent_registry_wiring.py:290-340`, profile v72→v73, recipe v36,
  `tool_notes.yaml`, `make manual`. Serves only `assert`/`review` decisions. **Batch this with other catalog
  changes**: every pin bump discards conversation continuation on live threads.

### 2.9 Privacy, retention, DSAR
- Raw `client_ip` nulled after 30 days (`CLUE_WVI_RAW_IP_RETENTION_DAYS`), keeping `ip_hash`; retention loop on the
  maintenance-run pattern.
- DSAR: a helper called from `erase()`'s ERASE_ALL branch (beside `compliance/dsar.py:1033`) and from
  `record_objection` (`:1064`) that revokes bindings and nulls contact references on resolutions; extend the access
  export (`:396`). (No HTTP DSAR route exists yet; compliance wiring is deferred.)
- Opt-out: `GET /_clue/optout` sets a do-not-track cookie and suppresses the visitor. Privacy-notice paragraph for
  customer pages and their site (US opt-out + GPC; EU consent).

## 3. Accuracy and production quality

| Risk | Control | Proof |
|---|---|---|
| Email security scanners pre-click links | UA + datacenter ASN class at edge and origin; scanner pattern (several links in one message hit within ~2 s, no JS, HEAD/prefetch); **identity binds only on the first human-confirmed hit** | Corporate-inbox test (Microsoft Defender, Proofpoint, Mimecast) shows 0 bound scanner clicks |
| Link-preview bots (LinkedIn, Slack, iMessage) | UA list; never bind; never alert | Share a link in each, 0 events marked human |
| Forwarded links | Token is single-identity: other browsers → `review`, never asserted | Forward test |
| Wrong person on shared devices | Cookie binding carries the method and date; a new token on the same browser supersedes | Two-person, one-laptop test |
| Lost cookies (Safari ~7 d, private mode, new device) | Report as unknown; any later personal-link click back-fills | Matrix test per browser |
| Duplicate counting | Session id, dedupe on reload, event ids, idempotent handlers | Reload storm test |
| Missed events | Server-side capture on page GET, independent of JS; canary | Canary every 10 min in prod |
| Slow or failed alerts | Fleet retries, dead-letter, latency metric | p95 alert latency < 60 s |
| Abuse / spoofed beacons | allowed-hosts check, Cloudflare rate limits, payload caps, tokens unguessable | Fuzz and rate tests |

**Known-visitor harness** (`scripts/wvi_known_visitor_test.py` + a manual sheet): about 20 known people, each sent
personal links through email, LinkedIn DM, printed QR and an ad, across iPhone camera, Android, desktop
Chrome/Safari/Firefox, LinkedIn in-app and email in-app browsers. Scorecard gates before any customer sees it:
**named-person precision 100%** on the test set, **≥ 95% of known human visits captured**, **0 bot alerts**,
**alert p95 < 60 s**, back-fill and forward cases correct.

**Monitoring:** metrics through `get_metric_sink` (events in, bot share, human share, assert/review/unknown, link
clicks, alerts fired/delivered/failed, latency); a per-workspace "tracking health" line in Settings; a synthetic
canary visit to a test page every 10 minutes that alarms if not recorded within 2 minutes.

## 4. Build order (fastest path)

| Step | Scope | Rough size |
|---|---|---|
| 0. Rulings | R1-R7 below, signed off by Aryan | 1-2 days |
| 1. Capture | migration; edge headers; origin `/r/`, `/_clue/v.js`, `/_clue/b.gif`, serve-time injection, server-side capture; `VisitSink` | ~4 days |
| 2. Links | tracked-link API + "Copy tracked link" UI; ABM `account.tracked_url`; QR link filling | ~2 days |
| 3. Resolve | `VISITOR_RESOLVE` ladder, stitching, committee/target match, activity `visit` items | ~3 days |
| 4. Alerts | Slack app + encrypted storage + delivery + rules; in-app alerts | ~3 days |
| 5. Screens | Activity tab, contact engagement, project analytics, Settings → Website tracking | ~3 days |
| 6. Customer site | snippet on customer domains, allowed hosts, link decoration, consent modes, install check | ~2 days |
| 7. Harden | harness run, canary, metrics, retention, DSAR hook, `read_engagement@1` | ~3 days |

Roughly **three to four weeks for one engineer**, with a usable internal demo (link → visit → Activity tab →
Slack) after steps 1-4. Steps 1-3 can start the day the rulings land.

**Later (not in this build):** own IP-to-company database (WVI-4 path B), CRM binding import (path C), anonymous
person-level (path D, rulings W18-W20), `clue.identify` form capture.

## 5. Rulings needed (Aryan)

| # | Decision | Recommendation |
|---|---|---|
| R1 | Snippet injection point | Serve time in the page origin behind a per-workspace switch (no republish, packages stay tracker-free); amends the custom-domain spec's deferred head-snippet review |
| R2 | How visits reach the fleet | Origin inserts rows only; fleet loop claims unresolved rows (keeps page_origin free of a fleet dependency) |
| R3 | Beacon transport | Same-origin image GET; **no CSP change**, no POST at edge or origin |
| R4 | Cookie scope | Parent-domain cookie on custom hostnames only; host-only on `*.pages.cluehq.ai` |
| R5 | Consent default | `auto`: track US, wait for consent in EU/UK; GPC and DNT always honoured |
| R6 | Slack token storage | New `CLUE_INTEGRATION_ENCRYPTION_KEY` + AES-GCM ciphertext column; first stored integration secret in the DB |
| R7 | Charts | Token-driven inline SVG for V1, no chart dependency |
