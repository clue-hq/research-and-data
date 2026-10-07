# Account research v26 — the plan to make it cheap, fast and sharp

**Status:** proposal for founder decision, 2026-10-06/07. Nothing in the product has changed.
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
(Doc S: content-schema fields draw on research fields and value-narrative sections). So the
contract is a short, typed **campaign brief**, not a dossier. Every item keeps today's provenance
(value, verbatim quote, source URL, date, attribution, confidence, use-class) — the claim store
and field registry stay as they are; what changes is *which* findings and *how many*.

**Account brief (cap ≈ 30 findings, ranked):**

| Class | What | Cap | Feeds |
|---|---|---|---|
| Trigger | Dated events: leadership change, funding, launch, expansion, hiring surge, award, layoff | 6 | why-now, email hook, ad timing |
| Initiative / priority | What they are publicly trying to do this year (in their words) | 5 | why-they-fit, landing-page headline |
| Pain / frustration | Problems they or their customers/employees name (resonance) | 5 | problem framing, ad copy |
| Motion & proof | How they sell/market; named customers; outcomes they claim | 5 | how-they-sell, credibility lines |
| Stack | Tools they use that matter to the seller's product | 4 | fit, technical angle |
| Committee | Who decides/champions/evaluates/blocks, with role evidence | 5 | contact selection |
| Watch-outs | Disqualifiers, sensitivities, competitors in place | 3 | do-not-say, routing |
| Firmographics | HQ, headcount, industry, founded, funding totals | fixed | programmatic slots (mail address block, stats) |

**Contact brief (cap ≈ 10 findings):** current remit and what they own (2); problem right now,
from their posts/jobs/initiatives (2); their own words — verbatim quotes with URL and date (2–3);
personal hooks usable as an opener, self-disclosed only, use-class gated (1–3); career arc in one
line (1); do-not-mention (1); identifiers for mail (title, office location).

**Dropped:** education entries, early-career roles as separate findings, namesake inventories,
hometown/pets/milestone sweeps, process narration ("AI Ark lookup failed"), recording listings
presented as evidence, anything with no plausible use in an outreach artifact. The researcher's
one-line *interpretation* becomes mandatory on Trigger/Initiative/Pain/Committee items and is
passed to the page writer.

This maps one-to-one onto the display sections that exist today (overview: why-they-fit, why-now,
buying-committee, how-to-approach, watch-outs; insights: buying-signals, money-and-momentum,
tools, how-they-sell; contact: why-this-person, problem-right-now, openers, angles,
do-not-mention) and onto the content plane's programmatic/dynamic slots.

---

## 2. The target pipeline (v26)

Keep the strong model for judgement; stop paying it to read, page, list and re-send. Acquisition
becomes code; extraction becomes a cheap model with a throw-away context; the agent judges a
compact candidate set in a bounded loop and writes the brief directly; pages are written once,
per section, in parallel.

```
Head-of-ABM launch (today 4 min → see W1-10)
   │
   ▼
A. ACQUIRE (code, parallel, ~2 min)           per account, at minute 0
   AI Ark company • ATS board • Exa deep report (fixed charter template from ICP+product)
   • 6 fixed-template Exa searches (leadership, hiring, stack, news/funding, ABM/marketing,
     customers/proof) with highlights • fetch top-K pages the deep report cites
   • AI Ark people search per persona role  ◄── committee candidates at minute ~1, not 15
   → raw bodies stored as today; indexed ONCE per batch; the agent never reads raw bodies
   │
   ▼
B. EXTRACT (cheap model, one call per source, parallel, ~1 min, context discarded)
   each source → typed candidate findings {class, finding, verbatim quote, url, date,
   attribution, subject}; quote must be a substring of the source (mechanical check,
   the same rule media quotes already obey) → candidates.json (≈ 10–20k tokens per account)
   │
   ▼
C. JUDGE + PLAN GAPS (Grok, ≤ 10 rounds, ≤ 60k context)
   input: seller/ICP/persona context + candidates.json (no raw sources)
   round 1: nominate the committee from AI Ark candidates + evidence  ──► person jobs start
   rounds 2–9: select/merge/rank into the brief; write interpretations; name ≤ 6 gap queries
              → one bounded A+B pass for the gaps
   last round: emit the brief as the dossier JSON (lenient schema; server fills defaults)
   │
   ├──► D. PEOPLE (from minute ~4, parallel): top-2 "deep" = A(person) + B + C(≤ 8 rounds, with
   │        one gap pass); others "light" = A + B + C(≤ 4 rounds, no gap pass). Media only if
   │        transcription is actually available (W4).
   ▼
E. PAGES (written ONCE per subject; per section; parallel; small model or Grok low effort)
   contact pages when the person finishes; account pages after the last person (one early
   draft optional); no Miscellaneous dump; why-they-fit / why-now first.
```

