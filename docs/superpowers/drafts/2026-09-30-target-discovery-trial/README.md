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

## Round 3 — arm G: the brief written by an agent (founder ruling 2026-09-30)

One model call (Grok 4.6, the Head of ABM's model) given the pinned ICP, the persona document and
the user's chat messages writes the whole brief — query, 2–5 criteria, gates each flagged
`disqualifying` or not — under `agent-brief-prompt.md` (trial-only; examples use dental clinics so
nothing about hotels is leaked). A company failing a disqualifying gate is marked excluded.
~$0.035 per brief. Spend $2.26; trial total $8.11 of $10.

| ICP | G long list | after the agent's disqualifying gates |
|---|---|---|
| hotel operators, count 10 + three count-3 | **19/19** real operators | 17 kept; **2 real hotels wrongly excluded** (Concord Hospitality, Nomada Hotel Group) by a false `fail` on the negatively-worded gate "The company is not a software … vendor" |
| Clue control, count 10 ("Find target accounts for this project." as the only chat) | 5/10 (OpenAI, Seismic, EasyPost, CereTax, Vartana are horizontal) | 4 kept (Tread, Lassie, Sirona, CereTax); Seismic and OpenAI correctly excluded as GTM/non-vertical; brightwheel wrongly excluded by the same negative gate |

What round 3 adds:

- **An agent-written brief fixes the hotel case on its own** (19/19, same as the hand-written D),
  unprompted: it wrote a company-type query and a "not a hotel-tech vendor" criterion itself, and
  restored the comma-truncated gate text by reading the document.
- **Negatively worded gates confuse the Answer verifier.** "The company is NOT a vendor …" produced
  false `fail`s on three real targets. Gates should be phrased positively ("The company sells
  software to hotels") with the disqualification carried by the flag, or the verifier must be told
  the polarity.
- **Websets is weaker on the Clue ICP whatever the brief** (A 4/10, D 7/10, G 5/10), while Exa
  `/search` with the company category scored 10/10 there. The Clue brief had almost no chat to work
  from; the real Head of ABM would have had the user's conversation.

## Round 4 — the production change, walked live (2026-09-30 / 2026-10-01)

The agent-authored brief shipped on `discovery/target-discovery-trial` (spec
`docs/superpowers/specs/archive/2026-09-30-agent-authored-account-discovery-design.md`) and was walked
in the app on the Conduit hotel-operators project. Every brief below was written by the Head of
ABM itself.

| Run | Ask | Source | Result | Spend |
|---|---|---|---|---|
| a1e002a3 (founder) | 5 | websets | 4 pass + 2 unclear added; Accor, Concord, Marriott wrongly excluded (side businesses read as "must not") | $0.70 |
| 36dba57d (founder) | 3 | websets | Exa Answer 402 (out of credits), 0 added; the wake turn's relaunch was refused by our own lock | $0.16 |
| 8e9f72db | 3 | websets | the tail of the same 402 | $0.16 |
| 46c7a9cd | 3 | search | the wake turn's own relaunch (lock taken over); ended dry — Exa `/search` answers any `excludeDomains` with zero results | $0.03 |
| 7a970d61 | 5 | websets | 5/5 hotel operators | $0.37 |
| d6b44e04 | 15 | websets | 15/15 hotel operators; Duane Street (closed) rightly excluded, Vesta Hospitality wrongly | $1.21 |
| b2d6a226 | 10 | websets | 10/10 hotel operators | $0.72 |
| 29fb39b3 | 20 | websets | Stop pressed after the reply: `stopped`, released, wake reported, 0 added | $0.29 |
| 2b76317d | 3 | search | after the excludes fix: 31 added (overfill), all hotel operators; HMP Properties wrongly excluded | $0.86 |
| 6a9f2ca3 | 2 | search | after the verification cap: 4 added, 4/4 hotel operators | $0.17 |

Graded by name and domain: **65 of 65 companies added after the Exa top-up are hotel operators or
hotel-management companies; no vendor reached the table.**

What the walk found and fixed on the branch:
- **The wake turn could never relaunch** (the lock was held until it finished) — `ab9d4bc8e`, a
  launch from the run's own wake turn takes the lock over; proven live at 19:59:34.
- **`/search` with `category: company` returns nothing when `excludeDomains` is sent** (reproduced
  with only `example.com` excluded) — `9f4d04cc2` pads the ask by the known domains and skips them
  in code; `e05ce5f8b` caps verification at twice the shortfall after the pad let an ask for 3
  verify 42.
- **The quote-on-page and right-company guards** turned correct verdicts to `unclear` (HHM's
  renamed LinkedIn, a job board for Zachry, "Concord Hospitality" vs "…Enterprises") and were
  removed by founder ruling (`8c4ece872`).

Still open:
- ~~**`must_not` gates exclude real targets.**~~ **Resolved (`9f3d3f67d`, founder ruling
  2026-10-01):** a `must_not` question now asks whether it is the company's *main* business.
  Replayed against Exa: Accor, Concord, Marriott, Vesta and HMP all kept (Vesta and HMP now cited
  their own sites); Dana.AI, withQ, nTouch and Cloudbeds still excluded; Hotel Equities and Ovolo
  kept — 15 of 15, one call each, $0.08. The own-site evidence rule was not adopted.
- The agent in another thread read the running discovery and declined on its own, so the tool's
  `discovery_in_progress` refusal was not re-exercised in this walk (it was exercised live on
  2026-09-30 at 18:07:38, and is covered by the DB tests).
- A held message runs after the wake turns but the transcript orders turns by submission, so its
  answer shows above the reports it followed — founder ruling 2026-10-01: keep this order.
- `/search` returned junk rows (`instagram.com`, an `exa.ai` page); the `must` gate excluded them,
  at a verification's cost each.
