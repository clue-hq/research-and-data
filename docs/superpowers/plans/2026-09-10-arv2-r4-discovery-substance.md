# ARV2 R4 — discovery, cohort approval and fleet fan-out, substance for founder review (2026-09-10, rev 4)

**Status: rev 3 — §8 items 1–5 RULED 2026-09-10 (below) plus the rev 3 ruling; items 6–10 open. Nothing here is code or
a plan yet; the R4 plan is written from this document once every §8 item is ruled, then implemented
by subagent-driven development.**

**Rev 2 rulings (founder, 2026-09-10).** (1) The Clue ICP is the exit-gate target. (2) Approval is
the accounts table for now (Option B); the chat gate comes later, once the founder has designed how
a gate is asked for inside a project — a tab beside Gallery listing the project's target accounts.
(3) **No spend caps.** The founder's standing rule (no budget-based blockers, 2026-09-08) applies to
discovery too; costs are recorded on the ledger and the pre-spend estimate is raised before the
wire, nothing stops a run on money. (4) Ask Websets for **35** candidates. Partial matches are
medium-fit, not rejects: the frontend shows the strongest signal for a company that matches every
criterion and an honestly weaker one for a partial match. (5) Unclear candidates are shown, marked
unclear. **No approval UI is built until the founder has seen a preview of how it would look** —
§4 is that preview, on the screens that exist today.

**Rev 3 ruling (founder, 2026-09-10): no frontend change of any kind in R4** — not to the lifted
screens, not a new slot, not a marker. Show every discovered account; write "unclear" for the
unclear ones and show a full match as the best fit, using only what the screens already render.
Frontend suggestions are stored for a separate polishing session
(`docs/superpowers/plans/2026-09-10-arv2-frontend-polish-backlog.md`), never applied in this one.

**Rev 4 ruling (founder, 2026-09-10): Overall fit and Fit score only.** No custom variables, no
notes column, nothing the dummy frontend (`clue-frontend/live-backend-v1`, live at
`localhost:3000`) does not already show; parity with it is the reference. The Overall fit
vocabulary question (High / Medium / Low today versus Best fit / Partial fit / Unclear / Low fit)
is §8 item 10, because changing those words is a change to the dummy frontend's own schema.

**Ruled already (founder, 2026-09-10):** Exa Websets builds the long list; every company is then
checked by our own cheap probe on the Exa search API, the way the experiment did it; AI Ark stays
the only enrichment source. Evidence: `.context/arv2-websets-experiment/evaluation.md`
(`_memory/2026-09-10-arv2-r4-websets-experiment.md`).

**Sources read:** master plan §5.1 (launch contract), §9 Track R row R4, Appendix A (the laws);
the confirmed Clue ICP (`.context/arv2-answer-key-knowledge/icp-clue-abm-buyers.md`: hard gates
with tests, exclusions, qualifier fields); the v3 proof of concept and its discovery report; the
Websets experiment; `arv2/account_research_launch.py` (`Arv2LaunchRequest.account_entity_ids`);
`arv2/account_research_store.py` (run/job rows); `clue_fleet/work_worker.py` (one leased work item
per worker process); `frontend_read/bulk_actions.py` and `project_account` (how an account joins a
project today); the O6 plan's set-valued gate (Task 3) as the gate pattern; O6 as merged locally in the semarang
workspace on 2026-09-10 (`f60d1d270`: project ICP pin, v44 grants, fleet worker concurrency).

## 0. What R4 delivers (the master plan's exit gate, restated)

A 20-account cohort is **discovered** from the project's confirmed ICP, **approved** by a human,
**researched** by the fleet under a concurrency cap that actually binds, and **displayed** on the
accounts screens. Four steps, one lane, ARV2's own rows only.

## 1. The discovery run, mechanically

A discovery is a **job of its own on the existing fleet**, not a tool call in the chat turn: it
takes minutes (a webset ran five to eight minutes in the experiment), it spends money, and it must
survive a worker restart. One new fleet kind, `arv2_discovery`, driven by a handler next to the
account research handler, composed in `fleet_main` behind the existing lane flag.

**Rows (one migration, hash id, reversible; ARV2 tables only, never the old `discovery_*` tables,
which Phase 6 drops):**

