# Website capture fidelity and skill foundation

**Goal:** Improve the shared onboarding capture and website-design pipeline for any customer, using Clue, AWS, Google Cloud and Conduit as regression cases. Prove faithful reproduction, then ground account-personalized pages in the captured library.
**Authority / Spec:** The active user goal and the 2026-09-20 capture audit. On 2026-09-21 the user confirmed that capture/reproduction and account-specific skill work continue under the existing goal, directly in Clue. Source reproduction remains an acceptance prerequisite for personalized quality. This plan is the implementation record, not a claim of completed fidelity.
**Architecture:** Extend the existing capture -> snapshot -> fragment -> brand-kit -> web-design seams. Preserve original bytes and capture provenance. Keep original captures distinct from derived React compositions and generated media.
**Stack:** Python capture/API, Playwright, Postgres registry, React website artifacts, existing application skills.

## Global constraints
- Work directly in `/Users/shashank/Documents/clue-latest-pull-sept7` on `codex/design-agent-v1`, through Clue's existing design runtime and native UI. The earlier isolated `codex/website-capture-v1` checkpoint was brought into this checkout on 2026-09-20. Do not build a standalone replacement or create another worktree for this implementation. Preserve the four original workspaces and Conduit Fresh. No remote push.
- No secret values in artifacts/logs. No unbounded crawling or arbitrary third-party script execution in generated pages.
- Frozen originals and prior drafts remain intact. All capture gaps and unsupported motion are reported, not silently replaced.
- Keep exact asset references and workspace/kit ownership. Do not weaken SSRF, asset-custody, approval, or contact-use gates.
- Tests using a database run against an isolated disposable database. Live ingestion writes are additive and scoped to the four authorized workspaces or the explicitly authorized Conduit Fresh workspace.
- Generated artwork can support brand aesthetics, but cannot count as source-fidelity evidence.
- Every new environment setting is documented in root and subsystem examples; existing operator values win.

## Current live-test constraint — 2026-09-21

The user suspended the four older instances and restricted live testing to Conduit
Fresh on port 3020. The latest ordinary-prompt attempt is terminal (cancelled by
request). The user asked for no repeated prompts: do not launch a new generation,
research, or ingestion test automatically. The four-brand benchmark remains open;
old-workspace results do not satisfy fresh-ingestion acceptance. Local code and
regression work can continue without restarting the platform.

## Review focus
Reference-resolution security; deduplicated fragment lineage across kit ingestions; media byte custody; bounded multipage coverage; no fabricated customer/contact evidence; visual fidelity at desktop and mobile.

## Task 1: Preserve quoted SVG local references
**Files:** `subsystems/clue-design/apps/api/lumen_api/fragments/cssscope.py`, `subsystems/clue-design/apps/api/tests/test_web_fragment_artifact.py`.
**Interface:** Existing `scope_fragment_css` and `sanitize_fragment_html`; same-document paint references must remain local and must not enter dependency digests.
- [x] Add failing tests for quoted SVG gradients/filters and mixed local/external CSS URLs, including inline style.
- [x] Run focused pytest. Expected: quoted local references fail with `fragment.unreadable_reference` before fix.
- [x] Correct successful local-reference termination while retaining malformed/external reference refusal.
- [x] Run full artifact tests. Expected: all pass, existing security refusals retained.
- [x] Commit tested fix with concise operational memory entry.

## Task 2: Capture the media actually referenced by source markup
**Files:** `lumen_ingestion/capture/{candidates,static,snapshot,net}.py`, capture/fragment pipeline tests, relevant configuration examples when necessary (paths under `subsystems/clue-design/apps/api`).
**Interface:** Candidate URLs -> typed Download -> captured_assets -> exact-token reference harvest.
- [x] Add source-shaped regressions for image `src` when srcset prefers another rendition, query-bearing relative image URLs, video/source URLs and posters.
- [x] Run regressions red. Expected: omitted source src/video candidates reproduce existing Conduit/Google gaps.
- [x] Preserve all exact source renditions; add bounded video custody without routing videos into image analysis.
- [x] Run capture + fragment pipeline tests. Expected: missing dependencies resolved and over-budget/unsafe requests still fail explicitly.
- [x] Commit tested media fix.

## Task 3: Preserve fragment availability across brand-kit ingestions
**Files:** `subsystems/design/clue_design/web_fragments.py`, its registry tests and migration if schema evidence requires one.
**Interface:** Content-addressed fragment identity plus workspace-scoped kit/version lineage and human release authority.
- [x] Reproduce identical-content reingestion under a new kit id, same kit version advancement, and cross-workspace isolation in tests.
- [x] Implement explicit capture/kit association without silently releasing unrelated fragments or overwriting immutable bytes.
- [x] Run registry and approval tests plus disposable migration smoke if a migration is added. Expected: latest approved capture can discover its original fragments; old releases remain traceable.
- [x] Commit tested association fix.

