# 2026-07-22 — §1a stage-2 rename executed: campaign_run → project_run (whole repo)

Branch `platform/workspace-restructure`, immediately after Phase-B integration (gates green),
before B4 — exactly the playbook window (`docs/specs/PB-rename-campaign-run-to-project-run.md`,
now marked EXECUTED). Atomic: one reversible migration + one repo-wide code flip + the
empty-allowlist guard. No aliases, no shims.

## Migration `814a272f79a5` (off head `399633c6e1cb`)
Enumerated against the LIVE catalog (psql information_schema/pg_catalog), not the migration files:
- Tables `campaign_run` → `project_run`, `campaign_phase_checkpoint` → `project_phase_checkpoint`
  (§3f judgment: checkpoint table is run machinery — renamed).
- Types `campaign_phase` → `project_phase`, `campaign_run_status` → `project_run_status`
  (values carry no token — verified).
- `campaign_run_id` → `project_run_id` on 9 carriers: account_run, budget_event, account_handoff,
  handoff_event, review_session, disposition, cost_estimate, adjustment_journal,
  campaign_phase_checkpoint (fleet's run_lease/fleet_task were stage-1-native already).
- 11 token-named constraints + 5 token-named indexes renamed (RENAME CONSTRAINT carries the
  backing index for pkeys/uniques; token-less index names keep their names — defs auto-follow).
- Gotcha 1 (A3.1): `disposition_reject_value_update` (the ONLY function whose body names the
  column — verified via prosrc scan) dropped + recreated over `project_run_id`, with its trigger.
- Gotcha 2: `labeled_dataset` view dropped + recreated (`d.project_run_id AS project_run_id`),
  based on the A3.1-era authoritative SQL (workspace_id form), not the M13.2 original.
- **Frozen:** `idempotency_scope` DB enum values (`account_step`, `campaign_phase`) untouched.
- up→down→up green on throwaway DBs (×2); single head `814a272f79a5`.

## Code flip (libs/subsystems/platform/tests/scripts, *.py)
- Protected sweep: masked the 3 frozen `"campaign_phase"` idempotency-VALUE literals
  (clue_core/enums.py member value; test_beat0_contracts.py set-assertion;
  test_idempotency.py `phase_key` prefix) → seds (campaign_run_status, campaign_run,
  campaign_phase, CampaignRun, CampaignPhase, CAMPAIGN_PHASE, then ATTR_CAMPAIGN_RUN_ID /
  _CAMPAIGN_RUN_IS_A_RUN_DRIVER) → unmask. **Gotcha found live:** test_beat0_contracts.py had a
  SECOND frozen site (`startswith("campaign_phase:")` at line ~204) the sweep flipped — caught by
  the offline suite, restored with an explanatory comment. The `IdempotencyScope.PROJECT_PHASE`
  member now carries the mandatory inline pin (`# value frozen: baked into ledger keys at rest`).
- Module renames (git mv): durable/campaign_run.py → project_run.py, durable/campaign.py →
  project.py (+ `durable.campaign` → `durable.project` path rewrite — NB BSD sed has no `\b`;
  used a char-class guard), tests/durable/test_campaign_{run_db,state_machine,idempotency,
  phase_sequence,budget_gate}.py → test_project_*.py.
- Stage-1 fleet exceptions: already token-flipped by the sweep (both seam sides flip together);
  the 8 `# §1a rename: flips at stage 2` markers deleted; the interim
  tests/fleet/test_rename_guard.py retired (superseded, its pinned counts went to zero).
- **Deliberately NOT renamed (bare campaign = channel program, §1a):** `set_campaign_cap`
  (frozen-core M7.5 protocol), `per_campaign_hard_cap_cents` (config key),
  `CampaignProgress`/`CampaignStateReader` family (M13 review), `BudgetScope.CAMPAIGN`,
  "per-campaign" prose. The guard deliberately does not scan bare `campaign`.

## Guard
`tests/test_project_rename_guard.py`: tokens `campaign_run|CampaignRun|CampaignPhase|
CAMPAIGN_RUN`, allowlist EMPTY, roots asserted present + >400 files scanned (anti-vacuous-scan
check). Lowercase `campaign_phase` deliberately unguarded (frozen ledger value).

## Docs
Harness §1a update line; CLAUDE.md orientation bullet + `[rename]` backlog entry marked DONE
(AGENTS.md resynced identical); PB-rename playbook → EXECUTED; PB-B1 §1a section shrunk to done
(+ its prose flipped).

## Verification
- make check green (mypy 311 files · 21 contracts · offline 1259+1 guard) — and the DB battery:
  db-fresh → upgrade → **2142 passed / 20 skipped**, green again on immediate rerun.
- db-smoke up→down→up on throwaway; `alembic heads` = `814a272f79a5` only.
- Recipe-#1 scripts 01→06 chain completes on the renamed schema by printed hints alone.
- Renamed-schema spot-audit on the smoke DB: 0 `campaign_run_id` columns / 0 old type names /
  0 campaign-prefixed tables; 12 `project_run_id` carriers; `idempotency_scope` values intact;
  guard-function body rewritten.

## Follow-ups
- Fable review of the rename commit (session requirement) — next step this session.
- docs/architecture + older docs/specs still use historical vocabulary in prose (harness §1a
  reading rule covers them; docs are governed separately from the code guard).

## Fable review outcome (post-commit `acfac61`) + fix pass
Reviewer verdict: **no blocking defects** — frozen-ledger invariant machine-verified (runtime
`phase_key` prefix check, DB enum values, zero `project_phase:` expectations anywhere); migration
re-verified up→down→up on the reviewer's own throwaway incl. one-step downgrade name-restore;
guard proven against a planted regression; module renames history-preserving; pure-rename
semantics confirmed on durable/project*.py. Applied from the report:
- **SF-1**: the playbook §4.5 prose flip (74 `campaign run`/`campaign-run` docstring lines,
  all run-meaning; zero channel-program collisions) — done. Gotcha: the prose sed clipped the
  playbook FILENAME inside the guard docstring (`PB-rename-campaign-run-to…` → mangled) — the
  A3.1 gotcha-3 class, fixed by rewording so the filename isn't line-wrapped.
- **SF-2**: docs/specs swept to project vocabulary (tokens + prose; PB-rename playbook excluded
  — it documents the rename; the one frozen-value mention in PB-B1 stays);
  `M8A-campaign-run-deep-orchestration.md` → `M8A-project-run-deep-orchestration.md` with all
  refs (specs README, 11 _memory notes) fixed. The M12 spec's handoff route now matches the
  code's `/project_runs/{project_run_id}/handoffs`.
- **N-1/N-2**: guard hardened — resolved-path self-exclusion; `campaign_phase_checkpoint`
  added to the pattern (old table name; cannot collide with the frozen value).
- Declined (recorded): N-3 stale index attnames (cosmetic pg_attribute residue — expected for
  future catalog audits); N-4 `CampaignStateReader`/`CampaignProgress` stay per the bare-campaign
  ruling (latent §1a debt only if the ruling is ever revisited).
Final gates after fixes: make check green (1260 offline incl. guard); DB suite 2143 passed.
