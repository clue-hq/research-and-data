# Preserve responsive website source states

Status: proposed architecture for review. No responsive recapture, migration,
generation, or platform restart has been performed for this proposal.

## Outcome and scope

Clue should capture the real content and assets a brand website presents on desktop
and mobile, retain the originals, and let its existing design agent reproduce those
states inside native React artifacts. The implementation must work for new brands;
Conduit Fresh is the current permitted live acceptance workspace. The suspended
older workspaces and the cancelled ordinary-prompt run remain untouched.

This extends the approved website capture/reproduction goal. It does not add a
second design agent, a standalone renderer, seeded brand markup, or a new research
workflow. Source acquisition, reusable-fragment readiness, and visual acceptance
remain separate statuses.

## Verified defect and current seams

- `lumen_ingestion/pipeline.py::_ingest_website` already forces rendered capture
  for every website ingestion. Static-tier escalation is not the missing step.
- `capture/rendered.py` captures one browser state. Its default stealth backend
  owns a coherent desktop fingerprint; overriding that existing viewport previously
  broke source WebGL rendering. It must remain intact.
- Conduit's desktop capture contains an empty mobile product branch apart from its
  background. The live source mounts the chat demo only when loaded at a mobile
  width. Waiting longer or repairing CSS cannot recover that missing DOM.
- `capture/snapshot.py::SiteSnapshot` contains one HTML/CSS/geometry/screenshot
  bundle. `site_snapshot.py::site_snapshot_id` and the design DAL key its custody on
  `(job, page URL)`. Adding another ordinary snapshot for that URL overwrites it.
- Section provenance currently identifies `snapshot_id`, `page_url`, viewport and
  DOM path. Source-flow reconstruction resolves paths inside that single frozen
  snapshot. A path from a mobile capture must never resolve against desktop HTML.
- `_SERIALIZE_HTML_JS` freezes observed SVG paint and removes hidden SVG nodes.
  That protects extracted logo appearance at the captured state; it is not proof
  that the resulting HTML supports a different responsive state.
- Local commit `b5b4837f` repairs lazy-image readiness in screenshots/review. It
  does not recover content absent from the source capture.

Paths above are relative to `subsystems/clue-design/apps/api/`, except the design
DAL, which is `subsystems/design/clue_design/site_snapshots.py`.

## Options

1. **Recommended: state manifests under existing page custody.** Keep the current
   desktop row and identity. Store immutable, content-addressed state manifests and
   their referenced bytes through the existing workspace-scoped design storage
   seam. Add bounded state references to page metadata. This preserves current
   callers and requires no live database migration.
2. Add a dedicated capture-state table and migration. This provides first-class
   relational queries but changes the database contract and operational deployment
   before the state consumer is proven. Reconsider if state lookup/retention needs
   outgrow the bounded manifest approach.
3. Append mobile snapshots to the existing page list, or invent URL fragments to
   distinguish them. Reject: the first overwrites custody; the second corrupts page
   identity and can contaminate page-role budgets and source provenance.

## Capture and budget contract

- Capture the existing desktop state first without modifying the stealth context.
- Capture mobile by fresh navigation in an independent Chromium context with a
  coherent mobile viewport, screen, touch and user-agent profile. Record the actual
  observed dimensions and backend. Do not resize the already-hydrated desktop page
  and call that independent mobile evidence.
- One mobile state is planned per selected page. A tablet state is conditional on
  observed source breakpoints/structural differences, with a hard maximum of two
  additional states per page. Missing tablet evidence stays explicit.
- Freeze a versioned capture policy in new ingestion requests. Old frozen requests
  keep their recorded behavior. The policy names profile IDs, widths, state limits
  and time/byte budgets; it contains no brand-specific selectors or assets.
- Proposed additional-state limits: 30-second navigation timeout, 60-second total
  state-capture deadline, and six minutes of additional capture work per ingestion
  job. Existing page, HTML, asset, network and fragment budgets still apply. Finish
  planned mobile states before optional tablet states so tablet work cannot consume
  the budget needed by the other selected pages.
- Each state follows existing URL/network guards, bounded scrolling, overlay
  handling, dependency capture and geometry collection. Byte accounting includes
  additional states; cached/shared dependencies are not downloaded repeatedly.
- Coverage records `captured`, `failed`, `budget_exhausted` or `not_requested`, with
  the profile, observed viewport, diagnostic and artifact references. Failed mobile
  acquisition never discards successful desktop evidence or reports fidelity success.
