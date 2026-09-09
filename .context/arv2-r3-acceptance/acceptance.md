# ARV2 R3 — live acceptance (2026-09-09)

Branch `track-r3`. Code under test: Tasks 1–9 + final-review fix wave (`2f5a00712`), then the live fix wave
(`be560aeab`) after the first five person jobs. Founder rulings during the run: stop after the first five,
fix what was found, re-test the **same five** on the fixed code; then a three-worker parallel test on the
last three. Evidence in this folder (`before/`, `after/`, `recall/`, `pages/`, `repair-lookups.txt`,
`worker*.log`).

## What ran

| Run | Launch | Jobs | Code |
| --- | --- | --- | --- |
| `ba43bd2f` | Zafran, account path (`launch_arv2_account_research`, cap 5) | 1 account job + committee fan-out: 4 person jobs (Vari Kaur, Rotem Peled-Dvir, Ben Seri, Sanaz Yashar); 1 vacant seat skipped | account job ran (12 rounds, 113 claims, $0.94); the 4 person jobs were dequeued by ruling |
| `1e2edb26` | 7 people on demand (`launch_arv2_person_research`) | Semien, Coles, Edupuganti, Paterson, Corio (old code); Chonoles (fixed code); Marathe dequeued | mixed |
| `4900b571` | Nick Fisher + Tom Anthony on demand | dequeued by ruling | — |
| `edb52ad3` | the same five people, re-run | Semien, Coles, Edupuganti, Paterson, Corio | fixed code; last three in parallel on 3 workers |

Fan-out seam (Zafran): 4 person jobs = 4 fleet tasks; 1 new contact created (Rotem Peled-Dvir), 3 reused from
the loader by LinkedIn URL. Committee candidates were written twice by the account job (once through
`write_claims`, once by finalize) — a dedupe for the account finalize is a follow-up.

## Defects found live, and fixed before the re-run

- **L1 — identity lock failed closed on a name spelling.** `_current_company_domain` trusted the provider's
  company block only when its name equalled the current position's name (`"Cogent Security"` vs `"Cogent"`), so
  the employer came back unknown and `lookup_person` refused `subject_lock_failed`: no provider claims, no
  email export, for all three Cogent people (the Harmonic pair passed on a name match). Fix: resolve the
  employer by the LinkedIn company URL first, name containment second; the tool corroborates rather than gates —
  a *different* resolvable employer refuses, an unknown one proceeds with marker `employer_unverified`.
- **C1b — the phone scan still dropped legitimate claims** (four talk lists, one career history: whitespace-
  separated years and dates merged into a 9–15 digit run). Fix: a phone match needs a phone signal (leading
  `+`, parenthesised area code, dash/dot-separated tail, UK 5+6, or a phone word in the sentence).
- **L2 — the unique-insight pass landed on `contact.facet.hooks`.** Fix: `UNIQUE_INSIGHT_TARGET_KEYS` (fact
  facets only); off-target rows dropped and reported.
- **Repair path** — `scripts/arv2_repair_person_lookups.py` re-runs the deterministic lookup for finished
  person jobs (no model). Run for real on the five old-code people: employer verified on all five by the URL
  ladder; emails for Coles, Edupuganti, Paterson, Corio; Semien's export returns nothing (the smoke test's 404
  case — provider side). Not idempotent: the Harmonic pair, whose lookup had succeeded, got duplicate rows.

## Before → after, per person (old-code job vs fixed-code re-run)

| person | rounds | $ | claims | provider claims (native) | email | insight | floor drops | audit EXACT / NOT_FOUND |
| --- | ---: | ---: | ---: | ---: | :---: | :---: | ---: | ---: |
| Semien | 10 → 14 | 0.62 → 0.78 | 48 → 52 | 0 → 6 | no → no (provider) | ✓ → ✓ | 0 → 0 | 27/0 → 28/7 |
| Coles | 14 → 11 | 0.76 → 0.74 | 57 → 61 | 0 → 7 | (repair) → ✓ | ✗ → ✓ | 4 → 0 | 31/4 → 32/4 |
| Edupuganti | 14 → 13 | 0.95 → 1.07 | 62 → 71 | 0 → 7 | (repair) → ✓ | ✓ → ✓ | 0 → 0 | 39/6 → 46/7 |
| Paterson | 12 → 16 | 0.90 → 1.25 | 67 → 80 | 7 → 7 | ✓ → ✓ | ✓ → ✓ | 1 → 0 | 40/3 → 57/4 |
| Corio | 10 → 13 | 0.59 → 0.85 | 57 → 58 | 7 → 7 | ✓ → ✓ | ✓ → ✓ | 0 → 0 | 25/3 → 27/3 |
| Chonoles (fixed code only) | 12 | 0.67 | 45 | 7 | ✓ | ✓ | 0 | 27/2 |

Every fix holds: lock verified on all six, provider claims native on all six, insight 6/6 on fact facets,
zero phone-drops, EXACT audits up for everyone. Cost per person on the fixed code: **$0.67–1.25 + 1.5 AI Ark
credits** (0.5 search + 1.0 export); model spend is ~80% of it; ~60k prompt tokens per round, ~85% cached.
The parallel jobs cost more rounds (13–16) — see below.

## Answer-key recall (leaf-value grading, `recall/{before,after}`)

