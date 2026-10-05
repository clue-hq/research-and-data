# Module run-scripts

Standalone scripts to run each subsystem module against a local Postgres. Each script runs
**one** module and prints what it produced. They chain (each prints the ids the next needs)
but every script can also run on its own (the profiling scripts seed a demo entity if you
don't pass one).

| # | Script | Module | Entry point |
|---|--------|--------|-------------|
| 00 | `00_stage0_trial.py` | Interactive Stage 0 deepagent trial | Recipe 0 / Head-of-ABM / governed Stage-0 tools |
| trial | `clue_trial.py` | HTTP-only Sumble acceptance CLI | local trial API + production Stage 0 / project run / C7 |
| 01 | `01_stage0_onboarding.py` | Stage 0 client onboarding | `stage0.reverse_profile` |
| 02 | `02_icp_synthesis.py` | ICP synthesis + confirm | `stage0.synthesize_icps` / `confirm_icp` |
| 03 | `03_find_accounts.py` | Account intake (import + identity), capped | `identity.insert_account_entity` |
| 04 | `04_account_profiling.py` | M2 account profiling | `profiling.profile_account` |
| 05 | `05_committee_discovery.py` | M3 committee discovery | `profiling.discover_committee` |
| 06 | `06_contact_profiling.py` | M4 contact profiling | `profiling.profile_contact` |
| 07 | `07_research_view_trial.py` | Read-only C7 production research-view inspection | `ProductionResearchViewComposer` |
| 08 | `08_seed_discovery_fixture.py` | Reproducible Stage-0 handoff for discovery tests | `trial.discovery_fixture.seed_insight_health_discovery_fixture` |
| 09 | `09_exa_websets_d2_canary.py` | Bounded live/replay Exa Websets D2 submit | `DurableExaWebsetSubmitter` |
| 10 | `10_exa_websets_d4_materialization.py` | Zero-provider-call D4 materialization/replay | `ExaWebsetsD4Materializer` |
| 11 | `11_exa_websets_d6_acceptance.py` | Bounded live/replay D6 production composition | `ComposingRunDriver` + durable Exa slices |
| 14 | `14_seed_insight_health_browser_fixture.py` | Authenticated Insight Health browser onboarding | `trial.browser_fixture.seed_insight_health_browser_fixture` |
| 16 | `16_official_site_c6_live.py` | Retained C6 Firecrawl lifecycle/replay canary | `OfficialSiteCrawlWorkHandler` |
| 18 | `18_official_site_c8_operator.py` | Body-free C8 progress inspection and fenced recovery | `PostgresOfficialSiteOperations` |

## One-time setup

```bash
make install     # create the venv + editable install (uses uv)
make db-up       # start Postgres+pgvector on localhost:5432 (user/pass/db = clue/clue/clue)
make migrate     # apply all migrations to head
```

That's it. The scripts register the field packs themselves (idempotent), so you don't run
anything else first.

## Environment variables

**For offline runs 01–06 you need none.** The default DB DSN matches `make db-up` exactly, and the
LLM gateway drops to a deterministic stub when no key is set. Script 00 is the exception: it is a
real agent-quality trial and requires `CLUE_OPENROUTER_API_KEY`.

| Variable | Needed? | Effect |
|----------|---------|--------|
| `CLUE_DATABASE_URL` | optional | DB DSN. Default `postgresql+asyncpg://clue:clue@localhost:5432/clue` (matches `make db-up`). Set only if your DB differs. |
| `CLUE_OPENROUTER_API_KEY` | optional | Unset → **deterministic stub gateway** (no live LLM). Set → real LLM for ICP synthesis / committee role inference. |
| `CLUE_SYNTHESIS_MODEL` | optional | OpenRouter model id for ICP synthesis. Unset → `openai/gpt-5.6-terra`. |
| `CLUE_FIRECRAWL_API_KEY` | optional | Live official-site scrape for Stage 0 / deep fields. Unset → those tiers return nothing. |
| `CLUE_APOLLO_API_KEY`, `CLUE_ZOOMINFO_API_KEY`, `CLUE_BUILTWITH_API_KEY`, `CLUE_EXA_API_KEY`, `CLUE_PARALLEL_API_KEY`, `CLUE_DUNS_API_KEY`, `CLUE_CRM_API_KEY`, `CLUE_CLAY_API_KEY` | optional | Live deterministic / tier-4 resolvers. Unset → no live data from that provider. |
| `CLUE_REDIS_URL` | optional | In-flight locks; not used by these scripts. |

Set keys in a git-ignored `.env` (see `.env.example`) or export them in your shell.

## Sumble-only end-to-end trial

The trial deliberately uses two terminal windows. The server owns all backend/domain imports and
durable state; the CLI is an HTTP client only.

Required `.env` entries:

```dotenv
CLUE_OPENROUTER_API_KEY=<your OpenRouter key>
CLUE_SUMBLE_API_KEY=<your Sumble key>
CLUE_TRIAL_ENABLED=true
CLUE_C7_RESEARCH_VIEW_READ_ENABLED=true
```

Start the local dependencies and server:

```bash
make db-up
make migrate
make redis-up
uv run python -m clue_api.trial_main
```

In the second terminal, verify the exact environment before creating a trial:

```bash
uv run python scripts/clue_trial.py doctor
uv run python scripts/clue_trial.py new
```

`doctor` must report `"ready": true`. Account admission itself is zero-provider-spend. Before the
first Sumble call the CLI prints Organizations (maximum 2 credits), Jobs (maximum 1 credit), and
whether confirmed Tech Stack is skipped. Tech Stack has no caller-bounded maximum and runs only
after its separate explicit opt-in. A second human confirmation admits the direct account to deep
research after the durable tier checkpoint.

Resume or inspect without repeating provider spend:

```bash
uv run python scripts/clue_trial.py resume <trial-id>
uv run python scripts/clue_trial.py status <trial-id>
uv run python scripts/clue_trial.py report <trial-id> --output /tmp/clue-trial-report.json
```

The API exports the non-authoritative inspection bundle under
`.context/sumble-trials/<trial-id>/`; Postgres and artifact storage remain authoritative.

## Sending a multi-line message (both interactive CLIs)

`00_stage0_trial.py` and `clue_trial.py` read **one line per turn**, so pasting a multi-paragraph
product brief straight into the prompt splits it across several turns (repeated questions, wasted
model calls). Two commands send a block as a **single** message:

| Command | Behaviour |
|---------|-----------|
| `/paste` | Reads lines until a line containing only `.` (or Ctrl-D), then sends them as one turn. |
| `/file PATH` | Sends the contents of a UTF-8 text file as one turn. |

Blank lines and indentation inside the block are preserved; only the outer whitespace is trimmed. A
pasted line starting with `/` is content, not a command. `/file` accepts a quoted or `~`-prefixed
path and refuses a missing path, a directory, a non-UTF-8 file, an empty file, or more than 16 KB —
a refusal prints an error and returns you to the prompt with durable state untouched. The 16 KB cap
is set by Stage-0 routing, not by the API: your message is the turn the agent must read and quote
offsets into, so it has to fit the turn's context budget. (It used to be tighter still — the agent
had to echo your message back byte-identically into `record_interview_answer`; PC-C8 moved that
body engine-side, so the echo is gone but the cap stays.) The shared
implementation is `scripts/cli_multiline.py` (stdlib-only, so `clue_trial.py` stays HTTP-only).