- No change silently re-enqueues completed ingestion or starts design generation.

## Durable state identity and reads

Each immutable manifest has a schema version, owning page-snapshot/job IDs,
profile ID, requested/final URL, capture timestamp, observed viewport, backend, HTML digest, ordered stylesheet
descriptors, screenshot digest, asset descriptors, geometry and capture diagnostics.
Its content digest is its state identity. The manifest and every referenced byte
use the existing `design_site_snapshot` storage source and workspace authorization.

Page metadata carries bounded references to these manifests. The desktop fields
and existing read signatures retain their meaning. Add explicit state-aware read
operations; a caller selecting a state receives that state's complete bytes and
geometry, or a typed missing/foreign-state refusal. It never falls back silently to
desktop. The reader validates manifest schema, digest, page identity and workspace
ownership before exposing content.

Fragment provenance stores the immutable state-manifest reference alongside the
existing page/snapshot identity. All source-path resolution, screenshot comparison
and repair reads use that state. A later re-offered capture may update the page's
current manifest references but cannot change the bytes addressed by a fragment's
older immutable reference. Existing desktop-only fragments continue to resolve
through their legacy snapshot path; they acquire no invented mobile proof.

Extract byte registration/loading into shared private helpers so desktop and
additional states cannot diverge in CSS ordering, asset validation, media custody
or tenant enforcement. Do not copy the persistence pipeline into a second module.

## Reuse inside native website artifacts

Capturing variants is necessary but does not by itself make them reusable.

1. Segment each successful state against its own DOM and geometry. Allocate the
   existing page/library fragment budget across states; do not multiply it by the
   number of profiles. Report states that were captured but not minted.
2. Match candidate sections using stable source IDs and compatible ancestry,
   supported by structure and content evidence. DOM path or heading equality alone
   is insufficient. Ambiguous matches remain separate candidates.
3. A responsive derivative may fill a missing source branch only with bytes captured
   from its matched state, retaining source visibility rules and original versions.
   A mobile placeholder with a background is not permission to invent a chat demo.
4. When source visibility rules cannot establish which variant belongs at a width,
   retain the alternatives and report the gap. Sample widths do not establish the
   original breakpoint. Do not assume every brand uses a 768px breakpoint.
5. Responsive composition must preserve CSS scoping, unique IDs, asset references,
   accessible visibility and slot bindings. One account/headline edit must update
   corresponding visible states consistently. Original source fragments remain
   immutable, and the derivative records all contributing state identities.
6. Preview, editor and export consume the same normal native artifact definition.
   No preview-only injected HTML or source-script replay is permitted.

Custom JavaScript behavior, WebGL programs and uncaptured interaction states remain
unsupported unless separately reconstructed through supported native components
and verified against recorded evidence. A screenshot of animation is one state,
not proof that the animation was recovered.

## Verification and promotion

Implementation proceeds in three reviewable slices under the existing goal:

1. **State custody:** backwards-compatible snapshot shape, immutable manifests,
   shared byte persistence/read helpers and explicit state-aware provenance reads.
   Local round-trip and disposable-database tests prove desktop/mobile coexistence,
   retry preservation, exact CSS/media bytes and cross-workspace refusal.
2. **Acquisition and coverage:** independent mobile navigation plus bounded optional
   tablet capture, shared dependency budgets and durable failure reporting. A local
   browser fixture mounts different DOM at initial mobile load; it must survive the
   real capture path. Test timeouts, HTTP refusal, HTML/asset limits and budget skips.
3. **Native reuse:** state-specific segmentation, conservative section matching,
   derived responsive composition, source-state review and edit/export parity.
   Test mismatched/ambiguous sections, inconsistent slots, duplicate IDs, foreign
   manifests, missing assets and unsupported breakpoint evidence as explicit gaps.

Acceptance requires source-versus-artifact comparison at captured desktop/mobile
widths and around every claimed breakpoint; image/typography/crop agreement; no
horizontal overflow; and correct native editing/export. Offline checks cannot mark
the live source reproduction benchmark complete.

Once new live tests are authorized, use only Conduit Fresh initially and preserve
the existing drafts. Capture through normal onboarding/Re-extract, then use a short
ordinary user request through Clue's own agent. Keep the broader fresh four-brand,
motion, account-grounding and repeatability gates open until separately demonstrated.

## Excluded actions

No live database migration, automatic recapture, new generation prompt, old-instance
restart, remote push, or arbitrary third-party script replay is part of this design
review. These remain governed by the user's current operating constraints.
