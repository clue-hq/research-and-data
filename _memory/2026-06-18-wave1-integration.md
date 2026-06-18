# 2026-06-18 — Wave 1 (M0.3 ∥ M0.4) parallel build + integration

First parallelized wave. Two unblocked, independent M0 issues built concurrently in isolated git
worktrees, then integrated by the orchestrator on `project-memory-instructions`.

## Mechanism (reusable pattern)
- Spawned two background `general-purpose` agents with `isolation: worktree`: `m03` (ENG-114, db/) and
  `m04` (ENG-120, config/). Each read its spec + conventions + architecture, implemented, self-verified
  `make check` in its own worktree, and committed to a named branch (`wave1-m03` @ c207326, `wave1-m04`
  @ ae728a6).
- **Worktree base gotcha:** both worktrees arrived checked out at the EMPTY initial commit `e3e5179`,
  not the current HEAD. Both agents detected this and re-based their branch onto M0.2 `6dc7d40` before
  working (m03 `git reset --hard 6dc7d40`; m04 branched off 6dc7d40). **Next time: tell worktree agents
  to confirm/`git reset --hard <HEAD-sha>` first.** Always integrate from the agents' final commit SHAs.
- **Integration:** `git checkout <branch> -- <its paths>` for each agent EXCLUDING `pyproject.toml` +
  `uv.lock` (avoids lock-merge conflicts). Then I hand-reconciled `pyproject` deps (union) and ran ONE
  `uv sync` to regenerate a single coherent lockfile. Overlap was ONLY pyproject + uv.lock — clean,
  exactly as the coordination contract intended (separate packages don't collide).

## Coordination contract (held)
- m03 owns db/, alembic/, docker-compose.yml, Makefile db targets. m04 owns config/, .env.example.
- Shared seam: DSN env var `CLUE_DATABASE_URL` — m04 documents it (.env.example + `DB_DSN_ENV_VAR`),
  m03 reads it directly (`db.database_url()`), NO import coupling. db/ imports only core; config/ imports
  only core (not obs/db). Neither touched core/, the other package, tests/conftest.py, or .github/.

## Verification (integrated tree)
- `make check` (no DSN): ruff clean, mypy --strict clean, import-linter **5 kept/0 broken** (50 files,
  97 deps), **133 passed + 7 skipped** (DB tests skip w/o DSN).
- **Live DB smoke** (throwaway `pgvector/pgvector:pg16` on host port **5433** — host already runs a
  Postgres on 5432 without a `clue` role, so 5432 collides; committed default stays 5432, CI uses a clean
  service): migrate→head leaves ONLY `alembic_version` (zero domain tables); `vector` ext present + a
  `vector(3)` column insert/select works; up→down→up reversible (downgrade drops `vector`). `make check`
  WITH the live DSN = **140 passed, 0 skipped**; `pytest tests/db` = 11 passed.
- macOS has no `timeout` binary — use a bounded `for i in $(seq …); do … && break; done` probe loop
  (no `sleep`) to wait for Postgres readiness.

## Integrator follow-ups done
- Added the M0.3 migration-conventions checklist backlink to the M1.1 spec (`docs/specs/M01-…` Data model
  line → `src/clue_research/db/README.md` § checklist).
- Wrote this note + the M0.4 note (m04 deferred its `_memory/` write per its scope constraint; m03 wrote
  its own `2026-06-18-m03-db-migrations.md`).

## Review outcome (wf_2daa6413-e7f, 4 lenses → verify)
- 4 "confirmed" but 2 were positive confirmations (seam consistent; layering correct). 2 actionable, both fixed:
  - **[major] DSN env-var name duplicated** (`db.DATABASE_URL_ENV` + `config.DB_DSN_ENV_VAR`, both
    "CLUE_DATABASE_URL") with no sync test — necessary duplication (packages can't import each other).
    FIXED: added `tests/test_seams.py` asserting equality + pointed both constant comments at it.
  - **[nit] dead `_default_allow_map()`** in config/policy.py (duplicated the field default). REMOVED.
- Post-fix `make check` GREEN: ruff, mypy 36 files, import-linter 5 kept/0 broken, 134 passed + 7 skipped.
- Next wave (after M0.3/M0.4 land): M0.5 (obs — needs M0.4 redaction helper), then M0.6 (CI/eval — needs
  M0.3–M0.5). M0.5 → M0.6 is a short serial tail; M0 then closes and the graph fans out (M1 → {M2,M3} → M4 …).
