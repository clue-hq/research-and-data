# Curated font library

The always-present open-font library (Track B): ~27 OFL families curated for
ad/poster work, materialized as per-weight static TTF faces in the
content-addressed asset store and described by the checked-in
`manifest.json`.

## How it works

- **Curation** (the taste layer — families, weights, tone tags, pairing
  hints) lives in `apps/api/lumen_ingestion/font_library.py`
  (`CURATED_FAMILIES`).
- **Provisioning** (`scripts/provision_font_library.py`) materializes the
  curation into an environment: it reads a pinned sparse clone of
  `github.com/google/fonts`, instances variable sources per curated weight
  (all non-wght axes pinned to their defaults; `recalcTimestamp=False` keeps
  bytes deterministic), verifies glyph coverage (fail-loud — a face missing
  "/", "×", or the em dash cannot ship), measures metrics with the same
  fontTools path kit fonts use, ingests every face into the asset store +
  SQLite records, and regenerates BOTH `manifest.json` and the agent-facing
  inventory doc
  (`apps/agent_runtime/knowledge_docs/knowledge/design/font-library.md`).
- **Serving**: `GET /font-library` returns the manifest; face bytes ride the
  standard `GET /assets/{id}/bytes` leg.
- **Rendering**: `CoreClient` injects the library spec into every shaping
  action; the Rust helper lazily loads only faces whose family the request's
  scene/kit JSON mentions. The editor mirrors this scene-driven loading in
  `apps/editor/src/engine/libraryFonts.ts`.

## Provisioning an environment

```bash
# one-time: sparse clone (pin = manifest provenance commit)
git clone --depth 1 --filter=blob:none --sparse https://github.com/google/fonts.git .context/google-fonts
git -C .context/google-fonts sparse-checkout set ofl/inter ofl/dmsans ... # every curated dir

PYTHONPATH=apps/api .venv/bin/python scripts/provision_font_library.py --fonts-repo .context/google-fonts

# verify an environment against the checked-in manifest (no writes):
.venv/bin/python scripts/provision_font_library.py --check
```

The manifest is checked in; the blobs are not. An unprovisioned environment
degrades cleanly to bundled Inter (the spec skips faces whose bytes are
absent), and `--check` reports exactly what is missing.

## Editing the curation

Change `CURATED_FAMILIES`, re-run the provisioning script, commit the
regenerated `manifest.json` + inventory doc together —
`apps/api/tests/test_font_library.py` pins manifest↔curation↔doc lockstep.
