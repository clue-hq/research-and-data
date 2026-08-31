# Lane 3 — Accounts Visual Parity: Co-founder's Working Document

> **Audience:** the design co-founder, working in parallel with Lane 1 (chat routes + chrome)
> and Lane 2 (website editor). This is a governance + worklist document, not an agent TDD plan.
> Its authority sources: the founder's parity rulings (2026-08-17), the three-agent frontend
> diff (`_memory/2026-08-17-frontend-tri-diff-synthesis.md`), and the parity constitution.

## 1. Mission and the one governing rule

The integrated accounts screens (running at `localhost:3000`) visually drifted from your
design during backend wiring sessions: invented tab navigation, raw backend strings rendered
as UI (registry-cased ALL-CAPS names, `account.resonance` field keys, ICP keys, claim UUIDs),
unbounded evidence dumps, em-dash empty rows. The mission is to restore your design — screen
by screen — without breaking the production wiring underneath.

**The governing rule (the parity constitution):** your design is baseline *and* ceiling.
Nothing user-visible exists unless you designed it; no raw identifier or backend enum ever
renders. The inverse also binds: the wiring under the screens (data fetching, schemas, hooks)
is production machinery — it is not yours to change, and it must not need changing for any
visual fix. Where those two rules collide (real data with no designed slot), the resolution is
a founder decision, never an improvisation — see §5.

## 2. Source of truth and a critical fact in your favor

Your `features/accounts` tree in `clue-hq/clue-frontend` has not changed since the monorepo
snapshot — verified: `git diff 4e2a300..c7f2bc5 -- src/features/accounts` is empty. **Your
frozen tree IS the design-approved baseline**, including the account-typography alignment
commit. Every visual delta between 3080 and 3000 is on the integrated side. You are not
reconciling two moving targets; you are regressing one drifted tree to your own reference.

Also verified and in your favor: the design system has **zero drift** — tokens, globals,
fonts, and shared UI primitives are byte-identical between the trees. Any class or token you
use from your build resolves identically in the monorepo.

## 3. Workspace setup and branch discipline

- Work in the monorepo (this repo), branch **`frontend/accounts-parity`** cut from
  `integration/frontend-design-part-iv-v2` — pull the branch tip first. Do NOT work in your
  standalone repo for this lane (that would create a second drift-and-relift cycle).
- Reference build: your repo at the `codex/chat-shell` tip, `npm run dev` on port 3080.
  Working build: `apps/frontend`, `npm ci && npm run dev` on port 3000 (no `.env` needed —
  auth is env-gated off; screens run on fixture/live data as currently wired).
- One commit per screen (or coherent sub-screen), message convention:
  `parity(accounts): <screen> regressed to design baseline`. Small commits; each one leaves
  `npm run lint && npm run build` green.
- Merges land back into `integration/frontend-design-part-iv-v2` via review with the founder.

## 4. Hard boundaries — what you may and may not touch

**Yours to edit freely:**
- `apps/frontend/src/features/accounts/components/**` (including `contacts/components/**`)
- Any `*.module.css` inside `features/accounts`

