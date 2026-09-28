# WVI-3 — Website de-anonymization: the implementation plan

**Status:** implementation plan, 2026-09-27, branch `feature/website-deanonymization`. Supersedes WVI-1 §4/§6/§7 and
WVI-2 §4.5 wherever this document differs (§5 lists every correction). Awaiting founder rulings (§6).
**Companions:** `WVI-website-visitor-identification.md` (WVI-1: vendors, ladder, legal, rulings W1–W9),
`WVI-2-research-register-and-90pct-blueprint.md` (research register, precision principles, C1–C12).
**Method tags:** `[REPO]` verified in this worktree at `cc695283e` (paths repo-relative, `file:line`) ·
`[FETCHED]` read from the vendor's live page this session · `[SNIPPET]` search text only · `[VENDOR]` vendor claim.

---

## 0. The five product questions, answered

### 0.1 How do we add website de-anonymization to Clue?

Three surfaces, one pipeline. Every surface produces the same `web_visit_event` row; one fleet handler resolves it
up the ladder and writes the result as activity + claims that the existing screens and agent already read.

| Surface | Who installs what | Identification available | Phase |
|---|---|---|---|
| **Clue-hosted pages** (`/w/{ws}/p/abm-<account>`) | nothing — Clue's own page server logs the request | tracked-link token (person), page-is-per-account (account), reverse IP (account) | V0 |
| **Outbound links** (email, LinkedIn DM/InMail, ads, QR on mail) | the rep copies a tracked link from the account/contact screen; later the content and design layers mint them automatically | deterministic person or account, plus channel + artifact attribution | V0 (manual) → V3 (automatic) |
| **The client's own website** | a one-line `clue.js` snippet with a per-domain pixel key | reverse IP (account), returning-visitor recognition, tracked links, and — US-only, gated, default off — identity-graph person reveal | V1 (company) → V2 (person) |

The ladder per visit (WVI-2 §4.3): exclude bots/VPN/cloud/relay → token → returning visitor → reverse IP → account
bind → (US, consented, target account, cap OK) graph reveal → AI Ark email→LinkedIn → contact bind → write.
"Unknown" is a valid answer; a wrong name is the only failure.

### 0.2 What do we need to prepare?

