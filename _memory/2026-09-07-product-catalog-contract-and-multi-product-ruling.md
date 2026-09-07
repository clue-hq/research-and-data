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
- **D17** — the Exa `outputSchema` for the catalog is final: 8 properties (2 top-level + 6 per item; my earlier "9" was a miscount, corrected by the R1 lane), depth 2, no citation
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

## Addendum (same day, later): company-overview contract + onboarding lane shape

- NEW `docs/specs/ARV2-COMPANY-OVERVIEW-CONTRACT.md` — Exa **Agent** run (`/agent/runs`, effort
  `high` = fixed $0.50), query = the founder's nine-section due-diligence prompt, schema = facts /
  seven markdown sections / competitors / named_customers / not_found. Live-validated on Insight
  Health: 67 s, $0.50, 60 searches, `schema_satisfied`, 8 grounding rows (per SECTION, not per
  fact; competitors/customers/not_found carry no grounding → v1.1 open item `evidence_url`).
  Artifact `CompanyOverviewResearch@1`: front matter = facts/competitors/customers/not_found/
  sources; body = fixed H2 headings in fixed order; `not_found` is RENDERED.
- Onboarding lane shape (Aryan, 2026-09-07): no scrapers as primary source. Fast recon = company
  overview (Agent, high) ∥ product lineup (search deep-reasoning) → ICP synthesis (2–3 ICPs at
  BRAND level, each naming its products) → one persona document per ICP (a section per
  persona_map role). Background = one Agent run per discovered product, parallel. All rendered
  read-only as markdown in the brand-context Knowledge folders (Company / Product / Audience /
  Proof). The Head-of-ABM reads the files itself (`read_file`) — NOTHING verbatim in opening
  context except the L2 index card (Aryan overruled the verbatim set). Customer reviews = separate
  Agent run (medium), contract not yet written.
