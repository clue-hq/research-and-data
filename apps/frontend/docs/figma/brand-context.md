# Brand Context fidelity map

Source file: `NcLl2r0dzVDN28xAQCwvM1`

Source page: `brand-context page`
Entry node supplied for implementation: `1149:72074`

Status: production-file correction implemented and browser-verified on
`codex/brand-context-page` at the 1680 × 945 Figma viewport.

The linked production Clue file is the only visual source used for this flow.
Older Brand Context explorations in the execution file are not implementation
evidence for this branch.

## Approved screen map

| Screen | Figma node | Frontend state |
| --- | --- | --- |
| Colors | `1679:73717` | `/brand-context?section=colors&theme=light` |
| Markdown preview | `1464:31303` | `/brand-context?section=knowledge&file=company%2FOverview.md&mode=preview` |
| Markdown edit | `1679:76593` | `/brand-context?section=knowledge&file=company%2FOverview.md&mode=edit` |
| Assets grid | `1757:35613` | `/brand-context?section=assets&view=grid` |
| Assets list | `1757:34828` | `/brand-context?section=assets&view=list` |
| Asset details | `1760:45204` / `1760:45229` | `asset` query set, read mode |
| Asset metadata edit | `1760:44669` / `1760:44972` | `asset` query set, field-level inline edit |
| Typography | `1676:67581` | `/brand-context?section=typography` |
| New style | `1679:73518` | Typography + New style dialog |
| New typeface | `1679:73514` | Typography + New typeface dialog |

The Brand Context sidebar uses the 32px-high `.Sidebar.item` component family.
The Brand Context layout preserves the production root split: 250px application
sidebar + 240px Brand Context sidebar. Both structural dividers are 0.5px; the
content header and panel do not add a second border over the sidebar divider.

The secondary navigation follows the production component geometry:

- 8px horizontal inset, producing a 224px item width
- 32px section headers and navigation rows with a 4px corner radius
- Satoshi 13/18 regular for `Brand kit` and `Knowledge`
- Satoshi 13/18 regular for navigation and document rows
- `Brand context` uses the production `tittle-sm` treatment: Satoshi 18/30 bold
- the open Company folder has no disclosure chevron; `Overview.md` owns a
  separate 1px × 32px tree-rule element at its 16px inset, with no horizontal
  branch or row-level pseudo-element
- hover and selected fills remain inside the 224px item area
- inactive navigation icons and labels both resolve to `color/content/subtle`
  (`#5E636C`); section labels resolve to `color/content/neutral` (`#1C2028`)

The Assets shell follows the two-row production header in nodes `1757:35613`
and `1757:34828`: a 36px title row, a 58px toolbar row, 240×34 search, a
chevron-based category Filter, and a 78×34 grid/list control. The filter covers
All assets, Logos, Backgrounds, Mockups, and AI-generated images while leaving
the table `Type` field MIME-oriented. List rows are 64px with 48px previews.
Name, Type, Size, and Created use the production 12px sort glyphs; Created is
descending by default. Asset overflow actions remain hidden until hover,
keyboard focus, or menu-open state and expose Rename, Edit details, and Delete.

## Production design-system source

The production Clue file is now the primary local variable authority:

- `packages/design-system/source/production/manifest.json`
- `packages/design-system/source/production/variables.json`

The verified Figma collections contain 183 primitives, 18 semantic tokens, and
52 typography variables. The typography collection resolves to 13 Satoshi/DM
Mono roles with four properties each. The generator overlays these production
values on the older component-token compatibility mirror.

Light and Dark on the Colors screen are two brand-palette datasets. They never
change the Clue page, sidebar, content, or application theme.

The palette selector follows production node `1757:29186`: a 34px-high,
two-item control with a 1px item gap, 12px horizontal content inset, 4px
icon-to-label gap, and Satoshi 13/18 medium labels. The exported sun and moon
vectors retain their native 11px and 10px footprints, centered inside matching
12px icon boxes instead of being stretched to a common glyph size.

## Exported production icon set

The Brand Context navigation no longer approximates production icons with a
general-purpose icon library. The following SVGs were exported from the exact
production component instances and are stored under
`public/icons/brand-context/`:

