# Clue-HQ — Research & Data Subsystem

The trustworthy data layer for the AI-native ABM platform: it turns a client's ICP into a
prioritized, deeply-researched, **verifiable** view of target accounts and their buying committees.
Its atomic unit is a **typed claim with provenance** (value + source + evidence span + tier +
confidence + freshness) — never a free-text dossier. Research stops at *verified meaning* (raw
claims + a per-persona value narrative); everything downstream consumes that.

> **Start with the docs, not the code.** The architecture (the *why*) and the build specs (the
> *how/when*) are the source of truth; this README only orients you to them.

## Where things live

| Path | What |
|---|---|
| [`docs/architecture/`](docs/architecture/) | The architecture doc set — **read the overview first**, then substrate → staged-flow → Docs B/C/D. The *why*. |
| [`docs/specs/`](docs/specs/) | The build specs: 14 milestone-layers (M0–M13), 65 issues. [`_conventions.md`](docs/specs/_conventions.md) is the DRY backbone; [`README.md`](docs/specs/README.md) is the index. |
| `src/clue_research/` | The code, one sub-package per milestone-layer (see below). |
| `tests/` | Structure + dependency-contract tests. |

**Spec ↔ Linear backlink convention:** every issue in the Linear **Research Subsystem** project
maps 1:1 to a spec section and links to it by repo-relative path — e.g.
`docs/specs/M01-claim-store-and-merge-policy.md §M1.2`. Spec docs live under `docs/specs/`; nothing
authoritative lives only in Linear.

## Package layout (`src/clue_research/`)

One package per milestone-layer seam. Each has a `README.md` naming its owning milestone.

| Package | Milestone | Role |
|---|---|---|
| `core/` | M0.2 | **Shared kernel** — typed contracts (`Entity`, `Claim`, `FieldDef`, `Resolver`, `SourceManifest`). Imports nothing internal. |
| `config/` | M0.4 | Config + secrets + jurisdiction/use-class/posture policy skeleton. *Policy is data.* |
| `obs/` | M0.5 | Tracing skeleton — named spans + metric emitters. |
| `db/` | M0.3 | Postgres + pgvector connection + migrations. Sole source of truth. |
| `claimstore/` | M1 | Append-only claim store + `current_value` merge + field registry. **The shared substrate.** |
| `identity/` | M2 | Identity resolution — name → resolved `entity_id`. |
| `icp/` | M3 | ICP spec + research-schema compiler + packs + scoring rubric. |
| `sources/` · `resolvers/` · `adapters/` | M4 | Waterfall engine (provider-agnostic) · per-provider resolvers · per-source modality adapters. |
| `stage0/` | M5 | Reverse-profiling, ICP synthesis, import + hybrid entry scenarios. |
| `discovery_scoring/` | M6 | Mode-M1 discovery + Pass A scoring + tiering + checkpoint. |
| `durable/` | M7 | LangGraph orchestrator-worker + state machine + budgets. Temporal-shaped. |
| `profiling/` | M8 | Pass B deep profiling (modes M2/M3/M4) + resonance + facets. |
| `verification/` | M9 | Gates, corroboration, faithfulness judge, identity-binding, freshness. |
| `compliance/` | M10 | Jurisdiction, use-class, appropriateness/use gate, postures, DSAR. |
| `synthesis/` | M11 | Tier-4 LLM synthesis (Exa/Parallel) — added last, behind verification. |
| `narrative/` | M12 | Per-persona value narrative + `account_handoff` + provenance index. |
| `review/` | M13 | Human review surface, disposition capture, learning loop, cost surface. |
| `api/` | M5/M13 | FastAPI app layer (placeholder). **Nothing imports it.** |

## Modular boundaries — enforced, not trusted (M0.1)

The product's hard requirement is that any one component is replaceable without breaking its
neighbours. Five rules make that a machine-checked fact (the `[tool.importlinter]` contracts in
`pyproject.toml`, run by `make contracts` and in CI):

1. Every package may import the shared base `core/`, `config/`, `obs/` (layered `obs → config → core`)
   — plus `db/` (M0.3), the shared persistence layer (importable, not part of the layered base).
2. `core/` imports nothing else inside `clue_research`.
3. Resolvers / adapters / judges / scorers never import each other (workers coordinate through the
   claim store, returning claim-id references — not by calling siblings).
4. Only `resolvers/<provider>/` and `adapters/<source>/` may import a provider SDK — the provider
   name never leaks downstream (swapping Clay → direct APIs is a config/registry change).
5. Nothing imports the `api/` app layer.

## Type checking & validation

Two complementary layers (they are **not** alternatives):

- **mypy** — *static* ("compile-time") type checking across the whole repo; catches type bugs
  before the code runs. Run by `make typecheck`.
- **pydantic** — *runtime* data validation. The `core/` domain models (M0.2) are pydantic models, so
  claim invariants (`source_tier ∈ 1..4`, `confidence ∈ 0..1`, "no `evidence_span` ⇒ not promotable")
  are enforced when claims are built from untrusted sources — exactly where mypy can't help.
  The pydantic mypy plugin is enabled so the two reinforce each other.

## Quickstart

```bash
make install   # uv sync — venv + deps + editable install
make check     # format-check + lint + mypy + import-linter + tests (what CI runs)
make format    # auto-format and apply safe fixes
make help      # list all targets
```

Toolchain: **uv** (env + lockfile), **ruff** (format + lint), **mypy** (static types),
**import-linter** (modular boundaries), **pytest** (tests). Python ≥ 3.12.
