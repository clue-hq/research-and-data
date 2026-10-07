# Account research — why it costs ~$25 and takes ~55 minutes per account, and how to fix it

**Status:** analysis and recommendations, 2026-10-06. Nothing in the product has been changed.
Branch `shank-audit-account-research-cost-optimization` (cut from main `496956c98`).

**Evidence.** The founder's production request of 2026-10-06 (Dialpad and Loopio, each with five
buying-committee people: 12 research runs, 17:15–18:11 UTC), pulled from Langfuse project
`clue-prod`, plus a read of the code on main by five parallel reviewers, whose key claims were then
re-checked by hand. Per-call data and the full call log are local in
`.artifacts/account-research-cost-20261006/` (`CALL-LOG.md`, CSVs; gitignored). The production
database was not read (not yet approved), so Exa / AI Ark prices come from the founder's own
figures, and which code version production ran on Oct 6 is unconfirmed.

---

## 1. The answer in one page

**Yes, this is an architecture problem, not a provider problem.** Exa and AI Ark cost about
$0.06–0.16 per run and answer in 0.3–3 seconds. Almost all of the money and most of the time is
spent by our own system around them. Three structural choices cause it:

1. **The research agent uses its own conversation as its memory, and never forgets anything.**
   Everything it reads (search results, web pages, its instruction files) is pulled into the
   conversation and re-sent to the model on every one of its 40–60 calls. The conversation grows
   from ~17k to ~200k tokens. 80% of the bill is paying to re-send it. A tool that would trim it is
   installed but switched off, and the built-in compaction is set to trigger at 450k tokens, a size
   no run ever reaches. The dossier is then written inside that full ~160k-token conversation.
2. **Every evidence call does all its bookkeeping on the spot, one call at a time.** After Exa
   answers in ~2 s, our platform spends ~55 s saving, re-downloading, re-checking and indexing the
   result — about 54 storage round trips and ~300 database statements for one search — all behind
   a single lock shared by every research job on that worker. Only four calls per job can be out at
   once, and a slot is held until the bookkeeping finishes.
3. **The pipeline is a relay that writes everything several times.** People wait ~8 minutes for
   the account's dossier import they barely use; each of the five people is a full, separate agent
   costing almost as much as the account; the researcher writes a JSON dossier, a page writer
   rewrites it as prose, and the account pages are then rewritten **about three more times each**
   (six rewrites across the two accounts, run back to back) as the people finish.

On top of that, **the instructions ask for coverage, not judgement**, and the page then adds back
everything the writer left out — which is why the output reads as long and buries what matters.

**How far off plan we are.** The master plan measured the proof of concept at about $0.17 per
account, $0.07–0.13 per person and $0.05 for display copy — under $1 for an account with five
people (`docs/specs/ARV2-MASTER-PLAN.md:131-132`). Today it is ~$25: roughly 30× more. The
governed deep-agent design (since ~2026-09-23; 24 recipe versions in 12 days; 55,748 lines in
`platform/api/clue_api/arv2/`) bought accuracy and traceability, which are worth keeping, but it
pays for them on every single model call and every single evidence call.

**What it should become.** With the changes in §6 — most of them small — the same request
should come in around **$5–8 and 15–20 minutes per account** after two phases, and **$2–4 and
12–15 minutes** after the third, with tighter, more useful pages. These are estimates from the
measured token volumes and timings; each phase must be checked by re-running Dialpad and Loopio
(§7).

---

## 2. Where the money goes

