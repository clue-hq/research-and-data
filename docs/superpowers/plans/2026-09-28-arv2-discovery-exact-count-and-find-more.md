# ARV2 discovery — exact count, top-up websets, "find more" (plan, 2026-09-28)

Status: **built 2026-09-28** on the founder's go ("proceed with the implementation"), taking the
recommended answer to every §4 choice: (1) search 2 only when Exa filled search 1 and our checks
removed some; (2) the turn-budget bundle committed first (`e431744b7`), v66 built on v65; (3) the
§3 deletions made; (4) the wall clock per search. The live acceptance run is owed (§5).
Context: `_memory/2026-09-28-account-discovery-audit.md`.

## 1. Founder rulings this plan implements

- Search 1 asks Exa for **exactly** the number the human asked for (no multiplier).
- If short: search 2 with the **same** criteria for the missing number, excluding what was found.
- If still short: search 3 with **slightly looser** criteria (the existing relaxed rule: drop the
  criterion the strict search satisfied least often).
- Partial and unclear companies **count** toward the number.
- **Decision 1:** each top-up search is a **new webset** that excludes the earlier websets
  (`exclude: [{source: "webset", id}]`) — the only exclude form Exa accepts (live-proven
  2026-09-28), and no risk of Exa's default `behavior: override` replacing earlier results.
- **Decision 2:** "find more" always starts a **new run**, excluding everything earlier runs of
  the project found.
- A company **another project already has** is checked against this project's ICP and added to
  this project when found (counts toward the number).
- The website-domain check stays as it is.
- Agent instructions change only in **new versions**.

## 2. How a run works after the change

1. Compose: read the run's pinned ICP, the project's members, every company earlier discovery
   runs of this project recorded, the workspace's accounts (domain → id), and the webset ids of
   every earlier run of this project.
2. Search k (k = 1, 2, 3): ask `count = target − shown`, criteria per §1, `exclude` = this
   project's earlier websets + this run's earlier searches. `externalId = arv2-discovery:<run>:<k>`;
   before creating, look the webset up by that external id so a crashed attempt never buys twice.
   Record the search row before reading. Poll to `idle`, verify every company as it appears, drain.
3. Per company: verify the website (unchanged). Skip — no gates asked — if it is already in this
   project, or an earlier discovery run of this project already found it. If it is an account of
   another project, ask every gate against this ICP, write this run's fit, and add it to this
   project (no new account row). Otherwise as today (new candidate account).
4. `shown` can never exceed the target: Exa lists a company only once it matches every
   criterion (checked on stored responses), and each search asks for the shortfall only.
5. The money fix from `b5eab8961` applies to every search: a run that ends early cancels the
   running webset and prices what Exa found.

## 3. What changes where

- **Migration** (hash id, reversible): new `arv2_discovery_search` (run_id, ordinal, kind
  `strict|strict_topup|relaxed`, webset_id, external_id, count, criteria, excluded webset ids,
  found, analyzed, recall_estimate, status); backfill the existing runs' webset/search ids; drop
  `arv2_discovery_run.webset_id / strict_search_id / relaxed_search_id / relaxed_requested /
  strict_count`.
- `exa_websets_client`: `create` takes `exclude_webset_ids`; `get` by external id; non-2xx on
  create raises a typed refusal (today a 400 is silently read as success); `add_search` deleted.
- `discovery_driver`: the three-search loop; cross-project path; the skip rules; resume per
  search row.
- `discovery_launch`: run identity = the launching user action (`action_ref`), so each human ask
  is a new run and a retried turn is the same run; the CLI passes its own request key.
  `request_relaxed_pass`, the CLI's `--relaxed-pass`, and `CLUE_ARV2_DISCOVERY_STRICT_COUNT`
  (settings, `.env`, `.env.example`) are deleted.
- `discovery_store`: search-row transitions; `unapproved_domains` → "every company an earlier run
  of this project recorded".
- Reads: `read_discovery_run@2` output unchanged (`relaxed_requested` now means "the run used the
  relaxed search"); frontend status unchanged (`asked` = total asked across searches).
- Instructions (new versions only): stage0-interview v39, manual-* v12, head-of-abm v66 (built on
  v65), tool notes, `launch_arv2_discovery@1` description and replay identity text. (As built: no
  prompt v18 — the prompt names no manual path, so v17 stands.)

## 4. Design choices needing founder sign-off

1. Search 2 always when short (founder's wording), or only when Exa filled search 1 and our
   checks removed some (skips a search that would find nothing; saves minutes, not money).
2. The turn-budget bundle (head-of-abm v65, uncommitted) must be committed before v66 is built on
   it.
3. The deletions in §3 (old relaxed re-open path, the fixed-35 setting, the old webset columns).
4. The 30-minute wall clock applies per search, not per run (three searches can take longer).

## 5. Verification

Offline driver/client/launch tests for every path above; the migration up→down→up on a throwaway
DB; one live run at `target_count` 3 on the lane stack (founder-triggered, spends money).
