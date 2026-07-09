# Agent operating rules for this repo

Rules in this file are hard-won from repeated live failures. They are not
suggestions — every one of them exists because an agent (or the orchestrator)
made the same mistake at least twice.

## 1. Engine builds and the wasm handshake (now source-content-stamped)

The engine (`crates/lumen-core`) runs in TWO places: the API's helper binary and
the editor's in-browser wasm. Both carry a build stamp, and the editor refuses
canvas editing when the stamps differ ("Canvas editing is disabled" banner).

**Class fix landed 2026-07-10:** the stamp is no longer git HEAD at build time —
it is a **content hash of the shared engine sources** (`crates/lumen-core`'s
`src/**/*.rs` + `Cargo.toml`, hashed by the single shared implementation in
`crates/build_support/engine_stamp.rs` that both crates' `build.rs` `include!`).
Identical sources ⇒ identical stamp, so **commits alone can no longer
desynchronize the two sides.** The old trap (the API helper silently rebuilds at
the current commit via `cargo run`, so ANY commit — even a docs-only one, proven
live 2026-07-09 — broke the handshake) is dead: a docs-only commit leaves both
stamps unchanged. This class of failure burned live verification runs three
times before the fix.

**The rule — whenever ENGINE SOURCES change (anything under
`crates/lumen-core/src/` or its `Cargo.toml`), run, as the LAST step:**

```bash
bash scripts/build_wasm_core.sh
node scripts/verify_handshake.mjs   # must print "HANDSHAKE OK"
# then, if the API server is running, restart it; and hard-refresh (⌘⇧R)
# any open editor tab before browser work.
```

Commits that do NOT touch engine sources need no rebuild — the stamp is content-
derived, not commit-derived. (When in doubt, the rebuild is cheap and idempotent:
`build.rs` re-runs only when a hashed file actually changed.)

Corollary for verification/browser runners: if you see the "Canvas editing is
disabled" banner, STOP and report the two engine hashes from the banner —
do not work around it. With content-stamping a mismatch means one side was built
from different engine sources (usually a stale wasm artifact); rebuild the wasm
and re-verify.

## 2. After API-side seeding, hard-refresh the editor

Any state written through the API (`POST /documents/{id}/operations`, scene
PUTs, kit publishes) is invisible to an already-open editor tab. Hard-refresh
(⌘⇧R) before interacting, or you are testing against stale state.

## 3. Full-suite gates for engine changes

A change under `crates/` is not done until, in order: `cargo test -p lumen-core`
→ `cargo build -p lumen-api-helper --release` → wasm rebuild + handshake →
`pytest apps/agent_runtime/tests` → `pytest apps/api/tests`
(`PYTHONPATH=.:apps/api:apps/agent_runtime`, `.venv/bin/python`). Zero
regressions; a failing test is analyzed, never weakened to pass.
