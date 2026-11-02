# Isolated recording demo — 2026-11-02

- Work is on `codex/illumio-usbank-demo` in this managed worktree. Source V2 worktree and port 5001 were left unchanged; isolated frontend uses localhost:3000.
- Added one-account fixture, sourced public retail assets, supplied ad, deployed design preview, generated branded card front and handwriting-inspired back. No production mutations. Provenance and replay instructions are in the frontend demo doc; no customer research is copied into this memory note.
- Shared the existing fixture fulfillment progression/reset behind an injected repository adapter. Distinct browser database, approval snapshots and exact-message artwork matching retained.
- Validation: 32 focused tests; design-system build; production build; lint zero errors (11 existing unrelated warnings). Browser exercised previews, itemized approval, every fulfillment stage, reload and reset. Reset to original draft for presentation.
- Tool notes: system Python lacks requests; public downloads used urllib with approved network access. Direct tsx CLI IPC was sandbox-blocked; `node --import tsx --test ...` passed. Browser screenshot clipping kept the origin incorrectly; captured the full canvas and cropped to observed frame bounds.
- Remaining boundary: account landing page is a saved preview, not newly published; QR goes to the public product destination. Other modules retain pre-existing fixture data. No live ordering, carrier tracking or agent execution.

## Gift and photographic card revision

- Replaced the coffee concept with sourced puzzle products and a matching note. Historical public research is identified as historical; no hobby is inferred.
- Added an optional native photographic front layout and an unchanged official brand photograph. Existing full-card artwork keeps its original rendering.
- Enlarged preview now shares Front / Message controls with the inline card. Updated generated handwriting remains exact-text bound; QR routing is unchanged.
- Revised concept uses a new isolated browser record so earlier scenario drafts/approvals remain preserved. No source V2 edits or production mutations.
- Focused suite: 32 tests passed. Browser confirmed new gift selection, photographic front and message-side flipping. Design-system and production builds passed; lint has zero errors and the same 11 pre-existing warnings.
- Tool recovery: CUA returned an unavailable browser binding; resetting its JS session restored the existing tab. One stale accessibility target was refreshed before continuing. An official webpage returned HTTP403 to urllib; its linked public CDN photograph downloaded successfully.
- Closing verification: queue displays the new selected product and $142 total; original source V2 worktree remains clean. Saved browser screenshots show the photographic front and enlarged message controls. No approval or purchase was performed during this revision.
