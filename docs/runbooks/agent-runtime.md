# Platform agent runtime operations

**Applies to:** C6 Head-of-ABM Stage 0, fresh-wake specialists, and governed per-account
research. The runtime is default-off in production until an operator admits a workspace.

## Deployment prerequisites

1. Apply the single Alembic head before enabling routing.
2. Configure `CLUE_AGENT_WORKSPACE_ROOT` as an absolute, private directory outside the source
   worktree, service-user home, durable artifact root, and shared temporary directories.
3. Configure the OpenRouter secret. Production composition fails before model spend if the
   workspace root, catalog, tool authority, model policy, or secret is invalid.
4. Keep the master and both surface switches off for the first deployment:

   ```text
   CLUE_AGENT_RUNTIME_ROUTING_ENABLED=false
   CLUE_AGENT_STAGE0_ROUTING_ENABLED=false
   CLUE_AGENT_ACCOUNT_ROUTING_ENABLED=false
   CLUE_AGENT_WORKSPACE_ALLOWLIST=[]
   CLUE_AGENT_CANARY_PERCENT=0
   CLUE_AGENT_ACCOUNT_PLAN_BUDGET_LIMIT_MILLICENTS=1000000
   ```

The runtime workspace is ephemeral. Durable artifact storage and Postgres remain authoritative.
No application code, executable tools, credentials, absolute host paths, or mutable resource
bodies belong in an agent execution root.

## Ownership and rollout

Routing is evaluated only when a `(workspace, surface, subject)` is first claimed. The durable
`agent_runtime_route` row then freezes `legacy` or `deepagent` ownership for that subject.
Configuration changes never steal in-flight ownership.

Use this sequence:

1. deploy with the master switch off and verify registry/turn reads;
2. enable the master plus one surface;
3. add one internal workspace to the JSON-array `CLUE_AGENT_WORKSPACE_ALLOWLIST`;
4. run the corresponding Stage-0 or account-research canary;
5. compare terminal coverage, promotable and verified refs, cost, rounds, duplicate effects, and
   visible failures against the mechanical baseline;
6. add further allowlisted workspaces;
7. only after the allowlist is healthy, set a small deterministic percentage.

The percentage cohort hashes `workspace_id + surface`; it is stable across restarts. A selected
deepagent error does not fall through to legacy. That error must remain visible, otherwise a retry
could create effects under two owners. Disable a surface to stop assigning **new** deepagent
subjects; existing route rows retain their owner and resume through the same path. The fleet
therefore continues composing the account runtime while any durable account route is owned by
`deepagent`, even after the rollout switches are reduced.

For an admitted account, the fleet prepares `account-research-unit@1` under a deterministic
execution/turn identity, freezes stage/readiness/budget/input/resource receipts, assembles the
account role's exact L1–L7 fresh-wake context, and uses the same governed gateway, toolbelt,
RecipeExecutor, coverage ledger, and DEEP scheduler as the mechanical path. The plan budget is
clamped to both `CLUE_AGENT_ACCOUNT_PLAN_BUDGET_LIMIT_MILLICENTS` and the durable account envelope.
A completed turn closes the C5 interaction gate; a crash resumes the same checkpoint and audited
workspace. Frozen bytes are re-hashed before model execution resumes.

## Read surfaces

All routes require workspace authentication and return body-free references:

- `GET /agent/registry`
- `GET /agent/projects/{project_id}/turns`
- `GET /agent/turns/{turn_id}`
- `GET /agent/turns/{turn_id}/progress`
- `GET /agent/turns/{turn_id}/telemetry`
- `GET /agent/routes/{stage0|account_research}/{subject_id}`

The turn view exposes status/failure, pinned profile and resource digest, context receipt,
artifact refs, and delegation ids. It never exposes prompt/skill bodies, model input/output
bodies, agent-workspace host paths, or erased content. Cross-workspace reads return not-found.

## Telemetry and alerts

The telemetry projection reports:

- input/output and cache-read/cache-creation tokens, model cost, and latency;
- tool-result count and durable reference yield;
- assembled context tokens and excluded refs;
- final workspace files/bytes and quota utilization;
- delegated-child spend;
- unfinalized failed/abandoned events;
- terminal-workspace cleanup receipts.

Alert on:

- an unfinalized failed/abandoned turn;
- duplicate effects or canary regression;
- sustained high context exclusion;
- workspace quota utilization above the chosen operational threshold;
- cleanup-loop errors or terminal roots with no cleanup receipt after retention plus two cadences;
- a model-cache ratio drop after a profile/prompt/history change;
- a surface assigning deepagent ownership while its intended switch is off (inspect the immutable
  route receipt first; it may legitimately predate the switch change).

## Cleanup and recovery

Since F3 (`docs/superpowers/specs/agent-workspace/`) a chat's agent folders live durably as a
versioned snapshot and a worker's disk is only a cache, so there are two cleanups and they do
different jobs. The old turn-keyed `AgentWorkspaceCleanupJob` and its
`CLUE_AGENT_CLEANUP_INTERVAL_S` cadence are gone; folders left by the layout that preceded it are
removed once with `scripts/remove_legacy_agent_workspaces.py` (dry run by default).

**The per-worker cache sweep (Phase 1) deletes nothing durable.** Each fleet worker owns one area
under `CLUE_AGENT_WORKSPACE_ROOT` and checks it every
`CLUE_AGENT_WORKSPACE_CACHE_SWEEP_INTERVAL_S` (300 s). A chat folder unused for
`CLUE_AGENT_WORKSPACE_CACHE_IDLE_S` (30 min) is removed, and once the area passes
`CLUE_AGENT_WORKSPACE_CACHE_MAX_BYTES` (10 GiB) idle folders go oldest first; the chats this
worker is running are never swept, and a worker wipes its whole area at start-up. The next turn
restores the chat from its snapshot, so a sweep costs a download, never a file.

**The retention job (Phase 2) is what actually expires files**, fleet-wide, once per
`CLUE_AGENT_WORKSPACE_RETENTION_SWEEP_INTERVAL_S` (86400 s) with one runner at a time behind an
advisory lock and a `maintenance_run` row (`agent_workspace_retention`). For a chat nothing has
touched for a while — the newest of its snapshot stamp and its newest submission — it publishes one
new snapshot version with the due entries marked expired: raw inputs (`reads/`,
`work/conversation_history/`, `work/large_tool_results/`) after
`CLUE_AGENT_WORKSPACE_RAW_RETENTION_S` (48 h), the agent's own working files (`scratch/` and the
rest of `work/`) after `CLUE_AGENT_WORKSPACE_WORKING_RETENTION_S` (7 days), and `outputs/` never —
it is kept for the chat's life. An expired entry keeps a receipt saying what the file was and how
to get it again, and the save releases its key, so the bytes are erased and purged from storage
when no other snapshot holds them. A chat with a queued, claimed or leased turn is skipped and
left for the next pass. Set either window or the interval only with the founder's agreement: they
are what the agent manual promises the agent in words.

**What to watch when retention stops.** Each pass logs `fleet.workspace_retention.ran` with
`chats_checked`, `chats_expired`, `files_expired`, `skipped_busy`, `stale` and `failed`. A chat
the pass cannot read or save — most often a manifest blob the rows still name but storage has
lost — is logged as `agent_workspace.retention.chat_failed` with its workspace and thread, and
counted in `failed`; the pass carries on. So a chat broken for good shows a non-zero `failed`
every day: **alert on `failed > 0` persisting**, and on `fleet.workspace_retention.ran` not
appearing for more than two intervals. The second case means the pass itself is raising
(`fleet.workspace_retention.error`) — and a pass that raises deliberately does *not* record its
`maintenance_run` row, so the fleet simply retries it on the next check rather than skipping a
day. Nothing is lost by a failed pass; files that should have expired expire late.

