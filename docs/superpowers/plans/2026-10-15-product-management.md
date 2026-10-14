# Product management in Brand context — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A person (in the app) or the Head of ABM (in chat) can add, rename, merge and remove a
brand's products; the product table, the product pages, the generated catalog, every affected
project's product set and the agent's next turn all follow, and onboarding re-runs respect it.

**Architecture:** The `product` table stays the one product list (new `merged` status +
`merged_into`). One API service, `clue_api/product_management.py`, performs every action in one
transaction: spine write → page writes → catalog rebuild → `product_change` row → project set
updates (`project_product` versions tagged with `product_change_id`). The Brand-context routes, the
Head of ABM tool `manage_products@1` and the fleet page writer all call that service. Documents
name their products in front matter (`product_id` / `product_ids`), set through a picker.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy async + Postgres, Alembic (hand-written,
reversible), clue_toolbelt tools, fleet work queue; Next.js + TypeScript + Zod frontend
(`apps/frontend`, node:test + tsx).

**Spec:** `docs/superpowers/specs/2026-10-15-product-management-design.md`

## Global Constraints

- The product table is the only product list; files are never parsed to decide what the products
  are (spec D1).
- Editing a document's title or text never renames a product (D2).
- The agent applies a change directly when the person asks; when it only suspects, it asks first (D3).
- Existing projects follow a merge/remove automatically and get a chat notice; only in chat (D4, §13).
- A merge writes a fresh page; old pages are retired, never deleted (D5).
- Onboarding never waits for a product review (D6); only the §9 guard is added to it.
- Migrations: Alembic random-hash id, `down_revision = "284e4383227f"`, every `upgrade()` has a
  `downgrade()`; named constraints; exactly one head.
- Every new runtime setting appears in `.env.example` with its default at the moment it is added.
- No Claude/AI attribution in commits. Commit locally only; never push.
- DB tests run only on the throwaway DB `clue_nashville_locktest` with no other `.env` keys:
  `$SCRATCH/pm/ptest.sh <paths>` (sets only `CLUE_DATABASE_URL`).
- UI built from existing components only; screenshots for founder review before merge.

## Review Focus

1. Two people act on the same brand at once (rename vs merge of the same product) — one wins, the
   other gets a 409, no half-written pages or sets. Test in Task 3.
2. A merge whose survivor is a *new* name that equals an archived product's name — allowed (partial
   unique index), the archived row is untouched. Test in Task 2.
3. Undo of a merge after a project's set was changed again by hand — that project is left alone,
   others are restored. Test in Task 3.
4. A tool replay (same turn, same inputs) — returns the first change, writes nothing new. Test in
   Task 6.
5. An onboarding re-run whose lineup names a merged product by its old spelling — resolves to the
   survivor, no new row, no new page; the catalog stays one product. Test in Task 4.

---

### Task 1: Migration — product merge, change log, project provenance, lineage state

**Files:**
- Create: `alembic/versions/<hash>_product_management.py` (`alembic revision -m "product management"`)
- Test: `tests/clue_spine/test_product_management_schema.py`

**Interfaces — Produces (DB):**
- `product.status IN ('active','archived','merged')` (`product_status`); `product.merged_into text NULL`
  FK `(merged_into, workspace_id) → product(product_id, workspace_id)` (`product_merged_into_fk`);
  `CHECK ((status = 'merged') = (merged_into IS NOT NULL))` (`product_merged_into_state`);
  `CHECK (merged_into IS NULL OR merged_into <> product_id)` (`product_merged_into_not_self`).
- `product_name_per_brand` becomes `CREATE UNIQUE INDEX product_name_per_brand ON product (brand_id, name) WHERE status = 'active'`.
- `product_change` table:
  ```sql
  CREATE TABLE product_change (
    change_id uuid PRIMARY KEY,
    workspace_id text NOT NULL,
    brand_id text NOT NULL,
    kind text NOT NULL,                -- add | rename | merge | remove | restore
    product_id text NOT NULL,          -- the product the change is about (survivor for merge)
    affected_product_ids jsonb NOT NULL DEFAULT '[]'::jsonb,  -- merged / removed / restored ids
    details jsonb NOT NULL DEFAULT '{}'::jsonb,  -- names before/after, aliases_added, created_survivor
    actor_user_id text NOT NULL REFERENCES platform_user(user_id),
    actor_turn_id uuid NULL,
    undoes_change_id uuid NULL REFERENCES product_change(change_id),
    idempotency_key text NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT product_change_kind CHECK (kind IN ('add','rename','merge','remove','restore')),
    CONSTRAINT product_change_brand_fk FOREIGN KEY (brand_id, workspace_id) REFERENCES brand(brand_id, workspace_id),
    CONSTRAINT product_change_product_fk FOREIGN KEY (product_id, workspace_id) REFERENCES product(product_id, workspace_id),
    CONSTRAINT product_change_idempotency UNIQUE (workspace_id, idempotency_key)
  );
  CREATE INDEX product_change_brand_recent ON product_change (workspace_id, brand_id, created_at DESC);
  ```
  plus an append-only trigger (`execution_reject_append_only_mutation()`, the `project_product` precedent).
