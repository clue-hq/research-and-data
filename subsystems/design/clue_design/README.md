# clue-design (import name: `clue_design`)

The design subsystem's **platform-native substrate package** — owned by **design-integration
Part II** (docs/specs/design-integration-master-plan.md §Part II; frozen implementation contract:
`docs/specs/PD-part2-design-substrate.md`).

Scaffold (slice **D0**): empty-but-contracted. What lands here, by slice:

- **D1** — nothing (the `design_*` Alembic migrations live in the shared `alembic/` tree); this
  package gains the package-local lifecycle enums the migrations mirror.
- **D2** — the async Postgres DAL (the port of the merged design API's SQLite `Repository`),
  split per domain, behind the standard `ConnFactory` seam.
- **D3–D7** — concept-join helpers, storage adapters, and event emitters as those slices land.

Not this package: the merged design apps + Rust engine (`subsystems/clue-design/` — three-language
tree, its own doc set), and all composition (which happens at `platform/api/clue_api`).

Import contract (machine-enforced in the root `pyproject.toml`): `clue_design` imports only
`clue_core` / `clue_db` / `clue_config` / `clue_obs` / `clue_storage`. It never imports another
subsystem (independence), the execution planes (toolbelt/agents/execution/fleet/projections), the
gateway, locks, or the spine; nothing imports it except the api composition root (and, from D2,
the design apps).
