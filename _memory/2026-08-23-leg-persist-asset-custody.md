# 2026-08-23 — generated-asset custody at the leg persist seam (genad2 walk)

Commits `9bc1be9aa` (fix) + `bacc54b6e` (review fix loop) on `integration/frontend-design-part-iv-v4`.
Full forensics + gate results: `.superpowers/sdd/2026-08-23-agent-authored-pages/custody-fix-report.md`
(gitignored, local only).

## Symptom
Chat-born ad's GENERATED hero image renders in every server-side SVG preview/export and 404s on
the editor canvas (`GET /asset-store/{digest}`) — permanently, across further chat iterations.

## What was DISPROVED (do not re-chase)
The leg-persist backstop ran and succeeded. `doc_9e93c1e08c395f57b5efc67d687c8314` v101's two
generated digests (`81820a82…`, thumbnail `b007e8a7…`) both have live `artifact` rows stamped
`design_asset`, created `14:08:19/20 UTC` — the final second of leg run
`run_6b30ec198f6c5d60bbb9d1ce05e51bc1`. Population scan of the live DB (55040): 115 documents,
22 scene-asset digests, 22 with a live design-namespace row, 0 without. So: the cache root was
right, the `provider: "local-store"` shape was recognised, and rows were written.

## Actual cause
Two halves of custody diverged and could not re-converge.
* Trigger (operational): the fs backend's root default is RELATIVE —
  `clue_config.settings.storage_fs_root = ".artifacts"` — so cwd decides it. The persisting
  process and the serving process were rooted in different conductor workspaces (colombo vs
  istanbul, verified with `lsof -d cwd`); bytes landed in one tree, the API read the other.
* Product defect (fixed): the backstop skipped on `DesignBlobStore.exists` — a ROW probe
  ("no blob I/O"). Once a row exists it says yes forever, so no later persist re-put the bytes,
  even though the engine cache still held them.

## Fix
`DesignBlobStore.has_readable_bytes` (row AND `storage.exists(key)`, one bridged transaction);
`register_scene_asset_backstop` skips on that instead. Healing is free — the backstop already
walks the whole scene asset table each persist, and `register_design_bytes` is content-addressed
+ row-before-blob. `PUT /scene` shares the function, so the MVP editor accept heals too (pinned).
`media.location` deliberately not re-pointed; readers resolve by digest.

## Review fix loop (`bacc54b6e`)
* Probe is now three-state (`CustodyState.READABLE/ROW_ONLY/ABSENT`) and **batched** — one bridged
  call per scene, concurrent backend stats. Measured warm, fs, 50 digests: 18ms vs 346ms serial
  (the serial shape was already at HEAD), so the accept path is ~19x cheaper than before the fix.
* A sick backend can no longer fail the accept: a failed REPAIR (row existed) is logged and
  skipped; a failed FIRST registration still propagates, unchanged. Do not "simplify" this into
  one blanket except — the asymmetry is the point.
* `scripts/provision_font_library.py` swapped off the row-only probe (it is a verifier and was
  reporting a healthy font library while faces 404'd).

## Open / follow-ups
* **Pin `CLUE_STORAGE_FS_ROOT` to an absolute path** in the dev `.env`s. The relative default is
  the trigger and the fix only makes it recoverable, not impossible.
* **Pre-existing, NOT caused by this work:** three design tests 404 on the unscoped
  `/asset-store` read — `test_pure_python_reads_survive_a_wiped_cache`,
  `test_the_public_route_falls_back_to_sniffing_for_octet_stream_rows`,
  `test_asset_store_serves_content_addressed_bytes`. Reproduced identically at the parent commit.
  The suite runs against `clue_db.DEFAULT_DATABASE_URL` (localhost:5432, NOT the live 55040), where
  the `acme-logo` fixture digest has **1557** live rows from dead tmp workspaces; the bounded scan
  (`_PUBLIC_READ_CANDIDATES = 50`) exhausts on corpses and the test's own row is #1557. Fix by
  pruning that dev DB or giving those tests unique bytes (the pattern is `unique_png()` in
  `test_scene_turn_persist.py`).
* `DesignBlobStore.exists` now has no production caller (tests only, where it expresses "the row
  still claims custody"). Left in place deliberately.