- `product_change_project` table (one row per project a change touched):
  ```sql
  CREATE TABLE product_change_project (
    change_id uuid NOT NULL REFERENCES product_change(change_id),
    project_id text NOT NULL,
    workspace_id text NOT NULL,
    outcome text NOT NULL,           -- updated | needs_choice | restored | left_as_is
    selection_version integer NULL,  -- the version this change wrote (updated / restored)
    previous_selection_version integer NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (change_id, project_id),
    CONSTRAINT product_change_project_outcome CHECK (outcome IN ('updated','needs_choice','restored','left_as_is')),
    CONSTRAINT product_change_project_version CHECK ((outcome IN ('updated','restored')) = (selection_version IS NOT NULL))
  );
  CREATE INDEX product_change_project_by_project ON product_change_project (workspace_id, project_id, created_at DESC);
  ```
- `product_change_notice_dismissal (change_id uuid, project_id text, user_id text, dismissed_at timestamptz DEFAULT now(), PRIMARY KEY (change_id, project_id, user_id))`, FK `(change_id, project_id) → product_change_project`.
- `project_product.product_change_id uuid NULL`; `project_product_confirmation_source` replaced by
  `CHECK (((gate_id IS NOT NULL)::int + (confirmation_turn_id IS NOT NULL)::int + (product_change_id IS NOT NULL)::int) = 1)`.
- `onboarding_product_lineage_state` widened: resolved states gain `'removed_by_person'` (product_id NOT NULL).
- `downgrade()` refuses (RAISE) while any `merged` product, `removed_by_person` lineage row or
  `product_change_id` project row exists; otherwise reverses every step.

- [ ] **Step 1: Write the failing schema test** — `tests/clue_spine/test_product_management_schema.py`,
  using `tests/clue_spine/conftest.py`'s `rollback_conn`/`run_async` and `require_spine_db`:
  ```python
  def test_merged_needs_a_target_and_the_name_is_unique_only_among_active():
      async def scenario():
          async with rollback_conn() as conn:
              ws = await create_workspace(conn, name="Acme")
              brand = await create_brand(conn, workspace_id=ws.workspace_id, name="Acme")
              a = await create_product(conn, brand_id=brand.brand_id, workspace_id=ws.workspace_id, name="A")
              b = await create_product(conn, brand_id=brand.brand_id, workspace_id=ws.workspace_id, name="B")
              with pytest.raises(IntegrityError, match="product_merged_into_state"):
                  async with conn.begin_nested():
                      await conn.execute(text("UPDATE product SET status='merged' WHERE product_id=:p"), {"p": a.product_id})
              await conn.execute(text("UPDATE product SET status='merged', merged_into=:b WHERE product_id=:a"), {"a": a.product_id, "b": b.product_id})
              # The merged row no longer holds its name: a new active "A" is allowed.
              await create_product(conn, brand_id=brand.brand_id, workspace_id=ws.workspace_id, name="A")
              with pytest.raises(IntegrityError, match="product_name_per_brand"):
                  await create_product(conn, brand_id=brand.brand_id, workspace_id=ws.workspace_id, name="B")
      run_async(scenario())

  def test_a_project_set_version_needs_exactly_one_source():
      # insert a project_product row with gate_id NULL, confirmation_turn_id NULL, product_change_id NULL
      # -> IntegrityError match "project_product_confirmation_source"; with product_change_id set -> ok
  ```
- [ ] **Step 2: Run** `$SCRATCH/pm/ptest.sh tests/clue_spine/test_product_management_schema.py -q` → FAIL
  (no `product_merged_into_state`; second create of "A" hits `product_name_per_brand`).
- [ ] **Step 3: Write the migration** with the DDL above.
- [ ] **Step 4: Run** `.venv/bin/alembic heads` (one head), the schema test (PASS), and `make db-smoke`
  equivalent on the throwaway DB: `alembic upgrade head && alembic downgrade -1 && alembic upgrade head`
  with only `CLUE_DATABASE_URL` set.
