# Account research v26 — the plan to make it cheap, fast and sharp

**Status:** proposal for founder decision, 2026-10-06/07. **Revision 3 (2026-10-07): independently
reviewed** — three reviewers checked it against the code (every W1–W3 item), rebuilt the cost ceiling
bottom-up from the raw call data, and attacked the depth claim against the actual Dialpad dossiers.
Their corrections are folded in below and marked **[rev]**. Founder rulings 2026-10-07:
every buying-committee contact (4–5 per account) gets the full research treatment — no light/deep
tiers; the account and all its contacts start together the moment the account is approved; what we
fetch is tightly specified. Nothing in the product has changed.
Branch `shank-audit-account-research-cost-optimization`. This supersedes the three-phase sketch in
`docs/superpowers/specs/2026-10-06-account-research-cost-and-speed-audit.md` (kept as the evidence
record; its §2–§5 measurements still stand).

**Evidence.** Every model call, tool call, tool input and tool output of the founder's production
request of 2026-10-06 (Dialpad and Loopio, each with five people: 12 research runs plus the chat
turn that launched them and the six account-page rewrites that followed), read from Langfuse
project `clue-prod`; the code on main (`496956c98`); five parallel code reviews whose claims were
re-checked by hand. Local data: `.artifacts/account-research-cost-20261006/` (gitignored). Not
read: the production database (not yet approved) — so Exa/AI Ark prices per call and which code
version production ran are still unverified.

---

## 0. What is actually wrong — the full list

The first audit said "architecture". This is the itemised version, each with evidence and what it
costs. Together they explain the whole $25 / ~55 min per account.

### A. The agent pays for everything it ever read, on every call

1. **No forgetting.** The agent's conversation grows 17k → 200k tokens over 40–60 model calls
   and is re-sent on every call; re-sending is 80% of the bill. Compaction is configured but can
   never fire (trigger = 90% of a 500k window = 450k; runs peak at 205k —
   `platform/agents/clue_agents/compaction.py:113-115`, `libs/clue-config/clue_config/settings.py:477,699`).
   LangChain's tool-result clearing (`ClearToolUsesEdit`) is installed and used nowhere.
2. **The dossier is written inside the full research context.** 36% of calls, 46% of model cost
   ($22 of $48), at ~160k tokens each (`prompts/quality-account-research/v25/SYSTEM.md:89-90`).
3. **Reading is two hops and inflated.** The evidence tool returns a receipt; the agent reads a
   results file that is mostly UUIDs and paths (JSON inside JSON), then reads each page. Pages are
   served in 256-character segments, pretty-printed and line-numbered: a 1,474-character LinkedIn
   post comes back as 2,753 characters (`quality_workspace.py:77-83`, `quality_views.py:44-56`).
4. **The Exa deep report — the one provider call that costs real money and ~50 s — is read in
   4–11 windows across as many rounds.** Reports are 52–60k characters; each run read 33–61k of
   it, 40–80 lines at a time, each window then re-sent on every later call.
5. **The opening prompt is sent twice** on every call (~4k tokens; `context.py:274-296` duplicates
   what `runtime.py:640` already put in the system message).

### B. Rounds thrown away on errors and traps

6. **27 failed dossier saves** across the 12 runs (every run had at least one; one person run
   had six). The `Finding` schema forbids extra keys and requires a nested `review` object with
   its own validators (`platform/api/clue_api/arv2/dossier_findings.py:16-47`); the model omits or
   mis-shapes it, the save is refused, and the whole round (at ~160k context, ~$0.09, ~15 s) is
   repeated.
7. **The grep → search_evidence → finalize trap.** `grep` on a results file is refused with "Use
   search_evidence with the readable source path" (`quality_workspace.py:135`); `search_evidence`
   then refuses the same path because it only accepts `/evidence/` paths
   (`quality_tools.py:358`); that failure counts as an "unresolved failed tool attempt", so
   `finalize_turn` is refused until the agent issues a `retry_of` repair. Measured: 38 refused
   greps, 9 failed `search_evidence`, **7 of 12 runs had their finish refused** and repaired at
   ~200k context.
8. **60 refused listings and searches** (`ls`/`glob`/`grep` on paths the view does not allow,
   e.g. `/research/documents` — `quality_views.py:436`).
9. **Totals:** 26 rounds in which every tool errored ($2.63), 56 more with at least one error
   ($3.85), 19 finalize-only rounds ($2.65), 9 listing-only rounds ($0.83). Roughly **$8 of $48
   (17%) and ~25 minutes of run time** are rounds that produced nothing.

### C. Media research cannot work in production, and the agents are told to pursue it

10. **Zero transcripts.** 9 `discover_media` calls, 6–7 `read_media` attempts, 17 media page
    fetches: **not one transcript.** Two attempts crashed with `FileNotFoundError: ffprobe`
    (`media_recording.py:103`) — the backend image installs no ffmpeg
    (`docker/backend/Dockerfile:44-46`), so audio can never be processed on the production
    worker. The other attempts returned `no_supported_recording_link` / `no_exact_episode_match`:
    the resolver supports YouTube, direct audio/video URLs and RSS feeds
    (`media_resolution.py:37-42,216,303-311`), not podcast-platform pages (Podcetera, Castro…).
    The Deepgram key is empty locally and absent from the deploy templates (production value
    unverified) — even with ffmpeg, transcription would stop there.
11. **The receipt says "completed" when the read failed.** The governed envelope around
    `acquire_research_evidence` reports `status: completed`; the real outcome
    (`state: unavailable`, or the ffprobe crash) is inside the body the agent must then read —
    one more round each time.
12. **The skills demand it anyway.** The person charter asks for "3–5 substantive verbatim
    quotations from long-form material: podcasts, webinars, talks"
    (`skills/person-depth-charter/v1/SKILL.md:91`); the account skill has a whole media section
    (`skills/account-dossier/v9/SKILL.md:187,254-261`). Dialpad's account run found a podcast with
    the *former* CMO and (correctly) never read it; every person run spent rounds discovering and
    failing to read recordings. The founder's instinct was right: nothing was transcribed.

### D. Our own platform, not the providers, is the slow part