| person | before | after |
| --- | ---: | ---: |
| Paterson | 0.19 | 0.12 |
| Semien | 0.33 | 0.33 |
| Corio | 0.07 | 0.29 |
| Coles | 0.11 | 0.22 |
| Edupuganti | 0.27 | 0.20 |
| Chonoles | 0.62 | — |

Reading: almost every key is `field_only` — the field is found but the free-text value does not leaf-match
the answer key's phrasing. Person facets are prose (a hobby, a quote, a talk); exact leaf agreement is the wrong
grader for them. **Follow-up:** a semantic or containment grader for facet text; until then "field found" is the
honest coverage number (≈ 0.9 on every person) and the recall figure understates the run.

## Parallelism

One worker process drives one job at a time (the fleet loop claims → drives → claims). The driver's
`CLUE_ARV2_ACCOUNT_MAX_PARALLEL_JOBS=4` never binds under that loop, and its single DB connection per process
would serialise store writes anyway. Across processes, N workers = N concurrent jobs.

Three workers on the last three re-runs: per-job wall 6:00 / 8:46 / 13:03 vs ~5:00 sequential; the three
finished in ~13 minutes where sequential would be ~15–16 — about +25% throughput, not 3×. Under load the
jobs took more rounds (13–16), and single transient 429s appeared (OpenRouter ×2, Gemini ×1, Exa ×1), all
retried; no lease loss, no tracebacks. The bottleneck under three-way load is the shared providers and the
model, not the fleet. Per-process concurrency >1 is a fleet-loop + driver-DB-lock change, not an ARV2 setting.

## The pages (read surface, in-process — `pages/*.json`; `:3000` is another workspace's dummy on fixtures)

- **Zafran contacts list**: 6 members from ARV2 rows in persona order — Nick Fisher, Sanaz Yashar (economic
  buyers), Vari Kaur (champion), Ben Seri (technical evaluator), Tom Anthony (user), Rotem Peled-Dvir (blocker,
  the contact the committee step created). No coverage row involved.
- **Cogent contacts list**: 2 of 3 — Coles is missing (see W2).
- **Semien's page**: title, persona, influence, location, best channel, education (Duke), followers; sections
  generated on read (why-this-person 2 items, openers 2; problem/angles empty — the account has few claims);
  Email **empty** (W1); tenure **empty** (W3).
- **Nick Fisher's page**: the loader's data as before (education, tenure 2y5m, 6,808 followers, creator badge,
  four sections incl. 3 angles and 2 do-not-mention rows); Email empty (W1).

Walk findings (integration defects, none in the agent):
- **W1** `core.work_email` is written as a bare string; `email_facts` expects `{address, status}` with
  `status ∈ {verified_smtp, catch_all_valid}` → the Email slot is empty for everyone. Fix: write
  `{address, status: <verdict>, checked_at}`; `not_found` writes nothing (as today).
- **W2** a person launched on demand gets no `contact.persona` / `contact.role_on_committee` claim unless the
  agent happens to write them, and the ARV2 committee source requires the persona claim → Coles, Corio and
  Chonoles are invisible in their accounts' contact lists. Fix: the person launch writes both at launch
  (`--persona`, default `user`; rationale "launched on demand by <user>").
- **W3** `current_position_start` reads `date.start` / `date.end` per entry; the AI Ark mapper writes flat
  `start` / `end` → tenure empty. Fix: the mapper writes the `date: {start, end}` shape the read surface and the
  answer key use.
- **W4** the AI Ark title carries the company (`"Head of Growth | Cogent"`); strip a trailing `| <company>`.
- **W5** `overviewParagraphs` is 0 — the `contact.overview` prose field belongs to the old prose tool; not R3's.

## Verdict

The R3 machinery works end to end on real people: committee fan-out, on-demand launch, the person agent, the
compliance pass, the repair path, the ARV2 committee source, and the pages. Three agent-side defects were
found and fixed live; four read-surface integration defects (W1–W4) remain and are small. The ten-person
answer-key reproduction is **partial by ruling** (6 people run on the fixed code; Zafran's committee and
Marathe/Fisher/Anthony dequeued) and the recall grader needs a facet-text mode before its number means what
the master plan's exit gate asks.

## After fix wave 2 (`353b55bcd`) and the second repair run

- **W1–W4 fixed on the wire** (`pages/*.json` re-dumped): Cogent contacts list = 3 rows (Coles economic_buyer,
  Edupuganti economic_buyer, Semien champion) with emails for Coles and Edupuganti; Coles's page shows
  `cameron@cogent.com` verified 2026-09-09, tenure 10 months, title `VP of Marketing`; Semien's page shows tenure
  1 year 1 month (email none — provider). Seating claims for Coles/Corio/Chonoles are written as
  `ExtractionMethod.HUMAN` with the rationale "launched on demand by <user>".
- Migration `7c4f1a2b9d63` moved `core.work_email` to `{address, status, checked_at}` and
  `contact.facet.career_history` to the nested `date` shape at the time of this walk; after the
  2026-09-10 rebase the work_email swap is D4-b's `7332ac974920` (closed vocabulary
  `WORK_EMAIL_STATUSES`) and `7c4f1a2b9d63` keeps only the career-history swap.
- **Loader follow-up (D1):** the answer key's `core.work_email` rows carry the provider's raw block
  (`status: "VALID"`), so the Zafran list's email chips stay empty and those rows now read `schema_valid=false`.
- Repair-run cost: 6 × 1.5 credits (search + export) for the six re-exports.