- [ ] **Step 5: Commit** `Product management: migration for merged products, change log and project provenance`.

### Task 2: Spine — rename, merge, archive, restore, resolve; set provenance

**Files:**
- Modify: `libs/clue-spine/clue_spine/spine.py` (product section ~:209-320, project set ~:560-715)
- Modify: `libs/clue-spine/clue_spine/__init__.py` (exports)
- Test: `tests/clue_spine/test_product_lifecycle.py`

**Interfaces — Produces:**
- `ProductStatus = Literal["active", "archived", "merged"]`; `Product.merged_into: str | None = None`;
  `_PRODUCT_COLUMNS` includes `merged_into`.
- `async def rename_product(conn, *, product_id: str, workspace_id: str, name: str) -> Product` —
  active only (else `ValueError("product is not active")`); the old name is appended to `aliases`;
  any alias folding to the new name is dropped. Duplicate active name → `IntegrityError` (`product_name_per_brand`).
- `async def archive_product(conn, *, product_id, workspace_id) -> Product` — active → archived.
- `async def merge_products(conn, *, product_ids: Sequence[str], into_product_id: str, workspace_id: str) -> tuple[Product, tuple[str, ...]]` —
  every id active and in the survivor's brand; survivor not in `product_ids`; merged rows →
  `status='merged', merged_into=survivor`; rows already merged INTO a merged id are re-pointed at the
  survivor (no chains); returns the refreshed survivor and the aliases actually added (names + aliases
  of the merged rows, folded-deduped against the survivor).
- `async def restore_product(conn, *, product_id, workspace_id) -> Product` — archived|merged → active,
  `merged_into` cleared.
- `async def remove_product_aliases(conn, *, product_id, workspace_id, aliases: Sequence[str]) -> Product`.
- `async def resolve_current_product(conn, product_id: str) -> Product | None` — follows `merged_into`
  (bounded to 8 hops, then `ValueError`).
- `confirm_project_product_set(..., product_change_id: UUID | None = None)` — exactly one of
  `gate_id` / `confirmation_turn_id` / `product_change_id`.
- `ProjectProductSet.product_change_id: UUID | None = None` (and the column in `_PROJECT_PRODUCT_COLUMNS`).

- [ ] **Step 1: Failing tests** in `tests/clue_spine/test_product_lifecycle.py`:
  - rename keeps the old name as alias and refuses a clash with another active product;
  - merge of A,B into C: A,B `merged`, `merged_into=C`, C's aliases gain "A","B" (+ their aliases),
    `resolve_current_product(A) == C`; a product earlier merged into A now points at C;
  - merge refuses a non-active member, a cross-brand member, and the survivor listed among members;
  - archive then restore round-trips; restore of a merged product clears `merged_into`;
  - a new survivor named like an archived product (Review Focus 2) is accepted;
  - `confirm_project_product_set` with `product_change_id` writes a version whose
    `product_change_id` reads back; two sources at once → `ValueError`.
- [ ] **Step 2: Run** `$SCRATCH/pm/ptest.sh tests/clue_spine/test_product_lifecycle.py -q` → FAIL (ImportError).
- [ ] **Step 3: Implement** the functions (SQL `UPDATE ... WHERE product_id=:id AND workspace_id=:ws`,
  `SELECT ... FOR UPDATE` on every row touched, sorted by id to avoid deadlocks).
- [ ] **Step 4: Run** the new test plus `tests/clue_spine/test_spine.py` → PASS.
- [ ] **Step 5: Commit** `Spine: rename, merge, archive and restore products; set versions from a product change`.

### Task 3: The product management service

**Files:**
- Create: `platform/api/clue_api/product_management.py`
- Test: `tests/api/test_product_management_db.py`

**Interfaces:**
- Consumes: Task 2 spine functions; `clue_api.arv2.onboarding_documents.render_markdown`,
  `KnowledgeDocument`; `clue_api.arv2.knowledge_frontmatter.parse_front_matter`;
  `clue_storage.{artifact_key, content_address, record_artifact, read_verified_artifact}`;
  `clue_api.arv2.onboarding_lineage.normalize_identity` (slug comparisons only);
  `clue_api.arv2.onboarding_driver.slugify` (the same slug onboarding uses).
