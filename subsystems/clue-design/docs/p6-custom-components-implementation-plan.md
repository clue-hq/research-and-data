# P6 custom components — living implementation plan

Status: **IN PROGRESS — P6.3 complete; P6.4 queued**

Owner branch: `agents/custom-components-v0`

Baseline: `fe6e6e4`

Last updated: 2026-07-30

This is the execution ledger for custom components in the website editor. It
turns the Tier-3 contract in
`.context/website-track/BUILD-PLAN.md` and the captured Mutiny skill in
`.context/website-track/mutiny-custom-components-skill-VERBATIM.txt` into
implementation-sized work. It is intentionally a living document: update it
when a slice starts, when scope or a decision changes, and when verification
evidence is available.

## How to maintain this plan

Status symbols:

- `▢` queued
- `◐` in progress
- `✅` complete and verified
- `⛔` blocked, with the blocking condition recorded

For every completed slice:

1. Replace its status with `✅`.
2. Record the commit(s), automated-test results, and browser evidence in the
   slice's **Completion record**.
3. Update **Current state** and the decision/change log.
4. Do not mark a slice complete when only its internal API works; its stated
   observable result and acceptance criteria must also work.
5. Do not silently broaden a slice. Put a newly discovered dependency in the
   smallest affected slice and record why.

## Current state

| Slice | Status | Delivers |
| --- | --- | --- |
| P6.1 Canonical model and durable registry | ✅ | First-class leaf nodes, immutable version records, checked operations |
| P6.2 Compiler and security gate | ✅ | TSX-to-artifact compilation, props schema, import/policy validation |
| P6.3 Sandboxed runtime and editor experience | ✅ | In-canvas rendering, picker, generated props inspector, ordinary editing |
| P6.4 Deep Agent authoring workflow | ▢ | Persistent source tools, compile-before-attach, custom-component skill |
| P6.5 Publish, rollback, and end-to-end hardening | ▢ | Self-contained delivery artifacts, pinned versions, complete live proof |

P6.1 was completed and verified on 2026-07-30.
P6.2 was completed and verified on 2026-07-30.
P6.3 was completed and verified on 2026-07-30.

## Outcome

When P6 is complete, a custom component will be a small reusable React/TSX
program used only when palette primitives, platform components, and embeds
cannot express the requested interaction or visual.

A human should observe this workflow:

1. A component appears in a **Custom components** picker using its declared
   name and description.
2. Placing it creates one selectable leaf in the existing website tree.
3. It can be moved, reparented, resized, duplicated, deleted, undone, and
   redone through the same operation history as text, buttons, and images.
4. Its typed props appear as normal inspector controls. Prop edits update the
   preview without editing source code.
5. Compile, missing-component, and runtime failures appear as bounded,
   actionable states; they do not break the rest of the page.
6. **Edit with AI** creates a new immutable version for this page. Other pages
   continue using their existing pinned version.
7. Published pages keep the version they were published with until they are
   explicitly republished.

The Deep Agent should be able to:

1. Prove a capability-ladder gap before choosing a custom component.
2. List and inspect reusable components.
3. create or edit component source in a persistent component filesystem;
4. compile and validate it;
5. attach only a successful immutable artifact;
6. report compile failures differently from transient infrastructure failures.

## Scope boundary

### In scope

- One account-scoped component library with reusable component slugs.
- React/TSX entry modules with `meta`, typed optional props, and defaults.
- Curated dependencies from the Mutiny contract: React, component-local and
  cross-component imports, selected `@visx/*` modules, `motion/react`, `gsap`,
  and `@gsap/react`.
- Tailwind-backed component styling and resolved website-theme injection.
- Safe personalization values through an explicit runtime input.
- Immutable compiled artifacts and per-page version pins.
- Sandboxed editor and delivery execution.
- Semantic first-frame output, client hydration, motion, and interaction.
- Editor picker, props inspector, version/error states, generic layout
  controls, history, publish, rollback, and Deep Agent tools.

### Out of scope for this milestone