## Offline vs. live — what you actually see

Offline (no keys) the scripts exercise the **full plumbing** — planning, fan-out, identity
resolution, the verification/governance tagging, claim writes — but most field **values**
come back empty or stub, because there's no live source behind them. Empty, flagged fields
are a correct output of this system; the scripts print statuses, counts, costs, and claim
refs so you can see the module ran. To get real research values, set the relevant provider
key and re-run. (Scripts 05 and 06 bind a tiny inline demo source/resolver so the
committee/contact path shows real, governed claims even offline; everything downstream of
that stand-in is the real implementation.)

## Run the chain

```bash
uv run python scripts/01_stage0_onboarding.py --name "Acme Robotics" --website "https://acme.example" --workspace-id acme
uv run python scripts/02_icp_synthesis.py --workspace-id acme --client-entity-id <from 01> --kb-version 1
uv run python scripts/03_find_accounts.py --workspace-id acme --max-accounts 5
uv run python scripts/04_account_profiling.py --workspace-id acme --account-id <from 03> --tier high
uv run python scripts/05_committee_discovery.py --workspace-id acme --account-id <from 03> --tier high
uv run python scripts/06_contact_profiling.py --workspace-id acme --account-id <from 03> --contact-id <from 05> --tier high
```

Each script also runs standalone with sensible defaults (04/05/06 seed a demo account/contact
if you omit the ids), e.g. `uv run python scripts/04_account_profiling.py --tier high`.
Use `--help` on any script for its arguments.