- Produces:
  ```python
  ProductAction = Literal["add", "rename", "merge", "remove"]

  @dataclass(frozen=True)
  class ProductActor:
      user_id: str
      turn_id: UUID | None = None

  class ProductChangeRefused(ValueError):
      code: str   # product_not_found | product_not_active | product_name_taken | merge_invalid |
                  # change_not_undoable | change_conflict | name_invalid

  @dataclass(frozen=True)
  class ProjectSetOutcome:
      project_id: str
      outcome: Literal["updated", "needs_choice", "restored", "left_as_is"]
      selection_version: int | None

  @dataclass(frozen=True)
  class ProductChangeResult:
      change_id: UUID
      kind: str
      product: Product                 # the product the change is about
      page_document_id: UUID | None    # the page written or opened
      page_pending: bool               # True → caller enqueues the page writer AFTER commit
      catalog_document_id: UUID
      projects: tuple[ProjectSetOutcome, ...]
      replayed: bool = False

  async def add_product(conn, storage, *, workspace_id, brand_id, actor, name, description=None,
                        page_markdown=None, idempotency_key=None) -> ProductChangeResult
  async def rename_product_action(conn, storage, *, workspace_id, brand_id, actor, product_id, name,
                                  idempotency_key=None) -> ProductChangeResult
  async def merge_products_action(conn, storage, *, workspace_id, brand_id, actor, product_ids,
                                  into_product_id=None, new_name=None, page_markdown=None,
                                  idempotency_key=None) -> ProductChangeResult
  async def remove_product_action(conn, storage, *, workspace_id, brand_id, actor, product_id,
                                  idempotency_key=None) -> ProductChangeResult
  async def undo_product_change(conn, storage, *, workspace_id, brand_id, actor, change_id) -> ProductChangeResult
  async def list_brand_products(conn, storage, *, workspace_id, brand_id) -> list[BrandProduct]
  async def recent_product_changes(conn, *, workspace_id, brand_id, since: datetime) -> list[ProductChangeLine]
  async def publish_product_page(conn, storage, *, workspace_id, brand_id, document_id: UUID,
                                 markdown: str) -> None   # fills a pending page (Task 7)
  def describe_change(kind, details) -> str  # "9 products merged into Proxon" etc.
  ```
  `BrandProduct(product_id, name, aliases, status, page_document_id, page_path, page_pending)`;
  `ProductChangeLine(change_id, kind, text, created_at)`.

Behaviour (each action, one transaction, brand row locked `FOR UPDATE` first — the
`save_knowledge_document` lock — so concurrent actions serialize):
- **Idempotency:** with `idempotency_key`, an existing `product_change` row for
  `(workspace_id, key)` returns its result with `replayed=True` and writes nothing.
- **Pages:** the main page of a product = the current servable brand-level `product-research`
  document whose front matter `product_id` equals it (latest version per path). Writes:
  - *write page* → next version at `product/<slugify(name)>.md`, status `ready`, front matter
    `{kind: product-research, as_of, product_id, product_name, status: ready, written_by:
    {user_id, turn_id, change_id}}`, body = given markdown (a leading `# <name>` heading is added if
    the body has none); earlier servable non-confirmed version of that path → `superseded`.
  - *pending page* (no markdown given for add/merge) → next version at that path, status `running`,
    no artifact; `page_pending=True`.
  - *retire path* → every servable non-confirmed brand-level version of the path → `superseded`.
  - *republish* (undo) → copy the retired document's bytes as the next version, status `ready`.
  - rename → write the current main page's body + updated front matter at the new slug path, retire
    the old path (if the slug changed); otherwise just a new version with the new `product_name`.
- **Catalog:** after every action, `product/catalog.md` gets a new `ready` version generated from the
  active products: front matter `{kind: product-catalog, generated: true, change_id, as_of,
  products: [{product_id, name, aliases, short_description, offering_kind, family, lifecycle,
  official_url, sources}]}` — descriptive fields carried from the previous catalog entry for that
  product (match by the entry's own `product_id`, else by `onboarding_product_lineage` for that
  catalog document + ordinal, else by `normalize_identity(name)`); body = `# Product catalog`, the
  line "_Generated from your products. To change this list, rename, merge or remove a product._",
  then a table Name | Also called | Kind | Description.
- **Projects:** mapping `{old_id: new_id | None}` (merge: member → survivor; remove: id → None).
  For every project of the brand whose *current* set contains a key: new set = mapped, deduped,
  order kept; empty → `product_change_project(outcome='needs_choice')`, no version; else
  `confirm_project_product_set(..., product_change_id=change_id, confirmed_by_user_id=actor.user_id)`
  and `outcome='updated'` with `previous_selection_version`.
