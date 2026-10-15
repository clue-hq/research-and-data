# Product management in Brand context — design

Date: 2026-10-15. Status: **implemented** on `feat/brand-context-product-management` (plan `docs/superpowers/plans/2026-10-15-product-management.md`); live proof owed.

## 1. The problem

During Proxon's onboarding, the product lineup research turned one platform into nine "products"
(they were features). Fixing that by hand showed that a brand's product list lives in three places
that nothing keeps in step:

1. **The `product` table** — names and ids. Onboarding inserts rows and adds aliases; nothing ever
   renames, merges or removes a row (`arv2/onboarding_lineage.py:17-18`). The picker, the research
   quality context and chat naming read names from here.
2. **`product/catalog.md`** — a second copy of the list as text. Editing it changes nothing in the
   table.
3. **One page per product** (`product/<slug>.md`, kind `product-research`), linked to its row by
   `product_id` in its front matter. The app cannot delete a page, so old pages stay servable and
   the Head of ABM keeps reading them.

And every project keeps its own product set (`project_product`, append-only by selection version),
so existing projects kept the nine products after the brand was fixed.

So an edit to a file changed one copy while the agent read the other two. The fix on 2026-10-14
was an operator write in production (archive 8 rows, supersede their pages, rewrite the catalog)
plus PR #118 (the picker skips archived products). This design makes that a normal action a person
or the agent can take.

## 2. Founder decisions (2026-10-15)

- **D1. The table is the one product list.** About twenty tables reference `product.product_id`
  (projects, claims, research directives, memory, ingestion, turn pins…), so a product's id must
  survive every edit. Files are never parsed to decide what the products are.
- **D2. A document says which product it is about in its front matter.** Editing a page's title or
  text never renames a product — a marketer could do that by accident. Renaming is its own action.
- **D3. The agent applies product changes directly** when the person asks for them in chat. When it
  only *notices* something (for example several products that look like features of one), it asks
  in chat first and does not act.
- **D4. Existing projects follow a merge or removal automatically**, and the project shows a notice
  saying what changed.
- **D5. A merge writes a fresh product page** for the merged product. The old pages are retired
  (hidden, history kept).
- **D6. Onboarding does not wait for a product review.** The onboarding flow itself is not changed
  here (it will be redesigned separately); only the guard in §9 is added.

## 3. The product list (table)

Migration (hand-written, reversible, hash id):

- `product.status` gains `merged`: `CHECK (status IN ('active','archived','merged'))`.
- New `product.merged_into text NULL`, FK to `product (product_id, workspace_id)`, with
  `CHECK ((status = 'merged') = (merged_into IS NOT NULL))` — the same pattern as
  `account_entity.merged_into`. A merge never points at a merged product (chains are collapsed
  when written).
- `product_name_per_brand UNIQUE (brand_id, name)` becomes a **partial** unique index
  `WHERE status = 'active'`, so a new or renamed product can reuse a name that only an archived or
  merged product holds.
- New table `product_change` — one row per action, append-only:
  `change_id, workspace_id, brand_id, kind (add|rename|merge|remove|restore), product_ids_before
  jsonb, product_id_after, names jsonb (before/after), actor_user_id NULL, actor_turn_id NULL,
  undoes_change_id NULL, created_at`. Exactly one actor is set. This is the audit, the source of
  the project notices (§7) and of the agent's "recent changes" (§8).

New `clue_spine` functions beside `create_product` / `add_product_aliases`
(`libs/clue-spine/clue_spine/spine.py`): `rename_product`, `merge_products`, `archive_product`,
`restore_product`, and `resolve_current_product(product_id)` (follows `merged_into`).

Old names are never lost: a rename adds the old name to `aliases`; a merge adds every merged
product's name and aliases to the surviving product's `aliases`.

## 4. Documents and products

### 4.1 The link lives in front matter

- A product page carries `product_id` (as today). Any other Brand-context document — proof,
  audience, a file a person wrote — may carry `product_ids: [...]`.
- The editor shows this as a **Products** field with a picker of the brand's active products. The
  person never edits YAML. The save route (`PUT` in `frontend_read/brand_knowledge.py`) takes an
  optional `product_ids` and writes it into the new version's front matter; ids must be active
  products of the brand.
- Each active product has exactly **one main page**: the servable `product-research` document whose
  front matter names it. Other documents linked to a product are extra material, not its page.

### 4.2 The catalog is generated

`product/catalog.md` is rebuilt from the table after every product action (a new version of the
same path, `produced_by` the change). It lists each active product with its name, "also called"
(aliases, including merged-from names), and the descriptive fields the previous catalog entry had
for that product (matched by `product_id` through `onboarding_product_lineage`). Each entry now
carries its `product_id`. In the app the catalog is **read-only** and labelled as generated.

## 5. The actions

Every action runs in one transaction: table change → page changes → catalog rebuild →
`product_change` row → project set updates (§7). Each is the same service whether a person or the
agent calls it.

| Action | Table | Pages |
|---|---|---|
| **Add** (name, optional description) | insert `active` row | write a main page (see §6) |
| **Rename** (product, new name) | set `name`, old name → `aliases` | main page moves to the new slug path: a new version at `product/<new-slug>.md` that supersedes the old document; the old path is retired. Front matter `product_name` updated. |
| **Merge** (products, into an existing product *or* a new name) | merged rows → `status merged`, `merged_into` = survivor; names/aliases → survivor's aliases; a new name creates the survivor row | the merged products' pages are retired; a **fresh main page** is written for the survivor (§6) |
| **Remove** (product) | `status archived` | its main page is retired; other documents keep their front matter but the picker no longer offers it |
| **Restore** (undo of a remove or merge) | back to `active`, `merged_into` cleared | the retired pages are re-published as new versions (same bytes) |