13. **~58 s per evidence call; the provider takes ~2 s.** 225 calls, 217 minutes in total.
    Inside: ~20 s before dispatch, ~37–46 s after the provider answers, in saving, re-downloading,
    re-verifying and indexing the result.
14. **One lock per worker process serialises every research job's database work**
    (`account_research_driver.py:504`, used by every tool transaction at `:1017-1020`); storage
    uploads happen inside those transactions. The Oct 3 fix (PR #91) kept the lock assuming the
    work inside it was database-only; it is not, and the wait is not measured.
15. **Each search is indexed as ~25 "sources", each uploaded, re-downloaded and re-verified.**
    ~54 storage round trips and ~300 SQL statements per search, all under that lock
    (`quality_evidence.py:136-238`). **~90% of evidence files are never read:** Dialpad created
    ~964, its six runs read 89; Loopio ~994, read 113.
16. **Four provider calls per job, and a slot is held until indexing finishes**
    (`account_research_tools.py:500,550`; cap at `settings.py:459`). The 5th and 6th+ calls in a
    batch wait 43 s and 76 s on average; a batch's results return together 30–70 s after the
    providers answered. AI Ark: one call per job with a 10.5 s pause held inside a shared lock.
17. **`recover_acquisitions` runs on every evidence call** (`account_research_tools.py:~717-726`)
    and re-indexes sibling calls' results, not only on replay.

### E. The pipeline's shape multiplies all of the above

18. **People wait ~8 minutes for an import they barely use.** Person release requires the account
    dossier import (`quality_person_release.py:89-92`); across all 10 person runs that dossier was
    opened 4 times (~3k tokens). Only the person's *page* needs it.
19. **The committee is chosen at minute 15** because the prompt says to pick candidates "after
    developing the account picture" (`SYSTEM.md:51`). AI Ark title search needs no account picture.
20. **Each person is the same 40–60-round machine as the account** ($3.3–4.9 each; five people =
    ~80% of the bill). Cross-job *query* duplication is small (2 exact repeats per account); the
    duplication is structural: every person buys its own AI Ark lookup + enrichment, its own Exa
    deep report, 5–14 searches and 2–7 fetches, re-reads the skills, and re-sends its own context
    50 times.
21. **Pages are written three times.** The researcher builds a JSON dossier (at peak context);
    the page writer rewrites it as prose in one 12–20k-token call at ~75 tokens/s (2.5–6 min, at
    the end of every run); then the account pages are rewritten as each person finishes — six
    extra writer calls across the two accounts, back to back 17:56→18:11, $1.10, sometimes from
    identical input (`quality_generation.py:224-265,398-403`). Final pages landed ~55 min after
    start, not 47.
22. **The chat turn that launches research took 4 minutes** (17:11:27 → 17:15:25; 5 model calls,
    9 file reads, $0.58) before any job started.
23. **12 research slots fleet-wide** (3 batch processes × 4 jobs, `deploy/vm/compose.yaml:66-68`,
    `settings.py:456`); two accounts with five people each fill all 12. A third account queues.

### F. The output is long because the instructions ask for coverage, and the page restores what the writer cut

24. **Coverage-first instructions.** Eleven coverage areas scanned twice; "preserve every
    meaningful account observation"; for people: hometown, alma mater, pets, milestones, namesake
    inventories, "retain self-shared personal depth even when it has no obvious seller relevance"
    (`account-dossier/v9:157-204`, `claim-ready-account-dossier/v3:19-22,176-181`,
    `person-depth-charter/v1:52-75,144-160`, `person-dossier/v5:89-93,160,238`). Measured on
    Dialpad: 34% of account finding words are filler; 46–51% for its people; 52% of all person
    findings are biography/identity, 29% about the current role.
25. **The writer gets caveats, not conclusions.** Every qualification is passed as a "Caveat:"
    line; the researcher's `agent_interpretation` ("possible economic buyer after the CMO
    departure") is dropped (`page_writer_view.py:68-86`). The why-now story is scattered across
    four sections; the first seller-critical Dialpad finding is #17 of 57.
26. **The Miscellaneous dump.** Any finding no section cites is appended, unranked and uncapped,
    including duplicates and findings the writer never saw (`quality_pages.py:531-571`, ruling
    2026-09-29). No person compliance pass runs for recipes ≥6 (`quality_claims.py:587-590`,
    `quality_policy.py:10-11`), so private findings can reach a page this way.

---

## 1. What research must produce — the campaign brief

Research exists to feed direct mail, email, landing pages and ads per account × persona
(Doc S: content-schema fields draw on research fields and value-narrative sections; a *repeater*
slot picks 3–5 items ranked by confidence × persona relevance, and a mailer, an email and a
landing page for the same persona each pick a different one). So the contract is a short, typed
**campaign brief**, not a dossier — ranked and capped, never shallow: every item is backed by the
full evidence pool (§2), and the caps were set **[rev]** so that none of today's seller-critical
Dialpad findings would be dropped. Every item keeps today's provenance (value, verbatim quote or
typed value with offset, source URL, date, attribution, confidence, use-class); the claim store
and field registry stay as they are.

**Account brief (cap ≈ 45 findings, ranked within class):**

| Class | What | Cap | Feeds |
|---|---|---|---|
| Trigger | One item per dated event: leadership change (and its successor or vacancy), funding, launch, expansion, hiring surge, award, layoff; a *sequence* item must cite ≥ 2 of them | **10** | why-now, email hook, ad timing |
| Initiative / priority | What they are publicly trying to do this year, in their words | 5 | why-they-fit, landing-page headline |
| Pain / frustration | Problems they, their customers or employees name (reviews, complaints, "frustrat…" posts by their marketing staff) — **acquired by two templates that today's run lacks** | 5 | problem framing, ad copy |
| Motion & proof | How they sell/market; named customers; outcomes they claim | 5 | how-they-sell, credibility lines |
| Stack | Tools they use that matter to the seller's product | 4 | fit, technical angle |
| Committee | Who decides/champions/evaluates/blocks, with role evidence — 4–5 nominated **plus alternates and blockers** | **8** | contact selection, routing |
| Watch-outs | Disqualifiers, sensitivities, competitors in place | 3 | do-not-say, routing |
| Not found | What was searched for and not found (vacant seats, absent tools), each citing the acquisition ledger operation | 3 | honest gaps; why-now when a seat is empty |
| Firmographics | HQ, headcount, industry, founded, funding totals | fixed | programmatic slots (mail address block, stats) |

