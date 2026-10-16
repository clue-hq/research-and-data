# 2026-10-16 — site-turn durability (K4-1, K4-5) on branch site/publish-durability

Plan (founder-approved): docs/superpowers/plans/2026-10-16-site-turn-durability.md. Ledger + task reports:
.superpowers/sdd/2026-10-16-site-turn-durability/ (git-ignored).

## What shipped (commits after 71ff008bd)
- Fleet leases: generations never repeat (release ends the row, keeps it; revoke bumps), a lapsed lease nobody took is
  renewed by its holder, per-process inline-lane worker id, daily prune of month-old ended rows (orphan-sweep clock).
- Design runs: equality fence on results/emits; re-offer keeps the stamp; site save fenced (run row + work lease,
  FOR SHARE, same tx), one save per run, idempotency key per attempt.
- Takeover continues: working copy per running turn (design_site_turn_workspace, migration d20a3b374a89), written at
  the first round and re-stamped every round, durability="sync", resume from the copy's checkpoint, per-attempt folders,
  pruned (copy + checkpoints) at every terminal write.
- Deploy drain: no new claims after SIGTERM, running work finishes; CLUE_FLEET_DRAIN_BOUND_S=600 then site turns drain at
  a step boundary (TurnDrained/WorkDrained) and requeue; compose chat/design stop_grace_period 11m.
- Session files: one versioned copy per site (design_site_session, migration db05b93f7377), CAS save, zombie fenced,
  local copy mirrored only after the CAS lands.
- Hand-back: unchanged turns say so; a takeover after the run's own save reports that version (one history entry).

## Verification
- Named test files on throwaway DBs clue_t7_fresh / clue_t7_verify (founder-approved): fleet 117 green; site scenarios 38;
  only pre-existing reds (p36 fresh-worker, fleet_wiring discovery flag, asset_upload/ingestion_pool hostname FK, p37).
- Migrations up/down/up OK, one head; lane DB clue_trenton migrated to db05b93f7377 (2026-10-16).
- LIVE (lane, 2026-10-16 20:27): run_site_ff6137521310 on the Garner Syracuse site. Embedded design-API worker took it
  (g1); SIGKILL at round 3. Fleet worker took over at g2, resumed at the round-3 checkpoint
  (site_turn.resumed_from_working_copy), 3 calls done + 5 by the takeover (only the in-flight call redone), saved v12,
  one envelope, session row v1, checkpoints and copy pruned. Cost: 8 model calls.

## Open / residual
- Drain (SIGTERM path) proven by tests only, not live.
- The dead attempt's model calls are not on the run's result_json receipts (in its own logs/traces only).
- Zombie checkpoint rows can survive a prune; a month-pruned lease row restarts at g1.
- test DBs clue_t7_fresh / clue_t7_verify still exist on clue-pg-trenton (drop when done).
- Never run the clue-design apps/api tests folder (7–8 h); named files only.