- A public marketplace or third-party package installation.
- Arbitrary npm dependencies.
- Cross-account or cross-tenant component sharing.
- Unsandboxed mounting in the editor or delivery page.
- A general-purpose IDE, manual source editor, or visual component builder.
- Collaborative source merging.
- Automatic graph layout or an unconstrained plugin system.
- Scaling infrastructure for many accounts. Correct account isolation and
  immutable versioning are still required for the first account.

## Architecture contract

### 1. Canonical document node

Add a distinct `CustomComponent` node kind. Do not overload the existing
branch-shaped built-in `Component` node or the human-pasted `Embed` node.

Conceptually:

```text
CustomComponent {
  slug: string,
  artifact_id: string,
  props: map<string, typed-json-value>
}
```

The node is always a leaf. `node.classes` remains the canonical owner of host
layout, responsive sizing, placement, and visibility. The artifact owns only
the component's internal rendering. The node pins an exact immutable artifact;
it never means "use whichever version is latest."

The existing checked-operation envelope remains the only document write path.
Custom-component placement, prop edits, version changes, move/reparent,
class-backed resize, duplicate, delete, Undo, and Redo must all be invertible.

### 2. Durable component registry

Component source must not live only in a chat thread or an ephemeral
Deep-Agent run workspace. The agent-facing path is virtual:

```text
/custom_components/<kebab-slug>/<kebab-slug>.tsx
```

It is backed by an account-scoped durable registry. Helpers may use relative
imports only within the slug directory. Cross-component imports resolve by
component slug and pin resolved artifact dependencies at compile time.

Each successful compile creates an immutable artifact containing at least:

- artifact ID and account ID;
- slug, source digest, bundle digest, and creation provenance;
- immutable source snapshot;
- `meta { name, description }`;
- extracted prop schema, defaults, and extraction warnings;
- compiled browser bundle and component-local CSS;
- dependency artifact pins and curated package versions;
- compiler/runtime contract versions;
- first-frame render metadata;
- diagnostics and build timestamps.

The document stores only the small artifact reference and node props. Source
and compiled bytes live in the registry/content-addressed object store. Editing
source creates a new artifact and changes only explicitly targeted page nodes
to that artifact. No other page follows automatically.

Failed compiles keep diagnostics but never become attachable artifacts.

### 3. Compiler and policy gate

Use a dedicated Node compiler service/worker rather than evaluating component
source in the Python API or Rust helper. Compilation is deterministic for a
given source, dependency set, compiler version, and Tailwind/theme contract.

The gate must:

- require a default export;
- validate kebab-case slug/path identity and path containment;
- parse TypeScript with an AST, not regular expressions;
- extract `meta` and a JSON Schema-like inspector contract from `Props`;
- support optional string, number, boolean, and string-literal-union props;
- extract destructuring defaults and warn loudly about unsupported prop fields;
- resolve only allowed bare imports, relative files, and component slugs;
- reject `eval`, `new Function`, dynamic `import()`, and `document.write`;
- reject CSS imports and event/script injection outside the component program;
- compile component-local Tailwind classes, including an explicit strategy for
  dynamic classes rather than silently dropping them;
- produce browser and first-frame render artifacts;
- run compile and render smoke tests in a time-, memory-, filesystem-, and
  network-constrained worker.

Compile/validation failures are deterministic authoring failures: fix the
source before retrying. Transient worker/infrastructure failures may be retried
once or twice, then must stop with an honest error.

### 4. Sandboxed runtime

Every component runs in a dedicated sandboxed iframe. It must not receive
`allow-same-origin`; it gets only the minimum capabilities required for scripts
and declared interactions. Apply a restrictive CSP and deny network access by
default. Any later endpoint capability requires an explicit, validated
declaration and separate review.

The host passes a structured, cloned payload:

```text
{
  props,
  theme: { colors, fonts, shadows, breakpoints },
  overrideVariables
}
```

The runtime reports ready/error state and intrinsic height through a
nonce/source-checked bridge. It cannot address the parent DOM. Required content
must be present in the server-rendered first frame; animation hydrates
client-side and must not hide load-bearing copy before hydration.

Editor, preview, export, and publish use the same versioned runtime contract.
No environment may silently render a different component version.

