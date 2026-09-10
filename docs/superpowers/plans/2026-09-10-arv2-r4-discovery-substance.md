# ARV2 R4 — discovery, cohort approval and fleet fan-out, substance for founder review (2026-09-10, rev 1)

**Status: DRAFT for rulings (§8). Nothing here is code or a plan yet; the R4 plan is written from
this document once every §8 item is ruled, then implemented by subagent-driven development.**

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
  human wants), `candidate_count` (how many to surface, ≥ target), `spend_cap_usd`,
  `status` (`not_started` / `in_progress` / `needs_review` / `completed` / `suspended`, the seam-1
  vocabulary), `webset_id`, `receipt_json`, timestamps.
- `arv2_discovery_candidate` — one per distinct company: `run_id`, `domain` (the folded
  registrable domain, unique per run), `name`, `homepage_url`, `source` (`webset` / `search`),
  `provider_snapshot_json` (the Websets item as received, firmographics included),
  `verdicts_json` (§3), `disposition` (`pass` / `unclear` / `fail` / `duplicate_of_existing`),
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
`spend_cap_usd` (10 credits per all-green result at the plan's per-credit rate; the API exposes no
credit counter, so the estimate is ours), or a hard 30-minute wall. Zero results is an honest
terminal outcome (law 12).

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
written to `verdicts_json`. **Disposition:** any `fail` on a hard gate → `fail`; every hard gate
`pass` → `pass`; otherwise `unclear`. `unclear` is shown to the human (they decide), never hidden
and never auto-approved. Probe spend is about $0.007 per candidate plus free ATS reads.

**Why the probe and not Websets' verdicts:** five of twenty-five Websets verdicts were wrong in
cohort-poisoning ways (a pre-seed called Series A, Bengaluru called US, a 2024 round dated 2026,
an unlabelled round called A, one entity credited with another's round). The probe caught all five.

## 4. Step three — the human approves the cohort

A human gate. Candidates with their verdicts, references and firmographics are presented; the
human approves a set. Two surfaces are possible; §8 rules which:

- **(a) A gate card in chat**, opened by the Head of ABM after the discovery run completes, built
  on O6's set-valued gate, which is now shipped (`open_product_set_selection_gate@1`, its answer
  route and the frontend card, merged into `integration/design-improvement` locally on 2026-09-10):
  a `cohort_approval` kind whose snapshot lists candidates with verdicts, pre-checked = the `pass`
  set, the answer carrying `selected_candidate_ids`. Matches the master plan's wording ("the agent
  proposes and opens the gate"). Two new Head-of-ABM tools ride with it — `launch_arv2_discovery@1`
  (starts the discovery job) and `open_cohort_approval_gate@1` — which means a profile bump (v45),
  the recipe allowlist, the authority map and the stage0-interview skill text (founder-reviewed),
  the same mechanics O6 used to grant the two ARV2 launches.
- **(b) The accounts table**: approved candidates become accounts immediately, the table shows them
  with verdict chips, and the existing "add to project" bulk action is the approval. Reuses D4-b;
  but unapproved candidates would sit in the main accounts list, and the table has no verdict slot
  today (dummy-frontend rule: no invented UI).

On approval, in one transaction: `insert_account_entity` (workspace-scoped, `status = candidate`,
domain as the strong key), `project_account` row with `added_via = 'discovered'`, the candidate's
`account_entity_id` set, `decision = approved`. Rejected candidates keep their row: a later run
skips them (§8 asks whether "rejected" is remembered across runs).

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

| Item | Per unit | 20-account cohort at `candidate_count` = 60 |
|---|---|---|
| Webset (3 criteria) | 10 credits per all-green result; Pro $0.00449/credit, Core $0.0061 | ≤ 600 credits ≈ $2.70 Pro / $3.70 Core |
| Probe (stage search) | $0.007 per candidate | $0.42 |
| ATS reads | free | — |
| Research, full effort | R2/R3 measured per account + per person | as today |

`spend_cap_usd` per discovery run and a per-candidate probe budget are §8 rulings. The plan tier is
a procurement ruling (Core covers the exit gate many times over; Pro pays off at production volume).

## 7. Acceptance (the exit gate, measured)

On the semarang stack, the confirmed Clue ICP (the only ICP with hard gates, an answer key and known
good accounts today): one discovery run, `target_count = 20`, the human approves, the launch fans
out, the cohort is researched and displayed. Measured and recorded under
`.context/arv2-r4-acceptance/`: candidates surfaced, pass/unclear/fail split, probe precision on a
hand-graded sample, whether Probook and Zafran are surfaced (recall against the answer key),
spend per approved account, time to idle, jobs in flight versus the cap.

## 8. Rulings needed from the founder

1. **ICP and brand for the exit-gate cohort.** Proposed: the Clue ICP (`clue-abm-buyers`, workspace
   of the answer key). Insight Health once O6 mints its confirmed ICP.
2. **Cohort approval surface**: (a) chat gate card after O6, or (b) accounts table + add-to-project.
   Recommendation: (a).
3. **Spend caps**: per discovery run (proposed $10) and per candidate probe (proposed $0.05).
4. **Candidate count**: how many to surface for a target of 20 (proposed 3× = 60, since the
   experiment's strict precision on three criteria was 56%).
5. **Unclear handling**: shown for the human to decide (proposed), or held back.
6. **Rejected memory**: a rejected candidate is not re-surfaced in later runs for the same project
   (proposed yes), and whether the Websets `exclude` import of existing accounts is used from day
   one (proposed: yes when the plan's exclusion cap is confirmed with Exa; local dedupe regardless).
7. **Plan tier**: Core ($49) for R4 and the exit gate; Pro only when volume justifies it.
8. **The cap's home**: a per-run cap on top of O6's per-process slots (proposed), or slots only.
9. **Where the two new Head-of-ABM tools land**: in R4 with a v45 profile bump (proposed), or held
   for O7 so the profile moves once.
