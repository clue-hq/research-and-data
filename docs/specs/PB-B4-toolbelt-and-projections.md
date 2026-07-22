# PB-B4 — toolbelt façade, projections + SSE, and the fleet run-start composition

**Status:** open (designed 2026-07-22 on `platform/b4-toolbelt-v0`; slices land sequentially).
**Authority:** harness doc §9 step 2 (+ its slotted additions A4/A5/A6/A8/A9 and the
readiness/coverage projection), REQ-02 (toolbelt), REQ-11 (visibility), REQ-16 (treaty Group A),
Doc A (no fake agency; toolbelt = the single write path), the Phase-B treaty §2 (B4 lane), and
the CLAUDE.md backlog items this phase closes. Pre-mortem #2 binds: silent-empty tools are the
enemy; loud preconditions are non-negotiable.

**Sequencing rule (founder instruction, 2026-07-22): backlog first.** Slice 1 closes the
run-machinery backlog before any new surface is built; slices 2–3 build the toolbelt and the
read side on top of a worker that can actually drive runs.

---

## 0. What B4 closes from the backlog

| Backlog item | Where it closes |
|---|---|
| **[B4×fleet]** per-`(client, icp)` DEEP/VERIFICATION composition inside the detached worker | Slice 1 — `ComposingRunDriver` |
| **[B2×stage0/M6]** Stage-0/scoring fetches run sink-less | Slice 1 — the M5/M6 registration surfaces are born snapshot-wrapped |
| **[B1×M13.2]** resume hook drives a bare `ProjectRun` (no ledger/budget) | Slice 1 — resume converges on the fleet driver composition |
| **[M9.1×M0.4]** `pre_spend_policy` global-NULL-slot uniqueness gap | Slice 1 ride-along migration (+ loader tie-break) |
| B1-wiring residuals: “production must actually pass the lock factory / bind the rubric priority” | Slice 1 — the composer passes both at run start |

Explicitly **not** B4: hard lease fence tokens (multi-worker prod), presign policy gate (no
presign consumer ships here), [B3×research] account localization, journal/recipes (step 5),
agent plane (step 6).

## 1. Design rulings (settled — do not relitigate in implementation)

**D1 — per-run registries, never the process-global singleton.** The phase registry keys
handlers by *phase*, so two concurrent runs with different ICPs on one worker would fight over
the DEEP slot (last-write-wins). `ComposingRunDriver` therefore composes a **per-`(workspace_id,
icp_key, icp_version)` `PhaseHandlerRegistry`** (LRU-cached) and drives a per-run `ProjectRun`
bound to the **shared** stores (`DbProjectRunStore`, `DbIdempotencyStore`, `BudgetEngine`) — the
state machine object is cheap; the durable state is shared. The boot-composable handlers
(REVIEW today) register into every composed registry. `fleet_main` swaps its driver for the
composing one; the empty-boot refusal remains for the degenerate no-composer case.

**D2 — the composer passes everything production was missing.** At composition it reads the run
row (`workspace_id`, `icp_key`, `icp_version`, `tier_cutoffs`) and binds: `storage =
build_storage_backend()`; `lock_factory = build_account_lock_factory()` (eager — the worker runs
inside `redis_lifespan`); `priority_for = tier_priority_from_rubric(run.tier_cutoffs)`;
fleet mode `scheduler = build_fleet_deep_scheduler(...)`; the VERIFICATION handler gets the
settings-built gateway + the per-run account resolver; committee sources bind to the production
set the deep composition already names. Single-flight and rubric priority are thereby **on** in
production, closing the B1-wiring residuals.

**D3 — M5/M6 phases get api-root registration surfaces, born snapshot-wrapped.** New clue_api
wiring (`phase_wiring.py`): build/register functions for `ReverseProfilingHandler`,
`IcpConfirmedHandler`, `DiscoveryPhaseHandler`, `ScoringPhaseHandler`,
`TierCheckpointPhaseHandler` — mirroring the verification/retention wiring style, each wrapped in
the (deliberately phase-generic) `SnapshotBindingPhaseHandler` when `storage` is passed
(required-keyword posture, same as the other registration surfaces). With this, **every phase of
the run sequence is registrable and the composer can drive a full run.**

**D4 — resume rides the fleet composition.** `ProjectRunResumeHook` defaults its driver to the
fleet-composed `ProjectRun` (ledger + budget engine — parity with the worker path; the bare
`ProjectRun()` divergence dies). Fleet deployments resume by **enqueue** (`enqueue_run_drive`);
the slice-2 resume tool uses the enqueue path when a queue is configured, in-process otherwise.

**D5 — toolbelt purity (dependency-inverted like resolvers).** `clue_toolbelt` imports only
`clue_core` / `clue_config` / `clue_db` / `clue_obs` — never research/memory/content/fleet/
gateway/api (machine-enforced, new import contract). It owns: the `Tool` protocol + typed
envelope (name, version, pydantic input model, `preconditions()`, `estimate()`, `invoke()`
returning **references, never blobs**), `PreconditionFailed` (machine-readable `reason_code` +
human message), the registry, the invocation wrapper (log_span per invocation — an unlogged
write is structurally impossible; `actor` stamped human|agent, REQ-20), and the A9 idempotency
store seam. **Concrete tools are constructed and registered at the `clue_api` composition
root** (the only package that may import everything).

**D6 — A9 idempotency.** `tool_invocation` table: `idempotency_key` (unique), `body_sha256`,
`tool_name`, `response_json`, `created_at`. Same key + same body within 24 h → replay the stored
response; same key + different body → `IdempotencyConflict` (HTTP 409). Additive over the domain
idempotency keys (M7.4 ledger untouched).