### 5. Publish and provenance

Export/publish packages every referenced immutable component artifact and its
pinned dependencies using content-addressed URLs. Delivery does not reach back
to mutable "latest" source. The publish manifest records artifact IDs, digests,
runtime/compiler versions, and prop/theme inputs needed for reproducibility.

Rollback restores the older publish snapshot and therefore its older component
pins. Editing a component after publication shows a clear **Republish to
update** state.

## Implementation slices

The five slices below are the minimum useful separation. They follow dependency
boundaries and each has a testable exit; splitting them further would mostly
create partially usable plumbing.

### P6.1 — Canonical model and durable registry `✅`

**Purpose**

Establish one safe identity/version model before UI or agent paths can create
custom components.

**Work**

- Add the leaf `CustomComponent` kind to `lumen-web`, validation, render
  placeholders, TypeScript mirrors, checked operations, inversion, duplicate,
  serialization, and document inspection.
- Reject children, empty/invalid slugs, unknown artifact references, unsupported
  prop values, and operations that would violate leaf semantics.
- Add account-scoped registry/artifact persistence and content-addressed
  storage records.
- Add internal/API contracts for listing, reading, and resolving immutable
  artifacts. Writes remain compile-gated; no endpoint may manufacture a
  successful artifact.
- Define deterministic migration/backfill behavior for development data.
- Keep the existing built-in `Component` and `Embed` semantics unchanged.

**Likely touchpoints**

- `crates/lumen-web/src/doc.rs`
- `crates/lumen-web/src/ops.rs`
- `crates/lumen-web/src/render.rs`
- `apps/editor/src/engine/webDocuments.ts`
- `apps/api/lumen_api/database.py`
- `apps/api/lumen_api/main.py`
- a new API migration and focused Rust/API/editor tests

**Observable result**

A fixture/API-created custom-component node round-trips as a first-class leaf,
appears in document inspection, participates in move/resize/history operations,
and renders a bounded missing/not-yet-rendered placeholder without damaging the
page. No picker or live TSX execution is promised in this slice.

**Acceptance**

- Round-trip serialization preserves slug, artifact pin, props, and classes.
- Generic move, reparent, resize, duplicate, delete, Undo, and Redo preserve
  invariants.
- Branch nodes cannot be reparented into a custom-component leaf.
- Cross-account artifact resolution is rejected.
- Missing/deleted artifacts produce an explicit placeholder, not lost content
  or a page-level error.
- Existing web documents still validate and render.

**Completion record**

- Commits: `70ec527` (`feat(web): add canonical custom component registry`)
  plus the plan-close commit containing this record.
- Automated gates:
  - `cargo test --workspace`: passed, including 148 `lumen-web` unit tests and
    6 `lumen-web` integration tests.
  - `cargo build -p lumen-api-helper --release`: passed. `lumen-core` was not
    changed, so the WASM rebuild/handshake gate did not apply.
  - Agent runtime: 540 passed, 1 skipped.
  - API: 472 passed, 3 skipped. A first sandboxed run had four network/DNS-only
    failures against `example.com`; the required network-enabled rerun passed.
  - Focused editor suites: 80 passed. Editor lint and production build passed.
  - Full editor suite: 1,051 passed and 26 failed in two pre-existing legacy
    `EditorApp` suites whose stale `CanvasSurface` mocks allow CanvasKit to
    request `/canvaskit/canvaskit.wasm`. P6.1 tests and edited paths are green;
    the unrelated harness failures were not weakened or hidden.
- Browser evidence:
  - Verified in the actual website editor with
    `doc_p61_custom_component_e19997f0e9f1`: the leaf renders a bounded,
    semantic **Custom component unavailable** placeholder and exposes its
    slug, full immutable artifact pin, prop count, leaf constraint, and
    computed size in inspection.
  - Generic reorder, physical pointer reparent, class-backed resize, duplicate,
    delete, Undo, and Redo all worked. Persistence after the physical
    reparent/Undo/Redo sequence ended at document version 11 with
    `cc_09e8e5` restored under `slot-right`.
  - Duplication preserved the artifact pin, typed props, and classes. Resizing
    produced exact 520-by-200 and 500-by-200 computed bounds in the exercised
    states.
  - Deleting the fixture's registry row and reloading retained the node and
    explicit placeholder without a page error; the missing node remained
    selectable and resizable. Browser console errors were empty.
