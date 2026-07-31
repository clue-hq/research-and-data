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
path and refuses a missing path, a directory, a non-UTF-8 file, an empty file, or more than 64 KB —
a refusal prints an error and returns you to the prompt with durable state untouched. The shared
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
