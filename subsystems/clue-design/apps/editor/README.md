# Lumen Editor

Next.js editor for the Lumen design engine.

## Browser WASM core (Track E)

Behind the `NEXT_PUBLIC_LUMEN_WASM_CORE=1` flag, the editor's optimistic
editing path runs the real Rust engine (`crates/lumen-core`) compiled to
WebAssembly through the thin `crates/lumen-wasm` bindings:

- The WASM module owns the local scene in its memory. JS sends operations
  and structured edits in; results, diagnostics, and mechanical scene
  deltas come out. Full scene snapshots cross the boundary only on init,
  reconcile, and undo frames — never per keystroke.
- Server authority is unchanged: `/documents/{id}/edits` and
  `/documents/{id}/operations` envelopes plus `base_version` reconciliation
  work exactly as before. The WASM core upgrades only the optimistic
  preview; the server response still reconciles, and divergence is surfaced
  as a diagnostic (it is a bug signal, not routine).
- Version handshake: the module reports
  `{ schema_version, engine_commit }`; the editor compares it against the
  API's build info and downgrades to server-only mode on mismatch. There is
  never mixed-version optimistic editing.

### Text measurement honesty

In-browser text measurement uses lumen-core's **heuristic fallback**
(per-character width weights and whitespace wrapping). `skia-safe` cannot
compile to wasm32, so the browser engine does **not** shape text the way
the server does (SkParagraph + HarfBuzz over the bundled `fonts/`).

Consequences, stated plainly:

- Line breaks, text-fit verdicts, and text-dependent layout computed in the
  browser are approximations.
- Server-computed geometry is authoritative for text-dependent layout; the
  editor renders server geometry when available (preflight/export
  responses replace local geometry).
- Bit-faithful in-browser shaping arrives in Wave 3 via a CanvasKit-backed
  `TextMeasurer` through the same trait. Until then, do not present
  browser-side text layout as matching the server pixel-for-pixel.

The module's `version()` payload carries
`text_measurement: "heuristic"` so tooling cannot mistake the fallback for
shaped parity.

### Building the module

```sh
npm install          # once; installs wasm-pack
npm run build:wasm   # builds crates/lumen-wasm into public/wasm/ and checks the size budget
```

The build enforces the Track E bundle budget (gzipped `.wasm` < 3MB). The
editor loads the module at runtime from `/wasm/`, so `npm run build` never
depends on the artifact existing; a missing or failed load degrades the
editor (legacy TS path until W4 retires it, server-only mode after).

Vitest suites that exercise the real WASM artifact skip with a notice when
`public/wasm/` has not been built. Run `npm run build:wasm` first to
include them; the conformance gate requires them to run.