- Residuals:
  - No P6.1 acceptance residual. Picker, source authoring/compilation, live TSX
    execution, generated prop controls, and delivery packaging are
    intentionally owned by P6.2–P6.5.
  - The 26 unrelated legacy editor harness failures above remain repository
    test debt and are explicitly carried forward.

### P6.2 — Compiler and security gate `✅`

**Purpose**

Turn persistent TSX source into immutable, inspectable, safe-to-attach
artifacts.

**Work**

- Add the dedicated compiler worker and versioned compile protocol.
- Implement source snapshots, helper-file containment, curated imports, and
  cross-component dependency pinning.
- Implement AST extraction for `meta`, props, defaults, warnings, and banned
  constructs.
- Compile component-local Tailwind CSS and both browser/first-frame artifacts.
- Run constrained compile/render smoke tests before publishing an artifact.
- Persist diagnostics with the correct compile-versus-transient taxonomy.
- Add create/edit/compile APIs that use optimistic version checks so concurrent
  edits cannot replace newer source.

**Likely touchpoints**

- a focused Node package under `apps/` or `packages/`
- API registry/compiler orchestration
- Tailwind/compiler configuration
- compiler fixtures and API tests

**Observable result**

A valid sample component compiles into an immutable artifact with name,
description, generated prop controls, defaults, CSS, dependency pins, and
digests. Invalid source returns precise diagnostics and remains unattached.
Editing the same slug creates a second artifact without modifying the first.

**Acceptance**

- Valid React/Tailwind, Visx, Motion, and GSAP fixtures compile.
- Forbidden constructs, unapproved packages, escaping relative paths, CSS
  imports, missing default exports, and invalid slugs fail deterministically.
- Unsupported prop types emit named warnings; supported props are not omitted.
- Defaults survive newly added optional props.
- A compile can never mutate an existing artifact.
- Compiler timeout/crash cannot corrupt the registry or create an attachable
  partial artifact.
- Identical inputs produce identical content digests.

**Completion record**

- Commits: `e1d27ae` (`feat(web): add constrained custom component compiler`)
  plus the plan-close commit containing this record.
- Automated gates:
  - Clean Node 24 install and audit: zero vulnerabilities. Compiler suite:
    24 passed, covering React/Tailwind, Visx, Motion, GSAP, contained helpers,
    dependency pins, deterministic output, constrained first-frame rendering,
    forbidden syntax/imports, TypeScript errors, and render timeout.
  - Focused P6.1/P6.2 API suites: 14 passed, including immutable revisions and
    artifacts, exact retries, stale writes and compiles, cross-account
    rejection, worker crash/timeout/malformed output, migration replay, and
    both write/write and write/compile concurrency races.
  - `cargo test --workspace` and
    `cargo build -p lumen-api-helper --release`: passed. No engine source
    changed, so the WASM rebuild/handshake gate did not apply.
  - Agent runtime: 539 passed, 2 skipped.
  - API: 478 passed, 6 skipped. The sandboxed run's four expected public-DNS
    failures were rerun with network access and passed.
  - Editor lint and production build passed. A clean build was used after a
    stale `.next` cache produced an unrelated missing `/icon.svg` error.
  - Full editor suite remained at the carried baseline: 1,051 passed and 26
    failed in the same two legacy `EditorApp` suites, with three associated
    CanvasKit missing-WASM unhandled errors. P6.2 has no editor implementation
    changes and did not alter or hide this debt.
  - Workflow YAML, shell syntax, Node module syntax, Python compile checks, and
    `git diff --check` passed.
