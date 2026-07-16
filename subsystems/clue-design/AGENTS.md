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

**Stamp scope caveat (found live 2026-07-13, print-W3 browser verification):**
the stamp hashes ONLY `crates/lumen-core`. A stale `lumen-api-helper` binary
built before changes to `crates/lumen-export` / `crates/lumen-skia` / the helper
itself **passes the handshake while serving old export behavior** (a helper
predating the print-ready report looked "in sync" and silently omitted it). The
handshake guarantees canvas-editing parity, NOT export-pipeline freshness. So:
after any change under `crates/` beyond lumen-core, rebuild the helper
(`cargo build -p lumen-api-helper --release`) and restart anything holding a
`LUMEN_CORE_HELPER` path — the handshake will not catch this for you.
(Class-fix candidate on the print-track backlog: extend the content hash to the
helper's full crate graph, or add a helper-freshness preflight to the API.)

Corollary for verification/browser runners: if you see the "Canvas editing is
disabled" banner, STOP and report the two engine hashes from the banner —
do not work around it. With content-stamping a mismatch means one side was built
from different engine sources (usually a stale wasm artifact); rebuild the wasm
and re-verify. **Second known cause (2026-07-13): the same banner appears when
the editor cannot reach the API at all — e.g. CORS.** The API's default
allowlist covers only `localhost:3000`; an editor served on any other port
(parallel-workspace verification runs use 3100+) must start the API with
`LUMEN_API_CORS_ORIGINS` including that origin. Before diagnosing a stamp
mismatch, check the browser console for CORS/"Failed to fetch" errors — if the
banner shows no hashes or the console shows fetch failures, it's connectivity,
not the engine.

## 2. After API-side seeding, hard-refresh the editor

Any state written through the API (`POST /documents/{id}/operations`, scene
PUTs, kit publishes) is invisible to an already-open editor tab. Hard-refresh
(⌘⇧R) before interacting, or you are testing against stale state.

## 3. Full-suite gates for engine changes

A change under `crates/` is not done until, in order: `cargo test --workspace`
(widened from `-p lumen-core` 2026-07-15: the narrow gate let `lumen-agent`
sit broken at HEAD for five commits — P4 audit finding)
→ `cargo build -p lumen-api-helper --release` → wasm rebuild + handshake →
`pytest apps/agent_runtime/tests` → `pytest apps/api/tests`
(`PYTHONPATH=.:apps/api:apps/agent_runtime`, `.venv/bin/python`). Zero
regressions; a failing test is analyzed, never weakened to pass.
