# ARV2 v26 — account research rebuilt for cost, speed and depth: program overview

**Status:** 2026-10-07. Document set produced from every production research run to date, the
whole research lane in the codebase, and the logs, by seven authoring lanes in three waves, then
two adversarial reviews, one reconciliation round under written rulings, and a re-check.
**Read this file first; it is the map.** Nothing in the product has been changed by this program.

Branch `shank-audit-account-research-cost-optimization` on `clue-hq/research-and-data`.

---

## 1. What this program answers

The founder's questions, in order: *why does one account with five contacts cost ~$25 and take
~55 minutes; what exactly is wrong; what would fix it without making the research thinner; and can
that fix be specified so precisely that implementing it is not trial and error.*

**Answer in one paragraph.** The providers are not the cost (Exa and AI Ark are ~4 % of evidence
time and ~$1 per account). The cost is the research agent carrying every page it ever read into
every one of its 40–60 model calls (80 % of the bill is re-sending its own conversation), and the
time is our own platform serialising every evidence call behind a worker-wide lock and a slot
held through ~45 s of indexing, plus a pipeline that waits, rewrites and chains. The fix keeps
Aryan's governed runtime, the claim store and the agent's investigative judgement, and changes
three things: evidence is read once by an extraction step and reaches the agent as verified
candidates; the agent judges and investigates within hard budgets; acquisition, contacts and
pages run in parallel from the moment an account is approved. Expected: **$3.48 (Flash) / $2.72 (Luna) + 17.6 AI Ark
credits and ~7 minutes per account with five fully-researched contacts** (verified arithmetic on
the corpus's token volumes; ≈ $4.3 at the corpus's follow-up rate), with a ceiling that is a
function of the settings sheet ($9.4 modeled; ≈ $23–26 structural), and depth checked by replay tests
built from all 42 production runs rather than hoped for.

## 2. The documents

| # | Document | What it is | Lines |
|---|---|---|---|
| 01 | `01-evidence-all-production-runs.md` | Every production run since go-live (44 traces, 42 agent runs, 7 accounts, 35 contacts, three code versions): cost, time, rounds, failures, media, follow-ups; the confirm/refute of the 26 issues; the DB queries still needed | 924 |
| 01b | `01b-follow-up-chains-and-nothing-lost.md` | Which findings came from which search chains across all runs; the follow-up floor table; the caps; the quote-fidelity rule; the replay fixtures | — |
| 02 | `02-codebase-map-research-lane.md` | The lane as built: entry points, tools, tables and invariants, the virtual filesystem, profiles/recipes, settings, fleet, telemetry, dead code, and the design intent to respect | 1,891 |
| 03a | `03a-runtime-and-toolbelt-mechanics.md` | The seams any change must fit (governed tool flow, pinning, context, replay, budgets, cost accounting) and the chosen mechanism for each v26 piece | 895 |
| 03 | `03-target-architecture-v26.md` | The design: the campaign-brief contract, every stage with inputs/outputs/failure behaviour, the candidate pool and judge view, context economics and the cost ceiling, orchestration, observability, rollout, and the parameter sheet (~75 settings) — **the design authority** | 1,966 |
| 04 | `04-implementation-spec-w0-w4.md` | Every work item with owner, effort, dependencies, file:line changes, settings, migrations, tests, acceptance, rollback; sequencing; re-mint, parity and migration checklists | 1,614 |
| 05 | `05-verification-harness-and-acceptance.md` | The frozen evidence pools, the replay harness, acceptance tests AT-1…AT-9 with thresholds and fallbacks, the cost/time gate with SQL, the depth gate, go/no-go and rollback triggers | 1,087 |
| 06 | `06-risk-register-and-open-decisions.md` | Twenty risks with where each mitigation lives; the thirteen decisions that are the founder's | — |
| — | `review-A-consistency-and-executability.md`, `review-B-determinism-numbers-depth.md`, `RECONCILIATION-RULINGS.md` | The adversarial reviews and the twenty rulings that settled their findings — kept so the reasoning is auditable | — |

