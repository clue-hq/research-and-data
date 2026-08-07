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