- ICP reconciliation with P3/P4: ICPs live at brand level (2–3 per company, each with
  `product_ids[]`); a project picks exactly ONE; the project product set defaults from the ICP's
  products and is edited at the product-set gate. Contract §6.4 + master plan §5.2 still need this
  rewording (pending Aryan's explicit yes to point 1 of the 18:0x message).
- Security: the Exa request sample Aryan pasted (`.context/attachments/52gUp1/`) contains a LIVE
  Exa API key in `Exa(api_key=...)`. Not copied anywhere; flagged to Aryan to rotate.

## Addendum 2: the Track O plan written

- NEW `docs/specs/ARV2-ONBOARDING-PLAN.md` (v1.0, PROPOSED): outcome + settled rulings S1–S8,
  architecture + artifact tree, the `onboarding_run`/`onboarding_step`/`brand_knowledge_document`
  state contract (failure law: recoverable refusals, `completed_with_gaps`), the three remaining
  research contracts as sections (reviews 4.3, per-product 4.4, evidence tool 4.5), the
  `onboarding-synthesis@v1` agent (prompt + `icp-synthesis` + `audience-persona` skills, final
  text), ICP/persona artifact formats, the Knowledge read contract (§7), Head-of-ABM integration
  (§8), phases O0–O7 with exit gates/owners/timeline, flags (§10), decision boxes O-D1–O-D6.
- Aryan's rulings captured before writing: persona evidence pass ON, thin evidence OK; brand-level
  ICP model confirmed; the ICP/persona prompts are for OUR synthesis agent, Exa only via the
  governed `exa_search_evidence@1` tool with a fixed template.
- Waiting on Aryan: O-D1 (synthesis model), O-D2 (per-product effort), O-D3 (reviews fast vs
  background), O-D4 (doc form), O-D5 (ICP gate @2 over artifact refs), O-D6 (evidence default).

## Addendum 3: origin merged (R1) + D1 coordination rule

- `85ec9db96` merged origin/integration/design-improvement (track-R PR #45, R1 clients) — one
  conflict in `_memory/README.md`, both sides kept. R1 corrected the catalog schema count to 8
  (carried into the plan + this note, `c54c53873`). Plan O2 re-based on R1's `arv2` package
  (`a778cf45e`): Exa search/deep-reasoning client + `ProviderCaller` exist; O2 adds the Exa Agent
  surface + 4 templates + mappers; tests LIVE per R1 ruling; driver uses `asyncio.to_thread`, one
  `ProviderCaller` per worker task.
- **D1 runs in parallel.** O1 ↔ D1 touchpoints (from the D1 lane, relayed by Aryan): Alembic
  (same head; second to land runs `alembic merge`), `settings.py` + `.env.example` (hand merge),
  and **O1 must not touch `clue_core.enums.Persona`** (D1 adds `user`). Recorded in the plan §9.
- Six decision boxes O-D1–O-D6 still open on Aryan's side (explained to him 2026-09-07 evening).

## Addendum 4: onboarding plan RATIFIED (Aryan, 2026-09-07 evening) — v1.1
O-D1 grok-4.6 + **effort blank (model default)**; O-D2 per-product `medium`; O-D3 reviews in
**fast** recon; O-D4 contracts stay as plan sections; O-D5 ICP gate @2 over artifact refs,
`synthesize_icps` off the new profile; O-D6 evidence tool default ON. Next: O1 + O2 implementation
plan (writing-plans), then charters for two parallel worktrees; O1 must respect the D1 rule
(Persona enum untouched; alembic merge if second).

## Addendum 5: O1 + O2 implementation plans written (writing-plans)
- `docs/superpowers/plans/2026-09-07-arv2-onboarding-o1-substrate.md` — 5 tasks: settings+env,
  the one migration (onboarding_run/step/document), project_product + spine fns, the
  product_set_selection kind + full answer-validator text (downgrade text proven == 064ad0f43519),
  close-out (one head, throwaway db-smoke, checklist, D1 merge rule).
- `docs/superpowers/plans/2026-09-07-arv2-onboarding-o2-exa-agent-surface.md` — 5 tasks: Agent
  pure parts, `ExaClient.agent_run` (create/poll/settle, ScriptedTransport for sequencing, live
  low-effort run), `onboarding_requests.py` templates, `onboarding_documents.py` mappers (+pyyaml,
  fixture = the Insight Health sample), guards/README/close-out.
- Facts verified for the plans: platform_user has (user_id, display_name, status) — no email;
  ScriptedTransport.requests; HttpRequest keeps header case; _body_json never raises;
  execution_reject_append_only_mutation raises unconditionally (UPDATE OR DELETE ok);
  alembic head = 44039cb83844 (single).
- Execution rule (memory): implementers = Opus subagents only; Fable reviews every task first-hand.

## Addendum 6: O3 + O4 implementation plans written (2026-09-07 late)
- `docs/superpowers/plans/2026-09-07-arv2-onboarding-o3-fleet-driver.md` (7 tasks) and
  `docs/superpowers/plans/2026-09-07-arv2-onboarding-o4-synthesis-agent.md` (7 tasks). Facts used:
  `.superpowers/sdd/o3o4-facts/{o3-driver-facts,o4-agent-facts}.md` (Opus Explore agents; verbatim signatures).
- Rulings baked into O3: onboarding gets its OWN artifact-keyed lineage table (`onboarding_product_lineage`;
  the old `product_catalog_lineage` is claim-FK'd and stays replay-only); the client-entity binder and the
  synthesis launcher are injected seams because the ARV2 import guard forbids `clue_api.arv2` from importing
  `clue_research.stage0` / other `clue_api` modules; one `ProviderCaller` PER STEP under
  `arv2_raw_root/onboarding/<run>/<step>/`; the two lineup passes merge by normalized name, own-domain
  grounding only; `POST /onboarding` refuses a second queued/running run per workspace (409).
- Rulings baked into O4: a governed turn needs a project + execution row, so the synthesis turn runs under a
  per-brand SYSTEM project row (`prj_onb_…`, name "Onboarding · <brand>", status `archived`) — O5/O6 must keep
  it out of the sidebar; inputs materialize as extra `WorkspaceSeedFile`s under `inputs/brand/knowledge/…`
  (ProjectLayerSource can only emit flat context/project/<name>.json); the turn executes inside a new one-gate
  system recipe `onboarding-synthesis-unit@1` (slot `onboarding_synthesis_interactions`, tool allowlist
  `exa_search_evidence@1`, static pin = skill `audience-persona@v1` satisfying the tool's `pin_requirements=("skill",)`);
  outputs are identified by their YAML front matter (`snapshot_outputs` discards logical paths); the C5 policy
  budget is a $5 record-only constant.
- Cross-lane: O3 and O4 each cut a migration off `0aa95f87eb49` → `alembic merge` when the second lands; O4's
  `OnboardingSynthesisResult` mirrors O3's `SynthesisOutcome` structurally (reconcile at merge); D1's
  `provider_call_ledger` replaces the JSONL sinks and its `user` Persona role lands separately.
- Both plans' final acceptance runs (money) are founder-triggered tasks, never run by an implementer.