- `arv2_discovery_run` — one per request: `workspace_id`, `project_id`, `brand_id`,
  `icp_artifact_key` + `icp_artifact_sha256` + `icp_key` + `icp_version` (the same pins the
  research run carries), `requested_by_user_id`, `target_count` (how many approved accounts the
  human wants), `candidate_count` (how many to surface, ≥ target; 35 by ruling 4),
  `status` (`not_started` / `in_progress` / `needs_review` / `completed` / `suspended`, the seam-1
  vocabulary), `webset_id`, `receipt_json`, timestamps.
- `arv2_discovery_candidate` — one per distinct company: `run_id`, `domain` (the folded
  registrable domain, unique per run), `name`, `homepage_url`, `source` (`webset` / `search`),
  `provider_snapshot_json` (the Websets item as received, firmographics included),
  `verdicts_json` (§3), `disposition` (`pass` / `partial` / `unclear` / `fail` /
  `duplicate_of_existing`), `fit` (0–1, §3),
  `decision` (`approved` / `rejected` / null) with `decided_by_user_id` and `decided_at`,
  `account_entity_id` (null until approved), `dedupe_hit` (the existing account it matched, if
  any).

Everything the provider returns is saved raw before parsing, the call is on the provider ledger
with its cost, and the pre-spend estimate is raised before the wire (Appendix A laws 1–2).

## 2. Step one — the long list (Exa Websets)

**Input.** The project's **pinned** confirmed ICP document (O6 Task 9b: `project_icp_pin`, read
through `arv2/icp_confirmation.current_project_icp_pin`; a project pins one ICP version and nothing
moves it on its own). Its front matter is the discovery brief. Nothing else is authored:
`hard_gates[]` give the criteria, `exclusions[]` give the query's negative half, the body's "who
they sell to" paragraph and the vertical give the query's positive half. A project with no pin
refuses `project_icp_not_pinned`, the same code the account launch uses.

**Query.** One webset, `entity.type = company`, `count = candidate_count`, `query` = a plain
sentence compiled from the ICP (what the company sells, to whom, at what stage), and **three
criteria at most**, each compiled from one hard gate whose test a public page can answer:

| Gate | Criterion, as written for Websets | Why this wording |
|---|---|---|
| geography | "Company is headquartered in the United States" | verifiable from the site/LinkedIn; 82–89% success rate in the experiment |
| stage | "Company's **most recent** funding round is a Series A or Series A extension, announced within the last N months" | "announced a Series A within N months" admitted two Series B companies; the ICP means the *current* stage |
| vertical / who they sell to | the ICP's own sentence for the buyer, one vertical named | 16–20% success rate; the discriminating criterion |

Hiring and intent are **never** webset criteria: their success rates were 3.7% and 2.7% and starved
the search to one company. They are graded by the probe (§3) from the ATS board and the job text.

**Exclusion before spend.** The run passes the workspace's existing account homepage URLs as a
Websets `exclude` import once the cohort is bigger than a screenful (the docs support it; the cap
per plan is unconfirmed, so R4 also dedupes locally, §3, and the import is a §8 ruling).

**Behaviour.** Async: create, then poll every 15 s with a stale-after guard, or the webhook when the
fleet's waiting state is wired for it; `status = in_progress` while it runs. Stop conditions: idle,
or a hard 30-minute wall. **No money stop** (ruling 3): the cost is recorded — 10 credits per
all-green result at the plan's per-credit rate, estimated by us since the API exposes no credit
counter — and the pre-spend estimate is raised before the wire, as a ledger fact, never a gate.
Zero results is an honest terminal outcome (law 12).

**Search stays** for two things: the per-company probe (§3) and the domain lock when a human names
a company. The v3-style prose queries are not a discovery method (the experiment reproduced the
proof of concept's negative finding exactly).

## 3. Step two — our probe grades every candidate

For every candidate, in code, before a human sees it:

1. **Dedupe against the workspace.** Fold the homepage domain; if an `account_entity` with that
   `primary_domain` exists in the workspace, `disposition = duplicate_of_existing`, no spend.
2. **Stage** — one Exa search (`"<name> (<url>) funding round Series A Series B raises"`, 5
   results, highlights only, published in the last N+6 months; $0.007). The most recent labelled
   round and its date are read from the highlights in code (regex over "Series A/B/C", "seed",
   "pre-seed", dollar amounts, dates). Verdict against the gate's own `test` text.
3. **Geography** — the Websets headquarters field, corroborated by the probe's highlights when
   they name a city; the ICP's rule ("US-headquartered").
4. **Hiring** — the existing ATS client: find the board from the careers page, fetch postings,
   count GTM titles (the ICP's own list: sales, marketing, growth, ABM, demand generation, SDR/BDR,
   partnerships, revenue operations). Free.
5. **Intent** — from the same postings' text: the ICP's tier-1/tier-2 signal phrases (outbound,
   list-building, named-account, target accounts, founder-led sales at its limit). A quote and its
   URL, or `unclear`. No model call at this step.
6. **Exclusions** — the ICP's `exclusions[]` that a page can answer (B2C, self-serve pricing
   page, a named ABM platform present, >800 employees, public/PE-owned): checked from the Websets
   snapshot and the probe text; anything unanswerable is `unclear`, never `pass`.

