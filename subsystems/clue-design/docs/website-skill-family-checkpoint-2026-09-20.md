# Supervised website skill-family checkpoint

**Current status, 2026-09-21:** all seven families / 24 responsibilities are in
Clue's main `codex/design-agent-v1` runtime: 11 entry skills and 15 detailed
references. Native runs have used them, but the complete four-brand source,
motion and account-personalization quality target has not passed. Continue
implementation and testing in the Clue platform, not the standalone gallery.

**Historical 2026-09-20 authoring checkpoint:** implemented in
`codex/website-capture-v1`, offline integration checked, not yet deployed to the
four workspaces. The scope, verification and remaining-work lists below record
that checkpoint; the dated native update at the end supersedes its deployment,
Docker and current-source-reader status.
The four brands are regression samples, not supported-brand boundaries. No
customer-specific asset packs were seeded by this work.

## Historical scope and supervision

Three specialists owned disjoint files: source/composition, media/motion, and
personalization/edit/review. Parent inspected their changes, owned shared runtime
routing and tests, and requested independent collaborator reviews. Reviews found
real errors before integration: imaginary reads/tools, full-page work for small
edits, wrong assembly/release assumptions, unsupported relationship claims and
false motion/fidelity acceptance. Corrections and limitations remain in the three
`website-skills-*-validation-2026-09-20.md` records.

These were unblinded collaborator decision walkthroughs. They do not count as
controlled fresh-model experiments, executed production workflows or visual passes.
No model/provider calls or live database/service/env mutations were made during
that authoring checkpoint. Subsequent native runs are recorded separately below.

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
| Total | 24 | 11 entries: 4 new, 7 updated; 15 detailed reference files |

These are skills over the existing tool surfaces, not 24 agents or 24 new tools.
Solo mode stays solo; existing author/reviewer roles remain conditional on runtime
configuration. New/rebuild, local edit and review turns get conditional routing.
Detailed skill references survive actual workspace materialization and remain
available on demand. Shared copy craft remains usable for scenes/ads.

The source tools now expose existing kit associations, origin, registry creation
time, payload digest and selected capture evidence. They do not equate kit approval
or registry birth with source freshness/fidelity. Authored product sections are no
longer mislabeled as campaign shells. No approval or tenancy gate was weakened.

## Historical offline verification

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

## Acceptance work identified at the authoring checkpoint

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

## Native deployment and qualification update — 2026-09-21

The skill files and conditional routing now run in the existing Clue design
agent. Docker Desktop and the standard sandbox were restored; normal chat
handoffs produced native website artifacts in Clue, AWS, Google Cloud and
Conduit. No independent page implementation or customer-specific seed catalog
was substituted. The historical “not deployed” and “Docker absent” statements
above no longer describe the runtime.

| Family | Written/routed | Native evidence and remaining limit |
|---|---|---|
| Source readiness | 4 responsibilities | Entry read in all four baselines; Fresh Conduit used newly captured/released sources. Detailed readiness reference was not read in audited runs. Full capture/dependency/motion manifest and design-owned refresh remain unavailable. |
| Source-faithful composition | 4 responsibilities | Creation/workflow used in all four; repair used in Clue/Google and later Conduit. Fresh Conduit reused six original bands. Older Clue/Google baselines mostly reused previously composed sections, so they did not prove original-site fidelity. |
| Media composition | 4 responsibilities | Entry read in all four; Fresh Conduit visibly retains real product imagery and the corrected Hyatt corporate mark. Neither detailed media reference was read in the audited runs. Four-brand crop/resolution/identity acceptance remains open. |
| Motion fidelity | 3 responsibilities | Entry and both references are available but no audited native run read them. Still/forced-state captures do not prove source playback, full interactions or WebGL recovery. |
| Account/campaign personalization | 3 responsibilities | Entries and some copy/evidence references were read. Projects in these tests lacked researched target-account rows; outputs are named invitations, not verified account-derived pages. Contact, segment, event and batch behavior remain untested. |
| Scoped editing | 3 responsibilities | Later Conduit corrections read the edit guidance. Fresh version 3 proves one precise inherited-link change while preserving the band. General repeatability, concurrency and latency acceptance remain open. |
| Fidelity review | 3 responsibilities | Review entry read in initial four baselines, but their complete source comparison was unavailable. Neither detailed review reference was read in audited receipts. Fresh Conduit desktop/mobile and links were inspected; this does not qualify all pages or motion. |

Across the original four native runs and subsequent Conduit edits, **10 of 11
entry skills** have an observed read; `web-motion-fidelity` does not. Across the
original four runs plus Conduit Fresh's initial and two correction traces,
**six of 14 detailed references** have an observed read. The eight without an
observed read are source readiness, both media references, both motion references,
audience modes and both review references. Read coverage is execution evidence,
not a visual-quality score or a reason to load every reference on every small edit.

### Fresh Conduit proof and limits

