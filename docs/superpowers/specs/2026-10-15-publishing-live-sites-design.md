# Publishing live sites: JavaScript, forms, tracking, embeds and snippets on published Puck sites

**Date:** 2026-10-15. **Status:** Phase 1 built (2026-10-15, commits `c0c466460` … `f02340713`
and the records commit that follows them; plan `docs/superpowers/plans/2026-10-15-publishing-live-sites-phase-1.md`;
the live in-app-browser walk is owed). Earlier: design agreed in discussion with the founder (2026-10-15); this
written spec awaits the founder's review. **Branch:** `puck/integration-wave1` (trenton).

**Supersedes:** the Wave 2 integration plan's Contract 3 publishing rules
(`docs/superpowers/plans/2026-10-09-website-agent-on-puck-integration.md`: "the sanitizer strips
`script` … `form` … every `on*` attribute", the site CSP `script-src 'none'`, and review-focus item 7
"agent script in published HTML publishes without it"); the section checker's rule "a section renders
its props and nothing else"; and the custom-domain spec's deferral of head/body snippets
(`docs/superpowers/specs/2026-09-17-custom-domain-publishing-design.md` §1 and its follow-ups).
**Does not change:** D2 (agent code runs only on the editor domain in the browser, and only in the
hardened headless Chromium on the server), the separate pages domain, the brand rules.

---

## 1. Why this spec exists

Published Puck sites today are **static**. The design API's hardened Chromium draws each page once to
plain HTML (`renderToStaticMarkup`, `site-kit/src/render-core.tsx:63`), a cleaner strips every script,
event handler and form (`lumen_api/site_sanitize.py`), and the page is served with
`script-src 'none'` (`clue_design/publishes.py:547`). React components, state, effects and clicks all
run in the editor and are flattened to inert HTML on publish.

That was never the founder's intent. It traces to one line of the 2026-10-09 isolation research,
"AI sections should default to static HTML with no hydration unless the section needs interactivity"
(`docs/superpowers/specs/2026-10-09-code-first-builder-isolation-research.md:235`), which the
integration plan turned into a hard rule without the "unless". The roadmap listed "the publish format"
as a founder decision; none was recorded.

**The founder's direction (2026-10-15):** a published site is a normal landing page — HTML, CSS,
JavaScript and assets — with React components, hooks, state and effects working for visitors. Running
real code on published pages was a main reason for moving to Puck.

