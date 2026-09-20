# Website capture fidelity and skill foundation

**Goal:** Capture representative source pages for Clue, AWS, Google Cloud and Conduit, prove faithful reproduction, then ground account-personalized pages in that library.
**Authority / Spec:** The active user goal and the 2026-09-20 capture audit; source reproduction precedes personalization. This plan is the implementation record, not a claim of completed fidelity.
**Architecture:** Extend the existing capture -> snapshot -> fragment -> brand-kit -> web-design seams. Preserve original bytes and capture provenance. Keep original captures distinct from derived React compositions and generated media.
**Stack:** Python capture/API, Playwright, Postgres registry, React website artifacts, existing application skills.

## Global constraints
- Work only in `codex/website-capture-v1`; preserve the original running checkout and four workspaces. No remote push.
- No secret values in artifacts/logs. No unbounded crawling or arbitrary third-party script execution in generated pages.
- Frozen originals and prior drafts remain intact. All capture gaps and unsupported motion are reported, not silently replaced.
- Keep exact asset references and workspace/kit ownership. Do not weaken SSRF, asset-custody, approval, or contact-use gates.
- Tests using a database run against an isolated disposable database. Live ingestion writes are additive and scoped to the four authorized workspaces.
- Generated artwork can support brand aesthetics, but cannot count as source-fidelity evidence.
- Every new environment setting is documented in root and subsystem examples; existing operator values win.

## Review focus
Reference-resolution security; deduplicated fragment lineage across kit ingestions; media byte custody; bounded multipage coverage; no fabricated customer/contact evidence; visual fidelity at desktop and mobile.

## Task 1: Preserve quoted SVG local references
**Files:** `subsystems/clue-design/apps/api/lumen_api/fragments/cssscope.py`, `subsystems/clue-design/apps/api/tests/test_web_fragment_artifact.py`.
**Interface:** Existing `scope_fragment_css` and `sanitize_fragment_html`; same-document paint references must remain local and must not enter dependency digests.
- [ ] Add failing tests for quoted SVG gradients/filters and mixed local/external CSS URLs, including inline style.
- [ ] Run focused pytest. Expected: quoted local references fail with `fragment.unreadable_reference` before fix.
- [ ] Correct successful local-reference termination while retaining malformed/external reference refusal.
- [ ] Run full artifact tests. Expected: all pass, existing security refusals retained.
- [ ] Commit tested fix with concise operational memory entry.

## Task 2: Capture the media actually referenced by source markup
**Files:** `lumen_ingestion/capture/{candidates,static,snapshot,net}.py`, capture/fragment pipeline tests, relevant configuration examples when necessary (paths under `subsystems/clue-design/apps/api`).
**Interface:** Candidate URLs -> typed Download -> captured_assets -> exact-token reference harvest.
- [ ] Add source-shaped regressions for image `src` when srcset prefers another rendition, query-bearing relative image URLs, video/source URLs and posters.
- [ ] Run regressions red. Expected: omitted source src/video candidates reproduce existing Conduit/Google gaps.
- [ ] Preserve all exact source renditions; add bounded video custody without routing videos into image analysis.
- [ ] Run capture + fragment pipeline tests. Expected: missing dependencies resolved and over-budget/unsafe requests still fail explicitly.
- [ ] Commit tested media fix.

## Task 3: Preserve fragment availability across brand-kit ingestions
**Files:** `subsystems/design/clue_design/web_fragments.py`, its registry tests and migration if schema evidence requires one.
**Interface:** Content-addressed fragment identity plus workspace-scoped kit/version lineage and human release authority.
- [ ] Reproduce identical-content reingestion under a new kit id, same kit version advancement, and cross-workspace isolation in tests.
- [ ] Implement explicit capture/kit association without silently releasing unrelated fragments or overwriting immutable bytes.
- [ ] Run registry and approval tests plus disposable migration smoke if a migration is added. Expected: latest approved capture can discover its original fragments; old releases remain traceable.
- [ ] Commit tested association fix.

## Task 4: Bounded multipage capture and coverage reporting
**Files:** `lumen_ingestion/capture/__init__.py`, `lumen_ingestion/pipeline.py`, ingestion API request models, platform ingestion enqueue seam, tests.
**Interface:** Explicit page plan -> per-page capture/mint outcomes -> durable coverage report. Existing homepage-only requests remain valid.
- [ ] Add failing tests for explicit supporting pages, bounded counts, fair section allocation and visible failures.
- [ ] Implement deep homepage plus selected pages, dependency/interaction inventory, durable status and meaningful refresh behavior through existing seams.
- [ ] Verify API compatibility and budget/failure tests. Expected: no page is silently skipped or treated as fidelity-ready after a partial capture.
- [ ] Commit tested coverage work.

## Task 5: Expanded four-brand source library and reproduction benchmark
**Files:** Additive evaluation artifacts and a tracked report under `subsystems/clue-design/docs/`; operational memory.
**Interface:** Tasks 1-4 outputs consumed by the normal web design library/runtime.
- [ ] Discover current official homepage, 1-2 product pages, one customer page, and 1-2 customer review/case-study pages per brand where available.
- [ ] Capture source references and dependencies, with separate per-brand manifests; store in their respective authorized workspaces.
- [ ] Restore standard sandbox prerequisites before fleet generation; do not bypass sandbox enforcement.
- [ ] Reproduce representative pages without messaging changes; inspect desktop/mobile and supported motion against frozen source captures.
- [ ] Report pass/fail by layout, typography, media, interaction and provenance; retain all failure evidence.

## Task 6: Skill families and grounded account personalization
**Files:** Existing application skills under `subsystems/clue-design/apps/agent_runtime/knowledge_docs/skills`, registry/harness tests where exposed.
**Interface:** Progressive skill loading over the verified library and existing account/claim/logo tools.
- [ ] Define seven families / 24 responsibilities from the audit; reuse existing skills instead of duplicate agents.
- [ ] Test source-first retrieval, supported animation, product crop/staging, proof media, scoped editing and fidelity review on the four brands.
- [ ] Implement missing skill files and callable routing with explicit evidence and fallback policies.
- [ ] Personalize approved pages using correct account logos and grounded insights; contact adaptation only with identity-bound, appropriate evidence.
- [ ] Verify repeatability, account isolation, responsive rendering and absence of invented proof.
- [ ] Final independent branch review; resolve important findings, run relevant checks, commit. Goal complete only after live acceptance criteria pass.
