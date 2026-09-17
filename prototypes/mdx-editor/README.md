# Clue MDXEditor prototype

Working review demo for Lane 2, isolated from `apps/frontend` and its dependencies.
Open **http://localhost:3047/**. No production repository, API, database, environment
file, account or project is used. Other Semarang/sibling-workspace servers are unaffected.

## Run

From this directory:

```sh
npm ci
npm run dev
```

The server binds to `127.0.0.1:3047`. Do not stop another process to claim this port.
The predev/prebuild asset step copies the current generated Clue tokens, local Satoshi
fonts and logo from `apps/frontend`; those generated copies are ignored by Git.
DM Mono is supplied locally by the pinned font package. There are no runtime font/CDN calls.

```sh
npm run typecheck
npm test
npm run build
```

## Review

- Four disposable samples: campaign plan, Knowledge document, long text/tables, and
  intentionally unsupported source. Each visited document keeps its own draft/history.
- Native MDXEditor controls for headings, bold/italic/strike, inline monospace, lists,
  links, table insertion/cell editing, monospace blocks and horizontal rules.
- Preview uses `react-markdown` + `remark-gfm`. Preview/Edit keeps the editor mounted.
- Save persists only to this browser/origin, under `clue:mdx-prototype:v1:<sample-id>`.
  Reload shows saved content; unsaved content is intentionally not autosaved. Discard
  restores the saved sample. Reset sample restores the original fixture.
- Source mode is provided by MDXEditor. After a source edit, switch to Rich text to
  validate the import before Save. Import failures retain the source and block Save.
- Read only disables editing and hides the formatting toolbar. Switching the demo's
  permission toggle starts a fresh editor history from the current draft, retaining
  source edits. Ordinary Preview/Edit and sample switching keep history.
- Full, 440px and 360px panel controls exercise wrapping. Wide tables scroll locally;
  prose, long URLs, inline monospace, blocks and source wrap within the panel.

Per founder review, code blocks are simple monospace text: no language picker or syntax
highlighting. Native fence metadata is retained when editing existing Markdown. The
native language control is hidden using its semantic `aria-label`, not a generated class.
Source mode and blocks have no visible line numbers. Image insertion, AI writing,
collaboration, diff review and production persistence are outside this prototype.

## Plan tab review — Lane 2 step 4

Open **http://localhost:3047/plan** on this same server. This is the visual review
checkpoint for Plan-tab plan Tasks 6–7, before the live shell is integrated.

- Gallery / Target accounts / Plan tab rail with Arrow keys, Home and End navigation.
- Slim document-name header, Preview/Edit, Save/Discard and a centered Markdown article.
  The document scrolls inside its pane; the header and tab rail stay in place.
- Plan ready and the specified No plan yet state; split, full and 360px layouts.
- The chat's collapsible plan card opens the Plan tab. Close and reopen the panel to
  check draft retention. “Simulate plan arrival” opens the tab with sample content;
  it does not run an agent, consume transcript events or call a backend.
- The existing prototype's editor/session is reused, with lazy initial editor mounting
  and the same library controls. Once opened, it stays mounted across Preview/Edit,
  tab switches and panel closing. Opening Edit alone does not enable Save.
- Saves use the distinct `clue:mdx-prototype:v1:plan-tab` browser key. Reset sample
  affects only this sample. The root editor demo and real documents are unaffected.

Real document reads/saves, URL state and transcript-driven auto-open belong to the
production integration after visual approval. That integration also needs the local
Semarang backend/schema rollout noted in the Lane 2 plan.

## Compatibility finding (initial prototype; resolved by Task 5)

Verified release set: MDXEditor **4.2.5**, Next **16.2.12**, React/React DOM **19.2.4**,
with MDXEditor's supported **Lexical 0.48.0** tree. Next/React match the main application.
Client-only dynamic import includes all MDXEditor plugins. Next Turbopack development
and webpack production build pass with this isolated dependency set.

The first experiment also installed the application's direct Lexical **0.49.0** packages.
It built successfully, but failed in the browser with:

> HorizontalRuleNode … is not a constructor that subclasses LexicalNode from the lexical package used by this editor

npm placed separate Lexical 0.48 instances beneath MDXEditor and `@lexical/react`.
Their nodes therefore did not share the editor's constructor identity. Removing the
experiment's application-Lexical dependencies and deduplicating the prototype's supported
0.48 tree resolved the failure. **No main-app dependency was changed or overridden.**
The dependency test guards this exact failure inside the prototype. It does not prove
coexistence with the application's existing 0.49 design text editor. Resolve version alignment or
a genuinely isolated bundle, then test both editors together before migration. Lane 2
Task 5 Step 1 initially remained open for that production compatibility decision/proof.

**2026-09-14:** the main app now aligns its direct Lexical packages with the supported
0.48.0 tree, with no overrides. Main-app Knowledge browser checks, constructor-identity
tests, design text regressions and the production build pass. See
`apps/frontend/src/components/markdown/README.md` (from the repository root).

## Integration details to carry forward

- The editor's `markdown` prop is an initial value, never a keystroke-controlled replacement.
  Plugins and toolbar callbacks keep stable identities while drafts change.
- Ignore initial normalization and compare future output with that baseline. Opening,
  focusing or undoing to the baseline must not create a fake edit. Untouched raw bytes
  remain the saved value; actual edits may normalize whitespace and list markers.
- Disable automatic URL linking during visual import: it caused an additional mutation
  after initial normalization, marking the long-URL fixture dirty without user input.
  Explicit links and the native link dialog remain available; Preview uses GFM autolinks.
- Do not overwrite the draft with an import error's trimmed/empty content. Keep the
  library's recoverable source and block Save while an import error exists.
- MDXEditor's source view rebuilds from its visual value when readOnly changes. The
  demo remounts from the current draft for permission transitions to prevent source loss.
  Production permission/busy transitions need the same preservation guarantees.
- The native block selector exposes H1–H6. Keeping all six preserves existing deeper
  headings; no custom selector or parser was added to restrict creation to H1–H3.
- Library variables/public classes theme toolbar, popups and body; compact controls use
  28px dimensions. Satoshi, DM Mono, typography, colors and button radii use Clue tokens.
  No generated vendor class names or dependency code are edited.

## Verification on 2026-09-13

TypeScript, three focused tests and the Next production build pass. Browser checks used
the separate `127.0.0.1` origin so the user's `localhost` demo drafts were not changed.

Verified: initial clean state for normal/long/unsupported documents; bold and italic;
inline monospace and monospace-block insertion/editing; native link creation; table
insertion/cell editing; H4/H6 preservation; separate drafts; Preview/Edit with undo back
to a clean saved baseline; Discard; source recovery; Save/reload; read-only visual/source
behavior and source draft retention during permission changes. At 360px, the frame,
toolbar, document and code stay contained; only the wide table scrolls. Final test-tab
console inspection had no errors/warnings.

Production backend/version-conflict semantics, every keyboard binding, main-app composer
coexistence and full Knowledge/Plan integration remain future acceptance work. This demo
does not claim those production gates are complete.

## Library references

- [Next.js integration and initial-value lifecycle](https://mdxeditor.dev/editor/docs/getting-started)
- [Native toolbar controls](https://mdxeditor.dev/editor/docs/customizing-toolbar)
- [Public theming surfaces](https://mdxeditor.dev/editor/docs/theming)
- [Error recovery](https://mdxeditor.dev/editor/docs/error-handling)
- [Source view](https://mdxeditor.dev/editor/docs/diff-source)
