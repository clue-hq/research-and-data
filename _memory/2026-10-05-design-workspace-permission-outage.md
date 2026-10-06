# 2026-10-05 — Design runs failed for ~27 h: root-owned design workspace after release #97

Symptom (co-founder, prod thread thr_89c5f649, 2026-10-05 00:26 + 00:47 UTC): "Design stopped before completion",
twice; the strategy agent then claimed the page "was never generated". Both design_agent_run rows (web_turn):
`Failed to materialize agent workspace at /srv/clue/lumen-agent … [Errno 13] Permission denied:
'/srv/clue/lumen-agent/.materialize.lock'`, 5–7 s, no model calls. Only these two design runs happened in the
window; the first after the 2026-10-05 15:21 deploy succeeded. VM worker logs from then were lost (containers recreated).

Root cause: #96 moved LUMEN_AGENT_WORKSPACE_ROOT to /srv/clue/lumen-agent and added deploy.sh steps to create it
(UID 1000, 0700). CI's VM step runs ci_deploy.sh → deploy.sh from the VM checkout BEFORE the new commit is
checked out, so #97's deploy (2026-10-04 12:28) ran the OLD deploy.sh (no preflight/prepare/move/health check;
log printed `deployed` immediately) with the NEW compose.yaml, whose bind mount made Docker create the missing
dir root-owned. #101's deploy (2026-10-05 15:21) ran #96's deploy.sh → prepared + moved → fixed.

Fixes (branch fix/deploy-self-update-design-failure-reason):
1. ci_deploy.sh fetches + checks out the requested sha first, then execs THAT deploy.sh (a failed checkout deploys
   nothing). Takes effect from the release AFTER this one (the VM runs the old ci_deploy.sh until then).
2. deploy.sh proves UID 1000 can write /srv/clue/lumen-agent (touch+rm in a one-off container) before any
   stop/move/up; refuses otherwise. Verified on the VM with the prod image: real dir → 0, root-owned dir → 1.
3. Failure reason: a turn whose every run failed before generating (model_calls == [] + diagnostic code) fails as
   `design_leg_runtime_failed` (frontend: "Design couldn't start because of a problem on our side. Nothing was
   generated — send your message again to retry."); the warning log carries the runs' diagnostic codes + hints;
   the leg exit summary (all head-of-abm sees of a closed leg) appends `design_run_failure_note` for the leg's
   latest run (codes only — never the hint's paths/errno).
Verified: new tests RED→GREEN (ci_deploy 2, deploy 2, failure note 4, leg engine 1, exit bridge 1, frontend 1);
tests/deploy 51, design-leg API suites, frontend projects 334/334; ruff/mypy clean.