Normal onboarding from the company URL captured the homepage, Agents, Inbox,
customer index and two customer stories. Forty original sections were approved
through the native brand UI. Clue's own design agent created a page from six
captured bands and authored campaign chrome. It then fetched the Hyatt corporate
wordmark through the normal logo path and saved version 3 after a scoped link
repair. All nine rendered CTA destinations were checked against the real Conduit
demo URL, with desktop/mobile styling and source product visuals preserved.
The last correction took 102.8 seconds; no new raster generation was needed.

This is bounded one-brand native evidence. It does not establish four-brand
source fidelity, deep Hyatt research, motion fidelity, publishing, or successful
completion of the full research onboarding aggregate. The latter failed on
duplicate product aliases; its generic deduplication repair is tested but not
yet proven by a full live rerun.

The old current-node/full-source-read gap is partly closed: `view("node:<id>")`
returns complete bounded active-turn node state; `inspect_cloned_section`
supports independent 12,000-character HTML/CSS pagination; the exact-href repair
lane avoids retranscribing entire source bands for anchor destination fixes.
These are real tools, not additional skill counts. Source acquisition/refresh,
complete capture evidence and temporal motion verification remain separate
capability/acceptance work.

Evidence: `website-native-platform-baseline-2026-09-20.md`,
`.local-setup/native-website-runtime/native-run-trace-audit.json`,
`.local-setup/conduit-fresh-native/native-run-trace-audit.json`,
`native-correction-trace-audit.json`, `native-link-repair-trace-audit.json`, and
`_memory/2026-09-21-conduit-fresh-native.md`. The local receipts are ignored
operational evidence; they are not seeded brand assets or a delivery surface.

### Native account-evidence implementation — 2026-09-21

The fifteenth reference, `web-account-personalization/references/account-argument.md`,
connects accessible target evidence to the reader's decision, seller mechanism,
proof, section choices and actual offer. It distinguishes named identity, supported
task relevance, researched account context and governed contact relevance. Internal
audit caveats belong in the handoff, not visitor copy; removing one cannot strengthen
an unsupported claim. Existing source geometry, product media and logos remain protected.

All three authoring-role prompts now route to scoped account reads even without a
target card. The delegated web author receives the same injected read tools as
the director. Direct turns without an injected provider receive none. Single-account
drafts no longer have to masquerade as reusable templates, and logo binding requires
a real mapped account ID. Registered assets still persist without a binding.

Validation: 112 integrated runtime checks passed, then 35 focused checks passed
after the final logo-binding corrections (overlapping sets, not 147 unique tests).
The new packaging/reference and logo-binding regressions failed before their fixes.
Independent source review found no remaining issues in the final prompt and clone-search
documentation changes. These checks establish delivery and behavior contracts, not
four-brand visual or researched-personalization acceptance.

Normal Head-of-ABM preparation chats were run in all four workspaces. None had the
requested target account ready for research. Project Add accounts selects existing
workspace accounts; workspace New account currently creates an unsaved browser draft.
The durable create/import API remains a documented platform gap. The reported zero
conversation budget is stale context, not an ARV2 launch gate. No discovery, manual
database seeding or research launch was used to bypass these prerequisites.

Four new native scoped-edit tests completed against the existing drafts:

| Workspace / target | Saved version | Duration | Bounded result |
|---|---:|---:|---|
| Clue / Google | 2 | 317.8 s | Existing source slots rebound; seven bands and assets preserved. |
| AWS / Insight Health | 2 | 259.3 s | Internal caveats removed; supported public product/task relevance retained. One malformed asset slot write refused before recovery. |
| Google Cloud / NVIDIA | 2 | 410.5 s | Caveats removed; two malformed slot writes refused. A derived section briefly lost CSS scoping; a later repair restored its layout. |
| Conduit / Hyatt | 3 | 215.4 s | Text-node edits retained logo, product images and layout; clearer guest-operations explanation. |

All four returned `completed_with_warnings`, checked project account membership
and found no target rows. Three explicitly read the new account-argument reference;
Clue used editing/copy guidance without reading that addition in this turn. Thus
the new reference's universal uptake is not proven. There were no new raster
generations, discovery/research launches or publishes. Prior versions remain.

Parent inspected the four native desktop outputs, Conduit's mobile preview and
Google's working in-page CTA. Each native run produced its own responsive render
review, which is self-review evidence rather than independent source acceptance.
AWS's browser session needed a refresh before viewing its saved result. Original
source fidelity, motion playback, real account research and cross-account reuse
are still unqualified. These are useful task proposals, not deep account research.

The failed slot writes led to a generic editing-reference correction: pinning
inputs are plain values, but `web_ops` fragment slots are one-key tagged objects
(`text`, `asset`, `visible`). Nine existing Rust schema/override tests passed.
This documentation correction was not re-exercised in another paid native run.
The general raw-repair CSS/no-op behavior remains a separate reliability follow-up.
Receipts: `.local-setup/native-account-skills/`.
