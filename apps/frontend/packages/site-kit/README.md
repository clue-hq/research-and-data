# @clue/site-kit

The code a Puck site is built from, shared by the design API's renderer, the site agent's harness
and the editor. It is the Puck trial's portable code (`trials/puck-spike/{lib,puck,scripts}`),
made pure: nothing here reads the brand or the site from disk. The caller builds the brand with
`brandData(...)` and hands over the site's files and its agent-written sections.

The trial stays in `trials/puck-spike/` as the frozen reference.

## Entry points

| Import | What it gives |
|---|---|
| `@clue/site-kit` | `brandData` and the brand types; `makeConfig` (the Puck config: our sections, the shell, the seller's cloned sections and the site's agent-written sections); `themeCss`; `fillClone`; the page contract (`PageSchema`, `pageSchemaWith`, `ShellSchema`, `COMPONENT_SCHEMAS`, `formatIssues`); `makeKit` and `AgentSectionModule` |
| `@clue/site-kit/editor` | `CloneEditor` and `AssetPicker`, passed to `makeConfig` as `editor` so published pages never bundle them |
| `@clue/site-kit/validate` | `validateSite(files, brand, agentSections, images?)`: the agent's validator (contracts only) |
| `@clue/site-kit/catalog` | `buildCatalog(brand, seller)`: the agent's catalog as `{relative path: markdown}` (`catalog/index.md`, `catalog/clones/<id>.md`, `catalog/sections.md`, `brand/brand.md`) |
| `@clue/site-kit/check-section` | `lint(source)` and `typeCheck(file)`: the check an agent-written section must pass |

## CLIs

- `node dist/validate-site.mjs < input.json` (development: `npx tsx bin/validate-site.ts`): reads
  `{"files": {"pages": {route: page}, "shell": shell | null}, "brand": BrandData, "agentSectionSchemas": {"<Name>": <stored props JSON Schema>}, "images": {"siteImages": [...], "accountLogos": [...]}}`
  and prints `{"valid": bool, "errors": [...]}`. It never imports a section module (D2).
- `node dist/build-catalog.mjs < input.json`: reads `{"brand": BrandData, "seller": "..."}` and
  prints `{"files": {path: markdown}}`.
- `npm run build -w @clue/site-kit` (from `apps/frontend`) writes those files, and the render
  bundle (`dist/render-browser.js`), into `dist/`.
- `tsx src/check-section.ts <file.tsx>`: prints `{"ok": bool, "errors": [...]}`. It never imports
  the section (D2); the props schema is read inside the design API's hardened render page
  (`lumen_api.site_render.read_section_schema`).

## Notes

- An agent-written section imports the kit as `@/puck/agent-kit` (the trial's alias); this
  package's `tsconfig.json` maps it to `src/agent-kit.tsx`, and `typeCheck` inherits that mapping.
  The file `typeCheck` checks must sit where `zod` and `react` resolve (inside `apps/frontend`).
- Every image, logo and font a site names is `/asset-store/<sha256>`, a blob of the workspace
  (Contract 1). `validateSite`'s fourth argument names this site's generated images and the
  account's logos; anything else must be one of the brand's assets.

## Tests

```bash
cd apps/frontend
npm test -w @clue/site-kit
npm run typecheck -w @clue/site-kit
```

The fixtures in `test/fixtures/` are the trial's Garner export (`data/brands/garner/*.json`), its
`garner-syracuse` and `conduit-atrium` sites, and the example section from its writing-a-section
skill. `clones.json` keeps only the five clones the `garner-syracuse` site uses, with each clone's
captured CSS replaced by a stub (no test reads it), so the fixtures stay small.
