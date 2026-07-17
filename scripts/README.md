# Module run-scripts

Standalone scripts to run each subsystem module against a local Postgres. Each script runs
**one** module and prints what it produced. They chain (each prints the ids the next needs)
but every script can also run on its own (the profiling scripts seed a demo entity if you
don't pass one).

| # | Script | Module | Entry point |
|---|--------|--------|-------------|
| 01 | `01_stage0_onboarding.py` | Stage 0 client onboarding | `stage0.reverse_profile` |
| 02 | `02_icp_synthesis.py` | ICP synthesis + confirm | `stage0.synthesize_icps` / `confirm_icp` |
| 03 | `03_find_accounts.py` | Account intake (import + identity), capped | `identity.insert_account_entity` |
| 04 | `04_account_profiling.py` | M2 account profiling | `profiling.profile_account` |
| 05 | `05_committee_discovery.py` | M3 committee discovery | `profiling.discover_committee` |
| 06 | `06_contact_profiling.py` | M4 contact profiling | `profiling.profile_contact` |

## One-time setup

```bash
make install     # create the venv + editable install (uses uv)
make db-up       # start Postgres+pgvector on localhost:5432 (user/pass/db = clue/clue/clue)
make migrate     # apply all migrations to head
```

That's it. The scripts register the field packs themselves (idempotent), so you don't run
anything else first.

## Environment variables

**For offline runs you need none.** The default DB DSN matches `make db-up` exactly, and the
LLM gateway drops to a deterministic stub when no key is set — which is what these scripts use.

| Variable | Needed? | Effect |
|----------|---------|--------|
| `CLUE_DATABASE_URL` | optional | DB DSN. Default `postgresql+asyncpg://clue:clue@localhost:5432/clue` (matches `make db-up`). Set only if your DB differs. |
| `CLUE_OPENROUTER_API_KEY` | optional | Unset → **deterministic stub gateway** (no live LLM). Set → real LLM for ICP synthesis / committee role inference. |
| `CLUE_SYNTHESIS_MODEL` | optional | OpenRouter model id for ICP synthesis. Unset → `anthropic/claude-opus-4-8`. |
| `CLUE_FIRECRAWL_API_KEY` | optional | Live official-site scrape for Stage 0 / deep fields. Unset → those tiers return nothing. |
| `CLUE_APOLLO_API_KEY`, `CLUE_ZOOMINFO_API_KEY`, `CLUE_BUILTWITH_API_KEY`, `CLUE_EXA_API_KEY`, `CLUE_PARALLEL_API_KEY`, `CLUE_DUNS_API_KEY`, `CLUE_CRM_API_KEY`, `CLUE_CLAY_API_KEY` | optional | Live deterministic / tier-4 resolvers. Unset → no live data from that provider. |
| `CLUE_REDIS_URL` | optional | In-flight locks; not used by these scripts. |

Set keys in a git-ignored `.env` (see `.env.example`) or export them in your shell.

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
uv run python scripts/01_stage0_onboarding.py --name "Acme Robotics" --website "https://acme.example" --client-id acme
uv run python scripts/02_icp_synthesis.py --client-id acme --client-entity-id <from 01> --kb-version 1
uv run python scripts/03_find_accounts.py --client-id acme --max-accounts 5
uv run python scripts/04_account_profiling.py --client-id acme --account-id <from 03> --tier high
uv run python scripts/05_committee_discovery.py --client-id acme --account-id <from 03> --tier high
uv run python scripts/06_contact_profiling.py --client-id acme --account-id <from 03> --contact-id <from 05> --tier high
```

Each script also runs standalone with sensible defaults (04/05/06 seed a demo account/contact
if you omit the ids), e.g. `uv run python scripts/04_account_profiling.py --tier high`.
Use `--help` on any script for its arguments.
