# Claude Code — repo rules

Follow the operating rules in @AGENTS.md — they are binding, not advisory.

The handshake rule (was: "after ANY commit"; class-fixed 2026-07-10): **whenever
ENGINE SOURCES change (anything under `crates/lumen-core/src/` or its
`Cargo.toml`), rebuild the editor wasm and verify the handshake** (`bash
scripts/build_wasm_core.sh && node scripts/verify_handshake.mjs` → must print
HANDSHAKE OK), then restart the API if running and hard-refresh any open editor
tab. Both engine stamps are now a **content hash of the shared engine sources**
(not git HEAD), so commits alone — docs-only or otherwise — can no longer
desynchronize the editor wasm from the API helper. If the banner ever shows two
different engine hashes, STOP and report them (see AGENTS.md §1 corollary).

Two caveats added 2026-07-13 (details in AGENTS.md §1): the stamp covers ONLY
`lumen-core`, so a stale helper binary with old lumen-export/lumen-skia code
PASSES the handshake — rebuild `lumen-api-helper` after any `crates/` change;
and the same "Canvas editing is disabled" banner also appears on plain API
connectivity failures (e.g. CORS when the editor runs on a port other than
3000) — check the browser console before diagnosing a stamp mismatch.
