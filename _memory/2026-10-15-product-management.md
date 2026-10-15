# 2026-10-15 — Product management in Brand context (branch feat/brand-context-product-management)

Why: Proxon's onboarding split one platform into 9 "products"; editing the files changed one copy
of the product list while the Head of ABM read the table (names), stale pages, and projects' frozen
sets. Spec `docs/superpowers/specs/2026-10-15-product-management-design.md` (founder rulings D1–D6
+ §13 answers), plan `docs/superpowers/plans/2026-10-15-product-management.md`.

## What shipped (local commits only, branch from origin/main b13fe5914, NOT pushed)
- Migrations `08cc763512fe` (product `merged` + `merged_into`; name unique among ACTIVE only;
  `product_change` append-only log; `product_change_project` + per-person dismissals;
  `project_product.product_change_id` third provenance; lineage state `removed_by_person`) and
  `1ecc7437e5bc` (fleet kind `product_page_write`).
- Spine: rename/merge/archive/restore/remove_aliases/resolve_current_product.
- `clue_api/product_management.py`: one transaction per action — spine → pages (retire = superseded,
  undo republishes bytes) → catalog regenerated (`generated: true`, keeps research fields per
  product) → change row → project sets moved (`needs_choice` when nothing would be left).
- Onboarding guard: ladder follows merges (link `redirected`, no re-research), archived →
  `removed_by_person`; model stage sees active products only; re-run regenerates the catalog.
- Background page writer (`product_page_writer.py`, `CLUE_PRODUCT_PAGE_WRITER_{ENABLED,MODEL,TIMEOUT_S}`,
  default model x-ai/grok-4.6) for app-made add/merge.
- Routes `/frontend/v1/brand-context/products*`, `/product-changes/{id}/undo`, document PUT
  `productIds` + generated-catalog refusal; `/frontend/v1/projects/{id}/product-notices` (+dismiss).
- Index card `recent_product_changes` (omitted when none → old cards byte-identical).
- Head of ABM v71: `manage_products@1` (applies directly; asks first when only suspecting —
  description text), recipe0-stage0@34, manual v17, stage0-interview v44 (paths only); trial
  surface withholds it.
- Frontend: Product folder menus/dialogs/Add product/pending pages/Generated badge, catalog notes
  with Undo, editor "Products:" picker, chat notice line above the transcript.

## Verification
- 409 DB tests (every touched file + neighbours) on throwaway `clue_nashville_locktest`, 0 failed;
  ruff/format/mypy clean on the branch's 50 Python files; import contracts 29 kept.
- Frontend: npm test 3301 pass / 0 fail; design-system:build + lint + build green.
- Pre-existing reds, not caused here: tests/stage0/test_phase_c5_recipe0.py (5),
  tests/api/test_lane_d4_model_planned_kickoff_db.py (3) — last touched at v44.

## Owed
- Screenshots for founder review: the lane stack DB `clue_nashville` sits at revision
  `9429b503cc9d` (another branch), so it could not be migrated; needs a DB at this branch's head
  with a brand, products and pages, an API on it and the frontend pointed at it. Lane stack was
  stopped (`./scripts/dev_stack_nashville.sh up` restarts it on the old DB).
- Founder review of agent-facing prose: the tool description, tool_notes entry, and the page
  writer's system prompt (`PRODUCT_PAGE_SYSTEM_PROMPT`). No skill/prompt chapter teaches products.
- Live proof on Proxon production after deploy: the brand's 8 archived rows predate `merged`, so
  they stay archived (not merged); a person can undo nothing there — re-merge is not needed.
- Item 3 (delete a page from the tree) is not built; when it is, deleting a product's main page
  must call the Remove action.

## Follow-up the same day (founder: items 1, 2, 4, 5)
- Brand context opens on Knowledge at `company/overview.md` when the link names no section.
- The page awaits only the documents; the brand kit is read separately (`getKitView`) and streamed
  to the client as a promise ("Loading the brand kit…" in its sections; text styles seed once).
- Catalog descriptions come from the first prose paragraph of each product's page; saving a
  product page regenerates the catalog. Every change returns `pagePath`.
- A missing document path falls back to the catalog; a rename opens the page at its new path.
- Not done (founder declined for now): a product list with menus at the top of the catalog view,
  so a product with no page still has no menu in the app (the Head of ABM can still change it).
- Verified: product DB suites green; frontend npm test 3304/0; design-system:build + lint + build.

## Load-speed work the same day (founder-approved, same branch)
- Root cause everywhere: stored files read from R2 one after another. `clue_api/knowledge_bytes.py`
  fetches concurrently (16) and caches by (workspace, storage key, digest); the DB liveness/digest
  check still runs on every read. Used by the Brand-context tree/product list/documents, project
  documents, chat message bodies and tagged-document labels.
- Brand context: `GET /brand-context/knowledge/full` (tree + every body, one read); section and
  document switches use `window.history.replaceState` (no server re-render). Stripe warm load:
  first byte 9.6–13 s -> 0.88 s.
- Chat: the conversation's messages/turns/gates start alongside the chat list and apply only when
  the list confirms the chat. Left-nav click on a 9-message chat: 7.7 s -> 3.1 s (first after
  restart) / 2.1 s (warm). Remaining: the project read gates the chat (~0.8 s) and ~11 concurrent
  requests (doubled by dev Strict Mode) contend in one API process.
- Not done (founder: only if still slow): start chat reads before the project read (needs a shared
  prefetch store because the chat view remounts per chat by design); reuse the project across chat
  switches; batch the per-document DB checks into one query.
- Pre-existing failure seen, not ours: tests/api/test_reference_images_contract.py (DesignLegTurnRunner
  has no _conn_factory).
- Lane stack: DB copy `clue_nashville_pm` (original `clue_nashville` untouched; .env backup
  `.env.bak-2026-10-15-before-pm-db`); page origin on 8064 because addis-ababa holds 8040.
