# 2026-06-18 — M0.1 repo & package structure + dependency rules (ENG-101)

## Goal
Implement the first roadmap issue: the modular monorepo skeleton + machine-enforced dependency
rules. Blocks all of M0 and the whole roadmap. Spec: `docs/specs/M00-foundations-and-shared-contracts.md §M0.1`.
Linear: ENG-101 (moved Todo → **In Progress**).

## Key design decision
Single **src-layout umbrella package `clue_research`** with one sub-package per milestone-layer,
NOT a uv workspace of ~15 separate distributions (15 empty pyproject.toml's = wrong for M0;
import-linter + the acceptance criteria are written around module-path contracts). Modularity is
enforced by import-linter contracts over module paths, not by separate dists.

## Toolchain (the M0.1 baseline)
- **uv** (env + `uv.lock`), Python pinned **3.12** (`.python-version`; system is 3.14).
- **ruff** (format + lint), **mypy --strict** (static "compile-time" types), **import-linter** (the
  5 modular-boundary contracts), **pytest** (structure + contract tests).
- **pydantic>=2.7** declared as a runtime dep NOW (user asked). Rationale recorded for them:
  mypy = static/compile-time whole-repo type checking; **pydantic = runtime data validation** for
  the `core/` domain models (M0.2) — enforces claim invariants (source_tier∈1..4, confidence∈0..1,
  "no evidence_span ⇒ not promotable") where mypy can't. They are complementary, not alternatives.
  `[tool.mypy] plugins=["pydantic.mypy"]` enabled. The MODELS themselves are M0.2, not M0.1.
- `make check` = the single gate (format-check + lint + mypy + lint-imports + pytest). CI
  (`.github/workflows/ci.yml`) runs the same; M0.6 extends CI (db/migration smoke, span smoke, evals).

## Package tree (`src/clue_research/`)
core(M0.2) config(M0.4) obs(M0.5) db(M0.3) · claimstore(M1) identity(M2) icp(M3)
sources+resolvers+adapters(M4) stage0(M5) discovery_scoring(M6) durable(M7) profiling(M8)
verification(M9) compliance(M10) synthesis(M11) narrative(M12) review(M13) · api(placeholder).
Each pkg = `__init__.py` (short docstring) + `README.md` (names its milestone + spec backlink +
boundary note). `py.typed` at umbrella root (PEP 561).

## The 5 import-linter contracts (in pyproject `[tool.importlinter]`, root_package=clue_research,
include_external_packages=true so external provider-SDK imports can be forbidden):
1. `forbidden`: core → any sibling (core imports nothing internal).
2. `layers`: obs → config → core (shared base ordering; obs uses config's redaction helper).
3. `independence`: resolvers, adapters, verification(judges), discovery_scoring(scorers) — workers
   never import each other.
4. `forbidden`: every pkg EXCEPT resolvers/ + adapters/ → provider SDKs (clay/apollo/zoominfo/
   builtwith/exa_py/parallel/firecrawl/simple_salesforce/hubspot). List illustrative; M4 finalizes.
5. `forbidden`: every pkg EXCEPT api → clue_research.api (nothing imports the app layer).

## Verification performed
- `make check` GREEN: ruff format+lint clean, mypy 21 files clean, import-linter **5 kept/0 broken**,
  **9 pytest pass**.
- **Negative-tested all 4 rule classes** (inject forbidden import → `lint-imports` reports BROKEN →
  revert): core→internal ✅, provider-SDK(`import firecrawl`) in claimstore ✅, resolvers→adapters ✅,
  narrative→api ✅. Clean tree then back to 5 kept/0 broken.
- import-linter auto-loads config from pyproject.toml (no `--config` needed; v2.11).
- `.venv`/caches/`.DS_Store`/`.env` correctly gitignored.
- Ran an adversarial review Workflow (4 lenses → verify) — wf_5e417a18-a29. 2 findings:
  - **F1 (claimed BLOCKER) — FALSE POSITIVE.** Both review+verify agents claimed the `layers`
    contract `["obs","config","core"]` was "backwards" and would block config→core / obs→config.
    Empirically DISPROVEN: config→core KEPT, obs→config KEPT, obs→core KEPT, core→config BROKEN —
    exactly intended. import-linter lists layers HIGH→LOW (first=highest, may import lower); the
    agents inverted it. Applying their "fix" would have inverted+broken M0.4/M0.5. Contract LEFT AS-IS.
    Lesson: always empirically verify a workflow finding before acting — and don't flip correct code.
  - **F2 (MAJOR, valid, applied) — spec clarity gap:** M0.1 Rule 1 named only core/config/obs but
    `db/` (M0.3) is shared persistence infra imported by M1/M2/M7… Implementation was already correct
    (nothing forbids db imports). Clarified the M00 spec (Rule 1 + Interface lines) and readme.md to
    name `db/` as importable-but-not-layered shared infra.

## State of files
- Modified: `readme.md` (was empty → full repo orientation + layout table + boundary rules + the
  type-checking/validation explainer).
- New (untracked): `pyproject.toml`, `uv.lock`, `.python-version`, `Makefile`, `.gitignore`,
  `.pre-commit-config.yaml`, `.github/workflows/ci.yml`, `src/clue_research/**`, `tests/**`.
- Throwaway scaffolders (`scaffold_packages.py`, `.context/_fix_inits.py`) were deleted after use.

## Open / follow-ups
- **Nothing committed/pushed** (standing rule: commit only on request). Offer: feature branch
  `shank/eng-101-...` + commit + PR `--base main`. Then move ENG-101 → In Review/Done.
- Provider-SDK forbidden list is illustrative — M4 must update import names to the real chosen SDKs.
- Negative/regression contract tests are intentionally deferred to M0.6 (manual negative-test done now).
- CI is minimal by design; M0.6 owns the full pipeline (Postgres+pgvector service, migration
  up/down/up smoke, span smoke, eval harness).
