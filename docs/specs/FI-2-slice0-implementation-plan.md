# FI-2 Slice 0 Implementation Plan — substrate tables, species attribute, identity repairs

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development — one fresh Opus subagent per task, sequential, orchestrator reviews the diff and commits between tasks. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Land FI-2 slice 0 (`docs/specs/FI-2-workspace-account-layer.md` §9): the `project_account` and `run_lineage` tables + writers, the `research_scope` field attribute + species declarations, the H1/H2/H3 identity repairs, backfills, and the canonical two-project fixture test.

**Architecture:** Three additive migrations (hash ids, hand-written, reversible) + two small substrate modules in `clue_research`, then writer wiring at existing run-mint/admission sites, then the identity repairs, then backfill scripts and the end-to-end fixture. No frozen-`core` change except the `FieldDef.research_scope` contract-delta (Task 3), which follows the `reuse_scope` precedent exactly.

**Tech Stack:** Python 3 / SQLAlchemy async (raw `text()` SQL, matching `identity/entities.py`), Alembic, pytest (DB-gated tests follow the repo's existing fixtures), `uv`.

## Global constraints (every task)

- **Read the spec first**: `docs/specs/FI-2-workspace-account-layer.md` (§1 baseline citations, §2–§6 designs, §9 ACs). Study digests: `_memory/2026-08-08-fi2-workspace-account-layer-studies.md`.
- **Migrations**: `alembic revision -m "<slug>"` (random hash id) off the current single head; hand-written reversible `upgrade()`/`downgrade()`; named constraints/indexes; **no new DB enum types** (use `text` + named CHECK — avoids enum-parity coupling); `make db-smoke` must pass on a clean per-branch throwaway DB; `alembic heads` returns exactly one head after your change.
- **Species vocabulary** (Task 3+): values are exactly `'project_neutral'` and `'project_relative'`.
- **Seam discipline**: no milestone package imports another's internals; new modules live in `clue_research` top-level or `claimstore/` as assigned; composition-root wiring stays at `platform/api`.
- **TDD**: write the failing test first, watch it fail, implement, watch it pass. Match surrounding code style; comments only for non-obvious constraints.
- **Do NOT commit.** Leave the working tree dirty; the orchestrator reviews your diff and commits. Do not push, ever.
- **Verify before you code**: the plan cites file:line from 2026-08-08 studies; confirm each citation against the live file before editing (lines may have drifted).
- Run targeted tests with `uv run pytest <path> -x -q`; finish your task with the full `make check` (and `make db-smoke` when you added a migration) and report results honestly.

---

### Task 1: `run_lineage` table + module

**Files:**
- Create: migration `alembic/versions/<hash>_fi2_run_lineage.py`
- Create: `subsystems/research/clue_research/claimstore/run_lineage.py`
- Test: `tests/claimstore/test_run_lineage.py`

**Interfaces (produces — later tasks import these exact names):**
```python
# clue_research/claimstore/run_lineage.py
RUN_LINEAGE_KINDS = ("discovery", "import", "scoring", "tiering", "entity_research",
                     "committee", "contact_research", "narrative", "stage0", "enrichment", "manual")

async def record_run_lineage(conn, *, run_id: uuid.UUID, workspace_id: str, kind: str,
                             project_id: str | None = None,
                             project_run_id: uuid.UUID | None = None,
                             created_at: datetime | None = None) -> None:
    """Idempotent (ON CONFLICT (run_id) DO NOTHING). Raises ValueError on unknown kind."""

async def project_run_ids(conn, *, workspace_id: str, project_id: str) -> tuple[uuid.UUID, ...]:
    """All run ids attributed to the project — the project-lens predicate input."""
```

**Steps:**
- [ ] **1.1** Write failing tests: (a) `record_run_lineage` inserts a row readable via `project_run_ids`; (b) calling it twice with the same `run_id` is a no-op (no error, one row); (c) unknown `kind` raises `ValueError` before touching the DB; (d) `project_run_ids` excludes other workspaces and other projects; (e) a `project_id=None` row (stage0) never appears in any `project_run_ids` result. Use the repo's existing DB-test fixture pattern (find it via an existing `tests/claimstore/` DB test).
- [ ] **1.2** Run: `uv run pytest tests/claimstore/test_run_lineage.py -x -q` → import error / table missing.
- [ ] **1.3** Migration — DDL verbatim from spec §3 (adapt only if `project_run`'s PK column name differs — verify in `alembic/versions/79d56a0f4425*` / the rename migration `814a272f79a5`):
```sql
CREATE TABLE run_lineage (
    run_id          uuid PRIMARY KEY,
    workspace_id    text NOT NULL,
    project_id      text NULL,
    project_run_id  uuid NULL REFERENCES project_run (id),
    kind            text NOT NULL,
    created_at      timestamptz NOT NULL,
    CONSTRAINT run_lineage_kind_check CHECK (kind IN
        ('discovery','import','scoring','tiering','entity_research','committee',
         'contact_research','narrative','stage0','enrichment','manual'))
);
CREATE INDEX run_lineage_by_project ON run_lineage (workspace_id, project_id);
```
`downgrade()` drops the table. Confirm the "no domain tables at M0 head" test doesn't cover this (it shouldn't — new migration is post-M0).
- [ ] **1.4** Implement the module (raw `text()` SQL, style of `identity/entities.py`).
- [ ] **1.5** `uv run pytest tests/claimstore/test_run_lineage.py -x -q` → PASS; then `make db-smoke`; `alembic heads` → one head. Report.

---

### Task 2: `project_account` table + membership module + merge re-pointing

**Files:**
- Create: migration `alembic/versions/<hash>_fi2_project_account.py`
- Create: `subsystems/research/clue_research/membership.py`
- Modify: `subsystems/research/clue_research/identity/entities.py` (`mark_merged`, ~:341-383)
- Test: `tests/test_membership.py`

**Interfaces (produces):**
```python
# clue_research/membership.py
ADDED_VIA = ("discovered", "imported", "manual", "directive")

async def ensure_project_account(conn, *, workspace_id: str, project_id: str,
                                 account_entity_id: uuid.UUID, added_via: str,
                                 added_at: datetime | None = None) -> None:
    """Idempotent; first add wins (ON CONFLICT DO NOTHING). ValueError on unknown added_via."""

async def projects_for_accounts(conn, *, workspace_id: str,
                                account_ids: Sequence[uuid.UUID]) -> dict[uuid.UUID, tuple[str, ...]]:
    """added_at-ascending project ids per account (first = primaryProjectId policy, spec §2)."""

async def accounts_for_project(conn, *, workspace_id: str, project_id: str) -> tuple[uuid.UUID, ...]

async def repoint_project_accounts(conn, *, workspace_id: str, loser_id: uuid.UUID,
                                   survivor_id: uuid.UUID) -> None:
    """INSERT survivor rows mirroring loser rows ON CONFLICT DO NOTHING, then DELETE loser rows."""
```

**Steps:**
- [ ] **2.1** Failing tests: (a) upsert + read-back through `projects_for_accounts`/`accounts_for_project`; (b) double-add is one row, first `added_via`/`added_at` retained; (c) ordering: two projects added at t1<t2 → tuple ordered (P_t1, P_t2); (d) `repoint_project_accounts` moves loser memberships to survivor, merging with survivor's existing rows without duplicates; (e) after `mark_merged(loser, survivor, …)` the loser has zero membership rows and the survivor has the union (this test drives the `mark_merged` wiring).
- [ ] **2.2** Run → fail.
- [ ] **2.3** Migration — DDL from spec §2 (verify the `project` table's PK/columns via the `b366c985ca12` migration before writing the FK; if no composite `(id, workspace_id)` unique exists on `project`, FK to `project(id)` alone and enforce workspace agreement with a named CHECK-free code-path validation — note whichever you did in the module docstring):
```sql
CREATE TABLE project_account (
    workspace_id      text NOT NULL,
    project_id        text NOT NULL,
    account_entity_id uuid NOT NULL,
    added_via         text NOT NULL,
    added_at          timestamptz NOT NULL,
    PRIMARY KEY (workspace_id, project_id, account_entity_id),
    CONSTRAINT project_account_added_via_check CHECK
        (added_via IN ('discovered','imported','manual','directive')),
    CONSTRAINT project_account_account_ws_fk FOREIGN KEY (account_entity_id, workspace_id)
        REFERENCES account_entity (id, workspace_id)
);
CREATE INDEX project_account_by_account ON project_account (workspace_id, account_entity_id);
```
- [ ] **2.4** Implement module; wire `repoint_project_accounts` inside `mark_merged`'s transaction (import `clue_research.membership` from `identity/entities.py` — membership imports nothing from `identity`, so no cycle; verify).
- [ ] **2.5** Tests pass; `make db-smoke`; one head. Report.

---

### Task 3: `research_scope` — migration, core contract-delta, registry enforcement, species declarations

**Files:**
- Create: migration `alembic/versions/<hash>_fi2_research_scope.py` (nullable `research_scope text` + named CHECK on `field_definition` AND `workspace_field_definition`)
- Modify: `libs/clue-core/clue_core/` — wherever `FieldDef` and `default_reuse_scope` live (locate by grep): add `research_scope: str | None = None` to `FieldDef`, add `default_research_scope(field_class, field_key) -> str` returning `'project_relative'` iff `field_key` starts with `account.scoring.` or equals `account.value_narrative` / `contact.persona` / `contact.role_on_committee`, else `'project_neutral'`; export both. **This is a frozen-core contract-delta — mirror how `reuse_scope`/`default_reuse_scope` were added (see `82831d3fa4c5` + core git history) and say "contract-delta" in your report.**
- Modify: `subsystems/research/clue_research/claimstore/registry.py` — persist/load the column; add `ResearchScopeError` mirroring `ReuseScopeError` (`registry.py:61-70`): a `<pack>.*` field (excluding `client.*`) registering with `research_scope=None` fails loud. Add a `resolve_research_scope(field_def) -> str` helper: explicit value, else `default_research_scope`.
- Modify (declarations, per spec §5.2 — founder-ratified 2026-08-08): explicit `research_scope="project_relative"` on the `FieldDef`s for `account.scoring.fit`/`.intent`/`.tier` (locate registration — likely `claimstore/packs.py` seeds and/or `discovery_scoring`), `account.value_narrative` (`narrative/fields.py`), `contact.persona` + `contact.role_on_committee` (`profiling/committee/fields.py:127-145`). Everything else stays `None` → neutral by default (incl. `operational_pain`, `strategic_moves`, `account.resonance.*` — ratified neutral).
- Test: `tests/claimstore/test_research_scope.py`

**Steps:**
- [ ] **3.1** Failing tests: (a) explicit value round-trips through register/load; (b) `resolve_research_scope` precedence: explicit > default; (c) defaults: `core.employee_count`→neutral, `account.scoring.fit`→relative, `account.value_narrative`→relative, `contact.persona`→relative, `contact.current_title`→neutral, `account.resonance.culture` (or any registered resonance key)→neutral; (d) a fake `acmepack.foo` field with no declared scope raises `ResearchScopeError` at registration; (e) DB CHECK rejects a bogus value.
- [ ] **3.2** Run → fail. **3.3** Migration + core delta + registry + declarations. **3.4** Tests pass; run the whole existing claimstore/registry test dir for regressions; `make db-smoke`; one head. Report.

---

### Task 4: run-lineage registration at every production run-mint site

**Files (verify each citation live):**
- Modify: `subsystems/research/clue_research/discovery_scoring/phases.py` (~:111-124, where the discovery run id is derived) → `record_run_lineage(kind="discovery", project_id=<from project_run>, project_run_id=…)`.
- Modify: `stage0/import_accounts.py` (~:131-135, `import_batch_run_id`) → `kind="import"`, `project_id=None` for now (Task 6 threads the real project).
- Modify: `platform/api/clue_api/account_research_fleet_launch.py` (where `research_run_id`/`entity_research_job` rows are created) → `kind="entity_research"` with the run's `project_run_id` + `project_id` (both available post-B3).
- Modify: the committee launch/worker run-stamp site (`profiling/committee/worker.py` / its launcher — the run id may be the account-deep run or `project_run_id` per `c6d84aa84b79`) → `kind="committee"`.
- Modify: the scoring/tiering run-mint call sites (`score_account` callers in `discovery_scoring`) → `kind="scoring"` / `kind="tiering"`.
- Modify: `stage0/client_kb.py` + `stage0/seeds.py` run ids → `kind="stage0"`, `project_id=None`.
- Test: `tests/test_run_lineage_registration.py`

**Interfaces:** consumes Task 1's `record_run_lineage` exactly as declared. Registration goes **inside the same transaction** as the first write that uses the run id, at the site where the id is minted (not per claim).

**Steps:**
- [ ] **4.1** Failing tests: for each path that has an existing test fixture (discovery admission, import, committee worker, scoring), extend/add a test asserting: after the path runs, every claim it wrote has `claim.run_id` resolvable in `run_lineage` with the right `kind` and `project_id`. Grep existing tests per path and reuse their setup wholesale.
- [ ] **4.2** → fail. **4.3** Wire the calls (idempotent, so replay-safe paths stay safe). **4.4** → pass; full `make check`. Report any path you could NOT test (no fixture exists) explicitly.

---

### Task 5: membership writers at the account-entry sites

**Files (verify citations):**
- Modify: `subsystems/research/clue_research/discovery_scoring/gate/admission.py` (admit path, ~:221-232) — after a successful ADMITTED/AUTO_MERGED disposition, `ensure_project_account(added_via="discovered", project_id=<from the batch/run context>)`. The project id must be threaded from the caller (`phases.py` / `exa_websets_materialization.py:973-979`) — add it to `admit`'s signature rather than guessing inside.
- Modify: `platform/api/clue_api/exa_websets_materialization.py` — thread project context into its `admit` calls; also on the replay/merge-rewrite path (~:1030-1063) ensure the survivor keeps membership.
- Modify: `subsystems/research/clue_research/directives.py` (~:820-831, `account_research_directive_account` insert) → `ensure_project_account(added_via="directive", project_id=<directive.project_id>)` in the same transaction.
- Test: `tests/test_membership_writers.py`

**Steps:**
- [ ] **5.1** Failing tests, reusing each path's existing fixtures: (a) discovery admission of a new account creates the membership row `(ws, project, entity, 'discovered')`; (b) admission that AUTO_MERGES into an existing entity still ensures membership for *this* project on the survivor; (c) directive scoping writes `('directive', …)` and a second scoping of the same account is a no-op; (d) trial add-account path (`trial/spine.py:307-346` → `admit`) — if the trial has a project notion, membership lands; if it does not, assert no crash and document.
- [ ] **5.2** → fail. **5.3** Implement (signature threading, same-transaction upserts). **5.4** → pass; `make check`. Report.

---

### Task 6: H3 — `import_accounts` gains project context

**Files:**
- Modify: `subsystems/research/clue_research/stage0/import_accounts.py` (signature ~:138-150; resolution loop ~:316-373)
- Modify: `platform/api/clue_api/toolbelt_wiring.py` (`import_accounts` tool args, ~:751-816)
- Test: extend the existing import tests (locate under `tests/` by grepping `import_accounts`)

**Behavior:** new optional `project_id: str | None = None` keyword. When set: validate the project exists in this workspace (SELECT against `project`; fail loud with a typed error if not), then for **every** account the batch resolves-to or creates, `ensure_project_account(added_via="imported")`, and register the batch run in `run_lineage` with the real `project_id` (upgrading Task 4's `None`; `record_run_lineage` is `DO NOTHING` on conflict, so mint-once ordering matters — register once, here, with the final value; adjust Task 4's import call accordingly). When `None`: workspace-level import, global-only accounts (spec §8.3) — today's behavior. Tool: add the optional `project_id` field to the pydantic args following the toolbelt's existing convention for additive-optional params (inspect a precedent in `toolbelt_wiring.py` before deciding whether this stays `@1` or bumps `@2`; report which and why).

**Steps:**
- [ ] **6.1** Failing tests: (a) import with `project_id` → membership rows for both a newly-created and a resolved-to-existing account; (b) import without → zero membership rows, unchanged legacy assertions; (c) unknown project → typed error, no accounts created (transactional); (d) lineage row carries the project.
- [ ] **6.2** → fail. **6.3** Implement. **6.4** → pass; `make check`. Report.

---

### Task 7: H1 — embed on creation + admission aliases + embedding backfill

**Files:**
- Modify: `subsystems/research/clue_research/identity/review.py` (new-entity sites ~:425-432 and ~:693-700)
- Modify: `subsystems/research/clue_research/discovery_scoring/gate/admission.py` (`_to_observation` ~:89-99)
- Create: `scripts/backfill_account_embeddings.py`
- Test: `tests/identity/test_h1_discovery_embedding.py`

**Behavior:** First read how `import_accounts.py:361` calls `embed_account` and what dependency it needs (`identity/embedding.py`). Thread that same dependency into `disposition()` as an **optional** parameter (embedder absent → skip embedding, exactly today's behavior — no hard new requirement on callers), and pass it from the admission gate's wiring (`admission.py` → its composition-root construction) so the discovery path embeds. Also populate `Observation.aliases` in `_to_observation` from the candidate's name via the same normalization import uses (`import_accounts.py:440-448` is the pattern; `name_key` machinery is in `identity/normalize.py:90-104`). Backfill script: iterate `account_entity` rows with no `account_entity_embedding` row, embed each (batch, idempotent, prints counts; dev-data scale).

**Steps:**
- [ ] **7.1** Failing regression test — the exact §1.2-H1 scenario: create an account through the admission/disposition path (with embedder wired), then `resolve` the same company **name-only** (no domain) → assert the disposition is the **review band** (`ENQUEUED`, score ≥ 0.70), not `NEW_ENTITY`. Mirror `tests/identity/test_review.py:215-241` but WITHOUT its `_seed` helper's manual `embed_account` call — creation itself must embed.
- [ ] **7.2** → fail (score 0.40, NEW_ENTITY). **7.3** Implement. **7.4** → pass; run the whole `tests/identity/` dir; `make check`. Report.

---

### Task 8: H2 — enrich-survivor on strong-key match

**Files:**
- Modify: `subsystems/research/clue_research/identity/review.py` (AUTO_MERGED, `subject_entity_id is None` branch, ~:393-403)
- Modify (if a helper is added): `subsystems/research/clue_research/identity/entities.py` (reuse `update_account` ~:282-323 / `canonicalize.plan_merge` logic)
- Test: `tests/identity/test_h2_enrich_survivor.py`

**Behavior (conservative, per spec §8.2):** when a disposition AUTO_MERGES an observation onto an existing survivor, apply in the same transaction: `aliases` ∪ observation aliases; `registry_ids` ∪ observation registry ids with **survivor-wins on conflict**; fill `primary_domain`/geo **only if the survivor's is missing** (and the domain fill must respect the `(workspace_id, primary_domain)` unique index — on violation, skip the fill, don't fail the ingest); **never** change `canonical_name`. Implement as a small `enrich_survivor(conn, *, survivor_id, observation, workspace_id)` built on the existing `update_account`, not by fabricating a loser entity for `auto_merge`.

**Steps:**
- [ ] **8.1** Failing tests: (a) import-matches-existing-by-domain where the observation carries a new alias + a DUNS the survivor lacks → survivor row gains both; (b) survivor already has a different DUNS → survivor's kept; (c) survivor has no geo, observation does → filled; survivor has geo → untouched; (d) `canonical_name` never changes; (e) `canonical_version` bumps iff something changed (match `update_account`'s existing versioning semantics — verify first).
- [ ] **8.2** → fail. **8.3** Implement. **8.4** → pass; `tests/identity/` green; `make check`. Report.

---

### Task 9: backfill script for membership + lineage

**Files:**
- Create: `scripts/backfill_fi2_slice0.py`
- Test: `tests/test_fi2_backfill.py` (fixture-seeded, calls the script's functions directly)

**Behavior (idempotent; dev-data only per the B3 synthetic-data ruling; prints before/after counts):**
1. Membership from discovery: `discovery_candidate_link` (status admitted/merged, use `survivor_entity_id` else `account_entity_id`) JOIN `discovery_batch` → `project_run_id` JOIN `project_run` → `project_id` ⇒ `ensure_project_account(added_via='discovered', added_at=<link/batch created_at>)`.
2. Membership from directives: `account_research_directive_account` JOIN `account_research_directive` → `project_id` ⇒ `added_via='directive'`.
3. Lineage from discovery: for each `project_run` × its pinned `(icp_key, icp_version)`, recompute `uuid5(NAMESPACE_URL, f"clue:discovery-run:{project_run_id}:{icp_key}:{icp_version}")` (copy the exact formula from `discovery_scoring/phases.py:111-124` — import it if importable, else replicate with a cross-check test against the real function) ⇒ `record_run_lineage(kind='discovery')`.
4. Lineage from M8D: `entity_research_job` rows ⇒ `record_run_lineage(run_id=research_run_id, kind='entity_research', project_run_id=…, project_id=<via project_run>)`.
5. Lineage from `account_run` ⇒ `kind='entity_research'` via its `project_run_id`.

**Steps:**
- [ ] **9.1** Failing test: seed a minimal fixture (one project_run, one discovery_candidate_link chain, one entity_research_job, one directive membership) → run backfill twice → assert exact expected membership/lineage rows and that the second run changes nothing.
- [ ] **9.2** → fail. **9.3** Implement. **9.4** → pass; `make check`. Report.

---

### Task 10: canonical two-project fixture + full gate

**Files:**
- Create: `tests/integration/test_fi2_slice0_two_projects.py` (place beside existing integration-style tests if a different dir convention exists — check first)

**Steps:**
- [ ] **10.1** Write the spec-§10 canonical fixture as one test module: workspace W; project A discovers acme.com (admission path, embedder wired); project B imports acme.com (with `project_id=B`). Assert: (a) one `account_entity` (same id both paths); (b) membership = {(A,'discovered'), (B,'imported')} and `projects_for_accounts` orders A before B; (c) every claim written by both paths resolves through `run_lineage` to the right project; (d) B's import observation enriched the survivor (H2: new alias present); (e) name-only re-encounter of acme lands in the review band (H1); (f) merged-loser membership re-pointing (create a duplicate by name, human-merge it, assert membership moved).
- [ ] **10.2** Make it pass (this should be wiring-free if Tasks 1–9 landed; fix what it flushes out).
- [ ] **10.3** Full gate: `make check` AND `make db-smoke` AND `alembic heads` (exactly one). Report full output summary.

---

## Self-review (done at plan-writing time)

- **Spec coverage:** §2→Tasks 2,5,9; §3→Tasks 1,4,9; §4/§5→Task 3; §8.1→Task 7; §8.2→Task 8; §8.3→Task 6; §9-slice-0 ACs (a)–(f) → Tasks 1–3 (db-smoke/head), 4 (lineage per path), 10 (convergence+membership), 7 (H1), 8 (H2), 3 (parity untouched — no DB enums added). §6 (economics) and §7 (read layer) are slices 1–3, deliberately absent.
- **Known unknowns delegated with guardrails, not placeholders:** exact `project` table shape (Task 2 verifies via `b366c985ca12`), `embed_account`'s dependency (Task 7 reads the import call site first), tool-version convention (Task 6 reports its choice), scoring FieldDef registration site (Task 3 locates by grep). Each has an explicit verify-then-act instruction and a reportable decision.
- **Type consistency:** `record_run_lineage`/`ensure_project_account`/`repoint_project_accounts`/`projects_for_accounts` signatures are declared once (Tasks 1–2) and consumed by name in Tasks 4–6, 9, 10.