Script 07 is intentionally different: it never seeds data and never performs acquisition. Supply
the exact workspace/project/project-run/account-or-contact IDs produced by a normal governed
research run. It then composes the persisted state through the same production readers used by the
API. See `docs/runbooks/research-views.md` for the Exa-first inspection sequence.

## Insight Health authenticated browser fixture

Script 14 first provisions the signed-in Clerk subject, its active owner membership, the Insight
Health workspace and brand, and the Aura AI product. Without a project id it deliberately creates
no project, Client KB, ICP, or research run. After Home creates the project, pass ``--project-id``
to materialize the recorded official-site Client KB that completed onboarding would have produced:

```bash
uv run python scripts/14_seed_insight_health_browser_fixture.py \
  --database-url postgresql+asyncpg://clue:clue@127.0.0.1:5432/clue_lane_f_browser \
  --provider-subject user_from_the_authenticated_browser \
  --project-id prj_created_from_home
```

With ``--project-id``, the script captures four bounded Insight Health official-page artifacts,
writes seven evidence-backed product-scoped Client-KB claims through ``reverse_profile``, and
appends website/client/product onboarding receipts to that project. The original captured turn
remains immutable. It still creates no ICP or research run, so ICP synthesis and locking remain the
browser journey under test. Repeating the command with the same subject/project is a zero-change
replay. A stable fixture id that already names incompatible state fails loudly.

## Insight Health/Aura discovery fixture

Script 08 builds the already-confirmed Stage-0 side of the account-discovery acceptance setup. It
does not scrape or call a provider during seeding: first harvest the required public pages into the
two default `.firecrawl/*.json` paths, create a dedicated database, migrate it, and run:

```bash
uv run python scripts/08_seed_discovery_fixture.py \
  --database-url postgresql+asyncpg://clue:clue@127.0.0.1:5432/clue_discovery_fixture
```

It captures the page bodies into the configured artifact store, writes tier-2 unverified
official-site claims, confirms the Aura neurosurgery ICP, evaluates discovery readiness, and leaves
the durable project run at `discovery`. The default reference bundle is written under
`.context/discovery-fixtures/insight-health-aura/`; Postgres and the artifact store remain
authoritative. Repeating the exact command reuses the same claims, ICP, context, decision, and run.

## Exa Websets D2 canary

Script 09 consumes the named Stage-0 fixture and submits exactly one two-company Webset with no
paid enrichment (20-credit maximum). It requires an explicit observation window. The first paid
create is disabled unless `--allow-live-create` is present:

```bash
uv run python scripts/09_exa_websets_d2_canary.py \
  --database-url postgresql+asyncpg://clue:clue@127.0.0.1:5432/clue_discovery_fixture \
  --observation-window 2026-08-02-d2-live-v2 \
  --generation 2 \
  --allow-live-create
```

Repeat the command without `--allow-live-create` in a fresh process. A successful replay reports
zero create and lookup calls and returns the same request fingerprint, operation id, provider id,
and artifacts. A terminal attempt also replays without network I/O; retrying it requires a
separately approved observation/generation rather than changing the old row.

The configured Exa team must have Websets API access. A key that can use the web application but
not the Websets API returns a durable, known-not-charged terminal failure and does not satisfy the
D2 success gate.

## Exa Websets D4 materialization

Script 10 consumes only an existing D3-terminal batch and its immutable filesystem artifacts. It
does not construct an Exa client or read an API key, so both the first D4 run and replay make zero
provider calls:

