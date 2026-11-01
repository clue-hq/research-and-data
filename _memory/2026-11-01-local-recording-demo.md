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