- **Undo** (merge and remove only; else `change_not_undoable`): restore each affected product
  (`restore_product`); for a merge remove `details.aliases_added` from the survivor and, when
  `details.created_survivor`, archive the survivor and retire its page; republish each affected
  product's retired main page (`details.retired_pages`: `{product_id: document_id}`); for each
  `updated` project of the original change: if its current version is still the one the change
  wrote → new version = the set of `previous_selection_version` (`outcome='restored'`), else
  `left_as_is` (Review Focus 3). The undo is itself a `restore` change with `undoes_change_id`; a
  change already undone → `change_not_undoable`.

- [ ] **Step 1: Failing scenario tests** (`tests/api/test_product_management_db.py`, the
  `test_frontend_write_brand_knowledge.py` fixtures: `_MemoryStorage`, `_document`, `seed_project`,
  `seed_principal`, `rollback_conn`):
  1. *Proxon replay*: 9 products with pages + a catalog + 2 projects (one holding all 9, one holding
     2) → merge 8 into the 9th with `page_markdown` → catalog lists 1 product whose "Also called"
     has the 8 names; 8 pages `superseded`; the survivor's page is the new markdown; both projects
     hold `[survivor]` at a new version with `product_change_id`; `product_change_project` rows say
     `updated`.
  2. *Rename*: page moves to the new slug path; old path not servable; `product.name` new; old name
     in aliases; catalog row renamed.
  3. *Remove* of the only product a project holds → `needs_choice`, set unchanged.
  4. *Undo merge* with one project changed by hand afterwards → products active, pages back,
     survivor aliases trimmed, the untouched project `restored`, the changed one `left_as_is`.
  5. *Add without markdown* → pending `running` page, `page_pending=True`; `publish_product_page`
     then makes it `ready`.
  6. *Idempotent replay*: same `idempotency_key` twice → one `product_change` row, `replayed=True`.
  7. *Concurrent actions* (Review Focus 1): two connections, rename and merge of the same product —
     the second blocks on the brand lock and then refuses `product_not_active` (409 at the route);
     no partial rows (use two real connections from the pool, each in its own transaction).
- [ ] **Step 2: Run** `$SCRATCH/pm/ptest.sh tests/api/test_product_management_db.py -q` → FAIL (ImportError).
- [ ] **Step 3: Implement** `product_management.py`.
- [ ] **Step 4: Run** → PASS.
- [ ] **Step 5: Commit** `Product management service: add, rename, merge, remove and undo in one transaction`.

### Task 4: Onboarding guard

**Files:**
- Modify: `platform/api/clue_api/arv2/onboarding_lineage.py` (`synchronize_catalog`, `_record`,
  the replay branch, `_model_stage` input)
- Modify: `platform/api/clue_api/arv2/onboarding_driver.py` (`_catalog_sync`: regenerate the catalog
  through `product_management.regenerate_catalog` when any link was redirected or removed)
- Test: `tests/arv2/test_onboarding_lineage_db.py` (new tests)

**Interfaces:**
- Consumes: `resolve_current_product` (Task 2); `regenerate_catalog(conn, storage, *, workspace_id,
  brand_id, change_id: UUID | None) -> UUID` (Task 3, public).
- Produces: `ProductLink.redirected: bool = False` (resolved through a merge or a removal);
  lineage state `removed_by_person`; a `removed_by_person` link has `product_id=None` (the lineage
  row keeps the archived id), so `_one_link_per_product` skips it.

Rules: rung 2 and rung 3 map every hit through `resolve_current_product`; hits that land on the same
current product count once; a current product that is `archived` → `removed_by_person`; the model
stage is shown active products only. The replay branch maps `removed_by_person` rows to
`product_id=None`.

- [ ] **Step 1: Failing tests:** (a) entry spelled like a merged product → `alias_reused` to the
  survivor, no new product; (b) entry spelled like an archived product → `removed_by_person`, link
  `product_id is None`, lineage row holds the archived id, no new product; (c) two entries hitting a
  merged product and its survivor → both reuse the survivor (not `unresolved_ambiguous`); (d) replay
  of (b) mirrors `removed_by_person` with `product_id None`.
- [ ] **Step 2: Run** `$SCRATCH/pm/ptest.sh tests/arv2/test_onboarding_lineage_db.py -q` → new tests FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** the lineage, driver and driver-db tests → PASS.
- [ ] **Step 5: Commit** `Onboarding: follow merges and skip removed products when a lineup is re-run`.

### Task 5: Brand-context product routes and the document product link

**Files:**
- Create: `platform/api/clue_api/frontend_read/brand_products.py` (routes + wire models)
- Modify: `platform/api/clue_api/frontend_read/brand_knowledge.py` — `KnowledgeDocumentUpdate.product_ids:
  list[str] | None = None` (alias `productIds`); `save_knowledge_document` writes it into the new
  version's front matter (`product_id` for a `product-research` page — exactly one id; `product_ids`
  otherwise) after checking every id is an active product of the brand (422 `PRODUCT_LINK_INVALID`);
  a save of the generated catalog (`front.generated is True`) → 409 `CATALOG_IS_GENERATED`;
  wire `KnowledgeDocumentWire` gains `product_ids: list[str]` and `generated: bool`.