Earlier, now superseded as plans but kept as evidence: `../2026-10-06-account-research-v26-cost-and-speed-plan.md`
and `../../specs/2026-10-06-account-research-cost-and-speed-audit.md`.

Data (gitignored, local; rebuildable from Langfuse with the included scripts):
`.artifacts/arv2-research-runs-20261007/` (corpus, CSVs, sequences, fixtures) and
`.artifacts/account-research-cost-20261006/` (the first per-call audit, cost model, depth review).

## 3. What is wrong today — the evidence in ten lines (details: 01 §2–§6, 01b)

1. **Re-sending, not thinking:** 80 % of model spend is the cached re-send of the agent's growing
   conversation (17k → ~200k tokens over 40–60 calls); output is 5 %. Compaction can never fire
   (trigger 450k) and the installed tool-result clearing is unused.
2. **31 % of all 1,956 model calls are read-only paging rounds**; error, finish and listing rounds
   are another 15 %. The traps are universal: refused dossier saves in 42/42 runs, refused greps in
   42/42, the finish step refused in 17/42 at ~188k context.
3. **Our platform, not the providers, owns evidence time:** ~58 s per call on v25 against ~2.5 s of
   provider time — a worker-wide lock, ~54 storage round trips per search, the slot held through
   indexing, re-indexing of siblings on every call. PR #91 fixed Oct 3's far worse machine; the
   ~45 s tail is unchanged since.
4. **95 % of indexed evidence (20,039 records) was never opened**; the Exa deep report is read 40
   lines at a time across 4–11 rounds.
5. **Contacts are 74–84 % of every account's bill** and each is the same 40–60-round machine;
   they wait ~8 minutes for an account import they open 16 times across 35 runs.
6. **Pages are written three times** (dossier → page → rewrites as each contact finishes; 13
   rewrites, two failed); the launching chat turn takes 4 minutes.
7. **Media never transcribes in production** (0 of 21 attempts: no ffmpeg in the image, unsupported
   links, no key) while the skills demand podcast quotes.
8. **Depth comes from follow-ups:** 401 seller-critical findings in the corpus; 60 % had a
   follow-up search among their producers, 16 % could only have come from one. Any design that
   removes the agent's ability to follow its nose is thinner research.
9. **Output buries the signal:** coverage-first instructions, the writer gets caveats but not the
   researcher's conclusions, and the Miscellaneous dump restores everything the writer cut.
10. **Two production defects found on the way, independent of this program:** a contact's
    privacy-stop never reaches current (v4) contact jobs; the person compliance floor is off for
    every recipe since v6.

## 4. The design in one page (details: 03)

```
APPROVAL ─► A0 committee (AI Ark, ≤ 63 s) ─► contact jobs released by the 10 s sweep
         ─► A1/A2 acquisition for the account AND every contact, as parallel code batches
            (≤ 25 + 5 × ≤ 19 provider calls, pooled per account by plan; D8/D9 pin the Exa sizes)
         ─► A3 follow-up FLOOR: 11 rules mined from all accounts, ≤ 2 rounds, entity-aware
         ─► B extraction: every source read once by a cheap model; quote rule mechanical;
            candidates carry subject anchors and entities; context discarded
         ─► C judge + investigate (Grok): account ≤ 20 rounds / 30 operations / 60k context;
            contact ≤ 12 / 15 / 56k; every operation returns candidates, never raw pages;
            the agent follows any lead within budget; per-class minimums force a gap round;
            one submit_brief call emits the campaign brief → unchanged claims import
         ─► E pages: per section, in parallel, written once; contact pages deferred until the
            account brief exists; one account refresh only if the committee changed
```

**What is kept:** the governed toolbelt, journal, replay and lease semantics, the claim store and
import, DSAR paths, the display contract, Aryan's profile/recipe mechanism (v26 = recipe 26 in
week 1 and recipe 27 for the pipeline, selected per workspace).