"Retired" means a new `superseded` row, never a delete — the soft-delete rule from the
Brand-context work (items 2–3). Deleting a product's main page from the knowledge tree **is** the
Remove action and says so in its confirmation ("This removes the product X").

## 6. Writing a product page

- **In chat** (the agent merged or added a product), the Head of ABM writes the page in the same
  turn, from the retired pages and its own knowledge, through the action's `page_markdown` input.
- **In the app**, the action queues a background task (fleet, one model call) that writes the page
  from the retired pages. Until it lands, the product shows in the catalog and its page reads
  "being written" (`running`, not servable).

## 7. Existing projects

- After a merge or remove, every project whose **current** product set contains an affected
  product gets a new selection version: merged ids replaced by the survivor, removed ids dropped,
  duplicates collapsed. `project_product` stays append-only; its provenance CHECK (exactly one of
  `gate_id` / `confirmation_turn_id`) gains a third option, `product_change_id`.
- A project whose set would become **empty** keeps its set and gets a notice asking the person to
  choose products.
- Research already running keeps the set it pinned (unchanged behaviour). A project's pinned ICP
  version is never moved (ruling 2026-09-10); its front-matter `product_ids` are read through
  `resolve_current_product`. The ICP pin's own `product_selection_version` is left as it was: the
  research launch takes the selection version as an input and only checks that the project has
  it, and the turn's index card names the project's **current** set, so the next launch uses the
  new version without re-pinning the ICP.
- **Notice:** the project's chat shell shows a dismissible line above the transcript, for example
  "Products changed on 15 Oct: 9 products merged into Proxon." with **Review in Brand context**
  and **Dismiss**. (Undo is offered in Brand context, not here, because it changes the whole brand,
  not one project.) Dismissal is stored per project and person. There is no existing banner
  component; it is built from the existing `role="status"` notice styles.

## 8. How the Head of ABM learns about changes

- New turns already re-read the brand's current files, so the catalog and pages are current on the
  next turn.
- The generated catalog's "also called" lines let the agent match an old name in the chat history
  to today's product.
- The brand index card gains `recent_product_changes`: the last 30 days of `product_change` rows as
  one line each ("15 Oct: merged A, B, C into Proxon"), bounded.
- **Tool `manage_products@1`** (Head of ABM profile **v71**): `action` add | rename | merge |
  remove | restore, with the matching inputs and an optional `page_markdown`. It applies
  immediately (D3). Prompt guidance: use it when the person asks for a product change; when you
  only suspect one, ask in chat first; after a merge or add, write the page.

## 9. Onboarding guard

In `arv2/onboarding_lineage.py`, rungs 2 (`_prior_product_id`) and 3 (`_candidates`) read every
product including archived ones. Changes:

- A match to a **merged** product resolves to its survivor (`resolve_current_product`).
- A match to an **archived** product is **dropped** from the lineup with a new lineage state
  `removed_by_person` (lineage-state enum, migration) — no row, no page. A person removed it, so a
  re-run does not bring it back.

## 10. Surfaces

API (`/frontend/v1`, workspace-scoped, owner/admin/member as for the existing save route):

- `GET /brand-context/products` — active products with aliases and main-page id; plus recent
  changes.
- `POST /brand-context/products` (add), `POST .../{id}/rename`, `POST .../merge`,
  `POST .../{id}/remove`, `POST /brand-context/product-changes/{change_id}/undo`.
- `PUT` document save: optional `product_ids`.
- Project read: `product_notices[]` (undismissed changes affecting it) and a dismiss route.

Frontend (existing components only; screenshots for review before merge):

- Brand context → Product folder: per-product menu (Rename, Merge into…, Remove), an Add product
  button, and the catalog marked "Generated".
- Editor: the **Products** picker in the document header.
- Project chat shell: the notice line (§7).

## 11. Out of scope

- The onboarding redesign (D6).
- Moving product-scoped **memory** or research directives from merged products to the survivor.
  They keep their ids; new work uses the survivor. Follow-up if it matters in practice.
- Changing the product-set rule for projects beyond §7.

## 12. Tests (business-logic scenarios on a throwaway DB)

1. Proxon replay: nine products → merge eight into the ninth → catalog lists one product with
   eight "also called" names; eight pages retired; a project holding all nine now holds one, and
   shows the notice; the next turn's index card lists only Proxon's page and the change line.
2. Rename → the picker, research quality context and chat naming show the new name; the page sits
   at the new path; the old name is an alias.
3. Remove → onboarding re-run with the same lineup does not recreate the product.
4. Undo a merge → products active again, pages re-published, project sets get a new version.
5. Editing a page title or text leaves `product.name` unchanged.
6. A project whose set would be emptied keeps its set and gets the "choose products" notice.
7. Two people acting on the same brand at once: one wins, the other gets a conflict, no partial
   writes.

## 13. Founder answers (2026-10-15)

- §6: confirmed — the agent writes the page when the change happens in chat; a background task
  writes it when the change happens in the app.
- §7: the notice shows **only in the project's chat** for now.
