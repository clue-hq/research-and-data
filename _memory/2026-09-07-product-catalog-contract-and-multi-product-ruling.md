# 2026-09-07 — product-catalog contract + the multi-product-per-project ruling (Track O)

Session with Aryan on the onboarding product catalog. Docs only; no code, no migration.

## What was decided (all Aryan, 2026-09-07)

- **P1 — a project targets a SET of products, not one.** Aryan overruled the recommendation to
  keep one product per project ("a very important ruling"). Durable shape: new `project_product`
  table, full set written per `selection_version` (append-only); `project.product_id` frozen as a
  legacy column, NULL for new projects; `confirm_project_product@1` replay-only.
- **P2** — the set can change any time as a new version; runs pin `(project_id,
  selection_version)` and keep it; nothing is re-researched automatically.
- **P3/P4** — exactly one ICP per project, targeting the whole set. No per-ICP product subset
  (the recommendation had been "subset allowed, default all"; overruled). Two product lines with
  two ICPs = two projects.
- **D17** — the Exa `outputSchema` for the catalog is final: 9 properties, depth 2, no citation
  fields (Exa returns `output.grounding` per field), `aliases` deliberately dropped. Exa docs
  (28 Aug 2026) limit `outputSchema` to depth 2 / 10 properties; `enum` is not on the documented
  keyword list — if rejected, values move to `description`, enforced platform-side.
- Gate: new kind `product_set_selection`, approved answer = `decision_payload.selected_option_refs[]`
  (≥ 1, each a snapshot candidate; per-element trigger check like `064ad0f43519`); browser
  transport `selected_product_ids[]`; old `product_selection` kind replay-only.
- Every catalog entry becomes a `product` row regardless of `offering_kind` (kind = grouping
  label, never a filter — a partner program is a legitimate ABM motion). `lifecycle` is a label;
  spine `product.status` stays human-controlled.

## Files written / edited (local commit, not pushed)

- NEW `docs/specs/ARV2-PRODUCT-CATALOG-CONTRACT.md` — the chain, the Exa shape, the
  `ProductCatalogResearch@1` artifact + grounding mapping, claim/sync deltas, the multi-product
  design (§6), wire contract (§7), the implementation file list (§9).
- `docs/specs/ARV2-MASTER-PLAN.md` → v1.6: header, §5.1 (`product_selection_version` on the run),
  §5.2 (ICP front matter provenance; one ICP per project over the whole set), Track O pointer,
  §12 rows D14–D17.
- `docs/specs/ARV2-ROADMAP.md` — child-doc pointer.
- `apps/frontend/docs/api-contracts/projects.md` — dated pointer amendment above the 2026-08-15
  combined human-gate amendment.

## Inventory of the single-product assumption (for the implementing charter)

`project.product_id` + `clue_spine.confirm_project_product`; `ConfirmProjectProductTool`
(`stage0_tools.py`); the `product_selection` gate + answer trigger (`agent_gate.py`,
`chat/schemas.py`, `chat/router.py`, migration `064ad0f43519`); `agent_turn_scope_pin`
(`company-and-selected-product-required-v3`); `ProductProfileCard@1` / `ProductKnowledgeCard@1` /
product tools; `project_run.product_id` + `project_run_stage0_pins_complete` (`1b71451d48cd`);
`account_research_turn_wiring` (run product == project product); C7 `research_view_api` pinned
read; `stage0_trial`; frontend `chat-gate.ts` / `chat-gate-card.tsx` (`selectedProductId`).
Old-lane readers are NOT rewritten: a NULL project product puts them in the S5.0 "no product
selected" state; all are quarantine-bound (Phase 6).

## Open / follow-ups

- Shashank's initials on D14–D17.
- Product-set display on the accounts screens has no designed slot (stays invisible per the
  dummy-frontend rule).
- Implementation charter per contract §9 (migration, gate kind, Exa client, frontend set-valued
  gate) — not started.
- D9 (Series A equivalence clause) still open.
