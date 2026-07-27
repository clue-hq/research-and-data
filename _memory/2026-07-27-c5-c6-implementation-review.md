# 2026-07-27 — C5/C6 implementation review (multi-agent audit)

Full adversarial review of the C5+C6 implementation (`08c1998..7755bea`, ~53.8k added lines,
269 files): 11 finder agents (3 line-scan slices, removed-behavior, cross-file tracer, reuse,
2× simplification, efficiency, altitude, conventions) → 48 deduped candidates → 12 verifier
agents (CONFIRMED/PLAUSIBLE/REFUTED, recall-biased). No code was changed in this session.

## Confirmed correctness defects (ranked)

1. **Workspace crash-brick** — `platform/agents/clue_agents/workspace.py:347`: a crash between
   `_write_temp`'s fsync and the link/unlink leaves a `.clue-tmp-*` residue; `_walk_files` raises
   on it, `_reopen_backend` never cleans subdirs, `snapshot_outputs` → `authorize_cleanup` →
   `cleanup` are chained behind the failing walk, and `discard_failed_materialization` is barred
   once resources are frozen. Turn can never finalize or clean up. Fix: sweep `.clue-tmp-*`
   during reopen/acquire (safe: residues are never linked into the tree).
2. **Executor infinite spin** — `executor.py:1685` + `invoker.py:183-191`: a raise before
   `journal.begin` (registry.get / input model_validate / snapshotter) journals no node terminal;
   `except Exception: return` swallows it, drive loop has no attempt cap → tight unbounded
   re-selection for a deterministic failure.
3. **Review-approval stall** — `api/review/composition.py:192-202`: checkpoint commit and
   `enqueue_run_drive` are non-atomic; crash between them + client retry hits
   `CheckpointNotAwaiting`, which is swallowed *before* re-enqueue. No run reconciler exists →
   approved run permanently unqueued.
4. **Map-expansion replay failure** — `executor.py:1842-1853`: on crash-replay `existing_count`
   already includes committed children and `requested` is added again; ceiling spuriously trips →
   resumable run becomes EXECUTION_FAILED. (`_insert_node` is row-idempotent; the *count* is not.
   Latent for shipped recipes — none use map nodes yet.)
5. **FAILED finalize masked** — `agents/runtime.py:234-248`: accepted statuses exclude FAILED, so
   an honest committed FAILED finalize is reported as `missing_finalize`, discarding the real
   failure_code.
6. **Required-context starvation** — `agents/context.py:556-591`: candidates iterate in
   stable_key order; a large earlier *optional* card (e.g. L3 `project:`) can consume the layer
   budget so a later *required* snapshot raises and aborts the turn.
7. **Uncertified default tool** — `api/toolbelt_wiring.py:1687-1703`: `research_account_gaps@1`
   (replay=uncertified, effect_class=WRITE, no pins, cost 0) is `make_default=True`; the HTTP
   `/tools/{name}` route takes no version → direct invocations get v1; replay-safe SPEND v2 is
   non-default and agent-only.
8. **Plan budget no-op** — `api/coverage_tools.py:213` (+`agent_execution_wiring.py:1330`):
   estimate() returns cost 0 for both v1/v2, so validate_plan's budget ceiling sums 0 for SPEND
   coverage ops and never rejects. (Related confirmed gap: PlanDelegationStep excluded from the
   slot max_children/max_nodes count at `agent_execution_wiring.py:1132-1143`; bounded only by
   the parallel policy graph ceiling.)
9. **Lineage guard at wrong altitude** — DISCOVERY-entry Stage-0 lineage completeness lives only
   in `api/project_execution_router.py:202-205`; `durable/project.py` `advance()` has no such
   transition guard, so a legacy/non-recipe run reaches DISCOVERY unchecked.
10. **Boot crash from stale route row** — `api/fleet_main.py:189-213`: a leftover
    `agent_runtime_route` owner='deepagent' row forces `build_agent_platform_components` even
    when `CLUE_AGENT_WORKSPACE_ROOT` is unset → `WorkspaceConfigurationError` at boot instead of
    mechanical-profiler fallback.

## Confirmed second-tier (not in top-10 report)

- `workspace.py:811-816` grep() lacks the `except WorkspaceError` wrapper every sibling has;
  default `**` glob over a binary/oversized file raises out of the tool boundary.