| | Dialpad | Loopio |
|---|---|---|
| Total (founder's tracked figure) | $24.79 + 9.7 AI Ark credits | $25.80 + 7.7 AI Ark credits |
| Model calls (Langfuse) | $24.16 | $25.23 |
| Account run / five people | $5.37 / $19.41 | $4.24 / $21.57 |

- **People are ~80% of the bill.** Each person run costs $3.30–4.90, almost as much as an account.
- **Model price (Grok 4.6, fitted from 604 calls):** $2.00 per million new input tokens, $0.50 per
  million cached, $6.00 per million output. No long-context surcharge.
- **Cost split:** re-sending the cached conversation 80%, new input 15%, the model's own writing
  5%. Reasoning effort is ~1% of cost.
- **What fills the conversation:** about half of the model cost traces back to files the agent
  reads in and then re-sends on every later call —
  - its own saved evidence results under `/research/operations/` (383 reads, ≈$10.58),
  - fetched pages and records under `/evidence/` (345 reads, ≈$5.55),
  - its instruction (skill) files, read once per run in 2–3 chunks each (96 reads, ≈$3.53),
  - the evidence tool's catalogue `/research/capabilities/0.json` (42 reads, ≈$1.39).
- **Why the reads are so heavy:** the evidence tool returns only a file path; the agent must read
  the result file, which mostly holds IDs and paths, then read each evidence item. The files are
  served in 100-line pages as JSON inside JSON, 1.5–2.3× bigger than their content.
- **The writing phase** (from the first saved dossier section to the end) is 36% of calls but 46%
  of model cost, because it runs at ~160k tokens of context.
- **Grok's cached-input price is high for this workload.** On the same token volumes, an account
  would cost ~$9 on Muse Spark 1.3, ~$5 on Gemini 3.8 Flash or DeepSeek V4 Pro (direct), ~$1.35 on
  GPT-5.6 Luna (OpenRouter list prices, 2026-10-07). Quality is the open question: in the 09-28
  evaluation only Grok 4.6 delivered across both test accounts; Muse was ~49% cheaper but
  misattributed a person's earlier-employer work to her current role.

## 3. Why it takes ~55 minutes

Timeline for each account (both ran side by side):

```
min 0 ─ account research ─────────── min 15: picks 5 people
         … account writes + imports its dossier … min 23: people finally start
                                       min 23 ── 5 people in parallel (20–25 min each) ── min 47
         account pages: written at min ~24, then rewritten ~3 more times each ──────────── min 53–56
```

Across all 12 runs (276 run-minutes): model thinking 41% (604 calls, ~11 s each), tools 40%,
page writer 16%, gaps 3%. The tool time is almost all the evidence tool:

| Evidence operation | Calls | Avg total | Provider answers in | Our platform, before + after |
|---|---|---|---|---|
| Web search (Exa) | 104 | 69 s | 2.5 s | 21 s + 46 s |
| Page fetch (Exa) | 61 | 35 s | 0.3 s | 16 s + 19 s |
| Deep report (Exa) | 12 | 115 s | 53 s | 16 s + 46 s |
| Person lookup (AI Ark) | 10 | 86 s | 2.6 s | 50 s + 42 s |

The specific causes, each confirmed in code:

- **One lock per worker serialises every job's database work** — `_db_lock = asyncio.Lock()` on
  the research handler (`platform/api/clue_api/arv2/account_research_driver.py:504`), taken by every
  tool transaction (`:1017-1020`), shared by the ≤4 jobs on that worker. Storage uploads and
  downloads happen inside those transactions. The Oct 3 slowness fix (PR #91, on main) kept this
  lock on the assumption the work inside it had become database-only; it hasn't, and the wait is
  not measured.
- **Each search is indexed as ~25 separate sources**, each uploaded, re-downloaded and re-verified
  (`quality_evidence.py:136-238`); 89% of them are never read.
- **The four-call limit holds a slot through the bookkeeping** — the provider semaphore
  (`account_research_tools.py:500`) is released only after `_drain` (`:550`) finishes, so call 5
  waits for call 1's indexing (43 s), call 6+ waits 76 s. AI Ark is one call per job, with a 10.5 s
  pause held inside a shared lock.
- **`recover_acquisitions` runs on every call** and re-indexes sibling calls' results, which is
  why a batch of results comes back together.
- **People wait for the account import** — person release requires the account's import marker
  (`quality_person_release.py:89-92`), although across all 10 person runs the account dossier was
  opened 4 times (~3k tokens). Only the person's *page* needs the account's import.
- **The committee is chosen late** because the account prompt says to pick candidates "after
  developing the account picture" (`prompts/quality-account-research/v25/SYSTEM.md:51`).
- **The page writer is one long call** writing 12–20k tokens at ~75 tokens/s (2.5–6 min), at the
  end of every run. The plan's design was one small call per section, in parallel; a 09-26 trial of
  that took 51 s. The account pages are rewritten as people finish — six rewrites across the two
  accounts, back to back from 17:56 to 18:11, sometimes from identical input.

## 4. Why the output "blabbers" and hides what matters

Measured on Dialpad's rebuilt dossiers:

| Dossier | Findings | Seller-critical | Useful context | Filler | Filler share of words |
|---|---|---|---|---|---|
| Dialpad account | 57 | 14 | 20 | 23 | 34% |
| Contact A (SVP) | 51 | 11 | 13 | 27 | 46% |
| Contact B (ABM manager) | 36 | 8 | 3 | 25 | 51% |

Across Dialpad's five people: 223 findings, 52% biography/identity (past jobs, education,
outside-work, namesakes), 29% about the current role or recent activity. The writer must pick from
~280 findings to fill ~35 account items.

Causes, confirmed in code and prompts:

- **The page adds back everything the writer dropped.** Any finding no section cites goes, unranked
  and uncapped, into Miscellaneous (`quality_pages.py:531-571`, founder ruling 2026-09-29) —
  including duplicates and findings the writer was never shown.
- **The writer gets the researcher's doubts but not its conclusions.** Every caveat is passed as a
  "Caveat:" line (`page_writer_view.py:80-81`); the researcher's interpretation ("possible economic
  buyer after the CMO departure", "live ABM programme") is not passed at all.
- **The instructions ask for coverage.** The account prompt and skills say to be thorough, carry
  every finding that matters, cover eleven areas twice, and keep broad investigation alongside
  seller-relevant depth. The person charter asks for hometown, alma mater, pets, milestones,
  namesakes, and to "retain self-shared personal depth even when it has no obvious seller relevance".
- **Structure buries the signal.** Findings are grouped by eleven coverage areas; Dialpad's first
  seller-critical finding is #17 of 57; the why-now story (new growth leader, vacant CMO seat, ABM
  hiring) is scattered across four sections; the Overview opens with company boilerplate; the
  watch-outs appear twice.
