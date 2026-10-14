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

## 2a. Watching a design run (the run view)

When you need to see what a run actually did — the brief it was handed, the scene
it left behind, every envelope and event in between — materialize the view:

```bash
set -a; source .env; set +a     # from the colombo repo root
.venv/bin/python subsystems/clue-design/scripts/run_view.py <run_id|doc_id|leg_id>
```

Use the venv interpreter explicitly (as §3 does): sourcing `.env` does not activate
anything, bare `python` is often not on PATH at all, and `asyncpg` lives only in the
repo-root `.venv`.

It writes `subsystems/clue-design/.design-runs/<ref>/` (gitignored — the path is
the SUBSYSTEM's, not the repo root's): `manifest.json`, the leg's frozen brief,
the current scene, seq-ordered `envelopes/`, `events.jsonl`, and `assets/`
linked to real bytes (symlinks; `--copy` to hand the directory around), with any
asset that has no bytes on this machine NAMED rather than dropped. Whatever it
could not resolve lands in `manifest["gaps"]` — the view is honest, never
fabricated.

Env: `CLUE_DATABASE_URL` and `CLUE_STORAGE_FS_ROOT` are both required, and the
storage root must be **absolute** — the CLI refuses a relative one instead of
resolving it against wherever you happen to be standing, because a wrong root
reports the frozen bundle and every durable asset as missing, which is a
confident lie. `LUMEN_ASSET_STORE_ROOT` is optional (defaults to this subsystem's
`subsystems/clue-design/.engine-cache`; a relative value warns and continues,
since a wrong cache root only costs a fallback to the durable blob).

**Paste any run id straight from a worker log.** The trio's INNER deepagent run
id — the one the logs print — is durable in no table; it survives only inside the
OUTER design run's `run_event` payloads, and the CLI bridges through them for
you, recording `bridged_from` in the manifest and naming both ids in the gaps.
Mind the asymmetry that bridge creates: the output DIRECTORY is named for the ref
you ASKED for, while `manifest["ref"]` is the outer run the view is actually of.
When you need to know which run you are looking at, read the manifest, not the
directory name.

The tree is DERIVED, read-only, and disposable — a view over the real homes (the
leg's frozen context bundle in platform blob storage, the engine materialization
cache, Postgres). Delete it freely; re-run to refresh. It is not a fourth
substrate and must never become a write path.

## 3. Full-suite gates for engine changes

A change under `crates/` is not done until, in order: `cargo test --workspace`
(widened from `-p lumen-core` 2026-07-15: the narrow gate let `lumen-agent`
sit broken at HEAD for five commits — P4 audit finding)
→ `cargo build -p lumen-api-helper --release` → wasm rebuild + handshake →
`pytest apps/agent_runtime/tests` → `pytest apps/api/tests`
(`PYTHONPATH=.:apps/api:apps/agent_runtime`, `.venv/bin/python`). Zero
regressions; a failing test is analyzed, never weakened to pass.

## 4. Parallel worktree agents: never use `git stash`

`refs/stash` is repo-global — shared by every worktree of this repo. Two agents
stashing concurrently interleave one stack: agent A's `pop` can apply agent B's
changes into A's worktree (happened live 2026-08-26 during the W1 wave; work
was recovered from the dangling stash commit, but only by luck and forensics).
For temporary saves in a worktree, commit to the worktree branch (and reset
afterwards) or copy files aside — anything but `git stash`.

## 5. Clone-fidelity runtime dependencies (F3, recorded at the CP1 walk)

Three environmental dependencies the clone-fidelity surfaces refuse loudly without — a fresh
checkout or a new worker host must carry all three before the flows run:

- **Playwright chromium on the API process** — the isolation render (dormant previews) and the
  behavioural review gate both launch it (typed refusal when absent).
- **node + `apps/editor/node_modules` on any worker that repairs clones** —
  `repair_cloned_section` shells out to the editor's Tailwind toolchain (declared, checked,
  20s-bounded).
- **the vendored Tailwind runtime** (`apps/editor/public/vendor/tailwind-browser.js`, mirrored
  under `apps/frontend/public/vendor/`) — UNTRACKED IN GIT; without it every editor-mode
  preview renders with no utility CSS and the review gate refuses to write durable verdicts
  (`evidence_settled` stays false, loudly).

Env-var trap (walk finding F-6): the design agent reads `LUMEN_AGENT_API_KEY`; a workspace
`.env` carrying only `CLUE_OPENROUTER_API_KEY` is a guaranteed first-run stumble — set both.

## 6. The hardened site renderer runs without Chromium's own sandbox in containers

`apps/api/lumen_api/hardened_browser.py` renders agent-written site code. In containers it runs with
`LUMEN_SITE_RENDER_CHROMIUM_SANDBOX=0` (set by the backend image; a production env file must leave
the line out) because Docker's default seccomp profile cannot give Chromium its sandbox — founder
decision 2026-10-14, option A of review finding S7-1. On a Mac the code default (on) stays. Before
changing that setting, the image, the release smoke check, or how agent code renders on the server,
read `docs/specs/2026-10-14-site-render-chromium-sandbox-decision.md` (repo root): it records the
residual risk, the hardening steps still owed, and when to move to a seccomp profile or the locked
render container.
