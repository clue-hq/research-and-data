# Editable Ad Quality — Linear ticket pack

Status: prepared locally; no team, project, milestone or issue has been created in Linear by this task. `CT-01`–`CT-10` below are planning keys, not Linear issue identifiers.

## Project setup

- Workspace: existing Clue HQ workspace; verify its ID through MCP before writing.
- Team: Product Engineering. Preferred identifier `PE`, subject to availability. Check for an existing matching team before creating it.
- Project: Editable Ad Quality — Control Test.
- Summary: Compare four generation treatments, preserve editable copy/logo/button layers, and select a brand-directed creative harness using rendered and editing evidence.
- Dates: September 7–8, 2026, America/Los_Angeles. First comparison on the first working night is a target; do not silently mark unfinished work complete when the date passes.
- Initial status: Planned; issues Todo. Leave people unassigned until ownership is agreed. Do not assign work to Aryan or Fable implicitly.
- Milestones: Control ready; First comparison tonight; Editability and generalization; Decision and handoff.
- Scope: local development in the existing checkout; no paid advertising, production rollout, remote push or new worktree.
- Success: every required editing gate passes, candidate creative is preferred over the fresh baseline, costs/timings and failures are recorded, and broader coverage is demonstrated or explicitly left open.

The product contract allows generated raster backgrounds/imagery, with native editable headline/support/CTA text, separate logo and button layers, and independently transformable artwork. Exact UI/screenshots/vector assets may remain original assets. No full-ad bitmap may substitute for the editable scene.

The [design](../specs/2026-09-07-editable-ad-control-design.md) and [implementation plan](2026-09-07-editable-ad-control.md) are the technical source of truth for this pack.

## CT-01 — Freeze the control cases and verify Fleet dispatch readiness

**Priority:** High. **Milestone:** Control ready. **Dependencies:** none. **Plan:** Task 1.

Establish comparable inputs and ownership before changing creative policy. Four live workers and database/Redis connectivity have been observed, but a fresh experiment claim and completion have not yet been demonstrated.

Acceptance:

- [ ] One case records objective, audience, message, sourced claims, pinned brand kit, format, exact source assets and separately identified style references.
- [ ] Code/model/resource/input digests are recorded without credentials; uploaded references pass normal asset custody.
- [ ] A Clue control project owns distinct A–D chats/documents/checkpoints; existing user work remains intact.
- [ ] Worker registrations, queue state and database identity are recorded at launch; fresh claim/lease/finish proof is required in CT-07.
- [ ] Inputs and generated private media remain ignored; only generic contracts/fixtures enter Git.

Evidence: manifest, ownership read-back and timestamped readiness report. Do not mark generation successful based on port health.

## CT-02 — Freeze experiment policy per run through the existing Design envelope

**Priority:** High. **Milestone:** Control ready. **Dependencies:** CT-01. **Plan:** Task 2.

Current runtime configuration comes from process environment. Mixed treatments need isolated, immutable run configuration so concurrent runs cannot inherit one another's policy.

Acceptance:

- [ ] A server-owned project/workspace-scoped manifest is resolved by the API and frozen by value at offer time.
- [ ] Allowlisted treatment configuration preserves ordinary-run defaults; unknown/cross-scope/digest-mismatched input refuses before provider calls.
- [ ] A concurrent A/D regression proves independent policy and reviewer settings in one process.
- [ ] Retry/resume uses frozen resource bytes and pins even when the active candidate changes.
- [ ] Shared dispatch/config changes have one integration owner and pass existing Fleet/design tests.

Evidence: focused tests, reviewed scoped commit and manifest digest. No process-global environment mutation during a comparison.

## CT-03 — Select relevant references from the pinned brand

**Priority:** High. **Milestone:** First comparison tonight. **Dependencies:** CT-01, CT-02. **Plan:** Task 3, initial scope.

The audited ad path can select workspace-wide references and reuse the first four images across style groups. This can hide strong ingested assets or select irrelevant artwork.

Acceptance:

