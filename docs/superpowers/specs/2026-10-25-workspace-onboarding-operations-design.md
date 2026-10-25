# Workspace onboarding operations: add, start, check, repair

Status: **approved by the founder, 2026-10-25.** The direction was approved earlier the same day:
build it properly in code, everything through API routes. Scope added the same day: every
operation also gets a script in `scripts/` that runs the same code, for use from a production
container.

Founder rulings on §8, 2026-10-25:

- **D1:** "for now let anyone call the api endpoint". The founder confirmed this means no sign-in
  at all (§8 D1).
- **D2–D8:** as recommended.
- **My calls in §8:** accepted.

## 1. Why

On 2026-10-23 the Illumio workspace was onboarded while two providers were broken.

- **Exa ran out of credit.** Every Exa call returned HTTP 402. Onboarding "finished" in 2 seconds
  with empty folders.
- **Then the OpenRouter key was disabled** (HTTP 401). The ICP turn failed. Product-catalog
  reconciliation failed. All 357 asset descriptions failed. The ad analyses and the ad-DNA card
  failed.
- **Every brand-kit ingestion job still said `succeeded`.** Nothing alerted anyone.

Recovery was painful for five reasons. Each one is a defect this work removes.

| # | What went wrong | Where |
|---|---|---|
| a | The kit backfill counts a *failed* description as already done, so it does nothing. | `lumen_ingestion/describe.py:380-386` |
| b | The only retry the product offers is one job per asset (the job itself accepts up to 200 targets, but the route sends one). The single ingestion coordinator runs them one at a time, about 45 s each, and every workspace's ingestion waits behind them. | `POST /assets/{id}/analysis/retry`, `lumen_api/asset_enrichment.py:123` |
| c | The ad-DNA card job id is fixed per harvest. A failed card can never be offered again without a new harvest. | `ad_library/auto_card.py:42-67` |
| d | Re-running onboarding never re-runs brand-kit ingestion. It skips whenever any ingestion job exists, failed ones included. | `platform/api/clue_api/brand_kit_ingestion.py:152-188` |
| e | Adding a workspace means piping a script over SSH into a worker container. Reaching the design API means `railway ssh` into platform-api. | `scripts/provision_additional_workspace.py` |

Illumio is still broken: 105 of 357 descriptions are ready, kit v1 has no descriptions, there is
no ad card and no ICP. It will be the first real use of this work, **after** the founder decides
to deploy and run it. This work does not touch production.

## 2. Goals, non-goals, anti-goals

**Goals**

1. **Four operator operations, each available as an API route and as a script** that calls the same
   function. The four: add a workspace to an existing login, start onboarding, check providers,
   repair a workspace.
2. **Check providers before spending.** Before onboarding starts, confirm that every provider it
   needs has a working key and credit. If one does not, refuse in plain words, before any run
   exists.
3. **Honest status.** A brand-kit job that finished with gaps says so instead of saying
   `succeeded`. The onboarding view lists each gap in plain words.
4. **Gap-driven, idempotent repair.**
   - Inspect the workspace and plan only what is missing.
   - A dry run shows the plan and an estimated cost.
   - Apply runs exactly that plan.
   - A second apply finds nothing to do.
   - Every apply is audited with who did it and why.

**Non-goals (this pass)**

- **"Restart fresh" re-extraction.** This means re-capturing the website and rebuilding the kit
  from zero. It is next, and §9 sketches it.
- **New screens.** No repair button and no "needs attention" panel. The designed frontend is the
  presentation truth. The routes are the contracts a future screen will use. The only frontend
  change is teaching the existing status parsers one new value (§5.3) so nothing breaks.
- **The setup screen's early exit on re-run** (`use-setup-progress.ts`). A separate card covers it.
- **Alerting**, for example paging someone when a provider goes down. The pre-flight and honest
  status make failures visible. A push alert is a separate piece.

**Anti-goals: things that would make this a failure even if it technically works**

