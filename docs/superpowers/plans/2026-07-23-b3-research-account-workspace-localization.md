# [B3×research] Account Workspace-Localization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Complete the `[B3×research]` backlog item — every account/contact entity is created workspace-stamped, all identity resolution and strong-key uniqueness become workspace-local, cross-tenant enrichment reuse is retired, and the B4 toolbelt account guard flips from a warning to a real fail-closed check.

**Architecture:** The memory lane (migration `50b778e4009a`) already added nullable `workspace_id`/`brand_id` + the `UNIQUE (id, workspace_id)` anchor to `account_entity`. This plan adds the research-lane half: one new migration (contact workspace column + composite FKs + re-scoped strong-key uniqueness), a contract-delta on the frozen-core entity models, workspace-required entity writers, workspace-filtered resolution, threading `workspace_id` through all six creation call chains, and the downstream unlocks (toolbelt guard, cache keying, docs supersession). Tenancy becomes a property of the data model: composite FKs onto the `(id, workspace_id)` anchors make cross-workspace merges and contact/account workspace mismatches *unrepresentable*, not merely checked.

**Tech Stack:** Python 3.12 / SQLAlchemy async (raw `text()` SQL) / Alembic (hash revision ids) / Postgres 15+ + pgvector / pydantic v2 frozen models / pytest.

## Global Constraints

