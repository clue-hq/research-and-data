# WVI-5 v2. Visitor intelligence on the Puck website engine: design and build plan

**Revision 2, 2026-11-13** (Aryan with Claude). Revision 1 was written 2026-10-18 from Shashank's WVI-5
(branch `feature/visitor-intelligence`, commit `814636ffc`), which was designed for the old page engine.
This document replaces WVI-5 and stands on its own: nothing here says "as WVI-5". WVI-4's research on how
visitor identification works still stands.

- **Checked against** `origin/main @ cc31d0f91` (2026-10-31). The Puck site layer is on `main` and live in
  production for every workspace since 2026-10-26, so the build starts from `main`.
- **References name files and functions, not line numbers.** Line numbers went stale within days.
- **"Today"** means it exists on `main`. **"New"** means this plan builds it. **"(proposed)"** marks a detail
  this revision chooses that the founder has not ruled on; it can change in review.
- **This replaces the tracking design in the live-sites spec**
  (`docs/superpowers/specs/2026-10-15-publishing-live-sites-design.md` §7: `kit.track`, `site_event`,
  `POST /_clue/events/{slug}`, a visitor id in `localStorage`). None of that was built. Decision D9.
- Decisions are in §9, numbered D1 onward. The earlier V and R numbers are mapped there once.

## 1. What this is for

Clue makes landing pages (Puck sites) for target accounts. Visitor intelligence tells the marketer two
things about each visit to those pages:

1. **Who came**, when we can honestly know it.
2. **Whether the visit meant anything**: a scanner, a glance, a real read, or real interest.

When a person on a target account's buying committee shows real interest, Clue raises an alert.

## 2. What we design around

### 2.1 Facts we cannot change

1. **The web is anonymous.** A server sees an IP address, a browser description and whatever the browser
   chooses to send. There is no name. Any identity is something we put there ourselves.
2. **Pages get forwarded,** and 1:few and 1:many sites are made for no single account. So the account a page
   was made for says nothing about who is reading it.
3. **Machines open links before people do.** Corporate email security (Microsoft Defender, Proofpoint,
   Mimecast) opens every link in a test browser that runs JavaScript.
4. **Our pages run under strict browser rules.** Each page is served with a content security policy: a
   header telling the browser which scripts may run and where the page may send data. A live page may run
   scripts from its own address and send data only to its own address.
5. **Code on the page is not fully trusted.** Sections written by the website agent run on the page, and
   every workspace's address sits under the one domain `cluehq.page`.
6. **Privacy law** limits what we store and when we need a visitor's consent.

### 2.2 Rules we set for ourselves

1. **Unknown is a correct answer. A wrong name is the only failure.**
2. **The page server only writes rows.** It never decides who a visitor is. It must stay fast and must never
   fail a page load.
3. **Nothing personal is ever in a URL.** A link holds a random token, and we store only its fingerprint.
4. **Every "this was Priya" carries how we know** and the evidence.
5. **We never try to get past corporate security.** We only filter it out.
6. **Whose page it is never says who visited.** A visit to a page made for Oliver Hotels, with no personal
   link and no known cookie, is unknown. The page's account is kept as a fact about the page, never as a
   statement about the visitor.
7. **New behaviour sits behind a switch,** and every env setting is in `.env.example` in the same commit.

## 3. The pieces

| Piece | Where it runs | Files | Its job |
|---|---|---|---|
| Edge Worker (today, changed) | Cloudflare, in front of everything on `cluehq.page` | `infra/cloudflare/pages-edge/`: `worker.js`, `routing.js`, `wrangler.toml` | Receives every visitor request and passes page traffic to our server |
| Page origin (today, changed) | Our server, `page-origin.cluehq.ai` | `platform/page_origin/clue_page_origin/`: `routes.py`, `edge.py`, `reads.py`, `app.py`, `main.py` | Looks up and returns the published page; new: records visits |
| Snippet (new) | The visitor's browser | served by the page origin as `/_clue/v.js` | Watches the visit and reports it |
| Resolver (new) | Fleet workers (our pool of background workers that take tasks from a Postgres queue) | new package `platform/api/clue_api/visitor_intel/` | Turns raw rows into "who" and "how strong" |
| App API (new routes) | Platform API | `platform/api/clue_api/frontend_read/` | Creates personal links; serves the data the screens need |
| Head of ABM tool (new) | Platform agent | `visitor_intel/` + agent catalog | Lets the agent read engagement |

```
 Personal link / QR ──┐
 Plain page address ──┼──►  Edge Worker  ──►  Page origin  ──►  visit_event rows (Postgres)
 Customer's own site ─┘     (Cloudflare)      (our server)              │
        ▲                                          │                    ▼
        └──── snippet reports back ◄── page ◄──────┘             Resolver (fleet)
                                                                   │         │
                                                       who + how strong   alert records
                                                                   │         │
                                                              Read routes ◄──┘
                                                       (Head of ABM tool, test page, later the screens)
```

## 4. How it works: one visit, step by step

### 4.1 How a page is served today

A visitor opens `https://conduit.cluehq.page/oliver-hotels`.

1. The request reaches Cloudflare and the Worker runs. `worker.js` is the thin part Cloudflare executes.
   The decision logic is one function, `decide()`, in `routing.js`, kept separate so it can be tested on a
   laptop without Cloudflare. `wrangler.toml` holds the settings: the Worker sits on `cluehq.page`, and our
   server is at `page-origin.cluehq.ai`.
2. `decide()` checks that the hostname is ours and the method is `GET` or `HEAD`. Any other method is refused
   (status 405).
3. The Worker forwards the request to `https://page-origin.cluehq.ai/oliver-hotels`, adding two headers.
4. The page origin checks the secret (`edge.py`, `EdgeGate.public_host`), finds the workspace from the
   hostname (`reads.workspace_for_hostname`), loads the published page and returns it (`routes.py`, `page()`
   and `route_page()`).

