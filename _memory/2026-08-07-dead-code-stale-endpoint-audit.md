# 2026-08-07 — Dead-code / stale-endpoint audit (clue_research + clue_api), pre-frontend-integration

Read-only audit by four parallel Opus review agents (substrate sweep, deep-research-flow sweep,
endpoint audit, mechanical dead-code detection). No code changed. Findings below are the
operational summary; each was verified with repo-wide caller searches.

## Endpoint reality (clue_api)

- Only ONE HTTP app is production-launchable: `projections_main` (`trial_main` is a
  loopback-only canary reusing it; `fleet_main` is a worker, not HTTP). No Makefile/compose/
  `[project.scripts]` target launches anything — deployment lives outside the tree.
- `handoff_app.py` (M12.3, 3 routes under `/accounts/{id}/handoff*` + `/project_runs/{id}/handoffs`)
  is FULLY ORPHANED — no entrypoint builds it; superseded by C7 research-views. Its route root
  also collides with the frontend's intended `/accounts/:id` path.
- All 11 C7 research-view routes are flag-gated and ALL SIX `c7_*` flags default False —
  a stock projections_main serves only projections/tools/SSE/ingestion.
- Stale aliases: the three `/dossier` routes (C7.7 deprecated aliases, default-off) — retire.
- Redundant: `PATCH /project_runs/{id}/manifest` duplicates `POST /tools/{pause_run|resume_run|
  adjust_budget}` and silently drops the Idempotency-Key. `GET /agent/registry` is never
  registered in production (no agent_registry passed).
- NO accounts-list endpoint exists anywhere. Nearest: `/project_runs/{id}/readiness` (ids/tier/
  status only) and `/v1/projects/{id}/research-view-status` (no names/domains/scores). The
  frontend accounts table needs a NEW backend read endpoint.
- Also for integration: three-way path-prefix inconsistency (`/v1` vs none vs `/ingestion`),
  header-based local auth only (`X-Workspace-Id`/`X-Actor`, `projections_auth_mode=local_header`
  enforced at startup), no error-envelope exception handler anywhere.

## Silently unbound production wiring (bugs, not in the CLAUDE.md backlog)

1. `register_synthesis_wiring` is never called by any production entrypoint → M11 tier-4
   synthesis resolvers (Exa Deep / Parallel Task) are unregistered in every production process.
2. `stage0_scrape_binder` is never passed to `build_toolbelt` (all three call sites) → PC-C4's
   live official-site scrape resolver is None in production (`phase_c_wiring.py` test-only).
3. NO deterministic resolver is registered in production at all (`register_deterministic_resolvers`,
   crm/firecrawl/generic_web/parallel binders — zero production callers). Live registrations are
   Exa + Sumble only. Product decision needed: is the M4 trust-tiered waterfall still the plan?
4. `compliance/use_gate.py` predicates (`should_store`, `gathers_source`, `usable_use_classes`,
   `decide_use`) and the M10.4 posture presets are tested but never enforced on any production
   path. Correctness/compliance question, not cleanliness.

## Deep-research flow (M8B→M8C→M8D) staleness

Live path today: `launch_account_research@1` → `AccountResearchFleetLauncher` →
`entity_research_job` queue → `SubjectNeutralEntityResearchWorkHandler` → M8D create_agent
units (account/contact catalogs v1) → governed entity_research/exa/sumble tools →
`resolve_field` with single-source override; contact: `approve_contact_research_selection@2` →
`ContactResearchFleetLauncher` → shared fleet → Exa compile/acquire/materialize → channels →
wake → `compose_contact_content_handoff@1`. Master gate `CLUE_ENTITY_RESEARCH_RUNTIME_ENABLED`
defaults False; provider flags independently default False.

- The M8D R1 quarantine (`entity_research_quarantine.py`, 9 replay-only tool addresses) is still
  the only fence. The quarantined inner tools are STILL FULLY CONSTRUCTED at toolbelt_wiring
  with all collaborators, then wrapped in a never-delegating shell — that construction is why
  the legacy trees can't be deleted piecemeal. ~8.5 kLOC in platform/ + ~30 modules in
  clue_research are structurally unreachable behind it: all of `clue_api/deep/` (2,364 LOC),
  `coverage_tools.py`, `exa_deep_preparation.py`, `sumble_committee_preparation/launch`,
  `contact_research_preparation.py` + `independent_contact_research.py`, the C6/C7
  account-research-unit wiring (`account_research_wiring.py`, `account_research_turn_wiring.py`,
  `RoutedAccountProfiler`), old fleet driver builders (`build_fleet_deep_scheduler/run_driver/
  worker` → `QueueBackedScheduler`, `ProjectRunWorker`), `sumble_mcp_journal.py` + sumble MCP
  adapter/client (superseded by REST v9), `sumble_committee_wake.py`, and the M7/M8 account-axis
  cluster in clue_research (`profiling/account|aspect_worker|resonance`, `durable/graph|workers|
  scheduler|planning|recursion|spans`, coverage controller/judge + ledger writers).
