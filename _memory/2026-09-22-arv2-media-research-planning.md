# ARV2 media planning and AI Ark v2 default — 2026-09-22

## Scope and founder decisions

- User requested a strong spec for the verified media gaps; explicitly answered **spec and
  implementation plan first**, so no media runtime implementation or paid canary is authorized
  by this session. User then separately instructed making AI Ark committee v2 the default and
  building the media improvement only on that updated flow.
- Current branch: `codex/ai-ark-committee-discovery-spec`, starting head `99253e5d4`.
  `git pull --ff-only` initially lacked permission to write the external worktree Git metadata;
  the authorized escalated retry completed **Already up to date** against the branch upstream.
- Preserve user-untracked `.context/attachments/V4drO2/`; no push, service restart or deployment.

## Changes

- Settings, `.env.example`, and local ignored `.env` now default new launches to catalog v2.
  Local default-change commit: `b35dc49f2`.
  Production launch service reads this selector for both account and on-demand person jobs.
  Legacy catalog helper defaults and historical job pins stay v1; existing processes need a
  config reload. No model changes or catalog-byte changes. Live v2 acceptance remains outstanding.
- Updated ARV2 README, master-plan header and committee design/plan/acceptance status to record
  the founder's later default-selection ruling without presenting it as live validation.
- Added `docs/superpowers/specs/archive/2026-09-22-arv2-media-research-design.md`: 14 verified gaps,
  four media tools, native public-video route, feed/page resolution, source-level acquisition
  reuse, versioned transcripts/passages, hybrid retrieval, attribution/timing/quality, reference
  claims, transcript-aware audits, scoped lifecycle/erasure, coverage and 20 acceptance cases.
- Added `docs/superpowers/plans/2026-09-22-arv2-media-research.md`: nine ordered steps and
  separate offline, live and activation states. Proposed next immutable catalog is v3 carrying
  all v2 capabilities; literal v2 predicates must be audited before that version is introduced.
- Design defaults remain proposals: workspace-only source reuse; 30-day retention aligned to
  current personal-source precedent; substantive-item accounting; native video model setting;
  attribution labels and measured recall/quality targets. No total-call/spend/zero-yield cap.

## Verification / closing state

- Focused config, ARV2 settings, catalog and v2 adapter suites: **70 passed**.
- Explicit checks: class default, local/example env selectors are v2; account/person v2 bundles
  load with manifests; null/explicit historical v1 pins still resolve to v1.
- Changed Python Ruff lint/format and `git diff --check` pass. All relative links in the new
  docs resolve; G01–G14 and A01–A20 are present. No new database migration or live DB change.
- Official Gemini video/embedding and YouTube caption docs checked for design feasibility;
  exact provider/model/endpoint behavior is still a future live proof. No provider calls ran.
- Media implementation awaits founder review. Existing AI Ark live acceptance is also pending;
  selecting its default does not establish live quality. Use git history for local commit IDs.