| Header (today) | Value | Why it exists |
|---|---|---|
| `x-clue-public-host` | The hostname the visitor typed | The Worker forwards to a different address, so the origin would only see its own name. This carries the original hostname, which is how the origin knows whose page to serve |
| `x-clue-edge-auth` | A secret only the Worker and the origin know | The origin is reachable from the internet. Without proof that a request came through the Worker, anyone could call it and claim any hostname |

Two habits in this code that all the new work copies:

- **Strip, then stamp.** The Worker deletes these headers from the incoming request before writing them, so
  a visitor cannot send their own.
- **Trust only after the secret checks out.** The origin answers 403 when the secret is wrong, and only then
  reads any other header the Worker wrote.

### 4.2 Step 0: a personal link is made (new)

`POST /frontend/v1/tracked-links` creates a link for one person, one account or one campaign (§5.5). It
generates a long random token, stores a row in `tracked_link`, and returns an address such as
`https://go.conduit.ai/r/x7k2Q9…`.

The table stores a fingerprint of the token (its SHA-256 hash), never the token. To look a token up we hash
what arrives and compare. If the database leaks, nobody gets working links. This is the house pattern
(`hash_invitation_token` in `platform/auth/clue_auth/provisioning.py`).

### 4.3 Step 1: the person clicks the link (new)

The browser sends `GET /r/x7k2Q9…` to `go.conduit.ai`.

**At the Worker.** `decide()` strips and stamps three more headers:

| Header (new) | Value | Where the Worker gets it | Why |
|---|---|---|---|
| `x-clue-client-ip` | The visitor's real IP address | Cloudflare supplies it (`cf-connecting-ip`) | The origin only sees Cloudflare's address as the caller. The real address is needed to tell office networks from scanner data centres |
| `x-clue-geo` | Country, network number, network owner: `IN;AS13335;Example%20Telecom` (format proposed) | Cloudflare's `request.cf` (`country`, `asn`, `asOrganization`) | Country decides the consent rule. The network owner is the main bot signal |
| `x-clue-bot` | A first guess: `none`, `preview`, `crawler`, `scanner`, `cloud` or `proxy` (values proposed) | The Worker compares the browser description and the network against lists (§5.7) | A cheap early label. The resolver makes the real decision |

`decide()` must tolerate a missing `request.cf`, which is absent under `node --test`.

**At the origin** (`routes.py`, new route `GET /r/{token}`), in order:

1. `edge.py` verifies the secret, as today.
2. Hash the token and look it up in `tracked_link`.
3. Read the visitor cookie from the request. If there is none and consent allows one (§5.11), make a new
   random id.
4. Write one `visit_event` row: kind `link_click`, the link's id, the visitor id, IP, network, bot guess,
   browser description, time.
5. Reply:

```
302
location: /oliver-hotels?utm_source=email&utm_campaign=…
set-cookie: clue_vid=8f3a…; Domain=conduit.ai; Path=/; Max-Age=34560000; Secure; HttpOnly; SameSite=Lax
cache-control: no-store
```

- `location` sends the browser on to the real page. The token is gone from the address bar, so a forwarded
  or bookmarked address carries no identity.
- `set-cookie` stores the visitor id (§5.6 explains every part of that line).
- `cache-control: no-store` tells every cache never to keep this reply.

The Worker already passes a 302 straight back to the browser instead of following it itself, so both the
cookie and the redirect reach the visitor.

An unknown token goes to the workspace's fallback page, as a missing page does today (`_miss`). An expired
or revoked token still redirects to its page but can name no one (D15).

### 4.4 Step 2: the page loads (changed)

The browser follows the redirect: `GET /oliver-hotels`, now carrying the cookie.

**At the origin** (`page()` and `route_page()`). It loads the stored page as today. If the workspace has
tracking on and the page is a live publish, it inserts one line before `</head>`:

```
<script src="/_clue/v.js" defer></script>
```

- **Why at serve time:** published pages are stored as finished files. Adding the line while serving covers
  every already-published site with no republish, and keeps stored pages free of tracking code.
- **Why the policy needs no change:** a live page may already run scripts from its own address
  (`site_live_csp` in `subsystems/design/clue_design/publishes.py`).
- **Why it does not disturb the page:** the line sits in the head, outside the `clue-site` element that React
  takes over (`site-kit/src/render-core.tsx`).
- **`ETag` must change too.** `ETag` is a header holding a fingerprint of the page; a browser sends it back to
  ask "has this changed?". Today `_page_headers` builds it from the stored page's fingerprint. Once we insert
  a line, it must cover the inserted line as well, or browsers would keep an old copy.
- The page reply sets no cookie and stays cacheable for 60 seconds, as today.

**At the Worker** (`worker.js`). For every page request it also sends a small background message to the
origin, `POST /_clue/hit`, carrying the path, the stamped headers above, and the visitor's `cookie`,
`user-agent` and `referer`. "Background" (`ctx.waitUntil`) means the visitor's page is not delayed. It is
authenticated with the existing edge secret.

- **Why at the edge (D3):** the Worker runs on every request, even one that Cloudflare answers from a stored
  copy. Counting there stays correct if page caching is ever turned on. Today nothing is cached, so this
  costs one extra small request per page view.
- **What counts as a page request (proposed):** method `GET`, and a path that is not `/p-assets/…`,
  `/asset-store/…`, `/_clue/…`, `/r/…`, `/favicon.ico`, `/healthz` or `…/manifest.json`.
- **No double counting:** the origin does not record page requests itself. A dev stack has no Worker, so a
  dev-only env flag lets the origin record them there.

### 4.5 Step 3: the snippet runs in the browser (new)

The browser fetches `GET /_clue/v.js`: one small file, the same for every site. It:

- makes a **session id** and keeps it for the tab (`sessionStorage`), so several pages read in one sitting
  are tied together;
- notes the **page facts**: route, title, the site the visitor came from, and the campaign labels (UTMs) in
  the address;
- listens for **real interaction**: scrolling, pointer or touch movement, a key press, tab focus, and how
  long the tab is actually visible. It sends flags and counts, never what was typed;
- watches each **section** and times how long it is on screen. Every section of a Puck page is wrapped in an
  element marked `data-clue-section` with the section's id (`site-kit/src/config.tsx`). The header and
  footer are ordinary sections with the ids `header` and `footer` (`SHELL_IDS` in `site-document.ts`);
