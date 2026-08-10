# 2026-08-07 — Design subsystem merged into the monorepo (Part I / Step 1)

## What happened
The design subsystem repo (**`clue-design`** / *havana*) was merged into this platform
repo (`research-and-data`) with **full history preservation**. It now lives under
**`subsystems/clue-design/`**. This is **Part I, Step 1** ("the merge") of the
authoritative plan **`docs/specs/design-integration-master-plan.md`** (ADOPTED 2026-08-03).
The merge is **already on `origin/main`** (via PR #40, canonical branch
`platform/monorepo-merge-v1`). Verified: `HEAD == origin/main` (0 ahead / 0 behind) on the
work branch `platform/design-integration`.

Only the **repo union** is done. Parts II–IV are **not started** (see plan §3):
- **Part II — substrate adoption:** design SQLite → platform Alembic/Postgres, `workspace_id
  NOT NULL` + `design_`-prefixed tables, brand-spine/account-entity joins, content-addressed
  storage, runs onto the platform fleet, writes through the toolbelt, events onto the
  `run_event` stream. Not begun.
- **Part III — agent integration:** the design deepagent as a **LangGraph-wrapped subagent**
  under the platform deepagent, three-node leg graph (design agent → HITL `interrupt` → END),
  Postgres checkpointer, engine-validated `finish_design_leg(reason=locked|out_of_scope|
  abandoned)` exit, message routing on graph state. **Gated behind C8** (context-assembly
  dependency). Not begun.
- **Part IV — surface integration:** extract the editor core as a package, mount it in the new
  platform shell, `focus_refs` canvas context per turn, passive speaker indicator. Not begun.

## Key merge facts (so nobody re-derives them)
- **Location:** `subsystems/clue-design/` — a self-contained tree with its own Rust crates
  (`crates/`), `apps/api` + `apps/agent_runtime` + `apps/editor`, `py_lumen_obs`,
  `py_lumen_config`, `docs/`, and its **own `AGENTS.md` + `CLAUDE.md`** (binding for design
  work; note the engine/wasm **handshake rule** in that `CLAUDE.md` — rebuild wasm +
  `lumen-api-helper` and verify the handshake whenever `crates/lumen-core/` changes).
- **History tracking works natively:** `git log subsystems/clue-design/…` and `git blame`
  (`--follow` for pre-merge renames) walk to the original authors/dates/messages. The
  **design-only ancestry** is anchored by the **second parent** of the merge commit
  **`3ab4a750`** (= `3233b0d9…`). NOTE: the plan's `design-import` **tag was NOT created** —
  use the second-parent commit as the anchor (only tags present: `inflection-point`,
  `phase-c1-coverage-goal-judge-v1`).
- **Walled off pending Step-2 hygiene:** `pyproject.toml` carries
  `[tool.uv.workspace] exclude = ["subsystems/clue-design"]` (line ~20) and ruff
  `extend-exclude = ["subsystems/clue-design"]` (line ~27). The design apps are **not** uv
  members yet; `make check` does not lint/format them yet. The platform pipeline is untouched.
- **Platform history was never rewritten** — platform commit hashes are hash-identical;
  in-flight platform branches (C8, etc.) survived untouched. Only the *design* history was
  rewritten (heavy-artifact strip + `--to-subdirectory-filter`) on disposable clones.
- **Merge-day commit series on the branch:** `3ab4a750` merge (landed first as `design/`,
  later renamed to `subsystems/clue-design/`) → `d62b88ed` add the master plan + pyproject
  exclude → `adc472f4` gitignore local-only heavy artifacts → `35512eef` restore two
  `docs/*.png` (stripped by an over-broad `*.png` glob — `*` matches across `/` in
  filter-repo `--path-glob`) → `3ed5aae0` ruff-exclude clue-design.

## Executed-as deviations from the plan script (recorded in the plan itself, §3 Step 1)
- Relocation ran in **two steps** (`design/` then `--force --path-rename design/:subsystems/
  clue-design/`), not the single-pass `--to-subdirectory-filter` in the script. Same end state.
- The **heavy-artifact strip ran after** the merge branch's first push, branch-scoped
  (`filter-repo --force --refs refs/heads/<branch> --invert-paths …` on a fresh clone) + a
  force-push of that branch only; `main` never rewritten.