- BEHAVIOR GAP (most important finding): `run_composition.py:418` registers the quarantine
  handler for ProjectPhase.DEEP, which raises unconditionally → no new project run can ever
  reach VERIFICATION or HANDOFF. And `run_verification@1` (NOT quarantined, granted to
  AgentRole.RESEARCH) depends on `get_account_deep_launch`, whose only writer is quarantined →
  always returns accounts_processed=0 on M8D-researched accounts. Verification + C7 handoff are
  structurally orphaned from the M8D path. No memory note records a decision — bridge missing.
- `coverage` ledger: `record_attempt/decision/evaluator_advice` have no live writer, but the
  readers (research_view_readers, clue_projections/research_coverage) are live → can only
  return empty.
- Source-call telemetry observer (`bind_source_call_observer`) bound only from quarantined
  `deep/handler.py` → M4 per-source-call telemetry inert; `supervisor_wiring` run-aggregate
  queries `fleet_task kind='account_job'` which nothing can produce → always empty fleet.
- `synthesis/gating.guard_synthesis_resolution` (M11.3 tripwire) off every live claim path.
- `approve_contact_research_selection@1` still registered, un-quarantined, functional (agent
  authority empty but a version-pinned human/API call works) — decide: quarantine or document.
- `ContactResearchSelectionMaterializer` composed only by scripts/13 acceptance harness —
  production composer unclear.
- projections_main constructs credentialed Exa-targeted + Sumble-gap provider starters whose
  only consumers are quarantined tools (wasted live credentials/construction).

## clue_research substrate dead code

- M12.1 `narrative/positioner.py` + prompts/policy/reuse tail (~900 LOC) never composed →
  `account.value_narrative` has NO writer; research-view VALUE_NARRATIVE section always empty;
  handoff narrative marker path is the only honest signal. `ATTR_PERSONA` literally 1 hit repo-wide.
- M13.3 learning loop chain (`review/learning|reweight|config_revision|yield_metrics`,
  `learning_wiring`, `backtest_wiring`) unreachable; `learning_wiring` has zero refs incl. tests.
- `review/millicredits.py` (172 LOC + DB table `b2df6d050fc5`) — no production reader.
- M5.4 `stage0/seeds.py` (663 LOC lookalike seeding) test-only. M2.4 `identity/review.py`
  queue has no producer. `stage0/readiness_policy.py` writer test-only (live reader reads rows
  only tests write).
- B3 retirement prose still stale in `claimstore/tenancy.py` and `identity/reuse.py` docstrings;
  `ReusePolicy` is a knob permanently one value.
- Duplicates (new, beyond backlog): two `VerificationHealth` models (narrative/health vs
  review/observability), two golden frameworks (verification/golden vs coverage/golden — latter
  has zero production importer), two disposition taxonomies (identity/review vs review/
  disposition), two ICP diffs, two committee-reader protocols, `_EmptyInput` ×2, `as_json` ×2,
  `_json_object` ×3 (one dead).
- Mechanical pass: zero orphan modules, zero TODO/FIXME/HACK/DEPRECATED markers repo-wide,
  13/6547 defs dead (~0.2%). `EntityResearchJobStore.list_jobs/cancel_run` protocol+impl pair
  unused. Large test-only inventory in compliance/verification/icp (posture presets,
  lawful-basis notice report, spot-check surface, golden seeding, etc.).

## Leave-alone confirmations (do not re-litigate)

`entity_research_quarantine.py` itself (the replay-only fence is load-bearing);
`sources/waterfall.resolve_field` + `plan_sources` (live claim writer/planner on M8D path);
`discover_committee`, `fill_contact_field`, `sumble_account_gaps`, `sumble_committee_inputs/
source`, `committee_eligibility`, `exa_websets_*` (M6A discovery, different flow),
`external_research_wake`, `contact_channel_enrichment`, `evals/` package (Makefile `make eval` +
verification imports), ingestion upload route (byte boundary, not redundant with the tool),
`get_research_view` tool vs REST route (refs-only vs composed body — both needed).

## Follow-ups handed to the founder (decisions, not edits)

1. Quarantined-tree disposition: keep replay-by-descriptor but stub the inner tools and delete
   the implementation trees (D1), or keep as-is.
2. The DEEP→VERIFICATION/HANDOFF bridge for M8D runs (J3) — known gap or oversight?
3. Resolver-waterfall future (deterministic resolvers unregistered) — D5.
4. use_gate/posture enforcement — compliance machinery unwired.
5. Frontend integration surface: C7 research-views + projections/tools/SSE only; needs a new
   accounts-list endpoint, prefix decision, auth decision, error-envelope decision, and C7 flags
   turned on.

No code was modified in this session. Full per-agent reports were delivered in-conversation only.

## Addendum (same day) — founder disposition: cleanup DEFERRED

Founder reviewed the audit and ruled on timing. Recorded here + in the CLAUDE.md backlog
(entries `[M8D×M7×frontend]` and `[audit 2026-08-07]`) so no future session re-opens this
prematurely. Endpoint-section claims were additionally re-verified first-hand by the orchestrator
(launch reality, handoff_app orphanhood, dossier alias handlers/headers/flags, agent-registry
conditional, PATCH-manifest `idempotency_key=None`, trial loopback gate, ingestion delegation,
refs-only tool output). Two corrections found in re-verification: there are SEVEN `c7_*` boolean
flags (not six; all default False — conclusion unchanged), and the handoff-route "collision" is
namespace adjacency (`/accounts/{id}/handoff` unprefixed vs frontend `/api/v1/accounts/:id`),
a prefix-convention question rather than an existing conflict.