- Live API and browser evidence:
  - Through the real API, account `acc_p62_live_20260730` compiled source
    revision
    `ccsrc_df0d699fab12ed107dddf2cec7c0d43add4fd15ead8eb6ae3049e35c06098ff0`
    into immutable artifact
    `ccart_b18b29e73eea8d101435c918e8e331d8a7d082117a56759973ff366ab0ca380a`.
    Its manifest exposed metadata, supported props, defaults, the named
    unsupported-prop warning, exact toolchain versions, and all source,
    bundle, CSS, and first-frame CAS records.
  - A forbidden-import/eval fixture returned deterministic HTTP 422 diagnostics
    and no artifact. Artifact member endpoints returned their integrity-checked
    bytes, and stale source-version compilation returned HTTP 409.
  - Reloaded the actual website design editor at
    `doc_p61_custom_component_e19997f0e9f1` against the final restarted API.
    The document, editor controls, sibling content, and bounded semantic
    custom-component placeholder all rendered normally.
- Residuals:
  - No P6.2 acceptance residual. Browser execution of the compiled bundle,
    picker/prop controls, and interactive error states remain intentionally
    compile-gated until the sandboxed P6.3 runtime lands.
  - Resolved in P6.3: the runtime recursively resolves the exact pinned
    dependency graph and contains missing pins, cycles, graph-size violations,
    and version conflicts per component.
  - The compiler requires Node 24 or newer so its process permission model is
    enforced consistently in local development and CI.

### P6.3 — Sandboxed runtime and editor experience `✅`

**Purpose**

Make successful artifacts usable and safely editable by a human in the actual
website design editor.

**Work**

- Add the sandboxed iframe runtime, restrictive CSP, versioned message bridge,
  theme/personalization input, error boundary, intrinsic-height reporting,
  server first frame, and client hydration.
- Add the Custom components picker using registry `meta`.
- Add generated inspector controls for supported props and literal unions.
- Add artifact/version, compile warning, runtime error, missing artifact, and
  **Republish to update** states.
- Reuse generic selection, geometry, class-backed resize, drag/reparent,
  duplicate/delete, and history code. Do not build custom parallel versions.
- Add **Edit with AI** as an entry point only; the authoring behavior lands in
  P6.4.
- Ensure selection and pointer events stay with the editor shell while the
  component remains interactive in preview/delivery modes.

**Likely touchpoints**

- `apps/editor/src/components/web/WebEditorApp.tsx`
- `apps/editor/src/components/web/WebInspectorPanel.tsx`
- focused reusable custom-component editor/runtime modules
- `apps/api/lumen_api/web_bridge.py`
- web render/runtime endpoints and editor tests

**Observable result**

In the website design editor, a user can insert a named custom component,
select it, move/reparent/resize/duplicate/delete it, change typed props in the
inspector, and Undo/Redo those changes. Theme changes flow into it. A component
failure stays inside its frame with an actionable error.

**Acceptance**

- The runtime iframe has no `allow-same-origin` and no ambient network access.
- Forged, stale, wrong-source, or wrong-nonce runtime messages are ignored.
- Props and theme updates render the exact pinned artifact.
- String, number, boolean, and literal-union inspector controls persist through
  save/reload.
- Generic editor operations and history work without custom duplicate logic.
- One broken component cannot break sibling nodes, selection, or the editor.
- Server-rendered required content is visible before hydration; animation
  respects reduced-motion behavior.
- Keyboard and screen-reader labels cover the picker, prop controls, states,
  and component frame.

**Completion record**

- Commits:
  - `00eaeb6` — sandboxed runtime, trusted bridge, picker, generated inspector,
    typed prop persistence, and generic editor integration.
- Automated gates:
  - `cargo test --workspace` passed; the release API helper rebuilt.
  - WASM rebuilt within budget (`813150` bytes gzipped) and
    `node scripts/verify_handshake.mjs` reported `HANDSHAKE OK` at
    `7b992f8c6ec8`.
  - Agent-runtime suite: `539 passed, 2 skipped`.
  - API suite: `485 passed, 6 skipped`; focused P6.3 runtime suite:
    `7 passed`.
  - Compiler suite: `28 passed`; the checked-in React host reproduced
    byte-for-byte.
  - Editor lint/typecheck and production build passed. Focused picker,
    inspector, document, and bridge suites passed (`123` tests).
  - Full editor run: `1063 passed`; its `26` failures remain confined to the
    two pre-existing legacy `EditorApp` suites, with the same three
    missing-CanvasKit test-environment rejections. No P6.3 test failed.