- listens for **clicks** (D5). Almost every part of a section carries a name (`data-clue-el`), so:
  - each click is reported once, for the innermost named element it landed on;
  - each report carries a flag saying whether the click was on a link or a button, and whether the link
    leaves the site;
  - a link with no name is still reported, by its address and its section.

It never reads the cookie (it cannot: §5.6) and never records typed text.

Every so often, and when the tab is hidden or closed, it sends a report:

```
POST /_clue/e                     host: go.conduit.ai
cookie: clue_vid=8f3a…            (attached by the browser, not by the script)
content-type: text/plain

{"sid":"s1","path":"/oliver-hotels","title":"…","ref":"mail.google.com","utm":{…},
 "events":[
  {"t":"interaction","scroll":true,"pointer":true,"key":false,"visible_ms":18400},
  {"t":"section_view","id":"pricing","visible_ms":9200},
  {"t":"element_click","section":"cta","key":"button","link":true,"outbound":false}
 ]}
```

The body's shape is proposed.

- **Why `sendBeacon` (D4):** it is a browser function made for this. The browser delivers it even while the
  tab is closing, which an ordinary request does not guarantee.
- **Why it is allowed:** a live page may send data to its own address, and `/_clue/e` is on its own address.
- **At the Worker:** today it refuses every `POST`. `decide()` will allow `POST` on exactly `/_clue/e`, with
  a size limit, and keep refusing every other one.
- **At the origin** (new route `POST /_clue/e`): verify the secret, find the workspace from the hostname,
  check the body is well-formed and small, read the cookie (setting one if absent and allowed), write one
  `visit_event` row per event, and answer 204 ("received, nothing to send back"). It answers 204 even when
  it throws a report away, so nobody probing it learns anything.
- **Fallback:** when `sendBeacon` is missing or blocked, the script requests a tiny image,
  `GET /_clue/b.gif?…`, with the same facts in the address. Image requests work almost everywhere.

**A page's reports can be forged by code on that page.** An agent-written section may call `fetch`, so it
could post made-up events. Two consequences are built in: identity never comes from the contents of a
report, only from the cookie our server set and the link token our server looked up; and report contents
count toward the signal tier but can never name anyone.

### 4.6 Step 4: what is stored

Everything is rows in `visit_event`, and rows are never edited. For the visit above: one `link_click`, one
`page_hit` (from the edge), then `page_view`, `interaction`, several `section_view` and one `element_click`
(from the snippet).

- Rows are joined by the **visitor id** (the cookie) and the **session id** (the tab).
- The edge's `page_hit` exists even when no script runs (a bot, a blocked script). It has no session id. The
  resolver attaches it to a session when the cookie matches and the times are seconds apart; otherwise it
  stands alone as an unverified hit.
- **No cookie, no join.** When a browser refuses cookies or consent is pending, the link click and the page
  session cannot be tied together, so that visit is counted but stays unknown. Where consent must be waited
  for, Clue pages ask for it (§5.11, D25).

The origin writes through a small new component, `VisitSink`, passed to `create_page_origin_app` (`app.py`)
next to the existing page reader. It exists so tests can swap in a fake beside `FakePageReads`
(`tests/page_origin/conftest.py`) and check what would be written without a database. Rows are inserted in a
background task, after the reply is sent. The origin's database role already has permission to insert.

### 4.7 Step 5: the resolver decides (new)

A loop on the fleet workers looks every few seconds for sessions that have rows not yet judged, and queues
one "resolve this session" task for each. Judging a session can be repeated safely: each run recomputes the
verdict from all of the session's rows, so a session is judged early and judged again as more events arrive
(proposed). The steps are in §5.7.

### 4.8 Step 6: alert records and read routes (new)

When a verdict meets an alert rule, the resolver writes an alert record (§5.9). New read routes serve the
data for accounts, contacts, projects and settings (§5.10). In part 1 these are used by the Head of ABM tool
and a throwaway test page; the designed screens come in part 2 (§7).

## 5. Component details

### 5.1 Which pages are tracked (D1, D2)

- **Every Puck site published in production is tracked.** A site is published either *static* (HTML only; the
  browser may run no script) or *live* (HTML plus JavaScript). One env setting decides it at the moment of
  publishing, `LUMEN_SITE_LIVE_WORKSPACES` (`live_sites_enabled` in `lumen_api/site_live.py`); `*` means every
  workspace. Production has `*` on the design API and on the worker machine (launch record:
  `_memory/2026-10-15-publishing-live-sites.md`, 2026-10-16 and 2026-10-19), so every published site is live.
  The founder ruled on 2026-11-13 that this needs no change.
- **A static publish cannot run the snippet.** It appears only where the setting is missing, such as a dev
  stack. It gets edge page hits and link clicks, never interaction, so it can never count as human. The
  setting is not checked by `deploy/check_prod_env.py`; losing it in production would silently stop
  tracking for new publishes.
- **Pages from the old engine are not supported.** They were development pages, no client uses them, and
  they will be removed. No design or code here is for them.
- **The editor and the preview are never tracked.** Both are drawn by the site-editor server on its own
  address, never by the page origin, and the script line is added only in the page origin's page routes.

### 5.2 Edge Worker: `infra/cloudflare/pages-edge/`

- `routing.js`, `decide()`: strip and stamp `x-clue-client-ip`, `x-clue-geo`, `x-clue-bot` next to the two
  existing headers (§4.3); allow `POST` on exactly `/_clue/e` with a size limit (§4.5).
- `worker.js`: take the `ctx` argument Cloudflare passes, and send the background page hit (§4.4).
- A Cloudflare rate-limit rule on `/_clue/*` and `/r/*`.
- Nothing in `wrangler.toml` or the repo configures page caching today.
- The Worker knows nothing about workspaces or settings. It reports every page request, and the origin
  drops reports for workspaces with tracking off.

### 5.3 Page origin: `platform/page_origin/clue_page_origin/`

