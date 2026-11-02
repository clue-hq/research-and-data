# Isolated recording demo — 2026-11-02

- Work is on `codex/illumio-usbank-demo` in this managed worktree. Source V2 worktree and port 5001 were left unchanged; isolated frontend uses localhost:3000.
- Added one-account fixture, sourced public retail assets, supplied ad, deployed design preview, generated branded card front and handwriting-inspired back. No production mutations. Provenance and replay instructions are in the frontend demo doc; no customer research is copied into this memory note.
- Shared the existing fixture fulfillment progression/reset behind an injected repository adapter. Distinct browser database, approval snapshots and exact-message artwork matching retained.
- Validation: 32 focused tests; design-system build; production build; lint zero errors (11 existing unrelated warnings). Browser exercised previews, itemized approval, every fulfillment stage, reload and reset. Reset to original draft for presentation.
- Tool notes: system Python lacks requests; public downloads used urllib with approved network access. Direct tsx CLI IPC was sandbox-blocked; `node --import tsx --test ...` passed. Browser screenshot clipping kept the origin incorrectly; captured the full canvas and cropped to observed frame bounds.
- Remaining boundary: account landing page is a saved preview, not newly published; QR goes to the public product destination. Other modules retain pre-existing fixture data. No live ordering, carrier tracking or agent execution.
