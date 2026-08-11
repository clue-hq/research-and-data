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

Accounts and Contacts are live-only. Their Server Component repositories use
the authenticated server request seam, while browser-originated requests use
the same-origin `/api/clue` BFF. Other flows may retain explicitly configured
fixtures until their own cutover, but that choice remains feature-owned.

Aryan can replace or extend HTTP adapters without changing presentation
components. Fixtures must never be imported by components or routes.

## Design-system rule

Figma is the design-authoring source. `@clue/design-system` is the runtime
delivery package. Product components consume semantic or component tokens,
not raw hex values or Figma extraction JSON.

Generated files are deterministic and are not hand-edited.

The package keeps two deliberately separate inputs:

- `source/figma` is an immutable mirror used for provenance and future diffs;
- `source/product` is the verified frontend contract for approved Dev Mode
  values, including temporary reconciliations when a Figma library and its
  consuming product screens resolve different values.

Product UI consumes `--clue-ds-product-*` variables. A mismatch is documented
in the product source instead of silently rewriting the raw Figma mirror.

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
