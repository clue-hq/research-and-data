# STANDING RULE (Aryan, 2026-09-07): no old-lane gate may ever block a new-lane turn

**Track this at every stage of development.** Re-check the checklist below in every charter, every
review, and every merge that touches onboarding (Track O), the Head-of-ABM profile, the product-set
gate, the agent turn wiring, or the ARV2 research lane. Aryan's instruction: "make sure that at
every stage of our development you keep track of this issue."

## The rule, in the master plan's own terms (§2 principle 2, §11, Phase 6)

Exactly two gates exist plus one floor: the lenient claim-write *shape* gate, and **human
authority** (product selection, ICP confirmation, cohort approval, launch, contact selection).
Everything else that blocks is off by configuration, a replay-only stub, or deleted at Phase 6.
The new onboarding lane stores the seller's company knowledge as **markdown artifacts** (company
overview, per-product research, ICPs + personas, customer reviews), **not** as Client-KB claims.
Therefore nothing that demands a Client-KB version, a readiness decision, or a Stage-0 pin may sit
on a new-lane path.

## Disposition of every old-lane mechanism that could refuse a turn

| Mechanism | Is it a gate the plan keeps? | Disposition |
|---|---|---|
| `product_selection` / `product_set_selection` gate | **Yes — human authority** | Stays. Its implementation must build candidates from spine `product` rows (+ the catalog artifact), never from `ClientKnowledgeCard@2` / a Client-KB version. The current `open_product_selection_gate@1` refuses `product_catalog_unavailable` without a Client-KB version — that refusal must not exist in the new tool. |
| `agent_turn_scope_pin` (`company-and-selected-product-required-v3`) | No — a replay receipt | Stays as a receipt; in the new lane it records artifact refs + digests, not a Client-KB version. Its "selected-product turn requires an established company Client-KB" refusal fires only when the legacy single `project.product_id` is set, which new projects never set. Goes with the old lane at Phase 6. |
| `evaluate_stage0_readiness`, `override_stage0_readiness`, `start_confirmed_project_run`, `list_client_knowledge@2`, `inspect_client_claim@2`, `list_product_knowledge@1`, `inspect_product_claim@1`, `synthesize_icps` → `icp_spec` rows, `submit_onboarding_input`/`start_recon` (old recon) | No — Stage-0 recon/readiness machinery | **Not granted** to the new Head-of-ABM profile; the toolbelt boot-time audit refuses a re-grant; replay-only stubs; deleted at Phase 6. "Readiness assumptions are dropped" (master plan Track O). |
| `ClientKnowledgeCard@2`, `Stage0ProjectStateCard@1`, `ProductProfileCard@1`, `ProductKnowledgeCard@1` | No — old-lane context cards | Not composed for new-lane workspaces. Replaced by the L2 brand-knowledge index card + read-only materialized `.md` files the agent reads itself (`read_file`/`grep`). |
| `project_run_stage0_pins_complete` CHECK, `project_run.product_id`, `readiness_decision` FK | No — old Stage-0 run pins | ARV2 runs pin `(project_id, product_selection_version)` + ICP artifact ref; they never populate the Stage-0 pin columns. |
| `account_research_turn_wiring` (run product == project product), C7 `research_view_api` pinned read, `stage0_trial` | No | Historical / quarantined; not on the new path. |
| `client_entity` row (`project_client_entity_id`) | Not a gate — spine identity | **Stays**: onboarding keeps creating the workspace client row at submit; artifacts, product rows, projects and DSAR key on it. |
| Claim write gate (lenient) | Yes — shape gate | Applies only to research claims (accounts/contacts lane). Company knowledge is artifacts, so it is not on the onboarding path at all. |

## The per-stage checklist (run it; do not assume)

1. **Profile grants.** `grep` the active Head-of-ABM profile: none of the readiness / Stage-0 /
   Client-KB / Product-KB tools above are listed. The boot-time audit test still refuses re-grants.
2. **Gate source.** The product-set gate tool reads `product` rows (+ catalog artifact ref); no
   call into `compile_client_knowledge_card_v2`, `current_kb_version`, or `load_pinned_client_knowledge`.
3. **Scope pin content.** New-lane pins carry artifact refs/digests; no code path raises
   `AgentTurnScopePinConflict` for a missing Client-KB on a project with `product_id IS NULL`.
4. **Context composition.** L2/L3 sources for new-lane workspaces compose the index card + seed
   files; no Client-KB card compiler runs; `CLUE_MEMORY_ENABLED=false` stays.
5. **Launch path.** `launch_account_research` needs account rows + ICP artifact ref +
   `product_selection_version` only; grep for any new precondition on `client_kb_version`,
   `readiness_decision_id`, or `project.product_id`.
6. **Static guard.** The "new lane imports no quarantined module" test is green and covers the
   onboarding modules too (`platform/api/clue_api/arv2/**`, the onboarding research agents).
7. **`.env.example` posture** unchanged: `CLUE_SELF_SERVE_PROVISIONING_ENABLED=false`,
   `CLUE_STAGE0_OFFICIAL_SITE_CRAWL_MODE=off`, `CLUE_ENTITY_RESEARCH_RUNTIME_ENABLED=false`.

If any item fails, it is a defect against master plan §2 principle 2 — fix the path, never add a
bypass flag.

## Related

- `docs/specs/ARV2-PRODUCT-CATALOG-CONTRACT.md` §5–§6 (gate reads product rows; catalog input is
  the artifact, not a claim) and §10 (this rule restated).
- `_memory/2026-09-07-product-catalog-contract-and-multi-product-ruling.md` (P1–P4, D14–D17).
- Context-mechanics facts verified 2026-09-07: seven-layer budgets 24k/12k/48k/16k/8k/96k/32k
  (utf8-byte counter); tool messages persist on the thread and reload into L6; the workspace is
  rebuilt per execution with read-only materialized seed files; framework tools `ls`, `read_file`,
  `write_file`, `edit_file`, `glob`, `grep`.