- Browser evidence:
  - Verified in the actual website design editor on
    `doc_p63_live_20260730`, using the account-local `Live Pricing Card`
    artifact pinned to
    `ccart_b18b29e73eea8d101435c918e8e331d8a7d082117a56759973ff366ab0ca380a`.
  - Inserted from the accessible Custom components picker; selected the outer
    leaf without granting the nested frame editor access; observed the exact
    pin, source version, compile warning, runtime-ready state, generated props,
    and ordinary size/spacing/history controls.
  - Edited string, number, and literal-union props; observed theme-token color
    changes in the hydrated component; saved/reloaded; and verified persisted
    values. The boolean path is covered by the generated checkbox test and the
    four-type API persistence/Undo/Redo round trip.
  - Duplicated to two independently hydrated frames, reordered them through
    the generic move operation, resized one to the class-backed `w-[520px]`,
    deleted it, and verified Undo/Redo counts and reload persistence.
  - Verified the **Edit with AI** handoff selects Chat, pre-fills the component
    instruction, and focuses the composer.
  - Inspected the live nested frame: `sandbox="allow-scripts"` only,
    `referrerpolicy="no-referrer"`, `credentialless`, a 32-character runtime
    nonce, exact node/artifact identity, deny-by-default CSP with
    `connect-src`, `frame-src`, and `worker-src` set to `none`, stored
    first-frame markup before the hydration module, and reduced-motion CSS.
  - A deliberately missing runtime host and deleted artifact were separately
    exercised through the render API: sibling content remained present and
    each failure produced one bounded `LUMW0410` unavailable state.
- Residuals:
  - No P6.3 acceptance residual.
  - The AI authoring action intentionally remains an entry point until P6.4.
  - Self-contained published packaging, page-local republish/rollback proof,
    JavaScript-disabled delivery, and mobile delivery hardening remain P6.5.
  - The unrelated legacy editor-suite baseline above remains named and was not
    weakened or changed.

### P6.4 — Deep Agent authoring workflow `▢`

**Purpose**

Let the website Deep Agent create and revise components without losing source
between turns or bypassing compile/version safety.

**Work**

- Expose the durable component registry as the agent's virtual
  `/custom_components/<slug>/` filesystem.
- Add a small, non-overlapping tool surface:
  - list attachable components;
  - inspect source, schema, diagnostics, versions, and usages;
  - create/update source with expected-version protection;
  - compile/publish an immutable artifact;
  - attach or repin explicitly targeted nodes.
- Materialize a custom-components skill based on the captured Mutiny skill,
  adapted to our sandbox, operation envelope, theme, and endpoint-honesty
  rules.
- Teach the capability ladder and require a recorded `ladder_gap`.
- Keep source edits separate from document ops: compiling source does not place
  it, and attaching a component does not mutate source.
- Preserve selected-node and scoped-edit safety. An AI edit may repin only the
  intended page/nodes; stale whole-document replacement remains forbidden.
- Add trace/provenance events for source writes, compiles, artifact creation,
  attachment, repinning, and failures.

**Likely touchpoints**

- `apps/agent_runtime/lumen_agent/harness_web.py`
- `apps/agent_runtime/lumen_agent/fs_backend.py`
- `apps/agent_runtime/lumen_agent/tools/`
- `apps/agent_runtime/knowledge_docs/skills/`
- `docs/deepagent-architecture.md`
- agent-runtime and API integration tests

**Observable result**

From a real website turn, the agent can explain the capability gap, create a
component, fix a compile error, attach the successful version, and later edit
it into a new version for only the current page. A later turn can inspect and
reuse the same source. Other pages remain visually and structurally unchanged.

**Acceptance**

- Component source survives separate agent runs and process restarts.
- The agent cannot attach source that has not passed the compile gate.
- Compile errors cause source repair; transient failures use bounded retries.
- Tools cannot escape the account, slug directory, selected scope, or expected
  source version.