- [ ] A two-brand test proves another brand's newer ad cannot enter the selected brand's reference set.
- [ ] Manual references retain precedence and exact asset identity; each style group receives its own relevant images.
- [ ] Descriptors record concept, composition, product relevance and asset role; reference selection is inspectable.
- [ ] Empty, mismatch, partial and provider-failure outcomes remain distinguishable.
- [ ] Tonight's curated references work through existing custody/attachment tools; automatic harvesting integration is tracked in CT-09.

Evidence: regression tests plus the actual selected reference set and selection reasons for each run.

## CT-04 — Add a concept and layer plan to the candidate Design policy

**Priority:** High. **Milestone:** First comparison tonight. **Dependencies:** CT-02. **Plan:** Task 4.

The engine supports more composition than the active square-ad instructions allow. Candidate policy should choose a composition from business intent and references while retaining a usable editable scene.

Acceptance:

- [ ] The director records concept, sourced message, copy, format, copy zones, asset roles and intended layers before artwork generation.
- [ ] C/D may use editorial, product demonstration, proof/review and launch compositions without a mandatory left-image/right-text split.
- [ ] A/B keep frozen baseline policy; no brand name or reference layout is hardcoded into production behavior.
- [ ] Main copy, logo and CTA are separate layers; useful native button/card/chip/device fragments compile and remain independently selectable.
- [ ] Awareness concepts can omit a button when appropriate; exact user wording and supplied proof are preserved.

Evidence: candidate resource digests, plan artifacts, compile tests and source scene inspection.

## CT-05 — Generate artwork by role and preserve multiple variants

**Priority:** High. **Milestone:** First comparison tonight. **Dependencies:** CT-03, CT-04. **Plan:** Task 5.

Produce useful artwork components while allowing users to edit the main ad copy and replace the imagery.

Acceptance:

- [ ] Prompts distinguish exact subject/product assets from style references and reserve intentional space for copy.
- [ ] Required headline/logo/CTA content is composed by the scene author rather than requested inside the artwork bitmap.
- [ ] C/D each retain two initial artwork variants with independent asset IDs, provenance and replaceable scene bindings.
- [ ] Cache identity includes scoped inputs, references, artwork role, model/settings and policy version.
- [ ] Existing provider parameters remain pinned; errors/refusals are recorded, with no placeholder counted as a success.

Evidence: provider/custody tests and variant asset records. Transparent output or masks require verification against the configured provider endpoint before use.

## CT-06 — Add structural editability gates and a reference-aware review

**Priority:** High. **Milestone:** First comparison tonight. **Dependencies:** CT-02, CT-04. **Plan:** Task 6.

A screenshot can look good while containing uneditable copy. Combine structural scene checks with visual judgment; use the existing independent scene reviewer for D.

Acceptance:

- [ ] Native text plus separate logo/button/image layers passes; flattened or outlined-only required copy fails.
- [ ] Wrong brand, missing required assets/fonts, invented claims and lost ownership are hard failures.
- [ ] Existing brand-fidelity functions receive explicit pinned kit input; no implicit legacy database lookup is used.
- [ ] Visual grading sees brief, relevant references and rendered scene with anchored 1–5 dimensions and rationale.
- [ ] D gets one bounded review/repair; C does not. Neither critic scores nor attractive pixels override a hard editing failure.

Evidence: real scene fixture tests, rubric and independent reviewer traces/costs.

## CT-07 — Run the matched four-treatment comparison through Fleet

**Priority:** High. **Milestone:** First comparison tonight. **Dependencies:** CT-02, CT-03, CT-04, CT-05, CT-06. **Plan:** Task 7, dispatch and evaluation.

Compare the same case across A current system, B curated references, C candidate creative/layer harness, and D C plus review. These are treatment packages; one batch is exploratory.

Acceptance:

- [ ] Runner uses normal authenticated offers, at most four concurrent runs, isolated document/checkpoint ownership and idempotent retries.
- [ ] Freeze the integrated checkpoint before starting; do not edit shared policy or restart workers during the batch.
- [ ] Every run has a fresh offer, claim owner/generation, lease evidence, terminal outcome and real scene/artifact references.
- [ ] Capture first usable preview, total time, calls, generated variants, repairs, cache/throttling and actual available cost data.
- [ ] Retain all results and failures; compare blind against a fresh baseline and repeat the useful contrast before asserting consistent improvement.

