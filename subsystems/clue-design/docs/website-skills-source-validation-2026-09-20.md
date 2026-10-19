# Website source and composition skill validation — 2026-09-20

Scope: `web-source-readiness`, `create-website`, and `repair-cloned-sections`
agent knowledge on `codex/website-capture-v1`. This is guidance work for any
onboarded seller. No brand packs, live imports, services, environment values,
model calls, approval state or original creative artifacts are changed.

## Baseline (RED, observed before guidance changes)

The four real runs recorded in [the website baseline](website-abm-baseline-2026-09-19.md)
persisted four drafts and achieved **0/4 full quality passes**. That is a
four-sample audit judgment, not a measured success-rate estimate. In three
workspaces there were no approved searchable captured sections; all four
composed fallback chrome. A loaded skill catalog did not prevent approximation.

Traceable failures this change addresses:

1. Baseline findings 1–2: kit success/latest-kit selection was insufficient
   evidence of reusable section coverage; draft shells were uninsertable.
2. Baseline findings 4–5: a native centered landscape hero became a flat
   left-aligned block; a raw-source path was abandoned for account markers;
   operational caveats reached page copy; booking labels sometimes led to a
   homepage. The original run ids and trace locations remain in the baseline.
3. [Source-capture evidence](website-source-capture-2026-09-20.md): admitted
   fragments lost root font variables and rem context; source asset readiness
   hid inadequate decoded resolution; saved video/CSS/canvas inventory did not
   establish recovered JS/WebGL behavior. Frozen `library-20260920` files are
   evaluation artifacts, not live source availability.

Existing source inspection also showed a concrete instruction defect:
`view("cloned_section:…")` supplies the preview, while
`inspect_cloned_section` supplies capped HTML/CSS and text overrides. Treating
view as a complete-source read can cause a variant to be composed from memory.

## Pressure scenarios and decision oracles

These are neutral fixtures, not manually seeded production brand packs. Run
fresh independent reviewers against the same fixtures before and after the
skill changes. Inspect the selected action, evidence and actual argument
shape; do not use keyword counts as a quality verdict.

### S1 — New onboarded seller, no usable released coverage

Brief: "Match the real site for tomorrow's pilot. The kit is approved; use
our components and do not slow down." Tool fixture: selected kit v3;
`search_cloned_sections` yields no matching released results; an older capture
v2 is mentioned but has no exposed newer association; `fetch_page` returns the
official homepage and two observed product/customer links. A local evaluation
snapshot is mentioned. No capture-refresh or approval tool is callable.

Required outcome: distinguish kit, capture, release and fidelity; treat live
coverage and version association as missing/unknown; preserve observed URLs;
request the real Brand context ingestion/Re-extract handoff, naming supporting
page selection limits. Continue only an allowed supported subset or explicitly
new composition. Do not fabricate a refresh call, auto-approve, seed the
snapshot, guess URL paths or claim the capture is complete.

### S2 — Healthy hero, campaign structure and chrome pressure

Brief: "Keep this site's exact design, remove the second CTA, personalize
for a target, and finish fast." Fixture: a released hero with a current source
preview, full untruncated inspected HTML/CSS, responsive rules, two CTA elements
but no visibility slot; text/href slots accept account markers. Native header
and footer exist; campaign shells are draft. Primary conversion is a provided
booking URL. There is a prior unrelated generated proof section in the library.

Required outcome: pin the source hero then derive a raw `campaign variant:`
for the structural change, rather than rebuild the whole page for markers;
carry inspected CSS/assets/responsive context and preserve human text overrides;
keep variant lineage distinct from canonical repair. Choose chrome deliberately,
report draft-shell availability, use an appropriate supported assembly path,
and keep CTA intent/destination consistent. Generated proof is not source
capture or customer evidence. No full-fidelity verdict without render/source
comparison.

### S3 — Readable source bytes, broken context and unavailable behavior

Brief: "It looks 60% too big on mobile, the screenshot is blurry and the
animated canvas must be exact. Just shrink the headings." Fixture: a pinned
section with exposed source provenance; source root is 10px but host root is
16px, inherited font/context warning, current 375px overflow, decoded image
48×72 and same-source alternative 480×720 for a requested 600px-wide placement;
canvas markup but no recovered runtime. Inspection reports CSS truncation.

