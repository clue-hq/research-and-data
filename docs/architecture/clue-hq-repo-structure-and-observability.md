# Clue-HQ — Backend Repo Structure & Observability Plan (Doc R)

> **Status: RATIFIED PLAN v1.0 (2026-07-17).** The physical reorganization of the platform
> backend repo (dar-es-salaam) into a production-grade uv workspace, and the structlog-first
> observability standard — both founder-ratified 2026-07-17. This is a *plan record*: nothing in
> the tree has moved yet; execution follows the phases in §5 on the branch named in §6. Scope is
> the backend repo only (the design engine repo, havana, keeps its own layout). This doc changes
> **packaging and logging only** — no logic changes ride any phase, and no substrate identifier
> (table, enum, claim field) is renamed (consistent with the §1a rename-deferral ruling).

## 1. Current-state assessment (why this is a promotion, not a rescue)

The repo is already disciplined: `src/` layout, uv + lockfile, ruff + mypy + pytest behind one
`make check` gate, a single reversible Alembic chain, and **import-linter contracts that
machine-enforce module boundaries** (`core` imports nothing internal; resolvers/adapters/judges
never import each other; provider SDKs sealed behind their packages). The 24 packages inside
`src/clue_research/` are well-bounded.

The gap is framing, not hygiene: the repo is packaged as *one subsystem* (`clue-research`) while
the doc set declares it the **platform backend home** (research + memory + content + toolbelt +
platform deepagent + fleet + api). Shared machinery (`core`, `db`, `config`, `obs`, `gateway`,
`locks`) lives *inside* the research package, so a future `clue_memory` or `clue_content` would
have to import from "research" to get the claim types — wrong dependency direction, and the kind
of confusion the doc set just spent a week eliminating. Logging today is an OTel tracing skeleton
(`obs/`); there is no structured-logging standard.

## 2. Rulings (founder, 2026-07-17)

| # | Ruling |
|---|---|
| R1 | **uv workspace** with three zones: `libs/` (shared, subsystem-agnostic), `subsystems/`, `platform/`. Package namespace: flat `clue_*` sibling packages (`clue_core`, `clue_obs`, …), distribution names `clue-core`, … |
| R2 | **Shim-and-deprecate** for the Phase-1 moves: `clue_research.core` (etc.) re-export from `clue_core` with a `DeprecationWarning` for one integration window, then deleted. In-flight branches keep working; nothing breaks silently. |
| R3 | **Timing**: Phase 0 immediately; Phase 1 *before* build-step 0/2 code lands (the cheapest moment it will ever be); scaffolds (Phase 2) right after; the `api` move (Phase 3) last, when step-2 toolbelt work begins. |
| R4 | **One deployable, two entrypoints** (api + fleet worker) for v1; the workspace layout supports splitting deployables later without another reorg. |
| R5 | **structlog from day one** via `clue-obs`, ported from havana's proven `py_lumen_obs` pattern (copy-port; no cross-repo imports). Direct `logging.getLogger`/`print` outside `clue-obs` is lint-banned. |

## 3. Target structure

```
dar-es-salaam/
├── pyproject.toml                 # workspace root: members, shared ruff/mypy/pytest config
├── Makefile                       # same gates; check = lint+typecheck+contracts+test, workspace-aware
├── alembic/                       # ONE migration chain (one DB, many subsystems; table ownership
│                                  #   by naming convention + migration slugs). Untouched by the reorg.
├── docs/  _memory/  scripts/
│
├── libs/                          # shared, subsystem-agnostic; each with its own pyproject
│   ├── clue-core/                 # domain types, enums, protocols (Resolver, gates), ids,
│   │                              #   canonical-json; the DRY backlog lands here as part of the move:
│   │                              #   normalize_host · reference_time · decode_jsonb_scalar · BudgetTracker
│   ├── clue-obs/                  # ALL logging + telemetry (§4) + the existing OTel tracing
│   ├── clue-db/                   # engine/session management, alembic env glue
│   ├── clue-config/               # settings, policy-as-data schemas, config_revision loaders
│   ├── clue-gateway/              # the LLM gateway (already seam-isolated; promoted as-is)
│   └── clue-locks/                # redis locks / rate-limit coordination (promoted as-is)
│
├── subsystems/
│   ├── research/   clue_research/ # claimstore, identity, sources, resolvers, adapters, icp, stage0,
│   │                              #   discovery_scoring, profiling, synthesis, narrative, verification,
│   │                              #   compliance, review, durable, evals — internals UNTOUCHED
│   ├── memory/     clue_memory/   # Doc M substrate behind its two seams            [scaffold]
│   └── content/    clue_content/  # Doc S plane: schema/, drafts/, scaling/, qa/    [scaffold]
│
├── platform/
│   ├── toolbelt/    clue_toolbelt/    # plane 2: typed tool envelope + registrations
│   ├── agents/      clue_agents/      # Doc A: platform deepagent, subagents, skills loader,
│   │                                  #   context_assembly/ (the 7 layers), workspace/
│   ├── fleet/       clue_fleet/       # the shell: worker, queue, envelopes, supervisor, units/
│   ├── projections/ clue_projections/ # read side: run views, cards, catalog, review surfaces
│   └── api/         clue_api/         # THE composition root: FastAPI routers, SSE, treaty DTOs,
│                                      #   wiring (today's clue_research/api — moves last, Phase 3)
└── tests/                         # mirrors the tree; + treaty contract tests (Mode B)
```

