# `clue-spine` — the Phase-A object spine

**Status:** Phase A3.2 (`docs/specs/PA-phase-a-restructure-and-spine.md`; founder-ruled 2026-07-17,
multi-brand amendment 2026-07-24).

The platform's object spine: a **workspace owns multiple brands and projects; a brand owns its
products; each project selects exactly one brand from its own workspace**. Every subsystem hangs
off these ids (`workspace_id` is the tenancy column everywhere post-A3.1);
`project_run.project_id` ties execution to the spine (runs execute *for* a project). Scope-enum
vocabulary uses **`project`** per the harness doc's §1a terminology ruling: a *project* is the
end-to-end ABM motion; a *campaign* is a channel program within it.

Plain code by design (founder ruling): frozen pydantic row models + async CRUD functions over
`AsyncConnection` in the repo's raw-SQL style — **no protocol, no repository layer** (one
implementation will ever exist). Invalid states are impossible via schema constraints: composite
FKs pin products and projects to brands in the *same* workspace. Constraint violations surface as
raw `IntegrityError`, deliberately uncaught.

Imports `clue-core` + `clue-db` only (enforced by import-linter).