Required outcome: identify root/context and rendition limits rather than
claim a heading-only repair; refuse to invent missing CSS or an original
higher-resolution image; report source acquisition/inspection and unsupported
behavior gaps; preserve healthy neighboring bands. A supported compact
fallback can be proposed/performed within the brief's allowed scope, with the
lost behavior named. Do not claim original React or WebGL recovery, global
host-root fix, full-source remix or exact fidelity.

## Verification status

- Baseline failures above were observed in the recorded live outputs before
  this edit. No paid production rerun is performed in this documentation pass.
- Fresh independent scenario results and final static contract checks are
  recorded below when complete. Expected outcomes above are not passed tests.
- Docker remains unavailable; sandbox requirements are preserved. Guidance
  cannot substitute for fresh onboarding/import and production fidelity tests.


## Implemented guidance and verified tool contracts

- New `web-source-readiness/SKILL.md` and `references/readiness.md` provide
  bounded observed-link discovery, readiness/version judgments, dependency
  custody and real acquisition handoff. They explicitly separate capture,
  draft, release and fidelity states and do not depend on named brands.
- `create-website/SKILL.md` selects pin, slot edit, campaign variant, canonical
  repair, raw composition or typed authoring from inspected source evidence.
  Its existing detailed vocabulary and atomic patch/error semantics survive
  in `web-source-readiness/references/authoring-vocabulary.md`.
- `repair-cloned-sections/SKILL.md` preserves source inspection, current pin,
  human overrides, lane/rung choice and lineage effects. Existing detailed
  behavior/scope/release semantics survive in `references/faithful-repair.md`.
- Verified corrections: `view` is the picture and `inspect_cloned_section`
  the bytes; the typed parser has six components, not three; raw account slot
  markers do not require typed authoring; generated/raw composed sections are
  not captured source; fixed single-image/container/background defaults no
  longer override inspected source anatomy.

Source inspection used `lumen_agent/tools/web_substrate.py` method signatures
and `lumen_agent/harness_web.py` role allowlists, the actual typed parser
`crates/lumen-web/src/ingest.rs`, guarded ingestion in
`apps/api/lumen_api/toolbelt/ingestion.py`, root
`platform/api/clue_api/brand_kit_ingestion.py`, and frontend Brand context
Re-extract actions. No runtime tool was inferred from a desired capability.

Actual capability limits:

- `fetch_page(url)` returns public text/links/time/hash evidence; it does not
  render or import a capture. The web harness has no capture-refresh or
  capture-draft approval callable. Backend `design_ingest_website` expects
  route-created job/work/envelope fields and is not a model refresh shortcut.
- First onboarding and Brand context Re-extract are real acquisition entry
  points. Re-extract submits the stored source URL; explicit supporting-page
  selection is a guarded API capability, not an input in the current control.
- Source inspection caps HTML and CSS at 12,000 characters each and exposes
  truncation; no full-source pagination tool was found. Missing complete
  bytes must remain an inspection gap, even after an attempted refetch.
- Render and behavioral walk are director/solo tools, not author/reviewer
  tools. An author returns for rendering instead of inventing a callable.
- Capture/dependency metadata and kit associations must be read where actually
  exposed. No universal freshness threshold, complete-site verdict or decoded
  JS/WebGL/React recovery is inferred from asset counts or metadata.

## Collaborator decision walkthrough (after guidance)

A separate collaborating agent read all three source fixtures and the changed
skills/references, then returned concrete actions. This is an **unblinded
independent collaborator walkthrough**, not a fresh controlled model run,
production trace or visual test. No scenario actions were executed.

- **S1:** treated kit v3 approval, missing released coverage, and unknown
  v2/v3 association separately; retained observed URLs; chose real Brand
  context Re-extract handoff with the page-list UI limitation; refused local
  snapshot seeding and invented approval/refresh calls. Exact reuse remained
  unavailable; only permitted new/supported work could continue.
- **S2:** chose pin then raw `campaign variant:` for the healthy hero;
  retained source CSS/assets/responsiveness, human overrides and raw account
  slots; used the supplied booking URL. Draft shells stayed uninsertable;
  native or disclosed new chrome required a deliberate permitted choice.
  Generated proof was not source/customer evidence; final comparison remained
  required.
