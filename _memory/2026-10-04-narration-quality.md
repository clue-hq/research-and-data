# 2026-10-04 — Research narration quality (branch research/narration-quality, worktree nashville)

Branched from perf/research-slowness-fixes @ acd0b90bb. Goal: the account/contact display pages
must turn good research into a usable seller brief. No code changed yet; decisions pending (below).

## Evidence (first production run, two accounts called A and B here — see 2026-10-03-first-production-research-quality-review.md)
Research accuracy is high (quotes verified against sources); the pages are not: caveats on almost
every item, no joined-up account story, openers that never bridge to the client's offer, bloated
Miscellaneous (namesakes, 1990s jobs, financial disclosures), repeated facts, mis-pointed citations.

## Causes found in the production writing guidance
Skills used by account profile v24 / person v24-person:
`platform/agents/catalog/research-quality/skills/account-research-narrative/v2`,
`research-narrative-editorial/v1`, `person-research-narrative/v2`.
- Guidance is dominated by anti-overclaiming rules; every "Better" example ends on a disclaimer
  ("does not establish…"), and a rule requires a date + freshness caveat beside every older signal
  in every section.
- No synthesis step: sections are written independently; the account pages were written at 16:11
  before person research finished (16:05–18:20), so person-level findings (a committee member's own statements about the
  problem and a team change) never reached the account story.
- Person guide makes hobbies/interests prominent, requires a "genuinely personal" opener and says
  not to force a product connection → food-bank / sabbatical / intern-comment openers.
- Miscellaneous rule: "every residual substantive finding needs a visible home"; wrong-entity
  records must be shown as excluded associations.
- The research agent writes pages at the end of a 40–70-call run (~176k-token context) under ~600
  lines of rules; the typed sentence schema (per-sentence qualifications) invites hedging.
- No check that a sentence's cited claim supports it.

## Proposed changes (awaiting founder decisions)
1. "Short version" account story first (4–6 sentences joining the 3–4 strongest facts across
   account + people); sections derive from it.
2. Caveat budget: only when it changes what the rep does; dates inline; the rest once in Watch-outs;
   rewrite examples to end on an action/question.
3. Every item ends with a "so what" for the rep; openers = hook → client-offer link → question;
   personal openers optional, never the lead.
4. Client offer → signal map per project (from pinned ICP/product context) so the writer recognises
   e.g. travelling workforce / navigator history / benefits-leader change as top signals.
5. Rewrite account pages after person research settles (at least a mandatory story refresh).
6. Separate writer with a small context instead of the researcher writing its own pages — reverses
   the 2026-09-27 researcher-owned-narrative ruling (`_memory/2026-09-27-researcher-owned-narrative.md`).
7. Miscellaneous = usable leftovers only; namesake/identity notes stay in the research record;
   Do-not-mention = things a rep could plausibly get wrong.
8. Mechanical citation check: a quote in a sentence must appear in a claim it cites.
9. One home per fact; other sections refer back.
10. Rubric + accounts A and B as test pages; iterate with narrative-only refreshes from existing
    dossiers (~$1 of writing each, no new research spend).

Decisions asked: (1) who writes (researcher vs separate writer); (2) where the short version lives
(new Overview section needs a frontend slot — founder ruling — or inside What they do / Why they fit);
(3) must every opener link to the offer; (4) the reader (rep preparing first outreach?).
Parked by founder 2026-10-04: removing sensitive data already in production and stopping its
collection; the account-sidebar headcount (3958) mismatch.
Skill content needs founder review before it is written/merged; write it plainly, not compressed.

## Founder decisions, 2026-10-04 (later)
- Seller brief must also say what the research is for: helping the seller win the target as a client
  (seller-agnostic). Separate writer approved provided context transfer and output quality hold.
  Short story lives in the existing Overview opening (why-they-fit intro). Openers/reader rulings not
  given — working assumption: rep preparing first outreach; openers tie to the offer.
- **No code that counts words/lines/items in agent prose** (memory `no-code-length-limits-on-agent-prose`).
  Code checks correctness only: refs resolve, quotes appear in cited findings, sections present,
  private topics absent, send_line only in openers. One repair attempt on a failed check.

## Trial iterations (writer only, saved production inputs, Grok 4.6 medium via OpenRouter)
Inputs exported read-only from production into the session scratchpad (customer data, not in repo).
Harness `scripts/trial_page_writer.py`; view `platform/api/clue_api/arv2/page_writer_view.py`;
guides `skills/{seller-brief,research-page-writing,account-pages,contact-page}/v1`.
- Seller brief: 27.6k prompt tokens, 35 s, $0.07; strong (signal map, exact ICP gates, proof with
  sources, buyer roles, gaps incl. missing persona doc).
