# W5 acceptance defect repairs — R2-B, R2-C/D2, R2-D (2026-08-26)

Isolated worktree off `integration/frontend-design-part-iv-v4` @ `63332169d` (contains
`587f809df`). Worktree was stale at `5ea7a8791` (a PR-42 merge) and was `git reset --hard`
to the branch tip before any work; nothing was stashed. Evidence for all three defects:
`.context/w5-apollo-e2e-report.md` §6 and §R2.

Three local commits, one per defect. Nothing pushed.

## R2-B (critical) — the distiller could be keyless on a stock checkout

**Root cause is one level below the lane.** `distill.py` reads `settings.openrouter_api_key`,
which is what *every* design-side OpenRouter caller reads (describer, brief agent, ingestion
assist, PDF vision, and `ad_runtime`'s style-group matcher). That field resolved
`OPENROUTER_API_KEY` only. The platform half of the repo namespaces the same secret as
`CLUE_OPENROUTER_API_KEY` (`clue_config.Secrets`, `env_prefix="CLUE_"`). Repo-root
`.env.example:222` bridges them by shell reference, but a `.env` written before that line
landed leaves the whole design subsystem keyless — so the distiller wrote no card,
pre-generation had nothing to anchor on, and the job still said `succeeded`.

**Fix:** declared `clue_openrouter_api_key` in `py_lumen_config.Settings` plus a
`model_validator(mode="after")` that fills `openrouter_api_key` from it when that is unset or
blank. One shared resolution in the settings package, not at any call site. Blank counts as
absent (matches the existing `_blank_is_unset` convention) so a half-migrated `.env` cannot
shadow a real platform key. `.env.example` comment updated: the bridge line is now
belt-and-braces, not load-bearing.

Rejected: a `validation_alias`/`AliasChoices` on the existing field. It works, but a blank
`OPENROUTER_API_KEY=` still shadows the platform key (proven by probe), and a hidden alias name
breaks this module's stated promise that every env var Python reads is declared in it.

## R2-C/D2 (high) — `succeeded` hid empty harvests and skipped steps

**Founder-side framing honoured:** an empty harvest is NOT an error (D5, no gates). The job row
enum is untouched — no migration, no `DesignIngestionStatus` change, no parity-test change.
(Checked the blast radius of adding a value: 9 touch points including `complete()`'s hardcoded
status literal and `claim_job_for_execution`'s `status IN ('queued','running')`. Not needed.)

**Fix:** `_outcome(evidence)` derives a bounded top-level summary and `_complete` stamps it.
`_complete` is the single point all four exit paths return through, so a future early return
cannot forget to describe itself. Carries `status` (`empty|partial|ok` — the summary's own
word, not the row's), a plain sentence, `creatives_kept` / `creatives_custodied` /
`card_written` / `assets_generated`, and the steps that produced nothing split three ways:
`steps_skipped`, `steps_failed`, `steps_not_reached` (absent keys — the W5 report's "no distil
or pregenerate key in steps", which reads as silence unless named). The same sentence is
reported as the final stage.

`ingestion_job_dto` gains `outcome` via `ingestion_job_outcome`, which lifts that ONE bounded
member out of evidence and never the body (staged digests / whole harvest report stay private).
The three older ingestion kinds compose no outcome and read `None`.

## R2-D (high) — 12 pre-generated grounds never reached the agent

**Root-caused before fixing.** Four separate reasons, all discovery:
1. `read_ad_lane` never queried `design_ad_pregenerated_asset`. The only reader in the whole API
   was the operator inspection route `GET /brand-ad-assets/{brand_kit_id}`.
2. `AgentRuntimeConfig` had no field for them.
3. The W1.1 scene-turn manifest (`SCENE_TURN_ASSET_LIBRARY_MAX=24`) is a generic
   `updated_at DESC` scan with no ad-lane awareness — the `ad-pregenerated` tag is written at
   `pregenerate.py:207-225` and read nowhere at turn time. Assets can ride it, incidentally.
4. Even when they ride it, the frame's `## ASSET INDEX` is built from the brand KIT only
   (`frame.py` `build_asset_index`), so library ids surface ONLY in `view`'s honest-miss text
   (`view.py:258,270,342`) — reachable only after guessing an id wrong.

**Fix (discovery only, no plumbing):** the lane read returns the grounds linked to the ACTIVE
card version (pinned to `card_id`+`version`, never the lineage — a ground was generated from one
card's prose), reduced to id / style group / shape, bounded at `PREGENERATED_CONTEXT_MAX = 12`
(2 per group x 6 groups = a whole well-formed lane; pre-generation itself has no cap). They ride
by value and the same W4 advisory block names them.

**Deliberate restraint:** only ids present in this turn's `asset_library` manifest are listed.
Advertising an id the author would then fail to open is worse than the silence it replaces. If
none are reachable, nothing composes.

Prose says outright that using one is optional and making your own ground is fine — a bare asset
list with no posture reads as the checklist D5 forbids (same red case the card block already has).

## Verification

- Red proven for every defect against the parent commit, by staging the ORIGINAL file(s) and
  re-running the new tests. R2-B: 3 fail (incl. `resolve_distiller` returning `NullAdDnaDistiller`).
  R2-D: all 6 fail. Never used `git stash` (AGENTS.md §4); R2-D used a checksummed
  backup/restore of two files, `shasum -c` verified OK after.
- Shared-venv trap handled: shared checkout's `.venv` interpreter with PYTHONPATH pinned at this
  worktree; verified `py_lumen_config` / `lumen_ingestion` / `lumen_agent` all resolve here.
  NOTE: `apps/agent_runtime/tests/conftest.py:7-11` hard-inserts the runtime root at
  `sys.path[0]`, so PYTHONPATH alone cannot redirect `lumen_agent` for a red proof.
- DB: created throwaway `clue_w5_defects_abfc3e`, `alembic upgrade head` -> `50ce19bf5ef7`.
  Never touched a shared DB.

## Residuals / known issues (not introduced here)

- **`test_ad_assets_onboarding.py` is flaky under random test order.** One run failed
  `test_an_empty_harvest_says_so_at_the_top_level`; it passes in isolation and in deterministic
  order (verified repeatedly), and a `design_job.finished status=failed` log line in the failing
  run points at the race `_run_job`'s own docstring documents: `fleet_task` is shared across
  workspaces, so a stray embedded worker can claim a job and drive it WITHOUT the injected
  stubs. Pre-existing hazard; the 5 new job rows widen the window. Real fix is offering these
  jobs without enqueueing fleet work, which is the shared helper's to change, not this repair's.
- **`test_web_review_cap.py::test_the_web_harness_installs_the_delegation_cap` is a rare
  order-dependent flake, and it is NOT a regression here.** Observed once across 6+ full-suite
  runs. Passes in isolation (10/10), passes when run straight after the ad-DNA file, and the
  full suite is clean in deterministic order. Proven not-mine by running the whole suite at
  three PINNED pytest-randomly seeds (1/2/3) against the base commit's `frame.py`/`config.py`/
  `test_ad_dna_frame_context.py` and then against these commits' versions: identical, zero
  failures on both sides. Likely mechanism: whichever test first imports `lumen_agent.harness_web`
  binds whichever `deepagents.create_deep_agent` is installed at that moment, and several tests
  install a stub module via `monkeypatch.setitem(sys.modules, ...)`.
- **3 pre-existing failures in `tests/test_web_retokenize.py`** — Tailwind theme drift guards
  that need `npm install` under `apps/editor`; `node_modules` is absent in this worktree. The
  tests say so themselves ("run `npm install` under apps/editor"). Unrelated to these changes.

## Process note worth not repeating

Do NOT mutate the working tree while a background suite is running. One "final" API run reported
`AttributeError: 'AgentRuntimeConfig' object has no attribute 'ad_pregenerated_assets'` purely
because the base-commit seed experiment swapped `config.py` out from under it mid-run. Re-run
after restoring; the failure did not reproduce.
- `subsystems/clue-design` is excluded from root ruff (`pyproject.toml` `exclude` /
  `extend-exclude`), so the ~77 ruff findings on the touched files are the tree's pre-existing
  house style (`Optional[...]`, quoted annotations). New code deliberately matches its neighbours.
- **Not fixed, still open from the same report:** R2-A (`total_ads` always 0), R2-E (prose card
  hard-truncates mid-sentence at 2400 chars), D8 (reversed-logo slot filled by a third-party
  19x19 glyph via background-luminance classification), D3 (SVG assets unviewable), D4 (WOFF2
  cannot be embedded in SVG export), D5 (kit type roles declare weights the custodied faces do
  not ship).
- **Design decision NOT taken (flagged, not decided):** whether pre-generation should be capped
  at the source. It scales as `2 x style_groups` with no bound; `PREGENERATED_CONTEXT_MAX` bounds
  only what reaches the prompt, not what gets paid for.
