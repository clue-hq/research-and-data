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
