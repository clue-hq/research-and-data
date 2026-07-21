# 2026-07-21 — B3 worktree: scoped memory slice 1 (Doc M) — built & gated

Branch `platform/b3-memory` (renamed from the Conductor workspace branch; cut at `e615e81`,
the treaty commit, per PB §4). Spec: `docs/specs/PB-B3-scoped-memory-slice-1.md`. All work is
local commits only (no push).

## Founder rulings this session (recorded in the spec §0)
1. **Q1** Claim-churn staleness (reference health / scope churn) **deferred** to
   integration/Phase C; `memory_claim_ref` ships indexed both directions so the signals stay
   computable. Slice-1 staleness = contradiction events + `cycles_since_confirmed`.
2. **Q2** Kill-switch is **both** layers: per-workspace DB toggle + audit journal
   (`memory_switch`/`memory_switch_audit`) is the mechanism; `CLUE_MEMORY_ENABLED` settings
   flag is the deploy master default layered above (effective = AND).
3. **Q3** Seam contracts live in **`clue_core/memory.py`** (append-only contract-delta).
4. **Q4** Reconciliation = deterministic pre-checks → LLM judge via the injected `LLMGateway`
   protocol (`CLUE_MEMORY_RECONCILE_MODEL`); eval golden set is file-based + memory-local.
5. **Q5** **`account` scope deferred** — the `MemoryScopeType` enum and the DB CHECK have no
   account arm (unrepresentable, loud); appending it later is additive (enum member + FK column
   + CHECK arm + an account⇄spine anchor decision).
6. **Q6** `MemoryCaps` shape (store caps / bundle budgets / edit-distilled threshold) lives in
   `clue-config/schema.py`, defaults + validators; per-client `config_revision` plumbing later.

## What was built (commits, in order)
- `7c008f8` docs(specs): PB-B3 spec.
- `2e4779c` feat(core+config): `clue_core/memory.py` (enums with `project` from birth;
  submission/bundle/label shapes; `canonical_bytes`/`bundle_hash` determinism; the
  MemoryDisabled/MemoryRejected/MemoryPreconditionFailed refusal split; `MemoryWriteSeam`,
  `ContextAssembly`, `ReconcileJudge` protocols; BORN_TRUST/BORN_STATUS) + config appends.
- `d1ed8ce` feat(db): migration `8aba77245267` (hash id off spine head `98422adaaa38`) —
  `memory` (per-scope composite FKs pinned to own workspace via spine anchors + **new
  `project_workspace_anchor`** added to the spine's `project` table, append-only; generated
  `scope_id`; two-way person-adjacency CHECK; superseded⇔successor CHECK), `memory_claim_ref`
  (FK → `claim(id)`, reverse index), `memory_event`, `memory_bundle_journal` (structurally
  ids-never-bodies), `memory_switch` + audit. DB FKs into research tables (`claim`,
  `contact_entity`) are schema-level only — Rule S1 intact.
- `909ec7a` feat(memory): the whole substrate — `write.py` (enforcement chain), `reconcile.py`
  (pure `decide()` + fenced LLM judge + fail-safe park-proposed), `assembly.py` (gate → one
  lexicographic rank under budgets → stability order → labels → journal + hash), `lifecycle.py`
  (ONE `rank_key`: bundle order = eviction inverted; losing-comparison sentences; backfill;
  off-cycle-fair `record_kickoff`), `switch.py`, `compliance.py` (`erase_subject` redacts to
  `[erased]` + severs refs + backfills; Art. 21 `lock_memory`), `evals/` (12 golden fixtures +
  runner over `decide()`). New import-linter **Rule S3**: memory imports only core+db+config.
  `clue_memory` added to ruff known-first-party (append-only root pyproject).
- (this commit) tests: `tests/memory/**` — 14 offline (incl. enum↔CHECK parity scan of the
  migration source, golden run, seam-guard scan) + 30 DB tests across write-seam / assembly /
  lifecycle / switch+compliance batteries; `_memory/` note.

## Verification (all green at this state)
- ruff format+check clean · mypy **292 files** clean · import-linter **17 kept / 0 broken**.
- Offline suite (no DB env): **1172 passed** (baseline 1158 + 14 memory offline).
- Full DB suite on the workspace DB (docker `clue-pg-calgary`, port 25636, db `clue_calgary`):
  **1996 passed** — and identical on immediate rerun (rerun-idempotency kept).
- `db-smoke` up→head → down→base → up→head on throwaway `clue_b3_smoke`: green; **one head**
  (`8aba77245267`).
- Recipe #1 regression: scripts/01→06 chain ran end-to-end in stub mode on this branch
  (workspace `acmeb3`) — unchanged behavior (0-filled fields offline is the correct output).

## Design decisions worth knowing (beyond the spec)
- `trust_grade` is an **ordinal smallint 0–4** (born 3/2/1 by provenance; +1 confirm capped,
  −1 contradiction floored) — transparent, never blended; every change journaled.
- The deterministic restatement pre-check short-circuits the judge entirely (tested with a
  RaisingJudge: 0 calls) — exact agreement costs no tokens.
- A judge failure/malformed response parks the submission `proposed` even for `user_stated`
  (fail-safe > convenience; golden fixture 09 covers it).
- A judge verdict naming a **dangling target id degrades to ADD** — the engine never trusts an
  unknown id from the model.
- `Memory.scope_id` is a **generated stored column** (CASE over scope_type) — one canonical
  grouping key for reconcile/assembly/indexes.
- Workspace-scope rows carry all three scope FKs NULL (the workspace IS the instance).
- Bundle `canonical_bytes()` excludes `journal_id` (per-assembly uuid) — determinism is a
  content property; the journal's `bundle_hash` witnesses it.
- Tests use `clue_memory._store` for **setup/inspection only** (e.g. simulating an activated
  `agent_observed` record — its review-queue producer is Phase C); the offline guard test +
  Rules S1/S3 keep production code out.

## Follow-ups (recorded in spec §9; none block B-integration)
1. `account` scope append (enum + FK + CHECK arm + anchor decision).
2. Claim-churn staleness signals — needs a sanctioned read over `claim`; decide raw-SQL vs
   seam at integration.
3. DSAR cascade wiring (claim erasure → `erase_subject` / ref severance) at the api root with
   the Doc D backlog; `memory_review` queue surface; run-manifest toggle recording (B1/fleet).
4. Kickoff-interview writer (Phase C step 4) calls `submit` + `record_kickoff`.
5. Minor: `memory_event` ordering within one transaction relies on `created_at` (= txn
   timestamp) → same-txn events tie; if a strict total order is ever needed, add a bigserial
   seq column (cheap ALTER). Tests assert event *sets*, not order.
6. Minor: cross-branch tension pairs are recorded product×project only (the two sibling axes
   in slice 1); revisit when `account` scope lands.

## Environment (Conductor workspace `calgary`)
Docker Postgres `clue-pg-calgary` on port **25636**, db `clue_calgary`, redis db 4; `.env` at
repo root holds `CLUE_DATABASE_URL`/`CLUE_REDIS_URL` (source with `set -a; source .env`).
Recreate with the standard per-workspace setup script (hash-derived port).