Evidence: run-view outputs, comparison table, manifests and traces. Four different creative concepts alone do not satisfy this experiment.

## CT-08 — Prove editing, persistence and export in the Codex browser

**Priority:** High. **Milestone:** Editability and generalization. **Dependencies:** CT-07. **Plan:** Task 7, browser acceptance.

Verify the actual user promise on a generated candidate, including after save and reload.

Acceptance:

- [ ] Change headline and CTA copy/style using native editor controls.
- [ ] Move/resize the separate logo and verify unrelated content remains intact.
- [ ] Replace an image with its other generated variant and adjust its crop/placement.
- [ ] Save/reload and confirm each edit persisted; record scene versions and browser errors.
- [ ] Export and compare against the editor for font, crop, clipping and layer placement. Source text remains live; ordinary PNG/JPEG export may flatten.

Evidence: before/after screenshots, source structure, persisted scene version and export inspection. Do not infer editing support from visible handles alone.

## CT-09 — Validate onboarding fallback, other brands and format adaptation

**Priority:** High. **Milestone:** Editability and generalization. **Dependencies:** CT-03, CT-07, CT-08. **Plan:** Tasks 3 and 8, second-day scope.

Generalize the selected candidate beyond the supplied brand and ensure reference availability does not determine whether the feature works.

Acceptance:

- [ ] Existing LinkedIn ingestion is offered through the brand-onboarding seam with idempotency and distinct empty/partial/mismatch/failure reporting.
- [ ] A no-ad-history case produces an honest brand/website-led fallback; it does not claim it retrieved ads.
- [ ] A different real brand and a different concept are evaluated; if unavailable, clearly limit conclusions to synthetic mechanics.
- [ ] Square, portrait and landscape recomposition pass copy-fit, asset-crop, logo and CTA checks; add placement safe areas when needed.
- [ ] No cross-brand reference contamination or branch-specific branding assumptions appear.

Evidence: onboarding tests, brand/format matrix and repeat comparisons. Additional ad-library providers remain separate follow-up scope.

## CT-10 — Record the decision and preserve the ABM-to-Design handoff

**Priority:** High. **Milestone:** Decision and handoff. **Dependencies:** CT-08, CT-09. **Plan:** Task 8.

Close with a measured configuration decision and a clear boundary for the ongoing Head-of-ABM skill work.

Acceptance:

- [ ] Document Head-of-ABM's business brief/source ownership and Design's concept/copy/composition ownership using the verified current path.
- [ ] Any handoff improvement preserves objective, audience, exact copy, offer/CTA, requested formats and governed source refs; changes use new immutable catalog versions.
- [ ] Record resource pins and the contract to coordinate with Fable; no message to collaborators, assignment or profile promotion is implied.
- [ ] Required checks pass on changed surfaces; the known public-asset test-environment failure remains explicit until independently resolved or clean-environment verified.
- [ ] Decision links hard gates, human preference, quality scores, costs/timings, repetitions and unresolved limits. Only completed work is marked Done.

Evidence: final decision report, scoped local commits and verified Linear read-back. Website work and production rollout remain separate steps.

## Creation and verification procedure

Use MCP to inspect workspace/team/project duplicates, then create the missing team/project and milestones. Create issues in dependency order, saving returned IDs and URLs in an ignored receipt before adding relations. If an operation has an uncertain outcome, read it back before retrying. Map every planning key to the real Linear identifier; never invent one.

Read back descriptions, dates, team membership of the project, priorities, milestone placement and dependency relations through MCP. Use browser control to verify Product Engineering, the project overview and the complete issue list. Team creation may require a UI operation if the connected MCP does not expose it; identify that capability gap before using a different write method.

Connection evidence on September 7: Linear 5.0.1 exists in Codex's plugin cache and its manifest points to `https://mcp.linear.app/mcp`. The user confirms Installed and connected in Codex. An initial browser account showed Install plugin. After the user switched to the intended account, browser verification showed Linear under Installed, with Try in chat and issue/project/milestone action definitions. This supersedes the initial browser result. The task still exposes no callable Linear MCP tools; installation is verified, but an authenticated MCP invocation is not. No installation, credential change or external project write has been performed by the agent.
