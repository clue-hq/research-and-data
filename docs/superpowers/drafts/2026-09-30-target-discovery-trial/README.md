# Target-account discovery trial (2026-09-30)

**Why.** The Conduit AI onboarding's first live discovery (hotel-operators ICP, 3 accounts) returned
three hotel-software vendors — Dana.AI, withQ, nTouch — i.e. the seller's competitors, not its
customers. This trial runs the production discovery pipeline in isolation to find out why and what
fixes it, before anything changes in the platform.

**Harness.** `scripts/trial_target_discovery.py` (tests: `tests/scripts/test_trial_target_discovery.py`).
No application DB writes, no fleet, no accounts. Provider pieces are imported from production
(`compile_brief`, `ExaWebsetsClient`, `ExaClient.answer`, the verifier's questions, `apply_guards`,
`fit_score`); only the DB-bound orchestration is replaced. Raw bodies, ledger rows, candidates and
grades are under `.artifacts/target-discovery-trial-20260930/run-*/` (git-ignored).

| Arm | What it sends |
|---|---|
| A | production exactly: the ICP as stored, `compile_brief` unchanged |
| B | the ICP's comma-split gates repaired |
| C | B + a query that says what the company IS (`overrides/*.yaml` `company_query`) |
| D | C + one exclusion criterion (`exclusion_criterion`) |
| E | Exa `/search`, category `company`, on the C query, then the same verifier |

Overrides for C/D/E are written from each ICP's own text.

## Defects found in the current pipeline

1. **Comma-split ICP gates.** The ICP-synthesis skill (`icp-synthesis/v2/SKILL.md`) writes gates as
   inline YAML (`- {key: …, rule: …, test: …}`); a comma inside a value starts a new key, and
   `parse_front_matter` keeps only the first part. The live hotel ICP sent Websets
   "There is a named guest-experience" and asked the verifier a gate-1 test of just "Brand site".
2. **The search query is the ICP's need sentence.** `buyer_sentence` takes the body's first paragraph
   ("… needs guest communication … hotel PMS … guest-experience suite") — the words vendors use
   about themselves.
3. **Exclusions are compiled and never asked.** No criterion keeps vendors or the competitive set out.
4. **A failed hard gate is not disqualifying.** `fit = passes / gates`, so failing "operates hotels"
   still scores 0.667 and shows as "Medium".

## Results (graded; `grades.json` + `grades-notes.json` per run)

Hotel operators — graded "operates hotels/resorts/serviced accommodation" vs "vendor":

| Run | A | B | C | D | E |
|---|---|---|---|---|---|
| run-01, count 10 | 10/10 | 9/10 | 8/10 | 10/10 | 10/10 |
| run-02, count 3 | 3/3 | | | 3/3 | 3/3 |
| run-03, count 3 | 3/3 | | | 3/3 | 3/3 |
| run-04, count 3 | **0/3** (Opally, Qwest, Enso Connect) | | | 3/3 | 3/3 |
| **total** | 16/19 | 9/10 | 8/10 | **19/19** | **19/19** |

Clue's own ICP (control) — graded on the KIND of company (US B2B vertical SaaS, not a competitor):

| run-05, count 10 | A 4/10 (3 unclear) | D 7/10 (1 unclear) | E 10/10 |

Spend: $5.85 of the $10 approved.

## What the evidence says

- **The live failure reproduces, intermittently.** Production's exact input returned 3/3 vendors in
  one of three count-3 runs — the live scenario — and none at count 10. Websets returns different
  companies each run; a small count shows whichever it confirms first.
- **Every vendor failed our own verifier's identity gate.** Cloudbeds, GRACESOFT, Hotelogix, Opally,
  Qwest and Enso Connect all got `fail` on "operates hotels" (live: withQ and nTouch `fail`, Dana.AI
  `unclear`). Websets' own evaluation passed them — its description of Qwest even claims it
  "operates or manages hotel-like properties". Treating a failed identity gate as disqualifying
  removes them regardless of the source.
- **The exclusion criterion (D) had zero vendors in 19 hotel companies**, and improved the control
  (4 → 7 of 10), costing Websets little: 85% of analysed hotel candidates satisfied it.
- **Repairing the gates alone (B) or changing only the query (C) did not stop vendors** (1 and 2 of 10).
- **Exa `/search` with the company category (E) was right on both ICPs (29/29)**, for ~$0.01 per
  long list instead of ~$0.45 of Websets credits. Caveats: it is deterministic — the three count-3
  repeats returned the same three companies — so "find more" needs `exclude_domains`; and its
  stage/hiring verdicts failed more often on the control (3 of 10 companies had a failed gate).
  This contradicts the 2026-09-10 experiment's weak `/search` result, which used prose queries
  without the company category.

## Not yet done

- Sample sizes are small (≤19 per arm per ICP); one grader (Claude), to be spot-checked by the founder.
- Arm F (AI Ark industry-filtered company search) not built.
- Production changes are a separate, designed change.