This also settles review root-cause group 4.3 ("what the marketer sees in the editor is not what gets
published"): once the published page runs the same React as the editor, most of the differences close
by construction (§13).

## 2. Founder rulings this spec implements (2026-10-15)

1. **The whole page comes alive** (hydration of the whole page, not "islands"). The same React runs in
   the editor and on the published page.
2. **Agent sections may use what a normal interactive page uses:** event handlers, state, effects,
   timers, animation, scroll and resize reading, observers.
3. **Guard by boundaries, not by banned words.** Where page code may send data is enforced by the
   browser through the page's security policy: **our own endpoints plus a short list of approved embed
   providers, never the open web.**
4. **Forms and lead capture are in scope now.** The kit gives sections a ready-made form and a tracking
   function (Ploy's `submitForm` / `ploy.track` pattern). Leads post to our endpoint, tagged with the
   account.
5. **Isolation between workspaces:** each workspace's pages live on their own subdomain of a pages
   domain listed on the Public Suffix List. The pages-domain move and its listing are **required**.
6. **Editing:** sections get an "editing" flag. In Edit mode interactive pieces stay still so a click
   selects; Preview runs them live.
7. **Keep refusing only what has a real reason:** `eval` and `Function` (clearer early message; the
   policy blocks them anyway), raw HTML injection (`dangerouslySetInnerHTML`), and all the brand rules.
8. **Custom head and body snippets are in scope now** (analytics tags, chat widgets). The page's policy
   is built per site from the domains its snippets need; only a person can add a snippet, never the
   agent; the snippet screen shows which outside services each snippet opens the page to.

## 3. What a published page becomes

```
                       publish (design API, hardened Chromium, network blocked)
 stored site ──► server render (renderToString) ──► HTML per route ─┐
 brand, agent section modules                       page data JSON ─┼─► publish package
 site-kit site runtime (built once per site-kit version) ───────────┤   (immutable, content-hashed)
 agent section modules (already compiled at write time) ────────────┤
 compiled CSS (Tailwind over the rendered HTML, as today) ──────────┘

 visitor ──► edge Worker ──► page origin: HTML (+ snippets, + policy header)
                                          /p-assets/<sha>.js  runtime, section modules
                                          /p-assets/<sha>.css site CSS
                                          /asset-store/<sha>  images, fonts
          browser: shows the server HTML at once, then React hydrates it: clicks, state,
          effects, forms, tracking and embeds work.
```

What stays: the server render still happens in the hardened Chromium page; search engines still read
full HTML; images and fonts are still served from the asset store; the CSS is still compiled per site
from the rendered HTML.

## 4. Components

### 4.1 Server render

- `renderSitePages` switches from `renderToStaticMarkup` to **`renderToString`**, so the HTML carries
  what React needs to hydrate it. It still runs inside `render-browser.tsx` in the hardened page.
- For each route the render also returns that route's **page data**: the Puck data of the page, the
  shell, and the subset of `BrandData` the page needs (the kit tokens and only the clones the page
  uses — clones carry captured HTML and can be large).
- Puck's server `Render` (`@puckeditor/core/rsc`) and its client `Render` must produce the same
  markup for the same data. **This is the first thing to prove** (§16, phase 1 spike); if they differ,
  both sides use the same one.

### 4.2 The site runtime

- One browser bundle built by site-kit's build (`bin/build-bundles.mjs`), next to `render-browser`:
  React, ReactDOM client, Puck's client `Render`, site-kit's config, sections, kit and theme, and the
  hydration entry. Content-hashed, so every publish that uses the same site-kit build shares one file.
- On load it reads the page data (`<script type="application/json" id="clue-page-data">`, which the
  browser never executes), loads the page's agent section modules, builds the same config the server
  render built (`makeConfig(brand, {basePath, shell, agentSections})`) and calls `hydrateRoot`.
- A hydration mismatch is reported to our events endpoint (§7) through React's `onRecoverableError`,
  so we learn of any drift between server and browser; React then repairs the page by drawing it in the
  browser.
- The runtime sets no cookies. A visitor id for tracking lives in `localStorage`, which is per origin.

### 4.3 Agent sections on the published page

- Each agent section's compiled module (stored at write time, `design_site_section`) is published as an
  immutable asset, `/p-assets/<sha>.js`.
- Sections import `react`, `react/jsx-runtime` and `zod`. An **import map** in the page points those at
  shims that hand over the runtime's own copies, exactly as the editor does today.
- **One shared function decides what a section can import from each library** — the editor's shims,
  the renderer's shims and the published runtime's shims all come from it (review finding K2-1: today
  the editor hands over a hand-written short list while the renderer hands over everything).

### 4.4 The publish package

- Manifest `delivery: "site_live"` (today's static site publishes keep `delivery: "site"` and keep
  being served exactly as now; §15).
- Pages: HTML per route (server render + our head + page data + the import map + the runtime script
  tag). Assets: the runtime, each agent section module, the site CSS. All go through the existing
  publish-asset path (`web_export.PublishPackage.assets`, served by the page origin's
  `/p-assets/{sha}.{js|css}` route with its integrity check, `clue_design.publishes.check_publish_asset`).
- The manifest records which embed providers the site uses (§8), so the policy can be built from it.

### 4.5 Verify, never rewrite

Hydration requires the HTML the browser receives to be exactly what React drew. A cleaner that removes
things from React's output would break hydration. So the publish step **checks** the rendered HTML and
**refuses** the publish with a plain reason, instead of stripping:

- no `<script>`, `<iframe>`, `<object>`, `<embed>`, `<base>` or `<meta http-equiv>` in rendered output
  (ours are added after the check);
- no `javascript:` URLs; `src`/`srcset`/`poster` only to the asset store, a site route, `data:`, or an
  approved embed provider through `kit.Embed`;
- a `<form>` only as drawn by `kit.Form`, posting to our own endpoint.

React never writes `on*` attributes into HTML, so event handlers cannot appear there. Clones keep their
own path: their captured HTML is cleaned when it is captured (scripts dropped, as today) and checked the
same way at publish. The agent's previews run the same check, so the agent sees a refusal before the
marketer does.

### 4.6 The page's security policy

Built per site, from three inputs: the platform's fixed part, the embed providers the site uses, and
the workspace's snippets (§9). The page origin assembles it when it serves the page.

| Directive | Value |
|---|---|
| `script-src` | `'self'`; the hash of the page's inline import map; the snippets' inline-script hashes and declared script hosts; the embed providers' script hosts (only providers that need a script) |
| `connect-src` | `'self'` (our form and events endpoints are same-origin paths); snippet hosts; embed provider hosts that need it |
| `frame-src` | the embed providers the site uses; snippet hosts that frame (chat widgets) |
| `img-src` | `'self' data:`; snippet pixel hosts |
| `style-src` | `'self' 'unsafe-inline'` (the theme, clones' captured CSS) |
| `font-src` / `media-src` | `'self' data:` / `'self'` |
| `form-action` | `'self'` |
| `object-src`, `base-uri` | `'none'` |
| `frame-ancestors` | `'self'` (header only) |

There is no `'unsafe-eval'` and no `'unsafe-inline'` for scripts: inline scripts run only by hash. This
is the boundary the research recommends ("a static page can carry a hash-based CSP with allowlists for
`connect-src`, `img-src` and `form-action`"), and it holds whatever tricks the code uses.

### 4.7 Page origin

- Serves `delivery: "site_live"` pages with the per-site policy header (§4.6) and injects the
  workspace's snippets (§9) at serve time.
- Gains two same-origin POST routes, the only non-GET routes it has:
  - `POST /_clue/forms/{slug}` — a form submission (§6);
  - `POST /_clue/events/{slug}` — tracking events and hydration reports (§7).
  Both are rate-limited per visitor IP and per publish, size-capped, and accept only the publish's
  declared forms and well-formed events.
- The ETag of a page covers both the publish's HTML digest and the snippet version, so a snippet change
  is served at once without a republish.

### 4.8 Edge Worker

Today it answers every non-GET/HEAD request on our hosts with `method_not_allowed`
(`infra/cloudflare/pages-edge/routing.js`). It gains one rule: `POST` to `/_clue/forms/…` and
`/_clue/events/…` is forwarded to the origin with the same edge-auth header; every other POST stays
refused.

## 5. What a section may do

**Allowed** (refusals removed from `site-kit/src/check-section.ts`):

- event handlers (`onClick`, `onSubmit`, …);
- React state, effects, refs, context, memo, transitions;
- timers (`setTimeout`, `setInterval`, `requestAnimationFrame`);
- reading the page for layout and motion: `window`, `document` (scroll, size, media queries,
  `IntersectionObserver`, `ResizeObserver`);
- `localStorage`, `fetch` and the like are not refused by the checker either: where they can reach is
  decided by the page's policy (§4.6), not by the checker. The skill steers the agent to `kit.Form` and
  `kit.track` for anything that sends data.

**Still refused** (each with its reason):

| Refused | Why |
|---|---|
| `eval`, `Function` | the page policy blocks them anyway; refusing early gives the agent a clear message |
| `dangerouslySetInnerHTML` | raw HTML injection |
| raw `<a>` | links must go through `kit.Link` / `kit.Button` so they reach the right page wherever the site is published (unchanged) |
| raw `<script>`, `<iframe>`, `<form>`, `<object>`, `<embed>` | use `kit.Embed` and `kit.Form`, which are the only ways to frame a provider or post data |
| a `kit.Button` or `kit.Link` inside a linked `kit.Card` | a link inside a link is invalid HTML; the browser reorders it and hydration breaks (review finding S1-5). Refused by the checker and, for cases the checker cannot see, by the kit while it draws |
| colour values, Tailwind palette colours and default type, custom colour/type/corner values, unknown brand names | brand rules, unchanged |
| `cookie` | page code does not set cookies: the runtime does not use them, and the pages domain's cookie isolation (§12) should not depend on every section behaving |

**One new rule, taught in the skill and checked in previews:** a section must draw the same thing on
the server and in the browser. Anything that depends on the browser (window size, time, random numbers,
storage) is read in an effect, not while drawing. The agent's preview reports any hydration mismatch
to the agent (§11).

**The kit gains:**

| Kit piece | What it does |
|---|---|
| `kit.Form({ name, fields, submitLabel, successMessage })` | a lead form drawn in the brand's style; posts to `/_clue/forms/{slug}`; shows its own sent and failed states |
| `kit.track(event, props)` | sends one tracking event to `/_clue/events/{slug}`, tagged with the site and account |
| `kit.Embed({ provider, url, title, aspect })` | frames one approved provider (§8), sized by `aspect`, with a title for accessibility |
| `kit.editing` | `true` in the editor's Edit mode, `false` in Preview and on the published page (§10) |

## 6. Forms and lead capture

- **Drawing:** `kit.Form` in agent sections. (A form inside the built-in sections is not in this
  spec.)
- **Submitting:** `POST /_clue/forms/{slug}` with the form's name and field values. The page origin
  checks the form is one the publish declared (the manifest lists each form's name and fields) and
  stores the submission. **No spam filtering in this spec** (founder, 2026-10-15): Cloudflare
  Turnstile is added when junk leads appear. The route keeps only the protections every public
  endpoint needs to stay up: a size cap and a generous per-visitor rate limit; it does not judge
  whether a submission is spam.
- **Storage (new table `site_form_submission`):** workspace, document, publish, slug, route, form name,
  field values, the account the site was made for, the visitor id, the time. Personal data: scoped to
  the workspace, erasable (a person can delete a submission; the DSAR erasure path covers the table),
  never shown to the agent.
- **Lead email (founder, 2026-10-15):** every new lead is emailed to the workspace's admins (the
  default recipients; choosing other recipients waits for a designed screen). How it works:
  - storing the submission and sending the email are separate steps. The form route writes the
    submission and an outbox row in one transaction and answers the visitor at once; a background
    worker sends the email through a transactional email service's HTTPS API, retrying on failure.
    A slow or failing email service never slows or loses a lead;
  - the email names the site, the account and the submitted fields, and links to the site in the app;
  - the service sends from a dedicated subdomain of `cluehq.ai` (for example `notify.cluehq.ai`),
    so its sending reputation is kept apart from the main domain; the founder creates the account,
    adds its DNS records (SPF, DKIM, DMARC) and puts its key in the env (`CLUE_EMAIL_*`, in
    `.env.example` with defaults from the start);
  - the email carries the lead's personal data to the email service (a new subprocessor) and to the
    recipients' inboxes. Erasing a submission cannot recall an email already sent.
- **Seeing leads in the app:** the founders design the leads screen later; until then leads are
  stored and emailed.

## 7. Tracking

- The runtime sends a `page_view` on load; sections send their own events with `kit.track`. Each event
  carries the site, the route, the account the site was made for and the visitor id.
- Stored in a new table `site_event` (workspace-scoped, retention-bounded). Hydration mismatch reports
  use the same endpoint with a reserved event name, so a drift between server and browser is visible
  to us.
- No reporting screen in this spec (it waits for designed frames); the data is collected from the
  first live publish.

## 8. Approved embeds

- A **code-owned registry** of providers. For each: the URL patterns accepted, how a page URL becomes
  an embed URL, and the policy hosts it needs (`frame-src`, plus `script-src`/`connect-src` only if the
  provider needs a script). The initial list (founder, 2026-10-15): Calendly, HubSpot (meetings and
  forms), YouTube, Vimeo, Loom, Wistia.
- `kit.Embed` refuses a URL that matches no provider (in the checker when the URL is literal; at
  render otherwise), so an unapproved host can never reach the page or its policy.
- The publish manifest lists the providers the site uses; the policy (§4.6) allows only those.
- In the editor and in the agent's previews the network is closed, so an embed draws as a sized
  placeholder naming the provider. The layout matches the published page; only the frame's content
  differs. This is the one intended difference between the editor and the published page.

## 9. Custom head and body snippets

- **Where:** Settings → Pages, the "Additional code snippets" card that the custom-domain spec removed
  for later (§ "Kept / Dropped / Deferred" of the 2026-09-17 spec). The card is lifted from the dummy
  frontend as designed; if its frames do not cover the policy display below, the co-founder owes them.
- **Scope:** per workspace (every site the workspace publishes). A per-site override is not in this
  spec.
- **Who:** a person with the workspace admin role. The agent never sees, writes or edits snippets; no
  tool exposes them.
- **What is stored** (new columns on `workspace_pages_settings`, or a sibling table): the head snippet,
  the body snippet, and for each the outside hosts it needs and the hashes of its inline scripts.
- **How hosts are found:** a code-owned library of common services (Google Tag Manager, Google
  Analytics, HubSpot, Segment, Intercom, Drift, Hotjar, LinkedIn Insight, Meta Pixel) maps a recognised
  snippet to the hosts it needs. The `src` of every external script in the snippet is added. Anything
  else the marketer adds by hand ("this snippet also connects to …").
- **What the screen shows:** for each snippet, the outside services it opens the page to, in plain
  words, and a note that page code on the same page can reach those services too.
- **Serving:** the page origin injects the head snippet before `</head>` and the body snippet before
  `</body>` when it serves a live page, and adds the snippet's hosts and hashes to that page's policy.
  A change applies at once to every live page of the workspace.
- **Custom domains:** a site on the customer's own domain runs its page code on their domain. The
  connect-a-domain screen says so in plain words (the research's "they should make that choice
  knowingly").

## 10. Editing

- Puck passes `puck.isEditing` to every component's render (site-kit already reads it,
  `site-kit/src/config.tsx:205`). The kit exposes it to sections as `kit.editing`.
- **Edit mode:** `kit.Form` shows its fields but never posts; `kit.Embed` shows its placeholder;
  carousels, tabs, accordions and other interactive pieces stay in their first state, so a click
  selects the section instead of driving it. The skill teaches sections to do the same with
  `kit.editing`.
- **Preview mode:** everything runs live, as on the published page, except embeds (placeholder; the
  editor domain's network stays closed) and form posts (a Preview submit shows the sent state without
  posting).
- The editor's own containment is unchanged (D2: separate domain, frame sandbox, editor CSP).

## 11. The agent's view

- The agent's previews and screenshots (`site_turn_ports.py`, `site_render.capture_site_screenshot`)
  run with **JavaScript on**: the hardened page loads the server HTML, the runtime and the section
  modules from local files, hydrates, lets effects and entrance animations settle, then takes the
  screenshot. The network stays blocked in all five layers.
- The preview returns, as warnings to the agent: hydration mismatches, errors thrown in effects, and
  the publish check's refusals (§4.5).

## 12. Isolation and domains

- Each workspace's pages are served from `<label>.<pages domain>`. With the pages domain on the Public
  Suffix List, browsers treat every label as its own site, so one workspace's page code cannot affect
  another's cookies or storage (the research's GitHub, Retool and Canva precedents).
- **Required before customers publish live sites in production:** the pages-domain move (runbook §8,
  after the review's group 4.5 fixes K3-6, S4-1, S4-3, S7-3) and the Public Suffix List application.
  Until then live publishing is behind a per-workspace flag for internal and demo workspaces.
- Agent code still never runs on `app.cluehq.ai` or in a platform process (D2).

## 13. How review group 4.3 fits

| Finding | Under this design |
|---|---|
| K5-2 editor lacks the brand's spacing | the editor's theme block is generated from site-kit's own role lists (colour, type, radius, spacing) at editor build time, so a new brand setting cannot be forgotten; a test pins it against `tailwindThemeCss` |
| K2-1 a section opens on the page but not in the editor | one shared import list for the renderer, the editor and the published runtime (§4.3) |
| K1-2 an id the editor refuses | one id rule (`ComponentIdSchema`), used by the save check and the editor; adding an agent section refuses a schema whose `id` is not required text |
| S1-5 a button inside a linked card | refused by the checker and by the kit while drawing (§5); hydration would otherwise break |
| S2a-2 agent sections break in Edit mode | before marking a text setting editable on the canvas, the editor draws the section off-screen with a marker word in it, and marks it editable only if the marker appears as visible text, unchanged; surface and style settings become pick-lists of the brand's choices |
| S2b-8 the brand is read once per site | the brand is read again whenever the loaded site uses a clone the editor's copy lacks |
| K1-3 a Versions-menu restore is refused because of its clones | the restore's check allows the clones of the version it brings back (the server-side half of S2b-8) |
| S6-2 button icons sized or coloured by the seller's CSS | site-kit draws the icon at the size the kit stores; capture writes each icon shape's real fill and stroke onto it (existing kits gain this only on a founder-approved re-capture) |
| S1-4 cleared headline | fixed earlier (sync fix) |
| state and effects differ between editor and page | gone: both run them |

**The guard for the whole class:** one test renders a real fixture site both ways — the editor's
Preview in a browser, and the published page (server render, then hydration in a browser) — and
compares them section by section: elements present, spacing, colours, text sizes, icon sizes. It also
asserts zero hydration mismatches. Embeds are compared as placeholders.

## 14. What stays the same

D2 and the hardened server render; the editor domain and its containment; the separate pages domain;
the brand rules and the measured brand kit; clones and their capture; the publish tables, the
publish-asset route and its integrity check; noindex and the SEO head; asset custody; static
`delivery: "site"` publishes already live.

## 15. Rollout and compatibility

- A per-workspace flag turns live publishing on. With it off, publishing is byte-identical to today.
- Existing static publishes keep serving under their own policy. Republishing a site with the flag on
  makes it live.
- The agent's skills change with the flag: the section-writing skill gains the allowed list, the kit's
  new pieces, the same-on-server-and-browser rule and the linked-card rule. The skill's exact wording is
  the founder's to review before it is written.

## 16. Phases

Each phase gets its own implementation plan; each ships behind the flag and is tested on its own.

1. **Live core.** Spike first: Puck server and client `Render` produce identical markup for the
   Garner fixture, and a page hydrates with zero mismatches. Then: `renderToString`, the site runtime,
   section modules and the import map as publish assets, the shared import list (K2-1), verify-not-strip
   (§4.5), the per-site policy without snippets or embeds, the page origin serving `site_live`, the
   relaxed checker (§5), `kit.editing`, and JS-on agent previews.
2. **Forms and tracking.** `kit.Form`, `kit.track`, the two POST routes, the Worker rule, the two
   tables, the outbox and the lead email, erasure.
3. **Embeds.** The provider registry, `kit.Embed`, placeholders, policy from the manifest.
4. **Snippets.** Storage, the Settings card, host detection, serve-time injection, policy merge, the
   custom-domain note.
5. **Group 4.3 and the parity test** (§13). The fixes that do not depend on phase 1 (K5-2, K1-2,
   S2b-8, S6-2 size) may land first.

The pages-domain move and Public Suffix List listing (§12) run beside these and gate production use.

**Scope of this round (founder, 2026-10-15):** phase 1 (most important), phase 3 (embeds), phase 4
(snippets), phase 5 (group 4.3 with K1-3) and the pages-domain prerequisite (group 4.5's fixes, then
the move). **Phase 2 — forms, the lead email and tracking — is designed here but built in a later
round**; its decisions (§18) stand. Until phase 2 lands:

- the kit has no `kit.Form` or `kit.track`, and the checker keeps refusing raw `<form>`;
- the page origin stays GET/HEAD only and the edge Worker is unchanged;
- hydration mismatches on published pages are not reported to us; the agent's previews (§11) and
  the parity test (§13) are what catch them;
- the page's policy keeps `connect-src 'self'` and `form-action 'none'`.

Order: phase 1 starts with its spike; group 4.5 and the 4.3 fixes that do not need phase 1 (K5-2,
K1-2, S2b-8 with K1-3, S6-2 size) run beside it; phases 3 and 4 follow phase 1 and can run side by
side; the rest of phase 5 and the parity test close the round.

## 17. Testing

- Phase 1 spike: identical server/client markup and zero hydration mismatches on the Garner fixture.
- The parity test (§13).
- Real-browser policy tests: a section that tries to send data to a host that is not allowed is
  blocked by the browser on the published page; an allowed embed loads; a snippet's declared host is
  allowed and an undeclared one is not; `eval` is refused.
- Verify-not-strip: a rendered page with a forbidden element is refused with its reason, and a clean
  page passes byte-identical.
- Forms end to end through the real Worker rule, page origin route and table: a submission is stored
  with its account and its lead email is sent through the outbox (a failing email service retries and
  never loses the lead); an oversized body and a burst past the rate limit are refused; an undeclared
  form is refused; erasure removes it.
- Edit mode: an interactive section stays still and a click selects it; Preview runs it.
- The agent preview reports a hydration mismatch and a publish-check refusal as warnings.
- Flag off: a publish is byte-identical to today.

## 18. Open decisions for the founder

1. **Lead notifications — decided (founder, 2026-10-15):** every lead is emailed to the workspace's
   admins (§6). Still open: **which email service** (the founder creates the account).
2. **Leads and tracking screens — decided (founder, 2026-10-15):** the founders design them later; the
   features (forms, tracking, storage) are built now and collect data from the first live publish.
3. **The first approved embed providers — decided (founder, 2026-10-15):** Calendly, HubSpot (meetings
   and forms), YouTube, Vimeo, Loom, Wistia.
4. **Spam protection — decided (founder, 2026-10-15):** none in this spec; Cloudflare Turnstile is
   added when the need appears.
5. **K1-3 — decided (founder, 2026-10-15):** fixed together with group 4.3 (§13): a restore allows the
   clones of the version it brings back.

## 19. Documents to update when this is approved

- The integration plan's Contract 3 and review-focus item 7 (superseded, pointing here).
- `subsystems/clue-design/apps/agent_runtime/lumen_agent/site/skills-e5/writing-a-section/SKILL.md`
  (with the founder's review of the wording).
- `docs/specs/pages-hosting-runbook.md` "Not done yet" (snippets) and §8 (the listing is required).
- The custom-domain spec's snippet deferral.