**Why fidelity holds.** Nothing is fabricated: every candidate finding carries a verbatim quote
that must appear in the stored source, with its path; the strong model still makes every
judgement (what matters, who is on the committee, what it means); claims are imported through the
same `finish_dossier` → import path with the same provenance. What goes away is the model reading
raw pages 40 lines at a time and carrying them for 50 calls.

**Why time collapses.** The slow things today are serial: 50 model calls each waiting on ~58 s
evidence calls, people waiting for the account import, one long page call per run, rewrites in a
chain. In v26 acquisition is one parallel batch, extraction is parallel, the judge loop is short,
people start at minute ~4, and pages are parallel and written once.

---

## 3. Numbers — today vs v26 (per account with five people)

Assumptions are explicit; everything must be re-measured by replay (§6). Prices: Grok 4.6
$2.00 / $0.50 cached / $6.00 per M; Gemini 3.8 Flash $0.75 / $0.075 / $3.75; GPT-5.6 Luna $0.20 /
$0.02 / $1.20 (OpenRouter, 2026-10-07).

| Stage | Today | v26 (estimate) | Arithmetic |
|---|---|---|---|
| Account research agent | $5.0, 30 min, 56–59 calls, avg 117–135k ctx | **$0.45, ~4 min**, ≤10 calls, avg ~45k ctx | cached 10×45k×$0.5/M = $0.23; new ~60k×$2/M = $0.12; out ~15k×$6/M = $0.09 |
| Account extraction (B) | — (the agent read it) | **$0.04–0.12**, ~1 min | ~330k chars ≈ 85k tok in, ~15k out: Luna $0.035 / Flash $0.12 |
| Account pages | $0.20 + $1.10 of rewrites, 5.5 min + chain | **$0.05–0.17**, ~1 min, once | 11 sections × (3k in + 1.5k out) |
| Person, deep (×2) | $3.3–4.9, 20–25 min each | **~$0.40, ~5 min** each | B $0.05 + C 7×30k cached $0.11 + new $0.08 + out $0.06 + page $0.09 |
| Person, light (×3) | same as deep | **~$0.20, ~3 min** each | 4 rounds, no gap pass |
| Providers (Exa, AI Ark) | ~$0.1–0.2 + AI Ark credits per account | about the same (fewer searches per person, one deep report each) | unchanged class of spend |
| **Total model** | **~$24** | **≈ $2.0–2.4** | 0.45+0.12+0.17 + 2×0.40 + 3×0.20 |
| **Total incl. providers** | **~$25 + 9 credits** | **≈ $3–4 + credits** | |
| **Time to final pages** | **~55 min** (+4 min launch) | **≈ 12–14 min** | A 2–3 → B 1 → C 3–4 (people start at ~4) → people 5–6 in parallel → pages 1 |

If W2 (platform throughput) is not done first, stage A still pays ~50 s per evidence call, but
because v26 issues acquisition as one code-driven batch with a single publish, most of that
overhead disappears anyway; W2 is what makes *today's* v25 faster while v26 is built.

What W1 alone (no restructure) is expected to give: **~$12–17 and ~35–40 min** — worth doing this
week, not worth stopping at.

---

## 4. The work, in order

Owner split follows `docs/specs/ARV2-WORK-SPLIT.md`: **(A)** = Aryan-owned (fleet wiring,
migrations, deploy, merges); **(L)** = leaf code/prompts/skills an agent can build on a task
branch for Shashank. Every item names its acceptance check.

### W1 — Stop the bleeding (this week; all small; no new architecture)