**Contact brief (cap ≈ 18 findings, every contact):** current remit and what they own (2); the
problem they are working on right now, from their posts, job postings and initiatives (3); their
own words — verbatim quotes with URL and date (**6**, so each artifact can pick a different one);
what they are proud of / recognised for, from their own or their employer's posts (2); personal
hooks usable as an opener, self-disclosed only, use-class gated (1–3); career arc in one line (1);
do-not-mention (1); identifiers for mail (title, office location).

**Dropped:** education entries, early-career roles as separate findings, namesake inventories,
hometown/pets/milestone sweeps, process narration ("AI Ark lookup failed"), recording listings
presented as evidence, anything with no plausible use in an outreach artifact. The researcher's
one-line *interpretation* is mandatory on Trigger/Initiative/Pain/Committee items and on every
contact's "problem right now", and is passed to the page writer.

This maps one-to-one onto the display sections that exist today (overview: why-they-fit, why-now,
buying-committee, how-to-approach, watch-outs; insights: buying-signals, money-and-momentum,
tools, how-they-sell; contact: why-this-person, problem-right-now, openers, angles,
do-not-mention) and onto the content plane's programmatic/dynamic/repeater slots.

---

## 2. The target pipeline (v26): everything starts at approval, in parallel

Keep the strong model for judgement; stop paying it to read, page, list and re-send. Acquisition
becomes code and runs for the account **and every contact at the same time**; follow-ups that
today's agent discovers by wandering are a **rule table executed in code** **[rev]**; extraction
is a cheap model with a throw-away context and a subject anchor; each judge is a short, bounded
loop over *all* candidates plus the acquisition ledger; pages are written once, per section, in
parallel. Nothing waits on the account dossier except the contact *pages*.

```
APPROVAL (the human confirms the account) ─► research driver starts the account job ──── t = 0
   │
   ├─ A0. COMMITTEE (first code step of the account job, ≤ 60 s — AI Ark paces at 10.5 s/call,
   │      so 5 role searches are a 52 s floor): one search per persona role (champion, economic
   │      buyer, technical evaluator, blocker, influencer), size 5 → rank by role fit + seniority
   │      + public footprint → the 4–5 contacts; their AI Ark records are kept and REUSED; contact
   │      jobs are created and released immediately (no import gate).
   │
   ├─ A1. ACQUIRE — ACCOUNT (code, one parallel batch, ~2 min)
   │      AI Ark company • ATS board • 1 Exa deep report (charter template from ICP + product;
   │      tier pinned, D8) • 8 fixed-template Exa searches with highlights (leadership, hiring,
   │      stack, news/funding, marketing/ABM programme, customers/proof, pain/resonance [rev],
   │      predecessor/successor for every ICP-relevant seat [rev]) • fetch the top-10 pages the
   │      deep report cites  → ≈ 22 provider calls
   │
   ├─ A2. ACQUIRE — EACH CONTACT (code, one parallel batch per contact, all 5 at once)
   │      AI Ark enrichment (identifiers only) • 1 Exa deep report (person charter: remit, current
   │      problem, own words, proud-of, hooks; numResults and per-result text PINNED, D9) • 6 fixed
   │      Exa searches (own LinkedIn posts, talks/interviews, articles/bylines, company mentions of
   │      them, their team's job postings, news) • fetch top-6 cited pages • media only when
   │      transcription is live (W4)  → ≈ 15 provider calls per contact
   │
   ├─ A3. GUARANTEED FOLLOW-UPS (code, table-driven, ≤ 2 rounds, ~1 min) [rev] — the FLOOR
   │      departure found → successor/vacancy query • marketing-department job listing → fetch the
   │      full posting • committee candidate → profile + last posts • stack vendor named → vendor's
   │      customer page • title found in a posting → AI Ark name search. The table is mined from
   │      every production run so far (W0), and it never replaces the agent's own follow-ups: the
   │      judge (C) can investigate further at any round, because its tools return extracted
   │      candidates, not raw pages — a follow-up costs ~$0.02, not ~$0.10 plus every later round.
   │      Evidence is pooled per account BY THE PLAN (the contact batches never re-request a URL
   │      or query the account batch already issued; /evidence already mounts per account); the
   │      schema stays job-keyed in v26.0 (the account-level operation pool is a later design note,
   │      item 18).
   │
   ▼
B. EXTRACT (cheap model; small sources batched 4 per call, large ones chunked; ~115–150 calls per
   account+5, parallel, ~1 min; instructions cached; context discarded)
   each source → candidate findings {class, finding, quote | typed value+offset, url, date,
   attribution, subject_anchor}; the quote rule (§6, AT-7) is mechanical; **no cap on candidates**;
   every contact candidate carries a subject anchor (LinkedIn slug/URL, or employer+title from the
   AI Ark record) — unanchored items can only become `unbound` hooks that are never served
   → candidates-account.json (≈ 12–20k tokens), candidates-<contact>.json (≈ 6–12k tokens each)
   │
   ├─ C-account. JUDGE + INVESTIGATE (Grok, ≤ 20 rounds, ≤ 30 follow-up operations, ≤ 60k context):
   │     seller/ICP/persona context + ALL account candidates + the people candidates [rev] + the
   │     acquisition ledger (every operation, zero-result and HTTP-failure flags). The agent keeps
   │     its full investigative loop — any search, fetch, AI Ark or ATS operation, as many hops as
   │     it judges necessary within the budget — but every operation returns EXTRACTED CANDIDATES
   │     (B runs inside the tool), never raw text. It selects, merges and ranks into the §1 brief;
   │     synthesis items cite ≥ 2 candidates; not-found items cite ledger operations; per-class
   │     minimums unmet ⇒ the mechanical gap round (AT-2) → emits the brief as the dossier JSON
   │     (schema with server defaults)
   │
   └─ C-contact ×5 (Grok, ≤ 12 rounds, ≤ 15 follow-up operations, ≤ 56k context [rev], in parallel
         with C-account): persona context + the ACCOUNT candidates filtered to Trigger/Initiative/
         Pain/Stack (so the contact is judged against the account's story without waiting for the
         account judge) + the contact's candidates + its ledger; the same investigative loop with
         candidate-returning tools → the §1 contact brief; interpretations; per-class minimums
         (own-words ≥ 2, problem-now ≥ 1) unmet ⇒ the mechanical gap round
   │
   ▼
E. PAGES (per section, parallel, written ONCE; small model, D4; each section gets a per-section
   slice of the brief, not the whole dossier)
   account overview + insights as soon as C-account finishes (~min 5); one refresh only if the
   committee section changed after the last contact; each contact page as soon as its judge
   finishes AND the account brief exists (deferred write, W1-8); no Miscellaneous dump;
   why-they-fit / why-now / problem-right-now first.
```

