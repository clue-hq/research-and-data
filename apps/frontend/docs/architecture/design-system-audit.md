# Frontend design-system baseline audit

Status: reviewed, 2026-10-24. This document is the living baseline for new platform UI work.
Branch at review: `feat/direct-mail-infrastructure-ui`; source commit: `ab10fd287`.
Review only: no runtime styles, tokens, application components, fixtures, env values, or Figma designs were changed.

## Scope and evidence boundary

Reviewed the resolved token package and generator, all ten shared UI TSX files,
the global font/theme wiring, shell and navigation, and representative tables,
toolbars, drawers, forms, notifications, and repository adapters. Inventoried
750 non-test TS/TSX/CSS source files across 11 feature directories, 26 page routes,
34 CSS modules, and 325 existing test files. This was a whole-source inventory
and targeted code review, not a line-by-line correctness review of all 750 files.

Read live Figma collections, all 278 variable definitions, all 14 text styles,
19 effect styles, and the component inventory of all 11 library component pages.
Visually inspected the live Button component set and the production Accounts
table frame. No localhost application was started; no full-app screenshot
comparison, lint, production build, or interaction/accessibility audit was run.
Frontend node_modules is not installed in this worktree.

## Source of truth and generation

| Source | Role |
| --- | --- |
| [Clue product](https://www.figma.com/design/NcLl2r0dzVDN28xAQCwvM1/Clue?node-id=1241-33471) | Product composition, approved screen patterns and product-local components |
| [Clue Design System](https://www.figma.com/design/Gqz4ROcgy5sZ4HMWsLpOVf/Clue-Design-System?node-id=69-3108) | Published components, color variables, typography and effects |
| [Resolved package source](../../packages/design-system/source/production/README.md) | One reconciled local input, with provenance and conflict-resolution rules |
| [Generator](../../packages/design-system/scripts/build-tokens.mjs) | Deterministically creates runtime CSS; validates counts, duplicate definitions and aliases |
| [Frontend standard](frontend.md) | Component, route, data, fixture, and integration boundaries |

The live library has **183 primitives, 43 semantic color tokens and 52 typography
variables**. The product file has 183 primitives, **27** local semantic tokens,
and 52 typography variables. Do not replace the resolved 43-token library set
with the smaller product-local set.

The package has 14 rendered text-style definitions (13 standard styles plus
Chain of thought), 21 application geometry/motion entries, and three component
contracts: Button (22 entries), Sidebar (11), Chat (3). Generated CSS defines
340 variables. The package exports CSS, not React UI components; React controls
currently live in the application.

The manifest is dated 2026-08-18; the Chat contract records a later approved
2026-09-20 change. Age alone does not establish drift: live comparisons below
distinguish what matches from what needs reconciliation.

All **226 color definitions and aliases match the live library** after CSS
name and RGBA normalization. All **14 text styles match** by Figma style ID,
family, style/weight, font size and line height. Collection-count agreement
does not establish component-geometry agreement.

## Visual foundation

- Satoshi is the main UI family; DM Mono Light is used for code. Inter is also
  imported for existing supporting surfaces.
- Published type scale: headings 24/36 and 18/30 at weight 700; large body 16/24;
  default body 14/20; small UI 13/18; captions 11/16; code 13/20.
- The published styles named text-lg-bold, text-default-bold and text-sm-bold
  resolve to Medium/500 in Figma. The repository correctly follows the actual
  style rather than inferring weight 700 from its name.
- Preserve Figma's `tittle-*` spelling in provenance and canonical tokens.
- Chat has a separate approved 14/22 body contract. Do not apply its line height
  globally to tables or forms. See [the chat fidelity map](../figma/projects-chat-flow.md).
- The shell has a 240px sidebar, 32px navigation rows, and a 58px action bar.
  Table tokens include 48px headers and 44/56/64px row density choices.
- Standard motion durations are 140/160/180ms. Several existing controls and
  shell styles honor reduced motion; this is not a verification of every control.
- Brand Context Light/Dark choices are customer brand-palette datasets,
  not application theme switches.

## Live Figma component inventory

Counts below are component nodes, including variants; they are not counts of
distinct React components. Decorative cover/separator pages are excluded.

| Library page | Component nodes | Component sets | Coverage |
| --- | ---: | ---: | --- |
| Avatar | 80 | 2 | Avatar and avatar group |
| Badge | 13 | 1 | 13 color variants, optional leading/trailing icons |
| Button | 109 | 3 | 60 standard, 45 icon, 4 link variants |
| Checkbox | 6 | 1 | Default, checked, indeterminate, disabled, hover and one generically named state |
| Dropdown | 15 | 3 | Control, values and label |
| Popover | 3 | 2 | Menu and menu item |
| Input | 15 | 2 | 12 field variants, 2 value variants, standalone label |
| Progress | 10 | 1 | Circular progress at five values and two sizes |
| Toggle | 2 | 1 | On/off |
| Icons | 1554 | 1 | Icon components, including a Socials set |
| Utils | 2 | 1 | Clue logo variants; page also contains typography specimens |

The full 60-variant button matrix is primary/secondary/transparent/critical ×
resting/hover/pressed/disabled/focused × lg/md/sm. Live component key:
`6e7c44bfbc0ea6fdb291fc342dc8791beb561ca5`.

## Findings to account for before new UI implementation

### DS-01 — Button geometry and React variants are not fully aligned

[Button source contract](../../packages/design-system/source/production/components/button.json)
records component-set node `1390:48408`, which no longer resolves in the live
library. The current set is `69:3647`; its stable key still matches.

For the primary/resting/lg variant:

| Property | Live Figma | Local token contract |
| --- | ---: | ---: |
| Height | 40px | 44px |
| Vertical padding | 6px | 8px |
| Horizontal padding | 16px | 20px |

The md variant is aligned at 32px height, 4/12px padding and 4px radius. The sm
variant is aligned at 26px height, 2/8px padding and 2px radius.

[Shared Button](../../src/components/ui/button.tsx) is a hybrid: the newer
`primary`, `transparent` and `md` entries consume Clue contracts, while older
variants and sizes retain their previous styling. Its `lg` uses `h-9` (36px
under the default spacing scale) and `sm` uses `h-7` (28px). Its base also
applies general rings, borders and disabled opacity. Do not assume a named
variant/size matches Figma merely because the token exists.

Before direct-mail uses these controls, agree the current target and validate
the required sizes and all interaction states. Changes to existing global
variants need regression coverage for their current consumers.

### DS-02 — Font delivery does not cover the published heading/italic styles

[Global CSS](../../src/app/globals.css) declares only Satoshi normal 400 and
normal 500. The only local Satoshi assets are regular and medium WOFF2 files.
The design system specifies 700 headings and an italic reasoning style.
There is no matching declared Satoshi 700 or italic face, so those appearances
depend on browser synthesis/fallback. Typography values matching Figma is not
enough to guarantee matching glyphs or wrapping.

Supply the approved font faces or a correctly declared variable family before
pixel-level acceptance of new heading/italic typography.

### DS-03 — Compatibility debt remains explicit and test-allowed

[legacy-compat.css](../../packages/design-system/generated/legacy-compat.css)
defines 48 old typography variables. Six source files still reference names
from that set: app-sidebar, project-sidebar-tree, chat-shell, scene-text-toolbar,
web-rich-text-toolbar and web-annotation-popover CSS.

The token test intentionally allows two unresolved variables:
- `--clue-content-default`: contact-row.tsx, line 140.
- `--clue-ds-color-bg-input`: chat-shell.module.css, line 198.

The current test passes with those exceptions; a passing test is not proof
that every token reference resolves. Keep new direct-mail code on canonical
tokens and do not expand the compatibility layer or its allowlist.

### DS-04 — Figma coverage exceeds the shared React control coverage

The ten shared UI TSX modules are Button, Badge, Card, Alert, CheckboxField,
SelectField, Collapsible, HoverCard, ConfirmationCard and DesignIcon.
Input/Textarea/Toggle implementations currently live inside Settings; table,
badge, avatar and drawer implementations are also feature-specific.

The shared Badge is a generic variant-based control rather than the complete
13-color Figma badge contract. The package is therefore a token foundation with
partially shared controls, not a complete one-to-one React library.

Audit candidates for first implementation: a consistent field wrapper,
input/textarea errors and help text, status badge, modal/drawer behavior, and
the required button variants. Extract a shared component when it is reused
across domains; keep direct-mail business-specific controls in its feature.

### DS-05 — Reuse the documented data boundary, with care around older examples

[Frontend architecture](frontend.md) requires schemas and models, repositories
and adapters, controller hooks, and presentation components. The Accounts
repository demonstrates explicit fixture selection and Zod validation; live
failures never silently become fixtures.

Not every existing component follows the ideal boundary:
[ProjectTargetAccounts](../../src/features/accounts/components/project-target-accounts.tsx)
contains fetch calls and schema parsing in TSX (lines 200 and 216).
Use the documented boundary for new work instead of copying that container's
transport logic into direct-mail UI.

Aryan's handoff should consist of explicit proposed request/response contracts,
validated fixture scenarios and a repository interface. Implement the HTTP
adapter against an agreed backend contract; screens should continue receiving
the same typed data and callbacks.

### DS-06 — Visual regression coverage needs to be established for the new flow

No Storybook stories or Playwright configuration was found under apps/frontend.
The existing token guard tests definition availability, not rendered pixels,
focus behavior, responsive layouts or Figma correspondence.

There are also generic shadcn-style `secondary` and `card` utility consumers
without corresponding local theme mappings in globals.css. Treat this as a
rendered-verification item: imported stylesheet output was not built in this
audit, so a visible failure is not asserted.

A static scan found 220 lines containing hex colors across 25 CSS/TSX source
files. Some are intentional content/editor colors or approved product
overrides. This is an inventory for targeted review, not 220 confirmed defects.

## Reuse map for direct mail

| Need | Existing starting point | Adaptation boundary |
| --- | --- | --- |
| Platform navigation/layout | components/shell/application-shell.tsx, app-sidebar.tsx | Reuse existing authenticated shell; decide the new navigation entry during feature design |
| Recipient/account selection | accounts-table.tsx, accounts-toolbar.tsx, account-table-view.ts, selection/column hooks | Preserve table density, column, selection and keyboard conventions; separate direct-mail models |
| Detail panels | account-preview-drawer.tsx, use-drawer-transition.ts | Reuse behavior/patterns; account-specific props and routing do not become mail-domain contracts |
| Forms | SelectField, CheckboxField, SettingsInput, SettingsTextarea | Consolidate required field semantics and validated error/disabled states |
| Menus and dialogs | Base UI Menu/Dialog usages in projects and settings | Reuse accessible primitives and established tokens |
| Feedback | ConfirmationProvider, Alert, recovery/empty views | Make loading, error, empty and success states explicit |
| Asset browsing | gallery-artifact-card.tsx, project-gallery-view.tsx, artifact-library.tsx | Use typed artifact references; decide whether direct mail needs existing assets or separate objects |
| Icons | DesignIcon, public/icons (189 SVGs), Lucide usages | Prefer existing Figma exports; preserve intrinsic leaf size and accessible labeling |
| Data integration | model/*.ts, data/*.repository.ts, feature hooks | Fixture and HTTP adapters share a schema and interface |

All 11 current feature areas were inventoried: Accounts, Artifacts, Brand Context,
Chat Shell, Design Editor, Gallery, Onboarding, Projects, Session, Settings and
Site Editor. No dedicated direct-mail infrastructure feature/route was found.
There is already a direct-mail artifact/category vocabulary in gallery and
project models; reuse that vocabulary where appropriate. Recipient validation,
mail preparation, ordering and shipment behavior remain new product decisions,
not existing implemented infrastructure.

## Working rules for the next phase

1. Define the direct-mail user flow and required screen/state inventory with the
   founder before designing screens. No feature screens exist yet.
2. Use the production shell and published semantic tokens. Make new design
   frames with real library component instances where suitable.
3. Resolve the control/font issues that affect the selected flow in a small,
   explicit foundation change, preserving existing consumers.
4. Use feature-owned fixture adapters with realistic states. Keep existing
   live account/contact behavior intact. Never use configuration failure as
   an implicit fixture fallback.
5. Compare each implemented flow at the same viewport as its approved Figma
   frame. Include empty/loading/error/disabled/success and keyboard/responsive
   checks. Verify real operations separately from simulated UI behavior.
6. Document proposed backend contracts in docs/api-contracts before handoff.
   New API payload assumptions require explicit reconciliation under AGENTS.md.

These are recommended next steps, not an approved direct-mail feature spec.

## Verification performed

- Fresh branch/status check: `feat/direct-mail-infrastructure-ui`, clean at audit start.
- Read-only live Figma collection, variable, style and component inventory.
- Exact normalized comparison: 226/226 color definitions/aliases, 14/14 rendered text styles.
- Token generator executed on a temporary copy outside the worktree:
  exit 0; regenerated CSS byte-identical to committed tokens.css.
- `node --test src/design-system-tokens.test.ts`: 2 passed, 0 failed;
  existing two-entry dangling-token allowlist remains in effect.
- Figma screenshots inspected: Button set `69:3647` and Accounts frame `1236:30576`.
- No app dependencies installed, no application process started, no database or
  research-provider calls made, no full frontend build/lint/browser acceptance claimed.