| # | Change | Where | Expected | Check |
|---|---|---|---|---|
| 1 | **Turn on tool-result clearing** (`ClearToolUsesEdit`: trigger ~100k, keep last 6 results, placeholder names the path) and give the research role a context-window override so compaction can fire (~120k) as a backstop | `platform/agents/clue_agents/runtime.py:643-664` (middleware tuple) or per-role at `quality_research_wiring.py:743`; `.env.example` parity | −30–38% model cost on v25 (simulated on the real calls) | replay Dialpad; cost/run and findings count |
| 2 | **Lenient finding schema**: `review` optional with server default `supported`, drop `extra="forbid"` for unknown keys, return the corrected field list instead of refusing the whole section | `arv2/dossier_findings.py:16-47`, `dossier_json.py:17-40` | removes the 27 failed saves (~$2.5, ~7 min) | zero `save_dossier_section` validation errors on replay |
| 3 | **Close the grep/search_evidence/finalize trap**: let `search_evidence` accept `/research/operations/…` paths, make `grep` on those paths work (or route it to search_evidence server-side), and stop a failed *advisory* search counting as an unresolved attempt that blocks `finalize_turn` | `quality_tools.py:358,388`, `quality_workspace.py:135`, finalize check in `agent_execution_wiring.py` (~2101 per the Oct 3 spec) | removes 7 refused finishes and ~45 wasted rounds | no finalize refusals on replay |
| 4 | **Serve views as plain text, whole by default, size-capped**; stop JSON-in-JSON for operation bodies; return the deep report as one readable document | `quality_workspace.py:43-55,77-83`, `quality_views.py:44-56,237` | −13–16% model cost; ~80 fewer paging rounds | tokens per evidence read ≤ 1.1× content |
| 5 | **Return content-bearing receipts** from `acquire_research_evidence` (title, URL, date, highlights ≤600 chars, evidence path) and the **real outcome** (`unavailable`, `tool_error`) in the receipt status | `quality_provider_tools.py:244-262,315-323` | one hop fewer per call; no "completed" for failed media reads | agent reads results file in <20% of calls |
| 6 | **Remove the duplicate L1 prompt and the dead `task` prompt** from every call | `context.py:274-296`, `runtime.py:640,190-196` | −3% | opening context ≈ 14k |
| 7 | **Release the provider slot when the provider answers** (move `_drain` outside the semaphore; AI Ark pause only around the HTTP call) | `account_research_tools.py:500-565,462-492` | ~2 min per run; more in bursts | batch position 5+ waits ≤ 15 s |
| 8 | **Start people at nomination**; hold only the contact page until the account imports | `quality_person_release.py:89-92` (new recipe condition); page writer already copes with a missing parent (`page_writer_runtime.py:414-437`) | −8 min per account | person jobs start < 1 min after nomination |
| 9 | **Write account pages once** after the last person; skip rewrites whose input hash is unchanged | `quality_generation.py:224-265,398-403`, `account_research_driver.py:849ff` | −$1 and −6–9 min to final pages | ≤ 2 account writer calls per account |
| 10 | **Launch latency**: make the Head-of-ABM research-launch path a direct tool call without the 9 file reads (separate chat-agent fix; record here so it is not lost) | Head-of-ABM profile/tools | −3–4 min before jobs start | launch turn < 45 s |
| 11 | **Disable media operations and strike the media instructions from the skills until W4 lands** (`discover_media`, `read_media` out of the v26 allowlist; remove "3–5 quotes from podcasts") | `recipe-v26.json` allowlist; `person-depth-charter`, `person-dossier`, `account-dossier` skills | removes ~35 wasted provider/tool calls and their reasoning per request | zero media calls until re-enabled |
| 12 | **Pages: pass `agent_interpretation` to the writer; stop the Miscellaneous dump for recipe ≥26; why-they-fit/why-now first; drop the duplicate "Context only"** | `page_writer_view.py:68-86`, `quality_pages.py:531-571`, `display/recipes.py:110-165` | shorter, decisive pages; no private leakage via the dump | page item count ≤ section caps |
| 13 | **Seller-led skills (v26 prompts)**: the §1 brief with caps replaces the eleven-area sweep and the personal-depth charter; ban process narration as findings; ask Exa for a compact evidence-first report | the four skills + both `SYSTEM.md` → v26 | person dossiers roughly halve; −20–30% person-run cost even on v25 | rubric: ≥ 70% of findings class A/B |