- Repair that re-runs the whole ~$2 onboarding when only the ICP is missing.
- One description job per asset, which blocks every other workspace's ingestion.
- A second implementation of any operation in a script that drifts from the route.
- A pre-flight that itself spends meaningful money, or that lets a run start when a provider is
  known to be dead.
- Writing to production, or repairing Illumio, as part of building this.

## 3. The four operations

Each operation is **one Python function**. The route and the script both call it. Each function
has a dry-run form that writes nothing and returns what would happen, and an apply form.

### 3.1 Add a workspace to an existing login

- **Code.** It reuses `clue_auth.provision_additional_workspace` unchanged. That function already
  creates the workspace, its one brand and an owner membership. It also refuses a website that is
  not a URL, an email with no user or with several users, an inactive user, and a duplicate name.
- **Dry run.** The route runs it inside a transaction that it rolls back, exactly as the script
  does today. The response shows the user, the workspace name and the onboarding link it would
  create.
- **Apply.** Commits the same transaction, then writes the audit row (§6).
- **Duplicate.** Refused with `409 workspace_exists`, naming the existing workspace id.
- **Script.** `scripts/provision_additional_workspace.py` keeps its flags and output, and moves
  onto the shared operation so that it also writes the audit row. Its actor is
  `operator:<--operator name>`.

### 3.2 Start onboarding for a workspace

- **Code.** The body of today's `POST /onboarding` moves into one function,
  `start_onboarding(conn, workspace_id, domain, brand_id, requested_by_user_id, actor)`. It keeps
  today's rules: brand resolution (the given brand, or the workspace's only brand), the company
  name passed to the enqueuer, and the open-run 409. The existing browser route and the new
  operator route both call it.
- **Pre-flight first.** It runs the pre-flight check (§3.3). If a required provider fails, it
  refuses with `503 providers_unavailable` and the list of failures. No run row is created and
  nothing is spent.
- **Brand-kit ingestion is now gap-aware** (fixes **d**). `brand_kit_ingestion.ensure` no longer
  skips because *some* ingestion job exists.
  - **No kit at all:** when the newest kit-building job `failed` and no kit exists, `ensure`
    offers a new website ingestion. Without this, a workspace whose capture died, for example
    because the design API was down, would have no way back.
  - **A kit exists:** when the newest job is queued, running, `succeeded` or
    `succeeded_with_gaps`, `ensure` skips. A gapped kit is repaired, not re-captured, so nothing
    is captured twice by accident.
  - **This is my call. Check it.**
- **Who starts it.** Today an operator has to sign in *as the user* and open a link. The operator
  route lets an operator start it directly for the new workspace, with no sign-in (§8, D1).
- **Script.** `scripts/start_workspace_onboarding.py --workspace <id> [--domain d] [--apply]`.

### 3.3 Pre-flight: check providers

One function, `check_providers()`. It probes each provider onboarding needs, all in parallel, with
a 5-second timeout each, so the whole check takes about 5 seconds at most.

| Provider | Used by | Probe | Cost |
|---|---|---|---|
| OpenRouter, platform key (`CLUE_OPENROUTER_API_KEY`) | ICP and persona turns, catalog reconcile | `GET https://openrouter.ai/api/v1/key`. Returns whether the key is valid and how much credit is left. | free |
| OpenRouter, design key (`OPENROUTER_API_KEY`, falls back to the platform key) | asset descriptions, ad analysis, ad-DNA card, kit brief | the same call, made only when it is a different key | free |
| Exa (`CLUE_EXA_API_KEY`) | every onboarding research step | Exa has no free balance check. Its usage API needs a separate admin key and reports usage, not balance. So the probe is one 1-result search with no page contents, recorded on the provider ledger like any call. | about half a cent |
| Adyntel (`ADYNTEL_*`), People Data Labs (`PDL_API_KEY`) | ad harvest | Key present when the ad lane is on. Not called. | free |
| Design API (`CLUE_DESIGN_API_BASE_URL`) | brand-kit ingestion | reachable within the timeout | free |

**Outcomes per provider:** `ok`, `no_credit` (402, or OpenRouter reports 0 left),
`key_invalid` (401/403), `unreachable`, `not_configured`.

