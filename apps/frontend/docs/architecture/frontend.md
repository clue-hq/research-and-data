# Clue frontend architecture

Status: production frontend standard.

The Clue frontend is a Next.js App Router application written in TypeScript.
It renders the Figma product design and exposes stable contracts for backend
integration. Business rules and persistence remain backend responsibilities.

## Documentation rule

Every product flow, backend integration, or architectural topic has one living
canonical document indexed by `docs/README.md`. Repeated discussions update the
same document; separate documents are created only for separate scopes. Any
backend-owned data change also updates the matching file under
`docs/api-contracts/`.

## Dependency direction

```text
app routes
  -> feature repositories
  -> runtime schemas and domain models
  -> feature controllers/hooks
  -> presentation components
  -> @clue/design-system
```

Dependencies must not point upward. In particular, presentation components
must never import repositories, fixtures, environment variables, or transport
clients.

## Folder responsibilities

```text
src/app/
  Route entry points, metadata, server-side orchestration, loading and error UI.

src/features/<feature>/model/
  Zod response schemas, domain types, and view-state types.

src/features/<feature>/data/
  Repository interfaces and transport adapters. A feature may be live-only;
  fixture adapters are optional and must never be an implicit production fallback.

src/features/<feature>/hooks/
  Feature-level client state and interaction controllers.

src/features/<feature>/<subfeature>/hooks/
  Subfeature-specific interaction controllers.

src/features/<feature>/components/
  Typed presentation and small composition boundaries.

src/components/
  Application-wide shell and reusable non-domain presentation.

packages/design-system/
  Figma provenance, generated tokens, and reusable Clue UI assets.
```

## TSX rule

TSX files express visual structure and bind typed props to events. They do not:

- fetch or mutate remote data;
- select fixture versus HTTP implementations;
- read environment variables;
- contain business validation;
- manufacture backend records;
- parse API responses;
- embed large state machines.

Reusable interaction logic belongs in a `.ts` controller hook. Backend
interaction belongs behind a repository or transport interface. A small TSX
container may invoke a controller and pass its values to a pure view; it must
not implement the controller itself.

## Route rule

App Router pages remain Server Components unless browser interactivity is
required. Route files may orchestrate independent repository reads with
`Promise.all`, handle `notFound`, and pass serializable typed props to a
feature screen. They should not contain visual page markup beyond composition.

## Data and backend handoff

Every backend-owned payload has:

1. a Zod schema under `model`;
2. a repository interface under `data`;
3. an authenticated HTTP adapter when a live backend contract exists;
4. an explicit unavailable/empty model when a backend capability does not yet
   exist — never unrelated demo data selected by missing configuration;
5. a written contract under `docs/api-contracts`.

Accounts and Contacts are live by default. Their Server Component repositories
use the authenticated server request seam, while browser-originated requests use
the same-origin `/api/clue` BFF. They also ship the design build's fixture
repositories, selected only by the explicit opt-in `CLUE_ACCOUNTS_FIXTURE_MODE=true`
(the exact string, read in exactly one module) for local design work. That flag is
a switch, never a fallback: with it unset, a live read that fails fails loudly and
no fixture stands in for it. Other flows may retain explicitly configured fixtures
until their own cutover, but that choice remains feature-owned.

Aryan can replace or extend HTTP adapters without changing presentation
components. Fixtures must never be imported by components or routes.

## Design-system rule

Figma is the design-authoring source. `@clue/design-system` is the runtime
delivery package. Product components consume semantic or component tokens,
not raw hex values or Figma extraction JSON.

Generated files are deterministic and are not hand-edited.

The package has one resolved generator input: `source/production`. It records
both the production Clue product source and the published Clue Design System
source, together with explicit conflict-resolution rules. A sync replaces this
resolved snapshot; it never appends another override layer.

Product UI consumes canonical semantic and typography tokens directly. The
`--clue-ds-product-*` namespace is limited to application geometry, motion, and
component contracts that do not exist as published Figma variables.

`generated/legacy-compat.css` is the one temporary exception. It holds the
variables only the pre-D4 token set defined, so the features that have not been
re-synced yet keep rendering; it is data, not a generator layer, and
`design-system:build` neither reads nor writes it. It is imported once, in
`src/app/layout.tsx`, immediately after `tokens.css`, and it may only shrink.
The CSS re-sync job deletes it together with its one-shot extractor
(`packages/design-system/scripts/extract-legacy-compat.mjs`). Every
`var(--clue-…)` referenced under `src/` must resolve in `tokens.css`,
`legacy-compat.css` or `globals.css` — `src/design-system-tokens.test.ts`
enforces that.

## Component rule

- Prefer a small component with one visual responsibility.
- Receive data and callbacks through explicit TypeScript props.
- Keep feature components close to their feature.
- Promote a component to the shared design system only when it is reusable
  across product domains.
- Keep server/client boundaries narrow to minimize shipped JavaScript.
- Preserve accessibility semantics and keyboard behavior.

## Required validation

Every structural or design-system change runs:

```sh
npm run design-system:build
npm run lint
npm run build
```

Interactive flows also receive a localhost browser smoke test.


## Shared Markdown documents (Lane 2, 2026-09-14)

`components/markdown/` owns the client-only MDXEditor 4.2.5, its library toolbar,
react-markdown/GFM preview and versioned draft transitions. Feature hooks retain
permission, fetching and save ownership. No custom parsing or formatting engine.

Project Gallery combines typed design cards with real project-document summaries
from the authenticated repository/BFF. Documents do not impersonate design artifacts.
`useProjectDocumentTabs` shares the list, resolves transcript references to stable
paths, and opens named tabs only after a click or fresh write. There is no fixed
Plan/Documents tab. Internal `surface=plan` remains a URL compatibility alias;
`document=<path>` selects the current file. Each visited file keeps its editor mounted
for draft/undo retention until the chat is left. Source parse errors cannot be saved.
The backend still owns kinds, titles, paths, revisions and access decisions.

Toolbar controls and shortcuts are native. H4–H6 stay available because the native
selector shares parsing configuration. Modifier shortcuts for strike/code/lists are
not added where the release does not provide them; their toolbar controls remain.