**What "optimised fetch" means, concretely.** Per account + 5 contacts: ≈ 22 + 5×15 + up to ~15
follow-ups = **~100–115 provider calls**, issued within the first ~3 minutes, versus today's ~230
issued one agent round at a time over 45 minutes. Searches cost ~$0.009 each (fitted on today's
runs), page fetches ~$0.004, the deep report at today's tier ≈ $0; AI Ark bills 0.5 credit per
person a role search returns, so A0 asks for 5 per role, not 10. Nothing is bought twice within
an account; AI Ark discovery records are reused instead of re-looked-up; ~90% of today's evidence
files (never read) are never *indexed* (item 19) because the extractor consumes each source once
and the agent reads none of them.

**Why depth holds — the mechanic.** Today a follow-up is expensive because of what it *returns*:
the raw page lands in the conversation and is re-sent on every later call, so a follow-up at
round 30 costs ~$0.10 and makes every round after it dearer — which is exactly why the agent
cannot afford to chase every lead. In v26 the agent makes the same move ("search for the
successor") and gets back verified candidates (a few hundred tokens), so a follow-up costs
~$0.02 and the agent can afford **more** of them, not fewer. The rule table and the per-class
minimums are a floor underneath that; the ceiling is the operation budget, not the agent's
curiosity. Depth is then checked, not hoped for: AT-9 requires the v26 judge to reproduce today's
follow-up chains on the frozen pools.

**Why fidelity holds.** Nothing is fabricated: every candidate carries a verbatim quote (or a
typed value with its source offset) that must pass the mechanical rule against the stored source;
every contact candidate is anchored to the subject; synthesis needs two sources; "not found" needs
a ledger operation; the strong model still makes every judgement; claims import through the same
`finish_dossier` → import path with the same provenance; the whole evidence pool is still acquired
and stored — the contact is researched against *all* of it, not a sample.

**Why time collapses.** Everything serial today (50 agent rounds each waiting ~58 s on an
evidence call; contacts waiting 8 min for the account import; one long page call per run; rewrites
in a chain; a 4-minute launch turn) becomes one parallel batch, parallel extraction, six short
judge loops side by side, and parallel page sections written once.

---

## 3. Numbers — today vs v26 (per account with five contacts, all deep) [rev]

Rebuilt bottom-up by an independent reviewer from the 604 measured calls and every source size in
the Dialpad run (script `scratchpad/costmodel/v26_cost_model.py`, assumptions printed with their
sources). Prices: Grok 4.6 $2.00 / $0.50 cached / $6.00 per M; Gemini 3.8 Flash $0.75 / $0.075 /
$3.75; GPT-5.6 Luna $0.20 / $0.02 / $1.20 (OpenRouter 2026-10-07). Exa fitted on today's runs:
search $0.009, contents $0.004, deep report ≈ $0 at the current tier. AI Ark ≈ $0.01 per credit.

| Extractor / page model (judge always Grok) | min | **expected** | max (before pinning D8/D9) | max after pinning |
|---|---|---|---|---|
| Luna / Luna | $1.24 | **$2.81** | $8.77 | ≈ $5 |
| Flash / Flash | $1.58 | **$4.06** | $13.09 | ≈ $6 |
| Grok everywhere | $2.17 | $6.51 | $20.98 | ≈ $9 |
| **Time to final pages** | 3.9 min | **6.6 min** | 18.7 min (no W2, no W1-11) | **≤ 10 min** with W2 + W1-11 |

Today, measured: **$25 + 9.7 credits, ~55 min.**

Expected-case stage table (Flash extraction, Flash pages):

| Stage | Expected | Arithmetic |
|---|---|---|
| A Exa | $0.69 | 55 searches × $0.009 + 40 fetches × $0.004 + 6 deep × ~$0 |
| A AI Ark | $0.10 | ≈ 10.7 credits (5 role searches × 5 people × 0.5 + company + 5 exports × 0.6) |
| B extract, account | $0.24 | 316k chars → 79k tokens of source + 146 calls × 2k instructions (80 % cached) + 173 candidates × 92 tokens |
| B extract, 5 contacts | $1.07 | ~400k chars **each** (person deep report + 20 result texts at the current 10k-char cap) — the single biggest line; D9 pins it |
| C judge, account | $0.23 (+ ≤ $0.30 at the full 20-round / 30-operation budget) | 7 rounds expected; opening context 28k; peak 45k; output 9.6k; each extra investigative round ≈ $0.03 |
| C judge, 5 contacts | $0.97 (+ ≤ $0.50 at the full 12-round / 15-operation budget) | 5 rounds each expected; opening 40k (own 12k + account slice + system 9k + persona 3k); output 5.4k |
| E pages, account (+½ refresh) | $0.15 | 11 sections × (7k in, 1.5k out) × 1.5 |
| E pages, 5 contacts | $0.30 | 30 sections × (9k in, 1.5k out) |
| Launch chat turn | $0.30 | today $0.58 / 240 s; W1-11 target one direct call |
| **Total** | **$4.06** | provider calls 113; credits 10.7 |

Expected critical path: launch 45 s → A0 62 s → A2 61 s (deep report 53 s + 8 s platform) → B
tail 21 s → C 160 s (the final 6k-token brief emit alone is ~70 s at ~88 tokens/s) → E 51 s →
**6.6 min**. Without W2 the platform overhead returns (57 s per evidence call) and the time
triples while cost barely moves.

**What is deterministic by construction** (fixed numbers in the pipeline): provider-call counts
(5 role searches; 8+6 account, 6 per contact; 6 deep reports; guaranteed follow-ups ≤ 2 rounds;
investigative operations ≤ 30 account / ≤ 15 contact), round caps 20/12, context caps 60k/56k, output caps 15k/12k, 41 page sections, the 10.5 s AI Ark gap, the
Exa `numResults` and per-result text caps, the price sheet. Because these are caps, the model
bill cannot exceed the "max after pinning" column; today's cost has no cap at all (350 rounds).

**What is measured** (today's runs): report size 52–60k chars; fetched text 1.6–7.1k chars; output
per round (median 274 tokens; dossier-writing rounds ~1.3k); cache misses (2 % of later calls);
latencies (deep report 41–87 s; search 2.5 s; platform 57 s per call today).

**What is still an estimate:** candidates per source (0.5–2 per search result, 15–50 per deep
report), extractor cache share, per-section page input, extraction concurrency, retry rates.

**The two configuration decisions that make the cost deterministic** (both are settings, not
experiments): **D9** — the per-result text cap and `numResults` on the person Exa requests
(`provider-requests/person-deep/v1/request-config.json` asks 10k chars × 20 results today; v26
pins e.g. 4k × 12) and whether the deep call's page texts are extracted at all (the report plus
search highlights carry most of the value); **D8** — the Exa deep-report tier (today's tier
costs ≈ $0; at $0.50 per report the total rises by $2.90). Pinned, the max collapses to ≈ $5–6.

What W1 alone (no restructure) is expected to give on today's v25: **~$12–17 and ~35–40 min** —
do it this week; do not stop there.

**Fleet.** Six jobs per account start at t=0; two accounts fill today's 12 slots (3 batch
processes × `CLUE_ARV2_ACCOUNT_MAX_PARALLEL_JOBS=4`, under `CLUE_FLEET_WORKER_CONCURRENCY=10`
per process — the live `/srv/clue/env` values are unverified). After W2 (lock instrumented,
pool sized, lock removed) judge loops are I/O-bound and the per-process cap can rise to 12–16
without new machines; A/B stages are not fleet jobs.

