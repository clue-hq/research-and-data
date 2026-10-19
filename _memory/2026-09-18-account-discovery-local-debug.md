# Local account discovery debug — 2026-09-18

- The Clue project's two discovery attempts failed with `arv2_discovery_not_composed`;
  no discovery run was created. Its ICP was already approved and pinned. Root `.env` and
  `.env.example` both disabled `CLUE_ARV2_DISCOVERY_ENABLED`. Enabled both; retained the
  existing Exa credential, strict candidate count, database, workspace bindings and models.
- The uploaded text was stored, but `submit_ingestion` failed before invocation with
  `IncompatibleRecipe`. Recipe #0 supplies an ingestion-policy version pin; the dynamic
  tool supplies the same version plus its content hash. `CompatibilityLoader` incorrectly
  rejected these compatible constraints as `conflicting_requirement`.
- Loader now combines compatible version/digest requirements before resolution, preserving
  the strongest required flag. Conflicting versions or hashes still refuse. Regression tests
  cover both orders, missing required resources, changed content, and conflicting hashes.
- Verification: four new parametrized cases failed before the fix; focused execution/graph/
  model/recipe-wiring/ingestion checks passed afterward (one DB-dependent test skipped).
  Ruff check and format check passed. A read-only replay of the exact failed upload's stored
  parameters and original recipe requirements passed against the local DB. The pinned ICP
  verified and compiled; the configured discovery handler constructed successfully.
- Reloaded only the two local platform APIs and four idle fleet workers after checking the
  queue. All four frontend workspaces remained authenticated after browser reloads. No auth
  bypass, migration, workspace creation, model call, ingestion, or paid discovery run performed.
- Operational pitfalls: `db_lifespan()` alone does not load root dotenv; an initial read-only
  preflight used the default DB and failed on a missing table. Loading the root environment
  before the same read passed. The local process helper exits after status, so importing it
  with runpy cannot be used to execute further maintenance; use its verified process matcher.
- Remaining: retry the user's search and ingestion through the normal authenticated chat to
  validate downstream provider results. The existing strict long-list count is 35 even for a
  five-account target; left unchanged. UI's generic "Complete a project step" label obscures
  which tool failed, and the old response incorrectly said it started a search that was refused.