```bash
uv run python scripts/10_exa_websets_d4_materialization.py \
  --database-url postgresql+asyncpg://clue:clue@127.0.0.1:5432/clue_discovery_fixture \
  --batch-id <D3-terminal-discovery-batch-id>
```

The first run reports created claims and admission/field-resolution summaries. Repeating it in a
fresh process must report `outcome=replayed`, `claims_created=0`, stable claim ids, and
`provider_calls_this_process=0`. D4 stops at `seal_pending`; D5 owns the actual batch seal.

## Exa Websets D6 production-composition acceptance

Script 11 consumes the Insight Health/Aura fixture from script 08 and drives the production
composition through durable acquisition, reconciliation, D4 materialization, D5 seal, the explicit
no-numeric-score selection mode, and the human tier checkpoint. It permits one two-row live create
only with `--allow-live-create`; email and phone remain disabled unless
`--include-contact-enrichments` is also supplied.

```bash
uv run python scripts/11_exa_websets_d6_acceptance.py \
  --database-url postgresql+asyncpg://clue:clue@127.0.0.1:5432/clue_d6_acceptance \
  --storage-root .context/discovery-fixtures/d6-acceptance/artifacts \
  --allow-live-create \
  --output .context/discovery-fixtures/d6-acceptance/d6-live-report.json
```

Run it again in a fresh process with `--replay-only` and without `--allow-live-create`. The replay
must return the identical sealed account set while every provider-call counter remains zero.

The runner does not manufacture a passing account. If all live rows satisfy the Exa criteria but
have mandatory field gaps, it leaves the project paused with `held_for_waterfall`. A selected row
is approved into deep research only when every required criterion is `yes`, every required field is
resolved, and the human checkpoint approves it.

Production deployments separately enable reconciliation and new paid acquisition:

```dotenv
CLUE_EXA_WEBSETS_LIFECYCLE_ENABLED=true
CLUE_EXA_WEBSETS_ACQUISITION_ENABLED=true
```

Keeping acquisition false while lifecycle is true drains existing work without allowing new
Webset spend. Acquisition fails closed when the lifecycle worker or API key is absent.

Provision the single team-level webhook separately after the projections service has a public URL:

```bash
python scripts/12_exa_websets_webhook_provision.py \
  --url https://api.example.com/v1/webhooks/exa-websets \
  --secret-output .secrets/exa-websets-webhook.env
```

On first creation, move the mode-0600 output into the deployment secret manager as
`CLUE_EXA_WEBSETS_WEBHOOK_SECRET`. The command never prints the secret. Re-running against the
same active URL/events is a zero-change replay; it refuses drift or multiple managed endpoints.

## Official-site C4 live canary

Script 15 performs one real Firecrawl single-page scrape and runs it through the C4
prepared/dispatched/receipt/artifact/snapshot protocol. Point it only at a fresh migrated database
and a dedicated artifact root that can be retained for review:

```bash
CLUE_DATABASE_URL=postgresql+asyncpg://clue:clue@127.0.0.1:5432/clue_c4_acceptance \
CLUE_C4_ARTIFACT_ROOT=/tmp/clue-c4-live-artifacts \
uv run python scripts/15_official_site_c4_live.py
```

The default Firecrawl mode reads `CLUE_FIRECRAWL_API_KEY` from the environment and prints only
durable IDs, states, call/blob/snapshot counts, receipt key names, and hashes. It never prints
credentials, raw receipts, or captured page bodies. Keep the named database and artifact root
until review is complete. Set `CLUE_C4_PAGE_FETCHER=scrapling` to run the same retained canary
through the credit-free pinned local adapter without a Firecrawl key; the default is `firecrawl`.

## Official-site C6 live lifecycle canary

Script 16 creates a new self-serve fixture in a dedicated migrated database, executes the
production shadow handler against `https://insighthealth.ai/`, and immediately cold-replays it. It
refuses any database whose name does not contain `c6`, requires an explicit confirmation variable,
and prints only IDs, hashes, phase states, and aggregate counters.

```bash
CLUE_DATABASE_URL=postgresql+asyncpg://clue:clue@127.0.0.1:5432/clue_c6_acceptance \
CLUE_C6_ARTIFACT_ROOT=/tmp/clue-c6-live-artifacts \
CLUE_C6_LIVE_CONFIRM=1 \
uv run python scripts/16_official_site_c6_live.py
```

