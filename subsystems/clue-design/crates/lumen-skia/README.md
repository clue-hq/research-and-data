# lumen-skia

Native-only Skia integration for the Lumen design engine (Wave 1 Track A).

- `FontManager` — deterministic byte-loaded fonts. The repo `fonts/`
  directory (Inter static TTFs 400/600/700/800 + SIL OFL license) is the
  cross-runtime parity contract; `FontManager::bundled()` embeds those bytes
  at compile time. No system font lookup anywhere in this crate.
- `SkiaTextMeasurer` (slice A2) — SkParagraph-backed `TextMeasurer`.
- `SkiaSceneRenderer` (slice A3) — direct scene→Skia PNG rasterization
  behind `lumen-export`'s `PngExportAdapter` interface.

## Hard layering rule

`skia-safe` binds native C++ Skia and cannot compile to wasm32. This crate
must never become a dependency of `lumen-core` (which stays wasm-clean) or of
`lumen-export`'s portable library surface. Composition happens in
`lumen-api-helper` only.

## Build and CI notes

- `skia-safe` is pinned workspace-wide (`=0.97.2` in the root `Cargo.toml`).
  That pin is also the Skia-version contract the Wave 3 CanvasKit editor
  build must match. Do not bump it casually.
- The feature set (`textlayout`, `svg`, `webp` + defaults) is chosen to hit a
  **published prebuilt binary** of rust-skia for CPU-only servers (no GPU
  backends). `skia-bindings` downloads the matching prebuilt Skia archive at
  build time; changing the feature combination can silently force a multi-hour
  from-source Skia build (which additionally needs python + ninja + clang).
- CI caching: cache `~/.cargo` and the `SKIA_BINARIES_URL` download via the
  standard cargo cache; the downloaded Skia archive lands in `target/` under
  `skia-bindings-*`, so caching `target/` across CI runs avoids re-downloading
  (~60 MB) and re-linking. An offline CI must pre-seed the archive and set
  `SKIA_BINARIES_URL` to a mirror.
- Rasterization is pinned to the CPU backend (`surfaces::raster_n32_premul`);
  no GL/Metal/Vulkan feature is enabled, so golden PNGs are
  machine-independent for a given Skia version + font bytes.

## Determinism contract

- Fonts load from bytes only; the typeface set is closed (font fallback
  disabled, no default font manager). An unknown family resolves to the
  explicit default family (`Inter`) with a `LUMS0100` warning diagnostic.
- Known limit: Skia instantiates typefaces through the platform parser
  (CoreText on macOS, FreeType on Linux). Same-platform output is fully
  deterministic; cross-platform metric parity must be validated when CI and
  production run on a different OS than dev. Wave 3's CanvasKit (FreeType)
  pixel-diff against A3 goldens is the planned check.
