# 2026-07-26 — C6.1 isolated production workspace

## Outcome

C6.1 is complete on `platform/c6-deepagent-runtime`. It adds the production isolated
workspace/root/materialization backend and its `StorageBackend` output handoff. It adds no
migration, production agent construction, executor, route, or feature routing. C6.2 is next.

## Implemented

- Added `CLUE_AGENT_WORKSPACE_ROOT` and `clue_api.agent_workspace_wiring`.
- Added dedicated-root validation: absolute canonical path, no link/dot traversal, unrelated to
  source/home, exact owner-only mode, expected scope-directory types only.
- Added one-shot `<workspace>/<project>/<execution>` creation from validated ASCII ids and an
  opaque `workspace_root_id`.
- Added a file-only Deep Agents backend with `virtual_mode=True`, normalized relative paths,
  readable/writable prefix authority, document/data extensions, and no command-execution surface.
- All host operations are anchored to open directory descriptors and use no-follow flags.
  Files must be private, regular, non-executable, owner-owned, and have one hard link.
- Writes use same-directory temporary files and atomic no-replace install; edits are locked
  compare-and-swap replacements. Quota decisions are locked across threads/processes.
- Added per-file, total-byte, and file-count quotas, incomplete-temp rejection, immutable
  resource/context/input trees, and manifest-last exact-resource materialization.
- Added single-flight output snapshots through an injected artifact sink. The API adapter writes
  workspace-scoped content-addressed blobs through the existing `StorageBackend`.
- Cleanup is rejected until outputs are durably snapshotted and a same-workspace finalization
  artifact ref authorizes it. Failed pre-model materialization has a separate discard path.
- The actual V1 folder catalogs/loaders remain C6.2; C6.1 supplies their exact immutable snapshot
  consumer without creating catalog content early.

## Adversarial coverage

Absolute/drive/traversal/dot/repeated/backslash/control/confusable paths; source/home root
relations and linked parents; cross-execution access/reuse; repository/environment/secret access;
symlinks, hard links, FIFO and executable injections; same-path and quota concurrency; edit races
and swapped-link replacement; crash-time atomic install failure; quota limits; immutable-resource
mutation; wrong/missing resource hashes; manifest failure; cross-workspace artifact refs; output
mutation; and cleanup-before-finalization all fail closed.

## Verification

- Focused C6.1/root/resource/API suite: 49 passed.
- All `tests/agents`: 67 passed, 1 skipped.
- Ruff format/lint excluding unrelated untracked `.claude/` and `.codex/`: green (820 files).
- Mypy: 401 source files, green.
- Import-linter: 24 contracts kept, 0 broken.
- Repository pytest: 1,461 passed, 1,070 skipped.
- `git diff --check`: green.

Literal `make check` is still obstructed at Ruff by the preserved untracked `.claude/` and
`.codex/` structural-humanizer scripts (16 `T201` findings). The equivalent source-controlled
gate passed.

## Next

Proceed with C6.2 only: real versioned folder catalogs, strict loaders/resolution, role profiles,
effective tool allowlists, progressive skill disclosure, and the provider-neutral production
model seam. Do not add C6 durable turn/history migrations until C6.3.
