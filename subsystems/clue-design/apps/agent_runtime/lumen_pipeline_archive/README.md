# ARCHIVED — quality-loop pipeline (frozen 2026-07-09)

This package is the retired deterministic pipeline (`LumenQualityLoop` +
one-shot director/author/reviewer provider calls). Per the D7-amended decision
in `docs/deepagent-architecture.md`:

- **The living design agent is `lumen_agent/`** (the true deepagent harness).
- This archive is kept for offline reference and as the eval baseline (M6).
  After Phase B it is wired into NO live path.
- **Do not import from this package in new code.** Shared components were
  COPIED into `lumen_agent/` (share-by-copy directive); fixes land there only.