New routes, declared before the page routes. They cannot collide with a published page: a page's slug is at
least three characters of `a-z`, `0-9` and `-` (`WEB_SLUG_PATTERN` in `lumen_api/toolbelt/publishes.py`), so
neither `r` nor `_clue` can be one.

| Route | What it does | Caching |
|---|---|---|
| `GET /r/{token}` | Records the click, sets the cookie, redirects to the page (§4.3) | `no-store` |
| `GET /_clue/v.js` | Returns the snippet | `public, max-age=300` |
| `POST /_clue/e` | Receives the snippet's reports (§4.5); may set the cookie; answers 204 | `no-store` |
| `GET /_clue/b.gif` | The same reports as an image request (fallback) | `no-store` |
| `POST /_clue/hit` | Receives page hits from the Worker; edge secret only | `no-store` |
| `GET /_clue/optout` | Sets a do-not-track cookie and stops recording that browser | `no-store` |

Other changes:

- **Script line and `ETag`** in `page()` and `route_page()` (§4.4).
- **The workspace lookup returns more.** `reads.workspace_for_hostname` returns only the workspace id today.
  It must also say whether the host is a Clue address or a customer's own domain, because that decides the
  cookie's form (§5.6). The hostname record already has it (`resolve_active_hostname` in
  `libs/clue-spine/clue_spine/hostnames.py`).
- **Logs are real work, not a setting.** The server's access log is on by default (`main.py`) and would
  write every `/r/{token}` address. The edge-refusal log (`edge.py`) writes the caller's IP address. The
  shared log redaction (`libs/clue-obs/clue_obs/redact.py`) hides only secret-shaped keys. Part 1 turns the
  access log off or replaces it with one that hides `/r/…` addresses, and removes the IP from the refusal
  log.

### 5.4 The snippet `/_clue/v.js`

What it collects and how it sends are in §4.5. The rest:

- **One file, at most 4 KB,** the same for Clue pages and the customer's own website.
- **Moving between pages of a site** is a full page load today (site links are plain links), so each page
  reports itself and the tab's session id ties them together.
- **Section type is not on the page.** The `data-clue-section` wrapper holds only the section's id, which is
  chosen per site (`hero`, `proof`). The resolver looks up the section's type and heading in the publish's
  stored page data by that id.
- **What carries an element name today:** our sections' parts (heading, body, image, button and so on, in
  `site-kit/src/sections.tsx`); in agent-written sections, whatever the agent named through the kit
  (`agent-kit.tsx`); in copied sections, inline links and buttons (`clone.ts`).
