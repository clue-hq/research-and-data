# 2026-09-02 — F5 (true multi-page + publishing) scope re-ratified on `design/website-multi-page`

Session: analysis + scope discussion only. No code changed. Master plan F5 section rewritten
(`docs/superpowers/plans/2026-08-27-clone-fidelity-master-plan.md`, status header + Phase F5;
the 2026-08-27 provision kept beneath it as record). Branch purpose: complete multi-page.

## What the scout found (verified in-tree, post-F4)
- Engine is N-page-shaped: `WebDoc.pages` vec (`id/name/route/root/nodes`), duplicate id/route
  validation, `derive` loops pages, `render_page(doc, page_id)`, **`SetPageMeta` op exists and
  nothing calls it**. No `AddPage`/`RemovePage`. Route validation = duplicates only (no grammar).
- Every doc born with one page `home` at `/` (`doc.rs` ~846; `web_new_doc` main.py ~2398).
- `"home"` sites (plan anchors were stale): `main.py` ~3594–3686 (render), ~8672 (turn targets),
  ~8840–8847 (turn fragment package); `web_export.py:81` `HOME_PAGE_ID`; `web_substrate.py:177`
  + `LumenWebTools.page_id` ~890 (≈40 tool sites read `self.page_id` — one assignment away from
  page-aware); `web_bridge.py:1250` default; `harness_web.py` `has_existing_content(...HOME)`;
  platform shell `engine/webDocuments.ts:509` render fetch has NO page param; dev-shell
  `WebEditorApp.tsx:151` first-page fallback, no switcher; thumbnail = first page.
- The "replay gate" blocker (b) is not separate work: the gate replays any engine-accepted op.
- Publish: `design_web_publish` PK `(workspace, slug)`, ONE `html` column; serving returns it;
  package renders `HOME_PAGE_ID` only; manifest stamps `page_id: "home"`.
- **Platform shell Publish is a dummy**: `use-artifact-sharing-controller.ts` fakes with a
  timer, prints `https://share.cluehq.ai/{slug}`; `clue:artifact-publish-request` has no
  listener; no platform BFF publish proxy. Designed share menu already has slug / indexing /
  description / custom-HTML fields (presentation truth exists).
- Public base = `request.base_url` of the design API (interim O6b `/w/{ws}/p/{slug}`).
- Capture is homepage-only (`ingest_website(url)`); multi-page capture "agreed, unscheduled"
  per `_memory/2026-08-30-brand-color-ingestion-poc.md`.
- Cloned nav anchors keep absolute hrefs to the client's live site (sanitizer keeps http(s));
  `FragmentSlotKind::Href` is the rebinding mechanism; `href_is_allowed` accepts `/` paths;
  F4 `ESCAPE_ROUTE_ROLES = {nav, footer}` refuses nav on ABM pages.
- Run-quality carry (OpenAI CFO run 2026-09-01, 57 min): `_ROUND_MUTATION_BUDGET = 14` per
  render round + delegation state loss will multiply per page in a multi-page build.

## Founder rulings (LAW, 2026-09-02) — R-F5-1..5
1. URL shape: tenant subdomain per workspace; `{handle}.pages.cluehq.ai/{site-slug}{route}`;
   public base from CONFIG (env-parity rule), never the request host.
2. Publish unit = the SITE (all pages under one slug, each at its route); no per-page state.
3. Dialog slug = site slug; home route stays `/`.
4. Indexing law unchanged (ABM noindex durable; ordinary sites follow the toggle).
5. Workspace handle — DEFAULT set by plan (auto-derived from workspace/brand name, editable
   until first publish, immutable after; rename+redirect = future). Founder to confirm at dispatch.
Also ruled: F5 owns default-domain serving (Part-IV item 5 no longer a gate); custom domains =
premium follow-on, resolver table designed to receive them.

## Later the same day — RULED: R-F5-6 CP3 v1 = per-account ABM microsite (landing + supporting
pages, internal nav, noindex); R-F5-7 pages from homepage library + new sections, multi-page
capture = separate follow-on on a SEPARATE BRANCH. R-F5-8: links are structurally FREE (any
destination, no gate); agent guidance only. F4's by-role nav/footer refusal (R24-1) and the
shell one-anchor shape gate (R23-3) demote to advisory in F5.4; publish audit unchanged;
sanitizer scheme rules + noindex law unchanged. ALL F5 rulings now in (R-F5-1..8; R-F5-5 is a
plan default to confirm at dispatch).

## Lanes fixed in the plan
F5.0 engine page ops + route grammar · F5.1 page-aware render/preview/review · F5.2 N-page
publish + serving `(ws, slug, route)` · F5.3 shell publish wiring (interim route first) + default
domain (handle, config base, host→workspace resolver table, wildcard DNS/TLS) · F5.4 agent page
vocabulary (active page, page tools, skills text, one author delegation per page, budget reset
per page render) · F5.5 route editor (needs a designed inspector slot — flag for dummy frontend).

## Execution plan written (same day, inline by Fable — founder: no Opus scouts for planning)
`docs/superpowers/plans/2026-09-02-f5-multipage-sites-and-publishing.md` — 22 tasks: T1–T3 engine
(route grammar LUMW0036, AddPage/RemovePage, API round-trip), T4–T5 page-aware render, T6–T9 agent
(active page + 4 page tools, turn-side literals, harness/prompts/skills, R-F5-8 advisory demotion),
T10–T12 publish (revision pages + materialized current pages, per-route serving + link rewrite +
export ZIP, PublicSiteAddress from env), T13–T16 shell publish wiring + workspace handle + Host
sub-app, T17–T21 op builders / page switcher / route editor / in-editor nav / dev-shell parity,
T22 CP3 walk. Env keys introduced: LUMEN_PUBLIC_PAGES_HOST_SUFFIX (blank = interim path routing),
LUMEN_PUBLIC_PAGES_SCHEME. Infra prerequisite outside code: public ingress for the design API +
wildcard DNS/TLS for *.pages.cluehq.ai (design API is tunnel-only today).

## Next
Founder reviews the execution plan
(superpowers:writing-plans; SDD, Opus implementers, Fable reviews) → dispatch F5.0 first.
Note: the SDD ledger `.superpowers/sdd/2026-08-27-clone-fidelity-master-plan/progress.md` is not
present in this worktree (untracked on the F4 host).