**What refuses:** OpenRouter (both keys), Exa and the design API are required. Any of them failing
refuses the start. The ad-lane keys only warn: the kit still builds without ads, and a later repair
can add the card. There is **no override flag**. A run against a dead provider is the thing this
exists to stop.

**How OpenRouter's credit is read** (checked against OpenRouter's docs, 2026-10-25):

- `GET /api/v1/key` says whether the key is valid. A disabled key gets a 401.
- It also gives the key's own spending cap (`limit_remaining`, null when uncapped) and any
  org budget (`effective_budget.remaining_usd`).
- It does not give the account balance. That is `GET /api/v1/credits` (`total_credits −
  total_usage`), which some sources say needs a management key.
- So the probe calls `/key`, then tries `/credits`. When `/credits` refuses, the balance is
  reported as "not readable with this key", and the check still passes on a valid key with
  headroom. **My call.**

**OpenRouter credit floor.** The check uses the smallest of those three figures, the balance, the
key cap and the budget, whichever are readable, and warns below a floor. **Exa reports no balance, so Exa can only fail outright, never warn about running
low.** New setting `CLUE_PREFLIGHT_OPENROUTER_MIN_CREDIT_USD`, default `5`. At or below the floor
it warns. At zero it refuses.

**Route.** The check is also its own read, scoped to a workspace:
`GET /ops/v1/workspaces/{workspace_id}/preflight`. It is scoped because the Exa probe's ledger row
needs a workspace to charge.

**Script.** `scripts/check_onboarding_providers.py`. It only reads, apart from the half-cent Exa
probe, so it has no `--apply`.

### 3.4 Repair a workspace

One function: `plan_repair(workspace_id) -> RepairPlan` and
`apply_repair(workspace_id, plan_digest, actor, reason)`. The plan has two halves, which run on
different machinery.

**A. Onboarding research and ICP (platform)**

- **Which run it reads.** The planner starts from the newest *full* onboarding run. Repair runs
  started after it are laid over it.
  - Each step, keyed by kind and subject, counts its **newest attempt** across that full run and
    every later repair run.
  - A repair run that is still queued counts its planned steps as **in flight**, even before
    their step rows exist.
  - The planner also reads the workspace's current knowledge documents.
  - The `gaps` list (§5.2) uses the same merge, so a repaired gap disappears.
  - **My call.**
- **Never two at once.** A repair is refused while a full run is open, and a full start is refused
  while a repair is open: `409 onboarding_in_progress` either way.
- **Who requested it.** `onboarding_run.requested_by_user_id` must name a user.
  - There is no signed-in caller (D1). So every route takes `operator_email` in its body, and
    every script takes it as `--operator-email`.
  - It must belong to an existing Clue user. It is stamped as the requester, and the actor is
    `operator:<email>`.
  - It is self-declared and not verified, so the audit trail records who the caller *said* they
    were.
  - **My call.** No schema change.
- **What counts as missing.** A step is missing when its newest attempt is `failed`, or when its
  document does not exist. An `empty` step is a correct outcome and is not repaired. For example,
  nobody could find reviews for the company.
- **Dependencies are planned with it:**
  - Redoing `lineup` also redoes `catalog_sync` and `product_research` for products that have no
    research.
  - Redoing the ICP step (`synthesis`) also redoes the `persona` steps.
  - If the ICP exists but its personas failed, only the personas are redone.
- **How it runs.** Apply creates one new onboarding run with `kind = 'repair'`. The run carries its
  list of planned steps. The existing onboarding fleet handler runs only those steps.
  - A new run id is needed anyway, because step ids and the ICP turn id are derived from the run id.
  - This follows the pattern of the existing narrow `customers` and `personas` runs.
  - New documents land as new versions, exactly as in a normal run.
- **What it costs instead.** Not the ~$2 full walk. Only the planned steps, for example about $0
  of Exa plus the ICP turn when only the ICP is missing.
- **Recorded on the run.** The repair run finishes as `completed` or `completed_with_gaps`, like
  any run. The newest *full* run stays the record of the original onboarding.

