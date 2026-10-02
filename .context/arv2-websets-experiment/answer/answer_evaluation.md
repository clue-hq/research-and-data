# Exa Answer as the verifier — structured output over the 18 discovered companies (2026-09-10)

**Setup.** The 15 companies the webset found plus Pie, GenHealth.ai and Avoca from Shashank's
query (Probook with its real site, `probook.ai`). For each company, one `POST /answer` per ICP hard
gate (`model: exa`, `text: true`, a system prompt, an `outputSchema`). The question is the gate's
`rule` and `test` copied from the confirmed ICP document; nothing gate-specific in code. Files:
`run_answer.py`, `companies.json`, `sample_avoca_stage.json` (one full response), raw
`../raw/answer_exa_*.json` (72 files), ledger `../ledger.json`.

**Guard.** One check in code: the `evidence_quote` must appear verbatim in the text of a citation
Exa returned (whitespace and typographic punctuation normalised), else the verdict is `unclear`.

## What the structured output looks like

```json
{"verdict": "fail",
 "reasoning": "The company's most recent funding round is a Series B, which is outside the criteria of being a Series A or Series A extension.",
 "evidence_quote": "Today, we announced our Series B at a $1 billion valuation, bringing our total raise to more than $125 million across Seed, Series A, and Series B.",
 "evidence_url": "https://www.avoca.ai/blog/avoca-raises-125m-series-b-1b-valuation",
 "evidence_date": "2026-04-27"}
```
plus `citations[]` (url, title, publishedDate, full text when requested) and `costDollars`.

## Numbers

| | |
|---|---|
| Calls | 72 (18 companies × 4 gates) |
| Cost | **$0.005 per call**, $0.36 total (≈ $0.02 per company for all four gates) |
| Latency | 1.8–5.1 s per call, median ≈ 2.3 s |
| Quote found verbatim in a returned citation | 69 / 72 |
| `evidence_url` is one of Exa's citations | 71 / 72 |
| Agreement with the hand-checked truth (26 verdicts where truth is known) | **24 / 26** |
| Account state at the end | the Exa account hit its credit limit (HTTP 402 on the next calls); the `exa-pro` comparison could not run |

## Verdicts

| company | stage | geography | hiring | intent | note |
|---|---|---|---|---|---|
| Patientdesk.ai | fail | pass | pass | pass | seed correctly seen; intent from a founder's LinkedIn post about a "setter" workflow |
| 1Fort AI | fail | pass | pass | pass | |
| Snout | pass | pass | pass | pass | |
| Lasso MD | fail | pass | pass | pass | seed 2023, correctly outside |
| &AI | fail | pass | pass | unclear | Answer noticed the same-name "&AI patent litigation company" and separated it |
| DentalHQ | fail | pass | fail | pass | hiring should be `unclear`: "no roles found" is absence, not contradiction |
| Probook | pass | pass | pass | pass | intent from the CEO's own post: "Being stuck in founder-led sales isn't a flex" |
| Digs | pass | pass | pass | pass | hiring via an aggregator (Simplify Jobs) posting; our Greenhouse read saw 0 roles — disputed, not wrong |
| Lassie | pass | pass | pass | pass | |
| Levanta | fail | pass | pass | pass | Series B 2026-08-27 correctly seen |
| INFI | pass | pass | unclear | pass | **intent is wrong**: the cited posting is infinIT (infinit.us), a different company |
| Superorder | **pass** | pass | fail | unclear | **stage is wrong**: it found the right fact (Series A, 2023-09-15) and then said it is "within the last 24 months"; a date-arithmetic slip |
| BeyondTrucks | pass | pass | pass | pass | Series A 2024-10, correctly inside the window |
| Equal Parts | pass | pass | pass | pass | hiring passed on "Associate, M&A Diligence & Risk" because the description lists revenue operations — a stretch |
| Boostly | pass | pass | pass | pass | |
| GenHealth.ai | pass | pass | pass | pass | |
| Avoca | fail | pass | pass | pass | Series B correctly seen (our regex probe got this wrong) |
| Pie | pass | pass | pass | pass | Houston HQ found; the site I guessed was wrong and did not matter |

## What it gets right that nothing else did today

