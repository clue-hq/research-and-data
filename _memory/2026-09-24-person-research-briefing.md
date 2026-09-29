# Account-to-person briefing — 2026-09-24

## Scope and decisions

- Founder authorized the concise account-authored person delegation, exact instruction review,
  and one explicitly approved OpenRouter/Langfuse prompt-only sample from retained context.
- Account parent writes `research_brief` on either AI Ark or web nomination. Head-of-ABM remains
  the account-brief owner; no Head prompt change. Brief supplements full person-depth coverage.
- No person charter/Exa rewrite, research-provider purchase, application-data mutation, live fleet
  or person-depth job in this slice. No new relationship/location/presentation gates. Email only.

## Implementation

- Quality account profile/prompt v9 adds `person-research-briefing@v1`; recipe/launch revision9.
- Nomination @3 stores exact prose separately from evidence using the existing ResearchArtifacts
  sink. Existing context/source derivation, contact/project bindings, retention and erasure apply.
- First nomination's brief survives replay and repeated nomination. The job stores artifact/hash
  references. Worker opening includes exact prose; `/research/person-brief/0.json` exposes it.
- Person context exposes selected identity, discovery refs, account findings/originals and existing
  full pinned document paths. Project pins remain authoritative; legacy jobs retain their opening.
- Person profile `quality-person-research@v9-person` retains prompt/skills v6 and removes nomination
  tools: an already-selected person does not need committee discovery. Specialists remain v6.
- Historical resource pins preserved. Application default runtime selector remains v2; this is the
  opt-in quality runtime. No push or deployment.

## Preview and review

- Script: `scripts/preview_person_research_brief.py`; output:
  `.artifacts/person-brief-preview-20260924/run-01/`. Exact prompt, opening, skill, inputs, captured
  nomination, unedited brief, per-call traces and resource manifest retained. Review at sibling
  `REVIEW.md`. No customer excerpts copied into this memory.
- Completed in 104.19s, six model calls, about $0.19 recorded cost. Brief 485 words before refs,
  533 total, slightly over the 300–450 guidance. Source-specific leads and broader coverage kept.
- Limitations: retained context, sparse persona, skill explicitly disclosed rather than testing
  autonomous selection; no real person worker consumed it. Langfuse model-name parser warned;
  application usage logs still recorded requested/served model.
- Post-sample review caught missing system-paragraph replacement: full new skill WAS supplied to
  the sample. Final system paragraph is now corrected/pinned but not live-retested. Preserve the
  original sampled prompt/manifest; do not present it as the corrected production prompt.

## Verification and failures

- Initial model call auto-review rejection resolved by founder's explicit payload approval.
- Local DB access needed sandbox escalation. All tests used newly created random local databases,
  dropped afterward; receipts retained. No application DB was used.
- Corrected duplicate tool-version compatibility requirements (then missing pins on old dynamic
  allowlist); final recipe has @3 only and person profile omits nomination tools.
- Corrected test helper assumptions about direct JSON views versus paginated passages and the
  erased-artifact exception. Source erasure demonstrably invalidates derived person assignment.
- Focused database suite: 12 passed (nomination, runtime, driver, tools). Focused offline checks:
  18 passed before final prompt paragraph correction; final recheck recorded below on completion.
- Scoped mypy: six runtime modules passed. Ruff/diff verification on changed files.

## Remaining

- Founder review of exact skill/instructions and unedited brief. Brevity/readability can improve.
- Next agreed slice: detailed person charter and actual person Exa request, preserving the PoC's
  explicit subquestions. Live person-depth quality and full fleet execution remain untested here.

## Closing checkpoint

- Final focused offline suite passed 18/18 after correcting and pinning the system paragraph.
- Database suite passed 12/12; all created test databases dropped. Scoped mypy, Ruff lint/format
  and git diff checks passed. No additional paid sample or live research was run.
- Exact instructions, limitations and the untouched model output are linked in the review artifact.

## Founder review follow-up

- Founder accepted the approach and requested explicit charter coverage under "Where I would
  like you to go deeper." Around 750 words is acceptable; never impose a hard word cap.
- Edited the requested preview Markdown with that summary (675 words). Preserved exact original
  as `person-brief.model-original.md`, matching the captured nomination; traces and JSON untouched.
  `REVIEW-EDIT.md` distinguishes the editorial revision from generated output.
- Versioned guidance as person-research-briefing v2, account profile/recipe/launch 10. Prompt v9
  and person profile v9-person stay unchanged. Historical pins remain valid. Preview script now
  resolves the current recipe constant instead of a stale literal.
- Existing account Exa/catalog suite passed (15 tests); Ruff and diff checks passed after fixing
  one line-wrap lint issue. Confirmed neither nomination input schema has a brief maxLength.
- No model/provider calls, database/fleet work, or person charter implementation in this follow-up.