## Task 4: Bounded multipage capture and coverage reporting
**Files:** `lumen_ingestion/capture/__init__.py`, `lumen_ingestion/pipeline.py`, ingestion API request models, platform ingestion enqueue seam, tests.
**Interface:** Explicit page plan -> per-page capture/mint outcomes -> durable coverage report. Existing homepage-only requests remain valid.
- [x] Add failing tests for explicit supporting pages, bounded counts, fair section allocation and visible failures.
- [x] Implement deep homepage plus selected pages, dependency/interaction inventory, durable status and meaningful refresh behavior through existing seams.
- [x] Verify API compatibility and budget/failure tests. Expected: no page is silently skipped or treated as fidelity-ready after a partial capture.
- [x] Commit tested coverage work.

## Task 5: Expanded four-brand source library and reproduction benchmark
**Files:** Additive evaluation artifacts and a tracked report under `subsystems/clue-design/docs/`; operational memory.
**Interface:** Tasks 1-4 outputs consumed by the normal web design library/runtime.
- [ ] Discover current official homepage, 1-2 product pages, one customer page, and 1-2 customer review/case-study pages per brand where available.
- [ ] Capture source references and dependencies, with separate per-brand manifests; store in their respective authorized workspaces.
- [x] Restore standard sandbox prerequisites before fleet generation; do not bypass sandbox enforcement. Docker Desktop and the standard sandbox now run native design jobs; see the native baseline report below.
- [ ] Reproduce representative pages without messaging changes; inspect desktop/mobile and supported motion against frozen source captures.
- [ ] Report pass/fail by layout, typography, media, interaction and provenance; retain all failure evidence.

**Partial live evidence, 2026-09-21:** four native baseline pages were saved on
September 20, but their older libraries did not prove fresh source reproduction.
Conduit Fresh subsequently ingested six pages through normal onboarding, released
40 captured sections through the UI, and created a native page using six captured
bands. This is one-brand evidence, not completion of the four-brand reproduction
and motion benchmark. The other Task 5 checkboxes stay open at that boundary.

## Task 6: Skill families and grounded account personalization
**Files:** Existing application skills under `subsystems/clue-design/apps/agent_runtime/knowledge_docs/skills`, registry/harness tests where exposed.
**Interface:** Progressive skill loading over the verified library and existing account/claim/logo tools.
- [x] Define seven families / 24 responsibilities from the audit; reuse existing skills instead of duplicate agents.
- [ ] Test source-first retrieval, supported animation, product crop/staging, proof media, scoped editing and fidelity review on the four brands.
- [x] Implement missing skill files and callable routing with explicit evidence and fallback policies. Four new skills, seven existing entries updated, fourteen progressive references. Offline delivery/contract validation is separate from model behavior and live quality.
- [ ] Personalize approved pages using correct account logos and grounded insights; contact adaptation only with identity-bound, appropriate evidence.
- [ ] Verify repeatability, account isolation, responsive rendering and absence of invented proof.
- [ ] Final independent branch review; resolve important findings, run relevant checks, commit. Goal complete only after live acceptance criteria pass.

**Implementation versus qualification, 2026-09-21:** all seven families / 24
responsibilities are written and routed in the main Clue checkout: 11 entry skills
and 15 detailed references after the account-argument addition. The initial four native runs and subsequent Conduit
corrections exercised 10 of 11 entrypoints; motion has not been exercised. The
audited original four runs plus Conduit Fresh's three runs read only six of the
14 detailed references. Materialization and entry reads do not prove full skill
execution or output quality. Account-grounded copy, real account bindings,
contact/segment/event variants and repeatability remain unqualified.

## Historical 2026-09-20 parallel skill checkpoint

User explicitly requested supervised parallel implementation now, not four-brand
special cases. Three bounded specialists owned source/composition, media/motion,
and personalization/edit/review. Parent owns runtime routing, source-evidence
projection, integration review and test closure. No additional production agent
roles or per-brand seed catalogs were introduced.

The family map is `knowledge_docs/knowledge/web/skill-families.md`; human validation
records are `subsystems/clue-design/docs/website-skills-*-validation-2026-09-20.md`.
Peer scenario walkthroughs are explicitly unblinded reasoning checks, not live
model runs. They found and corrected tool availability, stale node-state reads,
logo/evidence, release-lifecycle and prompt/rubric contradictions.

