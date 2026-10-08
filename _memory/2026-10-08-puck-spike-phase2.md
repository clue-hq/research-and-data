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
- Next: T8 findings doc + production roadmap.

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