- **Lesson:** `platform/monorepo-merge-v1` was a Conductor fork of the merge branch that
  initially forked from the *pre-cleanup* tip and carried the heavy blobs, so the `--refs`
  strip was re-run against it directly. A branch forked before a history rewrite keeps the
  dirty ancestry — re-strip the fork, don't trust the fork point.
- **Verification standard for the strip:** `git rev-list --objects <branch> | git cat-file
  --batch-check … | awk '$1=="blob" && $3>1000000'` must list only the deliberate keepers
  (the two `docs/*.png` images + the ingestion test-fixture brand-kit PDF). Pack size is a
  hint; the blob check is the truth.
- **Kept in history** (per the 2026-08-03/04 rulings): `.context/` markdown, the `docs/`
  images, test fixtures. **Stripped from history, kept local-only/gitignored:**
  `apps/api/asset-store/`, `apps/agent_runtime/.lumen-runs-*/` traces, `.context/a0-probe/`,
  `.context/attachments/`, `.context/**/*.png`, `.playwright-mcp/`,
  `apps/editor/public/vendor/`, root screenshot PNGs.

## Docs updated this session
- Root **`CLAUDE.md`** and **`AGENTS.md`**: the stale "design subsystem … lives in its own
  repo; this repo does not touch it" paragraph (and the Doc-S "design engine … lives in its
  own repo — havana" parenthetical) were rewritten to reflect the merge, the current
  Part-I-only status, the `subsystems/clue-design/` location, and the uv/ruff exclusion. The
  two root files stay near-identical (AGENTS.md lacks only the last two C8§6c backlog lines).
- This note + a pointer added to `_memory/README.md`.

## Next: Part I / Step 2 — week-one hygiene (plan §3 Step 2)
Not yet started. In order:
1. **Dedup shared libs:** fold post-fork improvements from `subsystems/clue-design/py_lumen_obs`
   + `py_lumen_config` into the platform's `clue-obs`/`clue-config`, migrate design imports,
   delete the duplicates.
2. **Real packaging:** proper `pyproject.toml` for `apps/api` + `apps/agent_runtime`; re-enter
   them into the uv workspace **as explicit members** (the `exclude` guard keeps the non-Python
   root out; Python apps re-enter by exact path); kill `sys.path` hacks; package-layout /
   structure-guard carve-out for `subsystems/clue-design` as the one non-Python subsystem.
3. **One version story:** Python 3.12 everywhere; one `deepagents` pin (platform's); one
   `langchain-*` lockfile resolution.
4. **Gradual strict gates:** design Python into ruff-format now, mypy-strict via lenient
   per-module overrides + tracked burn-down; keep `make check` green each commit.
5. **Import contracts:** register new packages in import-linter; design never imports
   research/memory/content internals (and vice versa); design Python → Rust engine only via the
   `lumen-api-helper` subprocess seam; nothing outside `subsystems/clue-design/` imports design
   internals except the composition root.
6. **Path-filtered CI:** design jobs (cargo test, wasm build + engine-handshake verify, editor
   vitest/tsc, design-API pytest, design-agent pytest) run only on `subsystems/clue-design/**`;
   `crates/lumen-core/**` is the one global design-side gate; cache the helper binary + wasm
   artifact; platform pipeline untouched.

**Gate for Step 2:** one obs, one config, one Python, one deepagents pin; all design packages
under import contracts; all CI lanes green including design-agent tests.

## Open follow-ups / caveats
- `design-import` tag never created — anchor design-only history off `3ab4a750`'s 2nd parent.
- The design tree is currently **outside** `make check` (uv/ruff excluded) — do not assume the
  root gates cover it until Step 2 lands the packaging + gates.
- Dev-only SQLite data is **not** migrated in Part II; schema + code port, dev data resets.
- The Rust engine (crates, helper seam, handshake, wasm) is **untouched by all four parts** —
  do not "port" it; respect the nested `CLAUDE.md`/`AGENTS.md` handshake rule when touching
  `crates/`.
- Out of scope this session (left as-is): the root docs' research/output-contract prose about
  the content layer being "not this repo" — separate concern from the design merge.
