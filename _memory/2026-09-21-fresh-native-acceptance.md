# Fresh native website acceptance

- Continue the existing capture/reproduction/account-skills goal; do not mark it
  complete from auth recovery or a successful model/tool run. Latest founder scope
  permits live testing only in Conduit Fresh on 3020. Old four workspaces remain
  suspended; prior cross-brand frozen-source evidence is not fresh native acceptance.
- Saved native test resumed after Google sign-in repair. Current run uses the approved
  fresh kit, captured homepage/two products/customer index/two customer stories,
  and the actual Clue design agent. Prior page versions remain separate.
- Founder correctly noted that the submitted test prompt is unusually detailed.
  Let that run finish without interruption. Classify it as a directed workflow test,
  not proof that ordinary users can get the same quality from simple instructions.
  Next ordinary-input test should use a short request such as "Create a Conduit
  landing page for Hyatt" with the existing agent/skill defaults, not a pasted
  quality checklist or hidden per-brand instructions.
- Early trace: actual reads of account argument, readiness, composition, media,
  conversion and repair guidance. Project Hyatt query returned no account. This can
  prove an honest task-relevant proposal, not researched account personalization.
  Do not initiate discovery/research or invent target evidence to pass that gate.
- Acceptance still requires rendered desktop/mobile source type/layout/media,
  authentic target logo, relevant copy, real CTA destinations, supported interaction
  states and honest missing-evidence reporting. CSS truncation is an inspection
  boundary; use existing pagination/targeted tools rather than rewriting full source.
- Fresh capture succeeded and the kit is approved. Overall onboarding aggregate
  still records the earlier alias failure although 15 steps completed; keep these
  separate in reporting.

## Directed run completed; parent review

- Run completed in 8m51s, saved the new native page v1, outcome
  completed_with_warnings. Correct fresh kit; six captured bands plus composed
  campaign header/footer. Trace records 119 tool calls, 21 section searches,
  four logo fetches, one rendered review and 14 successful skill/reference reads
  (13 distinct paths). No standalone page or manually seeded brand library.
- Hyatt provider asset was correctly rejected as the loyalty-program logo.
  Corporate arched wordmark from the official investor site is in the final
  header, verified visually. Parent inspected native desktop/mobile. Five demo
  links all point to the official absolute destination; legal links are absolute.
  Mobile has no horizontal overflow in the observed native preview.
- Parent clicked the procedure control: it did not change the selected state or
  exposed image. This is a real unresolved interaction defect, not a full fidelity
  pass. Mobile Inbox UI is hidden, leaving a tall background wash; source-parity
  versus capture/renderer cause still needs investigation.
- Corrected model self-review: security seals are NOT missing on mobile. Scrolling
  the live native preview loads all three (170px decoded/rendered). Offscreen
  lazy images in the compressed preview are insufficient missing-media evidence.
- User's current Home draft was left intact. A separate inspection tab displays
  the completed artifact. No new generation, research or edits to the finished
  draft were submitted during this acceptance pass.

## Logo search defect found during the run

- Recorded `search_assets(q="Hyatt corporate logo", kind="logo")` returned zero
  despite fetched document assets. Fetch stores SVG/PNG under vector/raster_image;
  the kind alias only recognized raw logo records. Exact-ID search worked, proving
  inventory presence, and dropping the kind filter exposed the assets.
- Regression reproduced empty results before repair. Search now reuses the existing
  fetched-logo provenance predicate for image records, preserving raw image kinds
  and refusing label-only/logo-tagged documents. Tests cover document, kit and
  library origins, explicit IDs, raw kinds and misleading labels.
- Targeted asset search/rendition checks: 58 passed. Full runtime suite finished:
  2722 passed, seven skipped and five failed. Four failed because the sandbox
  prevented Chromium starting; the four passed when rerun with local browser
  permissions. The remaining failure is the existing exact-wording assertion in
  `test_the_tool_docstrings_carry_the_amendment_too`; its `search_cloned_sections`
  target is identical to HEAD and outside this logo-filter repair. Full suite is
  therefore not green. Diff whitespace check passed.
- Workers are not reloaded while the user may have other work running; the completed
  directed run used the previous code and is not live verification of this repair.

## Next fidelity follow-up

- Read-only review found preview capture waits for styles but does not reliably
  scroll or decode offscreen lazy media. Desktop full-page capture precedes the
  scroll walk; mobile/reduced-motion captures do not walk. This explains why a
  screenshot alone cannot establish missing assets. Native scrolling was decisive.
- Implement a shared bounded media-readiness check for preview and clone-review
  paths, preserving scroll position and reporting unresolved media separately.
  Verify with delayed lazy media and genuine failed-media fixtures. Do not repair
  the actual three security assets, which load correctly in the native preview.
- Preserve this directed output as the review baseline. Run ordinary-input
  acceptance separately; do not count this heavily guided run as that gate.