- Editing one page creates a new artifact and repins only explicit target nodes.
- Agent-authored endpoints are real user-provided endpoints or obvious,
  surfaced placeholders; none are invented.
- Tool results and traces expose provenance without leaking source across
  accounts.

**Completion record**

- Commits: —
- Automated gates: —
- Browser evidence: —
- Residuals: —

### P6.5 — Publish, rollback, and end-to-end hardening `▢`

**Purpose**

Close the loop so editor success and delivered-page behavior are the same
reproducible product.

**Work**

- Package pinned browser bundles, CSS, dependency artifacts, server first
  frames, runtime host, and provenance into export/publish output.
- Use content-addressed immutable artifact URLs and a publish manifest.
- Ensure preview/export/publish resolve the same pinned runtime version.
- Make component edits require explicit republish; implement rollback and
  unpublish behavior without consulting mutable latest source.
- Exercise a representative interactive component plus curated Visx/Motion/GSAP
  fixtures at desktop and mobile widths.
- Run security-negative tests for CSP, bridge forgery, network denial, path
  escape, malicious source, resource exhaustion, and cross-account access.
- Run full automated gates and live browser verification on the actual website
  design editor, preview, published page, reload, Undo/Redo, and rollback.

**Likely touchpoints**

- `apps/api/lumen_api/web_export.py`
- publish/rollback records and endpoints
- delivery runtime/assets
- browser-e2e fixtures and full-stack tests

**Observable result**

The representative flow works end to end: the Deep Agent authors a missing
interactive component, it compiles, appears inside a built-in dialog, exposes
editable props, renders a semantic first frame, behaves interactively, and
publishes with its exact artifact pin. Editing it does not change the live page
until republish; rollback restores the old rendered version.

**Acceptance**

- Export is self-contained and does not depend on mutable registry "latest."
- Published HTML exposes meaningful required content without JavaScript.
- Hydration, interaction, reduced motion, responsive behavior, and intrinsic
  sizing work in delivery mode.
- A new artifact does not change another page or an existing publish.
- Republish changes only documents/nodes deliberately repinned to it.
- Rollback reproduces the prior artifact digests and visible behavior.
- Publish manifests contain sufficient artifact and compiler/runtime provenance
  to reproduce and audit the output.
- Full repository gates and actual-browser tests are green, with any unrelated
  pre-existing failures named rather than weakened.

**Completion record**

- Commits: —
- Automated gates: —
- Browser evidence: —
- Residuals: —

## Verification policy

Each slice gets focused unit/integration tests while it is built. The final
gate follows `AGENTS.md` exactly. Because P6.1 changes `crates/`, the required
order at the relevant completion point is:

1. `cargo test --workspace`
2. `cargo build -p lumen-api-helper --release`
3. If `crates/lumen-core` changed, run `bash scripts/build_wasm_core.sh`
4. If `crates/lumen-core` changed, run `node scripts/verify_handshake.mjs` and
   require `HANDSHAKE OK`
5. full `apps/agent_runtime/tests`
6. full `apps/api/tests`
7. editor lint, focused tests, full editor tests, and production build
8. hard-refresh the actual website editor after API-side seeding
9. browser verification in the design editor, preview, and published output

Browser evidence must cover at minimum:

- create/attach, select, move, reparent, resize, and generated prop editing;
- save/reload and Undo/Redo;
- theme and personalization inputs;
- deterministic compile error and contained runtime error;
- page-local version edit with a second page remaining unchanged;
- publish, no-change-before-republish, republish, and rollback;
- desktop and mobile layouts;
- first-frame semantics with JavaScript disabled;
- iframe sandbox/CSP/bridge restrictions in the actual runtime.

## Decisions and change log

