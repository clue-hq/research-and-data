# 2026-09-29 — stuck "Queued" design leg: three defects, fixed

Symptom: a LinkedIn-ad ask opened a design leg; the chat sat on "Queued", no design run.
Diagnosis (DB journal + Langfuse trace; py-spy needs root on macOS, not required in the end):

1. `read_account_research` (overview) read ONLY the legacy display lane (`display/blocks.py`
   `_LIVE_SQL`: `context_id IS NULL`), so every current-lane (ARV2 quality) overview was
   invisible → `overview_not_written` for Albany although its page existed since 22:36.
   Fix 13f1df084: read via `select_quality_context` + `quality_pages.read_page` first, legacy
   only when the account has no current-lane research; project from new optional
   `ToolContext.project_id` (set by the recipe executor from the execution's project and by
   `design_platform_reads` from the leg); none → the account's only project.
2. The refusal is journaled `node.blocked` (terminal in the journal), but the recipe drive loop
   counted only completed/recovered as settled → after `_complete_recipe` the blocked
   interaction child was re-dispatched forever (~15/s), refused as a replay (no action_ref),
   swallowed by `_execute_node` → fleet task held forever, thread starved.
   Fix d6b7579c0: blocked interaction children (compatibility_node_key = a gate) settle;
   a dispatch pass writing no event fails the execution `node_dispatch_made_no_progress`;
   `_complete_recipe` drives with `turn-action:<turn>` authority.
3. Found while unsticking: the retried leg-OPENING turn was routed to the leg runner ("turn id
   already exists with different immutable inputs"). Fix 761942996: opener stays head-of-abm.

Unstick: the stuck worker ignored SIGTERM (graceful shutdown waits on the looping task) —
killed that PID only; reclaim failed on defect 3 but the thread moved on and the design run
started. Residue: execution 3ff91589 (turn 4adb34f2) stays `running` (harmless).
Workers NOT restarted after 761942996 (design run was live) — restart when idle.

Sweep (legacy residuals / same bug class): no other work-dispatch loop lacks a no-progress
guard (fleet workers + project state machine already have one). Agent read tools otherwise
read ARV2 tables. Legacy tools still granted to head-of-abm v67 (need a profile bump to
remove; founder decision): get_research_view (project_run/account_run), draft_account_research_
directive + open_directive_confirmation_gate (legacy directive lane). Delegation grants
(run_verification/compose_handoff) unreachable (no child runner in fleet). Chat still polls the
legacy `/research-tasks` feed once per thread load (harmless).
