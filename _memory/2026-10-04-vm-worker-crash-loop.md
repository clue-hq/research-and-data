# 2026-10-04 — Every VM fleet worker crash-looped after the release deploy

Release #94 (63acfc644) deployed to the worker VM at 07:12 UTC. All five fleet workers (chat, design,
batch1-3) then restarted ~177 times each, so chat turns sat "Queued". `deploy.sh` reported success.

Cause: every fleet worker boots through `build_agent_workspace_factory` → `WorkspaceRootPolicy.prepare()`,
which requires every entry of CLUE_AGENT_WORKSPACE_ROOT (/srv/clue/workspaces) to be a private 0700
directory. deploy/vm/compose.yaml had put the design agent's root INSIDE it
(LUMEN_AGENT_WORKSPACE_ROOT=/srv/clue/workspaces/lumen-agent, deliberately — an old compose test even
required it). The design agent created that directory on first use (2026-10-03 20:14) with the default
umask → 0755. Workers that started before then never re-audited; the deploy's restart hit it.
Locally the two roots were never nested (lumen root unset → in-repo .deepagent-workspace).

Unblock (founder-approved): `sudo chmod 700 /srv/clue/workspaces/lumen-agent` at 07:56 UTC; all five
workers up, 0 errors since, and the queued agent_turn was claimed at 07:58:39.

Permanent fix (branch fix/vm-design-workspace-root):
- compose: LUMEN_AGENT_WORKSPACE_ROOT=/srv/clue/lumen-agent, its own bind mount (workers + ingestion).
- deploy.sh: (1) runs the workers' real boot check with the NEW image as UID 1000 before anything
  restarts — refuses with the error, old workers keep running; (2) always prepares
  /srv/clue/lumen-agent (UID 1000, 0700) in a root container (clue is UID 1001 and cannot chown;
  Docker would create a missing mount source as root); (3) one-time move of the old nested dir with
  the fleet stopped first (an old worker could otherwise re-create it 0755); (4) after `up`, compares
  restart counts across CLUE_DEPLOY_HEALTH_WAIT_S (default 45 s) and FAILS the deploy on any rise.
- bootstrap.sh creates /srv/clue/lumen-agent; the policy refusal now names the offending entry.
- Verified on the VM with the production image: the boot-check command exits 0 on the real root and
  1 on a throwaway root holding a 0755 entry; root containers have install/cp; the probe sees the old dir.
- Owed: the first deploy after merge performs the one-time move (stops the fleet ~60 s grace).