- Modify: `platform/api/clue_api/frontend_read/app.py` — register the product routes beside
  `register_brand_knowledge_routes` (same `conn_factory`, `storage`, `allow_local_mutations`, plus
  the fleet `work_queue` for the page writer, Task 7).
- Test: `tests/api/test_frontend_brand_products.py`

**Routes** (prefix `/frontend/v1/brand-context`; writes need `project.write`, the PUT route's
principal/local rule; brand from `resolve_knowledge_brand`):
| Method | Path | Body | Result |
|---|---|---|---|
| GET | `/products` | — | `{brandId, products: [BrandProductWire], recentChanges: [ProductChangeWire]}` |
| POST | `/products` | `{name, description?}` | `ProductChangeWire` |
| POST | `/products/{productId}/rename` | `{name}` | `ProductChangeWire` |
| POST | `/products/merge` | `{productIds, intoProductId?, newName?}` | `ProductChangeWire` |
| POST | `/products/{productId}/remove` | — | `ProductChangeWire` |
| POST | `/product-changes/{changeId}/undo` | — | `ProductChangeWire` |

`BrandProductWire {productId, name, aliases, pageDocumentId, pagePath, pagePending}`;
`ProductChangeWire {changeId, kind, text, createdAt, productId, pagePending, projectsUpdated,
projectsNeedingChoice, undoable}`. Refusals map `ProductChangeRefused.code` → HTTP: `product_not_found`
404; `product_name_taken`, `product_not_active`, `change_conflict`, `change_not_undoable` 409;
`merge_invalid`, `name_invalid` 422. App-path add/merge never pass markdown → the route enqueues
the page writer after commit when `page_pending`.

- [ ] Step 1: failing route tests (local-header app as in `test_frontend_write_brand_knowledge.py`):
  list → add → rename → merge → remove → undo, status codes and wire shapes; product link save
  writes front matter and refuses a foreign/archived id; catalog save refused; enqueue called once
  for a pending page (stub queue records calls).
- [ ] Step 2: run → FAIL. Step 3: implement. Step 4: run with the brand-knowledge suites → PASS.
- [ ] Step 5: commit `Brand context: product routes and the document product link`.

### Task 6: Head of ABM tool `manage_products@1` (profile v71, recipe v34, manual v17)

**Files:**
- Create: `platform/api/clue_api/product_management_tools.py`
- Modify: `platform/api/clue_api/toolbelt_wiring.py` (register beside `ConfigureProjectTargetingTool`)
- Modify: `platform/api/clue_api/agent_registry_wiring.py` (`C6_AGENT_TOOL_AUTHORITY["manage_products"]
  = (AgentRole.HEAD_OF_ABM,)`; withheld on `STAGE0_CONVERSATION_TRIAL_SURFACE`; HEAD_OF_ABM active `v71`)
- Create: `platform/agents/catalog/profiles/head-of-abm/v71/profile.yaml` (v70 + the tool entry with
  its schema digests; manual skills re-pinned at v17)
- Create: `platform/execution/recipes/recipe0-stage0-v34.json` (v33 + `manage_products@1` in the four
  lists); `recipe_wiring.SYSTEM_RECIPE_FILENAMES`; `recipe_contracts.RECIPE_0_TOOL_ADDRESSES`;
  `conversation_turns.CONVERSATION_RECIPE_VERSION = 34`; `chat/composer_context.py` pin `head-of-abm@v71`
- Modify: `platform/agents/catalog/manual/tool_notes.yaml` (entry + refusals); `platform/agents/clue_agents/manual/build.py`
  (`MANUAL_VERSION="v17"`, `PROFILE_VERSION="v71"`); `make manual` writes the v17 chapters
- Modify: `apps/frontend/src/features/projects/model/chat-tool-presentation.ts` `TOOL_LABELS` ("Updated products")
- Tests: `tests/api/test_product_management_tools.py`; update `test_agent_registry_wiring.py`,
  `test_toolbelt_wiring.py` (`_MATRIX` row, counts 145/169), `test_recipe_contracts.py` (v34 test),
  `tests/agents/test_catalog.py` as the v70 commit did.