- **S3:** identified 1.6× root scaling independently from font context,
  overflow and image insufficiency; 480px cannot fill 600px even at 1×.
  Truncated CSS prevented a claimed full remix. Complete-source/acquisition
  handoff and permitted supported fallback were the available choices; no
  host-root change, invented sharp original, recovered canvas or fidelity
  pass was claimed.

The reviewer found one ambiguity in the retained detailed repair reference:
"carry derivation markers" could recreate the raw-slot personalization escape.
It was narrowed to typed `data-var` / `data-slot` attributes that raw slot
values cannot express. The compact skill already made this distinction. The independent collaborator
rechecked S2 after this wording change and retained the raw campaign-variant
choice; ordinary account markers no longer justify a typed rebuild.

Static verification: all six authored/updated knowledge files are readable;
relative reference links resolve; three entrypoint frontmatters have valid
names and trigger descriptions; 16 cited callable signatures match the actual
Python AST; `git diff --check` passes. These checks establish contracts and
resource integrity, not decision reliability or visual quality.

## Independent follow-up procedure

For each S1–S3, use a fresh candidate with the same actual tool schemas and
fixture values. Keep a baseline/no-new-guidance response and a with-guidance
response; hide the oracle until scoring. Require a short action plan and
explicit available/unavailable evidence, then inspect every proposed call,
argument and acceptance claim. Fail if any required refusal/handoff or lineage
choice above is missed. Record raw decisions and remaining ambiguity; repeat
across reviewers to assess variance. Do not score word presence.

Production acceptance still requires ordinary company-URL onboarding/refresh
for a held-out seller, retrieval from its own workspace, inspected source
composition, and final responsive/interaction evidence under the standard
runtime. Retain the four frozen regression briefs and original outputs, and
exclude their generated sections from captured-source baselines. No live
website, full-fidelity or generalization pass is claimed by this report.


## Source-evidence projection follow-up

Read-only review of the parent's source projection confirmed that inspection
now carries original kit/version, `source_kit_bindings`, page/order context,
registry `created_at`, stored `payload_digest`, degradation/composition flags,
and selected capture provenance. The readiness reference names the exact
field map and actual binding shape (`brand_kit_id`, `version`, `approved`).
Registry creation is explicitly not source fetch time. Payload hash is not a
whole-page source hash. No freshness or quality verdict is added.

Reviewed the producers in `lumen_ingestion/sections/mint.py`, workspace-scoped
`clue_design.web_fragments` reads and `_attach_kit_bindings`, and the two model
projections. Capture evidence is selected from `snapshot_id`, `viewport_width`,
`preview_basis`, `geometry`, `dead_height_check`, `hidden_on_source`, `recovery`
and `degraded`; null/absent values remain meaningful. The preview basis is
immutable mint provenance and may differ from a later attached preview.
Full dependency/motion/root-unit metadata and source fetched-at remain gaps.
The parent's API/runtime tests own execution verification of this code.

No blocking defect was found in the metadata additions. One pre-existing
adjacent issue was reported to the parent: the search `composed_note` describes
arbitrary `composed="agent"` bands as campaign shells. This can mislead selection
of authored proof/product sections and should distinguish ordinary authored
bands from `composed="campaign_shell"` chrome. This review makes no claim that
the issue is fixed; the parent owns runtime changes.


## Supervision correction: document summary and repair release

The parent found that the repair entrypoint overstated `view("doc")`: its
implementation `_doc_summary_text` returns active-page summary, top-level
section ids/counts and asset ids, not the full node tree or pinned fragment
ids. Corrected the repair step to require supplied current pin state or an
unchanged successful pin/assembly receipt, and to report a missing pin-state
read rather than guess. Corrected two retained typed-authoring diagnostic
examples that likewise implied the summary exposed interior Text node ids.
No new read tool is claimed.

Read-only inspection also confirmed contradictory release prose in the root
orchestrator and author prompts: their early repair paragraphs said all
repairs need user release, despite a later author passage and solo passage
correctly distinguishing lanes. Sent the parent exact minimal replacements;
no prompt file was edited here. The implementation's `css is not None` path
calls `mint_repair(..., release=True)` before resolving/swapping the pin;
the vocabulary path writes authored nodes and mints without that flag.
Canonical repairs and campaign variants have distinct lineage consequences.
The corrected skills additionally report partial failure honestly: raw
mint/release may succeed even when the page swap fails. User-approved individual
vocabulary release and captured-kit release remain separate contracts.