1. **Reclassification (founder framing, adopted):** most substrate "dead code" is *awaiting
   composition*, not superseded — composition wiring is complete today only for Stage-0
   interview, account discovery, account profiling research, contact research, and the
   buying-committee flow. Uncomposed milestone machinery (positioner, learning loop, seeds,
   postures, handoff serving, identity review, millicredits) must NOT be deleted.
2. **True cleanup (superseded-forever: quarantined ~8.5 kLOC, old fleet drivers, Sumble MCP,
   handoff_app, /dossier aliases, B3 docstrings) is DEFERRED. Trigger:** design-integration
   branch merged into this branch AND M8D runtime flags exercised on. Then one dedicated
   stub-and-delete PR (descriptor-only stubs at toolbelt_wiring, delete implementation trees).
3. **Composition to-do list (wiring backlog, not bugs — audit misfiled these):**
   synthesis resolvers (`register_synthesis_wiring`), stage0 scrape binder
   (`stage0_scrape_binder` → `build_toolbelt`), deterministic resolver registrations
   (waterfall product decision rides along), and the DEEP-phase bridge (below).
4. **DEEP→VERIFICATION/HANDOFF gap — escalated, mechanics verified first-hand:**
   - The park is DELIBERATE: `run_composition.py`'s comment says DEEP is "intentionally
     uncomposed until the governed create_agent() entity runtime lands." The runtime has since
     landed (R10-accepted, default-off) but was never composed into the phase machine — so this
     is now "runtime landed, composition pending," i.e. itself a composition-backlog item.
   - HANDOFF already parks correctly (fail-closed: no handler unless
     `c7_production_handoff_enabled`).
   - Inconsistency: `run_verification@1` is un-quarantined (granted to AgentRole.RESEARCH) and
     silently returns accounts_processed=0 on M8D-researched accounts (its resolver reads
     `account_deep_launch`, only writer = quarantined `launch_account_deep@1`, agent
     authority `()`).
   - **Recommendation presented to founder: park explicitly now; bridge as its own spec'd lane
     before phase-2 project-level frontend integration.** Bridge shape: a DEEP handler that
     delegates to the M8D fleet (AccountResearchFleetLauncher + external-wake durable wait) and
     a verification account resolver read off the M8D run set instead of `account_deep_launch`.
   - **Pending founder sign-off (small code change, not yet made):** make `run_verification@1`
     fail loud — either add it to `QUARANTINED_ENTITY_RESEARCH_TOOL_ADDRESSES` or error on a
     missing launch ledger instead of returning a zero-account success.
   - Until bridged, phase-2 project-run screens must treat phases past TIER_CHECKPOINT as
     not-yet-composed.

## Addendum 2 (same day) — DEEP-gap decision RATIFIED: bridge, never unquarantine

Founder ratified the diagnosis with a sharpening: the R1 quarantine correctly retired the
M8A/M8B/M8C orchestration model (mechanical orchestrator, pre-agent provider preparation,
committee walking, automatic account→contact progression); verification/handoff are NOT
obsolete — their input/composition boundary was never migrated to the M8D fleet's outputs.
Ruling: the quarantine handler leaves the DEEP slot ONLY when replaced by a new M8D-compatible
adapter; unquarantining/restoring M8C code would reactivate exactly what M8D retired.

Bridge spec drafted: `docs/specs/M8D-R11-deep-phase-bridge.md` (R11.1 join-only DEEP adapter,
R11.2 fleet-terminal wake source, R11.3 verification selector off the R6 content-addressed
selection replacing the account_deep_launch read at BOTH consumers with fail-loud semantics,
R11.4 fleet-shaped DeepExternalWait contract-delta). Additional substrate facts verified while
grounding it: WAITING_EXTERNAL is already valid for DEEP with wake fall-through re-entering the
same handler (durable/project.py:440-442,494-506); the R6 launcher binds project_run_id and
works without the machine being at DEEP (account_research_fleet_launch.py:160, R6 acceptance
§1); EntityResearchJobStore.list_jobs (audit-flagged zero-caller) gets its first customer in
R11 or goes in the cleanup PR; the fleet controller computes all_terminal and
suspended|terminal returns (account_research_fleet.py:1001,207); ExternalResearchWakeDispatcher
has the pluggable sources seam (external_research_wake.py:128).

Spec §6 open decisions awaiting founder: (a) branch placement (recommended: own research-lane
worktree like B3/B4, merged in when accepted), (b) PAUSED vs AWAITING_INPUT for the no-launch
gate, (c) latest-vs-union on multiple fleet runs, (d) budget attribution (single enforcement at
fleet admission), (e) interim run_verification@1 guard only if R11 is deferred. Implementation
does not start until §6 is ratified.