---

## 4. The work, in order [rev]

Owner split follows `docs/specs/ARV2-WORK-SPLIT.md`: **(A)** = Aryan-owned (fleet wiring,
migrations, deploy, shared `clue_agents`, profile re-mints, merges); **(L)** = leaf code, prompts,
skills an agent can build on a task branch for Shashank. Every item names its acceptance check.

### W0 — Mine every production run before building (days; no spend; (L))

Every production research run since 2026-09-28 is in Langfuse (Zafran, Mortenson, McKee Foods,
Garner, Dialpad, Loopio and their contacts). For each: the ordered operation sequence, which
operations were follow-ups on an earlier result, and which findings trace to them (the method the
depth review used on Dialpad, `.artifacts/account-research-cost-20261006/depth-review/`). Output:
(a) the follow-up rule table built from **all** accounts, not one; (b) the per-account
"nothing-lost" lists for AT-6 and the follow-up-chain lists for AT-9; (c) the frozen evidence pools
for replay. This is what makes the depth tests deterministic instead of anecdotal.

**Prerequisites the review surfaced (all (A), small):**
- **P1 Deferred contact-page write.** A contact that starts before the account import must not
  write its page until the account's import-ready reference exists; trigger the write from
  `mark_account_import_ready` (`quality_person_release.py:28-61`). Today `read_parent_dossier`
  raises (`page_writer_runtime.py:414-415`) and the job ends `needs_review`. Required by items 8,
  21, 25.
- **P2 Re-mint step.** Every (L) prompt/skill/tool-shape change (items 5, 9, 11, 12, 14, 24)
  needs new profile yaml sha pins and the pinned test fixtures (`tests/arv2/test_quality_json_dossier.py:16`).
- **P3 Pool and pgbouncer sizing** (`CLUE_DB_POOL_SIZE`/`MAX_OVERFLOW`, today 5+10 per process,
  `libs/clue-db/clue_db/engine.py:104-106`; `pgbouncer.env` on the VM) before item 15, with
  `.env.example` parity for every new flag.
- **P4 Verify the live Head-of-ABM prompt/profile pair** (profiles list v70; the prompts dir shows
  v18) before item 11.

### W1 — Stop the bleeding (this week; all small; no new architecture)

