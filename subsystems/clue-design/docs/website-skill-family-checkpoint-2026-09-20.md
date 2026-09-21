# Supervised website skill-family checkpoint

Status: implemented in `codex/website-capture-v1`, offline integration checked;
not deployed to the four workspaces and not a production visual-quality pass.
The four brands are regression samples, not supported-brand boundaries. No
customer-specific asset packs were seeded by this work.

## Scope and supervision

Three specialists owned disjoint files: source/composition, media/motion, and
personalization/edit/review. Parent inspected their changes, owned shared runtime
routing and tests, and requested independent collaborator reviews. Reviews found
real errors before integration: imaginary reads/tools, full-page work for small
edits, wrong assembly/release assumptions, unsupported relationship claims and
false motion/fidelity acceptance. Corrections and limitations remain in the three
`website-skills-*-validation-2026-09-20.md` records.

These were unblinded collaborator decision walkthroughs. They do not count as
controlled fresh-model experiments, executed production workflows or visual passes.
No model/provider calls or live database/service/env mutations were made here.

## Family inventory

| Family | Responsibilities | Entry skills |
|---|---:|---|
| Source readiness | 4 | web-source-readiness |
| Source-faithful composition | 4 | create-website, repair-cloned-sections, campaign-page-workflow |
| Media composition | 4 | web-media-composition |
| Motion fidelity | 3 | web-motion-fidelity |
| Account/campaign personalization | 3 | web-account-personalization, campaign-landing-page, conversion-copywriting |
| Scoped editing | 3 | edit-website |
| Fidelity review | 3 | review-website |
| Total | 24 | 11 entries: 4 new, 7 updated; 14 detailed reference files |

These are skills over the existing tool surfaces, not 24 agents or 24 new tools.
Solo mode stays solo; existing author/reviewer roles remain conditional on runtime
configuration. New/rebuild, local edit and review turns get conditional routing.
Detailed skill references survive actual workspace materialization and remain
available on demand. Shared copy craft remains usable for scenes/ads.

The source tools now expose existing kit associations, origin, registry creation
time, payload digest and selected capture evidence. They do not equate kit approval
or registry birth with source freshness/fidelity. Authored product sections are no
longer mislabeled as campaign shells. No approval or tenancy gate was weakened.

## Verification

- 221 integrated runtime checks passed, zero failures/skips: skill delivery,
  all role prompts, clone tools, solo/trio behavior, account assembly, logo binding,
  review gate, grammar and brand-brief integration.
- 24 focused prompt/packaging checks passed again after final wording changes.
- Full backend cloned-section registry suite passed against the disposable
  website-capture database, including new provenance projection checks.
- Whitespace clean; new test module lint/format clean. Existing full-file lint
  debt was not rewritten; no lint findings in changed lines.
- Initial failures were preserved in ignored XML evidence: one obsolete prompt
  assertion, plus four review tests missing the isolated Tailwind browser bundle.
  The final run used that existing local bundle explicitly and passed. New metadata
  and composed-section regressions failed before their fixes and passed afterward.

Evidence: `.local-setup/website-capture/skill-integrated-tests.xml` and
`skill-final-prompt-tests.xml` (ignored evaluation outputs).

## Remaining acceptance work

1. Restore the standard Docker generation prerequisite; it is absent. Do not
   substitute an unsandboxed runner or count offline tests as live generation.
2. Finish capture/reproduction gaps and import expanded sources through governed
   ingestion. Frozen evaluation captures are not a finished live brand library.
3. Run fresh URL onboarding and all four brand cases through the actual pipeline;
   add a held-out brand to detect hardcoded assumptions. No manual asset seeding.
4. Compare final desktop/mobile output, image resolution/crop, typography, logos,
   real CTA destinations and supported motion against source evidence. A static
   state image alone cannot prove activation or playback.
5. Add a scoped current-node reader/full-source read as needed: `view("doc")`
   remains summary-only and source inspection remains capped. Without actual
   current payloads, skills must preserve content and report the read gap.
6. Prove account binding/derivation, repeatability, tenancy and contact-use limits.
   Only then can the requested production-quality scope pass.