(L) for 2–6, 11–13; (A) for 1 (shared middleware), 7–10.

### W2 — Platform throughput: evidence calls at provider speed (1–2 weeks, (A)-heavy)

| # | Change | Where | Expected |
|---|---|---|---|
| 14 | Remove the worker-wide `_db_lock` from research tool transactions; per-job bounded connections (`CLUE_ARV2_JOB_MAX_DB_CONNECTIONS`, `.env.example` parity); raise the pool / check pgbouncer (20) | `account_research_driver.py:504,1017-1020` | −15 s before and most of the −37 s after each call |
| 15 | Index once per batch: verify the original once per receipt and pass the body through; skip the re-read in `index_provider_artifacts` for non-AI-Ark rows; return the body from the drain instead of re-reading it; record rows then `gather` the uploads | `quality_evidence.py:136-238`, `quality_acquisition.py:153`, `committee_discovery.py:141`, `research_operations.py:187` | ~54 → ~27 storage calls per search, concurrent; lock-held time 8–12 s → 1–2 s |
| 16 | Drop per-call `recover_acquisitions` on the success path (keep on replay and at settle); add the two missing indexes (`provider_call_ledger(workspace_id, entity_research_job_id) WHERE phase='result'`, `arv2_evidence_source(workspace_id, ledger_id)`) — hash-id migration, reversible | `account_research_tools.py:~717-726`; `alembic/` | −2–10 s per batched call; O(job) not O(workspace) |
| 17 | Record one source per *useful* unit (the result, its text) instead of result + text + highlight ×8, and index lazily on first read for the ~90% never opened | `quality_evidence.py`, `quality_acquisition.py` | ~⅓ of today's sources; most indexing never happens |
| 18 | Instrument the lock wait (`db.critical_section` already exists for publish/persist/import) so this cannot regress silently | `account_research_driver.py` | a number on a dashboard |

Target: `acquire_research_evidence` ≈ provider time + ≤ 8 s; ~10 min off each account on v25.

### W3 — The v26 pipeline (2–4 weeks; new recipe, flag-gated per workspace; v25 untouched)

| # | Build | Where (new/changed) | Notes |
|---|---|---|---|
| 19 | **Acquisition plan in code** (stage A): a fixed, ICP-parameterised list of operations per subject kind, issued as one parallel batch through the existing `ToolRuntime.operate` path; committee candidates via AI Ark at minute 0 | new `arv2/acquisition_plan.py`; reuse `account_research_tools.py` bodies | the agent may add ≤ 6 gap operations later; nothing else |
| 20 | **Extractor** (stage B): one cheap-model call per source with a strict JSON output; mechanical quote-substring check; typed by the §1 classes; writes `candidates.json` to the job workspace | new `arv2/quality_extract.py`; model via `RESEARCH_EXTRACT_AGENT_MODEL` (+ parity) | reuse the existing substring verification used for media quotes; reject any candidate whose quote is not in the source |
| 21 | **Judge loop** (stage C): profile `quality-account-research@v26` / `…person@v26` with the §1 brief as the output schema, ≤ 10 / ≤ 8 / ≤ 4 round budgets by tier, context = seller/ICP/persona + candidates; nominate in round 1; gap pass = A+B once | new profiles, prompts, skills; `recipe-v26.json`; `quality_research_wiring.py` round budget per role | the dossier is emitted directly — no separate write phase |
| 22 | **Person tiers**: top-2 deep, others light; tier chosen at nomination from committee role + evidence strength | `quality_committee_tool.py` nomination output; person launch | product decision D2 |
| 23 | **Per-section parallel page writer**, written once per subject; small model or Grok low effort (`RESEARCH_NARRATIVE_AGENT_MODEL` already env-driven) | `page_writer.py`, `page_writer_runtime.py`; `scripts/trial_page_writer.py` for replay | the 2026-09-26 trial wrote 8 sections in 51 s |
| 24 | **Own model setting for person research** (today both profiles share role `account_research`) | profiles; `.env.example` | lets D4 experiments run per role |

### W4 — Media: fix it or keep it off (decision D1)