**Off-limits (production wiring and other lanes' territory):**
- `features/accounts/{data,model,hooks}/**` — repositories, Zod schemas, controllers,
  formatting/vocabulary helpers. If a visual fix seems to need a change here, stop and flag
  (§6). Exception you may *consume*: `model/formatting.ts`, `model/vocabulary.ts`,
  `model/prose.ts` exist precisely to turn raw backend values into displayable text — use
  them instead of rendering raw values, and request additions rather than writing your own.
- `src/app/**` (routes and layouts — two of your old route files still hard-depend on fixture
  data and would 404 live screens if copied back; routes are Lane-1 territory besides)
- `features/{projects,chat-shell,gallery,onboarding,session}/**`, `components/{shell,ui,chat}/**`
  (Lane 1/2 territory; onboarding has zero parity debt — verified)
- `package.json`, `packages/design-system/**`, `globals.css` (zero drift — nothing to fix)

**Nine files already at parity — do not touch:** `account-filter-select.tsx` + its CSS,
`account-flow-icon.tsx`, `account-readability.module.css`, `accounts-filter-panel.module.css`,
`column-resize-handle.tsx`, `table-density-selector.tsx`, `use-account-workspace-controller.ts`,
`use-resizable-column.ts`.

## 5. The worklist — 16 drifted presentation files

Sorted by drift size (changed lines between your baseline and the integrated file; "visual"
counts changed lines touching className/typography). Method guidance per tier below.

| # | file | yours L | integrated L | changed | visual |
|---|---|---|---|---|---|
| 1 | `components/accounts-table.tsx` | 469 | 525 | 366 | 23 |
| 2 | `components/account-detail-screen.tsx` | 225 | 269 | 350 | 53 |
| 3 | `components/account-detail-primitives.tsx` | 254 | 375 | 307 | 43 |
| 4 | `components/account-workspace-screens.tsx` | 251 | 253 | 298 | 43 |
| 5 | `components/account-contacts-screen.tsx` | 214 | 330 | 210 | 14 |
| 6 | `components/contact-profile-content.tsx` | 151 | 160 | 173 | 21 |
| 7 | `components/accounts-screen.tsx` | 60 | 218 | 168 | 13 |
| 8 | `contacts/components/contact-row.tsx` | 121 | 158 | 165 | 26 |
| 9 | `contacts/components/lookup-email-button.tsx` | 30 | 103 | 97 | — |
| 10 | `components/accounts-filter-panel.tsx` | 219 | 218 | 39 | 0 |
| 11 | `components/account-workspace-shell.tsx` | 265 | 262 | 29 | 3 |
| 12 | `components/contact-avatar.tsx` | 50 | 62 | 24 | 0 |
| 13 | `components/contact-full-screen.tsx` | 86 | 79 | 19 | 1 |
| 14 | `components/account-preview-drawer.tsx` | 42 | 42 | 12 | 0 |
| 15 | `components/account-checkbox.tsx` | 34 | 38 | 10 | 1 |
| 16 | `components/accounts-toolbar.tsx` | 551 | 550 | 7 | 0 |

**Method — big drifts (#1–#8):** *regress-to-baseline.* Start from YOUR file's JSX/class
structure as the skeleton, then re-bind the integrated file's live props and data flows into
it (the integrated versions consume real controller props your fixtures never had —
pagination `meta`, `bulkCapabilities`, evidence, recovery states). This re-binding is where
design and wiring meet: do the structure pass yourself, then pair with the founder's agent
lane for the prop re-binding rather than hand-wiring unfamiliar props. A screen is not done
with a compile — it's done with the §7 checklist.

**Method — small drifts (#10–#16):** *patch-in-place.* Diff your file against the integrated
one (`git diff --no-index`) and revert the visual deltas only; the wiring deltas (props,
callbacks) stay.

## 6. The six undesigned components — founder decisions required (open ruling R9)

These exist only in the integrated tree, render real product data, and have **no design
source**. They are the "invented UI" class. Do not delete them (they're wired to real data)
and do not restyle them ad hoc — each needs a three-way decision by you and the founder
together: **(a)** design a proper slot for it, **(b)** hide it until designed, or **(c)**
keep it agent-/API-only (invisible).

| component | what it shows | size |
|---|---|---|
| `account-facts.tsx` | researched-field values on the account page | 196L |
| `evidence-list.tsx` | claim evidence spans + source links | 112L |
| `table-pagination.tsx` | real pagination over the accounts table | 114L |
| `accounts-recovery-screen.tsx` | backend-unreachable recovery state | 103L |
| `account-avatar.tsx` | account logo/initial treatment | 60L |
| bulk-action chrome (`bulkCapabilities`/`meta` props through toolbar/table) | bulk select/act | — |

Note: pagination and the recovery screen are near-certainly "(a) design a slot" — the data
they carry is functionally mandatory (the table cannot lose paging; errors cannot dead-end).
Evidence/facts surfaces are the provenance views the founder flagged — likely "(b) hide
until designed" with a design request. Decide together before you reach those screens.

## 7. Definition of done — per screen

1. Side-by-side with 3080: same structure, spacing, typography, badges, empty states. No
   element exists at 3000 that doesn't exist at 3080 (unless it's a §6 item with an explicit
   (a)/(b) ruling recorded).
2. No raw backend strings anywhere: names render through the formatting helpers (not
   ALL-CAPS registry casing), no field keys, no UUIDs, no `Fit 100 · Intent 0 · ICP …` chips.
3. All live behavior still works: sorting, filtering, selection, pagination, contact
   navigation, add-to-chat — click through them, don't assume.
4. `npm run lint && npm run build` green; commit per convention.
5. Screenshot pair (3080 / 3000) attached to the review.

## 8. Escalation rules — when to stop and ask

- A visual fix needs a prop/field the component doesn't receive → flag to the founder's
  lane (seam request); never import from `data/` directly or widen a schema.
- Real data has no designed slot (you'll hit this on evidence/status surfaces) → §6 decision
  with the founder; never improvise a rendering.
- Anything route-shaped (URLs, redirects, tabs-as-navigation) → Lane 1 owns it; the invented
  five-tab account page navigation specifically is expected to *disappear* back into your
  designed structure — if any tab's content seems to have no home, that's a §6 item, not a
  reason to keep the tabs.
- You want to change something in your own design while here → fine, but do it in your repo
  first (the reference build stays the single source of truth), then mirror it; never let
  the monorepo lead the design.

## 9. Coordination with the other lanes

- Lane 1 (routes, then chat chrome) and Lane 2 (website editor) share **zero files** with
  your scope — merges are order-free. The one adjacency: `account-workspace-screens.tsx`
  contains a project link that Lane 1's route work also touches (a one-line href) — merge
  conflict there is trivial; take both changes.
- If you commit to your standalone repo during this period, tell the founder's lane — the
  standing re-sync rule diffs lifted files against your tip before every adoption slice, and
  silent upstream movement is the one thing that can reintroduce drift.
