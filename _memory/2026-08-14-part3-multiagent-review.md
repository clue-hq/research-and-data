# 2026-08-14 — Part III multi-agent adversarial review (4 Opus reviewers + Fable) + live API smoke

Live smoke: design creation via API endpoints only — PASSED end to end (design API on
:8371, embedded worker, riyadh DB; POST /agent/turns → trio (terra/terra/opus-4.8 via
platform gateway, 42 role-tagged calls, reviewer-accepted round 1) → 1080×1080 navy
launch artboard, preview.png rendered; run_d24a9beffe…). Two env facts: the design
runtime needs LUMEN_AGENT_API_KEY explicitly (CLUE_OPENROUTER_API_KEY does NOT flow
through — first attempt failed loudly on it; the P3.2 follow-up "document the design
env" is still open), and X-Workspace-Id is required (B3 guard confirmed live).

## Verified findings (Fable-confirmed where marked ✓; ordered by action priority)

1. ✓ **BRANCH RED**: `tests/api/test_journaled_invocation_roots.py` fails — P3.7b's
   `build_design_leg_finisher` calls bare `invoke_tool` (design_leg_wiring.py:223).
   Bypasses C5.1 journaled-invoker discipline (no invocation journal/param snapshot;
   the A9 idempotency comment is wrong — no store passed; convergence actually rests on
   the tool's own journal replay, which holds). Fix: route through the production
   ToolInvoker (available at the same fleet_main call) or the sanctioned pattern.
2. ✓ **Exit bridge inert in production** (engine HIGH-1): the live judge gets
   LangChain Responses list-of-blocks content; `str(list)` never parses → permanent
   fail-safe CONTINUE. Fix: extract text blocks (repo precedent
   entity_research_runtime._tool_message_text); add live-judge test. Also LOW: no
   role= on models.build (unattributed spend); temperature 0 vs policy note.
3. ✓ **Finalize replay poison** (engine HIGH-2): `finalized_at=datetime.now()` in both
   design finalize envelopes vs derived finalization_id → crash between
   record_finalization and commit_finalization_authority → every retry raises
   "different immutable envelope"; turn stuck running. Fix: submission.requested_at
   (the head-of-abm precedent, agent_runtime_wiring:1119).
4. **Thread-wedge on design-disabled deployment** (wiring HIGH-1): open_design_leg is
   live (storage-gated only) with chat_enabled=True/design_runtime_enabled=False; a
   model delegation opens a leg no lane can serve; mark_running precedes lane.drive →
   leg stuck 'running'; no reaper (same switch). Fix shape: build_design_leg_tools
   gains enabled= (build_design_tools precedent) + refusal design_leg_runtime_not_configured.
5. **Brand pin TOCTOU** (design-side H1): the P3.7c gate verifies on one connection,
   but resolve_agent_turn_brand_kit later re-reads on another and its except returns
   None → silent platform-default-kit design on transient failure. Fix: resolve once,
   pass by value (or required=True re-raise mode for pinned turns).
6. **No failure containment after mark_running on the design lane** (engine HIGH-3):
   any raise leaves agent_turn 'running' forever + no terminal SSE frame (pre-existing
   lane-D shape made much more reachable by Part III's three new throw sites). Fix:
   BaseException → mark_unfinalized wrapper (DurableDeepAgentTurnRunner precedent).
7. **Retry history self-pollution** (engine MED-4): prior_history loaded before the
   user append includes this turn's own message on retry → envelope drift vs frozen
   payload + judge input drift (couples with MED-5 judge re-run divergence: a retry
   can orphan a completed design run by exiting instead). Fix: exclude
   message_id=uuid5(turn,"user")/filter turn_id, or load before create.
8. **_join_terminal can park the single worker slot 30 min** (engine MED-6): requeue
   ignored by inline lane; reaper re-offers into the queue the blocked worker drains.
   Rethink: shorter join timeout + honest failure, or requeue-aware lane.
9. **Exit-turn replay double-summary** (engine MED-7): _project_committed appends
   uuid5(turn,"assistant") on replay of an exit turn (live path appended none). Fix:
   skip append when journal names this turn as closer, or derive-id match.
10. **Close not fully atomic** (engine MED-8): DbAgentHistoryStore.append opens its own
    txn inside the finish tool → orphan summary message if outer txn rolls back
    (phantom lock-in text in leg transcript). Fix: append via the same conn.
11. **Speaker projection only on list_threads** (wiring MED-2): /projects/sidebar wire
    has no speaker field; create/update return speaker=None. Part IV contract item.
12. **finish_design_leg DESIGN grant is inert/fictional** (wiring MED-3 + authority
    MED-1): the design runtime has no path to the tool; profile stamps 50-tool
    provenance on design turns. Needs ruling: either the bridge is THE sanctioned
    invoker (record it: authority HIGH-2 spec silence — §2.2 "design orchestrator
    only" vs platform-side pre-dispatch judge — needs a dated amendment + the
    routing-rule third input (closed-by-turn fallback) needs its amendment sentence),
    or a future design-side bridge restores the grant's truth.
13. **Non-turn-terminal stream hangs** (wiring MED-1): unhandled turn-body exception
    emits no terminal frame; prune can never collect that turn's frames (couples w/ 6).
14. Design-side MEDs: version-less/str-version brand pin edge (M1); document_version
    guard enforced by nobody (M2); unbounded leg history O(N²) + no context ceiling
    (M3); web-doc pinned → scene harness mismatch, silent fresh-scene (M4); failure
    summaries drop the refusal reason ("Design turn failed." — M5); one-clarification
    guard inert (M6, spec-acknowledged zero senders); fence-token breakout in both
    renderers + leg prompt lacks the SECURITY clause its docstring claims (M7 → golden
    adversarial fixtures + token stripping); regression gate compares counts not
    failure-name sets & fail_safe kind constant (M8). Authority MED-3/4: signature
    (pending_user_message derived not passed — safer, record it) and summary_refs
    thinner than master plan (no accepted_ops/open_gaps). Delta-4 canvas selection
    (target_node_ids/active_page_id) has NO end-to-end path (authority MED-5) — Part
    IV blocker to note. LOWs: leg.closed payload lacks redelivered_turn_id; double
    design-handler composition; ambiguous-02 fixture vs tie-break phrasing; L2-L4
    design-side; engine LOW-10/11/12; latent mid-run finish finalize shape.

## Cleared by review (load-bearing)
Storage reaches leg tools at all prod roots; recipe v7 seeded/promoted/enforced live;
profiles pins==grants boot-enforced; single alembic head, reversible downgrades; C6
audit intact; routing three-way branch transactionally consistent + gate-answer/
closing-turn structurally disjoint; envelope JSON round-trip clean; claim refs leak no
values; finish idempotency independent of toolbelt TTL; heartbeat math sound; no
mark_leg_running/create_run crash window; §2.4 scoping genuinely wired both sides.

**Disposition: ALL FINDINGS OPEN — assessment only, no fixes applied (user directs).**
Priority order for the fix pass: 1-3 (red gate + inert bridge + replay poison), then
4-6, then the MED ledger. Design API server from the smoke left running on :8371
(background task; dies with session).