- **Branch:** create `research/b3-account-workspace-localization` off `platform/b4-toolbelt-v0` (current head, clean). Never commit to `main`. **Never push.** No AI attribution in commits.
- **Alembic:** new migration ids are **random hashes** via `uv run alembic revision -m "<slug>"` — never hand-picked sequentials. `down_revision` = current head `7f2a9c4b1d8e`. Exactly one head at all times. Every `upgrade()` has a matching `downgrade()`. Named constraints/indexes.
- **Frozen core:** additions to `libs/clue-core/clue_core/entity.py` are a **contract-delta**: new fields defaulted (`None`), with an in-code comment citing the founder ruling 2026-07-22 and migration `50b778e4009a` (precedent: `clue_core/handoff.py:195`, `clue_core/verification.py:236`).
- **Gates:** `make check` (= `lint` + `typecheck` + `contracts` + `test`) and `make db-smoke` (up→down→up on a clean throwaway DB) must be green at the end of every task. DB tests need `make db-up` + `CLUE_DATABASE_URL` (see `tests/identity/conftest.py`).
- **Fail-closed:** an unknown/NULL/other-workspace entity is refused or invisible; never silently served. Errors are typed and loud.
- **Legacy rows:** `account_entity.workspace_id` stays **nullable at the DB** (the memory lane's fail-closed NULL semantics and its tests depend on NULL being representable). "Mandatory" is enforced at the writers (required param) — the application can no longer create a NULL-workspace row.
- **Vocabulary:** `workspace_id` (never `tenant_id`/`client_id`) for new code. The `IdempotencyScope` value strings and DB enum values are frozen — do not touch.

## Decisions locked for this plan

(D1) Contacts get their **own denormalized `workspace_id` column** + composite FK `(account_entity_id, workspace_id) → account_entity (id, workspace_id)` — contact workspace ≡ parent account workspace, enforced structurally. (D2) DB columns stay nullable; **writers require workspace**; legacy NULL rows become invisible to resolution and refused by the toolbelt. (D3) Research does **not** stamp `brand_id` (stays NULL; param plumbed for future callers; brand is 1-per-workspace in V1 and nothing in the research lane carries it). (D4) `reusable_public_value` (the cross-tenant amortization hook, zero production callers) is **deleted**; `reuse_scope`/`check_claim_writable`/DSAR machinery stay as privacy classification. (D5) The toolbelt guard **refuses NULL-workspace (legacy) accounts** as well as mismatches.

---

### Task 1: Migration + core contract-delta + entity writers/readers

**Files:**
- Create: `alembic/versions/<hash>_account_contact_workspace_local.py` (via `alembic revision`)
- Modify: `libs/clue-core/clue_core/entity.py` (AccountEntity, ContactEntity)
- Modify: `subsystems/research/clue_research/identity/entities.py` (`_ACCOUNT_COLUMNS`, `_CONTACT_COLUMNS`, `_INSERT_ACCOUNT`, `_INSERT_CONTACT`, `insert_account_entity`, `insert_contact_entity`, `mark_merged`; new `CrossWorkspaceMergeError`)
- Modify: `subsystems/research/clue_research/identity/__init__.py` (export `CrossWorkspaceMergeError`)
- Test: `tests/identity/test_workspace_locality.py` (new), touch-ups in `tests/identity/test_entity_model.py`

**Interfaces:**
- Consumes: existing `account_entity_workspace_anchor UNIQUE (id, workspace_id)` from `50b778e4009a`; `workspace` table from `98422adaaa38`.
- Produces (later tasks rely on):
  - `insert_account_entity(conn, *, canonical_name, primary_domain=None, aliases=(), hq_geo=None, registry_ids=None, status=AccountStatus.CANDIDATE, workspace_id: str | None = None, brand_id: str | None = None) -> EntityId` (transitional optional; Task 3 flips `workspace_id` to required `str`).
  - `insert_contact_entity(...)` — signature unchanged; stamps `workspace_id` from the parent account inside the INSERT.
  - `AccountEntity.workspace_id: str | None`, `AccountEntity.brand_id: str | None`, `ContactEntity.workspace_id: str | None`.
  - `CrossWorkspaceMergeError(ValueError)` raised by `mark_merged` on a cross-workspace pair.

- [ ] **Step 1: Create the migration skeleton**

Run: `uv run alembic revision -m "account contact workspace local"`
This assigns a hash revision id; confirm `down_revision = "7f2a9c4b1d8e"`. Then fill in:

```python
"""account/contact workspace-local — [B3×research] research-lane completion.

Founder ruling 2026-07-22 (see 50b778e4009a): accounts are workspace-local — no global account
identity, no cross-tenant enrichment reuse. 50b778e4009a added the nullable columns + anchor on
account_entity; this migration adds the research half: contact_entity.workspace_id (denormalized,
composite-FK-bound to the parent account so contact workspace ≡ account workspace is
unrepresentable otherwise), within-workspace merge FKs on both entity tables, and workspace-scoped
strong-key uniqueness (legacy NULL-workspace rows keep the old global uniqueness via partial
indexes). Columns stay nullable — legacy rows remain representable and fail-closed everywhere.
"""

from alembic import op

_REGISTRIES = ("DUNS", "NPI", "CIK", "LEI")  # mirror 0005_entity_model._IDENTIFYING_REGISTRIES


def upgrade() -> None:
    # 1. contact_entity gains workspace_id, bound to its parent account's (id, workspace_id).
    op.execute("ALTER TABLE contact_entity ADD COLUMN workspace_id text")
    op.execute(
        "ALTER TABLE contact_entity ADD CONSTRAINT contact_entity_workspace_fk "
        "FOREIGN KEY (workspace_id) REFERENCES workspace (workspace_id)"
    )
    op.execute(
        "ALTER TABLE contact_entity ADD CONSTRAINT contact_entity_account_workspace_fk "
        "FOREIGN KEY (account_entity_id, workspace_id) "
        "REFERENCES account_entity (id, workspace_id)"
    )
    op.execute(
        "ALTER TABLE contact_entity ADD CONSTRAINT contact_entity_workspace_anchor "
        "UNIQUE (id, workspace_id)"
    )
    # 2. Backfill from the parent account (no-op on legacy NULL parents).
    op.execute(
        "UPDATE contact_entity c SET workspace_id = a.workspace_id "
        "FROM account_entity a WHERE c.account_entity_id = a.id "
        "AND a.workspace_id IS NOT NULL"
    )
    # 3. Within-workspace merge fences (MATCH SIMPLE: NULL workspace ⇒ unenforced ⇒ legacy-safe).
    op.execute(
        "ALTER TABLE account_entity ADD CONSTRAINT account_entity_merge_same_workspace "
        "FOREIGN KEY (merged_into, workspace_id) REFERENCES account_entity (id, workspace_id)"
    )
    op.execute(
        "ALTER TABLE contact_entity ADD CONSTRAINT contact_entity_merge_same_workspace "
        "FOREIGN KEY (merged_into, workspace_id) REFERENCES contact_entity (id, workspace_id)"
    )
    # 4. Strong-key uniqueness → workspace-scoped; legacy NULL-workspace rows keep global semantics.
    op.execute("DROP INDEX account_entity_primary_domain_key")
    op.execute(
        "CREATE UNIQUE INDEX account_entity_primary_domain_ws_key "
        "ON account_entity (workspace_id, primary_domain) "
        "WHERE primary_domain IS NOT NULL AND workspace_id IS NOT NULL"
    )
    op.execute(
        "CREATE UNIQUE INDEX account_entity_primary_domain_legacy_key "
        "ON account_entity (primary_domain) "
        "WHERE primary_domain IS NOT NULL AND workspace_id IS NULL"
    )
    for ns in _REGISTRIES:
        op.execute(f"DROP INDEX account_entity_registry_{ns.lower()}_key")
        op.execute(
            f"CREATE UNIQUE INDEX account_entity_registry_{ns.lower()}_ws_key "
            f"ON account_entity (workspace_id, (registry_ids->>'{ns}')) "
            f"WHERE registry_ids ? '{ns}' AND workspace_id IS NOT NULL"
        )
        op.execute(
            f"CREATE UNIQUE INDEX account_entity_registry_{ns.lower()}_legacy_key "
            f"ON account_entity ((registry_ids->>'{ns}')) "
            f"WHERE registry_ids ? '{ns}' AND workspace_id IS NULL"
        )
    op.execute("DROP INDEX contact_entity_linkedin_url_key")
    op.execute(
        "CREATE UNIQUE INDEX contact_entity_linkedin_url_ws_key "
        "ON contact_entity (workspace_id, linkedin_url) "
        "WHERE linkedin_url IS NOT NULL AND workspace_id IS NOT NULL"
    )
    op.execute(
        "CREATE UNIQUE INDEX contact_entity_linkedin_url_legacy_key "
        "ON contact_entity (linkedin_url) "
        "WHERE linkedin_url IS NOT NULL AND workspace_id IS NULL"
    )
    op.execute("DROP INDEX contact_entity_verified_email_key")
    op.execute(
        "CREATE UNIQUE INDEX contact_entity_verified_email_ws_key "
        "ON contact_entity (workspace_id, verified_email) "
        "WHERE verified_email IS NOT NULL AND workspace_id IS NOT NULL"
    )
    op.execute(
        "CREATE UNIQUE INDEX contact_entity_verified_email_legacy_key "
        "ON contact_entity (verified_email) "
        "WHERE verified_email IS NOT NULL AND workspace_id IS NULL"
    )
    # 5. Plain lookup indexes for the workspace-filtered resolution queries (Task 2).
    op.execute("CREATE INDEX account_entity_workspace ON account_entity (workspace_id)")
    op.execute("CREATE INDEX contact_entity_workspace ON contact_entity (workspace_id)")


def downgrade() -> None:
    op.execute("DROP INDEX contact_entity_workspace")
    op.execute("DROP INDEX account_entity_workspace")
    op.execute("DROP INDEX contact_entity_verified_email_legacy_key")
    op.execute("DROP INDEX contact_entity_verified_email_ws_key")
    op.execute(
        "CREATE UNIQUE INDEX contact_entity_verified_email_key ON contact_entity (verified_email) "
        "WHERE verified_email IS NOT NULL"
    )
    op.execute("DROP INDEX contact_entity_linkedin_url_legacy_key")
    op.execute("DROP INDEX contact_entity_linkedin_url_ws_key")
    op.execute(
        "CREATE UNIQUE INDEX contact_entity_linkedin_url_key ON contact_entity (linkedin_url) "
        "WHERE linkedin_url IS NOT NULL"
    )
    for ns in _REGISTRIES:
        op.execute(f"DROP INDEX account_entity_registry_{ns.lower()}_legacy_key")
        op.execute(f"DROP INDEX account_entity_registry_{ns.lower()}_ws_key")
        op.execute(
            f"CREATE UNIQUE INDEX account_entity_registry_{ns.lower()}_key "
            f"ON account_entity ((registry_ids->>'{ns}')) WHERE registry_ids ? '{ns}'"
        )
    op.execute("DROP INDEX account_entity_primary_domain_legacy_key")
    op.execute("DROP INDEX account_entity_primary_domain_ws_key")
    op.execute(
        "CREATE UNIQUE INDEX account_entity_primary_domain_key ON account_entity (primary_domain) "
        "WHERE primary_domain IS NOT NULL"
    )
    op.execute(
        "ALTER TABLE contact_entity DROP CONSTRAINT contact_entity_merge_same_workspace"
    )
    op.execute(
        "ALTER TABLE account_entity DROP CONSTRAINT account_entity_merge_same_workspace"
    )
    op.execute("ALTER TABLE contact_entity DROP CONSTRAINT contact_entity_workspace_anchor")
    op.execute("ALTER TABLE contact_entity DROP CONSTRAINT contact_entity_account_workspace_fk")
    op.execute("ALTER TABLE contact_entity DROP CONSTRAINT contact_entity_workspace_fk")
    op.execute("ALTER TABLE contact_entity DROP COLUMN workspace_id")
```

**Verify against the on-disk `0005_entity_model.py` before writing** — the exact original index definitions being restored in `downgrade()` (predicates, expression syntax) must match what `0005` created, and confirm the four registry index names use `.lower()` naming.

- [ ] **Step 2: Run db-smoke to verify reversibility**

Run: `make db-up && make db-fresh && make db-smoke` — expect up→down→up green, and `uv run alembic heads` → exactly one head (the new hash).

- [ ] **Step 3: Contract-delta on the core entity models**

In `libs/clue-core/clue_core/entity.py`, add to `AccountEntity` (after `merged_into`):

```python
    # Workspace tenancy (contract-delta 2026-07-23, [B3×research]): accounts are workspace-local
    # (founder ruling 2026-07-22; migrations 50b778e4009a + the research-lane follow-up). Defaulted
    # None so pre-delta readers and legacy NULL-workspace rows keep validating.
    workspace_id: str | None = None
    brand_id: str | None = None
```

and to `ContactEntity` (after `merged_into`):

```python
    # Workspace tenancy (contract-delta 2026-07-23, [B3×research]): denormalized from the parent
    # account; the composite FK (account_entity_id, workspace_id) makes a mismatch unrepresentable.
    workspace_id: str | None = None
```

- [ ] **Step 4: Write failing tests for the writers**

Create `tests/identity/test_workspace_locality.py` (use the existing `tests/identity/conftest.py` fixtures: `require_identity_db`, `rollback_conn`). Include a local helper to satisfy the workspace FK:

```python
from sqlalchemy import text

async def seed_workspace(conn, workspace_id: str) -> str:
    await conn.execute(
        text(
            "INSERT INTO workspace (workspace_id, name) VALUES (:w, :w) "
            "ON CONFLICT (workspace_id) DO NOTHING"
        ),
        {"w": workspace_id},
    )
    return workspace_id
```

Tests (all `async`, using `rollback_conn`):

```python
async def test_insert_account_stamps_workspace(rollback_conn):
    ws = await seed_workspace(rollback_conn, "ws_t1")
    eid = await insert_account_entity(
        rollback_conn, canonical_name="Acme", primary_domain="acme.com", workspace_id=ws
    )
    account = await get_account(rollback_conn, eid)
    assert account is not None and account.workspace_id == ws and account.brand_id is None

async def test_same_domain_two_workspaces_coexist(rollback_conn):
    a, b = await seed_workspace(rollback_conn, "ws_a"), await seed_workspace(rollback_conn, "ws_b")
    id_a = await insert_account_entity(rollback_conn, canonical_name="Acme", primary_domain="acme.com", workspace_id=a)
    id_b = await insert_account_entity(rollback_conn, canonical_name="Acme", primary_domain="acme.com", workspace_id=b)
    assert id_a != id_b

async def test_same_domain_same_workspace_collides(rollback_conn):
    ws = await seed_workspace(rollback_conn, "ws_dup")
    await insert_account_entity(rollback_conn, canonical_name="Acme", primary_domain="acme.com", workspace_id=ws)
    with pytest.raises(IntegrityError):
        await insert_account_entity(rollback_conn, canonical_name="Acme 2", primary_domain="acme.com", workspace_id=ws)

async def test_contact_inherits_parent_workspace(rollback_conn):
    ws = await seed_workspace(rollback_conn, "ws_c")
    acc = await insert_account_entity(rollback_conn, canonical_name="Acme", workspace_id=ws)
    cid = await insert_contact_entity(rollback_conn, account_entity_id=acc, full_name="Jo Doe")
    contact = await get_contact(rollback_conn, cid)
    assert contact is not None and contact.workspace_id == ws

async def test_contact_strong_key_scoped_per_workspace(rollback_conn):
    # same linkedin_url under accounts in two workspaces coexists; dup within one collides
    ...

async def test_cross_workspace_merge_refused(rollback_conn):
    ws1, ws2 = await seed_workspace(rollback_conn, "ws_m1"), await seed_workspace(rollback_conn, "ws_m2")
    e1 = await insert_account_entity(rollback_conn, canonical_name="A", workspace_id=ws1)
    e2 = await insert_account_entity(rollback_conn, canonical_name="B", workspace_id=ws2)
    with pytest.raises(CrossWorkspaceMergeError):
        await mark_merged(rollback_conn, EntityType.ACCOUNT, e1, e2)

async def test_legacy_null_workspace_account_still_insertable_via_raw_sql(rollback_conn):
    # the memory-lane fail-closed semantics depend on NULL rows staying representable at the DB
    ...
```

Run: `uv run pytest tests/identity/test_workspace_locality.py -v` — expect FAIL (unknown `workspace_id` kwarg / missing model fields).

- [ ] **Step 5: Implement the writers/readers**

In `subsystems/research/clue_research/identity/entities.py`:

```python
_ACCOUNT_COLUMNS = (
    "id, canonical_name, primary_domain, aliases, hq_geo, registry_ids, status, merged_into, "
    "workspace_id, brand_id"
)
_CONTACT_COLUMNS = (
    "id, account_entity_id, full_name, linkedin_url, verified_email, aliases, geo, "
    "jurisdiction, status, merged_into, workspace_id"
)

_INSERT_ACCOUNT = text(
    """
    INSERT INTO account_entity (canonical_name, primary_domain, aliases, hq_geo, registry_ids,
                                status, workspace_id, brand_id)
    VALUES (:canonical_name, :primary_domain, :aliases, CAST(:hq_geo AS jsonb),
            CAST(:registry_ids AS jsonb), CAST(:status AS entity_status), :workspace_id, :brand_id)
    RETURNING id
    """
).bindparams(bindparam("aliases", type_=ARRAY(String())))

# insert_contact_entity: stamp the parent's workspace atomically in the INSERT itself
_INSERT_CONTACT = text(
    """
    INSERT INTO contact_entity (account_entity_id, full_name, linkedin_url, verified_email,
                                aliases, geo, jurisdiction, status, workspace_id)
    VALUES (:account_entity_id, :full_name, :linkedin_url, :verified_email, :aliases,
            CAST(:geo AS jsonb), :jurisdiction, CAST(:status AS entity_status),
            (SELECT workspace_id FROM account_entity WHERE id = :account_entity_id))
    RETURNING id
    """
).bindparams(bindparam("aliases", type_=ARRAY(String())))
```

`insert_account_entity` gains `workspace_id: str | None = None, brand_id: str | None = None` keyword params (docstring: transitional-optional, flipped to required in Task 3 of this plan) and passes both through. `mark_merged` gains the app-level fence (clear error before the FK would fire, and it also covers the NULL/legacy asymmetry the FK cannot):

```python
class CrossWorkspaceMergeError(ValueError):
    """Merge loser and survivor live in different workspaces — forbidden (accounts are
    workspace-local; founder ruling 2026-07-22). The composite merge FK backstops this."""


async def mark_merged(conn, entity_type, loser_id, survivor_id) -> None:
    if loser_id == survivor_id:
        raise MergeCycleError("an entity cannot be merged into itself")
    table = _table(entity_type)
    rows = (
        await conn.execute(
            text(f"SELECT id, workspace_id FROM {table} WHERE id IN (:a, :b)"),
            {"a": loser_id, "b": survivor_id},
        )
    ).mappings().all()
    scopes = {row["id"]: row["workspace_id"] for row in rows}
    if scopes.get(loser_id) != scopes.get(survivor_id):
        raise CrossWorkspaceMergeError(
            f"cannot merge across workspaces: {scopes.get(loser_id)!r} -> {scopes.get(survivor_id)!r}"
        )
    ...  # existing UPDATE unchanged
```

Export `CrossWorkspaceMergeError` from `identity/__init__.py`.

- [ ] **Step 6: Run the new tests + the full identity suite**

Run: `uv run pytest tests/identity/ -v` — all pass (existing tests unaffected: the new params default to `None`).

- [ ] **Step 7: Full gate + commit**

Run: `make check && make db-smoke`. Then:

```bash
git add alembic/versions/ libs/clue-core/ subsystems/research/clue_research/identity/ tests/identity/
git commit -m "feat(identity): B3xresearch slice 1 — workspace-local entity schema + stamped writers

Contact workspace column bound to the parent account by composite FK, within-workspace
merge fences, workspace-scoped strong-key uniqueness (legacy NULL rows keep global
semantics via partial indexes), core contract-delta, transitional-optional writer params."
```

---

### Task 2: Workspace-scoped identity resolution

**Files:**
- Modify: `subsystems/research/clue_research/identity/resolve.py` (`resolve`, `resolve_many`, `_deterministic_account`, `_deterministic_contact`, `_candidate_ids_account`, `_fetch_account_records`)
- Test: `tests/identity/test_workspace_locality.py` (extend), `tests/identity/test_resolve.py` (thread the new param)

**Interfaces:**
- Consumes: Task 1's stamped writers (tests create stamped entities).
- Produces: `resolve(conn, obs, *, policy=..., embedder=..., workspace_id: str | None = None) -> ResolutionResult` and the same param on `resolve_many` — **transitional-optional in this task** (`None` preserves today's unscoped behavior so existing callers keep compiling); Task 3 flips to required `str` and deletes the `None` branch.

- [ ] **Step 1: Write failing isolation tests**

Extend `tests/identity/test_workspace_locality.py`:

```python
async def test_deterministic_domain_match_is_workspace_scoped(rollback_conn):
    ws_a, ws_b = await seed_workspace(rollback_conn, "ws_ra"), await seed_workspace(rollback_conn, "ws_rb")
    id_a = await insert_account_entity(rollback_conn, canonical_name="Acme", primary_domain="acme.com", workspace_id=ws_a)
    obs = Observation(name="Acme", entity_type=EntityType.ACCOUNT, domain="acme.com")
    hit_a = await resolve(rollback_conn, obs, workspace_id=ws_a)
    miss_b = await resolve(rollback_conn, obs, workspace_id=ws_b)
    assert hit_a resolved to id_a           # match the ResolutionResult shape in test_resolve.py
    assert miss_b did NOT resolve to id_a   # ws_b sees nothing — NEW_ENTITY / no candidates
```

Plus the same shape for: registry-id match, contact strong-key match, alias-block candidates, trigram candidates, and ANN candidates (seed via `embed_account`; copy the embedding-seeding pattern from `tests/identity/test_resolve.py` / `test_embedding.py`). Also: `test_legacy_null_workspace_rows_invisible_to_scoped_resolution` — a raw-SQL NULL-workspace account with domain `legacy.com` is NOT found by `resolve(..., workspace_id="ws_x")`.

Run: `uv run pytest tests/identity/test_workspace_locality.py -v` — expect FAIL (no `workspace_id` param).

- [ ] **Step 2: Implement the filters**

Thread `workspace_id: str | None` from `resolve`/`resolve_many` into every query. Pattern (transitional — the `None` arm dies in Task 3):

```python
ws_clause = "AND workspace_id = :ws" if workspace_id is not None else ""
# _deterministic_account domain probe:
text(f"SELECT id FROM account_entity WHERE primary_domain = :d {ws_clause} LIMIT 1")
# registry probe:
text(f"SELECT id FROM account_entity WHERE registry_ids->>:ns = :v {ws_clause} LIMIT 1")
# _deterministic_contact:
text(f"SELECT id FROM contact_entity WHERE (linkedin_url = :s OR verified_email = :s) {ws_clause} LIMIT 1")
# ANN join (alias `a`):
"JOIN account_entity a ON a.id = e.entity_id WHERE a.status <> 'merged' " + ("AND a.workspace_id = :ws " if ...)
# alias-block and trigram queries: append the same clause after status <> 'merged'.
```

Bind `{"ws": workspace_id}` only when scoped. `_fetch_account_records` needs no filter (it fetches by already-scoped ids) — but add `workspace_id` to its SELECT list only if needed by scoring (it is not; leave it).

- [ ] **Step 3: Run tests**

Run: `uv run pytest tests/identity/ -v` — new isolation tests pass; existing `test_resolve.py` still green (unscoped `None` path unchanged).

- [ ] **Step 4: Gate + commit**

```bash
make check
git add subsystems/research/clue_research/identity/resolve.py tests/identity/
git commit -m "feat(identity): B3xresearch slice 2 — workspace-scoped resolution

Deterministic, ANN, alias-block and trigram candidate queries filter by workspace;
legacy NULL-workspace rows are invisible to a scoped resolve (fail-closed)."
```

---

### Task 3: Thread workspace through every creation chain; flip writers/resolution to required

**Files:**
- Modify: `subsystems/research/clue_research/stage0/client_kb.py` (`_resolve_client` ~241, callsite ~147)
- Modify: `subsystems/research/clue_research/stage0/seeds.py` (`_resolve_customer` ~379/413)
- Modify: `subsystems/research/clue_research/stage0/import_accounts.py` (`_resolve_contact_entity` ~683/698, `_resolve_and_tag_contact` ~614; any `disposition(`/`resolve(` calls)
- Modify: `subsystems/research/clue_research/identity/review.py` (`disposition` ~336/406, `resolve_create_new_entity` ~614/625)
- Modify: `subsystems/research/clue_research/discovery_scoring/gate/admission.py` (`admit` ~208, `_admit_resolved` ~178)
- Modify: `subsystems/research/clue_research/discovery_scoring/phases.py` (~146: pass `ctx.workspace_id`)
- Modify: `subsystems/research/clue_research/profiling/committee/admission.py` (`admit_candidate` ~132/164) and `profiling/committee/worker.py` (~284)
- Modify: `subsystems/research/clue_research/identity/entities.py` + `identity/resolve.py` (flip `workspace_id` to required `str`, delete transitional `None` branches)
- Test: `tests/identity/test_review.py`, `tests/stage0/test_seeds.py`, `tests/discovery_scoring/`, `tests/profiling/`, plus every test the flip breaks (mypy + pytest will enumerate)

**Interfaces:**
- Consumes: Task 1 writer params, Task 2 `resolve(..., workspace_id=...)`.
- Produces (final signatures — later tasks and production code rely on):
  - `insert_account_entity(..., workspace_id: str, brand_id: str | None = None)` — **required**.
  - `resolve(conn, obs, *, policy=..., embedder=..., workspace_id: str)` / same on `resolve_many` — **required**.
  - `disposition(conn, observation, result, *, policy=..., redis=None, workspace_id: str, decided_by=..., subject_entity_id=None)` — **required** (was `str | None = None`).
  - `admit(conn, candidate, run_id, *, workspace_id: str, redis=..., existence=..., ...)`.
  - `admit_candidate` unchanged externally — it reads `account.workspace_id` off the `AccountEntity` it already receives and fails loud (`ValueError`) if that is `None`.

- [ ] **Step 1: Write the failing stamped-creation tests first**

For each entry path, one test asserting the created entity is stamped. Examples (place next to each path's existing suite, reusing its fixtures):

```python
# tests/identity/test_review.py — disposition new-entity branch
async def test_disposition_new_entity_stamps_workspace(rollback_conn):
    ws = await seed_workspace(rollback_conn, "ws_disp")
    result = ...  # a below-threshold ResolutionResult, copied from the existing new-entity test
    outcome = await disposition(rollback_conn, obs, result, workspace_id=ws, decided_by="test")
    account = await get_account(rollback_conn, outcome.entity_id)
    assert account.workspace_id == ws

# tests/identity/test_review.py — human create-new-entity resolution
async def test_resolve_create_new_entity_stamps_task_workspace(rollback_conn):
    ...  # enqueue a review task with workspace_id=ws (existing enqueue fixture), resolve, assert stamp

# tests/stage0/test_seeds.py: the admitted-customer seed account carries the workspace
# tests/discovery_scoring/: an admitted discovery candidate carries ctx.workspace_id
# tests/profiling/: a committee-admitted contact carries the account's workspace
```

Run each: expect FAIL (unstamped / signature errors).

- [ ] **Step 2: Thread the chains**

Exact edits per site (each is "add a param, pass it down"):
1. `client_kb.py`: `_resolve_client(conn, client_input, *, workspace_id: str)`; caller at ~147 passes `workspace_id=workspace_id` (already in `reverse_profile` scope); `insert_account_entity(..., workspace_id=workspace_id)` at ~268.
2. `seeds.py` ~413: add `workspace_id=workspace_id` (already in `_resolve_customer` scope).
3. `review.py` `disposition`: change `workspace_id: str | None = None` → `workspace_id: str` (move it before the defaulted params, keyword-only section) and pass to `insert_account_entity` at ~406, keeping the existing `enqueue_review_task`/lock uses.
4. `review.py` `resolve_create_new_entity` ~625: `ws = task.workspace_id`; if `ws is None`: `raise MergeCycleError`-style typed error — add `class ReviewTaskUnscopedError(ValueError)` — then `insert_account_entity(..., workspace_id=ws)`.
5. `admission.py`: `admit(..., *, workspace_id: str, ...)` → `_admit_resolved(..., workspace_id=...)` → `disposition(..., workspace_id=workspace_id, decided_by="discovery")`; also pass `workspace_id=workspace_id` to its `resolve(...)` call. `phases.py:146`: `admit(conn, candidate, run_id, workspace_id=ctx.workspace_id, ...)`.
6. `import_accounts.py`: `_resolve_contact_entity(conn, contact, account_id, *, workspace_id: str)` (used for its `resolve(...)` call; the contact INSERT stamps from the parent automatically); `_resolve_and_tag_contact` passes its own `workspace_id`. Grep the file for `disposition(` and `resolve(` and thread `workspace_id` into every call.
7. `committee/admission.py` `admit_candidate`: derive `workspace_id = account.workspace_id`; `if workspace_id is None: raise ValueError("committee admission needs a workspace-stamped account ([B3xresearch])")`; pass into its `resolve(...)` call. `worker.py:284` needs no change if derivation is internal.

- [ ] **Step 3: Flip to required + delete transitional branches**

In `entities.py`: `workspace_id: str` (no default) on `insert_account_entity`. In `resolve.py`: `workspace_id: str` on `resolve`/`resolve_many`; delete the `ws_clause`-empty arm so every query is unconditionally scoped. Run `make typecheck` — mypy enumerates every straggler call site (including tests); fix each by seeding + passing a workspace.

- [ ] **Step 4: Full suite**

Run: `uv run pytest tests/ -x -q` then `make check`. Every existing identity/stage0/discovery/committee test now seeds a workspace — mechanical but wide; keep the diffs minimal (a `seed_workspace` helper + param threading, no test-logic rewrites).

- [ ] **Step 5: Commit**

```bash
git add subsystems/ tests/
git commit -m "feat(research): B3xresearch slice 3 — every entity-creation chain stamps workspace

workspace_id required on insert_account_entity/resolve/disposition/admit; discovery,
import, seeds, client-KB, review and committee chains thread it; committee derives it
from the resolved account and fails loud on an unstamped one."
```

---

### Task 4: Toolbelt account guard — warning becomes fail-closed

**Files:**
- Modify: `platform/api/clue_api/toolbelt_wiring.py` (`_warn_unscoped_account` ~152; `RunDeepAccountTool` ~693/782, `ResolveCommitteeTool` ~814/847, `ProfileContactTool` ~876/917)
- Test: the existing toolbelt test module under `tests/api/` covering these tools (find via `grep -rl "run_deep_account" tests/`)

**Interfaces:**
- Consumes: `AccountEntity.workspace_id` (Task 1), `identity.get_account`.
- Produces: `_load_account(self, tool: str, raw_id: str, ctx: ToolContext, conn) -> AccountEntity | None` — `None` for missing / malformed id / NULL-workspace (legacy) / other-workspace; callers surface the same not-found error shape `_load_run` uses (no existence leak). The `toolbelt.unscoped_account_access` WARNING is deleted; a `toolbelt.account_scope_refused` WARNING is emitted on refusal.

- [ ] **Step 1: Read the three tools' current dispatch shape** (how they open a connection and return errors — mirror `_load_run` at ~329 exactly).

- [ ] **Step 2: Write failing tests**

In the existing toolbelt test module (reuse its harness/fixtures):

```python
async def test_run_deep_account_refuses_cross_workspace_account(...):
    # account stamped ws_b, ctx.workspace_id == ws_a → same error shape as an unknown account id
async def test_run_deep_account_refuses_legacy_null_workspace_account(...):
async def test_run_deep_account_accepts_in_workspace_account(...):
# repeat (or parametrize) for resolve_committee and profile_contact
```

Run: expect FAIL (tools currently warn-and-proceed).

- [ ] **Step 3: Implement**

Replace `_warn_unscoped_account` with:

```python
async def _load_account(
    self, tool: str, raw_id: str, ctx: ToolContext, conn: AsyncConnection
) -> AccountEntity | None:
    """Fail-closed account→workspace guard ([B3×research], resolved 2026-07-23): a missing,
    malformed, legacy NULL-workspace, or other-workspace account resolves to not-found — no
    existence leak, mirroring _load_run. Refusals are WARNING-logged for audit."""
    entity_id = _parse_entity_id(raw_id)   # follow the existing _parse_run_id pattern
    account = await get_account(conn, entity_id) if entity_id is not None else None
    if account is None or account.workspace_id != ctx.workspace_id:
        log.warning(
            "toolbelt.account_scope_refused",
            tool=tool, actor=ctx.actor,
            workspace_id=ctx.workspace_id, account_entity_id=raw_id,
        )
        return None
    return account
```

(`account.workspace_id != ctx.workspace_id` refuses NULL-workspace legacy rows too — decision D5.) Wire all three tools through it; update the module docstring (~45) and the three tool docstrings that reference the residual.

- [ ] **Step 4: Tests green, gate, commit**

```bash
uv run pytest tests/api/ -v && make check
git add platform/api/ tests/api/
git commit -m "feat(toolbelt): B3xresearch slice 4 — account tools fail closed on workspace scope

run_deep_account/resolve_committee/profile_contact refuse cross-workspace and legacy
unstamped accounts as not-found; the unscoped-access warning is retired."
```

---

### Task 5: Retire cross-tenant reuse surface + workspace-keyed cache + docs supersession

**Files:**
- Modify: `subsystems/research/clue_research/identity/reuse.py` (delete `reusable_public_value`; module docstring supersession note), `identity/__init__.py` (drop export)
- Modify: `subsystems/research/clue_research/adapters/cache.py` (`content_key`), `adapters/pipeline.py` (~377-380, ~410-419 call sites)
- Modify: `tests/identity/test_reuse.py` (drop the dead-hook tests), `tests/adapters/test_cache.py`
- Modify (docs supersession notes): `docs/architecture/clue-hq-research-layer-architecture.md` (~29, ~97), `docs/architecture/clue-hq-harness-architecture-and-requirements.md` (~452), `docs/specs/M02-identity-resolution.md` (M2.5 section ~114-135), `docs/specs/M04-source-layer-and-source-intelligence.md` (~161-190), `docs/specs/M12-value-narrative-and-handoff.md` (~133)
- Modify: `CLAUDE.md` (`[B3×research]` entry → done+residuals; `[B4]` residual (c) → resolved)

**Interfaces:**
- Consumes: nothing new. Produces: `content_key(source_key: str, ref: str, workspace_id: str | None) -> str`.

- [ ] **Step 1: Delete `reusable_public_value`** (and its `identity/__init__.py` export + `tests/identity/test_reuse.py` cases). Add to `reuse.py`'s module docstring:

```
Superseded posture (2026-07-23, [B3×research]): accounts are workspace-local (founder ruling
2026-07-22 — provider licensing + GDPR controller separation), so cross-tenant amortization is
retired; entity ids are workspace-bound, making a cross-workspace claim read structurally
unrepresentable. ``reuse_scope`` remains as the *privacy classification* (write-leak guard
``check_claim_writable``; the DSAR selector ``dsar_private_claims``) — it no longer grants
cross-workspace sharing. The old amortization hook ``reusable_public_value`` was deleted here.
```

- [ ] **Step 2: Workspace-keyed cache.** Failing test first (`tests/adapters/test_cache.py`):

```python
def test_content_key_is_workspace_scoped():
    a = content_key("src", "ref", "ws_a")
    b = content_key("src", "ref", "ws_b")
    n = content_key("src", "ref", None)
    assert len({a, b, n}) == 3
```

Then:

```python
def content_key(source_key: str, ref: str, workspace_id: str | None) -> str:
    """Content-address of (source_key, ref) **within one workspace** — no cross-tenant cache
    sharing ([B3×research]); None = the public/unscoped fetch lane, its own partition."""
    digest = hashlib.sha256()
    for part in (source_key, ref, workspace_id or ""):
        digest.update(part.encode("utf-8"))
        digest.update(b"\x00")
    return digest.hexdigest()
```

Update both `pipeline.py` call sites to pass the `workspace_id` already in `run_pipeline`'s scope, and any other `content_key(` callers mypy finds.

- [ ] **Step 3: Docs supersession.** At each listed doc location add a short dated note (blockquote, not a rewrite), e.g.:

```markdown
> **Superseded 2026-07-23 ([B3×research]):** accounts are now workspace-local (founder ruling
> 2026-07-22; provider licensing + GDPR controller separation). Public-footprint claims are no
> longer shareable across workspaces — the amortization described below is retired. `reuse_scope`
> survives only as the privacy classification (write-leak guard + DSAR selector).
```

- [ ] **Step 4: CLAUDE.md.** Rewrite the `[B3×research]` backlog entry as **DONE (date, branch)** with residuals: (a) legacy NULL-workspace rows remain representable at the DB and invisible/fail-closed everywhere — decide backfill-or-purge before go-live; (b) `brand_id` is plumbed but never stamped by research (no brand context in the run lane). Update `[B4]` residual (c) to point at the now-live guard.

- [ ] **Step 5: Gate + commit**

```bash
make check
git add subsystems/ tests/ docs/ CLAUDE.md
git commit -m "feat(research): B3xresearch slice 5 — retire cross-tenant reuse surface

Delete the dead amortization hook, workspace-key the artifact cache, supersede the
cross-tenant amortization language in docs, close the CLAUDE.md backlog entry."
```

---

### Task 6: Close-out

**Files:**
- Create: `_memory/2026-07-23-b3-research-account-workspace-localization.md`

- [ ] **Step 1:** `make check && make db-smoke && uv run alembic heads` (single head).
- [ ] **Step 2:** Write the memory note: what landed per slice, decisions D1–D5 with grounds, residuals (legacy-row disposition, brand stamping, memory-lane docs contrast lines), verification performed.
- [ ] **Step 3:** `git add _memory/ && git commit -m "docs(close-out): B3xresearch executed — memory note"`.

---

## Self-Review notes

- Coverage against the backlog item: stamp-on-creation (T1/T3) ✓; domain/registry strong-key re-scope (T1) ✓; `merged_into` within-workspace (T1) ✓; contact strong-key workspace-local (T1) ✓; caches keyed by workspace (T5) ✓; supersede cross-tenant reuse language (T5) ✓; toolbelt guard unlock — the B4 residual (T4) ✓.
- Type consistency: `workspace_id: str` required on `insert_account_entity`/`resolve`/`resolve_many`/`disposition`/`admit` after T3; `AccountEntity.workspace_id: str | None` (model stays optional — legacy rows readable).
- Known transitional state: T1/T2 ship optional params so each task's gate is green; T3 flips to required. Reviewers should reject any task that leaves an unscoped production write/read path behind after T3.