**B. Brand kit (design)**

- **What the planner reads, per workspace:**
  - description rows with `analysis_status` of `failed`, `stale` or `unsupported`. `unsupported`
    is listed in the plan but never re-run. It means the file type cannot be described.
  - kit assets that have no description row
  - whether the newest kit carries the descriptions that are now ready
  - whether a usable ad harvest exists and has no ad-DNA card
- **How it runs.** Apply offers **one** new design ingestion job, `kit_repair`, on the existing
  coordinator. It does three things in order:
  1. **Describe all planned assets as one batch** (fixes **b**). This is ad creatives as well as
     kit assets. It uses the existing enrichment fan-out: one coordinator job hands out one child
     task per asset to the 4 × 10 analysis slots, at the same concurrency as a normal ingestion.
     357 assets take a few minutes, not 4½ hours.
  2. **Republish the kit with the descriptions stamped**, as a new version, through the same
     publish tool ingestion uses. It is skipped when nothing new is ready.
  3. **Offer the ad-DNA card** from the existing harvest when it is missing (fixes **c**, below).
     The card is its own job, as today. Repair does not re-harvest.
- **Status.** The `kit_repair` job finishes `succeeded`, `succeeded_with_gaps` (some descriptions
  still failed) or `failed`.
- **No kit at all:** the plan has one item, "capture the website". Apply offers a website
  ingestion, the same rule `ensure` uses (§3.2), and nothing else in this half.
- **The kit backfill fix** (fixes **a**). In `describe_kit_assets`, only a `ready` description
  counts as cached. A `failed` row is a miss and is described again. The `POST
  /brand-kits/{id}/describe-assets` route keeps its synchronous, one-at-a-time loop and now heals.
  It is for a handful of assets. A large heal, like Illumio's 252, goes through repair. **My
  call:** the route is not capped and not redirected.
- **The ad card can be offered again** (fixes **c**). The card job id gains an attempt number:
  `card_job_id(ws, harvest, attempt)`.
  - Attempt 0 gives exactly today's id, so existing card jobs keep their ids.
  - Repair offers attempt *n + 1* only when no card exists for that harvest and no card job for it
    is queued or running.
  - The public route still refuses `phase: "card"`. Only repair and the automatic hook offer cards.

**The plan, dry run and apply**

- **Dry run** (default) returns:
  - every planned item with a plain-language reason, for example "ICP: the last attempt failed,
    OpenRouter refused the key"
  - items already in flight, which are not planned again
  - an estimated cost per item and in total
  - a `plan_digest`: a hash of the planned items
- **Apply** takes the `plan_digest` from the dry run.
  - It re-plans inside the apply. If the plan no longer matches, it refuses with
    `409 plan_changed` and returns the new plan. So apply runs exactly the plan that was shown.
  - It refuses `409 nothing_to_repair` when the plan is empty.
- **A second apply** finds the first apply's work queued or running. Those items are "in flight",
  so the plan is empty and it refuses `nothing_to_repair`. After that work finishes, a new dry run
  shows only what is still missing.
- **Estimated cost.** The estimate uses fixed per-item figures kept in one table in code, the way
  `exa_client.AGENT_EFFORT_ESTIMATE_USD` already does for Exa. Exa steps use their configured
  effort's figure. The ICP and persona turns use one figure each, taken from recent real turns when
  the table is written. Descriptions use a per-image figure. The estimate is labelled as an
  estimate. **My call: fixed figures, not a live ledger average.** That keeps it simple, and the
  figures are easy to correct.
- **Audit.** Every apply writes one audit row (§6) with the actor, the reason, the plan, the
  estimate, and the ids of the run and job it started.

**Script.** `scripts/repair_workspace.py --workspace <id> --operator-email <e> [--reason "…"
--apply]`. It is a dry run by default and prints the plan and the estimate. It is one script for
both halves (§7).

## 4. Where each piece runs

