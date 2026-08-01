# Lumen custom-component compiler

This package is the P6.2 trust boundary for account-scoped custom-component
source. The API invokes `compiler.mjs` as a separate Node 24 process using the
versioned JSON protocol in `src/contracts.mjs`.

The compiler:

- parses every source file with the TypeScript AST;
- enforces component-directory containment and curated imports;
- rejects dynamic code execution, raw script/HTML injection, CSS imports, and
  unresolved dynamic Tailwind classes;
- type-checks the component and extracts static metadata, supported prop
  controls, and destructuring defaults;
- emits a React-external browser ESM bundle and component-local Tailwind CSS;
- produces a deterministic first frame inside a VM with no process, module
  loader, filesystem, or network capability;
- records exact curated/toolchain package versions and cross-component
  artifact pins in the manifest.

The API starts the process with a 192 MB heap, Node's permission model
(read-only access to this package and no network permission), and a wall-clock
timeout. A deterministic source error returns `status: "failed"`. Process,
timeout, storage, or protocol failures return `status: "transient_error"`.
Neither state creates an artifact.

Run locally:

```bash
npm ci
npm test
```