| Date | Decision/change | Reason |
| --- | --- | --- |
| 2026-07-30 | Created five-slice living plan. | Preserve the architecture and give each dependency boundary a testable exit without creating plumbing-only micro-slices. |
| 2026-07-30 | Durable account-scoped source registry plus immutable artifacts; documents pin artifact IDs. | Adopts Mutiny's proven per-page isolation while preserving our canonical document/history architecture. |
| 2026-07-30 | Separate `CustomComponent` leaf kind. | Existing built-in `Component` is a branch and `Embed` is human-owned pasted content; overloading either would weaken validation and editing semantics. |
| 2026-07-30 | Dedicated sandboxed iframe and constrained compiler worker. | Custom TSX is untrusted program code; compile checks and runtime isolation address different risks and both are required. |
| 2026-07-30 | One-account product scope, but correct account isolation/version pins now. | Avoid premature scale work without creating a migration trap or cross-page mutation hazard. |
| 2026-07-30 | P6.1 implementation started. | Establish the canonical leaf and immutable registry before compiler, editor-runtime, or agent authoring paths. |
| 2026-07-30 | P6.1 completed with normalized account-scoped families/artifacts, CAS metadata/blob storage, checked leaf operations, and bounded placeholders. | One immutable identity and persistence model is now established before any compile or execution path can create attachable artifacts. |
| 2026-07-30 | Removed a forced placeholder width discovered in live browser testing. | Platform placeholder CSS must not override the node's canonical class-backed width; after the fix, inspector and rendered geometry agreed exactly. |
| 2026-07-30 | P6.2 implementation started with a separate versioned Node compiler process and durable optimistic source revisions. | The Python API must orchestrate untrusted TSX without parsing or executing it, while deterministic authoring failures remain distinct from transient worker failures. |
| 2026-07-30 | P6.2 completed with a Node 24 permission-constrained compiler, TypeScript AST policy gate, isolated deterministic SSR smoke render, component-local Tailwind output, and immutable source/compile/artifact ledgers. | A successful artifact now has reproducible bytes and provenance, while unsafe source, stale versions, and worker failures cannot create attachable partial artifacts. |
| 2026-07-30 | Browser bundles externalize React 18 while curated libraries are bundled; the isolated first-frame build pins the same React version. | Visx's supported peer range and deterministic SSR require one explicit React identity instead of depending on the editor application's mutable package graph. |
| 2026-07-30 | Dynamic Tailwind class expressions are rejected unless every branch is statically enumerable. | Silently missing generated CSS would produce artifacts that compile successfully but render incorrectly. |
| 2026-07-30 | A post-worker source-version check rejects a compile overtaken by a concurrent source write. | The initial optimistic check alone had a time-of-check/time-of-use window that could make an older compile appear newest after a later edit. |
| 2026-07-30 | P6.3 implementation started with a dedicated nested sandbox per component and the existing outer editor bridge as the only trusted relay to the React shell. | The component must remain unable to address the editor while selection, sizing, runtime state, and canonical operations continue through existing editor-owned seams. |
| 2026-07-30 | P6.3 completed with one opaque nested frame per component, a checked-in React 18 host, exact pinned dependency-graph resolution, typed generated controls, and the existing outer bridge/history/geometry seams. | Components now execute without ambient network or editor access while humans retain ordinary selection and editing behavior and failures remain component-local. |

## Open implementation discoveries

These are investigation points inside the named slices, not unresolved product
scope:

- P6.1 resolved the registry split as account-scoped component families plus
  immutable artifact rows, CAS metadata, and content-addressed blobs. Artifact
  deletion is allowed for development/retention workflows and deterministically
  produces the document's explicit missing-artifact state rather than deleting
  or rewriting nodes.
- P6.2 resolved compiler transport as a versioned JSON protocol over a
  short-lived Node 24 process with memory, time, filesystem, and network
  constraints. Source is parsed and built there and first-frame code executes
  only inside a code-generation-disabled VM, never in the Python API process.
- P6.3 proved the smallest runtime capability set as `allow-scripts` without
  `allow-same-origin`; CSP denies network, frames, workers, objects, forms, and
  navigation. In-frame anchors and form submissions are intercepted. Network
  remains denied until an explicit endpoint contract is designed and reviewed.
- P6.2 generates and stores the deterministic first frame at successful compile
  time so it is content-addressed with the pinned artifact. P6.5 still needs to
  prove packaging and hydration use those exact stored bytes.