- **Stage, 17 of 18.** Every seed and pre-seed company that Websets had admitted as Series A is
  caught; Avoca and Levanta's Series B are caught; the Probook "seed + Series A together" case and
  the BeyondTrucks "old profile page says seed" case are both right. No tie-break of any kind.
- **Hiring and intent without a job-board integration.** It reads Ashby postings, LinkedIn job
  tabs, careers pages and aggregators as sources and quotes them. Our probe could read four boards;
  Answer produced hiring evidence for 16 companies.
- **Same-name awareness** in the &AI case, unprompted beyond the system-prompt line.

## Where it fails, and what each failure says

1. **Date arithmetic** (Superorder): the fact was right, the comparison to "24 months" was wrong.
   A code check of `evidence_date` against the window catches this deterministically — the one
   place code belongs, because it is arithmetic, not judgment.
2. **Same-name company** (INFI → infinIT): the system prompt's warning was not enough once. The
   guard passed because the quote really is on the cited page. A domain check — the cited URL or
   the posting's employer must match the company's verified domain — catches it.
3. **Fail where unclear was due** (DentalHQ hiring, Superorder hiring): absence of postings became
   `fail`. The instruction needs to say it more plainly, or code maps "no source found" to unclear.
4. **A GTM title stretched** (Equal Parts): the model read "revenue operations" in a job
   description as a GTM role. This is judgment; a human reading the same quote would see it.
5. **Aggregator sources** for hiring (Digs, DentalHQ): the ICP says "the company's own careers page
   or ATS board". Whether aggregators count is a ruling, not a bug.

## Answer with a schema vs Exa deep-reasoning vs the Exa Agent (what the lane already uses)

| | Answer (`/answer`, `outputSchema`) | Search `type=deep-reasoning` (`outputSchema`) | Agent (`/agent/runs`) |
|---|---|---|---|
| Shape | one question → one search pass → one synthesised answer, structured if asked | one query → multi-step research over up to 20 pages with the charter in the query and the target lock in the system prompt → one report or structured object | an autonomous multi-step run with an effort level, asynchronous |
| What it is for | verifying **one fact** about one subject | writing the **whole dossier** for one subject (R2/R3 use it for the account and person reports) | open-ended tasks |
| Latency | ~2 s | tens of seconds to minutes | minutes |
| Cost (this account) | $0.005 per call measured | ~$0.02–0.03 per subject measured in the proofs of concept (cost scales with pages) | not measured here |
| Structured output | yes, JSON Schema, works per call | yes, but the v2 proof of concept found the report is only reliable with a single free-text `report` property; the claims-shaped schema cut assertions to a third | yes |
| Where it fits R4 | the **qualifier** gate-by-gate, cheap enough to run on every candidate | the **deep research** step after approval, as today | not needed for R4 |

The difference in one line: Answer is a verifier you ask one question; deep-reasoning is a
researcher you hand a charter. The qualifier needs the first, and the R2 agent already owns the
second.

## Addendum — the same 72 questions through `POST /search` with `systemPrompt` + `outputSchema`

`run_search_schema.py`: `type=auto`, 6 results, page text 3000 chars, the identical system prompt,
schema and question text; no date bounds (so the retrieval difference is Exa's, not ours).

| | Answer | Search + schema |
|---|---|---|
| Cost per call | $0.005 | $0.007 (contents were not billed separately on this account) |
| Total, 72 calls | $0.36 | $0.50 |
| Median latency | 2.3 s | 3.6 s |
| Stage: read "Series A or Series A extension" correctly | 17/18 | **9/18** — nine companies with a plain Series A (Probook, Lassie, Snout, INFI, Digs, Equal Parts, GenHealth.ai, Pie, Superorder) were marked **fail** with the reasoning "a Series A, not a Series A extension" |
| Verdict agreement with Answer, all gates | — | 48/72 |
| Absence treated as `fail` (intent, hiring) | rare | frequent ("the sources do not describe…" → fail) |

Same prompt, same schema, same question: the synthesis behind `/search` read the test literally
and wrongly, the synthesis behind `/answer` read it as written. Search is also slower and costs
more per question on this account. Search keeps the control Answer lacks (date bounds, domain
include/exclude, page count), but that control did not buy quality here, and the reading error is
in the part we cannot control.