- **`kit.track` (D9):** the way an agent-written section sends a named event of its own. It posts to
  `/_clue/e` as an event of kind `custom`. Hydration problems (the browser's drawing of the page disagreeing
  with the server's) are reported the same way under a reserved name.
- **Never:** fingerprinting the device, reading form fields, recording the session.
- **On the customer's own website** (built last, D14) it loads from the workspace's connected domain
  (`https://go.conduit.ai/_clue/v.js`), so its reports go to a sibling address and the shared cookie
  travels with them. Reports are accepted only when the page's host is in the workspace's list of allowed
  hosts; otherwise they are silently dropped.
- **Link tagging:** on a Clue page, a link out to the customer's registered domain gets a short-lived,
  non-identifying tag (`?cl=…`) added at the moment of the click, which the origin maps to the visitor. It
  matters only when there is no shared cookie, and it is not the visitor id.

### 5.5 Personal links and QR codes

`POST /frontend/v1/tracked-links` `{accountId?, contactId?, projectId, channel, scope, target, messageId?,
artifactRef?}` with an `Idempotency-Key` returns `{token, url, expiresAt}`. Copying the same person's link
again for the same project and channel returns the same token.

- **Scope:** `person` (one contact: a 1:1 email, a LinkedIn message, one printed QR code per copy),
  `account` (the account only: a gift sent to an office), `campaign` (nobody in particular: 1:few and 1:many
  pages, ads). Only a `person` link can ever name anyone.
- **Target:** a published site and, optionally, a page within it.
- **Token:** at least 96 random bits, stored as a SHA-256 fingerprint (§4.2).
- **Address:** on whatever address the workspace has: its connected domain when there is one, otherwise its
  Clue address. Nothing in the product pushes a customer toward a custom domain (D8).
- **Campaign labels (UTMs)** are set by Clue per channel: `utm_source`, `utm_medium`, `utm_campaign` (the
  project), `utm_content` (the artifact). They describe the campaign and never identify a person.
- **Message id (later, D12):** when Clue composes the outreach, every link in one message shares a
  `message_id`, so "several links of one message opened within two seconds" can be recognised as a scanner.
  The column exists from the start; the rule is added later.
- **Lifetime (D16):** 180 days, or until revoked.
- **QR codes on print and direct mail:** each printed copy gets its own QR code, which is that copy's
  personal link, with the short address printed under it so it can also be typed. This uses the existing
  per-copy binding pipeline of the ad engine (`BindingAudience` in `crates/lumen-core/src/binding.rs`, the QR
  renderer in `crates/lumen-assets/src/qr.rs`, `_derive_and_persist_instance` in `lumen_api/main.py`). Puck
  sites do not use that pipeline, and this plan does not change it. The link format must be agreed with the
  direct-mail work (open item O2).

### 5.6 The visitor cookie

A cookie is a small named value our server asks the browser to keep and send back with every later request
to the same site. Ours holds a random id meaning "this browser" and nothing else. This document calls it
`clue_vid`.

| Setting | Value | Why |
|---|---|---|
| `HttpOnly` | on | Code on the page, including agent-written sections, cannot read or change it. Only our server handles the id |
| `Secure`, `SameSite=Lax` | on | Sent only over HTTPS; sent when a link is followed into the site |
| `Max-Age` | 400 days (D17) | The longest browsers allow |
| On a Clue address, `<label>.cluehq.page` | named `__Host-clue_vid`, no `Domain`, `Path=/` | The cookie goes back only to that one workspace's address, so one customer's visitor id never reaches another customer's pages. The `__Host-` prefix makes the browser refuse any wider cookie under that name |
| On a customer's own domain, `go.conduit.ai` | named `clue_vid`, `Domain=conduit.ai` | The customer's own website, `www.conduit.ai`, shares it. That is what lets a person identified on a Clue page be recognised on the customer's pricing page |

The rule behind both rows: the cookie spreads exactly as far as one customer's property and no further.

**Relation to the cookie lock (D10).** `cluehq.page` is not on the Public Suffix List (a list browsers use to
treat each subdomain as a separate site); the founder decided on 2026-10-19 not to file for it. Instead,
published pages switch off `document.cookie` for the code they run (`site-kit/src/cookie-lock.ts`), and
the runbook recorded that our servers set no cookies there. This plan sets one, from the server. The lock
does not affect it, because the lock only stops page scripts, and the cookie is limited to one workspace's
address. The same holds for the opt-out marker (§5.3), which is a second cookie of the same form. The
runbook's rule is amended to say so.

**Its limits.** The cookie marks one browser, not one person.

- A phone and a laptop are two visitors until each one opens one of the person's links. One person can have
  many browsers bound to them.
- A private window, or cleared cookies, makes a new stranger.
- Safari may keep the cookie about seven days on a customer's own domain, because the address is pointed at
  Clue's servers.
- Two people sharing one browser look like one visitor.

### 5.7 The resolver

New package `platform/api/clue_api/visitor_intel/`. One new fleet task kind, `visitor_resolve`, added after
`crm_write` in `platform/fleet/clue_fleet/enums.py` with a migration like
`a3b587b8fdfd_crm_write_fleet_kind.py`. The test that pins the last kind
(`tests/db/test_crm_write_foundation_migration.py`) must be updated. Handlers are passed to
`build_multi_work_worker` (`fleet_wiring.py`). The loop that finds unjudged sessions sits beside
`_orphan_sweep_loop` (`fleet_main.py`) and uses the same lock-and-record pattern as
`run_orphan_blob_sweep_if_due` (`storage_wiring.py`).

Each session gets two separate answers: **who**, and **how strong a signal**. An alert needs both.

**Step 1. Drop bots and scanners.** No single test works, so several weak signals are combined:

| Signal | What it catches | How it fails |
|---|---|---|
| The name the software gives itself (its `user-agent`) | Honest bots: Slackbot, Googlebot, LinkedInBot, link previewers | Trivial to fake; security scanners usually claim to be Chrome |
| The network the request came from | Scanners run in a vendor's or a cloud provider's data centres; people browse from office, home or mobile networks | Some companies send all staff browsing through a cloud proxy (Zscaler, Netskope), so real people also arrive from a data centre. These are classed apart (`proxy`) and are never dropped as bots |
| The type of request | Requests for headers only, or marked as a browser pre-loading a page | Catches only the lazy ones |
| Coming back | A scanner starts fresh each time and keeps no cookie; a browser that returns days later with our cookie is a person | Says nothing about a first visit |
| Message timing (later, D12) | Several links of one message opened within two seconds | Works only when Clue composed the message |

**Step 2. Require a real interaction.** "The script ran" is not enough, because scanners run scripts. A
session counts as human only with scrolling, pointer or touch movement, a key press, tab focus, or several
seconds with the tab actually visible, and not from a security-vendor or cloud-provider network.

**Step 3. Decide who.**

- The first human click of a `person` link binds that browser to that contact.
- The same link later, in a different browser, is probably a forward: decision `review`, never asserted.
- A browser already bound by an earlier link is the same person returning.
- Everything else is `unknown`.

**Step 4. Fill in the past.** Once a browser is bound, its earlier unjudged sessions take the name.

**Step 5. Relevance and tier.** Relevance comes from whether the contact's account is in the project
(`projects_for_accounts` in `subsystems/research/clue_research/membership.py`) and whether the contact is on
its buying committee (`committee_members` in `platform/api/clue_api/arv2/display/gather.py`). The tier comes
from what the session did:

| Tier | What it took | What we do |
|---|---|---|
| Verified intent | A click on a link or button, time on a high-intent section (pricing, security, integrations), a return visit, or two committee members of one account within seven days | Alert, when the person is known |
| Likely human | Real interaction with scrolling and reading time | Shown in the app; no alert |
| Unverified | A link click or page hit with no interaction | Logged only |
| Bot | Scanner or bot patterns | Discarded |

Which sections count as high-intent is a per-workspace setting, matched on the section's type and heading
and on element names.

**Step 6. Write.** A row in `visitor_identity_binding` when a browser is newly bound; the session's verdict
in `visitor_resolution`; a `visit` item on the account's activity feed; and any alert records.

**What protects us when a test is fooled.** A personal link names someone only on its first human click;
anything unsure stays unverified and names no one; an alert needs verified intent, which scanners almost
never produce; and the raw rows are kept, so an improved rule can re-judge old visits.

**What stays unsolved.** A test browser that fakes scrolling from an ordinary-looking network would pass as
human. The alert bar limits the damage. How often this happens is only known from the inbox test (§6).

### 5.8 Data model: one migration

House rules: raw SQL in `op.execute`; text columns with named `CHECK`s, no new database enum types;
workspace-scoped foreign keys on `(id, workspace_id)` (template:
`65fb2128c904_arv2_d1_display_substrate.py`); reversible; the downgrade refuses while visit rows exist
(template: `000b9d8bb17b_arv2_onboarding_synthesis_role.py`). `down_revision` is the single head of `main`
when the migration is written (`802fa1e6c449` on 2026-11-13).

| Table | Purpose and key columns |
|---|---|
| `tracked_link` | One row per link: `link_id`, `workspace_id`, `token_digest` UNIQUE, `scope` CHECK (person, account, campaign), `project_id`, `account_entity_id` (NULL for campaign), `contact_entity_id` (required for person), `channel` CHECK, `utm` jsonb, `artifact_ref` jsonb, `target_slug`, `target_route` NULL, `message_id` NULL, `created_by_user_id`, `created_at`, `expires_at`, `revoked_at`, `first_human_click_at`, `bound_visitor_id` |
| `web_visitor` | One row per browser: `visitor_id` uuid, `workspace_id`, `cookie_scope` CHECK (host, parent), `first_seen_at`, `last_seen_at` |
| `visit_event` | Append-only: `event_id`, `workspace_id`, `visitor_id`, `session_id`, `occurred_at`, `kind` CHECK (link_click, page_hit, page_view, interaction, section_view, element_click, custom, hydration_error), `hostname`, `host_kind`, `surface` CHECK (clue_page, customer_site), `path`, `route`, `slug`, `document_id`, `referrer_host`, `utm` jsonb, `link_id`, `section_id`, `element_key`, `is_link_or_button` bool, `outbound` bool, `visible_ms`, `interaction` jsonb (flags and counts), `event_name` (for custom), `user_agent`, `client_ip` (emptied after 30 days), `ip_hash`, `country`, `asn`, `as_org`, `bot_class` CHECK, `consent_state`, `gpc`, `resolved_at`; indexes on `(workspace_id, occurred_at DESC)` and a partial one on `resolved_at IS NULL` |
| `visitor_identity_binding` | "This browser is this contact": `workspace_id`, `visitor_id`, `contact_entity_id`, `account_entity_id`, `method` CHECK (link, returning, confirmed_forward, form, import), `strength` CHECK (strong, weak), `evidence` jsonb (link id, event id), `created_at`, `revoked_at` |
| `visitor_resolution` | One verdict per session: `account_entity_id`, `contact_entity_id`, `method`, `strength`, `decision` CHECK (assert, review, unknown), `tier` CHECK (verified_intent, likely_human, unverified, bot), `reasons` jsonb, `committee_member` bool, `target_account` bool |
| `visit_alert_rule`, `visit_alert` | The rules (trigger, scope, thresholds) and the fired alerts, with a UNIQUE `dedupe_key` |
| `account_activity_event` (today) | Its `kind` CHECK gains `visit` (defined in `65fb2128c904`). The read side needs three more changes: `_ACTIVITY_SQL` in `frontend_read/v1_shared.py` does not select `ref_json`; and the kind is a closed list in `v1_shared.py` (`ActivityKind`) and `contract_v1.py`, and in the frontend (`account-detail.ts`, the icon map in `account-activity-feed.tsx`) |

Tracking settings per workspace (on or off, consent mode, allowed hosts, high-intent sections) are stored
with the workspace's pages settings; the exact columns are settled in the migration (proposed).

**The IP address.** The raw address is emptied after 30 days (D18). A scrambled form is kept for counting.
A plain fingerprint would not be safe, because there are only about four billion IPv4 addresses and all of
them can be tried; so the scrambling uses a secret key (an HMAC). One platform key in env,
`CLUE_VISITOR_IP_HASH_KEY`, with the workspace id mixed in so the same address scrambles differently per
workspace (D19).

No table for a Slack connection is created here (D7).

### 5.9 Alerts

- **When one fires (D6):** only for a known buying-committee member with the verified-intent tier (decision
  `assert`). A `review` visit ("probably forwarded") appears in the app for a person to confirm or dismiss;
  a confirmed forward to a known committee member binds that browser to them.
- **Default rules:** a committee member's first verified visit; a returning committee member reads a
  high-intent section; two or more committee members of one account within seven days. Throttled per contact
  per day through the `dedupe_key`.
- **Part 1** produces alert records and a route that lists them. **Part 2** displays them in the app, on the
  product-notice pattern (`frontend_read/product_notices.py`).
- **Slack is out of this build (D7).** It is its own sprint and branch. A note for that sprint, not a
  decision: the CRM work has since built a connection path through Composio
  (`workspace_integration_connection`, Settings → Integrations), which avoids building our own storage for
  Slack's access token.

### 5.10 Read routes and the Head of ABM tool

New `frontend_read/visitor_intel.py` with `register_visitor_intel_routes`, registered in
`frontend_read/app.py` after `register_product_notice_routes`. Settings routes follow
`register_settings_pages_routes` and need the `workspace.manage_settings` permission.

| Route | Returns |
|---|---|
| `POST /tracked-links` | A personal, account or campaign link (§5.5) |
| `GET /accounts/{id}/visits` | The account's visits, each with who, how we know, and the tier |
| `GET /contacts/{id}/engagement` | One contact's visits and what they read |
| `GET /projects/{id}/engagement?range=30d` | Per page and per section: visitors, median time, link and button clicks, and the series a chart would draw |
| `POST /visits/{id}/confirm-forward`, `…/dismiss` | The answer to a "probably forwarded" visit |
| `GET /visit-alerts` | Alert records |
| `GET`, `PATCH /settings/website-tracking` | Tracking on or off, consent mode, allowed hosts, high-intent sections, alert rules |

The exact shapes are written into `apps/frontend/docs/api-contracts/` during part 1, as a proposal the
screen designs can be checked against (the contract-gap rule).

**Head of ABM tool, `read_engagement@1` (part 1, D13).** It serves only `assert` and `review` decisions. It
is built like `read_artifact` (`build_artifact_read_tools` in `artifact_read_tools.py`), registered in
`toolbelt_wiring.py`, and granted in `C6_AGENT_TOOL_AUTHORITY` (`agent_registry_wiring.py`). It needs a new
profile version and recipe version (the next free ones: `v88` and `48` on 2026-11-13), a tool note and a
manual rebuild. Its manual wording goes to the founder before it is written. Every version bump discards
conversation continuation on live threads, so batch it with other catalog changes when possible.

**Website agent reading engagement (part 2, D13).** A short summary in the agent's `site.md` (written by
`site_summary` in `lumen_agent/site/workspace.py`), such as "the pricing section was read by three committee
members; nobody reached the FAQ". Its skills also say it never writes tracking code of its own. The skill
wording goes to the founder first.