- Registry `names()`/`__contains__` are default-alias-only (`toolbelt/registry.py:62-88`) while
  authority admission keys on exact address (`agent_registry_wiring.py:161-180`) — audit and
  admission surfaces diverge for non-default versions.
- `stage0/governed.py:818-843` readiness replay guard omits metrics/reason_codes from the
  expected/actual comparison (verdict is compared; stale metrics survive in the durable row).
- PLAUSIBLE races: supervisor/controls read cursor without FOR UPDATE then append (spurious
  StaleCursor vs live drive loop, no retry wrapper; supervisor.py:255/411, controls.py:383);
  `work_worker.py:173` LostExecutionLease → generic except → finish(FAILED) terminal (narrow
  window); telemetry `cache_read_ratio` `le=1` can 500 if a provider reports cache_read outside
  input_tokens (`projections/agents.py:364`); DEEP aggregate counts envelope-excluded/quarantined
  accounts as succeeded in scalar counters (manifest does distinguish; `deep/handler.py:263,415`).
- Stale error text: ResumeRunTool failure message still says "only a PAUSED run can be resumed"
  though accepting ACTIVE is now intentional (`toolbelt_wiring.py:1484`).

## Confirmed cleanup themes (simplification/reuse/efficiency)

- **Duplicated safety-critical logic:** dead-in-production `ProjectRunWorker`+`build_fleet_worker`
  duplicate the B1 heartbeat/fencing logic vs `LeasedWorkWorker` (delete the dead pair); Kahn
  toposort written twice in `agents/contracts.py` (502-529 vs 600-635); cross-workspace fail-closed
  guard hand-copied ~18× across contracts/execution/context/workspace (needs one
  `require_same_workspace` helper); "exactly seven layers" validator ×3; folder catalog loader
  triplicated (`catalog.py:352-477`); gateway agent model 8-way envelope duplication with the sync
  half dead in production.
- **Five divergent canonical-JSON digest implementations** (clue_core.canonical_json,
  compatibility.canonical_payload_digest, graph.canonical_sha256, parameters.py inline,
  executor._canonical_bytes) with different flags — latent digest-mismatch family; collapse onto
  one clue_core helper. Also `parameters.py:94` hand-builds the artifact key bypassing
  `clue_storage.protocol.artifact_key`.
- **Dead machinery:** ActivityNode/ActivityInvoker path (no recipe, no invoker, raises if reached);
  RunControlReader + ExecutionRunViewReader protocols (zero consumers); unreachable
  RoleRegistryStatus.PLANNED + Optional profile; `__observe_current__` magic string pattern-matched
  cross-package (recipe_wiring.py:465,532) with no shared constant.
- **Hot-loop efficiency:** executor drive loop O(N²) (reloads+re-validates all node JSONB per
  iteration, ~6 sequential fresh-connection round-trips incl. redundant envelope JOIN);
  journal.append_event per-event SELECT of immutable execution metadata inside the cursor lock;
  rebuild_cursor and read_execution load full unbounded event history; recipe library view does a
  15-field json round-trip to read one already-decoded field + per-row correlated subquery +
  sequential compatibility.load.
- **Policy-as-code (mild):** `_REQUIRED_ACTIVE_ROLES` frozenset and `SpecialistTaskEnvelope.role`
  Literal hardcode role sets that profiles supposedly own.

## Refuted (guards proven — do not re-flag)

Streaming usage take-last (stream_usage=True → cumulative final chunk); admission-preamble drift
(build-path vs runtime-class mis-comparison; runtime checks are identical); supervisor
action_candidates loss (nothing consumes them for controls); lease compat adapter atomicity (one
txn + dead path); resume re-enqueue ×2 (queue ON CONFLICT + reopen-only-on-terminal make it a
no-op); coverage requested_round replay (bounded, marked, engine-authoritative); recipe pin
fallback (PinRequest validator forbids empty pins; compatibility.load catches mismatch);
recipe1-only ownership row (AdvanceProjectPhaseTool owner-gate + legacy guard block non-owners).

## Verification performed

Read-only review; no tests run, no code changed. Findings reported to the user via the review
surface; fixes not yet applied. Follow-ups: items 1-10 above are pre-production blockers for the
agent-canary path; cleanup themes are good C7/C8-adjacent refactor slices.
