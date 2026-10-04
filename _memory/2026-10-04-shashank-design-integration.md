# Integration of Shashank's design-agent work onto research-streaming — 2026-10-04

Branch `integration/shashank-design-onto-research-streaming` (local only, never pushed), cut from
`origin/research-streaming` @ `1ad82b6be` (research-streaming = main + 12 tracing commits; main's
only extra commits are research-streaming PR merges). Source: `brand-context-fixes/typography`
(Shashank Keshri, 100 commits unique vs main, Sep 18 – Oct 2).

## Decisions (user, with co-founder) — binding for this branch
- Discard ALL of Shashank's Head-of-ABM skill/manual work: head-of-abm v61–v63, manual-* v8–v10,
  tool_notes.yaml, manual/build.py, design_leg_tools.py wording, Head pins (2fc1fc505, cff9484cd,
  17c57a271, bdab6c278 incl. its design-skill half — it repeated the unresolved "discovered account
  is not approved" premise).
- Drop his `read_account_research@3` + design profile v3 (bf27a3822): it reads legacy
  `live_blocks`, which 13f1df084 retired — measured 0 legacy overview blocks for all 4 researched
  accounts in clue_dubai / clue_addis-ababa, so it would serve nothing.
- Instead: make the EXISTING `read_account_research@2` overview page in place (both Head of ABM and
  design agent). Measured on main: 3 of 4 real overviews cut (6/6, 4/6, 3/6, 4/6 sections served;
  12 KB page budget, 6000-char section clip, offset refused).
- Keep (code, not skills): workspace.py glob fix (no manual note), d79e50409 project decision
  provenance, compatibility-pin fix, Docker executable fix (verified red/green + live repro),
  Google sign-in, logo ladder, all website/design work and docs.
- Duplicates dropped for research-streaming's own: 0495b025a (e818a815b), a8a861afc (d850ab23a),
  0a8b79e11 (d6b7579c0 — opposite behaviour; Shashank's would fail the run).
- Setup-screen missing-website form (698b62071) HELD; user could not view the preview.
- Discovery ON by default (`.env.example` + code default).
- Head of ABM v71 + manual v17: correct "opening a leg starts nothing" (prompt v18 says it starts at
  once) in tool_notes/manual-siblings/manual-gates-authority; keep research-streaming's leg-close
  wording unchanged; fix tool_notes "overview is served whole".
- Method: one merge + follow-up commits.

## Progress (commits on the branch, oldest first)
- 6841e7f24 merge commit (all conflicts resolved; rank_assets + rendition families; fetched-logo
  kind rule moved into asset_catalog; SVG flag moved to asset-detail-dialog.tsx;
  project_design_context kept beside web_search; bdab6c278 design-skill text reverse-applied).
- 0132e11f5 alembic merge revision 10edab6dd974 (single head).
- a46fce640 read_account_research overview pages by whole section (offset = section index,
  next_offset; 6000-char clip removed; only a single section larger than the 12 KB page is
  clipped, byte-measured, flagged body_truncated; offset past end -> offset_past_end). Design
  wrapper description + 4 design skill passages reworded. Pins unchanged.
- 6676607ac Head of ABM v71 + manual v17 + stage0-interview v44 (path repoint only): design-leg
  first turn queued at once (manual-siblings, manual-gates-authority, tool_notes open_design_leg,
  design_leg_tools docstring); offset_not_paged note removed; tool descriptions say overview
  pages. Resource-manifest digest de9c2220… pinned in test_agent_registry_wiring.
- cf132b77a arv2_discovery_enabled defaults to true (handler still needs CLUE_EXA_API_KEY).

## Verification so far
- Throwaway DBs created on the local server: clue_trenton_integ (tests), clue_trenton_smoke
  (db-smoke up/down/up passed, single head 10edab6dd974). The lane DB clue_trenton no longer exists.
- read tools 76 pass; agent catalog/manual/registry/wiring/recipe set pass; design agent focused 44
  pass; lumen-web cargo tests 258 pass; strict editor wasm preflight passes (lumen-wasm depends only
  on lumen-core, unchanged); root ruff/format/mypy/import-linter clean.
- Run tests WITHOUT sourcing .env (env -i + CLUE_DATABASE_URL only): the real Exa key otherwise
  leaks into "keyless" fixtures and live keys must not ride broad suites.
- Owed per host: rebuild lumen-api-helper (Shashank changed lumen-web + helper main.rs).
- Root suite (--ignore-glob='*_live.py'): research-streaming baseline itself fails 143 tests
  (worktree in scratchpad, its own venv, DB clue_trenton_rsbase). This branch's extra failures
  were 21; in isolation 5 also fail on baseline (order-dependent), 10 fail on baseline when given
  the lane's `.env` (Settings reads the .env FILE even under env -i — lane settings, not code).
  One real regression: test_o6_conversation_composition_db expected the old decisions.md index
  summary changed by d79e50409 -> fixed in ab90fd4d4 (5/5 pass).
- Frontend gate (design-system:build, lint, build) passed; 196 onboarding/brand-context tests pass.
- Design focused tests: test_editor_preflight needs LUMEN_EMBEDDED_FLEET_WORKER=0 (51 pass with
  it); test_web_fragment_export needs apps/editor/node_modules (@tailwindcss/node) which is not
  installed in this worktree; the two test_web_turns failures ("agent_run ... not found") fail
  identically on research-streaming (pre-existing).
- ab90fd4d4 test fix for the decisions.md index description (the one merge-introduced failure).

## Closing state (2026-10-04, design comparison stopped by the user)
- Branch HEAD = ab90fd4d4 + this note; 7 commits on top of research-streaming, nothing pushed.
- Design focused tests (79 files from Shashank's kept commits, run in ONE pytest session):
  2045 passed / 68 failed / 4 skipped. Running the two folders separately (as AGENTS.md §3
  requires — a combined session shadows `conftest`) cleared many: apps/agent_runtime alone =
  22 failed / 98 passed (test_web_recreate_and_repair 11, test_web_review_gate 5,
  test_native_fragment_reuse 4, test_repaired_section_styles 1, test_web_geometry_vocabulary 1 —
  the last one also fails on Shashank's own branch). The apps/api per-folder run and the
  Shashank-branch baseline were STOPPED before finishing, so those design failures are
  UNCONFIRMED. Most likely cause: this worktree lacks apps/editor/node_modules and the untracked
  vendored Tailwind runtime (AGENTS.md §5), which the clone-repair / review-gate / fragment-export
  tests need. Owed: rerun `pytest apps/agent_runtime/tests` and `pytest apps/api/tests`
  separately on a host with those installed, against the Shashank branch as baseline.
- Throwaway DBs left on the local server (safe to drop): clue_trenton_integ, clue_trenton_smoke,
  clue_trenton_rsbase, clue_trenton_typo. Scratchpad baseline worktrees removed.
- Owed before any live run: rebuild lumen-api-helper on the host; founder review of the v17
  manual wording (presented in chat); setup-screen form (698b62071) still held.

## Verification of the Astra (Shashank's agent) typography/ad audit claims — 2026-10-04
Code-read + offline repro with the real normalizer (scratch script, no DB, no spend):
- CONFIRMED hidden headings win: capture/rendered.py `take(t, 3)` = first 3 per tag in DOM order,
  no visibility check; parse.py `_parse_computed_samples` drops `area` and keeps a bare
  `rendered :: h1` locator. Repro: hidden 96px/700 H1 before visible 56px/400 -> kit headline 96/700.
- CONFIRMED one heading family overwrites measured roles: normalizer/typography.py `_family_from`
  (frequency election) + build_type_styles line ~288. Repro: serif H1 + sans H2/H3 -> headline sans.
- CONFIRMED entry-page-only type samples: evidence_builder `build_evidence` parses only the entry
  snapshot; supporting pages feed assets only.
- CONFIRMED (ads) logo_policy LIGHT_SURFACES always allows surface.page/card; reference-fidelity
  gate (`substrate.py _reference_fidelity_error`) only activates via `_selected_reference_ids`,
  set solely in `_produce_image_asset` -> reuse-only ads finalize with no fidelity check.
- NEW (not in Astra's audit), root cause of bold ad headings: build_type_styles hard-codes
  display = max(heading_weight, 700) and stat = max(..., 700); eyebrow/label 600; subtitle 500.
  Only h1->headline, h2->title, body/p, button->cta, caption are measured (ANCHOR_LABELS). With no
  H1 captured, heading weight defaults to 700 and headline (32px) comes out smaller than title.
  Repro: all-400 source -> display 700, stat 700. The scene brand card puts type.display first
  (brand_card.py CARD_TYPE_ROLES) and SCENE_TYPE_SIZE_NOTE tells the agent to keep family/weight
  via style($type.display) -> every ad headline inherits the forced 700.
- NOT verified (evidence not on this machine): AWS cookie-modal provenance, Google draft-vs-approved
  kit, CSS truncation size, Arlo run traces — they live in Shashank's local `.local-setup/` and DB.

## Next (discussed, not started)
The branch's purpose was 1:1 creative typography fidelity. Shashank's audits
(subsystems/clue-design/docs/typography-ingestion-audit-and-plan-2026-09-29.md,
aws-google-typography-trace-2026-09-29.md, arlo-ad-trace-audit-2026-10-02.md) show the merged
fixes cover only part: still open — hidden headings win at capture (hidden 96px/700 beat visible
56px/400; AWS headline came from a cookie-modal H2), one frequency-elected heading family
overwrites every measured role, entry-page-only/no-viewport type samples, existing kits never
repaired (do NOT use scripts/rederive_kit_type_units.py for this), agent reuse of composed
fragments as if source, large component CSS truncated (AWS 2.7M chars), and scene ads have no
typography check (they use kit families/weights directly, so wrong kit weights become bold ad
headings). Proposed order: ingestion fix first (shared by web + ads), then versioned kit repair,
then a scene-ad typography check, then web fragment provenance/CSS truncation; no-spend replays
before any founder-run live test. Awaiting the user's answer on branch placement and order.

## Lane rebuilt for typography testing (2026-10-04, user request)
- Removed the stale 930 MB san-salvador storage from `.artifacts` (`git clean -fdx -- .artifacts`;
  the two git-tracked report folders kept).
- `clue_trenton` recreated as a dump/restore of `clue_addis-ababa` via the `clue-pg-papeete`
  container's own pg_dump/pg_restore (host tools are v15, server v16; addis had live connections),
  then upgraded to head 10edab6dd974. Contents: 241 kits, 64 design docs, 4 conduit.ai ingestions
  with saved evidence. Storage = addis-ababa `.artifacts` APFS-cloned (`cp -c -R`).
- `.env` rebuilt from `dushanbe/.env` with trenton DB/ports (3029/8019/8029/8039, pages 8049)/paths;
  previous file kept as `.env.bak-20261004`. All `.env.example` keys present.
- Built `lumen-api-helper` (release); handshake OK (engine bb1aaeea610a). `npm ci` in
  `apps/editor`; vendored `tailwind-browser.js` copied in. test_web_fragment_export now 16/16
  (was 14 env-blocked failures). Stack not started.

## Website quality diagnosis (2026-10-04) — evidence, no code changed
Real runs traced (addis-ababa worker traces + clue_trenton): "Conduit for JW Marriot"
(run_84f4a3c50ba35703b59963ba523a0dd4) and "Dana.AI landing page" (run_e0a891ca...).
- Capture yield: Conduit ingestion ingest_c162dc8c... minted 1 of 12 sections; 10 refused
  `fragment.unrehosted_reference` (/_next/image..., /figma/...svg?dpl=) — the requested-vs-final
  URL bug Shashank fixed in 0d06cd1d1 (on this branch, NOT on the lane that captured). So the agent
  composed 7 of 8 page sections itself. Fresh re-capture on this branch still owed to prove the fix.
- Composed sections: brand card (web lane) = display/headline/body/cta/eyebrow only (no title/h2,
  no units, no provenance); Conduit card headline 32/500 = builder default (real 56/400, section
  heading 48/400). Composed fragment CSS = raw px copied from the card (32/500, 20, 16, 12).
  theme.rs @theme emits only --color-*, --font-display/body, geometry (no type tokens); kit type
  rules carry NATIVE_SUBJECT :not(:where([data-lumen-fragment] *)) and composed sections ARE
  fragments -> kit scale never applies inside them. Source type scale (e.g. Conduit text-heading-1
  56px, source rem var) lives only in each clone's scoped CSS; compose_section mints without
  source_fragment_id (agent_cloned_sections.py ~1391; repairs pass it) so pasted clone CSS goes
  dead. web_typography_reference only downgrades accepted->completed_with_warnings, composed only.
  Skills conflict: brand-and-tokens ("use type.*") vs create-website ("source measurements win").
- Dynamic pages: rendered.py _harvest_page scrolls to bottom, scrollTo(0,0), 3s, then serializes
  (no settle-to-final-state, no getAnimations/finish); scripts dropped; JS inline styles kept;
  cssmatch keeps a rule only if all its classes exist in the captured subtree -> reveal-state rules
  (.is-visible etc.) dropped; hidden = display/visibility only; stealth backend has no viewport
  override (differs from downstream 1440); runtime has tabs/carousel only, no reveal logic.
  CORRECTION: the `opacity:1 !important` inline styles seen on the Conduit hero are SVG paint
  baking only (rendered.py SVG serializer), not a force-visible step.
- Unverified agent claims: editor vs export typography divergence (web_export drops
  --font-display/body; unguarded preflight), picker preview = source screenshot crop.

## Ploy study (2026-10-04) — skills zip + live Ploy session (read-only, in-app browser)
- Ploy clone = RECONSTRUCTION, not copy: capture HTML + linked CSS (+rendered fallback) as
  evidence -> design-system foundations (theme tokens) -> rebuild each section as a React/Tailwind
  component (source CSS translated to Tailwind incl. arbitrary values; source class names kept as
  hooks; SVGs extracted to components; text parsed programmatically, not retyped) -> interactions
  rebuilt per type (CSS / stateful component / carousel lib / motion lib / custom controller /
  stated fallback) -> visual + runtime review and repair. Ploy admits: not an identical copy;
  Stripe hero animated wave became a static image.
- Stack: Astro 6 routes (thin) + React 19 sections with typed props + TS + Tailwind v4 + CVA/shadcn
  + motion/react + react-hook-form/zod, Cloudflare Workers. ONE shared globals.css theme:
  color roles (--ploy-*) bound to Tailwind, font roles (heading/body/eyebrow/button) with measured
  weights (Stripe heading weight 300), letter-spacing, line-height, text-xs..9xl scale, radius
  tokens, real font file. Components carry @ployComponentId/Type/Pattern/Status registry JSDoc.
- New (from-scratch) sections: all colors via ploy tokens (only #0d1738 + white raw), one repeated
  house typography idiom (text-4xl md:text-6xl font-light leading-[1.05] tracking-[-0.045em]).
- Platform owns forms (submitForm -> /_ploy/form-submit) + tracking (window.ploy.track, account
  tagged); scale = /abm/[account] + typed records in PloyDB; direct text edit in preview (no AI).
- Key implication: our root cause is per-section scoped CSS islands vs Ploy's single shared theme;
  we copied Ploy's skill names/process but not its substrate. Raw notes: scratchpad only.

## Founder rulings after the Ploy study (2026-10-04) — direction only, no plan committed yet
- Each seller's pages may become a standard code project (Astro/React/Tailwind, Ploy-like) that
  the platform builds and serves, provided output quality is pristine. Ads stay on the current
  Rust scene engine.
- Our own capture pipeline stays as the evidence source for the rebuild (not Ploy's lighter one).
- Direct text editing in the preview (Ploy's no-AI quick edit) is wanted in the first version.
- Still open for discussion: week-1 bridge scope in the current engine, the parallel code-first
  lane's v1 scope, framework/hosting shape, what happens to existing web documents.

## Founder rulings + copy-quality diagnosis (2026-10-04, later)
- Rulings: existing web docs stay on the current engine (no migration); code-first lane = Astro
  static + React (Ploy-like); week-1 table accepted incl. the ad forced-bold fix; I build the
  code-first lane in a second worktree. ADDED to week 1: copy/content quality of 1:1 ABM pages
  (demos this week).
- Evidence: only 2 real web docs in clue_trenton (Conduit for JW Marriot doc_28084f01..., Dana.AI
  doc_c0c22f01...); copy extracted from fragment payloads + slots (scratchpad page_copy.txt).
- Findings: (1) audit/brief language leaks into visitor copy verbatim ("vendor-published case
  studies, not JW Marriott results, and not independent causal proof", "Opera Cloud is one Conduit
  names", "No generic startup signup", "Not a hotel-operator pitch") — Head-of-ABM briefs are
  written in caveat voice and the design agent lifts their wording; (2) copy-craft.md requires a
  visible qualification "BESIDE the claim, in body text" for analogous proof while
  conversion-copywriting/review-website say keep caveats out — contradictory, agent picks literal
  labeling; (3) Dana page names contacts in body copy ("Alon, the overlap") because the brief said
  "address him as economic buyer", and knocks the prospect ("not a disconnected CRM");
  (4) JW Marriott had no account research/account_id, so the page is a name swap; (5) copy skills
  are ~5.5k words of compressed rules (vs Ploy's plain worked weak/strong examples); writer is
  grok-4.6. Proposal (not approved yet) in chat.

## Merged origin/research-streaming (2026-10-04, 43 commits, merge 6415ea6e5)
- Brings PR #91 (research slowness), #92 (brand-context load), #93, #95, #96 (VM design workspace
  root, model fallback chain grok-4.7 -> muse-spark-1.3, 120 s first-token timeout), #98 (research
  page writer, recipe 25). No migrations (head stays 10edab6dd974); manual chapters current.
- Conflicts: workspace.py + its tests — both sides fixed grep/glob on a single-file path. Took
  research-streaming's leaf naming (mount-aware `named`) and kept the integration branch's
  `_matches_workspace_glob` (recursive `**` support); kept both test sets. 94/94 pass.
- Added CLUE_ARV2_PAGE_WRITER_TIMEOUT_S=900.0 to the local .env (parity). Running stack still on
  pre-merge code until restarted.

## Written down (2026-10-04): spec + roadmap
- Spec: docs/superpowers/specs/2026-10-04-website-quality-and-code-first-lane-design.md (Ploy
  study in detail, diagnosis with evidence, decisions, target architecture, week-1 bridge, risks).
- Roadmap: docs/superpowers/plans/2026-10-04-website-quality-roadmap.md (A1 brief format +
  research offer [Head of ABM v72/manual v18], A2 design copy skills, A3 research visibility
  [read_account_research sections insights + contacts, in place], A4 typography + ad headings +
  kit repair script, A5 seller theme with type tokens, A6 dynamic capture settle, A7 Garner demo
  walk; Part B code-first lane C0 spikes -> C6 evaluation). Each workstream gets its own
  step plan before it starts.
- Rulings: demo seller = garnerhealth.com; research offer is a recommendation, no hard gate.
- New finding: the website agent reads only the account OVERVIEW page; insights page, contact
  pages, person research and a contact list are unreachable from design (Head of ABM has
  get_research_view). Dana run read the overview once (old code: truncated, no paging), never read
  claims/contacts, and never opened web-account-personalization / copy-craft / account-argument.

## Week-1 execution started (2026-10-04) — branch `website-quality/week1` off 1c5704f6a
- Rulings: A1 brief wording APPROVED as presented; develop against Conduit first (Garner optional);
  A5 composed-type mismatch goes BACK to the agent (final call pending on run time — a single page
  must not take ~1 hour); execution = I implement directly, one whole-branch reviewer at the end.
- Plan: A3 code first, then ONE Head of ABM v72 / manual v18 carrying A1 + A3 tool text.