To make recordings usable: install ffmpeg in `docker/backend/Dockerfile`; set `CLUE_DEEPGRAM_API_KEY`
on the worker VM; add podcast-platform → RSS/audio resolution for the common hosts; surface the
true outcome in the receipt (W1-5). Until all four are done, media stays out of the allowlist
(W1-11). Media is worth it only for the "their own words" items of the top-2 contacts; it should
be a tier-1 person option, never an account-wide sweep.

---

## 5. Sequencing and what each step buys

1. **Week 1 — W1.** Expected on v25: ~$12–17 and ~35–40 min per account; zero error rounds;
   people start 8 min earlier; pages shorter and decisive. Replay Dialpad + Loopio after each
   sub-group (1–6 context/schema; 7–9 timing; 11–13 instructions/pages).
2. **Weeks 2–3 — W2 in parallel with W3 design.** Expected on v25: evidence calls ≈ provider +
   8 s; ~10 more minutes off.
3. **Weeks 3–5 — W3 behind `CLUE_ARV2_RECIPE_VERSION=26` for one workspace.** Expected: ≈ $3–4
   and ≈ 12–14 min per account with five people. v25 keeps serving other workspaces until the
   replay gate passes twice.
4. **W4 when D1 says so.**

---

## 6. The replay gate (how we know it worked)

Same two accounts (Dialpad, Loopio) after every step, on fixed evidence where possible (the
2026-09-28 method; `scripts/trial_page_writer.py` for pages). Pass requires all of:

- **Cost** per account + five people (Langfuse + provider ledger) at or below the step's target.
- **Time** from job start to final pages at or below target; evidence-call time vs provider time.
- **Nothing lost that matters:** the seller-critical items found today must still be found and be
  *more* prominent — Dialpad: ABM/field hiring, the new Head of Growth (May 2026), the vacant CMO
  seat since Sept 2025, the SVP Marketing hire (Feb 2026), named marketing leaders, the ABM
  manager's own posts on personalisation and field marketing; Loopio equivalents from its brief.
- **Fidelity:** every quote on a page is a substring of its source; no misattributed employer
  facts (the September Muse failure mode); use-class gates hold on personal hooks.
- **Zero**: failed saves, refused finishes, refused listings, media calls (until W4).

---

## 7. Decisions needed from the founder

| # | Decision | Recommendation |
|---|---|---|
| D1 | Media: fix (ffmpeg + Deepgram key + RSS resolution) or keep off | **Off now** (W1-11); fix later only for top-2 contacts' own words |
| D2 | Person depth: top-2 deep + 3 light | **Yes** — people are 80% of the bill; the light pass still gives remit, problem, quotes, hooks |
| D3 | Stop the Miscellaneous dump for recipe ≥26 (reverses 2026-09-29) | **Yes** — it is the main source of blabber and a privacy leak path |
| D4 | Allow a cheap model for extraction (B) and pages (E), Grok stays the judge | **Yes** — behind the replay gate; same OpenRouter exposure class as today |
| D5 | Account pages written once after the people (optional early draft) | **Yes, with the early draft** so the account is readable at minute ~6 |
| D6 | Read-only production database user (Aryan) | **Yes** — closes the provider-cost and job-timing blind spots |
| D7 | Who owns the Head-of-ABM launch latency (W1-10) | assign; it is 4 minutes on every request |

---

## 8. Risks and unknowns

- **Extraction recall.** A cheap extractor may miss a nuance a strong reader would catch. The gap
  pass (C) and the replay gate's "nothing lost" list are the guard; if recall is short, the
  extractor model moves up one class (Flash → Grok-mini-class) before the judge loop grows.
- **Lenient schema (W1-2).** Defaults must be conservative (`supported` only when a quote is
  present; otherwise `insufficient_context`), or the import gains unreviewed claims.
- **Lock removal (W2-14).** Correctness must rest on the database constraints that already exist
  (idempotent `begin`, manifest `FOR UPDATE`); do W2-15 first so transactions are short; keep the
  critical-section timing on.
- **Production code version** on Oct 6 is unverified; W2's expected gains assume the current
  main, which fully explains the measured timings.
- **Exa deep-report price** is not in Langfuse; it may be the largest single provider line and
  should be read from `provider_call_ledger` once D6 is done.
- **Fleet capacity** (12 slots) becomes the binding limit once runs are short; raising
  `arv2_account_max_parallel_jobs` is cheap after W2.