Each verdict is `{gate_key, verdict: pass|fail|unclear, reason, references[{url, quote}]}`,
written to `verdicts_json`. **Disposition and fit (ruling 4):** every hard gate `pass` → `pass`;
at least one `fail` and at least one `pass` → `partial`; every gate answered and at least one
`fail` with nothing unclear → still `partial` when a majority passes, `fail` when a majority fails;
any gate `unclear` and no `fail` → `unclear`. **Fit** is one number the screens already show:
`passes / gates`, with an unclear gate counted as half a pass — all four gates pass → 1.0 (High);
three pass and one unclear → 0.875 (High); two pass, two fail → 0.5 (Medium); one pass → 0.25 (Low).
The bands are the accounts list's own thresholds (`CLUE_ARV2_FIT_HIGH_THRESHOLD` 0.70,
`CLUE_ARV2_FIT_MEDIUM_THRESHOLD` 0.40). Unclear is never hidden and never auto-approved (ruling 5).
Probe spend is about $0.007 per candidate plus free ATS reads, recorded, not capped.

**Why the probe and not Websets' verdicts:** five of twenty-five Websets verdicts were wrong in
cohort-poisoning ways (a pre-seed called Series A, Bengaluru called US, a 2024 round dated 2026,
an unlabelled round called A, one entity credited with another's round). The probe caught all five.

## 4. Step three — the human approves the cohort (Option B, parity with the dummy frontend)

**Ruled:** the accounts table is the approval surface; nothing in the frontend changes; discovery
shows itself through **Overall fit and Fit score only** — the two columns the dummy frontend
already renders from the fit claim — and through nothing else.

**What the discovery job writes when it finishes.** Every candidate that is not a duplicate of an
existing account becomes an `account_entity` with `status = candidate`, `primary_domain` as the
strong key, workspace-scoped, plus:

- one `account.scoring.fit` claim (registered, project-relative; the run's `run_lineage` row,
  kind `discovery`, attributes it to the project) with `value` = the §3 fit. The list turns it
  into the badge and the score exactly as it does for a scored account today: every gate passed →
  1.0 → **High 100**; three of four with one unclear → 0.875 → High 88; two passed, two unclear →
  0.75 → High 75; half → 0.5 → Medium 50; one of four → 0.25 → Low 25;
- the ordinary `core.revenue_band` / `core.employee_count` claims from the Websets firmographics
  when present (source `exa_websets`), which fill the bands the table already has;
- the per-gate verdicts with references on the candidate row (`verdicts_json`) in full, handed to
  the researcher as "already established" at launch. They are not displayed in R4.

Research status reads **"Not started"** until a job exists. Every discovered account is shown,
low fit included.

**What the human does, on the screens that exist:**

1. Opens `/accounts`: thirty-odd new rows with Overall fit and Fit score.
2. Filters or sorts with the existing panel (Overall fit, Fit score).
3. Ticks rows → the existing **"Add to project"** bulk action. That write is the approval: the
   `project_account` row (`added_via = 'discovered'`); R4 stamps the candidate row
   `decision = approved`, `decided_by`, `decided_at`. Rows never added stay candidate accounts.
4. Names the approved accounts in the project chat; the Head of ABM launches
   `launch_arv2_account_research@1` (v44), or the operator runs the CLI. No research button.

**The one open word.** Today the dummy frontend's Overall fit accepts exactly `High`, `Medium`,
`Low` (its Zod enum, its badge, its filter panel), and the backend contract mirrors those three.
"Unclear" is therefore a Medium with an honest score until §8 item 10 is ruled.

## 5. Step four — launch and fan-out with a cap that binds

**Launch.** The approved accounts go through the existing `launch_arv2_account_research` with
`account_entity_ids = the cohort` — the launch already takes a list, checks the approved ICP
artifact against the project's pin, pins the product set, and creates one job per account. From
chat via the Head of ABM (v44 grants `launch_arv2_account_research@1` and
`launch_arv2_person_research@1` since O6) or the CLI. No research button.

**The cap.** Since O6 Task 9d (founder ruling 2026-09-10) one worker process drives
`CLUE_FLEET_WORKER_CONCURRENCY` tasks at once (default 1; semarang's `.env` runs 3), each slot
claiming on its own, and the ARV2 driver's per-process semaphore
(`CLUE_ARV2_ACCOUNT_MAX_PARALLEL_JOBS`, default 4) now binds *inside* a process. So today's cap is
**per process × N slots**, and provider fan-out multiplies with it (9d follow-up 2). R4 adds the
one thing that is still missing, a cap **per run**: `arv2_research_run.max_parallel_jobs` (from the
launch, default = the setting); a slot that claims a job whose run already has that many jobs
`in_progress` re-queues it (not a failure) with a short backoff, so a 20-account cohort cannot
take every slot of every worker at once. The AI Ark spacing rule (≥10.5 s between calls) becomes a
**shared** limiter keyed on the provider, since parallel slots and processes would otherwise each
keep their own clock (today it is per process).

**Display** needs nothing new: the accounts list reads research status from ARV2 job rows (account
jobs only, after the R3 rebase fix), and an account with no job shows as not started.

## 6. Cost and caps

| Item | Per unit | 20-account cohort at `candidate_count` = 35 |
|---|---|---|
| Webset (3 criteria, 35 candidates) | 10 credits per all-green result; Pro $0.00449/credit, Core $0.0061 | ≤ 350 credits ≈ $1.57 Pro / $2.14 Core |
| Probe (stage search) | $0.007 per candidate | $0.25 |
| ATS reads | free | — |
| Research, full effort | R2/R3 measured per account + per person | as today |

No caps (ruling 3): every figure is a ledger fact. The plan tier is a procurement ruling (Core
covers the exit gate many times over; Pro pays off at production volume).

## 7. Acceptance (the exit gate, measured)

On the semarang stack, the confirmed Clue ICP (the only ICP with hard gates, an answer key and known
good accounts today): one discovery run, `target_count = 20`, the human approves, the launch fans
out, the cohort is researched and displayed. Measured and recorded under
`.context/arv2-r4-acceptance/`: candidates surfaced, pass/unclear/fail split, probe precision on a
hand-graded sample, whether Probook and Zafran are surfaced (recall against the answer key),
spend per approved account, time to idle, jobs in flight versus the cap.

## 8. Rulings — 1–5 ruled 2026-09-10, 6–10 open

1. **RULED** — the Clue ICP (`clue-abm-buyers`, the answer key's workspace) is the exit-gate cohort.
2. **RULED** — Option B, the accounts table, for now; the chat gate follows the founder's design of
   the in-project target-accounts tab beside Gallery.
3. **RULED** — no spend caps of any kind; ledger and pre-spend estimate only.
4. **RULED** — 35 candidates; partial matches are medium-fit and shown with an honestly weaker
   signal (§3 fit, §4 columns).
5. **RULED** — unclear candidates are shown and marked; no approval UI before the founder has seen
   the preview (§4).
6. **Rejected memory**: an account left unapproved is not re-surfaced by a later run for the same
   project (proposed yes), and whether the Websets `exclude` import of existing accounts is used
   from day one (proposed: yes when the plan's exclusion cap is confirmed with Exa; local dedupe
   regardless).
7. **Plan tier**: Core ($49) for R4 and the exit gate; Pro only when volume justifies it.
8. **The cap's home**: a per-run cap on top of O6's per-process slots (proposed), or slots only.
9. **Where the two Head-of-ABM discovery tools land**: in R4 with a v45 profile bump (proposed),
   or held for O7 so the profile moves once. With Option B ruled, only `launch_arv2_discovery@1` is
   needed now; `open_cohort_approval_gate@1` waits for the founder's gate design.
10. **The Overall fit vocabulary.** The dummy frontend accepts exactly High / Medium / Low
    (`AccountFitSchema` in `src/features/accounts/model/account.ts`, the `FitBadge`, the filter
    panel's three options); the backend contract `AccountFit` mirrors them. Replacing them with
    Best fit / Partial fit / Unclear / Low fit is a change to the dummy frontend's schema, badge
    and filter, then the backend contract and its Zod oracle — i.e. a frontend change. Founder to
    rule: (a) keep the three words exactly (parity; unclear = Medium by score), or (b) change the
    words in the dummy frontend first, after which the backend follows in the same slice.