**Tool contract:**
```python
class ManageProductsInput(ToolInput):
    action: Literal["add", "rename", "merge", "remove"]
    product_id: str | None = None          # rename / remove
    product_ids: tuple[str, ...] | None = None  # merge: the products folded in
    into_product_id: str | None = None     # merge into an existing product
    name: str | None = None                # add / rename / merge into a new product
    page_markdown: str | None = Field(default=None, max_length=200_000)  # add / merge: the page
    source_turn_ref: str  # TRUSTED_TURN_FIELD
class ManageProductsOutput(ToolOutput):
    change_id: str; action: str; product_id: str; product_name: str; aliases: tuple[str, ...]
    page_document_id: str | None; catalog_document_id: str
    projects_updated: int; projects_needing_choice: int
```
`model_description`: "Change this brand's product list when the person asks you to: add a product,
rename one, merge several into one (for example features that onboarding listed as separate
products), or remove one. The change applies at once to the product list, the product pages, the
catalog and every project using those products. For add and merge, write page_markdown: the
product's page, from what you know and the pages being merged. If you only suspect the list is
wrong, ask the person first instead of calling this. " + `tool_manual_link("manage_products")`.
Effect WRITE; replay DOMAIN_IDEMPOTENT with `idempotency_key = f"turn:{turn_id}:{sha256(inputs without source_turn_ref)}"`;
`pin_requirements=("project",)`; preconditions validate the action's required fields and the turn
(refusal codes: `products_turn_unavailable`, `products_input_invalid`, plus the service codes).
Add/merge without `page_markdown` → `products_page_required`.

- [ ] Step 1: failing tool tests (preconditions per action; invoke merge writes change + page; replay
  returns the same change id; trial surface withholds it).
- [ ] Step 2: run → FAIL. Step 3: implement tool + grants + profile/recipe/manual bumps; compute the
  schema digests with `build_toolbelt(...).descriptor("manage_products")`.
- [ ] Step 4: run `tests/api/test_product_management_tools.py tests/api/test_agent_registry_wiring.py
  tests/api/test_toolbelt_wiring.py tests/api/test_recipe_contracts.py tests/agents -q` and `make manual-check` → PASS.
- [ ] Step 5: commit `Head of ABM v71: manage_products@1 (recipe 34, manual v17)`.

### Task 7: Background page writer (app path)

**Files:**
- Modify: `platform/fleet/clue_fleet/enums.py` — append `PRODUCT_PAGE_WRITE = "product_page_write"`.
- Create: `alembic/versions/<hash>_product_page_write_fleet_kind.py` (template `fd8795c4fd5a`).
- Create: `platform/api/clue_api/product_page_writer.py` — payload builder, deterministic
  `product_page_work_id(document_id)`, the one-call writer (the `conversation_naming` shape:
  OpenRouter through `ProviderCaller`, spend drained with `LedgerStamp(workspace_id=...)`), and
  `ProductPageWorkHandler` (never raises; `completed` / `failed`); prompt text in the module.