**What research produces:** a ranked, capped **campaign brief** per account (triggers,
initiatives, pains, motion & proof, stack, committee, watch-outs, not-found, firmographics; caps
from the all-accounts maxima) and per contact (remit, problem right now, own words ×8, proud-of,
hooks, career arc, do-not-mention) — every item with quote-or-typed-value, URL, date, attribution,
use-class, and the researcher's interpretation where it matters. Built for direct mail, email,
landing pages and ads.

## 5. The numbers (details: 03 §5, 05 §4, review B)

| Per account + 5 contacts, all full depth | Today (measured) | v26 expected | v26 ceiling |
|---|---|---|---|
| Model + providers | $25 + 9.7 credits | **$3.48 (Flash extractor, the default) / $2.72 (Luna)** + 17.6 credits; ≈ $4.3 if the judge investigates at the corpus's follow-up rate | modeled, every cap hit: **$9.4 / $8.1**; structural, from settings alone: **≈ $23–26 / $18–21** (03 §5.5; D8 unpinned adds $3.00) |
| Time to final pages | 39–56 min (+ 4 min launch) | **≈ 7 min** | ≤ 10 min with W2; ~19 min without |
| Week 1 alone (W1 on the current recipe) | — | ~$12–17, ~35–40 min | — |

The expected case is arithmetic on the corpus's measured token volumes at OpenRouter's prices,
recomputed independently by review B to the cent. The ceiling is a property of the settings
sheet, not a forecast. Two settings make it deterministic and are the founder's to pin: D8 (Exa
deep-report tier) and D9 (person Exa text caps).

## 6. The work (details: 04)

| Workstream | What | When |
|---|---|---|
| W0 | Freeze the evidence pools; cut the follow-up table and the nothing-lost lists from the corpus; the offline expressibility check | days, no spend |
| P1–P6 | Deferred contact page; re-mint procedure; pool/pgbouncer sizing; live prompt verification; recipe selector; **the privacy-stop fix** | week 1, Aryan |
| W1 (recipe 26) | Stop the bleeding: tool-result clearing, lenient-but-safe schema, the grep/search/finish trap, plain-text views, content-bearing receipts, slot release, contacts at nomination, committee first, pages once, launch latency, media off, writer gets conclusions, seller-led skills | week 1; RC-1 replay |
| W2 | Evidence calls at provider speed: instrument the lock, index once, drop per-call recovery, remove the lock, lazy indexing | weeks 2–3 |
| W3 (recipe 27) | The pipeline: committee pre-step, acquisition plans + floor, extractor, judge loops with `submit_brief`, per-section pages, contact role | weeks 3–5; RC-2 replay ×2; pilot workspace |
| W4 | Media, only when its four conditions hold | D1 |

## 7. How we know it worked (details: 05)

Replay the same accounts on frozen evidence after each checkpoint. Pass = cost and time at target,
zero error rounds, **and** AT-1 candidate recall ≥ 0.95, AT-6 nothing-lost per account, AT-9
follow-up chain recall ≥ 0.90, AT-7 quote rule with zero false accepts, AT-5 zero namesake facts,
AT-8 the account judge sees the people slice. Every test has a fixture from the corpus and a
pre-decided fallback, so a failure routes to a known change, not an investigation.

## 8. Decisions for the founder

Thirteen, listed with defaults and reasons in 06 §2. The two that unblock the build: **D8** and
**D9**. The two that change stored data about people: **D3** (stop the Miscellaneous dump) and
**D11** (restore the person compliance floor). **D12** (two recipe mints) and **D1** (media off)
are recommendations the set already assumes.

## 9. Handover to Aryan

1. Read 00 → 03 → 04 → 05; 01/01b/02/03a are the evidence and the as-built facts behind them.
2. P6 first (production defect), then W0 and P1–P5, then W1 in the day order in 04 §7.5.
3. The reconciliation rulings (`RECONCILIATION-RULINGS.md`) explain every place the documents
   changed after review; the reviews are kept so nothing is taken on trust.
4. Questions the spec could not close are listed in 04 §12 with the author's recommended answer.