If the first execution reports `recovery_pending`, retain the database/artifact root and wait for
the printed run's lease window to expire. Resume the **same** recon rather than seeding another:

```bash
CLUE_C6_REPLAY_WORKSPACE_ID=<workspace-id> \
CLUE_C6_REPLAY_RECON_RUN_ID=<recon-run-id> \
CLUE_DATABASE_URL=postgresql+asyncpg://clue:clue@127.0.0.1:5432/clue_c6_acceptance \
CLUE_C6_ARTIFACT_ROOT=/tmp/clue-c6-live-artifacts \
CLUE_C6_LIVE_CONFIRM=1 \
uv run python scripts/16_official_site_c6_live.py
```

The final replay must retain one crawl run, stable checkpoint IDs, and an attempt delta of zero.
Keep the isolated database and artifact root until the evidence has been reviewed.

## Official-site C8 inspection and recovery

Script 18 reads the C8 rows/events projection without loading page bodies or full provider
receipts. It requires an explicit database URL, workspace, and crawl run; no defaults can point an
operator at an unintended tenant.

```bash
uv run python scripts/18_official_site_c8_operator.py \
  --database-url postgresql+asyncpg://clue:clue@127.0.0.1:5432/clue_c8_acceptance \
  --workspace-id <workspace-id> \
  --crawl-run-id <crawl-run-id> \
  inspect
```

Mutation commands require exact repeated IDs. `reclaim-expired` uses DB time and routes an
already-dispatched call to reconciliation rather than fetching again. `quarantine-spend-unknown`
also requires the expected lease generation and can only settle an unleased matching ambiguity;
it never calls a provider. See
[`docs/runbooks/stage0-official-site-crawl.md`](../docs/runbooks/stage0-official-site-crawl.md) for
the production decision sequence and safety boundaries.

## Production-context broad release gate

Script 19 runs the full backend suite and compares every observed failure with the exact reviewed
S3-S6 release quarantine. It does not skip or mark tests as expected failures. A new failure or a
repaired test that remains in the manifest both fail the command so the baseline cannot silently
grow or become stale. Point `CLUE_DATABASE_URL` at a fresh, migrated, disposable database first:

```bash
uv run python scripts/19_production_context_release_gate.py --run
```

An already-produced JUnit result can be audited without rerunning tests:

```bash
uv run python scripts/19_production_context_release_gate.py \
  --junit /path/to/broad-suite.xml
```

The reviewed owners, reasons, removal conditions, and 32-node baseline live in
`tests/fixtures/production_context/release_broad_quarantine.json`.

## Fleet lease-spin replay

`fleet_lease_spin_replay.py` replays the 2026-10-05 incident in which ARV2 quality continuations
queued behind a running one were re-claimed every poll (one task 883 times in four minutes). It
runs the real fleet worker, queue and work leases — 4 workers × 3 slots at production timings —
with a stand-in reconciliation (a sleep, no LLM, no provider calls) and a stand-in quality sweep,
then prints claims, hand-backs, the most live tasks on the lease, attempt counts and catch-up
time as JSON. About two minutes per run.

It needs an explicit, migrated, **throwaway** database and refuses one whose `fleet_task` holds
anything but earlier replays' rows, since a running stack there would claim the replay's tasks:

```bash
docker run -d --name clue-pg-replay -e POSTGRES_USER=clue -e POSTGRES_PASSWORD=clue \
  -e POSTGRES_DB=replay -p 127.0.0.1:55171:5432 pgvector/pgvector:pg16
CLUE_DATABASE_URL=postgresql+asyncpg://clue:clue@127.0.0.1:55171/replay uv run alembic upgrade head
uv run python scripts/fleet_lease_spin_replay.py \
  --dsn postgresql+asyncpg://clue:clue@127.0.0.1:55171/replay --label with-fix
```

`--offer old` offers a new task per revision even on the fixed queue, which isolates the worker's
held-lease safety net. To measure a commit from before a change, check it out with
`git worktree add` and run this file's path from inside that checkout. First results (before vs
after the fix): `_memory/2026-10-05-fleet-lease-spin-fix.md`.
