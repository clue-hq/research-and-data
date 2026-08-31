// Stub target for the bundler aliases in next.config.ts. canvaskit-wasm's glue requires Node
// built-ins (`fs`/`path`/`crypto`) and the optional `canvas` package on code paths that never run
// in the browser; Turbopack has no webpack-style `resolve.fallback`, so those specifiers are
// aliased here under the `browser` condition instead. Intentionally exports nothing.
export {};