**Import rules (the constitution, now physical — enforced by import-linter as today):**
`libs/*` import nothing internal (`clue-core` imports *nothing*); subsystems import libs and
communicate only through the shared substrates (claims; memory seams) — never each other;
`platform/agents` imports the toolbelt façade + projections only (the REQ-02 contract);
`platform/api` is the **only** package that may import everything (composition root). The
deferred composition-root wirings in the backlog (pre-spend gate routing, binding pre-insert
stamp, verdict-rationale redaction) land in `clue_api` when their milestones integrate.

## 4. Observability standard (structlog-first, day one)

`clue-obs` is havana's `py_lumen_obs` pattern ported, plus platform specifics:

- **One `clue_obs.setup(mode)` per entrypoint** (api, fleet worker, CLI) — the only
  `structlog.configure` in the codebase. Chain: contextvars-merge → level + ISO-UTC timestamp →
  callsite → **redaction** → ConsoleRenderer (dev) / JSONRenderer (prod). Stdlib/uvicorn/alembic
  loggers bridge through the same chain. `CLUE_LOG_MODE` = `info | debug`.
- **Bound context is the platform spine**: `request_id`, `tenant_id`, `project_id`, `run_id`,
  `account_id`, **`actor`** (human | agent | delegated-agent — REQ-20's actor on every line for
  free), pinned `profile_version`.
- **`log_span` on every tool** — a `*_started` with no completion is hang forensics (havana's
  silent-hour lesson). The toolbelt envelope logs every invocation automatically: an unlogged
  write is structurally impossible.
- **`model_call_usage` at the gateway** (tokens, cached-prefill %, duration, served model) — the
  telemetry Doc A §1.3 requires for the per-tier agency-vs-coverage measurement.
- **Two DSAR-grade redaction rules**: secrets masked even in debug; **personal-claim *values*
  never logged — ids only** (ids-never-bodies, the journal rule extended to logs; otherwise
  erasure becomes log-scrubbing).
- **Sinks**: console truncates; per-run `run_<id>/logs/run.jsonl` never truncates.
- **Enforced, not trusted**: lint bans `print` and direct `logging.getLogger` outside `clue-obs`;
  a pytest fixture captures structured events so tests assert on them.
- **Event naming**: `subsystem.noun_verb`, snake_case keys.

## 5. Phases (each = green `make check`; move-only commits; `git mv` for history)

| Phase | Work | Gate / notes |
|---|---|---|
| **R0** (additive, zero risk) | Workspace-ify root `pyproject.toml`; create `libs/clue-obs`; wire `setup()` into the existing api entrypoint | Full suite green; no file moves |
| **R1** (the promotion) | `core`, `db`, `config`, `gateway`, `locks`, `obs` → `libs/*`; mechanical import rewrites; **DRY backlog items consolidated into `clue-core` in the same pass** (this phase *is* harness build step 3, enlarged); shims per R2; import-linter contracts updated | Full suite green; contracts green; move-only commits (no logic changes mixed in) |
| **R2** (scaffold the future) | Empty-but-contracted `subsystems/memory`, `subsystems/content`, `platform/*` packages | New work lands in the right home from its first commit |
| **R3** (composition root) | `clue_research/api` → `platform/api` (`clue_api`), when step-2 toolbelt work begins; delete R2 shims at the next integration | Full suite + db-smoke green |

**The governing risk is operational, not technical: Conductor worktrees.** R1 conflicts with
every open branch. Execute it at a quiet point — open milestone branches merged or parked — on
one dedicated branch (§6), completed within a day. Alembic, `_memory/`, and `docs/` are untouched
by every phase.

## 6. Branch & commit conventions for the revamp

- **Branch: `platform/workspace-restructure-v0`** (matches the repo family's `area/name-vN`
  convention, e.g. havana's `agents/deepagent-v0`). R0 may ride it or land separately as
  `platform/obs-structlog-v0` if R1 must wait on worktree quiescence.
- Commits: `chore(structure): move <pkg> to libs/ (move-only)` / `feat(obs): …` — move-only
  commits contain **zero** logic changes so review is `git diff --stat` + suite-green.
- Local commits only; no push without explicit instruction (repo rule).

## 7. Doc follow-ups (deliberately deferred until execution)

At R1 completion, in the same branch: rewrite `docs/specs/_conventions.md` §2's package-location
language, update `CLAUDE.md`/`AGENTS.md`'s structure references, and add the workspace layout to
`docs/architecture/README.md`. Until then, this doc is the single statement of the target; the
current tree remains authoritative for where code actually lives.
