# Puck spike phase 2 (agent on Puck) — branch spike/puck-phase1, trenton lane

Plan: docs/superpowers/plans/2026-10-07-puck-spike-phase2-agent.md. Code: trials/puck-spike/agent/.

## Done
- T1 (e253b7b73) schemas + catalog; T2 (ee2c8e934) validate/render/fetch/search/restore tools.
- T3 prompt + skills (3c2f3dffd): founder-approved 2026-10-07. Rulings: Syracuse worked example
  dropped from the copy skill (case A is Syracuse); build-skill example made up (Northwind/Lakeside);
  "one dark brand section" exception dropped (founder: drop it).
- T3 runner (2026-10-08): run_agent.py, cases.json, briefs/atrium.md (case C test brief),
  trials_puck_agent/{workspace,harness}.py. 26 Python tests + 12 TS tests green, all offline
  (scripted fake model). One live check (0.2 cents): grok-4.6 through our gateway sees an image
  inside a tool result; gateway cost lands on response_metadata["clue_cost_cents"].
- Harness rulings: create_agent + deepagents middleware (as the platform's scene solo graph), no
  subagent/todo/base prompt/summarization; ordered tool calls (proven needed by a failing test);
  finish guard; 40-call safety stop; builds start with no page.json/shell.json (write_file refuses
  to overwrite). Fixed prompt ~3.4k tokens vs ~52k platform.
- Dry assembly of all three cases from the lane DB (reads only): A 12 research blocks, 4 people,
  15 seller files, 21 clones; B 12 blocks, 3 people, 16 files, 29 clones; C research refused
  (insights_not_written; overview read separately now), 0 people.

## Founder ruling 2026-10-08 (before T4)
- Judgement is the agent's, not the validator's: numbers-in-evidence, named-people and
  notes-wording checks removed from validate_page (rules stay in prompt/skills); one destination
  stays blocking for now. people.json dropped. Runner now prints a live trace (trace.log).

## T4 run a1 (case A, 2026-10-08)
- completed: 19 calls, $0.82, 303 s, 2 renders, 0 validation errors (valid first try), 4 small
  edit_file fixes. Same clones as my hand picks. Misses: Nightingale as proof (conditions omitted),
  no web_search for seller-site proof (Aon never found), brand sections for proof/offer without a
  recorded reason, read 18/21 clone cards + fetched privacy/terms pages.
- Harness fixes after a1 (founder go): screenshots keep width (desktop 720 wide, mobile 375, tiles
  <=1600 px; a1's mobile reached the model ~132 px wide); context clearing off by default
  (--clear-renders) after a1's last call lost the whole cache ($0.16 of $0.82); brand.md titled
  from cases.json "seller" (Garner's kit is stored as "Doctor Quality Analytics" — platform
  ingestion defect); read_file without a limit reads up to 1000 lines; trace shows glob/grep
  patterns.

## T4 runs b1, c1 (after the harness fixes)
- b1 (Conduit x Dana.AI): completed, 17 calls, $0.69, 285 s, 2 renders, 0 invalid. Seller-site proof
  (fetched Wynwood House), recorded why brand sections, left out unverified "300+ brands". Review
  caught mobile button wrap + repeated channel copy; hero orphan "Dana.AI." still open after the one
  allowed re-render (reported honestly).
- c1 (Conduit x Atrium, thin research): completed, 16 calls, $0.57, 219 s, 2 renders, 0 invalid.
  Honest name-only page; dropped the 838 headcount (brief over research); Lauderdale Hotel proof,
  dropped the conditional $500k figure; 3 of 4 sections are clones. Search without include_domains.
  Missed: empty gap before the closing clone, closing band touching the footer.
- No late cache miss with clearing off (b1, c1). Zero Puck/validation mistakes across a1, b1, c1.
- Open founder decisions: render cap (one re-render vs until review passes, up to N); Nightingale as
  a failing case for the proof rule; multi-page workspace + route-existence check + shell nav
  before E2; A2 (variance) and E2 not yet run.

## a2, multi-page, a3/E2 (2026-10-08)
- a2: $0.63, 16 calls, valid first time; same page as a1 incl. Nightingale proof (consistent).
- Multi-page built (83d3bd94c) + founder-approved prompt/skill text (9f0af2f9f); clone renderer now
  absolutizes captured links the page did not change (they were broken on our pages).
- a3 (build + 10 edits, one session): build $0.62 (same page as a2, word-for-word headline); edits
  $6.03 total (avg $0.60, ~7 min each) vs bar $0.05/1 min; 7 exact, 2 partial (4 side change, 10
  removed earlier work), 1 fail (7 added a section for cards that did not exist, brought back the
  hidden logo row). 0 invalid in 79 calls. Context grew 83k->214k; one cache miss cost $0.83.
  Details in trials/puck-spike/ISSUES.md 24-30. Next to test: fresh session per edit.

## E2b (fresh session per edit, after the lean-harness pass)
- $2.73 for 10 edits ($0.27 avg, 2.7 min) vs a3 $6.03 ($0.60, 7 min); 8 exact/sound, 2 partial, 0
  fail; edit-7 rule works. Clearing caused full cache misses after each boundary ($0.76 of $2.73)
  -> propose clearing only above ~60k tokens. ISSUES.md 31-34. E5 code written, shared-file part
  pending (announced to founder).

## Efficiency fixes + E5 (2026-10-08)
- Founder: clearing only above 60k tokens; compaction at 300k (keep 60k); skills in the system prompt
  (fixed prompt ~6.7k tokens); plan.md upkeep and site.md left as they are. Commit 2c51366da.
- E5 (73fa923d3 code): write_section + check-section.ts + agent-kit; agent wrote AnalysisSteps, passed
  first time, on brand next to clones; 13 calls, $0.35. ISSUES.md 35-37. puck/agent-sections/index.ts
  is modified by the run (left uncommitted so the agent-e5 page still renders; restore before commits).
- E5b (trimmed skill, contract in words, brand/theme.css + brand/agent-kit.tsx read-only, 9d42c3a55):
  props still flat (founder's overspecification hypothesis not confirmed); lost brand-heading and
  Shell-spacing conventions the example carried (heading near-black, double padding). ISSUES 38-40.
- Next: decide reference fixes / E5c, then T8 findings doc + production roadmap.

## JavaScript-heavy capture (founder: note it, come back and test heavily)
- Notes: docs/superpowers/specs/2026-10-08-capturing-javascript-heavy-sites-notes.md. Root cause:
  capture saves one moment (scroll to bottom, back to top, serialize); altcarbon.com builds content
  client-side tied to scroll. Recommendation: record/replay their JS in a sandbox at capture time,
  save each section in view, ship our own (frozen clone / clone + vetted runtime / rebuilt
  component / labelled still), gate by fidelity. First experiment: 3-4 day capture prototype, no
  model spend.
- Alt Carbon prep parked (7bf25b37e); kit rules in brand.md kept as proposed/kit-rules-in-brand-md.patch.
  Spike export ignores the platform's `degraded` flag (Alt Carbon hero: dead_height) — fix when we
  return to Alt Carbon.

## Known limits

## Next
- T4 E1 builds (A twice, B, C) — waiting on founder go (spend ~$1 per page expected).

## Component library spike (2026-10-08 evening)
- Tools view_clone + compare_section (0a8ff4ae3), run setup e798fb329 (rebuilding-a-section skill,
  kit.Image fit="fill", bg-surface panels rule, finish guard skips sites with no page.json,
  run_agent --no-build). Run cl3 (5 Garner clone rebuilds + Syracuse page): $3.66, 107 calls,
  58 min; stopped runs cl1/cl2 $0.67. Results in ISSUES.md 44-53; page at /s/agent-cl3.
- Two harness bugs found mid-run and fixed: write_section's type check was a no-op (300af574a);
  Tailwind skipped git-ignored agent sections (b1f3ab458; puck/agent-sections/<site>/ is no longer
  ignored: never commit those folders, nor the regenerated index.ts).
- Founder ruling: the spike's partial brand kit is fine; production must expose every type role,
  measure more roles, cover band surfaces (recorded in the roadmap's phase 1).
- Capture prototype (subagent, worktree-agent-a8b9a099e34d9774a) + cluehq.ai run + reduced-motion
  probe: reduced-motion second load fixes cluehq.ai fully; Alt Carbon ships a poster under its canvas
  and a mobile hero (already in the clone); its only gap is the 305vh wrapper. Not yet written into
  the capture notes/roadmap (offered to founder).

## Integration plan (2026-10-09)
- Readiness map `docs/superpowers/specs/2026-10-08-puck-production-readiness-map.md` (corrected twice:
  inline editing is native in Puck 0.23 and proven in phase 1; inline text, asset library, versions
  and reorder handles are already designed; only the insert palette and delete/duplicate need designs).
- Founder rulings 2026-10-09: option A for agent-written sections (no iframes; strict presentational
  check; compiled per workspace; loaded at runtime into Puck's config); one Node renderer; per-workspace
  flag; Head of ABM unchanged (doc_kind="web" births a site for listed workspaces).
- Plan `docs/superpowers/plans/2026-10-09-website-agent-on-puck-integration.md`: Wave 1 detailed
  (site-kit package, site kind migration + DAL, site birth behind CLUE_DESIGN_SITE_ENGINE_WORKSPACES
  failing closed until the site executor, D2 runtime-loading spike, R1/R3 experiments); Lanes A/B/C
  outlined against cited switch points (design_leg_tools.py:540/1002, documents.py:188/595,
  design_leg_wiring.py:2568, fleet_handler.py:213/679, artifact-stage.tsx:471, publishes.py:94).
  Not yet executed; founder to pick the execution method.

## D2 decided (2026-10-09)
- Task 4 spike (412193a51): runtime loading works, but option A gives no containment — Puck mounts
  components via createPortal, so section code runs in the editor window with the marketer's session;
  4 hostile probes passed the lint. React's server render passes <script>, raw onerror (via a split
  dangerouslySetInnerHTML key) and outside images into "static" HTML (tested; no sanitizer exists yet).
- Research (8 researchers incl. engineering blogs): every AI/code-first builder runs generated code on
  a separate origin, one boundary per surface (Framer framercanvas.com, Figma figma.site, v0, Lovable,
  Claude, Canva, Google usercontent.goog, MCP Apps). Per-section frames only where distrusting authors
  share a page. Ploy (ploy.ai, Bryant Chou): Astro/React repo in a cloud sandbox, sandboxed builds,
  static on Cloudflare, no CSP, preview origin not public. Report:
  docs/superpowers/specs/2026-10-09-code-first-builder-isolation-research.md (its per-section
  recommendation NOT adopted).
- Founder decision: separate-domain editor — whole Puck editor on its own domain (no login), one frame
  in app.cluehq.ai, message bridge; locked render container; publish sanitizer + published-page CSP.
  Small latency explicitly accepted ("not streaming trading data"); no measurement spike.
- Recorded in readiness map §5/§6/§7/§8/§9 and the plan (new "D2" section, Review focus 6–7, A5, A7,
  B6, C1, C9, new C11; Lane C now 3–4 weeks; total 10.5–12 eng-weeks).
- Open: one shared editor domain vs one per workspace (C11); published pages default to
  *.pages.cluehq.ai, same registrable domain as the app — research recommends a distinct one (A7,
  founder decision). R1 question to founder still unanswered; Task 5 not started.