| # | Change | Where | Expected | Check |
|---|---|---|---|---|
| 1 | **Turn on tool-result clearing**: `ClearToolUsesEdit` (installed, langchain 1.3.14) with trigger ~100k, keep the last 6 tool results, `clear_tool_inputs=False` so the AI message keeps the path it read; exclude `finalize_turn` and the dossier tools; add it to the research bindings only (not Head-of-ABM); add a **per-role context-window setting** (none exists today) so compaction can act as a backstop — and record that the summariser will in practice not fire after clearing | `quality_research_wiring.py:743-752` (bindings middleware, precedes the summariser in `runtime.py:656-662`); new setting in `settings.py` + `.env.example` | −30–38% model cost on v25 (simulated on the real calls; a replay script over the stored observations is part of the item) | `tests/agents/test_compaction.py`: 7 tool messages past the trigger → the model request sees `[cleared]` on all but 6, the checkpoint keeps the originals |
| 2 | **Lenient finding schema**: `review` optional with server default **`supported` + reason "review omitted" + a marker** (NOT `insufficient_context` — that maps to `unresolved` and the page query drops the finding), allow unknown keys, return the corrected field list instead of refusing the section. (The "quote present" condition belongs to the v26 extractor; `Finding` has no quote field.) | `arv2/dossier_findings.py:16-47`, `dossier_json.py:17-40`; tool error path `quality_json_dossier.py:261-268` | removes the 27 failed saves (~$2.5, ~7 min) | update `tests/arv2/test_quality_json_dossier.py:86`; new `test_dossier_import_db.py` case: a defaulted review imports `conclusion='supported'` |
| 3 | **Close the grep/search_evidence/finalize trap**: implement `agrep` on `ResearchViewMount` over `/research/operations/<id>/` bodies; make `SearchPathEvidenceTool.invoke` return a refusal payload instead of raising (a raised error is a failed node and blocks `check_finalizable`; a returned error is not); the refusal must not set `governed_repair_budgeted` | `quality_workspace.py:131-135`, `quality_views.py:60`, `quality_tools.py:358`, `quality_evidence.py:476`; finalize check `agent_execution_wiring.py:2094-2109`; `tool_recovery.py:45-46` | removes 7 refused finishes and ~45 wasted rounds | extend `tests/arv2/test_quality_path_tools_db.py:42` |
| 4 | **Serve views as plain text, whole by default, size-capped**; stop JSON-in-JSON for operation bodies; return the deep report as one readable document (line numbers come from deepagents' filesystem middleware and stay) | `quality_workspace.py:43-55,77-83`, `quality_views.py:44-56,237` | ~half the read tokens; ~80 fewer paging rounds | `tests/arv2/test_research_read_bounds.py:10` |
| 5 | **Content-bearing receipts** from `acquire_research_evidence` (title, URL, date, highlights ≤ 600 chars, evidence path) and the **real outcome** (`unavailable`, `tool_error`) in the receipt status — a shape change, so ship as `acquire_research_evidence@2` or re-mint (P2) | `quality_provider_tools.py:69,229,315-323` | one hop fewer per call; no "completed" for failed media reads | `tests/arv2/test_quality_provider_db.py:228` |
| 6 | **Remove the duplicate L1 prompt** (the prompt body + resource map are sent again as the L1 identity message on fresh turns) | `clue_agents/context.py:275-298,900` vs `runtime.py:640` — shared, (A), affects Head-of-ABM too | −3% | `tests/agents/test_context.py` |
| 7 | **Release the provider slot when the provider answers**: split `_perform_hop` into dispatch/land so `_drain` (which includes `index_acquisition`) runs outside the semaphore; AI Ark's `sleep(min_gap)` stays inside the advisory lock (it is the cross-process gap) | `account_research_tools.py:500,550-565,672-688,470-491` | ~2 min per run; more in bursts | slow fake drain: call 5 dispatches before drain 1 ends |
| 8 | **Release contacts at nomination** for recipe ≥ 26 (a `TRUE` branch in `ready_person_jobs`; the 10 s sweep picks them up) — **requires P1** | `quality_person_release.py:89-92`; sweep `fleet_main.py:800-809` | −8 min per account | extend `tests/arv2/test_quality_person_release_db.py:103` |
| 9 | **Nominate the committee first** (AI Ark role searches in the opening round; `scope.committee_cap` unchanged) | `prompts/quality-account-research/v25/SYSTEM.md:51-52` → v26; re-mint (P2) | contacts start at minute ~2 on v25 | nominations precede the first `search_web` |
| 10 | **Account pages once after the last contact**: rewrites are already coalesced to one live + one after (`driver:980-990`, `quality_generation.py:390-410`); add "no child without `terminal_status`" to `pending_continuations` for recipe ≥ 26, and skip `publish_page` when `page_inputs().sha256` is unchanged | `quality_generation.py`, `page_writer_runtime.py:571-583` | −$1 and −6–9 min to final pages | `tests/arv2/test_page_writer_runtime_db.py:210` |
| 11 | **Launch latency**: the 9 file reads are mandated by the launch tool's description and the Head-of-ABM prompt; make the launch a direct call (prompt + tool description + re-mint); decide whether the brief stays required — **requires P4** | `account_research_launch.py:1321-1328`, `prompts/head-of-abm/…/SYSTEM.md:88-96` | −3–4 min before jobs start | launch turn < 45 s |
| 12 | **Disable media operations** by gating `discover_media`/`read_media` in `build_*_tools` on `quality_recipe_version < 26` (they are operations of `acquire_research_evidence`, not allowlist entries) and strike the media instructions from the skills | `quality_provider_tools.py:45-59`, `account_research_catalog.py:56-57`; the four skills | removes ~35 wasted provider/tool calls per request | `tests/arv2/test_quality_media_db.py` |
| 13 | **Pages: pass `agent_interpretation` to the writer; stop the Miscellaneous dump for recipe ≥ 26; why-they-fit/why-now first; drop the duplicate "Context only"** | `page_writer_view.py:68-86`, `quality_pages.py:531-571`, `display/recipes.py:110-118` | shorter, decisive pages; no private leakage via the dump | `tests/arv2/test_quality_pages_db.py` |
| 14 | **Seller-led skills (v26 prompts)**: the §1 brief with caps replaces the eleven-area sweep and the personal-depth charter; ban process narration as findings; ask Exa for a compact evidence-first report | the four skills + both `SYSTEM.md` → v26; re-mint (P2) | contact dossiers ~halve; −20–30% contact-run cost on v25 | rubric ≥ 70% A/B; AT-6 nothing-lost list |

(L) for 2–5, 9, 12–14; (A) for 1, 6–8, 10–11.

### W2 — Platform throughput: evidence calls at provider speed (1–2 weeks, (A)-heavy)

| # | Change | Where | Expected |
|---|---|---|---|
| 20 | **First: instrument the lock wait** with the existing `critical_section` around `_connection`, and size the pool (P3) | `account_research_driver.py:1017-1019`; `quality_evidence.py:248`, `dossier_import.py:453` | a number on a dashboard before anything is removed |
| 16 | Index once per batch: verify the original once per receipt and pass the body through; skip the re-read in `index_provider_artifacts` for non-AI-Ark rows; return the body from the drain instead of re-reading it; record rows first, then `gather` the uploads | `quality_evidence.py:136-238,165-167,191-194`, `quality_acquisition.py:153-155,197-271`, `committee_discovery.py:141-144`, `research_operations.py:187` | ~54 → ~27 storage calls per search, concurrent; lock-held time 8–12 s → 1–2 s |
| 17 | Drop per-call `recover_acquisitions` on the success path (keep on replay and at settle); add the two missing indexes (hash-id migration, reversible) | `account_research_tools.py:721-725`; `alembic/` | −2–10 s per batched call; O(job) not O(workspace) |
| 15 | **Then** remove the worker-wide `_db_lock` from research tool transactions (bounded per-job connections, `CLUE_ARV2_JOB_MAX_DB_CONNECTIONS`), after a lock-order review of the locks it currently hides (job `FOR NO KEY UPDATE`, generation `FOR UPDATE`, manifest `FOR UPDATE`, dossier advisory lock) and a multi-connection test fake | `account_research_driver.py:504,1017-1019,1263,793,1820,868`; `tests/arv2/test_account_research_driver.py:430` | the measured wait (item 20) goes to ~0 |
| 19 | Index the record and the report eagerly; index result text/highlights lazily on first `read_source` (keeps `replace_section`'s path check, `search_evidence`, navigation and replay working) | `quality_evidence.py`, `quality_acquisition.py`, `dossier_json.py:84-86` | most of the ~90 % never-read sources are never indexed |
| 18 | **Design note only in v26.0**: an account-level operation pool (today `arv2_research_operation` is job-keyed by `UNIQUE(workspace_id, job_id, kind, request_sha256)` and readers, erasure on privacy-stop and ledger stamping all depend on it). v26 avoids repurchases by plan (A1/A2/A3 are computed centrally per account); person lookups are never pooled | `research_operations.py:62-76`, `alembic/versions/0ab01fe27c1e…:39-57`, `account_research_tools.py:635-650` | no repurchases; schema unchanged |

Target: `acquire_research_evidence` ≈ provider time + ≤ 8 s; ~10 min off each account on v25.

### W3 — The v26 pipeline (2–4 weeks; new recipe, flag-gated per workspace; v25 untouched)

| # | Build | Where (new/changed) | Notes |
|---|---|---|---|
| 21 | **Committee at approval (A0)** as the **account job's first code step** (not in the chat launch — AI Ark pacing would block the chat turn and operations need a job row): role searches, a ranking function (none exists; `quality_committee_tool.py` nominates), then `create_job` + `register_child` + `save_person_brief` with the AI Ark record attached, released immediately (item 8 + P1) | `account_research_driver.py:1159-1180`; `quality_generation.py:185-205`; `person_research_brief.py:23-32`; `quality_person_job_id` (`account_research_launch.py:150-151`) | contacts never wait for the account run |
| 22 | **Acquisition plans in code (A1/A2)** plus the **follow-up rule table (A3)**: fixed, ICP-parameterised operation lists per subject kind issued through `ToolRuntime.operate` (keeps `arv2_research_operation` idempotency; bypasses the governed journal — recorded); table-driven follow-ups, ≤ 2 rounds, unit-tested as a pure function (AT-3) | new `arv2/acquisition_plan.py`, `arv2/followups.py`; reuse `account_research_tools.py` bodies | the judge adds nothing beyond the mechanical gap round |
| 23 | **Extractor (B)**: batched cheap-model calls, strict JSON, the §6 quote rule via the existing `substring_verdict` (`arv2/text.py:44`) plus the normaliser and typed-value branch, subject anchors, no candidate cap; model via a new `AgentRole` + `RESEARCH_EXTRACT_AGENT_MODEL` (+ parity) | new `arv2/quality_extract.py`; role in `clue_core/entity_research.py:74`, `clue_agents/contracts.py:225`, `agent_registry_wiring.py` (A) | AT-1, AT-5, AT-7 |
| 24 | **Judge + investigate loops (C)**: profiles `quality-account-research@v26` / `quality-person-research@v26` with the §1 brief as the output schema (synthesis ≥ 2 candidate ids; `not_found` cites ledger ops; `conflicts_with`, `wrong_entity`), per-role round budgets 20/12 and operation budgets 30/15 (today `Allowance` is global, `quality_research_wiring.py:1233-1238`), context caps 60k/56k; **the agent keeps the full `acquire_research_evidence` surface, but the tool runs extraction (B) on the result and returns candidates instead of a path** (the tool-result clearing of W1-1 stays as the backstop); account judge receives the people candidates; contact judge receives the class-filtered account slice; per-class minimums trigger the mechanical gap round (AT-2) | new profiles/prompts/skills; `recipe-v26.json`; `quality_provider_tools.py` receipt → candidates; wiring + settings (A) | the dossier is emitted directly — no separate write phase |
| 25 | **Per-section parallel page writer** on a small model (D4), each section fed a per-section slice of the brief; written once per subject; contact pages via P1; one account refresh only if the committee section changed | `page_writer.py:225-236`, `page_writer_runtime.py`; `scripts/trial_page_writer.py:293` for replay | the 2026-09-26 trial wrote 8 sections in 51 s |
| 26 | **Own `AgentRole` + model setting for contact research** (both profiles share `account_research` today) | roles, `<ROLE>_AGENT_MODEL`, `agent_registry_wiring.py` (A); `.env.example` | per-role tuning |

### W4 — Media: fix it or keep it off (decision D1)

To make recordings usable: install ffmpeg in `docker/backend/Dockerfile`; set `CLUE_DEEPGRAM_API_KEY`
on the worker VM; add podcast-platform → RSS/audio resolution for the common hosts; surface the
true outcome in the receipt (W1-5). Until all four are done, media stays off (W1-12). When it is
back, it is part of A2 for every contact whose searches surface a recording of *them* (not a
company recording that mentions them), and its quotes pass the same §6 rule against the transcript.

---

## 5. Sequencing and what each step buys

1. **Week 1 — W1 + P1–P4.** Expected on v25: ~$12–17 and ~35–40 min per account; zero error
   rounds; contacts start at minute ~2; pages shorter and decisive. Replay Dialpad + Loopio after
   each sub-group (1–6 context/schema; 7–11 timing; 12–14 instructions/pages).
2. **Weeks 2–3 — W2 (20 → 16 → 17 → 15 → 19) in parallel with W3 design.** Expected on v25:
   evidence calls ≈ provider + 8 s; ~10 more minutes off; six jobs per account never queue.
3. **Weeks 3–5 — W3 behind `CLUE_ARV2_RECIPE_VERSION=26` for one workspace**, with D8/D9 pinned.
   Expected: **≈ $3–4 + ~11 credits and ≈ 7 min (≤ 10) per account with five fully-researched
   contacts; hard ceiling ≈ $5–6.** v25 keeps serving other workspaces until the replay gate
   passes twice.
4. **W4 when D1 says so.**

---

## 6. The replay gate and the acceptance tests (how we know it worked) [rev]

Same two accounts (Dialpad, Loopio) after every step, on the **frozen evidence pools** captured
on 2026-10-06 (the 2026-09-28 replay method; `scripts/trial_page_writer.py` for pages). Pass
requires all of:

- **Cost** per account + five contacts (Langfuse + provider ledger) at or below the step's target;
  **time** from approval to final pages at or below target; evidence-call time vs provider time.
- **AT-1 Candidate recall.** For each of today's 43 account + 59 contact quoted spans, at least
  one extracted candidate contains it: ≥ 95 %. The extractor is uncapped; only the quote rule
  rejects.
- **AT-2 Per-class minimums trigger the gap round mechanically.** Trigger < 3, Committee < 4,
  Initiative < 1, contact own-words < 2 or problem-now < 1 ⇒ one A3+B round (code, ≤ 2 rounds).
  Test: a pool with the people sources removed must fire the committee gap round.
- **AT-3 Follow-up rule table.** `leadership_departure` ⇒ successor/vacancy query; marketing
  job listing ⇒ fetch the posting; committee candidate ⇒ profile + posts; stack vendor ⇒ customer
  page. Pure function, table-driven, unit-tested.
- **AT-4 Synthesis needs ≥ 2 paths.** The importer refuses `synthesis` with < 2 `source_paths`;
  the nothing-lost list includes the timeline / "no successor named" / combined-evidence types
  and asserts they import with ≥ 2 paths or as a ledger-cited `not_found`.
- **AT-5 Subject anchor.** Inject the known namesake sources into a contact's pool: the brief
  contains zero facts from them; unanchored candidates can only be `unbound` hooks, never served.
- **AT-6 Nothing-lost list as a committed test.** Per subject, (class, key phrase, date) tuples —
  Dialpad: ABM/field hiring, the new Head of Growth (May 2026), the vacant CMO seat since Sept
  2025 with no successor, the SVP Marketing hire (Feb 2026), named marketing leaders, the ABM
  manager's own posts on personalisation and field marketing; Loopio equivalents; for every
  contact: remit, current problem, ≥ 2 dated verbatim quotes, ≥ 1 usable hook. Each must be
  present, ranked within its class cap, quote-verified, dated, URL-cited.
- **AT-7 Quote rule.** Accept iff `normalize(quote) ⊂ normalize(source_text)` with normalize =
  NFKC, straight quotes, hyphenated dashes, collapsed whitespace, case-fold, one marked elision
  `[…]` splitting the quote into two spans of ≥ 8 words; **or** a typed value `{kind:
  number|date|money|title|location, value, source_offset}` whose offset slice contains the value.
  Regression over today's 43 spans: ≥ 41 pass (the 2 title-format cases via the typed branch).
- **AT-8 The account judge receives the people candidates**; the org-sequence finding is emitted.
- **AT-9 Follow-up recall.** On the frozen pools, for every follow-up chain mined in W0 (e.g.
  departure → successor search → "no successor" finding), the v26 judge issues an operation of the
  same kind on the same lead, or the floor table does: ≥ 90 % of chains reproduced per account.
  This is the test that proves depth is not thinner than today.
- **Zero**: failed saves, refused finishes, refused listings, media calls (until W4), repurchased
  operations within an account, misattributed employer facts.

---

## 7. Decisions needed from the founder

| # | Decision | Recommendation |
|---|---|---|
| D1 | Media: fix (ffmpeg + Deepgram key + RSS resolution) or keep off | **Off now** (W1-12); fix in W4 and switch on for every contact |
| D2 | ~~Contact depth tiers~~ — **ruled 2026-10-07: every contact gets full research; committee = 4–5** | adopted |
| D3 | Stop the Miscellaneous dump for recipe ≥ 26 (reverses 2026-09-29) | **Yes** — the main source of blabber and a privacy leak path |
| D4 | Cheap model for extraction (B) and pages (E); Grok stays the judge | **Yes**: Luna or Flash; it is the difference between $2.8–4.1 expected and $6.5 all-Grok |
| D5 | Account pages at ~minute 5, one refresh only if the committee section changes | **Yes** |
| D6 | Read-only production database user (Aryan) | **Yes** — settles the deep-report price and the live fleet values |
| D7 | Who owns the Head-of-ABM launch latency (W1-11) | assign; 4 minutes on every request |
| D8 | Exa deep-report tier, pinned per request (today's tier ≈ $0; $0.50 would add $2.90/account) | pin the current tier; never "auto"/metered |
| D9 | Person Exa request caps: per-result text and `numResults` (today 10k chars × 20), and whether the deep call's page texts are extracted | pin **4k × 12** and extract report + highlights; this is the largest single cost line and the whole gap between the $4 expected and the $13 max |
| D10 | Approve the discovered committee before the five contact researches start, or keep it automatic | automatic (faster); a gate can be added later |

---

## 8. Risks and unknowns

- **Follow-up depth.** A floor table alone would reproduce the accounts it was mined from and
  miss the next one; that is why the agent keeps its investigative loop (budgeted, with
  candidate-returning tools) and why AT-9 measures chain recall on every replay. If AT-9 fails on
  a new account, the budget rises before anything else changes.
- **Extraction recall** is guarded by AT-1 (uncapped candidates, ≥ 95 % span recall on the
  frozen pools) and the mechanical gap round; the pre-decided fallback is a stronger extractor
  (+≈ $0.3 per account), not a redesign.
- **Lenient schema (W1-2)**: the default must be `supported` + marker; `insufficient_context`
  would hide findings from pages.
- **Lock removal (W2-15)**: only after item 20 measures the wait, P3 sizes the pool, and the
  lock-order review; the Oct 3 diagnosis attributed the waits to storage and the manifest lock,
  so the gain from removing `_db_lock` is attributed, not yet measured.
- **Early contacts (W1-8) without P1** end in `needs_review`.
- **Operation pooling (18)** is a schema redesign; v26.0 avoids repurchases by plan instead.
- **Production code version** on Oct 6 and the live `/srv/clue/env` fleet values are unverified;
  Langfuse's 100 MB trace limit (one trace per launch turn aggregates all jobs) is unaddressed.
- **Fleet capacity** becomes the binding limit once runs are short: six jobs per account at t=0
  against 12 slots today; W2 raises it without new machines.