### 5.11 Privacy, consent and retention

- **Consent (D11).** Per workspace, `consent_mode` is `auto`, `wait` or `off`. `auto` waits for the visitor's
  consent in the EU, the UK and where India's DPDP Act requires it, and tracks without waiting elsewhere.
  The browser's "do not track" signals (GPC, DNT) are honoured: no cookie is set and events are marked.
- **While waiting,** the visit is counted with a tab-only id and no cookie, so a personal-link click cannot
  be tied to the page visit and nobody is named.
- **Clue pages show their own consent prompt (D25).** Without one, a visitor in a region that waits could
  never grant consent, and personal links would never name anyone there. The snippet draws the prompt, and
  only when consent must be waited for: never where tracking is allowed without waiting, and never when the
  browser sends a "do not track" signal. Accepting calls `clue.consent('granted')`; the next report tells
  the server, which then sets the cookie. The choice is remembered in the browser's `localStorage` as the
  single word `granted` or `declined` (proposed), so the prompt is not shown again. The prompt's wording and
  look are not designed yet (open item O3).
- **On the customer's own website** Clue shows no prompt. The customer's consent tool (OneTrust, Cookiebot)
  or their own call to `clue.consent('granted')` lifts the wait.
- **Retention.** The raw IP address is emptied after 30 days by a loop on the maintenance pattern.
- **Erasure.** A helper called from `erase` and `record_objection`
  (`subsystems/research/clue_research/compliance/dsar.py`) revokes a person's bindings and clears their
  references on verdicts. There is no HTTP route for erasure today.