| Operation | In the request | Afterwards |
|---|---|---|
| Add workspace | database write, synchronous | nothing |
| Pre-flight | about 5 s of parallel probes, synchronous | nothing |
| Start onboarding | pre-flight, then the run row, the fleet task and the ingestion offer; returns at once | fleet worker (`onboarding_run`) and design coordinator, as today |
| Repair, dry run | database reads, both halves in-process | nothing |
| Repair, apply | re-plan, a `repair` run plus its fleet task, a `kit_repair` job plus its design task, the audit row; returns at once | fleet worker and design coordinator |

**The coordinator caveat.** The `kit_repair` job holds the single ingestion coordinator while its
children run, as a normal ingestion's description pass does today. For 357 assets on 40 slots that
is a few minutes, not hours. It does not fix the coordinator being single. That is a separate
change.

**The seam.** The platform may import the shared design data-access package, `clue_design`. It
already does: `brand_kit_ingestion.py` reads `clue_design.ingestion.list_recent`. What it may not
import is the design *app* code (`lumen_*`).

Offering a design job needs only two things, both already importable by the platform:

- `clue_design.ingestion.create_job`
- `clue_fleet.queue.enqueue_task`

That is all `lumen_ingestion.jobs.create_and_offer` does. So:

- **Planning.** The brand-kit planner lives in `clue_design`, beside the description and ad-card
  data access it reads. The platform's repair function calls it in-process.
- **Offering.** Apply offers the `kit_repair` job in-process, in the same transaction as the
  onboarding repair run and the audit row. One transaction means one plan, applied whole or not
  at all.
- **Running.** What the `kit_repair` job *does* — describing, republishing, offering the card —
  is design app code. It runs on the design coordinator, never in the platform.
- **No new HTTP routes.** The design API gets none, and repair does not need the design API to be
  reachable. (Recommended; see D7.)

## 5. Honest status

### 5.1 Brand-kit jobs

- **New status.** A new terminal status, `succeeded_with_gaps`, joins
  `queued | running | succeeded | failed`. This needs one migration, which adds the value to the
  `design_ingestion_status` enum.
- **When a job uses it.**
  - Website, PDF and upload jobs: when any description failed, or the brief or grammar audit
    failed.
  - Harvest jobs: when any ad's analysis failed.
  - Card jobs: when the distil failed or wrote no card.
  - Asset-enrichment jobs: in place of today's `failed` with `asset_enrichment.partial`. Some
    assets succeeded, so the job is not a failure.
- **What is *not* a gap.**
  - A harvest with no ads (`empty`) is a correct outcome, the same as an `empty` research step.
  - So is a harvest-phase job whose card step is `deferred`. Harvest always defers the card to
    its own job. The ad lane's `partial` label is set for exactly that reason, so it cannot be the
    test.
- **Gaps are listed.** Each job also stores a short list of its gaps in its evidence, for example
  `{"area":"descriptions","failed":252,"reason":"provider_refused:openrouter:auth_invalid"}`. The
  job DTO serves it as `gaps`.
- **Readers that change.** Every reader that tests for `succeeded` treats `succeeded_with_gaps` as
  *finished with a usable result*:
  - the card readiness checks in `auto_card.py`
  - `brand_kit_ingestion.read_newest_ingestion_job`
  - the design DTO
  - the reaper

### 5.2 The onboarding view (`GET /onboarding/current`)

- **Unchanged.** Run statuses stay as they are. `completed_with_gaps` already exists and is already
  set whenever a step is `failed` or `empty`.
- **New field: `gaps`.** It lists, in plain words, every failed research step, a failed ICP or
  persona step, and the brand-kit job's gaps, each with its failure code.
  - Failure messages are shown too, cut to 200 characters. Today only codes are served.
  - The frontend ignores the new field until a screen is designed for it.

### 5.3 The frontend's status parsers

**Required, not optional.** Without this change the new value breaks the screens. Two parsers
accept only `queued | running | succeeded | failed` and turn anything else into `running`, so a
gapped kit would spin forever. Two more places test for `succeeded` directly:

- `apps/frontend/src/features/onboarding/data/setup.ts:22` (parser)
- `apps/frontend/src/features/brand-context/model/brand-kit-actions.ts:12` (parser)
- `apps/frontend/src/features/onboarding/model/setup-items.ts`, which maps ingestion status to
  the checklist row