| Area | Item | When |
|---|---|---|
| Rulings | W3 (opaque token in URL), W4 (server-side on Clue pages), W9 amended (V0 does not wait for ARV2 D3), new W10–W13 in §6 | before V0 code |
| Keys | ipregistry API key (20,000 free credits, no card `[FETCHED]` <https://ipregistry.co/pricing>) | V0 |
| Infra | a public hostname for the design API's page routes and for the collector; `FORWARDED_ALLOW_IPS` set on Railway/ngrok so the real client IP survives the proxy (§4.1) | V0 / V1 |
| Legal | privacy-policy paragraphs (US opt-out + GPC; EU company-level-only legitimate-interest) and a cookie-banner category for `clue_vid`; DPA clause naming Clue as processor for the tracker (Leadfeeder's model `[FETCHED]` <https://help.leadfeeder.com/en/articles/13922333-leadfeeder-tracker-data-processing-roles>) | V1 |
| Measurement | a list of ≥20 known people who will visit cluehq.ai from a tracked link and untracked (the known-visitor test, WVI-2 §1.J) | V1 |
| Person-level vendor | Leadpipe Platforms POC request ("3-month POC with high limits", no published price) or RB2B Pro ($149/mo, webhook payload has LinkedIn URL) as the control `[FETCHED]` <https://www.leadpipe.com/pricing/>, <https://www.rb2b.com/pricing> | V2 |
| Pilot | one client site willing to install the snippet and share a known-visitor list | V1 |

### 0.3 Is it going to be a website snippet?

**On Clue-hosted pages: no.** The page server already sees IP, user agent, referrer and query string, the published
page's CSP is `connect-src 'none'` in both the response header and a baked-in `<meta>` tag with a test pinning it
`[REPO]` `subsystems/clue-design/apps/api/lumen_api/web_export.py:1264-1288`,
`subsystems/clue-design/apps/api/tests/test_custom_component_publish.py:386-387`. Collection is a server hook (§3 slice B).

**On the client's website: yes, one line**, the same shape every vendor uses:

```html
<script async src="https://t.cluehq.ai/p/<pixel_id>.js"></script>
```

`clue.js` (≤2 KB, generated per pixel so the id and collector origin are embedded) does exactly this and nothing else:
sets a first-party `clue_vid` cookie (13 months) and a 30-minute session id; reads and strips `?cl=`; records page
URL, referrer, UTMs, and SPA route changes; sends via `navigator.sendBeacon` with `fetch(keepalive)` fallback;
honours `navigator.globalPrivacyControl` and DNT by never setting the cookie and marking the event `gpc=true`;
in consent jurisdictions runs in `waitForConsent` mode (sessionStorage-only id until a CMP grant — Snitcher's pattern
`[FETCHED]` <https://docs.snitcher.com/product/tracker/cookie-consent>), auto-detecting OneTrust
(`OneTrustGroupsUpdated`, group `C0004`), Cookiebot (`CookiebotOnAccept`, `Cookiebot.consent.marketing`) and exposing
`clue.consent('granted'|'denied')` for everything else; exposes `clue.identify({email})` for form fills. No
fingerprinting library in V1 (WVI-2 P2: fingerprints recognise, never identify). Installed via GTM Custom HTML, Webflow
/HubSpot head code, or a first-party CNAME proxy (`t.<client>.com`) later, exactly as PostHog/Plausible document
`[FETCHED]` <https://posthog.com/docs/advanced/proxy/cloudflare>, <https://plausible.io/docs/proxy/introduction>.

### 0.4 How do we manage the pixel?

A **pixel is a row**, not a secret. Copy the model every vendor converged on `[FETCHED]` RB2B
<https://support.rb2b.com/en/articles/10126115-installing-your-rb2b-tracking-script>, Vector
<https://learn.vector.co/articles/9526804207-allowlist-and-denylist-settings>, Leadpipe
<https://docs.leadpipe.com/guides/manage-pixels.md>:

- `wvi_pixel (pixel_id, workspace_id, domain, allowed_hosts[], path_denylist[], status active|paused, consent_mode
  auto|wait|off, created_at, rotated_from)`. One pixel per registrable domain; `allowed_hosts` accepts wildcard
  subdomains; the denylist wins over the allowlist (Vector's rule) so `/account/*` or `?token=` pages never report.
- The **pixel id is public and write-only**. The collector accepts an event only if the pixel is `active` and the
  request's `Origin`/`Referer` host matches `allowed_hosts`; a mismatch is a silent 204 (never leak whether a pixel
  exists). Server-side calls (webhooks, API) use a separate `Secrets` key, never the pixel id (Leadpipe's warning).
- **Rotation** = create a new pixel with `rotated_from`, pause the old one; a paused pixel's script returns a no-op body.
- **Abuse control**: per-pixel token bucket on the collector (reuse `clue_locks.RateLimiter`, a Redis Lua bucket keyed
  by an arbitrary string `[REPO]` `libs/clue-locks/clue_locks/rate_limit.py:43-69`; it is built nowhere today), body
  ≤ 4 KB, `202` enqueue-only, no response body that could be probed.
- **Where a client manages it**: there is no settings UI in the frontend at all `[REPO]` (protected routes are only
  accounts, brand-context, projects; `apps/frontend/src/config/navigation.ts:15-25`). V1 ships a minimal
  "Website tracking" page: snippet + copy button, domain + allowlist, status, consent mode, the "person-level reveal:
  off / US-only" switch (W6), and the coverage numbers from the harness. Until it exists the pilot is provisioned by API.

### 0.5 How do we match the person who comes to the website via LinkedIn?

**The honest answer: LinkedIn never tells a website which member clicked.** The Insight Tag returns aggregated
demographics only (≥300 matched members) and LinkedIn states "we don't share the personal data of members with you"
`[FETCHED]` <https://www.linkedin.com/help/lms/answer/a427660>. Organic clicks arrive through `lnkd.in` with a `trk=`
parameter and, from the iOS app, often no referrer at all; the paid-ads `li_fat_id` resolves to a member only inside
LinkedIn's Conversions API, never for us `[FETCHED]`
<https://learn.microsoft.com/en-us/linkedin/marketing/conversions/enabling-first-party-cookies?view=li-lms-2026-07>.
Every vendor that "finds the person on LinkedIn" does it the other way round: identity graph → email → B2B lookup →
LinkedIn URL (RB2B `[FETCHED]` <https://support.rb2b.com/en/articles/11155068-contact-level-identification>).

So Clue matches LinkedIn traffic with four mechanisms, strongest first:

1. **Per-recipient tracked links in DMs / InMail / comments (deterministic, worldwide, free).** The rep copies a
   contact-level link from the contact profile (`?cl=<token>`, channel `linkedin_dm`); the click binds `clue_vid` ↔
   contact with `identity_binding=STRONG`. The `?cl=` design is the one Userled ranks above every other method
   `[FETCHED]` <https://intercom.help/userled/en/articles/9515210-identity-layer>. Two guards: LinkedIn's link-preview
   crawler fetches every shared URL once "within seconds" with UA `LinkedInBot/1.0` from `*.fwd.linkedin.com` — it must
   be dropped before it consumes the token `[FETCHED]` <https://knownagents.com/agents/linkedinbot>; and a token must
   be **re-usable but single-identity**: the first human click binds, later clicks from other browsers are `WEAK`
   (forwarded link) and go to review (WVI-2 P3).
2. **Channel attribution for untracked LinkedIn clicks.** Referrer `linkedin.com` / `lnkd.in` or `utm_source=linkedin`
   → `channel=linkedin` on the event; the account comes from rung 1 (reverse IP) or from the page being per-account.
   That answers "which target accounts are clicking our LinkedIn posts" without naming anyone.
3. **Rung 2 for the unknown US visitor** (V2, gated, default off): graph reveal → email → AI Ark
   `POST /v1/people/reverse-lookup` (0.5 credit, returns `link.linkedin`) `[FETCHED]`
   <https://docs.ai-ark.com/reference/people-reverse-lookup> → cross-check employer against the IP holder → bind to a
   contact by `linkedin_url`/`verified_email` or insert as `needs_review`.
4. **Retargeting, not identification** (V3): identified contacts and target accounts → LinkedIn Matched Audiences
   (SHA-256 emails, ≥300 matches to serve) `[FETCHED]` <https://www.linkedin.com/help/lms/answer/a1489764>.

---

## 1. Architecture, verified against the repo

```
outbound artifact ──?cl=token──▶ Clue page server (design API, lumen_api)      client site ──clue.js──▶ POST /v1/collect
                                  │ middleware hook: GET /w/{ws}/p/{slug}          (platform projections app, public,
                                  │  drop bots · read cookie/IP/UA/referrer         pixel-keyed, rate-limited, 202)
                                  │  strip ?cl= · set clue_vid                              │
                                  ▼                                                          ▼
                    INSERT web_visit_event (raw SQL)  +  enqueue_task(VISITOR_RESOLVE, dedup visitor/day, reopen)
                                  │
                                  ▼  fleet worker (platform/api/clue_api/fleet_main.py)
                    VisitorResolveHandler ── exclusion lists ── visitor_link ── reverse_ip Resolver ── identity.resolve
                                  │                                   (V2: identity_graph Resolver ── AI Ark ── contact bind)
                                  ▼  one transaction
                    visitor_resolution (+cost cols) · claims account/contact.web_engagement (insert_claim) · labels
                                  │
                                  ▼
                    /frontend/v1 reads: Activity `visit` kind · account "Researched fields" · contact signal · (V3) agent tool
```

**The seam decision.** The design *app* (`lumen_api`) already imports `clue_fleet` lazily to enqueue `design_job`
`[REPO]` `subsystems/clue-design/apps/api/lumen_api/design_store.py:1813-1847`; the design *substrate* (`clue_design`)
may not (Rule S4, `pyproject.toml:552-574`), and neither may import research. So the collector in `lumen_api` writes the
`web_visit_event` row with `sqlalchemy.text` and enqueues via `clue_fleet` — it communicates through the database and
the queue, never through a research import. All resolution logic lives in the research subsystem
(`subsystems/research/clue_research/wvi/`), wired at the platform composition root (`platform/api/clue_api/wvi_wiring.py`,
`fleet_wiring.py`, `fleet_main.py`). The `/v1/collect` route lives in the platform projections app next to the Exa
webhook (`platform/api/clue_api/projections_app.py:931-932` mounts routers with no auth dependency).

**Why the hook is middleware, not the route.** The three `/w/` routes are marked temporary — Part IV item 5 deletes
them when hosting moves `[REPO]` `lumen_api/main.py:5432-5438`; the app-wide `structured_request_logging` middleware
(`main.py:779-836`) already reads `request.client.host` and survives that move. The hook matches `GET`, path prefix
`/w/`, HTML `200`.

---

## 2. Data model — one migration (`down_revision = "44039cb83844"`, hash id, `make db-smoke`)

| Table | Columns | Notes |
|---|---|---|
| `visitor_link` | `token text PK` (22-char url-safe random), `workspace_id`, `project_id NULL`, `account_entity_id NULL`, `contact_entity_id NULL`, `channel` CHECK (`email`,`linkedin_dm`,`linkedin_post`,`ad`,`direct_mail`,`other`), `artifact_ref text NULL`, `target_url text`, `created_by`, `created_at`, `expires_at NULL`, `first_click_visitor_id NULL` | random, never derived from ids (W3). `first_click_visitor_id` implements "first click binds, later browsers are WEAK". |
| `web_visit_event` | `event_id uuid PK`, `workspace_id`, `pixel_id NULL`, `visitor_id text`, `session_id text`, `link_token NULL`, `page_url text` (token stripped), `page_slug NULL`, `referrer NULL`, `utm jsonb`, `ip inet NULL` (nulled by the retention job after 30 d), `ip_hash text` (salted), `geo_country char(2) NULL`, `ua_class text`, `traffic_class text` (`enterprise`,`isp`,`hosting`,`vpn`,`relay`,`bot`,`unknown`), `consent_state` CHECK (`granted`,`denied`,`not_required`,`unknown`), `gpc bool`, `received_at`, `resolved_at NULL` | append-only. Bots are dropped before insert; `traffic_class` is set by the handler. |
| `visitor_resolution` | `resolution_id uuid PK`, `event_id FK`, `workspace_id`, `visitor_id`, `method` CHECK (`link`,`returning`,`reverse_ip`,`identity_graph`,`form`), `provider text NULL`, `account_entity_id NULL`, `contact_entity_id NULL`, `visiting_company jsonb NULL` (name, domain when no account exists), `identity_binding` (`strong`,`weak`) NULL, `decision` CHECK (`assert`,`review`,`refuse`,`unknown`), `checks jsonb`, `score numeric NULL`, `cost_cents int`, `latency_ms int`, `decided_at`, `superseded_by NULL` | append-only decision ledger (WVI-2 C12 + P10) **and** the V0 cost ledger — no workspace-level cost ledger exists in code `[REPO]` (closest: `source_call_observation`, project-run-scoped). |
| `wvi_pixel` (V1) | `pixel_id text PK`, `workspace_id`, `domain`, `allowed_hosts text[]`, `path_denylist text[]`, `status`, `consent_mode`, `created_at`, `rotated_from NULL` | §0.4 |
| `identification_label` (V1) | `visitor_id`, `contact_entity_id NULL`, `account_entity_id NULL`, `method`, `observed_at` | the free label set that calibrates rungs 1–2 (WVI-2 P8) |
| enum | `ALTER TYPE fleet_task_kind ADD VALUE IF NOT EXISTS 'visitor_resolve'` | append after `design_job`; the parity test compares labels in order `[REPO]` `tests/fleet/test_fleet_db.py:57-63`; never use the label in the same migration (`be855c8f6993` docstring) |

Not in the migration (runtime registration, not DDL `[REPO]`): field definitions are Python pack tuples loaded by
`RESEARCH_PACK_LOADERS` (`platform/api/clue_api/composition.py:95-103`), source manifests are seeded at boot by
`seed_source_manifests` (`sources/seeds.py:430-435`) and their `yields` must already be registered.

Retention: raw `ip` nulled after `CLUE_WVI_RAW_IP_RETENTION_DAYS` (30); events kept 13 months; resolutions keyed to a
contact follow the contact (DSAR §3 slice G).

---

## 3. Build slices, with owners (W5), files and exit checks

Backend = Aryan; frontend, `clue.js`, privacy text, provider clients as leaf code = Shashank via agents.
Every slice lands with its tests and its `.env.example` lines in the same commit.

### V0 — rungs 0 + 1 on Clue-hosted pages, no vendor, no snippet

**A. Migration + registry (backend).**
- Migration per §2. Template `alembic/versions/93113e83bf2f_stage0_official_site_crawl_worker_kinds.py:29-65` for the
  enum; downgrade rebuilds the enum with all nine labels.
- `FleetTaskKind.VISITOR_RESOLVE` appended `[REPO]` `platform/fleet/clue_fleet/enums.py:49-56`.
- New pack `subsystems/research/clue_research/wvi/fields.py`: build `FieldDef` directly (the `_seed` helper cannot set
  `signal_class` `[REPO]` `claimstore/packs.py:93-131`; precedent `stage0/fields.py:143-160`):
  `account.web_engagement` (`object`, `reuse_scope=TENANT_PRIVATE` — account fields default PUBLIC `[REPO]`
  `libs/clue-core/clue_core/field.py:214`, `research_scope=project_neutral`, `signal_class="intent"`,
  `value_schema` = `{last_visit_at, visits_30d, pages[], high_intent_pages[], channels[], identified_contacts}`),
  `contact.web_engagement` (same + `link_token_channel`), `account.visiting_company` (object). Append the loader to
  `RESEARCH_PACK_LOADERS` before `seed_source_manifests`.
- Sources in `sources/seeds.py` via `_entry`: `visitor_link` (STRUCTURED, BOTH, tier 1, STRONG, realtime),
  `reverse_ip` (STRUCTURED, ACCOUNT, tier 2, WEAK, `auth_ref="CLUE_IPREGISTRY_API_KEY"`, `provider="ipregistry"`).
  `auth_ref` needs a matching `Secrets` field `[REPO]` `tests/resolvers/test_static.py:152-165`.
- Settings (`libs/clue-config/clue_config/settings.py`, `secrets.py`, `.env.example`): `CLUE_WVI_ENABLED=false`,
  `CLUE_WVI_PERSON_LEVEL=off`, `CLUE_WVI_REVERSE_IP_PROVIDER=ipregistry`, `CLUE_WVI_IDENTITY_GRAPH_PROVIDER=none`,
  `CLUE_WVI_MONTHLY_REVEAL_CAP=500`, `CLUE_WVI_RAW_IP_RETENTION_DAYS=30`, `CLUE_WVI_PUBLIC_PAGE_ORIGIN=` (no setting
  holds the published-page origin today — it is frozen from the publishing request `[REPO]` `main.py:4334, 5382`),
  `CLUE_IPREGISTRY_API_KEY=`; precedent commit `077df4442` (flag + secret + example lines together).
- Exit: `alembic heads` single, `make db-smoke` green, enum-parity and registry tests green, `insert_claim` accepts a
  `tenant_private` `account.web_engagement` object claim in a unit test.

**B. Collector hook on Clue pages (backend, design app).**
- New `lumen_api/visit_collector.py`, called from the `structured_request_logging` middleware (`main.py:779-836`) on
  `GET /w/{ws}/p/{slug}` HTML 200s, behind `CLUE_WVI_ENABLED`.
- Reads: `?cl=` (then **redirects 302 to the same path without the query** so the token never sits in the address bar,
  browser history, or the `uvicorn.access` log, which prints query strings `[REPO]` `main.py:246-249`), `clue_vid`
  cookie (set if absent; 13 months; `SameSite=Lax`; `Secure`), `request.client.host`, `User-Agent`, `Referer`,
  `Accept-Language`. Bot drop with the `isbot` regex list plus `LinkedInBot`, `facebookexternalhit`, `Slackbot-LinkExpanding`,
  `Twitterbot` before any write.
- Writes `web_visit_event` with raw SQL in one bridge transaction and enqueues `VISITOR_RESOLVE`
  (`work_id = operation_id_from_key(f"visitor:{ws}:{visitor_id}")`, `dedup_key = f"visitor-resolve:{visitor_id}:{day}"`,
  `reopen_terminal=True`, payload = ids only) — the `create_run_and_offer` shape `[REPO]` `design_store.py:1788-1850`.
  Each `DesignStoreBridge._run` builds a private engine (`design_store.py:252-268`), so it is exactly one call.
- **Page response changes when the collector is on:** `Cache-Control: private, no-cache` instead of
  `public, max-age=60` (`main.py:5509-5521`) — otherwise repeat views within 60 s are invisible and a `Set-Cookie` on a
  `public` response can be cached for other visitors. ETag stays.
- The route allowlist test needs no change (no new route); the page-to-account join is
  `design_web_publish.document_id → design_document.account_id → design_account.account_entity_id`, nullable at both
  hops `[REPO]` `alembic/versions/86a9ce389e6e…:64-115, 242-273`.
- Exit: opening an ABM page with `?cl=` yields one event row with the token and a stripped `page_url`, a redirect, a
  cookie, and one queued task; opening it again the same day yields a second event and no second task; `curl -A LinkedInBot`
  yields nothing.

**C. Token minting + "Copy tracked link" (backend route, frontend action).**
- `POST /frontend/v1/visitor-links` in `platform/api/clue_api/frontend_read/visitor_links.py`, registered in
  `build_frontend_read_router` (`frontend_read/app.py:200-253`, static paths before UUID paths), copying the
  `add-to-project` shape (`bulk_actions.py:500-602`: `WireModel`, `Idempotency-Key`, `_requester` permission check,
  `{code,message}` errors). Body: `{accountId, contactId?, channel, targetUrl?, artifactRef?}`; response
  `{token, url}`. `targetUrl` defaults to the account's ABM page (`CLUE_WVI_PUBLIC_PAGE_ORIGIN` + `public_publish_path`);
  in V0 a non-Clue `targetUrl` is refused with `code="target_not_collectable"` (until `clue.js` exists).
- `GET /frontend/v1/accounts/{id}/visitor-links` for the list.
- Frontend (repository seam, no component fetches): `features/accounts/model/visitor-link.ts`,
  `data/visitor-links.repository.ts` over `fetchMutation` (`data/frontend-mutation.ts:17-44`), a controller hook
  copying `use-email-lookup-controller.ts`, and a menu item in the account "More account actions" menu
  `[REPO]` `components/account-workspace-shell.tsx:162-194` plus a real menu behind the contact "More contact actions"
  button (`contact-full-screen.tsx:61-68`, which has no handler today). Reuse the share-menu's link field + copy
  (`chat-shell/components/artifact-share-menu.tsx:147-189`); `use-copy-feedback.ts` needs a URL parameter (it only
  copies `window.location.href` `[REPO]` `:22-23`). Contract section in `apps/frontend/docs/api-contracts/accounts.md`.
- Exit: a rep copies a contact-level link for the September mailer; the URL contains only `?cl=<22 chars>`.

**D. Resolution handler (backend, research subsystem + platform wiring).**
- `subsystems/research/clue_research/wvi/handler.py`: `kind = FleetTaskKind.VISITOR_RESOLVE`, constructor takes
  `conn_factory`, `settings`, `secrets`, the two resolvers, `identity.resolve`; `handle(WorkContext) -> WorkResult`
  checks `stop_requested`/`lease_lost` (`stage0_setup_fleet.py:114-147` pattern). Registered in
  `build_multi_work_worker` (new keyword + guard, `fleet_wiring.py:324-387`) and built in `fleet_main.py` next to the
  stage-0 handler (`:835-843`), gated on `wvi_enabled`.
- Processes every unresolved event for the visitor:
  1. **Exclude**: `ua_class`, then IP against the local lists (Apple Private Relay CSV, `lord-alfred/ipranges` daily
     aggregate, X4BNet vpn/datacenter — refreshed by a nightly fleet-less script into `wvi_ip_exclusion` in V1; in V0
     rely on ipregistry's `security.is_vpn/is_proxy/is_relay/is_tor/is_cloud_provider` `[FETCHED]`
     <https://ipregistry.co/docs/responses/ip-address-fields>). Excluded → `decision=unknown`, `traffic_class` set, stop.
  2. **Rung 0**: `link_token` → `visitor_link`; first click stamps `first_click_visitor_id`; same visitor → STRONG,
     different visitor → WEAK + `review`. Also: a per-account page slug with no token still binds the **account**
     (method `link`, WEAK, because the URL could be forwarded).
  3. **Returning**: a prior STRONG resolution for this `visitor_id` < 90 days → inherit (method `returning`).
  4. **Rung 1**: `reverse_ip` resolver (`wvi/resolvers/ipregistry.py`, batch endpoint, EU base URL when the workspace
     policy is GDPR); keep only `company.type == "business"`; `identity.resolve(conn, Observation(domain=…),
     workspace_id=…)` `[REPO]` `identity/resolve.py:420-461` — exact domain hit = account; no account → `visiting_company`
     suggestion (accounts are created by discovery/import only). `fuzzy`/no-domain → WEAK.
  5. **Write** in one transaction: `visitor_resolution` (+ `cost_cents`, `latency_ms`), then claims via
     `account_claim`/`contact_claim` → `stamp_reuse(workspace_id)` → `insert_claim` (`profiling/committee/worker.py:152-182`
     pattern). `extraction_method=api` requires `source_url` → the stripped page URL; `run_id` is a plain NOT NULL uuid
     with no FK `[REPO]` `alembic/versions/0002_claim_table.py:104` → `uuid5(WVI_NS, resolution_id)`; `research_mode`
     `ACCOUNT_PROFILING` / `CONTACT_PROFILING`; contact claims carry `identity_binding` + `use_class=professional_public`.
     `web_engagement` is a rolling object, so each write **supersedes** the previous claim (`supersede_claim`,
     `claimstore/claims.py:241-263`).
  6. Mark events `resolved_at`.
- Exit (the V0 gate): from a tracked link in an email, the contact's Activity shows the visit with channel and pages
  within 60 s of the click; an untracked visit from a corporate IP shows as the account; a Private Relay / VPN visit is
  "unknown", never "Cloudflare"; every ipregistry call has a resolution row with its cost.

**E. Read side (backend read + frontend).**
- Activity: `research_subject_activity` cannot hold a visit — `project_run_id`/`account_run_id` are NOT NULL FKs
  `[REPO]` `alembic/versions/6a7f8eed5b23…:171-193` — so `read_account_activity`
  (`frontend_read/account_activity.py:241-272`) unions a second query over `visitor_resolution` (decision `assert`
  or `review`), and the event model becomes a discriminated union with a `visit` variant
  `{kind:"visit", method, channel, pages[], contactId?, binding, occurredAt}`. **Structured, not a sentence** — the
  accounts contract forbids display strings on the wire `[REPO]` `apps/frontend/docs/api-contracts/accounts.md:736-743`;
  the frontend composes "Nick opened the ABM page from the September mailer" itself. (This corrects WVI-1 §4.6.)
- Frontend: `model/account-activity.ts:6-45` (enum, union, labels, link target with nullable project),
  `components/account-workspace-screens.tsx:148-163, 202-246` (icon — `public/icons/detail/globe.svg` exists — and the
  null-project guard), both test files, the contract doc.
- Account detail: `account.web_engagement` registered `project_neutral` renders under "Researched fields" with no
  frontend change through `FactList`/`FactValue` (objects render as key: value lines) `[REPO]`
  `components/account-facts.tsx:61-97, 137-196`; a "Visited 3× this week" `TokenBadge` in `AccountIdentity`
  (`account-detail-primitives.tsx:31-60`) is a small optional selector.
- Contact: the "Recent signals" chip is **count-only** over two `contact.facet.*` keys with exact-set tests `[REPO]`
  `frontend_read/contacts.py:117-129, 313-319`, `tests/api/test_frontend_read_contacts.py:751-755`. Do not widen it; add a
  served `webEngagement` field to the contact payload (`model/account-contact.ts:114-125`) and render it beside the
  signals chip (`contact-profile-content.tsx:94-104`).
- Exit: the V0 gate above, seen in the browser on the accounts screens.

### V1 — the client's website (company-level worldwide, consent-aware)

**F. `clue.js` + `POST /v1/collect` + pixel registry.** Script per §0.3 served at `GET /p/{pixel_id}.js` from the
platform projections app (own origin, `Cache-Control: public, max-age=300`, no-op body for paused/unknown ids);
`POST /v1/collect` mounted like the Exa webhook (`projections_app.py:931-932`, `exa_websets_lifecycle.py:414-441`:
no auth dependency, 202, enqueue-only) with pixel/allowlist/denylist/rate-limit checks (§0.4); events flow into the
same `web_visit_event` + `VISITOR_RESOLVE`. Provisioning route `POST /frontend/v1/pixels` and the minimal settings page.
Exit: pixel on cluehq.ai; a visit from an office IP resolves the company; the script is inert on a denylisted path.

**G. Consent, jurisdiction, GPC, DSAR, retention.** Event `consent_state`/`gpc` gate the handler: `gpc=true` or
`denied` → exclusion only, no resolution; workspace `Jurisdiction` GDPR/UK → company-level ceiling regardless of
flags (W2; EDPB 2/2023 ¶55 treats IP read from the terminal as Art 5(3) `[FETCHED]`
<https://www.edpb.europa.eu/system/files/2023-11/edpb_guidelines_202302_technical_scope_art_53_eprivacydirective_en.pdf>
— the cookieless company-level path keeps Leadfeeder's legitimate-interest posture and sets no cookie before consent).
`compliance/dsar.py` has no table registry — `erase`, `record_objection`, `_tombstone_candidate`, `sweep_objections`
each get a `_erase_wvi_rows(contact_id)` call `[REPO]` `dsar.py:917-1036, 1038-1110, 1233-1315, 1317-1370`.
Nightly retention job (fleet-less script like the existing pruners): null `ip` after 30 d, refresh exclusion lists.
Privacy-policy text (US/EU) and the CMP contract shipped as product assets. Exit: EU visit → company-level only;
GPC visitor → nothing; DSAR erases a contact's visits and resolutions; SB 690 status re-checked (passed 28 Aug,
unsigned as of 27 Sep, governor deadline 30 Sep `[FETCHED]`
<https://leginfo.legislature.ca.gov/faces/billStatusClient.xhtml?bill_id=202520260SB690>).

**H. Known-visitor harness + labels.** `scripts/wvi_known_visitor_test.py` drives ≥20 listed people through tracked and
untracked visits on cluehq.ai and reports coverage and precision per rung; every rung-0 click writes
`identification_label`; a nightly job compares rung-1 decisions to labels (WVI-2 C10/C11). Exit: rung-1 precision
≥ 0.90 on labelled visits before any client sees a number.

### V2 — person-level, US only, gated, default off

**I. Identity-graph resolver + AI Ark + bind/review + cap.** `identity_graph` source (tier 3, WEAK prior);
`wvi/resolvers/leadpipe.py` (webhook receiver `POST /v1/webhooks/wvi/{provider}` with HMAC like Exa, plus API client;
payload has `email, first_name, last_name, company_domain, job_title, linkedin_url, page_url` `[FETCHED]`
<https://leadpipe.com/blog/webhook-payload-reference-every-visitor-data-field/>) and `rb2b.py` (webhook only; OEM API is
domain management) behind one interface. Gate (WVI-2 §4.3): `geo_country=US`, consent OK, no GPC,
account ∈ `project_account` or page ∈ intent list, monthly cap (sum of `visitor_resolution.cost_cents` per workspace-month;
`record-only` until `budget_controls_enabled`, `[REPO]` `durable/spend_posture.py:67-86`). Then AI Ark reverse lookup
(new client method; today no AI Ark client exists in code — ARV2 will add one, WVI adds the single method as leaf code),
employer-vs-IP-holder check, bind by strong keys or `insert_contact_entity` (inherits the account's workspace, strong-key
collision raises → resolve first `[REPO]` `identity/entities.py:194-236`) with `identity_binding=WEAK` +
`identity_review_task` (`identity/review.py:530-586`). Exit: harness person-level precision ≥ 0.90 before
`CLUE_WVI_PERSON_LEVEL=us_only` may be set for any workspace; zero person rows outside the US; every reveal has a
resolution row with cost.

### V3 — make it act

**J.** Intent weighting (`web_engagement` needs `pass_kind=SCORING` and a rubric `intent` entry — `signal_class` alone
does nothing in scoring `[REPO]` `icp/compiler.py:118-134`, `icp/rubric.py:64-68, 436-463`); Head-of-ABM read tool
`list_recent_visits(project_id, since)` via `build_toolbelt`; CRM outbox event `account.visited`/`visitor.identified`
(the `emit_handoff_event` shape); LinkedIn Matched Audiences export; automatic token minting in the content scaler
(openers) and in the design batch — note the web batch does not use the engine `BindingSet`, so `InstanceLink`/`UrlQr`
are unreachable for web pages `[REPO]` `main.py:5174-5181`, `lumen-api-helper/src/main.rs:438-447`; the mint goes into
`account_values` (`main.py:10302-10343`) as `account.tracked_url` instead. QR stays on the print/scene path.

---

## 4. Deployment and ops facts that shape the code

1. **Client IP.** No proxy-header config exists; uvicorn defaults trust `X-Forwarded-For` only from `127.0.0.1`
   `[REPO]` (`.venv/…/uvicorn/config.py:355-357`). Behind the local ngrok agent (demo runbook: `clue-design-api.ngrok.app`
   → `127.0.0.1:8060`) the real IP survives; on Railway or any non-loopback proxy set `FORWARDED_ALLOW_IPS` — add it to
   `.env.example` and `scripts/dev_stack.sh`.
2. **Hostnames.** Dev: frontend 3020, design API 8010, platform API 8020/8030 (`scripts/dev_stack.sh:10-23, 57-66`).
   The collector origin for `clue.js` is the platform projections app; give it a stable public name before the pilot.
3. **Cache headers** on published pages change from `public, max-age=60` to `private, no-cache` when the collector is on
   (§3 B). The p-assets `immutable` year-long cache is untouched and useless as a signal (by design).
4. **Log hygiene.** The `?cl=` redirect keeps tokens out of `uvicorn.access`; the structured middleware logs only the
   path (`main.py:797, 811`). Never log `ip` after the retention window.
5. **Token as a bearer.** A `visitor_link` token identifies a person to anyone who holds it; expiry defaults 180 days,
   and the first-click rule (§3 D.2) limits forwarding damage.
6. **Two workers, one queue.** `fleet_main` drains everything (gated by `CLUE_DESIGN_RUNTIME_ENABLED`); an embedded design
   worker competes for the queue (`main.py:529-541`). `VISITOR_RESOLVE` must be registered only in `fleet_main`.

---

## 5. Corrections to WVI-1 / WVI-2 after reading the code

| Spec said | Code says `[REPO]` | Plan does |
|---|---|---|
| Token written "into the page's `InstanceLink`" (WVI-1 §4.1) | web derive passes flat values, no `BindingSet`; `InstanceLink`/`UrlQr` used only by print/scene QR | mint via `/frontend/v1/visitor-links` (V0); automatic mint via `account_values` (V3) |
| Activity rides ARV2's `account_activity_event` (W9) | table exists in specs only; `research_subject_activity` needs project-run + account-run FKs | own `visitor_resolution` feeds a second activity query; W9 amended |
| "Text is served" for the activity row (WVI-1 §4.6) | accounts contract forbids display strings on the wire | structured `visit` variant; frontend composes the sentence |
| Add `contact.web_engagement` to `CONTACT_SIGNAL_FIELD_KEYS` | chip is count-only over facet keys with exact-set tests | separate served `webEngagement` field |
| `signal_class="intent"` feeds scoring | only `pass_kind=SCORING` + rubric entry does | V3 slice J |
| "cost ledger row (ARV2 rule)" | no workspace-level cost ledger in code | `visitor_resolution.cost_cents` is the ledger until ARV2's lands |
| `arv2/ai_ark_client.py` gains one method | no AI Ark client exists yet | WVI ships the one method as leaf code; ARV2 adopts |
| `/w/` route hook | routes are temporary (Part IV) | hook lives in app middleware |
| Fixture adapters flip to HTTP via `CLUE_API_BASE_URL` | Accounts is live-only, no fixture mode | inline test payloads, as the accounts feature does |

---

## 6. Rulings needed now

| # | Decision | Recommendation |
|---|---|---|
| W3 | Token in URL | Yes: opaque `?cl=`, stripped by redirect, 180-day expiry, first-click binds. |
| W4 | Server-side only on Clue pages | Yes; `clue.js` exists for client sites only. |
| W9 (amended) | V0 waits for ARV2 D3? | No. WVI owns `visitor_resolution`; ARV2's activity table adopts the `visit` kind later. |
| W10 | Page cache when collecting | `private, no-cache` on `/w/` pages while `CLUE_WVI_ENABLED`. |
| W11 | Where V1's settings live | A minimal "Website tracking" page under the workspace (first settings surface in the app); pilot provisioned by API until then. |
| W12 | Rung-1 provider for V0 | ipregistry (free 20k, `company.type` + privacy flags, EU base URL). Corroborate with ipapi.is free tier; Snitcher only as a sales-gated bake-off. |
| W13 | Rung-2 POC | Leadpipe Platforms POC first (webhook has `linkedin_url`, US-only built in); RB2B Pro $149 as the control on the same site for the harness. |

W1, W2, W6, W7 stand as recommended in WVI-1 §8.

---

## 7. Cost for the POC (10,000 visits / month)

| Item | V0 | V1 | V2 |
|---|---|---|---|
| Reverse IP (ipregistry) | $0 (free credits) | $0–7 | $0–7 |
| Exclusion lists, labels, harness | $0 | $0 | $0 |
| Person-level (gated ≈ 210 reveals) | — | — | Leadpipe Pro 500 $147 or the free POC; RB2B Pro $149 control |
| AI Ark reverse lookups (210 × 0.5 credit) | — | — | ≈ $1 |
| **Total** | **$0** | **≤ $7** | **≈ $150–300** |

Compare RB2B Pro ungated $149–199 for 600 reveals with no target-account gate `[FETCHED]` <https://www.rb2b.com/pricing>.

---

## Appendix — sources added in this document (WVI-1 App. B and WVI-2 §5 cover the rest)

RB2B install/cookies/domain allowlist/consent: <https://support.rb2b.com/en/articles/9503690-rb2b-install-guide-for-typescript> ·
<https://support.rb2b.com/en/articles/9910029-rb2b-cookie-information> · <https://support.rb2b.com/en/articles/10126115-installing-your-rb2b-tracking-script> ·
<https://support.rb2b.com/en/articles/9611828-considerations-when-controlling-rb2b-s-functionality-with-your-cookie-policy-banner> ·
<https://support.rb2b.com/en/articles/8976614-setup-guide-webhook> · <https://www.rb2b.com/pricing>
Leadpipe docs: <https://docs.leadpipe.com/guides/get-started> · <https://docs.leadpipe.com/guides/manage-pixels.md> ·
<https://docs.leadpipe.com/guides/set-up-webhooks.md> · <https://docs.leadpipe.com/guides/compliance-and-geography.md>
Vector: <https://learn.vector.co/articles/9526804207-allowlist-and-denylist-settings> · <https://learn.vector.co/articles/9450733872-how-vector-s-webhooks-work> ·
<https://learn.vector.co/articles/6201229721-installing-the-pixel-via-termly-s-consent-management-platform>
Snitcher/Leadfeeder: <https://docs.snitcher.com/product/tracker/installation> · <https://docs.snitcher.com/product/tracker/cookie-consent> ·
<https://help.leadfeeder.com/en/articles/13922292-using-leadfeeder-tracker-with-consent-to-comply-with-gdpr> ·
<https://help.leadfeeder.com/en/articles/13922333-leadfeeder-tracker-data-processing-roles>
OSS trackers: <https://docs.snowplow.io/docs/sources/trackers/javascript-trackers/web-tracker/cookies-and-local-storage/> ·
<https://posthog.com/docs/libraries/js/persistence> · <https://docs.umami.is/docs/tracker-configuration> · <https://plausible.io/docs/proxy/introduction>
CMPs/consent: <https://developer.onetrust.com/onetrust/docs/javascript-events-guide> · <https://www.cookiebot.com/en/developer/> ·
<https://developers.google.com/tag-platform/security/concepts/consent-mode> · <https://w3c.github.io/gpc/> · <https://oag.ca.gov/privacy/ccpa/gpc>
LinkedIn: <https://www.linkedin.com/help/lms/answer/a427660> · <https://www.linkedin.com/help/lms/answer/a1489764> ·
<https://learn.microsoft.com/en-us/linkedin/marketing/conversions/enabling-first-party-cookies?view=li-lms-2026-07> ·
<https://knownagents.com/agents/linkedinbot> · <https://help.lemlist.com/en/articles/4452718-why-are-my-link-clicks-not-tracked>
Providers: <https://ipregistry.co/docs/endpoints> · <https://ipregistry.co/docs/responses/ip-address-fields> · <https://ipregistry.co/docs/eu-base-url> ·
<https://ipinfo.io/lite> · <https://ipinfo.io/developers/company-api> · <https://ipapi.is/developers.html> ·
<https://docs.snitcher.com/powered-by-snitcher/ip2company/quickstart> · <https://docs.apollo.io/reference/people-enrichment> ·
<https://docs.ai-ark.com/reference/people-reverse-lookup>
Lists: <https://mask-api.icloud.com/egress-ip-ranges.csv> · <https://github.com/lord-alfred/ipranges> · <https://github.com/X4BNet/lists_vpn> ·
<https://github.com/omrilotan/isbot> · <https://iptoasn.com/> · <https://deepakgouda.github.io/assets/pdf/IMC-2025-Prefix2Org.pdf>
Legal: <https://leginfo.legislature.ca.gov/faces/billStatusClient.xhtml?bill_id=202520260SB690> ·
<https://www.edpb.europa.eu/system/files/2023-11/edpb_guidelines_202302_technical_scope_art_53_eprivacydirective_en.pdf> ·
<https://ico.org.uk/for-organisations/uk-gdpr-guidance-and-resources/personal-information-what-is-it/what-is-personal-information-a-guide/>
