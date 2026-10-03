# Website source-copy repair — 2026-09-28

## Scope and boundary

- Continued from the completed native-run trace audit. The goal is still active;
  this is one tooling checkpoint, not creative-quality acceptance.
- No additional native generation, source ingestion, saved-page edit, service
  restart or remote push. Keep the user's no-new-run instruction in force.
- Work is on `codex/design-agent-v1` in the original checkout. Preserve unrelated
  account-research tests and existing memory notes in the working tree.

## Implemented

- Extended the existing exact href derivative with optional exact CTA-label
  replacements. It changes one text node without transcribing source HTML/CSS,
  preserving icons, source assets, responsive CSS, slot bindings and the page pin.
- Matching accessible labels/titles follow the new text. Ambiguous styled labels,
  separate accessible names, existing text slots and human text overrides refuse
  rather than destroying or masking them. Failed maps leave the source unchanged.
- Campaign-specific changes use the existing `campaign variant:` lineage rule;
  verified that the original remains the resolver's choice for future original pins.
- Ingestion now exposes additional semantic card headings and up to eight CTA
  pairs, keeping existing primary keys. CTA detection no longer selects SVG titles
  or consumes icon-containing/partial-label wrappers.
- Updated the native repair skill for the actual tool arguments and limitations.
  Existing stored fragments are immutable: additional ingestion slots apply to
  newly minted fragments; the exact label derivative can work on held old captures.

## Verification

- RED: missing label API / secondary heading support failed before implementation.
- RED: separate accessible names remained stale, and SVG/partial-label detection
  reproduced unsafe slots. These regression cases passed after the corrections.
- Full focused suite: **409 passed in 98.39s**. Files: API
  `test_fragment_href_repair.py`, `test_ingestion_section_mint.py`,
  `test_fragment_repair.py`, `test_fragment_raw_css_repair.py`,
  `test_web_fragment_artifact.py`; runtime `test_web_cloned_sections.py`.
  Includes the actual engine's editor/delivery render and durable variant custody.
- Skill-family suite: **12 passed**. Offline agent retrieval/application probe:
  baseline required complete raw HTML/CSS for a plain label; updated guide selected
  exact label/link maps, preserved source markup and handled the refusal cases.
  This probe is documentation evidence, not native page-quality evidence.
- Initial broader run hit 34 local DB connection permission failures. Re-ran on
  an explicitly created disposable database with migrations applied from scratch.
  All passed there, then removed that disposable database. No live DB was migrated.
- Test commands used root `.venv/bin/python`, design-subsystem cwd,
  `PYTHONPATH=.:apps/api:apps/agent_runtime`, explicit disposable `CLUE_DATABASE_URL`,
  `-q -o addopts='' --tb=short` and unique `/tmp` basetemp directories.
- Targeted Ruff fatal/syntax checks and `git diff --check` passed.

## Still owed

- Machine-verifiable review coverage, strict-pass honesty and matching source
  reference viewports; full-page phone review and desktop overflow checks.
- Handoff separation of actual user constraints from generated recommendations.
- Account argument/section-purpose discipline, source typography and media-layer
  metadata, compact mobile composition and supported interactive feature states.
- The saved Hotel Equities page has not changed. No improved native output has
  been demonstrated. Do not equate this checkpoint with fixing the whole page.