**Measured timings (final live check, dushanbe stack, 2026-10-24 UTC).** One chat with 4 files
(69,194 bytes): the first save (version 1, 4 files uploaded) took 968 ms; after the whole
`CLUE_AGENT_WORKSPACE_ROOT` was deleted and every worker restarted, the cold restore (4 files
downloaded, 69,194 bytes) took 583 ms; an unchanged save took 5–10 ms; restoring a chat with no
version yet took 4 ms. After expiry the chat held 1 file (19 bytes) and restored in 348 ms and
370 ms. The expiry of 3 files (version 1 → 2, bytes erased and purged from R2) took 1.5 s. A warm
restore (this worker already holds the current copy) downloads nothing: 2 ms in the Phase 1 live
check. Read these as the order of magnitude for a small chat, not as a budget.

**Snapshot log lines to alert on.** Each is a `warning` carrying the workspace and thread (or the
keys) it concerns:

- `agent_workspace.save_unavailable` — storage could not be reached after the save's retries; the
  turn fails, the worker keeps its copy marked unsaved, and the chat's next turn saves it. **Alert
  on a sustained rate**: it means R2 trouble.
- `agent_workspace.save_refused` — a save was refused (`status` says why: `stale`, another writer
  saved first and the rebase could not apply, or `fenced`, the turn lost its lease). An occasional
  one is a zombie or a lost race doing what it should; **alert when one chat repeats it** or the
  rate climbs.
- `agent_workspace.release_save_failed` — a turn that stopped or failed could not save on its way
  out, so what it wrote since the last save is not in the chat's snapshot and a turn on another
  worker will not see it. **Alert on any.**
- `agent_workspace.purge_failed` — deleting erased bytes after a committed save failed. The turn
  is unaffected and the fleet's orphan sweep deletes them later; **alert only if it persists**.
- `agent_workspace.retention.chat_failed` — see above; alert when `failed > 0` persists.
- `agent_workspace.retention.claim_not_released` — a retention pass that raised could not release
  its claim, so no other pass starts until the claim is 6 hours old. Nothing is lost; **alert if it
  repeats**, and look for the `fleet.workspace_retention.error` beside it.

**The emergency switch (`CLUE_AGENT_WORKSPACE_SNAPSHOTS_ENABLED=false`).** Use it only when
snapshots themselves are the problem (storage down for a long time, a snapshot bug). Set it and
restart the workers. Each snapshots-off worker then runs every chat from one shared folder,
`<root>/local`, holding a shared lock on `<root>/workers/local.lock` for its whole life; turns
neither restore nor save, so a chat starts there **without** its saved files (its `outputs/`
included) and whatever it writes stays on that machine's disk only. The saved versions are left
exactly as they were. To turn it back on, set `true` and restart the workers: every chat restores
its last saved version on its next turn, and **everything written while the switch was off is
lost** — by design, it was never saved. Nothing needs cleaning by hand: a snapshots-on worker
removes `<root>/local` as soon as it can take that lock exclusively, i.e. once no snapshots-off
worker is alive — at its area claim and again on each cache sweep. During a rolling restart the
folder can outlive the restart for a moment while the old workers exit (seen in the live check);
it goes at the next claim or sweep.

DSAR is separate and stronger: it tombstones and erases subject-bound durable bodies, blocks
resurrection, marks affected turns unreplayable, and removes matching live workspaces immediately.
Retention cleanup must not be used as a substitute for DSAR.

For recovery:

1. inspect the turn, progress, telemetry, and ownership receipt;
2. leave the route row unchanged;
3. resume/retry through the durable C5 execution identity;
4. confirm the failed turn remains visible and no second owner ran;
5. if the problem is systemic, disable new assignments and preserve the affected root through the
   inspection window.

## Rollback

Turn off the master switch to return all **new** subjects to current mechanical behavior. Do not
edit or delete route receipts to force a fallback. Finish or explicitly fail existing deepagent
subjects under their recorded owner. Application rollback is safe while the additive C6.8 tables
remain; schema downgrade is only for a controlled full rollback after agent processes are stopped.
