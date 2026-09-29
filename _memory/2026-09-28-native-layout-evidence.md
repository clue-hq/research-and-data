# Native website layout evidence — 2026-09-28

- Continued the cross-run audit's source-contract priority under the active goal.
  No new design/model/provider generation, ingestion, DB write, live-page mutation,
  service restart, remote push or publication. Existing unrelated dirt preserved.
- Added bounded read-only browser measurements to the normal native preview pass
  and `view("layout:<width>")` / per-node reads. Captures selected-page reachable
  sections/fragments at existing 1440/768/375 widths without another render. Reads
  reject stale document/page/version/iteration. New files persist beside previews.
- Records computed text styles/boxes, media decode and CSS visibility, crop rules
  and ancestor padding/backgrounds. Shared container records reduce repetition.
  Explicit caps/omissions and capture failures; no aesthetic verdict, actual glyph
  font proof, image alpha/composite classification or original-controller recovery.
- Supervised read-only review found false-hidden descendant visibility overrides,
  zero-box display:contents ambiguity and mislabeled coordinate space. Offline
  regressions reproduced these plus stale-iteration acceptance before fixes.
  Visibility now honors target inheritance, unknown no-box text and ancestor
  display/opacity/clipping; boxes use document CSS pixels, paths are node-relative.
- Full-cap diagnostic payload initially exceeded the native view budget (82 KB).
  Scoped style sets plus shared container records fixed it without reducing the
  text/image count cap. Existing native envelope still refuses oversized results.
- Replayed held source fragments and a saved compose call, serving only 20 local
  assets in network-blocked Chromium. Reproduced type-weight/size drift, extra
  padded media backgrounds and CSS-hidden phone product imagery. No source/custody
  files changed. This is historical component replay, not final live-page proof.
  Summary: `/tmp/clue-layout-held-replay-20260928.json`; no raw source/research here.
- Canonical source-layout reference now linked from repair, product-story, media
  and review skills. A read-only reviewer applied the stale/type/hidden-media case
  correctly and retained font/asset/pixel uncertainty. This is comprehension proof,
  not a live model benchmark or evidence of improved page quality.
- Verification: 135 focused substrate/layout/skill tests passed; after the compact
  payload regression was added, all 13 layout/browser tests passed (136 unique
  focused checks overall). Scoped Ruff and whitespace checks pass. Shared legacy
  web_substrate.py has unrelated pre-existing lint debt; do not reformat it wholesale.
- Still owed: source font provenance/glyph checks, image classification/framing
  repair, account evidence-to-argument/CTA quality, retrieval/continuity and final
  native visual acceptance once another run is authorized. Goal remains active.
- Closing state: local checkpoint on codex/design-agent-v1; no remote publication.
