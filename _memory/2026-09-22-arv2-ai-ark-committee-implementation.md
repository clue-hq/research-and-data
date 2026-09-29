# ARV2 committee discovery implementation — 2026-09-22

- Founder explicitly requested implementation of the nine-step plan. Its engineering defaults
  are accepted as the implementation basis. No separate provider spend/deployment instruction.
- Branch `codex/ai-ark-committee-discovery-spec`; upstream pull reports already up to date at
  `8df27dd25`, with the local planning commit `23ed6e7c0` above it.
- Baseline focused suites: one pre-existing import-guard failure, for existing imports of
  `clue_api.langfuse_callbacks` and `clue_api.project_library_refresh`; other selected tests pass.
  Full output `/tmp/arv2-committee-baseline.log` (temporary).
- Preserve user `.context/attachments/V4drO2/`. No push.
- Contract decisions: keep v1 authority/pins; additive v2; reference-only persistence; invalidate
  a multi-person source page on erasure if safe redaction is unavailable; no repeat billing on
  unknown outcomes; persona absence/lineage uncertainty is explicit, not a hard quality gate.
- Public AI Ark function vocabulary downloaded for pre-spend validation. Local Postgres read
  initially failed sandbox access, then needed credentials; isolated DB setup is in progress.

## Implemented contracts and evidence

- Adapter: exact company ID/domain SMART role search, pagination/filter validation, ID-based
  email export, phone lookup and endpoint-specific empty/error states. Inferred credits remain
  distinct from provider headers; malformed phone data does not fabricate a zero charge.
- v2 account/person bundles, persona/artifact pins and explicit per-job profile refs. Default
  launch selector stays v1 in both example and local env. No model changes or v1 byte changes.
- Durable operations with one owner, canonical fingerprints and saved ledger/artifact receipts;
  abandoned leases become unknown without repurchase. Selection checkpoint recovers fanout.
- Shared provider identity binding; seeded jobs avoid name search, write profile facts first and
  run independent email/phone operations alongside depth. Unseeded lookup shares channel logic.
- Raw personal pages expire after 30 days. All subjects indexed, including unselected people;
  whole-page erasure overrides surviving citations. DSAR reaches account selection copies and
  old job authority; late responses stay unreadable. Maintenance performs physical purging.
- New source files and test mapping are listed in the durable acceptance report at
  `docs/superpowers/plans/2026-09-22-arv2-ai-ark-committee-acceptance.md`.

## Development failures and resolution

- Disposable database `clue_aiark_test_f36a3ed1d0` was created for this session; no shared DB used.
  A draft migration had been applied before its expiry column was added, so its first draft
  downgrade failed. The disposable schema was aligned, then step downgrade/upgrade and full
  downgrade-to-base/upgrade passed. One head: `0ab01fe27c1e`.
- SQL `LIKE '%:v2'` was parsed as a bind; use `right(profile_ref,2)='v2'`.
- Scripted driver fixture initially used wrong queue kwargs/store method names; corrected.
- New tests caught no-email and malformed-response accounting gaps, full-erasure reachability,
  and independent channel states; these now have explicit tests. A broad first run produced
  1248 passes, 4 skips and 4 failures: registry count and two sweep spies needed updates; the
  remaining import-guard failure is baseline. Focused rerun: 66 passed.
- Full mypy retains only baseline `design_leg_wiring.py:1627` Mapping/dict mismatch. Both import
  guard offenders and that type-error source were verified at the starting commit.
- 28 import contracts pass. Changed-file Ruff lint/format and diff whitespace checks pass.

## Release boundary

No paid live requests, deployment, push or PR. Probook/Zafran relevance/phone-contract canaries
and review must be explicitly initiated before v2 activation. Phones have backend claims only;
no frontend phone slot is shipped. User `.context/attachments/V4drO2/` remains untouched.

## Closing state

- Final broad regression: 1251 passed, 4 skipped, baseline import guard plus one new recovery
  fixture failure. The fixture had retained `finished_at` when simulating suspension; corrected
  to honor the existing terminal-state CHECK. Final focused rerun: 212 passed. Final fanout/driver
  database rerun: 30 passed, including all 20 new v2 DB tests. Counts overlap.
- Final review added parent refs for v2 web-selected people, so failed enqueue is recoverable for
  both provider and web candidates; no source profile is fabricated for the web path.
- Changed-file Ruff lint/format, diff whitespace and 28 import contracts pass. Full mypy still
  reports only the verified pre-existing design-lane error. No implementation failure remains.
- Implementation, tests, design rulings, plan checklist and acceptance report are committed locally
  together as one feature checkpoint. No push or activation. Use git history for the commit id.
- Remaining: explicit live Probook/Zafran canary and release review; baseline import/type errors
  are documented but not broadened into this feature. User attachment directory remains untracked.