**D7 — projections reuse the existing readers.** `clue_projections` wraps
`DurableCampaignStateReader` / `CampaignProgress` / the M13.4 `ObservabilitySurface` /
source-yield + verification-health aggregates — no re-derivation. Genuinely new: the **A4
run-manifest projection** (run machine + account graphs → `node_key`/`depends_on`/`status`/
`account_scope`/`gate`/`est_cost`; ops accepted only where the current machine has real
semantics — pause/adjust — everything else rejected 422 with reason) and the **readiness/
coverage projection** (“Surprise me”: what is known/filled vs planned per account/field-class).
Import posture: projections may import research read surfaces + libs; never toolbelt/agents/
fleet/api (new contract).

**D8 — SSE per the treaty summary (REQ-11/A5).** A `run_event` outbox table (workspace-scoped,
monotone `seq`, transactional emit — generalizing the M12.3 `handoff_event` pattern), an emitter
seam the worker/phase surfaces write through, and an SSE endpoint: envelope `{id: seq, event:
topic, data}`, per-workspace ordering, at-least-once + seq idempotence, `Last-Event-ID` replay
(≥ 24 h / 10 k events), `stream.hello` / `stream.reset`, single-use stream tokens
(`stream_token` table). Topics v1: `run.phase.started/completed`, `run.step.progress`
(A6 `timeline_phase` minimal mapping), `run.done`, `stream.*`. Replay is THE de-risk test.

**D9 — A8 quality-mode slot.** The envelope carries `quality_mode: str | None` — recorded and
journaled, **not** yet resolved to knobs (REQ-14 lands later; the slot exists so tool schemas
don’t churn).

**D10 — settings are append-only**: `CLUE_TOOLBELT_IDEMPOTENCY_TTL_S` (86400),
`CLUE_SSE_REPLAY_HORIZON_S` (86400), `CLUE_SSE_STREAM_TOKEN_TTL_S`, plus what slices genuinely
need. Policy as data; no magic numbers at the roots.

## 2. Slices (sequential, one Opus agent each; Fable review after each)

### Slice 1 — the worker drives whole runs (backlog close-out)
1. `clue_api/phase_wiring.py`: M5/M6 build/register surfaces (D3), snapshot-wrapped, storage
   required-keyword.
2. `ComposingRunDriver` (in `clue_api.fleet_wiring` or a sibling module): per-run registry +
   `ProjectRun` composition per D1/D2, LRU cache, structured logs of composed phases;
   `fleet_main` swaps to it.
3. Resume convergence per D4.
4. Migration: `pre_spend_policy` `NULLS NOT DISTINCT` (mirror migration 0009’s slots) + loader
   deterministic tie-break; hash id off current head `814a272f79a5`.
**Exit gates:** (a) a stub-mode run drives `reverse_profiling → … → handoff` **end-to-end
through `ProjectRunWorker` + `ComposingRunDriver`** on a real DB; (b) two runs with different
ICP specs drive concurrently on one worker with no handler cross-talk (the D1 race test);
(c) resume exercises ledger + budget (parity assertion vs the worker path); (d) migration
up→down→up; duplicate global `pre_spend_policy` rows impossible + deterministic load order.

### Slice 2 — the toolbelt (step-2 core)
1. `clue_toolbelt`: envelope/registry/PreconditionFailed/idempotency seam per D5/D6/D9.
2. `tool_invocation` migration.
3. Concrete tools at the api root over the existing capabilities: `reverse_profile`,
   `synthesize_icps`, `confirm_icp`, `import_accounts`, `discover_accounts`, `score_accounts`,
   `submit_tier_checkpoint`, `run_deep_account`, `resolve_committee`, `profile_contact`,
   `run_verification`, `compose_handoff`, `estimate_project` + run controls (`start_project_run`,
   `pause_run`, `resume_run` (D4 enqueue), `adjust_budget`). Each declares real preconditions
   (active ICP exists; scores exist before tiering; tier cutoffs before deep; …) with
   machine-readable codes.
4. Import contract: the toolbelt purity rule (D5).
**Exit gates:** the **out-of-order tool matrix** — every tool invoked on a fresh workspace with
unmet prerequisites raises `PreconditionFailed` with its documented reason code (never a silent
empty success); idempotent replay + 409-on-body-change tests; every invocation emits its
log_span with actor.

### Slice 3 — projections + SSE (read side)
1. `clue_projections` per D7 (+ its import contract).
2. `run_event` outbox + emitter seam + worker/phase emission (D8); `stream_token` store.
3. FastAPI surface (handoff_app style): projection routes, tool-invocation route with
   `Idempotency-Key` middleware (A9 at HTTP), SSE endpoint.
**Exit gates:** treaty SSE replay test (disconnect → reconnect with `Last-Event-ID` → zero gap,
duplicates tolerated by seq); projection reads during a driving worker (no writes, MVCC only);
manifest projection renders a live run; invalid manifest ops → 422 with reason.

## 3. Shared-surface manifest (treaty §3 discipline)
Alembic: one migration per slice, hash ids, sequential (no merge expected). `clue_config`
settings: append-only (D10). Root `pyproject.toml`: toolbelt/projections gain real deps +
two new import contracts. `clue_api`: all concrete wiring lands here (it is the composition
root — that is its job).

## 4. Standing gates (every slice)
`make check` green (incl. both rename guards + structure guards); full DB suite fresh **and**
rerun; `db-smoke` up→down→up single head; scripts/01–06 chain unchanged; the new slice’s exit
gates above; Fable review after each slice, findings fixed before the next opens.