- Production baseline (same metrics): account A Overview 1,028 words / 8 caveat sentences; every page
  had 1–4 private-topic mentions.
- it1: story present and correct (the workforce, a documented problem, a recent change in the owning
  team, and the committee member with directly relevant history → lead with them); 0 ref/quote errors; but Overview 1,458 words,
  repetition, one outside-knowledge fact (a vendor's parent company added from general knowledge), send_line on an account
  section, private topics surfaced as warnings in do-not-mention.
- it2: word targets in prose ignored (Overview 1,566); one contact page truncated (no repair yet).
- it3: per-section item guidance + repair loop + private-topic rule: Insights 1,229→703 words,
  contacts 700–1,060, 0 private mentions, 1–5 caveat sentences/page; the code length check never fired
  (prompt alone shortened pages) → code length checks then removed by founder ruling. Account B generalises
  (the story found its own fit evidence and a recent leadership change); flaws: a person with an unverified
  identity as first call, seller proof cited to target findings.
- Cost per account with 5 contacts ≈ $0.8–0.9; account call 3.5–5 min, contact calls 2–4 min (parallel).
- it4 (limits softened to "usual shape … go past when it earns its place") and it5 (limits stated
  firmly, no code check): no item-count breaches in any iteration; length differences come from
  sentences per item (up to 6 vs guidance 3) and run-to-run variance (account A Overview 1,255 /
  1,295 / 1,499 words across it3–it5). Prompt wording is no longer the length lever; the qualitative
  gains (story, 0 ref/quote errors, ~0 private topics, few caveats) are stable across 5 iterations
  and both accounts. Next levers if length matters: fewer allowed items, or a different writing model
  (env setting, founder's call).
- Comparison page (local, customer data): scratchpad `narr/narration-before-after.html`, built by
  `narr/compare.py LABEL OUT`.
- **Founder ruling (2026-10-04): ~1,500 words per page is acceptable when it carries valuable signals
  and much better narration.** Stop optimising for length; judge substance.
- Trial mechanics (for the record): each page set = ONE plain chat completion (no tools, no agent
  loop) returning JSON, plus at most one repair call when deterministic checks fail; direct
  OpenRouter calls, so not in Langfuse (production must go through the gateway with tracing/spend).

## Build into the pipeline (2026-10-04, plan docs/superpowers/plans/2026-10-04-separate-page-writer.md)

- Recipe 25 (catalog v25) is the cutover: the researcher only researches (no page tools, no
  narrative skills, prompts say a separate writer writes pages). Recipes < 25 unchanged.
- `page_writer.py` (guides, checks, repair, reference mapping) + `page_writer_view.py` (what the
  model reads) + `page_writer_runtime.py` (durable inputs, seller brief cached per context pin and
  guide hash as artifact `research_seller_brief`, provider call through ProviderCaller with the job's
  LedgerStamp + Langfuse, publish via `publish_page` under the writer's own execution row; reply
  retained as `research_page_writer`, subject-bound for erasure).
- Driver: after the quality runner and before settling, a completed recipe-25 job's pages are
  written (`_write_pages`); failure or uncomposed writer → `needs_review`. The account continuation
  for recipe 25 is a full rewrite (`_rewrite_account` → `rewrite_account_pages`), publish +
  generation settlement in one transaction under the work lease; failure settles `needs_review`.
  People = committee members (not excluded) plus any other person job of the run.
- Completion's missing-pages refusal applies to recipes 20–24 only (`quality_policy`).
- Env: `CLUE_ARV2_PAGE_WRITER_TIMEOUT_S=900.0`; model = `RESEARCH_NARRATIVE_AGENT_MODEL`/`_EFFORT`
  (fallback `arv2_display_model`).
- Rulings: the rewrite bypasses the alias-based reconciliation packet (writer already reads every
  dossier; cost if wrong: no `arv2_narrative_reconciliation` history for v25 generations); a
  transient DB error during rewrite settles needs_review instead of requeueing (cost: a rewrite
  must be re-triggered by hand).
- Founder ruling (2026-10-04): instructions/references must not be tied to a dev example. Writer
  guides now use neutral examples; tests/docs/script carry no trial names. Commit 5df15a3fc (local,
  unpushed) still contains two place names in an old harness regex — history purge is the founder's
  decision.
- Verification: throwaway DB `clue_nashville_sdd` on the local Postgres. Run DB suites with ONLY
  `CLUE_DATABASE_URL` exported (sourcing all of `.env` turns feature flags on and breaks
  flag-default tests, and loads paid keys).

## Local acceptance run (2026-10-04, after merging research-streaming)

- Setup: `clue_nashville` (copy of clue_addis-ababa, migrated to 4a94970221e9) on :55040; R2 bucket
  `clue-dev-bench` (values from dushanbe .env); untracked `scripts/dev_stack_nashville.sh` on
  3060/8061/8062/8063, 4×3 workers; Langfuse env `lane-nashville`; uploaded 5,022 referenced
  artifacts from addis-ababa/.artifacts to R2 (2,340 missing ones were all ws_test_* leftovers).
- Recipe-25 account research for one target account (via Head of ABM chat): researcher used no page
  tools; driver page writer published Overview + Insights (11 sections, one repair, ~$0.25 incl.
  repair) in ~4.5 min; job completed with no missing pages; the frontend Overview opens with the
  short story (fit, why now, who first, lead) and the neutral ICP-check wording.
- Fixed during the run: agent grep on a single-file path (0bd58855f); rewrite skipped when the
  account's own dossier never imported (a0014e7e9) — the first, failed job had been rewritten
  into a gaps-only page.
- Found (task chips, not this branch): (1) agent model calls have no wall-clock deadline —
  OpenRouter keep-alives defeat the 60 s read timeout; a provider 504 after 5.3 min × 3 attempts
  held a job 17.5 min, then it failed as opaque `value_error`. (2) lease-loss cascade: redelivered
  task marks itself done while the job is in_progress → original holder suspends → orphan with no
  task; a requeued job can't save its dossier (execution already terminal); a transient storage
  error during recovery fails the job outright. Trigger here was the laptop sleeping / Wi-Fi drop
  (founder), so lower priority, but the same holes exist on any worker pause.
- Owed: contact pages + the post-people account rewrite were not verified live — the person jobs
  were broken by the sleep cascade. Needs one clean person-research pass.
- Person pass (founder relaunched via Head of ABM, run started 09:53 UTC, independent person research):
  all five researched fine on the latest workers. Two more fixes landed from it: the
  `/research/generation.json` view crashed with MultipleResultsFound when one run held several
  independent-person generations (02b1ba36e), and contact pages for people with no parent
  account job could not find the account dossier (d34d6edb3, now: newest completed account
  dossier for the same account/project/context). The five in-process writes failed on the
  pre-fix workers; the contact pages were then written by one call per job to the production
  `write_job_pages` (real model, job-billed): 5/5 published first attempt, 1,200–1,430 words,
  1–2 caveat sentences, 0 private topics, 0 uncited facts, 2–3 openers each with send lines.
- Ruling owed (founder): independent person research does not trigger the account rewrite (the
  people are not children of the account's generation), so the Overview does not absorb their
  findings. Options: have the person launch register as children of the account's latest
  generation, or accept it.
- Leftover: run 2ad0307c has two orphaned in_progress person jobs from the crash (harmless).
- Founder ruling (2026-10-04): independent person launches attach to the account's research.
  Done (116c4e334): `quality_generation.attach_to_account_research` (newest generation for the
  same account/project/context whose account job is recipe 25+; containment-checked; register_child
  stays same-run only) called by `launch_arv2_person_research`; the driver's settle also calls
  `record_child_result` for an independent person; `committee_people` includes attached people from
  any run. Full arv2 suite 1,626 passed / 5 skipped / 0 failed. Live proof owed: the test account's people
  of run 2f48ed02 were launched before this change and are not attached.
- Live proof of the attach + rewrite (2026-10-04 16:15 IST): the account generation's two orphaned
  children (sleep cascade) were settled needs_review by hand (`orphaned_after_lease_loss`), today's
  five independent people were attached with `attach_to_account_research`, and the fleet sweep
  recorded their results and offered the continuation by itself. The recipe-25 rewrite published
  Overview + Insights (11 sections, 1 attempt, $0.26, ~260 s); 10/11 sections now cite person
  claims (buying committee 12), and the story absorbed a person-only finding (the CEO's 2023
  statement that an AI bot already handled routine guest calls) → the pitch reframed to "finish
  what the existing bot can't". Generation state `partial` (some earlier children needs_review).
