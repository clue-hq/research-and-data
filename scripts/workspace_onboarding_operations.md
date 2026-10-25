# Workspace onboarding operations: runbook

This covers four operator jobs:

- adding a workspace to an existing login
- starting onboarding for it
- checking the providers onboarding needs
- repairing a workspace that onboarded while a provider was down

Each one is a script in this folder and an API route under `/ops/v1`. A script and its route call
the same code.

Spec: `docs/superpowers/specs/2026-10-25-workspace-onboarding-operations-design.md`.

## Before you start

- **Every script is a dry run unless you add `--apply`.** A dry run prints what would happen and
  writes nothing.
- **Every script names you with `--operator-email`.** It must be the email of an existing Clue
  user, normally your own login. It is recorded in the `workspace_operation` audit table and on
  any onboarding run you start. Nobody checks it, so give your real one.
- **Only the steps marked "spends money" cost anything.** The provider check spends about half a
  cent: it makes one small Exa search, recorded on the provider ledger.

## Where each script runs

All production containers run the same image, so every script is already deployed. A script piped
over stdin runs only that one file; everything else it needs comes from the image.

| Script | Run it on | Why |
|---|---|---|
| `provision_additional_workspace.py` | the worker VM or platform-api | database writes only |
| `check_onboarding_providers.py` | platform-api (the VM works, but its design-API line reads `unreachable`) | the design API is on Railway's private network |
| `start_workspace_onboarding.py` | **platform-api only** | starting onboarding asks the design API for the brand-kit ingestion over HTTP |
| `repair_workspace.py` | the worker VM or platform-api | both halves of a repair are database writes |

**On the worker VM**, run from this repo's root on your laptop:

```bash
ssh ubuntu@40.160.37.148 'sudo docker exec -i vm-batch1-1 python - <args>' < scripts/<script>.py
```

**On platform-api**: `railway ssh` into the platform-api service, then run
`python - <args> < /app/scripts/<script>.py`. The image keeps the repo at `/app`.

## 1. Add a workspace to an existing login

1. **Dry run.** It prints the workspace, brand and membership it would create, and the onboarding
   link.

   ```bash
   ssh ubuntu@40.160.37.148 'sudo docker exec -i vm-batch1-1 python - --email shank@cluehq.ai --website https://acme.com --company-name "Acme" --operator-email you@cluehq.ai --app-origin https://app.cluehq.ai' < scripts/provision_additional_workspace.py
   ```

2. **Apply.** Run the same command with `--apply` added at the end. The output shows the new
   workspace id; you need it for steps 2 to 4.

**Refusals:**

- `workspace_exists`: that login already owns a workspace with this name.
- `identity_conflict`: the email matches no user, several users, or an inactive user.
- `COMPANY_WEBSITE_REQUIRED`: the website is not an http(s) URL with a domain.

## 2. Check the providers

```bash
python - --workspace ws_… < /app/scripts/check_onboarding_providers.py
```

It prints one line per provider. `BLOCKS` means onboarding would be refused. The script exits with
1 when anything blocks.

| Outcome | Meaning | What to do |
|---|---|---|
| `ok` | works | nothing |
| `low_credit` | works, but OpenRouter credit is below `CLUE_PREFLIGHT_OPENROUTER_MIN_CREDIT_USD` | top up soon |
| `no_credit` | OpenRouter at zero, or Exa answered 402 or "out of credit" | top up |
| `key_invalid` | the key was refused (401/403), for example a disabled OpenRouter key | replace the key |
| `unreachable` | no answer, a 5xx, or any other Exa error | check the provider's status, and the network |
| `not_configured` | the key or URL is not set | set it |

Adyntel and People Data Labs (the ad harvest) are only checked for a key, and they never block. A
kit without ads is still a kit, and a repair can add the card later.

## 3. Start onboarding (spends money: about $2)

Run this on platform-api:

```bash
python - --workspace ws_… --domain acme.com --operator-email you@cluehq.ai < /app/scripts/start_workspace_onboarding.py
```

The dry run is the provider check. Add `--apply` to start. Starting runs the check again and
refuses before anything is created if a provider is dead.

The workspace owner can still start onboarding from the browser by signing in and opening the
link from step 1. That start runs the same provider check.

**Refusals:**

- `providers_unavailable`: the blocking providers are listed.
- `onboarding_in_progress`: a full or repair run is already open.
- `brand_unavailable`: the workspace does not have exactly one brand.
- `enqueue_failed`: the fleet queue was down. Try again.

## 4. Repair a workspace (spends money: the estimate is printed)

1. **Dry run.** It shows only what is missing:
   - research or ICP steps whose last attempt failed
   - asset descriptions to redo, as one batch
   - the brand kit to republish with descriptions stamped on it
   - an ad-DNA card to rebuild from the existing harvest
   - a website to capture again, when no kit exists at all

   It also shows anything still running ("waiting"), an estimated cost, and a digest.

   ```bash
   ssh ubuntu@40.160.37.148 'sudo docker exec -i vm-batch1-1 python - --workspace ws_… --operator-email you@cluehq.ai' < scripts/repair_workspace.py
   ```

2. **Apply.** Run the same command with `--reason "what happened" --apply` added. It plans again
   and applies that plan in one transaction. It writes:
   - one repair onboarding run, which re-runs only the failed steps
   - one `kit_repair` design job, which describes the assets, republishes the kit and offers the
     card
   - one audit row
3. **Watch.** The repair run shows on the workspace's onboarding view. The `kit_repair` job runs on
   the design ingestion coordinator; it takes minutes, not hours.
4. **Re-check.** Run the dry run again once the work has finished. It should show nothing to
   repair. A second `--apply` while the work is still running refuses `nothing_to_repair`.

**Refusals:**

- `nothing_to_repair`: nothing is missing, or the repair is already running.
- `plan_changed`: the workspace changed since the plan was made. Read the new plan and run again.
- `reason_required`: you applied without `--reason`.
- `operator_unknown`: `--operator-email` does not match a Clue user.

**What repair never does:**

- harvest ads again
- re-run the whole onboarding
- describe a file type that cannot be described (these are listed as "unsupported")
- capture a website again when a kit already exists. Re-extracting a kit from scratch is a
  separate, later mode.

## The same thing over HTTP

The routes need no sign-in (founder ruling, 2026-10-25). Setting `CLUE_OPS_ROUTES_ENABLED=false`
removes them.

| Route | Body |
|---|---|
| `POST /ops/v1/workspaces` | `{email, website, company_name?, operator_email, apply}` |
| `GET /ops/v1/workspaces/{id}/preflight` | none |
| `POST /ops/v1/workspaces/{id}/onboarding` | `{domain, company_name?, operator_email, apply}` |
| `GET /ops/v1/workspaces/{id}/repair-plan` | none |
| `POST /ops/v1/workspaces/{id}/repair` | `{plan_digest, reason, operator_email}` |

A refusal comes back as `{"detail": {"code", "message", …}}`.