At this checkpoint, still required: live ingestion/reproduction, current rendered/behavioral evidence,
standard Docker generation runtime, unseeded fresh-brand onboarding and at least
one held-out-brand case. Full source/node readers, capture-refresh handoff and
remaining source-capture fidelity gaps are explicit. Do not call this complete
because skills are written or contract checks pass.

## 2026-09-21 native platform checkpoint and next gates

The prior standalone gallery is not the delivery surface. Continue through the
normal Head of ABM handoff and Clue design agent in the four workspaces. Preserve
the existing pages and test new changes as native artifacts/versions.

- **Deployed and observed:** the seven families are in the main runtime; Docker
  is working. The four native baseline runs completed with warnings. See
  `subsystems/clue-design/docs/website-native-platform-baseline-2026-09-20.md`.
- **Conduit Fresh bounded proof:** normal company-URL onboarding captured six
  pages and 40 original sections. The native design agent reused six bands,
  obtained the corporate Hyatt wordmark through the logo tool, and saved version
  3 after one exact-href correction. Desktop/mobile inspection and all nine
  rendered CTA destinations were checked. No source assets or completed page
  were manually seeded. Receipts: `.local-setup/conduit-fresh-native/` and
  `_memory/2026-09-21-conduit-fresh-native.md`.
- **Editing capability repaired:** exact active-node reads, independent bounded
  HTML/CSS pagination, and the exact-anchor repair lane now exist. The final
  Conduit correction took 102.8 seconds; this is one successful scoped edit,
  not a general latency or preservation guarantee.
- **Still partial:** Conduit's onboarding research aggregate failed on duplicate
  product aliases. The deduplication fix is tested, but a complete live rerun is
  not verified. Its page has no researched Hyatt account in the project and
  therefore remains a supported named-account invitation.
- **Remaining source capabilities:** design sees selected fragment provenance,
  not a complete capture-time/dependency/motion/coverage manifest or a callable
  ingestion refresh. Keep these gaps explicit and use the governed ingestion
  handoff. Captured HTML/CSS in React output does not recover original React or
  WebGL code.
- **Next qualification:** strengthen account evidence-to-copy use in the existing
  skills, then run native four-workspace tests against their actual source and
  account context. Test detailed media/review references, a source-supported
  motion case with temporal evidence, scoped edits and missing-evidence cases.
  Keep written, loaded, executed and visually accepted status separate.

### Account skill/runtime checkpoint — 2026-09-21

- Added the account-argument reference to the existing personalization family;
  grounded relevance now maps evidence to message, proof, offer and source sections.
- Corrected role-prompt contradictions and exposed the existing governed account
  reads to the delegated web author. Missing cards no longer suppress reads;
  named drafts are distinct from reusable templates; logo binding needs a real ID.
- 112 integrated checks and a later overlapping 35-check final regression passed.
  Final independent source review passed. Native quality remains separately assessed.
- All four normal preparation chats confirmed absent target membership/research.
  Durable account create/import is missing from the current normal UI/API flow;
  do not use browser-only drafts or seed rows as a substitute. Stale zero-budget
  context is not the actual research-launch blocker.
- Completed scoped relevance edits through all four existing native design sessions:
  Clue/AWS/Google saved v2, original Conduit saved v3, each with explicit warnings.
  Durations 215.4–410.5 seconds. Native traces confirm scoped account checks in all
  four and the new account-argument read in three. Corrected tagged-slot guidance
  after native retries (nine Rust contract checks passed; no further paid rerun).
  Account-researched, contact, event, scaling and motion qualification remain open.
  Google recovered a transient CSS namespace defect during raw variant/repair;
  general raw-repair correctness remains a separate reliability follow-up.

## Screenshot evidence checkpoint — 2026-09-21

- Shared bounded image readiness now warms below-fold lazy images before full-page
  previews/review, waits for decode, restores scroll and reports failures. Fully
  clipped inactive images do not delay a capture. No asset/source substitutions.
- Missing or unready image observations keep desktop/mobile findings advisory and
  suppress permanent degraded markers; reduced-motion comparison also waits for
  ready media on both sides. Incomplete previews do not qualify for cache reuse.
- Eight real-browser regressions pass, including an independent mutation control
  that reproduces the blank screenshot when warmup is disabled. The final review
  gates pass 101 checks. Full runtime: 2,729 passed, seven skipped, one unchanged
  exact-docstring assertion failed (recorded in the operational note).
- This is a local implementation checkpoint, not live rollout or source-fidelity
  acceptance. Responsive-only React content was absent from the captured desktop
  HTML; the helper cannot recover it. Preserve separate viewport/state originals
  before adding responsive recapture. CSS-background/video readiness, interactive
  source state recovery and the fresh-brand reproduction benchmark remain open.
