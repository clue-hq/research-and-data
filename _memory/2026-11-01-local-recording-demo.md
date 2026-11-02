# Local recording demo

- Scope: one existing researched account continued in V2 using public, sourced gift options and actual retailer photographs. No deployed writes, orders, payments, or backend integration.
- Plan: docs/superpowers/plans/2026-11-01-harvey-direct-mail-demo.md.
- Branch verified `feat/direct-mail-infrastructure-v2`; V1 unchanged.
- Existing V2 is running on port 5001. Browser access works; sandbox network calls require the approved external-network execution path.
- Completed: additive seed, exact merchant variant photos/provenance, existing review and cost approval, revision-safe simulation/reset, filtered queue and deployed-research links. Private research excerpts and credentials are not recorded here.
- Simulation is V2-only and limited to the dedicated recording ID. It performs no network mutation and creates no fake carrier URL or package photograph. Reset reverses only this mailer's net demo debit and preserves other records.
- Final review caught recovery-buffer retention on reset. Added a failing regression test, cleared this tab's buffer only after successful reset, and verified the unsaved-note reset in the browser.
- Verification: 27 focused tests pass; design-system build passes; lint 0 errors / 11 existing warnings; Next production build passes; diff whitespace check passes. Browser exercised all fulfillment stages, returned to original draft, tested queue filtering and reload, and verified retailer images render.
- Tooling: `tsx --test` CLI cannot open its IPC pipe in the sandbox; `node --import tsx --test` works. Two commands initially used the root instead of apps/frontend and were rerun from the correct directory. Public product fetching required the approved external-network execution path.
- Closing state: localhost:5001 running; opening gift review reset for recording. Branch remains local; no push or production change. See apps/frontend/docs/demos/harvey-direct-mail.md for the recording route and operational limitations.

## Recording chrome cleanup

- Removed the full-width recording banner at user request. Moved reset/replay and deployed-research access to an ellipsis menu in the page header; underlying simulation and approval behavior unchanged.
- Simplified the address checkbox to the requested text: “Use this public office address.”
- Verified menu rendering in the browser without resetting the user’s in-progress review. Token build, lint (0 errors / 11 existing warnings), production build and whitespace check passed for the menu change; the final checkbox adjustment is text-only.

## Recording overview polish

- Itemized costs now use one shared view for review, approval (single/bulk) and tracking. Added a separate historical-delivery fixture with an immutable approved card/gift snapshot and two-leg delivery history; seeding is additive and does not debit credits or reset the existing mailer.
- Replaced the default generic account walkthrough entrance with the recording queue. Earlier walkthrough remains explicitly reachable; project filters still expose other records.
- Added original brand assets and four read-only canvas captures from existing deployed designs. Captures are not editable/published copies; links lead to originals. Asset provenance stays in the demo manifest, not this memory.
- Preview-only profile/workspace renamed as requested. Restarted only the verified V2 port-5001 process to refresh the process-local profile fixture; V1 and production untouched.
- A browser media download stalled and reset the tool runtime. Recovered the existing browser via inventory and used screenshots plus observed public asset URLs. No browser credentials were extracted. One token-build invocation used the repo root and failed; reran successfully in apps/frontend.

- Closing verification: 28 Direct Mail tests and 6 preview tests passed; token build, lint (0 errors / 11 existing warnings), Next production build, and whitespace check passed. Browser verified both seeded accounts, preserved existing approval, delivered-only filtering, real ad preview, and requested profile/workspace branding. V2 remains running on port 5001; no production changes or remote publication.

## Physical card adaptation

- Replaced the local recording card placeholder with a generated composition based on the supplied physical card and official brand imagery. User clarified that the original lettering is real handwriting and requested generated images, not a substitute font; generated separate message artwork for both recording recipients. Original physical photos are not copied into the repo.
- Added original brand wordmark/mark, the user-approved front footer, and a deterministic homepage QR. Exact asset sources and prompts are in the frontend demo docs/manifest. The QR is not a recipient microsite or a tracking integration.
- Shared preview now supports optional branding and exact-text-bound message artwork. Text, signature or style edits stop using the cached handwriting image, preventing stale artwork. Local-only migration refreshes the two recording fixtures and their simulated card snapshots without resetting gifts, financial state or delivery progress.
- A hot-reload intermediate card omitted its brand display name and failed hydration; made that label backward compatible and added a regression check. An ESM one-liner failed against the TS CommonJS fixture and was rerun with require. Browser control recovered after resetting its stale runtime. No production actions occurred.
- Closing verification: 32 focused tests pass; design-system build, lint (0 errors / 11 existing warnings), production build and whitespace checks pass. Browser verified both faces in review and the separate approved card in tracking. QR decoded from the actual browser screenshot to the intended public homepage. Port 5001 remains running; V1 unchanged.
