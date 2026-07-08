# Claude Code — repo rules

Follow the operating rules in @AGENTS.md — they are binding, not advisory.

The one that has burned us twice and must never be skipped: **after any commit
touching `crates/`, rebuild the editor wasm and verify the handshake AS THE
LAST STEP, post-commit** (`bash scripts/build_wasm_core.sh && node
scripts/verify_handshake.mjs` → must print HANDSHAKE OK), then restart the API
if running and hard-refresh any open editor tab. Pre-commit builds don't count —
the stamp is git-HEAD-at-build-time, so build-then-commit always leaves the
wasm one commit behind.
