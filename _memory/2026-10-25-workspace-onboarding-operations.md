# 2026-10-25: Workspace onboarding operations (add, start, pre-flight, repair)

## Context

- **Branch:** `claude/onboarding-repair-routes-a187b5`, cut from `main` at `ab10fd287`.
- **Origin:** started from the session `seed-acc` (`local_fa6da6a8…`) after the 2026-10-23 Illumio
  incident. In that incident Exa returned 402, the OpenRouter key was disabled, every ingestion job
  still reported `succeeded`, and recovery was manual.
- **Founder approval (2026-10-25):** build the operator lifecycle in code, everything through API
  routes. The same day the founder added: matching scripts in `scripts/`, runnable from a
  production container.

## State

- **Spec drafted:** `docs/superpowers/specs/2026-10-25-workspace-onboarding-operations-design.md`.
- **Open decisions:** eight, D1–D8, in spec §8. A builder check has run; its corrections are folded into the spec. The founder must approve before any code is
  written.
- **Code written:** none so far.

## Verified facts (recon, 2026-10-25)

**Onboarding run status**
- `onboarding_run.status` already has `completed_with_gaps`. `finish_run` sets it when any step is
  `empty` or `failed` (`arv2/onboarding_store.py:457`).
- The setup screen treats `completed_with_gaps` as complete.

**Re-running steps**
- Step ids and the ICP turn id derive from the run id. Re-running a step therefore needs a new run.
- The narrow `customers` and `personas` run kinds already exist.

**Design ingestion jobs**
- Statuses and kinds are Postgres enums (`design_ingestion_status`, `design_ingestion_kind`).
- Website, PDF and upload jobs swallow description failures and still go `succeeded`
  (`jobs.py:186-247`, `pipeline.py:709`).

**Offering design jobs**
- Offering a design job is an in-process database write through the design tools
  (`_worker_design_tools`), not an HTTP call.
- So the brand-kit repair can be offered from any container that has the design code on its path
  (one image everywhere: `docker/backend/entrypoint.sh`).
- Only work inside a design-API request needs the design API, for example the synchronous
  `describe-assets` republish.

**Exa**
- Exa has no free balance endpoint. Its usage API needs an admin service key. The pre-flight
  therefore uses one 1-result search (about half a cent).

**Frontend status parsers**
- These parsers `.catch` unknown ingestion statuses to `running`, so a new status must be taught
  to them:
  - `apps/frontend/.../onboarding/data/setup.ts:22`
  - `brand-context/model/brand-kit-actions.ts:12`
  - `design-editor/engine/webDocuments.ts`
  - the clue-design editor's `webDocuments.ts`
  - `IngestConsole.tsx`

**Staff roles**
- No staff or platform-admin concept exists. "Operator" is a workspace role.

## Follow-ups

- After approval: write the plan, implement, run the scenario tests on a throwaway database, and
  commit locally. Never push.
- Never touch production or Illumio. The founder decides when to deploy and run.