- `subsystems/clue-design/apps/editor/src/components/brand/IngestConsole.tsx:105,181`

Each learns `succeeded_with_gaps` and treats it exactly like `succeeded`. Nothing new is drawn.
`webDocuments.ts` is unchanged: it reads design *run* status, not ingestion status.

## 6. Audit

There is one new platform table, `workspace_operation`. **Alternatively, one table per operation;
see D4.**

| Column | |
|---|---|
| `operation_id` | uuid primary key |
| `operation` | `add_workspace` \| `start_onboarding` \| `repair` |
| `workspace_id` | |
| `actor` | `human:<user_id>` from a route, `operator:<name>` from a script |
| `reason` | required for `repair`, optional otherwise; CHECK non-blank when present |
| `plan_json` | what was planned (repair) or created (add) |
| `estimated_cost_usd` | |
| `onboarding_run_id`, `design_job_ids` | what it started |
| `created_at` | |

- **Design side.** The `kit_repair` job's request also carries the actor, the reason and the
  audit row's id, so the design job can be traced back from its own row.
- **Dry runs** write nothing.

## 7. Scripts and where they can run

All production containers run the same backend image, so every script is already deployed with
the code it needs. A script piped over stdin runs only that one file, so it imports everything
else from the image.

| Script | Calls | Runs from |
|---|---|---|
| `scripts/provision_additional_workspace.py` | 3.1 | a worker container (`vm-batch1-1`) or platform-api |
| `scripts/start_workspace_onboarding.py` | 3.2 | **platform-api only**: starting onboarding also offers brand-kit ingestion over HTTP to the design API, which is reachable only on Railway's private network |
| `scripts/check_onboarding_providers.py` | 3.3 | anywhere; the design-API reachability line says "unreachable" from the VM, by design |
| `scripts/repair_workspace.py` | 3.4, both halves | a worker container (`vm-batch1-1`) or platform-api |

**Why repair runs from the VM.** I verified that offering a design job is a database write, not an
HTTP call: `clue_design.ingestion.create_job` plus `clue_fleet.queue.enqueue_task`. `auto_card.py`
already offers jobs this way from a worker. The kit republish happens inside the `kit_repair` job
on the coordinator, never in the script, so the script needs no engine and no design API.

**The real constraint.** Only work that runs inside a design-API request needs the design API
itself:

- the existing synchronous `describe-assets` republish
- `brand_kit_ingestion.ensure`, which offers the website ingestion and ad harvest over HTTP

That is why the start-onboarding script must run on platform-api. The repair's "capture the
website" item does not need it: it offers the website job in-process, like the rest of repair.

**Runbook.** One runbook, `scripts/workspace_onboarding_operations.md`, sits next to the scripts.
It gives:

- the exact command for each environment: `ssh … docker exec -i vm-batch1-1 python -` for the
  worker scripts, and `railway ssh` into platform-api for the start-onboarding script
- the dry-run-then-apply order
- what each refusal means

## 8. Decisions for the founder

Each decision has my recommendation first.

**D1. Who may call these routes? Founder ruling 2026-10-25: anyone, with no sign-in, for now.**

What that means in the build:

