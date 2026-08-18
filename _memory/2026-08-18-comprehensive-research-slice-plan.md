# 2026-08-18 — Comprehensive account/contact research: detailed A–G implementation plan authored

**Branch:** `platform/comprehensive-account-contact-research`
**Deliverable:** `docs/specs/FI-comprehensive-account-contact-research-plan.md` — the granular, task-level implementation plan for the founder-ratified contract `docs/FI-comprehensive-account-contact-research-contract.md` (§11 slices A–G). Planning session only; no product code changed.

## How it was produced
Five parallel read-only recon agents mapped exact current state before writing (all facts in the plan carry file:line cites): account launch path, committee/role-inference path, contact selection/launch/channels, progress projections + frontend task card, settings/flag composition. The 2026-08-18 audit transcript (`.context` attachment) was read as evidence; the contract supersedes it where they conflict.

## Load-bearing recon facts the plan is built on (verified 2026-08-18)
- `PROSE_ACCOUNT_FIELDS` (21) at `subsystems/research/clue_research/narrative/prose.py:142-164`; `PROSE_CONTACT_FIELDS` (15) at `:189-206`.
- Launcher drops `core.*` via raw `startswith("account.")` at `platform/api/clue_api/account_research_fleet_launch.py:325-332`; the shared wider projection `account_axis_field_keys` already exists (`libs/clue-core/clue_core/field.py:108-118`) and is what the in-job preparation uses.
- Fresh-claim reuse is deliberately post-launch (`born_complete_account_field_keys`, `account_entity_research.py:127`; subtraction at `exa_deep_preparation.py:141-157`; rationale comment at launcher `:244-269`) — plan keeps it, does NOT add a launch-time freshness probe.
- Exa >8-field bundling already exists (`EXA_OUTPUT_MAX_FIELDS=8`, `deep_contract.py:51`; packer `exa_deep_acquisition.py:881-998`).
- Committee coupling raises unconditionally for account-only jobs at `entity_research_provider_wiring.py:361-367`.
- Coverage table CHECK forces `account.%` field keys (migration `85595185f793` line ~195) — needs widening for `core.*`.
- False-HUMAN role provenance fallback: `profiling/committee/worker.py:97-116`; `needs_review=0` hardcoded `:503-511`; role inference is a worker leaf-LLM call (`infer_role`/`gate_role`), not the account agent.
- `approve_contact_research_selection@2` granted to nobody (`agent_registry_wiring.py:53-56`); precedent for reachability = trusted-turn `LaunchSelectedAccountResearchTool` (`entity_research_launch_tools.py:127-390`, `source_turn_ref` == `ctx.action_ref`).
- Contact slots miswired: `deep=contacts.build, enrichment=contacts.build` (`entity_research_provider_wiring.py:630-634`) while runtime authority makes Exa-based `enrich_contact` impossible (`contact_entity_research.py:1073-1076`) — structured enrichment is unreachable today.
- LinkedIn-only gates enumerated at: `contact_research_selection.py:276`, `frontend_read/contacts.py:684`, `bulk_actions.py:710`, `contact_channel_enrichment.py:341-346`, `exa_contact_compiler.py:515`; launch path already accepts `linkedin OR verified_email` (`contact_research_fleet_launch.py:477`).
- Live-progress substrate exists with no HTTP surface: `research_tasks_for_action_refs` (`clue_projections/research_tasks.py:116`), only caller is the turn-close snapshot (`chat/turn_stream.py:908-924`); turn SSE closes at terminal; card is stream-only (lost past `REHYDRATED_TURNS=3`); `needs_review` folded into `partial`; gates `_LAUNCHES_SQL` omits contact launches.
- No settings profile mechanism exists; all §9 flags default off in one flat `Settings` (`clue_config/settings.py`, `CLUE_` prefix); typed `EntityResearchProductionCompositionError` is the fail-visible precedent.

## Plan shape (summary)
- **A** — `CLUE_PRODUCT_PATH=integration_pilot` overlay in `Settings` (checked-in defaults; explicit env wins), startup credential preflight, freeze 21/15 contracts + static provider ownership (`clue_api/comprehensive_research_contract.py`), excluded-provider tripwires. Phased overlay: channels join in F, C7/handoff in G (their composition raises before those slices land).
- **B** — launcher filter → `account_axis_field_keys`; widen `account.%` CHECKs (migration); manifest `yields` extended per §3.1 ownership; `profile="comprehensive"` directive expansion (tool v4, skill account-deep-steering v7, profile v37); committee coupling decoupled; Sumble field materialization completed; deterministic employee_range/revenue_band derivation; 21-field settle acceptance test.
- **C** — needs_review split end-to-end; `GET .../threads/{id}/research-tasks` durable read over `research_tasks_for_action_refs` (revision = max job event_seq); frontend 3s poller (email-lookup pattern) into the existing card; cold-load rehydration.
- **D** — kill HUMAN fallback (D1, independent); `role_inference="agent_deferred"` discovery mode; new `record_committee_role_inferences` engine tool (account catalog v2, launcher pins v2); honest needs_review; roleless members stay visible.
- **E** — shared `contact_supported_identity` predicate replaces LinkedIn-only gates; `launch_selected_contact_research@1` trusted-turn tool (explicit_contacts | account_committee expansion) minting the human-authority selection receipt from the user's turn; steering skill update.
- **F** — `SumbleContactSemanticEnrichmentAction` (reuse-first People/Teams); slot routing fixed; 15-field defaults (contacts 3→20, fields 8→15); batching behind one `source_action_ref` task; channels observed-only with real adapters (no validator vendor permitted — states capped at OBSERVED); contact/channel progress on the task read + gates SQL fix.
- **G** — overlay completes (C7 read/compose/handoff); [C7×core] NULL-binding statement-drop fix; §12 browser acceptance matrix + paid email canary per the 2026-08-16 evidence conventions; §14 definition-of-done audit.

## Open decisions flagged for founder (in the plan's final section)
1. Product-path overlay mechanism (vs global default flips / tracked env file).
2. Role inference relocated into the account agent (vs worker-LLM + provenance fix only).
3. Ungrounded candidates carry no role claim (member visible, role empty).
4. Channels observed-only (no permitted validator vendor; paid canary = real email lookup).
5. Out-of-contract adjacent defect: chat pagination (oldest-50, cursor ignored) — recommended alongside Slice C, needs scope ruling.

## Follow-ups / not done here
- No implementation started; every slice awaits founder review of the plan (and the four open decisions) before Slice A begins.
- Profile/skill version numbers in the plan (v37/v38, skill v7, catalog v2) are "next free at implementation time" — re-check against the live catalog before promoting.
