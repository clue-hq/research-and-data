# Claude Code — repo rules

Follow the operating rules in @AGENTS.md — they are binding, not advisory.

The one that has burned us three times and must never be skipped: **after ANY
commit — regardless of which files changed — rebuild the editor wasm and verify
the handshake AS THE LAST STEP, post-commit** (`bash scripts/build_wasm_core.sh
&& node scripts/verify_handshake.mjs` → must print HANDSHAKE OK), then restart
the API if running and hard-refresh any open editor tab. Both engine stamps are
git-HEAD-at-build-time (not source-based), and the API helper silently rebuilds
itself at the new HEAD via cargo run — so even a docs-only commit breaks the
handshake. Pre-commit builds don't count.
