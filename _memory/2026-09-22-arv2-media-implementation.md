# ARV2 media implementation — 2026-09-22

- Founder approved canonical media spec/plan for implementation. Defaults in spec accepted.
- Base 79520ffca on codex/ai-ark-committee-discovery-spec; authorized pull reports already up to date.
- AI Ark v2 stays default; v3 will be opt-in pending founder-triggered live acceptance.
- Preserve user .context/attachments/V4drO2/. No paid providers, restart, push or deployment.
- Baseline media clients, tools, committee adapters and catalog: 239 passed (13.67s).
- Implementing typed references, explicit v1/v2/v3 capabilities and durable source ownership first.

- Implemented media tables, staged acquisition, public resolver/native video path, transcript indexes/search/open, provenance/audits, and v3 capability wiring. All still uncommitted/in progress.
- Founder corrected verification cadence: finish connected roadmap changes before final-behavior acceptance/regression; use narrow intermediate checks only for integrity/spend/lifecycle concerns. Do not tune tests for transient implementation states.
- Early baseline regression remained 239 passed; helper/provider subset 167 passed. Latest real DB run 26 passed with one cross-job fixture uniqueness error (duplicate account); fixed fixture to use a separate run over the existing account. Expiry/reacquisition now passes.
- Fixed a real expired-source reuse defect, privacy registration for later consumers, claim-write erasure race, scoped artifact/version FKs, and empty-transcript seconds accounting. Final consolidated checks remain pending.
- Full mypy currently reports only the existing design_leg_wiring.py:1627 Mapping/dict mismatch. New media files still need formatting/lint cleanup.
- No paid calls, v3 activation, pushes, or deployment. AI Ark v2 remains default.

- Consolidated core run: 520 passed / 5 failures (525 cases). Failures were committed concurrency-fixture cleanup (missing alias delete, contaminating two global-count queries) and two old launch fixtures that assumed v1 despite the earlier v2 default change. Fixed cleanup; kept legacy launch fixture explicitly on v1. v2/v3 launch, driver, committee handoff, channels and erasure are parameterized separately.
- Affected-suite rerun: 94 passed. Media/parser/structuring/tools/storage/DSAR suite: 304 passed. Final parser/replay suite: 60 passed. Discovery-reference-to-transcript/search/claim-audit trace: 1 passed. Counts overlap and are not additive.
- Migration up/down/up succeeded; single head 213dea37b230. Disposable DB clue_media_test_462553b0c5; no shared database migrated.
- Final review added source qualifications as non-evidence structuring context, preserved mined-quote usability/verdicts, and carried remembered transcript references through follow-up insight writes. Native structured responses without a TRANSCRIPT section cannot become speech. Search cursors pin index generations; caption cues preserve source timestamps; redirect targets determine relative-link bases.
- Touched code Ruff/format checks pass. All 28 import-linter contracts pass. Repo-wide baseline gaps: projections_app.py I001; design_leg_wiring.py:1627 mypy Mapping/dict (901 sources checked); ARV2 import guard retains two unrelated offenders (account_research_agent/langfuse_callbacks and icp_authoring/project_library_refresh). Two narrowly admitted URL/DNS safety modules are documented in the master-plan amendment; no new guard offender remains.
- Implementation tradeoffs: conservative UTF-8 byte-bounded chunk recipe rather than downloading a tokenizer at runtime; native-video USD explicitly unpriced pending current billed-usage calibration. Full recall/quality/autonomous-discovery and provider compatibility remain live acceptance, not offline proof.

## Closing state

- Runtime/schema/catalog implementation committed locally as 5d90cdbe3. Final completed-code media/Gemini/structuring/replay suite: 142 passed (4.74s).
- Strengthened the ownership acceptance test to run two distinct research jobs on independent committed connections; 1 passed (0.90s). No runtime code changed after the 142-case run.
- Plan Steps 1–8 marked complete; Step 9 remains pending. Acceptance record: docs/superpowers/plans/2026-09-22-arv2-media-acceptance.md. It distinguishes offline contracts from live-provider, autonomous-discovery, ASR/attribution, Recall@8 and quality/cost validation.
- Account/person v3 bundle digests recorded; v1/v2 resource bytes unchanged. Default/settings/example/local selector remains v2. Video setting parity confirmed.
- Apply migration to the explicitly selected isolated test DB before starting new-code API/workers. Shared services/DBs were not changed. Existing repo-wide Ruff/mypy/quarantine failures remain documented outside this feature.
- No paid live calls, service restarts, push, PR or deployment. User .context/attachments/V4drO2/ remains untracked and untouched.
