# `clue_research/identity/` — Identity Resolution

**Status:** implemented by M2 (ENG-100/106/112/118/124). M2.1 (`account_entity`/`contact_entity` + the entity store) has landed.

**Spec:** [`docs/specs/M02-identity-resolution.md`](../../../docs/specs/M02-identity-resolution.md)

Identity resolution as a service: dedup → record-link → canonicalize. The only place a free-text name becomes a resolved `entity_id` (conventions §2). Everything downstream keys on the ids this package returns.

## Modular boundary

`identity/` is **persistence-touching**: it owns the `account_entity`/`contact_entity` tables (M2.1) and writes/reads them through `db/`, and it reads/writes typed **claims** via `claimstore/` (M2.3 reads claims through `surviving_id`; M2.5 scopes claim reads by tenant). So it may import `core/`, `config/`, `obs/`, `db/`, and `claimstore/` — never a sibling *worker* package (resolvers/adapters/verification/scorers) and never a provider SDK or the `api/` app layer. Persistence follows the claim store's seam style: callers pass an `AsyncConnection`; no business SQL lives in `db/`.

> Note (M2.1): the earlier "may import only core/config/obs" line was scaffold prose from M0.1; it predated this package writing Postgres. The machine-enforced rule set — the `[tool.importlinter]` contracts in `pyproject.toml` — already permits `identity → db`/`claimstore`, and is the source of truth (run `make contracts`). The full rationale is in [`docs/specs/M00-foundations-and-shared-contracts.md` §M0.1](../../../docs/specs/M00-foundations-and-shared-contracts.md) and [`docs/specs/_conventions.md` §2](../../../docs/specs/_conventions.md).
