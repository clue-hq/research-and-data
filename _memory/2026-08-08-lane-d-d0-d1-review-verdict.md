# 2026-08-08 — Lane D D0+D1 orchestrator review verdict (Fable adversarial review)

## Verdict: both slices ACCEPTED

D0 (commits `f92fe1d7`, `49d7b7a5`, `d941c6f6`, `71fde4bd`) and D1 (`5528e634`, `e024833a`,
`9dab17e7`) reviewed against their briefs + charter ACs. Independently verified (not just agent
claims): combined suite run on the dedicated damascus DB (localhost:55040, merged head
`a21c4d290eb7`) = **136 passed, 1 failed**, the failure being
`test_agent_registry_wiring.py::test_resolved_snapshot_materializes_through_c61_backend` —
**proven pre-existing** by reverting `toolbelt_wiring.py`/`agent_registry_wiring.py` to
`68f358a0` and re-running (fails identically; `WorkspaceSecurityError: workspace parent
directory does not exist` — C6.1 skill-resource materialization, unrelated to Lane D).

Key files hand-reviewed: the D0 migration (excellent: named constraints, composite workspace
anchors, NOT VALID grandfathered FK, honest nullable ownership + membership⇒user CHECKs, index
matches `get_onboarding_input_for_artifact`'s exact predicate incl. DESC ordering),
`chat/principal.py` (startup refusal outside local_header mode; dev ids from settings never
headers; spend permissions absent), `turn_action.py` (canonical-UUID anti-aliasing; workspace
scope in SQL; no existence leak; 8 stable reason codes; pure-read replay safety),
`ensure_platform_thread`, the L6 inversion (retention newest-first for L6 only, emission
chronological, greedy-skip + required-failure semantics preserved).

## Accepted deviations (all well-reasoned by the agents)

- `agent_thread.created_by_user_id`/`created_via_membership_id` and `agent_turn` submitter
  columns are NULLABLE (brief said NOT NULL): trial/fleet/delegation turns have no human
  submitter and fabricating one violates Lane B ruling 8. The turn journal now auto-provisions
  shell thread rows (creator-less) which is what makes the NOT VALID FK enforceable.
  D1's resolver refuses NULL-submitter turns, so receipts stay deny-by-default.
- Thread tools are WRITE not STEERING (C6 audit refuses granting steering tools to any role;
  REQ-21 needs agent-managed threads). Disclosed-and-refused (`ROLE_UNAVAILABLE`) on existing
  surfaces rather than hidden — matches loud-preconditions doctrine; registry can only withhold
  profile-pinned tools anyway.
- `agent_thread_message` gets no own FK (integrity rides its composite FK to `agent_turn`).
- Route-scoped error envelope (frontend_read owns the app-level handlers).

## Follow-ups (owner: next Lane D briefs)

1. **[minor, real] `ensure_platform_thread` cross-project attach:** `ON CONFLICT (id) DO
   NOTHING` means a turn whose thread id already exists in the SAME workspace but a DIFFERENT
   project silently attaches to that other project's thread (cross-workspace fails loud on the
   FK). Server-minted ids make this near-impossible accidentally. Fix: after conflict, verify
   the surviving row's (workspace_id, project_id) and raise on mismatch. → fold into the
   B1-FK-join follow-up slice.
2. **B1-FK-join slice** (now unblocked, B1 cherry-picked as `9269ff3e`): FKs from
   `agent_thread`/`agent_turn` ownership columns to `platform_user`/`workspace_membership`;
   back the dev principal settings with real provisioned fixture rows (contract §4: even a dev
   adapter resolves a real user/membership from Postgres); decide when
   `created_via_membership_id` becomes writable (needs Lane B B4's ToolContext membership seam).
3. **9 thread-contract deviations** from D0's report await founder review before anyone records
   them into `api-contracts/projects.md` (notably: per-thread rename/pin/archive vs the doc's
   per-project shapes; new paginated `GET .../threads`; `meta.next_cursor` pagination; thread
   status `idle|archived` only until D2/D4; body-free message reads).
4. `HistoryLayerSource.load` reads every message body before the budget drops most (pre-existing
   N-read inefficiency; windowed loader when D2/D3 make long threads routine).
5. Pre-existing failing test above — belongs to C6.1 owners, not Lane D.

## Incidents (orchestrator, resolved)

- My compound command ran bare `git stash` + `git stash pop`; with nothing to stash, the pop
  applied a STALE pre-existing stash (stash@{0}, B3-era WIP) and conflicted across ~30 files.
  Fully undone with `git reset --hard HEAD` (tracked tree verified identical to HEAD
  beforehand). Both stash entries preserved for the founder to inspect/drop:
  stash@{0} "WIP on research/b3-account-workspace-localization", stash@{1} m13.1-era.
  **Lesson: never pop without checking `git stash list`; use `git stash push` + explicit ref.**
- Fixed lint on my alembic merge revision (template's unused imports) — `23089c46`.
- Environment trap (recorded for future sessions): localhost:5432 is a FOREIGN native Postgres;
  this worktree's dedicated DB is the `clue-pg-damascus` container on localhost:55040.

## State

Branch history through `23089c46`; single alembic head `a21c4d290eb7`; dedicated DB at head;
D0+D1 charter ACs met (D1's production caller arrives in D2 by design). Next: founder rules on
the 9 contract deviations; then brief D2 (AGENT_TURN async execution) — the largest remaining
gate to the kickoff flow — plus the small B1-FK-join slice (items 1+2 above).
