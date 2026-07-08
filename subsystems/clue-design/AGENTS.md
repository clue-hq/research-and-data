# Agent operating rules for this repo

Rules in this file are hard-won from repeated live failures. They are not
suggestions — every one of them exists because an agent (or the orchestrator)
made the same mistake at least twice.

## 1. Engine builds and the wasm handshake (the build-then-commit trap)

The engine (`crates/lumen-core`) runs in TWO places: the API's helper binary and
the editor's in-browser wasm. Both carry a build stamp derived from **git HEAD
at build time**, and the editor refuses canvas editing when the stamps differ
("Canvas editing is disabled" banner).

The trap: the API helper runs via `cargo run`, so it silently rebuilds itself at
the CURRENT commit on its next call — but the editor wasm only changes when you
rebuild it explicitly. If you rebuild the wasm during pre-commit testing and
then commit, the wasm is stamped one commit behind and the handshake breaks,
even though the sources are identical. This has burned live verification runs
twice (2026-07-08 and 2026-07-09).

**The rule — after ANY commit that touches `crates/`, run, in this order, as
the LAST step (post-commit, not before):**

```bash
bash scripts/build_wasm_core.sh
node scripts/verify_handshake.mjs   # must print "HANDSHAKE OK"
# then, if the API server is running, restart it; and hard-refresh (⌘⇧R)
# any open editor tab before browser work.
```

Pre-commit wasm builds (for running the editor test suite) are fine — they just
don't count: the post-commit rebuild must still happen.

Corollary for verification/browser runners: if you see the "Canvas editing is
disabled" banner, STOP and report the two engine hashes from the banner —
do not work around it, and do not assume a prior "HANDSHAKE OK" is still valid
if a commit has happened since.

(Backlog class-fix: stamp from a content hash of the crate sources instead of
git HEAD, so identical sources can never mismatch regardless of commit
choreography.)

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