- **No person compliance pass runs for these recipes**, so private findings are stored and can
  reach a page through the Miscellaneous dump.

The fixes for verbosity also cut cost: fewer required areas means fewer searches, reads and rounds.

## 5. Evaluation of what has been built

| Part | Verdict | Why |
|---|---|---|
| Claim store with provenance, quotes verified against sources | **Keep** | The product's differentiator; the Oct 3 review found quotes accurate |
| Idempotent launches, leased fleet, crash recovery, cost ledger, Langfuse tracing | **Keep** | Solid; made this audit possible |
| Separate page writer (recipe 25) | **Keep the idea, change the shape** | Right fix for page quality; should be per-section, parallel, written once |
| Research agent's context handling | **Fix now** | No forgetting, unreachable compaction, inflated file views, writing at peak context |
| Evidence tool's bookkeeping path | **Fix now** | Worker-wide lock, ~54 storage round trips per search, slot held through indexing |
| Account → person relay and page rewrites | **Fix now** | 8-minute gate for ~3k tokens of use; ~3 extra rewrites per account, back to back |
| Research instructions (skills, prompts) | **Rewrite for selection** | Coverage-first wording drives both blabber and cost |
| Governance on every file read, ~25 sources per search, two-step dossier → page | **Simplify** | Pays the full governance price on the hot path; most of it is never read |
| Model choice | **Test, don't switch blindly** | Grok's cached price dominates; cheaper models need a quality replay first |

## 6. The plan

Estimated effect per account with five people (today: ~$25, ~55 min to final pages):

| After | Cost | Time to final pages |
|---|---|---|
| Phase 1 — quick, low-risk changes (days) | ~$12–17 | ~35–40 min |
| Phase 2 — structural fixes (1–2 weeks) | ~$6–9 | ~15–20 min |
| Phase 3 — model and depth strategy (decisions + tests) | ~$2–4 | ~12–15 min |

Every change must pass the replay check in §7 before it ships.

### Phase 1 — quick, low-risk (S effort each)

1. **Trim stale tool results** — enable the installed `ClearToolUsesEdit` (trigger ~100k tokens,
   keep the last ~6 results, leave a placeholder naming the file path), and set a research-role
   context-window override so compaction can actually fire. Simulated on the real calls: **−38%
   model cost**. Risk: medium (the write phase relies on evidence in context) — pair with
   source-linked working notes.
2. **Fix the file views** — serve plain text, not 256-character JSON segments; return the whole
   view by default with a size cap (`quality_workspace.py:43-55,77-83`, `quality_views.py:44-56`).
   **−13–16%** and fewer paging rounds.
3. **Fewer, batched rounds** — save dossier sections in one or two rounds, fix the finalize
   refusal loop, drop the duplicated prompt (~4k tokens on every call), put the evidence
   catalogue in the tool schema. **−12–16%** combined.