- **The routes.** They live on their own router, `/ops/v1/…`, on the platform API, outside the
  signed-in `/frontend/v1` surface. They take the workspace id in the path. There is no principal,
  no membership and no permission check.
  - `POST /ops/v1/workspaces`: add a workspace. Body: `email`, `website`, optional
    `company_name`, `operator_email`, `apply` (default false).
  - `GET /ops/v1/workspaces/{workspace_id}/preflight`: check the providers.
  - `POST /ops/v1/workspaces/{workspace_id}/onboarding`: start onboarding. Body: optional
    `domain` (default: the workspace's website), `operator_email`, `apply` (default false).
  - `GET /ops/v1/workspaces/{workspace_id}/repair-plan`: the dry run.
  - `POST /ops/v1/workspaces/{workspace_id}/repair`: apply. Body: `plan_digest`, `reason`,
    `operator_email`.
- **The caller's name.** `operator_email` names an existing Clue user. It is self-declared, and it
  is what the audit row and the run's requester record (§3.4 A).
- **The risk, as the founder was told when choosing.** Anyone who can reach the platform API can
  add a workspace to any login and start paid onboarding or repair runs.
  - The guard rails that remain: pre-flight; one onboarding run at a time per workspace; repair
    plans only what is missing; every write is audited.
- **A kill switch. My call.** New setting `CLUE_OPS_ROUTES_ENABLED`, default `true`. When `false`,
  the router is not mounted and every `/ops/v1` path is a 404. Closing the routes is then an env
  change, not a deploy of new code. Sign-in can be added later without changing the operations,
  because they never read a principal.

**Options the founder did not take:** a staff allowlist plus owner/admin, owner/admin only, or a
staff table.

**D2. How should the brand kit report a partial result?**

- **(A) Recommended: the new `succeeded_with_gaps` status** (§5.1). It is honest everywhere. The
  cost is the migration and the three frontend parsers (§5.3).
- **(B) Keep `succeeded`, add a `gaps` field only.** Nothing changes for readers. But every screen
  keeps saying "succeeded", which is the dishonesty you asked to remove.

**D3. What does the brand-kit repair run as?**

- **(A) Recommended: one new design job kind, `kit_repair`** (describe, then republish, then offer
  the card). One row to watch, one status, one audit record. It needs a kind added to the design
  job enum.
- **(B) Extend the existing `asset_enrichment` job** with a "republish when done" option, and
  offer the card separately. There is no new kind, but the repair becomes two or three jobs to
  follow. `asset_enrichment` also caps at 200 targets, so Illumio's 357 would need two jobs.

**D4. Audit tables.**

- **(A) Recommended: one `workspace_operation` table** for all three operations (§6).
- **(B) One table per operation**, in the style of `arv2_research_job_resume`. This gives tighter
  columns, but three tables.

**D5. How does the onboarding half of repair run?**

- **(A) Recommended: a new onboarding run `kind = 'repair'`** carrying its planned steps. The
  existing handler runs only those. This needs one migration: the kind CHECK, plus a
  `planned_steps` column.
- **(B) Re-run the whole onboarding.** This is what exists today, and it is the ~$2 you ruled out.

**D6. Pre-flight strictness.**

- **(A) Recommended: refuse on any required provider, with no override.** Only the ad-lane keys
  warn.
- **(B) Warn only, and let the caller go ahead.**

**D7. How does the platform reach the brand-kit half of repair?**

- **(A) Recommended: in-process.** The planner lives in the shared `clue_design` data-access
  package. Apply offers the `kit_repair` job with `clue_design` and `clue_fleet` in one
  transaction (§4).
  - One function and one script, runnable from the VM.
  - No new design-API routes.
  - Apply is atomic across both halves.
- **(B) Over HTTP**, like `brand_kit_ingestion.ensure`: two new design-API routes (plan, apply).
  - The design half stays wholly inside the design app.
  - The platform's apply can no longer be one transaction.
  - The repair script only works through `railway ssh` into platform-api, or it becomes two
    scripts.

**D8. Does the pre-flight also guard a customer's own onboarding start?** Today a customer starts
onboarding with the browser's `POST /onboarding`.

- **(A) Recommended: yes.** Same function, same refusal.
  - The setup screen has no designed state for "a provider is down". It shows its existing
    generic failure state, and the user can try again later.
  - Each start pays one Exa probe, about half a cent. It is stamped on the provider ledger to the
    workspace.
  - A dead provider produces empty folders for a customer just as it did for Illumio, so failing
    honestly beats "finishing" in 2 seconds.
- **(B) No.** Operators only. Customers keep today's behaviour until a "provider down" state is
  designed.

**Unless you say otherwise, these are my calls:**

- the gap-aware `ensure` rule, including re-capturing when no kit exists at all (§3.2)
- fixed-figure estimates (§3.4)
- `unsupported` descriptions listed but never retried (§3.4 B)
- newest-attempt merge across full and repair runs, and never two runs at once (§3.4 A)
- the requesting user: the caller, or `--operator-email` for scripts (§3.4 A)
- the backfill route left uncapped (§3.4 B)
- reading OpenRouter's balance via `/key` then `/credits` (§3.3)
- what does and does not count as a brand-kit gap (§5.1)

## 9. Next, not in this pass: restart fresh

A `restart_fresh` repair mode would re-capture the website and rebuild the kit from zero, for a
kit that is wrong rather than incomplete. It would offer a new website ingestion and supersede the
old kit as a new version. It reuses this pass's plan, apply and audit machinery.

## 10. How it will be verified

Everything below runs on a throwaway database for this lane, with no real provider keys. Recorded
HTTP stubs stand in for Exa and OpenRouter, and a scripted model stands in for the ICP turn. Each
item is a scenario through the real routes, database and fleet handlers, not a unit test.

1. **The Illumio replay.**
   - Seed a workspace in Illumio's state: a full run whose ICP step failed with
     `provider_refused:openrouter:auth_invalid`; 252 of 357 descriptions failed; kit v1 without
     descriptions; a succeeded harvest with creatives and no card.
   - The dry run plans exactly: ICP plus personas; 252 descriptions as one job; the kit republish;
     the card.
   - Apply. The workers run the plan. The ICP exists, all 357 descriptions are ready, kit v2 carries
     the descriptions, and a card exists.
   - A second apply refuses `nothing_to_repair`. The audit row is there.
2. **Exa out of credit at start.** The stubbed Exa returns 402. Start onboarding refuses with
   `503 providers_unavailable`, and no run row exists. The same for a 401 from OpenRouter.
3. **Honest status.** An ingestion whose describer fails half the assets ends
   `succeeded_with_gaps`, with a `gaps` entry. `/onboarding/current` lists the gap. The card
   readiness check still accepts the kit.
4. **The backfill heals.** `describe-assets` on a kit with failed rows re-describes them and
   publishes a new version.
5. **The card is offered again.** After a failed card, repair offers attempt 1. Attempt 0's id is
   unchanged.
6. **Plan drift.** A dry run, then a description finishing, then apply with the old digest refuses
   `plan_changed`.
7. **Routes and the kill switch.**
   - The `/ops/v1` routes answer with no sign-in.
   - An unknown `operator_email` is refused with `422 operator_unknown`.
   - An unknown workspace id gets 404.
   - With `CLUE_OPS_ROUTES_ENABLED=false`, every `/ops/v1` path is a 404.
8. **Scripts.** A dry run writes nothing. `repair_workspace.py` runs without a design API
   configured. `--apply` has the same effect as the route, audit row
   included.
9. **Frontend.** The parser tests accept `succeeded_with_gaps`, and the frontend gate (`npm run
   design-system:build && npm run lint && npm run build`) passes.
10. **Design tests.** Named test files only, never the design test folder.
11. **Live proof, founder-triggered, spends money.** On a dev lane, start onboarding for a test
    workspace with a revoked key and see the refusal. Restore the key, break the ICP turn, repair,
    and see it finish.

## 11. New settings

Each goes into `.env.example`, with its default, when it is introduced:

- `CLUE_OPS_ROUTES_ENABLED=true`
- `CLUE_PREFLIGHT_OPENROUTER_MIN_CREDIT_USD=5`

## 12. Migrations

Hash ids, reversible, one head:

1. `onboarding_run.kind` gains `repair`, and the table gains a `planned_steps jsonb` column (D5).
2. The design ingestion job's status gains `succeeded_with_gaps` (D2), and its kind gains
   `kit_repair` (D3). Both are Postgres enum types (`design_ingestion_status`,
   `design_ingestion_kind`). Adding a value is one line. The downgrade has to rebuild each type
   without the value. Before that, it maps `succeeded_with_gaps` rows back to `succeeded` and
   refuses while any `kit_repair` job exists. The enum-parity tests guard the Python side.
3. The `workspace_operation` table (D4).
