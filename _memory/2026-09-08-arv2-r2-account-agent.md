# 2026-09-08 — ARV2 R2 (account research agent): plan written, ready to execute

Branch `track-R2` (worktree san-salvador), rebased onto `integration/design-improvement` @ `33ab4fed1`
(O3 + O4 + D2 merged; single alembic head `9f81e5692fea`). Founder rulings today: stop policy
(100 rounds / 50 per round / 30 min, no total-call or zero-yield caps, full mode only); ICP hard gates
are lenient fit verdicts, never an early exit; negatives born `outreach_safe=false`; twelve-section
charter; structuring client gains `mode=intent_sweep`. S7 substance fully APPROVED.

## Artefacts
- Plan: `docs/superpowers/plans/2026-09-08-arv2-r2-account-agent.md` (7 tasks; Task 7 = founder-triggered
  live acceptance on Probook + Zafran).
- Facts (exact signatures, four scouts): `docs/superpowers/plans/2026-09-08-arv2-r2-account-agent-facts/facts-{fleet,jobs,agent,tools}.md`.
- Substance §7 records the implementation decisions.

## Architecture decisions (why, in one line each)
- **Own rows + own fleet kind** (`arv2_research_run/_job`, `arv2_claim_annotation`, `arv2_account_research`):
  the M8D `entity_research_job` needs `product_id NOT NULL`, a sealed discovery and an `icp_spec`-keyed
  research directive (old Stage-0 machinery; standing-rule item 5), and its kind is owned by the
  quarantined handler.
- **Own `create_agent` loop**, not the M8D runtime: `EntityResearchStopPolicy` caps rounds at 64 and
  requires zero-yield/total-call caps; the tool-surface validator hard-codes M8D tool names; caps raise.
- **One `ProviderCaller` per tool invocation** with buffered sinks drained to `provider_call_ledger`
  (+ `extras_json`) and the artifact store after each `to_thread` hop; job-level halt registry;
  AI Ark/media serialised. Known residual: a lease lost mid-hop can lose that hop's rows.
- Only the launch/read tools join the toolbelt (`launch_arv2_account_research@1`,
  `read_arv2_account_research_run@1`, HEAD_OF_ABM; authority count 120→122); the twelve agent tools are
  `StructuredTool`s inside the driver.
- Stop-policy numbers are `CLUE_ARV2_ACCOUNT_*` settings (six new fields) — a limit change is an env change.
- Two new pack keys: `account.committee_candidate`, `account.icp_fit_verdict` (40 keys).

## Pre-existing base failures (not R2's)
`tests/arv2/test_onboarding_settings.py` (`CLUE_ONBOARDING_V2_ENABLED=true` vs default False) and
`tests/arv2/test_settings.py` (quoted display pitch). Two-line fixes on the base lane.

## Next
Execute the plan (subagent-driven, Opus implementers, Fable reviews each task). AI Ark people credit
is the only external prerequisite left before Task 7.
