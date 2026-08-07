# Clue frontend

Production-oriented Next.js frontend for the Clue platform. The implemented
shells follow the approved Figma **Account & Contacts flow - (dev)** and
**Projects/chat flow** frames. They cover the account workspace plus the clean
Home composer, project threads, generation progress, persistent artifact
Gallery, artifact viewers, and the canvas inspector shell.

## Stack

- Next.js App Router + React + TypeScript
- Tailwind CSS v4
- AI Elements inline attachments, installed as local source components and
  mapped to Clue design tokens
- Zod validation at data boundaries
- Satoshi 400/500, bundled locally for the Clue application shell
- Inter variable, self-hosted through Fontsource for editable artifact canvases that specify Inter in Figma
- Figma-exported interface icons
- Lobe Icons and Iconify Logos for repeatable brand assets

## Run locally

```bash
npm install
npm run assets:sync
npm run dev
```

Open one of the implemented states:

- Home composer: <http://localhost:3000/>
- New project thread: <http://localhost:3000/projects/10m-landing-page-campaign?thread=thread-primary>
- Completed artifact gallery: <http://localhost:3000/projects/10m-landing-page-campaign/gallery?thread=thread-primary>
- Editable web artifact: <http://localhost:3000/projects/10m-landing-page-campaign/artifacts/landing-page-sharper-abm?thread=thread-primary>
- Project placeholder: <http://localhost:3000/projects>

- Table: <http://localhost:3000/accounts>
- Side preview: <http://localhost:3000/accounts/openai/preview>
- Full account page: <http://localhost:3000/accounts/openai>
- Account contacts: <http://localhost:3000/accounts/openai/contacts>
- Full contact page: <http://localhost:3000/accounts/openai/contacts/denise-dresser>
- Account insights: <http://localhost:3000/accounts/openai/insights>
- Account artifacts: <http://localhost:3000/accounts/openai/artifacts>
- Account activity: <http://localhost:3000/accounts/openai/activity>

Quality checks:

```bash
npm run design-system:build
npm test
npm run lint
npm run build
npm audit --omit=dev
```

## Architecture

```text
src/
  app/                         Routes and route metadata
  components/
    ai-elements/                Local AI Elements source components
    shell/                     Cross-feature application shell
    ui/                        Small shared design primitives
  config/                      Data-driven navigation
  features/
    accounts/
      components/              Account-specific presentation and interaction
      data/                    Fixture and HTTP repository adapters
      model/                   Runtime schemas and inferred TypeScript types
    projects/
      config/                  Auditable Figma icon registry
      components/              Home, project thread, Gallery, and canvas UI
      data/                    Fixture and HTTP repository adapters
      hooks/                   Client-only interaction controllers
      model/                   Project/thread/run/artifact runtime schemas
public/
  fonts/                       Local Satoshi files
  icons/                       Exact SVG interface assets from Figma
  logos/                       Library-backed and vetted brand assets
docs/api-contracts/            Backend handoff specifications
packages/design-system/
  source/figma/                Immutable Figma extraction and provenance
  source/product/              Verified frontend semantic contract
  generated/                   Deterministic runtime tokens
```

The React components never import fixture records. `/accounts` calls
`getAccounts()`, account pages call `getAccountDetails()`, the contact flow uses
`getAccountContacts()` / `getAccountContact()`, and the remaining tabs call
`getAccountWorkspace()`. Home and project routes use `getProjectHome()` and
`getProjectWorkspace()`. Each function uses a feature-owned fixture repository
by default and switches to its HTTP adapter when `CLUE_API_BASE_URL` is
configured. Responses from either adapter are validated with the same Zod
schema before they enter the UI.

Backend-provided contact photos use the `avatarUrl` contract and have an
initials fallback. The browser does not scrape LinkedIn or couple rendering to
a fixed image host.

Copy `.env.example` to `.env.local` when the backend is ready:

```bash
CLUE_API_BASE_URL=https://api.cluehq.ai
```

The expected endpoints and payloads are documented in
[`docs/api-contracts/accounts.md`](docs/api-contracts/accounts.md) and
[`docs/api-contracts/projects.md`](docs/api-contracts/projects.md).
The canonical documentation index and update rules live in
[`docs/README.md`](docs/README.md).

## Design fidelity

The Accounts flow is implemented against these native Figma frames:

- `904:87762` — account table, 1680×945
- `904:87798` — account side preview, 1680×945
- `904:87904` — full account page, 1680×1399
- `904:88166` — account contacts table, 1680×945
- `904:88226` — selected contact drawer, 1680×945
- `904:88008` — full contact page, 1680×945
- `904:88089` — account insights, 1680×945
- `904:88108` — account artifacts, 1680×945
- `904:93875` — artifact preview, 1680×945
- `904:88125` — account activity, 1680×945

The application shell owns the viewport: side navigation and the 58px account
header remain fixed, while only the active content pane scrolls. Tables isolate
horizontal scrolling beneath their fixed toolbar. At widths below 1024px the
sidebar becomes a modal drawer, and account detail rails become on-demand
overlays instead of compressing the primary content.

Run `npm run assets:sync` after dependency updates to reproduce library-backed
brand SVGs. Screen-specific Figma exports, including the preview-table logo
glyphs and contact portraits, are stored locally and optimized for their
rendered size.

### Token precedence

The standalone Clue Design System export remains preserved under
`packages/design-system/source/figma`. Approved product components can resolve
newer external Tier 1/2/3 library values before the raw local collection is
updated, so verified Dev Mode values are recorded separately under
`packages/design-system/source/product`. Account and contact UI consumes the
generated `--clue-ds-product-*` contract; the raw mirror is never rewritten to
hide a mismatch.