- Modify: `libs/clue-config/clue_config/settings.py` — `product_page_writer_model: str` (default =
  the conversation naming model's default) and `product_page_writer_timeout_s: float = 120.0`;
  `.env.example` lines `CLUE_PRODUCT_PAGE_WRITER_MODEL=` / `CLUE_PRODUCT_PAGE_WRITER_TIMEOUT_S=120`.
- Modify: `platform/api/clue_api/fleet_wiring.py` (kwarg + guard + append), `fleet_main.py` (build).
- Tests: `tests/api/test_product_page_writer.py` (stub caller: pending page → ready with the model's
  markdown; model failure → page `failed`, task `failed`, never raises); `tests/db/test_product_page_write_kind_migration.py`
  (enum parity); `tests/api/test_fleet_wiring.py` row.

Input to the model: product name, aliases, and the bodies of the pages being merged (or, for an
add, the description the person typed). Instruction: write the product's page in the sections the
onboarding pages use (Overview, Capabilities, Use cases, Who it is for, Integrations, Pricing,
Differentiators, Competitors, Customer evidence, Not established), using only facts in the given
pages, keeping their source links, writing "_Not established._" where nothing is known.

- [ ] Steps: failing tests → run → implement → run → commit `Product pages: background writer for app-made merges and adds`.

### Task 8: The agent hears about product changes

**Files:**
- Modify: `platform/api/clue_api/brand_knowledge_context.py` — `BrandKnowledgeIndexCard.recent_product_changes:
  list[str] | None = None`, omitted from every dump when `None` (the `library_sha256` precedent);
  `compile_brand_knowledge_index_card(..., recent_product_changes: Sequence[str] | None = None)`;
  never dropped for budget.
- Modify: `platform/api/clue_api/agent_turn_fleet_wiring.py` (~:632) — read
  `recent_product_changes(conn, workspace_id, brand_id, since=now-30d)` beside `current_project_product_set`
  and pass the lines (`"15 Oct 2026: 9 products merged into Proxon"`) to `_compose_project_context`.
- Test: `tests/api/test_brand_knowledge_context.py` (card with/without changes; bytes unchanged when none).
- [ ] Steps: failing test → run → implement → run → commit `Brand index card: recent product changes`.

### Task 9: Project product notices (API)

**Files:**
- Create: `platform/api/clue_api/frontend_read/product_notices.py` —
  `GET /frontend/v1/projects/{projectId}/product-notices` → `{notices: [{changeId, text, createdAt,
  outcome}]}` (the project's `product_change_project` rows from the last 30 days not dismissed by
  this user; `needs_choice` text adds "Choose this project's products in chat."), and
  `POST /frontend/v1/projects/{projectId}/product-notices/{changeId}/dismiss` (204).
- Modify: `frontend_read/app.py` registration.
- Test: `tests/api/test_frontend_product_notices.py`.
- [ ] Steps: failing test → run → implement → run → commit `Project chat: product change notices`.

### Task 10: Frontend — Brand context products

**Files:**
- Modify: `apps/frontend/src/features/brand-context/model/brand-knowledge.ts` (Zod: `BrandProductSchema`,
  `ProductChangeSchema`, `BrandProductsSchema`; `KnowledgeDocumentSchema` gains `productIds`, `generated`)
- Create: `apps/frontend/src/features/brand-context/data/brand-products.ts` (+ `.test.ts`): `readBrandProducts`,
  `addProduct`, `renameProduct`, `mergeProducts`, `removeProduct`, `undoProductChange` (raw `fetch` to
  `/api/clue/frontend/v1/brand-context/...`, the `brand-knowledge-actions.ts` error mapping)
- Modify: `data/brand-knowledge-actions.ts` (`saveKnowledgeDocument` sends `productIds` when given)
- Create: `components/product-actions.tsx` — per-product `Menu` (Rename…, Merge into…, Remove…) and
  the dialogs (`Dialog` + `<form>`, the `project-directory-dialog.tsx` pattern): rename (input),
  merge (checkbox list of the other products + "into" select or new name), remove (confirm text
  "This removes the product X from the list and from every project that uses it."), add product
  (name + description), and a "Recent changes" list with Undo for merge/remove.
- Create: `components/document-products-field.tsx` — the Products picker in the editor header
  (checkbox list in a `Menu`; one choice for a product page).
- Modify: `brand-context-sidebar.tsx` (Product folder: "Add product" button + product menus on
  product pages; catalog row marked "Generated"), `brand-context-header.tsx` (picker; Edit hidden
  for the generated catalog), `use-brand-context-controller.ts` (products state + refresh),
  `page.tsx` (server read of products).
- Tests: model/data tests under node:test.
- [ ] Steps: failing data/model tests → `npm test` FAIL → implement → `npm test`, `npm run lint` PASS →
  commit `Brand context: product actions and the document products picker`.

### Task 11: Frontend — project chat notice

**Files:**
- Create: `apps/frontend/src/features/projects/data/product-notices.ts` (+ test) and
  `components/product-notices.tsx` (one `role="status"` line per notice with "Review in Brand context"
  link and Dismiss, `project-document-surface.module.css` notice styles)
- Modify: `components/conversation-content.tsx` (render above the transcript, before the transcript scroll)
- [ ] Steps: failing test → implement → `npm test`, `npm run lint` → commit `Project chat: show product change notices`.

### Task 12: Verification, docs, memory

- [ ] Backend: run every test file touched above plus `tests/clue_spine tests/arv2/test_onboarding_lineage_db.py
  tests/api/test_frontend_write_brand_knowledge.py tests/api/test_frontend_read_brand_knowledge.py`
  on the throwaway DB; `make lint` and `make typecheck` (no live keys).
- [ ] Frontend: `npm run design-system:build && npm run lint && npm run build` (lane stack down).
- [ ] Screenshots of Brand context (product menu, merge dialog, picker, generated catalog) and the
  chat notice, from the local stack, for founder review.
- [ ] Docs: `apps/frontend/docs/api-contracts/brand-context.md` (products routes, product link,
  generated catalog), `projects.md` (notices); spec status → implemented.
- [ ] `_memory/2026-10-15-product-management.md`: what shipped, rulings, owed live proof (the
  Proxon brand in production), and the prompt text of the page writer + tool description for
  founder review.