| UI role | Figma component | Local asset |
| --- | --- | --- |
| Colors | `Icons/swatch-book` | `swatch-book.svg` |
| Typography | `Icons/type` | `type.svg` |
| Assets | `Icons/album` | `album.svg` |
| Knowledge folder | `Icons/folder-closed` | `folder-closed.svg` |
| Knowledge document | `Icons/file-text` | `file-text.svg` |
| New folder | `Icons/folder-plus` | `folder-plus.svg` |
| New document | `Icons/plus` | `plus.svg` |
| Light palette | `Icons/sun` | `sun.svg` |
| Dark palette | `Icons/moon` | `moon.svg` |
| Asset search | `Icons/search` | `assets/search.svg` |
| Asset filter disclosure | `Icons/chevron-down` | `assets/chevron-down.svg` |
| Asset grid view | `Icons/layout-grid` | `assets/layout-grid.svg` |
| Asset list view | `Icons/list` | `assets/list.svg` |
| Asset sort resting | `Icons/arrow-up-down` | `assets/arrow-up-down.svg` |
| Asset sort descending | `Icons/move-down` | `assets/move-down.svg` |
| Asset row actions | `Icons/ellipsis` | `assets/ellipsis.svg` |
| Assets share link | `Icons/link` | `assets/link.svg` |

These SVGs retain the production stroke weight and geometry. The shared
`BrandContextIcon` wrapper only controls their rendered size and alignment.

## Deliberate product extension

The supplied New typeface dialog covers library font search. The implementation
adds the explicitly requested custom-font upload affordance inside that dialog,
without changing the approved outer dimensions or action hierarchy. The shell
accepts OTF, TTF, WOFF, and WOFF2 files; upload, validation, licensing, storage,
and delivery are backend work documented in the API contract.

## Component ownership

| Responsibility | File |
| --- | --- |
| Route orchestration | `src/app/brand-context/page.tsx` |
| Runtime schemas and view types | `src/features/brand-context/model/brand-context.ts` |
| Fixture and HTTP repository boundary | `src/features/brand-context/data/` |
| URL and interaction state | `src/features/brand-context/hooks/use-brand-context-controller.ts` |
| Application composition | `src/features/brand-context/components/brand-context-screen.tsx` |
| Brand Context navigation | `src/features/brand-context/components/brand-context-sidebar.tsx` |
| Colors | `src/features/brand-context/components/colors-panel.tsx` |
| Typography and type dialogs | `src/features/brand-context/components/typography-panel.tsx` |
| Assets and detail dialog | `src/features/brand-context/components/assets-panel.tsx` |
| Knowledge preview/editor | `src/features/brand-context/components/knowledge-panel.tsx` |
| Raw Markdown source editor | `src/features/brand-context/components/markdown-source-editor.tsx` |

Visual components receive typed values and callbacks. They do not import
fixtures, repositories, environment variables, or transport clients.

## Validation checklist

- Main AppSidebar remains the production shell and marks Brand context active.
- The second sidebar is independent of the Settings sidebar.
- Main canvas and sidebars remain fixed while each content panel scrolls.
- Colors retain light/dark brand-palette state in the URL without changing the application theme.
- Assets support search, category filtering, grid/list switching, details, inline
  rename, metadata edit, and delete/archive shell. The Filter and item overflow
  menus are keyboard accessible and close when focus leaves or Escape is used.
- Asset details close on Escape, the close control, or a backdrop click. Title
  and description use independent inline edit controls; there is no global edit
  mode or duplicated save button.
- Knowledge supports a Company/`Overview.md` route, Preview/Edit, and Share.
- The Knowledge header is a compact document breadcrumb: path segments use
  13/18 regular and the active filename uses 13/18 medium. It intentionally
  does not reuse the 24px page-heading treatment from Colors or Typography.
- Knowledge edit uses CodeMirror 6 with Markdown language support, DM Mono,
  line numbers, syntax colors, and raw-string state. The source canvas uses the
  production 32px outer inset, 16px number column, 24px number-to-source gap,
  and 13/20 code rhythm. This matches the production source-edit design and
  keeps the backend payload as plain Markdown.
- Typography supports typeface and text-style creation shells.
- Typography keeps the three production typeface samples in one responsive row
  and presents text styles as a single aligned table. `Font-weight` and
  `Line-height` remain single-line column labels rather than wrapping into tall
  header cells.
- A typeface card's three-dot control is its scoped action menu. It can seed a
  new text style with that typeface; uploaded custom typefaces also expose a
  remove action. It is not a second edit mode.
- Custom-font selection is frontend-only until the documented upload contract
  is implemented.
- Browser QA at 1680 × 945 confirms the white app surface in both palette modes,
  174 × 188 swatches, two accent cards, the compact typography matrix, asset
  grid/list states, and the centered Markdown preview.
