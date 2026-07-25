# `clue_research/profiling/` — Deep Profiling (modes M2/M3/M4)

**Status:** M8 in progress — the tiny seed (M8.2 part-1 / M8.5) has landed: the `account.resonance.*` and `contact.facet.*` field-classes (`fields.py`, `load_deep_profiling_pack`). Workers M8.1–M8.4 build on top.

**Spec:** [`docs/specs/M08-deep-profiling.md`](../../../docs/specs/M08-deep-profiling.md)

Pass B deep profiling: account profiling, `account.resonance.*`, committee discovery, contact profiling, and `contact.facet.*`.

## Modular boundary (M0.1 / ENG-101)

May import the shared base (`core/`, `config/`, `obs/`) **and the M1–M4 services** (`claimstore/`, `identity/`, `icp/`, `sources/`) — the Beat-0 independence contract bans only worker→sibling-worker edges (no importing another milestone package: `verification/`, `discovery_scoring/`, `durable/`, …). Components coordinate by reading/writing typed **claims** in `claimstore/`, not by importing each other; workers return claim-id references, not blobs. (The seed's `fields.py` registers field defs via `claimstore.load_pack`, exactly as `icp/packs.py` and `stage0/fields.py` do.)

The full machine-enforced rule set lives in
[`docs/specs/M00-foundations-and-shared-contracts.md` §M0.1](../../../docs/specs/M00-foundations-and-shared-contracts.md)
and [`docs/specs/_conventions.md` §2](../../../docs/specs/_conventions.md); the executable form is the
`[tool.importlinter]` contracts in `pyproject.toml` (run `make contracts`).