- **Opt-out.** `GET /_clue/optout` (§5.3).
- A privacy-notice paragraph for customer pages and the customer's own site.

## 6. Accuracy and proof

| Risk | Control | Proof |
|---|---|---|
| Email scanners that run JavaScript | Real-interaction test plus the network check; a link binds only on its first human click | Links sent into real corporate inboxes (Defender, Proofpoint, Mimecast): no scanner click is ever bound |
| Link-preview bots (LinkedIn, Slack, iMessage) | Name list; never bound, never alerted | A link shared in each: no event marked human |
| Real people behind a corporate proxy dropped as bots | Proxies classed apart from scanners | Known visitors behind a proxy are counted |
| A forwarded link | A link names one browser; another browser is `review` | Forward test |
| A page made for one account, opened by someone else | The page's account is never identity | Forward test: unknown or `review`, never the page's account |
| Two people on one browser | The binding carries its method and date; a new personal link on the same browser replaces it | Two people, one laptop |
| Lost cookies (Safari, private windows, a new device) | Reported as unknown; a later personal-link click fills in the past | A test per browser |
| Counting twice | Session ids, event ids, repeat-safe handlers; page requests recorded in one place only | Reload storm test |
| Page copies served by a cache | Page hits recorded at the edge | Hits counted with caching forced on |
| Reports lost when the tab closes | `sendBeacon`, with the image fallback | Leave-page test across browsers |
| Page code reading or faking the visitor id | `HttpOnly`; the `__Host-` name on Clue addresses | A page script cannot read the cookie; a wider cookie set from another workspace's address is never read as the visitor id |
| Page code faking engagement | Report contents count toward a tier, never toward a name | A forged report with no cookie and no link stays unknown |

**The known-visitor test.** About twenty known people; email, LinkedIn message, printed QR code, ads;
iPhone, Android, desktop Chrome, Safari and Firefox, in-app browsers; plus inboxes behind security scanners
and one person behind a corporate proxy. Before any customer's tracking is turned on:

- every person we name is the right person;
- at least 95% of known human visits are captured;
- no alert comes from a bot;
- 95% of alert records are written within 60 seconds;
- forward and fill-in-the-past cases are correct;
- section counts are within 5% of a hand-kept sheet.

**Monitoring.** Counts through `get_metric_sink` (events in, bot share, human share, the three decisions),
and a test visit every ten minutes.

## 7. Build plan

The build is in two parts (D21). Part 1 is everything that is not a screen. Part 2 is the visual side.

### Part 1: no screens

| Step | Scope | Rough size |
|---|---|---|
| 1. Capture | The migration; Worker headers, bot guess, page hits, `POST` on `/_clue/e`; origin routes, script line and `ETag`, host kind from the workspace lookup, `VisitSink`, log clean-up; the snippet with interaction, sections, clicks and `kit.track` | 5-6 days |
| 2. Links | The tracked-link route with scopes; QR filling | 2 days |
| 3. Resolve | The resolver: name list, network check, interaction test, first-human-click binding, fill-in, relevance, tiers, activity items | 3-4 days |
| 4. Alert records | Rules, alert records, throttling | 1 day |
| 5. Read routes | Every route in §5.10, with the API contract written into the frontend's contract docs | 2-3 days |
| 6. Head of ABM tool | `read_engagement@1`, after the founder approves its manual wording | 1 day |
| 7. Test page | A throwaway page for testing part 1 (below) | 1 day |
| 8. Customer's own site and consent | The snippet on customer domains, allowed hosts, link tagging; consent modes and the consent mechanism (waiting, `clue.consent`, the remembered choice), without the designed prompt | 2-3 days |
| 9. Prove it | The known-visitor test, the test visit, counts, retention, the erasure helper | 3-4 days |

Roughly four weeks for one engineer.

**The throwaway test page.** One standalone page under `trials/` (proposed), outside the main app, never
deployed, and deleted when part 2 lands. It calls the same routes the real screens will use, so testing it
tests those routes. It lets a person pick a contact and make their link, watch visits arrive with who, how
we know and the tier, see per-section numbers, and confirm or dismiss a forwarded visit.

**Turning it on.** Tracking goes on for Clue's own workspaces first, and for customers only after the
known-visitor test passes. Data is collected from then on, so the screens open with history in them.

### Part 2: the visual side

Built from the co-founder's frames (open item O1); wiring never invents UI.

- "Copy personal link" in the account header menu, on each contact, and in the site editor's Share menu
  (`artifact-share-menu.tsx`). Today the contact preview and contact rows have no menu, and there is no
  shared copy helper.
- Visits in the account's Activity tab, with "probably forwarded" visits to confirm or dismiss.
- A contact's engagement on their profile.
- A project analytics page: visits per page and per section, time spent, link and button clicks. The
  frontend has no chart library, so charts are drawn directly (D20).