4. **Release the provider slot when the provider answers** — move `_drain` outside the semaphore
   (`account_research_tools.py:500-565`); hold AI Ark's pause only around the HTTP call. **~2 min
   per run**, more in bursts.
5. **Start people at nomination** — drop the import condition for a new recipe; hold only the
   person's page until the account imports. **~8 min off every account.**
6. **Write the account pages once, after the last person; skip rewrites with unchanged input.**
   **~5–10 min earlier final pages**, fewer writer calls.
7. **Pages: stop the Miscellaneous dump for new recipes, pass the researcher's interpretation to
   the writer, put "why they fit" first, remove the duplicate watch-outs** (needs your ruling on
   the dump). Shorter, more decisive pages.
8. **Give person research its own model setting** (both share `account_research` today) so it can
   be tuned and tested separately.

### Phase 2 — structural (M effort each)

9. **Make evidence calls cost provider time + a few seconds** — remove the worker-wide lock from
   research tool transactions (bounded per-job connections; check the pgbouncer pool), cut the
   indexing round trips (verify once, pass the body through, upload in parallel), stop per-call
   `recover_acquisitions` on success (keep it on replay/settle; add the two missing indexes).
   **~58 s → ~8 s per call; ~10 min off each account.**
10. **Seller-led instructions** — person charter v26: current remit and recent statements, 2–3
    personal hooks from the person's own posts, career arc in one finding; drop hometown/pets/
    namesake sweeps. Account: a short "seller read" section first (top signals with dates, why now,
    who first, disqualifiers); other areas only when they change the approach; ask Exa for a
    compact evidence-first report. **Person dossiers roughly halve; −20–30% person-run cost.**
11. **Write the dossier from a fresh, small context** — end research with a notes file; the
    write phase starts from the prompt, the claim-ready skill and the notes, re-reading sources on
    demand. **−23–28%.**
12. **Return compact, content-bearing evidence results** — title, URL, date, short highlights and
    the evidence path, instead of a file of IDs. **~−10%** and one fewer hop per call.
13. **Choose the committee first** — AI Ark people search and the persona map in the first ~3
    minutes, so people start at ~minute 3.
14. **Page writer per section, in parallel**, on a faster setting — **~3 min off** the critical
    path.

### Phase 3 — model and depth strategy (decisions, then tests)

15. **A cheap reader for raw evidence** — a small model turns each page into verbatim quotes with
    path, employer and date; the main model only sees those notes. Grok stays the planner and
    judge, where the September errors were.
16. **Test cheaper models by replay** — page writer first (low risk), then person research on Muse
    xhigh with a wrong-employer guard; pin OpenRouter providers before any open-weight trial.
17. **Tier the committee** (product decision) — deep research on the top 2 people, a light pass
    (profile, one deep report, page) for the rest. People are ~80% of the bill.

## 7. How we will know it worked

- **Replay the same two accounts** (Dialpad, Loopio) after each phase, on fixed evidence where
  possible (the 09-28 evaluation method; `scripts/trial_page_writer.py` already replays the page
  writer for free).
- **Measure:** cost per account (Langfuse + provider ledger), time to final pages, model calls per
  run, average context, evidence-call time vs provider time.
- **Quality gate:** the seller-critical items found today (ABM/field hiring, new growth leader,
  vacant CMO seat, named marketing leaders, the contacts' own statements on personalisation and
  field marketing) must still be found and must be more prominent; no misattributed employer facts.

## 8. Decisions needed

1. Stop dumping uncited findings into Miscellaneous for new recipes (reverses the 2026-09-29
   ruling for v26+).
2. Person research depth: seller-led charter now; tiered committee (2 deep + 3 light) later.
3. Allow model experiments behind the replay gate (page writer first, then person research).
4. Account pages written once, after the people (optionally an early draft first).
5. People start at nomination now; committee-first in Phase 2.
6. A read-only production database user (Aryan), so audits like this one can read the provider
   ledger and job timings directly.

## 9. Still unverified

- Which code version production ran on Oct 6 (Langfuse carries no release tag). PR #91's fixes
  are on main; the timings are fully explained by the code as it stands.
- Exact Exa / AI Ark cost per call, live page lengths and the Miscellaneous item counts — all in
  the production database, pending read access.
- Savings figures are estimates from replaying the measured token volumes; quality effects are
  untested until §7 runs.