- Tracking settings.
- In-app alert display.
- The consent prompt on Clue pages (D25, open item O3).
- The website agent reading engagement (§5.10).

### Later, each its own piece of work

- Slack alerts (its own sprint and branch).
- The message-timing bot rule, once Clue composes or sends outreach.

## 8. Not in this build

- **Guessing the company from the visitor's network** (an IP-to-company map; roughly 25-35% of business
  visits, only ever "probable", never a person).
- **The same person across devices without a link.** Each device is named only by its own personal-link
  click. A "probably the same person" rule from network and timing is a separate design, and could never be
  allowed to fire alerts.
- **Forms and meeting bookings on pages.** Pages cannot submit forms yet (the live policy has
  `form-action 'none'`). When they can, a typed email identifies the device directly; this is the strongest
  fix for the cross-device gap.
- **Importing the customer's existing marketing identities** (HubSpot, Marketo, Mailchimp cookies).
- **Pushing visits into the CRM.** CRM writes exist now (lists, target flags, fit level, committee, Clue's
  own fields), but activity writes including visit roll-ups are parked there (rulings R-6.16 and R-6.19 in
  `docs/superpowers/specs/crm-integration/rulings.md`). When that is unparked, visits go through that
  existing write path.
- **Honeypot links** (a hidden link only a scanner would open): needs Clue to send the email itself, and
  Clue sends no email today.
- **"Opened within seconds of sending"** as a bot signal: we never know the send time.
- **Anonymous person-level identification** from third-party data.
- **Pages from the old engine** (D2).

## 9. Decisions

Ruled by the founder (Aryan) on 2026-11-13 unless a date says otherwise.

| # | Decision | Ruling | Was |
|---|---|---|---|
| D1 | Which pages are tracked | Every published site. Production already publishes every site live; the setting stays as it is | V1, R1 |
| D2 | Pages from the old engine | Not supported; no design or code for them | new |
| D3 | Where page views are counted | At the Cloudflare edge from day one | V5 |
| D4 | How the browser sends reports | `sendBeacon` `POST` on one address, with an image request as the fallback | V4, R3 |
| D5 | Section and click detail | In the first version. Clicks are recorded on every named element, once per click for the innermost one, with a "link or button" flag; only link and button clicks count toward verified intent | V2 |
| D6 | When an alert fires | Only a known committee member with verified intent; "probably forwarded" stays in the app | V6 |
| D7 | Slack | Out of this build; its own sprint and branch | R6 |
| D8 | Custom domain for emailed links | No warning and no push; links use whatever address the workspace has | new |
| D9 | The live-sites spec's unbuilt tracking design | Replaced by this design; that spec points here | V9 |
| D10 | The runbook's "no cookies on `cluehq.page`" rule | Amended: only the visitor cookie and its opt-out marker, each limited to the one workspace's address | new |
| D11 | Consent | Automatic by region, with per-workspace "always wait" and "off" | R5 |
| D12 | Bot detection in two passes | First: name list, network check, interaction test, first-human-click binding, tiers. Later: message timing | new |
| D13 | Agents reading engagement | Head of ABM tool in part 1. Website agent summary in part 2. Wording to the founder first | V3 |
| D14 | The customer's own website | In part 1, built last | new |
| D15 | Expired or revoked links | Still open their page; name no one | V8 |
| D16 | Link lifetime | 180 days | new |
| D17 | Cookie lifetime and scope | 400 days; one workspace's address on `cluehq.page`, the whole domain on a customer's own | R4 |
| D18 | Raw IP address | Emptied after 30 days; a keyed scramble is kept | new |
| D19 | The scrambling key | One platform key in env, mixed with the workspace id | new |
| D20 | Charts | Drawn directly, no chart library | R7 |
| D21 | Two-part build | Part 1 everything but screens, tested through a throwaway page; part 2 the screens | new |
| D22 | The page origin only writes rows; the fleet judges them | Kept (rule 2 in §2.2) | R2 |
| D23 | Whose page it is never says who visited | Ruled 2026-10-18 | new |
| D24 | Guessing the company from the network | Left out (§8). Ruled 2026-10-18 | V7 |
| D25 | Consent on Clue pages | Clue pages show their own consent prompt where consent must be waited for (§5.11). The mechanism is built in part 1; the designed prompt in part 2 | new |

### Open items

| # | Open item | Needed by |
|---|---|---|
| O1 | Screen frames from the co-founder for everything in part 2. The list of screens has not been sent | Before part 2; ideally during part 1 so the API contract can be checked against them |
| O2 | The QR link format, to be agreed with the direct-mail work (a tracking feature exists on branch `codex/illumio-usbank-demo`, not on `main`). Who to coordinate with is not decided | Before step 2 |
| O3 | The consent prompt on Clue pages (D25): its wording and look need a design from the co-founder and a legal check. Until the designed prompt exists, visitors in regions that wait are counted but never named | Before part 2; before tracking is turned on for a customer with EU, UK or Indian visitors |
| O4 | Confirm `LUMEN_SITE_LIVE_WORKSPACES=*` on every production process that publishes | Before step 1 |
| O5 | The details marked "(proposed)": header formats, the report body, what counts as a page request, when a session is judged, where the test page lives, where tracking settings are stored | During part 1 review |

## 10. Change log

- **2026-11-13, revision 2.** Rewritten to stand on its own and to explain why each piece exists (§4).
  Re-checked on `origin/main @ cc31d0f91`. Rulings D1-D25 recorded. Two-part build. Slack and old-engine
  pages removed. Click rule settled. Header and footer are ordinary sections (`header`, `footer`). The CRM
  line corrected (writes exist; visit roll-ups are parked). Agent versions, the last fleet kind and the
  migration head updated. "Opened within seconds of sending" removed. Consent on Clue pages found as a gap
  and ruled the same day: Clue pages show their own consent prompt (D25); its design is open item O3.
- **2026-10-18, revision 1** (`20005d576`, `2c49b3c57`). First version for Puck sites, fact-checked on
  `site/publish-durability @ 1df6a1757`.
